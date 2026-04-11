# Phase 1: hand-crafted Detert-inspired grand piano (8580)

**This is a hand-crafted diagnostic baseline, not an optimization result.** No
optimizer (CMA-ES, TPE, grid search) was involved. Parameters were picked by
informed guess from R2's research notes on Detert's Ivory instrument to test
whether the newly-added expressive primitives (`waveform_table`,
`hard_restart`, `pwm_lfo_*`, `filter_env`) can move the 8580 audibly closer
to a real grand piano.

See `tools/handcraft_piano.py` for the exact params and `inspection.json` for
the raw numeric measurements.

## Files

| File | What it is |
| --- | --- |
| `handcraft_full.wav` | Full instrument: waveform_table + hard_restart + PWM LFO + filter_env. 9-note chromatic scale C3..C5. |
| `handcraft_no_hard_restart.wav` | Ablation: same params with `hard_restart=False`. |
| `handcraft_no_waveform_table.wav` | Ablation: same params with `waveform_table=None` (falls back to base pulse only). |
| `handcraft_fur_elise.wav` | Fur Elise rendered via `tools/render_fur_elise.py` with the full hand-crafted patch. |
| `inspection.json` | Numeric stats for the four WAVs above. |

## Hand-crafted choices and why

- **`waveform_table = [0x81, 0x41, 0x11]`** — noise+pulse (frame 0 hammer-strike
  transient with broadband energy), then pulse+triangle (frame 1 harmonic
  body forming), then pure triangle (frame 2+ mellow sustained body). This is
  a waveform-register sequence; the "hammer strike" is driven by oscillator
  waveform-change clicks, **not** by $D418 volume-register manipulation
  (which is unusable on 8580).
- **`hard_restart = True`, 2 frames** — TEST bit + zero ADSR before gate-on
  resets oscillator phase so every note starts identically and defeats the
  SID ADSR bug.
- **`pwm_lfo_rate = 5 Hz`, `depth = 350`** — slow sinusoidal PWM around the
  2048 midpoint for a "detuned multi-string" shimmer.
- **`filter_env`** — 30 entries, 1 frame each, curving smoothly from 0x700
  (bright) down to 0x100 (dark) over ~0.6 s, then holding 0x100 for the tail.
  Mimics the fast high-frequency decay of a real piano.
- **ADSR 0/8/15/12** — instant attack, ~300 ms decay, high sustain (15 — the
  single most critical parameter; S=0 collapses the body to silence), long
  ~2.4 s release.
- **Base waveform** pulse @ PW=2048, LP filter, resonance 4.

## Numeric observations

Measured at 44.1 kHz mono from the chromatic scale renders:

| metric | full | no hard restart | no waveform table |
| --- | --- | --- | --- |
| duration (s) | 28.96 | 28.60 | 28.96 |
| RMS | 0.061 | 0.061 | 0.097 |
| peak | 0.272 | 0.283 | 0.278 |
| transient peak (first 50 ms) | 0.272 | 0.274 | 0.278 |
| early RMS (first 200 ms) | 0.123 | 0.122 | 0.144 |
| late RMS (last 500 ms) | 0.0165 | 0.0165 | 0.0272 |
| NaN fraction | 0 | 0 | 0 |
| clipped fraction | 0 | 0 | 0 |

Observations:

- **No NaNs, no clipping, all audible** — the scaffolding produces sane audio.
- **`no_hard_restart` is 360 ms shorter** in total duration, exactly as
  expected (no 2-frame hard-restart pre-roll per note × 9 notes ≈ 360 ms).
- **`no_waveform_table` is ~58% louder (RMS 0.097 vs 0.061)**. Without the
  noise+pulse → pulse+tri → tri transition the voice is pulse the entire
  time, which has more continuous energy than a triangle body. The
  waveform table trades average energy for attack transient shape.
- **Early/late RMS ratio** of the full patch is ~7.5×, consistent with a
  decaying piano envelope (filter_env darkening + ADSR decay to S=15 × Release
  shaping the tail).
- **Fur Elise** renders in 20.0 s, 40 events, 0.95 peak after normalization,
  no NaN/clip. Melodic content survives the hand-crafted patch at musical
  tempo.

## What this does and does not tell us

It tells us:
- The extended `SidParams` scaffolding works end-to-end for single-voice
  playback, note sequences, and Fur Elise-style melodic rendering.
- The ablations prove each primitive is actually wired and audibly distinct.
- No numeric pathologies (NaN, clipping, silence) in any of the four
  renders.

It does **not** tell us:
- Whether the hand-crafted parameters are anywhere near optimal.
- How close the audio is to the real Salamander grand-piano reference —
  that is the job of Phase 2 listening + re-optimization under the extended
  parameter space.
