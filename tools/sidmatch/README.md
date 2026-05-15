# sidmatch

A pipeline that extracts perceptual/spectral features from a reference
instrument recording and searches SID-chip parameter space (via CMA-ES)
for a patch that matches it as closely as the hardware allows.

## Modules

- `render.py` — `SidParams`, `render_pyresid(...)`, `render_vice(...)`,
  `compute_gate_release()` — SID audio renderers and ADSR timing
- `grid_search.py` — `grid_search(...)` — two-phase fast screening +
  top-K CMA-ES refinement
- `optimize.py` — `Optimizer` — CMA-ES wrapper for continuous SID
  parameter search
- `vice_verify.py` — builds a .prg harness and runs VICE headless with
  `-sounddev wav` to capture audio
- `features.py` — `extract(audio, sr) -> FeatureVec`
- `fitness.py` — `distance(ref, cand, weights=None) -> float`
- `surrogate.py` — MLP surrogate model for pre-screening candidates
- `cli.py` — command-line interface (`match`, `export` subcommands)

---

## Rendering

Two backends turn a `SidParams` patch into mono PCM:

| backend            | function              | speed              | notes                                   |
|--------------------|-----------------------|--------------------|-----------------------------------------|
| **pyresidfp**      | `render_pyresid(...)` | fast, in-process   | for the inner optimization loop         |
| **VICE (`x64sc`)** | `render_vice(...)`    | real-time, headless | ground-truth verification               |

### `SidParams`

Single-voice patch description (tracker-style). All fields have sensible
defaults. The v3 pipeline adds wavetable sequences, PW sweeps, filter
sweeps, and ADSR-aware duration.

#### Core fields

| field              | type                      | meaning                                                                    |
|--------------------|---------------------------|----------------------------------------------------------------------------|
| `waveform`         | `str`                     | `"triangle"`, `"saw"`, `"pulse"`, `"noise"`, or combos (`"triangle+pulse"`). Also serves as alias for sustain waveform in simple patches. |
| `attack`/`decay`/`sustain`/`release` | `int` 0-15  | SID ADSR nibbles                                                           |
| `frequency`        | `float` Hz                | note pitch; mapped via `hz_to_sid_freq()`                                  |
| `gate_frames`      | `int`                     | PAL frames (50Hz) the gate is held high                                    |
| `release_frames`   | `int`                     | PAL frames to keep capturing after gate-off                                |
| `volume`           | `int` 0-15                | SID master volume                                                          |
| `ring_mod`, `sync` | `bool`                    | ring modulation / hard sync                                                |
| `chip_model`       | `str`                     | `"6581"` or `"8580"` (default: unspecified, pyresidfp defaults to 6581)    |

#### Wavetable sequence (v3)

| field                  | type           | meaning                                                                  |
|------------------------|----------------|--------------------------------------------------------------------------|
| `wt_attack_frames`     | `int` 1-5      | number of frames the attack waveform plays before switching to sustain   |
| `wt_attack_waveform`   | `str` or None  | waveform for the attack phase (e.g. `"noise"`, `"pulse+saw"`). None = same as sustain. |
| `wt_sustain_waveform`  | `str` or None  | waveform for the sustain phase. None = same as `waveform`.               |
| `wt_use_test_bit`      | `bool`         | if True, frame 0 uses the SID test bit (`$08`) to reset oscillator phase |

#### PW sweep (v3)

| field       | type           | meaning                                                         |
|-------------|----------------|-----------------------------------------------------------------|
| `pw_start`  | `int` 0-4095   | starting pulse width                                            |
| `pw_delta`  | `int`          | change per frame (+ve = sweep up, -ve = sweep down, 0 = static) |
| `pw_min`    | `int` 0-4095   | lower bound for clamping / ping-pong                            |
| `pw_max`    | `int` 0-4095   | upper bound for clamping / ping-pong                            |
| `pw_mode`   | `str`          | `"sweep"` (clamp at bounds) or `"pingpong"` (reverse at bounds) |

#### Filter sweep (v3)

| field                  | type           | meaning                                                       |
|------------------------|----------------|---------------------------------------------------------------|
| `filter_cutoff_start`  | `int` 0-2047   | starting filter cutoff                                        |
| `filter_cutoff_end`    | `int` 0-2047   | sweep target cutoff                                           |
| `filter_sweep_frames`  | `int`          | how many PAL frames to reach end (0 = static)                 |
| `filter_resonance`     | `int` 0-15     | filter resonance                                              |
| `filter_mode`          | `"lp"/"bp"/"hp"/"off"` | filter routing                                        |
| `filter_voice1`        | `bool`         | route voice 1 through the filter                              |

#### Legacy fields (still supported)

| field              | type                      | meaning                                                                    |
|--------------------|---------------------------|----------------------------------------------------------------------------|
| `pulse_width`      | `int` 0-4095              | static pulse width (ignored if `pw_start`/`pw_delta` are set)              |
| `pw_table`         | `list[(frame, pw)]`       | per-frame PW overrides (superseded by PW sweep)                            |
| `filter_cutoff`    | `int` 0-2047              | static filter cutoff (used if `filter_cutoff_start` is None)               |
| `wavetable`        | `list[(frame, wf_byte)]`  | per-frame waveform-byte overrides (superseded by wavetable sequence)       |

```python
from sidmatch.render import SidParams, render_pyresid, render_vice
from pathlib import Path

patch = SidParams(
    waveform="saw", frequency=440.0,
    attack=0, decay=9, sustain=8, release=4,
    gate_frames=50, release_frames=25,
)
audio = render_pyresid(patch, sample_rate=44100)            # np.float32 in [-1, 1]
render_vice(patch, Path("vice_out.wav"), sample_rate=44100) # ~6s real-time
```

### ADSR timing and `compute_gate_release()`

The SID chip's ADSR envelope has hardware-defined timing that cannot be
set freely. The 16 attack steps range from **2 ms to 8 s**; the 16
decay/release steps range from **6 ms to 24 s**:

```
ATTACK_MS         = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
DECAY_RELEASE_MS  = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]
```

`compute_gate_release(attack, decay, sustain, release)` converts ADSR
nibbles into `(gate_frames, release_frames)` in PAL frames (50 Hz) so
the render is exactly long enough for the envelope to play out. Gate
covers attack + decay (or just attack if sustain=15); release covers the
release phase. Both are clamped to sensible bounds (10-200 and 10-250
frames respectively).

### VICE invocation details

```
x64sc -console -pal +autostart-warp +binarymonitor +remotemonitor \
      -sound -sounddev wav -soundarg <path> -soundrate 44100 \
      -soundoutput 1 -limitcycles <N> -autostartprgmode 1 \
      -autostart <prg>
```

- `wav` is a **sound device** (`-sounddev wav`), not a record device.
  `-soundrecdev` silently writes empty files in our VICE build.
- `-warp` / default autostart-warp **race the sound buffer** → empty WAV.
  Disable with `+autostart-warp` and let VICE run real-time.
- `-limitcycles N` exits rc=1 when hit; WAV flushes cleanly.
- `SDL_VIDEODRIVER=dummy` runs with no display.
- VICE emits a large power-on click; analysis skips the first ~0.5s.

---

## Feature extraction

All time-series features are resampled to **128 frames** (`features.TIME_SERIES_FRAMES`).
Audio is resampled to **22050 Hz** (halved from 44100 to reduce
computation) and silence is trimmed (-60 dB). Feature extraction uses
scipy and numpy directly on the hot path (librosa removed from inner
loop).

| field | type | description |
|---|---|---|
| `sr` | int | canonical analysis rate (44100) |
| `duration_s` | float | length after silence trimming |
| `amplitude_envelope` | ndarray[128] | normalized RMS per 10 ms hop, resampled |
| `attack_time_s` | float | time from 10% to peak of envelope |
| `decay_time_s` | float | time from peak to sustain level |
| `sustain_level` | float | median envelope value across sustain region |
| `release_time_s` | float | time from sustain region end to 10% of peak |
| `harmonic_magnitudes` | ndarray[16] | first 16 partials, averaged over sustain, peak-normalized |
| `spectral_centroid` | ndarray[128] | centroid (Hz) time series |
| `spectral_rolloff` | ndarray[128] | 85% rolloff (Hz) time series |
| `spectral_flatness` | ndarray[128] | flatness (0..1) time series |
| `fundamental_hz` | float | median YIN f0 over voiced frames |
| `noisiness` | float | mean spectral flatness |

`extract` handles mono/stereo, any input SR, short buffers, all-zero audio.
Raises `ValueError` on empty or non-finite input.

## Distance recipe

`distance(ref, cand, weights=None)` — weighted sum of per-component distances.

The v5 pipeline replaced the spectral centroid/rolloff/flatness/noisiness
components with a **multi-scale log-mel MSE** fitness function and added
**envelope derivative matching**:

| component | distance | default weight |
|---|---|---|
| `log_mel` | multi-scale log-mel spectrogram MSE (3 FFT sizes) | 1.0 |
| `envelope` | L2 between amplitude envelopes | 1.0 |
| `envelope_derivative` | L2 between envelope derivative curves | 0.5 |
| `harmonics` | cosine distance of partial vectors | 2.0 |
| `fundamental` | squared log2-ratio of f0 estimates | 2.0 |
| `adsr` | L1 over (attack, decay, sustain, release) / 4 | 1.0 |
| `onset_spectral` | adaptive onset-weighted spectral loss (weights attack transient by reference spectral flux) | 0.5 |
| `mfcc` | MFCC distance (timbral identity via Mel-frequency cepstral coefficients) | 0.5 |
| `spectral_convergence` | Frobenius norm ratio of reference vs candidate spectrograms | 0.5 |

Properties: `distance(x, x) == 0`, symmetric, non-negative.
Override via `weights={"harmonics": 3.0, ...}`.

---

## Matching (fast grid search)

The `match` subcommand uses a **two-phase grid search** with several
v5 pipeline improvements:

1. **Fast screening** -- renders each discrete combo (sustain waveform x
   attack waveform x filter mode x test bit = ~42 combos) once with
   mid-range continuous defaults. Takes seconds.
2. **Top-K refinement** -- the best K combos from phase 1 (default
   `--top-k 3`) are refined with full CMA-ES optimization using the
   given `--budget`.

### v5 pipeline improvements

- **Coarse-to-fine rendering** -- early evaluations render only 0.5s of
  audio, upgrading to 1.0s and then full duration as the search
  converges. Reduces per-eval cost in early stages.
- **Conditional parameter trimming** -- based on the combo (e.g. filter
  off, no pulse waveform), irrelevant continuous dimensions are frozen,
  leaving 5--13 active dims instead of the full set.
- **Successive halving for top-K** -- budget is reallocated from
  poorly-performing combos to promising ones during Phase 2.
- **Surrogate MLP pre-screening** -- after 500 evaluations, an MLP
  trained on past evaluations pre-screens candidates and skips those
  predicted to be poor. See `surrogate.py`.
- **Warm-start CMA-ES** -- CMA-ES restarts use a tighter sigma around
  the best-known solution for faster local convergence.
- **Parameter reparameterization** -- pulse width is parameterized as
  `pw_center`/`pw_width` instead of `pw_start`/`pw_delta`; filter cutoff
  uses log scale; all continuous parameters are normalized to [0,1].
- **Multi-step wavetable sequences** -- the search space includes 3--4
  step waveform patterns (not just attack+sustain), enabling richer
  timbral evolution per note.
- **22050 Hz rendering** -- inner-loop renders use 22050 Hz sample rate
  (halved from 44100), cutting render time roughly in half.
- **scipy+numpy feature extraction** -- librosa removed from the hot
  path; feature extraction uses scipy and numpy directly.

By default, `match` runs for **both** the 6581 and 8580 chip models and
writes results to `<work-dir>/6581/` and `<work-dir>/8580/` respectively:

```
python3 -m sidmatch.cli match \
    --sample tools/samples/grand-piano/salamander-piano-C4-v16-ff.wav \
    --frequency 261.63 \
    --name grand-piano \
    --budget 5000 \
    --top-k 3 \
    --work-dir work/grand-piano
```

A summary comparing the two chips' best fitness is printed at the end.

To run only a single chip variant, pass `--chip-model`:

```
python3 -m sidmatch.cli match \
    --chip-model 6581 \
    --sample ... --frequency 261.63 --name grand-piano \
    --work-dir work/grand-piano-6581
```

When `--chip-model` is given, it overrides the default `--all-chips`
behavior and results are written directly into `<work-dir>/` (no chip
subdirectory).

### CLI arguments for `match`

| argument        | default | meaning                                              |
|-----------------|---------|------------------------------------------------------|
| `--sample`      | required | path to reference WAV                               |
| `--frequency`   | required | fundamental frequency of the reference note (Hz)    |
| `--name`        | required | instrument name                                     |
| `--budget`      | 5000    | CMA-ES evaluations per top-K combo                   |
| `--top-k`       | 3       | number of top screening combos to refine with CMA-ES |
| `--patience`    | 500     | early-stop if no improvement for N evals             |
| `--workers`     | None    | parallel workers (None = auto)                       |
| `--seed`        | 0       | RNG seed                                             |
| `--work-dir`    | required | output directory                                    |
| `--chip-model`  | None    | `"6581"` or `"8580"` (default: run both)             |
| `--parallel-chips` / `--no-parallel-chips` | off | Refine both chip models concurrently (opt-in; useful on high-core-count machines) |
| `--optimizer`   | `cma`   | optimizer backend: `cma` (CMA-ES), `tpe` (Optuna TPE), or `tpe+cma` (hybrid) |
| `--perceptual-rerank` | off | re-rank top-K candidates using Zimtohrli psychoacoustic metric |

### Optuna TPE alternative

Pass `--optimizer tpe` to use Optuna's Tree-structured Parzen Estimator
instead of CMA-ES. TPE is a Bayesian optimization method that builds
density models over good and bad regions of parameter space. It requires
`pip install optuna`.

TPE now uses **batch ask/tell with a multiprocessing pool**, matching
the parallelism strategy used by CMA-ES. Each generation asks for a
batch of trials, evaluates them in parallel across workers, and tells
the results back. This eliminates the serial bottleneck that made early
TPE benchmarks significantly slower than CMA-ES. TPE also handles
1-dimensional search spaces where CMA-ES crashes (covariance matrix
requires >= 2 dimensions).

### Benchmark: CMA-ES vs TPE

Results from single-chip optimization runs (budget=5000):

| Instrument | Chip | CMA-ES Fitness | CMA-ES Time | TPE Fitness | TPE Time |
|---|---|---|---|---|---|
| Grand Piano | 8580 | 0.4721 | 70 min | 1.9050 | 259 min |
| Acoustic Guitar | 8580 | 0.5504 | 122 min | 2.8345 | 252 min |
| Violin | 6581 | 0.9138 | 49 min | 2.8142 | 275 min |

After fixing TPE parallel evaluation (batch ask/tell), the three-phase
pipeline with TPE produces competitive results:

| Instrument | Chip | Three-phase TPE Fitness |
|---|---|---|
| Grand Piano | 6581 | 0.4310 |
| Grand Piano | 8580 | 0.4884 |

CMA-ES remains the default, but TPE is now a viable alternative --
especially for 1-dimensional search spaces where CMA-ES cannot
operate. TPE instrument outputs are included in the repo under
`instruments/*-tpe/` for comparison.

### Hybrid TPE+CMA-ES backend

Pass `--optimizer tpe+cma` to run a two-stage hybrid optimization:

1. **TPE exploration (25% of budget)** -- Optuna's TPE explores the
   parameter space broadly, building density models over promising
   regions.
2. **CMA-ES refinement (75% of budget)** -- the best TPE solutions are
   used to warm-start CMA-ES: the mean is set to TPE's best point,
   sigma and per-dimension standard deviations are derived from the top
   solutions, and the best solutions are injected into the initial
   CMA-ES population.

This combines TPE's strength at global exploration with CMA-ES's
efficient local refinement.

### Zimtohrli perceptual re-ranking

Pass `--perceptual-rerank` to re-rank the top-K candidates after
optimization using Google's Zimtohrli psychoacoustic metric. This
provides a perceptually-grounded validation step beyond the spectral
fitness function. Requires `pip install zimtohrli`.

---

## Exporting instruments

After running `match`, use the `export` subcommand to write results
into `instruments/<name>/<chip>/`:

```
python3 -m sidmatch.cli export \
    --work-dir work/grand-piano \
    --name grand-piano
```

When the work directory contains both `6581/` and `8580/` subdirectories
(the default after a dual-chip `match` run), `export` writes **both**
variants automatically to `instruments/<name>/6581/` and
`instruments/<name>/8580/`, plus a combined `README.md` at the
`instruments/<name>/` level.

To export only one chip, pass `--chip-model`:

```
python3 -m sidmatch.cli export \
    --work-dir work/grand-piano \
    --name grand-piano \
    --chip-model 6581
```

Each chip subdirectory contains:

| File | Content |
|---|---|
| `params.json` | SID parameters + `fitness_score` + `version` |
| `raw.asm` | ACME tables with `; @meta fitness_score=` and `; @meta version=` |
| `goattracker.ins` | GoatTracker binary (fitness cannot be embedded in binary) |
| `sid_render.wav` | Copied from work-dir if present |

The top-level `instruments/<name>/README.md` documents both chip
variants with a comparison table, noting any missing variants.

### Versioning

Each export increments the instrument version automatically:

- If `instruments/<name>/<chip>/params.json` does not exist, version starts at 1.
- If it exists, the new version is `old_version + 1`.
- If the new fitness score is **worse** (higher) than the existing one,
  a warning is printed but the export proceeds. The user may want a
  different tuning or changed weights.

The version is recorded in both `params.json` (`"version"` field) and
`raw.asm` (`; @meta version=N`).

---

## Performance optimizations

The optimization pipeline includes several performance improvements
organized in three tiers:

### Tier 1 -- inner-loop speedups

- **Duplicate STFT elimination** -- `extract()` now computes the STFT
  magnitude spectrogram once and reuses it for harmonic magnitudes,
  spectral centroid, rolloff, and flatness (previously harmonic extraction
  ran a second STFT on the sustain slice).
- **YIN f0 bypass** -- `extract()` accepts a `known_f0` keyword.  When
  the fundamental is already known (as it always is for SID renders whose
  pitch we set), the expensive YIN autocorrelation is skipped entirely.
- **ReferenceSet caching in workers** -- multi-note worker processes now
  reconstruct the `ReferenceSet` once at `_mn_worker_init` time instead
  of deserializing it on every evaluation call.

### Tier 2 -- algorithmic improvements

- **Phase 1 screening defaults as CMA-ES x0** -- the mid-range parameter
  values used during fast grid screening are passed as the CMA-ES starting
  point (`x0`), giving the evolutionary search a head-start from a region
  already known to be reasonable.
- **Parallel Phase 1 screening** -- both `grid_search()` and
  `grid_search_multi_note()` now distribute the ~42 discrete combos across
  a multiprocessing pool instead of evaluating them sequentially.
- **Pre-computed reference features** -- `Optimizer` accepts an optional
  `ref_fv` parameter so callers (like `grid_search`) can pass the
  already-extracted reference features instead of re-extracting from the
  WAV file.

### Tier 3 -- advanced techniques

- **SID emulator instance pooling** -- `render_pyresid()` reuses a cached
  `SoundInterfaceDevice` via `reset()` instead of constructing a new
  instance on every render.  This avoids repeated Python/C++ object
  allocation in the inner loop.
- **Cheap fitness proxy** -- `extract_lite()` and `distance_lite()` compute
  only envelope, harmonics, fundamental, and ADSR (no spectral time-series).
  Worker processes use this as an early-rejection filter: if the lite
  distance exceeds 2x the current best fitness, the full extraction is
  skipped.  This provides a lower-bound guarantee (skipped components are
  always >= 0) so no good candidates are lost.

### Parallel top-K CMA-ES refinement

Phase 2 combos can be refined concurrently via `ThreadPoolExecutor`.  When
`--parallel-chips` is enabled, both chip-model runs share the thread pool
and the per-combo worker budget is divided across active combos.  Both
`grid_search()` and `grid_search_multi_note()` support this mode.

**Benchmark** (budget=500, grand-piano, 8-core machine):

| mode | wall-clock | CPU utilization |
|------|-----------|-----------------|
| sequential (default) | 15m 18s | 3.9x |
| `--parallel-chips` | 33m 46s | higher, but contention-bound |

The sequential default is faster on most machines; `--parallel-chips` is
only beneficial when cores significantly outnumber active combos.

Note: optimization uses **pyresidfp** exclusively.  VICE (`x64sc`) is only
used for post-optimization verification tests.

Together these changes yield an estimated **4--6x wall-clock speedup** with
no quality regression in fitness scores.

---

## Instrument-type constraints

The `--instrument-type` flag restricts the optimizer search space to
parameter ranges appropriate for a specific instrument family.  This
dramatically reduces wall-clock time and prevents the optimizer from
settling on acoustically implausible parameter sets.

### Usage

```bash
python3 -m tools.sidmatch.cli match ref.wav output/ --instrument-type piano
```

### Available profiles

| Profile | ADSR bounds | Waveform filter | Other |
|---------|------------|-----------------|-------|
| `piano` | A<=2, D>=9, S<=3, R=3-9 | pulse sustain required | attack waveform required, min 100 gate frames |

### What each profile constrains

- **ADSR bounds** -- restricts attack, decay, sustain, and release to
  ranges that match the instrument's physical envelope.  Bounds are
  applied as overrides in all optimizer backends (CMA-ES, TPE,
  TPE+CMA-ES).
- **Waveform filtering** -- removes discrete combo candidates whose
  sustain waveform does not include the expected wave shape (e.g. pulse
  for piano PWM tone).
- **Attack waveform requirement** -- forces a distinct attack transient
  waveform rather than reusing the sustain waveform.
- **Minimum gate frames** -- sets a floor on how long the gate stays
  open, preventing the optimizer from shortening notes below what the
  instrument physically requires.

### Adding a new profile

1. Add an entry to `INSTRUMENT_PROFILES` in `grid_search.py` with keys:
   - `adsr_bounds` -- dict of `(min, max)` tuples for attack, decay,
     sustain, release.
   - `screening_defaults` -- default ADSR/pulse values for Phase 1
     screening.
   - `require_pulse_sustain` -- bool, filter combos to pulse sustain.
   - `require_attack_waveform` -- bool, require distinct attack wave.
   - `min_gate_frames` -- int, minimum gate duration in frames.
2. The profile is automatically available via `--instrument-type <name>`.

---

## Environment

```
python3 -m pip install --user --break-system-packages \
    pyresidfp librosa numpy scipy soundfile cma pytest

# Optional: for --optimizer tpe or tpe+cma
python3 -m pip install --user --break-system-packages optuna

# Optional: for --perceptual-rerank
python3 -m pip install --user --break-system-packages zimtohrli
```

Tests:
```
python3 -m pytest tests/ -v
```
