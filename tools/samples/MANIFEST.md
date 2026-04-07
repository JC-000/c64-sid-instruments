# Reference Single-Note Samples

Reference recordings for SID instrument design. Each file is an isolated single note.
All WAVs are committed (each <5 MB).

## Piano (C3–C5 chromatic scale, forte)

Source: Salamander Grand Piano V3 (Alexander Holm), via the `sfzinstruments/SalamanderGrandPiano` GitHub mirror. Recorded at 48 kHz / 24-bit from a Yamaha C5 grand, 16 velocity layers. Licensed **CC-BY 3.0 Unported**.

Chromatic scale samples (v12 = forte) span C3–C5 in minor-third intervals for multi-pitch evaluation. A `note_map.json` in `grand-piano/` maps note names to frequencies and filenames. The repo uses sharp names (D#/F# instead of Eb/Gb); output files use flat names for readability.

## Guitar (target ~E4, 329.63 Hz)

Source: Philharmonia Orchestra free sample library, via the `skratchdot/philharmonia-samples` GitHub mirror. Originally distributed as MP3; converted to PCM WAV via librosa. Licensed **CC-BY-SA 3.0 Unported**. (Attribution: Philharmonia Orchestra.)

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

## Notes

- University of Iowa MIS (`theremin.music.uiowa.edu`) — originally targeted but the host returned HTTP 401 through the sandbox proxy for every request. Not used.
- Freesound.org downloads require OAuth, so could not be fetched programmatically here.
- Philharmonia MP3s were decoded to float32 via `librosa.load` (audioread backend) and written as 16-bit PCM WAV with `soundfile`. Re-encoding does not add information but makes them consumable by the `wave` module.
- Salamander FLACs were decoded with `soundfile` and re-encoded as 24-bit PCM WAV (original bit depth).
- All files were sanity-checked with Python's `wave` module for duration, sample rate, channels.
