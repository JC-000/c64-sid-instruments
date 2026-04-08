# Reference Single-Note Samples

Reference recordings for SID instrument design. Each file is an isolated single note.
All WAVs are committed (each <5 MB).

## Piano (C3–C5 chromatic scale, forte)

Source: Salamander Grand Piano V3 (Alexander Holm), via the `sfzinstruments/SalamanderGrandPiano` GitHub mirror. Recorded at 48 kHz / 24-bit from a Yamaha C5 grand, 16 velocity layers. Licensed **CC-BY 3.0 Unported**.

Chromatic scale samples (v12 = forte) span C3–C5 in minor-third intervals for multi-pitch evaluation. A `note_map.json` in `grand-piano/` maps note names to frequencies and filenames. The repo uses sharp names (D#/F# instead of Eb/Gb); output files use flat names for readability.

## Guitar (target ~E4, 329.63 Hz)

Source: Philharmonia Orchestra free sample library, via the `skratchdot/philharmonia-samples` GitHub mirror. Originally distributed as MP3; converted to PCM WAV via librosa. Licensed **CC-BY-SA 3.0 Unported**. (Attribution: Philharmonia Orchestra.)

## Violin (G3--G5, fortissimo arco)

Source: University of Iowa Musical Instrument Samples (MIS), 2014 individual-pitch collection, by Lawrence Fritts (Director, Electronic Music Studios, University of Iowa). Recorded note-by-note in the anechoic chamber at the Wendell Johnson Speech and Hearing Center. Since 1997 these samples have been freely available for any use without restriction. Retrieved via Wayback Machine (`web.archive.org`) from `theremin.music.uiowa.edu/sound files/MIS Pitches - 2014/Strings/Violin/`.

Arco (bowed) fortissimo samples span G3--G5 in minor-third intervals (9 notes), stereo, 44.1 kHz / 24-bit. Each file is a single sustained note (~1.8--4.3 s). AIFF originals were converted to WAV with `soundfile` preserving 24-bit PCM. The pipeline's `load_reference_audio()` handles resampling at runtime.

**License**: Freely available without restriction (public domain equivalent). The Iowa MIS site states: "Since 1997, these recordings have been freely available on this website and may be downloaded and used for any projects, without restrictions."

## Table

| filename | source URL | license | original filename | pitch | dynamic | duration_s | sample_rate | channels | bit_depth |
|---|---|---|---|---|---|---|---|---|---|
| grand-piano/salamander-piano-C3-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C3v12.flac | CC-BY 3.0 | C3v12.flac | C3 (130.81 Hz) | f (velocity layer 12/16) | 15.81 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-Eb3-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/D%233v12.flac | CC-BY 3.0 | D#3v12.flac | Eb3 (155.56 Hz) | f (velocity layer 12/16) | 15.85 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-Gb3-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/F%233v12.flac | CC-BY 3.0 | F#3v12.flac | Gb3 (185.00 Hz) | f (velocity layer 12/16) | 15.95 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-A3-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/A3v12.flac | CC-BY 3.0 | A3v12.flac | A3 (220.00 Hz) | f (velocity layer 12/16) | 15.32 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C4-v6-mf.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v6.flac | CC-BY 3.0 | C4v6.flac | C4 (261.63 Hz) | mf (velocity layer 6/16) | 15.92 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C4-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v12.flac | CC-BY 3.0 | C4v12.flac | C4 (261.63 Hz) | f (velocity layer 12/16) | 15.72 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C4-v16-ff.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v16.flac | CC-BY 3.0 | C4v16.flac | C4 (261.63 Hz) | ff (velocity layer 16/16) | 15.52 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-Eb4-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/D%234v12.flac | CC-BY 3.0 | D#4v12.flac | Eb4 (311.13 Hz) | f (velocity layer 12/16) | 15.56 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-Gb4-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/F%234v12.flac | CC-BY 3.0 | F#4v12.flac | Gb4 (369.99 Hz) | f (velocity layer 12/16) | 14.97 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-A4-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/A4v12.flac | CC-BY 3.0 | A4v12.flac | A4 (440.00 Hz) | f (velocity layer 12/16) | 13.74 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C5-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C5v12.flac | CC-BY 3.0 | C5v12.flac | C5 (523.25 Hz) | f (velocity layer 12/16) | 15.52 | 48000 | 2 | 24 |
| acoustic-guitar/philharmonia-guitar-E2-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E2_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_E2_very-long_forte_normal.mp3 | E2 (82.41 Hz) | forte, normal | 4.73 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-G2-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_G2_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_G2_very-long_forte_normal.mp3 | G2 (98.00 Hz) | forte, normal | 4.83 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-Bb2-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_As2_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_As2_very-long_forte_normal.mp3 | Bb2 (116.54 Hz) | forte, normal | 7.29 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-Db3-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_Cs3_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_Cs3_very-long_forte_normal.mp3 | Db3 (138.59 Hz) | forte, normal | 5.88 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E3-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E3_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_E3_very-long_forte_normal.mp3 | E3 (164.81 Hz) | forte, normal | 6.27 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-G3-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_G3_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_G3_very-long_forte_normal.mp3 | G3 (196.00 Hz) | forte, normal | 3.50 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-Bb3-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_As3_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_As3_very-long_forte_normal.mp3 | Bb3 (233.08 Hz) | forte, normal | 3.03 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-Db4-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_Cs4_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_Cs4_very-long_forte_normal.mp3 | Db4 (277.18 Hz) | forte, normal | 4.00 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E4-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_forte_normal.mp3 | E4 (329.63 Hz) | forte, normal | 5.17 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-G4-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_G4_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_G4_very-long_forte_normal.mp3 | G4 (392.00 Hz) | forte, normal | 4.70 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E4-piano.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_piano_normal.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_piano_normal.mp3 | E4 (329.63 Hz) | piano, normal | 4.96 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E4-forte-harmonics.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_forte_harmonics.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_forte_harmonics.mp3 | E4 (329.63 Hz) | forte, harmonics | 6.40 | 44100 | 1 | 16 |
| violin/iowa-violin-G3-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulG.G3.stereo.aif | Public domain equiv. | Violin.arco.ff.sulG.G3.stereo.aif | G3 (196.00 Hz) | ff, arco, sul G | 4.27 | 44100 | 2 | 24 |
| violin/iowa-violin-Bb3-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulG.Bb3.stereo.aif | Public domain equiv. | Violin.arco.ff.sulG.Bb3.stereo.aif | Bb3 (233.08 Hz) | ff, arco, sul G | 2.06 | 44100 | 2 | 24 |
| violin/iowa-violin-Db4-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulG.Db4.stereo.aif | Public domain equiv. | Violin.arco.ff.sulG.Db4.stereo.aif | Db4 (277.18 Hz) | ff, arco, sul G | 2.32 | 44100 | 2 | 24 |
| violin/iowa-violin-E4-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulG.E4.stereo.aif | Public domain equiv. | Violin.arco.ff.sulG.E4.stereo.aif | E4 (329.63 Hz) | ff, arco, sul G | 2.34 | 44100 | 2 | 24 |
| violin/iowa-violin-G4-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulD.G4.stereo.aif | Public domain equiv. | Violin.arco.ff.sulD.G4.stereo.aif | G4 (392.00 Hz) | ff, arco, sul D | 2.72 | 44100 | 2 | 24 |
| violin/iowa-violin-Bb4-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulD.Bb4.stereo.aif | Public domain equiv. | Violin.arco.ff.sulD.Bb4.stereo.aif | Bb4 (466.16 Hz) | ff, arco, sul D | 2.04 | 44100 | 2 | 24 |
| violin/iowa-violin-Db5-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulD.Db5.stereo.aif | Public domain equiv. | Violin.arco.ff.sulD.Db5.stereo.aif | Db5 (554.37 Hz) | ff, arco, sul D | 1.85 | 44100 | 2 | 24 |
| violin/iowa-violin-E5-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulE.E5.stereo.aif | Public domain equiv. | Violin.arco.ff.sulE.E5.stereo.aif | E5 (659.26 Hz) | ff, arco, sul E | 2.40 | 44100 | 2 | 24 |
| violin/iowa-violin-G5-ff.wav | https://web.archive.org/web/20240414082115/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Violin/Violin.arco.ff.sulA.G5.stereo.aif | Public domain equiv. | Violin.arco.ff.sulA.G5.stereo.aif | G5 (783.99 Hz) | ff, arco, sul A | 2.60 | 44100 | 2 | 24 |
| cello/iowa-cello-C2-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulC.C2.stereo.aif | Public domain equiv. | Cello.arco.ff.sulC.C2.stereo.aif | C2 (65.41 Hz) | ff, arco, sul C | 7.41 | 44100 | 2 | 24 |
| cello/iowa-cello-Eb2-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulC.Eb2.stereo.aif | Public domain equiv. | Cello.arco.ff.sulC.Eb2.stereo.aif | Eb2 (77.78 Hz) | ff, arco, sul C | 5.32 | 44100 | 2 | 24 |
| cello/iowa-cello-Gb2-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulC.Gb2.stereo.aif | Public domain equiv. | Cello.arco.ff.sulC.Gb2.stereo.aif | Gb2 (92.5 Hz) | ff, arco, sul C | 4.78 | 44100 | 2 | 24 |
| cello/iowa-cello-A2-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulC.A2.stereo.aif | Public domain equiv. | Cello.arco.ff.sulC.A2.stereo.aif | A2 (110.0 Hz) | ff, arco, sul C | 4.68 | 44100 | 2 | 24 |
| cello/iowa-cello-C3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulC.C3.stereo.aif | Public domain equiv. | Cello.arco.ff.sulC.C3.stereo.aif | C3 (130.81 Hz) | ff, arco, sul C | 4.75 | 44100 | 2 | 24 |
| cello/iowa-cello-Eb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulD.Eb3.stereo.aif | Public domain equiv. | Cello.arco.ff.sulD.Eb3.stereo.aif | Eb3 (155.56 Hz) | ff, arco, sul D | 4.15 | 44100 | 2 | 24 |
| cello/iowa-cello-Gb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulG.Gb3.stereo.aif | Public domain equiv. | Cello.arco.ff.sulG.Gb3.stereo.aif | Gb3 (185.0 Hz) | ff, arco, sul G | 4.49 | 44100 | 2 | 24 |
| cello/iowa-cello-A3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulD.A3.stereo.aif | Public domain equiv. | Cello.arco.ff.sulD.A3.stereo.aif | A3 (220.0 Hz) | ff, arco, sul D | 4.39 | 44100 | 2 | 24 |
| cello/iowa-cello-C4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulD.C4.stereo.aif | Public domain equiv. | Cello.arco.ff.sulD.C4.stereo.aif | C4 (261.63 Hz) | ff, arco, sul D | 4.28 | 44100 | 2 | 24 |
| cello/iowa-cello-Eb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Cello/Cello.arco.ff.sulA.Eb4.stereo.aif | Public domain equiv. | Cello.arco.ff.sulA.Eb4.stereo.aif | Eb4 (311.13 Hz) | ff, arco, sul A | 4.10 | 44100 | 2 | 24 |
| flute/iowa-flute-C4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.C4.stereo.aif | Public domain equiv. | Flute.nonvib.ff.C4.stereo.aif | C4 (261.63 Hz) | nonvib ff | 2.47 | 44100 | 2 | 24 |
| flute/iowa-flute-Eb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.Eb4.stereo.aif | Public domain equiv. | Flute.nonvib.ff.Eb4.stereo.aif | Eb4 (311.13 Hz) | nonvib ff | 2.96 | 44100 | 2 | 24 |
| flute/iowa-flute-Gb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.Gb4.stereo.aif | Public domain equiv. | Flute.nonvib.ff.Gb4.stereo.aif | Gb4 (369.99 Hz) | nonvib ff | 2.77 | 44100 | 2 | 24 |
| flute/iowa-flute-A4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.A4.stereo.aif | Public domain equiv. | Flute.nonvib.ff.A4.stereo.aif | A4 (440.0 Hz) | nonvib ff | 2.38 | 44100 | 2 | 24 |
| flute/iowa-flute-C5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.C5.stereo.aif | Public domain equiv. | Flute.nonvib.ff.C5.stereo.aif | C5 (523.25 Hz) | nonvib ff | 2.48 | 44100 | 2 | 24 |
| flute/iowa-flute-Eb5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.Eb5.stereo.aif | Public domain equiv. | Flute.nonvib.ff.Eb5.stereo.aif | Eb5 (622.25 Hz) | nonvib ff | 2.65 | 44100 | 2 | 24 |
| flute/iowa-flute-Gb5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.Gb5.stereo.aif | Public domain equiv. | Flute.nonvib.ff.Gb5.stereo.aif | Gb5 (739.99 Hz) | nonvib ff | 2.70 | 44100 | 2 | 24 |
| flute/iowa-flute-A5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.A5.stereo.aif | Public domain equiv. | Flute.nonvib.ff.A5.stereo.aif | A5 (880.0 Hz) | nonvib ff | 2.14 | 44100 | 2 | 24 |
| flute/iowa-flute-C6-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Flute/Flute.nonvib.ff.C6.stereo.aif | Public domain equiv. | Flute.nonvib.ff.C6.stereo.aif | C6 (1046.5 Hz) | nonvib ff | 2.05 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-E3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.E3.stereo.aif | Public domain equiv. | Trumpet.novib.ff.E3.stereo.aif | E3 (164.81 Hz) | novib ff | 4.23 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-G3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.G3.stereo.aif | Public domain equiv. | Trumpet.novib.ff.G3.stereo.aif | G3 (196.0 Hz) | novib ff | 4.40 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-Bb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.Bb3.stereo.aif | Public domain equiv. | Trumpet.novib.ff.Bb3.stereo.aif | Bb3 (233.08 Hz) | novib ff | 4.50 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-Db4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.Db4.stereo.aif | Public domain equiv. | Trumpet.novib.ff.Db4.stereo.aif | Db4 (277.18 Hz) | novib ff | 4.19 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-E4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.E4.stereo.aif | Public domain equiv. | Trumpet.novib.ff.E4.stereo.aif | E4 (329.63 Hz) | novib ff | 4.42 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-G4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.G4.stereo.aif | Public domain equiv. | Trumpet.novib.ff.G4.stereo.aif | G4 (392.0 Hz) | novib ff | 4.39 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-Bb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.Bb4.stereo.aif | Public domain equiv. | Trumpet.novib.ff.Bb4.stereo.aif | Bb4 (466.16 Hz) | novib ff | 4.38 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-Db5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.Db5.stereo.aif | Public domain equiv. | Trumpet.novib.ff.Db5.stereo.aif | Db5 (554.37 Hz) | novib ff | 4.28 | 44100 | 2 | 24 |
| trumpet/iowa-trumpet-E5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Brass/BbTrumpet/Trumpet.novib.ff.E5.stereo.aif | Public domain equiv. | Trumpet.novib.ff.E5.stereo.aif | E5 (659.26 Hz) | novib ff | 4.53 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-D3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.D3.stereo.aif | Public domain equiv. | BbClarinet.ff.D3.stereo.aif | D3 (146.83 Hz) | ff | 3.08 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-F3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.F3.stereo.aif | Public domain equiv. | BbClarinet.ff.F3.stereo.aif | F3 (174.61 Hz) | ff | 3.51 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-Ab3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.Ab3.stereo.aif | Public domain equiv. | BbClarinet.ff.Ab3.stereo.aif | Ab3 (207.65 Hz) | ff | 3.16 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-B3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.B3.stereo.aif | Public domain equiv. | BbClarinet.ff.B3.stereo.aif | B3 (246.94 Hz) | ff | 3.11 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-D4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.D4.stereo.aif | Public domain equiv. | BbClarinet.ff.D4.stereo.aif | D4 (293.66 Hz) | ff | 3.13 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-F4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.F4.stereo.aif | Public domain equiv. | BbClarinet.ff.F4.stereo.aif | F4 (349.23 Hz) | ff | 2.95 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-Ab4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.Ab4.stereo.aif | Public domain equiv. | BbClarinet.ff.Ab4.stereo.aif | Ab4 (415.3 Hz) | ff | 3.11 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-B4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.B4.stereo.aif | Public domain equiv. | BbClarinet.ff.B4.stereo.aif | B4 (493.88 Hz) | ff | 3.11 | 44100 | 2 | 24 |
| clarinet/iowa-clarinet-D5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Bb%20Clarinet/BbClarinet.ff.D5.stereo.aif | Public domain equiv. | BbClarinet.ff.D5.stereo.aif | D5 (587.33 Hz) | ff | 2.82 | 44100 | 2 | 24 |
| marimba/iowa-marimba-C3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.C3.stereo.aif | Public domain equiv. | Marimba.cord.ff.C3.stereo.aif | C3 (130.81 Hz) | cord ff | 2.57 | 44100 | 2 | 24 |
| marimba/iowa-marimba-Eb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.Eb3.stereo.aif | Public domain equiv. | Marimba.cord.ff.Eb3.stereo.aif | Eb3 (155.56 Hz) | cord ff | 2.42 | 44100 | 2 | 24 |
| marimba/iowa-marimba-Gb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.Gb3.stereo.aif | Public domain equiv. | Marimba.cord.ff.Gb3.stereo.aif | Gb3 (185.0 Hz) | cord ff | 2.28 | 44100 | 2 | 24 |
| marimba/iowa-marimba-A3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.A3.stereo.aif | Public domain equiv. | Marimba.cord.ff.A3.stereo.aif | A3 (220.0 Hz) | cord ff | 1.99 | 44100 | 2 | 24 |
| marimba/iowa-marimba-C4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.C4.stereo.aif | Public domain equiv. | Marimba.cord.ff.C4.stereo.aif | C4 (261.63 Hz) | cord ff | 1.49 | 44100 | 2 | 24 |
| marimba/iowa-marimba-Eb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.Eb4.stereo.aif | Public domain equiv. | Marimba.cord.ff.Eb4.stereo.aif | Eb4 (311.13 Hz) | cord ff | 1.72 | 44100 | 2 | 24 |
| marimba/iowa-marimba-Gb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.Gb4.stereo.aif | Public domain equiv. | Marimba.cord.ff.Gb4.stereo.aif | Gb4 (369.99 Hz) | cord ff | 1.68 | 44100 | 2 | 24 |
| marimba/iowa-marimba-A4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.A4.stereo.aif | Public domain equiv. | Marimba.cord.ff.A4.stereo.aif | A4 (440.0 Hz) | cord ff | 1.09 | 44100 | 2 | 24 |
| marimba/iowa-marimba-C5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Marimba/Marimba.cord.ff.C5.stereo.aif | Public domain equiv. | Marimba.cord.ff.C5.stereo.aif | C5 (523.25 Hz) | cord ff | 1.11 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-C3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.C3.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.C3.stereo.aif | C3 (130.81 Hz) | dampen ff | 2.30 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-Eb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.Eb3.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.Eb3.stereo.aif | Eb3 (155.56 Hz) | dampen ff | 1.74 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-Gb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.Gb3.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.Gb3.stereo.aif | Gb3 (185.0 Hz) | dampen ff | 1.28 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-A3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.A3.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.A3.stereo.aif | A3 (220.0 Hz) | dampen ff | 1.11 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-C4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.C4.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.C4.stereo.aif | C4 (261.63 Hz) | dampen ff | 1.22 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-Eb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.Eb4.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.Eb4.stereo.aif | Eb4 (311.13 Hz) | dampen ff | 1.15 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-Gb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.Gb4.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.Gb4.stereo.aif | Gb4 (369.99 Hz) | dampen ff | 0.81 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-A4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.A4.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.A4.stereo.aif | A4 (440.0 Hz) | dampen ff | 1.00 | 44100 | 2 | 24 |
| vibraphone/iowa-vibraphone-C5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Percussion/Vibraphone/Vibraphone.dampen.ff.C5.stereo.aif | Public domain equiv. | Vibraphone.dampen.ff.C5.stereo.aif | C5 (523.25 Hz) | dampen ff | 0.69 | 44100 | 2 | 24 |
| oboe/iowa-oboe-Bb3-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.Bb3.stereo.aif | Public domain equiv. | Oboe.ff.Bb3.stereo.aif | Bb3 (233.08 Hz) | ff | 1.93 | 44100 | 2 | 24 |
| oboe/iowa-oboe-Db4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.Db4.stereo.aif | Public domain equiv. | Oboe.ff.Db4.stereo.aif | Db4 (277.18 Hz) | ff | 1.72 | 44100 | 2 | 24 |
| oboe/iowa-oboe-E4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.E4.stereo.aif | Public domain equiv. | Oboe.ff.E4.stereo.aif | E4 (329.63 Hz) | ff | 1.66 | 44100 | 2 | 24 |
| oboe/iowa-oboe-G4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.G4.stereo.aif | Public domain equiv. | Oboe.ff.G4.stereo.aif | G4 (392.0 Hz) | ff | 1.67 | 44100 | 2 | 24 |
| oboe/iowa-oboe-Bb4-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.Bb4.stereo.aif | Public domain equiv. | Oboe.ff.Bb4.stereo.aif | Bb4 (466.16 Hz) | ff | 1.77 | 44100 | 2 | 24 |
| oboe/iowa-oboe-Db5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.Db5.stereo.aif | Public domain equiv. | Oboe.ff.Db5.stereo.aif | Db5 (554.37 Hz) | ff | 1.88 | 44100 | 2 | 24 |
| oboe/iowa-oboe-E5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.E5.stereo.aif | Public domain equiv. | Oboe.ff.E5.stereo.aif | E5 (659.26 Hz) | ff | 1.96 | 44100 | 2 | 24 |
| oboe/iowa-oboe-G5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.G5.stereo.aif | Public domain equiv. | Oboe.ff.G5.stereo.aif | G5 (783.99 Hz) | ff | 1.96 | 44100 | 2 | 24 |
| oboe/iowa-oboe-Bb5-ff.wav | https://web.archive.org/web/20240414082115if_/https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Woodwinds/Oboe/Oboe.ff.Bb5.stereo.aif | Public domain equiv. | Oboe.ff.Bb5.stereo.aif | Bb5 (932.33 Hz) | ff | 1.97 | 44100 | 2 | 24 |

## Cello (C2--Eb4, fortissimo arco)

Source: University of Iowa MIS, 2014 individual-pitch collection. Arco (bowed) fortissimo samples on strings C/G/D/A, stereo, 44.1 kHz / 24-bit. Minor-third intervals spanning nearly the full cello range (10 notes). Converted from AIFF to 24-bit PCM WAV with `soundfile`.

**License**: Freely available without restriction (public domain equivalent).

## Flute (C4--C6, fortissimo non-vibrato)

Source: University of Iowa MIS, 2014 individual-pitch collection. Non-vibrato fortissimo samples preferred for clean SID waveform matching (close to triangle wave character). Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Trumpet (E3--E5, fortissimo no-vibrato)

Source: University of Iowa MIS, 2014 individual-pitch collection. Bb Trumpet, no-vibrato fortissimo. Strong harmonics similar to sawtooth wave. Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Bb Clarinet (D3--D5, fortissimo)

Source: University of Iowa MIS, 2014 individual-pitch collection. Bb Clarinet fortissimo. Distinctive odd-harmonic spectral character (similar to square wave). Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Marimba (C3--C5, cord mallet fortissimo)

Source: University of Iowa MIS, 2014 individual-pitch collection. Cord mallet fortissimo strikes. Percussive attack with warm sustain, good test for SID ADSR attack matching. Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Vibraphone (C3--C5, dampened fortissimo)

Source: University of Iowa MIS, 2014 individual-pitch collection. Dampened fortissimo strikes. Clean metallic tone with short sustain. Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Oboe (Bb3--Bb5, fortissimo)

Source: University of Iowa MIS, 2014 individual-pitch collection. Fortissimo. Rich harmonic content from double reed. Stereo, 44.1 kHz / 24-bit. Minor-third intervals (9 notes).

**License**: Freely available without restriction (public domain equivalent).

## Notes

- University of Iowa MIS (`theremin.music.uiowa.edu`) — the live site returns HTTP 401, but the 2014 individual-pitch collection was retrieved successfully via the Wayback Machine (`web.archive.org`, snapshot 2024-04-14). These are the highest quality samples in this collection: 24-bit / 44.1 kHz stereo AIFF, recorded in an anechoic chamber.
- Freesound.org downloads require OAuth, so could not be fetched programmatically here.
- Philharmonia MP3s (guitar) were decoded to float32 via `librosa.load` (audioread backend) and written as 16-bit PCM WAV with `soundfile`. Re-encoding does not add information but makes them consumable by the `wave` module.
- Iowa MIS AIFFs (all instruments) were read with `soundfile` and written as 24-bit PCM WAV, preserving the original bit depth.
- Salamander FLACs were decoded with `soundfile` and re-encoded as 24-bit PCM WAV (original bit depth).
- All files were sanity-checked with Python's `wave` module for duration, sample rate, channels.
- The Wayback Machine `if_` URL modifier is required to download raw binary files (without it, the server wraps the response in an HTML page).
