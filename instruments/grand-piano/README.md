# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | not exported | available |
| **Fitness** | --- | 0.0000 |
| **Version** | --- | 5 |

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
| volume | 15 |

## Tags

`grand-piano`

## Files

Each chip subdirectory contains:

| File | Description |
|---|---|
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
