# Functional sim of the 2-channel DMA (cocotb + Verilator).
#
#   make            # regenerate csr.sv from the YAML spec, then run all tests
#   make WAVES=1    # same, plus dump.fst waveform (view with gtkwave)
#   make clean      # remove sim artifacts
#
# Requires the reggen venv active (reggen, cocotb 1.9.x) and Verilator >= 5.

SIM ?= verilator
TOPLEVEL_LANG ?= verilog

RTL  := $(CURDIR)/../../rtl
SPEC := $(CURDIR)/../../specs/dma_csr.yaml

VERILOG_SOURCES := $(RTL)/csr.sv $(RTL)/dma_fifo.sv $(RTL)/dma_channel.sv \
                   $(RTL)/dma_axi_mux.sv $(RTL)/dma_top.sv \
                   $(CURDIR)/axi_checker.sv $(CURDIR)/sim_top.sv
TOPLEVEL := sim_top
MODULE   := test_dma

EXTRA_ARGS += --timing -Wno-DECLFILENAME
ifeq ($(WAVES),1)
EXTRA_ARGS += --trace-fst --trace-structs   # compile-in FST trace support
SIM_ARGS   += --trace                       # enable dumping at runtime
endif

.DEFAULT_GOAL := run
.PHONY: run
run: $(RTL)/csr.sv
	$(MAKE) sim

# csr.sv is generated — always derived from the YAML single source of truth.
$(RTL)/csr.sv: $(SPEC)
	reggen gen $(SPEC) --target sv -o $(RTL)/csr.sv

include $(shell cocotb-config --makefiles)/Makefile.sim
