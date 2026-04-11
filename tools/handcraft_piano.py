#!/usr/bin/env python3
"""Phase 1 diagnostic: hand-crafted Detert-inspired grand piano (8580).

This is NOT an optimization result. It exists purely to prove whether the
expanded SidParams primitives (waveform_table, hard_restart, pwm_lfo,
filter_env) are expressive enough to move audibly closer to a real grand
piano on an 8580. No optimizer is involved; parameters are picked by
informed guess from R2's research notes on Detert's Ivory instrument.

Renders four WAVs into ``comparisons/phase1/``:

  * ``handcraft_full.wav``              — full instrument
  * ``handcraft_no_hard_restart.wav``   — hard_restart=False
  * ``handcraft_no_waveform_table.wav`` — waveform_table=None (base pulse only)
  * ``handcraft_fur_elise.wav``         — Fur Elise via render_fur_elise driver

The chromatic scale uses the same 9-note C3..C5 set as
``work/grand-piano-chromatic-scale-8580.wav`` for direct A/B comparison.

Usage: ``python3 tools/handcraft_piano.py``
"""

from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from sidmatch.render import SidParams, render_pyresid  # noqa: E402

SAMPLE_RATE = 44100
CHIP = "8580"
OUT_DIR = ROOT / "comparisons" / "phase1"
SAMPLES_DIR = ROOT / "tools" / "samples" / "grand-piano"
NOTES = ["C3", "Eb3", "Gb3", "A3", "C4", "Eb4", "Gb4", "A4", "C5"]
SILENCE_MS = 200
SILENCE_SAMPLES = int(SAMPLE_RATE * SILENCE_MS / 1000)


def make_handcraft_params() -> SidParams:
    """Build a Detert-inspired grand-piano patch for 8580.

    Design notes:

    - ``waveform_table = [0x81, 0x41, 0x11]`` — noise+pulse (frame 0,
      "hammer strike" transient with broadband energy), then pulse+triangle
      (frame 1, harmonic body forming), then triangle (frame 2+, sustained
      mellow body). This mirrors the Detert Ivory three-step wavetable
      described in R2's notes: a spectrally-shaped attack transient driven
      purely by waveform-register transitions, NOT by $D418 volume-register
      clicks (which are ~unusable on 8580).
    - ``hard_restart = True`` with 2 frames of TEST bit + zero ADSR resets
      oscillator phase so every note starts identically, defeating the
      ADSR bug.
    - ``pwm_lfo_rate = 5 Hz``, ``depth = 350`` — slow triangle-ish LFO
      around the 2048 midpoint, giving the "detuned multi-string" shimmer.
    - ``filter_env`` starts bright (0x700) and darkens to 0x100 over
      ~30 frames (~0.6s) — fast tonal darkening mimicking a piano's
      natural high-frequency decay.
    - ADSR: A=0 (instant hammer), D=8 (~300 ms), S=15 (CRITICAL: piano
      body must not collapse to zero), R=12 (~2.4 s long release).
    - Base waveform = pulse (0x41) is the fallback when the table is
      disabled in the ablation renders.
    """
    return SidParams(
        waveform="pulse",
        frequency=261.63,  # C4, overwritten per-note
        attack=0,
        decay=8,
        sustain=15,
        release=12,
        pulse_width=2048,
        filter_cutoff=1792,  # 0x700
        filter_resonance=4,
        filter_mode="lp",
        filter_voice1=True,
        gate_frames=90,     # ~1.8 s
        release_frames=60,  # ~1.2 s
        chip_model=CHIP,
        source_instrument="handcraft-detert-inspired-8580-phase1",

        # Phase 1 expressive primitives
        waveform_table=[0x81, 0x41, 0x11],
        waveform_table_hold_frames=1,
        hard_restart=True,
        hard_restart_frames=2,
        pwm_lfo_rate=5.0,
        pwm_lfo_depth=350,
        filter_env=[
            0x700, 0x6C0, 0x680, 0x640, 0x600, 0x5A0, 0x540, 0x4C0,
            0x460, 0x400, 0x3A0, 0x340, 0x2E0, 0x280, 0x230, 0x1E0,
            0x1A0, 0x170, 0x140, 0x120, 0x100, 0x100, 0x100, 0x100,
            0x100, 0x100, 0x100, 0x100, 0x100, 0x100,
        ],
        filter_env_hold_frames=1,
    )


def ablate(params: SidParams, **overrides) -> SidParams:
    return dataclasses.replace(params, **overrides)


def render_scale(params: SidParams) -> np.ndarray:
    """Render the 9-note chromatic scale, 200ms silence between notes."""
    with open(SAMPLES_DIR / "note_map.json") as f:
        note_map = json.load(f)

    segments = []
    for note in NOTES:
        freq = note_map[note]["freq_hz"]
        p = dataclasses.replace(params, frequency=freq)
        audio = render_pyresid(p, sample_rate=SAMPLE_RATE, chip_model=CHIP)
        segments.append(audio.astype(np.float32))
        segments.append(np.zeros(SILENCE_SAMPLES, dtype=np.float32))
    if segments:
        segments.pop()
    return np.concatenate(segments)


def inspect(audio: np.ndarray, label: str) -> dict:
    """Compute simple numeric observations — RMS, peak, envelope shape."""
    if audio.size == 0:
        return {"label": label, "empty": True}
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))
    # Transient peak: max |x| in first 50 ms
    head_n = min(len(audio), int(0.05 * SAMPLE_RATE))
    transient = float(np.max(np.abs(audio[:head_n]))) if head_n else 0.0
    # Envelope drop: mean |x| in first 200 ms vs last 500 ms
    early = audio[: int(0.2 * SAMPLE_RATE)]
    late = audio[int(-0.5 * SAMPLE_RATE):]
    early_rms = float(np.sqrt(np.mean(early ** 2))) if early.size else 0.0
    late_rms = float(np.sqrt(np.mean(late ** 2))) if late.size else 0.0
    nan_frac = float(np.mean(np.isnan(audio)))
    clip_frac = float(np.mean(np.abs(audio) >= 0.999))
    return {
        "label": label,
        "samples": int(len(audio)),
        "duration_s": round(len(audio) / SAMPLE_RATE, 3),
        "rms": round(rms, 5),
        "peak": round(peak, 5),
        "transient_peak_50ms": round(transient, 5),
        "early_rms_200ms": round(early_rms, 5),
        "late_rms_500ms": round(late_rms, 5),
        "nan_frac": nan_frac,
        "clip_frac": round(clip_frac, 5),
    }


def save_wav(audio: np.ndarray, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Light peak normalization to avoid clipping
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-6:
        audio = audio * (0.95 / peak)
    sf.write(str(out_path), audio.astype(np.float32), SAMPLE_RATE)


def render_fur_elise(params: SidParams, out_path: Path) -> None:
    """Drive tools/render_fur_elise.py with a JSON dump of this patch."""
    # Write params to a temp JSON file that render_fur_elise accepts
    params_dict = dataclasses.asdict(params)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tf:
        json.dump(params_dict, tf, indent=2)
        tmp_path = Path(tf.name)
    try:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "render_fur_elise.py"),
                "--params", str(tmp_path),
                "--notes", str(ROOT / "comparisons" / "fur_elise_notes.json"),
                "--chip", CHIP,
                "--out", str(out_path),
            ],
            check=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    full = make_handcraft_params()
    no_hr = ablate(full, hard_restart=False)
    no_wt = ablate(full, waveform_table=None)

    results = {}

    print("Rendering handcraft_full.wav ...")
    a_full = render_scale(full)
    save_wav(a_full, OUT_DIR / "handcraft_full.wav")
    results["handcraft_full"] = inspect(a_full, "handcraft_full")

    print("Rendering handcraft_no_hard_restart.wav ...")
    a_nohr = render_scale(no_hr)
    save_wav(a_nohr, OUT_DIR / "handcraft_no_hard_restart.wav")
    results["handcraft_no_hard_restart"] = inspect(a_nohr, "no_hard_restart")

    print("Rendering handcraft_no_waveform_table.wav ...")
    a_nowt = render_scale(no_wt)
    save_wav(a_nowt, OUT_DIR / "handcraft_no_waveform_table.wav")
    results["handcraft_no_waveform_table"] = inspect(a_nowt, "no_waveform_table")

    print("Rendering handcraft_fur_elise.wav ...")
    render_fur_elise(full, OUT_DIR / "handcraft_fur_elise.wav")
    fe_audio, _ = sf.read(str(OUT_DIR / "handcraft_fur_elise.wav"),
                          dtype="float32")
    if fe_audio.ndim > 1:
        fe_audio = fe_audio.mean(axis=1)
    results["handcraft_fur_elise"] = inspect(fe_audio, "fur_elise")

    print()
    print("Numeric inspection:")
    for label, row in results.items():
        print(f"  {label}:")
        for k, v in row.items():
            if k == "label":
                continue
            print(f"    {k}: {v}")

    # Write the inspection JSON alongside the WAVs for the README
    with open(OUT_DIR / "inspection.json", "w") as f:
        json.dump(results, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
