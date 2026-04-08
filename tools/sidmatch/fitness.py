"""Scalar distance between two :class:`FeatureVec`.

The fitness function is a weighted sum of per-component distances:

=========================  ===========================================
component                  distance
=========================  ===========================================
envelope                   L2 between normalized amplitude envelopes
                           (resampled to 128 frames at extract time)
harmonics                  cosine distance of the first 16 partial
                           magnitude vectors
spectral_centroid          L1 between log-centroid time series
                           (Hz, time-aligned at 128 frames)
spectral_rolloff           L1 between log-rolloff time series
spectral_flatness          L1 between flatness time series
noisiness                  squared error of scalar noisiness
fundamental                squared log2-ratio of the two f0 estimates
adsr                       L1 over (attack, decay, sustain, release)
                           with per-term scaling
envelope_delta             L2 between first-difference of envelopes
                           (penalizes attack/decay slope mismatch)
=========================  ===========================================

All components are non-negative and normalized to be O(1) so the
default weights are directly interpretable. ``distance(x, x)`` returns
exactly 0. The function is symmetric by construction.
"""

from __future__ import annotations

from typing import Mapping, Optional

import numpy as np

from .features import FeatureVec


DEFAULT_WEIGHTS: dict = {
    "envelope": 1.0,
    "harmonics": 2.0,
    "spectral_centroid": 0.0,   # superseded by log_mel
    "spectral_rolloff": 0.0,    # superseded by log_mel
    "spectral_flatness": 0.0,   # superseded by log_mel
    "noisiness": 0.0,           # superseded by log_mel
    "fundamental": 2.0,
    "adsr": 1.0,
    "log_mel": 3.0,
    "envelope_delta": 0.5,
}


def _safe_log(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    return np.log(np.maximum(np.asarray(x, dtype=np.float64), eps))


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 and nb == 0.0:
        return 0.0
    if na == 0.0 or nb == 0.0:
        return 1.0
    cos = float(np.dot(a, b) / (na * nb))
    cos = max(-1.0, min(1.0, cos))
    return 1.0 - cos


def _envelope_l2(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    n = min(a.size, b.size)
    if n == 0:
        return 0.0
    diff = a[:n] - b[:n]
    return float(np.sqrt(np.mean(diff * diff)))


def _log_series_l1(a: np.ndarray, b: np.ndarray, scale: float = 1.0) -> float:
    la = _safe_log(a)
    lb = _safe_log(b)
    n = min(la.size, lb.size)
    if n == 0:
        return 0.0
    return float(np.mean(np.abs(la[:n] - lb[:n])) / scale)


def _series_l1(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    n = min(a.size, b.size)
    if n == 0:
        return 0.0
    return float(np.mean(np.abs(a[:n] - b[:n])))


def _f0_log_ratio(a: float, b: float) -> float:
    if a <= 0.0 and b <= 0.0:
        return 0.0
    if a <= 0.0 or b <= 0.0:
        return 4.0  # large penalty: pitched vs unpitched mismatch
    r = np.log2(a / b)
    return float(r * r)


def _log_mel_mse(ref_mel: tuple | None, cand_mel: tuple | None) -> float:
    """Multi-scale log-mel MSE, averaged across scales.

    Each element of ref_mel / cand_mel is a 2-D array (n_mels, n_frames).
    The shorter spectrogram along the time axis is zero-padded to match.
    Returns 0.0 if either input is None (e.g. from extract_lite).
    """
    if ref_mel is None or cand_mel is None:
        return 0.0
    n_scales = min(len(ref_mel), len(cand_mel))
    if n_scales == 0:
        return 0.0
    total = 0.0
    for i in range(n_scales):
        r = np.asarray(ref_mel[i], dtype=np.float64)
        c = np.asarray(cand_mel[i], dtype=np.float64)
        # Truncate both to the shorter time axis to avoid silence-padding
        # artifacts inflating the MSE for near-identical signals.
        t = min(r.shape[1], c.shape[1])
        if t == 0:
            continue
        r = r[:, :t]
        c = c[:, :t]
        mse = float(np.mean((r - c) ** 2))
        # Normalize by the mean variance of the two spectrograms so the
        # component stays O(1) regardless of absolute energy scale.
        # This makes it a fractional MSE (0 = identical, ~1 = very different).
        var_r = float(np.var(r))
        var_c = float(np.var(c))
        norm = max((var_r + var_c) / 2.0, 1e-12)
        # Clamp to avoid degenerate cases where near-zero variance
        # inflates the normalized MSE (e.g. very short or silent audio).
        total += min(mse / norm, 4.0)
    return total / n_scales


def _adsr_l1(ref: FeatureVec, cand: FeatureVec) -> float:
    # scale times by 1 s (typical envelopes are under a few seconds);
    # sustain level is already in [0,1].
    terms = [
        abs(ref.attack_time_s - cand.attack_time_s),
        abs(ref.decay_time_s - cand.decay_time_s),
        abs(ref.sustain_level - cand.sustain_level),
        abs(ref.release_time_s - cand.release_time_s),
    ]
    return float(sum(terms) / 4.0)


def distance_lite(
    ref: FeatureVec,
    cand: FeatureVec,
    weights: Optional[Mapping[str, float]] = None,
) -> float:
    """Cheap partial distance using only envelope, harmonics, fundamental, and ADSR.

    Returns a lower bound on the full distance (since skipped spectral
    components are always >= 0).
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)

    total = 0.0
    total += w["envelope"] * _envelope_l2(ref.amplitude_envelope, cand.amplitude_envelope)
    total += w["harmonics"] * _cosine_distance(ref.harmonic_magnitudes, cand.harmonic_magnitudes)
    total += w["fundamental"] * _f0_log_ratio(ref.fundamental_hz, cand.fundamental_hz)
    total += w["adsr"] * _adsr_l1(ref, cand)
    return float(max(0.0, total))


def distance(
    ref: FeatureVec,
    cand: FeatureVec,
    weights: Optional[Mapping[str, float]] = None,
) -> float:
    """Scalar non-negative distance between two :class:`FeatureVec`.

    ``distance(x, x) == 0``, and the function is symmetric. ``weights``
    overrides :data:`DEFAULT_WEIGHTS`; unknown keys are ignored and
    missing keys fall back to the defaults.
    """
    if not isinstance(ref, FeatureVec) or not isinstance(cand, FeatureVec):
        raise TypeError("ref and cand must be FeatureVec instances")

    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)

    comps = {
        "envelope": _envelope_l2(ref.amplitude_envelope, cand.amplitude_envelope),
        "harmonics": _cosine_distance(ref.harmonic_magnitudes, cand.harmonic_magnitudes),
        "spectral_centroid": _log_series_l1(
            ref.spectral_centroid, cand.spectral_centroid, scale=np.log(2) * 4
        ),
        "spectral_rolloff": _log_series_l1(
            ref.spectral_rolloff, cand.spectral_rolloff, scale=np.log(2) * 4
        ),
        "spectral_flatness": _series_l1(ref.spectral_flatness, cand.spectral_flatness),
        "noisiness": (ref.noisiness - cand.noisiness) ** 2,
        "fundamental": _f0_log_ratio(ref.fundamental_hz, cand.fundamental_hz),
        "adsr": _adsr_l1(ref, cand),
        "log_mel": _log_mel_mse(ref.log_mel, cand.log_mel),
        "envelope_delta": _envelope_l2(
            np.diff(np.asarray(ref.amplitude_envelope, dtype=np.float64)),
            np.diff(np.asarray(cand.amplitude_envelope, dtype=np.float64)),
        ),
    }

    total = 0.0
    for k, v in comps.items():
        total += w[k] * float(v)
    # guard against tiny negative floats
    return float(max(0.0, total))
