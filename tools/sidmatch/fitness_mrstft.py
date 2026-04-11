"""Multi-resolution STFT loss with log-magnitude compression.

Waveform-level audio fitness function designed to preserve decay tails,
following Engel et al. 2020 (DDSP) and Yamamoto et al. 2020 (Parallel
WaveGAN). Sums per-resolution spectral convergence plus log-magnitude L1
across a bank of FFT sizes, with optional frame weighting that boosts
the contribution of quiet regions (decay tails) so the optimizer is
forced to match them instead of letting them vanish.

Motivation
----------
The legacy :func:`tools.sidmatch.fitness.distance` aggregates features
(MFCC means, linear-magnitude spectral convergence, etc.) in a way that
is dominated by the loudest portion of the signal. For percussive
sources like piano that means the attack overwhelms the fitness and a
sustain=0 patch (no decay tail) scores essentially the same as a proper
piano envelope. The fix is twofold:

  1. Compare log-magnitudes. ``log|S|`` compresses the huge dynamic
     range between attack and release, so a -40 dB tail contributes
     meaningfully to the loss.

  2. Frame-weight the per-frame contribution by ``1/(rms(t) + eps)``
     (normalized to mean-1). Reference frames with little energy get
     *more* weight, not less, which is the exact inversion of what a
     vanilla MSE does.

The two compound to make "tail missing" a large-distance configuration
instead of a rounding error.

Reference
---------
 * Engel et al., 2020, "DDSP: Differentiable Digital Signal Processing"
 * Yamamoto et al., 2020, "Parallel WaveGAN: A fast waveform generation
   model based on adversarial networks with multi-resolution spectrogram"
 * Schwaer & Mueller 2023, "Multi-Scale Spectral Loss Revisited"
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np


DEFAULT_FFT_SIZES: tuple[int, ...] = (2048, 1024, 512, 256, 128, 64)


def _to_mono_f64(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x)
    if a.ndim > 1:
        a = a.mean(axis=-1)
    return a.astype(np.float64, copy=False)


def _align_length(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Zero-pad the shorter signal so both have the same length.

    We pad rather than truncate: truncating would drop tails, which is
    exactly the failure mode this fitness is trying to punish.
    """
    n = max(a.size, b.size)
    if a.size < n:
        a = np.concatenate([a, np.zeros(n - a.size, dtype=a.dtype)])
    if b.size < n:
        b = np.concatenate([b, np.zeros(n - b.size, dtype=b.dtype)])
    return a, b


def _stft_mag(
    x: np.ndarray,
    n_fft: int,
    hop_length: int,
    window: str = "hann",
) -> np.ndarray:
    """Magnitude STFT via librosa, with lazy import."""
    import librosa

    if x.size < n_fft:
        pad = n_fft - x.size
        x = np.concatenate([x, np.zeros(pad, dtype=x.dtype)])
    S = librosa.stft(
        x,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=n_fft,
        window=window,
        center=True,
    )
    return np.abs(S).astype(np.float64)


def _per_resolution_loss(
    S_ref: np.ndarray,
    S_cand: np.ndarray,
    *,
    w_sc: float,
    w_log: float,
    eps: float,
    frame_weight: bool,
) -> float:
    """Spectral convergence + log-magnitude L1 at one FFT size."""
    # Trim to shared number of time frames. Both were built from the
    # same padded-length signal, so the sizes match; this is just a
    # belt-and-braces guard.
    t = min(S_ref.shape[1], S_cand.shape[1])
    if t == 0:
        return 0.0
    S_ref = S_ref[:, :t]
    S_cand = S_cand[:, :t]

    if frame_weight:
        # RMS per frame from the reference. Frames with low energy
        # (decay tails, silence) get a high inverse weight, so they
        # stop being free. Normalize to mean-1 so the overall loss
        # scale is comparable to the unweighted version.
        rms = np.sqrt(np.mean(S_ref ** 2, axis=0) + eps)
        w = 1.0 / rms
        w = w / (w.mean() + eps)
        w_row = w[None, :]
    else:
        w_row = 1.0

    diff = (S_ref - S_cand) * w_row
    log_diff = (np.log(S_ref + eps) - np.log(S_cand + eps)) * w_row

    ref_norm = np.linalg.norm(S_ref * w_row, "fro")
    sc = float(np.linalg.norm(diff, "fro") / (ref_norm + eps))
    lm = float(np.mean(np.abs(log_diff)))
    return w_sc * sc + w_log * lm


def mr_stft_distance(
    ref_wav: np.ndarray,
    cand_wav: np.ndarray,
    sr: int,
    *,
    fft_sizes: Sequence[int] = DEFAULT_FFT_SIZES,
    w_sc: float = 1.0,
    w_log: float = 1.0,
    eps: float = 1e-7,
    frame_weight: bool = True,
) -> float:
    """Multi-resolution STFT distance between two mono waveforms.

    Parameters
    ----------
    ref_wav, cand_wav
        Mono 1-D arrays. Stereo inputs are downmixed to mono. Lengths
        may differ; the shorter signal is zero-padded so missing tails
        count against the candidate.
    sr
        Sample rate in Hz (unused by the core computation — the STFT
        operates on samples — but kept in the signature for parity with
        perceptual losses and for documentation).
    fft_sizes
        FFT sizes for the resolution bank. Defaults to
        ``(2048, 1024, 512, 256, 128, 64)``, covering roughly 46 ms down
        to 1.5 ms at 44.1 kHz.
    w_sc, w_log
        Weights for the spectral-convergence and log-magnitude terms.
    eps
        Floor added before logs, divisions, and norms. 1e-7 is roughly
        -140 dB, small enough not to mask decay content but large enough
        to keep ``log(0)`` finite.
    frame_weight
        If True (default), each time frame's contribution is scaled by
        ``1 / (rms(t) + eps)``, normalized to mean-1 across frames.

    Returns
    -------
    float
        Non-negative scalar. ``mr_stft_distance(x, x, sr) == 0``.
        Symmetric up to the asymmetry of ``frame_weight`` (which uses
        the *reference* RMS). Pass the same array twice to verify.
    """
    del sr  # not used by the pure-sample STFT, kept for API parity
    a = _to_mono_f64(ref_wav)
    b = _to_mono_f64(cand_wav)
    a, b = _align_length(a, b)

    total = 0.0
    n = 0
    for n_fft in fft_sizes:
        hop = max(1, n_fft // 4)
        S_ref = _stft_mag(a, n_fft=n_fft, hop_length=hop)
        S_cand = _stft_mag(b, n_fft=n_fft, hop_length=hop)
        total += _per_resolution_loss(
            S_ref,
            S_cand,
            w_sc=w_sc,
            w_log=w_log,
            eps=eps,
            frame_weight=frame_weight,
        )
        n += 1
    if n == 0:
        return 0.0
    return float(max(0.0, total / n))


__all__ = ["mr_stft_distance", "DEFAULT_FFT_SIZES"]
