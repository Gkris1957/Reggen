# OpenSTA sign-off script for dma_top.
# Inputs come from environment (set by run.sh):
#   LIB      - path to the standard-cell Liberty (.lib) file
#   NETLIST  - gate-level netlist produced by Yosys
# Run:  sta -exit sta.tcl   (LIB/NETLIST exported first)

read_liberty $env(LIB)
read_verilog $env(NETLIST)
link_design dma_top

read_sdc dma.sdc

puts "===================== WORST SETUP PATHS ====================="
# Full expanded path so sta-analyzer can parse from/to, logic levels, delay.
report_checks -path_delay max -sort_by_slack -group_count 10 \
              -format full_clock_expanded

puts "===================== SUMMARY ====================="
report_worst_slack -max
report_tns
report_wns

# Also emit a hold check — cheap and a good sanity signal.
puts "===================== WORST HOLD PATHS ====================="
report_checks -path_delay min -sort_by_slack -group_count 3
