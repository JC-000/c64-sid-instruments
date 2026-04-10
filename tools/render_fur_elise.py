#!/usr/bin/env python3
"""Render a short Fur Elise passage through a given SID params JSON.

Minimal evaluation-artifact script (not a reusable feature). Reuses
``tools.sidmatch.render.render_pyresid`` in a loop, similar to
``work/render_chromatic_scale.py``, but feeds arbitrary note sequences.

Usage:
    python3 tools/render_fur_elise.py \
        --params instruments/grand-piano/8580/grand-piano-8580-params.json \
        --notes comparisons/fur_elise_notes.json \
        --chip 8580 \
        --out comparisons/fur_elise_ours_8580.wav
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from sidmatch.render import SidParams, render_pyresid  # noqa: E402

SAMPLE_RATE = 44100

# Equal-tempered frequencies, A4 = 440 Hz.
# MIDI note numbers: C4 = 60, A4 = 69.
NOTE_NAME_TO_SEMITONE = {
    "C": 0, "C#": 1, "Db": 1,
    "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4,
    "F": 5, "E#": 5,
    "F#": 6, "Gb": 6,
    "G": 7,
    "G#": 8, "Ab": 8,
    "A": 9,
    "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}


def note_to_freq(name: str) -> float:
    """Convert a note name like 'E5' or 'D#5' to Hz (A4=440)."""
    # Parse octave (last character is a digit, or last two for negative — we
    # don't expect negative octaves here).
    for i, ch in enumerate(name):
        if ch.isdigit():
            pitch = name[:i]
            octave = int(name[i:])
            break
    else:
        raise ValueError(f"Cannot parse note name: {name!r}")
    if pitch not in NOTE_NAME_TO_SEMITONE:
        raise ValueError(f"Unknown pitch class: {pitch!r}")
    # MIDI: C-1 = 0, so Cn = 12*(n+1). A4 = 12*5 + 9 = 69.
    midi = 12 * (octave + 1) + NOTE_NAME_TO_SEMITONE[pitch]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def dict_to_sidparams(d: dict) -> SidParams:
    valid = {f.name for f in dataclasses.fields(SidParams)}
    filtered = {k: v for k, v in d.items() if k in valid}
    return SidParams(**filtered)


def render_note(
    base_params: dict,
    freq_hz: float,
    gate_frames: int,
    release_frames: int,
    chip: str,
) -> np.ndarray:
    p = dict(base_params)
    p["frequency"] = freq_hz
    p["gate_frames"] = gate_frames
    p["release_frames"] = release_frames
    # Strip non-SidParams metadata.
    for k in ("reference_notes", "fitness_score", "version",
              "source", "variant", "chip_model", "source_instrument"):
        p.pop(k, None)
    sp = dict_to_sidparams(p)
    return render_pyresid(sp, sample_rate=SAMPLE_RATE, chip_model=chip)


def render_melody(
    params_path: Path,
    notes_path: Path,
    chip: str,
    out_path: Path,
    tempo_bpm: Optional[float] = None,
) -> None:
    with open(params_path) as f:
        base_params = json.load(f)
    with open(notes_path) as f:
        melody = json.load(f)

    bpm = float(tempo_bpm if tempo_bpm is not None
                else melody.get("tempo_bpm", 72))
    # beat_unit is the note that gets the beat (eighth => 1 beat = 1 eighth)
    beat_unit = melody.get("beat_unit", "eighth")
    beat_unit_in_16ths = {"quarter": 4, "eighth": 2, "sixteenth": 1}[beat_unit]

    # Seconds per sixteenth
    sec_per_beat = 60.0 / bpm
    sec_per_16th = sec_per_beat / beat_unit_in_16ths

    # 1 PAL frame = 1/50 s. gate_frames is an integer count of 50Hz frames.
    frames_per_sec = 50.0

    # Articulation: split each note's total duration into gate (note-on) and
    # release tail. Use ~85% gate, 15% release so consecutive notes are
    # distinguishable without a hard cutoff.
    gate_fraction = 0.85

    segments = []
    for entry in melody["notes"]:
        dur_16ths = float(entry["duration_16ths"])
        total_sec = dur_16ths * sec_per_16th
        total_frames = max(2, int(round(total_sec * frames_per_sec)))

        if entry.get("note") is None:
            # Rest: emit silence of total_frames/50 seconds.
            n_samples = int(round(total_sec * SAMPLE_RATE))
            segments.append(np.zeros(n_samples, dtype=np.float32))
            continue

        gate_frames = max(1, int(round(total_frames * gate_fraction)))
        release_frames = max(1, total_frames - gate_frames)
        freq = note_to_freq(entry["note"])
        audio = render_note(base_params, freq, gate_frames, release_frames, chip)

        # Trim or pad to exact total_frames duration so tempo stays accurate.
        expected_samples = int(round(total_sec * SAMPLE_RATE))
        if len(audio) > expected_samples:
            audio = audio[:expected_samples]
        elif len(audio) < expected_samples:
            audio = np.pad(audio, (0, expected_samples - len(audio)))
        segments.append(audio.astype(np.float32))

    out_audio = np.concatenate(segments) if segments else np.zeros(0, np.float32)

    # Light peak normalization to avoid clipping between the two variants.
    peak = float(np.max(np.abs(out_audio))) if out_audio.size else 0.0
    if peak > 1e-6:
        out_audio = out_audio * (0.95 / peak)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), out_audio, SAMPLE_RATE)
    dur = len(out_audio) / SAMPLE_RATE
    print(f"  Wrote {out_path} ({dur:.2f}s, {len(melody['notes'])} events, "
          f"chip={chip})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True, type=Path,
                    help="Path to a SID params JSON file.")
    ap.add_argument("--notes", required=True, type=Path,
                    help="Path to the note sequence JSON.")
    ap.add_argument("--chip", required=True, choices=["6581", "8580"])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tempo-bpm", type=float, default=None,
                    help="Override tempo (quarter-note BPM equivalent via "
                         "beat_unit in notes file).")
    args = ap.parse_args()

    render_melody(args.params, args.notes, args.chip, args.out, args.tempo_bpm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
