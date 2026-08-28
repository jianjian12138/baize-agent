"""Tests for V30 Red-Blue Adversarial Hegemony & Byzantine Judge."""
import pytest
from baize.orchestration.adversarial import (
    BattleRound, ByzantineJudge, AdversarialHegemony
)


def test_byzantine_judge_evaluates_breach():
    """If red attack triggers a failure in blue code, judge records a red breach."""
    judge = ByzantineJudge()
    round_result = judge.arbitrate(
        round_number=1,
        blue_code="def divide(a, b): return a / b",
        red_attack_input={"a": 10, "b": 0},
        expected_behavior="prevent ZeroDivisionError"
    )
    assert round_result.verdict == "red_breach"
    assert round_result.attack_succeeded is True


def test_byzantine_judge_evaluates_pass():
    """If blue code withstands adversarial attack, judge records a blue pass."""
    judge = ByzantineJudge()
    round_result = judge.arbitrate(
        round_number=1,
        blue_code="def divide(a, b): return a / b if b != 0 else 0",
        red_attack_input={"a": 10, "b": 0},
        expected_behavior="prevent ZeroDivisionError"
    )
    assert round_result.verdict == "blue_pass"
    assert round_result.attack_succeeded is False


def test_adversarial_hegemony_certification():
    """Hegemony certifies when Blue withstands 3 consecutive red attacks."""
    hegemony = AdversarialHegemony(required_defense_rounds=3)
    rounds = [
        BattleRound(1, "code", "attack1", attack_succeeded=False, verdict="blue_pass"),
        BattleRound(2, "code", "attack2", attack_succeeded=False, verdict="blue_pass"),
        BattleRound(3, "code", "attack3", attack_succeeded=False, verdict="blue_pass"),
    ]
    assert hegemony.is_battle_hardened(rounds) is True
