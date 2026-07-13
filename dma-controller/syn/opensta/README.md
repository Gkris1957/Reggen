# OpenSTA timing flow for `dma_top`

OpenSTA is a **sign-off static timing analyzer**, not a synthesizer. It reads a
*mapped gate-level netlist* plus a **Liberty** cell library and reports slack.
So the flow has three stages — synthesis is done by Yosys, timing by OpenSTA:

```
rtl/*.sv --(sv2v)--> build/dma_top.v --(Yosys+Liberty)--> build/dma_top_netlist.v --(OpenSTA)--> build/dma_top_sta.rpt
```

This mirrors what Quartus did in one tool (`../synth.tcl` + `../dma.sdc`), but with
an open-source ASIC-style flow you can run anywhere and that pairs with the
`sta-analyzer` tool (which already parses OpenSTA reports).

## Install

```bash
sudo apt-get install -y yosys opensta          # both are packaged on recent Ubuntu
# sv2v: packaged as 'sv2v' on some distros; otherwise grab the release binary:
#   https://github.com/zachjs/sv2v/releases  -> put 'sv2v' on PATH
```

If `opensta` isn't packaged, build it: <https://github.com/parallaxsw/OpenSTA>.

## Get a Liberty library

OpenSTA needs real cell timing. Any free standard-cell `.lib` works:

- **SkyWater sky130** (recommended, fully open PDK):
  `sky130_fd_sc_hd__tt_025C_1v80.lib` from the
  [open_pdks](https://github.com/RTimothyEdwards/open_pdks) / sky130 install.
- **Nangate 45nm** Open Cell Library (`NangateOpenCellLibrary_typical.lib`).

## Run

```bash
LIB=/path/to/sky130_fd_sc_hd__tt_025C_1v80.lib ./run.sh
```

Output: `build/dma_top_sta.rpt` — worst 10 setup paths (full expanded), plus
WNS/TNS and hold checks.

## Analyze with sta-analyzer

```bash
cd ../../../sta-analyzer
sta-analyze ../dma-controller/syn/opensta/build/dma_top_sta.rpt
# add --llm for a Claude root-cause + fix plan (needs ANTHROPIC_API_KEY)
```

## Notes

- `dma.sdc` here is the OpenSTA-compatible twin of `../dma.sdc`
  (`derive_clock_uncertainty` → `set_clock_uncertainty`; input delay excludes
  the clock port via `remove_from_collection`).
- Absolute slack numbers differ from the Quartus/Cyclone-V run — a sky130/Nangate
  ASIC library is a different fabric than a Cyclone V FPGA. What transfers is the
  *method* and the *shape* of the critical path (the burst-length calc into the
  AXI address/data registers).
- `synth -flatten` gives OpenSTA a flat netlist so `report_checks` names real
  leaf pins; drop `-flatten` if you want hierarchical instance paths.
