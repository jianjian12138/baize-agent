"""Baize Agent runtime package.

Pure Python standard library only — zero third-party runtime dependencies.
This module is intentionally minimal: it sets the single source of truth for
the published release version and must NOT import any submodule at import
time (keeps the package import cheap and avoids pulling stdlib-heavy modules
into `baize --version` / the `/health` endpoint / the dashboard).

The core runtime (`baize/agent.py`, `baize/cli.py`, `baize/serve.py`,
`baize/dashboard.py`, ...) does `from . import __version__`; previously that
name was only provided by an editable install, which broke `import baize`
from a plain checkout. W1 of the V25 upgrade creates this file so the version
is always resolvable. See docs/V25-arch-design/系统设计.md:485 and
docs/V25-专家评审.md N-03.
"""

__version__ = "36.0.0"
