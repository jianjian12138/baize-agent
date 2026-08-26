"""V21 P2-3 Automations: a lightweight, zero-dependency scheduler.

Design
------
- Two schedule kinds: ``recurring`` (interval ``interval:N`` seconds, or a
  minimal 5-field cron ``cron: "M H Dom Mon Dow"``) and ``once`` (fires at a
  single ``scheduled_at`` ISO timestamp, then becomes terminal ``DONE``).
- Automations persist to a JSON file (default ``persistence/automations.json``).
  A corrupt file fails closed to an empty list - never crash the host.
- A background daemon thread polls every ``BAIZE_AUTOMATIONS_POLL_SECONDS`` and
  fires every due automation.
- The run action is injectable: the real LLM-backed runner (``Orchestrator``)
  is only invoked in production. Unit tests inject a fake runner, so they
  assert *scheduling correctness*, not the model (honest: no model needed).
- fail-closed everywhere: a crashing automation or a crashing scheduler tick
  must never propagate into the host loop.

No third-party dependencies (stdlib ``threading`` / ``json`` / ``datetime``
only). This is a deliberate constraint from the project's iron rules.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import load_config
from .logging_setup import get_logger
from .observability import obs

log = get_logger("automations")

Runner = Callable[["AutomationSpec"], object]


# ---------------------------------------------------------------------------
# Time helpers (ISO <-> epoch, defensive)
# ---------------------------------------------------------------------------

def _now_ts() -> float:
    return time.time()


def _parse_iso(s: str | None) -> float | None:
    """Parse an ISO-8601 timestamp (or bare epoch seconds) to epoch float.

    Anything unparseable returns ``None`` rather than raising - schedulers must
    never die on a bad timestamp in a user file.
    """
    if not s:
        return None
    s = str(s).strip()
    if s in ("0", "none", "None", ""):
        return None
    try:
        if s.replace(".", "", 1).isdigit():   # bare epoch seconds
            return float(s)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _to_iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Minimal 5-field cron (stdlib only)
# ---------------------------------------------------------------------------

def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field into the set of matching integer values.

    Supports ``*``, lists (``a,b``), ranges (``a-b``) and steps (``*/n``,
    ``a-b/n``). Returns an empty set on malformed input (fail closed).
    """
    vals: set[int] = set()
    try:
        for part in str(field).split(","):
            part = part.strip()
            if not part:
                continue
            step = 1
            if "/" in part:
                head, step_s = part.split("/", 1)
                step = int(step_s) or 1
                part = head
            else:
                head = part
            if part == "*":
                rng = list(range(lo, hi + 1))
            elif "-" in part:
                a, b = part.split("-")
                rng = list(range(int(a), int(b) + 1))
            else:
                rng = [int(part)]
            for v in rng:
                if (v - lo) % step == 0:
                    vals.add(v)
    except (ValueError, IndexError):
        return set()
    return vals


def _next_cron_fire(expr: str, after: float) -> float | None:
    """Return the next epoch >= ``after`` matching the 5-field cron expr.

    Searches minute-by-minute up to 4 years out (bounded). ``0`` = Sunday, as
    in standard cron. Returns ``None`` if no match is found in range or the
    expression is malformed.
    """
    try:
        fields = expr.split()
        if len(fields) != 5:
            return None
        mins = _parse_cron_field(fields[0], 0, 59)
        hrs = _parse_cron_field(fields[1], 0, 23)
        doms = _parse_cron_field(fields[2], 1, 31)
        mons = _parse_cron_field(fields[3], 1, 12)
        dows = _parse_cron_field(fields[4], 0, 6)   # 0 = Sunday
    except (ValueError, IndexError):
        return None
    if not (mins and hrs and doms and mons and dows):
        return None
    # align to the next minute boundary
    t = int(after) + 1
    t = t - (t % 60) + 60
    end = after + 4 * 365 * 24 * 3600
    dom_star = fields[2].strip() == "*"
    dow_star = fields[4].strip() == "*"
    while t <= end:
        lt = time.localtime(t)
        wday = (lt.tm_wday + 1) % 7          # convert Mon=0..Sun=6 -> Sun=0
        if dom_star or dow_star:
            day_ok = (lt.tm_mday in doms) and (wday in dows)
        else:
            # both constrained: cron "OR" semantics
            day_ok = (lt.tm_mday in doms) or (wday in dows)
        if (lt.tm_mon in mons and day_ok and
                lt.tm_hour in hrs and lt.tm_min in mins):
            return float(t)
        t += 60
    return None


# ---------------------------------------------------------------------------
# Spec + persistent store
# ---------------------------------------------------------------------------

@dataclass
class AutomationSpec:
    id: str
    name: str = ""
    prompt: str = ""
    schedule_type: str = "recurring"    # recurring | once
    rrule: str = ""                     # interval:N | cron:"..." (recurring)
    scheduled_at: str = ""             # ISO timestamp (once)
    status: str = "ACTIVE"             # ACTIVE | PAUSED | DONE
    cwds: str = ""
    created_at: str = ""
    last_run: str = ""
    next_run: str = ""
    valid_from: str = ""               # ISO; optional activation window
    valid_until: str = ""              # ISO; optional expiry

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "AutomationSpec":
        known = {k: d.get(k, "") for k in cls.__dataclass_fields__}
        return cls(**known)


class AutomationStore:
    """JSON-backed store. Corrupt/empty files fail closed to []. """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def list(self) -> list[AutomationSpec]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            obs.record_error("automation_store_corrupt")
            log.warning("[automations] corrupt store %s: %s -> treated as empty",
                        self.path, exc)
            return []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "automations" in data:
            items = data.get("automations", [])
        else:
            return []
        out: list[AutomationSpec] = []
        for d in items:
            if isinstance(d, dict):
                try:
                    out.append(AutomationSpec.from_dict(d))
                except Exception:
                    continue
        return out

    def get(self, id: str) -> AutomationSpec | None:
        for s in self.list():
            if s.id == id:
                return s
        return None

    def save(self, spec: AutomationSpec) -> None:
        specs = [s for s in self.list() if s.id != spec.id]
        specs.append(spec)
        self._write(specs)

    def delete(self, id: str) -> None:
        specs = [s for s in self.list() if s.id != id]
        self._write(specs)

    def _write(self, specs: list[AutomationSpec]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"automations": [s.to_dict() for s in specs]},
            ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)            # atomic on POSIX/NTFS


# ---------------------------------------------------------------------------
# Default runner (real LLM path, only used in production)
# ---------------------------------------------------------------------------

def _default_runner(spec: AutomationSpec, client=None, on_event=None):
    """Run the automation prompt through the Orchestrator (real LLM path)."""
    from .llm import LLMClient
    from .orchestrator import Orchestrator
    client = client or LLMClient()
    if not client.configured:
        obs.record_error("automation_no_model")
        return {"ok": False, "reason": "model endpoint not configured"}
    orch = Orchestrator(client=client,
                        on_event=on_event or (lambda *_: None))
    res = orch.run(spec.prompt)
    return {"ok": res.success, "subtasks": len(res.reports)}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class AutomationScheduler:
    def __init__(self, store: AutomationStore | None = None,
                 runner: Runner | None = None, clock=None,
                 interval: float = 60.0, cfg: dict | None = None,
                 on_event=None):
        self.cfg = cfg or load_config()
        self._on_event = on_event or (lambda *_: None)
        self.store = store or AutomationStore(
            self.cfg.get("BAIZE_AUTOMATIONS_FILE") or
            Path(self.cfg["BAIZE_PERSISTENCE_DIR"]) / "automations.json")
        # Default runner lazily references the scheduler's on_event so a test
        # that injects on_event still sees events from the production path.
        self.runner = runner or (
            lambda spec: _default_runner(spec, on_event=self._on_event))
        self._clock = clock or _now_ts
        self.interval = float(self.cfg.get("BAIZE_AUTOMATIONS_POLL_SECONDS")
                              or interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- scheduling math ----------------------------------------------------

    def _in_valid_window(self, spec: AutomationSpec, now: float) -> bool:
        vf = _parse_iso(spec.valid_from) if hasattr(spec, "valid_from") else None
        vu = _parse_iso(spec.valid_until) if hasattr(spec, "valid_until") else None
        if vf is not None and now < vf:
            return False
        if vu is not None and now > vu:
            return False
        return True

    def _next_fire(self, spec: AutomationSpec, now: float) -> float | None:
        if spec.schedule_type == "once":
            return _parse_iso(spec.scheduled_at)
        last = _parse_iso(spec.last_run)
        created = _parse_iso(spec.created_at)
        if spec.rrule and spec.rrule.startswith("cron:"):
            return _next_cron_fire(spec.rrule.split(":", 1)[1].strip(), now)
        # interval (or hourly default)
        secs = 3600
        if spec.rrule and spec.rrule.startswith("interval:"):
            try:
                secs = float(spec.rrule.split(":", 1)[1])
            except (ValueError, IndexError):
                secs = 3600
            secs = secs if secs > 0 else 3600
        if last is None:
            # never run: anchor on creation time; if that is already in the
            # past the task is overdue and must fire now (catch-up to present,
            # without replaying every missed occurrence).
            anchor = created if created is not None else now
            if anchor <= now:
                return now
            nxt = anchor
        else:
            nxt = last
        while nxt <= now:           # advance to the first future occurrence
            nxt += secs
        return nxt

    def due_now(self) -> list[AutomationSpec]:
        now = self._clock()
        out: list[AutomationSpec] = []
        for spec in self.store.list():
            if spec.status != "ACTIVE":
                continue
            if not self._in_valid_window(spec, now):
                continue
            nxt = self._next_fire(spec, now)
            if nxt is not None and nxt <= now:
                out.append(spec)
        return out

    def next_due(self) -> float | None:
        now = self._clock()
        best: float | None = None
        for spec in self.store.list():
            if spec.status != "ACTIVE":
                continue
            if not self._in_valid_window(spec, now):
                continue
            nxt = self._next_fire(spec, now)
            if nxt is not None and (best is None or nxt < best):
                best = nxt
        return best

    # -- execution ----------------------------------------------------------

    def _fire(self, spec: AutomationSpec) -> None:
        try:
            self.runner(spec)
            obs.inc("automation_runs")
            spec.last_run = _to_iso(self._clock())
            if spec.schedule_type == "once":
                spec.status = "DONE"       # one-time: fire exactly once
            self.store.save(spec)
            self._on_event("automation", spec.name)
        except Exception as exc:           # fail-closed: never crash scheduler
            obs.record_error("automation_run_failed")
            spec.last_run = _to_iso(self._clock())
            self.store.save(spec)
            log.warning("[automations] run failed for %s: %s", spec.id, exc)

    def tick(self) -> list[str]:
        """Fire every due automation once. Returns the ids that were fired."""
        fired: list[str] = []
        for spec in self.due_now():
            self._fire(spec)
            fired.append(spec.id)
        return fired

    # -- daemon loop --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:               # fail-closed: tick crash is isolated
                obs.record_error("scheduler_tick_failed")

    def stop(self) -> None:
        self._stop.set()
