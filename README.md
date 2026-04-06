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

Each instrument in this library is produced by the CMA-ES optimizer in
`tools/sidmatch/`. The optimizer renders candidate SID patches, extracts
perceptual audio features from both the SID render and the reference
recording, and computes a **weighted distance** between the two feature
vectors. That scalar distance is the **fitness score**.

### What it measures

The fitness score is the weighted sum of eight component distances between
the reference sample and the SID render:

| Component | Distance metric | Default weight |
|---|---|---:|
| `envelope` | L2 between normalized amplitude envelopes (128 frames) | 1.0 |
| `harmonics` | Cosine distance of the first 16 partial magnitudes | 2.0 |
| `spectral_centroid` | L1 between log-centroid time series (scaled by 4 octaves) | 0.5 |
| `spectral_rolloff` | L1 between log-rolloff time series (scaled by 4 octaves) | 0.25 |
| `spectral_flatness` | L1 between flatness time series | 0.25 |
| `noisiness` | Squared error of scalar noisiness | 0.5 |
| `fundamental` | Squared log2-ratio of f0 estimates | 2.0 |
| `adsr` | L1 over (attack, decay, sustain, release) / 4 | 1.0 |

All components are non-negative and normalized to be O(1), so the default
weights are directly interpretable. The function is symmetric and
`distance(x, x) == 0`.

### How to interpret it

- **0** = identical features (perfect match)
- **Lower is better**
- **Typical range for SID instruments: 0.2 -- 0.6.** The SID chip's
  limited waveforms and coarse ADSR mean even well-optimized patches
  usually land above 0.2.
- Delivered scores: grand-piano **0.44** (6581) / **0.34** (8580),
  acoustic-guitar **0.28** (6581) / **0.35** (8580).

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
  For example, the grand piano lands on pulse + lowpass on the 6581 but
  saw + bandpass on the 8580; the acoustic guitar uses saw + bandpass on
  the 6581 but pulse + bandpass on the 8580.

The `--chip-model` flag on `sidmatch match` and `sidmatch export`
selects which emulated SID is used during optimization and rendering.

## License

Instruments are released under [CC-BY 4.0](LICENSE). Attribution goes to
each instrument's author as listed in its folder's `README.md`.
