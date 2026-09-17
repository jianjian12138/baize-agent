"""Unit tests for the optional Docker sandbox driver.

Scope and honesty note: there is no Docker daemon in this environment (and CI
may not have one either), so these tests stub the ``subprocess`` boundary rather
than running real containers. They verify the driver's OWN logic - argv
construction, result mapping, exit-code mapping and the availability probe -
which is exactly the part that can silently rot. They are NOT integration
tests against Docker, and are not claimed to be.

The container path (``run`` after the availability branch) had 0% coverage
before this file: nothing could reach it without a daemon, so a bug in the
``docker run`` arguments would have shipped undetected.
"""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from baize import docker_sandbox
from baize.docker_sandbox import DockerSandboxDriver, is_docker_available


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestDockerAvailabilityProbe(unittest.TestCase):
    def test_false_when_cli_is_not_installed(self):
        with mock.patch.object(docker_sandbox.shutil, "which", return_value=None):
            self.assertFalse(is_docker_available())

    def test_false_when_daemon_is_down(self):
        """CLI present but `docker info` fails - the bug that made the driver
        take the container path, get exit 127, and never reach its fallback."""
        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run",
                               return_value=_completed(1, stderr="Cannot connect to the Docker daemon")):
            self.assertFalse(is_docker_available())

    def test_true_when_daemon_answers(self):
        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run", return_value=_completed(0, stdout="Server: OK")):
            self.assertTrue(is_docker_available())

    def test_probe_is_cheap_not_a_full_info_dump(self):
        """The probe must pass capture_output and a short timeout, or a hung
        daemon would hang `baize doctor`."""
        seen = {}

        def _capture(cmd, **kw):
            seen["cmd"] = cmd
            seen.update(kw)
            return _completed(0)

        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run", side_effect=_capture):
            is_docker_available()
        self.assertEqual(seen["cmd"], ["docker", "info"])
        self.assertTrue(seen.get("capture_output"))
        self.assertIsInstance(seen.get("timeout"), (int, float))

    def test_false_when_the_probe_raises(self):
        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run", side_effect=OSError("boom")):
            self.assertFalse(is_docker_available())


class TestContainerPath(unittest.TestCase):
    def _driver_with_daemon(self, run_result):
        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run", return_value=_completed(0)):
            driver = DockerSandboxDriver(workspace=".")
        self.assertTrue(driver.docker_available)
        return driver, run_result

    def test_argv_pins_image_limits_and_mounts_the_workspace(self):
        captured = {}

        def _capture(cmd, **kw):
            captured["cmd"] = cmd
            return _completed(0, stdout="hi\n")

        driver, _ = self._driver_with_daemon(None)
        with mock.patch.object(docker_sandbox.subprocess, "run", side_effect=_capture):
            res = driver.run("echo hi")

        cmd = captured["cmd"]
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        self.assertIn(f"{driver.workspace}:/workspace", cmd)
        self.assertIn("--memory=1g", cmd)
        self.assertIn("--cpus=2.0", cmd)
        self.assertEqual(cmd[-3:], ["sh", "-c", "echo hi"])
        # the image must sit immediately before the command
        self.assertEqual(cmd[cmd.index("sh") - 1], driver.image)

        self.assertEqual(res["returncode"], 0)
        self.assertEqual(res["stdout"], "hi\n")
        self.assertFalse(res["degraded"])
        self.assertEqual(res["driver"], "docker_container")
        self.assertEqual(res["image"], driver.image)

    def test_timeout_maps_to_124(self):
        driver, _ = self._driver_with_daemon(None)
        with mock.patch.object(docker_sandbox.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("docker", 60)):
            res = driver.run("sleep 999")
        self.assertEqual(res["returncode"], 124)
        self.assertIn("timed out", res["stderr"])
        self.assertFalse(res["degraded"])
        self.assertEqual(res["driver"], "docker_container")

    def test_unexpected_failure_maps_to_docker_error_and_is_marked_degraded(self):
        driver, _ = self._driver_with_daemon(None)
        with mock.patch.object(docker_sandbox.subprocess, "run", side_effect=OSError("no exec")):
            res = driver.run("echo hi")
        self.assertEqual(res["returncode"], 1)
        self.assertTrue(res["degraded"])
        self.assertEqual(res["driver"], "docker_error")
        self.assertIn("no exec", res["stderr"])

    def test_container_path_is_not_taken_when_the_daemon_is_down(self):
        """Regression: the driver must fall back, not shell out to a dead CLI."""
        with mock.patch.object(docker_sandbox.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(docker_sandbox.subprocess, "run", return_value=_completed(1)):
            driver = DockerSandboxDriver(workspace=".")
        self.assertFalse(driver.docker_available)
        res = driver.run("echo fallback")
        self.assertEqual(res["driver"], "fallback_local_sandbox")


if __name__ == "__main__":
    unittest.main()
