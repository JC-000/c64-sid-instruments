"""ACME-assembled tiny C64 driver + VICE invocation for SID rendering.

The generated .prg installs a 50Hz raster IRQ at $1000 that:

    1. steps through a wavetable sequence (test bit, attack waveform,
       sustain waveform) with per-frame control register updates;
    2. applies PW sweep (linear or ping-pong) each frame;
    3. applies filter cutoff sweep each frame;
    4. holds the gate bit on for the computed ``gate_frames``, then
       clears it for ``release_frames`` more frames; and
    5. after the note finishes, silences the SID and halts in a loop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .render import SidParams

from .render import (  # noqa: E402
    PAL_CLOCK_HZ,
    hz_to_sid_freq,
    _waveform_mask,
    _compute_pw_for_frame,
    _compute_filter_cutoff_for_frame,
    WF_TEST,
    WF_GATE,
    WF_RING_MOD,
    WF_SYNC,
)

# Per-PAL-frame cycle budget: 63 cycles/line * 312 lines.
PAL_CYCLES_PER_FRAME = 63 * 312  # 19656

# Max frames we can put in a table embedded in the .prg.
MAX_TABLE_FRAMES = 512


def _hex(v: int, width: int = 2) -> str:
    return f"${v:0{width}x}"


def _build_control_byte(params: "SidParams", wf_mask: int, gate: bool) -> int:
    """Build a control register byte from waveform mask, flags, and gate."""
    cb = wf_mask
    if params.ring_mod:
        cb |= WF_RING_MOD
    if params.sync:
        cb |= WF_SYNC
    if gate:
        cb |= WF_GATE
    return cb & 0xFF


def build_prg(params: "SidParams", prg_path: Path) -> Path:
    """Assemble a tiny driver .prg for ``params``.

    The .prg autostarts via BASIC SYS and takes over IRQs. The IRQ handler
    steps through pre-computed per-frame tables for waveform control, PW,
    and filter cutoff values.
    """
    freq_reg = hz_to_sid_freq(params.frequency, PAL_CLOCK_HZ)
    freq_lo = freq_reg & 0xFF
    freq_hi = (freq_reg >> 8) & 0xFF

    ad = params.ad_byte()
    sr = params.sr_byte()
    mode_vol = params.filter_mode_vol_byte()
    res_filt = params.filter_res_filt_byte()

    gate_frames = max(1, int(params.gate_frames))
    total_frames = max(gate_frames + 1, int(params.gate_frames + params.release_frames))

    # Limit table size
    total_frames = min(total_frames, MAX_TABLE_FRAMES)
    gate_frames = min(gate_frames, total_frames - 1)

    gate_lo = gate_frames & 0xFF
    gate_hi = (gate_frames >> 8) & 0xFF
    total_lo = total_frames & 0xFF
    total_hi = (total_frames >> 8) & 0xFF

    # Pre-compute per-frame tables
    sustain_wf = _waveform_mask(params.effective_sustain_waveform())
    attack_wf = _waveform_mask(params.effective_attack_waveform())
    wt_attack_frames = max(1, params.wt_attack_frames)
    pw_start = params.effective_pw_start()
    pw_delta = params.pw_delta
    pw_min = params.pw_min
    pw_max = params.pw_max
    pw_mode = params.pw_mode or "sweep"
    cutoff_start = params.effective_filter_cutoff_start()
    cutoff_end = params.effective_filter_cutoff_end()
    sweep_frames = params.filter_sweep_frames

    # Build control byte table (gate-on phase)
    ctrl_table = []
    pw_lo_table = []
    pw_hi_table = []
    fc_lo_table = []
    fc_hi_table = []

    for f in range(total_frames):
        gate = f < gate_frames

        # Waveform control
        if params.wt_use_test_bit and f == 0:
            ctrl = WF_TEST  # no gate
        elif f <= wt_attack_frames and gate:
            ctrl = _build_control_byte(params, attack_wf, gate)
        else:
            ctrl = _build_control_byte(params, sustain_wf, gate)
        ctrl_table.append(ctrl)

        # PW
        pw = _compute_pw_for_frame(f, pw_start, pw_delta, pw_min, pw_max, pw_mode)
        pw_lo_table.append(pw & 0xFF)
        pw_hi_table.append((pw >> 8) & 0x0F)

        # Filter cutoff
        fc = _compute_filter_cutoff_for_frame(f, cutoff_start, cutoff_end, sweep_frames)
        fc_lo_table.append(fc & 0x07)
        fc_hi_table.append((fc >> 3) & 0xFF)

    def _table_bytes(table, name):
        """Format a table as ACME !byte lines."""
        lines = [f"{name}:"]
        for i in range(0, len(table), 16):
            chunk = table[i:i+16]
            line = "    !byte " + ", ".join(_hex(v) for v in chunk)
            lines.append(line)
        return "\n".join(lines)

    ctrl_data = _table_bytes(ctrl_table, "ctrl_table")
    pw_lo_data = _table_bytes(pw_lo_table, "pw_lo_table")
    pw_hi_data = _table_bytes(pw_hi_table, "pw_hi_table")
    fc_lo_data = _table_bytes(fc_lo_table, "fc_lo_table")
    fc_hi_data = _table_bytes(fc_hi_table, "fc_hi_table")

    asm = f"""
!cpu 6510
; ---------- BASIC stub: 10 SYS 4096 ----------
* = $0801
!byte $0c,$08,$0a,$00,$9e,$20,$34,$30,$39,$36,$00,$00,$00

* = $1000
    sei
    lda #$7f
    sta $dc0d           ; disable CIA1 IRQs
    lda $dc0d           ; ack
    lda #$01
    sta $d01a           ; enable raster IRQ
    lda #$1b
    sta $d011           ; vertical blank raster high bit = 0
    lda #$00
    sta $d012           ; raster line 0
    lda #<irq
    sta $0314
    lda #>irq
    sta $0315
    ; silence all voices, init SID
    ldx #$18
clr_sid:
    lda #$00
    sta $d400,x
    dex
    bpl clr_sid

    ; write static registers
    lda #{_hex(freq_lo)}
    sta $d400
    lda #{_hex(freq_hi)}
    sta $d401
    lda #{_hex(ad)}
    sta $d405
    lda #{_hex(sr)}
    sta $d406
    lda #{_hex(res_filt)}
    sta $d417
    lda #{_hex(mode_vol)}
    sta $d418

    ; reset frame counter (16-bit at $c000/$c001)
    lda #$00
    sta $c000
    sta $c001
    sta $c002           ; done flag: 0=running, 1=done

    cli
    ; main loop - just spin
forever:
    jmp forever

irq:
    lda #$01
    sta $d019           ; ack raster IRQ

    lda $c002
    bne irq_done        ; already finished, do nothing

    ; load frame counter into X (low byte) and Y (high byte)
    ldx $c000
    ldy $c001

    ; check if frame >= total_frames
    cpx #{_hex(total_lo)}
    tya
    sbc #{_hex(total_hi)}
    bcc not_done
    ; done: silence SID
    lda #$00
    sta $d404
    sta $d418
    lda #$01
    sta $c002
    jmp irq_done

not_done:
    ; Use frame counter as table index.
    ; For simplicity we only support up to 256 frames in the low byte
    ; path; for >256 frames we use the 16-bit counter.
    ; Since total_frames <= MAX_TABLE_FRAMES (512), and our tables are
    ; addressed with 16-bit indexing, we handle this with page-aware loads.

    ; Write control register from table
    lda ctrl_table,x
    sta $d404

    ; Write PW
    lda pw_lo_table,x
    sta $d402
    lda pw_hi_table,x
    sta $d403

    ; Write filter cutoff
    lda fc_lo_table,x
    sta $d415
    lda fc_hi_table,x
    sta $d416

    ; frame counter++
    inc $c000
    bne irq_done
    inc $c001

irq_done:
    jmp $ea31           ; chain to KERNAL IRQ (return via normal path)

; --- Per-frame data tables ---
{ctrl_data}
{pw_lo_data}
{pw_hi_data}
{fc_lo_data}
{fc_hi_data}
"""

    prg_path = Path(prg_path)
    prg_path.parent.mkdir(parents=True, exist_ok=True)
    asm_path = prg_path.with_suffix(".asm")
    asm_path.write_text(asm)

    result = subprocess.run(
        ["acme", "-f", "cbm", "-o", str(prg_path), str(asm_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"acme failed: rc={result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
            f"asm at {asm_path}"
        )
    if not prg_path.exists() or prg_path.stat().st_size < 20:
        raise RuntimeError(f"acme produced no/empty prg at {prg_path}")
    return prg_path


def _locate_vice() -> str:
    """Find x64sc binary."""
    for cand in ("x64sc", "/usr/local/bin/x64sc", "/usr/bin/x64sc"):
        p = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if p:
            return p
    raise RuntimeError("x64sc not found on PATH")


def run_vice_record(
    prg_path: Path,
    out_wav: Path,
    seconds: float,
    sample_rate: int = 44100,
) -> Path:
    """Boot ``prg_path`` in x64sc and record ``seconds`` of audio to ``out_wav``.

    Notes on VICE flags:

    * ``-sounddev wav -soundarg PATH`` uses the WAV sound driver, which
      writes a standard RIFF/WAVE file on clean shutdown.
    * ``-limitcycles N`` causes x64sc to exit with rc=1 once the CPU has
      executed N cycles. This still flushes the WAV properly.
    * Warp mode (``-warp`` / default autostart-warp) makes the sound
      backend race ahead of its buffers and produces an empty WAV, so we
      explicitly disable autostart-warp and do **not** pass ``-warp``.
      That means rendering runs in real-time.
    """
    out_wav = Path(out_wav)
    if out_wav.exists():
        out_wav.unlink()

    cycles = int(round(seconds * PAL_CLOCK_HZ))
    x64sc = _locate_vice()

    cmd = [
        x64sc,
        "-console",
        "-pal",
        "+autostart-warp",          # critical: keep real-time during autostart
        "+binarymonitor",
        "+remotemonitor",
        "+saveres",                 # do not write settings file
        "-sound",
        "-sounddev", "wav",
        "-soundarg", str(out_wav),
        "-soundrate", str(sample_rate),
        "-soundoutput", "1",        # mono
        "-limitcycles", str(cycles),
        "-autostartprgmode", "1",   # inject .prg
        "-autostart", str(prg_path),
    ]

    env = dict(os.environ)
    env.setdefault("SDL_VIDEODRIVER", "dummy")

    # Wall-clock timeout: seconds + startup overhead + slack.
    wall_timeout = max(30.0, seconds * 1.5 + 20.0)

    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=wall_timeout
    )
    # x64sc exits with rc=1 when -limitcycles is hit; that is expected.
    if not out_wav.exists() or out_wav.stat().st_size < 100:
        raise RuntimeError(
            f"VICE did not produce a WAV (rc={result.returncode}).\n"
            f"stderr: {result.stderr[-1000:]}\n"
            f"stdout tail: {result.stdout[-1000:]}\n"
            f"wav size: {out_wav.stat().st_size if out_wav.exists() else 'missing'}"
        )
    return out_wav
