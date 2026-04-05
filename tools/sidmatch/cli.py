"""Command-line interface for sidmatch.

Usage::

    python3 -m sidmatch.cli match \\
        --sample tools/samples/grand-piano/salamander-piano-C4-v16-ff.wav \\
        --frequency 261.63 \\
        --name grand-piano \\
        --budget 5000 \\
        --patience 500 \\
        --workers 8 \\
        --work-dir work/grand-piano
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .optimize import (
    Optimizer,
    OptimizerResult,
    sid_params_to_dict,
    sid_params_from_dict,
)
from .grid_search import grid_search
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
        "| waveform | filter | fitness | evals |",
        "|---|---|---:|---:|",
    ]
    for row in grid_results_summary:
        lines.append(
            f"| {row['waveform']} | {row['filter_mode']} "
            f"| {row['fitness']:.4f} | {row['evaluations']} |"
        )
    (work_dir / "report.md").write_text("\n".join(lines))


def cmd_match(args: argparse.Namespace) -> int:
    sample_path = Path(args.sample).resolve()
    if not sample_path.exists():
        print(f"sample not found: {sample_path}", file=sys.stderr)
        return 2

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    per_combo = max(50, args.budget // 8)

    print(
        f"[cli] grid_search per_combo_budget={per_combo} "
        f"workers={args.workers}",
        flush=True,
    )
    grid_results = grid_search(
        ref_wav_path=sample_path,
        ref_frequency_hz=args.frequency,
        work_dir=work_dir / "grid",
        per_combo_budget=per_combo,
        n_workers=args.workers,
        patience=max(50, per_combo // 2),
        seed=args.seed,
    )

    best = grid_results[0]
    best_combo = {
        "waveform": best.best_params.waveform,
        "filter_mode": best.best_params.filter_mode,
    }
    print(
        f"[cli] best grid combo: wf={best_combo['waveform']} "
        f"filter={best_combo['filter_mode']} fitness={best.best_fitness:.4f}",
        flush=True,
    )

    # Full run on best combo.
    fixed = {
        "waveform": best_combo["waveform"],
        "filter_mode": best_combo["filter_mode"],
        "filter_voice1": best_combo["filter_mode"] != "off",
    }
    if args.chip_model:
        fixed["chip_model"] = args.chip_model
    print(
        f"[cli] full optimization budget={args.budget} patience={args.patience}",
        flush=True,
    )
    opt = Optimizer(
        ref_wav_path=sample_path,
        ref_frequency_hz=args.frequency,
        fixed_kwargs=fixed,
        budget=args.budget,
        patience=args.patience,
        n_workers=args.workers,
        seed=args.seed,
        work_dir=work_dir / "final",
        log_interval=100,
    )
    result = opt.run()
    print(
        f"[cli] final best fitness={result.best_fitness:.4f} "
        f"evals={result.evaluations} time={result.wall_time_s:.1f}s "
        f"converged={result.converged}",
        flush=True,
    )

    # Write outputs.
    (work_dir / "best_params.json").write_text(
        json.dumps(sid_params_to_dict(result.best_params), indent=2)
    )
    # Render best patch.
    audio = render_pyresid(result.best_params, sample_rate=CANONICAL_SR,
                           chip_model=args.chip_model)
    sf.write(str(work_dir / "best_render.wav"), audio, CANONICAL_SR)
    # Plot.
    _save_fitness_plot(result.history, work_dir / "fitness_history.png")

    # Report.
    grid_summary = [
        {
            "waveform": r.best_params.waveform,
            "filter_mode": r.best_params.filter_mode,
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

    print(f"[cli] wrote outputs to {work_dir}/", flush=True)
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
              "pulse_width", "filter_cutoff", "filter_resonance",
              "filter_mode", "filter_voice1", "volume"):
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


def cmd_export(args: argparse.Namespace) -> int:
    """Export a work-dir result to instruments/<name>/."""
    work_dir = Path(args.work_dir).resolve()
    best_params_path = work_dir / "best_params.json"
    if not best_params_path.exists():
        print(f"best_params.json not found in {work_dir}", file=sys.stderr)
        return 2

    params_dict = json.loads(best_params_path.read_text())
    fitness_score = args.fitness_score

    # Resolve project root (two levels up from tools/sidmatch/).
    project_root = Path(__file__).resolve().parent.parent.parent
    inst_dir = project_root / "instruments" / args.name
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
                    f"[cli] WARNING: new fitness {fitness_score:.4f} is worse "
                    f"than existing {old_fitness:.4f} (version {version - 1}). "
                    f"Saving anyway as version {version}.",
                    flush=True,
                )
        except (json.JSONDecodeError, KeyError):
            pass

    # --- params.json ---
    params_dict["fitness_score"] = round(fitness_score, 4)
    params_dict["version"] = version
    if args.chip_model:
        params_dict["chip_model"] = args.chip_model
    if args.source_instrument:
        params_dict["source_instrument"] = args.source_instrument
    (inst_dir / "params.json").write_text(
        json.dumps(params_dict, indent=2) + "\n"
    )

    # --- raw.asm ---
    label = args.name.replace("-", "_")
    sid_params = sid_params_from_dict(
        {k: v for k, v in params_dict.items()
         if k not in ("fitness_score", "version")}
    )
    asm_text = encode_raw_asm(
        sid_params, label, fitness_score=fitness_score, version=version,
        chip_model=args.chip_model, source_instrument=args.source_instrument,
    )
    (inst_dir / "raw.asm").write_text(asm_text)

    # --- GoatTracker ---
    try:
        from .encoders.goattracker import encode_goattracker
        gt_data = encode_goattracker(sid_params, args.name)
        (inst_dir / "goattracker.ins").write_bytes(gt_data)
    except Exception as e:
        print(f"[cli] goattracker encode skipped: {e}", flush=True)

    # --- Copy render if present ---
    render_wav = work_dir / "best_render.wav"
    if render_wav.exists():
        import shutil
        shutil.copy2(render_wav, inst_dir / "sid_render.wav")

    # --- README.md ---
    readme_text = _instrument_readme(
        args.name, params_dict, fitness_score, version,
        chip_model=args.chip_model, source_instrument=args.source_instrument,
    )
    (inst_dir / "README.md").write_text(readme_text)

    print(
        f"[cli] exported {args.name} v{version} "
        f"(fitness={fitness_score:.4f}) to {inst_dir}/",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sidmatch")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("match", help="search SID patch space for a sample")
    m.add_argument("--sample", required=True, help="reference WAV path")
    m.add_argument("--frequency", type=float, required=True, help="pitch in Hz")
    m.add_argument("--name", required=True, help="instrument name")
    m.add_argument("--budget", type=int, default=5000)
    m.add_argument("--patience", type=int, default=500)
    m.add_argument("--workers", type=int, default=None)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--work-dir", required=True)
    m.add_argument("--chip-model", default=None, choices=["6581", "8580"],
                   help="target SID chip model (default: pyresidfp default, MOS6581)")
    m.add_argument("--source-instrument", default=None,
                   help="free-text description of the reference recording")
    m.set_defaults(func=cmd_match)

    e = sub.add_parser("export", help="export work-dir result to instruments/")
    e.add_argument("--work-dir", required=True, help="sidmatch work directory")
    e.add_argument("--name", required=True, help="instrument name (kebab-case)")
    e.add_argument("--fitness-score", type=float, required=True,
                   help="final fitness score")
    e.add_argument("--chip-model", default=None, choices=["6581", "8580"],
                   help="target SID chip model")
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
