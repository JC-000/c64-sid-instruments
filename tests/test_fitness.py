"""Tests for tools.sidmatch.fitness."""

import numpy as np
import pytest

from tools.sidmatch.features import extract
from tools.sidmatch.fitness import distance, DEFAULT_WEIGHTS


SR = 44100


def _sine(freq: float, dur: float = 1.0, tau: float = 0.4, sr: int = SR):
    t = np.arange(int(sr * dur)) / sr
    env = np.exp(-t / tau)
    return (np.sin(2 * np.pi * freq * t) * env).astype(np.float32)


def _attack_ramp(freq: float, attack_s: float, dur: float = 1.0, sr: int = SR):
    t = np.arange(int(sr * dur)) / sr
    env = np.clip(t / max(attack_s, 1e-6), 0.0, 1.0) * np.exp(-(t) / 1.5)
    return (np.sin(2 * np.pi * freq * t) * env).astype(np.float32)


def test_identical_inputs_zero():
    fv = extract(_sine(440.0), SR)
    assert distance(fv, fv) == 0.0


def test_distinct_signals_positive():
    a = extract(_sine(220.0), SR)
    b = extract(_sine(440.0), SR)
    assert distance(a, b) > 0.0


def test_fast_vs_slow_attack_positive():
    a = extract(_attack_ramp(440.0, attack_s=0.005), SR)
    b = extract(_attack_ramp(440.0, attack_s=0.3), SR)
    assert distance(a, b) > 0.0


def test_symmetric():
    a = extract(_sine(220.0), SR)
    b = extract(_sine(330.0), SR)
    d_ab = distance(a, b)
    d_ba = distance(b, a)
    assert abs(d_ab - d_ba) < 1e-9


def test_ordering_shifted_closer_than_different():
    ref_sig = _sine(440.0)
    # "slightly shifted": pad a few ms of silence at the front but
    # keep same content; features are extracted after trimming so they
    # should be almost identical.
    shift_samples = int(0.01 * SR)
    shifted_sig = np.concatenate([np.zeros(shift_samples, dtype=np.float32), ref_sig])
    different_sig = _sine(880.0)

    ref = extract(ref_sig, SR)
    shifted = extract(shifted_sig, SR)
    different = extract(different_sig, SR)

    d_close = distance(ref, shifted)
    d_far = distance(ref, different)
    assert d_close < d_far


def test_weights_override_affects_distance():
    a = extract(_sine(220.0), SR)
    b = extract(_sine(440.0), SR)
    d_default = distance(a, b)
    # zero-out everything => distance should collapse to 0
    zero_w = {k: 0.0 for k in DEFAULT_WEIGHTS}
    assert distance(a, b, weights=zero_w) == 0.0
    # boost fundamental weight => distance should grow
    big_w = dict(DEFAULT_WEIGHTS)
    big_w["fundamental"] = 20.0
    assert distance(a, b, weights=big_w) > d_default


def test_non_negative():
    a = extract(_sine(330.0), SR)
    b = extract(_sine(550.0, tau=0.2), SR)
    assert distance(a, b) >= 0.0


def test_rejects_non_featurevec():
    with pytest.raises(TypeError):
        distance("not a featurevec", "also not")  # type: ignore[arg-type]
