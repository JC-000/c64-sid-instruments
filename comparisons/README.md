# A/B comparison: Detert piano vs ours (native chips)

## Piece

**Beethoven — Bagatelle No. 25 in A minor, WoO 59 ("Fur Elise")**
Public domain. 1/8 pickup + mm. 1-8 (first ending) of the opening A-theme,
right-hand melody only (monophonic single-voice SID rendering, no
accompaniment).

Note sequence: [`fur_elise_notes.json`](./fur_elise_notes.json)
Rendering script: [`../tools/render_fur_elise.py`](../tools/render_fur_elise.py)

### Canonical source

The note sequence is transcribed from the Mutopia Project edition of
Beethoven WoO 59 (LilyPond source, typeset by Stelios Samelis, based on
Breitkopf & Härtel, 1888 — public domain):

<https://www.mutopiaproject.org/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.ly>

Mutopia piece page: <https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931>

### Transcription corrections (2026-04)

The original from-memory transcription had the right pitch collection for
the passage but mis-grouped the rhythms in several bars. It has been
rewritten to match the canonical Mutopia source exactly. Specific fixes:

- Added the 1/8 pickup (E5 D#5) that precedes bar 1. The memory version
  folded the pickup into bar 1 and dropped the tail of bar 1.
- Bar 1 now correctly ends with D5, C5 (memory had an extra D#5, E5
  oscillation and omitted D5 C5).
- Bars 2, 3, 4, 6 now use the canonical `8th + 16-rest + 16 + 16 + 16`
  rhythm (held note, then a sixteenth rest, then the three-sixteenth
  ascending pickup figure). The memory version had inconsistent groupings
  with quarter-note holds, full-beat rests, and no internal rests.
- Bar 7 now correctly reads B4(8th) rest E4 C5 B4 (memory had the bar-6
  pattern repeated here by mistake).
- Bar 8 (first ending) is a held A4 quarter note, as in the score. Memory
  had a compound B4 E4 C5 B4 A4 figure that belongs to the second ending /
  continuation, not the first ending.

The full event count went from 37 to 40 events after the fix.

## Variants

Each instrument is rendered through **its native SID chip revision**.
The Detert piano was hand-designed for the 6581, while our optimised
grand piano was fit specifically against the 8580. The A/B is therefore
intentionally cross-chip — we are comparing each instrument in the sonic
environment it was designed for, not rendering both through the same
chip.

| File | Params source | Chip | What it represents |
|---|---|---|---|
| `fur_elise_detert_6581.wav` | `instruments/reference-pianos/detert-piano/detert-piano-6581-params.json` | 6581 | Thomas Detert's manually-crafted piano params, reverse-engineered from `Ivory.sid` siddump analysis, rendered on their native 6581 chip. |
| `fur_elise_ours_8580.wav` | `instruments/grand-piano/8580/grand-piano-8580-params.json` (HEAD) | 8580 | Our current best grand piano 8580: the v7/v8 baseline params restored in commit `9ec6636`, rendered through the click-fixed renderer from commit `ce6eba9`, on its native 8580 chip. |

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
  SID piano sounds in existence), playing on its intended 6581, and

- our best automatically-optimised SID piano (old-approach + click fix),
  playing on its intended 8580.

Both play the same well-known melody so the comparison is about timbre,
attack transient, decay envelope, and PWM character as each instrument
sounds on its native chip — not about differences in tempo, rhythm, or
note choice.

## Reproducing

```bash
python3 tools/render_fur_elise.py \
    --params instruments/reference-pianos/detert-piano/detert-piano-6581-params.json \
    --notes comparisons/fur_elise_notes.json \
    --chip 6581 \
    --out comparisons/fur_elise_detert_6581.wav

python3 tools/render_fur_elise.py \
    --params instruments/grand-piano/8580/grand-piano-8580-params.json \
    --notes comparisons/fur_elise_notes.json \
    --chip 8580 \
    --out comparisons/fur_elise_ours_8580.wav
```

## Caveats

- **Monophonic only**: Fur Elise's opening is rendered here as the
  right-hand melody only. The left-hand arpeggio figure (mm. 3-4 etc.)
  is omitted because this A/B uses a single SID voice.
- **Cross-chip A/B**: because each instrument plays on its native SID
  revision, any timbral differences reflect both the instrument design
  *and* the chip differences. This is deliberate — it's how each piano
  is meant to sound.
- **Peak normalization**: each WAV is peak-normalized to 0.95 to keep
  the two variants at comparable loudness for direct comparison.
- **Tempo/articulation**: 72 BPM with 85% gate / 15% release split per
  note. The renderer's per-note gate length affects how the instrument's
  ADSR decay interacts with the melody, so the "same" params will sound
  slightly different here than in the chromatic-scale WAVs where each
  note gets the full 200+ frame gate.
