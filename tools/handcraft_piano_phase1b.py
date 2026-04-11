#!/usr/bin/env python3
"""Phase 1b: waveform-table ablations on the hand-crafted 8580 piano.

The Phase 1 baseline used ``waveform_table = [0x81, 0x41, 0x11]`` which starts
with **pure noise** (0x81 = noise + gate). At A=0 this plays a full frame of
random samples (~20 ms of static crackle), which does not resemble a piano
hammer strike. This script renders six alternative waveform tables on the
*exact same* hand-crafted parameters so the user can A/B-pick the most
piano-like attack.

Each ablation renders two WAVs:
  * chromatic scale (C3..C5, 9 notes)
  * Fur Elise

into ``comparisons/phase1b/``. All other params come from
``tools.handcraft_piano.make_handcraft_params``.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from handcraft_piano import (  # noqa: E402
    OUT_DIR as PHASE1_OUT_DIR,  # noqa: F401
    SAMPLE_RATE,
    CHIP,
    NOTES,  # noqa: F401
    inspect,
    make_handcraft_params,
    render_fur_elise,
    render_scale,
    save_wav,
)

OUT_DIR = ROOT / "comparisons" / "phase1b"


# (name, waveform_table, rationale)
ABLATIONS = [
    (
        "handcraft_wt_tri_only",
        [0x11],
        "triangle only — no attack transient primitive; baseline to hear "
        "the rest of the instrument (filter_env, PWM LFO, ADSR, hard restart) "
        "in isolation.",
    ),
    (
        "handcraft_wt_pul_tri",
        [0x41, 0x11],
        "pulse -> triangle — pulse-click attack (one frame of ~50% duty "
        "square edge) then mellow triangle body. Pulse waveform change from "
        "none to on produces a hard sample-level edge but no noise.",
    ),
    (
        "handcraft_wt_pultri_tri",
        [0x51, 0x11],
        "pulse+triangle -> triangle — combined-waveform 0x51 is a reedy "
        "hollow timbre on 8580, used historically for bass/piano. Morphs "
        "directly into pure triangle.",
    ),
    (
        "handcraft_wt_noisepul_pul_tri",
        [0xC1, 0x41, 0x11],
        "noise+pulse -> pulse -> triangle — 0xC1 is a narrow-band gated "
        "noise burst (pulse gates the noise shift register) for ~20 ms, then "
        "one frame of pulse, then triangle. Historically-used piano attack.",
    ),
    (
        "handcraft_wt_pul_pultri_tri",
        [0x41, 0x51, 0x11],
        "pulse -> pulse+triangle -> triangle — no noise at all; a smooth "
        "three-step morph from pulse through combined pulse+triangle to "
        "triangle. Cleanest possible attack progression.",
    ),
    (
        "handcraft_wt_noisepul_tri",
        [0xC1, 0x11],
        "noise+pulse -> triangle — shorter variant of the gated-noise "
        "burst, skipping the pulse intermediate. One frame of narrow-band "
        "noise then straight into triangle body.",
    ),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = make_handcraft_params()

    results: dict[str, dict] = {}

    for name, wt, _rationale in ABLATIONS:
        params = dataclasses.replace(base, waveform_table=wt)

        scale_path = OUT_DIR / f"{name}.wav"
        print(f"Rendering {scale_path.name} (wt={[hex(b) for b in wt]}) ...")
        a_scale = render_scale(params)
        save_wav(a_scale, scale_path)
        results[name] = inspect(a_scale, name)
        results[name]["waveform_table"] = [hex(b) for b in wt]

        fe_path = OUT_DIR / f"{name}_fur_elise.wav"
        print(f"Rendering {fe_path.name} ...")
        render_fur_elise(params, fe_path)
        fe_audio, _ = sf.read(str(fe_path), dtype="float32")
        if fe_audio.ndim > 1:
            fe_audio = fe_audio.mean(axis=1)
        results[f"{name}_fur_elise"] = inspect(fe_audio, f"{name}_fur_elise")
        results[f"{name}_fur_elise"]["waveform_table"] = [hex(b) for b in wt]

    print()
    print("Numeric inspection:")
    for label, row in results.items():
        print(f"  {label}:")
        for k, v in row.items():
            if k == "label":
                continue
            print(f"    {k}: {v}")

    with open(OUT_DIR / "inspection.json", "w") as f:
        json.dump(results, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
