"""Small grid search over discrete SID fields (waveform, filter_mode).

For each discrete combo runs a short CMA-ES pass and collects results.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .optimize import Optimizer, OptimizerResult


WAVEFORMS = [
    "saw",
    "pulse",
    "triangle",
    "saw+pulse",
    "triangle+pulse",
    "noise",
]
FILTER_MODES = ["off", "lp", "bp", "hp"]


def grid_search(
    ref_wav_path: Path,
    ref_frequency_hz: float,
    work_dir: Path,
    per_combo_budget: int = 300,
    n_workers: Optional[int] = None,
    patience: int = 150,
    seed: int = 0,
    weights: Optional[dict] = None,
    waveforms: Optional[List[str]] = None,
    filter_modes: Optional[List[str]] = None,
    verbose: bool = True,
) -> List[OptimizerResult]:
    """Run a short CMA-ES pass over each (waveform, filter_mode) combo.

    Returns results sorted ascending by ``best_fitness``.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    wfs = waveforms or WAVEFORMS
    fms = filter_modes or FILTER_MODES

    results: List[OptimizerResult] = []
    combos = [(w, f) for w in wfs for f in fms]
    for i, (wf, fm) in enumerate(combos):
        combo_dir = work_dir / f"grid_{wf.replace('+', '_')}_{fm}"
        fixed = {
            "waveform": wf,
            "filter_mode": fm,
            "filter_voice1": (fm != "off"),
        }
        if verbose:
            print(
                f"[grid {i+1}/{len(combos)}] wf={wf} filter={fm} "
                f"budget={per_combo_budget}",
                flush=True,
            )
        opt = Optimizer(
            ref_wav_path=ref_wav_path,
            ref_frequency_hz=ref_frequency_hz,
            fixed_kwargs=fixed,
            weights=weights,
            budget=per_combo_budget,
            patience=patience,
            n_workers=n_workers,
            seed=seed,
            work_dir=combo_dir,
            log_interval=0,
        )
        res = opt.run()
        if verbose:
            print(
                f"[grid {i+1}/{len(combos)}] -> fitness={res.best_fitness:.4f} "
                f"evals={res.evaluations} time={res.wall_time_s:.1f}s",
                flush=True,
            )
        results.append(res)

    results.sort(key=lambda r: r.best_fitness)
    return results
