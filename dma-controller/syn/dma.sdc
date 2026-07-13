# Timing constraints for dma_top — 100 MHz system clock.
create_clock -name clk -period 10.000 [get_ports clk]
derive_clock_uncertainty

# Single-clock design; treat async reset and top-level I/O generously for the
# area/Fmax characterization run (no board pinout yet).
set_false_path -from [get_ports rst_n]
set_input_delay  -clock clk 2.0 [all_inputs]
set_output_delay -clock clk 2.0 [all_outputs]
set_input_delay  -clock clk -remove [get_ports clk]
