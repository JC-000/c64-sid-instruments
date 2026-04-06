"""Grid search over discrete SID fields.

Searches over combinations of: sustain waveform, attack waveform,
filter mode, and test bit usage. For each combo runs a short CMA-ES
pass and collects results.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .optimize import Optimizer, OptimizerResult


# Sustain waveforms to try.
SUSTAIN_WAVEFORMS = ["saw", "pulse", "triangle"]

# Attack waveforms: None means same-as-sustain.
ATTACK_WAVEFORMS = [None, "noise", "pulse+saw", "saw+triangle"]

FILTER_MODES = ["off", "lp", "bp", "hp"]

TEST_BIT_OPTIONS = [False, True]


def _build_combos(
    sustain_waveforms: Optional[List[str]] = None,
    attack_waveforms: Optional[List[Optional[str]]] = None,
    filter_modes: Optional[List[str]] = None,
    test_bit_options: Optional[List[bool]] = None,
) -> List[dict]:
    """Build a filtered list of discrete parameter combos.

    Skips nonsensical combinations:
    - noise as sustain waveform (it has no pitch)
    - test bit + noise attack (redundant)

    Aims for ~30-50 combos.
    """
    sws = sustain_waveforms or SUSTAIN_WAVEFORMS
    aws = attack_waveforms or ATTACK_WAVEFORMS
    fms = filter_modes or FILTER_MODES
    tbs = test_bit_options or TEST_BIT_OPTIONS

    combos = []
    for sw in sws:
        for aw in aws:
            for fm in fms:
                for tb in tbs:
                    # Skip test bit + noise attack (redundant - test bit
                    # resets phase, noise is random anyway)
                    if tb and aw == "noise":
                        continue
                    combo = {
                        "wt_sustain_waveform": sw,
                        "wt_attack_waveform": aw if aw else "same_as_sustain",
                        "filter_mode": fm,
                        "filter_voice1": (fm != "off"),
                        "wt_use_test_bit": tb,
                    }
                    combos.append(combo)
    return combos


def grid_search(
    ref_wav_path: Path,
    ref_frequency_hz: float,
    work_dir: Path,
    per_combo_budget: int = 300,
    n_workers: Optional[int] = None,
    patience: int = 150,
    seed: int = 0,
    weights: Optional[dict] = None,
    sustain_waveforms: Optional[List[str]] = None,
    attack_waveforms: Optional[List[Optional[str]]] = None,
    filter_modes: Optional[List[str]] = None,
    test_bit_options: Optional[List[bool]] = None,
    verbose: bool = True,
) -> List[OptimizerResult]:
    """Run a short CMA-ES pass over each discrete combo.

    Returns results sorted ascending by ``best_fitness``.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    combos = _build_combos(
        sustain_waveforms=sustain_waveforms,
        attack_waveforms=attack_waveforms,
        filter_modes=filter_modes,
        test_bit_options=test_bit_options,
    )

    results: List[OptimizerResult] = []
    for i, combo in enumerate(combos):
        sw = combo["wt_sustain_waveform"]
        aw = combo["wt_attack_waveform"]
        fm = combo["filter_mode"]
        tb = combo["wt_use_test_bit"]

        combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
        combo_dir = work_dir / combo_label.replace("+", "_")

        if verbose:
            print(
                f"[grid {i+1}/{len(combos)}] sustain={sw} attack={aw} "
                f"filter={fm} test_bit={tb} budget={per_combo_budget}",
                flush=True,
            )
        opt = Optimizer(
            ref_wav_path=ref_wav_path,
            ref_frequency_hz=ref_frequency_hz,
            fixed_kwargs=combo,
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
