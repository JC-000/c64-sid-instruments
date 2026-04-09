"""Perceptual audio similarity scoring via Zimtohrli.

Zimtohrli is a psychoacoustic audio similarity metric from Google.
It is an optional dependency -- the rest of the pipeline works without it.

Install via ``pip install zimtohrli``.
"""

from __future__ import annotations

import logging
from math import gcd
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Zimtohrli requires 48 kHz audio.
_ZIMTOHRLI_SR = 48000

# Minimum signal length in samples at 48 kHz (10 ms).
_MIN_SAMPLES = int(_ZIMTOHRLI_SR * 0.01)


def _is_available() -> bool:
    """Return True if the zimtohrli package can be imported."""
    try:
        from zimtohrli import mos_from_signals  # noqa: F401
        return True
    except ImportError:
        return False


def _resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Resample audio from *sr_in* to *sr_out* using scipy."""
    if sr_in == sr_out:
        return audio
    from scipy.signal import resample_poly
    g = gcd(sr_in, sr_out)
    up = sr_out // g
    down = sr_in // g
    return resample_poly(audio, up, down).astype(np.float32)


def zimtohrli_distance(
    ref_audio: np.ndarray,
    cand_audio: np.ndarray,
    sr: int,
) -> float:
    """Compute Zimtohrli perceptual distance between two audio signals.

    Args:
        ref_audio: Reference audio as float32 numpy array (mono).
        cand_audio: Candidate audio as float32 numpy array (mono).
        sr: Sample rate of both signals.

    Returns:
        Perceptual distance score (lower = more similar).
        Returns ``float('inf')`` if zimtohrli is not installed or an
        error occurs.
    """
    try:
        from zimtohrli import mos_from_signals
    except ImportError:
        logger.warning(
            "zimtohrli not installed; returning inf. "
            "Install with: pip install zimtohrli"
        )
        return float("inf")

    # --- Validate inputs ---
    if ref_audio is None or cand_audio is None:
        return float("inf")
    if ref_audio.size == 0 or cand_audio.size == 0:
        return float("inf")

    # Ensure float32 in [-1, 1].
    ref_audio = np.asarray(ref_audio, dtype=np.float32)
    cand_audio = np.asarray(cand_audio, dtype=np.float32)
    ref_audio = np.clip(ref_audio, -1.0, 1.0)
    cand_audio = np.clip(cand_audio, -1.0, 1.0)

    # Resample to 48 kHz.
    ref_48k = _resample(ref_audio, sr, _ZIMTOHRLI_SR)
    cand_48k = _resample(cand_audio, sr, _ZIMTOHRLI_SR)

    # Ensure minimum length.
    if ref_48k.size < _MIN_SAMPLES or cand_48k.size < _MIN_SAMPLES:
        logger.warning(
            "Audio too short for Zimtohrli (ref=%d, cand=%d samples at 48kHz)",
            ref_48k.size, cand_48k.size,
        )
        return float("inf")

    # Pad shorter signal with zeros to match lengths.
    if ref_48k.size != cand_48k.size:
        max_len = max(ref_48k.size, cand_48k.size)
        if ref_48k.size < max_len:
            ref_48k = np.pad(ref_48k, (0, max_len - ref_48k.size))
        else:
            cand_48k = np.pad(cand_48k, (0, max_len - cand_48k.size))

    try:
        mos = mos_from_signals(ref_48k, cand_48k)
    except Exception as exc:
        logger.warning("Zimtohrli scoring failed: %s", exc)
        return float("inf")

    # mos_from_signals returns a MOS (Mean Opinion Score): higher = better
    # quality / more similar.  We want a distance where lower = better,
    # so invert: distance = 5.0 - mos (MOS scale is typically 1-5).
    distance = 5.0 - float(mos)
    return max(0.0, distance)


def rerank_with_zimtohrli(
    results: List["OptimizerResult"],
    ref_audio: np.ndarray,
    ref_sr: int,
    chip_model: str = "6581",
    top_k: int = 5,
) -> List[Tuple["OptimizerResult", float]]:
    """Re-rank optimization results using Zimtohrli perceptual metric.

    Args:
        results: List of OptimizerResult from grid_search / grid_search_multi_note.
        ref_audio: Reference audio as float32 numpy array (mono).
        ref_sr: Sample rate of the reference audio.
        chip_model: SID chip model for rendering candidates.
        top_k: Number of top candidates to re-rank.

    Returns:
        List of ``(OptimizerResult, zimtohrli_distance)`` tuples sorted by
        Zimtohrli distance (ascending -- lower is more perceptually similar).
        The original ``best_fitness`` is preserved inside each OptimizerResult.
    """
    from .render import render_pyresid

    if not _is_available():
        logger.warning(
            "zimtohrli not installed; skipping perceptual re-ranking"
        )
        return [(r, float("inf")) for r in results[:top_k]]

    # Take the top_k results (already sorted by spectral fitness).
    candidates = results[:top_k]

    scored: List[Tuple["OptimizerResult", float]] = []
    for result in candidates:
        # Render the candidate at the canonical SR used during optimization.
        # Use the reference SR for a fairer comparison.
        render_sr = ref_sr
        try:
            cand_audio = render_pyresid(
                result.best_params,
                sample_rate=render_sr,
                chip_model=chip_model,
            )
        except Exception as exc:
            logger.warning("Render failed for candidate: %s", exc)
            scored.append((result, float("inf")))
            continue

        dist = zimtohrli_distance(ref_audio, cand_audio, render_sr)
        scored.append((result, dist))

    # Sort by Zimtohrli distance (lower = better).
    scored.sort(key=lambda t: t[1])
    return scored
