"""Allow `python -m baize` to launch the CLI directly.

This mirrors the ergonomics of hermes-agent / pi-agent where the package
itself is the runnable entry point (e.g. `python -m baize doctor`).
"""
import sys

from baize.cli import main

if __name__ == "__main__":
    sys.exit(main())
