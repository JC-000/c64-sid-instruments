# Acoustic Guitar (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of an
acoustic guitar, optimized against a nylon-string guitar reference sample.

Optimized variants are provided for both the MOS 6581 and MOS 8580 SID chips.

## Source and Target

| | |
|---|---|
| **Source instrument** | Acoustic guitar reference sample |

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.2944 | 0.2867 |
| **Version** | v3 (pipeline v3) | v3 (pipeline v3) |

### MOS 6581

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | pulse           |
| Attack Waveform  | (same as sustain) |
| Test Bit         | no              |
| Attack           | 4 (38 ms)       |
| Decay            | 9 (750 ms)      |
| Sustain          | 10              |
| Release          | 4 (114 ms)      |
| PW Start         | 3810            |
| PW Sweep         | -24/frame (sweep down, clamped) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 383 -> 390 over 65 frames (sweep up) |
| Filter Resonance | 4 (of 15)       |
| **Fitness**      | **0.2944**      |

### MOS 8580

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | pulse           |
| Attack Waveform  | (same as sustain) |
| Test Bit         | yes (osc reset) |
| Attack           | 0 (2 ms)        |
| Decay            | 9 (750 ms)      |
| Sustain          | 7               |
| Release          | 5 (168 ms)      |
| PW Start         | 2747            |
| PW Sweep         | +10/frame (sweep up, clamped) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 287 -> 456 over 99 frames (sweep up) |
| Filter Resonance | 0 (of 15)       |
| **Fitness**      | **0.2867**      |

## Tags

`acoustic-guitar`

## Pipeline

Generated with the v3 tracker-style pipeline featuring:
- Wavetable sequences (test bit reset + attack waveform + sustain waveform)
- Per-frame PW sweep
- Per-frame filter cutoff sweep
- ADSR-aware gate/release frame computation

## Files

```
acoustic-guitar/
  6581/
    params.json       - Machine-readable SID parameters (6581)
    raw.asm           - ACME assembler include (6581)
    goattracker.ins   - GoatTracker 2.x instrument file (6581)
    sid_render.wav    - pyresidfp render (6581)
  8580/
    params.json       - Machine-readable SID parameters (8580)
    raw.asm           - ACME assembler include (8580)
    goattracker.ins   - GoatTracker 2.x instrument file (8580)
    sid_render.wav    - pyresidfp render (8580)
```
