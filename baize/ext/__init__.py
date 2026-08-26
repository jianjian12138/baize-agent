"""Baize extension modules (V25).

This package hosts OPTIONAL, fail-closed extensions that are NOT imported by
the core runtime. The core ``baize/`` package MUST never do a top-level
``import baize.ext`` (red line C: ext fail-closed). Red line A (zero runtime
dependencies) is preserved because every ext module uses only the Python
standard library.

Submodules added progressively in V25 (F3 MCP / F5 providers / F6 bus) must
lazy-import their stdlib pieces inside functions, so importing
``baize.ext`` itself stays cheap and safe. Consumers reach ext via
``plugin.discover`` / ``CompositionKernel.add_component`` — never via a
core-side import. See docs/V25-arch-design/系统设计.md and 升级计划 §3.3–§3.6.

收口契约 (F6): an ext module participates in the bus by exposing a
``Component``-shaped class (``KIND`` + ``build``) and being wired through
``BAIZE_COMPONENTS="baize.ext.<mod>:<Class>"`` (explicit, fail-closed) or
``plugin.discover()`` (auto, isolated). ``baize.ext.mcp.MCPComponent`` is the
canonical example. The one and only sanctioned core-side ext hook remains
``baize.tools.register_mcp_client`` (lazy import inside its function body).
"""
