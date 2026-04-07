"""CMA-ES optimizer for SID instrument matching.

Exposes a continuous-parameter optimizer that searches SID patch space
for a patch whose rendered audio matches a reference WAV (as scored by
:func:`sidmatch.fitness.distance`).

The decision vector is continuous. Discrete fields (waveform,
filter_mode, wt_use_test_bit, wt_attack_waveform) are fixed per run
and passed via ``fixed_kwargs``.
"""

from __future__ import annotations

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
# x[6]  pw_min              0..4095
# x[7]  pw_max              0..4095
# x[8]  filter_cutoff_start 0..2047
# x[9]  filter_cutoff_end   0..2047
# x[10] filter_sweep_frames 0..100
# x[11] filter_resonance    0..15
# x[12] wt_attack_frames    1..5
#
# Discrete (fixed_kwargs): wt_sustain_waveform, wt_attack_waveform,
# filter_mode, wt_use_test_bit, volume, frequency, chip_model, pw_mode.
# ---------------------------------------------------------------------------

BOUNDS_LOW = np.array(
    [0.0, 0.0, 0.0, 0.0,     # ADSR
     0.0, -50.0, 0.0, 0.0,   # PW sweep
     0.0, 0.0, 0.0,          # filter sweep start/end/frames
     0.0,                     # filter resonance
     1.0],                    # wt_attack_frames
    dtype=np.float64,
)
BOUNDS_HIGH = np.array(
    [15.0, 15.0, 15.0, 15.0,     # ADSR
     4095.0, 50.0, 4095.0, 4095.0,  # PW sweep
     2047.0, 2047.0, 100.0,         # filter sweep start/end/frames
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
    "pw_min",
    "pw_max",
    "filter_cutoff_start",
    "filter_cutoff_end",
    "filter_sweep_frames",
    "filter_resonance",
    "wt_attack_frames",
]


def _clip_int(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(float(v)))))


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
    x[6] = sid_params.pw_min
    x[7] = sid_params.pw_max
    x[8] = sid_params.effective_filter_cutoff_start()
    x[9] = sid_params.effective_filter_cutoff_end()
    x[10] = sid_params.filter_sweep_frames
    x[11] = sid_params.filter_resonance
    x[12] = sid_params.wt_attack_frames
    return x


def decode_params(x: np.ndarray, fixed_kwargs: Mapping) -> SidParams:
    """Decode a decision vector plus ``fixed_kwargs`` into a SidParams.

    Continuous values are clipped-and-rounded to the appropriate integer
    range. Gate and release frames are computed from ADSR timing.
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
    pw_min_val = _clip_int(x[6], 0, 4095)
    pw_max_val = _clip_int(x[7], 0, 4095)
    filter_cutoff_start = _clip_int(x[8], 0, 2047)
    filter_cutoff_end = _clip_int(x[9], 0, 2047)
    filter_sweep_frames = _clip_int(x[10], 0, 100)
    filter_resonance = _clip_int(x[11], 0, 15)
    wt_attack_frames = _clip_int(x[12], 1, 5)

    # Ensure pw_min <= pw_max
    if pw_min_val > pw_max_val:
        pw_min_val, pw_max_val = pw_max_val, pw_min_val

    kwargs = dict(fixed_kwargs)

    # Compute ADSR-aware gate/release frames
    gate_frames, release_frames = compute_render_duration(attack, decay, sustain, release)

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
    return d


def sid_params_from_dict(d: dict) -> SidParams:
    kw = dict(d)
    if kw.get("pw_table"):
        kw["pw_table"] = [tuple(t) for t in kw["pw_table"]]
    if kw.get("wavetable"):
        kw["wavetable"] = [tuple(t) for t in kw["wavetable"]]
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


def _worker_init(
    ref_fv_dict: dict,
    fixed_kwargs: dict,
    weights: Optional[dict],
    best_fitness_val: Optional[mp.Value] = None,
) -> None:
    global _WORKER_REF_FV, _WORKER_FIXED_KWARGS, _WORKER_WEIGHTS, _WORKER_BEST_FITNESS
    _WORKER_REF_FV = _fv_from_dict(ref_fv_dict)
    _WORKER_FIXED_KWARGS = dict(fixed_kwargs)
    _WORKER_WEIGHTS = dict(weights) if weights else None
    _WORKER_BEST_FITNESS = best_fitness_val


def _worker_eval(x_list: List[float]) -> float:
    assert _WORKER_REF_FV is not None and _WORKER_FIXED_KWARGS is not None
    x = np.asarray(x_list, dtype=np.float64)
    params = decode_params(x, _WORKER_FIXED_KWARGS)
    chip_model = _WORKER_FIXED_KWARGS.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)

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
) -> float:
    """In-process evaluation (used when n_workers=1)."""
    params = decode_params(x, fixed_kwargs)
    chip_model = fixed_kwargs.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)

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
    return {
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
    }


def _fv_from_dict(d: dict) -> FeatureVec:
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
    ) -> None:
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
        self.x0 = np.asarray(x0, dtype=np.float64) if x0 is not None else None

        # Load reference features.
        if ref_fv is not None:
            self.ref_fv = ref_fv
        elif ref_audio is not None and ref_sr is not None:
            audio = np.asarray(ref_audio, dtype=np.float32)
            sr = int(ref_sr)
            self.ref_fv = extract(audio, sr)
        elif ref_wav_path is not None:
            audio, sr = load_reference_audio(Path(ref_wav_path))
            self.ref_fv = extract(audio, sr)
        else:
            raise ValueError("must provide ref_fv, ref_wav_path, or ref_audio+ref_sr")

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
        t0 = time.time()
        # Start from caller-provided x0 or the mid-range point.
        x0 = self.x0 if self.x0 is not None else 0.5 * (BOUNDS_LOW + BOUNDS_HIGH)
        # sigma0 = one quarter of the average range.
        mean_range = float((BOUNDS_HIGH - BOUNDS_LOW).mean())
        sigma0 = mean_range / 6.0

        cma_opts = {
            "bounds": [BOUNDS_LOW.tolist(), BOUNDS_HIGH.tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": self.budget,
            "CMA_stds": (BOUNDS_HIGH - BOUNDS_LOW).tolist(),
        }
        es = cma.CMAEvolutionStrategy(x0.tolist(), sigma0, cma_opts)

        history: List[float] = []
        best_fitness = float("inf")
        best_x: np.ndarray = x0.copy()
        evaluations = 0
        non_improve = 0
        converged = False

        # Build pool if parallel.
        pool = None
        best_fitness_shared = None
        ref_fv_dict = _fv_to_dict(self.ref_fv)
        if self.n_workers > 1:
            best_fitness_shared = mp.Value('d', float('inf'))
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights, best_fitness_shared),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break
                solutions = es.ask()
                solutions_list = [list(s) for s in solutions]
                if pool is not None:
                    fitnesses = pool.map(_worker_eval, solutions_list)
                else:
                    fitnesses = [
                        _eval_single(
                            np.asarray(s), self.fixed_kwargs, self.ref_fv,
                            self.weights, best_fitness=best_fitness,
                        )
                        for s in solutions_list
                    ]
                es.tell(solutions, fitnesses)

                evaluations += len(fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x = np.asarray(solutions_list[gen_best_idx], dtype=np.float64)
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
                        f"best={best_fitness:.4f} t={elapsed:.1f}s",
                        flush=True,
                    )

                # Checkpoint every ~100 evals.
                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x, best_fitness, history, evaluations)

                # Patience stop.
                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        # Final checkpoint.
        self._save_checkpoint(best_x, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x, self.fixed_kwargs)
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


def _mn_worker_init(
    ref_set_data: list, fixed_kwargs: dict,
    weights: Optional[dict], alpha: float,
) -> None:
    global _MN_WORKER_REF_SET_DATA, _MN_WORKER_FIXED_KWARGS
    global _MN_WORKER_WEIGHTS, _MN_WORKER_ALPHA, _MN_WORKER_REF_SET
    _MN_WORKER_REF_SET_DATA = ref_set_data
    _MN_WORKER_FIXED_KWARGS = dict(fixed_kwargs)
    _MN_WORKER_WEIGHTS = dict(weights) if weights else None
    _MN_WORKER_ALPHA = alpha

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
    ) -> None:
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
        self.x0 = np.asarray(x0, dtype=np.float64) if x0 is not None else None

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
        from .multi_note import multi_note_fitness

        t0 = time.time()
        # Start from caller-provided x0 or the mid-range point.
        x0 = self.x0 if self.x0 is not None else 0.5 * (BOUNDS_LOW + BOUNDS_HIGH)
        mean_range = float((BOUNDS_HIGH - BOUNDS_LOW).mean())
        sigma0 = mean_range / 6.0

        cma_opts = {
            "bounds": [BOUNDS_LOW.tolist(), BOUNDS_HIGH.tolist()],
            "seed": self.seed if self.seed != 0 else 1,
            "verbose": -9,
            "maxfevals": self.budget,
            "CMA_stds": (BOUNDS_HIGH - BOUNDS_LOW).tolist(),
        }
        es = cma.CMAEvolutionStrategy(x0.tolist(), sigma0, cma_opts)

        history: List[float] = []
        best_fitness = float("inf")
        best_x: np.ndarray = x0.copy()
        evaluations = 0
        non_improve = 0
        converged = False

        pool = None
        if self.n_workers > 1:
            ref_set_data = _ref_set_to_data(self.ref_set)
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_mn_worker_init,
                initargs=(ref_set_data, self.fixed_kwargs, self.weights, self.alpha),
            )

        try:
            while evaluations < self.budget:
                if es.stop():
                    break
                solutions = es.ask()
                solutions_list = [list(s) for s in solutions]

                if pool is not None:
                    fitnesses = pool.map(_mn_worker_eval, solutions_list)
                else:
                    fitnesses = []
                    chip_model = self.fixed_kwargs.get("chip_model")
                    for s in solutions_list:
                        x = np.asarray(s, dtype=np.float64)
                        params = decode_params(x, self.fixed_kwargs)
                        try:
                            f = float(multi_note_fitness(
                                params, self.ref_set,
                                weights=self.weights,
                                alpha=self.alpha,
                                chip_model=chip_model,
                            ))
                        except Exception:
                            f = 1e6
                        fitnesses.append(f)

                es.tell(solutions, fitnesses)

                evaluations += len(fitnesses)
                gen_best = float(min(fitnesses))
                gen_best_idx = int(np.argmin(fitnesses))
                if gen_best < best_fitness - 1e-9:
                    best_fitness = gen_best
                    best_x = np.asarray(solutions_list[gen_best_idx], dtype=np.float64)
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
                        f"best={best_fitness:.4f} t={elapsed:.1f}s",
                        flush=True,
                    )

                if self.work_dir is not None and (
                    evaluations // 100
                    != (evaluations - len(fitnesses)) // 100
                ):
                    self._save_checkpoint(best_x, best_fitness, history, evaluations)

                if non_improve >= self.patience:
                    converged = True
                    break
        finally:
            if pool is not None:
                pool.close()
                pool.join()

        self._save_checkpoint(best_x, best_fitness, history, evaluations)

        wall = time.time() - t0
        best_params = decode_params(best_x, self.fixed_kwargs)
        return OptimizerResult(
            best_params=best_params,
            best_fitness=best_fitness,
            history=history,
            evaluations=evaluations,
            wall_time_s=wall,
            converged=converged,
        )
