# c64-sid-instruments

A library of reusable SID instruments for making music on the Commodore 64.

## Layout

Each instrument lives in its own folder under `instruments/`, with every
supported format side-by-side:

```
instruments/
  <instrument-name>/
    goattracker.ins   # GoatTracker 2.x instrument file
    sidwizard.ins     # SID-Wizard instrument file
    raw.asm           # ACME-includable register tables
    README.md         # Description, tags, usage notes, credits
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
- Delivered scores: grand-piano **0.43**, acoustic-guitar **0.28**.

Each instrument folder records its fitness score in both `params.json`
(field `fitness_score`) and `raw.asm` (comment `; @meta fitness_score=...`).

See `tools/sidmatch/fitness.py` for the implementation and
`tools/sidmatch/README.md` for the full feature-extraction and distance
documentation.

## License

Instruments are released under [CC-BY 4.0](LICENSE). Attribution goes to
each instrument's author as listed in its folder's `README.md`.
