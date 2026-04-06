# Grand Piano (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of a grand piano,
optimized against the Salamander Grand Piano V3 C4 fortissimo sample.

Optimized variants are provided for both the MOS 6581 and MOS 8580 SID chips.

## Source and Target

| | |
|---|---|
| **Source instrument** | Salamander Grand Piano V3, C4 fortissimo (CC-BY 3.0, Alexander Holm) |

## Chip Variants

### MOS 6581

| Parameter        | Value           |
|------------------|-----------------|
| Waveform         | pulse           |
| Attack           | 11              |
| Decay            | 11              |
| Sustain          | 12              |
| Release          | 5               |
| Pulse Width      | 1528            |
| PW Modulation    | 4-breakpoint table (959 -> 1088 -> 1024 -> 3619) |
| Filter Mode      | lowpass         |
| Filter Cutoff    | 310 (of 2047)   |
| Filter Resonance | 10 (of 15)      |
| Frequency        | 261.63 Hz (C4)  |
| **Fitness**      | **0.4369**      |

### MOS 8580

| Parameter        | Value           |
|------------------|-----------------|
| Waveform         | saw             |
| Attack           | 0               |
| Decay            | 6               |
| Sustain          | 15              |
| Release          | 7               |
| Pulse Width      | 141             |
| Filter Mode      | bandpass        |
| Filter Cutoff    | 72              |
| Filter Resonance | 15 (of 15)      |
| Frequency        | 261.63 Hz (C4)  |
| **Fitness**      | **0.3428**      |

## Tags

`piano`, `keyboard`, `percussive`

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
