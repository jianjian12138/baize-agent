"""Unit tests for Natural Language Cron parsing in automations."""
import pytest
from baize.automations import parse_nl_schedule


def test_parse_nl_schedule_intervals():
    assert parse_nl_schedule("每30分钟") == "cron: */30 * * * *"
    assert parse_nl_schedule("every 15 mins") == "cron: */15 * * * *"
    assert parse_nl_schedule("每2小时") == "cron: 0 */2 * * *"
    assert parse_nl_schedule("每10秒") == "interval:10"


def test_parse_nl_schedule_routines():
    assert parse_nl_schedule("每天早上8点") == "cron: 0 8 * * *"
    assert parse_nl_schedule("8am daily") == "cron: 0 8 * * *"
    assert parse_nl_schedule("每天晚上9点") == "cron: 0 21 * * *"
    assert parse_nl_schedule("工作日") == "cron: 0 9 * * 1-5"
    assert parse_nl_schedule("每周") == "cron: 0 9 * * 1"
    assert parse_nl_schedule("每月") == "cron: 0 9 1 * *"
    assert parse_nl_schedule("每小时") == "cron: 0 * * * *"


def test_parse_nl_schedule_passthrough():
    # standard cron / interval string passes through untouched
    assert parse_nl_schedule("cron: 0 0 * * *") == "cron: 0 0 * * *"
    assert parse_nl_schedule("interval:60") == "interval:60"
    assert parse_nl_schedule("0 12 * * *") == "cron: 0 12 * * *"
