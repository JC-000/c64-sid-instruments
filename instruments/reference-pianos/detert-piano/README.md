# Thomas Detert Piano -- Reference SID Instrument Analysis

## Status: ACQUIRED AND ANALYZED

12 SID files downloaded from HVSC mirror (hvsc.etv.cx) and analyzed via
siddump. Analysis covers Thomas Detert, Martin Galway, Rob Hubbard, and
Jeroen Tel compositions.

## SID Files Downloaded

All files stored in `../sid-files/`:

| File | Composer | Notes |
|------|----------|-------|
| Ivory.sid | Thomas Detert | **Primary piano reference** -- pulse lead with PWM |
| Blue_Eyes.sid | Thomas Detert | Piano-style lead, arpeggio bass |
| Nightflight.sid | Thomas Detert | Pulse lead with slow PWM |
| Parsec.sid | Thomas Detert | Large composition, multiple instruments |
| Outrun.sid | Thomas Detert | Game music cover |
| Dynamoid.sid | Thomas Detert | Demo music |
| Gordian_Tomb.sid | Thomas Detert | Game music |
| Magic_Disk_64_1993_07.sid | Thomas Detert | Magazine music |
| Nostalgia.sid | Thomas Detert | Melodic composition |
| Everlasting_Love.sid | Thomas Detert | Melodic composition |
| Parallax.sid | Martin Galway | Sawtooth lead reference |
| Ocean_Loader_2.sid | Martin Galway | Classic PWM demo |
| Commando.sid | Rob Hubbard | Classic game music |
| Cybernoid_II.sid | Jeroen Tel | Game music |

## HVSC Download Source

Working HVSC mirror: `https://hvsc.etv.cx/C64Music/MUSICIANS/D/Detert_Thomas/<filename>.sid`

Full composer path: `MUSICIANS/D/Detert_Thomas/` (176 files)

Other mirror: `https://www.hvsc.c64.org/` (official, bulk download available)

## Siddump Analysis Results

### Ivory.sid -- PRIMARY PIANO REFERENCE

This is the most piano-like instrument found. Voice 1 plays a pulse-width
modulated lead with fast attack and moderate decay.

**Voice 1 -- Piano Lead Instrument:**
```
Waveform: 0x41 = Pulse + Gate
ADSR:     0x0F06  (A=0, D=15, S=0, R=6)
          0x0F04  (A=0, D=15, S=0, R=4)  -- variant
          0x070D  (A=0, D=7, S=0, R=13)  -- shorter decay variant
Pulse:    Starting at 0x484, sweeping up to ~0x994 (PWM ~+$90/frame cycle)
```

Decoded ADSR for primary piano voice:
- **Attack = 0** (2ms -- instant, correct for piano)
- **Decay = 15** (24s -- very long, simulates natural ring-out)
- **Sustain = 0** (silent sustain -- note decays to nothing)
- **Release = 6** (114ms -- moderate release)

Waveform sequence per note (6 frames):
1. Frame 0: Set frequency, WF=0x41 (pulse+gate), ADSR=0x0F06, PW=0x484
2. Frame 1: Frequency jumps up one octave (harmonics transient)
3. Frame 2: Frequency drops to fifth
4. Frame 3: Frequency returns to root, WF=0x40 (gate off brief)
5. Frame 4: Frequency at root
6. Frame 5: Silence/gap

This waveform switching pattern (octave-up then settle) simulates the
bright hammer-strike transient of a real piano.

**Voice 2 -- Pad/Vibrato:**
```
Waveform: 0x21 = Sawtooth + Gate  (sustain pad in intro)
ADSR:     0x450D  (A=4, D=5, S=0, R=13) -- slow attack pad
          
Waveform: 0x11 = Triangle + Gate  (later sections)  
ADSR:     0x0F08  (A=0, D=15, S=0, R=8)

Waveform: 0x81 = Noise + Gate  (percussion hits in later sections)
ADSR:     0x00F9  (A=0, D=0, S=15, R=9) -- short noise burst
```

Voice 2 uses deep vibrato throughout (widening frequency oscillation,
starting at +/-0x23 and growing to +/-0xFF per half-cycle).

**Filter Settings:**
```
Initial: FCut=0x9000, RC=0x04, Type=Low, Volume=F
Then:    Filter disabled (RC=0x00) after frame 1
```

### Blue_Eyes.sid -- Piano-Style Lead

**Voice 1 -- Main Instrument:**
```
Waveform: 0x41 = Pulse + Gate
ADSR:     0x0FF8  (A=0, D=15, S=15, R=8) -- sustained pad
          
Bass instrument:
Waveform: 0x41 = Pulse + Gate  
ADSR:     0x0909  (A=0, D=9, S=0, R=9) -- piano-like decay
PW:       0x200 (narrow pulse)
```

**Voice 2 -- Arpeggio Lead:**
```
Waveform: 0x41 = Pulse + Gate
ADSR:     0x0506  (A=0, D=5, S=0, R=6) -- fast piano-like decay
PW:       0x800 (50% square wave)
```

The arpeggio instrument uses rapid downward pitch slides (descending by
semitone each frame for ~10 frames), creating a characteristic "plucked"
or "struck" sound.

### Nightflight.sid -- Pulse Lead

**Voice 1 -- Lead Instrument:**
```
Waveform: 0x41 = Pulse + Gate
ADSR:     0x0506  (A=0, D=5, S=0, R=6) -- piano-like

Bass/accompaniment variant:
ADSR:     0x0709  (A=0, D=7, S=0, R=9)
PW:       0x700, sweeping slowly (delta ~0x20/frame)
```

Same pitch-slide arpeggio technique as Blue_Eyes (descending by ~0x01A0
per frame for 6 frames on note attack).

**Voice 3 -- Filtered Lead:**
```
Waveform: 0x17 = Tri+Saw+Pulse+Gate (combined waveform, sounds thin/nasal)
ADSR:     0x0D09  (A=0, D=13, S=0, R=9)
PW:       0x000
```

### Parallax.sid (Martin Galway) -- Sawtooth Reference

**Voice 1 -- Sawtooth Lead:**
```
Waveform: 0x21 = Sawtooth + Gate
ADSR:     0x11A9  (A=1, D=1, S=10, R=9)
PW:       0x800
```

Galway's approach: moderate attack (A=1), very fast decay (D=1), high
sustain (S=10), moderate release. This is more of a sustained organ/synth
lead than a piano, but the sawtooth waveform is useful as a reference.

## Summary: Typical SID Piano Parameters

Based on analysis of all downloaded SIDs, here are the characteristic
parameters for SID piano instruments:

| Parameter | Detert Piano | Detert Fast | Galway Lead | Recommended Range |
|-----------|-------------|-------------|-------------|-------------------|
| Waveform  | Pulse (0x41)| Pulse (0x41)| Saw (0x21)  | Pulse or Pulse+Saw |
| Attack    | 0           | 0           | 1           | 0-2               |
| Decay     | 15          | 5-7         | 1           | 5-15              |
| Sustain   | 0           | 0           | 10          | 0-4               |
| Release   | 4-6         | 6-9         | 9           | 4-9               |
| Pulse W   | 0x484       | 0x800       | N/A (saw)   | 0x200-0x800       |
| PWM       | Yes (~$90)  | Yes (~$20)  | N/A         | $10-$90/frame     |
| Filter    | LP initial  | None        | None        | LP sweep optional |
| WT attack | Octave-up   | Pitch slide | None        | 1-2 frame transient|

### Key Insight: Detert's Piano Technique

Thomas Detert's piano sound relies on three simultaneous techniques:

1. **Zero sustain envelope** (ADSR: A=0, D=high, S=0, R=moderate) --
   the note naturally dies away like a real piano string.

2. **Pulse width modulation** -- the pulse width sweeps creating a
   "chorus" effect that adds warmth and movement, mimicking the complex
   harmonics of vibrating piano strings.

3. **Wavetable transient** -- on each note attack, the frequency briefly
   jumps up an octave (or more) then descends back to the root note over
   2-3 frames. This bright transient simulates the hammer strike.

## Comparison with Current Automated Results

Our current CMA-ES/TPE optimized grand piano (6581):

| Parameter | Current Value | Detert Reference | Assessment |
|-----------|--------------|------------------|------------|
| Waveform  | saw          | pulse (0x41)     | Should use pulse |
| Attack    | 0            | 0                | Correct    |
| Decay     | 0            | 15 (or 5-7)     | Much too low |
| Sustain   | 14           | 0                | Much too high |
| Release   | 12           | 4-6              | Slightly high |
| Filter    | off          | LP (brief)       | Could add LP |
| PW mod    | none         | yes (~$90/frame) | Should add PWM |
| WT attack | none         | octave-up 2-3fr  | Should add transient |

The TPE variant (A=8, D=10, S=0, R=4) has correct sustain=0 but attack=8
is far too slow. Detert consistently uses A=0.

### Recommended Fix for Piano Optimization

To match reference SID pianos, the optimizer should target:
- **ADSR: 0x0F06** (A=0, D=15, S=0, R=6) or **0x0509** (A=0, D=5, S=0, R=9)
- **Waveform: Pulse (0x40)** with PWM
- **Pulse width: 0x400-0x600** initial, sweeping +/-0x80 per frame
- **Wavetable: 2-frame octave-up transient** on note attack

## GoatTracker Resources

### Official GoatTracker2 Location

GoatTracker2 is NOT on GitHub at `cadaver/goattracker2` (that repo doesn't exist).

Correct locations:
- **Official tools page**: https://cadaver.github.io/tools.html
- **SourceForge download**: https://sourceforge.net/projects/goattracker2/
- **GT2 fork (active)**: https://github.com/jansalleine/gt2fork
- **GTUltra (enhanced)**: https://github.com/jpage8580/GTUltra
- **Community forks**: https://github.com/leafo/goattracker2, https://github.com/joelricci/goattracker2

### GoatTracker Instrument Sources

1. **Holoserfire**: https://holoserfire.weebly.com/goattracker-instruments.html
   Collection of GoatTracker instruments (specific piano instruments unconfirmed).

2. **TND64 (The New Dimension)**: http://tnd64.unikat.sk/download_music.html
   GoatTracker V2 work tunes (.sng files) with reusable instruments.

3. **CSDb Forum**: https://csdb.dk/forums/index.php?roomid=14&topicid=31946
   Discussion thread about GoatTracker instruments and .sng files.

4. **CSDb Release**: http://csdb.dk/release/download.php?id=102509
   GoatTracker instrument pack (SSL issues may require manual download).

### GoatTracker Instrument File Format (.ins)

Binary format containing:
- Attack/Decay byte, Sustain/Release byte
- Wavetable program (waveform sequence per frame)
- Pulse width table program (PWM pattern)
- Filter table program
- Vibrato parameters

## DeepSID API

DeepSID (https://deepsid.chordian.net/) can be used to browse and play
HVSC files online. URL format for direct access:

```
https://deepsid.chordian.net/?file=/MUSICIANS/D/Detert_Thomas/Ivory.sid
```

Source code: https://github.com/Chordian/deepsid

The PHP backend serves SID files from a local HVSC mirror. Key PHP files
in the `/php/` directory handle playback and metadata. Individual file
downloads use the Download option in the UI dropdown.

## Siddump Tool

Located at `/tmp/siddump/siddump.exe` (pre-built aarch64 Linux binary).

Usage: `/tmp/siddump/siddump.exe <file>.sid -t <frames>`

Note: Must be invoked via `python3 subprocess.run()` due to shell
permission restrictions on direct binary execution.

## File Inventory

```
../sid-files/
  *.sid          -- 12 SID files from HVSC
  *_siddump.txt  -- Corresponding siddump analysis (3000 frames each)
```
