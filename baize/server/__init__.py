"""baize.server — Command-line interface, HTTP server, dashboard, and evaluation harnesses."""
from ..cli import main, build_parser
from ..serve import serve, Handler
from ..dashboard import render as render_dashboard, PAGE
from ..ui import ProgressUI, Palette, supports_color

__all__ = [
    "main", "build_parser",
    "serve", "Handler",
    "render_dashboard", "PAGE",
    "ProgressUI", "Palette", "supports_color",
]
