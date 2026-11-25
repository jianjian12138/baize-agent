"""Example custom business invariant oracle hook (plug your own via module:func)."""
from __future__ import annotations

import sqlite3
from typing import Any


def check_inventory_conservation(*, world: Any, context: dict[str, Any]) -> list[str]:
    """Verify stock >= 0 and stock + sum(confirmed order qty) == initial_stock for every SKU."""
    db_path = getattr(world, "db_path", None)
    if db_path is None or not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        products = [dict(r) for r in conn.execute("SELECT sku, initial_stock, stock FROM products").fetchall()]
        orders = [dict(r) for r in conn.execute("SELECT sku, qty, status FROM orders").fetchall()]
    finally:
        conn.close()

    confirmed: dict[str, int] = {}
    for o in orders:
        if o["status"] == "confirmed":
            confirmed[o["sku"]] = confirmed.get(o["sku"], 0) + int(o["qty"])

    violations: list[str] = []
    for p in products:
        sku = p["sku"]
        expected = int(p["initial_stock"]) - confirmed.get(sku, 0)
        if int(p["stock"]) < 0 or int(p["stock"]) != expected:
            violations.append(
                f"Inventory conservation violated for {sku}: stock={p['stock']}, expected={expected}"
            )
    return violations
