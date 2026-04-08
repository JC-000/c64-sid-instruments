# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.0000 | 0.0000 |
| **Version** | 10 | 11 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 10 |
| decay | 3 |
| sustain | 9 |
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
| wt_attack_waveform | noise |
| wt_sustain_waveform | saw |
| wt_attack_frames | 2 |
| wt_use_test_bit | False |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 3 |
| decay | 9 |
| sustain | 6 |
| release | 2 |
| pulse_width | 719 |
| pw_start | 719 |
| pw_delta | -31 |
| pw_mode | sweep |
| filter_cutoff | 59 |
| filter_cutoff_start | 59 |
| filter_cutoff_end | 424 |
| filter_sweep_frames | 45 |
| filter_resonance | 15 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | False |
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
