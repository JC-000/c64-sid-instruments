"""Tests for sidmatch.multi_note (multi-note chromatic scale evaluation)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sidmatch.render import SidParams, render_pyresid
from sidmatch.features import extract, CANONICAL_SR
from sidmatch.multi_note import (
    ReferenceSet,
    NoteRef,
    multi_note_fitness,
    _multi_note_weights,
)
from sidmatch.optimize import MultiNoteOptimizer, sid_params_to_dict
from sidmatch.fitness import DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Three notes spanning roughly an octave.
_NOTES = [
    ("C4", 261.63),
    ("E4", 329.63),
    ("A4", 440.00),
]

_BASE_PATCH = SidParams(
    waveform="saw",
    attack=0,
    decay=7,
    sustain=10,
    release=5,
    pulse_width=2048,
    filter_cutoff=1024,
    filter_resonance=0,
    filter_mode="off",
    filter_voice1=False,
    frequency=261.63,
    gate_frames=50,
    release_frames=25,
    volume=15,
    wt_attack_frames=1,
    wt_attack_waveform=None,
    wt_sustain_waveform=None,
    wt_use_test_bit=False,
    pw_start=2048,
    pw_delta=0,
    pw_min=0,
    pw_max=4095,
    pw_mode="sweep",
    filter_cutoff_start=1024,
    filter_cutoff_end=1024,
    filter_sweep_frames=0,
)


def _create_ref_dir(tmp_path: Path) -> Path:
    """Create a reference set directory with synthetic WAVs and note_map.json."""
    ref_dir = tmp_path / "ref_set"
    ref_dir.mkdir()

    entries = []
    for note_name, freq_hz in _NOTES:
        from dataclasses import replace
        params = replace(_BASE_PATCH, frequency=freq_hz)
        audio = render_pyresid(params, sample_rate=CANONICAL_SR)
        wav_name = f"{note_name}.wav"
        sf.write(str(ref_dir / wav_name), audio, CANONICAL_SR)
        entries.append({"note": note_name, "freq_hz": freq_hz, "wav": wav_name})

    (ref_dir / "note_map.json").write_text(json.dumps(entries, indent=2))
    return ref_dir


def _build_ref_set_from_patch(patch: SidParams) -> ReferenceSet:
    """Build an in-memory ReferenceSet by rendering patch at each note freq."""
    from dataclasses import replace

    notes = []
    for note_name, freq_hz in _NOTES:
        p = replace(patch, frequency=freq_hz)
        audio = render_pyresid(p, sample_rate=CANONICAL_SR)
        fv = extract(audio, CANONICAL_SR)
        notes.append(NoteRef(note_name=note_name, freq_hz=freq_hz, ref_fv=fv))
    return ReferenceSet.from_features(notes)


# ---------------------------------------------------------------------------
# ReferenceSet loading
# ---------------------------------------------------------------------------

def test_reference_set_load(tmp_path):
    """ReferenceSet.load reads note_map.json and pre-computes features."""
    ref_dir = _create_ref_dir(tmp_path)
    ref_set = ReferenceSet.load(ref_dir)

    assert len(ref_set) == 3
    assert ref_set.note_names() == ["C4", "E4", "A4"]
    assert ref_set.frequencies() == [261.63, 329.63, 440.00]
    # Each note should have a valid FeatureVec.
    for note_ref in ref_set.notes:
        assert note_ref.ref_fv.sr == CANONICAL_SR
        assert note_ref.ref_fv.duration_s > 0


def test_reference_set_load_dict_format(tmp_path):
    """ReferenceSet.load handles the dict-format note_map.json used by download scripts."""
    ref_dir = tmp_path / "ref_dict"
    ref_dir.mkdir()

    # Create WAVs and a dict-format note_map.json
    from dataclasses import replace as dc_replace
    dict_map = {}
    for note_name, freq_hz in _NOTES:
        params = dc_replace(_BASE_PATCH, frequency=freq_hz)
        audio = render_pyresid(params, sample_rate=CANONICAL_SR)
        wav_name = f"{note_name}.wav"
        sf.write(str(ref_dir / wav_name), audio, CANONICAL_SR)
        dict_map[note_name] = {"freq_hz": freq_hz, "file": wav_name}

    (ref_dir / "note_map.json").write_text(json.dumps(dict_map, indent=2))

    ref_set = ReferenceSet.load(ref_dir)
    assert len(ref_set) == 3
    assert set(ref_set.note_names()) == {"C4", "E4", "A4"}


def test_reference_set_load_missing_json(tmp_path):
    with pytest.raises(FileNotFoundError, match="note_map.json"):
        ReferenceSet.load(tmp_path)


def test_reference_set_load_missing_wav(tmp_path):
    ref_dir = tmp_path / "ref_set"
    ref_dir.mkdir()
    (ref_dir / "note_map.json").write_text(
        json.dumps([{"note": "C4", "freq_hz": 261.63, "wav": "missing.wav"}])
    )
    with pytest.raises(FileNotFoundError, match="missing.wav"):
        ReferenceSet.load(ref_dir)


def test_reference_set_from_features():
    """ReferenceSet.from_features builds from pre-built NoteRefs."""
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)
    assert len(ref_set) == 3


# ---------------------------------------------------------------------------
# multi_note_fitness
# ---------------------------------------------------------------------------

def test_multi_note_weights():
    """fundamental weight should be zeroed in multi-note mode."""
    w = _multi_note_weights()
    assert w["fundamental"] == 0.0
    # Weights that are unchanged from DEFAULT_WEIGHTS.
    assert w["envelope"] == DEFAULT_WEIGHTS["envelope"]
    # Multi-note overrides: harmonics lowered, adsr raised.
    assert w["harmonics"] == 1.0
    assert w["adsr"] == 1.5


def test_multi_note_weights_custom():
    """Custom weights are respected, but fundamental is still zeroed."""
    w = _multi_note_weights({"envelope": 5.0, "fundamental": 99.0})
    assert w["fundamental"] == 0.0
    assert w["envelope"] == 5.0


def test_multi_note_fitness_self_zero():
    """Fitness of the reference patch against itself should be near zero."""
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)
    fitness = multi_note_fitness(_BASE_PATCH, ref_set)
    assert fitness < 0.05, f"self-fitness should be near zero, got {fitness}"


def test_multi_note_fitness_different_patch():
    """A very different patch should score higher than the reference."""
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)

    from dataclasses import replace
    bad_patch = replace(
        _BASE_PATCH,
        waveform="pulse",
        attack=15,
        decay=0,
        sustain=15,
        release=0,
        pulse_width=100,
    )
    fitness_bad = multi_note_fitness(bad_patch, ref_set)
    fitness_self = multi_note_fitness(_BASE_PATCH, ref_set)
    assert fitness_bad > fitness_self


def test_multi_note_fitness_alpha_bounds():
    """Verify the aggregation formula: (1-a)*mean + a*max."""
    # Use synthetic per-note distances to test the formula deterministically.
    # We build a ref set and a slightly different patch, compute per-note
    # distances manually, then verify multi_note_fitness matches the formula.
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)

    from dataclasses import replace as dc_replace
    from sidmatch.multi_note import _multi_note_weights
    from sidmatch.fitness import distance as fv_distance

    slightly_off = dc_replace(_BASE_PATCH, attack=5)

    # Compute per-note distances manually (same as multi_note_fitness internals).
    mn_weights = _multi_note_weights()
    distances = []
    for note_ref in ref_set.notes:
        note_params = dc_replace(slightly_off, frequency=note_ref.freq_hz)
        audio = render_pyresid(note_params, sample_rate=CANONICAL_SR)
        fv = extract(audio, CANONICAL_SR)
        d = fv_distance(note_ref.ref_fv, fv, weights=mn_weights)
        distances.append(d)

    mean_d = float(np.mean(distances))
    max_d = float(np.max(distances))

    # Verify formula for several alpha values.
    for alpha in [0.0, 0.25, 0.5, 1.0]:
        expected = (1.0 - alpha) * mean_d + alpha * max_d
        actual = multi_note_fitness(slightly_off, ref_set, alpha=alpha)
        # Allow tolerance for re-rendering jitter.
        assert abs(actual - expected) < 0.01, (
            f"alpha={alpha}: expected ~{expected:.6f}, got {actual:.6f}"
        )

    # max should always be >= mean
    assert max_d >= mean_d - 1e-9


def test_multi_note_fitness_empty_ref_set():
    """Empty ref set returns 0."""
    empty = ReferenceSet(notes=[])
    assert multi_note_fitness(_BASE_PATCH, empty) == 0.0


# ---------------------------------------------------------------------------
# MultiNoteOptimizer
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_multi_note_optimizer_runs(tmp_path):
    """MultiNoteOptimizer runs end-to-end with a tiny budget."""
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)

    fixed = {
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
    }
    opt = MultiNoteOptimizer(
        ref_set=ref_set,
        fixed_kwargs=fixed,
        budget=10,
        patience=1000,
        n_workers=1,
        seed=42,
        work_dir=tmp_path / "work",
        log_interval=0,
    )
    result = opt.run()
    assert result.evaluations >= 1
    assert np.isfinite(result.best_fitness)
    assert len(result.history) >= 1


@pytest.mark.slow
def test_multi_note_optimizer_checkpoint(tmp_path):
    """Checkpoint includes reference_notes metadata."""
    ref_set = _build_ref_set_from_patch(_BASE_PATCH)
    work_dir = tmp_path / "work"

    fixed = {
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
    }
    opt = MultiNoteOptimizer(
        ref_set=ref_set,
        fixed_kwargs=fixed,
        budget=10,
        patience=1000,
        n_workers=1,
        seed=42,
        work_dir=work_dir,
        log_interval=0,
    )
    result = opt.run()

    cp_path = work_dir / "optim_state.json"
    assert cp_path.exists()
    state = json.loads(cp_path.read_text())
    assert "reference_notes" in state
    assert len(state["reference_notes"]) == 3
    assert state["reference_notes"][0]["note"] == "C4"
    assert "alpha" in state
