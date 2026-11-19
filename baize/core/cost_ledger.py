"""V42.0.0 Helios — Session Cost Ledger, Cache Accounting & Hard Budget Circuit Breaker.

Pure Python standard library (SQLite WAL). Tracks per-call input/cached/output
tokens and estimated USD cost across providers, computes real prompt-cache hit
ratios, emits soft warnings at ``BAIZE_BUDGET_WARN_RATIO`` (default 80%), and
trips a hard circuit breaker (:class:`BudgetExceededError`) at 100% of either
``BAIZE_MAX_SESSION_USD`` or ``BAIZE_MAX_SESSION_TOKENS``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import load_config


@dataclass(frozen=True)
class ModelRate:
    """USD per 1,000,000 tokens for input, cached input, and output."""

    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


# Transparent built-in rate table (USD per 1M tokens); local models default to $0.00.
DEFAULT_RATES: dict[str, ModelRate] = {
    "deepseek-chat": ModelRate(0.27, 0.07, 1.10),
    "deepseek-reasoner": ModelRate(0.55, 0.14, 2.19),
    "gpt-4o": ModelRate(2.50, 1.25, 10.00),
    "gpt-4o-mini": ModelRate(0.15, 0.075, 0.60),
    "o3-mini": ModelRate(1.10, 0.55, 4.40),
    "claude-3-5-sonnet": ModelRate(3.00, 0.30, 15.00),
    "claude-sonnet-4": ModelRate(3.00, 0.30, 15.00),
    "gemini-2.5-flash": ModelRate(0.15, 0.0375, 0.60),
    "gemini-2.5-pro": ModelRate(1.25, 0.3125, 10.00),
    "ollama": ModelRate(0.0, 0.0, 0.0),
}
FALLBACK_RATE = ModelRate(0.50, 0.125, 1.50)


def resolve_rate(model: str, provider: str = "") -> ModelRate:
    low_p = (provider or "").strip().lower()
    if low_p == "ollama":
        return DEFAULT_RATES["ollama"]
    low_m = (model or "").strip().lower()
    if low_m in DEFAULT_RATES:
        return DEFAULT_RATES[low_m]
    for key, rate in DEFAULT_RATES.items():
        if key in low_m:
            return rate
    return FALLBACK_RATE


def estimate_usd(
    model: str,
    *,
    prompt_tokens: int,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
    provider: str = "",
) -> float:
    rate = resolve_rate(model, provider=provider)
    cached = min(max(0, int(cached_tokens)), max(0, int(prompt_tokens)))
    uncached = max(0, int(prompt_tokens) - cached)
    out = max(0, int(completion_tokens))
    usd = (
        (uncached / 1_000_000.0) * rate.input_per_1m
        + (cached / 1_000_000.0) * rate.cached_input_per_1m
        + (out / 1_000_000.0) * rate.output_per_1m
    )
    return round(usd, 6)


class BudgetExceededError(RuntimeError):
    """Raised when a session hits its configured hard USD or token limit."""

    def __init__(self, message: str, status: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status or {}


@dataclass
class BudgetStatus:
    session_id: str
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_usd: float
    cache_hit_ratio: float
    max_usd: float
    max_tokens: int
    warn_ratio: float
    usd_ratio: float
    token_ratio: float
    warning: bool
    exceeded: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CostLedger:
    """Thread-safe SQLite WAL ledger tracking token usage, cache hits, and budget guards."""

    def __init__(self, db_path: str | Path | None = None, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or load_config()
        if db_path is None:
            base = Path(self.cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
            db_path = base / "cost_ledger.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cost_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    estimated_usd REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_session ON cost_events(session_id)")

    def record(
        self,
        *,
        session_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> dict[str, Any]:
        pt = max(0, int(prompt_tokens))
        ct = min(max(0, int(cached_tokens)), pt)
        ot = max(0, int(completion_tokens))
        usd = estimate_usd(model, prompt_tokens=pt, cached_tokens=ct, completion_tokens=ot, provider=provider)
        ts = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cost_events(ts, session_id, provider, model, prompt_tokens, cached_tokens, completion_tokens, estimated_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, session_id or "default", provider or "openai", model or "unknown", pt, ct, ot, usd),
            )
        return {
            "ts": ts,
            "session_id": session_id or "default",
            "provider": provider,
            "model": model,
            "prompt_tokens": pt,
            "cached_tokens": ct,
            "completion_tokens": ot,
            "estimated_usd": usd,
        }

    def check_budget(
        self,
        session_id: str,
        *,
        max_usd: float | None = None,
        max_tokens: int | None = None,
        warn_ratio: float | None = None,
    ) -> BudgetStatus:
        import os
        live_cfg = load_config()
        def _pick(key: str, default: str) -> str:
            env_v = os.environ.get(key)
            if env_v not in (None, ""):
                return env_v
            if key in self.cfg and str(self.cfg.get(key) or "") != "":
                return str(self.cfg[key])
            return str(live_cfg.get(key, default) or default)
        m_usd = float(max_usd if max_usd is not None else _pick("BAIZE_MAX_SESSION_USD", "0"))
        m_tok = int(max_tokens if max_tokens is not None else _pick("BAIZE_MAX_SESSION_TOKENS", "0"))
        w_ratio = float(warn_ratio if warn_ratio is not None else _pick("BAIZE_BUDGET_WARN_RATIO", "0.8"))

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(cached_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0),
                    COALESCE(SUM(estimated_usd), 0.0)
                FROM cost_events WHERE session_id = ?
                """,
                (session_id or "default",),
            ).fetchone()
        pt, ct, ot, usd = int(row[0]), int(row[1]), int(row[2]), round(float(row[3]), 6)
        total = pt + ot
        cache_ratio = round(ct / pt, 4) if pt > 0 else 0.0
        usd_ratio = round(usd / m_usd, 4) if m_usd > 0 else 0.0
        tok_ratio = round(total / m_tok, 4) if m_tok > 0 else 0.0

        reasons: list[str] = []
        exceeded = False
        warning = False
        if m_usd > 0 and usd >= m_usd:
            exceeded = True
            reasons.append(f"session USD ${usd:.4f} reached hard cap ${m_usd:.4f}")
        elif m_usd > 0 and usd_ratio >= w_ratio:
            warning = True
            reasons.append(f"session USD ${usd:.4f} reached {usd_ratio*100:.0f}% of ${m_usd:.4f}")
        if m_tok > 0 and total >= m_tok:
            exceeded = True
            reasons.append(f"session tokens {total:,} reached hard cap {m_tok:,}")
        elif m_tok > 0 and tok_ratio >= w_ratio:
            warning = True
            reasons.append(f"session tokens {total:,} reached {tok_ratio*100:.0f}% of {m_tok:,}")

        return BudgetStatus(
            session_id=session_id or "default",
            prompt_tokens=pt,
            cached_tokens=ct,
            completion_tokens=ot,
            total_tokens=total,
            estimated_usd=usd,
            cache_hit_ratio=cache_ratio,
            max_usd=m_usd,
            max_tokens=m_tok,
            warn_ratio=w_ratio,
            usd_ratio=usd_ratio,
            token_ratio=tok_ratio,
            warning=warning,
            exceeded=exceeded,
            reason="; ".join(reasons),
        )

    def summary(self, limit_sessions: int = 20) -> dict[str, Any]:
        with self._connect() as conn:
            tot = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(cached_tokens), 0),
                       COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(estimated_usd), 0.0)
                FROM cost_events
                """
            ).fetchone()
            rows = conn.execute(
                """
                SELECT session_id, COUNT(*), SUM(prompt_tokens), SUM(cached_tokens),
                       SUM(completion_tokens), SUM(estimated_usd), MAX(ts)
                FROM cost_events
                GROUP BY session_id
                ORDER BY MAX(ts) DESC
                LIMIT ?
                """,
                (max(1, limit_sessions),),
            ).fetchall()
        pt = int(tot[1])
        ct = int(tot[2])
        return {
            "total_calls": int(tot[0]),
            "prompt_tokens": pt,
            "cached_tokens": ct,
            "completion_tokens": int(tot[3]),
            "total_tokens": pt + int(tot[3]),
            "estimated_usd": round(float(tot[4]), 6),
            "cache_hit_ratio": round(ct / pt, 4) if pt > 0 else 0.0,
            "sessions": [
                {
                    "session_id": r[0],
                    "calls": int(r[1]),
                    "prompt_tokens": int(r[2]),
                    "cached_tokens": int(r[3]),
                    "completion_tokens": int(r[4]),
                    "estimated_usd": round(float(r[5]), 6),
                    "cache_hit_ratio": round(int(r[3]) / int(r[2]), 4) if int(r[2]) > 0 else 0.0,
                    "last_ts": float(r[6]),
                }
                for r in rows
            ],
        }

    def reset_session(self, session_id: str) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM cost_events WHERE session_id = ?", (session_id,))
            return int(cur.rowcount)


_GLOBAL_LEDGER: CostLedger | None = None
_GLOBAL_LEDGER_PATH: str = ""


def get_cost_ledger(cfg: dict[str, Any] | None = None) -> CostLedger:
    global _GLOBAL_LEDGER, _GLOBAL_LEDGER_PATH
    c = cfg or load_config()
    p = str(Path(c.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "cost_ledger.sqlite3")
    if _GLOBAL_LEDGER is None or _GLOBAL_LEDGER_PATH != p:
        _GLOBAL_LEDGER = CostLedger(db_path=p, cfg=c)
        _GLOBAL_LEDGER_PATH = p
    return _GLOBAL_LEDGER
