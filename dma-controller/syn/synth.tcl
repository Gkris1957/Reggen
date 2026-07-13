# Quartus project setup for dma_top synthesis + timing characterization.
#   quartus_sh -t synth.tcl   (then quartus_map / quartus_fit / quartus_sta)
project_new dma_top -overwrite

set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CGXFC7C7F23C8
set_global_assignment -name TOP_LEVEL_ENTITY dma_top

set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/csr.sv
set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/dma_fifo.sv
set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/dma_channel.sv
set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/dma_axi_mux.sv
set_global_assignment -name SYSTEMVERILOG_FILE ../rtl/dma_top.sv

set_global_assignment -name SDC_FILE dma.sdc

# characterization settings
set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output

# IP characterization: the DMA is a core, not a chip — map its 400+ bus pins
# to virtual pins so the fitter measures logic timing, not I/O placement.
set_instance_assignment -name VIRTUAL_PIN ON -to *
set_instance_assignment -name VIRTUAL_PIN OFF -to clk

project_close
