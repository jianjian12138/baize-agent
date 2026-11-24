"""V42.0.0 Helios — Pure-Stdlib RFC 6455 WebSocket & Chrome DevTools Protocol (CDP) Client.

Enables real headless browser verification (navigation, DOM extraction, Console
error capture, uncaught exception capture, and PNG screenshot capture) using ONLY
Python standard library sockets—zero Playwright/Selenium dependencies.

Honest Degradation Contract:
  When no local Chrome/Chromium/Edge binary is detected and no explicit ``ws_url``
  is supplied, raises :class:`CDPUnavailableError` cleanly instead of faking a pass.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CDPUnavailableError(RuntimeError):
    """Raised honestly when no browser binary or CDP endpoint is available."""


def find_browser_binary(override: str = "") -> str | None:
    """Locate a local Chrome, Chromium, or Edge binary, or return None."""
    if override and Path(override).is_file():
        return str(Path(override))
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for cand in candidates:
        if os.path.isabs(cand):
            if Path(cand).is_file():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


class SimpleWebSocketClient:
    """Minimal, RFC 6455 compliant client-side WebSocket using pure Python stdlib."""

    def __init__(self, url: str, timeout: float = 15.0) -> None:
        self.url = url
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._buf = bytearray()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.url)
        scheme = (parsed.scheme or "ws").lower()
        if scheme not in ("ws", "wss"):
            raise ValueError(f"Unsupported WebSocket scheme: {scheme}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        if scheme == "wss":
            ctx = ssl.create_default_context()
            raw_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        raw_sock.settimeout(self.timeout)
        self._sock = raw_sock

        sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((sec_key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._sock.sendall(handshake)

        # Read HTTP 101 response headers
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed before completion")
            self._buf.extend(chunk)
        sep = self._buf.index(b"\r\n\r\n")
        header_text = bytes(self._buf[:sep]).decode("latin-1", errors="replace")
        del self._buf[: sep + 4]
        if " 101 " not in header_text.splitlines()[0]:
            raise ConnectionError(f"WebSocket handshake rejected: {header_text.splitlines()[0]}")
        hdrs: dict[str, str] = {}
        for line in header_text.splitlines()[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        if hdrs.get("sec-websocket-accept") != expected_accept:
            raise ConnectionError("Invalid Sec-WebSocket-Accept header")

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._buf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("WebSocket connection closed")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        assert self._sock is not None
        header = bytearray([0x80 | (opcode & 0x0F)])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask_key = os.urandom(4)
        header.extend(mask_key)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def recv_text(self, timeout: float | None = None) -> str:
        assert self._sock is not None
        if timeout is not None:
            self._sock.settimeout(timeout)
        fragments: list[bytes] = []
        while True:
            b1, b2 = self._recv_exact(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # Ping -> Pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # Pong
                continue
            if opcode == 0x8:  # Close
                raise ConnectionError("WebSocket closed by peer")
            fragments.append(payload)
            if fin:
                return b"".join(fragments).decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


@dataclass
class CDPVerifyResult:
    ok: bool
    url: str
    mode: str = "cdp"
    title: str = ""
    console_errors: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    dom_snippet: str = ""
    screenshot_path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CDPBrowserClient:
    """High-level CDP verifier supporting explicit WebSocket endpoints or local Chrome."""

    def __init__(self, *, ws_url: str = "", browser_binary: str = "", timeout: float = 15.0) -> None:
        self.ws_url = ws_url.strip()
        self.browser_binary = browser_binary.strip()
        self.timeout = float(timeout)
        self._proc: subprocess.Popen | None = None
        self._user_data_dir: str = ""
        self._ws: SimpleWebSocketClient | None = None
        self._msg_id = 0
        self.console_errors: list[str] = []
        self.exceptions: list[str] = []
        self.network_errors: list[str] = []

    def _launch_local_browser(self) -> str:
        binary = find_browser_binary(self.browser_binary)
        if not binary:
            raise CDPUnavailableError(
                "No local Chrome/Chromium/Edge binary found; set BAIZE_CDP_BINARY or install Chromium."
            )
        # Pick an ephemeral free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self._user_data_dir = tempfile.mkdtemp(prefix="baize-cdp-")
        self._proc = subprocess.Popen(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self._user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + min(self.timeout, 10.0)
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as r:
                    targets = json.loads(r.read().decode("utf-8"))
                    for t in targets:
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            return str(t["webSocketDebuggerUrl"])
            except Exception:
                time.sleep(0.15)
        self.close()
        raise CDPUnavailableError("Timed out waiting for headless browser DevTools endpoint")

    def connect(self) -> None:
        target_ws = self.ws_url or self._launch_local_browser()
        self._ws = SimpleWebSocketClient(target_ws, timeout=self.timeout)
        self._ws.connect()

    def send_command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("CDP client is not connected")
        self._msg_id += 1
        cid = self._msg_id
        self._ws.send_text(json.dumps({"id": cid, "method": method, "params": params or {}}))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self._ws.recv_text(timeout=max(0.5, deadline - time.time()))
            frame = json.loads(raw)
            if "method" in frame:
                self._handle_event(frame)
                continue
            if frame.get("id") == cid:
                if "error" in frame:
                    raise RuntimeError(f"CDP error for {method}: {frame['error']}")
                return frame.get("result") or {}
        raise TimeoutError(f"CDP command timed out: {method}")

    def _handle_event(self, frame: dict[str, Any]) -> None:
        ev = frame.get("method", "")
        params = frame.get("params") or {}
        if ev == "Runtime.consoleAPICalled":
            if params.get("type") in ("error", "assert"):
                args = params.get("args") or []
                msg = " ".join(str(a.get("value") or a.get("description") or "") for a in args).strip()
                self.console_errors.append(msg or "console.error")
        elif ev == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            exc = details.get("exception") or {}
            self.exceptions.append(str(exc.get("description") or details.get("text") or "uncaught exception"))
        elif ev == "Network.loadingFailed":
            err_txt = str(params.get("errorText") or "network loading failed")
            self.network_errors.append(f"loadingFailed: {err_txt}")
        elif ev == "Network.responseReceived":
            resp = params.get("response") or {}
            status = int(resp.get("status") or 0)
            if status >= 400:
                self.network_errors.append(f"HTTP {status} {resp.get('url', '')}")

    def verify_page(self, url: str, *, screenshot_path: str | Path | None = None) -> CDPVerifyResult:
        try:
            self.connect()
            self.send_command("Runtime.enable")
            self.send_command("Page.enable")
            self.send_command("Page.navigate", {"url": url})
            title_res = self.send_command("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
            dom_res = self.send_command(
                "Runtime.evaluate",
                {"expression": "document.body ? document.body.innerText.slice(0, 600) : ''", "returnByValue": True},
            )
            title = str(((title_res.get("result") or {}).get("value")) or "")
            dom_snippet = str(((dom_res.get("result") or {}).get("value")) or "")
            saved_shot = ""
            if screenshot_path:
                shot = self.send_command("Page.captureScreenshot", {"format": "png"})
                b64 = shot.get("data") or ""
                if b64:
                    sp = Path(screenshot_path)
                    sp.parent.mkdir(parents=True, exist_ok=True)
                    sp.write_bytes(base64.b64decode(b64))
                    saved_shot = str(sp)
            ok = (len(self.console_errors) == 0 and len(self.exceptions) == 0)
            return CDPVerifyResult(
                ok=ok,
                url=url,
                mode="cdp",
                title=title,
                console_errors=list(self.console_errors),
                exceptions=list(self.exceptions),
                dom_snippet=dom_snippet,
                screenshot_path=saved_shot,
            )
        finally:
            self.close()

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = ""


# ===========================================================================
# V47.0.0 Horizon: Stateful Interactive CDP Browser Session Pool (E2E Actions)
# ===========================================================================

class InteractiveBrowserSession:
    """Long-lived stateful CDP browser session supporting multi-step E2E flows."""

    def __init__(
        self,
        session_id: str,
        *,
        ws_url: str = "",
        browser_binary: str = "",
        timeout: float = 15.0,
    ) -> None:
        self.session_id = session_id
        self.client = CDPBrowserClient(ws_url=ws_url, browser_binary=browser_binary, timeout=timeout)
        self.current_url: str = ""
        self.last_screenshot: str = ""
        self._aria_refs: dict[str, dict[str, Any]] = {}
        self.action_count: int = 0
        self.last_used: float = time.monotonic()
        self._connected = False
        self._lock = threading.RLock()

    def ensure_connected(self) -> None:
        with self._lock:
            if not self._connected or self.client._ws is None:
                self.client.connect()
                self.client.send_command("Runtime.enable")
                self.client.send_command("Page.enable")
                try:
                    self.client.send_command("Network.enable")
                except Exception:
                    pass
                self._connected = True
            self.last_used = time.monotonic()

    def _eval(self, expr: str) -> Any:
        res = self.client.send_command(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in res:
            details = res["exceptionDetails"] or {}
            raise RuntimeError(str(details.get("text") or "JS evaluation error"))
        return (res.get("result") or {}).get("value")

    _ARIA_INTERACTIVE_ROLES = frozenset({
        "button", "link", "textbox", "searchbox", "combobox", "checkbox",
        "radio", "menuitem", "tab", "switch", "option", "slider", "spinbutton",
        "heading", "dialog", "alert", "navigation", "main", "form",
    })

    def _resolve_aria_ref(self, selector: str) -> dict[str, Any] | None:
        s = selector.strip()
        key = s[1:] if s.startswith("@") else s
        if len(key) >= 2 and key[0] == "e" and key[1:].isdigit():
            return self._aria_refs.get(key)
        return None

    def _run_on_aria_ref(self, ref_info: dict[str, Any], fn_decl: str, arguments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        backend_id = ref_info.get("backendDOMNodeId")
        if backend_id:
            try:
                resolved = self.client.send_command("DOM.resolveNode", {"backendNodeId": int(backend_id)})
                obj_id = (resolved.get("object") or {}).get("objectId")
                if obj_id:
                    call_res = self.client.send_command("Runtime.callFunctionOn", {
                        "objectId": obj_id,
                        "functionDeclaration": fn_decl,
                        "arguments": arguments or [],
                        "returnByValue": True,
                    })
                    val = (call_res.get("result") or {}).get("value")
                    if isinstance(val, dict):
                        return val
            except Exception:
                pass
        ref_key = ref_info.get("ref", "")
        if ref_key:
            sel_json = json.dumps(f'[data-baize-ref="{ref_key}"]')
            arg_vals = ", ".join(json.dumps(a.get("value")) for a in (arguments or []))
            call_args = (", " + arg_vals) if arg_vals else ""
            js = f"(() => {{ const el = document.querySelector({sel_json}); if (!el) return {{found: false}}; return ({fn_decl}).call(el{call_args}); }})()"
            val = self._eval(js)
            if isinstance(val, dict):
                return val
        return {"found": False}

    def _capture_aria_tree(self, max_nodes: int = 80) -> tuple[list[dict[str, Any]], str, str]:
        nodes_out: list[dict[str, Any]] = []
        source = "cdp-axtree"
        try:
            try:
                self.client.send_command("Accessibility.enable")
            except Exception:
                pass
            ax = self.client.send_command("Accessibility.getFullAXTree")
            raw_nodes = ax.get("nodes") if isinstance(ax, dict) else None
            if isinstance(raw_nodes, list) and raw_nodes:
                self._aria_refs = {}
                idx = 0
                for n in raw_nodes:
                    if not isinstance(n, dict) or n.get("ignored"):
                        continue
                    role_obj = n.get("role") or {}
                    role = str(role_obj.get("value") if isinstance(role_obj, dict) else role_obj or "").lower()
                    if role not in self._ARIA_INTERACTIVE_ROLES:
                        continue
                    name_obj = n.get("name") or {}
                    name = str(name_obj.get("value") if isinstance(name_obj, dict) else name_obj or "").strip()[:120]
                    backend_id = n.get("backendDOMNodeId")
                    if not name and not backend_id:
                        continue
                    idx += 1
                    ref_key = f"e{idx}"
                    entry = {"ref": ref_key, "role": role, "name": name, "backendDOMNodeId": backend_id}
                    self._aria_refs[ref_key] = entry
                    nodes_out.append(entry)
                    if idx >= max_nodes:
                        break
        except Exception:
            nodes_out = []

        if not nodes_out:
            source = "dom-fallback"
            js = """(() => {
              const els = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role],[aria-label],h1,h2,h3')).slice(0, 80);
              return els.map((el, i) => {
                const ref = 'e' + (i + 1);
                el.setAttribute('data-baize-ref', ref);
                const role = (el.getAttribute('role') || el.tagName || '').toLowerCase();
                const name = (el.getAttribute('aria-label') || el.innerText || el.placeholder || el.value || '').trim().slice(0, 120);
                return { ref, role, name, backendDOMNodeId: null };
              });
            })()"""
            raw_dom = self._eval(js) or []
            self._aria_refs = {}
            if isinstance(raw_dom, list):
                for item in raw_dom[:max_nodes]:
                    if isinstance(item, dict) and item.get("ref"):
                        self._aria_refs[str(item["ref"])] = item
                        nodes_out.append(item)

        lines = [f"[{n['ref']}] {n['role']} {json.dumps(n['name'], ensure_ascii=False)}" for n in nodes_out]
        return nodes_out, "\n".join(lines), source

    def execute(
        self,
        action: str,
        *,
        url: str = "",
        selector: str = "",
        value: str = "",
        expression: str = "",
        timeout: float = 10.0,
        screenshot_dir: Path | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single interactive E2E browser action on this live session."""
        act = (action or "").strip().lower()
        with self._lock:
            self.last_used = time.monotonic()
            if act == "close":
                self.close()
                return {"ok": True, "session_id": self.session_id, "action": "close", "closed": True}

            if act == "navigate":
                if not url.strip():
                    return {"ok": False, "action": act, "error": "navigate requires non-empty url"}
                # Enforce egress allowlist before connecting/navigating
                try:
                    from ..governance.dlp import check_egress_url
                    allowed, reason = check_egress_url(url.strip(), cfg=cfg)
                    if not allowed:
                        return {"ok": False, "action": act, "error": f"egress blocked: {reason}"}
                except Exception:
                    pass

            self.ensure_connected()
            self.action_count += 1

            if act == "navigate":
                self.client.send_command("Page.navigate", {"url": url.strip()})
                self.current_url = url.strip()
                title = str(self._eval("document.title || ''") or "")
                return {
                    "ok": True,
                    "session_id": self.session_id,
                    "action": "navigate",
                    "url": self.current_url,
                    "title": title,
                    "console_errors": list(self.client.console_errors),
                    "exceptions": list(self.client.exceptions),
                    "network_errors": list(self.client.network_errors),
                }

            if act == "click":
                if not selector.strip():
                    return {"ok": False, "action": act, "error": "click requires CSS selector or ARIA ref (e.g. e1 / @e1)"}
                ref_info = self._resolve_aria_ref(selector)
                if ref_info is not None:
                    fn_decl = (
                        "function() { "
                        "if (this.scrollIntoView) this.scrollIntoView({block: 'center'}); "
                        "if (this.click) this.click(); "
                        "return {found: true, ref: " + json.dumps(ref_info["ref"]) + ", tag: this.tagName || '', text: (this.innerText || this.value || '').slice(0, 120)}; }"
                    )
                    r = self._run_on_aria_ref(ref_info, fn_decl)
                else:
                    sel_json = json.dumps(selector.strip())
                    js = (
                        f"(() => {{ const el = document.querySelector({sel_json}); "
                        f"if (!el) return {{found: false}}; "
                        f"if (el.scrollIntoView) el.scrollIntoView({{block: 'center'}}); "
                        f"el.click(); "
                        f"return {{found: true, tag: el.tagName, text: (el.innerText || el.value || '').slice(0, 120)}}; }})()"
                    )
                    r = self._eval(js) or {}
                found = bool(isinstance(r, dict) and r.get("found"))
                return {
                    "ok": found,
                    "session_id": self.session_id,
                    "action": "click",
                    "selector": selector,
                    "element": r if isinstance(r, dict) else {},
                    "error": "" if found else f"element not found for selector: {selector}",
                    "console_errors": list(self.client.console_errors),
                    "exceptions": list(self.client.exceptions),
                }

            if act == "fill":
                if not selector.strip():
                    return {"ok": False, "action": act, "error": "fill requires CSS selector or ARIA ref (e.g. e2 / @e2)"}
                ref_info = self._resolve_aria_ref(selector)
                if ref_info is not None:
                    fn_decl = (
                        "function(val) { "
                        "if (this.focus) this.focus(); "
                        "this.value = val; "
                        "this.dispatchEvent(new Event('input', {bubbles: true})); "
                        "this.dispatchEvent(new Event('change', {bubbles: true})); "
                        "return {found: true, ref: " + json.dumps(ref_info["ref"]) + ", tag: this.tagName || '', length: String(this.value).length}; }"
                    )
                    r = self._run_on_aria_ref(ref_info, fn_decl, [{"value": str(value)}])
                else:
                    sel_json = json.dumps(selector.strip())
                    val_json = json.dumps(str(value))
                    js = (
                        f"(() => {{ const el = document.querySelector({sel_json}); "
                        f"if (!el) return {{found: false}}; "
                        f"el.focus && el.focus(); "
                        f"el.value = {val_json}; "
                        f"el.dispatchEvent(new Event('input', {{bubbles: true}})); "
                        f"el.dispatchEvent(new Event('change', {{bubbles: true}})); "
                        f"return {{found: true, tag: el.tagName, length: String(el.value).length}}; }})()"
                    )
                    r = self._eval(js) or {}
                found = bool(isinstance(r, dict) and r.get("found"))
                return {
                    "ok": found,
                    "session_id": self.session_id,
                    "action": "fill",
                    "selector": selector,
                    "result": r if isinstance(r, dict) else {},
                    "error": "" if found else f"input element not found for selector: {selector}",
                }

            if act == "wait":
                deadline = time.monotonic() + max(0.2, min(float(timeout), 30.0))
                sel = selector.strip()
                expr = expression.strip()
                if not sel and not expr:
                    return {"ok": False, "action": act, "error": "wait requires selector or expression"}
                check_js = f"Boolean(document.querySelector({json.dumps(sel)}))" if sel else f"Boolean({expr})"
                matched = False
                while time.monotonic() < deadline:
                    if bool(self._eval(check_js)):
                        matched = True
                        break
                    time.sleep(0.15)
                return {
                    "ok": matched,
                    "session_id": self.session_id,
                    "action": "wait",
                    "selector": sel,
                    "expression": expr,
                    "matched": matched,
                    "error": "" if matched else f"timed out waiting for {sel or expr}",
                }

            if act == "eval_assert":
                expr = expression.strip()
                if not expr:
                    return {"ok": False, "action": act, "error": "eval_assert requires expression"}
                val = self._eval(expr)
                passed = bool(val)
                return {
                    "ok": passed,
                    "session_id": self.session_id,
                    "action": "eval_assert",
                    "expression": expr,
                    "value": val,
                    "error": "" if passed else f"assertion evaluated falsy: {val!r}",
                }

            if act == "screenshot":
                shot = self.client.send_command("Page.captureScreenshot", {"format": "png"})
                b64 = shot.get("data") or ""
                if not b64:
                    return {"ok": False, "session_id": self.session_id, "action": "screenshot", "error": "empty screenshot data"}
                out_dir = screenshot_dir or Path("persistence/browser_shots")
                out_dir.mkdir(parents=True, exist_ok=True)
                sp = out_dir / f"{self.session_id}_{int(time.time() * 1000)}.png"
                sp.write_bytes(base64.b64decode(b64))
                self.last_screenshot = str(sp)
                return {
                    "ok": True,
                    "session_id": self.session_id,
                    "action": "screenshot",
                    "screenshot_path": str(sp),
                    "bytes": sp.stat().st_size,
                }

            if act == "snapshot":
                snap_js = (
                    "(() => ({"
                    "url: location.href, "
                    "title: document.title || '', "
                    "text: (document.body ? document.body.innerText : '').slice(0, 1200), "
                    "interactive_count: document.querySelectorAll('a,button,input,select,textarea').length"
                    "}))()"
                )
                info = self._eval(snap_js) or {}
                if isinstance(info, dict) and info.get("url"):
                    self.current_url = str(info["url"])
                return {
                    "ok": len(self.client.console_errors) == 0 and len(self.client.exceptions) == 0,
                    "session_id": self.session_id,
                    "action": "snapshot",
                    "page": info if isinstance(info, dict) else {},
                    "console_errors": list(self.client.console_errors),
                    "exceptions": list(self.client.exceptions),
                    "network_errors": list(self.client.network_errors),
                }

            if act == "aria_snapshot":
                nodes_out, tree_text, source = self._capture_aria_tree()
                return {
                    "ok": True,
                    "session_id": self.session_id,
                    "action": "aria_snapshot",
                    "source": source,
                    "node_count": len(nodes_out),
                    "nodes": nodes_out,
                    "tree": tree_text,
                    "console_errors": list(self.client.console_errors),
                    "exceptions": list(self.client.exceptions),
                    "network_errors": list(self.client.network_errors),
                }

            return {
                "ok": False,
                "session_id": self.session_id,
                "action": act,
                "error": f"unsupported browser action '{act}'. Valid: navigate, click, fill, wait, eval_assert, screenshot, snapshot, aria_snapshot, close.",
            }

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "connected": self._connected and self.client._ws is not None,
            "current_url": self.current_url,
            "action_count": self.action_count,
            "console_errors_count": len(self.client.console_errors),
            "exceptions_count": len(self.client.exceptions),
            "network_errors_count": len(self.client.network_errors),
            "last_screenshot": self.last_screenshot,
            "idle_seconds": round(max(0.0, time.monotonic() - self.last_used), 1),
        }

    def close(self) -> None:
        with self._lock:
            self._connected = False
            self.client.close()


class BrowserSessionPool:
    """Process-wide pool of stateful interactive CDP browser sessions."""

    def __init__(self, idle_timeout: float | None = None) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, InteractiveBrowserSession] = {}
        self._idle_timeout = idle_timeout

    def _effective_idle_timeout(self) -> float:
        if self._idle_timeout is not None:
            return self._idle_timeout
        try:
            return max(10.0, float(os.environ.get("BAIZE_BROWSER_IDLE_TIMEOUT", "300") or "300"))
        except ValueError:
            return 300.0

    def evict_idle(self) -> int:
        now = time.monotonic()
        limit = self._effective_idle_timeout()
        evicted = 0
        with self._lock:
            for sid in list(self._sessions.keys()):
                sess = self._sessions[sid]
                if now - sess.last_used > limit:
                    self._sessions.pop(sid, None)
                    sess.close()
                    evicted += 1
        return evicted

    def run_action(
        self,
        action: str,
        *,
        session_id: str = "default",
        url: str = "",
        selector: str = "",
        value: str = "",
        expression: str = "",
        timeout: float = 10.0,
        ws_url: str = "",
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch an interactive browser E2E action against a pooled session."""
        self.evict_idle()
        sid = (session_id or "default").strip() or "default"
        act = (action or "").strip().lower()
        if act == "close":
            with self._lock:
                sess = self._sessions.pop(sid, None)
            if sess is not None:
                sess.close()
            return {"ok": True, "session_id": sid, "action": "close", "closed": True}

        from ..core.config import load_config
        eff_cfg = cfg if cfg is not None else load_config()
        bin_override = str(eff_cfg.get("BAIZE_CDP_BINARY", "") or "")
        cdp_timeout = float(eff_cfg.get("BAIZE_CDP_TIMEOUT", "15") or 15)
        shot_dir = Path(eff_cfg.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "browser_shots"

        with self._lock:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = InteractiveBrowserSession(
                    sid,
                    ws_url=ws_url,
                    browser_binary=bin_override,
                    timeout=cdp_timeout,
                )
                self._sessions[sid] = sess

        try:
            return sess.execute(
                act,
                url=url,
                selector=selector,
                value=value,
                expression=expression,
                timeout=timeout,
                screenshot_dir=shot_dir,
                cfg=eff_cfg,
            )
        except CDPUnavailableError as exc:
            with self._lock:
                self._sessions.pop(sid, None)
            sess.close()
            return {
                "ok": False,
                "degraded": True,
                "session_id": sid,
                "action": act,
                "error": str(exc),
            }
        except Exception as exc:
            return {
                "ok": False,
                "session_id": sid,
                "action": act,
                "error": str(exc),
            }

    def status(self) -> dict[str, Any]:
        self.evict_idle()
        with self._lock:
            sessions = [s.status() for s in self._sessions.values()]
        return {
            "active_count": len(sessions),
            "idle_timeout_s": self._effective_idle_timeout(),
            "browser_binary_found": bool(find_browser_binary()),
            "sessions": sessions,
        }

    def close_all(self) -> int:
        with self._lock:
            items = list(self._sessions.values())
            self._sessions.clear()
        for sess in items:
            try:
                sess.close()
            except Exception:
                pass
        return len(items)


_BROWSER_POOL_LOCK = threading.Lock()
_GLOBAL_BROWSER_POOL: BrowserSessionPool | None = None


def get_browser_pool() -> BrowserSessionPool:
    """Return the singleton :class:`BrowserSessionPool`."""
    global _GLOBAL_BROWSER_POOL
    with _BROWSER_POOL_LOCK:
        if _GLOBAL_BROWSER_POOL is None:
            _GLOBAL_BROWSER_POOL = BrowserSessionPool()
        return _GLOBAL_BROWSER_POOL
