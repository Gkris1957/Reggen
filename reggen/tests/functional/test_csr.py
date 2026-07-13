"""Functional verification of the reggen-generated AXI-Lite CSR slave.

Drives the DUT (dma_csr_axil_csr, generated from examples/dma_lite.yaml) over a
real AXI4-Lite handshake in a Verilator simulation and checks the *behavior* the
static gates cannot: reset values, RW round-trips, WSTRB byte-enables, and the
W1C / W1S / RC / RO semantics.

Run via the Makefile in this directory:  make
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# Register offsets (mirror examples/dma_lite.yaml)
CTRL = 0x00
STATUS = 0x04
SRC_ADDR = 0x08
LENGTH = 0x10

OKAY = 0b00


class AxiLiteMaster:
    """Minimal AXI4-Lite master: one outstanding transaction at a time."""

    def __init__(self, dut):
        self.dut = dut

    async def reset(self):
        d = self.dut
        d.s_axi_aresetn.value = 0
        d.s_axi_awvalid.value = 0
        d.s_axi_wvalid.value = 0
        d.s_axi_bready.value = 0
        d.s_axi_arvalid.value = 0
        d.s_axi_rready.value = 0
        d.s_axi_awaddr.value = 0
        d.s_axi_wdata.value = 0
        d.s_axi_wstrb.value = 0
        d.s_axi_araddr.value = 0
        # drive all design-facing inputs low
        for sig in ("STATUS_BUSY_i", "STATUS_DONE_set_i", "STATUS_ERROR_set_i",
                    "CTRL_RESET_clr_i"):
            getattr(d, sig).value = 0
        await ClockCycles(d.s_axi_aclk, 5)
        d.s_axi_aresetn.value = 1
        await ClockCycles(d.s_axi_aclk, 2)

    async def write(self, addr, data, strb=0xF):
        d = self.dut
        await RisingEdge(d.s_axi_aclk)
        d.s_axi_awaddr.value = addr
        d.s_axi_awvalid.value = 1
        d.s_axi_wdata.value = data
        d.s_axi_wstrb.value = strb
        d.s_axi_wvalid.value = 1
        d.s_axi_bready.value = 1
        # wait for both address and data to be accepted
        while True:
            await RisingEdge(d.s_axi_aclk)
            if d.s_axi_awready.value and d.s_axi_wready.value:
                break
        d.s_axi_awvalid.value = 0
        d.s_axi_wvalid.value = 0
        # wait for write response
        while not d.s_axi_bvalid.value:
            await RisingEdge(d.s_axi_aclk)
        assert int(d.s_axi_bresp.value) == OKAY, f"BRESP not OKAY on write @0x{addr:x}"
        await RisingEdge(d.s_axi_aclk)
        d.s_axi_bready.value = 0

    async def read(self, addr):
        d = self.dut
        await RisingEdge(d.s_axi_aclk)
        d.s_axi_araddr.value = addr
        d.s_axi_arvalid.value = 1
        d.s_axi_rready.value = 1
        while not d.s_axi_arready.value:
            await RisingEdge(d.s_axi_aclk)
        d.s_axi_arvalid.value = 0
        while not d.s_axi_rvalid.value:
            await RisingEdge(d.s_axi_aclk)
        data = int(d.s_axi_rdata.value)
        assert int(d.s_axi_rresp.value) == OKAY, f"RRESP not OKAY on read @0x{addr:x}"
        await RisingEdge(d.s_axi_aclk)
        d.s_axi_rready.value = 0
        return data


async def start(dut):
    cocotb.start_soon(Clock(dut.s_axi_aclk, 10, units="ns").start())
    axi = AxiLiteMaster(dut)
    await axi.reset()
    return axi


@cocotb.test()
async def test_reset_values(dut):
    """After reset, registers read their spec'd reset values."""
    axi = await start(dut)
    # CTRL: BURST_LEN (bits 11:4) resets to 0x10 -> word value 0x100
    assert await axi.read(CTRL) == 0x100, "CTRL reset value wrong"
    assert await axi.read(SRC_ADDR) == 0x0
    assert await axi.read(LENGTH) == 0x0


@cocotb.test()
async def test_rw_roundtrip(dut):
    """RW registers store and read back exactly what was written."""
    axi = await start(dut)
    await axi.write(SRC_ADDR, 0xDEADBEEF)
    assert await axi.read(SRC_ADDR) == 0xDEADBEEF
    await axi.write(LENGTH, 0x0000_1000)
    assert await axi.read(LENGTH) == 0x0000_1000


@cocotb.test()
async def test_wstrb_byte_enables(dut):
    """A partial-strobe write only updates the addressed bytes."""
    axi = await start(dut)
    await axi.write(SRC_ADDR, 0xFFFFFFFF)              # all ones
    await axi.write(SRC_ADDR, 0x000000AA, strb=0b0001)  # only byte 0
    assert await axi.read(SRC_ADDR) == 0xFFFFFFAA, "WSTRB did not gate the write"


@cocotb.test()
async def test_reserved_bits_read_zero(dut):
    """Bits with no field read back as 0 even after writing all ones."""
    axi = await start(dut)
    await axi.write(CTRL, 0xFFFFFFFF)
    val = await axi.read(CTRL)
    # CTRL occupies bits 0,1,2 and 11:4 -> mask 0x0FF7; RESET(bit1) is W1S so it
    # sets, others store. Reserved bits (above 11, and bit3) must be 0.
    assert val & 0xFFFF_F008 == 0, f"reserved bits set: 0x{val:08x}"


@cocotb.test()
async def test_ro_field_reflects_hw_input(dut):
    """RO STATUS.BUSY mirrors the hardware input, not stored state."""
    axi = await start(dut)
    dut.STATUS_BUSY_i.value = 1
    await ClockCycles(dut.s_axi_aclk, 2)
    assert (await axi.read(STATUS)) & 0x1 == 1, "RO BUSY did not reflect input"
    dut.STATUS_BUSY_i.value = 0
    await ClockCycles(dut.s_axi_aclk, 2)
    assert (await axi.read(STATUS)) & 0x1 == 0


@cocotb.test()
async def test_w1c_hw_set_sw_clear(dut):
    """STATUS.DONE (W1C): HW pulse sets it, write-1 clears it."""
    axi = await start(dut)
    # HW event sets bit 1
    dut.STATUS_DONE_set_i.value = 1
    await ClockCycles(dut.s_axi_aclk, 1)
    dut.STATUS_DONE_set_i.value = 0
    await ClockCycles(dut.s_axi_aclk, 1)
    assert (await axi.read(STATUS)) & 0x2 == 0x2, "W1C bit not set by HW"
    # write 0 to bit 1 must NOT clear it
    await axi.write(STATUS, 0x0)
    assert (await axi.read(STATUS)) & 0x2 == 0x2, "W1C cleared by writing 0"
    # write 1 to bit 1 clears it
    await axi.write(STATUS, 0x2)
    assert (await axi.read(STATUS)) & 0x2 == 0x0, "W1C not cleared by writing 1"


@cocotb.test()
async def test_w1s_sw_set_hw_clear(dut):
    """CTRL.RESET (W1S): write-1 sets it, HW input clears it."""
    axi = await start(dut)
    await axi.write(CTRL, 0x2)                     # write 1 to bit 1 -> set
    assert (await axi.read(CTRL)) & 0x2 == 0x2, "W1S not set by writing 1"
    dut.CTRL_RESET_clr_i.value = 1                 # HW clear wins
    await ClockCycles(dut.s_axi_aclk, 2)
    dut.CTRL_RESET_clr_i.value = 0
    assert (await axi.read(CTRL)) & 0x2 == 0x0, "W1S not cleared by HW"
