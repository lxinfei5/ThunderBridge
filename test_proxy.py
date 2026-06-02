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
    SEEN_BY_MODEL = {}  # backend model id -> last request body (Auto Router checks)

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
            Mock.SEEN_BY_MODEL[body.get("model")] = body

            # Auto Router classifier: respond with plain JSON scores (the proxy's
            # classifier path is non-streaming). A "refactor"-ish task scores the
            # cheap model low so routing escalates to the strong candidate.
            if body.get("model") == "router-classifier":
                # Inspect ONLY the user turn (the task), not the system prompt -
                # the candidate cards themselves mention "refactor".
                user_msg = " ".join(m.get("content", "") for m in body.get("messages", [])
                                    if m.get("role") == "user" and isinstance(m.get("content"), str))
                hard = "refactor" in user_msg.lower()
                scores = {"claude-cheap": 0.4 if hard else 0.9,
                          "claude-strong": 0.92}
                self._j(200, {"choices": [{"message": {
                    "content": json.dumps({"scores": scores, "reasoning": "test"})}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
                return

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
                   {"id": "claude-retry", "display_name": "Retry Model"},
                   {"id": "claude-auto", "display_name": "Auto"},
                   {"id": "claude-cheap", "display_name": "Cheap"},
                   {"id": "claude-strong", "display_name": "Strong"}],
        "routes": {
            "claude-opus-4-8": {"model": "claude-opus-4-8", "upstream": mock, "auth": "passthrough"},
            "claude-mock": {"type": "openai_compat", "model": "mock-model",
                            "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}",
                            "max_output_tokens": 1234,
                            "headers": {"X-Test-UA": "openclaw/test"},
                            "body": {"reasoning_split": True}},
            "claude-retry": {"type": "openai_compat", "model": "retry-model",
                             "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}"},
            # Auto Router: a synthetic 'auto' picker, two real candidates, and a
            # cheap classifier - all pointed at the mock backend.
            "claude-auto": {"type": "auto"},
            "claude-cheap": {"type": "openai_compat", "model": "cheap-real",
                             "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}"},
            "claude-strong": {"type": "openai_compat", "model": "strong-real",
                              "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}"},
            "claude-classifier": {"type": "openai_compat", "model": "router-classifier",
                                  "upstream": mock + "/v1", "auth": "Bearer ${MOCK_KEY}"},
        },
        "router": {
            "enabled": True, "id": "claude-auto", "classifier": "claude-classifier",
            "threshold": 0.7, "default": "claude-cheap", "cache": True,
            "candidates": [
                {"id": "claude-cheap", "cost": 0.3, "supports_images": False,
                 "card": "cheap fast single-file tasks"},
                {"id": "claude-strong", "cost": 5.0, "supports_images": True,
                 "card": "frontier multi-file refactors and debugging"},
            ],
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
        assert "claude-auto" in ids, ids  # Auto Router picker is discoverable
        print("[ok] /v1/models discovery merge:", ids)

        h2 = json.loads(_get("/healthz"))
        assert h2["router"]["enabled"] and h2["router"]["id"] == "claude-auto", h2["router"]
        assert {c["id"] for c in h2["router"]["candidates"]} == {"claude-cheap", "claude-strong"}, h2["router"]
        print("[ok] healthz reports Auto Router config")

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

        # Auto Router (end-to-end through the running proxy): picking claude-auto
        # consults the classifier, then routes the REAL request to the cheapest
        # candidate that clears the bar. A trivial task -> cheap; a hard refactor
        # -> the strong candidate. We verify which backend model actually got hit.
        Mock.SEEN_BY_MODEL.clear()
        _post("/v1/messages", {"model": "claude-auto", "max_tokens": 50,
                               "messages": [{"role": "user", "content": "say ok"}]})
        assert "router-classifier" in Mock.SEEN_BY_MODEL, list(Mock.SEEN_BY_MODEL)
        assert "cheap-real" in Mock.SEEN_BY_MODEL, list(Mock.SEEN_BY_MODEL)
        assert "strong-real" not in Mock.SEEN_BY_MODEL, list(Mock.SEEN_BY_MODEL)
        print("[ok] auto router: trivial task -> cheapest viable candidate (claude-cheap)")

        Mock.SEEN_BY_MODEL.clear()
        _post("/v1/messages", {"model": "claude-auto", "max_tokens": 50,
                               "messages": [{"role": "user",
                                             "content": "do a huge multi-file refactor across the whole codebase"}]})
        assert "strong-real" in Mock.SEEN_BY_MODEL, list(Mock.SEEN_BY_MODEL)
        assert "cheap-real" not in Mock.SEEN_BY_MODEL, list(Mock.SEEN_BY_MODEL)
        print("[ok] auto router: hard task escalates to the strong candidate (claude-strong)")

        sys.path.insert(0, GW)
        import proxy as up
        os.environ["MOCK_KEY"] = "secret123"
        assert up._expand_env("Bearer ${MOCK_KEY}") == "Bearer secret123"
        print("[ok] ${ENV} expansion in route auth")

        # Auto Router unit logic (in-process): cheapest-among-viable selection,
        # the image hard-zero, the below-bar best-effort pick, score parsing
        # (clamp + extraction from prose), and the user-task signal extraction.
        rc = [{"id": "a", "cost": 0.3, "supports_images": False},
              {"id": "b", "cost": 5.0, "supports_images": True}]
        assert up._router_pick({"a": 0.9, "b": 0.95}, rc, 0.7, False)[0] == "a"   # cheapest >= bar
        assert up._router_pick({"a": 0.9, "b": 0.95}, rc, 0.7, True)[0] == "b"    # images -> 'a' hard-zeroed
        assert up._router_pick({"a": 0.4, "b": 0.5}, rc, 0.7, False)[0] == "b"    # none clear bar -> best
        assert up._parse_scores('noise {"scores":{"a":1.7,"b":-2},"reasoning":"x"} tail',
                                ["a", "b"]) == {"a": 1.0, "b": 0.0}               # clamp + extract
        # latest non-tool user turn is the task; pure tool_result turns are skipped
        assert up._last_user_text({"messages": [
            {"role": "user", "content": "real ask"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]},
        ]}) == "real ask"
        assert up._has_images({"messages": [
            {"role": "user", "content": [{"type": "image", "source": {}}]}]}) is True
        print("[ok] auto router unit: selection / image-reject / score-parse / signal")

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

        # Image forwarding: a user image block must survive translation as a real
        # image part (not a "[image omitted]" stub) so supports_images:true
        # backends actually receive the picture -- for openai_compat (chat
        # image_url) AND codex (Responses input_image). Text-only stays a string.
        _img = {"type": "image", "source": {"type": "base64",
                "media_type": "image/png", "data": "QUJD"}}
        _oai = up.anthropic_to_openai({"model": "m", "messages": [
            {"role": "user", "content": [_img, {"type": "text", "text": "what is this?"}]}]})["messages"]
        _u = [x for x in _oai if x["role"] == "user"][-1]
        assert isinstance(_u["content"], list), _u
        _ip = [p for p in _u["content"] if p.get("type") == "image_url"]
        assert _ip and _ip[0]["image_url"]["url"] == "data:image/png;base64,QUJD", _u
        assert any(p.get("type") == "text" and "what is this" in p.get("text", "") for p in _u["content"]), _u
        _plain = up.anthropic_to_openai({"model": "m", "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}]})["messages"]
        assert [x for x in _plain if x["role"] == "user"][-1]["content"] == "hi"  # text-only fast path unchanged
        if up._codex_oauth is not None:
            _instr, _items = up._codex_oauth._messages_to_responses_input(_oai)
            _cp = [c for it in _items for c in (it.get("content") or [])]
            assert any(c.get("type") == "input_image" and c.get("image_url") == "data:image/png;base64,QUJD"
                       for c in _cp), _items
            assert any(c.get("type") == "input_text" and "what is this" in c.get("text", "")
                       for c in _cp), _items
        print("[ok] image forwarding: user image -> openai_compat image_url + codex input_image")

        # Orchestrator + Worker: the picker should advertise a "Worker -> X" entry
        # per model, a plain pick should drive BOTH tiers (capturing the dynamic
        # workflow's stock-model background traffic), and a worker pick should set
        # only the worker tier. Tier is classified by interactive-only tools.
        up.UC_MODELS = [
            {"type": "model", "id": "claude-mock", "display_name": "Mock"},
            {"type": "model", "id": "claude-mimo", "display_name": "MiMo"},
        ]
        up.UC_SLOT_MAP = {
            "claude-mock": {"type": "openai_compat", "model": "mock-model"},
            "claude-mimo": {"type": "openai_compat", "model": "mimo-v2.5-pro"},
        }
        up.ORCH_WORKER = True
        up._ORCH_PICK_IDS.clear(); up._WORKER_MAP.clear()
        up._ACTIVE.update({"orch": None, "worker": None, "worker_explicit": False})
        up._wire_orchestrator_worker()
        ow_ids = [x["id"] for x in up.UC_MODELS]
        assert "claude-worker-mock" in ow_ids and "claude-worker-mimo" in ow_ids, ow_ids
        assert up.UC_SLOT_MAP["claude-worker-mock"]["model"] == "mock-model"  # inherits base route

        def _reset_sel():
            up._ACTIVE.update({"orch": None, "worker": None, "worker_explicit": False})

        assert up._request_tier({"tools": [{"name": "AskUserQuestion"}]}) == "heavy"
        assert up._request_tier({"tools": [{"name": "Bash"}]}) == "fast"

        _reset_sel()  # fresh session: stock model untouched until a pick happens
        assert up._select_target("claude-opus-4-8", "heavy") == "claude-opus-4-8"

        _reset_sel()  # plain pick -> BOTH tiers, captures stock background traffic
        up._select_target("claude-mock", "heavy")
        assert up._select_target("claude-opus-4-8", "heavy") == "claude-mock"
        assert up._select_target("claude-opus-4-8", "fast") == "claude-mock"

        _reset_sel()  # orchestrator mock + worker mimo
        up._select_target("claude-mock", "heavy")
        up._select_target("claude-worker-mimo", "fast")
        assert up._select_target("claude-opus-4-8", "heavy") == "claude-mock"
        assert up._select_target("claude-opus-4-8", "fast") == "claude-mimo"
        print("[ok] orchestrator+worker: picker entries, tier routing, stock-traffic capture")

        # /uc/select: the two-column pre-launch selector pre-sets both tiers
        # without needing a /model pick. _set_selection drives the same routing.
        _reset_sel()
        active = up._set_selection(orch="claude-minimax", worker=None)
        assert active["orch"] == "claude-minimax" and active["worker"] == "claude-minimax"
        _reset_sel()
        active = up._set_selection(orch="claude-mock", worker="claude-mimo")
        assert active["orch"] == "claude-mock" and active["worker"] == "claude-mimo"
        assert up._select_target("claude-opus-4-8", "heavy") == "claude-mock"
        assert up._select_target("claude-opus-4-8", "fast") == "claude-mimo"
        # live endpoint round-trip through the running proxy
        sel = json.loads(_get("/uc/select"))
        assert sel["ok"] and "orchestrators" in sel and "workers" in sel, sel
        r = _post("/uc/select", {"orchestrator": "claude-mock", "worker": "claude-mock"})
        assert json.loads(r)["active"]["orch"] == "claude-mock", r
        print("[ok] /uc/select endpoint: GET lists models, POST pre-sets tiers")

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
