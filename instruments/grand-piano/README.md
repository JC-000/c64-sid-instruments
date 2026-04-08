# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

Optimized with the three-phase pipeline (grid screening + top-K refinement)
using the TPE (Tree-structured Parzen Estimator) optimizer. Multi-note
chromatic evaluation across C3--C5 (9 pitches).

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.4310 | 0.4884 |
| **Version** | 12 | 13 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 0 |
| decay | 0 |
| sustain | 14 |
| release | 12 |
| pulse_width | 2048 |
| pw_start | 2048 |
| pw_delta | 0 |
| pw_mode | sweep |
| filter_cutoff | 44 |
| filter_cutoff_start | 44 |
| filter_cutoff_end | 44 |
| filter_sweep_frames | 50 |
| filter_resonance | 8 |
| filter_mode | off |
| filter_voice1 | False |
| wt_attack_waveform | --- |
| wt_sustain_waveform | saw |
| wt_attack_frames | 2 |
| wt_use_test_bit | False |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 8 |
| decay | 9 |
| sustain | 12 |
| release | 11 |
| pulse_width | 1445 |
| pw_start | 1445 |
| pw_delta | -37 |
| pw_mode | sweep |
| filter_cutoff | 510 |
| filter_cutoff_start | 510 |
| filter_cutoff_end | 25 |
| filter_sweep_frames | 26 |
| filter_resonance | 0 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 1 |
| wt_use_test_bit | True |
| volume | 15 |

## Tags

`grand-piano`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `grand-piano-<chip>-params.json` | Machine-readable SID parameters |
| `grand-piano-<chip>.asm` | ACME-includable assembly tables |
| `grand-piano-<chip>.ins` | GoatTracker 2.x instrument binary |
| `grand-piano-<chip>-scale.wav` | SID patch rendered at each reference note |

Top-level files:

| File | Description |
|---|---|
| `grand-piano-reference-scale.wav` | Concatenated reference samples for comparison |
