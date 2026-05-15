"""Encode :class:`SidParams` to a GoatTracker 2.x ``.ins`` binary.

Format (from the GoatTracker 2 readme.txt, section "File format: .INS"):

  Offset  Size  Description
  +0      4     ID string "GTI5"
  +4      1     Attack/Decay          (high-nibble attack, low-nibble decay)
  +5      1     Sustain/Release
  +6      1     Wavepointer           (1-based index into song wavetable)
  +7      1     Pulsepointer
  +8      1     Filterpointer
  +9      1     Vibrato param         (speedtable pointer)
  +10     1     Vibrato delay
  +11     1     Gateoff timer         (HR - hard-restart timer)
  +12     1     Hard-restart/1st-frame waveform
  +13     16    Instrument name (zero-padded)
                                                 -- 29 bytes so far --

Followed by four tables, one after the other, in the order
  wavetable, pulsetable, filtertable, speedtable

Each table is encoded as:
  +0      1     n = number of rows
  +1      n     left-side bytes   (one byte per row)
  +1+n    n     right-side bytes  (one byte per row)

The meaning of "left/right" depends on which table:

* wavetable:  left = waveform byte (or jump cmd), right = note/command arg.
* pulsetable: left = speed/cmd byte, right = target high-byte (0..$7f).
* filtertable: left = cutoff/cmd, right = resonance/passband or cutoff hi.
* speedtable: vibrato speed/depth.

SidParams fields that map cleanly:
  attack, decay, sustain, release -> AD/SR bytes
  pulse_width, pw_start/pw_delta  -> pulsetable
  waveform, wt_attack/sustain    -> wavetable
  filter_cutoff, filter_resonance,
  filter_mode, filter_voice1     -> filtertable
  name (from ``name`` argument)  -> 16-byte name

SidParams fields that DO NOT round-trip through GT ins:
  frequency       (GT instruments are note-agnostic; pitch is per-pattern)
  gate_frames, release_frames  (not an instrument property)
  volume          (GT volume is song-global, not per-instrument)
  ring_mod, sync  (these are per-frame waveform bits; we pack them into
                   the wavetable rows by OR-ing the mask, which survives
                   but is not a distinct field in the .ins)
"""

from __future__ import annotations

import struct
from typing import Dict, List, Tuple

from ..render import (
    SidParams,
    _waveform_mask,
    _compute_pw_for_frame,
    _compute_filter_cutoff_for_frame,
    WF_RING_MOD,
    WF_SYNC,
    WF_TEST,
)


GTI5_MAGIC = b"GTI5"
INS_HEADER_LEN = 29  # magic(4) + 9 bytes + name(16)


def _waveform_control_byte(params: SidParams, wf_override: int = None) -> int:
    """Build the waveform byte with sync/ringmod packed in (no gate bit)."""
    wf = wf_override if wf_override is not None else _waveform_mask(params.waveform)
    if params.ring_mod:
        wf |= WF_RING_MOD
    if params.sync:
        wf |= WF_SYNC
    return wf & 0xFE  # force bit 0 (gate) off; GT sets it from note logic


def _build_wavetable_rows(params: SidParams) -> List[Tuple[int, int]]:
    """Return ``(left, right)`` rows for the GT wavetable.

    Emits the wavetable sequence: test bit frame, attack waveform frames,
    sustain waveform. Falls back to legacy wavetable if present.

    left  = waveform control byte ($00..$fe; top bit indicates "relative").
    right = note/command arg.  $00 = no pitch change (let the tracker
            control the note via the frequency registers).  Values $01-$5F
            set an absolute note, $60-$7F do relative adjustment, $80+ are
            commands.  Instruments should use $00 so the player can set
            whatever note it wants.
    """
    rows: List[Tuple[int, int]] = []

    # Legacy path: if wavetable is explicitly set and no new wt fields
    wt = params.wavetable or []
    if wt and not params.wt_attack_waveform:
        for _, wf_byte in wt:
            rows.append((_waveform_control_byte(params, wf_byte), 0x00))
        # Jump to last entry (loop on final waveform).  Row indices in an
        # .ins file are 1-based; GT relocates them on import.
        sustain_idx = len(rows)  # 1-based index of the last waveform row
        rows.append((0xFF, sustain_idx))
        return rows

    # New wavetable sequence
    attack_wf = _waveform_mask(params.effective_attack_waveform())
    sustain_wf = _waveform_mask(params.effective_sustain_waveform())
    wt_attack_frames = max(1, params.wt_attack_frames)

    if params.wt_use_test_bit:
        # Frame 0: test bit (no gate, GT handles gate separately)
        rows.append((WF_TEST & 0xFE, 0x00))

    # Attack waveform frames
    for _ in range(wt_attack_frames):
        rows.append((_waveform_control_byte(params, attack_wf), 0x00))

    # Sustain waveform (final entry)
    rows.append((_waveform_control_byte(params, sustain_wf), 0x00))

    # Loop back to sustain waveform row so the player holds on it
    # rather than advancing past the end of this instrument's table.
    sustain_idx = len(rows)  # 1-based index of sustain row
    rows.append((0xFF, sustain_idx))

    return rows


def _build_pulsetable_rows(params: SidParams) -> List[Tuple[int, int]]:
    """Return ``(left, right)`` rows for the GT pulsetable.

    For an absolute pulse-width "set" GT uses left = $8X (command) and
    right = pw_hi (high 8 bits of the 12-bit pw shifted >>4). See readme.

    If PW sweep is configured, emit sweep entries.
    """
    rows: List[Tuple[int, int]] = []

    # Legacy path
    pw_table = params.pw_table or []
    if pw_table and params.pw_start is None:
        for _, pw in pw_table:
            pw_hi = (pw >> 4) & 0x7F
            rows.append((0x80, pw_hi))
        return rows

    # New PW sweep
    pw_start = params.effective_pw_start()
    pw_delta = params.pw_delta

    if pw_delta == 0:
        # Static PW
        pw_hi = (pw_start >> 4) & 0x7F
        rows.append((0x80, pw_hi))
    else:
        # In GT, pulsetable speed byte encodes delta direction/speed.
        # Positive speed = sweep up, negative (using two's complement) = sweep down.
        # We emit the initial absolute set followed by a speed entry.
        pw_hi = (pw_start >> 4) & 0x7F
        rows.append((0x80, pw_hi))  # absolute set
        # Speed entry: delta per frame (clamped to signed byte range)
        speed = max(-128, min(127, pw_delta))
        rows.append((speed & 0xFF, 0x00))

    return rows


def _build_filtertable_rows(params: SidParams) -> List[Tuple[int, int]]:
    """Return ``(left, right)`` rows for the GT filtertable.

    GT filtertable format (from the GoatTracker 2 readme):

      Left byte   Right byte   Meaning
      ─────────   ──────────   ───────
      $80-$F0     res|routing  Set filter params.  Left high nibble = passband
                               ($90=LP, $A0=BP, $C0=HP).  Right = resonance
                               (high nibble) | channel bitmask (low nibble),
                               written directly to SID $D417.
      $00         cutoff_hi    Set cutoff.  Right byte = cutoff high 8 bits
                               (bits 3-10 of the 11-bit cutoff value).
      $01-$7F     speed        Modulation step.  Left = time in ticks,
                               right = signed speed added to cutoff each tick.
      $FF         pos          Jump.  Right = destination ($00 = stop).

    If "Set filter params" is followed by "Set cutoff" ($00 left byte) on the
    next row, both execute on the same frame.

    The player unpacks the left byte with ASL, which shifts the passband
    nibble into $D418 bits 4-6 (LP=bit4, BP=bit5, HP=bit6).  The right byte
    is stored directly into $D417 (bits 4-7 = resonance, bits 0-2 = voice
    1/2/3 routing).
    """
    rows: List[Tuple[int, int]] = []

    # Passband encoding: high nibble of the left byte (before $80 OR).
    # After ASL in the player, $10 -> bit4 (LP), $20 -> bit5 (BP),
    # $40 -> bit6 (HP).  These match SID $D418 filter-type bits.
    mode_map = {"off": 0x00, "lp": 0x10, "bp": 0x20, "hp": 0x40}
    passband = mode_map.get((params.filter_mode or "off").lower(), 0x00)

    # Right byte of the "set filter" row: resonance (high nibble) |
    # voice routing bitmask (low nibble), matching SID $D417 layout.
    voice_routing = 0x01 if params.filter_voice1 else 0x00
    res_ctrl = ((params.filter_resonance & 0x0F) << 4) | voice_routing

    cutoff_start = params.effective_filter_cutoff_start()
    cutoff_end = params.effective_filter_cutoff_end()
    sweep_frames = params.filter_sweep_frames

    cutoff_hi = (cutoff_start >> 3) & 0xFF

    # Row 1: set filter parameters (passband + resonance/routing)
    rows.append((0x80 | passband, res_ctrl))
    # Row 2: set cutoff (executed on the same frame when immediately after
    # a "set filter" row)
    rows.append((0x00, cutoff_hi))

    if sweep_frames > 0 and cutoff_start != cutoff_end:
        # Modulation step: left = time in ticks, right = speed (signed)
        delta = (cutoff_end - cutoff_start) / max(1, sweep_frames)
        speed = max(-128, min(127, int(round(delta))))
        if speed != 0:
            rows.append((sweep_frames & 0x7F, speed & 0xFF))

    # Stop filter execution so the player doesn't advance past this
    # instrument's table entries.
    rows.append((0xFF, 0x00))

    return rows


def _build_speedtable_rows() -> List[Tuple[int, int]]:
    # No vibrato in SidParams -> empty speedtable.
    return []


def _encode_table(rows: List[Tuple[int, int]]) -> bytes:
    n = len(rows)
    if n > 0xFF:
        raise ValueError(f"table too long: {n} rows")
    lefts = bytes(r[0] & 0xFF for r in rows)
    rights = bytes(r[1] & 0xFF for r in rows)
    return bytes([n]) + lefts + rights


def encode_goattracker(params: SidParams, name: str) -> bytes:
    """Encode ``params`` as a GoatTracker 2.x .ins (GTI5) file.

    ``name`` is truncated/padded to 16 bytes (ASCII).
    """
    name_bytes = name.encode("ascii", errors="replace")[:16]
    name_bytes = name_bytes + b"\x00" * (16 - len(name_bytes))

    ad = ((params.attack & 0x0F) << 4) | (params.decay & 0x0F)
    sr = ((params.sustain & 0x0F) << 4) | (params.release & 0x0F)

    # Per-instrument tables are appended at index 1 by convention; the tracker
    # will fix up pointers on load. We store "1" as the starting pointer.
    wave_rows = _build_wavetable_rows(params)
    pulse_rows = _build_pulsetable_rows(params)
    filter_rows = _build_filtertable_rows(params)
    speed_rows = _build_speedtable_rows()

    wavepointer = 1 if wave_rows else 0
    pulsepointer = 1 if pulse_rows else 0
    filterpointer = 1 if filter_rows else 0
    vibrato = 0  # no speedtable entry
    vibrato_delay = 0
    gateoff_timer = 0  # 0 = use defaults
    first_wave = _waveform_control_byte(params) | 0x01  # gate=on hint

    header = (
        GTI5_MAGIC
        + struct.pack(
            "BBBBBBBBB",
            ad, sr, wavepointer, pulsepointer, filterpointer,
            vibrato, vibrato_delay, gateoff_timer, first_wave,
        )
        + name_bytes
    )
    assert len(header) == INS_HEADER_LEN, len(header)

    return (
        header
        + _encode_table(wave_rows)
        + _encode_table(pulse_rows)
        + _encode_table(filter_rows)
        + _encode_table(speed_rows)
    )


# ---------------------------------------------------------------------------
# Parser (round trip)
# ---------------------------------------------------------------------------


def _decode_table(data: bytes, offset: int) -> Tuple[List[Tuple[int, int]], int]:
    n = data[offset]
    lefts = data[offset + 1 : offset + 1 + n]
    rights = data[offset + 1 + n : offset + 1 + 2 * n]
    rows = list(zip(lefts, rights))
    return rows, offset + 1 + 2 * n


def parse_goattracker(data: bytes) -> Dict:
    """Parse a GTI5 .ins file. Returns a dict."""
    if data[:4] != GTI5_MAGIC:
        raise ValueError(f"Not a GoatTracker .ins file (magic={data[:4]!r})")
    (ad, sr, wp, pp, fp, vib, vib_d, gt, first_wf) = struct.unpack(
        "BBBBBBBBB", data[4:13]
    )
    name = data[13:29].rstrip(b"\x00").decode("ascii", errors="replace")

    off = INS_HEADER_LEN
    wave, off = _decode_table(data, off)
    pulse, off = _decode_table(data, off)
    filt, off = _decode_table(data, off)
    speed, off = _decode_table(data, off)

    return {
        "magic": "GTI5",
        "attack": (ad >> 4) & 0x0F,
        "decay": ad & 0x0F,
        "sustain": (sr >> 4) & 0x0F,
        "release": sr & 0x0F,
        "wavepointer": wp,
        "pulsepointer": pp,
        "filterpointer": fp,
        "vibrato": vib,
        "vibrato_delay": vib_d,
        "gateoff_timer": gt,
        "first_waveform": first_wf,
        "name": name,
        "wavetable": wave,
        "pulsetable": pulse,
        "filtertable": filt,
        "speedtable": speed,
        "size": off,
    }
