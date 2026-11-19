"""Thread-safe HTTP/HTTPS Keep-Alive Connection Pool (pure Python stdlib).

Reuses persistent TCP/TLS sockets across sequential LLM API requests to avoid
repeated handshake latency, with automatic stale-socket eviction and retry.
"""
from __future__ import annotations

import http.client
import io
import json
import threading
import time
import urllib.error
import urllib.parse
from typing import Any

__all__ = [
    "HTTPConnPool",
    "get_http_pool",
    "get_http_pool_stats",
    "pooled_post_json",
]


class HTTPConnPool:
    """Thread-safe per-(scheme, host, port) Keep-Alive HTTP/HTTPS pool."""

    def __init__(self, max_per_host: int = 8, idle_ttl: float = 60.0) -> None:
        self.max_per_host = max_per_host
        self.idle_ttl = idle_ttl
        self._lock = threading.Lock()
        self._pool: dict[tuple[str, str, int], list[tuple[http.client.HTTPConnection, float]]] = {}
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def acquire(self, scheme: str, host: str, port: int) -> tuple[http.client.HTTPConnection, bool]:
        key = (scheme, host, port)
        now = time.monotonic()
        with self._lock:
            bucket = self._pool.get(key)
            while bucket:
                conn, ts = bucket.pop()
                if now - ts <= self.idle_ttl and conn.sock is not None:
                    self.hits += 1
                    return conn, True
                self.evictions += 1
                try:
                    conn.close()
                except Exception:
                    pass
            self.misses += 1
        conn = (
            http.client.HTTPSConnection(host, port, timeout=120)
            if scheme == "https"
            else http.client.HTTPConnection(host, port, timeout=120)
        )
        return conn, False

    def release(self, scheme: str, host: str, port: int, conn: http.client.HTTPConnection) -> None:
        key = (scheme, host, port)
        with self._lock:
            bucket = self._pool.setdefault(key, [])
            if len(bucket) < self.max_per_host and conn.sock is not None:
                bucket.append((conn, time.monotonic()))
                return
            self.evictions += 1
        try:
            conn.close()
        except Exception:
            pass

    def stats(self) -> dict[str, int]:
        with self._lock:
            pooled = sum(len(v) for v in self._pool.values())
            return {
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "pooled": pooled,
            }

    def close_all(self) -> None:
        with self._lock:
            for bucket in self._pool.values():
                for conn, _ in bucket:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._pool.clear()


_CONN_POOL = HTTPConnPool()


def get_http_pool() -> HTTPConnPool:
    return _CONN_POOL


def get_http_pool_stats() -> dict[str, int]:
    """Return live Keep-Alive connection pool telemetry."""
    return _CONN_POOL.stats()


def pooled_post_json(url: str, headers: dict, payload: dict) -> dict[str, Any]:
    """POST JSON using the shared Keep-Alive connection pool with stale-socket retry."""
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise urllib.error.URLError(f"unknown url type: {url}")
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    data = json.dumps(payload).encode("utf-8")
    req_headers = dict(headers)
    req_headers.setdefault("Connection", "keep-alive")
    req_headers["Content-Length"] = str(len(data))

    for retry_stale in (True, False):
        conn, from_pool = _CONN_POOL.acquire(scheme, host, port)
        try:
            conn.request("POST", target, body=data, headers=req_headers)
            resp = conn.getresponse()
            raw_bytes = resp.read()
            if getattr(resp, "will_close", True):
                conn.close()
            else:
                _CONN_POOL.release(scheme, host, port, conn)
            if resp.status >= 400:
                raise urllib.error.HTTPError(
                    url, resp.status, resp.reason, resp.headers, io.BytesIO(raw_bytes)
                )
            return json.loads(raw_bytes.decode("utf-8"))
        except (http.client.HTTPException, OSError):
            try:
                conn.close()
            except Exception:
                pass
            if from_pool and retry_stale:
                continue
            raise
    raise urllib.error.URLError(f"request failed for {url}")
