#!/usr/bin/env python3
r"""
ultracode_selector.py -- two-column "pick orchestrator | pick worker" screen
that runs BEFORE Claude Code launches. Matches the UltraCode target design:

    +---- ORCHESTRATOR ----+   +------ WORKER --------+
    | > MiniMax-M3         |   | > Same as orchestrator|
    |   MiMo v2.5 Pro      |   |   MiniMax-M3          |
    |   GPT-5.5 (Codex)    |   |   MiMo v2.5 Pro       |
    +----------------------+   +----------------------+

It reads the available models from the live proxy's /uc/select, lets you choose
one orchestrator (left) and one worker (right) with the arrow keys, then POSTs
the choice to the proxy so the two tiers are pre-set before Claude opens.

Controls:  Up/Down move   Tab/Left/Right switch column   Enter confirm   Esc/q cancel

Pure standard library. Works in Windows Terminal / WSL. Prints the chosen
orchestrator model id on stdout (so the launcher can pass it to claude --model).
"""
import json
import os
import sys
import urllib.request

# Windows consoles default to cp1252, which can't encode the box-drawing/arrow
# glyphs -> UnicodeEncodeError. Force UTF-8 on stdout/stderr (and the console
# code page) so the UI renders everywhere.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
if os.name == "nt":
    try:
        os.system("")  # enable ANSI/VT processing on legacy consoles
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # UTF-8 code page
    except Exception:
        pass

PROXY = os.environ.get("UC_PROXY", "http://127.0.0.1:8141").rstrip("/")
TIMEOUT = float(os.environ.get("UC_SELECTOR_TIMEOUT", "5"))


def _open_tty():
    """The launcher captures stdout to read the chosen model id, so we must draw
    the UI on the real terminal, not stdout. Open the controlling terminal
    directly (CONOUT$ on Windows, /dev/tty on POSIX); fall back to stderr."""
    try:
        path = "CONOUT$" if os.name == "nt" else "/dev/tty"
        return open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        return sys.stderr


TTY = _open_tty()

# ---- ANSI helpers ----------------------------------------------------------
ESC = "\x1b"
RESET = ESC + "[0m"
BOLD = ESC + "[1m"
DIM = ESC + "[2m"
INVERT = ESC + "[7m"
HIDE_CUR = ESC + "[?25l"
SHOW_CUR = ESC + "[?25h"
ALT_ON = ESC + "[?1049h"
ALT_OFF = ESC + "[?1049l"


def c(code):
    return ESC + "[" + code + "m"

# UltraCode purple palette (truecolor; degrades fine on basic terminals)
PURPLE = c("38;2;167;139;250")     # a78bfa
PURPLE_BG = c("48;2;76;29;149")    # 4c1d95
MAGENTA = c("38;2;192;38;211")     # c026d3
GREY = c("38;2;148;163;184")       # 94a3b8
GREEN = c("38;2;52;211;153")       # 34d399
WHITE = c("38;2;245;245;245")


def _get_models():
    req = urllib.request.Request(PROXY + "/uc/select", method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_selection(orchestrator, worker):
    data = json.dumps({"orchestrator": orchestrator, "worker": worker}).encode("utf-8")
    req = urllib.request.Request(PROXY + "/uc/select", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ---- key reading (Windows + POSIX) -----------------------------------------
def _read_key():
    """Return one of: 'up','down','left','right','tab','enter','esc','q', or ''."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "esc"
        if ch == "\t":
            return "tab"
        if ch in ("q", "Q"):
            return "q"
        if ch in ("\x00", "\xe0"):  # arrow prefix
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(ch2, "")
        if ch in (" ",):
            return "enter"
        return ""
    # POSIX -- read from the controlling terminal, not stdin (the launcher may
    # pipe stdout/stdin to capture the chosen model id).
    import termios
    import tty
    global _TTY_IN
    try:
        _TTY_IN
    except NameError:
        try:
            _TTY_IN = open("/dev/tty", "rb", buffering=0)
        except Exception:
            _TTY_IN = None
    src = _TTY_IN if _TTY_IN is not None else sys.stdin.buffer
    fd = src.fileno()
    old = termios.tcgetattr(fd)

    def _rd():
        return src.read(1).decode("utf-8", "replace")
    try:
        tty.setraw(fd)
        ch = _rd()
        if ch == "\r" or ch == "\n":
            return "enter"
        if ch == "\t":
            return "tab"
        if ch in ("q", "Q"):
            return "q"
        if ch == "\x1b":
            nxt = _rd()
            if nxt != "[":
                return "esc"
            arrow = _rd()
            return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(arrow, "")
        if ch == " ":
            return "enter"
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---- rendering -------------------------------------------------------------
BOX_W = 34


def _pad(s, w):
    # visible length ignoring ANSI (we only embed color around whole cells)
    if len(s) > w:
        return s[: w - 1] + "\u2026"
    return s + " " * (w - len(s))


def _render(orchs, workers, oi, wi, col):
    lines = []
    title = "%s%s  U L T R A C O D E %s%s  pick your two models%s" % (
        BOLD, PURPLE, RESET, GREY, RESET)
    lines.append("")
    lines.append("  " + title)
    lines.append("  " + GREY + "  orchestrator runs the main loop \u00b7 workers run every parallel sub-agent" + RESET)
    lines.append("")

    def header(label, active):
        col_c = PURPLE if active else GREY
        bar = "\u2501" * (BOX_W - len(label) - 3)
        return "  " + col_c + "\u250f\u2501 " + BOLD + label + RESET + col_c + " " + bar + "\u2513" + RESET

    def row(items, idx, active, kind):
        out = []
        for i, it in enumerate(items):
            sel = (i == idx)
            name = it["display_name"]
            if kind == "worker" and it.get("_same"):
                name = "Same as orchestrator"
            marker = (GREEN + "\u25b8 " + RESET) if sel else "  "
            cell = _pad(name, BOX_W - 4)
            if sel and active:
                body = INVERT + PURPLE + " " + cell + " " + RESET
            elif sel:
                body = PURPLE + " " + cell + " " + RESET
            else:
                body = WHITE + " " + cell + " " + RESET
            col_c = PURPLE if active else GREY
            out.append(col_c + "\u2503" + RESET + marker + body + col_c + "\u2503" + RESET)
        return out

    o_active = (col == 0)
    w_active = (col == 1)
    o_header = header("ORCHESTRATOR", o_active)
    w_header = header("WORKER", w_active)
    o_rows = row(orchs, oi, o_active, "orch")
    w_rows = row(workers, wi, w_active, "worker")

    n = max(len(o_rows), len(w_rows))
    blank_o = (PURPLE if o_active else GREY) + "\u2503" + RESET + " " * (BOX_W) + (PURPLE if o_active else GREY) + "\u2503" + RESET
    blank_w = (PURPLE if w_active else GREY) + "\u2503" + RESET + " " * (BOX_W) + (PURPLE if w_active else GREY) + "\u2503" + RESET

    def footer(active):
        col_c = PURPLE if active else GREY
        return "  " + col_c + "\u2517" + "\u2501" * (BOX_W) + "\u251b" + RESET

    lines.append("  " + o_header + "   " + w_header)
    for i in range(n):
        lo = ("  " + o_rows[i]) if i < len(o_rows) else ("  " + blank_o)
        rw = ("   " + w_rows[i]) if i < len(w_rows) else ("   " + blank_w)
        lines.append(lo + rw)
    lines.append("  " + footer(o_active) + "   " + footer(w_active))
    lines.append("")
    chosen_o = orchs[oi]["display_name"]
    chosen_w = "Same as orchestrator" if workers[wi].get("_same") else workers[wi]["display_name"]
    lines.append("  " + MAGENTA + "\u279c" + RESET + " orchestrator " + BOLD + WHITE + chosen_o + RESET +
                 GREY + "   workers " + RESET + BOLD + WHITE + chosen_w + RESET)
    lines.append("")
    lines.append("  " + DIM + "\u2191\u2193 move   \u21c6 Tab/\u2190\u2192 switch column   \u23ce confirm   esc cancel" + RESET)
    return "\n".join(lines)


def main():
    try:
        info = _get_models()
    except Exception as e:
        sys.stderr.write("ultracode-selector: cannot reach proxy at %s/uc/select (%s)\n" % (PROXY, e))
        # Fail open: no selection; launcher proceeds with defaults.
        return 2

    orchs = info.get("orchestrators") or []
    workers_raw = info.get("workers") or []
    if not orchs:
        sys.stderr.write("ultracode-selector: no models advertised by proxy; skipping.\n")
        return 2

    # Worker column = "Same as orchestrator" + each worker model.
    workers = [{"id": None, "display_name": "Same as orchestrator", "_same": True}]
    for w in workers_raw:
        workers.append({"id": w["base"], "display_name": w["display_name"].replace("Worker \u2192 ", "")})

    oi, wi, col = 0, 0, 0
    out = TTY
    out.write(ALT_ON + HIDE_CUR)
    try:
        while True:
            out.write(ESC + "[2J" + ESC + "[H")
            out.write(_render(orchs, workers, oi, wi, col))
            out.flush()
            k = _read_key()
            if k in ("esc", "q"):
                return 1
            if k == "enter":
                break
            if k in ("tab", "left", "right"):
                col = 1 - col if k == "tab" else (0 if k == "left" else 1)
            elif k == "up":
                if col == 0:
                    oi = (oi - 1) % len(orchs)
                else:
                    wi = (wi - 1) % len(workers)
            elif k == "down":
                if col == 0:
                    oi = (oi + 1) % len(orchs)
                else:
                    wi = (wi + 1) % len(workers)
    finally:
        out.write(SHOW_CUR + ALT_OFF)
        out.flush()

    orchestrator = orchs[oi]["id"]
    worker = None if workers[wi].get("_same") else workers[wi]["id"]
    try:
        _post_selection(orchestrator, worker)
    except Exception as e:
        sys.stderr.write("ultracode-selector: failed to set selection: %s\n" % e)
        return 2
    # Emit the orchestrator id so the launcher can set it as the default model.
    print(orchestrator)
    return 0


if __name__ == "__main__":
    sys.exit(main())
