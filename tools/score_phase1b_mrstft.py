#!/usr/bin/env python3
"""Score Phase 1b ablations against the Salamander reference with MR-STFT.

Uses ``tools.sidmatch.fitness.distance_v2`` (length-trimmed reference) so
numbers are directly comparable to what the optimizer sees.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from sidmatch.fitness import distance_v2  # noqa: E402

REF_PATH = ROOT / "instruments" / "grand-piano" / "grand-piano-reference-scale.wav"

TARGETS = [
    # Phase 1b ablations (chromatic scale)
    ("phase1b: tri_only          [0x11]",           "comparisons/phase1b/handcraft_wt_tri_only.wav"),
    ("phase1b: pul_tri           [0x41,0x11]",      "comparisons/phase1b/handcraft_wt_pul_tri.wav"),
    ("phase1b: pultri_tri        [0x51,0x11]",      "comparisons/phase1b/handcraft_wt_pultri_tri.wav"),
    ("phase1b: noisepul_pul_tri  [0xC1,0x41,0x11]", "comparisons/phase1b/handcraft_wt_noisepul_pul_tri.wav"),
    ("phase1b: pul_pultri_tri    [0x41,0x51,0x11]", "comparisons/phase1b/handcraft_wt_pul_pultri_tri.wav"),
    ("phase1b: noisepul_tri      [0xC1,0x11]",      "comparisons/phase1b/handcraft_wt_noisepul_tri.wav"),
    # Phase 1 baselines (noise attack)
    ("phase1:  handcraft_full    [0x81,0x41,0x11]", "comparisons/phase1/handcraft_full.wav"),
    ("phase1:  no_hard_restart",                     "comparisons/phase1/handcraft_no_hard_restart.wav"),
    ("phase1:  no_waveform_table",                   "comparisons/phase1/handcraft_no_waveform_table.wav"),
    # Older reference points
    ("comp:    grand-piano-8580-scale-head",         "comparisons/grand-piano-8580-scale-head.wav"),
    ("comp:    grand-piano-8580-scale-4a94c09",      "comparisons/grand-piano-8580-scale-4a94c09.wav"),
    ("comp:    grand-piano-8580-scale-mrstft-opt",   "comparisons/grand-piano-8580-scale-mrstft-opt.wav"),
]


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, sr


def main() -> int:
    ref, ref_sr = load_mono(REF_PATH)
    print(f"Reference: {REF_PATH.relative_to(ROOT)}  "
          f"({ref.size} samples @ {ref_sr} Hz, {ref.size / ref_sr:.2f} s)")
    print()

    results: list[dict] = []
    for label, rel in TARGETS:
        path = ROOT / rel
        if not path.exists():
            print(f"  SKIP (missing): {rel}")
            continue
        cand, cand_sr = load_mono(path)
        if cand_sr != ref_sr:
            print(f"  SKIP (sr mismatch: {cand_sr} vs {ref_sr}): {rel}")
            continue
        d = float(distance_v2(ref, cand, ref_sr))
        results.append({"label": label, "path": rel, "mrstft": d,
                        "cand_samples": int(cand.size),
                        "cand_duration_s": round(cand.size / cand_sr, 3)})
        print(f"  {d:10.5f}   {label}")

    results.sort(key=lambda r: r["mrstft"])
    print()
    print("Sorted (lower = better):")
    for r in results:
        print(f"  {r['mrstft']:10.5f}   {r['label']}")

    out_path = ROOT / "comparisons" / "phase1b" / "mrstft_scores.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print()
    print(f"Wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
