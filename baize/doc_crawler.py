"""Zero-Dependency Online Documentation Crawler & @docs RAG Indexer (V37.0.0 Prometheus).

Pure Python standard library — zero third-party dependencies (urllib.request + html.parser).
Inspired by Cursor's @docs feature:
1. Fetches HTML from technical documentation URLs (e.g. FastAPI, Pydantic, React, PyTorch).
2. Strips navigation bars, footers, scripts, and styles.
3. Converts clean semantic content into Markdown chunks and indexes into Baize's Hybrid RAG.
"""
from __future__ import annotations

import html.parser
import re
import urllib.request
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "DocHTMLToMarkdownParser",
    "fetch_and_parse_doc_url",
    "DocCrawlerRegistry",
]


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
        elif tag in ("pre",):
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
        if self.ignore_stack and self.ignore_stack[-1] == tag:
            self.ignore_stack.pop()
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
        # Normalize multiple newlines
        clean = re.sub(r'\n{3,}', '\n\n', raw).strip()
        return clean


def fetch_and_parse_doc_url(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch documentation web page and return clean Markdown chunks."""
    # Basic URL validation
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {"success": False, "error": "Invalid URL format (must include http:// or https://)"}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BaizeAgent/37.0.0 (@docs crawler)"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                return {"success": False, "error": f"Unsupported content type: {content_type}"}
            raw_bytes = response.read()
            html_text = raw_bytes.decode("utf-8", errors="replace")

        parser = DocHTMLToMarkdownParser()
        parser.feed(html_text)
        md_content = parser.get_markdown()
        title = parser.page_title or parsed.netloc

        # Split into semantic chunks
        chunks = [c.strip() for c in md_content.split("\n\n") if len(c.strip()) > 30]

        return {
            "success": True,
            "url": url,
            "title": title,
            "markdown": md_content[:15000],  # first 15k chars
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
    """In-memory cache of scraped external documentation."""
    _DOCS: dict[str, dict[str, Any]] = {}

    @classmethod
    def index_url(cls, url: str) -> dict[str, Any]:
        res = fetch_and_parse_doc_url(url)
        if res.get("success"):
            cls._DOCS[url] = res
        return res

    @classmethod
    def list_indexed_docs(cls) -> list[dict[str, Any]]:
        return [
            {"url": url, "title": data.get("title", url), "chunks_count": data.get("total_chunks", 0)}
            for url, data in cls._DOCS.items()
        ]
