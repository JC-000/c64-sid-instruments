# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.4658 | 0.4720 |
| **Version** | 8 | 9 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 3 |
| decay | 7 |
| sustain | 15 |
| release | 12 |
| pulse_width | 664 |
| pw_start | 664 |
| pw_delta | 15 |
| pw_mode | sweep |
| filter_cutoff | 143 |
| filter_cutoff_start | 143 |
| filter_cutoff_end | 239 |
| filter_sweep_frames | 39 |
| filter_resonance | 12 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | saw+triangle |
| wt_sustain_waveform | saw |
| wt_attack_frames | 1 |
| wt_use_test_bit | True |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 2 |
| decay | 6 |
| sustain | 15 |
| release | 12 |
| pulse_width | 4033 |
| pw_start | 4033 |
| pw_delta | -48 |
| pw_mode | sweep |
| filter_cutoff | 210 |
| filter_cutoff_start | 210 |
| filter_cutoff_end | 153 |
| filter_sweep_frames | 90 |
| filter_resonance | 3 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
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
