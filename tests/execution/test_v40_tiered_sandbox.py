"""Tests for V40 tiered sandbox isolation (rlimit, env scrubbing, Docker routing)."""
from __future__ import annotations

import tempfile
import types
import unittest
from unittest import mock

from baize.execution import docker_sandbox, sandbox


class TestV40TieredSandbox(unittest.TestCase):
    def test_scrub_environment_strips_secrets_and_keeps_safe_vars(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/dev",
            "BAIZE_AUTH_TOKEN": "secret-tok",
            "OPENAI_API_KEY": "sk-123",
            "AWS_SECRET_ACCESS_KEY": "aws-sec",
            "GITHUB_TOKEN": "ghp_xxx",
            "LANG": "C.UTF-8",
        }
        cleaned = sandbox.scrub_environment(env)
        self.assertEqual(cleaned["PATH"], "/usr/bin")
        self.assertEqual(cleaned["HOME"], "/home/dev")
        self.assertNotIn("BAIZE_AUTH_TOKEN", cleaned)
        self.assertNotIn("OPENAI_API_KEY", cleaned)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", cleaned)
        self.assertNotIn("GITHUB_TOKEN", cleaned)

    def test_resolve_sandbox_mode_tiers(self):
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_ENABLED": "0"}), "")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_ENABLED": "1"}), "local-hardened")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_MODE": "local-hardened"}), "local-hardened")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_MODE": "docker"}), "docker")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_MODE": "auto"}), "auto")

    def test_sandbox_posture_discloses_honest_tier(self):
        with mock.patch.object(docker_sandbox, "is_docker_available", return_value=False):
            p_disabled = sandbox.sandbox_posture({"BAIZE_SANDBOX_ENABLED": "0"})
            self.assertEqual(p_disabled["configured_mode"], "disabled")
            p_docker = sandbox.sandbox_posture({"BAIZE_SANDBOX_MODE": "docker"})
            self.assertIn("fail-closed", p_docker["effective_isolation"])
            p_auto = sandbox.sandbox_posture({"BAIZE_SANDBOX_MODE": "auto"})
            self.assertIn("local-hardened", p_auto["effective_isolation"])

    def test_strict_docker_mode_fails_closed_when_daemon_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(docker_sandbox, "is_docker_available", return_value=False):
                res = sandbox.run("echo should-not-run", cwd=td, mode="docker")
            self.assertEqual(res.returncode, 126)
            self.assertTrue(res.degraded)
            self.assertEqual(res.mechanism, "docker_unavailable")
            self.assertEqual(res.stdout, "")

    def test_auto_mode_degrades_honestly_to_local_hardened_when_docker_absent(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(docker_sandbox, "is_docker_available", return_value=False):
                res = sandbox.run("echo fallback-ok", cwd=td, mode="auto")
            self.assertEqual(res.returncode, 0)
            self.assertIn("fallback-ok", res.stdout)
            self.assertTrue(res.degraded)
            self.assertIn("docker-fallback", res.mechanism)

    def test_docker_driver_enforces_network_none_and_pids_limit(self):
        captured = {}

        def _cap(cmd, **kw):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="", timed_out=False)

        with mock.patch.object(docker_sandbox, "is_docker_available", return_value=True), \
             mock.patch.object(docker_sandbox.proc_mod, "run", side_effect=_cap):
            drv = docker_sandbox.DockerSandboxDriver(workspace=".")
            res = drv.run("echo ok")
        self.assertEqual(res["returncode"], 0)
        self.assertIn("--network=none", captured["cmd"])
        self.assertIn("--pids-limit=128", captured["cmd"])


if __name__ == "__main__":
    unittest.main()
