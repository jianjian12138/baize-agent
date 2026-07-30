"""V20 terminal UI - live progress rendering for agent and team runs.

Zero dependencies. Renders the (kind, detail) event stream emitted by Agent
and Orchestrator into a readable, colored timeline with per-phase timing and
a closing summary table.

Color is auto-detected and degrades safely:
  - disabled when stdout is not a TTY (piping to a file stays clean)
  - disabled when NO_COLOR is set (https://no-color.org)
  - enabled on Windows only after a successful VT-mode probe

Usage:
    ui = ProgressUI()
    agent = Agent(on_event=ui.event)
    res = agent.run(goal)
    ui.summary()
"""
from __future__ import annotations

import os
import sys
import time

__all__ = ["supports_color", "Palette", "ProgressUI"]


def supports_color(stream=None) -> bool:
    """True only when ANSI color is genuinely safe to emit."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("BAIZE_FORCE_COLOR") == "1":
        return True
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        try:  # enable VT processing; if it fails, stay monochrome
            import ctypes
            kernel32 = ctypes.windll.kernel32
            return bool(kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7))
        except Exception:
            return False
    return os.environ.get("TERM", "") != "dumb"


class Palette:
    """ANSI codes, or empty strings when color is unavailable."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        codes = {"dim": "\033[2m", "bold": "\033[1m", "red": "\033[31m",
                 "green": "\033[32m", "yellow": "\033[33m", "blue": "\033[34m",
                 "magenta": "\033[35m", "cyan": "\033[36m", "reset": "\033[0m"}
        for name, code in codes.items():
            setattr(self, name, code if enabled else "")

    def paint(self, color: str, text: str) -> str:
        return f"{getattr(self, color, '')}{text}{self.reset}"


# kind -> (glyph, color)
_STYLES = {
    "phase":    ("=>", "cyan"),
    "tool":     ("->", "blue"),
    "final":    ("OK", "green"),
    "reflect":  ("**", "magenta"),
    "compress": ("~~", "dim"),
    "loop":     ("!!", "yellow"),
    "error":    ("XX", "red"),
    "retry":    ("<>", "yellow"),
}


class ProgressUI:
    """Streaming progress renderer for the agent/orchestrator event stream."""

    def __init__(self, stream=None, color: bool | None = None,
                 verbose: bool = True, max_detail: int = 110):
        self.stream = stream or sys.stdout
        enabled = supports_color(self.stream) if color is None else color
        self.p = Palette(enabled)
        self.verbose = verbose
        self.max_detail = max_detail
        self.started = time.perf_counter()
        self.counts: dict[str, int] = {}
        self.events: list[tuple[float, str, str]] = []

    # --- event sink ---------------------------------------------------------

    def event(self, kind: str, detail: str = "") -> None:
        """Drop-in for on_event=(kind, detail). Never raises."""
        try:
            elapsed = time.perf_counter() - self.started
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.events.append((elapsed, kind, detail))
            if self.verbose:
                self._render(elapsed, kind, detail)
        except Exception:
            pass  # UI must never break a run

    def _render(self, elapsed: float, kind: str, detail: str) -> None:
        glyph, color = _STYLES.get(kind, ("..", "dim"))
        text = detail.replace("\n", " ")
        if len(text) > self.max_detail:
            text = text[:self.max_detail - 1] + "…"
        stamp = self.p.paint("dim", f"{elapsed:6.1f}s")
        badge = self.p.paint(color, f"{glyph} {kind:<8}")
        print(f"{stamp} {badge} {text}", file=self.stream, flush=True)

    # --- summary ------------------------------------------------------------

    def summary(self, result=None) -> str:
        """Render a closing summary; returns the text (also printed)."""
        total = time.perf_counter() - self.started
        lines = [self.p.paint("bold", "-" * 62),
                 self.p.paint("bold", f"  run finished in {total:.1f}s")]
        if self.counts:
            parts = "  ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
            lines.append(f"  events: {parts}")
        if result is not None:
            reason = getattr(result, "stopped_reason", None)
            if reason:
                color = "green" if reason == "final" else "yellow"
                lines.append(f"  outcome: {self.p.paint(color, reason)}  "
                             f"steps={getattr(result, 'steps', '?')}  "
                             f"tools={getattr(result, 'tool_calls', '?')}")
            success = getattr(result, "success", None)
            if success is not None:
                color = "green" if success else "red"
                label = "SUCCESS" if success else "FAILED"
                lines.append(f"  overall: {self.p.paint(color, label)}")
        lines.append(self.p.paint("bold", "-" * 62))
        text = "\n".join(lines)
        print(text, file=self.stream, flush=True)
        return text

    def bar(self, done: int, total: int, width: int = 30) -> str:
        """Render a static progress bar (returned, not printed)."""
        total = max(1, total)
        filled = int(width * min(done, total) / total)
        return (f"[{'#' * filled}{'.' * (width - filled)}] "
                f"{done}/{total}")
