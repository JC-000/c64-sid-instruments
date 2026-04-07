# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

Optimized using **multi-note chromatic fitting** (9 pitches, C3-C5) with the
**V4 click-free renderer** (volume register pre-roll fix).

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.4194 | 0.4621 |
| **Version** | 4 | 4 |

Fitness scores are multi-note aggregated distances across 9 chromatic pitches
(C3-C5).  Lower is better.  See `docs/multi-note-fitting.md` for details.

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 12 |
| decay | 6 |
| sustain | 9 |
| release | 10 |
| pulse_width | 278 |
| pw_start | 278 |
| pw_delta | 50 |
| pw_mode | sweep |
| filter_cutoff | 154 |
| filter_cutoff_start | 154 |
| filter_cutoff_end | 320 |
| filter_sweep_frames | 44 |
| filter_resonance | 11 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | (none) |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | True |
| gate_frames | 65 |
| release_frames | 80 |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 12 |
| decay | 6 |
| sustain | 7 |
| release | 8 |
| pulse_width | 900 |
| pw_start | 900 |
| pw_delta | -1 |
| pw_mode | sweep |
| filter_cutoff | 426 |
| filter_cutoff_start | 426 |
| filter_cutoff_end | 166 |
| filter_sweep_frames | 18 |
| filter_resonance | 4 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | False |
| gate_frames | 65 |
| release_frames | 20 |
| volume | 15 |

## V4 changes (click fix)

The V3 renders suffered from a **volume register click** -- a DAC transient
caused by the SID's volume register jumping from 0 to 15 at the start of
each render.  This click contaminated fitness evaluation (distorting attack
detection, inflating spectral flatness, biasing harmonic estimates) and
produced audible artifacts.

The V4 pipeline adds a **1-frame pre-roll** in `render_pyresid()`: volume is
set to 15 one PAL frame before the gate opens, giving the DAC time to settle.
The pre-roll samples are discarded from the output.

With the click removed, re-optimization found different parameter strategies:

- **6581**: Shifted from short-gate/long-release (10/155 frames in V3) to
  balanced gate/release (65/80 frames).  Now uses test bit for attack
  transient.  Lower filter resonance (11 vs 15).
- **8580**: Wider filter sweep (426->166 vs nearly flat in V3).  Shorter
  release (20 vs 125 frames).

## Tags

`grand-piano`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
| `sid_render.wav` | Rendered audio (click-free) |
