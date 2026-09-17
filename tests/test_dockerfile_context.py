"""The Dockerfile must be buildable against the *filtered* build context.

Docker resolves ``COPY`` sources against the build context after
``.dockerignore`` has been applied. So a ``COPY docs/ ./docs/`` line is not
merely redundant - it is unbuildable. The build dies with::

    failed to compute cache key: "/docs": not found

That is exactly what happened on ``v30-dev``, and it went unnoticed because the
``docker`` CI job had never once been green, so nobody was reading its output.

These tests are the cheap local stand-in for a real ``docker build`` (which needs
a running daemon). They pin the four things that actually broke, or could break:

  * every ``COPY`` source exists in the repository
  * every ``COPY`` source survives ``.dockerignore``
  * every ``ENV BAIZE_*`` name is a key the code actually reads
  * the directories the image creates are the ones ``baize doctor`` requires
"""
from __future__ import annotations

import fnmatch
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations so a multi-line RUN reads as one line."""
    joined: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        joined.append(buffer + line)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _copy_sources() -> list[str]:
    """Source paths from every COPY instruction (flags such as --chown stripped)."""
    sources: list[str] = []
    for line in _logical_lines(_dockerfile_text()):
        m = re.match(r"^\s*COPY\s+(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        parts = [p for p in m.group(1).split() if not p.startswith("--")]
        if len(parts) < 2:
            continue
        sources.extend(parts[:-1])  # last token is the destination
    return sources


def _dockerignore_patterns() -> list[str]:
    patterns: list[str] = []
    for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            patterns.append(entry)
    return patterns


def _is_ignored(source: str, patterns: list[str]) -> bool:
    """Gitignore-ish match, enough for the flat patterns this repo uses."""
    clean = source.rstrip("/")
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if not pat:
            continue
        if fnmatch.fnmatch(clean, pat) or fnmatch.fnmatch(clean, f"{pat}/*"):
            return True
        # A directory pattern also excludes everything beneath it.
        if clean == pat or clean.startswith(pat + "/"):
            return True
    return False


# --- COPY sources -----------------------------------------------------------


def test_every_copy_source_exists_in_the_repo():
    missing = [s for s in _copy_sources() if not (ROOT / s.rstrip("/")).exists()]
    assert not missing, (
        "COPY sources that do not exist in the build context:\n"
        + "\n".join(f"  {s}" for s in missing)
    )


def test_every_copy_source_survives_dockerignore():
    """This is the bug that made the image unbuildable: COPY of an ignored path."""
    patterns = _dockerignore_patterns()
    bad = [s for s in _copy_sources() if _is_ignored(s, patterns)]
    assert not bad, (
        "COPY sources excluded by .dockerignore - Docker resolves COPY against the\n"
        "filtered context, so the build fails with "
        '`failed to compute cache key: "/<path>": not found`:\n'
        + "\n".join(f"  {s}" for s in bad)
        + "\n\nEither drop the COPY line, or un-ignore the path in .dockerignore."
    )


def test_assets_directory_is_copied():
    """BAIZE_ASSETS_DIR defaults to <root>/assets and `baize index build` scans it."""
    assert any(s.rstrip("/") == "assets" for s in _copy_sources()), (
        "assets/ is not COPYed, so the container starts with an empty skill index"
    )


# --- ENV keys ---------------------------------------------------------------


def test_every_baize_env_key_is_a_real_config_key():
    """A dead ENV name silently does nothing - which is how the server ended up
    bound to 127.0.0.1 while the image declared 0.0.0.0."""
    from baize.config import _DEFAULTS  # the documented default set

    names: list[str] = []
    for line in _logical_lines(_dockerfile_text()):
        m = re.match(r"^\s*ENV\s+(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        for token in m.group(1).split():
            name = token.split("=", 1)[0]
            if name.startswith("BAIZE_"):
                names.append(name)

    assert names, "expected the Dockerfile to set at least one BAIZE_* variable"
    unknown = [n for n in names if n not in _DEFAULTS]
    assert not unknown, (
        "ENV names that no code reads (dead configuration):\n"
        + "\n".join(f"  {n}" for n in unknown)
        + f"\n\nKnown keys include: {sorted(k for k in _DEFAULTS if k.startswith('BAIZE_'))[:12]} ..."
    )


def test_server_binds_all_interfaces_not_loopback():
    """A container that binds 127.0.0.1 is unreachable through -p."""
    text = _dockerfile_text()
    assert re.search(r"^ENV\s+BAIZE_SERVE_HOST=0\.0\.0\.0", text, re.MULTILINE), (
        "BAIZE_SERVE_HOST must be 0.0.0.0 in the image, otherwise port publishing "
        "from the host cannot reach the server"
    )


# --- runtime directories ----------------------------------------------------


def test_image_creates_the_directories_doctor_requires():
    """baize/doctor.py treats BAIZE_PERSISTENCE_DIR and BAIZE_PROJECTS_DIR as
    required, so a missing directory makes `docker run ... doctor` exit 1."""
    from baize.config import _DEFAULTS

    workdir = re.search(r"^WORKDIR\s+(\S+)", _dockerfile_text(), re.MULTILINE)
    assert workdir, "Dockerfile has no WORKDIR"
    base = workdir.group(1).rstrip("/")

    for key in ("BAIZE_PERSISTENCE_DIR", "BAIZE_PROJECTS_DIR"):
        subdir = pathlib.Path(_DEFAULTS[key]).name
        expected = f"{base}/{subdir}"
        assert expected in _dockerfile_text(), (
            f"the image never creates {expected} ({key} defaults to <root>/{subdir}), "
            "so `baize doctor` fails inside the container"
        )
