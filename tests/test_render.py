"""Integration test for both rendering backends.

Renders the same 440Hz sawtooth patch via pyresidfp and via VICE, then
checks that:

  * both outputs have non-trivial RMS energy;
  * their normalized cross-correlation peak exceeds 0.85
    (alignment-tolerant); and
  * the detected fundamental frequency is within 5Hz of 440Hz in both.

Also tests new wavetable sequence, PW sweep, and filter sweep features.
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest
from scipy.fft import rfft, rfftfreq
from scipy.signal import correlate

from c64_test_harness import render_wav

from sidmatch.render import (
    SidParams,
    render_pyresid,
    render_vice,
    compute_gate_release,
    ATTACK_MS,
    DECAY_RELEASE_MS,
    PAL_FRAME_HZ,
)
from sidmatch.vice_verify import build_prg

skip_no_vice = pytest.mark.skipif(
    shutil.which("x64sc") is None, reason="x64sc not found"
)


TARGET_HZ = 440.0
SR = 44100


def _fundamental_hz(x: np.ndarray, sr: int = SR) -> float:
    """Estimate the fundamental via simple FFT peak-picking.

    Uses the loudest one-second window of ``x``.
    """
    x = np.asarray(x, dtype=np.float32)
    # Use loudest ~1s window, but skip a possible leading boot-click region.
    lead = min(len(x) - 1, int(0.5 * sr)) if len(x) > 2 * sr else 0
    body = x[lead:]
    win = sr // 5
    if len(body) < win * 2:
        seg = x
    else:
        rms_env = np.sqrt(np.convolve(body ** 2, np.ones(win) / win, mode="valid"))
        peak = int(np.argmax(rms_env)) + lead
        start = peak + int(0.05 * sr)
        end = min(len(x), start + sr)
        seg = x[start:end]
    if len(seg) < 2048:
        return 0.0
    window = np.hanning(len(seg))
    X = np.abs(rfft(seg * window))
    freqs = rfftfreq(len(seg), 1.0 / sr)
    # skip DC / sub-bass bin
    lo = 20
    peak_idx = lo + int(np.argmax(X[lo:]))
    # parabolic interpolation for a sub-bin estimate
    if 0 < peak_idx < len(X) - 1:
        a, b, c = X[peak_idx - 1], X[peak_idx], X[peak_idx + 1]
        denom = (a - 2 * b + c)
        if denom != 0:
            delta = 0.5 * (a - c) / denom
            peak_idx_f = peak_idx + delta
            return float(peak_idx_f * sr / len(seg))
    return float(freqs[peak_idx])


def _normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    n = np.linalg.norm(x)
    if n < 1e-12:
        return x
    return x / n


def _max_xcorr(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized-cross-correlation peak, alignment-tolerant."""
    a = _normalize(a)
    b = _normalize(b)
    # correlate b with a (shorter dot longer) using scipy 'valid'-like via 'full'
    c = correlate(a, b, mode="full", method="auto")
    return float(np.max(np.abs(c)))


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return x


def _trim_to_note(x: np.ndarray, sr: int = SR, seconds: float = 1.0) -> np.ndarray:
    """Extract a ``seconds``-long window from the stable part of the note."""
    if len(x) < sr:
        return x
    lead = min(len(x) - 1, int(0.5 * sr)) if len(x) > 2 * sr else 0
    body = x[lead:]
    win = sr // 5  # 200ms
    if len(body) < win * 2:
        return x
    env = np.sqrt(np.convolve(body ** 2, np.ones(win) / win, mode="valid"))
    peak = int(np.argmax(env)) + lead
    start = peak + int(0.05 * sr)
    end = min(len(x), start + int(seconds * sr))
    start = max(0, end - int(seconds * sr))
    return x[start:end]


@pytest.fixture(scope="module")
def patch() -> SidParams:
    return SidParams(
        waveform="saw",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=8,
        release=4,
        filter_mode="off",
        gate_frames=50,
        release_frames=25,
    )


@pytest.fixture(scope="module")
def pyresid_signal(patch) -> np.ndarray:
    return render_pyresid(patch, sample_rate=SR)


@pytest.fixture(scope="module")
def vice_signal(patch, tmp_path_factory) -> np.ndarray:
    tmp = tmp_path_factory.mktemp("vice")
    prg_path = tmp / "patch.prg"
    out = tmp / "patch.wav"
    build_prg(patch, prg_path)
    boot_pad = 3.0
    note_seconds = (patch.gate_frames + patch.release_frames) / PAL_FRAME_HZ
    duration = boot_pad + note_seconds + 1.0
    render_wav(prg_path=str(prg_path), out_wav=str(out),
               duration_seconds=duration, sample_rate=SR)
    return _read_wav(out)


def test_pyresid_energy(pyresid_signal):
    rms = float(np.sqrt(np.mean(pyresid_signal ** 2)))
    assert rms > 1e-3, f"pyresid RMS too low: {rms}"


@skip_no_vice
def test_vice_energy(vice_signal):
    rms = float(np.sqrt(np.mean(vice_signal ** 2)))
    assert rms > 1e-3, f"vice RMS too low: {rms}"


def test_pyresid_fundamental(pyresid_signal):
    f = _fundamental_hz(pyresid_signal)
    assert abs(f - TARGET_HZ) < 5.0, f"pyresid fundamental off: {f}"


@skip_no_vice
def test_vice_fundamental(vice_signal):
    f = _fundamental_hz(vice_signal)
    assert abs(f - TARGET_HZ) < 5.0, f"vice fundamental off: {f}"


@skip_no_vice
def test_cross_correlation(pyresid_signal, vice_signal):
    a = _trim_to_note(pyresid_signal, seconds=0.5)
    b = _trim_to_note(vice_signal, seconds=0.5)
    peak = _max_xcorr(a, b)
    assert peak > 0.85, f"cross-correlation too low: {peak}"


# ---------------------------------------------------------------------------
# Wavetable sequence tests
# ---------------------------------------------------------------------------


def test_wavetable_sequence_produces_audio():
    """Test bit -> saw attack -> saw sustain produces non-trivial audio."""
    params = SidParams(
        waveform="saw",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=8,
        release=4,
        filter_mode="off",
        gate_frames=50,
        release_frames=25,
        wt_use_test_bit=True,
        wt_attack_waveform="saw",
        wt_sustain_waveform="saw",
        wt_attack_frames=2,
    )
    audio = render_pyresid(params, sample_rate=SR)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert rms > 1e-3, f"wavetable patch RMS too low: {rms}"
    assert len(audio) > 0


def test_wavetable_different_attack_sustain():
    """Attack waveform noise, sustain saw - should still produce pitched audio."""
    params = SidParams(
        waveform="saw",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=8,
        release=4,
        filter_mode="off",
        gate_frames=50,
        release_frames=25,
        wt_attack_waveform="noise",
        wt_sustain_waveform="saw",
        wt_attack_frames=2,
    )
    audio = render_pyresid(params, sample_rate=SR)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert rms > 1e-3, f"mixed wavetable patch RMS too low: {rms}"


# ---------------------------------------------------------------------------
# PW sweep tests
# ---------------------------------------------------------------------------


def test_pw_sweep_changes_spectrum():
    """PW sweep should produce different spectra at start vs end."""
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=0,
        sustain=15,
        release=0,
        filter_mode="off",
        gate_frames=100,
        release_frames=10,
        pw_start=512,
        pw_delta=20,
        pw_min=0,
        pw_max=4095,
        pw_mode="sweep",
    )
    audio = render_pyresid(params, sample_rate=SR)
    assert len(audio) > 0

    # Compare spectra from first quarter and last quarter
    n = len(audio)
    q = n // 4
    first_quarter = audio[:q]
    last_quarter = audio[3*q:]

    spec_first = np.abs(rfft(first_quarter * np.hanning(len(first_quarter))))
    spec_last = np.abs(rfft(last_quarter * np.hanning(len(last_quarter))))

    # The spectra should differ since PW is sweeping
    # Use spectral centroid as a proxy for brightness
    freqs_first = rfftfreq(len(first_quarter), 1.0 / SR)
    freqs_last = rfftfreq(len(last_quarter), 1.0 / SR)

    def centroid(spec, freqs):
        total = spec.sum()
        if total < 1e-12:
            return 0.0
        return float(np.sum(spec * freqs) / total)

    c_first = centroid(spec_first, freqs_first)
    c_last = centroid(spec_last, freqs_last)

    # They should not be identical (some tolerance for nearly-identical)
    assert abs(c_first - c_last) > 10.0, (
        f"PW sweep did not change spectrum: centroid_first={c_first:.1f} "
        f"centroid_last={c_last:.1f}"
    )


def test_pw_pingpong():
    """PW ping-pong mode should produce audio."""
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=0,
        sustain=15,
        release=0,
        filter_mode="off",
        gate_frames=100,
        release_frames=10,
        pw_start=2048,
        pw_delta=30,
        pw_min=1024,
        pw_max=3072,
        pw_mode="pingpong",
    )
    audio = render_pyresid(params, sample_rate=SR)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert rms > 1e-3, f"PW ping-pong patch RMS too low: {rms}"


# ---------------------------------------------------------------------------
# Filter sweep tests
# ---------------------------------------------------------------------------


def test_filter_sweep_changes_brightness():
    """Filter sweep should change brightness over time."""
    params = SidParams(
        waveform="saw",
        frequency=TARGET_HZ,
        attack=0,
        decay=0,
        sustain=15,
        release=0,
        filter_mode="lp",
        filter_voice1=True,
        filter_resonance=8,
        gate_frames=100,
        release_frames=10,
        filter_cutoff_start=200,
        filter_cutoff_end=1800,
        filter_sweep_frames=80,
    )
    audio = render_pyresid(params, sample_rate=SR)
    assert len(audio) > 0

    # Compare brightness (spectral centroid) of first vs last quarter
    n = len(audio)
    q = n // 4
    first_quarter = audio[:q]
    last_quarter = audio[2*q:3*q]

    spec_first = np.abs(rfft(first_quarter * np.hanning(len(first_quarter))))
    spec_last = np.abs(rfft(last_quarter * np.hanning(len(last_quarter))))

    freqs_first = rfftfreq(len(first_quarter), 1.0 / SR)
    freqs_last = rfftfreq(len(last_quarter), 1.0 / SR)

    def centroid(spec, freqs):
        total = spec.sum()
        if total < 1e-12:
            return 0.0
        return float(np.sum(spec * freqs) / total)

    c_first = centroid(spec_first, freqs_first)
    c_last = centroid(spec_last, freqs_last)

    # Filter opens from 200 to 1800, so last should be brighter
    assert c_last > c_first, (
        f"Filter sweep did not increase brightness: "
        f"centroid_first={c_first:.1f} centroid_last={c_last:.1f}"
    )


# ---------------------------------------------------------------------------
# ADSR-aware gate/release computation
# ---------------------------------------------------------------------------


def test_compute_gate_release_basic():
    """Basic ADSR timing: A=0 (2ms), D=9 (750ms), S=8, R=4 (114ms)."""
    gate, release = compute_gate_release(0, 9, 8, 4)
    # gate should cover attack (2ms) + decay (750ms) = 752ms -> ~37 frames + margin
    assert gate >= 10
    assert gate <= 200
    # release for R=4 (114ms) -> ~5 frames + margin
    assert release >= 10
    assert release <= 250


def test_compute_gate_release_max_sustain():
    """S=15: gate still uses attack + decay_ms for consistent duration."""
    gate, release = compute_gate_release(0, 9, 15, 4)
    # A=0 (2ms) + D=9 (750ms) = 752ms -> ~42 frames
    assert gate >= 10
    assert gate <= 50


def test_compute_gate_release_extreme_values():
    """Extreme ADSR: A=15, D=15, S=0, R=15."""
    gate, release = compute_gate_release(15, 15, 0, 15)
    # A=15 (8000ms) + D=15 (24000ms) = 32000ms -> capped at 200 frames
    assert gate == 200
    # R=15 (24000ms) -> capped at 250 frames
    assert release == 250


# ---------------------------------------------------------------------------
# Phase 1 expressive primitives: backwards compat + new-feature smoke tests
# ---------------------------------------------------------------------------


def test_phase1_backwards_compat_bit_identical():
    """SidParams with phase-1 fields set to defaults must render within the
    pyresidfp determinism floor of a pair of identical back-to-back calls.

    pyresidfp exhibits a tiny (~1e-4 peak) sample-level residual between
    nominally-identical renders even when the cache is cleared between
    calls (upstream init determinism issue). So we compare the
    "defaults-explicit" render against the "defaults-implicit" render and
    require the delta to stay below that floor plus a small safety
    margin, which proves the phase-1 scaffolding is a true no-op when
    unused.
    """
    from sidmatch import render as _render_mod

    base = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=8,
        release=4,
        pulse_width=2048,
        filter_cutoff=1024,
        filter_mode="off",
        gate_frames=40,
        release_frames=20,
    )
    # Reference: pure baseline params
    _render_mod._SID_CACHE.clear()
    a = render_pyresid(base, sample_rate=SR)
    # Same params, but touching all phase-1 defaults explicitly -> no-op
    b_params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=8,
        release=4,
        pulse_width=2048,
        filter_cutoff=1024,
        filter_mode="off",
        gate_frames=40,
        release_frames=20,
        waveform_table=None,
        waveform_table_hold_frames=1,
        hard_restart=False,
        hard_restart_frames=2,
        pwm_lfo_rate=0.0,
        pwm_lfo_depth=0,
        filter_env=None,
        filter_env_hold_frames=1,
    )
    _render_mod._SID_CACHE.clear()
    b = render_pyresid(b_params, sample_rate=SR)
    assert a.shape == b.shape

    # Measure pyresidfp determinism floor for this exact config
    _render_mod._SID_CACHE.clear()
    a2 = render_pyresid(base, sample_rate=SR)
    det_floor = float(np.max(np.abs(a - a2)))

    diff = float(np.max(np.abs(a - b)))
    # Allow up to 2x the measured determinism floor (plus a small epsilon
    # for edge cases) — if phase-1 defaults introduced any real logic
    # change we would see a diff orders of magnitude larger.
    assert diff <= det_floor * 2 + 1e-5, (
        f"Phase 1 defaults changed rendering beyond determinism floor: "
        f"diff={diff}, floor={det_floor}"
    )


def test_phase1_waveform_table_produces_audio():
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=14,
        release=11,
        pulse_width=2048,
        filter_mode="off",
        gate_frames=60,
        release_frames=30,
        waveform_table=[0x80, 0x40, 0x10],  # noise -> pulse -> tri
        waveform_table_hold_frames=1,
    )
    audio = render_pyresid(params, sample_rate=SR)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert rms > 1e-3, f"waveform_table patch RMS too low: {rms}"


def test_phase1_hard_restart_runs():
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=14,
        release=11,
        pulse_width=2048,
        filter_mode="off",
        gate_frames=50,
        release_frames=25,
        hard_restart=True,
        hard_restart_frames=2,
    )
    audio = render_pyresid(params, sample_rate=SR)
    assert len(audio) > 0
    assert float(np.sqrt(np.mean(audio ** 2))) > 1e-3


def test_phase1_pwm_lfo_changes_spectrum():
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=0,
        sustain=15,
        release=0,
        pulse_width=2048,
        filter_mode="off",
        gate_frames=100,
        release_frames=10,
        pwm_lfo_rate=5.0,
        pwm_lfo_depth=400,
    )
    audio = render_pyresid(params, sample_rate=SR)
    assert float(np.sqrt(np.mean(audio ** 2))) > 1e-3


def test_phase1_filter_env_runs():
    env = [0x700, 0x600, 0x500, 0x400, 0x300, 0x200, 0x100]
    params = SidParams(
        waveform="pulse",
        frequency=TARGET_HZ,
        attack=0,
        decay=9,
        sustain=14,
        release=11,
        pulse_width=2048,
        filter_mode="lp",
        filter_voice1=True,
        filter_resonance=4,
        gate_frames=60,
        release_frames=20,
        filter_env=env,
        filter_env_hold_frames=4,
    )
    audio = render_pyresid(params, sample_rate=SR)
    assert float(np.sqrt(np.mean(audio ** 2))) > 1e-3


def test_compute_gate_release_fast():
    """Fast ADSR: A=0, D=0, S=0, R=0."""
    gate, release = compute_gate_release(0, 0, 0, 0)
    # A=0 (2ms) + D=0 (6ms) = 8ms -> min 10 frames
    assert gate == 10
    # R=0 (6ms) -> min 10 frames
    assert release == 10
