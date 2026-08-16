"""Exhaustive config_schema.validate() coverage (V22 #95 review fix #3).

config_schema now validates every BAIZE_* kind including the new
BAIZE_COMPONENTS (structural) and BAIZE_MODE (enum) keys. These tests exercise
each validation branch - valid pass and each error path - so the fail-fast
schema is real, not cosmetic.
"""
from __future__ import annotations

import pytest

from baize.config import load_config
from baize.config_schema import ConfigError, validate


def _base():
    return load_config()


def test_defaults_validate():
    # Every SCHEMA key present + valid (defaults must be a valid config).
    assert validate(_base()) is not None


def test_int_range_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_AGENT_MAX_STEPS"] = "24"
    assert validate(cfg)
    cfg["BAIZE_AGENT_MAX_STEPS"] = "999999"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_float_range_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_CHAOS_FAILURE_RATE"] = "0.5"
    assert validate(cfg)
    cfg["BAIZE_CHAOS_FAILURE_RATE"] = "5.0"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_bool_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_CHAOS_ENABLED"] = "1"
    assert validate(cfg)
    cfg["BAIZE_CHAOS_ENABLED"] = "maybe"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_enum_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_VECTOR_BACKEND"] = "tfidf"
    assert validate(cfg)
    cfg["BAIZE_VECTOR_BACKEND"] = "bogus"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_json_or_empty_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_MODEL_ROUTER"] = ""  # empty allowed
    assert validate(cfg)
    cfg["BAIZE_MODEL_ROUTER"] = '[{"name":"x"}]'
    assert validate(cfg)
    cfg["BAIZE_MODEL_ROUTER"] = "{not json"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_path_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_PERSISTENCE_DIR"] = "/tmp/x"
    assert validate(cfg)
    cfg["BAIZE_PERSISTENCE_DIR"] = ""
    with pytest.raises(ConfigError):
        validate(cfg)


def test_components_format_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_COMPONENTS"] = "sandbox"           # builtin ref ok
    assert validate(cfg)
    cfg["BAIZE_COMPONENTS"] = "a.b:Cls,tool"      # valid module:Class
    assert validate(cfg)
    cfg["BAIZE_COMPONENTS"] = "not a token!!"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_mode_pass_and_fail():
    cfg = _base()
    cfg["BAIZE_MODE"] = "coding"
    assert validate(cfg)
    cfg["BAIZE_MODE"] = "bogus"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_missing_key_fails():
    cfg = _base()
    del cfg["BAIZE_PERSISTENCE_DIR"]  # a required SCHEMA key
    with pytest.raises(ConfigError):
        validate(cfg)
