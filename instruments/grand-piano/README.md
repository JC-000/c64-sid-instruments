# Grand Piano (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of a grand piano,
optimized against the Salamander Grand Piano V3 C4 fortissimo sample.

Optimized variants are provided for both the MOS 6581 and MOS 8580 SID chips.

## Source and Target

| | |
|---|---|
| **Source instrument** | Salamander Grand Piano V3, C4 fortissimo (CC-BY 3.0, Alexander Holm) |

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Fitness** | 0.2593 | 0.2534 |
| **Version** | v3 (pipeline v3) | v3 (pipeline v3) |

### MOS 6581

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | pulse           |
| Attack Waveform  | pulse+saw       |
| Test Bit         | yes (osc reset) |
| Attack           | 9 (250 ms)      |
| Decay            | 10 (1500 ms)    |
| Sustain          | 1               |
| Release          | 6 (204 ms)      |
| PW Start         | 1977            |
| PW Sweep         | -13/frame (sweep down, clamped 2791-2854) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 158 -> 536 over 98 frames (sweep up) |
| Filter Resonance | 15 (of 15)      |
| Frequency        | 261.63 Hz (C4)  |
| Gate / Release   | 92 / 15 frames  |
| **Fitness**      | **0.2593**      |

### MOS 8580

| Parameter        | Value           |
|------------------|-----------------|
| Sustain Waveform | pulse           |
| Attack Waveform  | pulse+saw       |
| Test Bit         | yes (osc reset) |
| Attack           | 1 (8 ms)        |
| Decay            | 6 (168 ms)      |
| Sustain          | 14              |
| Release          | 10 (1500 ms)    |
| PW Start         | 672             |
| PW Sweep         | +41/frame (sweep up, clamped 370-1300) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 63 -> 320 over 100 frames (sweep up) |
| Filter Resonance | 15 (of 15)      |
| Frequency        | 261.63 Hz (C4)  |
| Gate / Release   | 15 / 80 frames  |
| **Fitness**      | **0.2534**      |

## Tags

`piano`, `keyboard`, `percussive`

## Pipeline

Generated with the v3 tracker-style pipeline featuring:
- Wavetable sequences (test bit reset + attack waveform + sustain waveform)
- Per-frame PW sweep
- Per-frame filter cutoff sweep
- ADSR-aware gate/release frame computation

## Files

```
grand-piano/
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

## Attribution

Reference sample: **Salamander Grand Piano V3** by Alexander Holm,
licensed under [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The SID instrument parameters and encoded files in this directory are a
new derived work produced by algorithmic optimization (CMA-ES) against
spectral features of the reference sample. The SID render itself is an
original synthesis output and is not a copy of the sample.
