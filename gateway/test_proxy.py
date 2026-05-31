#!/usr/bin/env python3
"""Self-contained end-to-end test for ultracode_proxy.py.

Runs entirely offline against a mock backend (no real API keys, no network).
Proves: /v1/models discovery merge, the UltraCode envelope on passthrough,
OpenAI<->Anthropic tool-call translation, and ${ENV} expansion in slots.

    python3 gateway/test_proxy.py        # exits 0 on success

Used by scripts/doctor.py and by CI.
"""
import json, os, sys, threading, time, urllib.request, subprocess, signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GW = os.path.dirname(os.path.abspath(__file__))
MOCK_PORT = int(os.environ.get("UC_TEST_MOCK_PORT", "8788"))
PROXY_PORT = int(os.environ.get("UC_TEST_PROXY_PORT", "8141"))
SEEN_OAI = None
SEEN_OAI_HEADERS = None
SEEN_ANTH = None


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _j(self, status, obj):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/v1/models"):
            self._j(200, {"data": [{"type": "model", "id": "claude-opus-4-8",
                                    "display_name": "Opus"}]})
        else:
            self._j(404, {"e": "nope"})

    def do_POST(self):
        global SEEN_OAI, SEEN_OAI_HEADERS, SEEN_ANTH
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) if n else b"{}")
        path = self.path.split("?")[0]
        if path.endswith("/v1/chat/completions"):
            SEEN_OAI = body
            SEEN_OAI_HEADERS = {k: v for k, v in self.headers.items()}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def sse(o):
                self.wfile.write(("data: " + json.dumps(o) + "\n\n").encode())
                self.wfile.flush()
            sse({"choices": [{"delta": {"content": "Hello "}}]})
            sse({"choices": [{"delta": {"content": "world"}}]})
            sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
                "function": {"name": "get_weather", "arguments": "{\"city\":"}}]}}]})
            sse({"choices": [{"delta": {"tool_calls": [{"index": 0,
                "function": {"arguments": "\"Paris\"}"}}]}}]})
            sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 11, "completion_tokens": 7}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        elif path.endswith("/v1/messages"):
            SEEN_ANTH = body
            self._j(200, {"id": "msg_x", "type": "message", "role": "assistant",
                          "model": body.get("model"),
                          "content": [{"type": "text", "text": "ok"}],
                          "stop_reason": "end_turn",
                          "usage": {"input_tokens": 1, "output_tokens": 1}})
        else:
            self._j(404, {"e": "nope"})


def _post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PROXY_PORT, path),
                                 data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer sk-ant-dummy"})
    return urllib.request.urlopen(req, timeout=10).read().decode()


def _get(path):
    return urllib.request.urlopen("http://127.0.0.1:%d%s" % (PROXY_PORT, path),
                                  timeout=10).read().decode()


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mock = "http://127.0.0.1:%d" % MOCK_PORT

    slots = {
        "claude-opus-4-8": {"model": "claude-opus-4-8", "upstream": mock, "auth": "passthrough"},
        "claude-mock": {"type": "openai_compat", "model": "mock-model",
                        "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}",
                        "max_output_tokens": 1234,
                        "headers": {"X-Test-UA": "openclaw/test"}},
    }
    models = {"models": [{"id": "claude-mock", "display_name": "Mock Model"}]}
    slots_f = os.path.join(GW, "_test_slots.json")
    models_f = os.path.join(GW, "_test_models.json")
    open(slots_f, "w").write(json.dumps(slots))
    open(models_f, "w").write(json.dumps(models))

    env = dict(os.environ, UC_LISTEN_PORT=str(PROXY_PORT), UC_UPSTREAM=mock,
               UC_SLOT_MAP=slots_f, UC_MODELS_FILE=models_f, MOCK_KEY="secret123")
    p = subprocess.Popen([sys.executable, os.path.join(GW, "ultracode_proxy.py")],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                _get("/healthz")
                break
            except Exception:
                time.sleep(0.1)
        h = json.loads(_get("/healthz"))
        assert h["ok"] and h["codex_helper"], h
        print("[ok] healthz + codex helper importable")

        ids = [x["id"] for x in json.loads(_get("/v1/models"))["data"]]
        assert "claude-mock" in ids and "claude-opus-4-8" in ids, ids
        print("[ok] /v1/models discovery merge:", ids)

        _post("/v1/messages", {"model": "claude-opus-4-8", "max_tokens": 100,
                               "messages": [{"role": "user", "content": "hi"}]})
        assert SEEN_ANTH["output_config"]["effort"] == "xhigh"
        assert SEEN_ANTH["thinking"]["type"] == "adaptive"
        assert SEEN_ANTH["max_tokens"] >= 64000
        sysv = SEEN_ANTH["system"]
        has_reminder = ("Ultracode is on:" in sysv) if isinstance(sysv, str) else \
            any("Ultracode is on:" in (b.get("text", "")) for b in sysv)
        assert has_reminder
        print("[ok] UltraCode envelope on passthrough (xhigh/adaptive/64k/reminder)")

        out = _post("/v1/messages", {"model": "claude-mock", "max_tokens": 50, "stream": True,
            "tools": [{"name": "get_weather", "description": "w",
                       "input_schema": {"type": "object",
                                        "properties": {"city": {"type": "string"}}}}],
            "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": "weather in paris?"}]})
        assert SEEN_OAI["tools"][0]["function"]["name"] == "get_weather", SEEN_OAI
        assert SEEN_OAI.get("tool_choice") == "auto"
        assert SEEN_OAI.get("max_tokens") == 1234, SEEN_OAI.get("max_tokens")  # slot cap honored
        hdr = {k.lower(): v for k, v in (SEEN_OAI_HEADERS or {}).items()}
        assert hdr.get("x-test-ua") == "openclaw/test", SEEN_OAI_HEADERS  # custom headers
        assert hdr.get("authorization") == "Bearer secret123", SEEN_OAI_HEADERS  # ${ENV} auth reached backend
        assert '"type": "tool_use"' in out and '"name": "get_weather"' in out
        assert "input_json_delta" in out and "Paris" in out
        assert '"stop_reason": "tool_use"' in out
        assert "Hello " in out and "world" in out
        print("[ok] openai_compat streaming tool-call -> Anthropic tool_use")

        sys.path.insert(0, GW)
        import ultracode_proxy as up
        os.environ["MOCK_KEY"] = "secret123"
        assert up._expand_env("Bearer ${MOCK_KEY}") == "Bearer secret123"
        print("[ok] ${ENV} expansion in slot auth")
        print("\nALL TESTS PASSED")
        return 0
    finally:
        p.send_signal(signal.SIGTERM)
        srv.shutdown()
        for f in (slots_f, models_f):
            try:
                os.remove(f)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
