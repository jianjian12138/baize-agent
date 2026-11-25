"""Zero-dep HTTP server for built-in FlashCart demo SUT."""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import db

STATIC_DIR = Path(__file__).resolve().parent / "static"


def make_handler(db_path: str):
    class DemoHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_file(self, path: Path, content_type: str) -> None:
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._send_json(200, {"status": "ok", "service": "flashcart-demo"})
            elif path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif path == "/static/app.js":
                self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            elif path == "/api/products":
                self._send_json(200, {"products": db.list_products(db_path)})
            elif path == "/api/orders":
                self._send_json(200, {"orders": db.list_orders(db_path)})
            else:
                self._send_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads((self.rfile.read(length) if length > 0 else b"{}").decode("utf-8") or "{}")
            if path == "/api/orders":
                st, pl = db.create_order(
                    db_path,
                    sku=str(body.get("sku", "")),
                    qty=body.get("qty"),
                    idempotency_key=str(body.get("idempotency_key", "")),
                )
                self._send_json(st, pl)
                return
            m = re.fullmatch(r"/api/orders/(\d+)/cancel", path)
            if m:
                st, pl = db.cancel_order(db_path, int(m.group(1)))
                self._send_json(st, pl)
                return
            self._send_json(404, {"error": "NOT_FOUND"})

    return DemoHandler


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--db", default="/tmp/flashcart_demo.sqlite3")
    args = p.parse_args()
    db.init_db(args.db)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(args.db))
    print(f"FLASHCART_DEMO_READY http://{args.host}:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
