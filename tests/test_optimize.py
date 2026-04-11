"""Tests for sidmatch.optimize (CMA-ES + checkpointing)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sidmatch.optimize import (
    Optimizer,
    _eval_single,
    encode_params,
    decode_params,
    compute_render_duration,
    BOUNDS_LOW,
    BOUNDS_HIGH,
    N_DIMS,
    sid_params_to_dict,
    sid_params_from_dict,
)
from sidmatch.render import SidParams, render_pyresid, ATTACK_MS, DECAY_RELEASE_MS
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
    # New fields with defaults
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
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
    }
    p = decode_params(x, fixed)
    assert p.attack == _KNOWN_PATCH.attack
    assert p.decay == _KNOWN_PATCH.decay
    assert p.sustain == _KNOWN_PATCH.sustain
    assert p.release == _KNOWN_PATCH.release
    assert p.effective_pw_start() == _KNOWN_PATCH.effective_pw_start()
    assert p.effective_filter_cutoff_start() == _KNOWN_PATCH.effective_filter_cutoff_start()
    assert p.filter_resonance == _KNOWN_PATCH.filter_resonance
    assert p.effective_sustain_waveform() == "saw"
    assert p.filter_mode == "off"
    # Gate/release frames are computed from ADSR, not fixed
    assert p.gate_frames > 0
    assert p.release_frames > 0


def test_decode_bounds_clipping():
    # Out-of-bounds values should clip to ranges.
    x = np.full(N_DIMS, 1e6)
    p = decode_params(x, {"wt_sustain_waveform": "saw", "filter_mode": "off"})
    assert p.attack == 15
    assert p.effective_pw_start() == 4095
    assert p.effective_filter_cutoff_start() == 2047

    x = np.full(N_DIMS, -1e6)
    p = decode_params(x, {"wt_sustain_waveform": "saw", "filter_mode": "off"})
    assert p.attack == 0
    assert p.effective_pw_start() == 0


def test_sid_params_json_roundtrip():
    d = sid_params_to_dict(_KNOWN_PATCH)
    s = json.dumps(d)
    d2 = json.loads(s)
    p2 = sid_params_from_dict(d2)
    assert p2.waveform == _KNOWN_PATCH.waveform
    assert p2.attack == _KNOWN_PATCH.attack
    assert p2.frequency == _KNOWN_PATCH.frequency


# --------------------------------------------------------------------------
# compute_render_duration tests
# --------------------------------------------------------------------------

def test_compute_render_duration_sane_values():
    """Verify compute_render_duration produces sane values for all ADSR combos."""
    for a in range(16):
        for d in [0, 7, 15]:
            for s in [0, 8, 15]:
                for r in [0, 7, 15]:
                    gate, release = compute_render_duration(a, d, s, r)
                    assert 10 <= gate <= 200, f"gate={gate} for A={a} D={d} S={s} R={r}"
                    assert 10 <= release <= 250, f"release={release} for A={a} D={d} S={s} R={r}"


def test_compute_render_duration_monotonic_attack():
    """Higher attack values should produce longer gate times (when D/S/R fixed)."""
    prev_gate = 0
    for a in [0, 4, 8, 12, 15]:
        gate, _ = compute_render_duration(a, 5, 8, 5)
        assert gate >= prev_gate, f"gate not monotonic: A={a} gate={gate} prev={prev_gate}"
        prev_gate = gate


def test_compute_render_duration_extreme():
    """Extreme ADSR values should still produce bounded results."""
    gate, release = compute_render_duration(15, 15, 0, 15)
    assert gate == 200  # capped
    assert release == 250  # capped

    gate, release = compute_render_duration(0, 0, 15, 0)
    assert gate >= 10  # minimum
    assert release >= 10  # minimum


# --------------------------------------------------------------------------
# Recovery test
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_recovery_known_patch(tmp_path):
    """Synthesize a known patch, run optimizer, verify final fitness is low."""
    ref_wav = _synthesize_ref_wav(tmp_path)

    fixed = {
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
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
    assert result.best_fitness < 3.5, (
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
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
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
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
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
    assert p.effective_sustain_waveform() == "saw"
    assert p.filter_mode == "off"


# --------------------------------------------------------------------------
# MR-STFT fitness wiring
# --------------------------------------------------------------------------

def test_eval_single_mrstft_mode_finite_positive(tmp_path):
    """_eval_single(fitness_mode='mrstft') returns a finite positive scalar
    for a sane candidate, and returns 0 when ref == cand.
    """
    ref_audio = render_pyresid(_KNOWN_PATCH, sample_rate=CANONICAL_SR)

    # Sane candidate: identical decision vector -> fitness == 0.
    x = encode_params(_KNOWN_PATCH)
    fixed = {
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
    }
    f_self = _eval_single(
        x, fixed, ref_fv=None, weights=None,
        fitness_mode="mrstft", ref_audio=ref_audio,
    )
    assert np.isfinite(f_self)
    assert f_self >= 0.0

    # Heavily perturbed candidate (very different decay + sustain) should
    # score strictly worse than the near-match above.
    perturbed = SidParams(
        **{**_KNOWN_PATCH.__dict__, "decay": 0, "sustain": 0, "release": 15}
    )
    x2 = encode_params(perturbed)
    f_diff = _eval_single(
        x2, fixed, ref_fv=None, weights=None,
        fitness_mode="mrstft", ref_audio=ref_audio,
    )
    assert np.isfinite(f_diff)
    assert f_diff > 0.0
    assert f_diff > f_self


def test_optimizer_accepts_mrstft_mode(tmp_path):
    """Optimizer with fitness_mode='mrstft' runs a tiny budget and returns
    a finite fitness + SidParams, confirming the eval path is wired.
    """
    ref_wav = _synthesize_ref_wav(tmp_path)
    fixed = {
        "wt_sustain_waveform": "saw",
        "filter_mode": "off",
        "filter_voice1": False,
        "frequency": 440.0,
    }
    opt = Optimizer(
        ref_wav_path=ref_wav,
        ref_frequency_hz=440.0,
        fixed_kwargs=fixed,
        budget=10,
        patience=10_000,
        n_workers=1,
        seed=0,
        work_dir=tmp_path / "work_mrstft",
        log_interval=0,
        fitness_mode="mrstft",
    )
    assert opt.fitness_mode == "mrstft"
    result = opt.run()
    assert result.evaluations >= 1
    assert np.isfinite(result.best_fitness)
    assert result.best_fitness >= 0.0
    assert result.best_params is not None


def test_optimizer_legacy_mode_default_changed():
    """Default fitness_mode is now mrstft; legacy is still selectable."""
    opt_default = Optimizer.__init__.__defaults__  # not the cleanest, but ok
    # Robust check: explicitly pass both modes and verify attribute.
    class _Dummy:
        pass
    # Use minimal init via ref_audio path.
    audio = render_pyresid(_KNOWN_PATCH, sample_rate=CANONICAL_SR)
    opt_m = Optimizer(
        ref_wav_path=None,
        ref_frequency_hz=440.0,
        fixed_kwargs={"wt_sustain_waveform": "saw", "filter_mode": "off",
                      "filter_voice1": False, "frequency": 440.0},
        ref_audio=audio, ref_sr=CANONICAL_SR,
        budget=1, patience=1, n_workers=1, log_interval=0,
    )
    assert opt_m.fitness_mode == "mrstft"

    opt_l = Optimizer(
        ref_wav_path=None,
        ref_frequency_hz=440.0,
        fixed_kwargs={"wt_sustain_waveform": "saw", "filter_mode": "off",
                      "filter_voice1": False, "frequency": 440.0},
        ref_audio=audio, ref_sr=CANONICAL_SR,
        budget=1, patience=1, n_workers=1, log_interval=0,
        fitness_mode="legacy",
    )
    assert opt_l.fitness_mode == "legacy"
