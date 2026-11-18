"""Zero-Dependency Online Documentation Crawler & @docs RAG Indexer (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies (urllib.request + html.parser).
Inspired by Cursor's @docs feature:
1. Validates URL scheme (http/https only) and resolves hostnames against private/loopback SSRF ranges.
2. Fetches HTML with bounded size cap and strips navigation bars, footers, scripts, and styles.
3. Converts semantic content into Markdown chunks, persists them to disk, and supports TF-IDF search.
"""
from __future__ import annotations

import html.parser
import ipaddress
import json
import re
import socket
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import ROOT, load_config
from .vector import TfidfIndex

__all__ = [
    "DocHTMLToMarkdownParser",
    "fetch_and_parse_doc_url",
    "DocCrawlerRegistry",
    "validate_public_http_url",
]

MAX_DOC_BYTES = 1_500_000


def _is_disallowed_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(url: str) -> tuple[bool, str]:
    """Validate that ``url`` is an HTTP(S) URL not targeting local/private networks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid URL scheme {parsed.scheme!r} (only http:// and https:// are permitted)"
    host = parsed.hostname
    if not host:
        return False, "Invalid URL format (missing hostname)"
    if host.lower() in ("localhost", "localhost.localdomain") or host.lower().endswith(".local"):
        return False, f"Blocked local hostname: {host}"
    # Literal IP check
    try:
        if _is_disallowed_ip(host):
            return False, f"Blocked non-public IP address: {host}"
        return True, ""
    except ValueError:
        pass
    # DNS resolution check against private/loopback/metadata IPs
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Allow network layer to report DNS error if offline, unless literal local
        return True, ""
    for info in infos:
        addr = info[4][0].split("%")[0]
        if _is_disallowed_ip(addr):
            return False, f"Blocked SSRF target IP ({addr}) for host {host}"
    return True, ""


class _NoPrivateRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, reason = validate_public_http_url(newurl)
        if not ok:
            raise ValueError(f"redirect blocked: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DocHTMLToMarkdownParser(html.parser.HTMLParser):
    """Parses technical documentation HTML and outputs clean Markdown text."""

    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self.ignore_stack: list[str] = []
        self.in_pre = False
        self.in_code = False
        self.page_title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        if tag in ("script", "style", "nav", "footer", "header", "noscript", "svg", "button", "aside"):
            self.ignore_stack.append(tag)
            return

        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.text_parts.append(f"\n\n{'#' * level} ")
        elif tag == "p":
            self.text_parts.append("\n\n")
        elif tag == "pre":
            self.in_pre = True
            self.text_parts.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.in_code = True
            self.text_parts.append(" `")
        elif tag == "li":
            self.text_parts.append("\n- ")
        elif tag == "br":
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self.ignore_stack:
            # Unwind back to matching tag so malformed/unclosed inner tags
            # cannot swallow the rest of the document.
            while self.ignore_stack:
                popped = self.ignore_stack.pop()
                if popped == tag:
                    break
            return

        if tag == "title":
            self._in_title = False
        elif tag == "pre":
            self.in_pre = False
            self.text_parts.append("\n```\n")
        elif tag == "code" and self.in_code:
            self.in_code = False
            self.text_parts.append("` ")

    def handle_data(self, data: str):
        if self.ignore_stack:
            return
        if self._in_title:
            self.page_title += data.strip()
            return
        cleaned = data if self.in_pre else " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned + " ")

    def get_markdown(self) -> str:
        raw = "".join(self.text_parts)
        clean = re.sub(r"\n{3,}", "\n\n", raw).strip()
        return clean


def fetch_and_parse_doc_url(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch documentation web page safely and return clean Markdown chunks."""
    ok, reason = validate_public_http_url(url)
    if not ok:
        return {"success": False, "url": url, "error": reason}

    parsed = urlparse(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BaizeAgent/39.0.0 (@docs crawler)"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(_NoPrivateRedirectHandler)
        with opener.open(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower() and "text" not in content_type.lower():
                return {"success": False, "error": f"Unsupported content type: {content_type}"}
            raw_bytes = response.read(MAX_DOC_BYTES)
            html_text = raw_bytes.decode("utf-8", errors="replace")

        parser = DocHTMLToMarkdownParser()
        parser.feed(html_text)
        md_content = parser.get_markdown()
        title = parser.page_title or parsed.netloc

        chunks = [c.strip() for c in md_content.split("\n\n") if len(c.strip()) > 30]

        return {
            "success": True,
            "url": url,
            "title": title,
            "markdown": md_content[:15000],
            "total_chunks": len(chunks),
            "chunks": chunks[:25],
            "message": f"成功抓取并解析文档 [{title}]，提取出 {len(chunks)} 个语义知识切片！"
        }
    except Exception as exc:
        return {
            "success": False,
            "url": url,
            "error": f"抓取在线文档失败: {exc}"
        }


class DocCrawlerRegistry:
    """Persistent + in-memory cache of scraped external documentation with TF-IDF search."""

    _DOCS: dict[str, dict[str, Any]] = {}

    @classmethod
    def _store_path(cls, cfg: dict | None = None) -> Path:
        cfg = cfg or load_config()
        p = Path(cfg.get("BAIZE_PERSISTENCE_DIR", str(ROOT / "persistence")))
        p.mkdir(parents=True, exist_ok=True)
        return p / "docs_index.json"

    @classmethod
    def _load_persisted(cls, cfg: dict | None = None) -> None:
        if cls._DOCS:
            return
        sp = cls._store_path(cfg)
        if sp.exists():
            try:
                data = json.loads(sp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cls._DOCS.update(data)
            except Exception:
                pass

    @classmethod
    def _save_persisted(cls, cfg: dict | None = None) -> None:
        try:
            sp = cls._store_path(cfg)
            sp.write_text(json.dumps(cls._DOCS, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def index_url(cls, url: str, cfg: dict | None = None) -> dict[str, Any]:
        cls._load_persisted(cfg)
        res = fetch_and_parse_doc_url(url)
        if res.get("success"):
            cls._DOCS[url] = res
            cls._save_persisted(cfg)
        return res

    @classmethod
    def list_indexed_docs(cls, cfg: dict | None = None) -> list[dict[str, Any]]:
        cls._load_persisted(cfg)
        return [
            {"url": url, "title": data.get("title", url), "chunks_count": data.get("total_chunks", 0)}
            for url, data in cls._DOCS.items()
        ]

    @classmethod
    def search(cls, query: str, top_k: int = 5, cfg: dict | None = None) -> list[dict[str, Any]]:
        cls._load_persisted(cfg)
        idx = TfidfIndex()
        for url, data in cls._DOCS.items():
            title = data.get("title", url)
            for i, chunk in enumerate(data.get("chunks", [])):
                idx.add(f"{url}#{i}", chunk, {"url": url, "title": title, "text": chunk})
        if len(idx) == 0:
            return []
        return idx.search(query, top_k=top_k, method="bm25")
