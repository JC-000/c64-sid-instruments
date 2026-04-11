#!/usr/bin/env python3
"""Validation harness for the MR-STFT fitness (Phase 2.5).

Renders the chromatic scale for a set of candidate param versions,
compares each against the Salamander reference scale, and prints both
the new multi-resolution STFT fitness and (for a sanity anchor) a
lightweight legacy-style numeric summary.

Pass criterion: the HEAD params (with a proper release tail) must
score *better* (lower) than the pre-restore sustain=0 buggy params.
If that ordering flips, the new fitness is still broken.

Usage::

    python3 -m tools.sidmatch.validate_mrstft

Add ``--commit <sha>:<label>`` to score an additional git revision of
the 8580 params. ``HEAD`` and ``db63b8f`` are always included.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

import numpy as np
import soundfile as sf

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.sidmatch.fitness_mrstft import mr_stft_distance  # noqa: E402
from tools.sidmatch.render import render_pyresid  # noqa: E402
from tools.sidmatch.cli import sid_params_from_dict  # noqa: E402


REF_WAV = _REPO / "instruments" / "grand-piano" / "grand-piano-reference-scale.wav"
HEAD_PARAMS = (
    _REPO / "instruments" / "grand-piano" / "8580" / "grand-piano-8580-params.json"
)
SCALE_SR = 44100
GAP_MS = 200


def _render_scale(params_dict: dict, chip_model: str) -> np.ndarray:
    """Mirror of cli._render_chromatic_scale, kept local to avoid
    pulling in the heavy CLI module's top-level side effects."""
    reference_notes = params_dict.get("reference_notes", [])
    gap = np.zeros(int(SCALE_SR * GAP_MS / 1000), dtype=np.float32)
    segments: list[np.ndarray] = []
    for note_info in reference_notes:
        note_dict = dict(params_dict)
        note_dict["frequency"] = note_info["freq_hz"]
        sid_params = sid_params_from_dict(
            {k: v for k, v in note_dict.items()
             if k not in ("fitness_score", "version", "reference_notes", "notes")}
        )
        audio = render_pyresid(sid_params, sample_rate=SCALE_SR, chip_model=chip_model)
        if segments:
            segments.append(gap)
        segments.append(audio.astype(np.float32))
    if not segments:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(segments)


def _params_from_git(sha: str, relpath: str) -> dict:
    out = subprocess.check_output(
        ["git", "show", f"{sha}:{relpath}"], cwd=str(_REPO)
    )
    return json.loads(out)


def _params_from_file(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_ref() -> Tuple[np.ndarray, int]:
    data, sr = sf.read(str(REF_WAV))
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float64), sr


def _rms_legacy_like(ref: np.ndarray, cand: np.ndarray) -> float:
    """Very coarse legacy sanity number: linear-magnitude STFT
    convergence at a single FFT size, no frame weighting, no log.
    Not the real legacy fitness (which runs on FeatureVec), but a
    cheap anchor that demonstrates the "loud region dominates"
    pathology on the same audio."""
    import librosa
    n = max(ref.size, cand.size)
    a = np.concatenate([ref, np.zeros(n - ref.size)]) if ref.size < n else ref
    b = np.concatenate([cand, np.zeros(n - cand.size)]) if cand.size < n else cand
    S_ref = np.abs(librosa.stft(a.astype(np.float64), n_fft=2048, hop_length=512))
    S_cand = np.abs(librosa.stft(b.astype(np.float64), n_fft=2048, hop_length=512))
    t = min(S_ref.shape[1], S_cand.shape[1])
    S_ref = S_ref[:, :t]
    S_cand = S_cand[:, :t]
    num = np.linalg.norm(S_ref - S_cand, "fro")
    den = np.linalg.norm(S_ref, "fro") + 1e-9
    return float(num / den)


def _score(label: str, params: dict, chip: str, ref: np.ndarray) -> dict:
    print(f"  rendering {label} ...")
    scale = _render_scale(params, chip)
    print(f"    scale samples: {scale.size} ({scale.size / SCALE_SR:.1f}s)")
    d_new = mr_stft_distance(ref, scale.astype(np.float64), SCALE_SR)
    d_new_no_fw = mr_stft_distance(
        ref, scale.astype(np.float64), SCALE_SR, frame_weight=False
    )
    d_legacy = _rms_legacy_like(ref, scale.astype(np.float64))
    return {
        "label": label,
        "adsr": (
            params.get("attack"),
            params.get("decay"),
            params.get("sustain"),
            params.get("release"),
        ),
        "mr_stft": d_new,
        "mr_stft_no_fw": d_new_no_fw,
        "legacy_sc": d_legacy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="append",
        default=[],
        help="Extra SHA[:label] to score. Uses 8580 params from that commit.",
    )
    args = parser.parse_args()

    print(f"Loading reference: {REF_WAV}")
    ref, sr = _load_ref()
    assert sr == SCALE_SR, f"reference sr={sr}, expected {SCALE_SR}"
    print(f"  {ref.size} samples ({ref.size / sr:.1f}s)")

    rel = "instruments/grand-piano/8580/grand-piano-8580-params.json"
    targets: List[Tuple[str, dict]] = []
    targets.append(("HEAD (A=2 D=6 S=15 R=12)", _params_from_file(HEAD_PARAMS)))
    pre = _params_from_git("db63b8f", rel)
    targets.append(
        (f"db63b8f (A={pre['attack']} D={pre['decay']} S={pre['sustain']} R={pre['release']})",
         pre),
    )
    for spec in args.commit:
        sha, _, label = spec.partition(":")
        p = _params_from_git(sha, rel)
        targets.append((label or sha, p))

    rows = []
    for label, params in targets:
        chip = params.get("chip_model") or "8580"
        rows.append(_score(label, params, chip, ref))

    # Print table
    print()
    print("=" * 78)
    print("MR-STFT VALIDATION (lower = better)")
    print("=" * 78)
    hdr = f"{'version':<34}  {'ADSR':<14}  {'mr_stft':>10}  {'no_fw':>10}  {'leg_sc':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        adsr = "/".join(str(x) for x in r["adsr"])
        print(
            f"{r['label']:<34}  {adsr:<14}  "
            f"{r['mr_stft']:>10.4f}  {r['mr_stft_no_fw']:>10.4f}  "
            f"{r['legacy_sc']:>8.4f}"
        )

    # Pass criterion
    head = rows[0]
    prerest = rows[1]
    verdict = "PASS" if head["mr_stft"] < prerest["mr_stft"] else "FAIL"
    print()
    print(f"RANKING CHECK: HEAD < db63b8f ? {verdict}")
    print(f"  HEAD     mr_stft = {head['mr_stft']:.4f}")
    print(f"  db63b8f  mr_stft = {prerest['mr_stft']:.4f}")
    print(f"  delta    = {prerest['mr_stft'] - head['mr_stft']:+.4f}")

    # Also reveal the pathology on the legacy-ish column
    print()
    print("Legacy (no-log, no-frame-weight) for contrast:")
    print(f"  HEAD     legacy_sc = {head['legacy_sc']:.4f}")
    print(f"  db63b8f  legacy_sc = {prerest['legacy_sc']:.4f}")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
