"""Tests for Baize Universal Agent Desktop Studio App (V33.0.0)."""
from __future__ import annotations

import unittest
from baize.desktop_ui import render_desktop_studio
from baize.desktop import _is_server_alive, _find_browser_app_binary
from baize import dashboard
from baize.cli import build_parser


class TestDesktopApp(unittest.TestCase):
    def test_render_desktop_studio_contains_all_9_modules(self):
        html = render_desktop_studio("33.0.0")
        self.assertIn("Baize Agent Studio", html)
        self.assertIn("V33.0.0", html)
        
        # 9 Core Modules
        self.assertIn("tab-workbench", html)
        self.assertIn("tab-archive", html)
        self.assertIn("tab-team", html)
        self.assertIn("tab-skills", html)
        self.assertIn("tab-memory", html)
        self.assertIn("tab-models", html)
        self.assertIn("tab-doctor", html)
        self.assertIn("tab-security", html)
        self.assertIn("tab-integrations", html)

    def test_dashboard_render_delegates_to_desktop_studio(self):
        html = dashboard.render("33.0.0")
        self.assertIn("Baize Agent Studio", html)
        self.assertIn("白泽智能桌面工作台", html)

    def test_desktop_launcher_helper(self):
        # Server alive check on dummy closed port returns False
        self.assertFalse(_is_server_alive("127.0.0.1", 59999))

    def test_cli_desktop_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["desktop", "--host", "127.0.0.1", "--port", "9999"])
        self.assertEqual(args.command, "desktop")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 9999)


if __name__ == "__main__":
    unittest.main()
