"""Multi-note chromatic scale evaluation for SID instrument fitting.

Instead of optimizing against a single reference note, this module
evaluates a SID instrument patch at multiple pitches (a chromatic scale)
and compares each against the corresponding reference recording.

The aggregated fitness is::

    (1 - alpha) * weighted_mean(distances) + alpha * max(distances)

with ``alpha=0.15`` by default, which penalises outlier notes that the
patch handles poorly while still optimising the average.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional

import numpy as np

from .features import FeatureVec, extract, CANONICAL_SR
from .fitness import distance, DEFAULT_WEIGHTS
from .optimize import decode_params, load_reference_audio
from .render import SidParams, render_pyresid


@dataclass
class NoteRef:
    """A single note in a reference set."""
    note_name: str
    freq_hz: float
    ref_fv: FeatureVec


@dataclass
class ReferenceSet:
    """A collection of reference notes with pre-computed feature vectors.

    Loaded from a directory containing a ``note_map.json`` file and the
    corresponding WAV files.  The JSON schema is::

        [
            {"note": "C4", "freq_hz": 261.63, "wav": "C4.wav"},
            {"note": "D4", "freq_hz": 293.66, "wav": "D4.wav"},
            ...
        ]

    WAV paths are resolved relative to the directory containing the JSON.
    """
    notes: List[NoteRef] = field(default_factory=list)

    @classmethod
    def load(cls, dir_path: Path) -> "ReferenceSet":
        """Load a reference set from *dir_path*/note_map.json.

        Supports two JSON formats:

        **Array format** (canonical)::

            [
                {"note": "C4", "freq_hz": 261.63, "wav": "C4.wav"},
                ...
            ]

        **Dict format** (as produced by sample download scripts)::

            {
                "C4": {"freq_hz": 261.63, "file": "C4.wav"},
                ...
            }

        WAV paths are resolved relative to the directory containing the JSON.
        """
        dir_path = Path(dir_path)
        map_path = dir_path / "note_map.json"
        if not map_path.exists():
            raise FileNotFoundError(f"note_map.json not found in {dir_path}")

        raw = json.loads(map_path.read_text())

        # Normalise into a list of (note_name, freq_hz, wav_filename).
        entries: List[tuple] = []
        if isinstance(raw, list):
            # Array format: [{"note": ..., "freq_hz": ..., "wav": ...}]
            for item in raw:
                entries.append((
                    str(item["note"]),
                    float(item["freq_hz"]),
                    str(item.get("wav") or item.get("file")),
                ))
        elif isinstance(raw, dict):
            # Dict format: {"C4": {"freq_hz": ..., "file": ...}, ...}
            for note_name, info in raw.items():
                entries.append((
                    str(note_name),
                    float(info["freq_hz"]),
                    str(info.get("file") or info.get("wav")),
                ))
        else:
            raise ValueError(
                f"note_map.json: expected a JSON array or object, got {type(raw).__name__}"
            )

        notes: List[NoteRef] = []
        for note_name, freq_hz, wav_filename in entries:
            wav_path = dir_path / wav_filename
            if not wav_path.exists():
                raise FileNotFoundError(
                    f"WAV file not found: {wav_path} (note {note_name})"
                )
            audio, sr = load_reference_audio(wav_path)
            fv = extract(audio, sr)
            notes.append(NoteRef(note_name=note_name, freq_hz=freq_hz, ref_fv=fv))

        return cls(notes=notes)

    @classmethod
    def from_features(cls, notes: List[NoteRef]) -> "ReferenceSet":
        """Build a ReferenceSet from pre-built NoteRef objects."""
        return cls(notes=list(notes))

    def note_names(self) -> List[str]:
        return [n.note_name for n in self.notes]

    def frequencies(self) -> List[float]:
        return [n.freq_hz for n in self.notes]

    def __len__(self) -> int:
        return len(self.notes)


def _multi_note_weights(weights: Optional[Mapping[str, float]] = None) -> dict:
    """Build weights dict for multi-note mode.

    The ``fundamental`` component gets weight 0 because frequency is set
    explicitly per note (not optimized).

    Default overrides vs single-note DEFAULT_WEIGHTS:
      - harmonics: 2.0 -> 1.0  (SID waveform limitations inflate this)
      - adsr: 1.0 -> 1.5       (envelope match is perceptually important)
    """
    w = dict(DEFAULT_WEIGHTS)
    # Multi-note specific defaults
    w["harmonics"] = 1.0
    w["adsr"] = 1.5
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)
    w["fundamental"] = 0.0
    return w


def multi_note_fitness(
    params: SidParams,
    ref_set: ReferenceSet,
    weights: Optional[Mapping[str, float]] = None,
    alpha: float = 0.15,
    chip_model: Optional[str] = None,
) -> float:
    """Evaluate *params* against all notes in *ref_set*.

    For each note the frequency on *params* is overridden, the patch is
    rendered, features are extracted, and distance is computed against
    that note's reference.

    The aggregate score is::

        (1 - alpha) * weighted_mean(distances) + alpha * max(distances)

    Parameters
    ----------
    params : SidParams
        The candidate patch.  Its ``frequency`` field is overwritten per note.
    ref_set : ReferenceSet
        Pre-computed reference features for each note.
    weights : dict, optional
        Feature-component weights.  ``fundamental`` is forced to 0.
    alpha : float
        Blend between mean and max.  0 = pure mean, 1 = pure max.
    chip_model : str, optional
        SID chip model override for rendering.

    Returns
    -------
    float
        Aggregated scalar fitness (lower is better).
    """
    if len(ref_set) == 0:
        return 0.0

    mn_weights = _multi_note_weights(weights)
    distances: List[float] = []

    for note_ref in ref_set.notes:
        # Copy params and set frequency for this note.
        from dataclasses import replace
        note_params = replace(params, frequency=note_ref.freq_hz)

        try:
            audio = render_pyresid(
                note_params, sample_rate=CANONICAL_SR, chip_model=chip_model
            )
            # Match durations: pad SID render with silence to match the
            # reference length so envelope/spectral comparisons are fair.
            # Without this, a 1.3s SID render is compared against a 2.0s
            # reference window, unfairly penalising the SID's shorter tail.
            ref_dur_samples = int(note_ref.ref_fv.duration_s * CANONICAL_SR)
            if audio.shape[0] < ref_dur_samples:
                pad = np.zeros(ref_dur_samples - audio.shape[0], dtype=audio.dtype)
                audio = np.concatenate([audio, pad])
            fv = extract(audio, CANONICAL_SR, known_f0=note_ref.freq_hz)
            d = distance(note_ref.ref_fv, fv, weights=mn_weights)
        except Exception:
            d = 1e6
        distances.append(d)

    mean_d = float(np.mean(distances))
    max_d = float(np.max(distances))
    return (1.0 - alpha) * mean_d + alpha * max_d
