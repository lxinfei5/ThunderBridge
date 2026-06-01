#!/usr/bin/env python3
"""Self-contained end-to-end test for proxy.py.

Runs entirely offline against a mock backend (no real API keys, no network).
Proves: /v1/models discovery merge, the UltraCode envelope on passthrough,
OpenAI<->Anthropic tool-call translation, and ${ENV} expansion in routes.

    python3 test_proxy.py        # exits 0 on success

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
    RETRY_HITS = 0  # counts hits for the "retry-model" empty-then-recover case

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

            if body.get("model") == "retry-model":
                # First attempt returns an empty turn (no text/tool) -> the proxy
                # must retry; the second attempt recovers with real content.
                Mock.RETRY_HITS += 1
                if Mock.RETRY_HITS == 1:
                    sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 5, "completion_tokens": 0}})
                else:
                    sse({"choices": [{"delta": {"content": "recovered"}}]})
                    sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return
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

    config = {
        "proxy": {"listen_port": PROXY_PORT, "anthropic_upstream": mock, "max_tokens_floor": 64000},
        "models": [{"id": "claude-mock", "display_name": "Mock Model"},
                   {"id": "claude-retry", "display_name": "Retry Model"}],
        "routes": {
            "claude-opus-4-8": {"model": "claude-opus-4-8", "upstream": mock, "auth": "passthrough"},
            "claude-mock": {"type": "openai_compat", "model": "mock-model",
                            "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}",
                            "max_output_tokens": 1234,
                            "headers": {"X-Test-UA": "openclaw/test"},
                            "body": {"reasoning_split": True}},
            "claude-retry": {"type": "openai_compat", "model": "retry-model",
                             "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}"},
        },
    }
    cfg_f = os.path.join(GW, "_test_config.json")
    open(cfg_f, "w").write(json.dumps(config))

    env = dict(os.environ, UC_CONFIG=cfg_f, MOCK_KEY="secret123", UC_EMPTY_RETRY_BACKOFF="0")
    p = subprocess.Popen([sys.executable, os.path.join(GW, "proxy.py")],
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
        assert SEEN_OAI.get("reasoning_split") is True, SEEN_OAI  # route 'body' param merged (M3 needs this)
        hdr = {k.lower(): v for k, v in (SEEN_OAI_HEADERS or {}).items()}
        assert hdr.get("x-test-ua") == "openclaw/test", SEEN_OAI_HEADERS  # custom headers
        assert hdr.get("authorization") == "Bearer secret123", SEEN_OAI_HEADERS  # ${ENV} auth reached backend
        assert '"type": "tool_use"' in out and '"name": "get_weather"' in out
        assert "input_json_delta" in out and "Paris" in out
        assert '"stop_reason": "tool_use"' in out
        assert "Hello " in out and "world" in out
        print("[ok] openai_compat streaming tool-call -> Anthropic tool_use")

        out = _post("/v1/messages", {"model": "claude-retry", "max_tokens": 50,
            "messages": [{"role": "user", "content": "hi"}]})
        assert Mock.RETRY_HITS == 2, "expected 1 empty turn + 1 retry, got %d hits" % Mock.RETRY_HITS
        assert "recovered" in out, out
        print("[ok] empty turn auto-retried -> recovered (upstream hit %dx)" % Mock.RETRY_HITS)

        sys.path.insert(0, GW)
        import proxy as up
        os.environ["MOCK_KEY"] = "secret123"
        assert up._expand_env("Bearer ${MOCK_KEY}") == "Bearer secret123"
        print("[ok] ${ENV} expansion in route auth")

        # issue #3: a rejected tool call (with or without a comment) must not leave
        # an assistant tool_calls message unanswered, and tool replies must come
        # BEFORE the user's text — otherwise strict backends (DeepSeek) 400 with
        # "insufficient tool messages following tool_calls message".
        def _assert_tool_adjacency(msgs):
            for i, mm in enumerate(msgs):
                if mm.get("tool_calls"):
                    need = [t["id"] for t in mm["tool_calls"]]
                    got = []
                    j = i + 1
                    while j < len(msgs) and msgs[j].get("role") == "tool":
                        got.append(msgs[j]["tool_call_id"]); j += 1
                    assert got == need, ("tool_calls %s not immediately answered by %s"
                                         % (need, got), msgs)

        def _assistant_calls(*ids):
            return {"role": "assistant",
                    "content": [{"type": "text", "text": "ok"}]
                    + [{"type": "tool_use", "id": i, "name": "t", "input": {}} for i in ids]}

        # (a) rejected with a comment + a tool_result present
        m = up.anthropic_to_openai({"model": "m", "messages": [
            {"role": "user", "content": "go"},
            _assistant_calls("call_1"),
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "rejected"},
                {"type": "text", "text": "no, do it differently"}]}]})["messages"]
        _assert_tool_adjacency(m)
        assert m[-1] == {"role": "user", "content": "no, do it differently"}, m  # comment AFTER tool

        # (b) rejected with NO tool_result, only a user comment -> stub synthesized
        m = up.anthropic_to_openai({"model": "m", "messages": [
            {"role": "user", "content": "go"},
            _assistant_calls("call_1"),
            {"role": "user", "content": [{"type": "text", "text": "nah"}]}]})["messages"]
        _assert_tool_adjacency(m)
        assert any(x.get("role") == "tool" and x["tool_call_id"] == "call_1" for x in m), m

        # (c) parallel calls, only one answered -> the other gets a stub
        m = up.anthropic_to_openai({"model": "m", "messages": [
            {"role": "user", "content": "go"},
            _assistant_calls("call_1", "call_2"),
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "done"}]}]})["messages"]
        _assert_tool_adjacency(m)
        tool_ids = [x["tool_call_id"] for x in m if x.get("role") == "tool"]
        assert tool_ids == ["call_1", "call_2"], tool_ids
        print("[ok] rejected/partial tool calls stay valid for strict backends (issue #3)")

        print("\nALL TESTS PASSED")
        return 0
    finally:
        p.send_signal(signal.SIGTERM)
        srv.shutdown()
        try:
            os.remove(cfg_f)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
