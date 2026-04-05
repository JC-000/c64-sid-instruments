"""Audio feature extraction for SID instrument matching.

Takes a mono/stereo audio buffer at any sample rate and produces a
FeatureVec suitable for comparison via :mod:`sidmatch.fitness`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import librosa


# Canonical analysis parameters.
CANONICAL_SR = 44100
HOP_MS = 10.0  # ~10 ms hop for envelope / spectral time series
N_FFT = 2048
N_HARMONICS = 16
TIME_SERIES_FRAMES = 128  # resample all time series to this many frames
SILENCE_DB = -60.0  # trim threshold


@dataclass
class FeatureVec:
    """Bundle of features describing a single monophonic note.

    Fields
    ------
    sr: canonical sample rate used for analysis.
    duration_s: duration after silence trimming.
    amplitude_envelope: normalized RMS per hop (1-D, length TIME_SERIES_FRAMES).
    attack_time_s / decay_time_s / sustain_level / release_time_s:
        heuristic ADSR points derived from the envelope.
    harmonic_magnitudes: relative magnitudes of the first N_HARMONICS partials,
        averaged over the sustain region and normalized so max == 1.
    spectral_centroid / spectral_rolloff / spectral_flatness:
        time series resampled to TIME_SERIES_FRAMES.
    fundamental_hz: median estimated f0 (Hz) over the tonal region.
    noisiness: mean spectral flatness over the sustain region in [0, 1].
    """

    sr: int
    duration_s: float
    amplitude_envelope: np.ndarray
    attack_time_s: float
    decay_time_s: float
    sustain_level: float
    release_time_s: float
    harmonic_magnitudes: np.ndarray
    spectral_centroid: np.ndarray
    spectral_rolloff: np.ndarray
    spectral_flatness: np.ndarray
    fundamental_hz: float
    noisiness: float

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, np.ndarray):
                d[k] = v.tolist()
        return d


# ---------------------------------------------------------------------------
# helpers

def _to_mono(audio: np.ndarray) -> np.ndarray:
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim == 1:
        return a
    if a.ndim == 2:
        # librosa convention: (channels, samples) OR (samples, channels)
        # Assume smaller dim is channels.
        if a.shape[0] <= 8 and a.shape[0] < a.shape[1]:
            return a.mean(axis=0)
        return a.mean(axis=1)
    raise ValueError(f"unsupported audio ndim={a.ndim}")


def _resample_series(x: np.ndarray, n: int = TIME_SERIES_FRAMES) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size == 0:
        return np.zeros(n, dtype=np.float64)
    if x.size == n:
        return x
    # linear interpolation onto n evenly-spaced points
    old_idx = np.linspace(0.0, 1.0, num=x.size)
    new_idx = np.linspace(0.0, 1.0, num=n)
    return np.interp(new_idx, old_idx, x)


def _detect_adsr(env: np.ndarray, hop_s: float) -> tuple:
    """Heuristic ADSR from a normalized amplitude envelope.

    env must be scaled to roughly [0, 1]. Returns
    (attack_s, decay_s, sustain_level, release_s).
    """
    if env.size == 0 or float(env.max()) <= 1e-8:
        return 0.0, 0.0, 0.0, 0.0

    peak_idx = int(np.argmax(env))
    peak_val = float(env[peak_idx])

    # Attack: from first crossing of 10% of peak to peak.
    thr_lo = 0.1 * peak_val
    try:
        start_idx = int(np.argmax(env >= thr_lo))
    except ValueError:
        start_idx = 0
    attack_s = max(0.0, (peak_idx - start_idx) * hop_s)

    # Sustain: median of the middle 60% after the peak (but before the
    # tail drops below 10% of peak).
    tail = env[peak_idx:]
    if tail.size <= 2:
        sustain_level = peak_val
        decay_s = 0.0
        release_s = 0.0
    else:
        below = np.where(tail < 0.1 * peak_val)[0]
        end_rel = int(below[0]) if below.size else int(tail.size - 1)
        if end_rel < 2:
            sustain_level = float(tail[-1])
            decay_s = 0.0
            release_s = 0.0
        else:
            mid_a = max(1, end_rel // 4)
            mid_b = max(mid_a + 1, (3 * end_rel) // 4)
            sustain_level = float(np.median(tail[mid_a:mid_b]))
            # Decay: time from peak to where envelope first reaches sustain.
            decay_mask = tail[:mid_b] <= sustain_level
            if decay_mask.any():
                decay_rel = int(np.argmax(decay_mask))
            else:
                decay_rel = mid_a
            decay_s = max(0.0, decay_rel * hop_s)
            # Release: from sustain region end to <10% of peak.
            release_s = max(0.0, (end_rel - mid_b) * hop_s)

    return float(attack_s), float(decay_s), float(sustain_level), float(release_s)


def _harmonic_magnitudes(
    y: np.ndarray, sr: int, f0: float, n_harmonics: int = N_HARMONICS
) -> np.ndarray:
    """Average magnitudes of the first ``n_harmonics`` partials.

    Estimated from a magnitude STFT by picking the bin nearest each partial.
    Returns a length-n_harmonics vector normalized so the max equals 1
    (or all zeros if no energy is present).
    """
    if f0 <= 0.0 or not np.isfinite(f0):
        return np.zeros(n_harmonics, dtype=np.float64)

    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=_hop_length(sr)))
    if S.size == 0:
        return np.zeros(n_harmonics, dtype=np.float64)

    # Average magnitude per frequency bin over time (focus on loud frames).
    frame_energy = S.sum(axis=0)
    if frame_energy.max() <= 0.0:
        return np.zeros(n_harmonics, dtype=np.float64)
    keep = frame_energy >= 0.25 * frame_energy.max()
    if not keep.any():
        keep = slice(None)
    mean_mag = S[:, keep].mean(axis=1)

    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    nyq = sr / 2.0
    out = np.zeros(n_harmonics, dtype=np.float64)
    # Tolerance for bin picking: half a semitone around each partial.
    for k in range(1, n_harmonics + 1):
        target = f0 * k
        if target >= nyq:
            break
        # pick peak within +/- 50 cents window
        lo = target * 2 ** (-0.5 / 12)
        hi = target * 2 ** (0.5 / 12)
        mask = (freqs >= lo) & (freqs <= hi)
        if not mask.any():
            # fallback to nearest bin
            idx = int(np.argmin(np.abs(freqs - target)))
            out[k - 1] = mean_mag[idx]
        else:
            out[k - 1] = float(mean_mag[mask].max())

    m = out.max()
    if m > 0:
        out = out / m
    return out


def _hop_length(sr: int) -> int:
    return max(1, int(round(sr * HOP_MS / 1000.0)))


def _estimate_f0(y: np.ndarray, sr: int) -> float:
    """Median f0 over voiced frames using YIN."""
    if y.size < 2048:
        return 0.0
    try:
        f0 = librosa.yin(
            y,
            fmin=50.0,
            fmax=min(4000.0, sr / 2.0 - 1.0),
            sr=sr,
            frame_length=2048,
            hop_length=_hop_length(sr),
        )
    except Exception:
        return 0.0
    f0 = f0[np.isfinite(f0) & (f0 > 0)]
    if f0.size == 0:
        return 0.0
    return float(np.median(f0))


# ---------------------------------------------------------------------------
# main entrypoint

def extract(audio: np.ndarray, sr: int) -> FeatureVec:
    """Extract a :class:`FeatureVec` from a raw audio buffer.

    Parameters
    ----------
    audio : np.ndarray
        Mono or stereo waveform (float-like). Shape (N,), (N, 2) or (2, N).
    sr : int
        Input sample rate, in Hz.
    """
    if audio is None:
        raise ValueError("audio is None")
    y = _to_mono(audio)
    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        raise ValueError("audio is empty")
    if not np.all(np.isfinite(y)):
        raise ValueError("audio contains non-finite samples")

    # Resample to canonical rate.
    if sr != CANONICAL_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=CANONICAL_SR)
    work_sr = CANONICAL_SR

    # Handle all-zero / silent input: return a zeroed FeatureVec.
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak <= 1e-9:
        return FeatureVec(
            sr=work_sr,
            duration_s=float(y.size / work_sr),
            amplitude_envelope=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
            attack_time_s=0.0,
            decay_time_s=0.0,
            sustain_level=0.0,
            release_time_s=0.0,
            harmonic_magnitudes=np.zeros(N_HARMONICS, dtype=np.float64),
            spectral_centroid=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
            spectral_rolloff=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
            spectral_flatness=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
            fundamental_hz=0.0,
            noisiness=0.0,
        )

    # Trim silence.
    y_trim, _ = librosa.effects.trim(y, top_db=-SILENCE_DB)
    if y_trim.size < 256:
        y_trim = y  # too short to trim; keep original
    duration_s = float(y_trim.size / work_sr)

    hop = _hop_length(work_sr)

    # Amplitude envelope (RMS per hop), normalized.
    rms = librosa.feature.rms(y=y_trim, frame_length=N_FFT, hop_length=hop)[0]
    rms_max = float(rms.max()) if rms.size else 0.0
    env_norm = rms / rms_max if rms_max > 0 else rms
    env_resampled = _resample_series(env_norm)

    # ADSR from un-resampled envelope so time units remain meaningful.
    hop_s = hop / work_sr
    attack_s, decay_s, sustain_level, release_s = _detect_adsr(env_norm, hop_s)

    # Spectral features.
    S_mag = np.abs(librosa.stft(y_trim, n_fft=N_FFT, hop_length=hop))
    centroid = librosa.feature.spectral_centroid(
        S=S_mag, sr=work_sr, n_fft=N_FFT, hop_length=hop
    )[0]
    rolloff = librosa.feature.spectral_rolloff(
        S=S_mag, sr=work_sr, n_fft=N_FFT, hop_length=hop, roll_percent=0.85
    )[0]
    flatness = librosa.feature.spectral_flatness(
        S=S_mag, n_fft=N_FFT, hop_length=hop
    )[0]

    # Fundamental estimation.
    f0 = _estimate_f0(y_trim, work_sr)

    # Harmonic magnitudes over sustain region if we have one, else whole signal.
    if env_norm.size > 4:
        peak_frame = int(np.argmax(env_norm))
        # sustain = from peak to last frame above 20% of peak
        above = np.where(env_norm[peak_frame:] > 0.2)[0]
        if above.size:
            sus_end = peak_frame + int(above[-1])
        else:
            sus_end = env_norm.size - 1
        sus_start = peak_frame
        if sus_end - sus_start < 2:
            sus_start, sus_end = 0, env_norm.size - 1
        # Convert frame indices to sample indices.
        a = sus_start * hop
        b = min(y_trim.size, (sus_end + 1) * hop)
        sus_sig = y_trim[a:b] if b > a + N_FFT else y_trim
    else:
        sus_sig = y_trim

    harmonics = _harmonic_magnitudes(sus_sig, work_sr, f0)

    # Noisiness: mean spectral flatness over the sustain region.
    noisiness = float(np.mean(flatness)) if flatness.size else 0.0

    return FeatureVec(
        sr=work_sr,
        duration_s=duration_s,
        amplitude_envelope=env_resampled.astype(np.float64),
        attack_time_s=attack_s,
        decay_time_s=decay_s,
        sustain_level=sustain_level,
        release_time_s=release_s,
        harmonic_magnitudes=harmonics.astype(np.float64),
        spectral_centroid=_resample_series(centroid),
        spectral_rolloff=_resample_series(rolloff),
        spectral_flatness=_resample_series(flatness),
        fundamental_hz=float(f0),
        noisiness=noisiness,
    )
