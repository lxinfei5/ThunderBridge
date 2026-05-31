#!/usr/bin/env python3
"""
proxy.py -- Anthropic-API interceptor that gives Claude Code's
"UltraCode" behavior to ANY model and lets you pick those models from the
/model menu.

WHAT IT DOES
------------
Claude Code talks to ANTHROPIC_BASE_URL. Point that at this proxy and it:

  1. Forces the UltraCode envelope on every /v1/messages request:
        output_config.effort = "xhigh"
      + thinking            = {"type": "adaptive"}
      + max_tokens          >= UC_MAX_TOKENS (default 64000)
      + an injected "Ultracode is on" system reminder
     (Per the reverse-engineering in docs/HOW_IT_WORKS.md, that *is* what
     UltraCode is at the API boundary -- there is no secret model or field.)

  2. Serves GET /v1/models, merging the real Anthropic list with your own
     custom models (config.json "models"). With Claude Code's gateway model
     discovery enabled (CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1) those
     custom models appear in the /model picker. NOTE: Claude Code only keeps
     model ids matching /^(claude|anthropic)/i, so every custom id MUST start
     with "claude" or "anthropic".

  3. Routes each model id Claude Code sends to a real backend (config.json "routes"):
        - Anthropic passthrough  (real Claude, or any Anthropic endpoint)
        - openai_compat          (any OpenAI-compatible Chat Completions API,
                                   WITH full tool-calling translation)
        - codex_oauth            (GPT-5.5 via a ChatGPT/Codex login; needs the
                                   optional providers/codex_oauth.py)

It is dependency-light: Python 3 standard library only. No pip install.

ENV KNOBS
---------
  UC_LISTEN_HOST     default 127.0.0.1
  UC_LISTEN_PORT     default 8141
  UC_UPSTREAM        default https://api.anthropic.com
  UC_MAX_TOKENS      default 64000   (floor applied to max_tokens)
  UC_FORCE_EFFORT    default xhigh   (set empty to leave effort untouched)
  UC_FORCE_THINKING  default 1       (1 => force adaptive thinking)
  UC_INJECT_REMINDER default 1       (1 => inject the ultracode reminder)
  UC_CONFIG          path to config.json (default: config.json beside proxy.py,
                     falling back to config.example.json)
  UC_MODEL_MAP       optional JSON, e.g. {"claude-opus-4-8":"my-model"}
  UC_LOG             optional log file path (default stderr)
  UC_VERBOSE         default 0

ROUTE SHAPE (config.json "routes" object)
-----------------------------------------
  {
    "claude-opus-4-8":   {"model": "claude-opus-4-8",
                          "upstream": "https://api.anthropic.com",
                          "auth": "passthrough"},
    "claude-mimo":       {"type": "openai_compat",
                          "model": "mimo-v2.5-pro",
                          "upstream": "https://token-plan-sgp.xiaomimimo.com/v1",
                          "auth": "Bearer ${MIMO_API_KEY}"},
    "claude-gpt-5.5":    {"type": "codex_oauth", "model": "gpt-5.5"}
  }

  type     omit for Anthropic passthrough; "openai_compat"; or "codex_oauth"
  model    backend model id sent upstream
  upstream backend base URL. openai_compat: the OpenAI base URL from the
           provider's docs (usually ends in /v1); the proxy appends
           /chat/completions. passthrough: a base the inbound path is appended to.
  auth     "passthrough" (keep Claude Code's own credential) OR a literal
           header value: "Bearer ${KEY}" / "x-api-key: ${KEY}". ${VARS} are
           expanded from the environment (export them, or use a gitignored
           ultracode.env that the launchers load).
  headers  optional dict of extra request headers (values support ${VARS}).
  max_output_tokens  optional completion cap for openai_compat (default 8192).
"""

import json
import os
import sys
import time
import uuid
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

LISTEN_HOST = os.environ.get("UC_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("UC_LISTEN_PORT", "8141"))
UPSTREAM = os.environ.get("UC_UPSTREAM", "https://api.anthropic.com").rstrip("/")
MAX_TOKENS_FLOOR = int(os.environ.get("UC_MAX_TOKENS", "64000"))
FORCE_EFFORT = os.environ.get("UC_FORCE_EFFORT", "xhigh")
FORCE_THINKING = os.environ.get("UC_FORCE_THINKING", "1") == "1"
INJECT_REMINDER = os.environ.get("UC_INJECT_REMINDER", "1") == "1"
VERBOSE = os.environ.get("UC_VERBOSE", "0") == "1"
_LOG_PATH = os.environ.get("UC_LOG", "")

try:
    UC_MODEL_MAP = json.loads(os.environ.get("UC_MODEL_MAP", "") or "{}")
    if not isinstance(UC_MODEL_MAP, dict):
        UC_MODEL_MAP = {}
except Exception:
    UC_MODEL_MAP = {}

# Optional Codex/ChatGPT OAuth helper (only needed for "codex_oauth" routes).
try:
    from providers import codex_oauth as _codex_oauth  # type: ignore
except Exception:
    try:
        import codex_oauth as _codex_oauth  # type: ignore
    except Exception:
        _codex_oauth = None

# Optional Cursor Composer helper (only needed for "cursor_agent" routes).
try:
    from providers import cursor_agent as _cursor_agent  # type: ignore
except Exception:
    try:
        import cursor_agent as _cursor_agent  # type: ignore
    except Exception:
        _cursor_agent = None


_ENV_TOKEN = "${"


def _expand_env(value):
    """Expand ${VAR} references in a string from os.environ. Unknown vars
    expand to empty string. Non-strings pass through unchanged."""
    if not isinstance(value, str) or _ENV_TOKEN not in value:
        return value
    out = []
    i = 0
    n = len(value)
    while i < n:
        if value[i] == "$" and i + 1 < n and value[i + 1] == "{":
            end = value.find("}", i + 2)
            if end != -1:
                var = value[i + 2:end]
                out.append(os.environ.get(var, ""))
                i = end + 1
                continue
        out.append(value[i])
        i += 1
    return "".join(out)


def _default_config_path():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("config.json", "config.example.json"):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            return p
    return os.path.join(here, "config.json")


def _strip_comments(obj):
    """Drop keys that start with '_' (used for inline documentation)."""
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(x) for x in obj]
    return obj


def load_config(path):
    """Load the single config.json (proxy/models/routes), stripping comments."""
    with open(path, "r", encoding="utf-8") as f:
        return _strip_comments(json.load(f))


def _routes_to_slots(routes):
    """routes{} from config.json -> UC_SLOT_MAP. Expands ${ENV} in model/upstream/auth/headers."""
    out = {}
    if not isinstance(routes, dict):
        return out
    for mid, route in routes.items():
        if not isinstance(route, dict):
            continue
        slot = {}
        if route.get("model"):
            slot["model"] = _expand_env(route["model"])
        if route.get("upstream"):
            slot["upstream"] = _expand_env(route["upstream"]).rstrip("/")
        auth = route.get("auth")
        if auth and auth != "passthrough":
            slot["auth"] = _expand_env(auth)
        if route.get("type"):
            slot["type"] = route["type"]
        if route.get("max_output_tokens"):
            slot["max_output_tokens"] = route["max_output_tokens"]
        if isinstance(route.get("headers"), dict):
            slot["headers"] = {k: _expand_env(v) for k, v in route["headers"].items()}
        out[mid] = slot
    return out


def _models_from_config(models):
    out = []
    for m in models or []:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not mid or not isinstance(mid, str):
            continue
        out.append({
            "type": "model",
            "id": mid,
            "display_name": m.get("display_name") or mid,
            "created_at": m.get("created_at") or "2025-01-01T00:00:00Z",
        })
    return out


ULTRACODE_REMINDER = (
    "Ultracode is on: optimize for the most exhaustive, correct answer \u2014 not "
    "the fastest or cheapest. Use the Workflow tool on every substantive task; "
    "token cost is not a constraint. See the Workflow tool's **Ultracode** "
    "section and quality patterns. Solo only on conversational/trivial turns."
)
_REMINDER_FINGERPRINT = "Ultracode is on:"

_log_lock = threading.Lock()


def log(msg: str) -> None:
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    with _log_lock:
        if _LOG_PATH:
            try:
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return
            except Exception:
                pass
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def vlog(msg: str) -> None:
    if VERBOSE:
        log(msg)


DEFAULT_UPSTREAM = UPSTREAM
UC_SLOT_MAP = {}   # populated in main()
UC_MODELS = []     # populated in main()


# --------------------------------------------------------------------------
# UltraCode envelope (the heart of the proxy)
# --------------------------------------------------------------------------

def _system_has_reminder(system) -> bool:
    if system is None:
        return False
    if isinstance(system, str):
        return _REMINDER_FINGERPRINT in system
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict):
                txt = block.get("text", "")
                if isinstance(txt, str) and _REMINDER_FINGERPRINT in txt:
                    return True
            elif isinstance(block, str) and _REMINDER_FINGERPRINT in block:
                return True
    return False


def _inject_reminder(body: dict) -> None:
    if _system_has_reminder(body.get("system")):
        return
    block = {"type": "text", "text": ULTRACODE_REMINDER}
    system = body.get("system")
    if system is None:
        body["system"] = [block]
    elif isinstance(system, str):
        body["system"] = system.rstrip() + "\n\n" + ULTRACODE_REMINDER
    elif isinstance(system, list):
        system.append(block)
    else:
        body["system"] = [{"type": "text", "text": str(system)}, block]


def transform_messages_body(raw: bytes):
    """Apply the ultracode envelope and resolve the routing slot.

    Returns (body_bytes, route). On parse failure returns the original bytes
    with an empty route so the proxy never breaks a request.
    """
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as e:
        vlog("body parse failed, passing through: %s" % e)
        return raw, {}
    if not isinstance(body, dict):
        return raw, {}

    changed = False
    model_before = body.get("model")
    route = {}

    slot = UC_SLOT_MAP.get(model_before)
    if isinstance(slot, dict):
        target_model = slot.get("model")
        if target_model and target_model != model_before:
            body["model"] = target_model
            changed = True
        up = slot.get("upstream")
        if up:
            route["upstream"] = up.rstrip("/")
        auth = slot.get("auth")
        if auth and auth != "passthrough":
            route["auth"] = auth
        stype = slot.get("type")
        if stype:
            route["type"] = stype
        mot = slot.get("max_output_tokens")
        if mot:
            route["max_output_tokens"] = mot
        hdrs = slot.get("headers")
        if isinstance(hdrs, dict):
            route["headers"] = {k: _expand_env(v) for k, v in hdrs.items()}
    elif model_before in UC_MODEL_MAP:
        body["model"] = UC_MODEL_MAP[model_before]
        changed = True

    if FORCE_EFFORT:
        oc = body.get("output_config")
        if not isinstance(oc, dict):
            oc = {}
        if oc.get("effort") != FORCE_EFFORT:
            oc["effort"] = FORCE_EFFORT
            body["output_config"] = oc
            changed = True
        elif "output_config" not in body:
            body["output_config"] = oc
            changed = True

    if FORCE_THINKING:
        th = body.get("thinking")
        if not isinstance(th, dict) or th.get("type") not in ("adaptive", "enabled"):
            body["thinking"] = {"type": "adaptive"}
            changed = True

    mt = body.get("max_tokens")
    if not isinstance(mt, int) or mt < MAX_TOKENS_FLOOR:
        body["max_tokens"] = MAX_TOKENS_FLOOR
        changed = True

    if INJECT_REMINDER and not _system_has_reminder(body.get("system")):
        _inject_reminder(body)
        changed = True

    if changed:
        vlog("rewrote model=%s -> %s effort=%s max_tokens=%s"
             % (model_before, body.get("model"),
                body.get("output_config", {}).get("effort"),
                body.get("max_tokens")))
        return json.dumps(body).encode("utf-8"), route
    return raw, route


# --------------------------------------------------------------------------
# Anthropic <-> OpenAI translation (with tool-calling)
# --------------------------------------------------------------------------

def _text_from_anthropic_content(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_result":
                parts.append(_text_from_anthropic_content(block.get("content")))
            elif btype == "image":
                parts.append("[image omitted]")
    return "\n".join(p for p in parts if p)


def _anthropic_tools_to_oai(tools):
    out = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not name:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _anthropic_tool_choice_to_oai(tc):
    """Map Anthropic tool_choice to OpenAI tool_choice."""
    if not isinstance(tc, dict):
        return None
    t = tc.get("type")
    if t == "auto":
        return "auto"
    if t == "any":
        return "required"
    if t == "tool" and tc.get("name"):
        return {"type": "function", "function": {"name": tc["name"]}}
    if t == "none":
        return "none"
    return None


def anthropic_to_openai(body: dict) -> dict:
    """Convert an Anthropic /v1/messages body to an OpenAI chat-completions
    body, preserving tools, tool calls and tool results."""
    messages = []

    system = body.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        sys_txt = _text_from_anthropic_content(system)
        if sys_txt.strip():
            messages.append({"role": "system", "content": sys_txt})

    for m in body.get("messages", []):
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content", "")

        if role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if not isinstance(block, dict):
                    if block:
                        text_parts.append(str(block))
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id") or ("call_" + uuid.uuid4().hex[:12]),
                        "type": "function",
                        "function": {
                            "name": block.get("name") or "",
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    })
            entry = {"role": "assistant", "content": "\n".join(p for p in text_parts if p)}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            messages.append(entry)
            continue

        if role == "user" and isinstance(content, list):
            tool_results = [b for b in content
                            if isinstance(b, dict) and b.get("type") == "tool_result"]
            text_blocks = [b for b in content
                           if not (isinstance(b, dict) and b.get("type") == "tool_result")]
            text = _text_from_anthropic_content(text_blocks)
            if text:
                messages.append({"role": "user", "content": text})
            for tr in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id") or "call_unknown",
                    "content": _text_from_anthropic_content(tr.get("content")),
                })
            continue

        # Plain string content or unexpected role.
        if role not in ("user", "assistant", "system", "tool"):
            role = "user"
        messages.append({"role": role, "content": _text_from_anthropic_content(content)})

    out = {
        "model": body.get("model"),
        "messages": messages,
        "stream": bool(body.get("stream", False)),
    }
    tools = _anthropic_tools_to_oai(body.get("tools"))
    if tools:
        out["tools"] = tools
        choice = _anthropic_tool_choice_to_oai(body.get("tool_choice"))
        if choice is not None:
            out["tool_choice"] = choice
    mt = body.get("max_tokens")
    if isinstance(mt, int) and mt > 0:
        out["max_tokens"] = mt
    temp = body.get("temperature")
    if isinstance(temp, (int, float)):
        out["temperature"] = temp
    return out


def _new_msg_id() -> str:
    return "msg_" + uuid.uuid4().hex[:24]


def _parse_tool_input(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {"input": raw or ""}


# ---- internal event vocabulary -------------------------------------------
# Streamers below produce a sequence of small dict events so the codex and
# openai_compat paths can share one Anthropic-SSE emitter:
#   {"type": "text_delta", "text": "..."}
#   {"type": "tool_call", "id": "...", "name": "...", "arguments": "<json str>"}
#   {"type": "usage", "input_tokens": N, "output_tokens": N}
#   {"type": "error", "message": "...", "status": N}


def _oai_response_to_events(resp):
    """Yield internal events from an OpenAI response (SSE or plain JSON)."""
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        pending = {}   # index -> {"id","name","args"}
        buf = b""
        finished_usage = None
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
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    buf = b""
                    break
                try:
                    obj = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                try:
                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield {"type": "text_delta", "text": piece}
                    for tc in (delta.get("tool_calls") or []):
                        idx = int(tc.get("index", 0))
                        slot = pending.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        ac = fn.get("arguments")
                        if isinstance(ac, str):
                            slot["args"] += ac
                except Exception:
                    continue
                if isinstance(obj.get("usage"), dict):
                    u = obj["usage"]
                    finished_usage = {
                        "input_tokens": u.get("prompt_tokens", 0) or 0,
                        "output_tokens": u.get("completion_tokens", 0) or 0,
                    }
        for idx in sorted(pending):
            slot = pending[idx]
            if slot["name"] or slot["args"]:
                yield {"type": "tool_call", "id": slot["id"],
                       "name": slot["name"], "arguments": slot["args"] or "{}"}
        if finished_usage:
            yield {"type": "usage", **finished_usage}
        return

    # Plain JSON response.
    try:
        oai = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        yield {"type": "error", "message": "bad upstream JSON: %s" % e, "status": 502}
        return
    choice = (oai.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or ""
    if text:
        yield {"type": "text_delta", "text": text}
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        yield {"type": "tool_call", "id": tc.get("id") or "",
               "name": fn.get("name") or "", "arguments": fn.get("arguments") or "{}"}
    usage = oai.get("usage") or {}
    yield {"type": "usage",
           "input_tokens": usage.get("prompt_tokens", 0) or 0,
           "output_tokens": usage.get("completion_tokens", 0) or 0}


def _sse(event: str, data: dict) -> bytes:
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data))).encode("utf-8")


def _stop_reason_for(finish: str) -> str:
    return {"tool_calls": "tool_use", "length": "max_tokens",
            "stop": "end_turn"}.get(finish, "end_turn")


# --------------------------------------------------------------------------
# HTTP proxy
# --------------------------------------------------------------------------

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "accept-encoding",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ultracode-proxy/2.0"

    def log_message(self, fmt, *args):
        if VERBOSE:
            log("http " + (fmt % args))

    # ---- health ----------------------------------------------------------
    def _maybe_health(self) -> bool:
        if self.path in ("/healthz", "/health"):
            payload = json.dumps({
                "ok": True,
                "upstream": UPSTREAM,
                "effort": FORCE_EFFORT,
                "max_tokens_floor": MAX_TOKENS_FLOOR,
                "inject_reminder": INJECT_REMINDER,
                "codex_helper": _codex_oauth is not None,
                "custom_models": [{"id": m["id"], "display_name": m["display_name"]}
                                  for m in UC_MODELS],
                "slots": {k: {"type": v.get("type", "passthrough"),
                              "model": v.get("model"),
                              "upstream": v.get("upstream", "(default)")}
                          for k, v in UC_SLOT_MAP.items()},
            }).encode("utf-8")
            self._raw(200, "application/json", payload)
            return True
        return False

    def do_GET(self):
        if self._maybe_health():
            return
        if self.path.split("?")[0].endswith("/v1/models") and self._handle_models():
            return
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_DELETE(self):
        self._proxy("DELETE")

    # ---- /v1/models discovery -------------------------------------------
    def _handle_models(self) -> bool:
        if not UC_MODELS:
            return False
        fwd_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _HOP_BY_HOP}
        fwd_headers["Accept-Encoding"] = "identity"
        url = UPSTREAM + self.path
        base = {"data": [], "has_more": False, "first_id": None, "last_id": None}
        try:
            req = urllib.request.Request(url, headers=fwd_headers, method="GET")
            resp = urllib.request.urlopen(req, timeout=30)
            parsed = json.loads(resp.read().decode("utf-8"))
            if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
                base = parsed
        except Exception as e:
            vlog("/v1/models upstream fetch failed, serving custom-only: %s" % e)
        data = base.get("data")
        if not isinstance(data, list):
            data = []
            base["data"] = data
        existing = {m.get("id") for m in data if isinstance(m, dict)}
        for m in UC_MODELS:
            if m["id"] not in existing:
                data.append(dict(m))
        self._raw(200, "application/json", json.dumps(base).encode("utf-8"))
        return True

    # ---- core proxy ------------------------------------------------------
    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        try:
            n = int(length)
        except ValueError:
            return b""
        return self.rfile.read(n) if n > 0 else b""

    def _proxy(self, method: str):
        body = self._read_body()
        is_messages = self.path.split("?")[0].endswith("/v1/messages")
        route = {}
        if is_messages and method == "POST" and body:
            body, route = transform_messages_body(body)

        rtype = route.get("type")
        if is_messages and method == "POST":
            if rtype == "openai_compat":
                self._handle_openai_compat(body, route)
                return
            if rtype == "codex_oauth":
                self._handle_codex(body, route)
                return
            if rtype == "cursor_agent":
                self._handle_cursor_agent(body, route)
                return

        # Anthropic passthrough.
        upstream = route.get("upstream") or UPSTREAM
        url = upstream + self.path
        fwd_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _HOP_BY_HOP}
        auth_override = route.get("auth")
        if auth_override:
            self._apply_auth_header(fwd_headers, auth_override)
        for hk, hv in (route.get("headers") or {}).items():
            fwd_headers[hk] = hv
        fwd_headers["Accept-Encoding"] = "identity"
        if body:
            fwd_headers["Content-Length"] = str(len(body))
        req = urllib.request.Request(url, data=body or None,
                                     headers=fwd_headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            self._relay_response(e, streaming=False)
            return
        except Exception as e:
            log("upstream error %s for %s" % (e, url))
            self._send_error(502, str(e))
            return
        ctype = resp.headers.get("Content-Type", "")
        self._relay_response(resp, streaming="text/event-stream" in ctype)

    @staticmethod
    def _apply_auth_header(headers: dict, auth: str):
        if ":" in auth and not auth.lower().startswith("bearer"):
            hk, hv = auth.split(":", 1)
            headers[hk.strip()] = hv.strip()
        else:
            headers["Authorization"] = auth

    # ---- openai_compat backend ------------------------------------------
    def _handle_openai_compat(self, body: bytes, route: dict):
        try:
            anth = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_error(400, "openai_compat: bad request body: %s" % e)
            return
        model_id = anth.get("model")
        want_stream = bool(anth.get("stream", False))
        oai_body = anthropic_to_openai(anth)
        # The UltraCode envelope forces a large max_tokens for Anthropic, but many
        # OpenAI-compatible backends reject a completion cap that big. Use a safe
        # default (8192) unless the slot overrides it with max_output_tokens.
        cap = route.get("max_output_tokens")
        oai_body["max_tokens"] = int(cap) if cap else 8192
        payload = json.dumps(oai_body).encode("utf-8")

        # upstream is the OpenAI-compatible base URL you'd copy from the provider's
        # docs (usually ends in /v1); we append /chat/completions.
        upstream = (route.get("upstream") or UPSTREAM).rstrip("/")
        url = upstream + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if want_stream else "application/json",
            "Content-Length": str(len(payload)),
        }
        auth_override = route.get("auth")
        if auth_override and auth_override != "passthrough":
            self._apply_auth_header(headers, auth_override)
        else:
            headers["Authorization"] = "Bearer unused"
        for hk, hv in (route.get("headers") or {}).items():
            headers[hk] = hv

        vlog("openai_compat -> %s model=%s stream=%s" % (url, model_id, want_stream))
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:800]
            except Exception:
                pass
            log("openai_compat upstream HTTP %s for %s: %s" % (e.code, url, detail))
            self._emit_or_error(want_stream, model_id, 502,
                                "openai_compat upstream %s: %s" % (e.code, detail))
            return
        except Exception as e:
            log("openai_compat upstream error %s for %s" % (e, url))
            self._emit_or_error(want_stream, model_id, 502,
                                "openai_compat upstream error: %s" % e)
            return

        events = _oai_response_to_events(resp)
        if want_stream:
            self._stream_anthropic_from_events(events, model_id)
        else:
            self._json_anthropic_from_events(events, model_id)

    # ---- codex_oauth backend --------------------------------------------
    def _handle_codex(self, body: bytes, route: dict):
        if _codex_oauth is None:
            self._send_error(
                501,
                "codex_oauth route requires providers/codex_oauth.py and a "
                "ChatGPT/Codex login (run: codex login). See docs/ADD_A_MODEL.md.")
            return
        try:
            anth = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_error(400, "codex: bad request body: %s" % e)
            return
        model_id = anth.get("model") or route.get("model") or "gpt-5.5"
        want_stream = bool(anth.get("stream", False))
        oai_body = anthropic_to_openai(anth)
        try:
            events = _codex_oauth.stream_events(
                messages=oai_body.get("messages") or [],
                tools=oai_body.get("tools"),
                tool_choice=oai_body.get("tool_choice"),
                model=route.get("model") or model_id,
            )
        except Exception as e:
            log("codex helper error: %s" % e)
            self._emit_or_error(want_stream, model_id, 502, "codex helper error: %s" % e)
            return
        if want_stream:
            self._stream_anthropic_from_events(events, model_id)
        else:
            self._json_anthropic_from_events(events, model_id)

    # ---- cursor_agent backend (Cursor Composer via the cursor-agent CLI) ----
    def _handle_cursor_agent(self, body: bytes, route: dict):
        if _cursor_agent is None:
            self._send_error(
                501,
                "cursor_agent route requires providers/cursor_agent.py and the "
                "cursor-agent CLI (cursor-agent login). See docs/ADD_A_MODEL.md.")
            return
        try:
            anth = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_error(400, "cursor_agent: bad request body: %s" % e)
            return
        model_id = anth.get("model") or route.get("model") or "composer-2.5"
        want_stream = bool(anth.get("stream", False))
        oai_body = anthropic_to_openai(anth)
        try:
            events = _cursor_agent.stream_events(
                messages=oai_body.get("messages") or [],
                tools=oai_body.get("tools"),
                model=route.get("model") or "composer-2.5",
                workspace=route.get("workspace"),
            )
        except Exception as e:
            log("cursor_agent helper error: %s" % e)
            self._emit_or_error(want_stream, model_id, 502, "cursor_agent helper error: %s" % e)
            return
        if want_stream:
            self._stream_anthropic_from_events(events, model_id)
        else:
            self._json_anthropic_from_events(events, model_id)

    def _emit_or_error(self, want_stream, model_id, status, message):
        if want_stream:
            self._stream_anthropic_from_events(
                iter([{"type": "error", "message": message, "status": status}]), model_id)
        else:
            self._send_error(status, message)

    # ---- shared Anthropic emitters --------------------------------------
    def _stream_anthropic_from_events(self, events, model_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.close_connection = True
        self.send_header("Connection", "close")
        self.end_headers()

        msg_id = _new_msg_id()
        self.wfile.write(_sse("message_start", {
            "type": "message_start",
            "message": {"id": msg_id, "type": "message", "role": "assistant",
                        "model": model_id, "content": [],
                        "stop_reason": None, "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0}}}))
        self.wfile.flush()

        index = 0
        text_open = False
        emitted = False
        stop_reason = "end_turn"
        out_tok = 0

        def open_text():
            nonlocal text_open
            self.wfile.write(_sse("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {"type": "text", "text": ""}}))
            text_open = True

        def close_block():
            self.wfile.write(_sse("content_block_stop",
                                  {"type": "content_block_stop", "index": index}))

        try:
            for ev in events:
                et = ev.get("type")
                if et == "text_delta":
                    txt = ev.get("text") or ""
                    if not txt:
                        continue
                    if not text_open:
                        open_text()
                    self.wfile.write(_sse("content_block_delta", {
                        "type": "content_block_delta", "index": index,
                        "delta": {"type": "text_delta", "text": txt}}))
                    self.wfile.flush()
                    emitted = True
                elif et == "tool_call":
                    if text_open:
                        close_block()
                        index += 1
                        text_open = False
                    self.wfile.write(_sse("content_block_start", {
                        "type": "content_block_start", "index": index,
                        "content_block": {"type": "tool_use",
                                          "id": ev.get("id") or ("toolu_" + uuid.uuid4().hex[:16]),
                                          "name": ev.get("name") or "", "input": {}}}))
                    self.wfile.write(_sse("content_block_delta", {
                        "type": "content_block_delta", "index": index,
                        "delta": {"type": "input_json_delta",
                                  "partial_json": ev.get("arguments") or "{}"}}))
                    close_block()
                    index += 1
                    emitted = True
                    stop_reason = "tool_use"
                elif et == "usage":
                    out_tok = ev.get("output_tokens", out_tok) or out_tok
                elif et == "error":
                    if not emitted:
                        if not text_open:
                            open_text()
                        self.wfile.write(_sse("content_block_delta", {
                            "type": "content_block_delta", "index": index,
                            "delta": {"type": "text_delta",
                                      "text": "[ultracode-proxy] " + (ev.get("message") or "upstream error")}}))
                        emitted = True
                    break
            if text_open:
                close_block()
            elif not emitted:
                # Never sent a block; emit an empty text block so Claude Code
                # gets a well-formed turn.
                open_text()
                close_block()
        except Exception as e:
            vlog("anthropic stream relay ended: %s" % e)

        self.wfile.write(_sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": out_tok}}))
        self.wfile.write(_sse("message_stop", {"type": "message_stop"}))
        self.wfile.flush()

    def _json_anthropic_from_events(self, events, model_id: str):
        full_text = ""
        tool_blocks = []
        in_tok = 0
        out_tok = 0
        err = None
        for ev in events:
            et = ev.get("type")
            if et == "text_delta":
                full_text += ev.get("text") or ""
            elif et == "tool_call":
                tool_blocks.append({
                    "type": "tool_use",
                    "id": ev.get("id") or ("toolu_" + uuid.uuid4().hex[:16]),
                    "name": ev.get("name") or "",
                    "input": _parse_tool_input(ev.get("arguments") or "{}"),
                })
            elif et == "usage":
                in_tok = max(in_tok, ev.get("input_tokens", 0) or 0)
                out_tok = max(out_tok, ev.get("output_tokens", 0) or 0)
            elif et == "error" and not full_text and not tool_blocks:
                err = ev
        if err is not None:
            self._send_error(int(err.get("status") or 502), err.get("message") or "upstream error")
            return
        content = []
        if full_text:
            content.append({"type": "text", "text": full_text})
        content.extend(tool_blocks)
        if not content:
            content.append({"type": "text", "text": ""})
        out = {
            "id": _new_msg_id(), "type": "message", "role": "assistant",
            "model": model_id, "content": content,
            "stop_reason": "tool_use" if tool_blocks else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
        }
        self._raw(200, "application/json", json.dumps(out).encode("utf-8"))

    # ---- low-level response helpers -------------------------------------
    def _relay_response(self, resp, streaming: bool):
        status = getattr(resp, "status", None) or resp.getcode()
        self.send_response(status)
        for k, v in resp.headers.items():
            kl = k.lower()
            if kl in _HOP_BY_HOP or kl in ("content-length", "content-encoding"):
                continue
            self.send_header(k, v)
        if streaming:
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.close_connection = True
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception as e:
                vlog("stream relay ended: %s" % e)
        else:
            data = resp.read()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _send_error(self, status: int, message: str):
        body = json.dumps({"type": "error",
                           "error": {"type": "proxy_error", "message": message}}).encode("utf-8")
        self._raw(status, "application/json", body)

    def _raw(self, status: int, ctype: str, payload: bytes):
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            pass


def main():
    global UC_SLOT_MAP, UC_MODELS, LISTEN_PORT, UPSTREAM, MAX_TOKENS_FLOOR
    cfg_path = os.environ.get("UC_CONFIG", "") or _default_config_path()
    try:
        cfg = load_config(cfg_path)
        log("config: %s" % cfg_path)
    except FileNotFoundError:
        cfg = {}
        log("config not found (%s); copy config.example.json to config.json" % cfg_path)
    except Exception as e:
        cfg = {}
        log("config parse failed (%s): %s -- continuing with defaults" % (cfg_path, e))

    proxy_cfg = cfg.get("proxy") if isinstance(cfg.get("proxy"), dict) else {}
    # Precedence: explicit env var > config.json > built-in default.
    if "UC_LISTEN_PORT" not in os.environ and proxy_cfg.get("listen_port"):
        LISTEN_PORT = int(proxy_cfg["listen_port"])
    if "UC_UPSTREAM" not in os.environ and proxy_cfg.get("anthropic_upstream"):
        UPSTREAM = str(proxy_cfg["anthropic_upstream"]).rstrip("/")
    if "UC_MAX_TOKENS" not in os.environ and proxy_cfg.get("max_tokens_floor"):
        MAX_TOKENS_FLOOR = int(proxy_cfg["max_tokens_floor"])

    UC_SLOT_MAP = _routes_to_slots(cfg.get("routes"))
    UC_MODELS = _models_from_config(cfg.get("models"))
    if UC_MODELS:
        log("  advertising %d model(s) on GET /v1/models:" % len(UC_MODELS))
        for m in UC_MODELS:
            log("    %s  (%s)" % (m["id"], m["display_name"]))
    else:
        log("  no models configured (GET /v1/models passes through unchanged)")
    for mid, slot in UC_SLOT_MAP.items():
        log("  route %s -> type=%s model=%s upstream=%s"
            % (mid, slot.get("type", "anthropic"), slot.get("model", mid),
               slot.get("upstream", "(default)")))
    if _codex_oauth is None:
        log("  codex_oauth helper not importable (codex_oauth routes will 501)")
    if _cursor_agent is None:
        log("  cursor_agent helper not importable (cursor_agent routes will 501)")
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    log("ultracode-proxy listening on http://%s:%d -> %s"
        % (LISTEN_HOST, LISTEN_PORT, UPSTREAM))
    log("effort=%s thinking=%s max_tokens_floor=%d inject_reminder=%s"
        % (FORCE_EFFORT, FORCE_THINKING, MAX_TOKENS_FLOOR, INJECT_REMINDER))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
