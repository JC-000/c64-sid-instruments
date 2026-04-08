# Grand Piano (SID Instrument)

A SID chip instrument patch: grand-piano.

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.4658 | 0.4720 |
| **Version** | 7 | 8 |

## Optimization Notes

**v5 (2026-04-07):** Re-optimized with `--max-attack 8` to constrain ADSR attack
to percussive values (≤100ms). The previous v4 optimization after the click fix
had converged on attack=12 (1000ms) for both chips, producing an unnatural
muffled onset with rising volume. Constraining the attack to ≤8 (≤100ms) yields
a fast, piano-appropriate transient (6581: 24ms, 8580: 16ms) with only a small
fitness trade-off.

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
| `params.json` | Machine-readable SID parameters |
| `raw.asm` | ACME-includable assembly tables |
| `goattracker.ins` | GoatTracker 2.x instrument binary |
