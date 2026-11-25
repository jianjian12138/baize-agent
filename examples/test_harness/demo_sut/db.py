"""Built-in demo SUT storage layer (SQLite WAL with inventory conservation & idempotency)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SEED_PRODUCTS = [
    ("sku-laptop", "ThinkLab Pro 14", 129900, 10),
    ("sku-keyboard", "MechKey 75", 14900, 25),
    ("sku-monitor", "UltraView 27 4K", 49900, 5),
]


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str | Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                initial_stock INTEGER NOT NULL CHECK(initial_stock >= 0),
                stock INTEGER NOT NULL CHECK(stock >= 0)
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT UNIQUE NOT NULL,
                sku TEXT NOT NULL REFERENCES products(sku),
                qty INTEGER NOT NULL CHECK(qty > 0),
                total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
                status TEXT NOT NULL CHECK(status IN ('confirmed', 'cancelled')),
                created_at REAL NOT NULL
            );
        """)
        for sku, name, price, stock in SEED_PRODUCTS:
            conn.execute(
                "INSERT OR IGNORE INTO products(sku, name, price_cents, initial_stock, stock) VALUES (?, ?, ?, ?, ?)",
                (sku, name, price, stock, stock),
            )
    finally:
        conn.close()


def list_products(db_path: str | Path) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT sku, name, price_cents, initial_stock, stock FROM products ORDER BY sku").fetchall()]
    finally:
        conn.close()


def create_order(db_path: str | Path, *, sku: str, qty: int, idempotency_key: str) -> tuple[int, dict[str, Any]]:
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        return 400, {"error": "INVALID_QTY", "message": "qty must be a positive integer"}
    if not idempotency_key or not idempotency_key.strip():
        return 400, {"error": "MISSING_IDEMPOTENCY_KEY", "message": "idempotency_key is required"}
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT id, idempotency_key, sku, qty, total_cents, status, created_at FROM orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return 200, {"order": dict(existing), "idempotent_replay": True}
        prod = conn.execute("SELECT sku, name, price_cents, stock FROM products WHERE sku = ?", (sku,)).fetchone()
        if prod is None:
            conn.execute("ROLLBACK")
            return 404, {"error": "SKU_NOT_FOUND", "message": f"unknown sku: {sku}"}
        if prod["stock"] < qty:
            conn.execute("ROLLBACK")
            return 409, {"error": "INSUFFICIENT_STOCK", "available": prod["stock"]}
        total_cents = int(prod["price_cents"]) * qty
        conn.execute("UPDATE products SET stock = stock - ? WHERE sku = ?", (qty, sku))
        cur = conn.execute(
            "INSERT INTO orders(idempotency_key, sku, qty, total_cents, status, created_at) VALUES (?, ?, ?, ?, 'confirmed', ?)",
            (idempotency_key, sku, qty, total_cents, time.time()),
        )
        order = conn.execute(
            "SELECT id, idempotency_key, sku, qty, total_cents, status, created_at FROM orders WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        conn.execute("COMMIT")
        return 201, {"order": dict(order), "idempotent_replay": False}
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return 500, {"error": "INTERNAL_ERROR", "message": str(exc)}
    finally:
        conn.close()


def cancel_order(db_path: str | Path, order_id: int) -> tuple[int, dict[str, Any]]:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute(
            "SELECT id, idempotency_key, sku, qty, total_cents, status, created_at FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            conn.execute("ROLLBACK")
            return 404, {"error": "ORDER_NOT_FOUND"}
        if order["status"] == "cancelled":
            conn.execute("COMMIT")
            return 200, {"order": dict(order), "already_cancelled": True}
        conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        conn.execute("UPDATE products SET stock = stock + ? WHERE sku = ?", (order["qty"], order["sku"]))
        updated = conn.execute(
            "SELECT id, idempotency_key, sku, qty, total_cents, status, created_at FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        conn.execute("COMMIT")
        return 200, {"order": dict(updated), "already_cancelled": False}
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return 500, {"error": "INTERNAL_ERROR", "message": str(exc)}
    finally:
        conn.close()


def list_orders(db_path: str | Path) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT id, idempotency_key, sku, qty, total_cents, status, created_at FROM orders ORDER BY id DESC").fetchall()]
    finally:
        conn.close()
