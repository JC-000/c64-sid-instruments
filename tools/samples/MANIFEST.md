# Reference Single-Note Samples

Reference recordings for SID instrument design. Each file is an isolated single note.
All WAVs are committed (each <5 MB).

## Piano (target ~C4, 261.63 Hz)

Source: Salamander Grand Piano V3 (Alexander Holm), via the `sfzinstruments/SalamanderGrandPiano` GitHub mirror. Recorded at 48 kHz / 24-bit from a Yamaha C5 grand, 16 velocity layers. Licensed **CC-BY 3.0 Unported**.

## Guitar (target ~E4, 329.63 Hz)

Source: Philharmonia Orchestra free sample library, via the `skratchdot/philharmonia-samples` GitHub mirror. Originally distributed as MP3; converted to PCM WAV via librosa. Licensed **CC-BY-SA 3.0 Unported**. (Attribution: Philharmonia Orchestra.)

## Table

| filename | source URL | license | original filename | pitch | dynamic | duration_s | sample_rate | channels | bit_depth |
|---|---|---|---|---|---|---|---|---|---|
| grand-piano/salamander-piano-C4-v6-mf.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v6.flac | CC-BY 3.0 | C4v6.flac | C4 (261.63 Hz) | mf (velocity layer 6/16) | 15.92 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C4-v12-f.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v12.flac | CC-BY 3.0 | C4v12.flac | C4 (261.63 Hz) | f (velocity layer 12/16) | 15.72 | 48000 | 2 | 24 |
| grand-piano/salamander-piano-C4-v16-ff.wav | https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/C4v16.flac | CC-BY 3.0 | C4v16.flac | C4 (261.63 Hz) | ff (velocity layer 16/16) | 15.52 | 48000 | 2 | 24 |
| acoustic-guitar/philharmonia-guitar-E4-forte.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_forte_normal.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_forte_normal.mp3 | E4 (329.63 Hz) | forte, normal | 5.17 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E4-piano.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_piano_normal.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_piano_normal.mp3 | E4 (329.63 Hz) | piano, normal | 4.96 | 44100 | 1 | 16 |
| acoustic-guitar/philharmonia-guitar-E4-forte-harmonics.wav | https://raw.githubusercontent.com/skratchdot/philharmonia-samples/master/audio/guitar/guitar_E4_very-long_forte_harmonics.mp3 | CC-BY-SA 3.0 | guitar_E4_very-long_forte_harmonics.mp3 | E4 (329.63 Hz) | forte, harmonics | 6.40 | 44100 | 1 | 16 |

## Notes

- University of Iowa MIS (`theremin.music.uiowa.edu`) — originally targeted but the host returned HTTP 401 through the sandbox proxy for every request. Not used.
- Freesound.org downloads require OAuth, so could not be fetched programmatically here.
- Philharmonia MP3s were decoded to float32 via `librosa.load` (audioread backend) and written as 16-bit PCM WAV with `soundfile`. Re-encoding does not add information but makes them consumable by the `wave` module.
- Salamander FLACs were decoded with `soundfile` and re-encoded as 24-bit PCM WAV (original bit depth).
- All files were sanity-checked with Python's `wave` module for duration, sample rate, channels.
