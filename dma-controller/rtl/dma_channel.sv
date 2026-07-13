// -----------------------------------------------------------------------------
// dma_channel — one DMA channel: independent, concurrently-running read and
// write engines joined by a FIFO (v2 pipelined datapath).
//
// Modes (mode_i):
//   MM2MM (0): AXI read  -> FIFO -> AXI write        (memory copy)
//   MM2S  (1): AXI read  -> FIFO -> m_axis stream    (memory to stream)
//   S2MM  (2): s_axis    -> FIFO -> AXI write        (stream to memory)
//
// Pipelining: the read engine keeps fetching ahead while the write engine
// drains — the FIFO decouples them. Two safety-by-construction rules:
//   * the read engine only commits an AR when FIFO space >= that whole burst
//     (single outstanding AR), so the FIFO can never overflow;
//   * the write engine only commits an AW when FIFO data >= that whole burst,
//     so W beats never starve mid-burst (no WVALID stalls, no padding).
//
// Byte-granular LENGTH: words = ceil(LENGTH/4); the final W beat / stream beat
// carries partial WSTRB / TKEEP for LENGTH%4 bytes. Addresses stay word
// aligned (bits [1:0] ignored).
//
// Bursts never cross a 4KB boundary on either address (AXI A3.4.1):
//   beats = min(words_remaining, max_burst, room_to_4KB(addr)).
//
// Errors: a non-OKAY RRESP/BRESP latches an error; both engines finish their
// current committed burst protocol-correctly, stop committing new ones, and
// the channel completes with err_o (done_o is not raised). FIFO residue is
// discarded on the next start. In MM2S an aborted frame simply stops without
// TLAST — the ERROR flag tells software the frame is bad.
// -----------------------------------------------------------------------------
`default_nettype none

module dma_channel #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 32
) (
    input  wire        clk,
    input  wire        rst_n,

    // control (from CSR)
    input  wire        start_i,       // one-shot start (W1S auto-clear bit)
    input  wire [1:0]  mode_i,        // 0 MM2MM, 1 MM2S, 2 S2MM
    // bits [1:0] of src/dst are deliberately ignored (word alignment)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [31:0] src_addr_i,
    input  wire [31:0] dst_addr_i,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire [31:0] len_bytes_i,
    input  wire [7:0]  max_burst_i,   // beats per burst; 0 treated as 1
    output wire        busy_o,
    output wire        done_o,        // 1-cycle pulse: clean completion
    output wire        err_o,         // 1-cycle pulse: aborted on bus error

    // AXI4 master — read path
    output wire [ADDR_WIDTH-1:0] m_axi_araddr,
    output reg  [7:0]            m_axi_arlen,
    output wire [2:0]            m_axi_arsize,
    output wire [1:0]            m_axi_arburst,
    output reg                   m_axi_arvalid,
    input  wire                  m_axi_arready,
    input  wire [DATA_WIDTH-1:0] m_axi_rdata,
    input  wire [1:0]            m_axi_rresp,
    input  wire                  m_axi_rlast,
    input  wire                  m_axi_rvalid,
    output wire                  m_axi_rready,
    // AXI4 master — write path
    output wire [ADDR_WIDTH-1:0] m_axi_awaddr,
    output reg  [7:0]            m_axi_awlen,
    output wire [2:0]            m_axi_awsize,
    output wire [1:0]            m_axi_awburst,
    output reg                   m_axi_awvalid,
    input  wire                  m_axi_awready,
    output wire [DATA_WIDTH-1:0]   m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0] m_axi_wstrb,
    output wire                    m_axi_wlast,
    output wire                    m_axi_wvalid,
    input  wire                    m_axi_wready,
    input  wire [1:0]            m_axi_bresp,
    input  wire                  m_axi_bvalid,
    output wire                  m_axi_bready,

    // AXI-Stream out (MM2S)
    output wire [DATA_WIDTH-1:0]   m_axis_tdata,
    output wire [DATA_WIDTH/8-1:0] m_axis_tkeep,
    output wire                    m_axis_tlast,
    output wire                    m_axis_tvalid,
    input  wire                    m_axis_tready,
    // AXI-Stream in (S2MM)
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready
);

    localparam [1:0] RESP_OKAY = 2'b00;
    localparam [1:0] MODE_MM2S = 2'd1, MODE_S2MM = 2'd2;

    // ---- read-engine states ----
    // Burst sizing is pipelined over SETUP (register the three candidates)
    // and CALC (min-reduce) — the single-cycle version was the synthesis
    // critical path (31-bit clamp + cascaded mins, ~-3.5 ns at 100 MHz).
    localparam [3:0]
        R_IDLE   = 4'd0,
        R_SETUP  = 4'd1,   // register burst candidates
        R_CALC   = 4'd2,   // min-reduce -> rd_burst
        R_REQ    = 4'd3,   // wait for FIFO space, issue AR
        R_AR     = 4'd4,
        R_DATA   = 4'd5,
        R_NEXT   = 4'd6,
        R_STREAM = 4'd7,   // S2MM: accept s_axis beats
        R_DONE   = 4'd8;

    // ---- write-engine states ----
    localparam [3:0]
        W_IDLE   = 4'd0,
        W_SETUP  = 4'd1,   // register burst candidates
        W_CALC   = 4'd2,   // min-reduce -> wr_burst
        W_REQ    = 4'd3,   // wait for FIFO data, issue AW
        W_AW     = 4'd4,
        W_DATA   = 4'd5,
        W_B      = 4'd6,
        W_NEXT   = 4'd7,
        W_STREAM = 4'd8,   // MM2S: drain to m_axis
        W_DONE   = 4'd9;

    reg [3:0]  r_state, w_state;
    reg        active;
    reg [1:0]  mode_q;
    reg [7:0]  maxb_q;
    reg [3:0]  tail_q;                 // strobes/keep of the final word
    reg [31:0] rd_addr, wr_addr;
    reg [30:0] rd_words, wr_words;     // words left to fetch / to deliver
    reg [8:0]  rd_burst, wr_burst;     // committed burst beats (1..255)
    reg [8:0]  wr_beat;
    reg [8:0]  fifo_count;             // 0..256
    reg        err_rd, err_wr;
    reg [1:0]  fin_cnt;                // completion sequencing (see below)

    wire abort = err_rd | err_wr;

    // total words = ceil(LENGTH / 4); tail strobes for LENGTH % 4
    wire [30:0] words_total = {1'b0, len_bytes_i[31:2]} + {30'b0, |len_bytes_i[1:0]};
    wire [3:0]  tail_calc   = (len_bytes_i[1:0] == 2'd0) ? 4'hF :
                              (len_bytes_i[1:0] == 2'd1) ? 4'h1 :
                              (len_bytes_i[1:0] == 2'd2) ? 4'h3 : 4'h7;

    // Burst sizing pipeline stage 1 (registered in SETUP): the three
    // independent candidates, each a shallow computation.
    reg [10:0] rd_wc, rd_room, wr_wc, wr_room, mb_q;

    wire [10:0] mb_calc      = (maxb_q == 8'd0) ? 11'd1 : {3'b000, maxb_q};
    wire [10:0] rd_wc_calc   = (rd_words > 31'd1024) ? 11'd1024 : rd_words[10:0];
    wire [10:0] wr_wc_calc   = (wr_words > 31'd1024) ? 11'd1024 : wr_words[10:0];
    wire [10:0] rd_room_calc = 11'd1024 - {1'b0, rd_addr[11:2]};
    wire [10:0] wr_room_calc = 11'd1024 - {1'b0, wr_addr[11:2]};

    // Stage 2 (registered in CALC): min-reduce of the registered candidates.
    function automatic [8:0] min3(input [10:0] a, input [10:0] b,
                                  input [10:0] c);
        reg [10:0] m;
        begin
            m    = (a < b) ? a : b;
            m    = (c < m) ? c : m;
            min3 = m[8:0];
        end
    endfunction

    wire [8:0] fifo_space = 9'd256 - fifo_count;

    // ---- FIFO ----
    wire fifo_clr = start_i && !active;
    wire fifo_push, fifo_pop;
    wire [DATA_WIDTH-1:0] fifo_dout;
    wire fifo_empty;

    dma_fifo #(.WIDTH(DATA_WIDTH), .DEPTH_LOG2(8)) u_fifo (
        .clk   (clk),
        .rst_n (rst_n),
        .clr   (fifo_clr),
        .push  (fifo_push),
        .din   ((mode_q == MODE_S2MM) ? s_axis_tdata : m_axi_rdata),
        .pop   (fifo_pop),
        .dout  (fifo_dout),
        .empty (fifo_empty)
    );

    assign fifo_push = ((r_state == R_DATA)   && m_axi_rvalid) ||
                       ((r_state == R_STREAM) && s_axis_tvalid && s_axis_tready);
    assign fifo_pop  = (m_axi_wvalid && m_axi_wready) ||
                       (m_axis_tvalid && m_axis_tready);

    // ---- AXI constants / datapath wiring ----
    localparam [2:0] SIZE_WORD = 3'b010;
    assign m_axi_arsize  = SIZE_WORD;
    assign m_axi_awsize  = SIZE_WORD;
    assign m_axi_arburst = 2'b01;                    // INCR
    assign m_axi_awburst = 2'b01;
    assign m_axi_araddr  = rd_addr;
    assign m_axi_awaddr  = wr_addr;
    assign m_axi_rready  = (r_state == R_DATA);
    assign m_axi_bready  = (w_state == W_B);

    wire final_word = (wr_words == 31'd1);
    assign m_axi_wvalid = (w_state == W_DATA) && !fifo_empty;
    assign m_axi_wdata  = fifo_dout;
    assign m_axi_wstrb  = final_word ? tail_q : {DATA_WIDTH/8{1'b1}};
    assign m_axi_wlast  = m_axi_wvalid && (wr_beat == wr_burst - 9'd1);

    assign m_axis_tvalid = (w_state == W_STREAM) && !fifo_empty && (wr_words != 31'd0);
    assign m_axis_tdata  = fifo_dout;
    assign m_axis_tkeep  = final_word ? tail_q : {DATA_WIDTH/8{1'b1}};
    assign m_axis_tlast  = final_word;

    assign s_axis_tready = (r_state == R_STREAM) && (fifo_count != 9'd256)
                           && (rd_words != 31'd0);

    // ---- status ----
    reg done_r, err_r;
    assign busy_o = active;
    assign done_o = done_r;
    assign err_o  = err_r;

    // ---- single clocked process: both engines + channel control ----
    always @(posedge clk) begin
        if (!rst_n) begin
            r_state       <= R_IDLE;
            w_state       <= W_IDLE;
            active        <= 1'b0;
            mode_q        <= 2'd0;
            maxb_q        <= 8'd0;
            tail_q        <= 4'd0;
            rd_addr       <= '0;
            wr_addr       <= '0;
            rd_words      <= '0;
            wr_words      <= '0;
            rd_burst      <= '0;
            wr_burst      <= '0;
            wr_beat       <= '0;
            fifo_count    <= '0;
            err_rd        <= 1'b0;
            err_wr        <= 1'b0;
            fin_cnt       <= 2'd0;
            rd_wc         <= '0;
            rd_room       <= '0;
            wr_wc         <= '0;
            wr_room       <= '0;
            mb_q          <= '0;
            m_axi_arlen   <= '0;
            m_axi_arvalid <= 1'b0;
            m_axi_awlen   <= '0;
            m_axi_awvalid <= 1'b0;
            done_r        <= 1'b0;
            err_r         <= 1'b0;
        end else begin
            done_r <= 1'b0;
            err_r  <= 1'b0;

            fifo_count <= fifo_count + {8'b0, fifo_push} - {8'b0, fifo_pop};

            // ---- channel start / finish ----
            if (!active) begin
                if (start_i) begin
                    active     <= 1'b1;
                    mode_q     <= mode_i;
                    maxb_q     <= max_burst_i;
                    tail_q     <= tail_calc;
                    rd_addr    <= {src_addr_i[31:2], 2'b00};
                    wr_addr    <= {dst_addr_i[31:2], 2'b00};
                    rd_words   <= words_total;
                    wr_words   <= words_total;
                    err_rd     <= 1'b0;
                    err_wr     <= 1'b0;
                    fifo_count <= '0;
                    r_state    <= (words_total == 31'd0) ? R_DONE :
                                  (mode_i == MODE_S2MM)  ? R_STREAM : R_SETUP;
                    w_state    <= (words_total == 31'd0) ? W_DONE :
                                  (mode_i == MODE_MM2S)  ? W_STREAM : W_SETUP;
                end
            end else if (r_state == R_DONE && w_state == W_DONE) begin
                // Completion is sequenced so software can never observe
                // BUSY=0 with DONE/ERROR still 0: pulse the flag first, keep
                // BUSY high until the CSR's W1C bit has actually latched
                // (the set input takes one extra cycle), then go idle.
                if (fin_cnt == 2'd0) begin
                    done_r  <= ~abort;
                    err_r   <=  abort;
                    fin_cnt <= 2'd1;
                end else if (fin_cnt == 2'd1) begin
                    fin_cnt <= 2'd2;
                end else begin
                    fin_cnt <= 2'd0;
                    active  <= 1'b0;
                    r_state <= R_IDLE;
                    w_state <= W_IDLE;
                end
            end

            // ---- read engine ----
            case (r_state)
                R_SETUP: begin
                    if (abort)
                        r_state <= R_DONE;
                    else begin
                        rd_wc   <= rd_wc_calc;
                        rd_room <= rd_room_calc;
                        mb_q    <= mb_calc;
                        r_state <= R_CALC;
                    end
                end
                R_CALC: begin
                    rd_burst <= min3(rd_wc, rd_room, mb_q);
                    r_state  <= R_REQ;
                end
                R_REQ: begin
                    if (abort)
                        r_state <= R_DONE;   // write side may stop draining
                    else if (fifo_space >= rd_burst) begin
                        m_axi_arlen   <= rd_burst[7:0] - 8'd1;
                        m_axi_arvalid <= 1'b1;
                        r_state       <= R_AR;
                    end
                end
                R_AR: begin
                    if (m_axi_arready && m_axi_arvalid) begin
                        m_axi_arvalid <= 1'b0;
                        r_state       <= R_DATA;
                    end
                end
                R_DATA: begin
                    if (m_axi_rvalid) begin
                        if (m_axi_rresp != RESP_OKAY)
                            err_rd <= 1'b1;
                        if (m_axi_rlast)
                            r_state <= R_NEXT;
                    end
                end
                R_NEXT: begin
                    rd_addr  <= rd_addr + {21'b0, rd_burst, 2'b00};
                    rd_words <= rd_words - {22'b0, rd_burst};
                    r_state  <= (rd_words == {22'b0, rd_burst}) ? R_DONE : R_SETUP;
                end
                R_STREAM: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        rd_words <= rd_words - 31'd1;
                        if (rd_words == 31'd1)
                            r_state <= R_DONE;
                    end
                end
                default: ;   // R_IDLE, R_DONE: wait
            endcase

            // ---- write engine ----
            case (w_state)
                W_SETUP: begin
                    if (abort)
                        w_state <= W_DONE;       // no new bursts after an error
                    else begin
                        wr_wc   <= wr_wc_calc;
                        wr_room <= wr_room_calc;
                        mb_q    <= mb_calc;
                        w_state <= W_CALC;
                    end
                end
                W_CALC: begin
                    wr_burst <= min3(wr_wc, wr_room, mb_q);
                    w_state  <= W_REQ;
                end
                W_REQ: begin
                    if (abort)
                        w_state <= W_DONE;       // reads stopped: data may never come
                    else if (fifo_count >= wr_burst) begin
                        m_axi_awlen   <= wr_burst[7:0] - 8'd1;
                        m_axi_awvalid <= 1'b1;
                        wr_beat       <= '0;
                        w_state       <= W_AW;
                    end
                end
                W_AW: begin
                    if (m_axi_awready && m_axi_awvalid) begin
                        m_axi_awvalid <= 1'b0;
                        w_state       <= W_DATA;
                    end
                end
                W_DATA: begin
                    if (m_axi_wvalid && m_axi_wready) begin
                        wr_beat  <= wr_beat + 9'd1;
                        wr_words <= wr_words - 31'd1;
                        if (m_axi_wlast)
                            w_state <= W_B;
                    end
                end
                W_B: begin
                    if (m_axi_bvalid) begin
                        if (m_axi_bresp != RESP_OKAY)
                            err_wr <= 1'b1;
                        w_state <= W_NEXT;
                    end
                end
                W_NEXT: begin
                    wr_addr <= wr_addr + {21'b0, wr_burst, 2'b00};
                    w_state <= (err_wr || wr_words == 31'd0) ? W_DONE : W_SETUP;
                end
                W_STREAM: begin
                    if (m_axis_tvalid && m_axis_tready) begin
                        wr_words <= wr_words - 31'd1;
                        if (wr_words == 31'd1)
                            w_state <= W_DONE;
                    end else if (abort && fifo_empty)
                        w_state <= W_DONE;       // aborted frame: stop (no TLAST)
                end
                default: ;   // W_IDLE, W_DONE: wait
            endcase
        end
    end

endmodule
`default_nettype wire
