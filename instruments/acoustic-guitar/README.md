# Acoustic Guitar (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of an acoustic
guitar, optimized against the Philharmonia Orchestra E4 forte sample.

Optimized variants are provided for both the MOS 6581 and MOS 8580 SID chips.

## Source and Target

| | |
|---|---|
| **Source instrument** | Philharmonia Orchestra, acoustic guitar E4 forte (CC-BY-SA 3.0) |

## Chip Variants

### MOS 6581

| Parameter        | Value           |
|------------------|-----------------|
| Waveform         | saw             |
| Attack           | 7               |
| Decay            | 11              |
| Sustain          | 3               |
| Release          | 15              |
| Pulse Width      | 942             |
| Filter Mode      | bandpass        |
| Filter Cutoff    | 84              |
| Filter Resonance | 11 (of 15)      |
| Frequency        | 329.63 Hz (E4)  |
| **Fitness**      | **0.2764**      |

### MOS 8580

| Parameter        | Value           |
|------------------|-----------------|
| Waveform         | pulse           |
| Attack           | 5               |
| Decay            | 15              |
| Sustain          | 7               |
| Release          | 7               |
| Pulse Width      | 1431            |
| PW Modulation    | 4-breakpoint table (1448 -> 814 -> 3274 -> 287) |
| Filter Mode      | bandpass        |
| Filter Cutoff    | 65              |
| Filter Resonance | 0 (of 15)       |
| Frequency        | 329.63 Hz (E4)  |
| **Fitness**      | **0.3512**      |

## Tags

`acoustic-guitar`, `plucked`, `string`

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

## Attribution

Reference sample: **Philharmonia Orchestra** acoustic guitar samples,
licensed under [CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
The SID instrument parameters and encoded files in this directory are a
new derived work produced by algorithmic optimization (CMA-ES) against
spectral features of the reference sample.
