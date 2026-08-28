"""Test modular subpackages and top-level re-exports for backward compatibility."""
import pytest


def test_core_subpackage_imports():
    from baize.core import (
        Agent, LLMClient, load_config, Session, AutonomyPolicy,
        resolve_mode, CompositionKernel, obs
    )
    assert Agent is not None
    assert LLMClient is not None
    assert callable(load_config)


def test_orchestration_subpackage_imports():
    from baize.orchestration import (
        Orchestrator, ProjectContract, AtomicTask, RunLedger, Role, TeamConfig
    )
    assert Orchestrator is not None
    assert ProjectContract is not None
    assert RunLedger is not None


def test_tooling_subpackage_imports():
    from baize.tooling import ToolRegistry, default_registry, run_sandboxed, build_index
    assert ToolRegistry is not None
    assert callable(default_registry)
    assert callable(run_sandboxed)


def test_knowledge_subpackage_imports():
    from baize.knowledge import log_event, remember, recall, augment, get_backend
    assert callable(log_event)
    assert callable(recall)
    assert callable(get_backend)


def test_security_subpackage_imports():
    from baize.security import run_gate, validate_manifest, HookRegistry, run_checks
    assert callable(run_gate)
    assert callable(validate_manifest)
    assert HookRegistry is not None
    assert callable(run_checks)


def test_serve_and_cli_imports():
    from baize.serve import serve
    from baize.cli import main
    from baize.dashboard import render
    assert callable(main)
    assert callable(serve)
    assert callable(render)
