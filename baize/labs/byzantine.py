"""Quorum arbitration over caller-supplied review verdicts.

Pure Python standard library — zero third-party dependencies.

WHAT THIS IS
------------
A vote counter with a configurable quorum, plus a reproducible content digest of
the inputs. Feed it verdicts, it tells you whether the approvals clear the quorum
and hands back a digest you can compare against a later run.

WHAT THIS IS NOT
----------------
It is not a Byzantine Fault Tolerant protocol and it does not run any agent. The
name and the field names in the response are kept for API compatibility, but the
module docstring used to describe things that were not happening:

  * "Coordinates 3 independent agent nodes (Red Team Attacker, Blue Team Defender,
    Arbiter Judge)" - there were **two** verdict dictionaries, both literals
    defined in this file. The third "node" was the vote-counting code.
  * ``vulnerabilities_found: 0``, ``fuzzing_rounds: 50``,
    ``confinement_check: "PASS"`` and ``invariants_satisfied: 6`` were typed into
    the file. No fuzzer ran, no sandbox was inspected, no invariant was counted.
  * ``target_code`` was accepted and then never read - the function took the code
    under review and ignored it.
  * ``bft_signature`` was ``sha256(goal + votes + time.time())``: a hash of the
    current time. It changed on every call, so it was not even a content digest,
    let alone a signature - there is no key and nothing verifies it.

Now: no verdict in, no verdict out. Call without ``verdicts`` and the response
says ``awaiting_verdicts`` instead of inventing an approval. Call with verdicts
and the quorum, the counts and the digest are all computed from what you passed.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

__all__ = [
    "DEFAULT_QUORUM",
    "run_byzantine_consensus",
]

#: Approvals required for the quorum to be met, out of the verdicts supplied.
DEFAULT_QUORUM = 2

#: Stated in every response so a caller cannot read the digest as a signature.
DIGEST_KIND = (
    "sha256 over goal + target digest + votes; reproducible and unkeyed, so it is "
    "a content digest, not a signature"
)


def _code_facts(target_code: str) -> dict[str, Any]:
    """Facts about the submitted code that were actually measured.

    Deliberately limited to what can be observed without parsing or executing it:
    this module has no analyser. ``analysed: False`` is the honest answer to "did
    you look at it", and it is stated rather than left to inference.
    """
    return {
        "chars": len(target_code),
        "lines": target_code.count("\n") + (1 if target_code else 0),
        "sha256_prefix": hashlib.sha256(target_code.encode("utf-8")).hexdigest()[:16],
        "analysed": False,
    }


def run_byzantine_consensus(
    target_code: str = "",
    goal: str = "核心支付/状态机发布评审",
    verdicts: list[dict[str, Any]] | None = None,
    quorum: int = DEFAULT_QUORUM,
) -> dict[str, Any]:
    """Count approvals over ``verdicts`` and apply ``quorum``.

    Returns ``status="awaiting_verdicts"`` and no verdict when ``verdicts`` is
    empty or missing. It never fabricates a vote: the previous revision returned
    two literal ``APPROVE``s, which made ``consensus_reached`` true for every
    input including the empty string.
    """
    start = time.perf_counter()
    code_facts = _code_facts(target_code or "")

    if not verdicts:
        return {
            "status": "awaiting_verdicts",
            "goal": goal,
            "target_code_facts": code_facts,
            "verdicts_supplied": 0,
            "quorum_required": quorum,
            "approvals": None,
            "consensus_reached": None,
            "consensus_type": (
                f"rule-based quorum (approvals >= {quorum} of the verdicts supplied)"
            ),
            "digest": None,
            "digest_kind": DIGEST_KIND,
            "signed": False,
            "nodes": [],
            "arbiter_decision": None,
            "arbitration_time_ms": round((time.perf_counter() - start) * 1000, 2),
            "message": (
                "没有收到任何评审意见，因此没有可仲裁的共识。本函数只做票数统计，"
                "不启动任何 Agent、不分析代码、不做任何签名。"
                "（旧版本会在此处返回两条硬编码 APPROVE 与一个时间戳哈希，"
                "并把它标成 BFT-SIG-。）"
            ),
        }

    votes = [str(item.get("vote", "")).strip().upper() for item in verdicts]
    approvals = votes.count("APPROVE")
    reached = approvals >= quorum

    payload = json.dumps(
        {"goal": goal, "target": code_facts["sha256_prefix"], "votes": votes},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    digest = "BFT-DIGEST-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()

    return {
        "status": "success",
        "goal": goal,
        "target_code_facts": code_facts,
        "verdicts_supplied": len(verdicts),
        "quorum_required": quorum,
        "approvals": approvals,
        "consensus_reached": reached,
        "consensus_type": (
            f"rule-based quorum: {approvals} approval(s) >= {quorum} required, "
            f"over {len(verdicts)} supplied verdict(s)"
        ),
        "digest": digest,
        "digest_kind": DIGEST_KIND,
        "signed": False,
        "nodes": verdicts,
        "arbiter_decision": (
            f"quorum met ({approvals}/{len(verdicts)})" if reached
            else f"quorum not met ({approvals}/{len(verdicts)})"
        ),
        "arbitration_time_ms": round((time.perf_counter() - start) * 1000, 2),
        "message": (
            f"对 {len(verdicts)} 条评审意见完成票数统计：赞成 {approvals} 条，"
            f"门槛 {quorum} 条，{'达到' if reached else '未达到'}。"
            f"内容摘要 {digest}（可复现，非签名）。"
        ),
    }
