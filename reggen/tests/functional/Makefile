# Functional sim of the reggen-generated AXI-Lite CSR (cocotb + Verilator).
#
#   make            # regenerate DUT from YAML, then run the cocotb tests
#   make clean      # remove sim build artifacts
#
# Requires the reggen venv active (for `reggen` and `cocotb`), Verilator, make.

SIM ?= verilator
TOPLEVEL_LANG ?= verilog

SPEC := ../../examples/dma_lite.yaml
DUT  := dma_csr.sv

VERILOG_SOURCES := $(PWD)/$(DUT)
TOPLEVEL := dma_csr_axil_csr
MODULE   := test_csr

# Verilator needs --timing for the cocotb clock; silence generated-name lint.
EXTRA_ARGS += --timing -Wno-DECLFILENAME

# Default: regenerate the DUT from the current spec, then run the cocotb flow.
.DEFAULT_GOAL := run
.PHONY: run
run: $(DUT)
	$(MAKE) sim

# Regenerate the DUT so the sim always matches the current generator.
$(DUT): $(SPEC)
	reggen gen $(SPEC) --target sv -o $(DUT)

include $(shell cocotb-config --makefiles)/Makefile.sim
