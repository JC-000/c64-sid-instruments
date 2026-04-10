# A/B comparison: Detert piano vs ours (8580)

## Piece

**Beethoven — Bagatelle No. 25 in A minor, WoO 59 ("Fur Elise")**
Public domain. Opening A-theme, mm. 1-8, right-hand melody only (monophonic
single-voice SID rendering, no accompaniment).

Note sequence: [`fur_elise_notes.json`](./fur_elise_notes.json)
Rendering script: [`../tools/render_fur_elise.py`](../tools/render_fur_elise.py)

## Variants

Both WAVs render the exact same note sequence through the same renderer
(`tools/sidmatch/render.py::render_pyresid`) targeting the **8580** SID
chip model. Only the instrument parameters differ.

| File | Params source | What it represents |
|---|---|---|
| `fur_elise_detert_8580.wav` | `instruments/reference-pianos/detert-piano/detert-piano-6581-params.json` | Thomas Detert's manually-crafted piano params, reverse-engineered from `Ivory.sid` siddump analysis. Human-designed reference. |
| `fur_elise_ours_8580.wav` | `instruments/grand-piano/8580/grand-piano-8580-params.json` (HEAD) | Our current best grand piano 8580: the v7/v8 baseline params restored in commit `9ec6636`, rendered through the click-fixed renderer from commit `ce6eba9`. |

The Detert params JSON is chip-agnostic (no `chip_model` field); it has
been used to render both 6581 and 8580 chromatic scales previously in the
repo, so rendering it through the 8580 chip here is consistent with
existing usage.

## What this A/B is evaluating

Our "best" piano instrument is **not** the output of any of the newer
algorithmic fitting experiments. The TPE/CMA-ES warm-start and
instrument-type constraint-profile work (commits `6ab5902`, `4a94c09`,
`db63b8f`) produced regressions in perceptual piano quality. Commit
`9ec6636` ("Fix fitness saturation, restore piano baseline params")
rolled the grand piano params back to the pre-regression v7/v8 baseline.
Combined with the volume-register click fix from `ce6eba9`, that baseline
is currently the best-sounding SID piano we have.

This A/B isolates the **instrument quality gap** between:

- a human-crafted SID piano (Detert, widely regarded as one of the best
  SID piano sounds in existence), and

- our best automatically-optimized SID piano (old-approach + click fix).

Both play the same well-known melody so the comparison is purely about
timbre, attack transient, decay envelope, and PWM character — not about
any differences in tempo, rhythm, or note choice.

## Reproducing

```bash
python3 tools/render_fur_elise.py \
    --params instruments/grand-piano/8580/grand-piano-8580-params.json \
    --notes comparisons/fur_elise_notes.json \
    --chip 8580 \
    --out comparisons/fur_elise_ours_8580.wav

python3 tools/render_fur_elise.py \
    --params instruments/reference-pianos/detert-piano/detert-piano-6581-params.json \
    --notes comparisons/fur_elise_notes.json \
    --chip 8580 \
    --out comparisons/fur_elise_detert_8580.wav
```

## Caveats

- **Monophonic only**: Fur Elise's opening is transcribed here as the
  right-hand melody only. The left-hand arpeggio figure (mm. 3-4 etc.)
  is omitted because this A/B uses a single SID voice.
- **Transcription**: the note sequence is transcribed from memory of
  the published score, not from a machine-parsed MIDI. It is intended
  to be recognizable, not performance-grade edition-accurate.
- **Peak normalization**: each WAV is peak-normalized to 0.95 to keep
  the two variants at comparable loudness for direct comparison.
- **Tempo/articulation**: 72 BPM with 85% gate / 15% release split per
  note. The renderer's per-note gate length affects how the instrument's
  ADSR decay interacts with the melody, so the "same" params will sound
  slightly different here than in the chromatic-scale WAVs where each
  note gets the full 200+ frame gate.
