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

    # Wavetable should have rows for test bit + attack frames + sustain + jump
    # test_bit=True -> 1 row, attack_frames=2 -> 2 rows, sustain -> 1 row,
    # jump -> 1 row = 5
    assert len(info["wavetable"]) >= 4

    # Pulsetable should have at least 1 row (absolute set + speed entry for delta)
    assert len(info["pulsetable"]) >= 1

    # The waveform bytes should have ring_mod + sync bits set (except test bit
    # row and the $FF jump marker)
    from tools.sidmatch.render import WF_RING_MOD, WF_SYNC
    for left, _ in info["wavetable"]:
        if left == 0xFF:  # skip jump marker
            continue
        if left != (0x08 & 0xFE):  # skip test bit row
            assert (left & WF_RING_MOD) == WF_RING_MOD
            assert (left & WF_SYNC) == WF_SYNC

    # GT filtertable row 0 = set filter params (passband + res/routing),
    # row 1 = set cutoff.  Cutoff is in the RIGHT byte of row 1.
    assert info["filtertable"][1][1] == (p.filter_cutoff >> 3) & 0xFF
    # Resonance is in the RIGHT byte of row 0 (high nibble)
    assert (info["filtertable"][0][1] >> 4) & 0x0F == p.filter_resonance


def test_goattracker_name_truncation():
    p = SidParams()
    long = "a" * 40
    data = encode_goattracker(p, long)
    info = parse_goattracker(data)
    assert info["name"] == "a" * 16


# ---------------------------------------------------------------------------
# GoatTracker – integration tests for shipped .ins files
# ---------------------------------------------------------------------------

_INSTRUMENTS_DIR = Path(__file__).resolve().parent.parent / "instruments"

_SHIPPED_INSTRUMENTS = [
    ("acoustic-guitar", "6581"),
    ("acoustic-guitar", "8580"),
    ("grand-piano", "6581"),
    ("grand-piano", "8580"),
]


@pytest.mark.parametrize("name,chip", _SHIPPED_INSTRUMENTS)
def test_goattracker_shipped_ins_parse(name, chip):
    """Load each shipped .ins, parse it, verify basic structure."""
    ins_path = _INSTRUMENTS_DIR / name / chip / f"{name}-{chip}.ins"
    data = ins_path.read_bytes()
    info = parse_goattracker(data)

    assert info["magic"] == "GTI5"
    assert 0 <= info["attack"] <= 15
    assert 0 <= info["decay"] <= 15
    assert 0 <= info["sustain"] <= 15
    assert 0 <= info["release"] <= 15
    assert len(info["name"]) > 0
    assert info["size"] == len(data)


@pytest.mark.parametrize("name,chip", _SHIPPED_INSTRUMENTS)
def test_goattracker_shipped_ins_roundtrip(name, chip):
    """Load params.json, encode to .ins, compare byte-for-byte with shipped file."""
    import json
    from tools.sidmatch.optimize import sid_params_from_dict

    ins_path = _INSTRUMENTS_DIR / name / chip / f"{name}-{chip}.ins"
    json_path = _INSTRUMENTS_DIR / name / chip / f"{name}-{chip}-params.json"

    original_data = ins_path.read_bytes()
    with open(json_path) as f:
        params_dict = json.load(f)
    params = sid_params_from_dict(params_dict)

    # The shipped .ins name is the parsed name from the file
    info = parse_goattracker(original_data)
    re_encoded = encode_goattracker(params, info["name"])

    assert re_encoded == original_data, (
        f"Re-encoded bytes differ for {name}-{chip}. "
        f"Original {len(original_data)} bytes vs re-encoded {len(re_encoded)} bytes."
    )


# ---------------------------------------------------------------------------
# GoatTracker – boundary value tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack,decay,sustain,release", [
    (0, 0, 0, 0),
    (15, 15, 15, 15),
    (0, 15, 0, 15),
    (15, 0, 15, 0),
])
def test_goattracker_adsr_boundaries(attack, decay, sustain, release):
    p = SidParams(attack=attack, decay=decay, sustain=sustain, release=release)
    data = encode_goattracker(p, "adsr_test")
    info = parse_goattracker(data)
    assert info["attack"] == attack
    assert info["decay"] == decay
    assert info["sustain"] == sustain
    assert info["release"] == release


def test_goattracker_filter_cutoff_zero():
    p = SidParams(filter_cutoff=0, filter_cutoff_start=0, filter_mode="lp")
    data = encode_goattracker(p, "fc0")
    info = parse_goattracker(data)
    # Row 0 = set filter params, row 1 = set cutoff (right byte)
    assert info["filtertable"][1][1] == 0  # cutoff_hi = 0 >> 3 = 0


def test_goattracker_filter_cutoff_max():
    p = SidParams(filter_cutoff=2047, filter_cutoff_start=2047, filter_mode="lp")
    data = encode_goattracker(p, "fc_max")
    info = parse_goattracker(data)
    # Row 1 = set cutoff, right byte = cutoff hi
    assert info["filtertable"][1][1] == (2047 >> 3) & 0xFF


def test_goattracker_filter_resonance_zero():
    """Resonance=0 with LP filter and voice1 routing.
    Row 0 left = $80 | $10 (LP passband) = $90.
    Row 0 right = (0 << 4) | 0x01 (voice1) = $01."""
    p = SidParams(filter_resonance=0, filter_mode="lp", filter_voice1=True)
    data = encode_goattracker(p, "res0")
    info = parse_goattracker(data)
    left = info["filtertable"][0][0]
    right = info["filtertable"][0][1]
    # Left = $80 | $10 = $90 (set filter + LP passband)
    assert left == 0x90
    # Right = resonance(0) << 4 | voice1(1) = $01
    assert right == 0x01


def test_goattracker_filter_resonance_max():
    """Resonance=15 with LP filter and voice1 routing.
    Row 0 left = $80 | $10 = $90.
    Row 0 right = (15 << 4) | 0x01 = $F1."""
    p = SidParams(filter_resonance=15, filter_mode="lp", filter_voice1=True)
    data = encode_goattracker(p, "res15")
    info = parse_goattracker(data)
    left = info["filtertable"][0][0]
    right = info["filtertable"][0][1]
    assert left == 0x90
    assert right == 0xF1
    # Resonance recoverable from right byte high nibble
    assert (right >> 4) & 0x0F == 15


def test_goattracker_pw_start_zero():
    p = SidParams(waveform="pulse", pw_start=0, pw_delta=0)
    data = encode_goattracker(p, "pw0")
    info = parse_goattracker(data)
    # pw_hi = (0 >> 4) & 0x7F = 0
    assert info["pulsetable"][0] == (0x80, 0x00)


def test_goattracker_pw_start_max():
    p = SidParams(waveform="pulse", pw_start=4095, pw_delta=0)
    data = encode_goattracker(p, "pw_max")
    info = parse_goattracker(data)
    # pw_hi = (4095 >> 4) & 0x7F = 255 & 0x7F = 127
    assert info["pulsetable"][0] == (0x80, 0x7F)


def test_goattracker_boundary_roundtrip():
    """Extreme ADSR + filter + PW values round-trip correctly."""
    p = SidParams(
        attack=15, decay=15, sustain=15, release=15,
        filter_cutoff=2047, filter_cutoff_start=2047,
        filter_resonance=15, filter_mode="hp",
        filter_voice1=True,
        waveform="pulse", pw_start=4095, pw_delta=0,
    )
    data = encode_goattracker(p, "boundary")
    info = parse_goattracker(data)
    assert info["attack"] == 15
    assert info["decay"] == 15
    assert info["sustain"] == 15
    assert info["release"] == 15
    # Row 0 right byte has resonance in high nibble
    assert (info["filtertable"][0][1] >> 4) & 0x0F == 15
    # Row 1 right byte has cutoff
    assert info["filtertable"][1][1] == (2047 >> 3) & 0xFF


# ---------------------------------------------------------------------------
# GoatTracker – waveform type tests
# ---------------------------------------------------------------------------

from tools.sidmatch.render import (
    WF_TRIANGLE, WF_SAW, WF_PULSE, WF_NOISE,
    WF_RING_MOD, WF_SYNC, WF_TEST, _waveform_mask,
)

_SINGLE_WAVEFORMS = [
    ("triangle", WF_TRIANGLE),
    ("saw", WF_SAW),
    ("pulse", WF_PULSE),
    ("noise", WF_NOISE),
]


@pytest.mark.parametrize("wf_name,expected_mask", _SINGLE_WAVEFORMS)
def test_goattracker_single_waveform(wf_name, expected_mask):
    """Each single waveform encodes the correct mask bits in the wavetable."""
    p = SidParams(
        waveform=wf_name,
        wt_attack_waveform=wf_name,
        wt_sustain_waveform=wf_name,
        wt_use_test_bit=False,
    )
    data = encode_goattracker(p, "wf_test")
    info = parse_goattracker(data)
    # All wavetable rows should contain the expected waveform mask (with gate off)
    for left, _ in info["wavetable"]:
        assert left & expected_mask == expected_mask, (
            f"waveform={wf_name}: row left=0x{left:02x} missing 0x{expected_mask:02x}"
        )


_COMBO_WAVEFORMS = [
    ("triangle+pulse", WF_TRIANGLE | WF_PULSE),
    ("saw+pulse", WF_SAW | WF_PULSE),
    ("triangle+saw", WF_TRIANGLE | WF_SAW),
]


@pytest.mark.parametrize("wf_name,expected_mask", _COMBO_WAVEFORMS)
def test_goattracker_combo_waveform(wf_name, expected_mask):
    """Combined waveforms encode all the correct mask bits."""
    p = SidParams(
        waveform=wf_name,
        wt_attack_waveform=wf_name,
        wt_sustain_waveform=wf_name,
        wt_use_test_bit=False,
    )
    data = encode_goattracker(p, "wf_combo")
    info = parse_goattracker(data)
    for left, _ in info["wavetable"]:
        assert left & expected_mask == expected_mask, (
            f"waveform={wf_name}: row left=0x{left:02x} missing 0x{expected_mask:02x}"
        )


# ---------------------------------------------------------------------------
# GoatTracker – filter mode tests
# ---------------------------------------------------------------------------

_FILTER_MODES = [
    ("lp", 0x10),   # $90 & $70 = $10
    ("bp", 0x20),   # $A0 & $70 = $20
    ("hp", 0x40),   # $C0 & $70 = $40
    ("off", 0x00),  # $80 & $70 = $00
]


@pytest.mark.parametrize("mode,expected_bits", _FILTER_MODES)
def test_goattracker_filter_mode(mode, expected_bits):
    """Each filter mode encodes the correct passband bits in the filtertable.

    In GT2, the left byte of a "set filter" row is $80 | passband, where
    passband occupies the high nibble: $10=LP, $20=BP, $40=HP.  The player
    does ASL to shift these into $D418 bits 4-6.
    """
    p = SidParams(filter_mode=mode, filter_resonance=0)
    data = encode_goattracker(p, "filt_mode")
    info = parse_goattracker(data)
    left = info["filtertable"][0][0]
    # Passband is in bits 4-6 of the left byte (mask out the $80 cmd bit)
    passband = left & 0x70
    assert passband == expected_bits, (
        f"mode={mode}: passband=0x{passband:02x} expected 0x{expected_bits:02x}"
    )


# ---------------------------------------------------------------------------
# GoatTracker – ring mod and sync tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ring_mod,sync", [
    (True, False),
    (False, True),
    (True, True),
    (False, False),
])
def test_goattracker_ring_mod_sync(ring_mod, sync):
    """Ring mod and sync bits are independently controlled in wavetable rows."""
    p = SidParams(
        waveform="saw",
        wt_attack_waveform="saw",
        wt_sustain_waveform="saw",
        wt_use_test_bit=False,
        ring_mod=ring_mod,
        sync=sync,
    )
    data = encode_goattracker(p, "rmsync")
    info = parse_goattracker(data)
    for left, _ in info["wavetable"]:
        if left == 0xFF:  # skip jump marker
            continue
        if ring_mod:
            assert left & WF_RING_MOD == WF_RING_MOD
        else:
            assert left & WF_RING_MOD == 0
        if sync:
            assert left & WF_SYNC == WF_SYNC
        else:
            assert left & WF_SYNC == 0


# ---------------------------------------------------------------------------
# GoatTracker – negative pw_delta (two's complement)
# ---------------------------------------------------------------------------

def test_goattracker_negative_pw_delta():
    """Negative pw_delta encodes as two's complement byte."""
    p = SidParams(waveform="pulse", pw_start=3000, pw_delta=-26)
    data = encode_goattracker(p, "neg_pwd")
    info = parse_goattracker(data)
    # Should have 2 rows: absolute set + speed entry
    assert len(info["pulsetable"]) == 2
    speed_byte = info["pulsetable"][1][0]
    # -26 in two's complement unsigned byte = 256 - 26 = 230
    assert speed_byte == (-26) & 0xFF
    assert speed_byte == 230


# ---------------------------------------------------------------------------
# GoatTracker – wt_use_test_bit=False
# ---------------------------------------------------------------------------

def test_goattracker_no_test_bit():
    """When wt_use_test_bit=False, wavetable has fewer rows (no test bit frame)."""
    p_with = SidParams(
        waveform="saw",
        wt_attack_waveform="saw",
        wt_sustain_waveform="saw",
        wt_attack_frames=2,
        wt_use_test_bit=True,
    )
    p_without = SidParams(
        waveform="saw",
        wt_attack_waveform="saw",
        wt_sustain_waveform="saw",
        wt_attack_frames=2,
        wt_use_test_bit=False,
    )
    data_with = encode_goattracker(p_with, "tb_on")
    data_without = encode_goattracker(p_without, "tb_off")
    info_with = parse_goattracker(data_with)
    info_without = parse_goattracker(data_without)

    # With test bit: test_frame(1) + attack(2) + sustain(1) + jump(1) = 5 rows
    assert len(info_with["wavetable"]) == 5
    # Without test bit: attack(2) + sustain(1) + jump(1) = 4 rows
    assert len(info_without["wavetable"]) == 4

    # The first row with test bit should have WF_TEST set
    assert info_with["wavetable"][0][0] & WF_TEST != 0
    # None of the waveform rows without test bit should have WF_TEST
    # (skip the $FF jump marker)
    for left, _ in info_without["wavetable"]:
        if left == 0xFF:
            continue
        assert left & WF_TEST == 0


# ---------------------------------------------------------------------------
# GoatTracker – empty/minimal instrument
# ---------------------------------------------------------------------------

def test_goattracker_default_sidparams():
    """Default SidParams() with no special features encodes/parses cleanly."""
    p = SidParams()
    data = encode_goattracker(p, "minimal")
    info = parse_goattracker(data)

    assert info["magic"] == "GTI5"
    assert info["name"] == "minimal"
    assert info["attack"] == p.attack
    assert info["decay"] == p.decay
    assert info["sustain"] == p.sustain
    assert info["release"] == p.release
    assert len(info["wavetable"]) >= 1
    assert len(info["pulsetable"]) >= 1
    assert len(info["filtertable"]) >= 1
    assert info["size"] == len(data)

    # Re-encode should produce identical bytes
    data2 = encode_goattracker(p, "minimal")
    assert data2 == data


# ---------------------------------------------------------------------------
# GoatTracker – name edge cases
# ---------------------------------------------------------------------------

def test_goattracker_empty_name():
    p = SidParams()
    data = encode_goattracker(p, "")
    info = parse_goattracker(data)
    assert info["name"] == ""


def test_goattracker_exact_16_char_name():
    p = SidParams()
    name16 = "abcdefghijklmnop"
    assert len(name16) == 16
    data = encode_goattracker(p, name16)
    info = parse_goattracker(data)
    assert info["name"] == name16


def test_goattracker_non_ascii_name():
    """Non-ASCII characters get replaced (ASCII-only encoder)."""
    p = SidParams()
    data = encode_goattracker(p, "caf\u00e9")
    info = parse_goattracker(data)
    # The encoder uses errors="replace", so non-ASCII becomes '?'
    assert len(info["name"]) == 4
    assert info["name"][:3] == "caf"


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
