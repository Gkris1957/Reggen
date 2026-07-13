// -----------------------------------------------------------------------------
// dma_axi_mux — 2:1 AXI4 master multiplexer with round-robin arbitration.
//
// AXI read and write paths are independent, so each is arbitrated separately:
//   * read path locks from the AR handshake until the RLAST beat completes
//   * write path locks from the AW handshake until the B response completes
// Grant priority rotates away from the last-served channel (round-robin).
//
// Each dma_channel keeps at most one outstanding AR and one outstanding AW,
// and only drives W beats after its AW is accepted (which only happens while
// granted), so no AXI IDs or reorder buffers are needed.
// -----------------------------------------------------------------------------
`default_nettype none

module dma_axi_mux #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 32
) (
    input  wire clk,
    input  wire rst_n,

    // ---- channel 0 master port ----
    input  wire [ADDR_WIDTH-1:0] c0_araddr,
    input  wire [7:0]            c0_arlen,
    input  wire [2:0]            c0_arsize,
    input  wire [1:0]            c0_arburst,
    input  wire                  c0_arvalid,
    output wire                  c0_arready,
    output wire [DATA_WIDTH-1:0] c0_rdata,
    output wire [1:0]            c0_rresp,
    output wire                  c0_rlast,
    output wire                  c0_rvalid,
    input  wire                  c0_rready,
    input  wire [ADDR_WIDTH-1:0] c0_awaddr,
    input  wire [7:0]            c0_awlen,
    input  wire [2:0]            c0_awsize,
    input  wire [1:0]            c0_awburst,
    input  wire                  c0_awvalid,
    output wire                  c0_awready,
    input  wire [DATA_WIDTH-1:0]   c0_wdata,
    input  wire [DATA_WIDTH/8-1:0] c0_wstrb,
    input  wire                    c0_wlast,
    input  wire                    c0_wvalid,
    output wire                    c0_wready,
    output wire [1:0]            c0_bresp,
    output wire                  c0_bvalid,
    input  wire                  c0_bready,

    // ---- channel 1 master port ----
    input  wire [ADDR_WIDTH-1:0] c1_araddr,
    input  wire [7:0]            c1_arlen,
    input  wire [2:0]            c1_arsize,
    input  wire [1:0]            c1_arburst,
    input  wire                  c1_arvalid,
    output wire                  c1_arready,
    output wire [DATA_WIDTH-1:0] c1_rdata,
    output wire [1:0]            c1_rresp,
    output wire                  c1_rlast,
    output wire                  c1_rvalid,
    input  wire                  c1_rready,
    input  wire [ADDR_WIDTH-1:0] c1_awaddr,
    input  wire [7:0]            c1_awlen,
    input  wire [2:0]            c1_awsize,
    input  wire [1:0]            c1_awburst,
    input  wire                  c1_awvalid,
    output wire                  c1_awready,
    input  wire [DATA_WIDTH-1:0]   c1_wdata,
    input  wire [DATA_WIDTH/8-1:0] c1_wstrb,
    input  wire                    c1_wlast,
    input  wire                    c1_wvalid,
    output wire                    c1_wready,
    output wire [1:0]            c1_bresp,
    output wire                  c1_bvalid,
    input  wire                  c1_bready,

    // ---- merged master port (to memory) ----
    output wire [ADDR_WIDTH-1:0] m_axi_araddr,
    output wire [7:0]            m_axi_arlen,
    output wire [2:0]            m_axi_arsize,
    output wire [1:0]            m_axi_arburst,
    output wire                  m_axi_arvalid,
    input  wire                  m_axi_arready,
    input  wire [DATA_WIDTH-1:0] m_axi_rdata,
    input  wire [1:0]            m_axi_rresp,
    input  wire                  m_axi_rlast,
    input  wire                  m_axi_rvalid,
    output wire                  m_axi_rready,
    output wire [ADDR_WIDTH-1:0] m_axi_awaddr,
    output wire [7:0]            m_axi_awlen,
    output wire [2:0]            m_axi_awsize,
    output wire [1:0]            m_axi_awburst,
    output wire                  m_axi_awvalid,
    input  wire                  m_axi_awready,
    output wire [DATA_WIDTH-1:0]   m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0] m_axi_wstrb,
    output wire                    m_axi_wlast,
    output wire                    m_axi_wvalid,
    input  wire                    m_axi_wready,
    input  wire [1:0]            m_axi_bresp,
    input  wire                  m_axi_bvalid,
    output wire                  m_axi_bready
);

    // ---- read-path arbiter: lock AR -> RLAST ----
    reg r_busy, r_gnt;      // grant: 0 = ch0, 1 = ch1
    reg r_rr;               // round-robin pointer: who gets priority next

    always @(posedge clk) begin
        if (!rst_n) begin
            r_busy <= 1'b0;
            r_gnt  <= 1'b0;
            r_rr   <= 1'b0;
        end else if (!r_busy) begin
            if (r_rr == 1'b0 ? c0_arvalid : c1_arvalid) begin
                r_gnt  <= r_rr;
                r_busy <= 1'b1;
            end else if (r_rr == 1'b0 ? c1_arvalid : c0_arvalid) begin
                r_gnt  <= ~r_rr;
                r_busy <= 1'b1;
            end
        end else if (m_axi_rvalid && m_axi_rready && m_axi_rlast) begin
            r_busy <= 1'b0;
            r_rr   <= ~r_gnt;                     // rotate away from served ch
        end
    end

    wire r0 = r_busy && (r_gnt == 1'b0);
    wire r1 = r_busy && (r_gnt == 1'b1);

    assign m_axi_araddr  = r1 ? c1_araddr  : c0_araddr;
    assign m_axi_arlen   = r1 ? c1_arlen   : c0_arlen;
    assign m_axi_arsize  = r1 ? c1_arsize  : c0_arsize;
    assign m_axi_arburst = r1 ? c1_arburst : c0_arburst;
    assign m_axi_arvalid = (r0 && c0_arvalid) || (r1 && c1_arvalid);
    assign c0_arready    = r0 && m_axi_arready;
    assign c1_arready    = r1 && m_axi_arready;

    assign c0_rdata  = m_axi_rdata;
    assign c1_rdata  = m_axi_rdata;
    assign c0_rresp  = m_axi_rresp;
    assign c1_rresp  = m_axi_rresp;
    assign c0_rlast  = m_axi_rlast;
    assign c1_rlast  = m_axi_rlast;
    assign c0_rvalid = r0 && m_axi_rvalid;
    assign c1_rvalid = r1 && m_axi_rvalid;
    assign m_axi_rready = (r0 && c0_rready) || (r1 && c1_rready);

    // ---- write-path arbiter: lock AW -> B ----
    reg w_busy, w_gnt, w_rr;

    always @(posedge clk) begin
        if (!rst_n) begin
            w_busy <= 1'b0;
            w_gnt  <= 1'b0;
            w_rr   <= 1'b0;
        end else if (!w_busy) begin
            if (w_rr == 1'b0 ? c0_awvalid : c1_awvalid) begin
                w_gnt  <= w_rr;
                w_busy <= 1'b1;
            end else if (w_rr == 1'b0 ? c1_awvalid : c0_awvalid) begin
                w_gnt  <= ~w_rr;
                w_busy <= 1'b1;
            end
        end else if (m_axi_bvalid && m_axi_bready) begin
            w_busy <= 1'b0;
            w_rr   <= ~w_gnt;
        end
    end

    wire w0 = w_busy && (w_gnt == 1'b0);
    wire w1 = w_busy && (w_gnt == 1'b1);

    assign m_axi_awaddr  = w1 ? c1_awaddr  : c0_awaddr;
    assign m_axi_awlen   = w1 ? c1_awlen   : c0_awlen;
    assign m_axi_awsize  = w1 ? c1_awsize  : c0_awsize;
    assign m_axi_awburst = w1 ? c1_awburst : c0_awburst;
    assign m_axi_awvalid = (w0 && c0_awvalid) || (w1 && c1_awvalid);
    assign c0_awready    = w0 && m_axi_awready;
    assign c1_awready    = w1 && m_axi_awready;

    assign m_axi_wdata  = w1 ? c1_wdata : c0_wdata;
    assign m_axi_wstrb  = w1 ? c1_wstrb : c0_wstrb;
    assign m_axi_wlast  = w1 ? c1_wlast : c0_wlast;
    assign m_axi_wvalid = (w0 && c0_wvalid) || (w1 && c1_wvalid);
    assign c0_wready    = w0 && m_axi_wready;
    assign c1_wready    = w1 && m_axi_wready;

    assign c0_bresp  = m_axi_bresp;
    assign c1_bresp  = m_axi_bresp;
    assign c0_bvalid = w0 && m_axi_bvalid;
    assign c1_bvalid = w1 && m_axi_bvalid;
    assign m_axi_bready = (w0 && c0_bready) || (w1 && c1_bready);

endmodule
`default_nettype wire
