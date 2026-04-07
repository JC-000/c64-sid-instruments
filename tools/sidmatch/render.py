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

# Cache for SID emulator instances, keyed by (sample_rate, chip_model_str).
_SID_CACHE: dict = {}

# ---------------------------------------------------------------------------
# SID ADSR timing tables (hardware-defined, in milliseconds)
# ---------------------------------------------------------------------------
ATTACK_MS = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
DECAY_RELEASE_MS = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]


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


def compute_gate_release(attack: int, decay: int, sustain: int, release: int) -> Tuple[int, int]:
    """Compute gate_frames and release_frames so full ADSR plays out.

    Uses the hardware ADSR timing tables. Returns (gate_frames, release_frames)
    in PAL frames (50 Hz).
    """
    attack_ms = ATTACK_MS[max(0, min(15, attack))]
    decay_ms = DECAY_RELEASE_MS[max(0, min(15, decay))]
    release_ms = DECAY_RELEASE_MS[max(0, min(15, release))]

    # Gate must cover attack + enough decay to reach sustain level.
    # If sustain == 15, decay is skipped (already at peak = sustain),
    # but we still need enough gate time for the sound to ring so that
    # feature extraction can meaningfully compare against the reference.
    # Use attack + decay_ms as the minimum even at S=15, so the gate
    # duration is consistent and never collapses to a tiny value.
    gate_ms = attack_ms + decay_ms

    gate_frames = max(10, min(200, int(gate_ms / 20) + 5))  # PAL frames, with margin

    # Release: let it play out, but cap at 5 seconds (250 frames).
    release_frames = max(10, min(250, int(release_ms / 20) + 5))

    return gate_frames, release_frames


@dataclass
class SidParams:
    """Parameters for a single SID voice patch.

    Only voice 1 is driven (voices 2 and 3 are silenced). The patch is played
    at a single pitch for ``gate_frames`` PAL frames, then released for
    ``release_frames`` more frames.

    Attributes:
        waveform: "triangle", "saw", "pulse", "noise" or a ``+``-joined
            combination (e.g. ``"triangle+pulse"``). Also serves as alias
            for sustain waveform in simple patches.
        attack, decay, sustain, release: standard SID ADSR nibbles (0-15).
        pulse_width: static pulse width 0-4095 (only meaningful for pulse
            waveforms). Ignored if pw_start/pw_delta are used.
        pw_table: optional list of ``(frame, pw_value)`` tuples; legacy
            support. Superseded by pw_start/pw_delta/pw_min/pw_max/pw_mode.

        -- Wavetable sequence --
        wt_attack_frames: number of frames the attack waveform plays (1-5).
        wt_attack_waveform: waveform for attack phase ("noise", "pulse+saw",
            etc.). Empty or None means same as waveform/sustain.
        wt_sustain_waveform: waveform for sustain phase. Empty or None
            means same as waveform.
        wt_use_test_bit: whether frame 0 uses test bit ($08) to reset
            oscillator phase.

        -- PW sweep --
        pw_start: starting pulse width (0-4095).
        pw_delta: change per frame (positive=sweep up, negative=down, 0=static).
        pw_min: lower bound for ping-pong (0-4095).
        pw_max: upper bound for ping-pong (0-4095).
        pw_mode: "sweep" or "pingpong".

        -- Filter sweep --
        filter_cutoff_start: starting filter cutoff (0-2047).
        filter_cutoff_end: sweep target (0-2047).
        filter_sweep_frames: how many frames to reach end (0=static).

        filter_cutoff: legacy static cutoff (0-2047). Used if
            filter_cutoff_start is None.
        filter_resonance: 0-15.
        filter_mode: "lp", "bp", "hp" or "off".
        filter_voice1: route voice 1 through the filter.
        ring_mod: enable ring modulation with voice 3.
        sync: hard-sync voice 1 to voice 3.
        frequency: note pitch in Hz (converted to SID freq register).
        gate_frames: frames to hold gate on (50Hz PAL).
        release_frames: frames after gate-off to keep capturing.
        wavetable: optional list of ``(frame, waveform_byte)`` overrides
            (legacy). Superseded by wt_attack_waveform/wt_sustain_waveform.
        volume: master volume 0-15.
        chip_model: target SID chip model, ``"6581"`` or ``"8580"``.
            ``None`` means unspecified (pyresidfp defaults to MOS6581).
        source_instrument: free-text description of the reference recording
            used during optimization.
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
    chip_model: Optional[str] = None
    source_instrument: Optional[str] = None

    # -- Wavetable sequence --
    wt_attack_frames: int = 1
    wt_attack_waveform: Optional[str] = None
    wt_sustain_waveform: Optional[str] = None
    wt_use_test_bit: bool = False

    # -- PW sweep --
    pw_start: Optional[int] = None
    pw_delta: int = 0
    pw_min: int = 0
    pw_max: int = 4095
    pw_mode: str = "sweep"

    # -- Filter sweep --
    filter_cutoff_start: Optional[int] = None
    filter_cutoff_end: Optional[int] = None
    filter_sweep_frames: int = 0

    # ---- derived helpers ----

    def effective_sustain_waveform(self) -> str:
        """Return the sustain waveform name."""
        return self.wt_sustain_waveform or self.waveform or "saw"

    def effective_attack_waveform(self) -> str:
        """Return the attack waveform name."""
        return self.wt_attack_waveform or self.effective_sustain_waveform()

    def effective_pw_start(self) -> int:
        """Return the effective starting pulse width."""
        if self.pw_start is not None:
            return self.pw_start & 0x0FFF
        return self.pulse_width & 0x0FFF

    def effective_filter_cutoff_start(self) -> int:
        """Return the effective starting filter cutoff."""
        if self.filter_cutoff_start is not None:
            return self.filter_cutoff_start & 0x07FF
        return self.filter_cutoff & 0x07FF

    def effective_filter_cutoff_end(self) -> int:
        """Return the effective ending filter cutoff."""
        if self.filter_cutoff_end is not None:
            return self.filter_cutoff_end & 0x07FF
        return self.effective_filter_cutoff_start()

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


def _compute_pw_for_frame(frame: int, pw_start: int, pw_delta: int,
                          pw_min: int, pw_max: int, mode: str) -> int:
    """Compute pulse width for a given frame according to sweep parameters."""
    if pw_delta == 0:
        return max(pw_min, min(pw_max, pw_start))

    if mode == "pingpong":
        # ping-pong: sweep back and forth between pw_min and pw_max
        span = max(1, pw_max - pw_min)
        raw_offset = abs(pw_delta) * frame
        # how many half-cycles
        phase = raw_offset % (2 * span)
        if phase <= span:
            val = pw_start + (pw_delta // abs(pw_delta)) * phase if pw_delta != 0 else pw_start
        else:
            val = pw_start + (pw_delta // abs(pw_delta)) * (2 * span - phase) if pw_delta != 0 else pw_start
        # Simple approach: linear sweep with reflection at boundaries
        pw = pw_start + pw_delta * frame
        # reflect at boundaries
        while True:
            if pw > pw_max:
                pw = 2 * pw_max - pw
                pw_delta = -pw_delta
            elif pw < pw_min:
                pw = 2 * pw_min - pw
                pw_delta = -pw_delta
            else:
                break
            # safety valve
            if abs(pw - pw_start) > 2 * (pw_max - pw_min + 1):
                pw = max(pw_min, min(pw_max, pw))
                break
        return max(0, min(4095, pw))
    else:
        # simple sweep: clamp at boundaries
        pw = pw_start + pw_delta * frame
        return max(pw_min, min(pw_max, max(0, min(4095, pw))))


def _compute_filter_cutoff_for_frame(frame: int, cutoff_start: int,
                                     cutoff_end: int, sweep_frames: int) -> int:
    """Compute filter cutoff for a given frame according to sweep parameters."""
    if sweep_frames <= 0 or cutoff_start == cutoff_end:
        return cutoff_start
    if frame >= sweep_frames:
        return cutoff_end
    # linear interpolation
    frac = frame / sweep_frames
    val = cutoff_start + frac * (cutoff_end - cutoff_start)
    return max(0, min(2047, int(round(val))))


# ---------------------------------------------------------------------------
# pyresidfp backend
# ---------------------------------------------------------------------------


def _resolve_chip_model(chip_model: Optional[str] = None):
    """Return a pyresidfp ``ChipModel`` enum value.

    Accepts ``"6581"`` or ``"8580"`` (strings). ``None`` leaves pyresidfp's
    default (MOS6581).
    """
    if chip_model is None:
        return None
    from pyresidfp._pyresidfp import ChipModel  # type: ignore

    chip_model = str(chip_model).strip()
    if chip_model in ("6581", "MOS6581"):
        return ChipModel.MOS6581
    if chip_model in ("8580", "MOS8580"):
        return ChipModel.MOS8580
    raise ValueError(
        f"Unknown chip_model {chip_model!r}; expected '6581' or '8580'"
    )


def _get_sid(sample_rate: int, chip_model: Optional[str] = None):
    """Get a cached SID instance, or create one. Reuses via reset()."""
    from pyresidfp import SoundInterfaceDevice

    key = (sample_rate, chip_model)
    if key in _SID_CACHE:
        sid = _SID_CACHE[key]
        sid.reset()
        return sid

    model = _resolve_chip_model(chip_model)
    kw: dict = dict(
        sampling_frequency=sample_rate,
        clock_frequency=PAL_CLOCK_HZ,
    )
    if model is not None:
        kw["model"] = model
    sid = SoundInterfaceDevice(**kw)
    sid.reset()
    _SID_CACHE[key] = sid
    return sid


def render_pyresid(
    params: SidParams, sample_rate: int = 44100, chip_model: Optional[str] = None,
) -> np.ndarray:
    """Render ``params`` with pyresidfp.

    Implements tracker-style per-frame wavetable sequence, PW sweep, and
    filter sweep.  The rendering sequence is:

    1. Frame 0: if wt_use_test_bit, write test bit ($08, no gate) to reset
       oscillator phase.
    2. Frame 1..wt_attack_frames: write attack waveform + gate.
    3. Frame wt_attack_frames+1 onward: write sustain waveform + gate.
    4. Each frame: update PW register according to PW sweep params.
    5. Each frame: update filter cutoff according to filter sweep params.
    6. At gate_frames: gate off (clear gate bit, keep waveform).
    7. Continue for release_frames more frames.

    Returns a mono float32 numpy array in ``[-1, 1]``.
    """
    # Local import so that test collection works without pyresidfp.
    from pyresidfp import WritableRegister  # type: ignore

    sid = _get_sid(sample_rate, chip_model)

    freq_reg = hz_to_sid_freq(params.frequency, PAL_CLOCK_HZ)

    # Effective PW and filter parameters
    pw_start = params.effective_pw_start()
    pw_delta = params.pw_delta
    pw_min = params.pw_min
    pw_max = params.pw_max
    pw_mode = params.pw_mode or "sweep"

    cutoff_start = params.effective_filter_cutoff_start()
    cutoff_end = params.effective_filter_cutoff_end()
    sweep_frames = params.filter_sweep_frames

    # Waveform masks
    sustain_wf = _waveform_mask(params.effective_sustain_waveform())
    attack_wf = _waveform_mask(params.effective_attack_waveform())
    wt_attack_frames = max(1, params.wt_attack_frames)

    # Legacy wavetable/pw_table support
    legacy_wt = dict(params.wavetable or [])
    legacy_pw = dict(params.pw_table or [])
    use_legacy_wt = bool(params.wavetable) and not params.wt_attack_waveform
    use_legacy_pw = bool(params.pw_table) and params.pw_start is None

    # Master volume / filter mode
    sid.write_register(
        WritableRegister.Filter_Mode_Vol, params.filter_mode_vol_byte()
    )
    sid.write_register(
        WritableRegister.Filter_Res_Filt, params.filter_res_filt_byte()
    )
    # Initial filter cutoff
    cutoff = cutoff_start & 0x07FF
    sid.write_register(WritableRegister.Filter_Fc_Lo, cutoff & 0x07)
    sid.write_register(WritableRegister.Filter_Fc_Hi, (cutoff >> 3) & 0xFF)

    # Voice 1 frequency
    sid.write_register(WritableRegister.Voice1_Freq_Lo, freq_reg & 0xFF)
    sid.write_register(WritableRegister.Voice1_Freq_Hi, (freq_reg >> 8) & 0xFF)
    # Voice 1 initial pulse width
    pw = pw_start & 0x0FFF
    sid.write_register(WritableRegister.Voice1_Pw_Lo, pw & 0xFF)
    sid.write_register(WritableRegister.Voice1_Pw_Hi, (pw >> 8) & 0x0F)
    # ADSR
    sid.write_register(WritableRegister.Voice1_Attack_Decay, params.ad_byte())
    sid.write_register(
        WritableRegister.Voice1_Sustain_Release, params.sr_byte()
    )

    frame_dur = timedelta(seconds=1.0 / PAL_FRAME_HZ)

    # Pre-roll: clock 1 frame with volume/filter set but no gate to absorb
    # the SID volume register click. Writing $D418 after reset causes a DC
    # transient in the 6581 DAC (the 4-bit volume feeds through directly).
    # This pre-roll lets that transient settle before real audio starts.
    sid.clock(frame_dur)

    samples: List[int] = []

    def _build_control(wf_mask: int, gate: bool) -> int:
        cb = wf_mask
        if params.ring_mod:
            cb |= WF_RING_MOD
        if params.sync:
            cb |= WF_SYNC
        if gate:
            cb |= WF_GATE
        return cb & 0xFF

    def _wf_for_frame_legacy(f: int, gate: bool) -> int:
        wf = legacy_wt.get(f, _waveform_mask(params.waveform))
        return _build_control(wf, gate)

    def _wf_for_frame(f: int, gate: bool) -> int:
        """Determine waveform control byte for frame f using wavetable sequence."""
        if use_legacy_wt:
            return _wf_for_frame_legacy(f, gate)

        if params.wt_use_test_bit and f == 0:
            # Test bit: $08, no gate (resets oscillator phase)
            return WF_TEST
        if f <= wt_attack_frames:
            return _build_control(attack_wf, gate)
        return _build_control(sustain_wf, gate)

    # --- Gate ON phase ---
    for f in range(params.gate_frames):
        # Update waveform
        ctrl = _wf_for_frame(f, gate=True)
        sid.write_register(WritableRegister.Voice1_Control_Reg, ctrl)

        # Update PW
        if use_legacy_pw:
            if f in legacy_pw:
                new_pw = legacy_pw[f] & 0x0FFF
                sid.write_register(WritableRegister.Voice1_Pw_Lo, new_pw & 0xFF)
                sid.write_register(
                    WritableRegister.Voice1_Pw_Hi, (new_pw >> 8) & 0x0F
                )
        else:
            new_pw = _compute_pw_for_frame(f, pw_start, pw_delta, pw_min, pw_max, pw_mode)
            sid.write_register(WritableRegister.Voice1_Pw_Lo, new_pw & 0xFF)
            sid.write_register(
                WritableRegister.Voice1_Pw_Hi, (new_pw >> 8) & 0x0F
            )

        # Update filter cutoff
        new_cutoff = _compute_filter_cutoff_for_frame(f, cutoff_start, cutoff_end, sweep_frames)
        sid.write_register(WritableRegister.Filter_Fc_Lo, new_cutoff & 0x07)
        sid.write_register(WritableRegister.Filter_Fc_Hi, (new_cutoff >> 3) & 0xFF)

        chunk = sid.clock(frame_dur)
        samples.extend(chunk)

    # --- Gate OFF phase ---
    gate_off_wf = sustain_wf if not use_legacy_wt else _waveform_mask(params.waveform)
    gate_off_ctrl = _build_control(gate_off_wf, gate=False)
    sid.write_register(WritableRegister.Voice1_Control_Reg, gate_off_ctrl)

    for f in range(params.release_frames):
        # Continue PW and filter sweeps during release
        abs_frame = params.gate_frames + f
        if not use_legacy_pw:
            new_pw = _compute_pw_for_frame(abs_frame, pw_start, pw_delta, pw_min, pw_max, pw_mode)
            sid.write_register(WritableRegister.Voice1_Pw_Lo, new_pw & 0xFF)
            sid.write_register(
                WritableRegister.Voice1_Pw_Hi, (new_pw >> 8) & 0x0F
            )
        new_cutoff = _compute_filter_cutoff_for_frame(abs_frame, cutoff_start, cutoff_end, sweep_frames)
        sid.write_register(WritableRegister.Filter_Fc_Lo, new_cutoff & 0x07)
        sid.write_register(WritableRegister.Filter_Fc_Hi, (new_cutoff >> 3) & 0xFF)

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

    Uses the c64-test-harness ``render_wav`` function for VICE lifecycle
    management instead of raw subprocess calls.
    """
    from c64_test_harness import render_wav

    from .vice_verify import build_prg

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

    render_wav(
        prg_path=str(prg_path),
        out_wav=str(out_wav),
        duration_seconds=seconds,
        sample_rate=sample_rate,
    )
    return out_wav
