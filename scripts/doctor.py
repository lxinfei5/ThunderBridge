#!/usr/bin/env python3
"""
UltraCode-Shim doctor: verify a machine is ready, validate your config, and run
the offline self-test. Cross-platform, standard library only.

    python3 scripts/doctor.py            # full check
    python3 scripts/doctor.py --no-test  # skip the proxy self-test

Exit code is non-zero if anything REQUIRED is missing, so an AI or CI can gate
on it. Each failure prints the one command that fixes it.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATEWAY = REPO / "gateway"
CONFIG = REPO / "config"

OK = "[ok]  "
NOTE = "[note]"
FAIL = "[FAIL]"
counts = {"ok": 0, "note": 0, "fail": 0}


def ok(m): counts.__setitem__("ok", counts["ok"] + 1); print(OK, m, flush=True)
def note(m): counts.__setitem__("note", counts["note"] + 1); print(NOTE, m, flush=True)
def fail(m): counts.__setitem__("fail", counts["fail"] + 1); print(FAIL, m, flush=True)


def load_env_file(p: Path):
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def referenced_vars(s: str):
    return re.findall(r"\$\{([^}]+)\}", s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-test", action="store_true", help="skip the proxy self-test")
    ap.add_argument("--ci", action="store_true",
                    help="CI mode: don't fail on a missing Claude Code CLI")
    args = ap.parse_args()

    print("UltraCode-Shim doctor")
    print("repo:", REPO)
    print()

    # 1. Python
    if sys.version_info >= (3, 8):
        ok("python %d.%d.%d" % sys.version_info[:3])
    else:
        fail("python >= 3.8 required; found %d.%d" % sys.version_info[:2])

    # 2. proxy present + compiles
    proxy = GATEWAY / "ultracode_proxy.py"
    if proxy.is_file():
        rc = subprocess.run([sys.executable, "-m", "py_compile", str(proxy)]).returncode
        ok("gateway/ultracode_proxy.py present and compiles") if rc == 0 \
            else fail("gateway/ultracode_proxy.py has a syntax error")
    else:
        fail("missing gateway/ultracode_proxy.py")

    # 3. claude CLI
    if shutil.which("claude"):
        ok("claude CLI on PATH: %s" % shutil.which("claude"))
    elif args.ci:
        note("claude CLI not found (CI mode - skipping)")
    else:
        fail("claude CLI not found - install: npm i -g @anthropic-ai/claude-code")

    # 4. config: load env, resolve slots/models (fall back to examples)
    load_env_file(CONFIG / "ultracode.env")
    slots_path = CONFIG / "ultracode_slots.json"
    models_path = CONFIG / "ultracode_models.json"
    using_example = False
    if not slots_path.is_file():
        slots_path = CONFIG / "ultracode_slots.example.json"
        models_path = CONFIG / "ultracode_models.example.json"
        using_example = True
        note("no config/ultracode_slots.json yet - validating the .example "
             "(the launcher copies it on first run)")

    slots = {}
    models = []
    try:
        raw = json.loads(slots_path.read_text(encoding="utf-8"))
        slots = {k: v for k, v in raw.items() if not k.startswith("_")}
        ok("slots file parses: %s (%d slots)" % (slots_path.name, len(slots)))
    except Exception as e:
        fail("could not parse %s: %s" % (slots_path.name, e))
    try:
        models = (json.loads(models_path.read_text(encoding="utf-8")) or {}).get("models", [])
        ok("models file parses: %s (%d models)" % (models_path.name, len(models)))
    except Exception as e:
        fail("could not parse %s: %s" % (models_path.name, e))

    # 5. discovery rule: ids must start with claude/anthropic; must be routed
    model_ids = [m.get("id") for m in models if isinstance(m, dict)]
    for mid in model_ids:
        if not re.match(r"^(claude|anthropic)", mid or "", re.I):
            fail("model id '%s' will NOT appear in /model (must start with 'claude' or 'anthropic')" % mid)
        if mid not in slots:
            fail("model '%s' has no route in slots - add a matching entry" % mid)
    if model_ids and counts["fail"] == 0:
        ok("all advertised model ids are discoverable and routed")

    # 6. per-slot backend checks
    for name, slot in slots.items():
        if not isinstance(slot, dict):
            continue
        stype = slot.get("type", "passthrough")
        if stype == "codex_oauth":
            auth = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
            if auth.is_file():
                ok("slot '%s': Codex login found (%s)" % (name, auth))
            else:
                note("slot '%s': no %s - run `codex login` before using it" % (name, auth))
            continue
        # Any slot may reference ${VARS} in auth or header values.
        refs = set(referenced_vars(slot.get("auth", "")))
        for hv in (slot.get("headers") or {}).values():
            refs.update(referenced_vars(hv))
        for var in sorted(refs):
            if os.environ.get(var):
                ok("slot '%s': key %s is set" % (name, var))
            elif using_example:
                note("slot '%s': %s not set yet (example backend; set it in "
                     "config/ultracode.env once you keep this slot)" % (name, var))
            else:
                fail("slot '%s': %s is empty - set it in config/ultracode.env" % (name, var))

    # 7. port free
    port = int(os.environ.get("UC_LISTEN_PORT", "8141"))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free = s.connect_ex(("127.0.0.1", port)) != 0
    s.close()
    ok("port %d is free" % port) if free else \
        note("port %d already in use - a proxy may already be running (fine), or pick another" % port)

    # 8. offline self-test
    if not args.no_test and (GATEWAY / "test_proxy.py").is_file():
        print("\nrunning offline self-test (gateway/test_proxy.py)...", flush=True)
        rc = subprocess.run([sys.executable, str(GATEWAY / "test_proxy.py")]).returncode
        ok("self-test passed") if rc == 0 else fail("self-test failed (see output above)")

    print()
    print("Result: %d ok, %d notes, %d failures" % (counts["ok"], counts["note"], counts["fail"]))
    if counts["fail"]:
        print("Fix the [FAIL] lines above, then re-run: python3 scripts/doctor.py")
        return 1
    if using_example:
        print("Looks good. The launcher will create your editable config on first run.")
    else:
        print("Ready. Launch: windows\\Start-UltraCode.ps1  (or  bin/ultracode  on mac/linux).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
