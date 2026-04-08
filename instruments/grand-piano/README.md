# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.0000 | 0.0000 |
| **Version** | 9 | 10 |

### 6581 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 0 |
| decay | 0 |
| sustain | 4 |
| release | 10 |
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
| wt_attack_waveform | None |
| wt_sustain_waveform | saw |
| wt_attack_frames | 5 |
| wt_use_test_bit | False |
| volume | 15 |

### 8580 Parameters

| Parameter | Value |
|---|---|
| waveform | saw |
| attack | 1 |
| decay | 9 |
| sustain | 6 |
| release | 3 |
| pulse_width | 2429 |
| pw_start | 2429 |
| pw_delta | 1 |
| pw_mode | sweep |
| filter_cutoff | 2035 |
| filter_cutoff_start | 2035 |
| filter_cutoff_end | 291 |
| filter_sweep_frames | 43 |
| filter_resonance | 15 |
| filter_mode | lp |
| filter_voice1 | True |
| wt_attack_waveform | pulse+saw |
| wt_sustain_waveform | saw |
| wt_attack_frames | 2 |
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
