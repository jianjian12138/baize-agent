"""In-process registry of self-synthesized meta-tools.

Pure Python standard library — zero third-party dependencies.

WHAT THIS IS
------------
A dict-shaped registry. ``list_market_tools`` returns three curated entries plus
anything published in this process; ``publish_market_tool`` appends to that list
and returns the stored record. ``darwin_hash`` is a sha256 **content digest** of
``name:code:generation_id``, so the same tool always hashes the same way.

WHAT THIS IS NOT
----------------
The module docstring used to promise that agents could "publish, share, verify,
and dynamically mount" tools "with cryptographic genetic signatures". None of the
last three happened:

  * nothing verifies a published tool, yet every record carried
    ``verified_gate: True`` and the response said "已通过物理门禁认证" (passed
    physical gate certification);
  * ``downloads`` was the literal ``12`` on every record, including a tool
    published one line earlier, because nothing counts downloads;
  * nothing mounts or executes the tool's ``code`` - it is stored as text;
  * a sha256 of the content is a digest, not a signature: there is no key and
    nothing checks it. ``digest_kind`` in the response says so;
  * the registry lives in this process only. A publication is gone when the
    process exits, which ``persisted: False`` states rather than leaves implied.

``fitness_score`` is whatever the publisher claimed. Nothing here measures it.
"""
from __future__ import annotations

import hashlib
from typing import Any

__all__ = [
    "MarketTool",
    "clear_published_tools",
    "list_market_tools",
    "publish_market_tool",
]

#: What ``darwin_hash`` actually is. Returned in every record so a caller cannot
#: read the prefix as proof of authenticity.
DIGEST_KIND = (
    "sha256 over name:code:generation_id; a reproducible content digest, not a "
    "signature - there is no key and nothing verifies it"
)

#: Why ``verified_gate`` is ``None`` rather than ``False``: no check runs, so
#: neither answer would be true. ``False`` would imply a gate ran and rejected.
GATE_NOTE = (
    "no gate is run on publish - nothing parses, imports or executes the tool's "
    "code, so there is no verification result to report"
)

#: Why ``downloads`` is ``None``: the registry keeps no download accounting.
DOWNLOADS_NOTE = "not tracked - this registry counts nothing"


class MarketTool:
    def __init__(
        self,
        tool_id: str,
        name: str,
        category: str,
        description: str,
        author_agent: str,
        fitness_score: float,
        generation_id: int,
        code: str,
        darwin_hash: str = "",
    ):
        self.tool_id = tool_id
        self.name = name
        self.category = category
        self.description = description
        self.author_agent = author_agent
        #: Claimed by the publisher. Nothing in this module measures it.
        self.fitness_score = fitness_score
        self.generation_id = generation_id
        self.code = code
        self.darwin_hash = darwin_hash or self._compute_hash()
        #: None, not True: see GATE_NOTE.
        self.verified_gate: bool | None = None
        #: None, not 12: see DOWNLOADS_NOTE.
        self.downloads: int | None = None

    def _compute_hash(self) -> str:
        h = hashlib.sha256(
            f"{self.name}:{self.code}:{self.generation_id}".encode("utf-8")
        ).hexdigest()
        return f"DARWIN-{h[:10].upper()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "author_agent": self.author_agent,
            "fitness_score": self.fitness_score,
            "fitness_score_measured": False,
            "generation_id": self.generation_id,
            "darwin_hash": self.darwin_hash,
            "digest_kind": DIGEST_KIND,
            "verified_gate": self.verified_gate,
            "gate_note": GATE_NOTE,
            "downloads": self.downloads,
            "downloads_note": DOWNLOADS_NOTE,
            "mounted": False,
            "code": self.code,
        }


#: Curated seed entries. Their ``code`` is illustrative text that nothing runs,
#: and their ``fitness_score`` is a claimed number, not a measurement.
_CURATED_MARKETPLACE: tuple[MarketTool, ...] = (
    MarketTool(
        tool_id="dt-01",
        name="k8s_manifest_validator",
        category="DevOps & SRE",
        description="自主合成的 Kubernetes YAML 规范与资源配额深度校验器",
        author_agent="Baize-Darwin-Gen3",
        fitness_score=0.98,
        generation_id=3,
        code="def validate_k8s_yaml(content: str) -> bool:\n    # Auto-synthesized logic\n    return 'apiVersion' in content and 'kind' in content",
    ),
    MarketTool(
        tool_id="dt-02",
        name="ast_sql_injection_guard",
        category="Security & Audit",
        description="基于 AST 语法树特征的 SQL 拼接与注入物理扫描器",
        author_agent="Baize-Darwin-Gen5",
        fitness_score=0.99,
        generation_id=5,
        code="def scan_sql_injection(ast_node) -> list[str]:\n    # AST pattern detection\n    return []",
    ),
    MarketTool(
        tool_id="dt-03",
        name="graphql_schema_differ",
        category="API & Architecture",
        description="GraphQL Schema 破坏性变更与字段废弃影响面精准分析器",
        author_agent="Baize-Darwin-Gen4",
        fitness_score=0.96,
        generation_id=4,
        code="def diff_graphql(old_s: str, new_s: str) -> dict:\n    return {'breaking_changes': 0}",
    ),
)

#: Tools published in this process. Separate from the curated tuple so publishing
#: cannot mutate the seed data - the previous revision appended to the same list
#: it served from, so a publication in one test was visible to the next.
_PUBLISHED_TOOLS: list[MarketTool] = []


def clear_published_tools() -> int:
    """Drop everything published in this process. Returns how many were removed."""
    removed = len(_PUBLISHED_TOOLS)
    _PUBLISHED_TOOLS.clear()
    return removed


def list_market_tools() -> list[dict[str, Any]]:
    """Return the curated entries followed by anything published this process."""
    return [t.to_dict() for t in (*_CURATED_MARKETPLACE, *_PUBLISHED_TOOLS)]


def publish_market_tool(data: dict[str, Any]) -> dict[str, Any]:
    """Store a tool record. Nothing is verified, mounted or persisted."""
    name = data.get("name", "custom_synthesized_tool")
    category = data.get("category", "Custom")
    description = data.get("description", "Agent 自主繁衍合成的新工具")
    author = data.get("author", "Baize-Agent-Worker")
    code = data.get("code", "def execute(): pass")
    gen_id = int(data.get("generation_id", 1))
    fitness = float(data.get("fitness_score", 0.95))

    new_tool = MarketTool(
        tool_id=f"dt-{len(_CURATED_MARKETPLACE) + len(_PUBLISHED_TOOLS) + 1:02d}",
        name=name,
        category=category,
        description=description,
        author_agent=author,
        fitness_score=fitness,
        generation_id=gen_id,
        code=code,
    )
    _PUBLISHED_TOOLS.append(new_tool)
    return {
        "status": "published",
        "tool": new_tool.to_dict(),
        "persisted": False,
        "persistence_note": (
            "stored in this process only - the registry is an in-memory list and "
            "nothing writes it to disk"
        ),
        "message": (
            f"元工具 [{name}] 已写入本进程内存注册表，内容摘要 {new_tool.darwin_hash}。"
            "未做任何校验、未挂载、未持久化——本模块只存储记录。"
        ),
    }
