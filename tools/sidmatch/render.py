"""Rendering backends for SID instruments.

Two renderers are provided:

  * ``render_pyresid`` - fast in-process rendering via pyresidfp. Suitable for
    the inner optimization loop (thousands of candidates per instrument).
  * ``render_vice``    - ground-truth rendering via VICE's ``x64sc`` emulator.
    Slow (real-time) but authoritative.

Both backends take a :class:`SidParams` describing a single-voice patch and
return a mono WAV (as a numpy array or an on-disk .wav file respectively).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# SID PAL clock, cycles per second.
PAL_CLOCK_HZ = 985248.0
# PAL frame rate in Hz (50Hz -> 1 frame every 19656 cycles).
PAL_FRAME_HZ = 50.0
PAL_CYCLES_PER_FRAME = int(round(PAL_CLOCK_HZ / PAL_FRAME_HZ))

# Waveform bit masks in the SID voice control register.
WF_TRIANGLE = 0x10
WF_SAW = 0x20
WF_PULSE = 0x40
WF_NOISE = 0x80
WF_SYNC = 0x02
WF_RING_MOD = 0x04
WF_TEST = 0x08
WF_GATE = 0x01


def _waveform_mask(name: str) -> int:
    """Convert a human-friendly waveform string to a SID control-reg bitmask.

    Accepts single names (``"saw"``) or ``+``/``|`` combinations
    (``"triangle+pulse"``).
    """
    mask = 0
    if not name:
        return WF_SAW
    for part in name.replace("|", "+").split("+"):
        part = part.strip().lower()
        if part in ("tri", "triangle"):
            mask |= WF_TRIANGLE
        elif part in ("saw", "sawtooth"):
            mask |= WF_SAW
        elif part in ("pul", "pulse", "square"):
            mask |= WF_PULSE
        elif part in ("noise", "nse"):
            mask |= WF_NOISE
        elif part in ("", "off", "none"):
            pass
        else:
            raise ValueError(f"Unknown waveform name {part!r}")
    return mask


def _filter_mode_mask(mode: str) -> int:
    """Bitmask for D418 filter-mode nibble (upper bits)."""
    mode = (mode or "off").lower()
    if mode in ("off", "none", ""):
        # High-nibble bit 7 = voice 3 OFF; no filter bits set.
        return 0x00
    if mode == "lp":
        return 0x10
    if mode == "bp":
        return 0x20
    if mode == "hp":
        return 0x40
    raise ValueError(f"Unknown filter mode {mode!r}")


def hz_to_sid_freq(hz: float, clock: float = PAL_CLOCK_HZ) -> int:
    """Convert a frequency in Hz to the 16-bit SID frequency register value.

    ``F_out = (freq_reg * clock) / 2**24``, so
    ``freq_reg = round(hz * 2**24 / clock)``.
    """
    reg = int(round(hz * (1 << 24) / clock))
    return max(0, min(0xFFFF, reg))


@dataclass
class SidParams:
    """Parameters for a single SID voice patch.

    Only voice 1 is driven (voices 2 and 3 are silenced). The patch is played
    at a single pitch for ``gate_frames`` PAL frames, then released for
    ``release_frames`` more frames.

    Attributes:
        waveform: "triangle", "saw", "pulse", "noise" or a ``+``-joined
            combination (e.g. ``"triangle+pulse"``).
        attack, decay, sustain, release: standard SID ADSR nibbles (0-15).
        pulse_width: static pulse width 0-4095 (only meaningful for pulse
            waveforms). Ignored if ``pw_table`` is given.
        pw_table: optional list of ``(frame, pw_value)`` tuples; the pulse
            width is updated on those frames.
        filter_cutoff: 11-bit filter cutoff 0-2047.
        filter_resonance: 0-15.
        filter_mode: "lp", "bp", "hp" or "off".
        filter_voice1: route voice 1 through the filter.
        ring_mod: enable ring modulation with voice 3.
        sync: hard-sync voice 1 to voice 3.
        frequency: note pitch in Hz (converted to SID freq register).
        gate_frames: frames to hold gate on (50Hz PAL).
        release_frames: frames after gate-off to keep capturing.
        wavetable: optional list of ``(frame, waveform_byte)`` overrides that
            replace the control-register waveform bits on specific frames
            (the GATE bit is preserved).
        volume: master volume 0-15.
    """

    waveform: str = "saw"
    attack: int = 0
    decay: int = 9
    sustain: int = 8
    release: int = 4
    pulse_width: int = 2048
    pw_table: Optional[List[Tuple[int, int]]] = None
    filter_cutoff: int = 1024
    filter_resonance: int = 0
    filter_mode: str = "off"
    filter_voice1: bool = False
    ring_mod: bool = False
    sync: bool = False
    frequency: float = 440.0
    gate_frames: int = 50  # 1 second at 50Hz PAL
    release_frames: int = 25
    wavetable: Optional[List[Tuple[int, int]]] = None
    volume: int = 15

    # ---- derived helpers ----

    def control_byte(self, gate: bool = True) -> int:
        wf = _waveform_mask(self.waveform)
        cb = wf
        if self.ring_mod:
            cb |= WF_RING_MOD
        if self.sync:
            cb |= WF_SYNC
        if gate:
            cb |= WF_GATE
        return cb & 0xFF

    def ad_byte(self) -> int:
        return ((self.attack & 0x0F) << 4) | (self.decay & 0x0F)

    def sr_byte(self) -> int:
        return ((self.sustain & 0x0F) << 4) | (self.release & 0x0F)

    def filter_mode_vol_byte(self) -> int:
        return (_filter_mode_mask(self.filter_mode) | (self.volume & 0x0F)) & 0xFF

    def filter_res_filt_byte(self) -> int:
        # bit0 = filter voice 1; high nibble = resonance.
        v = ((self.filter_resonance & 0x0F) << 4)
        if self.filter_voice1:
            v |= 0x01
        return v & 0xFF

    def total_frames(self) -> int:
        return int(self.gate_frames + self.release_frames)


# ---------------------------------------------------------------------------
# pyresidfp backend
# ---------------------------------------------------------------------------


def render_pyresid(
    params: SidParams, sample_rate: int = 44100
) -> np.ndarray:
    """Render ``params`` with pyresidfp.

    Returns a mono float32 numpy array in ``[-1, 1]``.
    """
    # Local import so that test collection works without pyresidfp.
    from pyresidfp import SoundInterfaceDevice, WritableRegister  # type: ignore

    sid = SoundInterfaceDevice(
        sampling_frequency=sample_rate,
        clock_frequency=PAL_CLOCK_HZ,
    )
    sid.reset()

    freq_reg = hz_to_sid_freq(params.frequency, PAL_CLOCK_HZ)
    pw = params.pulse_width & 0x0FFF
    cutoff = params.filter_cutoff & 0x07FF

    # Master volume / filter mode
    sid.write_register(
        WritableRegister.Filter_Mode_Vol, params.filter_mode_vol_byte()
    )
    sid.write_register(
        WritableRegister.Filter_Res_Filt, params.filter_res_filt_byte()
    )
    # Filter cutoff: lo=3 bits, hi=8 bits (total 11 bits).
    sid.write_register(WritableRegister.Filter_Fc_Lo, cutoff & 0x07)
    sid.write_register(WritableRegister.Filter_Fc_Hi, (cutoff >> 3) & 0xFF)

    # Voice 1 frequency
    sid.write_register(WritableRegister.Voice1_Freq_Lo, freq_reg & 0xFF)
    sid.write_register(WritableRegister.Voice1_Freq_Hi, (freq_reg >> 8) & 0xFF)
    # Voice 1 pulse width
    sid.write_register(WritableRegister.Voice1_Pw_Lo, pw & 0xFF)
    sid.write_register(WritableRegister.Voice1_Pw_Hi, (pw >> 8) & 0x0F)
    # ADSR
    sid.write_register(WritableRegister.Voice1_Attack_Decay, params.ad_byte())
    sid.write_register(
        WritableRegister.Voice1_Sustain_Release, params.sr_byte()
    )

    # Build per-frame schedule of waveform/pw updates.
    pw_lookup = dict(params.pw_table or [])
    wt_lookup = dict(params.wavetable or [])

    samples: List[int] = []
    frame_dur = timedelta(seconds=1.0 / PAL_FRAME_HZ)

    base_wf = _waveform_mask(params.waveform)

    def wf_for_frame(f: int, gate: bool) -> int:
        wf = wt_lookup.get(f, base_wf)
        cb = wf
        if params.ring_mod:
            cb |= WF_RING_MOD
        if params.sync:
            cb |= WF_SYNC
        if gate:
            cb |= WF_GATE
        return cb & 0xFF

    # Gate ON
    sid.write_register(
        WritableRegister.Voice1_Control_Reg, wf_for_frame(0, True)
    )

    for f in range(params.gate_frames):
        if f in pw_lookup:
            new_pw = pw_lookup[f] & 0x0FFF
            sid.write_register(WritableRegister.Voice1_Pw_Lo, new_pw & 0xFF)
            sid.write_register(
                WritableRegister.Voice1_Pw_Hi, (new_pw >> 8) & 0x0F
            )
        if f in wt_lookup or f == 0:
            sid.write_register(
                WritableRegister.Voice1_Control_Reg, wf_for_frame(f, True)
            )
        chunk = sid.clock(frame_dur)
        samples.extend(chunk)

    # Gate OFF
    sid.write_register(
        WritableRegister.Voice1_Control_Reg, wf_for_frame(params.gate_frames, False)
    )
    for f in range(params.release_frames):
        chunk = sid.clock(frame_dur)
        samples.extend(chunk)

    audio = np.asarray(samples, dtype=np.int32).astype(np.float32) / 32768.0
    # Clip to [-1, 1] just in case.
    audio = np.clip(audio, -1.0, 1.0)
    return audio


# ---------------------------------------------------------------------------
# VICE backend
# ---------------------------------------------------------------------------


def render_vice(
    params: SidParams, out_wav: Path, sample_rate: int = 44100
) -> Path:
    """Render ``params`` via VICE's ``x64sc`` and write to ``out_wav``.

    Builds a tiny .prg that writes the desired SID register sequence to
    $D400-$D418 on each PAL IRQ, then boots VICE headlessly with the WAV
    sound driver to capture the audio to disk.
    """
    from .vice_verify import build_prg, run_vice_record

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    prg_path = out_wav.with_suffix(".prg")
    build_prg(params, prg_path)

    # Seconds of real-time emulation required. Autostart boot takes ~2.5s;
    # the note itself runs for (gate+release) frames at 50Hz. We add a
    # generous margin to ensure VICE captures the entire envelope.
    boot_pad = 3.0
    note_seconds = params.total_frames() / PAL_FRAME_HZ
    seconds = boot_pad + note_seconds + 1.0

    run_vice_record(prg_path, out_wav, seconds, sample_rate=sample_rate)
    return out_wav
