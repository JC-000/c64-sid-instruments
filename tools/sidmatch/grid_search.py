"""Grid search over discrete SID fields.

Two-phase approach:
  1. **Fast screening** -- one render per discrete combo with sensible
     mid-range continuous defaults.  ~42 evaluations total.
  2. **Top-K refinement** -- full CMA-ES on the best *K* combos from
     phase 1 (default K=3).

The old exhaustive strategy (mini CMA-ES per combo) is preserved as
:func:`grid_search_exhaustive`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from .optimize import (
    Optimizer,
    OptimizerResult,
    load_reference_audio,
    _eval_single,
    N_DIMS,
)
from .features import FeatureVec, extract, CANONICAL_SR


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


# ---------------------------------------------------------------------------
# Sensible mid-range defaults for fast screening
# ---------------------------------------------------------------------------

_SCREENING_DEFAULTS = dict(
    attack=0,          # instant attack
    decay=9,           # 750ms decay
    sustain=4,         # low sustain
    release=7,         # 240ms release
    pw_start=2048,
    pw_delta=4,
    pw_min=512,
    pw_max=3584,
    filter_cutoff_start=1024,
    filter_cutoff_end=200,
    filter_sweep_frames=30,
    filter_resonance=8,
    wt_attack_frames=2,
)


def _screen_combo(
    combo: dict,
    ref_fv: FeatureVec,
    ref_frequency_hz: float,
    weights: Optional[dict] = None,
    chip_model: Optional[str] = None,
) -> float:
    """Render one combo with mid-range continuous defaults and return fitness."""
    from .render import render_pyresid

    # Build fixed_kwargs with frequency and chip_model
    fixed = dict(combo)
    fixed["frequency"] = ref_frequency_hz
    if chip_model:
        fixed["chip_model"] = chip_model

    # Build a decision vector from the screening defaults
    x = np.zeros(N_DIMS, dtype=np.float64)
    x[0] = _SCREENING_DEFAULTS["attack"]
    x[1] = _SCREENING_DEFAULTS["decay"]
    x[2] = _SCREENING_DEFAULTS["sustain"]
    x[3] = _SCREENING_DEFAULTS["release"]
    x[4] = _SCREENING_DEFAULTS["pw_start"]
    x[5] = _SCREENING_DEFAULTS["pw_delta"]
    x[6] = _SCREENING_DEFAULTS["pw_min"]
    x[7] = _SCREENING_DEFAULTS["pw_max"]
    x[8] = _SCREENING_DEFAULTS["filter_cutoff_start"]
    x[9] = _SCREENING_DEFAULTS["filter_cutoff_end"]
    x[10] = _SCREENING_DEFAULTS["filter_sweep_frames"]
    x[11] = _SCREENING_DEFAULTS["filter_resonance"]
    x[12] = _SCREENING_DEFAULTS["wt_attack_frames"]

    return _eval_single(x, fixed, ref_fv, weights)


# ---------------------------------------------------------------------------
# New fast grid_search (default)
# ---------------------------------------------------------------------------

def grid_search(
    ref_wav_path: Path,
    ref_frequency_hz: float,
    work_dir: Path,
    budget: int = 5000,
    patience: int = 500,
    n_workers: Optional[int] = None,
    top_k: int = 3,
    chip_model: str = "6581",
    seed: int = 0,
    weights: Optional[dict] = None,
) -> List[OptimizerResult]:
    """Fast two-phase grid search: screen all combos, then refine top K.

    Phase 1 evaluates each discrete combo once with sensible mid-range
    continuous defaults (~42 evals).  Phase 2 runs full CMA-ES on the
    top *top_k* combos.

    Returns results sorted ascending by ``best_fitness``.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    combos = _build_combos()

    # --- Phase 1: fast screening (1 eval per combo) ---
    t0 = time.time()
    audio, sr = load_reference_audio(Path(ref_wav_path))
    ref_fv = extract(audio, sr)

    screen_results: List[tuple[float, int, dict]] = []
    for i, combo in enumerate(combos):
        fitness = _screen_combo(
            combo, ref_fv, ref_frequency_hz,
            weights=weights, chip_model=chip_model,
        )
        screen_results.append((fitness, i, combo))

    screen_results.sort(key=lambda t: t[0])
    screen_time = time.time() - t0

    print(
        f"[grid] Phase 1: screened {len(combos)} combos in {screen_time:.1f}s",
        flush=True,
    )
    print("[grid] Top 10 screening results:", flush=True)
    for rank, (fit, idx, combo) in enumerate(screen_results[:10]):
        sw = combo["wt_sustain_waveform"]
        aw = combo["wt_attack_waveform"]
        fm = combo["filter_mode"]
        tb = combo["wt_use_test_bit"]
        print(
            f"  {rank+1:2d}. fitness={fit:.4f}  sustain={sw} attack={aw} "
            f"filter={fm} test_bit={tb}",
            flush=True,
        )

    # --- Phase 2: refine top K combos with full CMA-ES ---
    top_combos = screen_results[:top_k]
    per_combo_budget = budget  # full budget per combo

    results: List[OptimizerResult] = []
    for rank, (screen_fit, idx, combo) in enumerate(top_combos):
        sw = combo["wt_sustain_waveform"]
        aw = combo["wt_attack_waveform"]
        fm = combo["filter_mode"]
        tb = combo["wt_use_test_bit"]

        combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
        combo_dir = work_dir / combo_label.replace("+", "_")

        fixed = dict(combo)
        fixed["chip_model"] = chip_model

        print(
            f"[grid] Phase 2 [{rank+1}/{top_k}] refining: sustain={sw} "
            f"attack={aw} filter={fm} test_bit={tb} "
            f"(screen={screen_fit:.4f}, budget={per_combo_budget})",
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
            log_interval=100,
        )
        res = opt.run()
        print(
            f"[grid] Phase 2 [{rank+1}/{top_k}] -> fitness={res.best_fitness:.4f} "
            f"evals={res.evaluations} time={res.wall_time_s:.1f}s",
            flush=True,
        )
        results.append(res)

    results.sort(key=lambda r: r.best_fitness)
    return results


# ---------------------------------------------------------------------------
# Old exhaustive grid_search (preserved for backwards compatibility)
# ---------------------------------------------------------------------------

def grid_search_exhaustive(
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
    """Run a short CMA-ES pass over each discrete combo (exhaustive).

    This is the original strategy (~42 combos x per_combo_budget evals).
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
