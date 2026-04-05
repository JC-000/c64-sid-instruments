# sidmatch: SID instrument rendering

Two backends turn a `SidParams` patch into a mono WAV:

| backend            | function              | speed              | notes                                   |
|--------------------|-----------------------|--------------------|-----------------------------------------|
| **pyresidfp**      | `render_pyresid(...)` | fast, in-process   | for the inner optimization loop         |
| **VICE (`x64sc`)** | `render_vice(...)`    | real-time, headless | ground-truth verification               |

## `SidParams`

Single-voice patch description. All fields have sensible defaults.

| field              | type                      | meaning                                                                    |
|--------------------|---------------------------|----------------------------------------------------------------------------|
| `waveform`         | `str`                     | `"triangle"`, `"saw"`, `"pulse"`, `"noise"`, or combos (`"triangle+pulse"`) |
| `attack`           | `int` 0-15                | SID ADSR attack nibble                                                     |
| `decay`            | `int` 0-15                | decay nibble                                                               |
| `sustain`          | `int` 0-15                | sustain nibble                                                             |
| `release`          | `int` 0-15                | release nibble                                                             |
| `pulse_width`      | `int` 0-4095              | static pulse width                                                         |
| `pw_table`         | `list[(frame, pw)]`       | optional per-frame PW overrides                                            |
| `filter_cutoff`    | `int` 0-2047              | 11-bit SID filter cutoff                                                   |
| `filter_resonance` | `int` 0-15                | filter resonance                                                           |
| `filter_mode`      | `"lp"/"bp"/"hp"/"off"`    | filter routing                                                             |
| `filter_voice1`    | `bool`                    | route voice 1 through the filter                                           |
| `ring_mod`         | `bool`                    | enable ring modulation                                                     |
| `sync`             | `bool`                    | enable hard sync                                                           |
| `frequency`        | `float` Hz                | note pitch; internally mapped via `hz_to_sid_freq()`                       |
| `gate_frames`      | `int`                     | PAL frames (50Hz) the gate is held high                                    |
| `release_frames`   | `int`                     | PAL frames to keep capturing after gate-off                                |
| `wavetable`        | `list[(frame, wf_byte)]`  | optional per-frame waveform-byte overrides                                 |
| `volume`           | `int` 0-15                | SID master volume                                                          |

## Usage

```python
from sidmatch.render import SidParams, render_pyresid, render_vice
from pathlib import Path

patch = SidParams(
    waveform="saw", frequency=440.0,
    attack=0, decay=9, sustain=8, release=4,
    gate_frames=50, release_frames=25,
)

# In-process render -> np.float32 array in [-1, 1]
audio = render_pyresid(patch, sample_rate=44100)

# Authoritative render -> WAV file on disk (takes ~6 seconds real time)
render_vice(patch, Path("vice_out.wav"), sample_rate=44100)
```

## VICE invocation details

`render_vice` builds a tiny .prg via `acme`, then invokes `x64sc` headlessly:

```
x64sc -console -pal +autostart-warp +binarymonitor +remotemonitor \
      -sound -sounddev wav -soundarg <path> -soundrate 44100 \
      -soundoutput 1 -limitcycles <N> -autostartprgmode 1 \
      -autostart <prg>
```

Key findings from developing this:

* VICE's `wav` backend is a **sound device** (`-sounddev wav`), not the
  recording device. `-soundrecdev` silently wrote empty files in our tests.
* `-warp` and the default autostart-warp **race the sound buffer** and
  produce a 44-byte (header-only) WAV. We disable them (`+autostart-warp`)
  and let VICE run real-time.
* `-limitcycles N` exits with `rc=1` once `N` CPU cycles have executed.
  That is expected; the WAV is flushed cleanly on that exit.
* `SDL_VIDEODRIVER=dummy` is set so VICE runs with no display.
* VICE emits a large power-on click at the start of the WAV; downstream
  analysis should skip the first ~0.5s.

## Environment

```
python3 -m pip install --user --break-system-packages \
    pyresidfp librosa numpy scipy soundfile cma pytest
```

(A `.venv` sits at the repo root but lacks `pip` because `python3-venv`
is not installed — `--user` installation is what this worktree uses.)

Tests: `python3 -m pytest tests/test_render.py -v`
