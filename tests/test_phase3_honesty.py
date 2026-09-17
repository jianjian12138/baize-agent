"""The Phase 3 "industrial" cluster advertised evidence it never produced.

``baize/byzantine.py`` returned two literal ``APPROVE`` verdicts, so every input
reached consensus, and its ``bft_signature`` was ``sha256(goal + votes +
time.time())`` - a timestamp hash that changed on every call and was verified by
nothing. ``baize/tool_market.py`` stamped ``verified_gate: True`` and
``downloads: 12`` on every record while running no gate and counting nothing.

Both were headline README claims ("3 节点拜占庭博弈全票加密签名",
"已通过物理门禁认证"). These tests pin the honest behaviour so the literals
cannot come back, and check that the numbers which *are* reported are functions
of the inputs rather than of the clock.
"""
from __future__ import annotations

import pytest

from baize import byzantine, tool_market
from baize.byzantine import run_byzantine_consensus
from baize.tool_market import (
    clear_published_tools,
    list_market_tools,
    publish_market_tool,
)

VERDICTS_2_APPROVE = [{"vote": "APPROVE"}, {"vote": "APPROVE"}]


@pytest.fixture(autouse=True)
def _isolate_market():
    """The registry is process-global, so publications must not leak between
    tests. The previous revision appended straight to the served list."""
    clear_published_tools()
    yield
    clear_published_tools()


class TestByzantineDoesNotInventVerdicts:
    def test_no_verdicts_means_no_verdict(self):
        res = run_byzantine_consensus("def f(): pass", "goal")
        assert res["status"] == "awaiting_verdicts"
        assert res["consensus_reached"] is None
        assert res["approvals"] is None
        assert res["nodes"] == []
        assert res["digest"] is None
        assert res["arbiter_decision"] is None

    def test_an_empty_verdict_list_is_treated_as_no_verdicts(self):
        assert run_byzantine_consensus("", "g", verdicts=[])["status"] == "awaiting_verdicts"

    def test_it_never_returns_a_field_called_bft_signature(self):
        for res in (
            run_byzantine_consensus("", "g"),
            run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE),
        ):
            assert "bft_signature" not in res
            assert res["signed"] is False
            assert "not a signature" in res["digest_kind"]

    def test_the_digest_is_reproducible_and_not_a_clock_value(self):
        first = run_byzantine_consensus("code", "goal", verdicts=VERDICTS_2_APPROVE)
        second = run_byzantine_consensus("code", "goal", verdicts=VERDICTS_2_APPROVE)
        assert first["digest"] == second["digest"]
        assert first["digest"].startswith("BFT-DIGEST-")

    @pytest.mark.parametrize(
        "code, goal, verdicts",
        [
            ("code", "other goal", VERDICTS_2_APPROVE),
            ("other code", "goal", VERDICTS_2_APPROVE),
            ("code", "goal", [{"vote": "APPROVE"}, {"vote": "REJECT"}]),
        ],
    )
    def test_the_digest_changes_when_the_inputs_change(self, code, goal, verdicts):
        base = run_byzantine_consensus("code", "goal", verdicts=VERDICTS_2_APPROVE)
        other = run_byzantine_consensus(code, goal, verdicts=verdicts)
        assert base["digest"] != other["digest"]

    def test_the_quorum_is_actually_applied(self):
        one = run_byzantine_consensus("", "g", verdicts=[{"vote": "APPROVE"}, {"vote": "REJECT"}])
        assert one["approvals"] == 1
        assert one["consensus_reached"] is False
        two = run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE)
        assert two["approvals"] == 2
        assert two["consensus_reached"] is True
        # A caller can raise the bar, and then two approvals are not enough.
        strict = run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE, quorum=3)
        assert strict["consensus_reached"] is False
        assert strict["quorum_required"] == 3

    def test_votes_are_normalised_but_not_rounded_up(self):
        res = run_byzantine_consensus(
            "", "g", verdicts=[{"vote": " approve "}, {"vote": "abstain"}, {}]
        )
        assert res["approvals"] == 1
        assert res["verdicts_supplied"] == 3

    def test_the_target_code_is_measured_rather_than_ignored(self):
        res = run_byzantine_consensus("a\nb\nc", "g", verdicts=VERDICTS_2_APPROVE)
        facts = res["target_code_facts"]
        assert facts["chars"] == 5
        assert facts["lines"] == 3
        assert len(facts["sha256_prefix"]) == 16
        # The honest part: the code was received, not read.
        assert facts["analysed"] is False
        empty = run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE)
        assert empty["target_code_facts"]["lines"] == 0

    def test_the_reported_duration_is_a_real_non_negative_number(self):
        res = run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE)
        assert isinstance(res["arbitration_time_ms"], float)
        assert res["arbitration_time_ms"] >= 0


class TestTheMarketplaceDoesNotClaimVerification:
    def test_publishing_claims_no_gate_and_no_downloads(self):
        res = publish_market_tool({"name": "t", "code": "def run(): pass"})
        tool = res["tool"]
        assert tool["verified_gate"] is None
        assert tool["downloads"] is None
        assert tool["mounted"] is False
        assert tool["fitness_score_measured"] is False
        assert res["persisted"] is False
        assert "未做任何校验" in res["message"]
        assert "已通过物理门禁认证" not in res["message"]

    def test_the_hash_is_a_content_digest_not_a_nonce(self):
        a = publish_market_tool({"name": "t", "generation_id": 3, "code": "def run(): pass"})
        b = publish_market_tool({"name": "t", "generation_id": 3, "code": "def run(): pass"})
        assert a["tool"]["darwin_hash"] == b["tool"]["darwin_hash"]
        c = publish_market_tool({"name": "t", "generation_id": 4, "code": "def run(): pass"})
        assert a["tool"]["darwin_hash"] != c["tool"]["darwin_hash"]
        assert "not a signature" in a["tool"]["digest_kind"]

    def test_publishing_does_not_mutate_the_curated_seed(self):
        before = [t["name"] for t in list_market_tools()]
        publish_market_tool({"name": "leaky", "code": "def run(): pass"})
        after = [t["name"] for t in list_market_tools()]
        assert after[:len(before)] == before
        assert after[len(before):] == ["leaky"]

    def test_clear_published_tools_restores_the_seed_and_reports_the_count(self):
        publish_market_tool({"name": "one", "code": "def run(): pass"})
        publish_market_tool({"name": "two", "code": "def run(): pass"})
        assert clear_published_tools() == 2
        assert len(list_market_tools()) == 3
        assert clear_published_tools() == 0

    def test_every_published_tool_gets_a_distinct_id(self):
        ids = {
            publish_market_tool({"name": f"t{i}", "code": "def run(): pass"})["tool"]["tool_id"]
            for i in range(5)
        }
        assert len(ids) == 5
        assert all(tool_id.startswith("dt-") for tool_id in ids)


def test_the_documented_digest_kind_matches_what_is_returned():
    """The constants exist so the disclosure cannot drift from the payload."""
    res = publish_market_tool({"name": "t", "code": "def run(): pass"})
    assert res["tool"]["digest_kind"] == tool_market.DIGEST_KIND
    assert res["tool"]["gate_note"] == tool_market.GATE_NOTE
    assert res["tool"]["downloads_note"] == tool_market.DOWNLOADS_NOTE
    byz = run_byzantine_consensus("", "g", verdicts=VERDICTS_2_APPROVE)
    assert byz["digest_kind"] == byzantine.DIGEST_KIND
