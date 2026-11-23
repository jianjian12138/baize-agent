"""V45 Polyglot Project Fingerprint Detector & Unified Verification Adapter.

Pure Python standard library only. Detects primary/secondary languages, package
managers, build/lint/test/coverage commands, and recommended LSP servers across
Python, TypeScript/JavaScript, Go, Rust, Java, Dart/Flutter, and C/C++.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ProjectProfile",
    "detect_project_profile",
    "run_polyglot_gate",
    "clear_profile_cache",
]


@dataclass
class ProjectProfile:
    workspace: str
    primary_language: str = "unknown"
    languages: list[str] = field(default_factory=list)
    package_manager: str = ""
    manifests: list[str] = field(default_factory=list)
    build_cmd: list[str] = field(default_factory=list)
    lint_cmd: list[str] = field(default_factory=list)
    test_cmd: list[str] = field(default_factory=list)
    coverage_cmd: list[str] = field(default_factory=list)
    lsp_candidates: dict[str, list[str]] = field(default_factory=dict)
    detected_at: float = field(default_factory=lambda: round(time.time(), 3))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def format_for_context(self) -> str:
        if self.primary_language == "unknown" and not self.languages:
            return ""
        langs = ", ".join(self.languages) if self.languages else self.primary_language
        parts = [f"languages=[{langs}]", f"primary={self.primary_language}"]
        if self.package_manager:
            parts.append(f"pm={self.package_manager}")
        if self.build_cmd:
            parts.append(f"build=`{' '.join(self.build_cmd)}`")
        if self.test_cmd:
            parts.append(f"test=`{' '.join(self.test_cmd)}`")
        if self.lint_cmd:
            parts.append(f"lint=`{' '.join(self.lint_cmd)}`")
        return "[ProjectProfile] " + " | ".join(parts)


_MANIFEST_NAMES = (
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    "pnpm-lock.yaml",
    "bun.lockb",
    "bun.lock",
    "yarn.lock",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pubspec.yaml",
    "CMakeLists.txt",
    "Makefile",
)

_EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".dart": "dart",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
}

_LSP_BY_LANG: dict[str, list[str]] = {
    "python": ["pyright-langserver --stdio", "pylsp"],
    "typescript": ["typescript-language-server --stdio"],
    "javascript": ["typescript-language-server --stdio"],
    "go": ["gopls serve"],
    "rust": ["rust-analyzer"],
    "java": ["jdtls"],
    "dart": ["dart language-server --protocol=lsp"],
    "c": ["clangd"],
    "cpp": ["clangd"],
}

_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    "target", ".baize_worktrees", "persistence", ".idea", ".vscode",
})

_CACHE_LOCK = threading.Lock()
_PROFILE_CACHE: dict[str, tuple[tuple[tuple[str, int], ...], ProjectProfile]] = {}


def clear_profile_cache() -> None:
    with _CACHE_LOCK:
        _PROFILE_CACHE.clear()


def _manifest_signature(ws: Path) -> tuple[tuple[str, int], ...]:
    sig: list[tuple[str, int]] = []
    for name in _MANIFEST_NAMES:
        p = ws / name
        if p.is_file():
            try:
                sig.append((name, p.stat().st_mtime_ns))
            except OSError:
                pass
    return tuple(sig)


def _scan_language_counts(ws: Path, max_files: int = 400) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen = 0
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if seen >= max_files:
                return counts
            ext = Path(fn).suffix.lower()
            lang = _EXT_TO_LANG.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
                seen += 1
    return counts


def _detect_node_commands(ws: Path) -> tuple[str, list[str], list[str], list[str], list[str]]:
    if (ws / "pnpm-lock.yaml").is_file():
        pm = "pnpm"
    elif (ws / "bun.lockb").is_file() or (ws / "bun.lock").is_file():
        pm = "bun"
    elif (ws / "yarn.lock").is_file():
        pm = "yarn"
    else:
        pm = "npm"

    scripts: dict[str, str] = {}
    pkg = ws / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and isinstance(data.get("scripts"), dict):
                scripts = {str(k): str(v) for k, v in data["scripts"].items()}
        except Exception:
            pass

    def _run_script(name: str) -> list[str]:
        if pm == "npm":
            return ["npm", "run", name] if name != "test" else ["npm", "test"]
        return [pm, "run", name] if name != "test" else [pm, "test"]

    build_cmd = _run_script("build") if "build" in scripts else (["npx", "tsc", "--noEmit"] if (ws / "tsconfig.json").is_file() else [])
    lint_cmd = _run_script("lint") if "lint" in scripts else []
    test_cmd = _run_script("test") if "test" in scripts else []
    cov_cmd = _run_script("test:coverage") if "test:coverage" in scripts else []
    return pm, build_cmd, lint_cmd, test_cmd, cov_cmd


def detect_project_profile(workspace: str | Path = ".", *, use_cache: bool = True) -> ProjectProfile:
    """Detect project languages, package manager, and verification commands."""
    ws = Path(workspace).resolve()
    key = str(ws)
    sig = _manifest_signature(ws)
    if use_cache:
        with _CACHE_LOCK:
            cached = _PROFILE_CACHE.get(key)
            if cached is not None and cached[0] == sig:
                return cached[1]

    manifests = [name for name, _ in sig]
    counts = _scan_language_counts(ws)

    # Order languages by manifest presence first, then file count
    lang_order: list[str] = []

    def _add(lang: str) -> None:
        if lang and lang not in lang_order:
            lang_order.append(lang)

    if "Cargo.toml" in manifests:
        _add("rust")
    if "go.mod" in manifests:
        _add("go")
    if "pubspec.yaml" in manifests:
        _add("dart")
    if "tsconfig.json" in manifests:
        _add("typescript")
    if "package.json" in manifests:
        _add("typescript" if "tsconfig.json" in manifests or counts.get("typescript", 0) > 0 else "javascript")
    if any(m in manifests for m in ("pom.xml", "build.gradle", "build.gradle.kts")):
        _add("java")
    if any(m in manifests for m in ("pyproject.toml", "setup.py", "requirements.txt")):
        _add("python")
    if "CMakeLists.txt" in manifests:
        _add("cpp")

    for lang, _cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
        _add(lang)

    primary = lang_order[0] if lang_order else "unknown"
    pm = ""
    build_cmd: list[str] = []
    lint_cmd: list[str] = []
    test_cmd: list[str] = []
    cov_cmd: list[str] = []

    if primary == "python":
        if (ws / "uv.lock").is_file() or shutil.which("uv"):
            pm = "uv" if (ws / "uv.lock").is_file() else "pip"
        elif (ws / "poetry.lock").is_file():
            pm = "poetry"
        else:
            pm = "pip"
        build_cmd = ["python3", "-m", "compileall", "-q", "."]
        lint_cmd = ["ruff", "check", "."] if shutil.which("ruff") else []
        test_cmd = ["pytest", "-q"] if shutil.which("pytest") else ["python3", "-m", "unittest", "discover", "-q"]
        cov_cmd = ["pytest", "--cov", "-q"] if shutil.which("pytest") else []
    elif primary in ("typescript", "javascript"):
        pm, build_cmd, lint_cmd, test_cmd, cov_cmd = _detect_node_commands(ws)
    elif primary == "go":
        pm = "go"
        build_cmd = ["go", "build", "./..."]
        lint_cmd = ["go", "vet", "./..."]
        test_cmd = ["go", "test", "./..."]
        cov_cmd = ["go", "test", "-cover", "./..."]
    elif primary == "rust":
        pm = "cargo"
        build_cmd = ["cargo", "check"]
        lint_cmd = ["cargo", "clippy", "--quiet"]
        test_cmd = ["cargo", "test"]
    elif primary == "java":
        if (ws / "pom.xml").is_file():
            pm = "maven"
            build_cmd = ["mvn", "-q", "test-compile"]
            test_cmd = ["mvn", "-q", "test"]
        else:
            pm = "gradle"
            gradle_bin = "./gradlew" if (ws / "gradlew").is_file() else "gradle"
            build_cmd = [gradle_bin, "compileJava"]
            test_cmd = [gradle_bin, "test"]
    elif primary == "dart":
        is_flutter = False
        pub = ws / "pubspec.yaml"
        if pub.is_file():
            try:
                is_flutter = "flutter:" in pub.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        pm = "flutter" if is_flutter else "dart"
        lint_cmd = ["flutter", "analyze"] if is_flutter else ["dart", "analyze"]
        test_cmd = ["flutter", "test"] if is_flutter else ["dart", "test"]
    elif primary in ("c", "cpp"):
        pm = "cmake" if (ws / "CMakeLists.txt").is_file() else "make"
        build_cmd = ["cmake", "--build", "build"] if pm == "cmake" else ["make"]
        test_cmd = ["ctest", "--test-dir", "build", "--output-on-failure"] if pm == "cmake" else ["make", "test"]

    lsp_candidates = {lang: list(_LSP_BY_LANG[lang]) for lang in lang_order if lang in _LSP_BY_LANG}
    profile = ProjectProfile(
        workspace=key,
        primary_language=primary,
        languages=lang_order,
        package_manager=pm,
        manifests=manifests,
        build_cmd=build_cmd,
        lint_cmd=lint_cmd,
        test_cmd=test_cmd,
        coverage_cmd=cov_cmd,
        lsp_candidates=lsp_candidates,
    )
    if use_cache:
        with _CACHE_LOCK:
            _PROFILE_CACHE[key] = (sig, profile)
    return profile


def run_polyglot_gate(workspace: str | Path = ".", *, timeout: int = 120) -> dict[str, Any]:
    """Run detected build/lint/test commands for any supported project language."""
    ws = Path(workspace).resolve()
    profile = detect_project_profile(ws, use_cache=False)
    checks: list[dict[str, Any]] = []
    for stage, cmd in (("build", profile.build_cmd), ("lint", profile.lint_cmd), ("test", profile.test_cmd)):
        if not cmd:
            continue
        exe = cmd[0]
        if not (exe.startswith("./") or shutil.which(exe)):
            checks.append({"stage": stage, "cmd": cmd, "status": "skipped", "reason": f"{exe} not found on PATH"})
            continue
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ws),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            out = (proc.stdout + "\n" + proc.stderr).strip()
            checks.append({
                "stage": stage,
                "cmd": cmd,
                "status": "passed" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode,
                "elapsed_ms": elapsed_ms,
                "output": out[-1200:],
            })
        except subprocess.TimeoutExpired:
            checks.append({"stage": stage, "cmd": cmd, "status": "failed", "reason": f"timeout after {timeout}s"})
        except OSError as exc:
            checks.append({"stage": stage, "cmd": cmd, "status": "failed", "reason": str(exc)})

    failed = [c for c in checks if c["status"] == "failed"]
    ran = [c for c in checks if c["status"] in ("passed", "failed")]
    return {
        "ok": len(failed) == 0 and len(ran) > 0,
        "profile": profile.to_dict(),
        "checks": checks,
        "passed_count": sum(1 for c in checks if c["status"] == "passed"),
        "failed_count": len(failed),
        "skipped_count": sum(1 for c in checks if c["status"] == "skipped"),
    }
