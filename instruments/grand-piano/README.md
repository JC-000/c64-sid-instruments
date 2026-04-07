# Grand Piano (SID Instrument)

A Commodore 64 SID chip instrument approximating the timbre of a grand piano,
optimized against the Salamander Grand Piano V3 across a 9-note chromatic
range (C3--C5) using the multi-note evaluation pipeline.

Both MOS 6581 and MOS 8580 variants are provided.

## Source and Target

| | |
|---|---|
| **Source instrument** | Salamander Grand Piano V3, fortissimo samples (CC-BY 3.0, Alexander Holm) |
| **Evaluation range** | C3, Eb3, Gb3, A3, C4, Eb4, Gb4, A4, C5 (9 notes at minor-third intervals) |
| **Pipeline** | v3 tracker-style + multi-note chromatic fitting |

## Chip Variants

| | 6581 | 8580 |
|---|---|---|
| **Status** | available | available |
| **Version** | v3 | v4 |

### MOS 6581

| Parameter | Value |
|---|---|
| Sustain Waveform | saw |
| Attack Waveform | pulse+saw |
| Attack Frames | 1 |
| Test Bit | no |
| Attack | 5 |
| Decay | 1 |
| Sustain | 15 |
| Release | 12 |
| PW Start | 530 |
| PW Sweep | -13/frame (clamped 2605--3462) |
| Filter Mode | lowpass |
| Filter Cutoff | 78 -> 305 over 42 frames |
| Filter Resonance | 15 |
| Gate / Release | 10 / 155 frames |

### MOS 8580

| Parameter | Value |
|---|---|
| Sustain Waveform | saw |
| Attack Waveform | pulse+saw |
| Attack Frames | 3 |
| Test Bit | yes (osc reset) |
| Attack | 9 |
| Decay | 5 |
| Sustain | 15 |
| Release | 11 |
| PW Start | 3324 |
| PW Sweep | -23/frame (clamped 334--1061) |
| Filter Mode | lowpass |
| Filter Cutoff | 166 -> 157 over 40 frames |
| Filter Resonance | 6 |
| Gate / Release | 25 / 125 frames |

## Multi-note Optimization

Previous versions optimized against a single C4 reference sample.  This
version uses the **multi-note chromatic fitting** pipeline: the optimizer
evaluates each candidate patch at all 9 reference pitches and minimizes an
aggregated fitness score:

    (1 - alpha) * mean(distances) + alpha * max(distances)

with `alpha = 0.15`.  This penalizes patches that work well at one pitch
but break at others, producing instruments that track correctly across the
keyboard.

### Encoder fixes

The wavetable command bytes in both GoatTracker and raw\_asm encoders were
previously hardcoded to values that overrode the tracker's pitch control
(`$80` in GoatTracker, frame counter in raw\_asm).  This caused every note
to sound at the same pitch regardless of the tracker's frequency setting.
Both encoders now emit `$00` (no pitch change), allowing the tracker/player
to control the note via the SID frequency registers.

## Tags

`piano`, `keyboard`, `percussive`

## Pipeline

Generated with the v3 tracker-style pipeline featuring:
- Wavetable sequences (test bit reset + attack waveform + sustain waveform)
- Per-frame PW sweep
- Per-frame filter cutoff sweep
- ADSR-aware gate/release frame computation
- Multi-note chromatic scale evaluation (9 pitches, C3--C5)

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
spectral features of the reference samples.  The SID renders are original
synthesis outputs and are not copies of the samples.
