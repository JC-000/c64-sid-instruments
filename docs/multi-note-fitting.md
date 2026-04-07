# Multi-note Chromatic Fitting

The multi-note evaluation pipeline optimizes a SID instrument patch across
multiple pitches simultaneously, rather than fitting against a single
reference recording.

## Motivation

A SID instrument is a single set of parameters (ADSR, waveform, pulse width
sweep, filter sweep) that must sound correct at every note the tracker plays.
Optimizing against one reference pitch can produce a patch that works well at
that pitch but breaks at others -- for example, if the filter cutoff is tuned
to a specific fundamental frequency, or the PW sweep rate only sounds natural
in a narrow range.

Multi-note fitting evaluates each candidate across an array of reference
pitches and aggregates the per-note fitness scores, penalizing patches with
large outliers.

## Aggregation formula

Given per-note distances `d_1, d_2, ..., d_N`:

    fitness = (1 - alpha) * mean(d_i) + alpha * max(d_i)

Default `alpha = 0.15`.  This mostly optimizes average quality but also
prevents any single note from being badly out of character.

## Fitness weight adjustments

When running in multi-note mode the following weight overrides are applied
(relative to the single-note defaults):

| Component | Single-note | Multi-note | Rationale |
|---|---:|---:|---|
| `harmonics` | 2.0 | 1.0 | SID waveform limitations inflate harmonic distance at extreme pitches |
| `adsr` | 1.0 | 1.5 | Envelope match is perceptually important across the range |
| `fundamental` | 2.0 | 0.0 | Frequency is set explicitly per note, not optimized |

## CLI usage

Use `--reference-set` instead of `--sample` + `--frequency`:

```bash
python3 -m sidmatch.cli match \
    --reference-set tools/samples/grand-piano \
    --name grand-piano \
    --budget 5000 \
    --patience 500 \
    --workers 8 \
    --work-dir work/grand-piano-chromatic
```

The `--reference-set` flag points to a directory containing:

1. **`note_map.json`** -- maps note names to frequencies and WAV filenames.
2. **WAV files** -- one per note, recorded at the specified pitch.

## note\_map.json format

Two formats are accepted:

**Array format** (canonical):

```json
[
    {"note": "C4", "freq_hz": 261.63, "wav": "piano-C4.wav"},
    {"note": "D4", "freq_hz": 293.66, "wav": "piano-D4.wav"}
]
```

**Dict format** (as produced by sample download scripts):

```json
{
    "C4": {"freq_hz": 261.63, "file": "piano-C4.wav"},
    "D4": {"freq_hz": 293.66, "file": "piano-D4.wav"}
}
```

WAV paths are resolved relative to the directory containing `note_map.json`.

## Reference sample requirements

- All WAV files should be recordings of the **same instrument** at different
  pitches, with consistent dynamics (e.g., all fortissimo or all mezzo-forte).
- The pipeline resamples to 44100 Hz internally.  Any sample rate is accepted.
- Mono or stereo (stereo is mixed to mono automatically).
- Spacing: minor-third intervals (every 3 semitones) across 2 octaves gives
  good coverage with 9 notes.  Closer spacing is fine but increases
  optimization time linearly.

## Volume register click fix (V4)

When the SID renderer starts playback, it sets the volume register ($D418)
from 0 to 15.  On real hardware (and in accurate emulators like reSID), this
causes a **DAC transient** -- a sharp click at sample offset 0 -- because
the SID's audio-output DAC is directly coupled to the volume nybble.

This click is a well-known C64 technique (it's how "digi" sample playback
works), but it's unwanted in instrument renders.  Before V4, the click was
present in every render and contaminated fitness evaluation in several ways:

- **Attack detection**: the sharp transient was misidentified as part of the
  instrument's attack, distorting the ADSR envelope feature.
- **Spectral flatness**: the broadband click energy inflated flatness,
  making tonal instruments appear noisier than they are.
- **Harmonic estimation**: click energy leaked into the harmonic partial
  magnitudes, biasing the cosine-distance calculation.

### The fix

`render_pyresid()` now inserts a **1-frame pre-roll** before the gate opens:
the volume register is set to 15, the emulator is clocked for one PAL frame
(~19656 cycles), and those samples are discarded.  By the time the gate
opens, the DAC has settled and the output is click-free.

See `tools/sidmatch/render.py` for the implementation.

### Impact on optimization

With the click removed, re-optimization (V3 -> V4) found different parameter
strategies for grand piano, particularly on the 6581 where the click had
the largest effect.  See `instruments/grand-piano/README.md` for details.

## Implementation

- `tools/sidmatch/multi_note.py` -- `ReferenceSet` loader, `multi_note_fitness()`.
- `tools/sidmatch/optimize.py` -- `MultiNoteOptimizer` (CMA-ES wrapper using
  `multi_note_fitness` as the objective).
- `tools/sidmatch/grid_search.py` -- `grid_search_multi_note()` (discrete
  screening against the full reference set).
- `tools/sidmatch/cli.py` -- `--reference-set` argument and multi-note match
  dispatch.
