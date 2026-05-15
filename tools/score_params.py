#!/usr/bin/env python3
"""Score SID instrument params against a reference set.

Usage:
    python -m tools.score_params <params.json> <reference-set-dir> [--chip 6581|8580]

Renders the instrument at each note in the reference set, extracts features,
computes per-component and total fitness distances using the current fitness
function.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Ensure repo root is on sys.path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from tools.sidmatch.render import SidParams, render_pyresid
from tools.sidmatch.features import FeatureVec, extract, CANONICAL_SR
from tools.sidmatch.fitness import (
    DEFAULT_WEIGHTS,
    _envelope_l2,
    _cosine_distance,
    _log_series_l1,
    _series_l1,
    _f0_log_ratio,
    _log_mel_mse,
    _onset_spectral_distance,
    _mfcc_distance,
    _spectral_convergence_distance,
    _adsr_l1,
)
from tools.sidmatch.multi_note import ReferenceSet, _multi_note_weights
from tools.sidmatch.optimize import load_reference_audio


def compute_components(ref: FeatureVec, cand: FeatureVec) -> Dict[str, float]:
    """Compute per-component raw (unweighted) distances."""
    return {
        "envelope": _envelope_l2(ref.amplitude_envelope, cand.amplitude_envelope),
        "harmonics": _cosine_distance(ref.harmonic_magnitudes, cand.harmonic_magnitudes),
        "spectral_centroid": _log_series_l1(
            ref.spectral_centroid, cand.spectral_centroid, scale=np.log(2) * 4
        ),
        "spectral_rolloff": _log_series_l1(
            ref.spectral_rolloff, cand.spectral_rolloff, scale=np.log(2) * 4
        ),
        "spectral_flatness": _series_l1(ref.spectral_flatness, cand.spectral_flatness),
        "noisiness": (ref.noisiness - cand.noisiness) ** 2,
        "fundamental": _f0_log_ratio(ref.fundamental_hz, cand.fundamental_hz),
        "adsr": _adsr_l1(ref, cand),
        "log_mel": _log_mel_mse(ref.log_mel, cand.log_mel),
        "envelope_delta": _envelope_l2(
            np.diff(np.asarray(ref.amplitude_envelope, dtype=np.float64)),
            np.diff(np.asarray(cand.amplitude_envelope, dtype=np.float64)),
        ),
        "onset_spectral": _onset_spectral_distance(ref, cand),
        "mfcc": _mfcc_distance(ref, cand),
        "spectral_convergence": _spectral_convergence_distance(ref, cand),
    }


def load_params_from_json(path: Path) -> SidParams:
    """Load a params JSON into a SidParams dataclass, handling field name variations."""
    raw = json.loads(path.read_text())

    # Build kwargs for SidParams, filtering to known fields
    from dataclasses import fields as dc_fields
    known = {f.name for f in dc_fields(SidParams)}
    kwargs = {}
    for k, v in raw.items():
        if k in known:
            kwargs[k] = v
        # Skip unknown fields like fitness_score, version, reference_notes, etc.

    return SidParams(**kwargs)


def score_params(
    params: SidParams,
    ref_set: ReferenceSet,
    chip_model: Optional[str] = None,
    label: str = "",
) -> Dict:
    """Score params against all notes. Returns per-note and aggregate results."""
    mn_weights = _multi_note_weights()

    all_components: Dict[str, List[float]] = {k: [] for k in DEFAULT_WEIGHTS}
    note_distances: List[float] = []

    for note_ref in ref_set.notes:
        note_params = replace(params, frequency=note_ref.freq_hz)
        try:
            audio = render_pyresid(note_params, sample_rate=CANONICAL_SR, chip_model=chip_model)

            # Pad to match reference duration
            target_samples = int(note_ref.ref_fv.duration_s * CANONICAL_SR)
            if audio.shape[0] < target_samples:
                pad = np.zeros(target_samples - audio.shape[0], dtype=audio.dtype)
                audio = np.concatenate([audio, pad])

            fv = extract(audio, CANONICAL_SR, known_f0=note_ref.freq_hz)
            comps = compute_components(note_ref.ref_fv, fv)

            for k, v in comps.items():
                all_components[k].append(v)

            # Weighted total for this note
            d = sum(mn_weights[k] * v for k, v in comps.items())
            note_distances.append(d)
        except Exception as e:
            print(f"  WARNING: Note {note_ref.note_name} failed: {e}")
            note_distances.append(1e6)
            for k in all_components:
                all_components[k].append(float("nan"))

    # Aggregate: mean and max
    mean_d = float(np.mean(note_distances))
    max_d = float(np.max(note_distances))
    alpha = 0.15
    aggregate = (1.0 - alpha) * mean_d + alpha * max_d

    # Mean components across notes
    mean_components = {}
    for k, vals in all_components.items():
        clean = [v for v in vals if not np.isnan(v)]
        mean_components[k] = float(np.mean(clean)) if clean else float("nan")

    return {
        "label": label,
        "aggregate_fitness": aggregate,
        "mean_fitness": mean_d,
        "max_fitness": max_d,
        "mean_components": mean_components,
        "note_distances": note_distances,
        "note_names": ref_set.note_names(),
        "weights": mn_weights,
    }


def print_comparison(results: List[Dict]):
    """Print a formatted comparison table."""
    # Active components (weight > 0)
    weights = results[0]["weights"]
    active = [k for k, w in weights.items() if w > 0]

    # Header
    labels = [r["label"] for r in results]
    col_w = max(18, max(len(l) for l in labels) + 2)

    print("\n" + "=" * 80)
    print("PIANO FITNESS COMPARISON")
    print("=" * 80)

    # Per-component table
    print(f"\n{'Component':<24} {'Weight':>6}", end="")
    for r in results:
        print(f"  {r['label']:>{col_w}}", end="")
    print()
    print("-" * (32 + (col_w + 2) * len(results)))

    for comp in active:
        w = weights[comp]
        print(f"  {comp:<22} {w:>6.1f}", end="")
        for r in results:
            raw = r["mean_components"].get(comp, 0.0)
            weighted = raw * w
            print(f"  {raw:>{col_w - 10}.4f} (w={weighted:.3f})", end="")
        print()

    # Totals
    print("-" * (32 + (col_w + 2) * len(results)))
    print(f"  {'WEIGHTED TOTAL':<22} {'':>6}", end="")
    for r in results:
        total = sum(r["mean_components"].get(k, 0) * weights[k] for k in active)
        print(f"  {total:>{col_w}.4f}", end="")
    print()

    print(f"\n  {'Mean distance':<22} {'':>6}", end="")
    for r in results:
        print(f"  {r['mean_fitness']:>{col_w}.4f}", end="")
    print()

    print(f"  {'Max distance':<22} {'':>6}", end="")
    for r in results:
        print(f"  {r['max_fitness']:>{col_w}.4f}", end="")
    print()

    print(f"  {'AGGREGATE (a=0.15)':<22} {'':>6}", end="")
    for r in results:
        print(f"  {r['aggregate_fitness']:>{col_w}.4f}", end="")
    print()

    # Winner
    if len(results) == 2:
        a, b = results
        diff = a["aggregate_fitness"] - b["aggregate_fitness"]
        if diff < 0:
            print(f"\n  >>> {a['label']} is BETTER by {abs(diff):.4f} ({abs(diff)/b['aggregate_fitness']*100:.1f}%)")
        elif diff > 0:
            print(f"\n  >>> {b['label']} is BETTER by {abs(diff):.4f} ({abs(diff)/a['aggregate_fitness']*100:.1f}%)")
        else:
            print(f"\n  >>> TIE")

    # Per-note breakdown
    print(f"\n{'Per-note distances':}")
    print(f"  {'Note':<8}", end="")
    for r in results:
        print(f"  {r['label']:>{col_w}}", end="")
    print()
    for i, name in enumerate(results[0]["note_names"]):
        print(f"  {name:<8}", end="")
        for r in results:
            d = r["note_distances"][i]
            print(f"  {d:>{col_w}.4f}", end="")
        print()

    print()


def print_params_summary(label: str, params: SidParams):
    """Print key params for a version."""
    print(f"\n  {label}:")
    print(f"    Waveform:      {params.waveform}")
    print(f"    ADSR:          A={params.attack} D={params.decay} S={params.sustain} R={params.release}")
    print(f"    Gate/Release:  {params.gate_frames}/{params.release_frames} frames")
    print(f"    PW:            start={params.effective_pw_start()} delta={params.pw_delta}")
    print(f"    Filter:        mode={params.filter_mode} cutoff={params.effective_filter_cutoff_start()}->{params.effective_filter_cutoff_end()} res={params.filter_resonance}")
    print(f"    WT attack:     {params.wt_attack_waveform} x{params.wt_attack_frames} test_bit={params.wt_use_test_bit}")
    print(f"    WT sustain:    {params.wt_sustain_waveform}")
    if params.wavetable_steps:
        print(f"    WT steps:      {params.wavetable_steps}")


def main():
    parser = argparse.ArgumentParser(description="Score SID params against reference set")
    parser.add_argument("params_json", nargs="+", help="One or more params JSON files to score")
    parser.add_argument("--ref-dir", required=True, help="Reference set directory (with note_map.json)")
    parser.add_argument("--chip", default=None, help="Override chip model (6581 or 8580)")
    parser.add_argument("--labels", nargs="*", help="Labels for each params file")
    args = parser.parse_args()

    ref_dir = Path(args.ref_dir)
    print(f"Loading reference set from {ref_dir} ...")
    ref_set = ReferenceSet.load(ref_dir)
    print(f"  {len(ref_set)} notes: {ref_set.note_names()}")

    results = []
    all_params = []
    for i, pj in enumerate(args.params_json):
        path = Path(pj)
        label = args.labels[i] if args.labels and i < len(args.labels) else path.stem
        chip = args.chip
        params = load_params_from_json(path)
        if chip is None and params.chip_model:
            chip = params.chip_model

        print(f"\nScoring {label} (chip={chip}) ...")
        result = score_params(params, ref_set, chip_model=chip, label=label)
        results.append(result)
        all_params.append((label, params))

    # Print params summary
    print("\n" + "=" * 80)
    print("PARAMS SUMMARY")
    print("=" * 80)
    for label, params in all_params:
        print_params_summary(label, params)

    # Print comparison
    print_comparison(results)


if __name__ == "__main__":
    main()
