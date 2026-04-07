# Acoustic Guitar (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of an
acoustic guitar, optimized against reference samples from the
Philharmonia Orchestra acoustic guitar forte normal collection.

Optimized variants are provided for both the MOS 6581 and MOS 8580 SID chips.

## Source and Target

| | |
|---|---|
| **Source instrument** | Philharmonia Orchestra acoustic guitar forte normal |
| **Pipeline** | v4 multi-note chromatic fitting |
| **Reference notes** | 10 notes, E2 through G4 (chromatic subset) |

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.6767 | 0.6985 |
| **Version** | v3 | v4 |

**Note on fitness scores:** The v4 multi-note chromatic pipeline optimizes a
single parameter set across 10 reference pitches simultaneously (E2, G2, Bb2,
Db3, E3, G3, Bb3, Db4, E4, G4). This is a much harder optimization target than
the previous single-note approach, so the aggregate fitness values (0.6767 /
0.6985) are higher (worse) than the old single-note scores (0.29 / 0.29). The
trade-off is that the instrument now sounds correct across the full playable
range rather than being over-fitted to a single pitch.

### MOS 6581

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | saw             |
| Attack Waveform  | saw+triangle    |
| Test Bit         | yes (osc reset) |
| Attack           | 3 (16 ms)       |
| Decay            | 8 (600 ms)      |
| Sustain          | 12              |
| Release          | 12 (2.4 s)      |
| PW Start         | 3211            |
| PW Sweep         | +38/frame (sweep up, clamped) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 1010 -> 300 over 8 frames (sweep down) |
| Filter Resonance | 4 (of 15)       |
| **Fitness**      | **0.6767**      |

### MOS 8580

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | saw             |
| Attack Waveform  | saw+triangle    |
| Test Bit         | no              |
| Attack           | 8 (100 ms)      |
| Decay            | 3 (16 ms)       |
| Sustain          | 15              |
| Release          | 12 (2.4 s)      |
| PW Start         | 2245            |
| PW Sweep         | -26/frame (sweep down, clamped) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 187 -> 50 over 100 frames (sweep down) |
| Filter Resonance | 0 (of 15)       |
| **Fitness**      | **0.6985**      |

## Tags

`acoustic-guitar`

## Pipeline

Generated with the v4 multi-note chromatic fitting pipeline featuring:
- Simultaneous optimization across 10 reference notes (E2-G4)
- Wavetable sequences (test bit reset + saw+triangle attack + saw sustain)
- Per-frame PW sweep
- Per-frame filter cutoff sweep
- ADSR-aware gate/release frame computation
- Both chips converged on saw waveform with saw+triangle attack and lowpass filter

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
