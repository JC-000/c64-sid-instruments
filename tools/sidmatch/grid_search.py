"""Grid search over discrete SID fields.

Three-phase approach (default, ``three_phase=True``):
  1. **Fast screening** -- one render per discrete combo with sensible
     mid-range continuous defaults.  ~132 evaluations total.
  2. **ADSR sweep** -- for each top-K combo, run a small optimizer
     (budget ~500) on only the 4 ADSR dimensions to find the best
     envelope.  Remaining continuous params use screening defaults.
  3. **Low-dim refinement** -- CMA-ES/TPE on the remaining 1-5
     continuous dims (PW + filter + wt_attack_frames) with the ADSR
     frozen at the Phase 2 optimum.

Legacy two-phase approach (``three_phase=False``):
  1. **Fast screening** -- same as above.
  2. **Top-K refinement** -- full CMA-ES on all continuous dims for the
     best *K* combos from phase 1 (with successive halving).

The old exhaustive strategy (mini CMA-ES per combo) is preserved as
:func:`grid_search_exhaustive`.
"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import numpy as np

from .optimize import (
    Optimizer,
    MultiNoteOptimizer,
    OptimizerResult,
    load_reference_audio,
    decode_params,
    _eval_single,
    N_DIMS,
    _fv_to_dict,
    _fv_from_dict,
    _ref_set_to_data,
    _IDX_ADSR,
    BOUNDS_LOW,
    BOUNDS_HIGH,
    active_params,
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

    # Multi-step wavetable patterns (durations fixed in the combo definition).
    # These use wavetable_steps which overrides the 2-step attack/sustain logic.
    _MULTISTEP_PATTERNS = [
        # noise attack into pulse sustain (pluck)
        ("noise_1_pulse", [("noise", 1), ("pulse", 0)]),
        # mixed attack into saw sustain
        ("pulse_saw_2_saw", [("pulse+saw", 2), ("saw", 0)]),
        # 3-step pluck: noise -> pulse+saw -> pulse
        ("noise_1_pulse_saw_2_pulse", [("noise", 1), ("pulse+saw", 2), ("pulse", 0)]),
        # soft triangle attack into saw sustain (brass)
        ("triangle_2_saw", [("triangle", 2), ("saw", 0)]),
        # evolving pad: triangle -> pulse -> saw
        ("triangle_3_pulse_5_saw", [("triangle", 3), ("pulse", 5), ("saw", 0)]),
        # 4-step: noise -> saw -> pulse+saw -> pulse
        ("noise_1_saw_2_pulse_saw_3_pulse",
         [("noise", 1), ("saw", 2), ("pulse+saw", 3), ("pulse", 0)]),
    ]

    for _label, steps in _MULTISTEP_PATTERNS:
        # Determine sustain waveform from the last step (duration 0)
        sustain_wf_name = steps[-1][0] if steps[-1][1] == 0 else steps[-1][0]
        for fm in fms:
            for tb in tbs:
                combo = {
                    "wt_sustain_waveform": sustain_wf_name,
                    "wt_attack_waveform": steps[0][0],
                    "filter_mode": fm,
                    "filter_voice1": (fm != "off"),
                    "wt_use_test_bit": tb,
                    "wavetable_steps": list(steps),
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


def _screen_worker(args: tuple) -> tuple:
    """Worker for parallel Phase 1 screening. Returns (fitness, index, combo)."""
    combo, ref_fv_dict, ref_frequency_hz, weights, chip_model, idx = args
    from .optimize import _fv_from_dict
    ref_fv = _fv_from_dict(ref_fv_dict)
    fitness = _screen_combo(combo, ref_fv, ref_frequency_hz, weights=weights, chip_model=chip_model)
    return (fitness, idx, combo)


def _screen_worker_multi_note(args: tuple) -> tuple:
    """Worker for parallel multi-note Phase 1 screening."""
    combo, ref_set_data, weights, alpha, chip_model, idx = args
    from .optimize import _fv_from_dict
    from .multi_note import ReferenceSet, NoteRef, multi_note_fitness

    # Reconstruct ReferenceSet
    notes = []
    for entry in ref_set_data:
        notes.append(NoteRef(
            note_name=entry["note_name"],
            freq_hz=entry["freq_hz"],
            ref_fv=_fv_from_dict(entry["ref_fv"]),
        ))
    ref_set = ReferenceSet.from_features(notes)

    fitness = _screen_combo_multi_note(combo, ref_set, weights=weights, alpha=alpha, chip_model=chip_model)
    return (fitness, idx, combo)


# ---------------------------------------------------------------------------
# Helper: extract continuous x0 vector from SidParams
# ---------------------------------------------------------------------------

def _x0_from_params(params) -> np.ndarray:
    """Extract the 13-dim continuous decision vector from a SidParams result.

    Used by successive halving to seed the next round's CMA-ES with the
    best solution found so far.
    """
    x = np.zeros(N_DIMS, dtype=np.float64)
    x[0] = getattr(params, "attack", 0)
    x[1] = getattr(params, "decay", 0)
    x[2] = getattr(params, "sustain", 0)
    x[3] = getattr(params, "release", 0)
    x[4] = getattr(params, "pw_start", getattr(params, "pulse_width", 2048))
    x[5] = getattr(params, "pw_delta", 0)
    x[6] = getattr(params, "pw_min", 0)
    x[7] = getattr(params, "pw_max", 4095)
    x[8] = getattr(params, "filter_cutoff_start", getattr(params, "filter_cutoff", 1024))
    x[9] = getattr(params, "filter_cutoff_end", 200)
    x[10] = getattr(params, "filter_sweep_frames", 0)
    x[11] = getattr(params, "filter_resonance", 8)
    x[12] = getattr(params, "wt_attack_frames", 2)
    return x


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
    parallel: bool = True,
    max_attack: int = 15,
    optimizer_backend: str = "cma",
    three_phase: bool = True,
    adsr_budget: int = 500,
) -> List[OptimizerResult]:
    """Grid search: screen all combos, then refine top K.

    When ``three_phase=True`` (default), uses a three-phase hierarchical
    decomposition:

    - Phase 1: screen each discrete combo once with mid-range defaults.
    - Phase 2: for each top-K combo, run a small optimizer (``adsr_budget``
      evals) over only the 4 ADSR dimensions.
    - Phase 3: CMA-ES/TPE on remaining continuous dims (PW + filter +
      wt_attack_frames) with ADSR frozen at Phase 2 optimum.

    When ``three_phase=False``, falls back to the legacy two-phase flow
    (screen + full CMA-ES with successive halving).

    Parameters
    ----------
    parallel : bool
        If True (default), Phase 2/3 runs the top-K refinements
        concurrently using a thread pool.  Each refinement's internal
        worker count is reduced so total CPU usage stays bounded.
    three_phase : bool
        Enable the three-phase hierarchical decomposition (default True).
    adsr_budget : int
        Evaluation budget for the Phase 2 ADSR sweep per combo
        (default 500).  Only used when ``three_phase=True``.

    Returns results sorted ascending by ``best_fitness``.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    combos = _build_combos()

    # --- Phase 1: fast screening (1 eval per combo) ---
    t0 = time.time()
    audio, sr = load_reference_audio(Path(ref_wav_path))
    ref_fv = extract(audio, sr)

    ref_fv_dict = _fv_to_dict(ref_fv)
    n_workers_phase1 = n_workers or (os.cpu_count() or 1)
    if n_workers_phase1 > 1 and len(combos) > 1:
        work_items = [
            (combo, ref_fv_dict, ref_frequency_hz, weights, chip_model, i)
            for i, combo in enumerate(combos)
        ]
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(n_workers_phase1, len(combos))) as pool:
            screen_results = pool.map(_screen_worker, work_items)
    else:
        screen_results = []
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

    # --- Select top K combos ---
    top_combos = screen_results[:top_k]

    # Build screening x0 from Phase 1 defaults to seed CMA-ES.
    screening_x0 = np.zeros(N_DIMS, dtype=np.float64)
    for i, key in enumerate([
        "attack", "decay", "sustain", "release",
        "pw_start", "pw_delta", "pw_min", "pw_max",
        "filter_cutoff_start", "filter_cutoff_end",
        "filter_sweep_frames", "filter_resonance", "wt_attack_frames",
    ]):
        screening_x0[i] = _SCREENING_DEFAULTS[key]

    # Divide workers across parallel combos so total CPU stays bounded.
    total_workers = n_workers or (os.cpu_count() or 1)
    actual_top_k = len(top_combos)

    if three_phase:
        # =====================================================================
        # THREE-PHASE HIERARCHICAL DECOMPOSITION
        # =====================================================================

        # --- Phase 2: ADSR sweep for each top-K combo ---
        t_adsr = time.time()
        print(
            f"[grid] Phase 2: ADSR sweep — {actual_top_k} combos, "
            f"{adsr_budget} evals each (ADSR-only optimization)",
            flush=True,
        )

        # Build freeze_indices for ADSR-only: freeze everything EXCEPT ADSR.
        # We determine non-ADSR active indices per combo.
        adsr_set = set(_IDX_ADSR)

        def _run_adsr_sweep(entry):
            screen_fit, _idx, combo = entry
            sw = combo["wt_sustain_waveform"]
            aw = combo["wt_attack_waveform"]
            fm = combo["filter_mode"]
            tb = combo["wt_use_test_bit"]

            combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
            combo_dir = work_dir / (combo_label.replace("+", "_") + "_adsr")

            fixed = dict(combo)
            fixed["chip_model"] = chip_model

            # Freeze all non-ADSR active params at screening defaults.
            act = active_params(fixed)
            freeze = {i: screening_x0[i] for i in act if i not in adsr_set}

            opt = Optimizer(
                ref_wav_path=ref_wav_path,
                ref_frequency_hz=ref_frequency_hz,
                fixed_kwargs=fixed,
                weights=weights,
                budget=adsr_budget,
                patience=adsr_budget,  # don't early-stop the short sweep
                n_workers=per_combo_workers_adsr,
                seed=seed,
                work_dir=combo_dir,
                log_interval=0,
                ref_fv=ref_fv,
                x0=screening_x0.copy(),
                max_attack=max_attack,
                warm_start=False,
                use_surrogate=False,
                optimizer_backend=optimizer_backend,
                freeze_indices=freeze,
            )
            res = opt.run()

            best_adsr = {
                0: _x0_from_params(res.best_params)[0],
                1: _x0_from_params(res.best_params)[1],
                2: _x0_from_params(res.best_params)[2],
                3: _x0_from_params(res.best_params)[3],
            }
            print(
                f"[grid]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                f"ADSR sweep fitness={res.best_fitness:.4f} "
                f"A={int(best_adsr[0])} D={int(best_adsr[1])} "
                f"S={int(best_adsr[2])} R={int(best_adsr[3])} "
                f"evals={res.evaluations}",
                flush=True,
            )
            return (screen_fit, combo, best_adsr, res)

        run_parallel_adsr = parallel and actual_top_k > 1
        if run_parallel_adsr:
            per_combo_workers_adsr = max(1, total_workers // actual_top_k)
        else:
            per_combo_workers_adsr = n_workers

        adsr_results = []
        if run_parallel_adsr:
            with ThreadPoolExecutor(max_workers=actual_top_k) as executor:
                futures = {
                    executor.submit(_run_adsr_sweep, entry): i
                    for i, entry in enumerate(top_combos)
                }
                for future in as_completed(futures):
                    try:
                        adsr_results.append(future.result())
                    except Exception:
                        logging.exception("[grid] Phase 2 ADSR sweep failed")
        else:
            for entry in top_combos:
                try:
                    adsr_results.append(_run_adsr_sweep(entry))
                except Exception:
                    logging.exception("[grid] Phase 2 ADSR sweep failed")

        adsr_time = time.time() - t_adsr
        print(
            f"[grid] Phase 2: ADSR sweep done in {adsr_time:.1f}s",
            flush=True,
        )

        # --- Phase 3: Low-dim CMA-ES on remaining params with ADSR frozen ---
        t_refine = time.time()
        print(
            f"[grid] Phase 3: low-dim refinement — {len(adsr_results)} combos, "
            f"budget={budget} each (ADSR frozen, PW+filter+wt active)",
            flush=True,
        )

        # Successive halving for Phase 3.
        n_rounds = max(1, math.ceil(math.log2(len(adsr_results))) + 1) if len(adsr_results) > 1 else 1
        total_budget_p3 = budget * len(adsr_results)
        budget_per_round = total_budget_p3 // n_rounds

        # Build survivors: (screen_fit, combo, x0, adsr_freeze, cumulative_result)
        survivors = []
        for screen_fit, combo, best_adsr, adsr_res in adsr_results:
            x0 = _x0_from_params(adsr_res.best_params)
            survivors.append((screen_fit, combo, x0, best_adsr, adsr_res))

        for rnd in range(n_rounds):
            n_alive = len(survivors)
            if n_alive == 0:
                break
            round_budget_each = max(10, budget_per_round // n_alive)

            run_parallel_p3 = parallel and n_alive > 1
            if run_parallel_p3:
                per_combo_workers = max(1, total_workers // n_alive)
            else:
                per_combo_workers = n_workers

            print(
                f"[grid] Phase 3 round {rnd+1}/{n_rounds}: {n_alive} combos, "
                f"{round_budget_each} evals each",
                flush=True,
            )

            def _run_round_combo_p3(entry):
                screen_fit, combo, x0, adsr_freeze, prev_result = entry
                sw = combo["wt_sustain_waveform"]
                aw = combo["wt_attack_waveform"]
                fm = combo["filter_mode"]
                tb = combo["wt_use_test_bit"]

                combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
                combo_dir = work_dir / combo_label.replace("+", "_")

                fixed = dict(combo)
                fixed["chip_model"] = chip_model

                opt = Optimizer(
                    ref_wav_path=ref_wav_path,
                    ref_frequency_hz=ref_frequency_hz,
                    fixed_kwargs=fixed,
                    weights=weights,
                    budget=round_budget_each,
                    patience=patience,
                    n_workers=per_combo_workers,
                    seed=seed + rnd,
                    work_dir=combo_dir,
                    log_interval=100,
                    ref_fv=ref_fv,
                    x0=x0,
                    max_attack=max_attack,
                    warm_start=True,
                    optimizer_backend=optimizer_backend,
                    freeze_indices=adsr_freeze,
                )
                res = opt.run()

                # Accumulate evaluations and wall time across rounds.
                total_evals = res.evaluations + (prev_result.evaluations if prev_result else 0)
                total_wall = res.wall_time_s + (prev_result.wall_time_s if prev_result else 0)

                # Keep the best result across rounds.
                if prev_result and prev_result.best_fitness < res.best_fitness:
                    combined = OptimizerResult(
                        best_params=prev_result.best_params,
                        best_fitness=prev_result.best_fitness,
                        history=prev_result.history + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )
                else:
                    combined = OptimizerResult(
                        best_params=res.best_params,
                        best_fitness=res.best_fitness,
                        history=(prev_result.history if prev_result else []) + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )

                best_x = _x0_from_params(res.best_params)

                print(
                    f"[grid]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                    f"round_fitness={res.best_fitness:.4f} "
                    f"cumul_fitness={combined.best_fitness:.4f} "
                    f"evals={total_evals}",
                    flush=True,
                )
                return (screen_fit, combo, best_x, adsr_freeze, combined)

            round_results = []
            if run_parallel_p3:
                with ThreadPoolExecutor(max_workers=n_alive) as executor:
                    futures = {
                        executor.submit(_run_round_combo_p3, entry): i
                        for i, entry in enumerate(survivors)
                    }
                    for future in as_completed(futures):
                        idx = futures[future]
                        try:
                            round_results.append(future.result())
                        except Exception:
                            logging.exception(
                                "[grid] Phase 3 round %d combo %d failed",
                                rnd + 1, idx + 1,
                            )
            else:
                for i, entry in enumerate(survivors):
                    try:
                        round_results.append(_run_round_combo_p3(entry))
                    except Exception:
                        logging.exception(
                            "[grid] Phase 3 round %d combo %d failed",
                            rnd + 1, i + 1,
                        )

            round_results.sort(key=lambda e: e[4].best_fitness)

            if rnd < n_rounds - 1 and len(round_results) > 1:
                n_keep = math.ceil(len(round_results) / 2)
                eliminated = round_results[n_keep:]
                survivors = round_results[:n_keep]
                print(
                    f"[grid] Phase 3 round {rnd+1}/{n_rounds}: keeping {n_keep}, "
                    f"eliminating {len(eliminated)} combos",
                    flush=True,
                )
                for _, combo, _, _, res in eliminated:
                    sw = combo["wt_sustain_waveform"]
                    aw = combo["wt_attack_waveform"]
                    fm = combo["filter_mode"]
                    print(
                        f"[grid]   eliminated: {sw}/{aw}/{fm} "
                        f"(fitness={res.best_fitness:.4f})",
                        flush=True,
                    )
            else:
                survivors = round_results

        refine_time = time.time() - t_refine
        print(
            f"[grid] Phase 3: refinement done in {refine_time:.1f}s",
            flush=True,
        )

        results: List[OptimizerResult] = [entry[4] for entry in survivors if entry[4] is not None]
        results.sort(key=lambda r: r.best_fitness)
        return results

    else:
        # =================================================================
        # LEGACY TWO-PHASE: successive halving with full CMA-ES
        # =================================================================

        # Successive halving budget allocation.
        total_budget = budget * actual_top_k
        n_rounds = max(1, math.ceil(math.log2(actual_top_k)) + 1) if actual_top_k > 1 else 1
        budget_per_round = total_budget // n_rounds

        print(
            f"[grid] Phase 2: successive halving — {actual_top_k} combos, "
            f"{n_rounds} rounds, total_budget={total_budget}, "
            f"budget_per_round={budget_per_round}",
            flush=True,
        )

        # Track survivors: list of (screen_fit, combo, x0, cumulative_result)
        survivors = [
            (screen_fit, combo, screening_x0.copy(), None)
            for screen_fit, _idx, combo in top_combos
        ]

        for rnd in range(n_rounds):
            n_alive = len(survivors)
            if n_alive == 0:
                break
            round_budget_each = max(10, budget_per_round // n_alive)

            run_parallel = parallel and n_alive > 1
            if run_parallel:
                per_combo_workers = max(1, total_workers // n_alive)
            else:
                per_combo_workers = n_workers

            print(
                f"[grid] Phase 2 round {rnd+1}/{n_rounds}: {n_alive} combos, "
                f"{round_budget_each} evals each",
                flush=True,
            )

            def _run_round_combo(entry):
                screen_fit, combo, x0, prev_result = entry
                sw = combo["wt_sustain_waveform"]
                aw = combo["wt_attack_waveform"]
                fm = combo["filter_mode"]
                tb = combo["wt_use_test_bit"]

                combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
                combo_dir = work_dir / combo_label.replace("+", "_")

                fixed = dict(combo)
                fixed["chip_model"] = chip_model

                opt = Optimizer(
                    ref_wav_path=ref_wav_path,
                    ref_frequency_hz=ref_frequency_hz,
                    fixed_kwargs=fixed,
                    weights=weights,
                    budget=round_budget_each,
                    patience=patience,
                    n_workers=per_combo_workers,
                    seed=seed + rnd,
                    work_dir=combo_dir,
                    log_interval=100,
                    ref_fv=ref_fv,
                    x0=x0,
                    max_attack=max_attack,
                    warm_start=True,
                    optimizer_backend=optimizer_backend,
                )
                res = opt.run()

                # Accumulate evaluations and wall time across rounds.
                total_evals = res.evaluations + (prev_result.evaluations if prev_result else 0)
                total_wall = res.wall_time_s + (prev_result.wall_time_s if prev_result else 0)

                # Keep the best result across rounds.
                if prev_result and prev_result.best_fitness < res.best_fitness:
                    combined = OptimizerResult(
                        best_params=prev_result.best_params,
                        best_fitness=prev_result.best_fitness,
                        history=prev_result.history + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )
                else:
                    combined = OptimizerResult(
                        best_params=res.best_params,
                        best_fitness=res.best_fitness,
                        history=(prev_result.history if prev_result else []) + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )

                # Extract best x from the result params for seeding next round.
                best_x = _x0_from_params(res.best_params)

                print(
                    f"[grid]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                    f"round_fitness={res.best_fitness:.4f} "
                    f"cumul_fitness={combined.best_fitness:.4f} "
                    f"evals={total_evals}",
                    flush=True,
                )
                return (screen_fit, combo, best_x, combined)

            # Run this round's combos (parallel or sequential).
            round_results = []
            if run_parallel:
                with ThreadPoolExecutor(max_workers=n_alive) as executor:
                    futures = {
                        executor.submit(_run_round_combo, entry): i
                        for i, entry in enumerate(survivors)
                    }
                    for future in as_completed(futures):
                        idx = futures[future]
                        try:
                            round_results.append(future.result())
                        except Exception:
                            logging.exception(
                                "[grid] Phase 2 round %d combo %d failed",
                                rnd + 1, idx + 1,
                            )
            else:
                for i, entry in enumerate(survivors):
                    try:
                        round_results.append(_run_round_combo(entry))
                    except Exception:
                        logging.exception(
                            "[grid] Phase 2 round %d combo %d failed",
                            rnd + 1, i + 1,
                        )

            # Sort by cumulative best fitness and halve.
            round_results.sort(key=lambda e: e[3].best_fitness)

            if rnd < n_rounds - 1 and len(round_results) > 1:
                n_keep = math.ceil(len(round_results) / 2)
                eliminated = round_results[n_keep:]
                survivors = round_results[:n_keep]
                print(
                    f"[grid] Phase 2 round {rnd+1}/{n_rounds}: keeping {n_keep}, "
                    f"eliminating {len(eliminated)} combos",
                    flush=True,
                )
                for _, combo, _, res in eliminated:
                    sw = combo["wt_sustain_waveform"]
                    aw = combo["wt_attack_waveform"]
                    fm = combo["filter_mode"]
                    print(
                        f"[grid]   eliminated: {sw}/{aw}/{fm} "
                        f"(fitness={res.best_fitness:.4f})",
                        flush=True,
                    )
            else:
                survivors = round_results

        # Collect final results from all survivors.
        results: List[OptimizerResult] = [entry[3] for entry in survivors if entry[3] is not None]
        results.sort(key=lambda r: r.best_fitness)
        return results


# ---------------------------------------------------------------------------
# Multi-note grid search
# ---------------------------------------------------------------------------


def _screen_combo_multi_note(
    combo: dict,
    ref_set,
    weights: Optional[dict] = None,
    alpha: float = 0.25,
    chip_model: Optional[str] = None,
) -> float:
    """Screen one combo against all reference notes with mid-range defaults."""
    from .multi_note import multi_note_fitness

    fixed = dict(combo)
    if chip_model:
        fixed["chip_model"] = chip_model

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

    params = decode_params(x, fixed)
    return multi_note_fitness(
        params, ref_set, weights=weights, alpha=alpha, chip_model=chip_model,
    )


def grid_search_multi_note(
    ref_set,
    work_dir: Path,
    budget: int = 5000,
    patience: int = 500,
    n_workers: Optional[int] = None,
    top_k: int = 3,
    chip_model: str = "6581",
    seed: int = 0,
    weights: Optional[dict] = None,
    alpha: float = 0.25,
    parallel: bool = True,
    max_attack: int = 15,
    optimizer_backend: str = "cma",
    three_phase: bool = True,
    adsr_budget: int = 500,
) -> List[OptimizerResult]:
    """Grid search using multi-note evaluation.

    When ``three_phase=True`` (default), uses the same three-phase
    hierarchical decomposition as :func:`grid_search`:

    - Phase 1: screen each discrete combo once.
    - Phase 2: ADSR-only optimization for each top-K combo.
    - Phase 3: low-dim CMA-ES on remaining params with ADSR frozen.

    Parameters
    ----------
    ref_set : ReferenceSet
        Pre-loaded reference notes with feature vectors.
    work_dir : Path
        Output directory for checkpoints.
    budget : int
        CMA-ES evaluation budget per combo in Phase 3.
    patience, n_workers, top_k, chip_model, seed, weights :
        Same semantics as :func:`grid_search`.
    alpha : float
        Aggregation parameter for multi-note fitness.
    parallel : bool
        If True (default), runs the top-K refinements
        concurrently using a thread pool.
    three_phase : bool
        Enable the three-phase hierarchical decomposition (default True).
    adsr_budget : int
        Evaluation budget for the Phase 2 ADSR sweep per combo.

    Returns
    -------
    list[OptimizerResult]
        Results sorted ascending by ``best_fitness``.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    combos = _build_combos()

    # --- Phase 1: fast screening ---
    t0 = time.time()

    ref_set_data = _ref_set_to_data(ref_set)
    n_workers_phase1 = n_workers or (os.cpu_count() or 1)
    if n_workers_phase1 > 1 and len(combos) > 1:
        work_items = [
            (combo, ref_set_data, weights, alpha, chip_model, i)
            for i, combo in enumerate(combos)
        ]
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(n_workers_phase1, len(combos))) as pool:
            screen_results = pool.map(_screen_worker_multi_note, work_items)
    else:
        screen_results = []
        for i, combo in enumerate(combos):
            fitness = _screen_combo_multi_note(
                combo, ref_set, weights=weights, alpha=alpha,
                chip_model=chip_model,
            )
            screen_results.append((fitness, i, combo))

    screen_results.sort(key=lambda t: t[0])
    screen_time = time.time() - t0

    print(
        f"[grid-mn] Phase 1: screened {len(combos)} combos "
        f"({len(ref_set)} notes each) in {screen_time:.1f}s",
        flush=True,
    )
    print("[grid-mn] Top 10 screening results:", flush=True)
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

    # --- Select top K combos ---
    top_combos = screen_results[:top_k]

    # Build screening x0 from Phase 1 defaults to seed CMA-ES.
    screening_x0 = np.zeros(N_DIMS, dtype=np.float64)
    for i, key in enumerate([
        "attack", "decay", "sustain", "release",
        "pw_start", "pw_delta", "pw_min", "pw_max",
        "filter_cutoff_start", "filter_cutoff_end",
        "filter_sweep_frames", "filter_resonance", "wt_attack_frames",
    ]):
        screening_x0[i] = _SCREENING_DEFAULTS[key]

    # Divide workers across parallel combos so total CPU stays bounded.
    total_workers = n_workers or (os.cpu_count() or 1)
    actual_top_k = len(top_combos)

    if three_phase:
        # =====================================================================
        # THREE-PHASE HIERARCHICAL DECOMPOSITION (multi-note)
        # =====================================================================

        # --- Phase 2: ADSR sweep for each top-K combo ---
        t_adsr = time.time()
        print(
            f"[grid-mn] Phase 2: ADSR sweep — {actual_top_k} combos, "
            f"{adsr_budget} evals each (ADSR-only optimization)",
            flush=True,
        )

        adsr_set = set(_IDX_ADSR)

        def _run_adsr_sweep_mn(entry):
            screen_fit, _idx, combo = entry
            sw = combo["wt_sustain_waveform"]
            aw = combo["wt_attack_waveform"]
            fm = combo["filter_mode"]
            tb = combo["wt_use_test_bit"]

            combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
            combo_dir = work_dir / (combo_label.replace("+", "_") + "_adsr")

            fixed = dict(combo)
            fixed["chip_model"] = chip_model

            # Freeze all non-ADSR active params at screening defaults.
            act = active_params(fixed)
            freeze = {i: screening_x0[i] for i in act if i not in adsr_set}

            opt = MultiNoteOptimizer(
                ref_set=ref_set,
                fixed_kwargs=fixed,
                weights=weights,
                alpha=alpha,
                budget=adsr_budget,
                patience=adsr_budget,
                n_workers=per_combo_workers_adsr,
                seed=seed,
                work_dir=combo_dir,
                log_interval=0,
                x0=screening_x0.copy(),
                max_attack=max_attack,
                warm_start=False,
                use_surrogate=False,
                optimizer_backend=optimizer_backend,
                freeze_indices=freeze,
            )
            res = opt.run()

            best_adsr = {
                0: _x0_from_params(res.best_params)[0],
                1: _x0_from_params(res.best_params)[1],
                2: _x0_from_params(res.best_params)[2],
                3: _x0_from_params(res.best_params)[3],
            }
            print(
                f"[grid-mn]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                f"ADSR sweep fitness={res.best_fitness:.4f} "
                f"A={int(best_adsr[0])} D={int(best_adsr[1])} "
                f"S={int(best_adsr[2])} R={int(best_adsr[3])} "
                f"evals={res.evaluations}",
                flush=True,
            )
            return (screen_fit, combo, best_adsr, res)

        run_parallel_adsr = parallel and actual_top_k > 1
        if run_parallel_adsr:
            per_combo_workers_adsr = max(1, total_workers // actual_top_k)
        else:
            per_combo_workers_adsr = n_workers

        adsr_results = []
        if run_parallel_adsr:
            with ThreadPoolExecutor(max_workers=actual_top_k) as executor:
                futures = {
                    executor.submit(_run_adsr_sweep_mn, entry): i
                    for i, entry in enumerate(top_combos)
                }
                for future in as_completed(futures):
                    try:
                        adsr_results.append(future.result())
                    except Exception:
                        logging.exception("[grid-mn] Phase 2 ADSR sweep failed")
        else:
            for entry in top_combos:
                try:
                    adsr_results.append(_run_adsr_sweep_mn(entry))
                except Exception:
                    logging.exception("[grid-mn] Phase 2 ADSR sweep failed")

        adsr_time = time.time() - t_adsr
        print(
            f"[grid-mn] Phase 2: ADSR sweep done in {adsr_time:.1f}s",
            flush=True,
        )

        # --- Phase 3: Low-dim CMA-ES on remaining params with ADSR frozen ---
        t_refine = time.time()
        print(
            f"[grid-mn] Phase 3: low-dim refinement — {len(adsr_results)} combos, "
            f"budget={budget} each (ADSR frozen, PW+filter+wt active)",
            flush=True,
        )

        n_rounds = max(1, math.ceil(math.log2(len(adsr_results))) + 1) if len(adsr_results) > 1 else 1
        total_budget_p3 = budget * len(adsr_results)
        budget_per_round = total_budget_p3 // n_rounds

        survivors = []
        for screen_fit, combo, best_adsr, adsr_res in adsr_results:
            x0 = _x0_from_params(adsr_res.best_params)
            survivors.append((screen_fit, combo, x0, best_adsr, adsr_res))

        for rnd in range(n_rounds):
            n_alive = len(survivors)
            if n_alive == 0:
                break
            round_budget_each = max(10, budget_per_round // n_alive)

            run_parallel_p3 = parallel and n_alive > 1
            if run_parallel_p3:
                per_combo_workers = max(1, total_workers // n_alive)
            else:
                per_combo_workers = n_workers

            print(
                f"[grid-mn] Phase 3 round {rnd+1}/{n_rounds}: {n_alive} combos, "
                f"{round_budget_each} evals each",
                flush=True,
            )

            def _run_round_combo_mn_p3(entry):
                screen_fit, combo, x0, adsr_freeze, prev_result = entry
                sw = combo["wt_sustain_waveform"]
                aw = combo["wt_attack_waveform"]
                fm = combo["filter_mode"]
                tb = combo["wt_use_test_bit"]

                combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
                combo_dir = work_dir / combo_label.replace("+", "_")

                fixed = dict(combo)
                fixed["chip_model"] = chip_model

                opt = MultiNoteOptimizer(
                    ref_set=ref_set,
                    fixed_kwargs=fixed,
                    weights=weights,
                    alpha=alpha,
                    budget=round_budget_each,
                    patience=patience,
                    n_workers=per_combo_workers,
                    seed=seed + rnd,
                    work_dir=combo_dir,
                    log_interval=100,
                    x0=x0,
                    max_attack=max_attack,
                    warm_start=True,
                    optimizer_backend=optimizer_backend,
                    freeze_indices=adsr_freeze,
                )
                res = opt.run()

                total_evals = res.evaluations + (prev_result.evaluations if prev_result else 0)
                total_wall = res.wall_time_s + (prev_result.wall_time_s if prev_result else 0)

                if prev_result and prev_result.best_fitness < res.best_fitness:
                    combined = OptimizerResult(
                        best_params=prev_result.best_params,
                        best_fitness=prev_result.best_fitness,
                        history=prev_result.history + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )
                else:
                    combined = OptimizerResult(
                        best_params=res.best_params,
                        best_fitness=res.best_fitness,
                        history=(prev_result.history if prev_result else []) + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )

                best_x = _x0_from_params(res.best_params)

                print(
                    f"[grid-mn]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                    f"round_fitness={res.best_fitness:.4f} "
                    f"cumul_fitness={combined.best_fitness:.4f} "
                    f"evals={total_evals}",
                    flush=True,
                )
                return (screen_fit, combo, best_x, adsr_freeze, combined)

            round_results = []
            if run_parallel_p3:
                with ThreadPoolExecutor(max_workers=n_alive) as executor:
                    futures = {
                        executor.submit(_run_round_combo_mn_p3, entry): i
                        for i, entry in enumerate(survivors)
                    }
                    for future in as_completed(futures):
                        idx = futures[future]
                        try:
                            round_results.append(future.result())
                        except Exception:
                            logging.exception(
                                "[grid-mn] Phase 3 round %d combo %d failed",
                                rnd + 1, idx + 1,
                            )
            else:
                for i, entry in enumerate(survivors):
                    try:
                        round_results.append(_run_round_combo_mn_p3(entry))
                    except Exception:
                        logging.exception(
                            "[grid-mn] Phase 3 round %d combo %d failed",
                            rnd + 1, i + 1,
                        )

            round_results.sort(key=lambda e: e[4].best_fitness)

            if rnd < n_rounds - 1 and len(round_results) > 1:
                n_keep = math.ceil(len(round_results) / 2)
                eliminated = round_results[n_keep:]
                survivors = round_results[:n_keep]
                print(
                    f"[grid-mn] Phase 3 round {rnd+1}/{n_rounds}: keeping {n_keep}, "
                    f"eliminating {len(eliminated)} combos",
                    flush=True,
                )
                for _, combo, _, _, res in eliminated:
                    sw = combo["wt_sustain_waveform"]
                    aw = combo["wt_attack_waveform"]
                    fm = combo["filter_mode"]
                    print(
                        f"[grid-mn]   eliminated: {sw}/{aw}/{fm} "
                        f"(fitness={res.best_fitness:.4f})",
                        flush=True,
                    )
            else:
                survivors = round_results

        refine_time = time.time() - t_refine
        print(
            f"[grid-mn] Phase 3: refinement done in {refine_time:.1f}s",
            flush=True,
        )

        results: List[OptimizerResult] = [entry[4] for entry in survivors if entry[4] is not None]
        results.sort(key=lambda r: r.best_fitness)
        return results

    else:
        # =================================================================
        # LEGACY TWO-PHASE: successive halving with full CMA-ES (multi-note)
        # =================================================================

        total_budget = budget * actual_top_k
        n_rounds = max(1, math.ceil(math.log2(actual_top_k)) + 1) if actual_top_k > 1 else 1
        budget_per_round = total_budget // n_rounds

        print(
            f"[grid-mn] Phase 2: successive halving — {actual_top_k} combos, "
            f"{n_rounds} rounds, total_budget={total_budget}, "
            f"budget_per_round={budget_per_round}",
            flush=True,
        )

        survivors = [
            (screen_fit, combo, screening_x0.copy(), None)
            for screen_fit, _idx, combo in top_combos
        ]

        for rnd in range(n_rounds):
            n_alive = len(survivors)
            if n_alive == 0:
                break
            round_budget_each = max(10, budget_per_round // n_alive)

            run_parallel = parallel and n_alive > 1
            if run_parallel:
                per_combo_workers = max(1, total_workers // n_alive)
            else:
                per_combo_workers = n_workers

            print(
                f"[grid-mn] Phase 2 round {rnd+1}/{n_rounds}: {n_alive} combos, "
                f"{round_budget_each} evals each",
                flush=True,
            )

            def _run_round_combo_mn(entry):
                screen_fit, combo, x0, prev_result = entry
                sw = combo["wt_sustain_waveform"]
                aw = combo["wt_attack_waveform"]
                fm = combo["filter_mode"]
                tb = combo["wt_use_test_bit"]

                combo_label = f"{sw}_{aw}_{fm}_tb{int(tb)}"
                combo_dir = work_dir / combo_label.replace("+", "_")

                fixed = dict(combo)
                fixed["chip_model"] = chip_model

                opt = MultiNoteOptimizer(
                    ref_set=ref_set,
                    fixed_kwargs=fixed,
                    weights=weights,
                    alpha=alpha,
                    budget=round_budget_each,
                    patience=patience,
                    n_workers=per_combo_workers,
                    seed=seed + rnd,
                    work_dir=combo_dir,
                    log_interval=100,
                    x0=x0,
                    max_attack=max_attack,
                    warm_start=True,
                    optimizer_backend=optimizer_backend,
                )
                res = opt.run()

                total_evals = res.evaluations + (prev_result.evaluations if prev_result else 0)
                total_wall = res.wall_time_s + (prev_result.wall_time_s if prev_result else 0)

                if prev_result and prev_result.best_fitness < res.best_fitness:
                    combined = OptimizerResult(
                        best_params=prev_result.best_params,
                        best_fitness=prev_result.best_fitness,
                        history=prev_result.history + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )
                else:
                    combined = OptimizerResult(
                        best_params=res.best_params,
                        best_fitness=res.best_fitness,
                        history=(prev_result.history if prev_result else []) + res.history,
                        evaluations=total_evals,
                        wall_time_s=total_wall,
                        converged=res.converged,
                    )

                best_x = _x0_from_params(res.best_params)

                print(
                    f"[grid-mn]   {sw}/{aw}/{fm}/tb{int(tb)}: "
                    f"round_fitness={res.best_fitness:.4f} "
                    f"cumul_fitness={combined.best_fitness:.4f} "
                    f"evals={total_evals}",
                    flush=True,
                )
                return (screen_fit, combo, best_x, combined)

            round_results = []
            if run_parallel:
                with ThreadPoolExecutor(max_workers=n_alive) as executor:
                    futures = {
                        executor.submit(_run_round_combo_mn, entry): i
                        for i, entry in enumerate(survivors)
                    }
                    for future in as_completed(futures):
                        idx = futures[future]
                        try:
                            round_results.append(future.result())
                        except Exception:
                            logging.exception(
                                "[grid-mn] Phase 2 round %d combo %d failed",
                                rnd + 1, idx + 1,
                            )
            else:
                for i, entry in enumerate(survivors):
                    try:
                        round_results.append(_run_round_combo_mn(entry))
                    except Exception:
                        logging.exception(
                            "[grid-mn] Phase 2 round %d combo %d failed",
                            rnd + 1, i + 1,
                        )

            round_results.sort(key=lambda e: e[3].best_fitness)

            if rnd < n_rounds - 1 and len(round_results) > 1:
                n_keep = math.ceil(len(round_results) / 2)
                eliminated = round_results[n_keep:]
                survivors = round_results[:n_keep]
                print(
                    f"[grid-mn] Phase 2 round {rnd+1}/{n_rounds}: keeping {n_keep}, "
                    f"eliminating {len(eliminated)} combos",
                    flush=True,
                )
                for _, combo, _, res in eliminated:
                    sw = combo["wt_sustain_waveform"]
                    aw = combo["wt_attack_waveform"]
                    fm = combo["filter_mode"]
                    print(
                        f"[grid-mn]   eliminated: {sw}/{aw}/{fm} "
                        f"(fitness={res.best_fitness:.4f})",
                        flush=True,
                    )
            else:
                survivors = round_results

        results: List[OptimizerResult] = [entry[3] for entry in survivors if entry[3] is not None]
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
