"""Command-line interface for sidmatch.

By default, ``match`` runs the full optimization for **both** 6581 and 8580
chip models and writes results to ``<work-dir>/6581/`` and
``<work-dir>/8580/`` respectively.  Use ``--chip-model`` to restrict to a
single chip.

Usage::

    # Both chips (default):
    python3 -m sidmatch.cli match \\
        --sample tools/samples/grand-piano/salamander-piano-C4-v16-ff.wav \\
        --frequency 261.63 \\
        --name grand-piano \\
        --budget 5000 \\
        --patience 500 \\
        --workers 8 \\
        --work-dir work/grand-piano

    # Single chip:
    python3 -m sidmatch.cli match \\
        --chip-model 6581 \\
        --sample ... --frequency 261.63 --name grand-piano \\
        --work-dir work/grand-piano-6581
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .optimize import (
    Optimizer,
    MultiNoteOptimizer,
    OptimizerResult,
    sid_params_to_dict,
    sid_params_from_dict,
)
from .grid_search import grid_search, grid_search_multi_note
from .multi_note import ReferenceSet
from .render import render_pyresid, SidParams
from .features import CANONICAL_SR
from .encoders.raw_asm import encode_raw_asm


def _save_fitness_plot(history, out_path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"[cli] matplotlib unavailable, skipping plot: {e}", flush=True)
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(history, lw=1.5)
    ax.set_xlabel("generation")
    ax.set_ylabel("best fitness so far")
    ax.set_title("CMA-ES fitness history")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


def _write_report(
    work_dir: Path,
    name: str,
    sample_path: Path,
    frequency: float,
    grid_results_summary: list,
    best_combo: dict,
    final_result: OptimizerResult,
) -> None:
    lines = [
        f"# sidmatch report: {name}",
        "",
        f"- Reference: `{sample_path}`",
        f"- Target frequency: {frequency:.2f} Hz",
        f"- Final best fitness: **{final_result.best_fitness:.4f}**",
        f"- Evaluations: {final_result.evaluations}",
        f"- Wall time: {final_result.wall_time_s:.1f}s",
        f"- Converged (patience hit): {final_result.converged}",
        "",
        "## Selected discrete combo",
        "",
        "```json",
        json.dumps(best_combo, indent=2),
        "```",
        "",
        "## Best parameters",
        "",
        "```json",
        json.dumps(sid_params_to_dict(final_result.best_params), indent=2),
        "```",
        "",
        "## Grid search results",
        "",
        "| sustain_wf | attack_wf | filter | test_bit | fitness | evals |",
        "|---|---|---|---|---:|---:|",
    ]
    for row in grid_results_summary:
        lines.append(
            f"| {row['waveform']} | {row.get('attack_wf', '')} | {row['filter_mode']} "
            f"| {row.get('test_bit', '')} "
            f"| {row['fitness']:.4f} | {row['evaluations']} |"
        )
    (work_dir / "report.md").write_text("\n".join(lines))


CHIP_MODELS = ["6581", "8580"]


def _run_match_single_chip(
    sample_path: Path,
    work_dir: Path,
    args: argparse.Namespace,
    chip_model: str,
) -> OptimizerResult:
    """Run the full match pipeline for a single chip model.

    Uses fast two-phase grid search: screen all discrete combos with a
    single evaluation each, then refine the top K with full CMA-ES.
    Results are written into *work_dir* (which should already be
    chip-specific, e.g. ``<root>/6581/``).
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    top_k = getattr(args, "top_k", 3)

    print(
        f"[cli] [{chip_model}] grid_search: fast screen + top-{top_k} "
        f"refinement, budget={args.budget} workers={args.workers}",
        flush=True,
    )
    grid_results = grid_search(
        ref_wav_path=sample_path,
        ref_frequency_hz=args.frequency,
        work_dir=work_dir / "grid",
        budget=args.budget,
        patience=args.patience,
        n_workers=args.workers,
        top_k=top_k,
        chip_model=chip_model,
        seed=args.seed,
    )

    result = grid_results[0]
    best_combo = {
        "wt_sustain_waveform": result.best_params.effective_sustain_waveform(),
        "wt_attack_waveform": result.best_params.wt_attack_waveform or "same_as_sustain",
        "filter_mode": result.best_params.filter_mode,
        "wt_use_test_bit": result.best_params.wt_use_test_bit,
    }
    print(
        f"[cli] [{chip_model}] best combo: sustain_wf={best_combo['wt_sustain_waveform']} "
        f"attack_wf={best_combo['wt_attack_waveform']} "
        f"filter={best_combo['filter_mode']} "
        f"test_bit={best_combo['wt_use_test_bit']} "
        f"fitness={result.best_fitness:.4f}",
        flush=True,
    )

    # Write outputs.
    (work_dir / "best_params.json").write_text(
        json.dumps(sid_params_to_dict(result.best_params), indent=2)
    )
    # Render best patch.
    audio = render_pyresid(result.best_params, sample_rate=CANONICAL_SR,
                           chip_model=chip_model)
    sf.write(str(work_dir / "best_render.wav"), audio, CANONICAL_SR)
    # Plot.
    _save_fitness_plot(result.history, work_dir / "fitness_history.png")

    # Report.
    grid_summary = [
        {
            "waveform": r.best_params.effective_sustain_waveform(),
            "attack_wf": r.best_params.effective_attack_waveform(),
            "filter_mode": r.best_params.filter_mode,
            "test_bit": r.best_params.wt_use_test_bit,
            "fitness": r.best_fitness,
            "evaluations": r.evaluations,
        }
        for r in grid_results
    ]
    _write_report(
        work_dir=work_dir,
        name=args.name,
        sample_path=sample_path,
        frequency=args.frequency,
        grid_results_summary=grid_summary,
        best_combo=best_combo,
        final_result=result,
    )

    print(f"[cli] [{chip_model}] wrote outputs to {work_dir}/", flush=True)
    return result


def _run_match_multi_note_chip(
    ref_set: ReferenceSet,
    work_dir: Path,
    args: argparse.Namespace,
    chip_model: str,
) -> OptimizerResult:
    """Run the multi-note match pipeline for a single chip model."""
    work_dir.mkdir(parents=True, exist_ok=True)

    top_k = getattr(args, "top_k", 3)

    print(
        f"[cli] [{chip_model}] multi-note grid_search: {len(ref_set)} notes, "
        f"fast screen + top-{top_k} refinement, budget={args.budget} "
        f"workers={args.workers}",
        flush=True,
    )
    grid_results = grid_search_multi_note(
        ref_set=ref_set,
        work_dir=work_dir / "grid",
        budget=args.budget,
        patience=args.patience,
        n_workers=args.workers,
        top_k=top_k,
        chip_model=chip_model,
        seed=args.seed,
    )

    result = grid_results[0]
    best_combo = {
        "wt_sustain_waveform": result.best_params.effective_sustain_waveform(),
        "wt_attack_waveform": result.best_params.wt_attack_waveform or "same_as_sustain",
        "filter_mode": result.best_params.filter_mode,
        "wt_use_test_bit": result.best_params.wt_use_test_bit,
    }
    print(
        f"[cli] [{chip_model}] best combo: sustain_wf={best_combo['wt_sustain_waveform']} "
        f"attack_wf={best_combo['wt_attack_waveform']} "
        f"filter={best_combo['filter_mode']} "
        f"test_bit={best_combo['wt_use_test_bit']} "
        f"fitness={result.best_fitness:.4f}",
        flush=True,
    )

    # Write outputs.
    params_dict = sid_params_to_dict(result.best_params)
    params_dict["reference_notes"] = [
        {"note": n.note_name, "freq_hz": n.freq_hz}
        for n in ref_set.notes
    ]
    (work_dir / "best_params.json").write_text(
        json.dumps(params_dict, indent=2)
    )
    # Render best patch at the first note's frequency.
    audio = render_pyresid(result.best_params, sample_rate=CANONICAL_SR,
                           chip_model=chip_model)
    sf.write(str(work_dir / "best_render.wav"), audio, CANONICAL_SR)
    _save_fitness_plot(result.history, work_dir / "fitness_history.png")

    print(f"[cli] [{chip_model}] wrote outputs to {work_dir}/", flush=True)
    return result


def cmd_match(args: argparse.Namespace) -> int:
    reference_set_path = getattr(args, "reference_set", None)

    # Validate arguments: need either --reference-set or --sample + --frequency.
    if not reference_set_path and (not args.sample or args.frequency is None):
        print(
            "error: provide either --reference-set or both --sample and --frequency",
            file=sys.stderr,
        )
        return 2

    if reference_set_path:
        # Multi-note mode.
        ref_set_dir = Path(reference_set_path).resolve()
        if not ref_set_dir.is_dir():
            print(f"reference-set directory not found: {ref_set_dir}", file=sys.stderr)
            return 2
        ref_set = ReferenceSet.load(ref_set_dir)
        print(
            f"[cli] Loaded reference set: {len(ref_set)} notes "
            f"({', '.join(ref_set.note_names())})",
            flush=True,
        )
    else:
        ref_set = None
        sample_path = Path(args.sample).resolve()
        if not sample_path.exists():
            print(f"sample not found: {sample_path}", file=sys.stderr)
            return 2

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Determine which chip models to run.
    if args.chip_model:
        chips = [args.chip_model]
    elif args.all_chips:
        chips = list(CHIP_MODELS)
    else:
        chips = list(CHIP_MODELS)

    parallel_chips = getattr(args, "parallel_chips", False) and len(chips) > 1

    results: dict[str, OptimizerResult] = {}

    if parallel_chips:
        # Halve workers per chip so both don't fight over all cores.
        original_workers = args.workers
        cpu_count = args.workers or __import__("os").cpu_count() or 1
        args_per_chip: dict[str, argparse.Namespace] = {}
        for chip in chips:
            ns = argparse.Namespace(**vars(args))
            ns.workers = max(1, cpu_count // 2)
            args_per_chip[chip] = ns

        print(
            f"[cli] Running {len(chips)} chip models in parallel "
            f"({cpu_count // 2} workers each)",
            flush=True,
        )

        # Use threads for outer parallelism; inner optimizer spawns its
        # own multiprocessing.Pool per chip which is safe from threads.
        with ThreadPoolExecutor(max_workers=len(chips)) as executor:
            futures = {}
            for chip in chips:
                chip_work_dir = work_dir / chip
                chip_args = args_per_chip[chip]
                if ref_set is not None:
                    fut = executor.submit(
                        _run_match_multi_note_chip,
                        ref_set, chip_work_dir, chip_args, chip,
                    )
                else:
                    fut = executor.submit(
                        _run_match_single_chip,
                        sample_path, chip_work_dir, chip_args, chip,
                    )
                futures[fut] = chip

            for fut in as_completed(futures):
                chip = futures[fut]
                try:
                    results[chip] = fut.result()
                except Exception as exc:
                    print(
                        f"[cli] [{chip}] FAILED: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

        # Restore original workers value on args (defensive).
        args.workers = original_workers
    else:
        for chip in chips:
            if len(chips) > 1:
                chip_work_dir = work_dir / chip
            else:
                chip_work_dir = work_dir

            if ref_set is not None:
                result = _run_match_multi_note_chip(ref_set, chip_work_dir, args, chip)
            else:
                result = _run_match_single_chip(sample_path, chip_work_dir, args, chip)
            results[chip] = result

    # Print summary comparing chips.
    if len(results) > 1:
        print("\n[cli] === Chip comparison summary ===", flush=True)
        print(f"{'Chip':<8} {'Fitness':>10} {'Evals':>8} {'Time (s)':>10} {'Converged'}", flush=True)
        print("-" * 50, flush=True)
        for chip, res in results.items():
            print(
                f"{chip:<8} {res.best_fitness:>10.4f} {res.evaluations:>8} "
                f"{res.wall_time_s:>10.1f} {res.converged}",
                flush=True,
            )
        best_chip = min(results, key=lambda c: results[c].best_fitness)
        print(f"\n[cli] Best chip: {best_chip} (fitness={results[best_chip].best_fitness:.4f})", flush=True)

    return 0


_README_TEMPLATE = """\
# {title} (SID Instrument)

{description}

## Source and Target

| | |
|---|---|
| **Source instrument** | {source_instrument} |
| **Target SID model** | {chip_model} |

## Tags

{tags}

## Winning Parameters

| Parameter | Value |
|---|---|
{param_rows}

## Fitness

- **Fitness score:** {fitness_score:.4f}
- **Version:** {version}

## Files

| File | Description |
|---|---|
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
| `README.md` | This file |
"""


def _instrument_readme(
    name: str,
    params_dict: dict,
    fitness_score: float,
    version: int,
    chip_model: str | None = None,
    source_instrument: str | None = None,
) -> str:
    title = name.replace("-", " ").title()
    rows = []
    for k in ("waveform", "attack", "decay", "sustain", "release",
              "pulse_width", "pw_start", "pw_delta", "pw_mode",
              "filter_cutoff", "filter_cutoff_start", "filter_cutoff_end",
              "filter_sweep_frames", "filter_resonance",
              "filter_mode", "filter_voice1",
              "wt_attack_waveform", "wt_sustain_waveform",
              "wt_attack_frames", "wt_use_test_bit",
              "volume"):
        if k in params_dict:
            rows.append(f"| {k} | {params_dict[k]} |")
    return _README_TEMPLATE.format(
        title=title,
        description=f"A SID chip instrument patch: {name}.",
        tags=f"`{name}`",
        param_rows="\n".join(rows),
        fitness_score=fitness_score,
        version=version,
        chip_model=chip_model or params_dict.get("chip_model", "unspecified"),
        source_instrument=source_instrument or params_dict.get("source_instrument", "unspecified"),
    )


def _export_single_chip(
    work_dir: Path,
    inst_dir: Path,
    chip_model: str,
    name: str,
    source_instrument: Optional[str],
) -> tuple[dict, float, int]:
    """Export one chip variant from *work_dir* into *inst_dir*.

    Returns ``(params_dict, fitness_score, version)``.
    """
    best_params_path = work_dir / "best_params.json"
    params_dict = json.loads(best_params_path.read_text())
    # Derive fitness from the optimizer checkpoint.
    fitness_score = params_dict.get(
        "fitness_score",
        _read_fitness_from_checkpoint(work_dir),
    )

    inst_dir.mkdir(parents=True, exist_ok=True)

    # --- Versioning ---
    existing_params_path = inst_dir / "params.json"
    version = 1
    if existing_params_path.exists():
        try:
            existing = json.loads(existing_params_path.read_text())
            version = existing.get("version", 0) + 1
            old_fitness = existing.get("fitness_score")
            if old_fitness is not None and fitness_score > old_fitness:
                print(
                    f"[cli] [{chip_model}] WARNING: new fitness "
                    f"{fitness_score:.4f} is worse than existing "
                    f"{old_fitness:.4f} (version {version - 1}). "
                    f"Saving anyway as version {version}.",
                    flush=True,
                )
        except (json.JSONDecodeError, KeyError):
            pass

    # --- params.json ---
    params_dict["fitness_score"] = round(fitness_score, 4)
    params_dict["version"] = version
    params_dict["chip_model"] = chip_model
    if source_instrument:
        params_dict["source_instrument"] = source_instrument
    (inst_dir / "params.json").write_text(
        json.dumps(params_dict, indent=2) + "\n"
    )

    # --- raw.asm ---
    label = name.replace("-", "_")
    sid_params = sid_params_from_dict(
        {k: v for k, v in params_dict.items()
         if k not in ("fitness_score", "version")}
    )
    asm_text = encode_raw_asm(
        sid_params, label, fitness_score=fitness_score, version=version,
        chip_model=chip_model, source_instrument=source_instrument,
    )
    (inst_dir / "raw.asm").write_text(asm_text)

    # --- GoatTracker ---
    try:
        from .encoders.goattracker import encode_goattracker
        gt_data = encode_goattracker(sid_params, name)
        (inst_dir / "goattracker.ins").write_bytes(gt_data)
    except Exception as e:
        print(f"[cli] [{chip_model}] goattracker encode skipped: {e}", flush=True)

    # --- Copy render if present ---
    render_wav = work_dir / "best_render.wav"
    if render_wav.exists():
        import shutil
        shutil.copy2(render_wav, inst_dir / "sid_render.wav")

    print(
        f"[cli] exported {name} [{chip_model}] v{version} "
        f"(fitness={fitness_score:.4f}) to {inst_dir}/",
        flush=True,
    )
    return params_dict, fitness_score, version


def _read_fitness_from_checkpoint(work_dir: Path) -> float:
    """Try to read the best fitness from the optimizer checkpoint."""
    cp_path = work_dir / "final" / "optim_state.json"
    if cp_path.exists():
        try:
            state = json.loads(cp_path.read_text())
            return float(state["best_fitness"])
        except (json.JSONDecodeError, KeyError):
            pass
    return 0.0


_COMBINED_README_TEMPLATE = """\
# {title} (SID Instrument)

{description}

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | {status_6581} | {status_8580} |
| **Fitness** | {fitness_6581} | {fitness_8580} |
| **Version** | {version_6581} | {version_8580} |

{variant_details}

## Tags

`{name}`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
"""


def _write_combined_readme(
    inst_dir: Path,
    name: str,
    chip_data: dict[str, tuple[dict, float, int] | None],
    source_instrument: Optional[str] = None,
) -> None:
    """Write a combined README.md covering both chip variants."""
    title = name.replace("-", " ").title()

    def _chip_status(chip: str) -> tuple[str, str, str]:
        data = chip_data.get(chip)
        if data is None:
            return "not exported", "---", "---"
        _, fitness, version = data
        return "available", f"{fitness:.4f}", str(version)

    s6, f6, v6 = _chip_status("6581")
    s8, f8, v8 = _chip_status("8580")

    details_parts = []
    for chip in CHIP_MODELS:
        data = chip_data.get(chip)
        if data is None:
            continue
        params_dict, fitness, version = data
        rows = []
        for k in ("waveform", "attack", "decay", "sustain", "release",
                  "pulse_width", "pw_start", "pw_delta", "pw_mode",
                  "filter_cutoff", "filter_cutoff_start", "filter_cutoff_end",
                  "filter_sweep_frames", "filter_resonance",
                  "filter_mode", "filter_voice1",
                  "wt_attack_waveform", "wt_sustain_waveform",
                  "wt_attack_frames", "wt_use_test_bit",
                  "volume"):
            if k in params_dict:
                rows.append(f"| {k} | {params_dict[k]} |")
        details_parts.append(
            f"### {chip} Parameters\n\n"
            f"| Parameter | Value |\n|---|---|\n"
            + "\n".join(rows)
        )

    readme_text = _COMBINED_README_TEMPLATE.format(
        title=title,
        description=f"A SID chip instrument patch: {name}.",
        name=name,
        status_6581=s6,
        status_8580=s8,
        fitness_6581=f6,
        fitness_8580=f8,
        version_6581=v6,
        version_8580=v8,
        variant_details="\n\n".join(details_parts),
    )
    (inst_dir / "README.md").write_text(readme_text)


def cmd_export(args: argparse.Namespace) -> int:
    """Export a work-dir result to instruments/<name>/."""
    work_dir = Path(args.work_dir).resolve()

    # Resolve project root (two levels up from tools/sidmatch/).
    project_root = Path(__file__).resolve().parent.parent.parent
    inst_base = project_root / "instruments" / args.name

    # Detect which chip results exist in the work dir.
    available_chips: list[str] = []
    for chip in CHIP_MODELS:
        if (work_dir / chip / "best_params.json").exists():
            available_chips.append(chip)

    # Fall back to legacy flat layout (single chip).
    if not available_chips and (work_dir / "best_params.json").exists():
        chip = args.chip_model or "6581"
        available_chips = [chip]

    if not available_chips:
        print(
            f"No best_params.json found in {work_dir} "
            f"(checked subdirs 6581/, 8580/ and root)",
            file=sys.stderr,
        )
        return 2

    # If user explicitly requested a single chip, filter.
    if args.chip_model:
        if args.chip_model not in available_chips:
            print(
                f"Chip {args.chip_model} results not found in {work_dir}",
                file=sys.stderr,
            )
            return 2
        available_chips = [args.chip_model]

    chip_data: dict[str, tuple[dict, float, int] | None] = {}
    for chip in available_chips:
        # Determine source work dir for this chip.
        chip_work = work_dir / chip if (work_dir / chip / "best_params.json").exists() else work_dir
        chip_inst = inst_base / chip
        params_dict, fitness, version = _export_single_chip(
            work_dir=chip_work,
            inst_dir=chip_inst,
            chip_model=chip,
            name=args.name,
            source_instrument=args.source_instrument,
        )
        chip_data[chip] = (params_dict, fitness, version)

    # Mark missing chips as None for the README.
    for chip in CHIP_MODELS:
        if chip not in chip_data:
            chip_data[chip] = None

    # --- Combined README.md at instruments/<name>/ level ---
    inst_base.mkdir(parents=True, exist_ok=True)
    _write_combined_readme(
        inst_base, args.name, chip_data,
        source_instrument=args.source_instrument,
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sidmatch")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("match", help="search SID patch space for a sample")
    m.add_argument("--sample", required=False, default=None, help="reference WAV path (single-note mode)")
    m.add_argument("--frequency", type=float, required=False, default=None, help="pitch in Hz (single-note mode)")
    m.add_argument("--reference-set", default=None,
                   help="path to directory with note_map.json + WAVs (multi-note mode)")
    m.add_argument("--name", required=True, help="instrument name")
    m.add_argument("--budget", type=int, default=5000)
    m.add_argument("--patience", type=int, default=500)
    m.add_argument("--workers", type=int, default=None)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--top-k", type=int, default=3,
                   help="number of top discrete combos to refine with CMA-ES (default: 3)")
    m.add_argument("--work-dir", required=True)
    m.add_argument("--chip-model", default=None, choices=["6581", "8580"],
                   help="run only this chip model (overrides --all-chips)")
    m.add_argument("--all-chips", default=True, action=argparse.BooleanOptionalAction,
                   help="run both 6581 and 8580 variants (default: True)")
    m.add_argument("--parallel-chips", default=False, action=argparse.BooleanOptionalAction,
                   help="run chip models in parallel when using both (default: False)")
    m.add_argument("--source-instrument", default=None,
                   help="free-text description of the reference recording")
    m.set_defaults(func=cmd_match)

    e = sub.add_parser("export", help="export work-dir result to instruments/")
    e.add_argument("--work-dir", required=True, help="sidmatch work directory")
    e.add_argument("--name", required=True, help="instrument name (kebab-case)")
    e.add_argument("--fitness-score", type=float, default=None,
                   help="final fitness score (auto-detected from work-dir if omitted)")
    e.add_argument("--chip-model", default=None, choices=["6581", "8580"],
                   help="export only this chip model (default: export all available)")
    e.add_argument("--source-instrument", default=None,
                   help="free-text description of the reference recording")
    e.set_defaults(func=cmd_export)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
