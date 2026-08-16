"""F5 coverage expansion: bring cli.py / context.py / serve.py up to parity.

Targets the specific uncovered blocks reported by `coverage report`:
  * cli.py   : cmd_gate (156-174), cmd_bench public branch (181-190),
               cmd_automations full dispatch (200-271)
  * context.py: Anthropic-style block extraction (37-45), non-str content
                (46->32), dedup branches (84->83, 88-89, 91->90), empty warm
                skip (94->exit), empty snapshot branches (100->104, 105->109),
                persist-no-path (113), load edge cases (120, 123-124, 125->exit)
  * serve.py : GET /bench, /gate, /sessions/<id>, POST /sessions/fork,
               /sessions/compress (76, 81, 85-93, 125, 127, 167-192)

Honesty: serve handler routes are exercised over a *real* localhost
ThreadingHTTPServer; the sessions backend is monkeypatched with canned data
because that backend is covered independently in test_sessions.py.
"""
from __future__ import annotations

import json
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import baize.serve as serve_mod
from baize import context
from baize.cli import cmd_automations, cmd_bench, cmd_gate
from baize.serve import ThreadingHTTPServer

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# cli.py : cmd_gate / cmd_bench(public) / cmd_automations
# ---------------------------------------------------------------------------

def test_cli_gate(tmp_path, capsys, monkeypatch):
    manifest = REPO / "baize.manifest.json"
    args = types.SimpleNamespace(
        manifest=str(manifest), coverage_data=str(tmp_path / "nope.coverage"))
    rc = cmd_gate(args)
    out = capsys.readouterr().out
    assert "NO FAKE DONE GATE" in out
    assert "manifest" in out
    assert "coverage" in out
    assert "overall" in out
    assert rc in (0, 1, 2)


def test_cli_bench_public(capsys, monkeypatch):
    args = types.SimpleNamespace(public=True)
    rc = cmd_bench(args)
    out = capsys.readouterr().out
    assert "公开基准" in out
    assert rc == 0


class _FakeSpec:
    def __init__(self, id, name, status="ACTIVE", schedule_type="once",
                 rrule="", scheduled_at="", cwds=""):
        self.id = id
        self.name = name
        self.status = status
        self.schedule_type = schedule_type
        self.rrule = rrule
        self.scheduled_at = scheduled_at
        self.cwds = cwds


class _FakeStore:
    def __init__(self):
        self.specs = {}

    def list(self):
        return list(self.specs.values())

    def save(self, spec):
        self.specs[spec.id] = spec

    def get(self, id):
        return self.specs.get(id)

    def delete(self, id):
        self.specs.pop(id, None)


_SHARED_STORE = _FakeStore()


class _FakeScheduler:
    def __init__(self):
        # share one store across instances so add/list/remove see the same data
        self.store = _SHARED_STORE

    def _next_fire(self, s, now):
        return now + 10

    def runner(self, spec):
        return {"ok": True, "id": spec.id}


def _auto_args(**kw):
    base = dict(action="list", id=None, name=None, prompt=None,
                schedule_type="once", rrule="", scheduled_at="", cwds="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_cli_automations_dispatch(capsys, monkeypatch):
    monkeypatch.setattr("baize.automations.AutomationScheduler", _FakeScheduler)

    # list (empty)
    assert cmd_automations(_auto_args(action="list")) == 0
    capsys.readouterr()

    # add
    assert cmd_automations(_auto_args(
        action="add", id="a1", name="t", prompt="p",
        schedule_type="recurring", rrule="FREQ=DAILY")) == 0
    out = capsys.readouterr().out
    assert "added a1" in out

    # list (now has one)
    assert cmd_automations(_auto_args(action="list")) == 0
    out = capsys.readouterr().out
    assert "a1" in out

    # pause / resume
    assert cmd_automations(_auto_args(action="pause", id="a1")) == 0
    out = capsys.readouterr().out
    assert "PAUSED" in out
    assert cmd_automations(_auto_args(action="resume", id="a1")) == 0
    out = capsys.readouterr().out
    assert "ACTIVE" in out

    # run-now
    assert cmd_automations(_auto_args(action="run-now", id="a1")) == 0

    # remove
    assert cmd_automations(_auto_args(action="remove", id="a1")) == 0
    out = capsys.readouterr().out
    assert "removed a1" in out

    # usage errors
    assert cmd_automations(_auto_args(action="remove")) == 2
    assert cmd_automations(_auto_args(action="pause")) == 2
    assert cmd_automations(_auto_args(action="run-now")) == 2
    # unknown action
    assert cmd_automations(_auto_args(action="bogus")) == 2


# ---------------------------------------------------------------------------
# context.py : extraction + tiered memory edge paths
# ---------------------------------------------------------------------------

def test_extract_evidence_anthropic_blocks():
    msgs = [{
        "role": "assistant",
        "content": [
            {"type": "tool_use", "name": "fs_write", "input": {}},
            {"type": "tool_result",
             "content": [{"type": "text", "text": "Error: disk full"}]},
        ],
    }]
    ev = context.extract_evidence(msgs)
    assert "fs_write" in ev["tool_calls"]
    assert ev["errors"] >= 1


def test_extract_evidence_non_str_content():
    # content is neither str nor list -> the loop must not raise
    ev = context.extract_evidence([{"role": "user", "content": 12345}])
    assert ev["goals"] == []


def test_tiered_memory_dedup():
    tm = context.TieredMemory(hot_limit=2)
    # push two messages that yield the SAME verdict + tool call + goal so the
    # "already present" dedup branches (84->83, 88-89, 91->90) are exercised.
    dup = {"role": "assistant",
           "content": '{"verdict":"pass","evidence":"ok"}'}
    tc = {"role": "assistant",
          "content": [{"type": "tool_use", "name": "fs_write", "input": {}}]}
    goal = {"role": "user", "content": "shared goal"}
    for _ in range(4):
        tm.push(dup)
        tm.push(tc)
        tm.push(goal)
    # hot is capped
    assert len(tm.hot) == 2
    # cold collected exactly one of each (dedup worked)
    assert tm.cold["verdicts"].count('{"verdict":"pass","evidence":"ok"}') == 1
    assert tm.cold["tool_calls"].count("fs_write") == 1
    assert tm.cold["goals"].count("shared goal") == 1


def test_tiered_memory_empty_content_skips_warm():
    tm = context.TieredMemory(hot_limit=1)
    tm.push({"role": "user", "content": "   "})  # whitespace -> no warm line
    tm.push({"role": "user", "content": "x"})      # forces demote of "   "
    assert tm.warm == []                           # whitespace produced no warm
    tm.push({"role": "user", "content": "y"})      # forces demote of "x"
    assert len(tm.warm) == 1                       # "x" produced a warm line


def test_tiered_memory_snapshot_empty_branches():
    tm = context.TieredMemory(hot_limit=8)
    # no warm, no cold -> neither system note appended (100->104, 105->109)
    snap = tm.snapshot()
    assert all(m.get("role") != "system" for m in snap)
    # a verbatim hot message survives
    tm.push({"role": "user", "content": "hi"})
    snap2 = tm.snapshot()
    assert any(m.get("content") == "hi" for m in snap2)


def test_tiered_memory_persist_no_path():
    tm = context.TieredMemory(hot_limit=2)  # path=None
    tm.push({"role": "user", "content": "x"})  # overflows -> demote
    # persist() must early-return without writing anything
    tm.persist()
    assert tm.path is None


def test_tiered_memory_load_edge_cases(tmp_path):
    p = tmp_path / "cold.json"
    # missing file -> load() is a no-op
    tm = context.TieredMemory(hot_limit=2, path=str(p))
    tm.load()
    assert tm.cold["verdicts"] == []

    # corrupt JSON -> load() swallows JSONDecodeError and returns
    p.write_text("{not valid json", encoding="utf-8")
    tm2 = context.TieredMemory(hot_limit=2, path=str(p))
    tm2.load()
    assert tm2.cold["verdicts"] == []

    # non-dict JSON -> load() keeps default cold (125->exit)
    p.write_text("[1,2,3]", encoding="utf-8")
    tm3 = context.TieredMemory(hot_limit=2, path=str(p))
    tm3.load()
    assert isinstance(tm3.cold, dict)


# ---------------------------------------------------------------------------
# serve.py : extra GET/POST routes over a real localhost server
# ---------------------------------------------------------------------------

@pytest.fixture
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve_mod.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    yield base
    srv.shutdown()
    srv.server_close()


def _req(base, method, path, body=None):
    url = base + path
    data = None
    headers = {}
    if body is not None:
        data = (body if isinstance(body, (bytes, bytearray))
                else json.dumps(body).encode("utf-8"))
        if not isinstance(body, (bytes, bytearray)):
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_get_bench(http_server):
    code, headers, body = _req(http_server, "GET", "/bench")
    assert code == 200
    assert "application/json" in headers.get("Content-Type", "")


def test_get_gate(http_server):
    code, headers, body = _req(http_server, "GET", "/gate")
    assert code == 200
    payload = json.loads(body)
    assert "status" in payload


def test_get_session_by_id(http_server, monkeypatch):
    def fake_read(sid):
        return [{"kind": "message", "message": {"role": "assistant",
                                                "content": "hi"}}]

    def fake_lineage():
        return {"s1": {"parent": "p0", "at_index": 2}}

    monkeypatch.setattr(serve_mod.sessions_mod, "_read_records", fake_read)
    monkeypatch.setattr(serve_mod.sessions_mod, "list_lineage", fake_lineage)

    code, _, body = _req(http_server, "GET", "/sessions/s1")
    assert code == 200
    payload = json.loads(body)
    assert payload["session_id"] == "s1"
    assert payload["fork_of"] == "p0"
    assert payload["fork_at_index"] == 2

    # bad id (contains slash)
    code, _, _ = _req(http_server, "GET", "/sessions/a/b")
    assert code == 400

    # not found
    def fake_read_missing(sid):
        raise FileNotFoundError()
    monkeypatch.setattr(serve_mod.sessions_mod, "_read_records",
                        fake_read_missing)
    code, _, _ = _req(http_server, "GET", "/sessions/missing")
    assert code == 404


def test_post_fork(http_server, monkeypatch):
    monkeypatch.setattr(serve_mod.sessions_mod, "fork_session",
                        lambda parent, at_index: "new-" + parent)
    code, _, body = _req(http_server, "POST", "/sessions/fork",
                         {"parent": "s1", "at_index": "3"})
    assert code == 200
    payload = json.loads(body)
    assert payload["new_session_id"] == "new-s1"

    # missing parent
    code, _, _ = _req(http_server, "POST", "/sessions/fork", {})
    assert code == 400

    # bad at_index
    code, _, _ = _req(http_server, "POST", "/sessions/fork",
                      {"parent": "s1", "at_index": "xyz"})
    assert code == 400

    # parent not found
    monkeypatch.setattr(serve_mod.sessions_mod, "fork_session",
                        lambda parent, at_index: (_ for _ in ()).throw(
                            FileNotFoundError()))
    code, _, _ = _req(http_server, "POST", "/sessions/fork", {"parent": "x"})
    assert code == 404


def test_post_compress(http_server, monkeypatch):
    monkeypatch.setattr(serve_mod.sessions_mod, "compress_session",
                        lambda sid: {"session_id": sid, "compressed": True})
    code, _, body = _req(http_server, "POST", "/sessions/compress",
                         {"id": "s1"})
    assert code == 200
    payload = json.loads(body)
    assert payload["compressed"] is True

    # missing id
    code, _, _ = _req(http_server, "POST", "/sessions/compress", {})
    assert code == 400

    # not found
    monkeypatch.setattr(serve_mod.sessions_mod, "compress_session",
                        lambda sid: (_ for _ in ()).throw(FileNotFoundError()))
    code, _, _ = _req(http_server, "POST", "/sessions/compress", {"id": "x"})
    assert code == 404
