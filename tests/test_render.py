"""Integration test for both rendering backends.

Renders the same 440Hz sawtooth patch via pyresidfp and via VICE, then
checks that:

  * both outputs have non-trivial RMS energy;
  * their normalized cross-correlation peak exceeds 0.85
    (alignment-tolerant); and
  * the detected fundamental frequency is within 5Hz of 440Hz in both.

Marked as an integration test because the VICE render runs in real time
(~6 seconds).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from scipy.fft import rfft, rfftfreq
from scipy.signal import correlate

from sidmatch.render import SidParams, render_pyresid, render_vice


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
    """Extract a ``seconds``-long window from the stable part of the note.

    The VICE capture contains a power-on click and long stretches of
    silence; pyresidfp output starts at the attack immediately. We find
    the loudest window using a ~200ms envelope, then return a window
    starting ~50ms after the envelope peak (past the attack transient).
    """
    if len(x) < sr:
        return x
    # Skip a small leading region that may contain a boot click.
    lead = min(len(x) - 1, int(0.5 * sr)) if len(x) > 2 * sr else 0
    body = x[lead:]
    win = sr // 5  # 200ms
    if len(body) < win * 2:
        return x
    env = np.sqrt(np.convolve(body ** 2, np.ones(win) / win, mode="valid"))
    peak = int(np.argmax(env)) + lead
    # start slightly past the peak to be inside the sustain region
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
    out = tmp_path_factory.mktemp("vice") / "patch.wav"
    render_vice(patch, out, sample_rate=SR)
    return _read_wav(out)


def test_pyresid_energy(pyresid_signal):
    rms = float(np.sqrt(np.mean(pyresid_signal ** 2)))
    assert rms > 1e-3, f"pyresid RMS too low: {rms}"


def test_vice_energy(vice_signal):
    rms = float(np.sqrt(np.mean(vice_signal ** 2)))
    assert rms > 1e-3, f"vice RMS too low: {rms}"


def test_pyresid_fundamental(pyresid_signal):
    f = _fundamental_hz(pyresid_signal)
    assert abs(f - TARGET_HZ) < 5.0, f"pyresid fundamental off: {f}"


def test_vice_fundamental(vice_signal):
    f = _fundamental_hz(vice_signal)
    assert abs(f - TARGET_HZ) < 5.0, f"vice fundamental off: {f}"


def test_cross_correlation(pyresid_signal, vice_signal):
    a = _trim_to_note(pyresid_signal, seconds=0.5)
    b = _trim_to_note(vice_signal, seconds=0.5)
    peak = _max_xcorr(a, b)
    assert peak > 0.85, f"cross-correlation too low: {peak}"
