# reggen

One YAML register-map spec → SystemVerilog AXI-Lite CSR slave, UVM register
block, C header, and Markdown docs. A single source of truth across design,
verification, software, and documentation.

## Status

Validated YAML → four generated artifacts, each guarded by a real toolchain check.

| Stage | Output | Gate |
|---|---|---|
| Validation | — | 3-stage: YAML parse → JSON Schema → semantic checks |
| IR | typed object model | masks / reset / reserved bits / access flags |
| `sv` | SystemVerilog AXI-Lite CSR slave | Verilator `--lint-only -Wall` |
| `uvm` | UVM `uvm_reg_block` package | QuestaSim compile vs UVM 1.2 (opt-in) |
| `c` | C register header | `gcc -Wall -Wextra` + runtime macro check |
| `md` | Markdown register map | structural |

All outputs are deterministic (no embedded timestamps) and locked by a
golden-file regression suite.

## Install (dev)

```bash
cd reggen
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Use

```bash
# validate a spec (exit code 1 on any error)
reggen validate examples/dma_lite.yaml

# generate any target (stdout, or -o FILE)
reggen gen examples/dma_lite.yaml --target sv  -o dma_csr.sv
reggen gen examples/dma_lite.yaml --target uvm -o dma_csr_reg_pkg.sv
reggen gen examples/dma_lite.yaml --target c   -o dma_csr.h
reggen gen examples/dma_lite.yaml --target md  -o REGS.md
```

```python
from reggen import load_ir
rmap = load_ir("examples/dma_lite.yaml")     # validated + built IR
print(rmap.register("CTRL").reset_value)
```

## Natural-language frontend (Claude API)

`reggen nl2yaml` converts a plain-English register description into YAML that
has already passed the full 3-stage validation — the validator runs **in the
loop**: Claude's output is checked, and every error is fed back for
self-correction (up to `--max-retries` rounds). The result is never an
unvalidated guess.

```bash
pip install -e ".[nl]"           # adds the anthropic SDK
export ANTHROPIC_API_KEY=...     # or `ant auth login`

reggen nl2yaml "A DMA channel: control register with a self-clearing start \
bit and an 8-bit burst length, a status register with busy (read-only) and \
a done interrupt flag cleared by writing 1, plus 32-bit source, destination \
and byte-count registers." -o dma_ch.yaml

reggen gen dma_ch.yaml --target sv   # straight into the normal flow
```

Uses `claude-opus-4-8` with adaptive thinking; the schema+rules system prompt
carries a cache breakpoint so correction rounds hit the prompt cache. The
loop is fully unit-tested with a fake client (no key needed for `pytest`).

## Test

```bash
pytest -q                          # full suite: validation, IR, generators, golden files, nl2yaml
REGGEN_UPDATE_GOLDEN=1 pytest      # regenerate golden snapshots after an intended change
REGGEN_UVM_COMPILE=1 pytest        # also run the QuestaSim+UVM compile gate (needs Questa)
REGGEN_FUNCTIONAL=1 pytest tests/test_functional.py   # cocotb sim of the generated CSR
```

The functional sim drives the generated AXI-Lite slave over a real Verilator
simulation (reset values, RW round-trip, WSTRB byte-enables, W1C/W1S/RC/RO
semantics). Run it directly for the full log:

```bash
cd tests/functional && make        # needs the venv active (reggen, cocotb, Verilator)
```

## Spec shape (v0)

```yaml
block:
  name: dma_csr          # required, valid identifier
  data_width: 32         # 8 | 16 | 32 | 64  (bus width)
  addr_width: 12         # offset must fit in this many bits
  base_address: 0x0000   # optional

registers:
  - name: CTRL
    offset: 0x00         # byte address; unique + aligned to register width
    fields:              # EITHER fields ...
      - name: ENABLE
        bits: "0"        # "MSB:LSB" or single "N"
        access: RW       # RW RO WO W1C W1S RW1C RW1S RC
        reset: 0x0
  - name: SRC_ADDR
    offset: 0x08
    access: RW           # ... OR a register-level access/reset (whole-width field)
    reset: 0x0
```

A register uses **either** `fields` **or** register-level `access`/`reset`,
never both — one source of truth per register.
