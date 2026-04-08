# Violin (SID Instrument)

A SID chip instrument patch: violin.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.0000 | 0.0000 |
| **Version** | 1 | 1 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 1 |
| decay | 6 |
| sustain | 4 |
| release | 6 |
| pulse_width | 3359 |
| pw_start | 3359 |
| pw_delta | -43 |
| pw_mode | sweep |
| filter_cutoff | 44 |
| filter_cutoff_start | 44 |
| filter_cutoff_end | 44 |
| filter_sweep_frames | 50 |
| filter_resonance | 8 |
| filter_mode | off |
| filter_voice1 | False |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | True |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 8 |
| decay | 4 |
| sustain | 15 |
| release | 1 |
| pulse_width | 1185 |
| pw_start | 1185 |
| pw_delta | 21 |
| pw_mode | sweep |
| filter_cutoff | 44 |
| filter_cutoff_start | 44 |
| filter_cutoff_end | 44 |
| filter_sweep_frames | 50 |
| filter_resonance | 8 |
| filter_mode | off |
| filter_voice1 | False |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 4 |
| wt_use_test_bit | True |
| volume | 15 |

## Tags

`violin`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `violin-<chip>-params.json` | Machine-readable SID parameters |
| `violin-<chip>.asm` | ACME-includable assembly tables |
| `violin-<chip>.ins` | GoatTracker 2.x instrument binary |
| `violin-<chip>-scale.wav` | SID patch rendered at each reference note |

Top-level files:

| File | Description |
|---|---|
| `violin-reference-scale.wav` | Concatenated reference samples for comparison |
