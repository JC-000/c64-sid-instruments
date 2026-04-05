# sidmatch

Audio feature extraction and a fitness/distance function used to drive a
CMA-ES optimizer that searches for SID-instrument parameters matching a
reference recording (e.g. grand-piano C4).

## Modules

- `features.py` &mdash; `extract(audio, sr) -> FeatureVec`
- `fitness.py` &mdash; `distance(ref, cand, weights=None) -> float`

## `FeatureVec` fields

All time-series features are resampled to a common length of **128 frames**
(see `features.TIME_SERIES_FRAMES`) so they can be compared pointwise
without DTW. Audio is internally resampled to **44.1 kHz** and silence is
trimmed (&minus;60 dB threshold) before analysis.

| field | type | description |
|---|---|---|
| `sr` | int | canonical analysis rate (44100) |
| `duration_s` | float | length after silence trimming |
| `amplitude_envelope` | ndarray[128] | normalized RMS per 10 ms hop, resampled |
| `attack_time_s` | float | time from 10% to peak of envelope |
| `decay_time_s` | float | time from peak to sustain level |
| `sustain_level` | float | median envelope value across sustain region, in [0,1] |
| `release_time_s` | float | time from sustain region end to 10% of peak |
| `harmonic_magnitudes` | ndarray[16] | magnitudes of the first 16 partials, averaged over sustain, peak-normalized |
| `spectral_centroid` | ndarray[128] | centroid (Hz) time series |
| `spectral_rolloff` | ndarray[128] | 85% rolloff (Hz) time series |
| `spectral_flatness` | ndarray[128] | flatness (0..1) time series |
| `fundamental_hz` | float | median YIN f0 over voiced frames |
| `noisiness` | float | mean spectral flatness (noise-vs-tonal in [0,1]) |

`extract` handles mono/stereo (mixed to mono), any input sample rate, very
short buffers, and all-zero audio (returns a zeroed `FeatureVec`). It
raises `ValueError` on empty or non-finite input.

## Distance recipe

`distance(ref, cand, weights=None)` is a weighted sum of per-component
distances, each O(1) in magnitude:

| component | distance | default weight |
|---|---|---|
| `envelope` | L2 between amplitude envelopes | 1.0 |
| `harmonics` | cosine distance of partial vectors | 2.0 |
| `spectral_centroid` | L1 between log-centroid series, scaled by ~4 octaves | 0.5 |
| `spectral_rolloff` | L1 between log-rolloff series, scaled by ~4 octaves | 0.25 |
| `spectral_flatness` | L1 between flatness series | 0.25 |
| `noisiness` | squared error of scalar noisiness | 0.5 |
| `fundamental` | squared log2-ratio of f0 estimates | 2.0 |
| `adsr` | L1 over (attack, decay, sustain, release) / 4 | 1.0 |

Pass `weights={"harmonics": 3.0, ...}` to override; unknown keys are ignored.

Properties:

- `distance(x, x) == 0`
- symmetric: `distance(x, y) == distance(y, x)`
- non-negative

## Testing

    pytest tests/test_features.py tests/test_fitness.py -v
