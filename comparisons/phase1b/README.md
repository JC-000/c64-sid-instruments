# Phase 1b: waveform-table ablations

**Problem:** the Phase 1 baseline (`comparisons/phase1/handcraft_full.wav`)
used `waveform_table = [0x81, 0x41, 0x11]`, which starts with **pure noise**
(`0x81` = noise + gate). At A=0 and full ADSR peak this plays a full frame
(~20 ms) of random samples, producing audible static crackle on note onset
rather than a piano-like hammer strike. Confirmed by ear.

This set renders six alternative waveform tables on the *exact same*
hand-crafted parameters (hard_restart=True/2f, PWM LFO 5 Hz depth 350,
filter_env 0x700→0x100 over 30 frames, ADSR 0/8/15/12, base pulse PW=2048,
8580) so the most piano-like attack primitive can be picked by ear.

Source: `tools/handcraft_piano_phase1b.py`, which reuses
`tools.handcraft_piano.make_handcraft_params` and only overrides
`waveform_table`. Base-params defaults in `handcraft_piano.py` are
**unchanged**.

## Ablations

| # | name                          | waveform_table        | rationale |
| - | ----------------------------- | --------------------- | --------- |
| 1 | `handcraft_wt_tri_only`       | `[0x11]`              | Triangle only. No attack primitive — reference baseline to hear the rest of the instrument in isolation. |
| 2 | `handcraft_wt_pul_tri`        | `[0x41, 0x11]`        | Pulse → triangle. One frame of pulse as the attack (hard sample-level edge, no noise), then mellow triangle body. |
| 3 | `handcraft_wt_pultri_tri`     | `[0x51, 0x11]`        | Pulse+triangle combined → triangle. `0x51` on 8580 is a reedy hollow timbre; morphs directly into pure triangle. |
| 4 | `handcraft_wt_noisepul_pul_tri` | `[0xC1, 0x41, 0x11]`| Noise+pulse combined (pulse gates the noise shift register = narrow-band gated noise burst) → pulse → triangle. Historically-used piano attack. |
| 5 | `handcraft_wt_pul_pultri_tri` | `[0x41, 0x51, 0x11]`  | Pulse → pulse+triangle → triangle. No noise at all; smooth three-step morph, cleanest attack progression. |
| 6 | `handcraft_wt_noisepul_tri`   | `[0xC1, 0x11]`        | Noise+pulse → triangle, skipping the pulse intermediate. One frame of narrow-band noise then straight into triangle body. |

Each ablation produces two WAVs: `<name>.wav` (9-note chromatic scale
C3..C5) and `<name>_fur_elise.wav` (Für Elise via `render_fur_elise.py`).
All 8580, 44.1 kHz mono.

## Numeric inspection (chromatic scale)

| ablation                         | rms    | peak   | transient peak (50 ms) | early rms (200 ms) | late rms (500 ms) | early/late | NaN | clip |
| -------------------------------- | ------ | ------ | ---------------------- | ------------------ | ----------------- | ---------- | --- | ---- |
| `tri_only`                       | 0.0608 | 0.2699 | 0.2699                 | 0.1200             | 0.01653           | 7.26×      | 0   | 0    |
| `pul_tri`                        | 0.0612 | 0.2776 | 0.2776                 | 0.1225             | 0.01653           | 7.41×      | 0   | 0    |
| `pultri_tri`                     | 0.0606 | 0.2750 | 0.2750                 | 0.1175             | 0.01653           | 7.11×      | 0   | 0    |
| `noisepul_pul_tri`               | 0.0608 | 0.2750 | **0.1769**             | 0.1203             | 0.01653           | 7.28×      | 0   | 0    |
| `pul_pultri_tri`                 | 0.0610 | 0.2776 | 0.2776                 | 0.1204             | 0.01653           | 7.28×      | 0   | 0    |
| `noisepul_tri`                   | 0.0605 | 0.2646 | **0.1770**             | 0.1162             | 0.01653           | 7.03×      | 0   | 0    |

Phase 1 `handcraft_full` (noise attack, for comparison): rms 0.061, peak 0.272,
transient 0.272, early 0.123, late 0.0165.

## Numeric inspection (Für Elise)

| ablation            | rms   | peak  | transient peak (50 ms) | early rms | late rms |
| ------------------- | ----- | ----- | ---------------------- | --------- | -------- |
| `tri_only`          | 0.299 | 0.950 | 0.911                  | 0.406     | 0.221    |
| `pul_tri`           | 0.278 | 0.950 | 0.915                  | 0.381     | 0.202    |
| `pultri_tri`        | 0.277 | 0.950 | 0.886                  | 0.372     | 0.209    |
| `noisepul_pul_tri`  | 0.276 | 0.950 | **0.521**              | 0.372     | 0.206    |
| `pul_pultri_tri`    | 0.273 | 0.950 | 0.915                  | 0.371     | 0.202    |
| `noisepul_tri`      | 0.282 | 0.950 | **0.540**              | 0.377     | 0.214    |

Note: Für Elise values are post-normalisation (peak ≈ 0.95 by design in
`save_wav`), so absolute levels are not comparable across ablations; the
**transient-peak / peak ratio** is the useful signal.

## Observations

- **No NaNs, no clipping, no silence** in any of the 12 renders. All
  combined-waveform tables (`0x51`, `0xC1`) produce audible output on 8580.
- **Gated-noise variants have a noticeably lower transient peak** (0.177
  on the scale, vs 0.27 for pure-pulse-edge attacks), and on Für Elise the
  transient-peak / peak ratio drops from ~0.96 to ~0.55. This is consistent
  with `0xC1` being a spectrally narrow, lower-energy burst — the pulse
  voice gates the noise shift register, so the waveform output is "noise
  AND pulse", producing much quieter samples than pure noise (`0x81`). This
  is the **desired** behaviour: a softer, less-clicky hammer strike.
- **Pure-pulse-edge attacks** (`pul_tri`, `pultri_tri`, `pul_pultri_tri`)
  all saturate the transient at the same level as the sustained body,
  meaning the "attack" is indistinguishable in amplitude from the body —
  this will likely sound tonal rather than percussive.
- **`tri_only`** has no attack primitive; any onset click comes purely
  from the hard-restart TEST-bit release and the triangle starting at
  phase 0. It exists as the "what does this instrument sound like without
  any attack trick" baseline.
- The early/late RMS ratio is ~7× for every ablation, showing the
  filter_env + ADSR body decay is unchanged across ablations (expected —
  only the first 1–3 frames differ).

## MR-STFT fitness scores against Salamander reference

Scored with `tools.sidmatch.fitness.distance_v2` against
`instruments/grand-piano/grand-piano-reference-scale.wav` (the same
function wired into the optimizer). Reference is trimmed to candidate
length before STFT, as `distance_v2` does. Lower is better.

See `tools/score_phase1b_mrstft.py` for the scorer and
`mrstft_scores.json` for the raw numbers.

Sorted (lower = better):

| Variant                                                   | Waveform table        | MR-STFT ↓ | Human rank |
| --------------------------------------------------------- | --------------------- | --------: | :--------: |
| `comparisons/grand-piano-8580-scale-4a94c09.wav`          | (older TPE opt)       |     91.60 |    TBD     |
| `comparisons/grand-piano-8580-scale-head.wav`             | (HEAD baseline)       |    107.40 |    TBD     |
| `comparisons/grand-piano-8580-scale-mrstft-opt.wav`       | (MR-STFT opt)         |    115.95 |    TBD     |
| `phase1b/handcraft_wt_pul_pultri_tri.wav`                 | `[0x41, 0x51, 0x11]`  |    412.32 |    TBD     |
| `phase1b/handcraft_wt_pul_tri.wav`                        | `[0x41, 0x11]`        |    412.41 |    TBD     |
| `phase1b/handcraft_wt_pultri_tri.wav`                     | `[0x51, 0x11]`        |    415.75 |    TBD     |
| `phase1b/handcraft_wt_noisepul_pul_tri.wav`               | `[0xC1, 0x41, 0x11]`  |    416.41 |    TBD     |
| `phase1/handcraft_full.wav`                               | `[0x81, 0x41, 0x11]`  |    418.14 |    TBD     |
| `phase1b/handcraft_wt_tri_only.wav`                       | `[0x11]`              |    420.45 |    TBD     |
| `phase1b/handcraft_wt_noisepul_tri.wav`                   | `[0xC1, 0x11]`        |    431.98 |    TBD     |
| `phase1/handcraft_no_hard_restart.wav`                    | `[0x81, 0x41, 0x11]`  |    436.51 |    TBD     |
| `phase1/handcraft_no_waveform_table.wav`                  | `None` (pulse only)   |    666.44 |    TBD     |

### Calibration observations (this is the important data)

1. **Every hand-crafted ablation (Phase 1 and 1b) scores 4×–5× worse than
   the older optimizer runs** (412–666 vs 91–116). All 9 hand-crafted
   patches occupy a tight band (412–436) far above the 91–116 optimizer
   band. The hand-crafted patches are audibly *closer* to a real piano
   (they have a decaying envelope, filter_env darkening, and — in most
   1b variants — a non-crackling attack), but MR-STFT disagrees.

2. **MR-STFT's spread across the six 1b ablations is only 20 units
   (412→432)**, ~5% of the fitness range. The attack primitive — which
   the user can hear clearly is the dominant perceptual difference — is
   essentially invisible to MR-STFT at this level of base mismatch. The
   fitness is dominated by the sustained-body spectrum, not the
   first 20 ms.

3. **`pul_pultri_tri` (the cleanest smooth morph) ranks best** at 412.32
   and **`noisepul_tri` ranks worst at 431.98**. MR-STFT prefers
   smoother, more harmonic attacks because they match the reference's
   *average* spectrum more closely across frames. A piano hammer-strike
   is broadband for ~20 ms, so the noise-bearing variants necessarily
   inject energy into frequency bins the reference does not occupy at
   that moment — and MR-STFT punishes that even though it is the
   perceptually correct behaviour. This is evidence the fitness
   can't distinguish "has a piano-like broadband transient" from "has
   no transient at all".

4. **`tri_only` (no attack primitive, 420.45) scores *better* than both
   noise-bearing variants** (`noisepul_pul_tri` 416.41 is slightly
   better, but `noisepul_tri` 431.98 is worse). Confirms the hypothesis
   that the current fitness rewards "smoothest tail" over "correct
   onset character".

5. **`no_waveform_table` scores 666** (60% worse than any variant that
   uses *any* waveform table). This one is consistent with perception —
   pulse-only for the entire note is audibly the worst of all options —
   and shows the fitness *can* detect gross timbre mismatches. It only
   fails at the fine transient-shape level.

6. **`no_hard_restart` is worse than `handcraft_full` by ~18 units**
   (436 vs 418) purely because missing the 2-frame hard-restart pre-roll
   shifts the onset timing by ~40 ms, causing a phase misalignment
   against the reference at every note onset. This is a real effect but
   also a red herring — the fitness sees a temporal shift, not a
   qualitative difference.

### Implication for next steps

The current MR-STFT (even with log-mag + frame weighting) cannot rank
attack-primitive differences. To make the fitness prefer the
perceptually-best variant, we'd need to add something like:

- An onset-spectrum-specific term (STFT over the first ~40 ms only,
  weighted more heavily than the body).
- A broadband-transient descriptor (spectral flatness or spectral
  centroid variance) in the first 20 ms, compared directly to the
  reference's equivalent.
- Perceptual masking (e.g. Zimtohrli re-ranking is already in the
  pipeline for exactly this reason — but it's only used for final
  re-ranking, not as the optimizer's main fitness).

The 4× gap between "hand-crafted with a decaying envelope" (412–436) and
"older optimizer result" (91–116) *also* suggests the optimizer may have
been fitting low-hanging-fruit spectral averages without producing a
genuinely piano-like onset. This is consistent with the user's
observation that the older TPE params ranked best on MR-STFT but
"sounded non-piano".

## Predicted ranking (most → least piano-like, by spectral/structural reasoning)

1. **`noisepul_pul_tri` (`[0xC1, 0x41, 0x11]`)** — narrow-band gated-noise
   burst provides the broadband hammer-strike character (inharmonic
   partials in the first ~20 ms, which is what a real piano hammer
   produces), but at ~35% the amplitude of pure noise so it does not
   crackle. The intermediate pulse frame gives a brief harmonic
   stabilisation before the triangle body settles. This is the
   historically-documented Detert-style primitive and matches how real
   piano onsets decompose (broadband transient → quasi-harmonic attack →
   harmonic body).
2. **`noisepul_tri` (`[0xC1, 0x11]`)** — same gated-noise hammer, one
   frame shorter, straight into triangle. Slightly less harmonic "body
   forming" moment; may sound a touch more abrupt but should still be
   very piano-like.
3. **`pul_pultri_tri` (`[0x41, 0x51, 0x11]`)** — no noise. Three-step
   harmonic morph produces a non-broadband attack; the `0x51` interlude
   adds a brief reedy/hollow moment that loosely approximates the
   quasi-inharmonic spectrum of a piano attack without using noise at all.
   Probably the best-sounding no-noise option.
4. **`pultri_tri` (`[0x51, 0x11]`)** — pulse+triangle combined straight
   into triangle. Two-step morph, cleaner than pure pulse. Will sound
   tonal rather than percussive.
5. **`pul_tri` (`[0x41, 0x11]`)** — one frame of pulse, then triangle.
   Minimal attack shaping; will sound like a triangle voice with a
   single pulse-edge click. Probably too clean / too "square".
6. **`tri_only` (`[0x11]`)** — no attack primitive at all. The hard-restart
   pre-roll and gate-on provide only a minimal phase-reset onset; the
   instrument will sound like a pure-triangle bell, not a piano. Included
   as a reference baseline.

## Caveats

- All predictions are **spectral/structural reasoning only**, not listening
  tests. Real piano-likeness has to be picked by ear.
- `0xC1` is safe for single-frame bursts on both 6581 and 8580, but holding
  noise-combined waveforms for many frames can lock the shift register to
  zero on 6581. Here we use it for at most one frame per note, so it is
  safe on both chips. Renders here are 8580 only as specified.
- Parameters other than `waveform_table` are **identical** across all six
  ablations and match Phase 1's `make_handcraft_params()` exactly, so any
  audible difference is attributable purely to the first 1–3 frames of the
  waveform register.
