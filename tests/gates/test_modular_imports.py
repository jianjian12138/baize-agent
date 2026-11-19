"""Test modular 9-domain subpackages and public lazy re-exports."""


def test_core_subpackage_imports():
    from baize.core import (
        Agent,
        LLMClient,
        load_config,
        Session,
        AutonomyPolicy,
        resolve_mode,
        CompositionKernel,
    )
    assert Agent is not None
    assert LLMClient is not None
    assert callable(load_config)


def test_orchestration_subpackage_imports():
    from baize.orchestration import (
        Orchestrator,
        ProjectContract,
        AtomicTask,
        RunLedger,
        Role,
        TeamConfig,
        HookRegistry,
        run_checks,
    )
    assert Orchestrator is not None
    assert ProjectContract is not None
    assert RunLedger is not None
    assert HookRegistry is not None
    assert callable(run_checks)


def test_tooling_subpackage_imports():
    from baize.execution import ToolRegistry, default_registry, run_sandboxed
    from baize.codebase import (
        SymbolGraph,
        ArchCacheManager,
        RepoMapGenerator,
        HierarchicalRepoMap,
        slice_code_context,
        BlastRadiusAnalyzer,
        TestImpactMatrix,
        analyze_change_impact,
        grep_workspace,
    )
    assert ToolRegistry is not None
    assert callable(default_registry)
    assert callable(run_sandboxed)
    assert callable(slice_code_context)
    assert callable(analyze_change_impact)
    assert callable(grep_workspace)


def test_knowledge_subpackage_imports():
    from baize.knowledge import log_event, remember, recall, augment, get_backend, build_index
    assert callable(log_event)
    assert callable(recall)
    assert callable(get_backend)
    assert callable(build_index)


def test_security_subpackage_imports():
    from baize.governance import run_gate, validate_manifest, obs, run_doctor
    assert callable(run_gate)
    assert callable(validate_manifest)
    assert obs is not None
    assert callable(run_doctor)


def test_serve_and_cli_imports():
    from baize.interfaces.serve import serve
    from baize.interfaces.cli import main
    from baize.interfaces.ui import render
    assert callable(main)
    assert callable(serve)
    assert callable(render)
