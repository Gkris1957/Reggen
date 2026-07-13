// -----------------------------------------------------------------------------
// dma_fifo — synchronous FIFO for the DMA burst buffer.
//
// The channel engine reserves space before committing a read burst and data
// before committing a write burst, so overflow/underflow are impossible by
// construction — no 'full' flag is exposed; occupancy is tracked by the user.
// 'clr' synchronously empties the FIFO (used on transfer start to discard
// residue from a previously aborted transfer).
// -----------------------------------------------------------------------------
`default_nettype none

module dma_fifo #(
    parameter int WIDTH      = 32,
    parameter int DEPTH_LOG2 = 8            // 256 words >= one max AXI burst
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             clr,

    input  wire             push,
    input  wire [WIDTH-1:0] din,

    input  wire             pop,
    output wire [WIDTH-1:0] dout,
    output wire             empty
);

    localparam int DEPTH = 1 << DEPTH_LOG2;

    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [DEPTH_LOG2:0] wptr, rptr;           // one extra bit for wrap

    assign empty = (wptr == rptr);
    assign dout  = mem[rptr[DEPTH_LOG2-1:0]];

    always @(posedge clk) begin
        if (!rst_n) begin
            wptr <= '0;
            rptr <= '0;
        end else if (clr) begin
            wptr <= '0;
            rptr <= '0;
        end else begin
            if (push) begin
                mem[wptr[DEPTH_LOG2-1:0]] <= din;
                wptr <= wptr + 1'b1;
            end
            if (pop)
                rptr <= rptr + 1'b1;
        end
    end

endmodule
`default_nettype wire
