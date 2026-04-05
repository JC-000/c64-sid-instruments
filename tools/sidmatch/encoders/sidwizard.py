"""SID-Wizard instrument encoder - STUB (format unverified).

SID-Wizard (by Hermit / Mihaly Horvath) ships instruments with a ``.swi``
extension (sometimes referred to as ``.ins``). The file layout is defined in
the tracker's 6502 assembly source (compiled with 64tass) and is not
published as a stand-alone specification. A web search against the
SID-Wizard manuals (v1.4 / v1.5 / v1.6) and source-tree readmes did NOT
surface an authoritative byte-level layout we could match against a reference
example.

Rather than fabricate a format, this module raises ``NotImplementedError``
and encourages the caller to:

1. Run SID-Wizard and "Save Instrument" to obtain a reference .swi file.
2. Reverse-engineer the layout from the SID-Wizard source at
   https://github.com/anarkiwi/sid-wizard (see ``sid-wizard.asm`` around
   the ``saveins``/``loadins`` labels).
3. Re-implement ``encode_sidwizard``/``parse_sidwizard`` once the layout
   is verified against a round-tripped reference instrument.

Relevant references:

* SID-Wizard 1.5 user manual:
  https://csdb.dk/getinternalfile.php/125509/SID-Wizard-1.5-UserManual.pdf
* SID-Wizard source (fork): https://github.com/anarkiwi/sid-wizard
* SID-Wizard on SourceForge: https://sourceforge.net/projects/sid-wizard/
"""

from __future__ import annotations

from typing import Dict

from ..render import SidParams


_UNVERIFIED = (
    "SID-Wizard .ins/.swi format unverified - see docstring. Obtain a "
    "reference instrument exported by SID-Wizard itself and diff against "
    "the assembly source before implementing."
)


def encode_sidwizard(params: SidParams, name: str) -> bytes:
    """Not implemented: format unverified - see docstring."""
    raise NotImplementedError(_UNVERIFIED)


def parse_sidwizard(data: bytes) -> Dict:
    """Not implemented: format unverified - see docstring."""
    raise NotImplementedError(_UNVERIFIED)
