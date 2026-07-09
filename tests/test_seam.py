"""Seam enforcement.

The abstraction bet of this project (docs/02) is that everything *above the seam* — the
future ``tools/``, ``mcp/``, ``agent/``, and ``evals/`` packages — is ignorant of the data
source. This test converts that intention into something that fails CI the moment the seam
leaks: nothing above the seam may reference ``obd``, ``dbc``, or ``cantools``.

Phase 0 has not built those packages yet, so this test scans whatever exists and passes
trivially today. It is committed now precisely so it is already guarding when Phase 1+
add code above the seam.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "canopy"
_ABOVE_SEAM = ("tools", "mcp", "agent", "evals")
# Word-boundary matches so we don't trip on unrelated substrings.
_FORBIDDEN = re.compile(r"\b(obd|dbc|cantools)\b", re.IGNORECASE)


def test_above_seam_has_no_data_source_leak():
    offenders: list[str] = []
    for package in _ABOVE_SEAM:
        pkg_dir = _SRC / package
        if not pkg_dir.exists():
            continue
        for py in pkg_dir.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if _FORBIDDEN.search(line):
                    offenders.append(f"{py.relative_to(_SRC)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Data-source knowledge leaked above the seam (docs/02):\n" + "\n".join(offenders)
    )
