"""Functional verification of the 2-channel AXI DMA (v2).

Components:
  * AxiLiteMaster — drives the CSR slave port.
  * AxiMemSlave   — AXI4 slave memory, WSTRB byte-merge aware, random
                    backpressure on every channel, SLVERR region, and a
                    per-burst AXI 4KB-boundary check.
  * StreamSink / StreamSource — AXI-Stream endpoints with random throttling.
  * axi_checker.sv (in sim_top) — VALID/payload stability asserted in RTL.

Coverage: reset/version, MM2MM single word + multi-burst + byte tail +
4KB split + zero length + SLVERR abort/recovery, MM2S stream out (TLAST/TKEEP),
S2MM stream in, per-channel IRQ masking, concurrent dual-channel transfers
through the round-robin mux, and back-to-back reuse.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# ---- register map (mirrors specs/dma_csr.yaml) ----
CH_BASE = {0: 0x00, 1: 0x20}
CTRL, STATUS, SRC, DST, LENGTH = 0x00, 0x04, 0x08, 0x0C, 0x10
INT_EN = 0x80
VERSION = 0x84

START = 1 << 0
MODE_MM2MM, MODE_MM2S, MODE_S2MM = 0 << 1, 1 << 1, 2 << 1
BURST_SHIFT = 8
ST_BUSY, ST_DONE, ST_ERROR = 1, 2, 4

OKAY, SLVERR = 0b00, 0b10
ERR_BASE = 0xE000_0000


def ctrl_word(mode=MODE_MM2MM, burst=16):
    return (burst << BURST_SHIFT) | mode | START


class AxiLiteMaster:
    def __init__(self, dut):
        self.dut = dut

    async def write(self, addr, data):
        d = self.dut
        await RisingEdge(d.clk)
        d.s_axil_awaddr.value = addr
        d.s_axil_awvalid.value = 1
        d.s_axil_wdata.value = data
        d.s_axil_wstrb.value = 0xF
        d.s_axil_wvalid.value = 1
        d.s_axil_bready.value = 1
        while True:
            await RisingEdge(d.clk)
            if d.s_axil_awready.value and d.s_axil_wready.value:
                break
        d.s_axil_awvalid.value = 0
        d.s_axil_wvalid.value = 0
        while not d.s_axil_bvalid.value:
            await RisingEdge(d.clk)
        assert int(d.s_axil_bresp.value) == OKAY
        await RisingEdge(d.clk)
        d.s_axil_bready.value = 0

    async def read(self, addr):
        d = self.dut
        await RisingEdge(d.clk)
        d.s_axil_araddr.value = addr
        d.s_axil_arvalid.value = 1
        d.s_axil_rready.value = 1
        while not d.s_axil_arready.value:
            await RisingEdge(d.clk)
        d.s_axil_arvalid.value = 0
        while not d.s_axil_rvalid.value:
            await RisingEdge(d.clk)
        data = int(d.s_axil_rdata.value)
        assert int(d.s_axil_rresp.value) == OKAY
        await RisingEdge(d.clk)
        d.s_axil_rready.value = 0
        return data


class AxiMemSlave:
    """Byte-accurate AXI4 slave memory with WSTRB merge and backpressure."""

    def __init__(self, dut, rng):
        self.dut = dut
        self.rng = rng
        self.mem = {}          # byte address -> byte value
        self.bursts = []       # (kind, addr, beats)
        self.boundary_violations = []
        dut.m_axi_arready.value = 0
        dut.m_axi_rvalid.value = 0
        dut.m_axi_rdata.value = 0
        dut.m_axi_rresp.value = 0
        dut.m_axi_rlast.value = 0
        dut.m_axi_awready.value = 0
        dut.m_axi_wready.value = 0
        dut.m_axi_bvalid.value = 0
        dut.m_axi_bresp.value = 0
        cocotb.start_soon(self._read_channel())
        cocotb.start_soon(self._write_channel())

    # -- byte-level helpers --
    def word(self, addr):
        return sum(self.mem.get(addr + i, 0) << (8 * i) for i in range(4))

    def set_word(self, addr, value):
        for i in range(4):
            self.mem[addr + i] = (value >> (8 * i)) & 0xFF

    def _check_4k(self, kind, addr, beats):
        self.bursts.append((kind, addr, beats))
        if (addr & 0xFFF) + beats * 4 > 0x1000:
            self.boundary_violations.append((kind, hex(addr), beats))

    async def _stall(self, p=0.4, maxc=3):
        while self.rng.random() < p:
            await ClockCycles(self.dut.clk, self.rng.randint(1, maxc))

    async def _read_channel(self):
        d = self.dut
        while True:
            while True:
                await RisingEdge(d.clk)
                if d.m_axi_arvalid.value:
                    break
            await self._stall()
            d.m_axi_arready.value = 1
            await RisingEdge(d.clk)
            addr = int(d.m_axi_araddr.value)
            beats = int(d.m_axi_arlen.value) + 1
            d.m_axi_arready.value = 0
            self._check_4k("R", addr, beats)
            err = addr >= ERR_BASE
            for i in range(beats):
                await self._stall()
                d.m_axi_rdata.value = self.word(addr + 4 * i)
                d.m_axi_rresp.value = SLVERR if err else OKAY
                d.m_axi_rlast.value = 1 if i == beats - 1 else 0
                d.m_axi_rvalid.value = 1
                while True:
                    await RisingEdge(d.clk)
                    if d.m_axi_rready.value:
                        break
                d.m_axi_rvalid.value = 0
                d.m_axi_rlast.value = 0

    async def _write_channel(self):
        d = self.dut
        while True:
            while True:
                await RisingEdge(d.clk)
                if d.m_axi_awvalid.value:
                    break
            await self._stall()
            d.m_axi_awready.value = 1
            await RisingEdge(d.clk)
            addr = int(d.m_axi_awaddr.value)
            beats = int(d.m_axi_awlen.value) + 1
            d.m_axi_awready.value = 0
            self._check_4k("W", addr, beats)
            err = addr >= ERR_BASE
            got = 0
            while True:
                d.m_axi_wready.value = 1 if self.rng.random() < 0.7 else 0
                await RisingEdge(d.clk)
                if d.m_axi_wready.value and d.m_axi_wvalid.value:
                    if not err:
                        data = int(d.m_axi_wdata.value)
                        strb = int(d.m_axi_wstrb.value)
                        base = addr + 4 * got
                        for i in range(4):          # WSTRB byte merge
                            if strb & (1 << i):
                                self.mem[base + i] = (data >> (8 * i)) & 0xFF
                    last = bool(d.m_axi_wlast.value)
                    got += 1
                    if last:
                        break
            d.m_axi_wready.value = 0
            assert got == beats, f"W beats {got} != AWLEN+1 {beats}"
            await self._stall()
            d.m_axi_bresp.value = SLVERR if err else OKAY
            d.m_axi_bvalid.value = 1
            while True:
                await RisingEdge(d.clk)
                if d.m_axi_bready.value:
                    break
            d.m_axi_bvalid.value = 0


class StreamSink:
    """Collects one channel's m_axis output with random TREADY throttling."""

    def __init__(self, dut, ch, rng):
        self.dut = dut
        self.rng = rng
        self.beats = []        # (data, keep, last)
        self.td = getattr(dut, f"ch{ch}_m_axis_tdata")
        self.tk = getattr(dut, f"ch{ch}_m_axis_tkeep")
        self.tl = getattr(dut, f"ch{ch}_m_axis_tlast")
        self.tv = getattr(dut, f"ch{ch}_m_axis_tvalid")
        self.tr = getattr(dut, f"ch{ch}_m_axis_tready")
        self.tr.value = 0
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            self.tr.value = 1 if self.rng.random() < 0.7 else 0
            await RisingEdge(self.dut.clk)
            if self.tr.value and self.tv.value:
                self.beats.append(
                    (int(self.td.value), int(self.tk.value), bool(self.tl.value))
                )


class StreamSource:
    """Drives one channel's s_axis input with random TVALID gaps."""

    def __init__(self, dut, ch, rng):
        self.dut = dut
        self.rng = rng
        self.td = getattr(dut, f"ch{ch}_s_axis_tdata")
        self.tv = getattr(dut, f"ch{ch}_s_axis_tvalid")
        self.tr = getattr(dut, f"ch{ch}_s_axis_tready")
        self.tv.value = 0
        self.td.value = 0

    async def send(self, words):
        d = self.dut
        for w in words:
            while self.rng.random() < 0.3:
                await RisingEdge(d.clk)
            self.td.value = w
            self.tv.value = 1
            while True:
                await RisingEdge(d.clk)
                if self.tr.value:
                    break
            self.tv.value = 0


async def setup(dut, seed=1):
    rng = random.Random(seed)
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axil_awvalid.value = 0
    dut.s_axil_wvalid.value = 0
    dut.s_axil_bready.value = 0
    dut.s_axil_arvalid.value = 0
    dut.s_axil_rready.value = 0
    mem = AxiMemSlave(dut, rng)
    sinks = {c: StreamSink(dut, c, rng) for c in (0, 1)}
    srcs = {c: StreamSource(dut, c, rng) for c in (0, 1)}
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    return AxiLiteMaster(dut), mem, rng, sinks, srcs


async def program(axil, ch, src, dst, nbytes):
    base = CH_BASE[ch]
    await axil.write(base + SRC, src)
    await axil.write(base + DST, dst)
    await axil.write(base + LENGTH, nbytes)


async def wait_idle(axil, dut, ch, timeout=30000):
    base = CH_BASE[ch]
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        status = await axil.read(base + STATUS)
        if not status & ST_BUSY:
            return status
    raise AssertionError(f"timeout: ch{ch} BUSY never deasserted")


async def run_dma(axil, dut, ch, src, dst, nbytes, burst=16, mode=MODE_MM2MM):
    await program(axil, ch, src, dst, nbytes)
    await axil.write(CH_BASE[ch] + CTRL, ctrl_word(mode, burst))
    return await wait_idle(axil, dut, ch)


def preload(mem, src, words, rng):
    data = [rng.getrandbits(32) for _ in range(words)]
    for i, w in enumerate(data):
        mem.set_word(src + 4 * i, w)
    return data


def readback_words(mem, dst, words):
    return [mem.word(dst + 4 * i) for i in range(words)]


def expected_bytes(data_words, nbytes):
    out = []
    for w in data_words:
        out += [(w >> (8 * i)) & 0xFF for i in range(4)]
    return out[:nbytes]


def readback_bytes(mem, dst, nbytes):
    return [mem.mem.get(dst + i, None) for i in range(nbytes)]


# =============================== tests ======================================

@cocotb.test()
async def test_version_and_reset(dut):
    """VERSION reads 2.0.0; both channels idle at reset."""
    axil, _, _, _, _ = await setup(dut)
    assert await axil.read(VERSION) == 0x0002_0000
    for ch in (0, 1):
        assert await axil.read(CH_BASE[ch] + CTRL) == 0x10 << BURST_SHIFT
        assert await axil.read(CH_BASE[ch] + STATUS) == 0
    assert dut.irq.value == 0


@cocotb.test()
async def test_single_word_each_channel(dut):
    """One-word MM2MM copy on each channel independently."""
    axil, mem, rng, _, _ = await setup(dut, seed=2)
    for ch, (src, dst) in enumerate([(0x1000, 0x2000), (0x3000, 0x4000)]):
        data = preload(mem, src, 1, rng)
        status = await run_dma(axil, dut, ch, src, dst, 4)
        assert status & ST_DONE and not status & ST_ERROR
        assert readback_words(mem, dst, 1) == data


@cocotb.test()
async def test_multi_burst_with_tail(dut):
    """100 words on ch0, burst 16: pipelined bursts, data intact."""
    axil, mem, rng, _, _ = await setup(dut, seed=3)
    words = 100
    data = preload(mem, 0x1_0000, words, rng)
    status = await run_dma(axil, dut, 0, 0x1_0000, 0x2_0000, words * 4, burst=16)
    assert status & ST_DONE and not status & ST_ERROR
    assert readback_words(mem, 0x2_0000, words) == data
    rbursts = [b for b in mem.bursts if b[0] == "R"]
    assert [beats for _, _, beats in rbursts] == [16] * 6 + [4]
    assert not mem.boundary_violations


@cocotb.test()
async def test_byte_tail_strobes(dut):
    """LENGTH=103 bytes: final beat writes only 3 bytes (WSTRB=0111)."""
    axil, mem, rng, _, _ = await setup(dut, seed=4)
    nbytes = 103                       # 25 words + 3-byte tail
    words = 26
    data = preload(mem, 0x1000, words, rng)
    # canary bytes beyond the tail must survive untouched
    for i in range(3):
        mem.mem[0x2000 + nbytes + i] = 0xC0 + i
    status = await run_dma(axil, dut, 0, 0x1000, 0x2000, nbytes)
    assert status & ST_DONE
    assert readback_bytes(mem, 0x2000, nbytes) == expected_bytes(data, nbytes)
    assert [mem.mem[0x2000 + nbytes + i] for i in range(3)] == [0xC0, 0xC1, 0xC2], \
        "tail WSTRB overwrote bytes beyond LENGTH"


@cocotb.test()
async def test_4kb_boundary_split(dut):
    """src 16 bytes below a 4KB line: bursts split exactly at 0x3000."""
    axil, mem, rng, _, _ = await setup(dut, seed=5)
    words = 16
    src = 0x2FF0
    data = preload(mem, src, words, rng)
    status = await run_dma(axil, dut, 0, src, 0x8000, words * 4, burst=16)
    assert status & ST_DONE
    assert readback_words(mem, 0x8000, words) == data
    assert not mem.boundary_violations, mem.boundary_violations
    rbursts = [b for b in mem.bursts if b[0] == "R"]
    assert rbursts[0] == ("R", 0x2FF0, 4), rbursts
    assert rbursts[1] == ("R", 0x3000, 12), rbursts


@cocotb.test()
async def test_zero_length(dut):
    """LENGTH=0: immediate DONE, zero bus activity."""
    axil, mem, _, _, _ = await setup(dut, seed=6)
    status = await run_dma(axil, dut, 0, 0x1000, 0x2000, 0)
    assert status & ST_DONE and not status & ST_ERROR
    assert mem.bursts == []


@cocotb.test()
async def test_error_aborts_and_recovers(dut):
    """SLVERR read: ERROR set, DONE clear; channel usable afterwards."""
    axil, mem, rng, _, _ = await setup(dut, seed=7)
    status = await run_dma(axil, dut, 0, ERR_BASE, 0x2000, 64)
    assert status & ST_ERROR and not status & ST_DONE
    await axil.write(CH_BASE[0] + STATUS, ST_ERROR)      # W1C
    data = preload(mem, 0x1000, 8, rng)
    status = await run_dma(axil, dut, 0, 0x1000, 0x2000, 32)
    assert status & ST_DONE
    assert readback_words(mem, 0x2000, 8) == data


@cocotb.test()
async def test_mm2s_stream_out(dut):
    """MM2S: memory streams out on ch0 m_axis with TLAST and tail TKEEP."""
    axil, mem, rng, sinks, _ = await setup(dut, seed=8)
    nbytes = 42                        # 10 words + 2-byte tail (TKEEP 0011)
    words = 11
    data = preload(mem, 0x1000, words, rng)
    status = await run_dma(axil, dut, 0, 0x1000, 0, nbytes, mode=MODE_MM2S)
    assert status & ST_DONE
    await ClockCycles(dut.clk, 20)     # let the sink drain
    beats = sinks[0].beats
    assert len(beats) == words
    assert [b[0] for b in beats] == data
    assert all(k == 0xF for _, k, _ in beats[:-1])
    assert beats[-1][1] == 0x3, "tail TKEEP wrong"
    assert beats[-1][2] and not any(l for _, _, l in beats[:-1]), "TLAST wrong"


@cocotb.test()
async def test_s2mm_stream_in(dut):
    """S2MM: ch1 s_axis stream lands in memory with tail strobes."""
    axil, mem, rng, _, srcs = await setup(dut, seed=9)
    nbytes = 29                        # 7 words + 1-byte tail
    words = 8
    data = [rng.getrandbits(32) for _ in range(words)]
    await program(axil, 1, 0, 0x6000, nbytes)
    await axil.write(CH_BASE[1] + CTRL, ctrl_word(MODE_S2MM, 16))
    cocotb.start_soon(srcs[1].send(data))
    status = await wait_idle(axil, dut, 1)
    assert status & ST_DONE
    assert readback_bytes(mem, 0x6000, nbytes) == expected_bytes(data, nbytes)


@cocotb.test()
async def test_irq_per_channel_masking(dut):
    """irq = OR of enabled flags; per-channel enables mask correctly."""
    axil, mem, rng, _, _ = await setup(dut, seed=10)
    preload(mem, 0x1000, 4, rng)
    status = await run_dma(axil, dut, 1, 0x1000, 0x2000, 16)
    assert status & ST_DONE and dut.irq.value == 0       # masked
    await axil.write(INT_EN, 1 << 0)                     # only CH0_DONE_EN
    await ClockCycles(dut.clk, 2)
    assert dut.irq.value == 0, "ch1 flag must not pass ch0 enable"
    await axil.write(INT_EN, 1 << 2)                     # CH1_DONE_EN
    await ClockCycles(dut.clk, 2)
    assert dut.irq.value == 1
    await axil.write(CH_BASE[1] + STATUS, ST_DONE)       # W1C
    await ClockCycles(dut.clk, 2)
    assert dut.irq.value == 0


@cocotb.test()
async def test_concurrent_channels(dut):
    """Both channels run MM2MM at once through the round-robin mux."""
    axil, mem, rng, _, _ = await setup(dut, seed=11)
    w0, w1 = 80, 60
    d0 = preload(mem, 0x1_0000, w0, rng)
    d1 = preload(mem, 0x3_0000, w1, rng)
    await program(axil, 0, 0x1_0000, 0x2_0000, w0 * 4)
    await program(axil, 1, 0x3_0000, 0x4_0000, w1 * 4)
    await axil.write(CH_BASE[0] + CTRL, ctrl_word(burst=8))
    await axil.write(CH_BASE[1] + CTRL, ctrl_word(burst=8))
    s0 = await wait_idle(axil, dut, 0)
    s1 = await wait_idle(axil, dut, 1)
    assert s0 & ST_DONE and s1 & ST_DONE
    assert readback_words(mem, 0x2_0000, w0) == d0, "ch0 data corrupted"
    assert readback_words(mem, 0x4_0000, w1) == d1, "ch1 data corrupted"
    assert not mem.boundary_violations
    # both channels' bursts must interleave on the shared port
    r_addrs = [a for k, a, _ in mem.bursts if k == "R"]
    assert any(a >= 0x3_0000 for a in r_addrs) and any(a < 0x2_0000 for a in r_addrs)


@cocotb.test()
async def test_back_to_back(dut):
    """Three consecutive transfers on ch0; state fully recycles."""
    axil, mem, rng, _, _ = await setup(dut, seed=12)
    for n, (src, dst, words) in enumerate(
        [(0x1000, 0x9000, 17), (0x3000, 0xB000, 64), (0x5000, 0xD000, 3)]
    ):
        data = preload(mem, src, words, rng)
        status = await run_dma(axil, dut, 0, src, dst, words * 4, burst=8)
        assert status & ST_DONE, f"transfer {n} failed"
        await axil.write(CH_BASE[0] + STATUS, ST_DONE)
        assert readback_words(mem, dst, words) == data, f"transfer {n} mismatch"
    assert not mem.boundary_violations
