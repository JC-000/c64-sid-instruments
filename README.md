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

## License

Instruments are released under [CC-BY 4.0](LICENSE). Attribution goes to
each instrument's author as listed in its folder's `README.md`.
