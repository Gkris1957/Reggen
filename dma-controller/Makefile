# dma-controller top-level targets.
# Requires the reggen venv active:  source ../reggen/.venv/bin/activate

RTL  := rtl
SPEC := specs/dma_csr.yaml

.PHONY: regen lint sim clean

# Regenerate every reggen artifact from the YAML single source of truth.
regen:
	reggen gen $(SPEC) --target sv  -o $(RTL)/csr.sv
	reggen gen $(SPEC) --target uvm -o tb/uvm/csr_reg_block.sv
	reggen gen $(SPEC) --target c   -o $(RTL)/csr.h
	reggen gen $(SPEC) --target md  -o docs/REGS.md

lint: regen
	verilator --lint-only -Wall -Wno-DECLFILENAME --top-module dma_top \
	    $(RTL)/csr.sv $(RTL)/dma_fifo.sv $(RTL)/dma_channel.sv \
	    $(RTL)/dma_axi_mux.sv $(RTL)/dma_top.sv
	@echo LINT CLEAN

sim:
	$(MAKE) -C tb/cocotb

clean:
	$(MAKE) -C tb/cocotb clean
