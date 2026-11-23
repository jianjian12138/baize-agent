"""V47.0.0 Horizon Native Mobile Simulator Bridge (Android ADB & iOS Simctl).

Pure Python standard library — zero third-party dependencies.
Auto-detects connected Android emulators/devices via ``adb`` and booted iOS
Simulators via ``xcrun simctl``. Supports screenshot capture, tap/swipe/input
interactions, app launch, and crash log inspection, with optional Stage 2
multimodal vision review.

Honest Degradation (NO FAKE DONE):
When no native simulator/device or CLI binary is available on the host, the
bridge explicitly marks ``degraded=True``, explains what is missing, runs the
project's native unit/widget tests (e.g. ``flutter test`` / ``dart test`` /
``gradle test`` / ``swift test``), and optionally chains ``verify_ui`` against
a Web/PWA preview URL.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import load_config

__all__ = [
    "MobileDevice",
    "MobileVerifyReport",
    "list_mobile_devices",
    "mobile_action",
    "verify_mobile_app",
]


@dataclass
class MobileDevice:
    platform: str          # "android" | "ios"
    device_id: str
    name: str
    state: str             # "device" | "booted" | "offline" | "unauthorized"
    is_emulator: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MobileVerifyReport:
    ok: bool
    mode: str              # "native-adb" | "native-simctl" | "degraded-unit-and-web"
    degraded: bool = False
    devices: list[MobileDevice] = field(default_factory=list)
    active_device: str = ""
    screenshot_path: str = ""
    crash_logs: list[str] = field(default_factory=list)
    unit_test_ok: bool | None = None
    unit_test_output: str = ""
    web_preview_report: dict[str, Any] | None = None
    vision_summary: str = ""
    defects: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "degraded": self.degraded,
            "devices": [d.to_dict() for d in self.devices],
            "active_device": self.active_device,
            "screenshot_path": self.screenshot_path,
            "crash_logs": list(self.crash_logs),
            "unit_test_ok": self.unit_test_ok,
            "unit_test_output": self.unit_test_output[:1200],
            "web_preview_report": self.web_preview_report,
            "vision_summary": self.vision_summary,
            "defects": list(self.defects),
            "notes": list(self.notes),
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    def format_for_agent(self) -> str:
        tag = "DEGRADED" if self.degraded else ("PASS" if self.ok else "FAIL")
        lines = [
            f"[mobile_verify:{self.mode}] {tag} devices={len(self.devices)} "
            f"active={self.active_device or 'none'} elapsed={self.elapsed_ms:.1f}ms"
        ]
        if self.screenshot_path:
            lines.append(f"  screenshot: {self.screenshot_path}")
        if self.crash_logs:
            lines.append(f"  crash_logs ({len(self.crash_logs)}): " + " | ".join(self.crash_logs[:3]))
        if self.unit_test_ok is not None:
            lines.append(f"  unit_tests: {'PASS' if self.unit_test_ok else 'FAIL'}")
        if self.web_preview_report is not None:
            lines.append(f"  web_preview: {'PASS' if self.web_preview_report.get('ok') else 'FAIL'}")
        for d in self.defects[:6]:
            lines.append(f"  - DEFECT: {d}")
        for n in self.notes[:4]:
            lines.append(f"  * note: {n}")
        return "\n".join(lines)


def _run_cmd(argv: list[str], *, timeout: int = 20, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _discover_android_devices(timeout: int = 10) -> list[MobileDevice]:
    adb = shutil.which("adb")
    if not adb:
        return []
    try:
        res = _run_cmd([adb, "devices", "-l"], timeout=timeout)
    except Exception:
        return []
    if res.returncode != 0:
        return []
    devices: list[MobileDevice] = []
    for raw in (res.stdout or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        dev_id, state = parts[0], parts[1]
        model_m = re.search(r"model:(\S+)", line)
        name = model_m.group(1) if model_m else dev_id
        devices.append(MobileDevice(
            platform="android",
            device_id=dev_id,
            name=name,
            state=state,
            is_emulator=dev_id.startswith("emulator-") or "emulator" in name.lower(),
        ))
    return devices


def _discover_ios_simulators(timeout: int = 10) -> list[MobileDevice]:
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return []
    try:
        res = _run_cmd([xcrun, "simctl", "list", "devices", "booted", "-j"], timeout=timeout)
    except Exception:
        return []
    if res.returncode != 0 or not (res.stdout or "").strip():
        return []
    try:
        payload = json.loads(res.stdout)
    except json.JSONDecodeError:
        return []
    devices: list[MobileDevice] = []
    for _runtime, dev_list in (payload.get("devices") or {}).items():
        if not isinstance(dev_list, list):
            continue
        for item in dev_list:
            if not isinstance(item, dict):
                continue
            state = str(item.get("state") or "").lower()
            if state != "booted":
                continue
            devices.append(MobileDevice(
                platform="ios",
                device_id=str(item.get("udid") or ""),
                name=str(item.get("name") or "iOS Simulator"),
                state="booted",
                is_emulator=True,
            ))
    return devices


def list_mobile_devices() -> dict[str, Any]:
    """Discover all online Android (ADB) and booted iOS Simulator (simctl) devices."""
    android = _discover_android_devices()
    ios = _discover_ios_simulators()
    all_devs = [*android, *ios]
    online = [d for d in all_devs if d.state in ("device", "booted")]
    return {
        "adb_available": bool(shutil.which("adb")),
        "simctl_available": bool(shutil.which("xcrun")),
        "total": len(all_devs),
        "online_count": len(online),
        "devices": [d.to_dict() for d in all_devs],
    }


def _select_device(device_id: str = "", platform_hint: str = "") -> MobileDevice | None:
    devs = [*_discover_android_devices(), *_discover_ios_simulators()]
    online = [d for d in devs if d.state in ("device", "booted")]
    if device_id:
        for d in online:
            if d.device_id == device_id:
                return d
    if platform_hint:
        for d in online:
            if d.platform == platform_hint.lower():
                return d
    return online[0] if online else None


def _capture_screenshot(dev: MobileDevice, out_path: Path) -> tuple[bool, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if dev.platform == "android":
        adb = shutil.which("adb")
        if not adb:
            return False, "adb binary not found"
        try:
            proc = subprocess.run(
                [adb, "-s", dev.device_id, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=15,
            )
            if proc.returncode == 0 and proc.stdout:
                out_path.write_bytes(proc.stdout)
                return True, str(out_path)
            return False, (proc.stderr or b"screencap failed").decode("utf-8", errors="replace").strip()
        except Exception as exc:
            return False, str(exc)

    if dev.platform == "ios":
        xcrun = shutil.which("xcrun")
        if not xcrun:
            return False, "xcrun binary not found"
        try:
            res = _run_cmd([xcrun, "simctl", "io", dev.device_id, "screenshot", str(out_path)], timeout=15)
            if res.returncode == 0 and out_path.is_file():
                return True, str(out_path)
            return False, (res.stderr or res.stdout or "simctl screenshot failed").strip()
        except Exception as exc:
            return False, str(exc)
    return False, f"unsupported platform: {dev.platform}"


def _fetch_crash_logs(dev: MobileDevice, max_lines: int = 30) -> list[str]:
    if dev.platform == "android":
        adb = shutil.which("adb")
        if not adb:
            return []
        try:
            res = _run_cmd([adb, "-s", dev.device_id, "logcat", "-d", "-t", str(max_lines), "*:E"], timeout=10)
            if res.returncode != 0:
                return []
            crashes = []
            for l in (res.stdout or "").splitlines():
                if any(k in l for k in ("FATAL EXCEPTION", "AndroidRuntime", "ANR in", " E ")):
                    crashes.append(l.strip()[:220])
            return crashes[-10:]
        except Exception:
            return []
    if dev.platform == "ios":
        xcrun = shutil.which("xcrun")
        if not xcrun:
            return []
        try:
            res = _run_cmd(
                [xcrun, "simctl", "spawn", dev.device_id, "log", "show", "--last", "2m", "--style", "compact", "--predicate", "messageType == 16"],
                timeout=12,
            )
            if res.returncode != 0:
                return []
            lines = [l.strip()[:220] for l in (res.stdout or "").splitlines() if l.strip() and not l.startswith("Timestamp")]
            return lines[-10:]
        except Exception:
            return []
    return []


def mobile_action(
    action: str,
    *,
    device_id: str = "",
    platform_hint: str = "",
    x: int = 0,
    y: int = 0,
    x2: int = 0,
    y2: int = 0,
    text: str = "",
    app_id: str = "",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a native simulator/device interaction via ADB or iOS Simctl."""
    act = (action or "").strip().lower()
    if act == "list_devices":
        return {"ok": True, "action": "list_devices", **list_mobile_devices()}

    dev = _select_device(device_id=device_id, platform_hint=platform_hint)
    if dev is None:
        return {
            "ok": False,
            "degraded": True,
            "action": act,
            "error": (
                "No online Android (adb) or booted iOS Simulator (xcrun simctl) device found. "
                "Start an emulator/simulator or use verify_mobile_app for automatic unit-test + Web preview fallback."
            ),
            **list_mobile_devices(),
        }

    eff_cfg = cfg if cfg is not None else load_config()
    if act == "screenshot":
        pers = Path(eff_cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
        out = pers / "mobile_shots" / f"{dev.platform}_{int(time.time() * 1000)}.png"
        ok, detail = _capture_screenshot(dev, out)
        return {
            "ok": ok,
            "action": act,
            "device": dev.to_dict(),
            "screenshot_path": detail if ok else "",
            "error": "" if ok else detail,
        }

    if act == "logs":
        logs = _fetch_crash_logs(dev)
        return {"ok": True, "action": act, "device": dev.to_dict(), "crash_logs": logs, "count": len(logs)}

    if dev.platform == "android":
        adb = shutil.which("adb")
        if not adb:
            return {"ok": False, "error": "adb binary not found"}
        if act == "tap":
            res = _run_cmd([adb, "-s", dev.device_id, "shell", "input", "tap", str(int(x)), str(int(y))])
            return {"ok": res.returncode == 0, "action": act, "device": dev.to_dict(), "stderr": res.stderr.strip()}
        if act == "swipe":
            res = _run_cmd([adb, "-s", dev.device_id, "shell", "input", "swipe", str(int(x)), str(int(y)), str(int(x2)), str(int(y2)), "300"])
            return {"ok": res.returncode == 0, "action": act, "device": dev.to_dict(), "stderr": res.stderr.strip()}
        if act == "input_text":
            safe_txt = str(text).replace(" ", "%s")
            res = _run_cmd([adb, "-s", dev.device_id, "shell", "input", "text", safe_txt])
            return {"ok": res.returncode == 0, "action": act, "device": dev.to_dict(), "stderr": res.stderr.strip()}
        if act == "launch":
            if not app_id:
                return {"ok": False, "error": "launch requires app_id (Android package name)"}
            res = _run_cmd([adb, "-s", dev.device_id, "shell", "monkey", "-p", app_id, "-c", "android.intent.category.LAUNCHER", "1"])
            return {"ok": res.returncode == 0, "action": act, "device": dev.to_dict(), "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}
        return {"ok": False, "error": f"unsupported android action: {act}"}

    if dev.platform == "ios":
        xcrun = shutil.which("xcrun")
        if not xcrun:
            return {"ok": False, "error": "xcrun binary not found"}
        if act == "launch":
            if not app_id:
                return {"ok": False, "error": "launch requires app_id (iOS bundle identifier)"}
            res = _run_cmd([xcrun, "simctl", "launch", dev.device_id, app_id])
            return {"ok": res.returncode == 0, "action": act, "device": dev.to_dict(), "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}
        if act in ("tap", "swipe", "input_text"):
            return {
                "ok": False,
                "degraded": True,
                "action": act,
                "device": dev.to_dict(),
                "error": (
                    f"iOS simctl does not expose raw coordinate '{act}' without XCTest/WebDriverAgent; "
                    "use screenshot + launch + logs or run xcodebuild test / flutter integration_test."
                ),
            }
        return {"ok": False, "error": f"unsupported ios action: {act}"}

    return {"ok": False, "error": f"unsupported platform: {dev.platform}"}


def verify_mobile_app(
    workspace: str | Path = ".",
    *,
    device_id: str = "",
    platform_hint: str = "",
    app_id: str = "",
    fallback_web_url: str = "",
    check_visual: bool = False,
    cfg: dict[str, Any] | None = None,
    client: Any = None,
) -> MobileVerifyReport:
    """End-to-end mobile app verification with automatic honest degradation.

    1. Probes local ADB / iOS Simctl for an online simulator/device.
    2. If online: optionally launches ``app_id``, captures native screenshot,
       reads crash logs, and optionally runs Stage 2 multimodal vision review.
    3. If no native simulator is online: transparently degrades (``degraded=True``),
       runs the project's native test command (via ``detect_project_profile``),
       and chains ``verify_ui`` on ``fallback_web_url`` when configured.
    """
    t0 = time.perf_counter()
    eff_cfg = cfg if cfg is not None else load_config()
    ws = Path(workspace).resolve()
    all_devs = [*_discover_android_devices(), *_discover_ios_simulators()]
    dev = _select_device(device_id=device_id, platform_hint=platform_hint)

    # Path A: Native online simulator/device
    if dev is not None:
        mode = "native-adb" if dev.platform == "android" else "native-simctl"
        defects: list[str] = []
        notes: list[str] = []
        if app_id:
            lres = mobile_action("launch", device_id=dev.device_id, app_id=app_id, cfg=eff_cfg)
            if not lres.get("ok"):
                defects.append(f"failed to launch {app_id}: {lres.get('stderr') or lres.get('error')}")
            else:
                time.sleep(0.5)

        pers = Path(eff_cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
        shot_file = pers / "mobile_shots" / f"{dev.platform}_{int(time.time() * 1000)}.png"
        shot_ok, shot_detail = _capture_screenshot(dev, shot_file)
        shot_path = shot_detail if shot_ok else ""
        if not shot_ok:
            defects.append(f"screenshot failed: {shot_detail}")

        crashes = _fetch_crash_logs(dev)
        if crashes:
            defects.append(f"detected {len(crashes)} native crash/error log line(s)")

        vision_summary = ""
        if check_visual and shot_path:
            try:
                from .visual_verify import ViewportCapture, _run_vision_review
                cap = ViewportCapture(viewport="mobile", width=390, height=844, ok=True, screenshot_path=shot_path)
                v_ok, v_summary, v_defects = _run_vision_review(
                    f"mobile://{dev.platform}/{app_id or dev.name}", [cap], cfg=eff_cfg, client=client
                )
                vision_summary = v_summary
                if not v_ok:
                    defects.extend(v_defects)
            except Exception as exc:
                notes.append(f"vision review skipped: {exc}")

        return MobileVerifyReport(
            ok=len(defects) == 0,
            mode=mode,
            degraded=False,
            devices=all_devs,
            active_device=dev.device_id,
            screenshot_path=shot_path,
            crash_logs=crashes,
            vision_summary=vision_summary,
            defects=defects,
            notes=notes,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # Path B: Honest Degradation — no native emulator online -> unit tests + optional Web/PWA verify_ui
    notes = [
        "No online Android (adb) or booted iOS Simulator (xcrun simctl) detected; "
        "honestly degraded to project unit/widget tests + optional Web/PWA preview verification."
    ]
    defects: list[str] = []
    unit_ok: bool | None = None
    unit_out = ""
    try:
        from ..codebase.project_profile import detect_project_profile
        prof = detect_project_profile(ws)
        if prof.test_cmd:
            exe = shutil.which(prof.test_cmd[0])
            if exe:
                proc = _run_cmd([exe, *prof.test_cmd[1:]], timeout=90, cwd=str(ws))
                unit_ok = (proc.returncode == 0)
                unit_out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                if not unit_ok:
                    defects.append(f"unit test command failed: {' '.join(prof.test_cmd)}")
            else:
                notes.append(f"test runner '{prof.test_cmd[0]}' not installed on PATH; skipped unit tests.")
        else:
            notes.append("No native mobile/unit test command detected in workspace profile.")
    except Exception as exc:
        notes.append(f"profile/unit test step skipped: {exc}")

    web_url = (fallback_web_url or str(eff_cfg.get("BAIZE_MOBILE_FALLBACK_WEB_URL", "") or "")).strip()
    web_rep_dict: dict[str, Any] | None = None
    if web_url:
        try:
            from .visual_verify import verify_ui
            vrep = verify_ui(web_url, viewports=["mobile"], check_visual=check_visual, cfg=eff_cfg, client=client)
            web_rep_dict = vrep.to_dict()
            if not vrep.ok:
                defects.extend([f"web_preview: {d}" for d in vrep.defects])
        except Exception as exc:
            defects.append(f"web_preview failed: {exc}")

    overall_ok = (len(defects) == 0) and (unit_ok is not False)
    return MobileVerifyReport(
        ok=overall_ok,
        mode="degraded-unit-and-web",
        degraded=True,
        devices=all_devs,
        active_device="",
        unit_test_ok=unit_ok,
        unit_test_output=unit_out,
        web_preview_report=web_rep_dict,
        defects=defects,
        notes=notes,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )
