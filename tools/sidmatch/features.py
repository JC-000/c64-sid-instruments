"""Audio feature extraction for SID instrument matching.

Takes a mono/stereo audio buffer at any sample rate and produces a
FeatureVec suitable for comparison via :mod:`sidmatch.fitness`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
from scipy.signal import resample_poly
from math import gcd


# Canonical analysis parameters.
CANONICAL_SR = 22050
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
    log_mel: Optional[tuple] = None  # tuple of 2D arrays (n_mels × n_frames), one per scale
    onset_energy_ratio: float = 0.0  # spectral flux ratio: onset vs whole-note average
    onset_log_mel: Optional[tuple] = None  # log-mel slices for onset region only
    mfcc: Optional[np.ndarray] = None  # shape (13, n_frames) or None
    stft_mag: Optional[np.ndarray] = None  # magnitude STFT for spectral convergence

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


# ---------------------------------------------------------------------------
# Pure numpy/scipy replacements for librosa hot-path functions
# ---------------------------------------------------------------------------

def _resample_audio(y: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio using scipy.signal.resample_poly (integer-ratio)."""
    if orig_sr == target_sr:
        return y
    g = gcd(int(orig_sr), int(target_sr))
    up = target_sr // g
    down = orig_sr // g
    return resample_poly(y, up, down).astype(np.float32)


def _stft_mag(y: np.ndarray, n_fft: int, hop_length: int) -> np.ndarray:
    """Compute magnitude STFT using numpy (matching librosa's center-pad convention).

    Returns shape (1 + n_fft//2, n_frames).
    """
    # Center-pad the signal (librosa default).
    pad_len = n_fft // 2
    y_padded = np.pad(y, (pad_len, pad_len), mode='reflect')

    # Hann window
    window = np.hanning(n_fft + 1)[:n_fft].astype(np.float32)

    n_frames = 1 + (len(y_padded) - n_fft) // hop_length
    if n_frames <= 0:
        return np.zeros((1 + n_fft // 2, 0), dtype=np.float32)

    # Build frame matrix and apply window + FFT
    indices = np.arange(n_fft)[None, :] + (np.arange(n_frames) * hop_length)[:, None]
    frames = y_padded[indices] * window[None, :]
    S = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)).T  # (freq_bins, n_frames)
    return S.astype(np.float32)


def _fft_frequencies(sr: int, n_fft: int) -> np.ndarray:
    """Equivalent to librosa.fft_frequencies."""
    return np.fft.rfftfreq(n_fft, d=1.0 / sr)


def _rms_from_stft(S: np.ndarray) -> np.ndarray:
    """RMS per frame from magnitude STFT. Returns shape (n_frames,)."""
    return np.sqrt(np.mean(S ** 2, axis=0))


def _rms_frames(y: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    """Compute RMS per frame directly from audio (no STFT needed)."""
    # Center-pad like librosa
    pad_len = frame_length // 2
    y_padded = np.pad(y, (pad_len, pad_len), mode='reflect')

    n_frames = 1 + (len(y_padded) - frame_length) // hop_length
    if n_frames <= 0:
        return np.zeros(0, dtype=np.float32)

    indices = np.arange(frame_length)[None, :] + (np.arange(n_frames) * hop_length)[:, None]
    frames = y_padded[indices]
    return np.sqrt(np.mean(frames ** 2, axis=1)).astype(np.float32)


def _spectral_centroid(S: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Spectral centroid per frame. Returns shape (n_frames,)."""
    S_sum = S.sum(axis=0)
    S_sum = np.where(S_sum == 0, 1.0, S_sum)  # avoid division by zero
    return (freqs[:, None] * S).sum(axis=0) / S_sum


def _spectral_rolloff(S: np.ndarray, freqs: np.ndarray, roll_percent: float = 0.85) -> np.ndarray:
    """Spectral rolloff per frame. Returns shape (n_frames,)."""
    cumsum = np.cumsum(S, axis=0)
    total = cumsum[-1:, :]  # shape (1, n_frames)
    threshold = roll_percent * total
    # For each frame, find first freq bin where cumsum >= threshold
    n_frames = S.shape[1]
    rolloff = np.zeros(n_frames, dtype=np.float64)
    for i in range(n_frames):
        if total[0, i] <= 0:
            rolloff[i] = 0.0
            continue
        above = np.where(cumsum[:, i] >= threshold[0, i])[0]
        if above.size:
            rolloff[i] = freqs[above[0]]
        else:
            rolloff[i] = freqs[-1]
    return rolloff


def _spectral_flatness(S: np.ndarray) -> np.ndarray:
    """Spectral flatness per frame. Returns shape (n_frames,)."""
    eps = 1e-10
    S_pos = np.maximum(S, eps)
    geo_mean = np.exp(np.mean(np.log(S_pos), axis=0))
    arith_mean = np.mean(S_pos, axis=0)
    return (geo_mean / arith_mean).astype(np.float64)


def _trim_silence(y: np.ndarray, top_db: float = 60.0, frame_length: int = 2048, hop_length: int = 512) -> np.ndarray:
    """Trim leading/trailing silence based on RMS threshold.

    Equivalent to librosa.effects.trim but uses numpy directly.
    Returns trimmed audio (no index tuple).
    """
    if y.size == 0:
        return y

    rms = _rms_frames(y, frame_length, hop_length)
    if rms.size == 0 or rms.max() <= 0:
        return y

    # Convert top_db threshold to linear
    rms_max = rms.max()
    threshold = rms_max * 10.0 ** (-top_db / 20.0)

    above = np.where(rms >= threshold)[0]
    if above.size == 0:
        return y

    first_frame = int(above[0])
    last_frame = int(above[-1])

    start_sample = first_frame * hop_length
    # End sample: last active frame center + half frame
    end_sample = min(y.size, last_frame * hop_length + frame_length)

    trimmed = y[start_sample:end_sample]
    return trimmed if trimmed.size > 0 else y


# ---------------------------------------------------------------------------
# Mel filterbank and multi-scale log-mel spectrogram
# ---------------------------------------------------------------------------

def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def _mel_filterbank(sr: int, n_fft: int, n_mels: int = 64) -> np.ndarray:
    """Create a mel filterbank matrix of shape (n_mels, 1 + n_fft // 2)."""
    n_freqs = 1 + n_fft // 2
    fmin = 0.0
    fmax = sr / 2.0

    # Mel-spaced center frequencies
    mel_min = _hz_to_mel(np.array(fmin))
    mel_max = _hz_to_mel(np.array(fmax))
    mel_points = np.linspace(float(mel_min), float(mel_max), n_mels + 2)
    hz_points = _mel_to_hz(mel_points)

    # FFT bin frequencies
    fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    filterbank = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        lo, center, hi = hz_points[i], hz_points[i + 1], hz_points[i + 2]
        # Rising slope
        if center > lo:
            up = (fft_freqs - lo) / (center - lo)
        else:
            up = np.zeros_like(fft_freqs)
        # Falling slope
        if hi > center:
            down = (hi - fft_freqs) / (hi - center)
        else:
            down = np.zeros_like(fft_freqs)
        filterbank[i] = np.maximum(0.0, np.minimum(up, down))

    return filterbank


def _compute_log_mel_specs(y: np.ndarray, sr: int, n_mels: int = 64) -> tuple:
    """Compute multi-scale log-mel spectrograms (FFT 512 and 2048).

    Returns a tuple of two 2-D arrays, each of shape (n_mels, n_frames).
    """
    scales = [
        (512, 256),    # (n_fft, hop_length)
        (2048, 512),
    ]
    results = []
    for n_fft, hop in scales:
        S = _stft_mag(y, n_fft=n_fft, hop_length=hop)
        fb = _mel_filterbank(sr, n_fft, n_mels)
        mel_spec = fb @ S  # (n_mels, n_frames)
        # Use log compression with a floor to avoid extreme values in
        # quiet bands that amplify rendering jitter.
        log_mel = np.log(np.maximum(mel_spec, 1e-4) + 1e-7)
        results.append(log_mel.astype(np.float32))
    return tuple(results)


# ---------------------------------------------------------------------------
# Onset spectral flux and MFCC helpers
# ---------------------------------------------------------------------------


def _spectral_flux(S: np.ndarray) -> np.ndarray:
    """Frame-to-frame L2 spectral change. Returns shape (n_frames,)."""
    if S.shape[1] < 2:
        return np.zeros(max(S.shape[1], 0), dtype=np.float64)
    diff = np.diff(S, axis=1)
    flux = np.sqrt(np.sum(diff ** 2, axis=0))
    # Prepend 0 for the first frame so length matches n_frames
    return np.concatenate([[0.0], flux])


def _onset_features(y: np.ndarray, sr: int, n_mels: int = 64,
                     onset_ms: float = 50.0) -> tuple:
    """Compute onset energy ratio and onset log-mel spectrograms.

    Returns (onset_energy_ratio, onset_log_mel_tuple).
    onset_energy_ratio: spectral flux in the first onset_ms divided by
                        whole-note average spectral flux.
    onset_log_mel_tuple: tuple of 2-D arrays (n_mels, onset_frames) for
                         each mel scale (512 and 2048 FFT).
    """
    onset_samples = int(sr * onset_ms / 1000.0)
    if y.size < onset_samples or y.size < 512:
        return 0.0, None

    scales = [
        (512, 256),
        (2048, 512),
    ]

    # Compute spectral flux ratio using the fine-grained scale (512 FFT)
    S_full = _stft_mag(y, n_fft=512, hop_length=256)
    flux = _spectral_flux(S_full)
    if flux.size == 0 or float(np.mean(flux)) < 1e-12:
        onset_ratio = 0.0
    else:
        onset_frames_512 = max(1, onset_samples // 256)
        onset_flux = float(np.mean(flux[:onset_frames_512])) if onset_frames_512 <= flux.size else float(np.mean(flux))
        avg_flux = float(np.mean(flux))
        onset_ratio = onset_flux / max(avg_flux, 1e-12)

    # Compute onset log-mel for each scale
    onset_mels = []
    for n_fft, hop in scales:
        onset_frames = max(1, onset_samples // hop)
        S = _stft_mag(y, n_fft=n_fft, hop_length=hop)
        # Take only onset frames
        S_onset = S[:, :onset_frames]
        fb = _mel_filterbank(sr, n_fft, n_mels)
        mel_spec = fb @ S_onset
        log_mel = np.log(np.maximum(mel_spec, 1e-4) + 1e-7)
        onset_mels.append(log_mel.astype(np.float32))

    return float(onset_ratio), tuple(onset_mels)


def _compute_mfcc(y: np.ndarray, sr: int, n_mfcc: int = 13) -> np.ndarray:
    """Compute MFCCs using the DCT of log-mel spectrogram.

    Returns shape (n_mfcc, n_frames).
    Uses scipy DCT to avoid librosa dependency for this step.
    """
    from scipy.fft import dct

    # Use the 2048-FFT log-mel as the basis
    S = _stft_mag(y, n_fft=2048, hop_length=512)
    n_mels = 64
    fb = _mel_filterbank(sr, 2048, n_mels)
    mel_spec = fb @ S
    log_mel = np.log(np.maximum(mel_spec, 1e-10) + 1e-7)

    # DCT-II along the mel axis for each frame
    mfcc = dct(log_mel, type=2, axis=0, norm='ortho')[:n_mfcc, :]
    return mfcc.astype(np.float32)


# ---------------------------------------------------------------------------
# harmonic magnitudes (kept mostly as-is, but uses _fft_frequencies)
# ---------------------------------------------------------------------------

def _harmonic_magnitudes(
    y: np.ndarray, sr: int, f0: float, n_harmonics: int = N_HARMONICS,
    S: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Average magnitudes of the first ``n_harmonics`` partials.

    Estimated from a magnitude STFT by picking the bin nearest each partial.
    Returns a length-n_harmonics vector normalized so the max equals 1
    (or all zeros if no energy is present).
    """
    if f0 <= 0.0 or not np.isfinite(f0):
        return np.zeros(n_harmonics, dtype=np.float64)

    if S is None:
        S = _stft_mag(y, n_fft=N_FFT, hop_length=_hop_length(sr))
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

    freqs = _fft_frequencies(sr=sr, n_fft=N_FFT)
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
    """Median f0 over voiced frames using YIN (librosa fallback)."""
    if y.size < 2048:
        return 0.0
    try:
        import librosa
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
# lightweight extraction for early rejection

def extract_lite(audio: np.ndarray, sr: int, known_f0: float) -> FeatureVec:
    """Lightweight feature extraction for early rejection.

    Computes only envelope, ADSR, harmonics, and fundamental (from known_f0).
    Spectral centroid/rolloff/flatness and noisiness are zeroed.
    """
    y = _to_mono(audio)
    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        raise ValueError("audio is empty")

    if sr != CANONICAL_SR:
        y = _resample_audio(y, orig_sr=sr, target_sr=CANONICAL_SR)
    work_sr = CANONICAL_SR

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

    y_trim = _trim_silence(y, top_db=-SILENCE_DB)
    if y_trim.size < 256:
        y_trim = y
    duration_s = float(y_trim.size / work_sr)
    hop = _hop_length(work_sr)

    # Envelope via direct RMS (no STFT needed)
    rms = _rms_frames(y_trim, frame_length=N_FFT, hop_length=hop)
    rms_max = float(rms.max()) if rms.size else 0.0
    env_norm = rms / rms_max if rms_max > 0 else rms
    env_resampled = _resample_series(env_norm)

    # ADSR (cheap: runs on the envelope, no FFT needed)
    hop_s = hop / work_sr
    attack_s, decay_s, sustain_level, release_s = _detect_adsr(env_norm, hop_s)

    # Harmonics (single STFT)
    S_mag = _stft_mag(y_trim, n_fft=N_FFT, hop_length=hop)
    harmonics = _harmonic_magnitudes(y_trim, work_sr, known_f0, S=S_mag)

    return FeatureVec(
        sr=work_sr,
        duration_s=duration_s,
        amplitude_envelope=env_resampled.astype(np.float64),
        attack_time_s=attack_s,
        decay_time_s=decay_s,
        sustain_level=sustain_level,
        release_time_s=release_s,
        harmonic_magnitudes=harmonics.astype(np.float64),
        spectral_centroid=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
        spectral_rolloff=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
        spectral_flatness=np.zeros(TIME_SERIES_FRAMES, dtype=np.float64),
        fundamental_hz=float(known_f0),
        noisiness=0.0,
    )


# ---------------------------------------------------------------------------
# main entrypoint

def extract(audio: np.ndarray, sr: int, *, known_f0: Optional[float] = None) -> FeatureVec:
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
        y = _resample_audio(y, orig_sr=sr, target_sr=CANONICAL_SR)
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
            log_mel=None,
        )

    # Trim silence.
    y_trim = _trim_silence(y, top_db=-SILENCE_DB)
    if y_trim.size < 256:
        y_trim = y  # too short to trim; keep original
    duration_s = float(y_trim.size / work_sr)

    hop = _hop_length(work_sr)

    # Amplitude envelope (RMS per hop), normalized.
    rms = _rms_frames(y_trim, frame_length=N_FFT, hop_length=hop)
    rms_max = float(rms.max()) if rms.size else 0.0
    env_norm = rms / rms_max if rms_max > 0 else rms
    env_resampled = _resample_series(env_norm)

    # ADSR from un-resampled envelope so time units remain meaningful.
    hop_s = hop / work_sr
    attack_s, decay_s, sustain_level, release_s = _detect_adsr(env_norm, hop_s)

    # Spectral features.
    S_mag = _stft_mag(y_trim, n_fft=N_FFT, hop_length=hop)
    freqs = _fft_frequencies(sr=work_sr, n_fft=N_FFT)
    centroid = _spectral_centroid(S_mag, freqs)
    rolloff = _spectral_rolloff(S_mag, freqs, roll_percent=0.85)
    flatness = _spectral_flatness(S_mag)

    # Fundamental estimation.
    f0 = known_f0 if known_f0 is not None else _estimate_f0(y_trim, work_sr)

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
        # Slice the already-computed STFT to the sustain frames.
        S_sustain = S_mag[:, sus_start:sus_end + 1]
        harmonics = _harmonic_magnitudes(y_trim, work_sr, f0, S=S_sustain)
    else:
        harmonics = _harmonic_magnitudes(y_trim, work_sr, f0, S=S_mag)

    # Noisiness: mean spectral flatness over the sustain region.
    noisiness = float(np.mean(flatness)) if flatness.size else 0.0

    # Multi-scale log-mel spectrograms.
    log_mel = _compute_log_mel_specs(y_trim, work_sr)

    # Onset spectral features.
    onset_ratio, onset_log_mel = _onset_features(y_trim, work_sr)

    # MFCCs (13 coefficients per frame).
    mfcc = _compute_mfcc(y_trim, work_sr)

    # Magnitude STFT for spectral convergence (reuse the already-computed one).
    # S_mag was computed with N_FFT and hop; store it for spectral convergence.
    stft_mag_out = S_mag

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
        log_mel=log_mel,
        onset_energy_ratio=onset_ratio,
        onset_log_mel=onset_log_mel,
        mfcc=mfcc,
        stft_mag=stft_mag_out,
    )
