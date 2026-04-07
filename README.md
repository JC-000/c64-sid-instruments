# c64-sid-instruments

A library of reusable SID instruments for making music on the Commodore 64.

## Layout

Each instrument lives in its own folder under `instruments/`, with
chip-specific variants in separate subdirectories:

```
instruments/
  <instrument-name>/
    README.md         # Description, both variants documented
    6581/             # MOS 6581 optimized
      params.json
      raw.asm
      goattracker.ins
      sid_render.wav
    8580/             # MOS 8580 optimized
      params.json
      raw.asm
      goattracker.ins
      sid_render.wav
```

## Supported formats

- **GoatTracker** — `.ins` files loadable in GoatTracker 2.x (Cadaver).
- **SID-Wizard** — `.ins` files loadable in SID-Wizard (Hermit).
- **Raw .asm** — Plain ACME-syntax register/wavetable/pulsetable/filtertable
  data for embedding directly in your own music routine.

Not every instrument needs every format; see each instrument's README for
what's available.

## Using an instrument

**GoatTracker / SID-Wizard**: load the `.ins` file via the tracker's
instrument load menu.

**Raw asm**: `!source` the `.asm` file from your ACME project and wire the
tables into your player.

## Contributing

Add a new folder under `instruments/` named in kebab-case (e.g.
`bass-pluck`, `lead-saw-sweep`). Include at least one format and a
`README.md` describing the sound, tags, and any usage caveats.

## Fitness score

Each instrument in this library is produced by the **tracker-style
pipeline** in `tools/sidmatch/`. The pipeline uses wavetable sequences,
PW and filter sweeps, and ADSR-aware render durations -- techniques drawn
from how real C64 tracker instruments work -- to approximate real-world
instrument timbres on the SID chip.

The optimizer renders candidate SID patches, extracts perceptual audio
features from both the SID render and the reference recording, and
computes a **weighted distance** between the two feature vectors. That
scalar distance is the **fitness score**.

### What it measures

The fitness score is the weighted sum of eight component distances between
the reference sample and the SID render:

| Component | Distance metric | Default weight |
|---|---|---:|
| `envelope` | L2 between normalized amplitude envelopes (128 frames) | 1.0 |
| `harmonics` | Cosine distance of the first 16 partial magnitudes | 1.0 |
| `spectral_centroid` | L1 between log-centroid time series (scaled by 4 octaves) | 0.5 |
| `spectral_rolloff` | L1 between log-rolloff time series (scaled by 4 octaves) | 0.25 |
| `spectral_flatness` | L1 between flatness time series | 0.25 |
| `noisiness` | Squared error of scalar noisiness | 0.5 |
| `fundamental` | Squared log2-ratio of f0 estimates | 2.0 |
| `adsr` | L1 over (attack, decay, sustain, release) / 4 | 1.5 |

All components are non-negative and normalized to be O(1), so the default
weights are directly interpretable. The function is symmetric and
`distance(x, x) == 0`.

### How to interpret it

- **0** = identical features (perfect match)
- **Lower is better**
- **Typical range for SID instruments: 0.2 -- 0.6.** The SID chip's
  limited waveforms and coarse ADSR mean even well-optimized patches
  usually land above 0.2.
- Delivered scores: acoustic-guitar **0.2944** (6581) / **0.2867** (8580)
  (v3 pipeline).  Grand piano **0.4194** (6581) / **0.4621** (8580)
  (v4 pipeline, multi-note chromatic evaluation across C3--C5, 9 pitches;
  see `instruments/grand-piano/README.md`).

Each instrument folder records its fitness score in both `params.json`
(field `fitness_score`) and `raw.asm` (comment `; @meta fitness_score=...`).

See `tools/sidmatch/fitness.py` for the implementation and
`tools/sidmatch/README.md` for the full feature-extraction and distance
documentation.

## Optimization targets

Each instrument in this library is optimized against a specific **source
recording** and a specific **target SID chip model**.

- **Source recording** -- the real-world instrument sample used as the
  optimization reference. Each instrument's README and `params.json` cite
  the exact sample (e.g. "Salamander Grand Piano V3, C4 fortissimo").
- **Target SID model** -- either MOS 6581 or CSG 8580. The two chip
  revisions have significantly different analog filter implementations:
  the 6581 has a darker, more distorted filter curve while the 8580's
  filters are cleaner and closer to spec. An instrument optimized for one
  chip will still play on the other, but the filter response (and
  therefore the timbre) may differ noticeably.
- Every instrument now ships with both **6581** and **8580** variants,
  since the chips' different analog filter implementations cause the
  optimizer to find substantially different timbral strategies for each.

### Tracker-style instrument techniques (v3 pipeline)

The v3 pipeline models instruments the way C64 tracker musicians
actually build them:

- **Wavetable sequences** -- each note plays a frame-by-frame waveform
  sequence: an optional test-bit reset (oscillator phase sync on frame
  0), an attack waveform for the first few frames, then a sustain
  waveform for the rest of the note. This mimics the wavetable
  programming in GoatTracker / SID-Wizard.
- **PW sweep** -- the pulse width is not static; it sweeps from
  `pw_start` by `pw_delta` per frame, clamped between `pw_min` and
  `pw_max` (with optional ping-pong mode). This produces the rich,
  animated pulse timbres heard in C64 music.
- **Filter sweep** -- the filter cutoff interpolates from
  `filter_cutoff_start` to `filter_cutoff_end` over
  `filter_sweep_frames` PAL frames, creating natural brightness decay
  (or attack).
- **ADSR-aware render duration** -- the gate and release durations are
  computed from the SID's hardware ADSR timing tables via
  `compute_gate_release()`. The SID's ADSR is constrained: attack
  ranges from 2 ms to 8 s (16 steps), decay/release from 6 ms to 24 s
  (16 steps). The pipeline ensures each render is exactly long enough
  for the ADSR envelope to play out.
- **Fast grid search** -- the optimizer screens ~42 discrete
  combinations of sustain waveform, attack waveform, filter mode, and
  test-bit usage in seconds (one render per combo with mid-range
  continuous defaults). The top K combos (default 3, configurable via
  `--top-k`) are then refined with full CMA-ES optimization. This is
  dramatically faster than the old exhaustive mini-CMA-ES per combo.

- **Multi-note chromatic evaluation** -- instead of optimizing against a
  single reference note, the pipeline can evaluate each candidate across
  multiple pitches.  Supply a directory of reference WAVs with a
  `note_map.json` via `--reference-set` and the optimizer minimizes the
  aggregated fitness: `(1 - alpha) * mean(d) + alpha * max(d)` (default
  `alpha=0.15`).  This penalises patches that break at certain pitches
  and produces instruments that track correctly across the keyboard.
  See `tools/sidmatch/multi_note.py` and `docs/multi-note-fitting.md`.

- **Parallel top-K CMA-ES** -- Phase 2 refinement combos can run
  concurrently via `--parallel-chips`.  See `tools/sidmatch/README.md`
  for benchmarks and guidance on when this helps.

The `--chip-model` flag on `sidmatch match` and `sidmatch export`
selects which emulated SID is used during optimization and rendering.

## License

Instruments are released under [CC-BY 4.0](LICENSE). Attribution goes to
each instrument's author as listed in its folder's `README.md`.
