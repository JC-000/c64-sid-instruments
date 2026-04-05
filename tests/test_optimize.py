"""Tests for sidmatch.optimize (CMA-ES + checkpointing)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sidmatch.optimize import (
    Optimizer,
    encode_params,
    decode_params,
    BOUNDS_LOW,
    BOUNDS_HIGH,
    N_DIMS,
    sid_params_to_dict,
    sid_params_from_dict,
)
from sidmatch.render import SidParams, render_pyresid
from sidmatch.features import CANONICAL_SR


# A simple recoverable patch: saw, no filter, moderate ADSR.
_KNOWN_PATCH = SidParams(
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
    frequency=440.0,
    gate_frames=50,
    release_frames=50,
    volume=15,
)


def _synthesize_ref_wav(tmp_path: Path) -> Path:
    audio = render_pyresid(_KNOWN_PATCH, sample_rate=CANONICAL_SR)
    out = tmp_path / "ref.wav"
    sf.write(str(out), audio, CANONICAL_SR)
    return out


# --------------------------------------------------------------------------
# Encode / decode round-trip
# --------------------------------------------------------------------------

def test_encode_decode_roundtrip():
    x = encode_params(_KNOWN_PATCH)
    assert x.shape == (N_DIMS,)
    assert np.all(x >= BOUNDS_LOW - 1e-9)
    assert np.all(x <= BOUNDS_HIGH + 1e-9)

    fixed = {
        "waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
        "gate_frames": 50,
        "release_frames": 50,
    }
    p = decode_params(x, fixed)
    assert p.attack == _KNOWN_PATCH.attack
    assert p.decay == _KNOWN_PATCH.decay
    assert p.sustain == _KNOWN_PATCH.sustain
    assert p.release == _KNOWN_PATCH.release
    assert p.pulse_width == _KNOWN_PATCH.pulse_width
    assert p.filter_cutoff == _KNOWN_PATCH.filter_cutoff
    assert p.filter_resonance == _KNOWN_PATCH.filter_resonance
    assert p.waveform == "saw"
    assert p.filter_mode == "off"


def test_decode_bounds_clipping():
    # Out-of-bounds values should clip to ranges.
    x = np.full(N_DIMS, 1e6)
    p = decode_params(x, {"waveform": "saw", "filter_mode": "off"})
    assert p.attack == 15
    assert p.pulse_width == 4095
    assert p.filter_cutoff == 2047

    x = np.full(N_DIMS, -1e6)
    p = decode_params(x, {"waveform": "saw", "filter_mode": "off"})
    assert p.attack == 0
    assert p.pulse_width == 0


def test_sid_params_json_roundtrip():
    d = sid_params_to_dict(_KNOWN_PATCH)
    s = json.dumps(d)
    d2 = json.loads(s)
    p2 = sid_params_from_dict(d2)
    assert p2.waveform == _KNOWN_PATCH.waveform
    assert p2.attack == _KNOWN_PATCH.attack
    assert p2.frequency == _KNOWN_PATCH.frequency


# --------------------------------------------------------------------------
# Recovery test
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_recovery_known_patch(tmp_path):
    """Synthesize a known patch, run optimizer, verify final fitness is low."""
    ref_wav = _synthesize_ref_wav(tmp_path)

    fixed = {
        "waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
        "gate_frames": 50,
        "release_frames": 50,
    }
    opt = Optimizer(
        ref_wav_path=ref_wav,
        ref_frequency_hz=440.0,
        fixed_kwargs=fixed,
        budget=300,
        patience=400,
        n_workers=1,  # keep test serial
        seed=42,
        work_dir=tmp_path / "work",
        log_interval=0,
    )
    result = opt.run()
    print(
        f"[test] recovery final fitness={result.best_fitness:.4f} "
        f"evals={result.evaluations} params={sid_params_to_dict(result.best_params)}"
    )
    assert result.best_fitness < 0.5, (
        f"optimizer did not recover known patch: fitness={result.best_fitness:.4f}"
    )
    assert result.evaluations > 0


# --------------------------------------------------------------------------
# Parallel smoke
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_parallel_smoke(tmp_path):
    ref_wav = _synthesize_ref_wav(tmp_path)
    fixed = {
        "waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
        "gate_frames": 50,
        "release_frames": 50,
    }
    opt = Optimizer(
        ref_wav_path=ref_wav,
        ref_frequency_hz=440.0,
        fixed_kwargs=fixed,
        budget=50,
        patience=1000,
        n_workers=2,
        seed=7,
        work_dir=tmp_path / "work",
        log_interval=0,
    )
    result = opt.run()
    assert result.evaluations >= 1
    assert np.isfinite(result.best_fitness)
    assert len(result.history) >= 1


# --------------------------------------------------------------------------
# Checkpoint restore
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_checkpoint_restore(tmp_path):
    ref_wav = _synthesize_ref_wav(tmp_path)
    work_dir = tmp_path / "work"
    fixed = {
        "waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
        "gate_frames": 50,
        "release_frames": 50,
    }
    opt = Optimizer(
        ref_wav_path=ref_wav,
        ref_frequency_hz=440.0,
        fixed_kwargs=fixed,
        budget=50,
        patience=10_000,
        n_workers=1,
        seed=1,
        work_dir=work_dir,
        log_interval=0,
    )
    result = opt.run()
    assert result.evaluations > 0

    # Checkpoint file exists and round-trips.
    state = Optimizer.load_checkpoint(work_dir)
    assert "best_x" in state
    assert "best_params" in state
    assert "history" in state
    assert state["evaluations"] == result.evaluations
    assert abs(state["best_fitness"] - result.best_fitness) < 1e-9

    # best_params must reload into a SidParams.
    p = sid_params_from_dict(state["best_params"])
    assert p.waveform == "saw"
    assert p.filter_mode == "off"
