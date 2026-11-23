"""V45 Nexus tests: Zero-install default OS light sandbox, Landlock ctypes, Seatbelt hardening & SessionDockerPool."""
from __future__ import annotations

import subprocess
import tempfile
import types
import unittest
from unittest import mock

from baize.core.config import _DEFAULTS, validate
from baize.execution import docker_sandbox, proc as proc_mod, sandbox


class TestV45NativeSandboxAndDockerPool(unittest.TestCase):
    def test_default_sandbox_enabled_local_hardened_and_explicit_disable_compat(self) -> None:
        self.assertEqual(_DEFAULTS["BAIZE_SANDBOX_ENABLED"], "1")
        self.assertEqual(_DEFAULTS["BAIZE_SANDBOX_NET"], "allow")
        self.assertEqual(_DEFAULTS["BAIZE_DOCKER_SESSION_POOL"], "1")
        # Default config resolves to local-hardened (zero-install OS light sandbox)
        self.assertEqual(sandbox.resolve_sandbox_mode(dict(_DEFAULTS)), "local-hardened")
        # Explicit opt-out still returns disabled ("")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_ENABLED": "0"}), "")
        self.assertEqual(sandbox.resolve_sandbox_mode({"BAIZE_SANDBOX_MODE": "disabled"}), "")
        # Schema validation passes cleanly with default config
        validate(dict(_DEFAULTS))

    def test_seatbelt_profile_shields_sensitive_dirs_and_respects_network_policy(self) -> None:
        with mock.patch.object(sandbox, "_sensitive_home_paths", return_value=["/Users/dev/.ssh", "/Users/dev/.aws"]):
            prof_allow = sandbox._seatbelt_profile("/tmp/ws", allow_net=True)
            self.assertIn('(deny default)', prof_allow)
            self.assertIn('(allow file-write* (subpath "/tmp/ws"))', prof_allow)
            self.assertIn('(deny file-read* (subpath "/Users/dev/.ssh"))', prof_allow)
            self.assertIn('(deny file-read* (subpath "/Users/dev/.aws"))', prof_allow)
            self.assertIn('(allow network*)', prof_allow)

            prof_none = sandbox._seatbelt_profile("/tmp/ws", allow_net=False)
            self.assertIn('(deny network-outbound)', prof_none)
            self.assertNotIn('(allow network*)', prof_none)

    def test_sandbox_posture_discloses_landlock_driver_network_and_pool(self) -> None:
        with mock.patch.object(docker_sandbox, "is_docker_available", return_value=False):
            post = sandbox.sandbox_posture({"BAIZE_SANDBOX_ENABLED": "1", "BAIZE_SANDBOX_NET": "none"})
            self.assertEqual(post["configured_mode"], "local-hardened")
            self.assertEqual(post["network_policy"], "none")
            self.assertIn(post["landlock_driver"], ("python-landlock", "ctypes", "none"))
            self.assertIn("docker_session_pool", post)
            self.assertIn("protected_paths", post)

    def test_linux_ctypes_landlock_detection_path(self) -> None:
        with mock.patch.object(sandbox.platform, "system", return_value="Linux"):
            with mock.patch.object(sandbox, "_landlock_ctypes_supported", return_value=True):
                self.assertEqual(sandbox.landlock_driver(), "ctypes")
                self.assertEqual(sandbox.platform_mechanism(), "landlock")

    def test_session_docker_pool_reuses_warm_container_and_cleans_up(self) -> None:
        pool = docker_sandbox.SessionDockerPool()
        fake_sub = mock.MagicMock(returncode=0, stdout="cid123\n", stderr="")
        fake_proc_res = types.SimpleNamespace(returncode=0, stdout="hello-from-pool\n", stderr="", timed_out=False)

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(subprocess, "run", return_value=fake_sub) as mock_sub,                  mock.patch.object(proc_mod, "run", return_value=fake_proc_res) as mock_proc:
                r1 = pool.exec_in_session(session_id="sess-42", command="echo 1", workspace=td)
                r2 = pool.exec_in_session(session_id="sess-42", command="echo 2", workspace=td)

                self.assertEqual(r1["returncode"], 0)
                self.assertEqual(r1["driver"], "docker_session_pool")
                self.assertEqual(r1["container"], r2["container"])
                # `docker run -d` should be called only ONCE for the same session!
                self.assertEqual(mock_sub.call_count, 1)
                self.assertIn("run", mock_sub.call_args[0][0])
                self.assertIn("-d", mock_sub.call_args[0][0])
                # `docker exec` called twice
                self.assertEqual(mock_proc.call_count, 2)
                self.assertEqual(mock_proc.call_args[0][0][:2], ["docker", "exec"])
                self.assertEqual(pool.status()["active_containers"], 1)

                stopped = pool.stop_all()
                self.assertEqual(stopped, 1)
                self.assertEqual(pool.status()["active_containers"], 0)
                # Last subprocess call was `docker rm -f <cname>`
                self.assertEqual(mock_sub.call_args[0][0][:3], ["docker", "rm", "-f"])


if __name__ == "__main__":
    unittest.main()
