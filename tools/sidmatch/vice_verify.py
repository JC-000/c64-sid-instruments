"""ACME-assembled tiny C64 driver + VICE invocation for SID rendering.

The generated .prg installs a 50Hz raster IRQ at $1000 that:

    1. writes all SID registers to produce the requested patch;
    2. counts PAL frames in a 16-bit counter at $C000/$C001;
    3. holds the gate bit on for the first ``gate_frames`` frames, then
       clears it for another ``release_frames`` frames; and
    4. after the note finishes, silences the SID and halts in a loop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .render import SidParams

from .render import PAL_CLOCK_HZ, hz_to_sid_freq, _waveform_mask  # noqa: E402

# Per-PAL-frame cycle budget: 63 cycles/line * 312 lines.
PAL_CYCLES_PER_FRAME = 63 * 312  # 19656


def _hex(v: int, width: int = 2) -> str:
    return f"${v:0{width}x}"


def build_prg(params: "SidParams", prg_path: Path) -> Path:
    """Assemble a tiny driver .prg for ``params``.

    The .prg autostarts via BASIC SYS and takes over IRQs.
    """
    freq_reg = hz_to_sid_freq(params.frequency, PAL_CLOCK_HZ)
    freq_lo = freq_reg & 0xFF
    freq_hi = (freq_reg >> 8) & 0xFF

    pw = params.pulse_width & 0x0FFF
    pw_lo = pw & 0xFF
    pw_hi = (pw >> 8) & 0x0F

    cutoff = params.filter_cutoff & 0x07FF
    fc_lo = cutoff & 0x07
    fc_hi = (cutoff >> 3) & 0xFF

    ad = params.ad_byte()
    sr = params.sr_byte()
    mode_vol = params.filter_mode_vol_byte()
    res_filt = params.filter_res_filt_byte()

    ctrl_on = params.control_byte(gate=True)
    ctrl_off = params.control_byte(gate=False)

    gate_frames = max(1, int(params.gate_frames))
    total_frames = max(gate_frames + 1, int(params.gate_frames + params.release_frames))

    gate_lo = gate_frames & 0xFF
    gate_hi = (gate_frames >> 8) & 0xFF
    total_lo = total_frames & 0xFF
    total_hi = (total_frames >> 8) & 0xFF

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
    lda #{_hex(pw_lo)}
    sta $d402
    lda #{_hex(pw_hi)}
    sta $d403
    lda #{_hex(ad)}
    sta $d405
    lda #{_hex(sr)}
    sta $d406
    lda #{_hex(fc_lo)}
    sta $d415
    lda #{_hex(fc_hi)}
    sta $d416
    lda #{_hex(res_filt)}
    sta $d417
    lda #{_hex(mode_vol)}
    sta $d418

    ; reset frame counter
    lda #$00
    sta $c000
    sta $c001
    sta $c002           ; phase: 0=gate-on, 1=gate-off, 2=done

    ; gate on
    lda #{_hex(ctrl_on)}
    sta $d404

    cli
    ; main loop - just spin
forever:
    jmp forever

irq:
    lda #$01
    sta $d019           ; ack raster IRQ

    lda $c002
    cmp #$02
    beq irq_done        ; already finished, do nothing

    ; frame counter++
    inc $c000
    bne +
    inc $c001
+

    ; if phase == 0 (gate-on), check for gate-off transition
    lda $c002
    bne check_off

    ; compare counter to gate_frames
    lda $c000
    cmp #{_hex(gate_lo)}
    lda $c001
    sbc #{_hex(gate_hi)}
    bcc irq_done        ; counter < gate_frames -> still gating
    ; gate-off
    lda #{_hex(ctrl_off)}
    sta $d404
    lda #$01
    sta $c002
    jmp irq_done

check_off:
    ; phase == 1: compare to total_frames
    lda $c000
    cmp #{_hex(total_lo)}
    lda $c001
    sbc #{_hex(total_hi)}
    bcc irq_done
    ; done: silence SID
    lda #$00
    sta $d404
    sta $d418
    lda #$02
    sta $c002

irq_done:
    jmp $ea31           ; chain to KERNAL IRQ (return via normal path)
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
