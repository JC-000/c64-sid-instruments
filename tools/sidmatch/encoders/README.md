# SID instrument encoders

Turn a `SidParams` dataclass (see `tools/sidmatch/render.py`) into files that
can be included in an ACME project or loaded by a tracker.

## `raw_asm.py` - ACME source tables  [WORKING, round-trip tested]

Emits a single `.asm` chunk with the labels:

| label                         | contents                                |
|-------------------------------|-----------------------------------------|
| `<prefix>_adsr`               | 2 bytes: `(A<<4)|D`, `(S<<4)|R`         |
| `<prefix>_wavetable`          | `(waveform, cmd)` rows, `$ff,$00` end   |
| `<prefix>_pulsetable`         | `(speed, target_hi)` rows, `$ff,$00` end |
| `<prefix>_filtertable`        | `(cutoff_hi, res\|rt, mode)` row        |
| `<prefix>_freq_lo/_freq_hi`   | 16-bit SID frequency register            |
| `<prefix>_volume`             | `$00..$0f`                              |
| `<prefix>_gate_frames`        | 16-bit frame count                      |
| `<prefix>_release_frames`     | 16-bit frame count                      |

Table row layout follows the GoatTracker convention, so the same .asm can
be consumed by a GT-style playroutine or a bespoke driver.

Every field of `SidParams` is preserved; the parser reads `; @meta k=v`
comment lines to recover the original Python values including floats
(`frequency`) and the pair-list tables (`pw_table`, `wavetable`).

Reference: GoatTracker readme describes the underlying table layout
<https://github.com/leafo/goattracker2/blob/master/readme.txt>.

## `goattracker.py` - GT2 `.ins` binary  [WORKING, round-trip tested]

GoatTracker 2.x instrument file format (magic `GTI5`):

```
+0    4   "GTI5"
+4    1   AD (attack<<4 | decay)
+5    1   SR (sustain<<4 | release)
+6    1   wavepointer
+7    1   pulsepointer
+8    1   filterpointer
+9    1   vibrato param (speedtable pointer)
+10   1   vibrato delay
+11   1   gateoff timer
+12   1   hard-restart / first-frame waveform byte
+13  16   instrument name, zero-padded ASCII
+29  ...  wavetable    : 1 byte n, n left bytes, n right bytes
     ...  pulsetable   : 1 byte n, n left bytes, n right bytes
     ...  filtertable  : 1 byte n, n left bytes, n right bytes
     ...  speedtable   : 1 byte n, n left bytes, n right bytes
```

Sources:

* <https://github.com/leafo/goattracker2/blob/master/readme.txt> (canonical
  README by Cadaver, shipped with GT 2.76)
* <https://github.com/jpage8580/GTUltra/blob/master/readme%20-%20OriginalGT2%20Documentation.txt>
* <http://phd-sid.ethz.ch/debian/goattracker/goattracker/readme.txt>

**Fields preserved**: ADSR, waveform (including `ring_mod`/`sync` OR-ed into
the wavetable rows), `pulse_width`/`pw_table` (as pulsetable speed/target
rows), filter cutoff/resonance/mode/voice1-routing (as a filtertable row).

**Fields that DO NOT fit the .ins model**:

* `frequency` - GT instruments are note-agnostic; pitch comes from patterns.
* `gate_frames`, `release_frames` - not an instrument property.
* `volume` - GT master volume is song-global.
* `wavetable`/`pw_table` frame indices - GT tables are advanced per tick,
  so the per-row "frame" number is dropped; only the sequence is kept.

On load, GoatTracker appends the embedded tables to the song's global tables
and rewrites the three pointer bytes, so the concrete `wavepointer` value in
a freshly-saved .ins is the offset into the empty-song tables (usually `1`).

## `sidwizard.py` - SID-Wizard `.swi`  [STUB, format unverified]

See the module docstring. A web search did not turn up an authoritative
byte-level specification for SID-Wizard instruments - the format is defined
implicitly in the tracker's 6502 assembly source. Until a reference .swi
instrument is round-tripped against the SID-Wizard source, `encode_sidwizard`
and `parse_sidwizard` raise `NotImplementedError`.

Starting points for a future implementation:

* <https://github.com/anarkiwi/sid-wizard> - tracker source in 64tass syntax
* <https://csdb.dk/getinternalfile.php/125509/SID-Wizard-1.5-UserManual.pdf>
* <https://sourceforge.net/projects/sid-wizard/>
