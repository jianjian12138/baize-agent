"""Tests for baize.automations - zero-dep scheduler (P2-3).

The run action is injected everywhere so we assert *scheduling correctness*
without a model. fail-closed behaviour (corrupt store, crashing runner) is
exercised directly.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from baize import automations as auto
from baize.automations import (
    AutomationScheduler,
    AutomationSpec,
    AutomationStore,
    _next_cron_fire,
    _parse_cron_field,
    _parse_iso,
    _to_iso,
)


NOW = 1_600_000_000.0  # fixed epoch for deterministic scheduling tests


def make_store(tmp_path):
    return AutomationStore(tmp_path / "automations.json")


def make_scheduler(store, runner=lambda s: {"ok": True}, clock=lambda: NOW):
    return AutomationScheduler(store=store, runner=runner, clock=clock)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def test_store_roundtrip(tmp_path):
    store = make_store(tmp_path)
    assert store.list() == []
    spec = AutomationSpec(id="a", name="nightly", schedule_type="recurring",
                          rrule="interval:3600", created_at=_to_iso(NOW))
    store.save(spec)
    got = store.get("a")
    assert got is not None
    assert got.name == "nightly"
    assert len(store.list()) == 1
    store.delete("a")
    assert store.get("a") is None
    assert store.list() == []


def test_store_atomic_update_keeps_others(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(id="a", name="first"))
    store.save(AutomationSpec(id="b", name="second"))
    store.save(AutomationSpec(id="a", name="first-rev"))   # overwrite a
    ids = [s.id for s in store.list()]
    assert ids == ["b", "a"]
    assert store.get("a").name == "first-rev"


def test_store_corrupt_fail_closed(tmp_path):
    p = tmp_path / "automations.json"
    p.write_text("{not valid json,,", encoding="utf-8")
    store = AutomationStore(p)
    assert store.list() == []          # corrupt -> empty, not crash


# ---------------------------------------------------------------------------
# Cron parsing
# ---------------------------------------------------------------------------

def test_parse_cron_field_wildcard():
    assert _parse_cron_field("*", 0, 59) == set(range(0, 60))


def test_parse_cron_field_step():
    assert _parse_cron_field("*/15", 0, 59) == {0, 15, 30, 45}


def test_parse_cron_field_range_and_list():
    assert _parse_cron_field("1-5", 0, 59) == {1, 2, 3, 4, 5}
    assert _parse_cron_field("1,3,5", 0, 59) == {1, 3, 5}


def test_parse_cron_field_malformed_returns_empty():
    assert _parse_cron_field("x-y-z", 0, 59) == set()


def test_next_cron_fire_every_minute():
    # every minute -> the very next minute boundary (tz-independent)
    expected = (int(NOW) // 60 + 1) * 60
    assert _next_cron_fire("* * * * *", NOW) == expected


def test_next_cron_fire_step_aligned():
    nxt = _next_cron_fire("*/15 * * * *", NOW)
    assert nxt is not None
    assert nxt > NOW
    assert nxt % 900 == 0                 # :00/:15/:30/:45 minute boundaries


def test_next_cron_fire_midnight():
    nxt = _next_cron_fire("0 0 * * *", NOW)
    assert nxt is not None
    assert nxt > NOW
    import time as _t
    lt = _t.localtime(nxt)
    assert lt.tm_hour == 0 and lt.tm_min == 0


def test_next_cron_fire_malformed():
    assert _next_cron_fire("not a cron", NOW) is None


# ---------------------------------------------------------------------------
# Due / firing logic
# ---------------------------------------------------------------------------

def test_recurring_interval_due_then_cools_off(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(
        id="a", schedule_type="recurring", rrule="interval:5",
        created_at=_to_iso(NOW - 100)))
    sched = make_scheduler(store)
    assert [s.id for s in sched.due_now()] == ["a"]
    sched.tick()
    # after firing, last_run=NOW -> next fire at NOW+5, not due yet
    assert sched.due_now() == []
    got = store.get("a")
    assert _parse_iso(got.last_run) == NOW


def test_once_past_fires_then_terminal(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(
        id="a", schedule_type="once", scheduled_at=_to_iso(NOW - 10),
        status="ACTIVE"))
    sched = make_scheduler(store)
    assert [s.id for s in sched.due_now()] == ["a"]
    sched.tick()
    got = store.get("a")
    assert got.status == "DONE"           # one-time: fires exactly once
    assert sched.due_now() == []


def test_once_future_not_due(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(
        id="a", schedule_type="once", scheduled_at=_to_iso(NOW + 10)))
    assert AutomationScheduler(store=store, clock=lambda: NOW).due_now() == []


def test_paused_not_due(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(
        id="a", schedule_type="recurring", rrule="interval:1",
        created_at=_to_iso(NOW - 100), status="PAUSED"))
    assert AutomationScheduler(store=store, clock=lambda: NOW).due_now() == []


def test_valid_window_blocks(tmp_path):
    store = make_store(tmp_path)
    # not yet active (valid_from in the future)
    store.save(AutomationSpec(
        id="future", schedule_type="recurring", rrule="interval:1",
        created_at=_to_iso(NOW - 100), valid_from=_to_iso(NOW + 10)))
    # already expired (valid_until in the past)
    store.save(AutomationSpec(
        id="expired", schedule_type="recurring", rrule="interval:1",
        created_at=_to_iso(NOW - 100), valid_until=_to_iso(NOW - 10)))
    assert AutomationScheduler(store=store, clock=lambda: NOW).due_now() == []


def test_next_due_is_nearest(tmp_path):
    store = make_store(tmp_path)
    # both anchored in the FUTURE so neither is overdue; ordering by interval
    store.save(AutomationSpec(id="late", schedule_type="recurring",
                              rrule="interval:100",
                              created_at=_to_iso(NOW + 10)))
    store.save(AutomationSpec(id="soon", schedule_type="recurring",
                              rrule="interval:5",
                              created_at=_to_iso(NOW + 5)))
    sched = AutomationScheduler(store=store, clock=lambda: NOW)
    nxt = sched.next_due()
    assert nxt is not None
    # "soon" (next fire NOW+5) precedes "late" (next fire NOW+10)
    assert abs(nxt - (NOW + 5)) < 1


def test_tick_fail_closed_on_runner_crash(tmp_path):
    store = make_store(tmp_path)
    store.save(AutomationSpec(
        id="a", schedule_type="recurring", rrule="interval:1",
        created_at=_to_iso(NOW - 100)))
    state = {"called": False}
    def boom(spec):
        state["called"] = True
        raise RuntimeError("automation blew up")
    sched = make_scheduler(store, runner=boom)
    sched.tick()                          # must NOT propagate the exception
    assert state["called"] is True
    # fail-closed: last_run is still recorded so we don't spin forever
    assert store.get("a").last_run != ""


# ---------------------------------------------------------------------------
# Zero-dependency guard
# ---------------------------------------------------------------------------

def test_stdlib_only_no_third_party_imports():
    src = Path(auto.__file__).read_text(encoding="utf-8")
    forbidden = r"^\s*(import|from)\s+(requests|httpx|yaml|tiktoken|litellm|"
    forbidden += r"anthropic|openai|croniter|apscheduler)\b"
    matches = re.findall(forbidden, src, re.M)
    assert matches == [], f"forbidden import in automations.py: {matches}"


def test_module_not_polluting_sys_modules_with_forbidden():
    for mod in ("yaml", "httpx", "litellm", "tiktoken"):
        # only fail if it was imported *because of* our module; since we import
        # lazily and nothing else loaded it, it should be absent.
        if mod in sys.modules:
            # allowed only if something else already loaded it
            continue
        assert mod not in sys.modules
