"""Round-trip + assembler tests for the instrument encoders."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.sidmatch.render import SidParams, hz_to_sid_freq, PAL_CLOCK_HZ
from tools.sidmatch.encoders import (
    encode_raw_asm, parse_raw_asm,
    encode_goattracker, parse_goattracker,
    encode_sidwizard, parse_sidwizard,
)


def _rich_params() -> SidParams:
    """Patch with non-default values on every writable field."""
    return SidParams(
        waveform="triangle+pulse",
        attack=3,
        decay=11,
        sustain=7,
        release=6,
        pulse_width=3072,
        pw_table=[(0, 1024), (12, 2048), (30, 3800)],
        filter_cutoff=1500,
        filter_resonance=9,
        filter_mode="bp",
        filter_voice1=True,
        ring_mod=True,
        sync=True,
        frequency=523.25,
        gate_frames=80,
        release_frames=40,
        wavetable=[(0, 0x11), (8, 0x21), (16, 0x41)],
        volume=12,
        # New fields
        wt_attack_frames=2,
        wt_attack_waveform="pulse+saw",
        wt_sustain_waveform="triangle+pulse",
        wt_use_test_bit=True,
        pw_start=3072,
        pw_delta=10,
        pw_min=1024,
        pw_max=3800,
        pw_mode="sweep",
        filter_cutoff_start=1500,
        filter_cutoff_end=800,
        filter_sweep_frames=40,
    )


# ---------------------------------------------------------------------------
# raw_asm
# ---------------------------------------------------------------------------


def test_raw_asm_roundtrip_default():
    p = SidParams()
    text = encode_raw_asm(p, "inst_default")
    assert "inst_default_adsr" in text
    assert "inst_default_wavetable" in text
    assert "inst_default_pulsetable" in text
    assert "inst_default_filtertable" in text

    meta = parse_raw_asm(text)
    assert meta["attack"] == p.attack
    assert meta["decay"] == p.decay
    assert meta["sustain"] == p.sustain
    assert meta["release"] == p.release
    assert meta["waveform"] == p.waveform
    assert meta["frequency"] == pytest.approx(p.frequency)
    assert meta["freq_reg"] == hz_to_sid_freq(p.frequency, PAL_CLOCK_HZ)
    assert meta["volume"] == p.volume


def test_raw_asm_roundtrip_rich():
    p = _rich_params()
    text = encode_raw_asm(p, "my_piano")
    meta = parse_raw_asm(text)

    # Scalar fields
    for f in (
        "waveform", "attack", "decay", "sustain", "release",
        "pulse_width", "filter_cutoff", "filter_resonance",
        "filter_mode", "gate_frames", "release_frames", "volume",
    ):
        assert meta[f] == getattr(p, f), f"{f}: {meta[f]!r} != {getattr(p, f)!r}"
    assert meta["frequency"] == pytest.approx(p.frequency)
    assert meta["ring_mod"] is True
    assert meta["sync"] is True
    assert meta["filter_voice1"] is True

    # New fields
    assert meta["wt_attack_frames"] == p.wt_attack_frames
    assert meta["wt_use_test_bit"] is True
    assert meta["pw_delta"] == p.pw_delta
    assert meta["pw_min"] == p.pw_min
    assert meta["pw_max"] == p.pw_max
    assert meta["filter_cutoff_start"] == p.effective_filter_cutoff_start()
    assert meta["filter_cutoff_end"] == p.effective_filter_cutoff_end()
    assert meta["filter_sweep_frames"] == p.filter_sweep_frames

    # Legacy table fields still present
    assert meta["pw_table"] == p.pw_table
    assert meta["wavetable"] == p.wavetable


def test_raw_asm_invalid_prefix():
    with pytest.raises(ValueError):
        encode_raw_asm(SidParams(), "has-dash")
    with pytest.raises(ValueError):
        encode_raw_asm(SidParams(), "1leading_digit")


@pytest.mark.skipif(shutil.which("acme") is None, reason="acme not on PATH")
def test_raw_asm_assembles(tmp_path: Path):
    p = _rich_params()
    text = encode_raw_asm(p, "probe")
    tables_path = tmp_path / "probe_tables.asm"
    tables_path.write_text(text)

    wrapper = tmp_path / "wrap.asm"
    wrapper.write_text(
        "!cpu 6510\n"
        "* = $1000\n"
        '!source "probe_tables.asm"\n'
        "    rts\n"
    )
    out = tmp_path / "out.prg"
    r = subprocess.run(
        ["acme", "-f", "cbm", "-o", str(out), str(wrapper)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (
        f"acme failed rc={r.returncode}\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert out.exists() and out.stat().st_size > 2


# ---------------------------------------------------------------------------
# GoatTracker
# ---------------------------------------------------------------------------


def test_goattracker_magic_and_header():
    p = SidParams()
    data = encode_goattracker(p, "default")
    assert data[:4] == b"GTI5"
    assert len(data) >= 29


def test_goattracker_roundtrip_default():
    p = SidParams()
    data = encode_goattracker(p, "default")
    info = parse_goattracker(data)
    assert info["magic"] == "GTI5"
    assert info["name"] == "default"
    assert info["attack"] == p.attack
    assert info["decay"] == p.decay
    assert info["sustain"] == p.sustain
    assert info["release"] == p.release
    assert info["size"] == len(data)
    # Default patch: wavetable has attack + sustain = 2 rows
    assert len(info["wavetable"]) >= 1
    assert len(info["pulsetable"]) >= 1
    assert len(info["filtertable"]) >= 1
    assert len(info["speedtable"]) == 0


def test_goattracker_roundtrip_rich():
    p = _rich_params()
    data = encode_goattracker(p, "rich_patch")
    info = parse_goattracker(data)

    assert info["name"] == "rich_patch"
    assert info["attack"] == p.attack
    assert info["decay"] == p.decay
    assert info["sustain"] == p.sustain
    assert info["release"] == p.release

    # Wavetable should have rows for test bit + attack frames + sustain
    # test_bit=True -> 1 row, attack_frames=2 -> 2 rows, sustain -> 1 row = 4
    assert len(info["wavetable"]) >= 3

    # Pulsetable should have at least 1 row (absolute set + speed entry for delta)
    assert len(info["pulsetable"]) >= 1

    # The waveform bytes should have ring_mod + sync bits set (except test bit row)
    from tools.sidmatch.render import WF_RING_MOD, WF_SYNC
    for left, _ in info["wavetable"]:
        if left != (0x08 & 0xFE):  # skip test bit row
            assert (left & WF_RING_MOD) == WF_RING_MOD
            assert (left & WF_SYNC) == WF_SYNC

    # Filter cutoff hi round-trips
    assert info["filtertable"][0][1] == (p.filter_cutoff >> 3) & 0xFF
    # Filter resonance in left byte high nibble (note: 0x80 cmd bit overlaps
    # with resonance bit 3 for res >= 8, so we check the full byte)
    assert (info["filtertable"][0][0] >> 4) & 0x0F == p.filter_resonance


def test_goattracker_name_truncation():
    p = SidParams()
    long = "a" * 40
    data = encode_goattracker(p, long)
    info = parse_goattracker(data)
    assert info["name"] == "a" * 16


# ---------------------------------------------------------------------------
# SID-Wizard (stub)
# ---------------------------------------------------------------------------


def test_sidwizard_stub_raises():
    with pytest.raises(NotImplementedError, match="format unverified"):
        encode_sidwizard(SidParams(), "whatever")
    with pytest.raises(NotImplementedError, match="format unverified"):
        parse_sidwizard(b"xxxx")


@pytest.mark.skip(reason="SID-Wizard .swi/.ins binary format unverified - "
                         "no authoritative public spec located. See "
                         "tools/sidmatch/encoders/README.md and "
                         "tools/sidmatch/encoders/sidwizard.py for the "
                         "research trail and next steps.")
def test_sidwizard_roundtrip_rich():  # pragma: no cover
    p = _rich_params()
    data = encode_sidwizard(p, "rich_patch")
    info = parse_sidwizard(data)
    assert info["attack"] == p.attack
