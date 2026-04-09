"""Tests for tools.sidmatch.perceptual."""

import numpy as np
import pytest

from tools.sidmatch.perceptual import (
    zimtohrli_distance,
    rerank_with_zimtohrli,
    _is_available,
    _resample,
)


SR = 44100


def _sine(freq: float, dur: float = 0.5, sr: int = SR):
    t = np.arange(int(sr * dur)) / sr
    return (np.sin(2 * np.pi * freq * t) * 0.8).astype(np.float32)


class TestResample:
    def test_same_rate_noop(self):
        x = _sine(440.0)
        y = _resample(x, 44100, 44100)
        np.testing.assert_array_equal(x, y)

    def test_upsample_length(self):
        x = _sine(440.0, sr=22050)
        y = _resample(x, 22050, 44100)
        # Should roughly double in length.
        assert abs(len(y) - 2 * len(x)) <= 2

    def test_downsample_length(self):
        x = _sine(440.0, sr=48000)
        y = _resample(x, 48000, 24000)
        assert abs(len(y) - len(x) // 2) <= 2


class TestZimtohrliDistance:
    def test_empty_audio_returns_inf(self):
        empty = np.array([], dtype=np.float32)
        signal = _sine(440.0)
        assert zimtohrli_distance(empty, signal, SR) == float("inf")
        assert zimtohrli_distance(signal, empty, SR) == float("inf")

    def test_none_audio_returns_inf(self):
        assert zimtohrli_distance(None, _sine(440.0), SR) == float("inf")
        assert zimtohrli_distance(_sine(440.0), None, SR) == float("inf")

    def test_very_short_audio_returns_inf(self):
        short = np.array([0.1, 0.2], dtype=np.float32)
        signal = _sine(440.0)
        assert zimtohrli_distance(short, signal, SR) == float("inf")

    @pytest.mark.skipif(
        not _is_available(), reason="zimtohrli not installed"
    )
    def test_identical_signals_low_distance(self):
        x = _sine(440.0)
        dist = zimtohrli_distance(x, x, SR)
        assert dist < 1.0, f"Expected low distance for identical signals, got {dist}"

    @pytest.mark.skipif(
        not _is_available(), reason="zimtohrli not installed"
    )
    def test_different_signals_higher_distance(self):
        a = _sine(440.0)
        b = _sine(880.0)
        dist_same = zimtohrli_distance(a, a, SR)
        dist_diff = zimtohrli_distance(a, b, SR)
        assert dist_diff > dist_same, (
            f"Different signals should have higher distance: "
            f"same={dist_same:.4f} diff={dist_diff:.4f}"
        )

    @pytest.mark.skipif(
        not _is_available(), reason="zimtohrli not installed"
    )
    def test_different_lengths_handled(self):
        a = _sine(440.0, dur=0.5)
        b = _sine(440.0, dur=1.0)
        dist = zimtohrli_distance(a, b, SR)
        assert np.isfinite(dist)

    def test_returns_nonnegative(self):
        """Distance should never be negative (even without zimtohrli)."""
        a = _sine(440.0)
        dist = zimtohrli_distance(a, a, SR)
        if np.isfinite(dist):
            assert dist >= 0.0


class TestRerankWithZimtohrli:
    @pytest.mark.skipif(
        not _is_available(), reason="zimtohrli not installed"
    )
    def test_rerank_preserves_results(self):
        """Reranking should return all candidates."""
        from tools.sidmatch.optimize import OptimizerResult
        from tools.sidmatch.render import SidParams

        params = SidParams(waveform="saw", frequency=440.0)
        results = [
            OptimizerResult(best_params=params, best_fitness=0.5),
            OptimizerResult(best_params=params, best_fitness=0.3),
        ]
        ref = _sine(440.0)
        ranked = rerank_with_zimtohrli(results, ref, SR, top_k=2)
        assert len(ranked) == 2
        # Each entry is (OptimizerResult, zimtohrli_distance).
        for res, dist in ranked:
            assert hasattr(res, "best_fitness")
            assert isinstance(dist, float)

    def test_rerank_without_zimtohrli_returns_inf(self):
        """Without zimtohrli, all distances should be inf."""
        if _is_available():
            pytest.skip("zimtohrli is installed")
        from tools.sidmatch.optimize import OptimizerResult
        from tools.sidmatch.render import SidParams

        params = SidParams(waveform="saw", frequency=440.0)
        results = [
            OptimizerResult(best_params=params, best_fitness=0.5),
        ]
        ref = _sine(440.0)
        ranked = rerank_with_zimtohrli(results, ref, SR, top_k=1)
        assert len(ranked) == 1
        assert ranked[0][1] == float("inf")
