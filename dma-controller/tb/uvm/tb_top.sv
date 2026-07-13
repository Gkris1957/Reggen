// -----------------------------------------------------------------------------
// tb_top — UVM RAL testbench top: dma_top + AXI-Lite interface + UVM run.
//
//   vsim -c work.tb_top +UVM_TESTNAME=dma_ral_test -do "run -all; quit -f"
// -----------------------------------------------------------------------------
`ifndef TB_TOP_SV
`define TB_TOP_SV

module tb_top;

    import uvm_pkg::*;
    import dma_ral_pkg::*;

    logic clk = 0;
    logic rst_n = 0;

    always #5 clk = ~clk;

    initial begin
        repeat (5) @(posedge clk);
        rst_n = 1;
    end

    axil_if #(.ADDR_WIDTH(12), .DATA_WIDTH(32)) axil (.clk(clk), .rst_n(rst_n));

    // unused DUT inputs tied off
    logic [31:0] tie_rdata  = '0;
    logic [1:0]  tie_resp   = '0;

    dma_top u_dut (
        .clk              (clk),
        .rst_n            (rst_n),
        .s_axil_awaddr    (axil.awaddr),
        .s_axil_awvalid   (axil.awvalid),
        .s_axil_awready   (axil.awready),
        .s_axil_wdata     (axil.wdata),
        .s_axil_wstrb     (axil.wstrb),
        .s_axil_wvalid    (axil.wvalid),
        .s_axil_wready    (axil.wready),
        .s_axil_bresp     (axil.bresp),
        .s_axil_bvalid    (axil.bvalid),
        .s_axil_bready    (axil.bready),
        .s_axil_araddr    (axil.araddr),
        .s_axil_arvalid   (axil.arvalid),
        .s_axil_arready   (axil.arready),
        .s_axil_rdata     (axil.rdata),
        .s_axil_rresp     (axil.rresp),
        .s_axil_rvalid    (axil.rvalid),
        .s_axil_rready    (axil.rready),
        // AXI master: no memory attached in the RAL TB (CSR access only)
        .m_axi_araddr     (),
        .m_axi_arlen      (),
        .m_axi_arsize     (),
        .m_axi_arburst    (),
        .m_axi_arvalid    (),
        .m_axi_arready    (1'b0),
        .m_axi_rdata      (tie_rdata),
        .m_axi_rresp      (tie_resp),
        .m_axi_rlast      (1'b0),
        .m_axi_rvalid     (1'b0),
        .m_axi_rready     (),
        .m_axi_awaddr     (),
        .m_axi_awlen      (),
        .m_axi_awsize     (),
        .m_axi_awburst    (),
        .m_axi_awvalid    (),
        .m_axi_awready    (1'b0),
        .m_axi_wdata      (),
        .m_axi_wstrb      (),
        .m_axi_wlast      (),
        .m_axi_wvalid     (),
        .m_axi_wready     (1'b0),
        .m_axi_bresp      (tie_resp),
        .m_axi_bvalid     (1'b0),
        .m_axi_bready     (),
        .ch0_m_axis_tdata (),
        .ch0_m_axis_tkeep (),
        .ch0_m_axis_tlast (),
        .ch0_m_axis_tvalid(),
        .ch0_m_axis_tready(1'b0),
        .ch0_s_axis_tdata (tie_rdata),
        .ch0_s_axis_tvalid(1'b0),
        .ch0_s_axis_tready(),
        .ch1_m_axis_tdata (),
        .ch1_m_axis_tkeep (),
        .ch1_m_axis_tlast (),
        .ch1_m_axis_tvalid(),
        .ch1_m_axis_tready(1'b0),
        .ch1_s_axis_tdata (tie_rdata),
        .ch1_s_axis_tvalid(1'b0),
        .ch1_s_axis_tready(),
        .irq              ()
    );

    initial begin
        uvm_config_db#(dma_ral_pkg::axil_vif_t)::set(null, "*", "vif", axil);
        run_test("dma_ral_test");
    end

endmodule

`endif // TB_TOP_SV
