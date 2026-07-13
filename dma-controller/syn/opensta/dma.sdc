# OpenSTA constraints for dma_top — 100 MHz system clock.
# OpenSTA-compatible variant of ../dma.sdc (Quartus flavour).
#   - derive_clock_uncertainty -> explicit set_clock_uncertainty
#   - "input delay on all inputs except clk" via remove_from_collection

create_clock -name clk -period 10.000 [get_ports clk]
set_clock_uncertainty 0.100 [get_clocks clk]

# Async reset is not a timed path.
set_false_path -from [get_ports rst_n]

# Generous I/O budget for an IP-characterization run (no board pinout yet).
set inputs_no_clk [remove_from_collection [all_inputs] [get_ports clk]]
set_input_delay  -clock clk 2.0 $inputs_no_clk
set_output_delay -clock clk 2.0 [all_outputs]
