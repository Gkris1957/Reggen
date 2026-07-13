// -----------------------------------------------------------------------------
// sim_top — simulation wrapper: dma_top + AXI protocol checker on the shared
// master port. Port-for-port identical to dma_top (the checker is invisible
// to the testbench). Simulation only; synthesis targets dma_top directly.
// -----------------------------------------------------------------------------
`default_nettype none

module sim_top #(
    parameter int AXIL_ADDR_WIDTH = 12,
    parameter int ADDR_WIDTH      = 32,
    parameter int DATA_WIDTH      = 32
) (
    input  wire clk,
    input  wire rst_n,

    input  wire [AXIL_ADDR_WIDTH-1:0] s_axil_awaddr,
    input  wire                       s_axil_awvalid,
    output wire                       s_axil_awready,
    input  wire [31:0]                s_axil_wdata,
    input  wire [3:0]                 s_axil_wstrb,
    input  wire                       s_axil_wvalid,
    output wire                       s_axil_wready,
    output wire [1:0]                 s_axil_bresp,
    output wire                       s_axil_bvalid,
    input  wire                       s_axil_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0] s_axil_araddr,
    input  wire                       s_axil_arvalid,
    output wire                       s_axil_arready,
    output wire [31:0]                s_axil_rdata,
    output wire [1:0]                 s_axil_rresp,
    output wire                       s_axil_rvalid,
    input  wire                       s_axil_rready,

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
    output wire                  m_axi_bready,

    output wire [DATA_WIDTH-1:0]   ch0_m_axis_tdata,
    output wire [DATA_WIDTH/8-1:0] ch0_m_axis_tkeep,
    output wire                    ch0_m_axis_tlast,
    output wire                    ch0_m_axis_tvalid,
    input  wire                    ch0_m_axis_tready,
    input  wire [DATA_WIDTH-1:0]   ch0_s_axis_tdata,
    input  wire                    ch0_s_axis_tvalid,
    output wire                    ch0_s_axis_tready,

    output wire [DATA_WIDTH-1:0]   ch1_m_axis_tdata,
    output wire [DATA_WIDTH/8-1:0] ch1_m_axis_tkeep,
    output wire                    ch1_m_axis_tlast,
    output wire                    ch1_m_axis_tvalid,
    input  wire                    ch1_m_axis_tready,
    input  wire [DATA_WIDTH-1:0]   ch1_s_axis_tdata,
    input  wire                    ch1_s_axis_tvalid,
    output wire                    ch1_s_axis_tready,

    output wire irq
);

    dma_top #(
        .AXIL_ADDR_WIDTH(AXIL_ADDR_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_dut (.*);

    axi_checker #(.ADDR_WIDTH(ADDR_WIDTH), .DATA_WIDTH(DATA_WIDTH)) u_chk (
        .clk    (clk),
        .rst_n  (rst_n),
        .araddr (m_axi_araddr),
        .arlen  (m_axi_arlen),
        .arvalid(m_axi_arvalid),
        .arready(m_axi_arready),
        .rdata  (m_axi_rdata),
        .rresp  (m_axi_rresp),
        .rlast  (m_axi_rlast),
        .rvalid (m_axi_rvalid),
        .rready (m_axi_rready),
        .awaddr (m_axi_awaddr),
        .awlen  (m_axi_awlen),
        .awvalid(m_axi_awvalid),
        .awready(m_axi_awready),
        .wdata  (m_axi_wdata),
        .wstrb  (m_axi_wstrb),
        .wlast  (m_axi_wlast),
        .wvalid (m_axi_wvalid),
        .wready (m_axi_wready),
        .bresp  (m_axi_bresp),
        .bvalid (m_axi_bvalid),
        .bready (m_axi_bready)
    );

endmodule
`default_nettype wire
