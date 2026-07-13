REGGEN — register automation + AXI4 DMA controller

reggen is a Python tool that takes one YAML register specification and generates a synthesizable SystemVerilog register interface, a UVM verification model, a C header, and Markdown documentation — all from the same source, so they can never drift apart. It runs the spec through a three-stage validator (YAML parsing, JSON Schema structure checks, and semantic cross-field checks) before generating anything, so no malformed or logically inconsistent spec ever reaches the generators.

On top of that, this repo contains a real 2-channel AXI4 DMA controller built around a reggen-generated register interface. The DMA has independent read and write engines decoupled by a FIFO so bursts overlap instead of running serially, a round-robin arbiter sharing one AXI4 master port between channels, and burst-splitting logic that respects AXI's 4KB address boundary rule. It's verified with a cocotb testbench that randomly stalls every channel, injects bus errors, and checks the 4KB rule on every burst — this caught a real one-cycle race condition between the busy and done status flags during development. The design was synthesized on a Cyclone V FPGA at 100 MHz; the first synthesis run failed timing by -3.5 ns on a burst-length calculation, which was pipelined across two clock cycles to close timing at +1.77 ns.

A third piece, sta-analyzer, reads a Quartus or OpenSTA timing report, groups the violations by pattern, and proposes where to insert pipeline registers — on the DMA's own real timing report, it independently reached the same fix that was applied by hand.

Together: one spec generates the register interface, the DMA is built around it, cocotb proves it works, Quartus proves it's fast enough, and sta-analyzer helps read the results. See each project's own folder (reggen/, dma-controller/, sta-analyzer/) for full details.

