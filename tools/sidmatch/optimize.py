"""CMA-ES optimizer for SID instrument matching.

Exposes a continuous-parameter optimizer that searches SID patch space
for a patch whose rendered audio matches a reference WAV (as scored by
:func:`sidmatch.fitness.distance`).

The decision vector is continuous. Discrete fields (waveform,
filter_mode, wt_use_test_bit, wt_attack_waveform) are fixed per run
and passed via ``fixed_kwargs``.
"""

from __future__ import annotations

import itertools
import json
import multiprocessing as mp
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

import numpy as np
import soundfile as sf
import librosa
import cma

from .render import (
    SidParams,
    render_pyresid,
    compute_gate_release,
    ATTACK_MS,
    DECAY_RELEASE_MS,
)
from .features import FeatureVec, extract, extract_lite, CANONICAL_SR
from .fitness import distance, distance_lite
from .surrogate import FitnessSurrogate


# ---------------------------------------------------------------------------
# Decision-vector layout (13 continuous dimensions)
# ---------------------------------------------------------------------------
#
# x[0]  attack              0..15
# x[1]  decay               0..15
# x[2]  sustain             0..15
# x[3]  release             0..15
# x[4]  pw_start            0..4095
# x[5]  pw_delta            -50..+50
# x[6]  pw_center           0..4095   (midpoint of PW sweep range)
# x[7]  pw_width            0..4095   (full width of PW range)
# x[8]  log_cutoff_start    0..11     (log2-scale filter cutoff)
# x[9]  log_cutoff_end      0..11     (log2-scale filter cutoff)
# x[10] filter_sweep_frames 0..100
# x[11] filter_resonance    0..15
# x[12] wt_attack_frames    1..5
#
# Discrete (fixed_kwargs): wt_sustain_waveform, wt_attack_waveform,
# filter_mode, wt_use_test_bit, volume, frequency, chip_model, pw_mode.
# ---------------------------------------------------------------------------

BOUNDS_LOW = np.array(
    [0.0, 0.0, 0.0, 0.0,     # ADSR
     0.0, -50.0, 0.0, 0.0,   # PW sweep (pw_start, pw_delta, pw_center, pw_width)
     0.0, 0.0, 0.0,          # filter sweep (log_cutoff_start, log_cutoff_end, frames)
     0.0,                     # filter resonance
     1.0],                    # wt_attack_frames
    dtype=np.float64,
)
BOUNDS_HIGH = np.array(
    [15.0, 15.0, 15.0, 15.0,        # ADSR
     4095.0, 50.0, 4095.0, 4095.0,  # PW sweep (pw_start, pw_delta, pw_center, pw_width)
     11.0, 11.0, 100.0,             # filter sweep (log_cutoff_start, log_cutoff_end, frames)
     15.0,                           # filter resonance
     5.0],                           # wt_attack_frames
    dtype=np.float64,
)
N_DIMS = BOUNDS_LOW.size

_PARAM_NAMES = [
    "attack",
    "decay",
    "sustain",
    "release",
    "pw_start",
    "pw_delta",
    "pw_center",
    "pw_width",
    "log_cutoff_start",
    "log_cutoff_end",
    "filter_sweep_frames",
    "filter_resonance",
    "wt_attack_frames",
]


def _clip_int(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(float(v)))))


# ---------------------------------------------------------------------------
# Active-parameter helpers for search-space trimming
# ---------------------------------------------------------------------------

# Index constants for the 13-element decision vector.
_IDX_ADSR = [0, 1, 2, 3]           # attack, decay, sustain, release
_IDX_PW = [4, 5, 6, 7]             # pw_start, pw_delta, pw_center, pw_width
_IDX_FILTER = [8, 9, 10, 11]       # log_cutoff_start/end, sweep_frames, resonance
_IDX_WT_ATTACK = [12]              # wt_attack_frames

# Indices of integer-valued parameters (for TPE suggest_int).
_INTEGER_PARAM_INDICES = frozenset([0, 1, 2, 3, 11, 12])  # ADSR + resonance + wt_attack_frames

# Mid-range defaults for inactive dimensions (used when expanding reduced vectors).
_MIDPOINT = 0.5 * (BOUNDS_LOW + BOUNDS_HIGH)


def active_params(fixed_kwargs: dict) -> list:
    """Return indices (into the 13-element vector) of parameters that matter.

    Parameters that are irrelevant for the given discrete combo are excluded
    so CMA-ES can focus covariance adaptation on the dimensions that actually
    affect the rendered audio.

    Rules:
      - ADSR (0-3) and wt_attack_frames (12) are always active.
      - PW params (4-7) are active only when pulse waveform is used
        (sustain is pulse, or attack waveform contains "pulse").
      - Filter params (8-11) are active only when filter_mode != "off".
    """
    indices = list(_IDX_ADSR)  # always include ADSR

    # PW params: needed when any waveform involves pulse
    sustain_wf = fixed_kwargs.get("wt_sustain_waveform") or ""
    attack_wf = fixed_kwargs.get("wt_attack_waveform") or ""
    needs_pw = sustain_wf == "pulse" or "pulse" in attack_wf
    # Also check multi-step wavetable for any pulse waveform
    wt_steps = fixed_kwargs.get("wavetable_steps")
    if wt_steps:
        for wf_name, _dur in wt_steps:
            if "pulse" in wf_name:
                needs_pw = True
                break
    if needs_pw:
        indices.extend(_IDX_PW)

    # Filter params: needed when filter is active
    if fixed_kwargs.get("filter_mode") != "off":
        indices.extend(_IDX_FILTER)

    indices.extend(_IDX_WT_ATTACK)  # always include
    return sorted(indices)


def _expand_vector(x_reduced: np.ndarray, active_idx: list,
                   bounds_high: np.ndarray) -> np.ndarray:
    """Expand a reduced vector back to full N_DIMS using mid-range defaults.

    Inactive dimensions get the midpoint of their bounds range.
    """
    midpoint = 0.5 * (BOUNDS_LOW + bounds_high)
    full = midpoint.copy()
    for i, idx in enumerate(active_idx):
        full[idx] = x_reduced[i]
    return full


def _reduce_vector(x_full: np.ndarray, active_idx: list) -> np.ndarray:
    """Extract only the active dimensions from a full vector."""
    return x_full[active_idx].copy()


def _surrogate_adsr_sweep(
    surrogate: "FitnessSurrogate",
    best_x_norm: np.ndarray,
    active_idx: list,
    bounds_low_active: np.ndarray,
    bounds_high_active: np.ndarray,
    top_n: int = 20,
) -> np.ndarray:
    """Sweep all 65,536 ADSR combos via surrogate, return top-N candidates.

    Parameters
    ----------
    surrogate : FitnessSurrogate
        Trained surrogate model.
    best_x_norm : ndarray, shape (n_active,)
        Current best normalized parameter vector (in [0, 1] space).
    active_idx : list of int
        Indices (into the 13-element full vector) that are active.
    bounds_low_active : ndarray
        Lower bounds for active dimensions (original scale).
    bounds_high_active : ndarray
        Upper bounds for active dimensions (original scale).
    top_n : int
        Number of top candidates to return.

    Returns
    -------
    ndarray, shape (top_n, n_active)
        Top-N normalized vectors sorted by predicted fitness (best first).
    """
    n_active = len(active_idx)
    range_active = bounds_high_active - bounds_low_active
    range_safe = np.where(range_active > 0, range_active, 1.0)

    # Find which positions in the reduced/active vector correspond to ADSR
    # (original indices 0-3).
    adsr_positions = []
    for pos, orig_idx in enumerate(active_idx):
        if orig_idx in (0, 1, 2, 3):
            adsr_positions.append(pos)

    if not adsr_positions:
        # No ADSR params active (shouldn't happen, but be safe).
        return best_x_norm.reshape(1, -1)

    # Determine per-ADSR ranges (integer bounds).
    adsr_ranges = []
    for pos in adsr_positions:
        lo = int(bounds_low_active[pos])
        hi = int(bounds_high_active[pos])
        adsr_ranges.append(range(lo, hi + 1))

    # Generate all ADSR combos.
    all_combos = np.array(list(itertools.product(*adsr_ranges)), dtype=np.float64)
    n_combos = all_combos.shape[0]

    # Tile the current best into (n_combos, n_active) and replace ADSR cols.
    candidates = np.tile(best_x_norm, (n_combos, 1))
    for col_i, pos in enumerate(adsr_positions):
        # Normalize the integer ADSR value to [0, 1].
        candidates[:, pos] = (all_combos[:, col_i] - bounds_low_active[pos]) / range_safe[pos]

    # Batch predict.
    predicted = surrogate.predict(candidates)

    # Return top-N by predicted fitness (lower is better).
    top_indices = np.argsort(predicted)[:top_n]
    return candidates[top_indices]


def compute_render_duration(attack: int, decay: int, sustain: int, release: int) -> Tuple[int, int]:
    """Compute gate_frames and release_frames so full ADSR plays out.

    This is a convenience wrapper around render.compute_gate_release that
    is accessible from the optimize module.
    """
    return compute_gate_release(attack, decay, sustain, release)


def encode_params(sid_params: SidParams) -> np.ndarray:
    """Encode a :class:`SidParams` into a continuous decision vector.

    Discrete/categorical fields are dropped (caller must keep them in
    ``fixed_kwargs``). Returns a float64 array of length ``N_DIMS``.
    """
    x = np.zeros(N_DIMS, dtype=np.float64)
    x[0] = sid_params.attack
    x[1] = sid_params.decay
    x[2] = sid_params.sustain
    x[3] = sid_params.release
    x[4] = sid_params.effective_pw_start()
    x[5] = sid_params.pw_delta
    # Encode pw_min/pw_max as pw_center/pw_width
    pw_min = sid_params.pw_min
    pw_max = sid_params.pw_max
    x[6] = (pw_min + pw_max) / 2.0        # pw_center
    x[7] = float(pw_max - pw_min)          # pw_width
    # Encode filter cutoff in log2 space
    cutoff_start = sid_params.effective_filter_cutoff_start()
    cutoff_end = sid_params.effective_filter_cutoff_end()
    x[8] = np.log2(cutoff_start + 1.0)    # log_cutoff_start
    x[9] = np.log2(cutoff_end + 1.0)      # log_cutoff_end
    x[10] = sid_params.filter_sweep_frames
    x[11] = sid_params.filter_resonance
    x[12] = sid_params.wt_attack_frames
    return x


def decode_params(x: np.ndarray, fixed_kwargs: Mapping) -> SidParams:
    """Decode a decision vector plus ``fixed_kwargs`` into a SidParams.

    Continuous values are clipped-and-rounded to the appropriate integer
    range. Gate and release frames are computed from ADSR timing.

    If ``fixed_kwargs`` contains ``_min_gate_frames``, the computed
    ``gate_frames`` is clamped from below to that value.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size != N_DIMS:
        raise ValueError(f"expected {N_DIMS} dims, got {x.size}")

    attack = _clip_int(x[0], 0, 15)
    decay = _clip_int(x[1], 0, 15)
    sustain = _clip_int(x[2], 0, 15)
    release = _clip_int(x[3], 0, 15)
    pw_start = _clip_int(x[4], 0, 4095)
    pw_delta = _clip_int(x[5], -50, 50)
    # Decode pw_center/pw_width to pw_min/pw_max (guarantees pw_min <= pw_max)
    pw_center = float(x[6])
    pw_width = float(x[7])
    pw_min_val = _clip_int(pw_center - pw_width / 2.0, 0, 4095)
    pw_max_val = _clip_int(pw_center + pw_width / 2.0, 0, 4095)
    # Decode log2-scale filter cutoff (clamp log value to [0, 11] before exp)
    log_cutoff_start = max(0.0, min(11.0, float(x[8])))
    log_cutoff_end = max(0.0, min(11.0, float(x[9])))
    filter_cutoff_start = min(2047, max(0, round(2.0 ** log_cutoff_start - 1.0)))
    filter_cutoff_end = min(2047, max(0, round(2.0 ** log_cutoff_end - 1.0)))
    filter_sweep_frames = _clip_int(x[10], 0, 100)
    filter_resonance = _clip_int(x[11], 0, 15)
    wt_attack_frames = _clip_int(x[12], 1, 5)

    kwargs = dict(fixed_kwargs)

    # Compute ADSR-aware gate/release frames
    gate_frames, release_frames = compute_render_duration(attack, decay, sustain, release)
    _min_gf = fixed_kwargs.get("_min_gate_frames")
    if _min_gf is not None and gate_frames < int(_min_gf):
        gate_frames = int(_min_gf)

    # Resolve waveform aliases
    wt_sustain_waveform = str(kwargs.get("wt_sustain_waveform", kwargs.get("waveform", "saw")))
    wt_attack_waveform = kwargs.get("wt_attack_waveform")
    if wt_attack_waveform == "same_as_sustain" or wt_attack_waveform is None:
        wt_attack_waveform_str: Optional[str] = None
    else:
        wt_attack_waveform_str = str(wt_attack_waveform)

    wt_use_test_bit = bool(kwargs.get("wt_use_test_bit", False))
    filter_mode = str(kwargs.get("filter_mode", "off"))
    pw_mode = str(kwargs.get("pw_mode", "sweep"))

    # Multi-step wavetable: passed as fixed discrete combo, durations baked in
    wavetable_steps = kwargs.get("wavetable_steps")
    if wavetable_steps is not None:
        wavetable_steps = [tuple(s) for s in wavetable_steps]

    # Determine if filter voice1 should be enabled
    has_filter = filter_mode != "off"

    return SidParams(
        waveform=wt_sustain_waveform,
        attack=attack,
        decay=decay,
        sustain=sustain,
        release=release,
        pulse_width=pw_start,
        pw_table=None,
        filter_cutoff=filter_cutoff_start,
        filter_resonance=filter_resonance,
        filter_mode=filter_mode,
        filter_voice1=bool(kwargs.get("filter_voice1", has_filter)),
        ring_mod=bool(kwargs.get("ring_mod", False)),
        sync=bool(kwargs.get("sync", False)),
        frequency=float(kwargs.get("frequency", 440.0)),
        gate_frames=gate_frames,
        release_frames=release_frames,
        volume=int(kwargs.get("volume", 15)),
        chip_model=kwargs.get("chip_model"),
        # Wavetable sequence
        wt_attack_frames=wt_attack_frames,
        wt_attack_waveform=wt_attack_waveform_str,
        wt_sustain_waveform=wt_sustain_waveform,
        wt_use_test_bit=wt_use_test_bit,
        wavetable_steps=wavetable_steps,
        # PW sweep
        pw_start=pw_start,
        pw_delta=pw_delta,
        pw_min=pw_min_val,
        pw_max=pw_max_val,
        pw_mode=pw_mode,
        # Filter sweep
        filter_cutoff_start=filter_cutoff_start,
        filter_cutoff_end=filter_cutoff_end,
        filter_sweep_frames=filter_sweep_frames,
    )


def sid_params_to_dict(p: SidParams) -> dict:
    d = asdict(p)
    # asdict handles lists of tuples fine; ensure JSON-serializable.
    if d.get("pw_table") is not None:
        d["pw_table"] = [list(t) for t in d["pw_table"]]
    if d.get("wavetable") is not None:
        d["wavetable"] = [list(t) for t in d["wavetable"]]
    if d.get("wavetable_steps") is not None:
        d["wavetable_steps"] = [list(t) for t in d["wavetable_steps"]]
    return d


def sid_params_from_dict(d: dict) -> SidParams:
    kw = dict(d)
    if kw.get("pw_table"):
        kw["pw_table"] = [tuple(t) for t in kw["pw_table"]]
    if kw.get("wavetable"):
        kw["wavetable"] = [tuple(t) for t in kw["wavetable"]]
    if kw.get("wavetable_steps"):
        kw["wavetable_steps"] = [tuple(t) for t in kw["wavetable_steps"]]
    # Strip keys that are not SidParams fields (e.g. fitness_score, version).
    import dataclasses
    valid_fields = {f.name for f in dataclasses.fields(SidParams)}
    kw = {k: v for k, v in kw.items() if k in valid_fields}
    return SidParams(**kw)


# ---------------------------------------------------------------------------
# Reference loading
# ---------------------------------------------------------------------------

def load_reference_audio(
    ref_wav_path: Path,
    onset_window_s: float = 2.0,
) -> Tuple[np.ndarray, int]:
    """Load a reference WAV, trim to ``onset_window_s`` seconds from onset.

    Returns (mono audio at canonical SR, CANONICAL_SR).
    """
    audio, sr = sf.read(str(ref_wav_path), always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    if sr != CANONICAL_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=CANONICAL_SR)
        sr = CANONICAL_SR

    # Find onset: first sample above 1% of peak.
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0:
        thr = 0.01 * peak
        above = np.where(np.abs(audio) >= thr)[0]
        onset = int(above[0]) if above.size else 0
    else:
        onset = 0

    n_take = int(round(onset_window_s * sr))
    end = min(audio.size, onset + n_take)
    return audio[onset:end].astype(np.float32), sr


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

# Per-process globals populated by the initializer.
_WORKER_REF_FV: Optional[FeatureVec] = None
_WORKER_FIXED_KWARGS: Optional[dict] = None
_WORKER_WEIGHTS: Optional[dict] = None
_WORKER_BEST_FITNESS: Optional[mp.Value] = None
_WORKER_RENDER_DUR: Optional[float] = None


def _worker_init(
    ref_fv_dict: dict,
    fixed_kwargs: dict,
    weights: Optional[dict],
    best_fitness_val: Optional[mp.Value] = None,
    render_dur: Optional[float] = None,
) -> None:
    global _WORKER_REF_FV, _WORKER_FIXED_KWARGS, _WORKER_WEIGHTS
    global _WORKER_BEST_FITNESS, _WORKER_RENDER_DUR
    _WORKER_REF_FV = _fv_from_dict(ref_fv_dict)
    _WORKER_FIXED_KWARGS = dict(fixed_kwargs)
    _WORKER_WEIGHTS = dict(weights) if weights else None
    _WORKER_BEST_FITNESS = best_fitness_val
    _WORKER_RENDER_DUR = render_dur


def _worker_eval(x_list: List[float]) -> float:
    assert _WORKER_REF_FV is not None and _WORKER_FIXED_KWARGS is not None
    x = np.asarray(x_list, dtype=np.float64)
    params = decode_params(x, _WORKER_FIXED_KWARGS)
    chip_model = _WORKER_FIXED_KWARGS.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)

        # Truncate to current render duration tier for coarse-to-fine.
        if _WORKER_RENDER_DUR is not None:
            max_samples = int(_WORKER_RENDER_DUR * CANONICAL_SR)
            if audio.shape[0] > max_samples:
                audio = audio[:max_samples]

        # Early rejection: compute cheap partial fitness first.
        if _WORKER_BEST_FITNESS is not None:
            threshold = _WORKER_BEST_FITNESS.value
            if threshold < 1e5:  # only apply once we have a real best
                fv_lite = extract_lite(audio, CANONICAL_SR, known_f0=params.frequency)
                d_lite = distance_lite(_WORKER_REF_FV, fv_lite, weights=_WORKER_WEIGHTS)
                if d_lite > 2.0 * threshold:
                    return d_lite  # skip full extraction

        fv = extract(audio, CANONICAL_SR, known_f0=params.frequency)
        return float(distance(_WORKER_REF_FV, fv, weights=_WORKER_WEIGHTS))
    except Exception as e:
        # Penalize broken candidates heavily.
        return 1e6


def _eval_single(
    x: np.ndarray,
    fixed_kwargs: dict,
    ref_fv: FeatureVec,
    weights: Optional[dict],
    best_fitness: float = float("inf"),
    render_dur_s: Optional[float] = None,
) -> float:
    """In-process evaluation (used when n_workers=1)."""
    params = decode_params(x, fixed_kwargs)
    chip_model = fixed_kwargs.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)

        # Truncate to current render duration tier for coarse-to-fine.
        if render_dur_s is not None:
            max_samples = int(render_dur_s * CANONICAL_SR)
            if audio.shape[0] > max_samples:
                audio = audio[:max_samples]

        # Early rejection: compute cheap partial fitness first.
        if best_fitness < 1e5:
            fv_lite = extract_lite(audio, CANONICAL_SR, known_f0=params.frequency)
            d_lite = distance_lite(ref_fv, fv_lite, weights=weights)
            if d_lite > 2.0 * best_fitness:
                return d_lite  # skip full extraction

        fv = extract(audio, CANONICAL_SR, known_f0=params.frequency)
        return float(distance(ref_fv, fv, weights=weights))
    except Exception:
        return 1e6


def _fv_to_dict(fv: FeatureVec) -> dict:
    d = {
        "sr": fv.sr,
        "duration_s": fv.duration_s,
        "amplitude_envelope": np.asarray(fv.amplitude_envelope).tolist(),
        "attack_time_s": fv.attack_time_s,
        "decay_time_s": fv.decay_time_s,
        "sustain_level": fv.sustain_level,
        "release_time_s": fv.release_time_s,
        "harmonic_magnitudes": np.asarray(fv.harmonic_magnitudes).tolist(),
        "spectral_centroid": np.asarray(fv.spectral_centroid).tolist(),
        "spectral_rolloff": np.asarray(fv.spectral_rolloff).tolist(),
        "spectral_flatness": np.asarray(fv.spectral_flatness).tolist(),
        "fundamental_hz": fv.fundamental_hz,
        "noisiness": fv.noisiness,
        "onset_energy_ratio": fv.onset_energy_ratio,
        "onset_log_mel": (
            tuple(np.asarray(m).tolist() for m in fv.onset_log_mel)
            if fv.onset_log_mel is not None else None
        ),
        "mfcc": np.asarray(fv.mfcc).tolist() if fv.mfcc is not None else None,
        "stft_mag": np.asarray(fv.stft_mag).tolist() if fv.stft_mag is not None else None,
    }
    return d


def _fv_from_dict(d: dict) -> FeatureVec:
    onset_log_mel_raw = d.get("onset_log_mel")
    onset_log_mel = (
        tuple(np.asarray(m, dtype=np.float32) for m in onset_log_mel_raw)
        if onset_log_mel_raw is not None else None
    )
    mfcc_raw = d.get("mfcc")
    mfcc = np.asarray(mfcc_raw, dtype=np.float32) if mfcc_raw is not None else None
    stft_raw = d.get("stft_mag")
    stft_mag = np.asarray(stft_raw, dtype=np.float32) if stft_raw is not None else None
    return FeatureVec(
        sr=int(d["sr"]),
        duration_s=float(d["duration_s"]),
        amplitude_envelope=np.asarray(d["amplitude_envelope"], dtype=np.float64),
        attack_time_s=float(d["attack_time_s"]),
        decay_time_s=float(d["decay_time_s"]),
        sustain_level=float(d["sustain_level"]),
        release_time_s=float(d["release_time_s"]),
        harmonic_magnitudes=np.asarray(d["harmonic_magnitudes"], dtype=np.float64),
        spectral_centroid=np.asarray(d["spectral_centroid"], dtype=np.float64),
        spectral_rolloff=np.asarray(d["spectral_rolloff"], dtype=np.float64),
        spectral_flatness=np.asarray(d["spectral_flatness"], dtype=np.float64),
        fundamental_hz=float(d["fundamental_hz"]),
        noisiness=float(d["noisiness"]),
        onset_energy_ratio=float(d.get("onset_energy_ratio", 0.0)),
        onset_log_mel=onset_log_mel,
        mfcc=mfcc,
        stft_mag=stft_mag,
    )


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

@dataclass
class OptimizerResult:
    best_params: SidParams
    best_fitness: float
    history: List[float] = field(default_factory=list)
    evaluations: int = 0
    wall_time_s: float = 0.0
    converged: bool = False


class Optimizer:
    """CMA-ES optimizer over SID continuous patch parameters."""

    # Coarse-to-fine render duration tiers: (fraction_of_budget, duration_s).
    # Evaluated in order; the first tier whose threshold exceeds progress wins.
    _DURATION_TIERS = [
        (0.50, 0.5),   # first 50% of budget: 0.5 s
        (0.80, 1.0),   # 50%–80% of budget: 1.0 s
        (1.01, None),   # 80%–100%: full duration (None = no truncation)
    ]

    def __init__(
        self,
        ref_wav_path: Optional[Path],
        ref_frequency_hz: float,
        fixed_kwargs: Mapping,
        weights: Optional[Mapping[str, float]] = None,
        budget: int = 5000,
        patience: int = 500,
        n_workers: Optional[int] = None,
        seed: int = 0,
        work_dir: Optional[Path] = None,
        ref_audio: Optional[np.ndarray] = None,
        ref_sr: Optional[int] = None,
        log_interval: int = 100,
        ref_fv: Optional[FeatureVec] = None,
        x0: Optional[np.ndarray] = None,
        max_attack: int = 15,
        onset_window_s: float = 2.0,
        warm_start: bool = False,
        use_surrogate: bool = True,
        optimizer_backend: str = "cma",
        sensitivity_screen: bool = False,
        freeze_indices: Optional[dict] = None,
        adsr_bound_overrides: Optional[dict] = None,
        min_gate_frames: Optional[int] = None,
    ) -> None:
        self.use_surrogate = bool(use_surrogate)
        self.optimizer_backend = optimizer_backend
        self.sensitivity_screen = bool(sensitivity_screen)
        self.ref_frequency_hz = float(ref_frequency_hz)
        self.fixed_kwargs = dict(fixed_kwargs)
        self.fixed_kwargs.setdefault("frequency", self.ref_frequency_hz)
        self.weights = dict(weights) if weights else None
        self.budget = int(budget)
        self.patience = int(patience)
        self.n_workers = int(n_workers) if n_workers is not None else (os.cpu_count() or 1)
        self.seed = int(seed)
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.log_interval = int(log_interval)
        self.max_attack = int(np.clip(max_attack, 0, 15))
        self.x0 = np.asarray(x0, dtype=np.float64) if x0 is not None else None
        self.onset_window_s = float(onset_window_s)
        self.warm_start = bool(warm_start)
        # freeze_indices: dict mapping full-vector index -> fixed original-scale value.
        # These dimensions are excluded from CMA-ES and injected during decode.
        self.freeze_indices = dict(freeze_indices) if freeze_indices else {}
        # adsr_bound_overrides: dict mapping ADSR index -> (lo, hi) to constrain
        # the search space for instrument-type profiles.
        self.adsr_bound_overrides = dict(adsr_bound_overrides) if adsr_bound_overrides else {}
        # min_gate_frames: floor for gate_frames (e.g., 100 for piano).
        self.min_gate_frames = int(min_gate_frames) if min_gate_frames is not None else None
        if self.min_gate_frames is not None:
            self.fixed_kwargs["_min_gate_frames"] = self.min_gate_frames

        # Load reference audio and features.
        if ref_fv is not None:
            self.ref_fv = ref_fv
            # Store ref audio for coarse-to-fine re-extraction.
            if ref_audio is not None:
                self._ref_audio = np.asarray(ref_audio, dtype=np.float32)
                if ref_sr is not None and ref_sr != CANONICAL_SR:
                    self._ref_audio = librosa.resample(
                        self._ref_audio, orig_sr=ref_sr, target_sr=CANONICAL_SR,
                    )
            else:
                self._ref_audio = None
        elif ref_audio is not None and ref_sr is not None:
            audio = np.asarray(ref_audio, dtype=np.float32)
            sr = int(ref_sr)
            if sr != CANONICAL_SR:
                audio = librosa.resample(audio, orig_sr=sr, target_sr=CANONICAL_SR)
            self._ref_audio = audio
            self.ref_fv = extract(audio, CANONICAL_SR)
        elif ref_wav_path is not None:
            audio, sr = load_reference_audio(Path(ref_wav_path), onset_window_s=self.onset_window_s)
            self._ref_audio = audio  # already at CANONICAL_SR
            self.ref_fv = extract(audio, sr)
        else:
            raise ValueError("must provide ref_fv, ref_wav_path, or ref_audio+ref_sr")

    def _effective_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return (bounds_low, bounds_high) with ADSR overrides applied."""
        bl = BOUNDS_LOW.copy()
        bh = BOUNDS_HIGH.copy()
        bh[0] = min(float(self.max_attack), bh[0])
        for idx, (lo, hi) in self.adsr_bound_overrides.items():
            bl[idx] = max(float(lo), bl[idx])
            bh[idx] = min(float(hi), bh[idx])
        return bl, bh

    def _render_duration_for_eval(self, eval_count: int) -> Optional[float]:
        """Return the render duration in seconds for the current eval count.

        Returns None when full duration should be used (no truncation).
        """
        progress = eval_count / max(1, self.budget)
        for threshold, dur_s in self._DURATION_TIERS:
            if progress < threshold:
                return dur_s
        return None  # full duration

    def _ref_fv_for_duration(self, dur_s: Optional[float]) -> FeatureVec:
        """Return reference features truncated to *dur_s* seconds.

        If dur_s is None or no ref audio is stored, returns the full ref_fv.
        """
        if dur_s is None or self._ref_audio is None:
            return self.ref_fv
        max_samples = int(dur_s * CANONICAL_SR)
        if self._ref_audio.shape[0] <= max_samples:
            return self.ref_fv
        truncated = self._ref_audio[:max_samples]
        return extract(truncated, CANONICAL_SR)

    # ---------- sensitivity screen ----------

    def _sensitivity_screen(
        self,
        x0_norm: np.ndarray,
        active_idx: list,
        ref_fv: "FeatureVec",
        fixed_kwargs: dict,
        chip_model=None,
        render_dur_s: Optional[float] = None,
        bounds_high: Optional[np.ndarray] = None,
    ) -> list:
        """Run OAT sensitivity screen. Returns active_idx positions to freeze.

        Perturbs each active dimension to its min (0.0) and max (1.0) in
        normalized space, measures the fitness delta from baseline, and
        returns indices (within *active_idx*) whose sensitivity is below
        5% of the baseline fitness.

        ADSR parameters (indices 0-3 in the full 13-dim vector) are never
        frozen, even if they appear low-sensitivity.

        Cost: 2 * len(active_idx) + 1 evaluations.
        """
        if bounds_high is None:
            bounds_high = BOUNDS_HIGH

        lo_red = BOUNDS_LOW[active_idx]
        hi_red = bounds_high[active_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _denorm(xn):
            return xn * range_red_safe + lo_red

        # Evaluate baseline.
        x0_full = _expand_vector(_denorm(x0_norm), active_idx, bounds_high)
        baseline = _eval_single(
            x0_full, fixed_kwargs, ref_fv,
            self.weights, render_dur_s=render_dur_s,
        )

        threshold = 0.05 * baseline if baseline > 0 else 0.0
        freeze_positions: list = []

        for pos in range(len(active_idx)):
            orig_idx = active_idx[pos]
            # Never freeze ADSR (indices 0-3 in full vector).
            if orig_idx in _IDX_ADSR:
                continue

            # Perturb to min.
            x_low = x0_norm.copy()
            x_low[pos] = 0.0
            x_low_full = _expand_vector(_denorm(x_low), active_idx, bounds_high)
            f_low = _eval_single(
                x_low_full, fixed_kwargs, ref_fv,
                self.weights, render_dur_s=render_dur_s,
            )

            # Perturb to max.
            x_high = x0_norm.copy()
            x_high[pos] = 1.0
            x_high_full = _expand_vector(_denorm(x_high), active_idx, bounds_high)
            f_high = _eval_single(
                x_high_full, fixed_kwargs, ref_fv,
                self.weights, render_dur_s=render_dur_s,
            )

            sensitivity = max(abs(f_low - baseline), abs(f_high - baseline))
            if sensitivity < threshold:
                freeze_positions.append(pos)
                if self.log_interval > 0:
                    print(
                        f"[sensitivity] freeze {_PARAM_NAMES[orig_idx]} "
                        f"(sens={sensitivity:.4f}, thr={threshold:.4f})",
                        flush=True,
                    )
            elif self.log_interval > 0:
                print(
                    f"[sensitivity] keep   {_PARAM_NAMES[orig_idx]} "
                    f"(sens={sensitivity:.4f}, thr={threshold:.4f})",
                    flush=True,
                )

        return freeze_positions

    # ---------- checkpoint helpers ----------

    def _checkpoint_path(self) -> Optional[Path]:
        if self.work_dir is None:
            return None
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return self.work_dir / "optim_state.json"

    def _save_checkpoint(
        self,
        best_x: np.ndarray,
        best_fitness: float,
        history: List[float],
        evaluations: int,
    ) -> None:
        path = self._checkpoint_path()
        if path is None:
            return
        best_params = decode_params(best_x, self.fixed_kwargs)
        state = {
            "best_x": np.asarray(best_x).tolist(),
            "best_fitness": float(best_fitness),
            "best_params": sid_params_to_dict(best_params),
            "history": list(map(float, history)),
            "evaluations": int(evaluations),
            "fixed_kwargs": self.fixed_kwargs,
            "seed": self.seed,
            "budget": self.budget,
            "patience": self.patience,
            "param_names": _PARAM_NAMES,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, path)

    @staticmethod
    def load_checkpoint(work_dir: Path) -> dict:
        """Load a saved checkpoint from ``work_dir``. Returns the state dict.

        Raises FileNotFoundError if the checkpoint does not exist.
        """
        path = Path(work_dir) / "optim_state.json"
        if not path.exists():
            raise FileNotFoundError(f"no checkpoint at {path}")
        return json.loads(path.read_text())

    # ---------- main loop ----------

    def run(self) -> OptimizerResult:
        if self.optimizer_backend == "tpe":
            return self._run_tpe()
        if self.optimizer_backend == "tpe+cma":
            return self._run_tpe_then_cma()
        return self._run_cma()

    def _run_tpe(self) -> OptimizerResult:
        """Optuna TPE optimization path with parallel batch evaluation."""
        try:
            import optuna
        except ImportError:
            raise ImportError(
                "optuna is required for TPE optimizer: pip install optuna"
            )
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        act_idx = active_params(self.fixed_kwargs)
        # Apply caller-provided freeze_indices.
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]
        n_active = len(act_idx)

        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = (0.5 * (bounds_low + bounds_high)).copy()
        # Inject frozen values into x0.
        for fidx, fval in self.freeze_indices.items():
            best_x_full[fidx] = fval
        evaluations = 0
        non_improve = 0
        converged = False

        # Coarse-to-fine: current render duration tier and matching ref features.
        current_render_dur = self._render_duration_for_eval(0)
        current_ref_fv = self._ref_fv_for_duration(current_render_dur)

        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(
                n_startup_trials=min(50, self.budget // 2),
                multivariate=True,
                group=True,
                constant_liar=True,
                n_ei_candidates=256,
                seed=self.seed if self.seed != 0 else None,
            ),
            direction="minimize",
        )

        def _trial_to_x_full(trial):
            """Sample params from an Optuna trial and return the full vector."""
            x_red = np.empty(n_active, dtype=np.float64)
            for i, orig_i in enumerate(act_idx):
                name = _PARAM_NAMES[orig_i]
                if orig_i in _INTEGER_PARAM_INDICES:
                    val = trial.suggest_int(
                        name, int(bounds_low[orig_i]), int(bounds_high[orig_i])
                    )
                    x_red[i] = float(val)
                else:
                    norm = trial.suggest_float(name, 0.0, 1.0)
                    x_red[i] = norm * range_red_safe[i] + lo_red[i]
            x_full = _expand_vector(x_red, act_idx, bounds_high)
            for fidx, fval in self.freeze_indices.items():
                x_full[fidx] = fval
            return x_full

        n_workers = self.n_workers

        # Build multiprocessing pool for parallel evaluation.
        pool = None
        best_fitness_shared = None
        ref_fv_dict = _fv_to_dict(current_ref_fv)
        if n_workers > 1:
            best_fitness_shared = mp.Value('d', float('inf'))
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                          best_fitness_shared, current_render_dur),
            )

        try:
            while evaluations < self.budget and non_improve < self.patience:
                # Check if render duration tier has changed.
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    current_ref_fv = self._ref_fv_for_duration(current_render_dur)
                    ref_fv_dict = _fv_to_dict(current_ref_fv)
                    best_fitness = float("inf")
                    non_improve = 0
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = float("inf")
                    # Re-create pool with updated ref features and render dur.
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=n_workers,
                            initializer=_worker_init,
                            initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                                      best_fitness_shared, current_render_dur),
                        )

                # Ask Optuna for a batch of trials.
                batch_size = min(n_workers, self.budget - evaluations)
                trials = [study.ask() for _ in range(batch_size)]

                # Build full parameter vectors for each trial.
                candidates_full = [_trial_to_x_full(t) for t in trials]
                candidates_list = [list(c) for c in candidates_full]

                # Evaluate in parallel or sequentially.
                if pool is not None:
                    fitnesses = pool.map(_worker_eval, candidates_list)
                else:
                    fitnesses = [
                        _eval_single(
                            np.asarray(c), self.fixed_kwargs, current_ref_fv,
                            self.weights, best_fitness=best_fitness,
                            render_dur_s=current_render_dur,
                        )
                        for c in candidates_list
                    ]

                # Tell Optuna the results and update tracking.
                for trial, fitness, x_full in zip(trials, fitnesses, candidates_full):
                    study.tell(trial, fitness)
                    evaluations += 1
                    if fitness < best_fitness - 1e-9:
                        best_fitness = fitness
                        best_x_full = x_full.copy()
                        non_improve = 0
                        if best_fitness_shared is not None:
                            best_fitness_shared.value = best_fitness
                    else:
                        non_improve += 1
                    history.append(best_fitness)

                # Checkpoint every ~100 evals.
                if self.work_dir is not None and evaluations % 100 < batch_size:
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                # Log progress.
                if self.log_interval > 0 and evaluations % self.log_interval < batch_size:
                    elapsed = time.time() - t0
                    print(
                        f"[optim-tpe] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if non_improve >= self.patience:
                    converged = True
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        # Final checkpoint.
        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )

    def _run_cma(self) -> OptimizerResult:
        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        # Determine active parameter indices for this combo.
        act_idx = active_params(self.fixed_kwargs)

        # Apply caller-provided freeze_indices: remove those from active set.
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]

        n_active = len(act_idx)

        # Build reduced bounds for CMA-ES (only active dimensions).
        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]

        # Normalization helpers: CMA-ES operates in [0,1] hypercube.
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)  # avoid div-by-zero

        def _normalize(x_orig):
            return (x_orig - lo_red) / range_red_safe

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        # Start from caller-provided x0 or the mid-range point.
        if self.x0 is not None:
            x0_full = np.clip(self.x0, bounds_low, bounds_high)
        else:
            x0_full = 0.5 * (bounds_low + bounds_high)
        # Inject frozen values into x0_full so they propagate correctly.
        for fidx, fval in self.freeze_indices.items():
            x0_full[fidx] = fval
        x0_red = _reduce_vector(x0_full, act_idx)
        x0_norm = _normalize(x0_red)

        # --- OAT sensitivity screen: freeze low-impact params ---
        frozen_values = dict(self.freeze_indices)  # start with caller-provided freezes
        if self.sensitivity_screen and n_active > 0:
            current_ref_fv_screen = self._ref_fv_for_duration(
                self._render_duration_for_eval(0)
            )
            freeze_positions = self._sensitivity_screen(
                x0_norm, act_idx, current_ref_fv_screen,
                self.fixed_kwargs,
                chip_model=self.fixed_kwargs.get("chip_model"),
                render_dur_s=self._render_duration_for_eval(0),
                bounds_high=bounds_high,
            )
            if freeze_positions:
                # Record frozen values before removing from active set.
                for pos in freeze_positions:
                    frozen_values[act_idx[pos]] = x0_full[act_idx[pos]]
                # Remove frozen positions from active set (iterate in reverse).
                for pos in sorted(freeze_positions, reverse=True):
                    del act_idx[pos]
                n_active = len(act_idx)
                # Rebuild reduced bounds and normalization.
                lo_red = bounds_low[act_idx]
                hi_red = bounds_high[act_idx]
                range_red = hi_red - lo_red
                range_red_safe = np.where(range_red > 0, range_red, 1.0)

                def _normalize(x_orig):
                    return (x_orig - lo_red) / range_red_safe

                def _denormalize(x_norm):
                    return x_norm * range_red_safe + lo_red

                x0_red = _reduce_vector(x0_full, act_idx)
                x0_norm = _normalize(x0_red)
                if self.log_interval > 0:
                    print(
                        f"[sensitivity] reduced active dims: "
                        f"{n_active + len(freeze_positions)} -> {n_active}",
                        flush=True,
                    )

        # --- Low-dimensional fallbacks (CMA-ES needs >= 2 dims) ---
        if n_active == 0:
            # All params frozen -- evaluate the single point and return.
            current_render_dur = self._render_duration_for_eval(0)
            current_ref_fv = self._ref_fv_for_duration(current_render_dur)
            fitness = _eval_single(
                x0_full, self.fixed_kwargs, current_ref_fv,
                self.weights, render_dur_s=current_render_dur,
            )
            wall = time.time() - t0
            best_params = decode_params(x0_full, self.fixed_kwargs)
            return OptimizerResult(
                best_params=best_params,
                best_fitness=fitness,
                history=[fitness],
                evaluations=1,
                wall_time_s=wall,
                converged=True,
            )

        if n_active == 1:
            # 1-D grid search fallback (CMA-ES requires >= 2 dimensions).
            n_grid = 50
            current_render_dur = self._render_duration_for_eval(0)
            current_ref_fv = self._ref_fv_for_duration(current_render_dur)
            best_fitness = float("inf")
            best_x_full_grid: np.ndarray = x0_full.copy()
            for val in np.linspace(0.0, 1.0, n_grid):
                x_red = _denormalize(np.array([val]))
                x_full = _expand_vector(x_red, act_idx, bounds_high)
                if frozen_values:
                    for fidx, fval in frozen_values.items():
                        x_full[fidx] = fval
                fitness = _eval_single(
                    x_full, self.fixed_kwargs, current_ref_fv,
                    self.weights, best_fitness=best_fitness,
                    render_dur_s=current_render_dur,
                )
                if fitness < best_fitness:
                    best_fitness = fitness
                    best_x_full_grid = x_full.copy()
            wall = time.time() - t0
            best_params = decode_params(best_x_full_grid, self.fixed_kwargs)
            return OptimizerResult(
                best_params=best_params,
                best_fitness=best_fitness,
                history=[best_fitness],
                evaluations=n_grid,
                wall_time_s=wall,
                converged=True,
            )

        # sigma0 in normalized [0,1] space: ~1/6 of range normally, ~1/10 for warm-start.
        sigma0 = 0.10 if self.warm_start else 0.17

        cma_opts = {
            "bounds": [np.zeros(n_active).tolist(), np.ones(n_active).tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": self.budget,
        }
        es = cma.CMAEvolutionStrategy(x0_norm.tolist(), sigma0, cma_opts)

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = x0_full.copy()
        evaluations = 0
        non_improve = 0
        converged = False

        # Surrogate model for pre-screening candidates.
        surrogate: Optional[FitnessSurrogate] = None
        surr_X: List[np.ndarray] = []  # accumulated normalized param vectors
        surr_y: List[float] = []       # accumulated fitness values
        surr_train_threshold = 500     # first training after this many evals
        surr_retrain_interval = 200    # retrain every N evals after that
        surr_last_train_count = 0      # evals at last training
        adsr_sweep_done = False        # one-shot ADSR sweep flag

        # Coarse-to-fine: current render duration tier and matching ref features.
        current_render_dur = self._render_duration_for_eval(0)
        current_ref_fv = self._ref_fv_for_duration(current_render_dur)

        # Build pool if parallel.
        pool = None
        best_fitness_shared = None
        ref_fv_dict = _fv_to_dict(current_ref_fv)
        if self.n_workers > 1:
            best_fitness_shared = mp.Value('d', float('inf'))
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                          best_fitness_shared, current_render_dur),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break

                # Check if render duration tier has changed.
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    current_ref_fv = self._ref_fv_for_duration(current_render_dur)
                    ref_fv_dict = _fv_to_dict(current_ref_fv)
                    # Reset best fitness since features changed with new duration.
                    best_fitness = float("inf")
                    non_improve = 0
                    # Reset surrogate data since fitness landscape changed.
                    surr_X.clear()
                    surr_y.clear()
                    surrogate = None
                    surr_last_train_count = 0
                    adsr_sweep_done = False
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = float("inf")
                    # Re-create pool with updated ref features and render dur.
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=self.n_workers,
                            initializer=_worker_init,
                            initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                                      best_fitness_shared, current_render_dur),
                        )

                solutions_norm = es.ask()
                # Denormalize from [0,1] back to original ranges, then expand.
                solutions_full = [
                    _expand_vector(_denormalize(np.asarray(s)), act_idx, bounds_high)
                    for s in solutions_norm
                ]
                # Apply frozen parameter values from sensitivity screen.
                if frozen_values:
                    for sf in solutions_full:
                        for fidx, fval in frozen_values.items():
                            sf[fidx] = fval
                solutions_full_list = [list(s) for s in solutions_full]

                # Surrogate pre-screening: evaluate all with surrogate,
                # only run expensive eval on the top 50%.
                eval_indices = list(range(len(solutions_norm)))
                surr_predictions: Optional[np.ndarray] = None
                if self.use_surrogate and surrogate is not None and surrogate.is_ready:
                    norm_arr = np.array(solutions_norm, dtype=np.float64)
                    surr_predictions = surrogate.predict(norm_arr)
                    n_keep = max(1, len(solutions_norm) // 2)
                    ranked = np.argsort(surr_predictions)
                    eval_indices = sorted(ranked[:n_keep].tolist())

                # Run expensive evaluation only on selected candidates.
                eval_full_list = [solutions_full_list[i] for i in eval_indices]
                if pool is not None:
                    eval_fitnesses = pool.map(_worker_eval, eval_full_list)
                else:
                    eval_fitnesses = [
                        _eval_single(
                            np.asarray(s), self.fixed_kwargs, current_ref_fv,
                            self.weights, best_fitness=best_fitness,
                            render_dur_s=current_render_dur,
                        )
                        for s in eval_full_list
                    ]

                # Build full fitness list: real values for evaluated, surrogate for rest.
                fitnesses = [0.0] * len(solutions_norm)
                eval_map = dict(zip(eval_indices, eval_fitnesses))
                for i in range(len(solutions_norm)):
                    if i in eval_map:
                        fitnesses[i] = eval_map[i]
                    elif surr_predictions is not None:
                        fitnesses[i] = float(surr_predictions[i])
                    else:
                        fitnesses[i] = 1e6  # should not happen

                es.tell(solutions_norm, fitnesses)

                # Accumulate data for surrogate training.
                if self.use_surrogate:
                    for i in eval_indices:
                        surr_X.append(np.asarray(solutions_norm[i], dtype=np.float64))
                        surr_y.append(eval_map[i])

                    # Train/retrain surrogate when enough data has accumulated.
                    total_surr = len(surr_y)
                    if total_surr >= surr_train_threshold and (
                        surrogate is None
                        or total_surr - surr_last_train_count >= surr_retrain_interval
                    ):
                        if surrogate is None:
                            surrogate = FitnessSurrogate(input_dim=n_active)
                        surrogate.fit(np.array(surr_X), np.array(surr_y))
                        surr_last_train_count = total_surr

                        # One-shot surrogate ADSR sweep after first training.
                        if not adsr_sweep_done and surrogate.is_ready:
                            adsr_sweep_done = True
                            best_x_red = _reduce_vector(best_x_full, act_idx)
                            best_x_norm_current = _normalize(best_x_red)
                            adsr_candidates = _surrogate_adsr_sweep(
                                surrogate, best_x_norm_current, act_idx,
                                lo_red, hi_red, top_n=20,
                            )
                            # Evaluate top-5 with the real fitness function.
                            n_verify = min(5, adsr_candidates.shape[0])
                            for ci in range(n_verify):
                                cand_norm = adsr_candidates[ci]
                                cand_red = _denormalize(cand_norm)
                                cand_full = _expand_vector(cand_red, act_idx, bounds_high)
                                if frozen_values:
                                    for fidx, fval in frozen_values.items():
                                        cand_full[fidx] = fval
                                cand_fitness = _eval_single(
                                    cand_full, self.fixed_kwargs, current_ref_fv,
                                    self.weights, best_fitness=best_fitness,
                                    render_dur_s=current_render_dur,
                                )
                                evaluations += 1
                                surr_X.append(cand_norm.copy())
                                surr_y.append(cand_fitness)
                                if cand_fitness < best_fitness - 1e-9:
                                    best_fitness = cand_fitness
                                    best_x_full = cand_full.copy()
                                    non_improve = 0
                                    if best_fitness_shared is not None:
                                        best_fitness_shared.value = best_fitness
                                    es.inject([cand_norm.tolist()])

                evaluations += len(eval_fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x_full = np.asarray(solutions_full_list[gen_best_idx], dtype=np.float64)
                    non_improve = 0
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = best_fitness
                else:
                    non_improve += len(fitnesses)
                history.append(best_fitness)

                # Log progress.
                if self.log_interval > 0 and (
                    evaluations // self.log_interval
                    != (evaluations - len(fitnesses)) // self.log_interval
                ):
                    elapsed = time.time() - t0
                    print(
                        f"[optim] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                # Checkpoint every ~100 evals.
                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                # Patience stop.
                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        # Final checkpoint.
        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )

    def _run_tpe_then_cma(self, tpe_fraction: float = 0.25) -> OptimizerResult:
        """Two-phase optimization: TPE exploration then CMA-ES refinement.

        Runs TPE for *tpe_fraction* of the budget to explore the search space,
        then warm-starts CMA-ES with the top-K solutions for the remaining budget.
        """
        try:
            import optuna
        except ImportError:
            raise ImportError(
                "optuna is required for TPE optimizer: pip install optuna"
            )
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        act_idx = active_params(self.fixed_kwargs)
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]
        n_active = len(act_idx)

        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _normalize(x_orig):
            return (x_orig - lo_red) / range_red_safe

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        tpe_budget = max(1, int(self.budget * tpe_fraction))
        cma_budget = self.budget - tpe_budget

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = (0.5 * (bounds_low + bounds_high)).copy()
        for fidx, fval in self.freeze_indices.items():
            best_x_full[fidx] = fval
        evaluations = 0
        non_improve = 0
        converged = False

        # Collect all evaluated solutions (normalized) and their fitnesses.
        all_solutions_norm: List[np.ndarray] = []
        all_fitnesses: List[float] = []

        # ---- Phase 1: TPE exploration ----
        current_render_dur = self._render_duration_for_eval(0)
        current_ref_fv = self._ref_fv_for_duration(current_render_dur)

        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(
                n_startup_trials=min(50, tpe_budget // 2),
                multivariate=True,
                group=True,
                constant_liar=True,
                n_ei_candidates=256,
                seed=self.seed if self.seed != 0 else None,
            ),
            direction="minimize",
        )

        def _trial_to_x_full(trial):
            x_red = np.empty(n_active, dtype=np.float64)
            for i, orig_i in enumerate(act_idx):
                name = _PARAM_NAMES[orig_i]
                if orig_i in _INTEGER_PARAM_INDICES:
                    val = trial.suggest_int(
                        name, int(bounds_low[orig_i]), int(bounds_high[orig_i])
                    )
                    x_red[i] = float(val)
                else:
                    norm = trial.suggest_float(name, 0.0, 1.0)
                    x_red[i] = norm * range_red_safe[i] + lo_red[i]
            x_full = _expand_vector(x_red, act_idx, bounds_high)
            for fidx, fval in self.freeze_indices.items():
                x_full[fidx] = fval
            return x_full

        n_workers = self.n_workers
        pool = None
        best_fitness_shared = None
        ref_fv_dict = _fv_to_dict(current_ref_fv)
        if n_workers > 1:
            best_fitness_shared = mp.Value('d', float('inf'))
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                          best_fitness_shared, current_render_dur),
            )

        try:
            while evaluations < tpe_budget and non_improve < self.patience:
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    current_ref_fv = self._ref_fv_for_duration(current_render_dur)
                    ref_fv_dict = _fv_to_dict(current_ref_fv)
                    best_fitness = float("inf")
                    non_improve = 0
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = float("inf")
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=n_workers,
                            initializer=_worker_init,
                            initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                                      best_fitness_shared, current_render_dur),
                        )

                batch_size = min(n_workers, tpe_budget - evaluations)
                trials = [study.ask() for _ in range(batch_size)]
                candidates_full = [_trial_to_x_full(t) for t in trials]
                candidates_list = [list(c) for c in candidates_full]

                if pool is not None:
                    fitnesses = pool.map(_worker_eval, candidates_list)
                else:
                    fitnesses = [
                        _eval_single(
                            np.asarray(c), self.fixed_kwargs, current_ref_fv,
                            self.weights, best_fitness=best_fitness,
                            render_dur_s=current_render_dur,
                        )
                        for c in candidates_list
                    ]

                for trial, fitness, x_full in zip(trials, fitnesses, candidates_full):
                    study.tell(trial, fitness)
                    evaluations += 1
                    # Store normalized solution for CMA-ES warm-start.
                    x_red = _reduce_vector(x_full, act_idx)
                    x_norm = _normalize(x_red)
                    all_solutions_norm.append(x_norm)
                    all_fitnesses.append(fitness)
                    if fitness < best_fitness - 1e-9:
                        best_fitness = fitness
                        best_x_full = x_full.copy()
                        non_improve = 0
                        if best_fitness_shared is not None:
                            best_fitness_shared.value = best_fitness
                    else:
                        non_improve += 1
                    history.append(best_fitness)

                if self.work_dir is not None and evaluations % 100 < batch_size:
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                if self.log_interval > 0 and evaluations % self.log_interval < batch_size:
                    elapsed = time.time() - t0
                    print(
                        f"[optim-tpe+cma/tpe] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if non_improve >= self.patience:
                    converged = True
        finally:
            if pool is not None:
                pool.close()
                pool.join()
                pool = None

        if converged or cma_budget <= 0 or n_active < 2:
            # TPE converged or no budget left or too few dims for CMA-ES.
            self._save_checkpoint(best_x_full, best_fitness, history, evaluations)
            wall = time.time() - t0
            best_params = decode_params(best_x_full, self.fixed_kwargs)
            return OptimizerResult(
                best_params=best_params,
                best_fitness=best_fitness,
                history=history,
                evaluations=evaluations,
                wall_time_s=wall,
                converged=converged,
            )

        # ---- Phase 2: CMA-ES refinement warm-started from TPE results ----

        # Extract top-K solutions from TPE phase.
        all_fitnesses_arr = np.array(all_fitnesses, dtype=np.float64)
        all_solutions_arr = np.array(all_solutions_norm, dtype=np.float64)
        k = min(20, max(1, len(all_fitnesses) // 5))
        top_k_indices = np.argsort(all_fitnesses_arr)[:k]
        top_k_solutions = all_solutions_arr[top_k_indices]

        # Compute mean and per-dimension std from top-K.
        x0_cma = np.mean(top_k_solutions, axis=0)
        if k > 1:
            per_dim_std = np.std(top_k_solutions, axis=0)
        else:
            per_dim_std = np.full(n_active, 0.1)
        per_dim_std = np.clip(per_dim_std, 0.01, 0.5)

        sigma0 = float(np.median(per_dim_std))
        if sigma0 < 1e-6:
            sigma0 = 0.1
        cma_stds = per_dim_std / sigma0

        # Clip x0 to valid bounds.
        x0_cma = np.clip(x0_cma, 0.0, 1.0)

        cma_opts = {
            "bounds": [np.zeros(n_active).tolist(), np.ones(n_active).tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": cma_budget,
            "CMA_stds": cma_stds.tolist(),
        }
        es = cma.CMAEvolutionStrategy(x0_cma.tolist(), sigma0, cma_opts)

        # Inject top-K solutions into CMA-ES (limit to popsize to avoid
        # "unused injected direction/solutions" error from pycma).
        inject_solutions = [s.tolist() for s in top_k_solutions[:es.popsize]]
        es.inject(inject_solutions)

        # Reset patience for CMA-ES phase.
        non_improve = 0

        # Surrogate model for pre-screening candidates.
        surrogate: Optional[FitnessSurrogate] = None
        surr_X: List[np.ndarray] = []
        surr_y: List[float] = []
        surr_train_threshold = 500
        surr_retrain_interval = 200
        surr_last_train_count = 0
        adsr_sweep_done = False

        # Seed surrogate with TPE data.
        if self.use_surrogate:
            surr_X = list(all_solutions_arr)
            surr_y = list(all_fitnesses)

        # Coarse-to-fine rendering for CMA-ES phase.
        current_render_dur = self._render_duration_for_eval(evaluations)
        current_ref_fv = self._ref_fv_for_duration(current_render_dur)

        frozen_values = dict(self.freeze_indices)

        pool = None
        best_fitness_shared = None
        ref_fv_dict = _fv_to_dict(current_ref_fv)
        if self.n_workers > 1:
            best_fitness_shared = mp.Value('d', best_fitness)
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                          best_fitness_shared, current_render_dur),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break

                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    current_ref_fv = self._ref_fv_for_duration(current_render_dur)
                    ref_fv_dict = _fv_to_dict(current_ref_fv)
                    best_fitness = float("inf")
                    non_improve = 0
                    surr_X.clear()
                    surr_y.clear()
                    surrogate = None
                    surr_last_train_count = 0
                    adsr_sweep_done = False
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = float("inf")
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=self.n_workers,
                            initializer=_worker_init,
                            initargs=(ref_fv_dict, self.fixed_kwargs, self.weights,
                                      best_fitness_shared, current_render_dur),
                        )

                solutions_norm = es.ask()
                solutions_full = [
                    _expand_vector(_denormalize(np.asarray(s)), act_idx, bounds_high)
                    for s in solutions_norm
                ]
                if frozen_values:
                    for sf in solutions_full:
                        for fidx, fval in frozen_values.items():
                            sf[fidx] = fval
                solutions_full_list = [list(s) for s in solutions_full]

                # Surrogate pre-screening.
                eval_indices = list(range(len(solutions_norm)))
                surr_predictions: Optional[np.ndarray] = None
                if self.use_surrogate and surrogate is not None and surrogate.is_ready:
                    norm_arr = np.array(solutions_norm, dtype=np.float64)
                    surr_predictions = surrogate.predict(norm_arr)
                    n_keep = max(1, len(solutions_norm) // 2)
                    ranked = np.argsort(surr_predictions)
                    eval_indices = sorted(ranked[:n_keep].tolist())

                eval_full_list = [solutions_full_list[i] for i in eval_indices]
                if pool is not None:
                    eval_fitnesses = pool.map(_worker_eval, eval_full_list)
                else:
                    eval_fitnesses = [
                        _eval_single(
                            np.asarray(s), self.fixed_kwargs, current_ref_fv,
                            self.weights, best_fitness=best_fitness,
                            render_dur_s=current_render_dur,
                        )
                        for s in eval_full_list
                    ]

                fitnesses = [0.0] * len(solutions_norm)
                eval_map = dict(zip(eval_indices, eval_fitnesses))
                for i in range(len(solutions_norm)):
                    if i in eval_map:
                        fitnesses[i] = eval_map[i]
                    elif surr_predictions is not None:
                        fitnesses[i] = float(surr_predictions[i])
                    else:
                        fitnesses[i] = 1e6

                es.tell(solutions_norm, fitnesses)

                # Accumulate data for surrogate training.
                if self.use_surrogate:
                    for i in eval_indices:
                        surr_X.append(np.asarray(solutions_norm[i], dtype=np.float64))
                        surr_y.append(eval_map[i])
                    total_surr = len(surr_y)
                    if total_surr >= surr_train_threshold and (
                        surrogate is None
                        or total_surr - surr_last_train_count >= surr_retrain_interval
                    ):
                        if surrogate is None:
                            surrogate = FitnessSurrogate(input_dim=n_active)
                        surrogate.fit(np.array(surr_X), np.array(surr_y))
                        surr_last_train_count = total_surr

                        if not adsr_sweep_done and surrogate.is_ready:
                            adsr_sweep_done = True
                            best_x_red = _reduce_vector(best_x_full, act_idx)
                            best_x_norm_current = _normalize(best_x_red)
                            adsr_candidates = _surrogate_adsr_sweep(
                                surrogate, best_x_norm_current, act_idx,
                                lo_red, hi_red, top_n=20,
                            )
                            n_verify = min(5, adsr_candidates.shape[0])
                            for ci in range(n_verify):
                                cand_norm = adsr_candidates[ci]
                                cand_red = _denormalize(cand_norm)
                                cand_full = _expand_vector(cand_red, act_idx, bounds_high)
                                if frozen_values:
                                    for fidx, fval in frozen_values.items():
                                        cand_full[fidx] = fval
                                cand_fitness = _eval_single(
                                    cand_full, self.fixed_kwargs, current_ref_fv,
                                    self.weights, best_fitness=best_fitness,
                                    render_dur_s=current_render_dur,
                                )
                                evaluations += 1
                                surr_X.append(cand_norm.copy())
                                surr_y.append(cand_fitness)
                                if cand_fitness < best_fitness - 1e-9:
                                    best_fitness = cand_fitness
                                    best_x_full = cand_full.copy()
                                    non_improve = 0
                                    if best_fitness_shared is not None:
                                        best_fitness_shared.value = best_fitness
                                    es.inject([cand_norm.tolist()])

                evaluations += len(eval_fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x_full = np.asarray(solutions_full_list[gen_best_idx], dtype=np.float64)
                    non_improve = 0
                    if best_fitness_shared is not None:
                        best_fitness_shared.value = best_fitness
                else:
                    non_improve += len(fitnesses)
                history.append(best_fitness)

                if self.log_interval > 0 and (
                    evaluations // self.log_interval
                    != (evaluations - len(fitnesses)) // self.log_interval
                ):
                    elapsed = time.time() - t0
                    print(
                        f"[optim-tpe+cma/cma] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )


# ---------------------------------------------------------------------------
# Multi-note worker pool
# ---------------------------------------------------------------------------

# Per-process globals for multi-note workers.
_MN_WORKER_REF_SET_DATA: Optional[list] = None
_MN_WORKER_FIXED_KWARGS: Optional[dict] = None
_MN_WORKER_WEIGHTS: Optional[dict] = None
_MN_WORKER_ALPHA: float = 0.25
_MN_WORKER_REF_SET = None
_MN_WORKER_RENDER_DUR: Optional[float] = None


def _mn_worker_init(
    ref_set_data: list, fixed_kwargs: dict,
    weights: Optional[dict], alpha: float,
    render_dur: Optional[float] = None,
) -> None:
    global _MN_WORKER_REF_SET_DATA, _MN_WORKER_FIXED_KWARGS
    global _MN_WORKER_WEIGHTS, _MN_WORKER_ALPHA, _MN_WORKER_REF_SET
    global _MN_WORKER_RENDER_DUR
    _MN_WORKER_REF_SET_DATA = ref_set_data
    _MN_WORKER_FIXED_KWARGS = dict(fixed_kwargs)
    _MN_WORKER_WEIGHTS = dict(weights) if weights else None
    _MN_WORKER_ALPHA = alpha
    _MN_WORKER_RENDER_DUR = render_dur

    # Build the ReferenceSet once at worker init instead of per evaluation.
    from .multi_note import ReferenceSet, NoteRef
    notes = []
    for entry in ref_set_data:
        notes.append(NoteRef(
            note_name=entry["note_name"],
            freq_hz=entry["freq_hz"],
            ref_fv=_fv_from_dict(entry["ref_fv"]),
        ))
    _MN_WORKER_REF_SET = ReferenceSet.from_features(notes)


def _mn_worker_eval(x_list: List[float]) -> float:
    from .multi_note import multi_note_fitness

    assert _MN_WORKER_REF_SET is not None
    assert _MN_WORKER_FIXED_KWARGS is not None

    x = np.asarray(x_list, dtype=np.float64)
    params = decode_params(x, _MN_WORKER_FIXED_KWARGS)
    chip_model = _MN_WORKER_FIXED_KWARGS.get("chip_model")
    try:
        return float(multi_note_fitness(
            params, _MN_WORKER_REF_SET,
            weights=_MN_WORKER_WEIGHTS,
            alpha=_MN_WORKER_ALPHA,
            chip_model=chip_model,
            render_duration_s=_MN_WORKER_RENDER_DUR,
        ))
    except Exception:
        return 1e6


def _ref_set_to_data(ref_set) -> list:
    """Serialize a ReferenceSet to a list of dicts for multiprocessing."""
    return [
        {
            "note_name": n.note_name,
            "freq_hz": n.freq_hz,
            "ref_fv": _fv_to_dict(n.ref_fv),
        }
        for n in ref_set.notes
    ]


# ---------------------------------------------------------------------------
# MultiNoteOptimizer
# ---------------------------------------------------------------------------


class MultiNoteOptimizer:
    """CMA-ES optimizer that evaluates patches against multiple reference notes.

    Like :class:`Optimizer` but uses a :class:`~sidmatch.multi_note.ReferenceSet`
    instead of a single reference WAV. The 13-dim decision vector is
    identical; frequency is **not** optimized but iterated over per-note
    inside the fitness function.
    """

    # Same coarse-to-fine tiers as Optimizer.
    _DURATION_TIERS = Optimizer._DURATION_TIERS

    def __init__(
        self,
        ref_set,
        fixed_kwargs: Mapping,
        weights: Optional[Mapping[str, float]] = None,
        alpha: float = 0.25,
        budget: int = 5000,
        patience: int = 500,
        n_workers: Optional[int] = None,
        seed: int = 0,
        work_dir: Optional[Path] = None,
        log_interval: int = 100,
        x0: Optional[np.ndarray] = None,
        max_attack: int = 15,
        onset_window_s: float = 2.0,
        warm_start: bool = False,
        use_surrogate: bool = True,
        optimizer_backend: str = "cma",
        sensitivity_screen: bool = False,
        freeze_indices: Optional[dict] = None,
        adsr_bound_overrides: Optional[dict] = None,
        min_gate_frames: Optional[int] = None,
    ) -> None:
        self.use_surrogate = bool(use_surrogate)
        self.optimizer_backend = optimizer_backend
        self.sensitivity_screen = bool(sensitivity_screen)
        self.ref_set = ref_set
        self.fixed_kwargs = dict(fixed_kwargs)
        self.weights = dict(weights) if weights else None
        self.alpha = float(alpha)
        self.budget = int(budget)
        self.patience = int(patience)
        self.n_workers = int(n_workers) if n_workers is not None else (os.cpu_count() or 1)
        self.seed = int(seed)
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.log_interval = int(log_interval)
        self.max_attack = int(np.clip(max_attack, 0, 15))
        self.x0 = np.asarray(x0, dtype=np.float64) if x0 is not None else None
        self.onset_window_s = float(onset_window_s)
        self.warm_start = bool(warm_start)
        self.freeze_indices = dict(freeze_indices) if freeze_indices else {}
        self.adsr_bound_overrides = dict(adsr_bound_overrides) if adsr_bound_overrides else {}
        self.min_gate_frames = int(min_gate_frames) if min_gate_frames is not None else None
        if self.min_gate_frames is not None:
            self.fixed_kwargs["_min_gate_frames"] = self.min_gate_frames

    def _effective_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return (bounds_low, bounds_high) with ADSR overrides applied."""
        bl = BOUNDS_LOW.copy()
        bh = BOUNDS_HIGH.copy()
        bh[0] = min(float(self.max_attack), bh[0])
        for idx, (lo, hi) in self.adsr_bound_overrides.items():
            bl[idx] = max(float(lo), bl[idx])
            bh[idx] = min(float(hi), bh[idx])
        return bl, bh

    def _render_duration_for_eval(self, eval_count: int) -> Optional[float]:
        """Return the render duration in seconds for the current eval count."""
        progress = eval_count / max(1, self.budget)
        for threshold, dur_s in self._DURATION_TIERS:
            if progress < threshold:
                return dur_s
        return None

    def _ref_set_for_duration(self, dur_s: Optional[float]):
        """Return a ReferenceSet with features re-extracted at *dur_s*.

        If dur_s is None, returns the original ref_set. Otherwise truncates
        each note's ref audio and re-extracts features. For multi-note we
        don't have raw audio stored per note, so we just pass the duration
        to multi_note_fitness which truncates the candidate audio instead.
        """
        return self.ref_set

    # ---------- sensitivity screen ----------

    def _sensitivity_screen(
        self,
        x0_norm: np.ndarray,
        active_idx: list,
        fixed_kwargs: dict,
        render_dur_s: Optional[float] = None,
        bounds_high: Optional[np.ndarray] = None,
    ) -> list:
        """Run OAT sensitivity screen for multi-note optimizer.

        Same logic as :meth:`Optimizer._sensitivity_screen` but evaluates
        fitness via :func:`multi_note_fitness`.

        Returns list of active_idx positions to freeze.
        """
        from .multi_note import multi_note_fitness

        if bounds_high is None:
            bounds_high = BOUNDS_HIGH

        lo_red = BOUNDS_LOW[active_idx]
        hi_red = bounds_high[active_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _denorm(xn):
            return xn * range_red_safe + lo_red

        chip_model = fixed_kwargs.get("chip_model")

        def _eval_mn(x_full):
            params = decode_params(x_full, fixed_kwargs)
            try:
                return float(multi_note_fitness(
                    params, self.ref_set,
                    weights=self.weights, alpha=self.alpha,
                    chip_model=chip_model,
                    render_duration_s=render_dur_s,
                ))
            except Exception:
                return 1e6

        # Evaluate baseline.
        x0_full = _expand_vector(_denorm(x0_norm), active_idx, bounds_high)
        baseline = _eval_mn(x0_full)

        threshold = 0.05 * baseline if baseline > 0 else 0.0
        freeze_positions: list = []

        for pos in range(len(active_idx)):
            orig_idx = active_idx[pos]
            # Never freeze ADSR (indices 0-3 in full vector).
            if orig_idx in _IDX_ADSR:
                continue

            x_low = x0_norm.copy()
            x_low[pos] = 0.0
            f_low = _eval_mn(
                _expand_vector(_denorm(x_low), active_idx, bounds_high)
            )

            x_high = x0_norm.copy()
            x_high[pos] = 1.0
            f_high = _eval_mn(
                _expand_vector(_denorm(x_high), active_idx, bounds_high)
            )

            sensitivity = max(abs(f_low - baseline), abs(f_high - baseline))
            if sensitivity < threshold:
                freeze_positions.append(pos)
                if self.log_interval > 0:
                    print(
                        f"[sensitivity-mn] freeze {_PARAM_NAMES[orig_idx]} "
                        f"(sens={sensitivity:.4f}, thr={threshold:.4f})",
                        flush=True,
                    )
            elif self.log_interval > 0:
                print(
                    f"[sensitivity-mn] keep   {_PARAM_NAMES[orig_idx]} "
                    f"(sens={sensitivity:.4f}, thr={threshold:.4f})",
                    flush=True,
                )

        return freeze_positions

    def _checkpoint_path(self) -> Optional[Path]:
        if self.work_dir is None:
            return None
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return self.work_dir / "optim_state.json"

    def _save_checkpoint(
        self,
        best_x: np.ndarray,
        best_fitness: float,
        history: List[float],
        evaluations: int,
    ) -> None:
        path = self._checkpoint_path()
        if path is None:
            return
        best_params = decode_params(best_x, self.fixed_kwargs)
        state = {
            "best_x": np.asarray(best_x).tolist(),
            "best_fitness": float(best_fitness),
            "best_params": sid_params_to_dict(best_params),
            "history": list(map(float, history)),
            "evaluations": int(evaluations),
            "fixed_kwargs": self.fixed_kwargs,
            "seed": self.seed,
            "budget": self.budget,
            "patience": self.patience,
            "param_names": _PARAM_NAMES,
            "reference_notes": [
                {"note": n.note_name, "freq_hz": n.freq_hz}
                for n in self.ref_set.notes
            ],
            "alpha": self.alpha,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, path)

    def run(self) -> OptimizerResult:
        if self.optimizer_backend == "tpe":
            return self._run_tpe()
        if self.optimizer_backend == "tpe+cma":
            return self._run_tpe_then_cma()
        return self._run_cma()

    def _run_tpe(self) -> OptimizerResult:
        """Optuna TPE optimization path for multi-note with parallel batch evaluation."""
        try:
            import optuna
        except ImportError:
            raise ImportError(
                "optuna is required for TPE optimizer: pip install optuna"
            )
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        from .multi_note import multi_note_fitness

        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        act_idx = active_params(self.fixed_kwargs)
        # Apply caller-provided freeze_indices.
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]
        n_active = len(act_idx)

        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = (0.5 * (bounds_low + bounds_high)).copy()
        # Inject frozen values into x0.
        for fidx, fval in self.freeze_indices.items():
            best_x_full[fidx] = fval
        evaluations = 0
        non_improve = 0
        converged = False

        current_render_dur = self._render_duration_for_eval(0)
        chip_model = self.fixed_kwargs.get("chip_model")

        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(
                n_startup_trials=min(50, self.budget // 2),
                multivariate=True,
                group=True,
                constant_liar=True,
                n_ei_candidates=256,
                seed=self.seed if self.seed != 0 else None,
            ),
            direction="minimize",
        )

        def _trial_to_x_full(trial):
            """Sample params from an Optuna trial and return the full vector."""
            x_red = np.empty(n_active, dtype=np.float64)
            for i, orig_i in enumerate(act_idx):
                name = _PARAM_NAMES[orig_i]
                if orig_i in _INTEGER_PARAM_INDICES:
                    val = trial.suggest_int(
                        name, int(bounds_low[orig_i]), int(bounds_high[orig_i])
                    )
                    x_red[i] = float(val)
                else:
                    norm = trial.suggest_float(name, 0.0, 1.0)
                    x_red[i] = norm * range_red_safe[i] + lo_red[i]
            x_full = _expand_vector(x_red, act_idx, bounds_high)
            for fidx, fval in self.freeze_indices.items():
                x_full[fidx] = fval
            return x_full

        n_workers = self.n_workers

        # Build multiprocessing pool for parallel evaluation.
        pool = None
        ref_set_data = _ref_set_to_data(self.ref_set)
        if n_workers > 1:
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=n_workers,
                initializer=_mn_worker_init,
                initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                          self.alpha, current_render_dur),
            )

        try:
            while evaluations < self.budget and non_improve < self.patience:
                # Check if render duration tier has changed.
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    best_fitness = float("inf")
                    non_improve = 0
                    # Re-create pool with updated render dur.
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=n_workers,
                            initializer=_mn_worker_init,
                            initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                                      self.alpha, current_render_dur),
                        )

                # Ask Optuna for a batch of trials.
                batch_size = min(n_workers, self.budget - evaluations)
                trials = [study.ask() for _ in range(batch_size)]

                # Build full parameter vectors for each trial.
                candidates_full = [_trial_to_x_full(t) for t in trials]
                candidates_list = [list(c) for c in candidates_full]

                # Evaluate in parallel or sequentially.
                if pool is not None:
                    fitnesses = pool.map(_mn_worker_eval, candidates_list)
                else:
                    fitnesses = []
                    for c in candidates_list:
                        params = decode_params(np.asarray(c), self.fixed_kwargs)
                        try:
                            f = float(multi_note_fitness(
                                params, self.ref_set,
                                weights=self.weights,
                                alpha=self.alpha,
                                chip_model=chip_model,
                                render_duration_s=current_render_dur,
                            ))
                        except Exception:
                            f = 1e6
                        fitnesses.append(f)

                # Tell Optuna the results and update tracking.
                for trial, fitness, x_full in zip(trials, fitnesses, candidates_full):
                    study.tell(trial, fitness)
                    evaluations += 1
                    if fitness < best_fitness - 1e-9:
                        best_fitness = fitness
                        best_x_full = x_full.copy()
                        non_improve = 0
                    else:
                        non_improve += 1
                    history.append(best_fitness)

                # Checkpoint every ~100 evals.
                if self.work_dir is not None and evaluations % 100 < batch_size:
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                # Log progress.
                if self.log_interval > 0 and evaluations % self.log_interval < batch_size:
                    elapsed = time.time() - t0
                    print(
                        f"[optim-mn-tpe] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if non_improve >= self.patience:
                    converged = True
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )

    def _run_cma(self) -> OptimizerResult:
        from .multi_note import multi_note_fitness

        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        # Determine active parameter indices for this combo.
        act_idx = active_params(self.fixed_kwargs)
        # Apply caller-provided freeze_indices.
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]
        n_active = len(act_idx)

        # Build reduced bounds for CMA-ES (only active dimensions).
        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]

        # Normalization helpers: CMA-ES operates in [0,1] hypercube.
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _normalize(x_orig):
            return (x_orig - lo_red) / range_red_safe

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        # Start from caller-provided x0 or the mid-range point.
        if self.x0 is not None:
            x0_full = np.clip(self.x0, bounds_low, bounds_high)
        else:
            x0_full = 0.5 * (bounds_low + bounds_high)
        # Inject frozen values into x0_full.
        for fidx, fval in self.freeze_indices.items():
            x0_full[fidx] = fval
        x0_red = _reduce_vector(x0_full, act_idx)
        x0_norm = _normalize(x0_red)

        # --- OAT sensitivity screen: freeze low-impact params ---
        frozen_values = dict(self.freeze_indices)  # start with caller-provided freezes
        if self.sensitivity_screen and n_active > 0:
            freeze_positions = self._sensitivity_screen(
                x0_norm, act_idx, self.fixed_kwargs,
                render_dur_s=self._render_duration_for_eval(0),
                bounds_high=bounds_high,
            )
            if freeze_positions:
                for pos in freeze_positions:
                    frozen_values[act_idx[pos]] = x0_full[act_idx[pos]]
                for pos in sorted(freeze_positions, reverse=True):
                    del act_idx[pos]
                n_active = len(act_idx)
                lo_red = bounds_low[act_idx]
                hi_red = bounds_high[act_idx]
                range_red = hi_red - lo_red
                range_red_safe = np.where(range_red > 0, range_red, 1.0)

                def _normalize(x_orig):
                    return (x_orig - lo_red) / range_red_safe

                def _denormalize(x_norm):
                    return x_norm * range_red_safe + lo_red

                x0_red = _reduce_vector(x0_full, act_idx)
                x0_norm = _normalize(x0_red)
                if self.log_interval > 0:
                    print(
                        f"[sensitivity-mn] reduced active dims: "
                        f"{n_active + len(freeze_positions)} -> {n_active}",
                        flush=True,
                    )

        # --- Low-dimensional fallbacks (CMA-ES needs >= 2 dims) ---
        if n_active == 0:
            # All params frozen -- evaluate the single point and return.
            current_render_dur = self._render_duration_for_eval(0)
            chip_model = self.fixed_kwargs.get("chip_model")
            x_params = decode_params(x0_full, self.fixed_kwargs)
            try:
                fitness = float(multi_note_fitness(
                    x_params, self.ref_set,
                    weights=self.weights,
                    alpha=self.alpha,
                    chip_model=chip_model,
                    render_duration_s=current_render_dur,
                ))
            except Exception:
                fitness = 1e6
            wall = time.time() - t0
            return OptimizerResult(
                best_params=x_params,
                best_fitness=fitness,
                history=[fitness],
                evaluations=1,
                wall_time_s=wall,
                converged=True,
            )

        if n_active == 1:
            # 1-D grid search fallback (CMA-ES requires >= 2 dimensions).
            n_grid = 50
            current_render_dur = self._render_duration_for_eval(0)
            chip_model = self.fixed_kwargs.get("chip_model")
            best_fitness = float("inf")
            best_x_full_grid: np.ndarray = x0_full.copy()
            for val in np.linspace(0.0, 1.0, n_grid):
                x_red = _denormalize(np.array([val]))
                x_full = _expand_vector(x_red, act_idx, bounds_high)
                if frozen_values:
                    for fidx, fval in frozen_values.items():
                        x_full[fidx] = fval
                x_params = decode_params(x_full, self.fixed_kwargs)
                try:
                    fitness = float(multi_note_fitness(
                        x_params, self.ref_set,
                        weights=self.weights,
                        alpha=self.alpha,
                        chip_model=chip_model,
                        render_duration_s=current_render_dur,
                    ))
                except Exception:
                    fitness = 1e6
                if fitness < best_fitness:
                    best_fitness = fitness
                    best_x_full_grid = x_full.copy()
            wall = time.time() - t0
            best_params = decode_params(best_x_full_grid, self.fixed_kwargs)
            return OptimizerResult(
                best_params=best_params,
                best_fitness=best_fitness,
                history=[best_fitness],
                evaluations=n_grid,
                wall_time_s=wall,
                converged=True,
            )

        sigma0 = 0.10 if self.warm_start else 0.17

        cma_opts = {
            "bounds": [np.zeros(n_active).tolist(), np.ones(n_active).tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": self.budget,
        }
        es = cma.CMAEvolutionStrategy(x0_norm.tolist(), sigma0, cma_opts)

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = x0_full.copy()
        evaluations = 0
        non_improve = 0
        converged = False

        # Surrogate model for pre-screening candidates.
        surrogate: Optional[FitnessSurrogate] = None
        surr_X: List[np.ndarray] = []
        surr_y: List[float] = []
        surr_train_threshold = 500
        surr_retrain_interval = 200
        surr_last_train_count = 0
        adsr_sweep_done = False

        # Coarse-to-fine: current render duration tier.
        current_render_dur = self._render_duration_for_eval(0)
        ref_set_data = _ref_set_to_data(self.ref_set)

        pool = None
        if self.n_workers > 1:
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_mn_worker_init,
                initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                          self.alpha, current_render_dur),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break

                # Check if render duration tier has changed.
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    # Reset best fitness since feature comparison changed.
                    best_fitness = float("inf")
                    non_improve = 0
                    # Reset surrogate data since fitness landscape changed.
                    surr_X.clear()
                    surr_y.clear()
                    surrogate = None
                    surr_last_train_count = 0
                    adsr_sweep_done = False
                    # Re-create pool with updated render dur.
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=self.n_workers,
                            initializer=_mn_worker_init,
                            initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                                      self.alpha, current_render_dur),
                        )

                solutions_norm = es.ask()
                # Denormalize from [0,1] back to original ranges, then expand.
                solutions_full = [
                    _expand_vector(_denormalize(np.asarray(s)), act_idx, bounds_high)
                    for s in solutions_norm
                ]
                # Apply frozen parameter values from sensitivity screen.
                if frozen_values:
                    for sf in solutions_full:
                        for fidx, fval in frozen_values.items():
                            sf[fidx] = fval
                solutions_full_list = [list(s) for s in solutions_full]

                # Surrogate pre-screening.
                eval_indices = list(range(len(solutions_norm)))
                surr_predictions: Optional[np.ndarray] = None
                if self.use_surrogate and surrogate is not None and surrogate.is_ready:
                    norm_arr = np.array(solutions_norm, dtype=np.float64)
                    surr_predictions = surrogate.predict(norm_arr)
                    n_keep = max(1, len(solutions_norm) // 2)
                    ranked = np.argsort(surr_predictions)
                    eval_indices = sorted(ranked[:n_keep].tolist())

                eval_full_list = [solutions_full_list[i] for i in eval_indices]
                if pool is not None:
                    eval_fitnesses = pool.map(_mn_worker_eval, eval_full_list)
                else:
                    eval_fitnesses = []
                    chip_model = self.fixed_kwargs.get("chip_model")
                    for s in eval_full_list:
                        x = np.asarray(s, dtype=np.float64)
                        params = decode_params(x, self.fixed_kwargs)
                        try:
                            f = float(multi_note_fitness(
                                params, self.ref_set,
                                weights=self.weights,
                                alpha=self.alpha,
                                chip_model=chip_model,
                                render_duration_s=current_render_dur,
                            ))
                        except Exception:
                            f = 1e6
                        eval_fitnesses.append(f)

                # Build full fitness list.
                fitnesses = [0.0] * len(solutions_norm)
                eval_map = dict(zip(eval_indices, eval_fitnesses))
                for i in range(len(solutions_norm)):
                    if i in eval_map:
                        fitnesses[i] = eval_map[i]
                    elif surr_predictions is not None:
                        fitnesses[i] = float(surr_predictions[i])
                    else:
                        fitnesses[i] = 1e6

                es.tell(solutions_norm, fitnesses)

                # Accumulate data for surrogate training.
                if self.use_surrogate:
                    for i in eval_indices:
                        surr_X.append(np.asarray(solutions_norm[i], dtype=np.float64))
                        surr_y.append(eval_map[i])
                    total_surr = len(surr_y)
                    if total_surr >= surr_train_threshold and (
                        surrogate is None
                        or total_surr - surr_last_train_count >= surr_retrain_interval
                    ):
                        if surrogate is None:
                            surrogate = FitnessSurrogate(input_dim=n_active)
                        surrogate.fit(np.array(surr_X), np.array(surr_y))
                        surr_last_train_count = total_surr

                        # One-shot surrogate ADSR sweep after first training.
                        if not adsr_sweep_done and surrogate.is_ready:
                            adsr_sweep_done = True
                            best_x_red = _reduce_vector(best_x_full, act_idx)
                            best_x_norm_current = _normalize(best_x_red)
                            adsr_candidates = _surrogate_adsr_sweep(
                                surrogate, best_x_norm_current, act_idx,
                                lo_red, hi_red, top_n=20,
                            )
                            n_verify = min(5, adsr_candidates.shape[0])
                            chip_model_sweep = self.fixed_kwargs.get("chip_model")
                            for ci in range(n_verify):
                                cand_norm = adsr_candidates[ci]
                                cand_red = _denormalize(cand_norm)
                                cand_full = _expand_vector(cand_red, act_idx, bounds_high)
                                if frozen_values:
                                    for fidx, fval in frozen_values.items():
                                        cand_full[fidx] = fval
                                cand_params = decode_params(cand_full, self.fixed_kwargs)
                                try:
                                    cand_fitness = float(multi_note_fitness(
                                        cand_params, self.ref_set,
                                        weights=self.weights,
                                        alpha=self.alpha,
                                        chip_model=chip_model_sweep,
                                        render_duration_s=current_render_dur,
                                    ))
                                except Exception:
                                    cand_fitness = 1e6
                                evaluations += 1
                                surr_X.append(cand_norm.copy())
                                surr_y.append(cand_fitness)
                                if cand_fitness < best_fitness - 1e-9:
                                    best_fitness = cand_fitness
                                    best_x_full = cand_full.copy()
                                    non_improve = 0
                                    es.inject([cand_norm.tolist()])

                evaluations += len(eval_fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x_full = np.asarray(solutions_full_list[gen_best_idx], dtype=np.float64)
                    non_improve = 0
                else:
                    non_improve += len(fitnesses)
                history.append(best_fitness)

                if self.log_interval > 0 and (
                    evaluations // self.log_interval
                    != (evaluations - len(fitnesses)) // self.log_interval
                ):
                    elapsed = time.time() - t0
                    print(
                        f"[optim-mn] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )

    def _run_tpe_then_cma(self, tpe_fraction: float = 0.25) -> OptimizerResult:
        """Two-phase optimization: TPE exploration then CMA-ES refinement.

        Runs TPE for *tpe_fraction* of the budget to explore the search space,
        then warm-starts CMA-ES with the top-K solutions for the remaining budget.
        """
        try:
            import optuna
        except ImportError:
            raise ImportError(
                "optuna is required for TPE optimizer: pip install optuna"
            )
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        from .multi_note import multi_note_fitness

        t0 = time.time()
        bounds_low, bounds_high = self._effective_bounds()

        act_idx = active_params(self.fixed_kwargs)
        if self.freeze_indices:
            act_idx = [i for i in act_idx if i not in self.freeze_indices]
        n_active = len(act_idx)

        lo_red = bounds_low[act_idx]
        hi_red = bounds_high[act_idx]
        range_red = hi_red - lo_red
        range_red_safe = np.where(range_red > 0, range_red, 1.0)

        def _normalize(x_orig):
            return (x_orig - lo_red) / range_red_safe

        def _denormalize(x_norm):
            return x_norm * range_red_safe + lo_red

        tpe_budget = max(1, int(self.budget * tpe_fraction))
        cma_budget = self.budget - tpe_budget

        history: List[float] = []
        best_fitness = float("inf")
        best_x_full: np.ndarray = (0.5 * (bounds_low + bounds_high)).copy()
        for fidx, fval in self.freeze_indices.items():
            best_x_full[fidx] = fval
        evaluations = 0
        non_improve = 0
        converged = False

        # Collect all evaluated solutions (normalized) and their fitnesses.
        all_solutions_norm: List[np.ndarray] = []
        all_fitnesses_list: List[float] = []

        # ---- Phase 1: TPE exploration ----
        current_render_dur = self._render_duration_for_eval(0)
        chip_model = self.fixed_kwargs.get("chip_model")

        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(
                n_startup_trials=min(50, tpe_budget // 2),
                multivariate=True,
                group=True,
                constant_liar=True,
                n_ei_candidates=256,
                seed=self.seed if self.seed != 0 else None,
            ),
            direction="minimize",
        )

        def _trial_to_x_full(trial):
            x_red = np.empty(n_active, dtype=np.float64)
            for i, orig_i in enumerate(act_idx):
                name = _PARAM_NAMES[orig_i]
                if orig_i in _INTEGER_PARAM_INDICES:
                    val = trial.suggest_int(
                        name, int(bounds_low[orig_i]), int(bounds_high[orig_i])
                    )
                    x_red[i] = float(val)
                else:
                    norm = trial.suggest_float(name, 0.0, 1.0)
                    x_red[i] = norm * range_red_safe[i] + lo_red[i]
            x_full = _expand_vector(x_red, act_idx, bounds_high)
            for fidx, fval in self.freeze_indices.items():
                x_full[fidx] = fval
            return x_full

        n_workers = self.n_workers
        pool = None
        ref_set_data = _ref_set_to_data(self.ref_set)
        if n_workers > 1:
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=n_workers,
                initializer=_mn_worker_init,
                initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                          self.alpha, current_render_dur),
            )

        try:
            while evaluations < tpe_budget and non_improve < self.patience:
                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    best_fitness = float("inf")
                    non_improve = 0
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=n_workers,
                            initializer=_mn_worker_init,
                            initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                                      self.alpha, current_render_dur),
                        )

                batch_size = min(n_workers, tpe_budget - evaluations)
                trials = [study.ask() for _ in range(batch_size)]
                candidates_full = [_trial_to_x_full(t) for t in trials]
                candidates_list = [list(c) for c in candidates_full]

                if pool is not None:
                    fitnesses = pool.map(_mn_worker_eval, candidates_list)
                else:
                    fitnesses = []
                    for c in candidates_list:
                        params = decode_params(np.asarray(c), self.fixed_kwargs)
                        try:
                            f = float(multi_note_fitness(
                                params, self.ref_set,
                                weights=self.weights,
                                alpha=self.alpha,
                                chip_model=chip_model,
                                render_duration_s=current_render_dur,
                            ))
                        except Exception:
                            f = 1e6
                        fitnesses.append(f)

                for trial, fitness, x_full in zip(trials, fitnesses, candidates_full):
                    study.tell(trial, fitness)
                    evaluations += 1
                    x_red = _reduce_vector(x_full, act_idx)
                    x_norm = _normalize(x_red)
                    all_solutions_norm.append(x_norm)
                    all_fitnesses_list.append(fitness)
                    if fitness < best_fitness - 1e-9:
                        best_fitness = fitness
                        best_x_full = x_full.copy()
                        non_improve = 0
                    else:
                        non_improve += 1
                    history.append(best_fitness)

                if self.work_dir is not None and evaluations % 100 < batch_size:
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                if self.log_interval > 0 and evaluations % self.log_interval < batch_size:
                    elapsed = time.time() - t0
                    print(
                        f"[optim-mn-tpe+cma/tpe] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if non_improve >= self.patience:
                    converged = True
        finally:
            if pool is not None:
                pool.close()
                pool.join()
                pool = None

        if converged or cma_budget <= 0 or n_active < 2:
            self._save_checkpoint(best_x_full, best_fitness, history, evaluations)
            wall = time.time() - t0
            best_params = decode_params(best_x_full, self.fixed_kwargs)
            return OptimizerResult(
                best_params=best_params,
                best_fitness=best_fitness,
                history=history,
                evaluations=evaluations,
                wall_time_s=wall,
                converged=converged,
            )

        # ---- Phase 2: CMA-ES refinement warm-started from TPE results ----

        all_fitnesses_arr = np.array(all_fitnesses_list, dtype=np.float64)
        all_solutions_arr = np.array(all_solutions_norm, dtype=np.float64)
        k = min(20, max(1, len(all_fitnesses_list) // 5))
        top_k_indices = np.argsort(all_fitnesses_arr)[:k]
        top_k_solutions = all_solutions_arr[top_k_indices]

        x0_cma = np.mean(top_k_solutions, axis=0)
        if k > 1:
            per_dim_std = np.std(top_k_solutions, axis=0)
        else:
            per_dim_std = np.full(n_active, 0.1)
        per_dim_std = np.clip(per_dim_std, 0.01, 0.5)

        sigma0 = float(np.median(per_dim_std))
        if sigma0 < 1e-6:
            sigma0 = 0.1
        cma_stds = per_dim_std / sigma0

        x0_cma = np.clip(x0_cma, 0.0, 1.0)

        cma_opts = {
            "bounds": [np.zeros(n_active).tolist(), np.ones(n_active).tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": cma_budget,
            "CMA_stds": cma_stds.tolist(),
        }
        es = cma.CMAEvolutionStrategy(x0_cma.tolist(), sigma0, cma_opts)

        # Limit injected solutions to popsize to avoid pycma error.
        inject_solutions = [s.tolist() for s in top_k_solutions[:es.popsize]]
        es.inject(inject_solutions)

        non_improve = 0

        # Surrogate model for pre-screening candidates.
        surrogate: Optional[FitnessSurrogate] = None
        surr_X: List[np.ndarray] = []
        surr_y: List[float] = []
        surr_train_threshold = 500
        surr_retrain_interval = 200
        surr_last_train_count = 0
        adsr_sweep_done = False

        # Seed surrogate with TPE data.
        if self.use_surrogate:
            surr_X = list(all_solutions_arr)
            surr_y = list(all_fitnesses_list)

        current_render_dur = self._render_duration_for_eval(evaluations)

        frozen_values = dict(self.freeze_indices)

        pool = None
        if self.n_workers > 1:
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_mn_worker_init,
                initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                          self.alpha, current_render_dur),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break

                new_render_dur = self._render_duration_for_eval(evaluations)
                if new_render_dur != current_render_dur:
                    current_render_dur = new_render_dur
                    best_fitness = float("inf")
                    non_improve = 0
                    surr_X.clear()
                    surr_y.clear()
                    surrogate = None
                    surr_last_train_count = 0
                    adsr_sweep_done = False
                    if pool is not None:
                        pool.close()
                        pool.join()
                        ctx = mp.get_context("fork")
                        pool = ctx.Pool(
                            processes=self.n_workers,
                            initializer=_mn_worker_init,
                            initargs=(ref_set_data, self.fixed_kwargs, self.weights,
                                      self.alpha, current_render_dur),
                        )

                solutions_norm = es.ask()
                solutions_full = [
                    _expand_vector(_denormalize(np.asarray(s)), act_idx, bounds_high)
                    for s in solutions_norm
                ]
                if frozen_values:
                    for sf in solutions_full:
                        for fidx, fval in frozen_values.items():
                            sf[fidx] = fval
                solutions_full_list = [list(s) for s in solutions_full]

                # Surrogate pre-screening.
                eval_indices = list(range(len(solutions_norm)))
                surr_predictions: Optional[np.ndarray] = None
                if self.use_surrogate and surrogate is not None and surrogate.is_ready:
                    norm_arr = np.array(solutions_norm, dtype=np.float64)
                    surr_predictions = surrogate.predict(norm_arr)
                    n_keep = max(1, len(solutions_norm) // 2)
                    ranked = np.argsort(surr_predictions)
                    eval_indices = sorted(ranked[:n_keep].tolist())

                eval_full_list = [solutions_full_list[i] for i in eval_indices]
                if pool is not None:
                    eval_fitnesses = pool.map(_mn_worker_eval, eval_full_list)
                else:
                    eval_fitnesses = []
                    for s in eval_full_list:
                        x = np.asarray(s, dtype=np.float64)
                        params = decode_params(x, self.fixed_kwargs)
                        try:
                            f = float(multi_note_fitness(
                                params, self.ref_set,
                                weights=self.weights,
                                alpha=self.alpha,
                                chip_model=chip_model,
                                render_duration_s=current_render_dur,
                            ))
                        except Exception:
                            f = 1e6
                        eval_fitnesses.append(f)

                fitnesses = [0.0] * len(solutions_norm)
                eval_map = dict(zip(eval_indices, eval_fitnesses))
                for i in range(len(solutions_norm)):
                    if i in eval_map:
                        fitnesses[i] = eval_map[i]
                    elif surr_predictions is not None:
                        fitnesses[i] = float(surr_predictions[i])
                    else:
                        fitnesses[i] = 1e6

                es.tell(solutions_norm, fitnesses)

                # Accumulate data for surrogate training.
                if self.use_surrogate:
                    for i in eval_indices:
                        surr_X.append(np.asarray(solutions_norm[i], dtype=np.float64))
                        surr_y.append(eval_map[i])
                    total_surr = len(surr_y)
                    if total_surr >= surr_train_threshold and (
                        surrogate is None
                        or total_surr - surr_last_train_count >= surr_retrain_interval
                    ):
                        if surrogate is None:
                            surrogate = FitnessSurrogate(input_dim=n_active)
                        surrogate.fit(np.array(surr_X), np.array(surr_y))
                        surr_last_train_count = total_surr

                        if not adsr_sweep_done and surrogate.is_ready:
                            adsr_sweep_done = True
                            best_x_red = _reduce_vector(best_x_full, act_idx)
                            best_x_norm_current = _normalize(best_x_red)
                            adsr_candidates = _surrogate_adsr_sweep(
                                surrogate, best_x_norm_current, act_idx,
                                lo_red, hi_red, top_n=20,
                            )
                            n_verify = min(5, adsr_candidates.shape[0])
                            chip_model_sweep = self.fixed_kwargs.get("chip_model")
                            for ci in range(n_verify):
                                cand_norm = adsr_candidates[ci]
                                cand_red = _denormalize(cand_norm)
                                cand_full = _expand_vector(cand_red, act_idx, bounds_high)
                                if frozen_values:
                                    for fidx, fval in frozen_values.items():
                                        cand_full[fidx] = fval
                                cand_params = decode_params(cand_full, self.fixed_kwargs)
                                try:
                                    cand_fitness = float(multi_note_fitness(
                                        cand_params, self.ref_set,
                                        weights=self.weights,
                                        alpha=self.alpha,
                                        chip_model=chip_model_sweep,
                                        render_duration_s=current_render_dur,
                                    ))
                                except Exception:
                                    cand_fitness = 1e6
                                evaluations += 1
                                surr_X.append(cand_norm.copy())
                                surr_y.append(cand_fitness)
                                if cand_fitness < best_fitness - 1e-9:
                                    best_fitness = cand_fitness
                                    best_x_full = cand_full.copy()
                                    non_improve = 0
                                    es.inject([cand_norm.tolist()])

                evaluations += len(eval_fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x_full = np.asarray(solutions_full_list[gen_best_idx], dtype=np.float64)
                    non_improve = 0
                else:
                    non_improve += len(fitnesses)
                history.append(best_fitness)

                if self.log_interval > 0 and (
                    evaluations // self.log_interval
                    != (evaluations - len(fitnesses)) // self.log_interval
                ):
                    elapsed = time.time() - t0
                    print(
                        f"[optim-mn-tpe+cma/cma] evals={evaluations}/{self.budget} "
                        f"best={best_fitness:.4f} dims={n_active}/{N_DIMS} t={elapsed:.1f}s",
                        flush=True,
                    )

                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        self._save_checkpoint(best_x_full, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x_full, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )
