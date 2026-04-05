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
)
from .grid_search import grid_search
from .render import render_pyresid
from .features import CANONICAL_SR


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
    audio = render_pyresid(result.best_params, sample_rate=CANONICAL_SR)
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
    m.set_defaults(func=cmd_match)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
