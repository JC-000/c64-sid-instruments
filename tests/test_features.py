"""Tests for tools.sidmatch.features."""

import numpy as np
import pytest

from tools.sidmatch.features import extract, FeatureVec, TIME_SERIES_FRAMES


def _exp_decay_sine(freq: float, sr: int = 44100, dur: float = 1.5, tau: float = 0.4):
    t = np.arange(int(sr * dur)) / sr
    env = np.exp(-t / tau)
    sig = np.sin(2 * np.pi * freq * t) * env
    return sig.astype(np.float32)


def test_extract_returns_featurevec_shapes():
    sig = _exp_decay_sine(440.0)
    fv = extract(sig, 44100)
    assert isinstance(fv, FeatureVec)
    assert fv.amplitude_envelope.shape == (TIME_SERIES_FRAMES,)
    assert fv.spectral_centroid.shape == (TIME_SERIES_FRAMES,)
    assert fv.spectral_rolloff.shape == (TIME_SERIES_FRAMES,)
    assert fv.spectral_flatness.shape == (TIME_SERIES_FRAMES,)
    assert fv.harmonic_magnitudes.size == 16


def test_fundamental_detected_440():
    sig = _exp_decay_sine(440.0)
    fv = extract(sig, 44100)
    assert abs(fv.fundamental_hz - 440.0) < 2.0


def test_fast_attack_detected():
    sig = _exp_decay_sine(440.0)
    fv = extract(sig, 44100)
    # pure exponential decay: no ramp-up, attack should be very short.
    assert fv.attack_time_s < 0.05


def test_envelope_monotonic_after_attack():
    sig = _exp_decay_sine(440.0)
    fv = extract(sig, 44100)
    env = fv.amplitude_envelope
    peak = int(np.argmax(env))
    tail = env[peak:]
    # Allow small non-monotone wiggles from RMS framing: check overall trend.
    # Compare first third and last third of the tail.
    n = tail.size
    if n >= 6:
        first = float(tail[: n // 3].mean())
        last = float(tail[-n // 3 :].mean())
        assert last < first
    # And check it never climbs back to the peak value.
    assert float(tail[1:].max()) <= float(tail[0]) + 1e-6


def test_stereo_input_handled():
    sig = _exp_decay_sine(440.0)
    stereo = np.stack([sig, sig], axis=1)  # (N, 2)
    fv = extract(stereo, 44100)
    assert abs(fv.fundamental_hz - 440.0) < 2.0

    stereo2 = np.stack([sig, sig], axis=0)  # (2, N)
    fv2 = extract(stereo2, 44100)
    assert abs(fv2.fundamental_hz - 440.0) < 2.0


def test_different_sample_rates():
    for sr in (22050, 32000, 48000):
        sig = _exp_decay_sine(440.0, sr=sr)
        fv = extract(sig, sr)
        assert abs(fv.fundamental_hz - 440.0) < 3.0
        assert fv.sr == 44100


def test_all_zero_audio():
    sig = np.zeros(44100, dtype=np.float32)
    fv = extract(sig, 44100)
    assert fv.fundamental_hz == 0.0
    assert float(fv.amplitude_envelope.max()) == 0.0


def test_empty_audio_raises():
    with pytest.raises(ValueError):
        extract(np.zeros(0, dtype=np.float32), 44100)


def test_very_short_audio():
    # under 2048 samples; should still return something.
    sig = _exp_decay_sine(440.0, dur=0.02)
    fv = extract(sig, 44100)
    assert isinstance(fv, FeatureVec)


def test_nonfinite_audio_raises():
    sig = _exp_decay_sine(440.0)
    sig[100] = np.nan
    with pytest.raises(ValueError):
        extract(sig, 44100)
