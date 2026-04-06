# sidmatch

A pipeline that extracts perceptual/spectral features from a reference
instrument recording and searches SID-chip parameter space (via CMA-ES)
for a patch that matches it as closely as the hardware allows.

## Modules

- `render.py` — `render_pyresid(...)`, `render_vice(...)` — SID audio
  renderers (pyresidfp + VICE backends)
- `vice_verify.py` — builds a .prg harness and runs VICE headless with
  `-sounddev wav` to capture audio
- `features.py` — `extract(audio, sr) -> FeatureVec`
- `fitness.py` — `distance(ref, cand, weights=None) -> float`

---

## Rendering

Two backends turn a `SidParams` patch into mono PCM:

| backend            | function              | speed              | notes                                   |
|--------------------|-----------------------|--------------------|-----------------------------------------|
| **pyresidfp**      | `render_pyresid(...)` | fast, in-process   | for the inner optimization loop         |
| **VICE (`x64sc`)** | `render_vice(...)`    | real-time, headless | ground-truth verification               |

### `SidParams`

Single-voice patch description. All fields have sensible defaults.

| field              | type                      | meaning                                                                    |
|--------------------|---------------------------|----------------------------------------------------------------------------|
| `waveform`         | `str`                     | `"triangle"`, `"saw"`, `"pulse"`, `"noise"`, or combos (`"triangle+pulse"`) |
| `attack`/`decay`/`sustain`/`release` | `int` 0-15  | SID ADSR nibbles                                                           |
| `pulse_width`      | `int` 0-4095              | static pulse width                                                         |
| `pw_table`         | `list[(frame, pw)]`       | optional per-frame PW overrides                                            |
| `filter_cutoff`    | `int` 0-2047              | 11-bit SID filter cutoff                                                   |
| `filter_resonance` | `int` 0-15                | filter resonance                                                           |
| `filter_mode`      | `"lp"/"bp"/"hp"/"off"`    | filter routing                                                             |
| `filter_voice1`    | `bool`                    | route voice 1 through the filter                                           |
| `ring_mod`, `sync` | `bool`                    | ring modulation / hard sync                                                |
| `frequency`        | `float` Hz                | note pitch; mapped via `hz_to_sid_freq()`                                  |
| `gate_frames`      | `int`                     | PAL frames (50Hz) the gate is held high                                    |
| `release_frames`   | `int`                     | PAL frames to keep capturing after gate-off                                |
| `wavetable`        | `list[(frame, wf_byte)]`  | optional per-frame waveform-byte overrides                                 |
| `volume`           | `int` 0-15                | SID master volume                                                          |

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

## Matching

By default, `match` runs the full optimization for **both** the 6581 and
8580 chip models and writes results to `<work-dir>/6581/` and
`<work-dir>/8580/` respectively:

```
python3 -m sidmatch.cli match \
    --sample tools/samples/grand-piano/salamander-piano-C4-v16-ff.wav \
    --frequency 261.63 \
    --name grand-piano \
    --budget 5000 \
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

## Environment

```
python3 -m pip install --user --break-system-packages \
    pyresidfp librosa numpy scipy soundfile cma pytest
```

Tests:
```
python3 -m pytest tests/ -v
```
