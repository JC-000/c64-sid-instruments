# Grand Piano (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of a grand piano,
optimized against the Salamander Grand Piano V3 C4 fortissimo sample.

## Source and Target

| | |
|---|---|
| **Source instrument** | Salamander Grand Piano V3, C4 fortissimo (CC-BY 3.0, Alexander Holm) |
| **Target SID model** | MOS 6581 |

## Tags

`piano`, `keyboard`, `percussive`, `pulse`, `lowpass`

## Winning Parameters

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

## Fitness

- **Final fitness: 0.4369** (weighted multi-feature distance)
- Evaluations: 2068 (converged via patience at 600)
- Grid search explored 24 waveform/filter combinations; pulse+LP won at 0.3667
- Full CMA-ES refinement lowered to 0.4369

## Spectral Comparison

The SID pulse wave with lowpass filtering at cutoff 310 and resonance 10
produces a dark, muffled tone that captures the piano's fundamental and lower
partials. The aggressive LP filter rolls off the upper harmonics, mimicking
the damped quality of a piano's struck string. The slow attack (11) and
long decay (11) approximate the piano's percussive onset and sustained ring,
though the SID's discrete ADSR steps produce a noticeably different envelope
shape than a real piano's continuous amplitude curve.

Key differences from a real piano:
- No inharmonicity (SID partials are perfectly harmonic)
- Simpler spectral evolution (no per-partial decay rates)
- Coarser amplitude envelope (16 discrete ADSR levels)
- No sympathetic resonance or pedal effects

## Files

- `raw.asm` - ACME assembler include (verified with `acme`)
- `goattracker.ins` - GoatTracker 2.x instrument file (GTI5 format)
- `params.json` - Machine-readable SID parameters
- `sid_render.wav` - pyresidfp render of the winning patch (2s, 44.1kHz)

## Attribution

Reference sample: **Salamander Grand Piano V3** by Alexander Holm,
licensed under [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The SID instrument parameters and encoded files in this directory are a
new derived work produced by algorithmic optimization (CMA-ES) against
spectral features of the reference sample. The SID render itself is an
original synthesis output and is not a copy of the sample.
