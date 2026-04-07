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
Audio is resampled to **44.1 kHz** and silence is trimmed (−60 dB).

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

`distance(ref, cand, weights=None)` — weighted sum of per-component distances:

| component | distance | default weight |
|---|---|---|
| `envelope` | L2 between amplitude envelopes | 1.0 |
| `harmonics` | cosine distance of partial vectors | 2.0 |
| `spectral_centroid` | L1 between log-centroid series (÷ 4 octaves) | 0.5 |
| `spectral_rolloff` | L1 between log-rolloff series (÷ 4 octaves) | 0.25 |
| `spectral_flatness` | L1 between flatness series | 0.25 |
| `noisiness` | squared error of scalar noisiness | 0.5 |
| `fundamental` | squared log2-ratio of f0 estimates | 2.0 |
| `adsr` | L1 over (attack, decay, sustain, release) / 4 | 1.0 |

Properties: `distance(x, x) == 0`, symmetric, non-negative.
Override via `weights={"harmonics": 3.0, ...}`.

---

## Matching (fast grid search)

The `match` subcommand uses a **two-phase grid search**:

1. **Fast screening** -- renders each discrete combo (sustain waveform x
   attack waveform x filter mode x test bit = ~42 combos) once with
   mid-range continuous defaults. Takes seconds.
2. **Top-K refinement** -- the best K combos from phase 1 (default
   `--top-k 3`) are refined with full CMA-ES optimization using the
   given `--budget`.

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

Together these changes yield an estimated **4--6x wall-clock speedup** with
no quality regression in fitness scores.

---

## Environment

```
python3 -m pip install --user --break-system-packages \
    pyresidfp librosa numpy scipy soundfile cma pytest
```

Tests:
```
python3 -m pytest tests/ -v
```
