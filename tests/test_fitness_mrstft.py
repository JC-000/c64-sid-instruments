"""Tests for the multi-resolution STFT fitness (Phase 2.5).

These are the regression tests for the "loud region dominates" failure
mode of the legacy fitness. In particular, ``test_tail_zeroed`` is the
specific test the task brief calls out: a signal that has had its last
30% silenced must score *much* worse than a gain-scaled copy, because
frame weighting is meant to make quiet regions count.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tools.sidmatch.fitness_mrstft import mr_stft_distance
from tools.sidmatch.fitness import distance_v2


SR = 44100


def _piano_like(duration_s: float = 2.0, sr: int = SR, freq: float = 261.63) -> np.ndarray:
    """Cheap piano-ish: three partials with an exponential decay envelope.

    Realistic enough to exercise all FFT sizes without pulling in the
    SID renderer.
    """
    t = np.arange(int(duration_s * sr), dtype=np.float64) / sr
    env = np.exp(-3.0 * t)  # ~20 dB over 1.5 s
    sig = (
        1.0 * np.sin(2 * math.pi * freq * t)
        + 0.5 * np.sin(2 * math.pi * 2 * freq * t)
        + 0.25 * np.sin(2 * math.pi * 3 * freq * t)
    )
    return (env * sig).astype(np.float64)


def test_identical_signals_zero():
    x = _piano_like()
    d = mr_stft_distance(x, x, SR)
    assert d < 1e-6, f"expected ~0 for identical signals, got {d}"


def test_scaled_copy_small_but_nonzero():
    x = _piano_like()
    y = 0.5 * x
    d = mr_stft_distance(x, y, SR)
    # Log-magnitude catches the gain difference, but frame weighting
    # keeps it bounded. We mostly care: strictly positive, and way
    # below the time-reversed ceiling checked below.
    assert d > 1e-4, f"scaled copy should register a nonzero distance, got {d}"
    assert d < 1.0, f"scaled copy distance unexpectedly huge: {d}"


def test_time_reversed_large():
    x = _piano_like()
    y = x[::-1].copy()
    d_same = mr_stft_distance(x, x, SR)
    d_rev = mr_stft_distance(x, y, SR)
    assert d_rev > d_same + 0.5, (
        f"time-reversed should be much worse than identical: "
        f"same={d_same} rev={d_rev}"
    )


def test_tail_zeroed_is_large():
    """Regression test for the original failure mode.

    The candidate matches the reference for the first 70% of the
    signal but then cuts to silence — exactly what a sustain=0 SID
    patch does to a piano envelope. Frame-weighting is supposed to
    make this a large-distance configuration. If this test starts
    failing, the fitness has regressed to "loud region dominates".
    """
    x = _piano_like()
    cut = int(0.7 * x.size)
    y = x.copy()
    y[cut:] = 0.0

    d_scaled = mr_stft_distance(x, 0.5 * x, SR)
    d_tail = mr_stft_distance(x, y, SR)

    assert d_tail > 0.5, f"tail-zeroed distance too small: {d_tail}"
    # Missing tail must be *much* worse than a global -6 dB gain offset.
    assert d_tail > 3.0 * d_scaled, (
        f"tail-zeroed ({d_tail}) should dominate scaled-copy ({d_scaled})"
    )


def test_distance_v2_entry_point():
    """The fitness.distance_v2 re-export should behave the same."""
    x = _piano_like()
    y = 0.5 * x
    d_direct = mr_stft_distance(x, y, SR)
    d_v2 = distance_v2(x, y, SR)
    assert d_direct == pytest.approx(d_v2)


def test_frame_weighting_toggles_tail_sensitivity():
    """Turning frame weighting off should reduce tail-zeroed penalty.

    Sanity check that the frame-weighting knob actually does what the
    docstring claims.
    """
    x = _piano_like()
    cut = int(0.7 * x.size)
    y = x.copy()
    y[cut:] = 0.0

    d_weighted = mr_stft_distance(x, y, SR, frame_weight=True)
    d_plain = mr_stft_distance(x, y, SR, frame_weight=False)
    assert d_weighted > d_plain, (
        f"frame-weighted tail penalty ({d_weighted}) should exceed "
        f"unweighted ({d_plain})"
    )
