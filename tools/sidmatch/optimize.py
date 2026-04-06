"""CMA-ES optimizer for SID instrument matching.

Exposes a continuous-parameter optimizer that searches SID patch space
for a patch whose rendered audio matches a reference WAV (as scored by
:func:`sidmatch.fitness.distance`).

The decision vector is continuous. Discrete fields (waveform,
filter_mode) are fixed per run and passed via ``fixed_kwargs``.
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

from .render import SidParams, render_pyresid
from .features import FeatureVec, extract, CANONICAL_SR
from .fitness import distance


# ---------------------------------------------------------------------------
# Decision-vector layout
# ---------------------------------------------------------------------------
#
# x[0]  attack          0..15
# x[1]  decay           0..15
# x[2]  sustain         0..15
# x[3]  release         0..15
# x[4]  pulse_width     0..4095
# x[5]  filter_cutoff   0..2047
# x[6]  filter_resonance 0..15
# x[7..10] pw_table values at 4 evenly-spaced frames (0..4095)
#
# Discrete (fixed_kwargs): waveform, filter_mode, filter_voice1, ring_mod,
# sync, volume, gate_frames, release_frames, frequency.
# ---------------------------------------------------------------------------

PW_BREAKPOINTS = 4  # number of PW-modulation breakpoints

BOUNDS_LOW = np.array(
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] + [0.0] * PW_BREAKPOINTS,
    dtype=np.float64,
)
BOUNDS_HIGH = np.array(
    [15.0, 15.0, 15.0, 15.0, 4095.0, 2047.0, 15.0] + [4095.0] * PW_BREAKPOINTS,
    dtype=np.float64,
)
N_DIMS = BOUNDS_LOW.size

_PARAM_NAMES = [
    "attack",
    "decay",
    "sustain",
    "release",
    "pulse_width",
    "filter_cutoff",
    "filter_resonance",
] + [f"pw_bp_{i}" for i in range(PW_BREAKPOINTS)]


def _clip_int(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(float(v)))))


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
    x[4] = sid_params.pulse_width
    x[5] = sid_params.filter_cutoff
    x[6] = sid_params.filter_resonance
    # pw_table breakpoints
    if sid_params.pw_table:
        # Sample PW table at the 4 breakpoint positions.
        total = max(1, sid_params.gate_frames)
        for i in range(PW_BREAKPOINTS):
            target_frame = int(i * (total - 1) / max(1, PW_BREAKPOINTS - 1))
            # find closest entry
            closest = min(
                sid_params.pw_table,
                key=lambda t: abs(t[0] - target_frame),
            )
            x[7 + i] = closest[1]
    else:
        x[7:7 + PW_BREAKPOINTS] = sid_params.pulse_width
    return x


def decode_params(x: np.ndarray, fixed_kwargs: Mapping) -> SidParams:
    """Decode a decision vector plus ``fixed_kwargs`` into a SidParams.

    Continuous values are clipped-and-rounded to the appropriate integer
    range. Bypasses pw_table construction when the waveform contains no
    pulse component or when all breakpoints coincide with ``pulse_width``.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size != N_DIMS:
        raise ValueError(f"expected {N_DIMS} dims, got {x.size}")

    attack = _clip_int(x[0], 0, 15)
    decay = _clip_int(x[1], 0, 15)
    sustain = _clip_int(x[2], 0, 15)
    release = _clip_int(x[3], 0, 15)
    pulse_width = _clip_int(x[4], 0, 4095)
    filter_cutoff = _clip_int(x[5], 0, 2047)
    filter_resonance = _clip_int(x[6], 0, 15)

    kwargs = dict(fixed_kwargs)
    gate_frames = int(kwargs.get("gate_frames", 50))

    # PW table: build only if waveform has pulse component and breakpoints vary.
    waveform = kwargs.get("waveform", "saw")
    has_pulse = "pulse" in str(waveform).lower()

    bp_values = [_clip_int(x[7 + i], 0, 4095) for i in range(PW_BREAKPOINTS)]
    pw_table: Optional[List[Tuple[int, int]]] = None
    if has_pulse and PW_BREAKPOINTS >= 2 and max(bp_values) - min(bp_values) > 16:
        # Distribute breakpoints across gate_frames.
        pw_table = []
        for i, v in enumerate(bp_values):
            frame = int(i * (gate_frames - 1) / (PW_BREAKPOINTS - 1))
            pw_table.append((frame, v))

    return SidParams(
        waveform=str(waveform),
        attack=attack,
        decay=decay,
        sustain=sustain,
        release=release,
        pulse_width=pulse_width,
        pw_table=pw_table,
        filter_cutoff=filter_cutoff,
        filter_resonance=filter_resonance,
        filter_mode=str(kwargs.get("filter_mode", "off")),
        filter_voice1=bool(kwargs.get("filter_voice1", has_pulse or kwargs.get("filter_mode", "off") != "off")),
        ring_mod=bool(kwargs.get("ring_mod", False)),
        sync=bool(kwargs.get("sync", False)),
        frequency=float(kwargs.get("frequency", 440.0)),
        gate_frames=int(kwargs.get("gate_frames", 50)),
        release_frames=int(kwargs.get("release_frames", 50)),
        volume=int(kwargs.get("volume", 15)),
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


def _worker_init(ref_fv_dict: dict, fixed_kwargs: dict, weights: Optional[dict]) -> None:
    global _WORKER_REF_FV, _WORKER_FIXED_KWARGS, _WORKER_WEIGHTS
    _WORKER_REF_FV = _fv_from_dict(ref_fv_dict)
    _WORKER_FIXED_KWARGS = dict(fixed_kwargs)
    _WORKER_WEIGHTS = dict(weights) if weights else None


def _worker_eval(x_list: List[float]) -> float:
    assert _WORKER_REF_FV is not None and _WORKER_FIXED_KWARGS is not None
    x = np.asarray(x_list, dtype=np.float64)
    params = decode_params(x, _WORKER_FIXED_KWARGS)
    chip_model = _WORKER_FIXED_KWARGS.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)
        fv = extract(audio, CANONICAL_SR)
        return float(distance(_WORKER_REF_FV, fv, weights=_WORKER_WEIGHTS))
    except Exception as e:
        # Penalize broken candidates heavily.
        return 1e6


def _eval_single(
    x: np.ndarray,
    fixed_kwargs: dict,
    ref_fv: FeatureVec,
    weights: Optional[dict],
) -> float:
    """In-process evaluation (used when n_workers=1)."""
    params = decode_params(x, fixed_kwargs)
    chip_model = fixed_kwargs.get("chip_model")
    try:
        audio = render_pyresid(params, sample_rate=CANONICAL_SR, chip_model=chip_model)
        fv = extract(audio, CANONICAL_SR)
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
    ) -> None:
        self.ref_frequency_hz = float(ref_frequency_hz)
        self.fixed_kwargs = dict(fixed_kwargs)
        self.fixed_kwargs.setdefault("frequency", self.ref_frequency_hz)
        # Pick sensible defaults for envelope timing so the SID renders 2s.
        self.fixed_kwargs.setdefault("gate_frames", 50)
        self.fixed_kwargs.setdefault("release_frames", 50)
        self.weights = dict(weights) if weights else None
        self.budget = int(budget)
        self.patience = int(patience)
        self.n_workers = int(n_workers) if n_workers is not None else (os.cpu_count() or 1)
        self.seed = int(seed)
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.log_interval = int(log_interval)

        # Load reference features.
        if ref_audio is not None and ref_sr is not None:
            audio = np.asarray(ref_audio, dtype=np.float32)
            sr = int(ref_sr)
        elif ref_wav_path is not None:
            audio, sr = load_reference_audio(Path(ref_wav_path))
        else:
            raise ValueError("must provide either ref_wav_path or ref_audio+ref_sr")
        self.ref_fv = extract(audio, sr)

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
        # Start from the mid-range point.
        x0 = 0.5 * (BOUNDS_LOW + BOUNDS_HIGH)
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
        ref_fv_dict = _fv_to_dict(self.ref_fv)
        if self.n_workers > 1:
            ctx = mp.get_context("fork")
            pool = ctx.Pool(
                processes=self.n_workers,
                initializer=_worker_init,
                initargs=(ref_fv_dict, self.fixed_kwargs, self.weights),
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
                        _eval_single(np.asarray(s), self.fixed_kwargs, self.ref_fv, self.weights)
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
