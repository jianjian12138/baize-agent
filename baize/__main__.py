"""Module entry point for ``python -m baize``.

Keep this shim deliberately small so module execution follows the same CLI
path as the installed ``baize`` console script.
"""
from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
