# Acoustic Guitar (SID Instrument)

A SID chip instrument patch: acoustic-guitar.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.0000 | 0.0000 |
| **Version** | 4 | 5 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 3 |
| decay | 8 |
| sustain | 12 |
| release | 12 |
| pulse_width | 3211 |
| pw_start | 3211 |
| pw_delta | 38 |
| pw_mode | sweep |
| filter_cutoff | 1010 |
| filter_cutoff_start | 1010 |
| filter_cutoff_end | 300 |
| filter_sweep_frames | 8 |
| filter_resonance | 4 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | saw+triangle |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | True |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 8 |
| decay | 3 |
| sustain | 15 |
| release | 12 |
| pulse_width | 2245 |
| pw_start | 2245 |
| pw_delta | -26 |
| pw_mode | sweep |
| filter_cutoff | 187 |
| filter_cutoff_start | 187 |
| filter_cutoff_end | 50 |
| filter_sweep_frames | 100 |
| filter_resonance | 0 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | saw+triangle |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | False |
| volume | 15 |

## Tags

`acoustic-guitar`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `acoustic-guitar-<chip>-params.json` | Machine-readable SID parameters |
| `acoustic-guitar-<chip>.asm` | ACME-includable assembly tables |
| `acoustic-guitar-<chip>.ins` | GoatTracker 2.x instrument binary |
| `acoustic-guitar-<chip>-scale.wav` | SID patch rendered at each reference note |

Top-level files:

| File | Description |
|---|---|
| `acoustic-guitar-reference-scale.wav` | Concatenated reference samples for comparison |
