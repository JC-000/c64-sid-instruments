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
from .fitness_mrstft import mr_stft_distance


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
    "onset_spectral": 2.0,
    "mfcc": 1.5,
    "spectral_convergence": 1.5,
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
        # Zero-mean each spectrogram before comparing so that a global
        # energy offset (e.g. SID vs real instrument loudness) does not
        # dominate the distance.  This focuses on *spectral shape* over time.
        r = r - r.mean()
        c = c - c.mean()
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


def _onset_spectral_distance(ref: FeatureVec, cand: FeatureVec) -> float:
    """Onset-weighted log-mel MSE, scaled by the reference onset flux ratio.

    If both onset_log_mel are None (e.g. from extract_lite), returns 0.
    The onset flux ratio acts as an adaptive weight: sharp transients
    (piano, guitar) produce a high ratio, amplifying onset mismatch.
    Smooth onsets (violin, organ) produce a low ratio, reducing onset weight.
    """
    if ref.onset_log_mel is None or cand.onset_log_mel is None:
        return 0.0
    # Use the max of both onset energy ratios as the adaptive multiplier.
    # max() keeps the asymmetric intent (sharp transient in either signal
    # amplifies onset mismatch) while ensuring distance(a,b) == distance(b,a).
    # Clamp to [0, 4] to prevent extreme amplification from very sharp
    # transients (the ratio can reach 10x+), keeping the component O(1).
    onset_ratio = min(max(ref.onset_energy_ratio, cand.onset_energy_ratio, 0.0), 4.0)
    if onset_ratio < 1e-6:
        return 0.0

    n_scales = min(len(ref.onset_log_mel), len(cand.onset_log_mel))
    if n_scales == 0:
        return 0.0

    total_mse = 0.0
    for i in range(n_scales):
        r = np.asarray(ref.onset_log_mel[i], dtype=np.float64)
        c = np.asarray(cand.onset_log_mel[i], dtype=np.float64)
        t = min(r.shape[1], c.shape[1])
        if t == 0:
            continue
        r = r[:, :t]
        c = c[:, :t]
        # Zero-mean to focus on spectral shape, not global energy offset.
        r = r - r.mean()
        c = c - c.mean()
        mse = float(np.mean((r - c) ** 2))
        var_r = float(np.var(r))
        var_c = float(np.var(c))
        norm = max((var_r + var_c) / 2.0, 1e-12)
        total_mse += min(mse / norm, 4.0)
    avg_mse = total_mse / n_scales

    return float(min(onset_ratio * avg_mse, 4.0))


def _mfcc_distance(ref: FeatureVec, cand: FeatureVec) -> float:
    """Cosine distance between mean MFCC vectors.

    MFCCs are averaged across all frames to produce a single 13-D vector
    per signal, then compared via cosine distance.
    Returns 0.0 if either MFCC is None (e.g. from extract_lite).
    """
    if ref.mfcc is None or cand.mfcc is None:
        return 0.0
    ref_mean = np.mean(ref.mfcc, axis=1)
    cand_mean = np.mean(cand.mfcc, axis=1)
    return _cosine_distance(ref_mean, cand_mean)


def _spectral_convergence_distance(ref: FeatureVec, cand: FeatureVec) -> float:
    """Frobenius norm ratio: ||S_ref - S_cand||_F / ||S_ref||_F.

    This emphasizes frequency bins where the reference has energy,
    unlike MSE which weights all bins equally.
    Returns 0.0 if either STFT is None.
    """
    if ref.stft_mag is None or cand.stft_mag is None:
        return 0.0
    r = np.asarray(ref.stft_mag, dtype=np.float64)
    c = np.asarray(cand.stft_mag, dtype=np.float64)
    # Align time axes to the shorter one
    t = min(r.shape[1], c.shape[1])
    if t == 0:
        return 0.0
    r = r[:, :t]
    c = c[:, :t]
    # Use average of both norms in denominator for symmetry:
    # distance(a, b) == distance(b, a)
    ref_norm = float(np.linalg.norm(r, 'fro'))
    cand_norm = float(np.linalg.norm(c, 'fro'))
    avg_norm = (ref_norm + cand_norm) / 2.0
    if avg_norm < 1e-12:
        return 0.0
    diff_norm = float(np.linalg.norm(r - c, 'fro'))
    # Clamp to [0, 4] to avoid extreme values
    return float(min(diff_norm / avg_norm, 4.0))


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
        "onset_spectral": _onset_spectral_distance(ref, cand),
        "mfcc": _mfcc_distance(ref, cand),
        "spectral_convergence": _spectral_convergence_distance(ref, cand),
    }

    total = 0.0
    for k, v in comps.items():
        total += w[k] * float(v)
    # guard against tiny negative floats
    return float(max(0.0, total))


def distance_v2(
    ref_wav: np.ndarray,
    cand_wav: np.ndarray,
    sr: int,
    **kwargs,
) -> float:
    """Waveform-level fitness using multi-resolution STFT with log-mag.

    This is the Phase 2.5 replacement for :func:`distance`. It operates
    directly on mono waveforms (not :class:`FeatureVec`) and uses a
    log-magnitude multi-resolution STFT loss with per-frame RMS
    weighting so decay tails are not dominated by attack transients.
    See :mod:`tools.sidmatch.fitness_mrstft` for details.

    The legacy :func:`distance` is intentionally left untouched so
    existing optimizer and test code keeps working while this new
    fitness is validated in parallel.

    Length equalization: the reference is trimmed to the candidate's
    length (when longer). This is important because reference samples
    from libraries such as Salamander can be 140 s long while SID
    renders are ~32 s. If we let ``mr_stft_distance`` zero-pad the
    candidate up to the reference length, a huge chunk of silent
    frames dominates the log-magnitude distance and swamps the actual
    onset/decay mismatch. Trimming the reference focuses the loss on
    the portion both signals actually cover.
    """
    ref = np.asarray(ref_wav)
    cand = np.asarray(cand_wav)
    if ref.ndim > 1:
        ref = ref.mean(axis=-1)
    if cand.ndim > 1:
        cand = cand.mean(axis=-1)
    if ref.size > cand.size and cand.size > 0:
        ref = ref[: cand.size]
    return mr_stft_distance(ref, cand, sr, **kwargs)
