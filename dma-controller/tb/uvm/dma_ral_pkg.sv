// -----------------------------------------------------------------------------
// dma_ral_pkg — UVM register-abstraction-layer environment for the DMA CSR.
//
// Uses the reggen-GENERATED register model (csr_reg_block.sv -> dma_csr_reg_pkg)
// with a minimal AXI4-Lite agent and a uvm_reg_adapter, and runs:
//   * uvm_reg_hw_reset_seq  — every register's reset value via the front door
//   * a RAL smoke sequence  — write/read/mirror on the address registers
//
// Volatile / hardware-tied registers (STATUS, VERSION) are excluded from the
// reset check via the standard NO_REG_TESTS attribute.
// -----------------------------------------------------------------------------
`ifndef DMA_RAL_PKG_SV
`define DMA_RAL_PKG_SV

package dma_ral_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"
    import dma_csr_reg_pkg::*;

    typedef virtual axil_if #(.ADDR_WIDTH(12), .DATA_WIDTH(32)) axil_vif_t;

    // ---------------- sequence item ----------------
    class axil_item extends uvm_sequence_item;
        `uvm_object_utils(axil_item)
        rand bit          is_write;
        rand bit [11:0]   addr;
        rand bit [31:0]   data;
        bit [1:0]         resp;

        function new(string name = "axil_item");
            super.new(name);
        endfunction
    endclass

    // ---------------- driver ----------------
    class axil_driver extends uvm_driver #(axil_item);
        `uvm_component_utils(axil_driver)
        axil_vif_t vif;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            if (!uvm_config_db#(axil_vif_t)::get(this, "", "vif", vif))
                `uvm_fatal("NOVIF", "axil_if not set")
        endfunction

        task run_phase(uvm_phase phase);
            vif.awvalid <= 0;
            vif.wvalid  <= 0;
            vif.bready  <= 0;
            vif.arvalid <= 0;
            vif.rready  <= 0;
            @(posedge vif.rst_n);
            forever begin
                seq_item_port.get_next_item(req);
                if (req.is_write) drive_write(req);
                else              drive_read(req);
                seq_item_port.item_done();
            end
        endtask

        task drive_write(axil_item it);
            @(posedge vif.clk);
            vif.awaddr  <= it.addr;
            vif.awvalid <= 1;
            vif.wdata   <= it.data;
            vif.wstrb   <= 4'hF;
            vif.wvalid  <= 1;
            vif.bready  <= 1;
            do @(posedge vif.clk); while (!(vif.awready && vif.wready));
            vif.awvalid <= 0;
            vif.wvalid  <= 0;
            while (!vif.bvalid) @(posedge vif.clk);
            it.resp = vif.bresp;
            @(posedge vif.clk);
            vif.bready <= 0;
        endtask

        task drive_read(axil_item it);
            @(posedge vif.clk);
            vif.araddr  <= it.addr;
            vif.arvalid <= 1;
            vif.rready  <= 1;
            while (!vif.arready) @(posedge vif.clk);
            vif.arvalid <= 0;
            while (!vif.rvalid) @(posedge vif.clk);
            it.data = vif.rdata;
            it.resp = vif.rresp;
            @(posedge vif.clk);
            vif.rready <= 0;
        endtask
    endclass

    // ---------------- agent (driver + sequencer, no monitor needed) --------
    class axil_agent extends uvm_agent;
        `uvm_component_utils(axil_agent)
        axil_driver                 drv;
        uvm_sequencer #(axil_item)  sqr;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            drv = axil_driver::type_id::create("drv", this);
            sqr = uvm_sequencer#(axil_item)::type_id::create("sqr", this);
        endfunction

        function void connect_phase(uvm_phase phase);
            drv.seq_item_port.connect(sqr.seq_item_export);
        endfunction
    endclass

    // ---------------- reg <-> bus adapter ----------------
    class axil_reg_adapter extends uvm_reg_adapter;
        `uvm_object_utils(axil_reg_adapter)

        function new(string name = "axil_reg_adapter");
            super.new(name);
            supports_byte_enable = 0;
            provides_responses   = 0;
        endfunction

        virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
            axil_item it = axil_item::type_id::create("it");
            it.is_write = (rw.kind == UVM_WRITE);
            it.addr     = rw.addr[11:0];
            it.data     = rw.data[31:0];
            return it;
        endfunction

        virtual function void bus2reg(uvm_sequence_item bus_item,
                                      ref uvm_reg_bus_op rw);
            axil_item it;
            if (!$cast(it, bus_item))
                `uvm_fatal("CAST", "not an axil_item")
            rw.kind   = it.is_write ? UVM_WRITE : UVM_READ;
            rw.addr   = {20'b0, it.addr};
            rw.data   = {32'b0, it.data};
            rw.status = (it.resp == 2'b00) ? UVM_IS_OK : UVM_NOT_OK;
        endfunction
    endclass

    // ---------------- environment ----------------
    class dma_ral_env extends uvm_env;
        `uvm_component_utils(dma_ral_env)
        axil_agent        agent;
        dma_csr_reg_block regmodel;
        axil_reg_adapter  adapter;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            agent    = axil_agent::type_id::create("agent", this);
            adapter  = axil_reg_adapter::type_id::create("adapter");
            regmodel = dma_csr_reg_block::type_id::create("regmodel");
            regmodel.build();
        endfunction

        function void connect_phase(uvm_phase phase);
            regmodel.default_map.set_sequencer(agent.sqr, adapter);
            regmodel.default_map.set_auto_predict(1);
        endfunction
    endclass

    // ---------------- RAL smoke sequence ----------------
    class ral_smoke_seq extends uvm_sequence;
        `uvm_object_utils(ral_smoke_seq)
        dma_csr_reg_block model;

        function new(string name = "ral_smoke_seq");
            super.new(name);
        endfunction

        task body();
            uvm_status_e   status;
            uvm_reg_data_t value;

            // write/read/mirror round-trip on plain RW registers
            model.CH0_SRC_ADDR.write(status, 32'hDEAD_BEE0, .parent(this));
            model.CH0_DST_ADDR.write(status, 32'hCAFE_F00C, .parent(this));
            model.CH1_LENGTH.write(status, 32'h0000_1234, .parent(this));

            model.CH0_SRC_ADDR.read(status, value, .parent(this));
            if (value != 32'hDEAD_BEE0)
                `uvm_error("SMOKE", $sformatf("SRC readback 0x%08h", value))
            model.CH1_LENGTH.mirror(status, UVM_CHECK, .parent(this));

            // VERSION is a HW constant, checked directly
            model.VERSION.read(status, value, .parent(this));
            if (value != 32'h0002_0000)
                `uvm_error("SMOKE", $sformatf("VERSION 0x%08h", value))
        endtask
    endclass

    // ---------------- test ----------------
    class dma_ral_test extends uvm_test;
        `uvm_component_utils(dma_ral_test)
        dma_ral_env env;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            env = dma_ral_env::type_id::create("env", this);
        endfunction

        task run_phase(uvm_phase phase);
            uvm_reg_hw_reset_seq reset_seq;
            ral_smoke_seq        smoke;

            phase.raise_objection(this);

            // exclude HW-tied / volatile registers from the reset-value check
            uvm_resource_db#(bit)::set({"REG::", env.regmodel.VERSION.get_full_name()},
                                       "NO_REG_TESTS", 1, this);
            uvm_resource_db#(bit)::set({"REG::", env.regmodel.CH0_STATUS.get_full_name()},
                                       "NO_REG_TESTS", 1, this);
            uvm_resource_db#(bit)::set({"REG::", env.regmodel.CH1_STATUS.get_full_name()},
                                       "NO_REG_TESTS", 1, this);

            reset_seq = uvm_reg_hw_reset_seq::type_id::create("reset_seq");
            reset_seq.model = env.regmodel;
            reset_seq.start(null);

            smoke = ral_smoke_seq::type_id::create("smoke");
            smoke.model = env.regmodel;
            smoke.start(env.agent.sqr);

            phase.drop_objection(this);
        endtask
    endclass

endpackage

`endif // DMA_RAL_PKG_SV
