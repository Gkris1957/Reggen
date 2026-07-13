// -----------------------------------------------------------------------------
// axi_checker — simulation-only AXI4 handshake protocol monitor.
//
// Enforces the AXI stability rule on every channel of the DUT's shared master
// port: once VALID is asserted it must stay asserted, with stable payload,
// until READY completes the handshake ($fatal on violation). Catches the
// classic "valid dropped / payload changed mid-wait" bugs that data checks
// can miss when a test happens to pass.
// -----------------------------------------------------------------------------
`default_nettype none

module axi_checker #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 32
) (
    input wire clk,
    input wire rst_n,

    input wire [ADDR_WIDTH-1:0] araddr,
    input wire [7:0]            arlen,
    input wire                  arvalid,
    input wire                  arready,
    input wire [DATA_WIDTH-1:0] rdata,
    input wire [1:0]            rresp,
    input wire                  rlast,
    input wire                  rvalid,
    input wire                  rready,
    input wire [ADDR_WIDTH-1:0] awaddr,
    input wire [7:0]            awlen,
    input wire                  awvalid,
    input wire                  awready,
    input wire [DATA_WIDTH-1:0]   wdata,
    input wire [DATA_WIDTH/8-1:0] wstrb,
    input wire                    wlast,
    input wire                    wvalid,
    input wire                    wready,
    input wire [1:0]            bresp,
    input wire                  bvalid,
    input wire                  bready
);

    // previous-cycle snapshots
    reg                  p_arvalid, p_arready;
    reg [ADDR_WIDTH-1:0] p_araddr;
    reg [7:0]            p_arlen;
    reg                  p_awvalid, p_awready;
    reg [ADDR_WIDTH-1:0] p_awaddr;
    reg [7:0]            p_awlen;
    reg                  p_wvalid, p_wready, p_wlast;
    reg [DATA_WIDTH-1:0] p_wdata;
    reg [DATA_WIDTH/8-1:0] p_wstrb;
    reg                  p_rvalid, p_rready, p_rlast;
    reg [DATA_WIDTH-1:0] p_rdata;
    reg [1:0]            p_rresp;
    reg                  p_bvalid, p_bready;
    reg [1:0]            p_bresp;

    always @(posedge clk) begin
        if (rst_n) begin
            // AR: valid-held-until-ready + stable payload
            if (p_arvalid && !p_arready) begin
                if (!arvalid)
                    $fatal(1, "AXI: ARVALID dropped before ARREADY");
                if (araddr != p_araddr || arlen != p_arlen)
                    $fatal(1, "AXI: AR payload changed while waiting");
            end
            // AW
            if (p_awvalid && !p_awready) begin
                if (!awvalid)
                    $fatal(1, "AXI: AWVALID dropped before AWREADY");
                if (awaddr != p_awaddr || awlen != p_awlen)
                    $fatal(1, "AXI: AW payload changed while waiting");
            end
            // W
            if (p_wvalid && !p_wready) begin
                if (!wvalid)
                    $fatal(1, "AXI: WVALID dropped before WREADY");
                if (wdata != p_wdata || wstrb != p_wstrb || wlast != p_wlast)
                    $fatal(1, "AXI: W payload changed while waiting");
            end
            // R (slave-driven: checks the TB model too)
            if (p_rvalid && !p_rready) begin
                if (!rvalid)
                    $fatal(1, "AXI: RVALID dropped before RREADY");
                if (rdata != p_rdata || rresp != p_rresp || rlast != p_rlast)
                    $fatal(1, "AXI: R payload changed while waiting");
            end
            // B
            if (p_bvalid && !p_bready) begin
                if (!bvalid)
                    $fatal(1, "AXI: BVALID dropped before BREADY");
                if (bresp != p_bresp)
                    $fatal(1, "AXI: B payload changed while waiting");
            end
        end
        p_arvalid <= arvalid; p_arready <= arready;
        p_araddr  <= araddr;  p_arlen   <= arlen;
        p_awvalid <= awvalid; p_awready <= awready;
        p_awaddr  <= awaddr;  p_awlen   <= awlen;
        p_wvalid  <= wvalid;  p_wready  <= wready;
        p_wdata   <= wdata;   p_wstrb   <= wstrb;   p_wlast <= wlast;
        p_rvalid  <= rvalid;  p_rready  <= rready;
        p_rdata   <= rdata;   p_rresp   <= rresp;   p_rlast <= rlast;
        p_bvalid  <= bvalid;  p_bready  <= bready;
        p_bresp   <= bresp;
    end

endmodule
`default_nettype wire
