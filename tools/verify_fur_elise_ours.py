#!/usr/bin/env python3
"""Verification sanity check for comparisons/fur_elise_ours_8580.wav.

Prints duration, RMS, peak, and a sustain-indicator metric (fraction of
samples whose 10ms-smoothed envelope exceeds -40 dB of the peak).
Accepts an optional second WAV path to print side-by-side stats.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def stats(path: Path) -> dict:
    audio, sr = sf.read(str(path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    env = np.abs(audio)
    window = max(1, int(sr * 0.01))  # 10 ms boxcar
    env_sm = np.convolve(env, np.ones(window) / window, mode="same")
    peak = float(np.max(env_sm)) if env_sm.size else 0.0
    thresh = 0.01 * peak  # -40 dB of envelope peak
    frac_above = float(np.mean(env_sm > thresh)) if env_sm.size else 0.0
    return {
        "path": str(path),
        "duration_s": len(audio) / sr,
        "rms": float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0,
        "peak": float(np.max(np.abs(audio))) if audio.size else 0.0,
        "sustain_frac_above_-40dB": frac_above,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: verify_fur_elise_ours.py WAV [WAV ...]", file=sys.stderr)
        return 2
    for arg in argv[1:]:
        s = stats(Path(arg))
        print(
            f"{s['path']}: dur={s['duration_s']:.2f}s "
            f"rms={s['rms']:.4f} peak={s['peak']:.4f} "
            f"sustain={s['sustain_frac_above_-40dB']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
