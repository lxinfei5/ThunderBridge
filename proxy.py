#!/usr/bin/env python3
"""ultracode-unlock proxy -- config-driven Anthropic-API interceptor.

This proxy gives Claude Code's "ultracode" envelope (xhigh effort, adaptive
thinking, high max_tokens, the ultracode system reminder) to ANY model, and
turns Claude Code's native /model menu into a multi-backend switcher.

You configure it with ONE file: config.json (copy config.example.json).
Everything else is derived automatically:

  config.models[]  -> the model ids advertised on GET /v1/models
  config.routes{}  -> per-model-id backend routing (slot map)

Run it with start.ps1 / start.sh (which also points Claude Code at it).
Dependency-light: Python stdlib only (http.server + urllib).
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
# Config loading -- the ONLY thing a user edits is config.json
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))


def _config_path() -> str:
    """Resolve config.json: $UC_CONFIG override, else ./config.json next to me."""
    override = os.environ.get("UC_CONFIG", "").strip()
    if override:
        return override
    return os.path.join(HERE, "config.json")


def _strip_comments(obj):
    """Drop keys starting with '_' (documentation comments) recursively."""
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def load_config(path: str) -> dict:
    """Read + parse config.json, stripping `_`-prefixed comment keys.

    On any failure prints a friendly message and exits non-zero -- a broken
    config should never silently start a misrouted proxy.
    """
    if not os.path.isfile(path):
        sys.stderr.write(
            "ERROR: config not found at %s\n"
            "       Copy config.example.json to config.json and edit it.\n"
            % path)
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        sys.stderr.write("ERROR: could not parse %s as JSON: %s\n" % (path, e))
        sys.exit(2)
    if not isinstance(raw, dict):
        sys.stderr.write("ERROR: %s must be a JSON object.\n" % path)
        sys.exit(2)
    return _strip_comments(raw)


# Populated in main() from config.json.
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8141
UPSTREAM = "https://api.anthropic.com"
MAX_TOKENS_FLOOR = 64000
FORCE_EFFORT = "xhigh"
FORCE_THINKING = True
INJECT_REMINDER = True
VERBOSE = os.environ.get("UC_VERBOSE", "0") == "1"
_LOG_PATH = os.environ.get("UC_LOG", "")

UC_SLOT_MAP = {}   # model_id -> {model, upstream, auth, type}
UC_MODELS = []     # [{type, id, display_name, created_at}] for /v1/models


def derive_runtime(cfg: dict):
    """Translate the user-facing config into the proxy's internal structures.

    Returns (slot_map, models). Validates that every model id starts with
    'claude'/'anthropic' (Claude Code's gateway discovery drops the rest) and
    that each model has a matching route.
    """
    proxy_cfg = cfg.get("proxy") or {}
    global LISTEN_PORT, UPSTREAM, MAX_TOKENS_FLOOR
    LISTEN_PORT = int(proxy_cfg.get("listen_port", LISTEN_PORT))
    UPSTREAM = str(proxy_cfg.get("anthropic_upstream", UPSTREAM)).rstrip("/")
    MAX_TOKENS_FLOOR = int(proxy_cfg.get("max_tokens_floor", MAX_TOKENS_FLOOR))

    models_cfg = cfg.get("models") or []
    routes_cfg = cfg.get("routes") or {}
    slot_map = {}
    models = []
    for m in models_cfg:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        if not (mid.startswith("claude") or mid.startswith("anthropic")):
            sys.stderr.write(
                "WARNING: model id %r does not start with 'claude'/'anthropic'; "
                "Claude Code will hide it. Skipping.\n" % mid)
            continue
        models.append({
            "type": "model",
            "id": mid,
            "display_name": m.get("display_name") or mid,
            "created_at": m.get("created_at") or "2025-01-01T00:00:00Z",
        })
        route = routes_cfg.get(mid)
        if isinstance(route, dict):
            slot = {}
            if route.get("model"):
                slot["model"] = route["model"]
            if route.get("upstream"):
                slot["upstream"] = str(route["upstream"]).rstrip("/")
            if route.get("auth"):
                slot["auth"] = route["auth"]
            if route.get("type"):
                slot["type"] = route["type"]
            slot_map[mid] = slot
        else:
            sys.stderr.write(
                "WARNING: model %r has no entry in 'routes'; it will be passed "
                "to Anthropic unchanged.\n" % mid)
    return slot_map, models


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Request transform -- the ultracode envelope
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
    """Apply the ultracode envelope + slot routing to a /v1/messages body.

    Returns (body_bytes, route). On parse failure returns the original bytes and
    an empty route so a request is never broken.
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
# Anthropic <-> OpenAI translation (for type: openai_compat routes)
# --------------------------------------------------------------------------

def _text_from_anthropic_content(content):
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
            elif btype == "tool_use":
                parts.append("[tool_use %s args=%s]"
                             % (block.get("name", "?"),
                                json.dumps(block.get("input", {}))[:2000]))
            elif btype == "tool_result":
                parts.append("[tool_result] "
                             + _text_from_anthropic_content(block.get("content")))
            elif btype == "image":
                parts.append("[image omitted]")
    return "\n".join(p for p in parts if p)


def anthropic_to_openai(body: dict) -> dict:
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
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role,
                         "content": _text_from_anthropic_content(m.get("content", ""))})
    out = {"model": body.get("model"), "messages": messages,
           "stream": bool(body.get("stream", False))}
    mt = body.get("max_tokens")
    if isinstance(mt, int) and mt > 0:
        out["max_tokens"] = mt
    temp = body.get("temperature")
    if isinstance(temp, (int, float)):
        out["temperature"] = temp
    return out


def _new_msg_id() -> str:
    return "msg_" + uuid.uuid4().hex[:24]


def openai_json_to_anthropic(oai: dict, model_id: str) -> dict:
    text, finish, in_tok, out_tok = "", "end_turn", 0, 0
    try:
        choice = (oai.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        fr = choice.get("finish_reason")
        finish = "max_tokens" if fr == "length" else "end_turn"
        usage = oai.get("usage") or {}
        in_tok = usage.get("prompt_tokens", 0) or 0
        out_tok = usage.get("completion_tokens", 0) or 0
    except Exception:
        pass
    return {
        "id": oai.get("id") or _new_msg_id(),
        "type": "message", "role": "assistant", "model": model_id,
        "content": [{"type": "text", "text": text}],
        "stop_reason": finish, "stop_sequence": None,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }


def _sse(event: str, data: dict) -> bytes:
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data))).encode("utf-8")


def openai_stream_to_anthropic(resp, wfile, model_id: str):
    msg_id = _new_msg_id()
    wfile.write(_sse("message_start", {
        "type": "message_start",
        "message": {"id": msg_id, "type": "message", "role": "assistant",
                    "model": model_id, "content": [], "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0}}}))
    wfile.write(_sse("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""}}))
    wfile.flush()
    finish, out_tok, buf = "end_turn", 0, b""
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
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    buf = b""
                    break
                try:
                    obj = json.loads(payload.decode("utf-8"))
                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        out_tok += 1
                        wfile.write(_sse("content_block_delta", {
                            "type": "content_block_delta", "index": 0,
                            "delta": {"type": "text_delta", "text": piece}}))
                        wfile.flush()
                    fr = choice.get("finish_reason")
                    if fr == "length":
                        finish = "max_tokens"
                    elif fr == "stop":
                        finish = "end_turn"
                except Exception:
                    continue
    except Exception as e:
        vlog("openai stream relay ended: %s" % e)
    wfile.write(_sse("content_block_stop", {"type": "content_block_stop", "index": 0}))
    wfile.write(_sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": finish, "stop_sequence": None},
        "usage": {"output_tokens": out_tok}}))
    wfile.write(_sse("message_stop", {"type": "message_stop"}))
    wfile.flush()
    return out_tok


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
    server_version = "ultracode-unlock/1.0"

    def log_message(self, fmt, *args):
        if VERBOSE:
            log("http " + (fmt % args))

    def _maybe_health(self) -> bool:
        if self.path in ("/healthz", "/health"):
            payload = json.dumps({
                "ok": True, "upstream": UPSTREAM, "effort": FORCE_EFFORT,
                "max_tokens_floor": MAX_TOKENS_FLOOR,
                "inject_reminder": INJECT_REMINDER,
                "custom_models": [{"id": m["id"], "display_name": m["display_name"]}
                                  for m in UC_MODELS],
                "slot_map": {k: {"model": v.get("model"),
                                 "upstream": v.get("upstream", "(default)"),
                                 "type": v.get("type", "anthropic"),
                                 "auth": v.get("auth", "passthrough")}
                             for k, v in UC_SLOT_MAP.items()},
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
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

    def _handle_models(self) -> bool:
        """Serve GET /v1/models, appending custom models to the upstream list."""
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
        payload = json.dumps(base).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        return True

    def _read_request_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        try:
            n = int(length)
        except ValueError:
            return b""
        return self.rfile.read(n) if n > 0 else b""

    def _proxy(self, method: str):
        body = self._read_request_body()
        is_messages = self.path.split("?")[0].endswith("/v1/messages")
        route = {}
        if is_messages and method == "POST" and body:
            body, route = transform_messages_body(body)

        if is_messages and method == "POST" and route.get("type") == "openai_compat":
            self._proxy_openai_compat(body, route)
            return

        upstream = route.get("upstream") or UPSTREAM
        url = upstream + self.path
        fwd_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _HOP_BY_HOP}
        auth_override = route.get("auth")
        if auth_override:
            if ":" in auth_override and not auth_override.lower().startswith("bearer"):
                hk, hv = auth_override.split(":", 1)
                fwd_headers[hk.strip()] = hv.strip()
            else:
                fwd_headers["Authorization"] = auth_override
        fwd_headers["Accept-Encoding"] = "identity"
        if body:
            fwd_headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(url, data=body if body else None,
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

    def _proxy_openai_compat(self, body: bytes, route: dict):
        try:
            anth = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_error(400, "openai_compat: bad request body: %s" % e)
            return
        model_id = anth.get("model")
        want_stream = bool(anth.get("stream", False))
        payload = json.dumps(anthropic_to_openai(anth)).encode("utf-8")
        upstream = (route.get("upstream") or UPSTREAM).rstrip("/")
        url = upstream + "/v1/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Accept": "text/event-stream" if want_stream else "application/json",
                   "Content-Length": str(len(payload))}
        auth_override = route.get("auth")
        if auth_override and auth_override != "passthrough":
            if ":" in auth_override and not auth_override.lower().startswith("bearer"):
                hk, hv = auth_override.split(":", 1)
                headers[hk.strip()] = hv.strip()
            else:
                headers["Authorization"] = auth_override
        else:
            headers["Authorization"] = "Bearer unused"
        vlog("openai_compat -> %s model=%s stream=%s" % (url, model_id, want_stream))
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            err_body = b""
            try:
                err_body = e.read()
            except Exception:
                pass
            log("openai_compat upstream HTTP %s for %s: %s" % (e.code, url, err_body[:500]))
            self._send_error(502, "openai_compat upstream %s: %s"
                             % (e.code, err_body.decode("utf-8", "replace")[:800]))
            return
        except Exception as e:
            log("openai_compat upstream error %s for %s" % (e, url))
            self._send_error(502, "openai_compat upstream error: %s" % e)
            return
        upstream_stream = "text/event-stream" in resp.headers.get("Content-Type", "")
        if want_stream:
            # End-of-turn correctness: an SSE turn is only "done" for Claude Code
            # when it sees message_stop AND the connection finishes. Under HTTP/1.1
            # keep-alive the socket would stay open, so Claude Code keeps showing
            # the thinking spinner and routes the next message into its queue
            # instead of reading it. We close the connection after the final
            # event so the client cleanly ends the turn.
            #
            # IMPORTANT ordering: the HTTP status line MUST be written first
            # (send_response), THEN headers (including Connection: close), THEN
            # end_headers(). Emitting the Connection header or flushing the
            # socket before send_response produces a malformed response that
            # Claude Code cannot parse, which triggers its retry loop (1..10).
            self.send_response(200)
            self.close_connection = True
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            if upstream_stream:
                openai_stream_to_anthropic(resp, self.wfile, model_id)
            else:
                try:
                    oai = json.loads(resp.read().decode("utf-8"))
                    text = ((oai.get("choices") or [{}])[0]
                            .get("message", {}) or {}).get("content", "")
                except Exception:
                    text = ""
                self._fake_anthropic_stream(model_id, text)
            return
        try:
            oai = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._send_error(502, "openai_compat: bad upstream JSON: %s" % e)
            return
        out = json.dumps(openai_json_to_anthropic(oai, model_id)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _fake_anthropic_stream(self, model_id: str, text: str):
        msg_id = _new_msg_id()
        self.wfile.write(_sse("message_start", {
            "type": "message_start",
            "message": {"id": msg_id, "type": "message", "role": "assistant",
                        "model": model_id, "content": [], "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0}}}))
        self.wfile.write(_sse("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""}}))
        if text:
            self.wfile.write(_sse("content_block_delta", {
                "type": "content_block_delta", "index": 0,
                "delta": {"type": "text_delta", "text": text}}))
        self.wfile.write(_sse("content_block_stop", {"type": "content_block_stop", "index": 0}))
        self.wfile.write(_sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0}}))
        self.wfile.write(_sse("message_stop", {"type": "message_stop"}))
        self.wfile.flush()

    def _send_error(self, status: int, message: str):
        msg = json.dumps({"type": "error",
                          "error": {"type": "proxy_error", "message": message}}).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        except Exception:
            pass

    def _relay_response(self, resp, streaming: bool):
        status = getattr(resp, "status", None) or resp.getcode()
        self.send_response(status)
        for k, v in resp.headers.items():
            kl = k.lower()
            if kl in _HOP_BY_HOP or kl in ("content-length", "content-encoding"):
                continue
            self.send_header(k, v)
        if streaming:
            # See _proxy_openai_compat: close the socket after the stream so the
            # client (Claude Code) cleanly ends the turn and stops spinning.
            # Headers are emitted AFTER send_response(status) above, so writing
            # the Connection: close header here is correctly ordered (status
            # line first). Do NOT flush before end_headers() — that would emit a
            # malformed response that Claude Code retries 1..10.
            self.close_connection = True
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
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


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------

def main():
    global UC_SLOT_MAP, UC_MODELS
    cfg = load_config(_config_path())
    UC_SLOT_MAP, UC_MODELS = derive_runtime(cfg)

    if UC_MODELS:
        log("advertising %d custom model(s) on GET /v1/models:" % len(UC_MODELS))
        for m in UC_MODELS:
            log("  %s  (%s)" % (m["id"], m["display_name"]))
    else:
        log("no models configured (GET /v1/models passes through unchanged)")
    for mid, slot in UC_SLOT_MAP.items():
        log("  route %s -> type=%s model=%s upstream=%s auth=%s"
            % (mid, slot.get("type", "anthropic"), slot.get("model", mid),
               slot.get("upstream", "(default)"),
               "override" if slot.get("auth") else "passthrough"))

    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    log("ultracode-unlock listening on http://%s:%d -> %s"
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
