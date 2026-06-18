#!/usr/bin/env python3
"""
Guard: PowerShell launchers must be pure ASCII.

Windows PowerShell 5.1 decodes a BOM-less .ps1 as the system ANSI code page
(CP1252), not UTF-8. A stray non-ASCII byte (e.g. an em-dash U+2014 -> E2 80 94,
whose 0x94 is a closing curly quote in CP1252) prematurely terminates a string
literal and breaks parsing for the whole file. See issue #17.

This fails (exit 1) if any *.ps1 contains a non-ASCII byte, printing each
offending file:line so the fix is obvious. Standard library only.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    bad = []
    for path in sorted(REPO.rglob("*.ps1")):
        raw = path.read_bytes()
        for lineno, line in enumerate(raw.split(b"\n"), start=1):
            for col, byte in enumerate(line, start=1):
                if byte > 0x7F:
                    rel = path.relative_to(REPO)
                    bad.append((rel, lineno, col, byte))
                    break
    if bad:
        sys.stderr.write("non-ASCII byte(s) found in PowerShell launcher(s):\n")
        for rel, lineno, col, byte in bad:
            sys.stderr.write("  %s:%d col %d  byte 0x%02X\n" % (rel, lineno, col, byte))
        sys.stderr.write("Replace with ASCII (e.g. '--' for an em-dash); see issue #17.\n")
        return 1
    print("[ok] all .ps1 launchers are pure ASCII")
    return 0


if __name__ == "__main__":
    sys.exit(main())
