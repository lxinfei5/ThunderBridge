#!/usr/bin/env python3
"""
codex_oauth.py -- optional helper that lets UltraCode-Shim route a model to
GPT-5.5 (and other Codex models) using a ChatGPT/Codex *login* instead of an
API key.

This is only used by routes whose "type" is "codex_oauth". It is pure Python
standard library (no pip install). It reuses the credentials created by the
official Codex CLI, so the user must first run:

    codex login

WHAT IT IS NOT
--------------
This is a thin protocol adapter. It does not implement an OAuth device flow
itself (the Codex CLI does that and writes ~/.codex/auth.json); it just reads
that token, talks to the Codex Responses API, and converts the result into the
small event vocabulary proxy.py consumes:

    {"type": "text_delta",  "text": "..."}
    {"type": "tool_call",   "id": "...", "name": "...", "arguments": "<json>"}
    {"type": "usage",       "input_tokens": N, "output_tokens": N}
    {"type": "error",       "message": "...", "status": N}

ENV KNOBS
---------
  CODEX_HOME             dir holding auth.json   (default ~/.codex)
  UC_CODEX_BASE_URL      Codex API base          (default https://chatgpt.com/backend-api/codex)
  UC_CODEX_EFFORT        reasoning effort         (default medium; none/low/medium/high/xhigh)
  UC_CODEX_SERVICE_TIER  optional service tier    (e.g. priority)
  UC_CODEX_REFRESH_CMD   best-effort refresh cmd  (default "codex login status")
  UC_CODEX_STREAM_IDLE_TIMEOUT  per-read idle timeout in seconds (default 150) --
                         bounds a stalled stream so the proxy's empty-turn retry
                         can re-attempt instead of hanging ~10 min on one turn
"""

import base64
import json
import os
import shlex
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
AUTH_FILE = CODEX_HOME / "auth.json"
BASE_URL = os.environ.get("UC_CODEX_BASE_URL", "https://chatgpt.com/backend-api/codex").rstrip("/")
RESPONSES_URL = BASE_URL + "/responses"
DEFAULT_EFFORT = os.environ.get("UC_CODEX_EFFORT", "medium")
SERVICE_TIER = os.environ.get("UC_CODEX_SERVICE_TIER", "").strip()
REFRESH_CMD = os.environ.get("UC_CODEX_REFRESH_CMD", "codex login status")
# Per-read (idle) timeout for the streaming Codex response, in seconds. urllib's
# socket timeout applies to EACH resp.read(), so this bounds how long a STALLED
# upstream (Codex opens the SSE, then goes silent mid-turn -- an intermittent
# ChatGPT-side hiccup) can block before we raise and let the proxy's empty-turn
# retry re-attempt a fresh turn. The old hard-coded 600s meant a single hung
# sub-agent could freeze an entire multi-agent / dynamic-workflow run for ~10 min.
# Codex /responses emits frequent events (created/in_progress/reasoning deltas),
# so a healthy high-effort turn effectively never goes silent this long.
STREAM_IDLE_TIMEOUT = float(os.environ.get("UC_CODEX_STREAM_IDLE_TIMEOUT", "150"))


class CodexAuthError(Exception):
    pass


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def _load_auth() -> dict:
    if not AUTH_FILE.is_file():
        raise CodexAuthError(
            "no %s -- run `codex login` first (install the Codex CLI if needed)." % AUTH_FILE)
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise CodexAuthError("could not read %s: %s" % (AUTH_FILE, e))


def _decode_jwt_claims(token: str) -> dict:
    # Best-effort, UNVERIFIED decode of the JWT payload. We only read non-secret
    # routing hints from our OWN locally-stored Codex token (the account id and
    # the exp used to decide when to nudge a refresh) -- never an authorization
    # decision -- so a signature check would add a crypto dependency for no
    # security gain. The token's authority is enforced upstream by Codex. (#27)
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


def _account_id(token: str):
    claims = _decode_jwt_claims(token)
    auth = claims.get("https://api.openai.com/auth") or {}
    return auth.get("chatgpt_account_id")


def _is_expiring(token: str, skew: int = 120) -> bool:
    claims = _decode_jwt_claims(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return time.time() >= (exp - skew)


def _best_effort_refresh() -> None:
    if not REFRESH_CMD:
        return
    try:
        # shlex.split honors quoting/escapes so a refresh command with a quoted
        # path or argument (e.g. "/opt/My Tools/codex" login status) isn't split
        # on the spaces inside the quotes. posix=False on Windows. (#27)
        argv = shlex.split(REFRESH_CMD, posix=(os.name != "nt"))
    except ValueError:
        argv = REFRESH_CMD.split()
    if not argv:
        return
    try:
        subprocess.run(argv, timeout=25, capture_output=True, check=False)
    except Exception:
        pass


def _access_token() -> str:
    state = _load_auth()
    token = (state.get("tokens") or {}).get("access_token") or ""
    if not token:
        raise CodexAuthError("no access_token in %s -- run `codex login`." % AUTH_FILE)
    if _is_expiring(token):
        _best_effort_refresh()
        state = _load_auth()
        token = (state.get("tokens") or {}).get("access_token") or token
        if _is_expiring(token):
            raise CodexAuthError("Codex token expired -- run `codex login` to refresh.")
    return token


def _headers(token: str) -> dict:
    h = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "codex_cli_rs/0.0.0",
        "originator": "codex_cli_rs",
        "OpenAI-Beta": "responses=experimental",
    }
    acc = _account_id(token)
    if acc:
        h["ChatGPT-Account-ID"] = acc
    return h


# --------------------------------------------------------------------------
# OpenAI chat-completions  ->  Codex Responses API request
# --------------------------------------------------------------------------

def _messages_to_responses_input(messages):
    instructions = []
    items = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if isinstance(content, str) and content:
                instructions.append(content)
            continue
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": m.get("tool_call_id") or "call_unknown",
                "output": content if isinstance(content, str) else json.dumps(content),
            })
            continue
        if role == "assistant":
            if isinstance(content, str) and content:
                items.append({"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": content}]})
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                items.append({
                    "type": "function_call",
                    "call_id": tc.get("id") or "call_unknown",
                    "name": fn.get("name") or "",
                    "arguments": fn.get("arguments") or "{}",
                })
            continue
        # user / default. Content is either a plain string or a list of OpenAI
        # chat parts ({"type":"text"} / {"type":"image_url"}) when the user pasted
        # an image -- map those to the Responses API's input_text / input_image so
        # vision-capable models (GPT-5.5) actually receive the image.
        if isinstance(content, list):
            parts = []
            for p in content:
                if not isinstance(p, dict):
                    if p:
                        parts.append({"type": "input_text", "text": str(p)})
                    continue
                ptype = p.get("type")
                if ptype in ("text", "input_text"):
                    parts.append({"type": "input_text", "text": p.get("text") or ""})
                elif ptype == "image_url":
                    iu = p.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else iu
                    if url:
                        parts.append({"type": "input_image", "image_url": url})
                elif ptype == "input_image" and p.get("image_url"):
                    parts.append({"type": "input_image", "image_url": p["image_url"]})
            if not parts:
                parts = [{"type": "input_text", "text": json.dumps(content)}]
        else:
            parts = [{"type": "input_text",
                      "text": content if isinstance(content, str) else json.dumps(content)}]
        items.append({"type": "message", "role": "user", "content": parts})
    return "\n\n".join(instructions), items


def _tools_to_responses(tools):
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        out.append({
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            "strict": False,
        })
    return out


def _tool_choice_to_responses(tc):
    if tc in ("auto", "required", "none"):
        return tc
    if isinstance(tc, dict) and tc.get("type") == "function":
        name = (tc.get("function") or {}).get("name")
        if name:
            return {"type": "function", "name": name}
    return "auto"


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------

def stream_events(messages, tools=None, tool_choice=None, model="gpt-5.5",
                  reasoning_effort=None, service_tier=None):
    """Yield internal events for a Codex Responses API call. Never raises for
    expected failures -- yields an {"type":"error"} event instead so the proxy
    can surface it cleanly to Claude Code."""
    try:
        token = _access_token()
    except CodexAuthError as e:
        yield {"type": "error", "message": str(e), "status": 401}
        return

    instructions, input_items = _messages_to_responses_input(messages)
    body = {
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "store": False,
        "stream": True,
        "parallel_tool_calls": True,
        "reasoning": {"effort": (reasoning_effort or DEFAULT_EFFORT)},
    }
    resp_tools = _tools_to_responses(tools)
    if resp_tools:
        body["tools"] = resp_tools
        body["tool_choice"] = _tool_choice_to_responses(tool_choice)
    tier = service_tier or SERVICE_TIER
    if tier:
        body["service_tier"] = tier

    payload = json.dumps(body).encode("utf-8")
    headers = _headers(token)
    headers["Content-Length"] = str(len(payload))
    req = urllib.request.Request(RESPONSES_URL, data=payload, headers=headers, method="POST")

    try:
        resp = urllib.request.urlopen(req, timeout=STREAM_IDLE_TIMEOUT)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        yield {"type": "error",
               "message": "Codex API HTTP %s: %s" % (e.code, detail),
               "status": e.code}
        return
    except Exception as e:
        yield {"type": "error", "message": "Codex API error: %s" % e, "status": 502}
        return

    pending = {}      # canonical id -> {"name","args"}
    alias = {}        # any id (item id "fc_..." or call id "call_...") -> canonical
    buf = b""
    in_tok = 0
    out_tok = 0
    try:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line or not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    buf = b""
                    break
                try:
                    obj = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
                et = obj.get("type") or ""
                if et == "response.output_text.delta":
                    d = obj.get("delta")
                    if d:
                        yield {"type": "text_delta", "text": d}
                elif et == "response.output_item.added":
                    item = obj.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = item.get("call_id") or ""
                        item_id = item.get("id") or ""
                        canon = call_id or item_id
                        # The 'added'/'done' events use call_id; the argument
                        # deltas use item_id. Alias both to one canonical key so
                        # we don't emit the same call twice.
                        if call_id:
                            alias[call_id] = canon
                        if item_id:
                            alias[item_id] = canon
                        pending[canon] = {"name": item.get("name") or "",
                                          "args": item.get("arguments") or ""}
                elif et == "response.function_call_arguments.delta":
                    raw = obj.get("call_id") or obj.get("item_id") or ""
                    canon = alias.get(raw, raw)
                    slot = pending.setdefault(canon, {"name": "", "args": ""})
                    if isinstance(obj.get("delta"), str):
                        slot["args"] += obj["delta"]
                elif et == "response.output_item.done":
                    item = obj.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = item.get("call_id") or ""
                        item_id = item.get("id") or ""
                        canon = alias.get(call_id) or alias.get(item_id) or call_id or item_id
                        slot = pending.get(canon, {"name": "", "args": ""})
                        name = item.get("name") or slot.get("name") or ""
                        args = item.get("arguments") or slot.get("args") or "{}"
                        yield {"type": "tool_call", "id": canon or None,
                               "name": name, "arguments": args}
                        pending.pop(canon, None)
                elif et in ("response.completed", "response.done", "response.incomplete"):
                    # response.incomplete = the turn was cut off (e.g. reasoning hit
                    # the output budget at high effort). It often carries no text/tool
                    # call -> the proxy's empty-turn retry handles it.
                    usage = ((obj.get("response") or {}).get("usage")) or {}
                    in_tok = usage.get("input_tokens", in_tok) or in_tok
                    out_tok = usage.get("output_tokens", out_tok) or out_tok
                elif et in ("error", "response.failed"):
                    err = obj.get("error") or {}
                    yield {"type": "error",
                           "message": err.get("message") or "Codex stream error",
                           "status": 502}
    except Exception as e:
        yield {"type": "error", "message": "Codex stream relay ended: %s" % e, "status": 502}
        return

    # Flush any tool calls that got an added/delta but never a 'done'. Require a
    # name: a nameless leftover is a phantom (e.g. a stray delta whose id never
    # matched an 'added'), and emitting it would be a duplicate, unusable call.
    for cid, slot in pending.items():
        if slot.get("name"):
            yield {"type": "tool_call", "id": cid or None,
                   "name": slot["name"], "arguments": slot.get("args") or "{}"}
    if in_tok or out_tok:
        yield {"type": "usage", "input_tokens": in_tok, "output_tokens": out_tok}


if __name__ == "__main__":
    # Tiny self-test: confirm auth + a one-line completion.
    import sys
    msgs = [{"role": "user", "content": "Reply with exactly: CODEX_OAUTH_OK"}]
    got = ""
    for ev in stream_events(msgs, model=os.environ.get("UC_CODEX_TEST_MODEL", "gpt-5.5")):
        if ev["type"] == "text_delta":
            got += ev["text"]
        elif ev["type"] == "error":
            print("ERROR:", ev["message"], file=sys.stderr)
            sys.exit(1)
    print(got.strip())
