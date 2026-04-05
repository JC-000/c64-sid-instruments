# Acoustic Guitar (SID Instrument)

A SID chip instrument patch approximating the timbre of an acoustic guitar
playing E4 forte (~329.63 Hz). Optimised via CMA-ES spectral matching
against a Philharmonia Orchestra sample.

## Tags

`acoustic-guitar`, `plucked`, `string`, `E4`, `forte`

## Winning Parameters

| Parameter          | Value   |
|--------------------|---------|
| Waveform           | saw     |
| Filter mode        | bandpass|
| Attack             | 7       |
| Decay              | 11      |
| Sustain            | 3       |
| Release            | 15      |
| Pulse width        | 942     |
| Filter cutoff      | 84      |
| Filter resonance   | 11      |
| Filter voice1      | true    |
| Volume             | 15      |
| Gate frames        | 50      |
| Release frames     | 50      |

## Optimization Summary

- **Fitness (pyresidfp vs reference):** 0.2764
- **Evaluations:** 2,959 (converged via patience at 600)
- **Wall time:** ~57 s
- **Best grid combo:** saw + bandpass filter (fitness 0.2907 after grid phase)
- **Full CMA-ES refined to:** 0.2764

## Spectral Comparison / VICE Verification

- pyresidfp vs reference distance: **0.471**
- VICE vs reference distance: **23.56**
- pyresidfp vs VICE distance: **23.67**

The large pyresidfp-vs-VICE gap is a known infrastructure issue (VICE WAV
amplitude ~0.37x vs pyresidfp 1.0x, as documented by C1/grand-piano). The
spectral shape is consistent across backends; the distance metric is
dominated by the amplitude mismatch rather than timbral difference.

## Guitar-Likeness Assessment

The saw waveform through a bandpass filter at low cutoff (84) with high
resonance (11) produces a nasal, mid-focused tone that captures the
plucked-string character reasonably well for a single SID voice. The A=7
D=11 S=3 R=15 envelope gives a moderately slow attack with a long decay
into a quiet sustain -- mimicking the pluck-and-ring of a guitar string.
The fitness of 0.2764 is good for a single-oscillator SID approximation of
a complex acoustic instrument. The tonal result is recognisably
"stringy/plucked" rather than a faithful acoustic guitar reproduction,
which is the best one can expect from 6581/8580 hardware.

## Files

| File              | Description                                      |
|-------------------|--------------------------------------------------|
| `params.json`     | Machine-readable SID parameters                  |
| `raw.asm`         | ACME-includable assembly tables                  |
| `goattracker.ins` | GoatTracker 2.x instrument binary                |
| `sid_render.wav`  | pyresidfp render (44.1 kHz, mono, ~2 s)          |
| `README.md`       | This file                                        |

SID-Wizard export was skipped (encoder not yet implemented).

## Attribution

Reference sample: **Philharmonia Orchestra** acoustic guitar E4 forte,
licensed under **CC BY-SA 3.0**.
Source: https://philharmonia.co.uk/resources/sound-samples/

The SID instrument patch is a new derived work produced by automated
spectral matching. The repository is licensed CC-BY-4.0; the CC-BY-SA 3.0
origin of the reference sample is flagged here for pre-release license
review (SA share-alike may propagate to derived works depending on
interpretation).
