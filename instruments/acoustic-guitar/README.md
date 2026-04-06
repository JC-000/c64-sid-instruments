# Acoustic Guitar (SID Instrument)

A SID chip instrument patch: acoustic-guitar.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.2944 | 0.2867 |
| **Version** | 2 | 3 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | pulse |
| attack | 4 |
| decay | 9 |
| sustain | 10 |
| release | 4 |
| pulse_width | 3810 |
| pw_start | 3810 |
| pw_delta | -24 |
| pw_mode | sweep |
| filter_cutoff | 383 |
| filter_cutoff_start | 383 |
| filter_cutoff_end | 390 |
| filter_sweep_frames | 65 |
| filter_resonance | 4 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | None |
| wt_sustain_waveform | pulse |
| wt_attack_frames | 2 |
| wt_use_test_bit | False |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | pulse |
| attack | 0 |
| decay | 9 |
| sustain | 7 |
| release | 5 |
| pulse_width | 2747 |
| pw_start | 2747 |
| pw_delta | 10 |
| pw_mode | sweep |
| filter_cutoff | 287 |
| filter_cutoff_start | 287 |
| filter_cutoff_end | 456 |
| filter_sweep_frames | 99 |
| filter_resonance | 0 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | None |
| wt_sustain_waveform | pulse |
| wt_attack_frames | 4 |
| wt_use_test_bit | True |
| volume | 15 |

## Tags

`acoustic-guitar`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
