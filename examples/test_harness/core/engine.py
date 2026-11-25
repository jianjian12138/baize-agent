"""Declarative scenario execution engine with structured JSON evidence & JUnit XML export."""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .drivers import HttpDriver, check_ui_contract, json_extract
from .env import HarnessWorld
from .oracles import (
    evaluate_http_expect,
    evaluate_log_invariants,
    evaluate_sql_invariants,
    run_python_oracle_hook,
)

_TPL_RE = re.compile(r"\{\{([A-Za-z0-9_.-]+)\}\}")


def _render_vars(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        # Exact full-token match preserves int/bool/float type when substituting JSON fields
        m_full = _TPL_RE.fullmatch(value)
        if m_full:
            k = m_full.group(1)
            if k == "uuid":
                return uuid.uuid4().hex[:10]
            if k in ctx:
                return ctx[k]
        def _repl(m: re.Match) -> str:
            k = m.group(1)
            if k == "uuid":
                return uuid.uuid4().hex[:10]
            return str(ctx.get(k, m.group(0)))
        return _TPL_RE.sub(_repl, value)
    if isinstance(value, list):
        return [_render_vars(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _render_vars(v, ctx) for k, v in value.items()}
    return value


def load_scenarios(cfg: dict[str, Any], config_dir: Path) -> list[dict[str, Any]]:
    raw = cfg.get("scenarios")
    if isinstance(raw, list):
        return raw
    sc_file = cfg.get("scenarios_file")
    if sc_file:
        p = Path(str(sc_file))
        if not p.is_absolute():
            p = (config_dir / p).resolve()
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
            return data["scenarios"]
        if isinstance(data, list):
            return data
    raise ValueError("Harness config must define 'scenarios' list or 'scenarios_file'.")


def _execute_step(
    step: dict[str, Any],
    *,
    world: HarnessWorld,
    http: HttpDriver,
    ctx: dict[str, Any],
    config_dir: Path,
) -> list[str]:
    kind = str(step.get("type", "http")).strip().lower()
    errors: list[str] = []

    if kind == "http":
        method = str(step.get("method", "GET")).upper()
        path = str(_render_vars(step.get("path", "/"), ctx))
        body = _render_vars(step.get("json"), ctx) if "json" in step else None
        headers = _render_vars(step.get("headers"), ctx) if "headers" in step else None
        resp = http.request(method, path, json_body=body, headers=headers)
        expect = _render_vars(step.get("expect") or {}, ctx)
        errors.extend(evaluate_http_expect(resp, expect))
        for var_name, expr in (step.get("save") or {}).items():
            ctx[var_name] = json_extract(resp.get("json"), str(expr))
        return errors

    if kind == "concurrent_http":
        count = int(step.get("count", 4))
        workers = int(step.get("workers", min(count, 8)))
        method = str(step.get("method", "POST")).upper()
        path = str(_render_vars(step.get("path", "/"), ctx))

        def _one(idx: int) -> int:
            local_ctx = dict(ctx, idx=idx)
            local_body = _render_vars(step.get("json"), local_ctx) if "json" in step else None
            local_hdrs = _render_vars(step.get("headers"), local_ctx) if "headers" in step else None
            d = HttpDriver(world.base_url, default_headers=http.default_headers)
            return int(d.request(method, path, json_body=local_body, headers=local_hdrs)["status"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            statuses = list(ex.map(_one, range(count)))
        ctx["_last_concurrent_statuses"] = statuses
        dist = {str(s): statuses.count(s) for s in sorted(set(statuses))}
        for code_str, expected_cnt in (step.get("expect_status_counts") or {}).items():
            actual_cnt = statuses.count(int(code_str))
            if actual_cnt != int(expected_cnt):
                errors.append(
                    f"Concurrent HTTP status {code_str}: expected {expected_cnt}, got {actual_cnt} (all={dist})"
                )
        return errors

    if kind == "ui_contract":
        path = str(_render_vars(step.get("path", "/"), ctx))
        resp = http.request("GET", path)
        if resp["status"] != 200:
            errors.append(f"UI GET {path} returned HTTP {resp['status']}")
            return errors
        js_rel = str(step.get("js_file") or "").strip()
        js_path = None
        if js_rel:
            p = Path(js_rel)
            js_path = p if p.is_absolute() else (config_dir / p).resolve()
        errors.extend(
            check_ui_contract(
                html=resp["text"],
                required_markers=list(step.get("required_markers") or []),
                js_file=js_path,
                node_eval=str(step.get("node_eval") or ""),
            )
        )
        return errors

    if kind == "sql_invariant":
        return evaluate_sql_invariants(world.db_path, list(step.get("checks") or []))

    if kind == "oracle_hook":
        hook = str(step.get("hook") or "").strip()
        return run_python_oracle_hook(hook, world=world, context=ctx, config_dir=config_dir)

    return [f"Unknown step type: {kind!r}"]


def run_harness(
    *,
    cfg: dict[str, Any],
    config_dir: Path,
    artifacts_dir: Path,
    suite: str = "all",
    scenario_ids: list[str] | None = None,
    override_base_url: str = "",
) -> dict[str, Any]:
    all_scenarios = load_scenarios(cfg, config_dir)
    selected = []
    for sc in all_scenarios:
        if scenario_ids and sc.get("id") not in scenario_ids:
            continue
        if suite != "all" and sc.get("suite", "e2e") != suite:
            continue
        selected.append(sc)

    target_cfg = dict(cfg.get("target") or {})
    default_headers = dict(cfg.get("default_headers") or {})
    global_oracles = list(cfg.get("global_oracles") or [])
    forbidden_log_markers = cfg.get("forbidden_log_markers")
    isolate_per_scenario = bool(cfg.get("isolate_per_scenario", target_cfg.get("mode") == "command"))

    artifacts_dir = Path(artifacts_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    t_suite = time.monotonic()
    results: list[dict[str, Any]] = []
    infra_error: str | None = None

    def _run_one(sc: dict[str, Any], world: HarnessWorld) -> dict[str, Any]:
        t0 = time.monotonic()
        http = HttpDriver(world.base_url, default_headers=default_headers)
        ctx: dict[str, Any] = {"base_url": world.base_url}
        failures: list[str] = []
        for idx, step in enumerate(sc.get("steps") or []):
            step_errs = _execute_step(step, world=world, http=http, ctx=ctx, config_dir=config_dir)
            if step_errs:
                step_label = step.get("name") or f"step#{idx+1}({step.get('type', 'http')})"
                failures.extend([f"[{step_label}] {e}" for e in step_errs])
                if step.get("stop_on_fail", True):
                    break

        if not failures:
            for hook in global_oracles:
                failures.extend(run_python_oracle_hook(str(hook), world=world, context=ctx, config_dir=config_dir))
            if not sc.get("allow_server_errors", False):
                failures.extend(evaluate_log_invariants(world.read_logs(), forbidden_log_markers))

        passed = len(failures) == 0
        return {
            "scenario_id": str(sc.get("id") or "unnamed"),
            "suite": str(sc.get("suite") or "e2e"),
            "description": str(sc.get("description") or ""),
            "passed": passed,
            "duration_ms": round((time.monotonic() - t0) * 1000.0, 2),
            "failure_reason": "; ".join(failures),
            "failures": failures,
            "transcript": http.transcript[-8:],
            "server_log_tail": world.read_logs()[-600:] if not passed else "",
        }

    if isolate_per_scenario:
        for sc in selected:
            sc_id = str(sc.get("id") or "unnamed")
            try:
                with HarnessWorld(
                    target_cfg=target_cfg,
                    config_dir=config_dir,
                    artifacts_dir=artifacts_dir / sc_id,
                    override_base_url=override_base_url,
                ) as world:
                    results.append(_run_one(sc, world))
            except Exception as exc:
                infra_error = f"INFRA_ERROR: {type(exc).__name__}: {exc}"
                results.append({
                    "scenario_id": sc_id,
                    "suite": str(sc.get("suite") or "e2e"),
                    "description": str(sc.get("description") or ""),
                    "passed": False,
                    "duration_ms": 0.0,
                    "failure_reason": infra_error,
                    "failures": [infra_error],
                    "transcript": [],
                    "server_log_tail": "",
                })
    else:
        try:
            with HarnessWorld(
                target_cfg=target_cfg,
                config_dir=config_dir,
                artifacts_dir=artifacts_dir / "_shared_world",
                override_base_url=override_base_url,
            ) as world:
                for sc in selected:
                    results.append(_run_one(sc, world))
        except Exception as exc:
            infra_error = f"INFRA_ERROR: {type(exc).__name__}: {exc}"
            for sc in selected:
                results.append({
                    "scenario_id": str(sc.get("id") or "unnamed"),
                    "suite": str(sc.get("suite") or "e2e"),
                    "description": str(sc.get("description") or ""),
                    "passed": False,
                    "duration_ms": 0.0,
                    "failure_reason": infra_error,
                    "failures": [infra_error],
                    "transcript": [],
                    "server_log_tail": "",
                })

    passed_cnt = sum(1 for r in results if r["passed"])
    failed_cnt = len(results) - passed_cnt
    exit_code = 0 if failed_cnt == 0 else (2 if infra_error else 1)
    report = {
        "service": str(cfg.get("service_name") or "target-service"),
        "suite": suite,
        "total": len(results),
        "passed": passed_cnt,
        "failed": failed_cnt,
        "exit_code": exit_code,
        "duration_ms": round((time.monotonic() - t_suite) * 1000.0, 2),
        "results": results,
    }
    (artifacts_dir / "latest_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def write_junit_xml(report: dict[str, Any], out_path: Path) -> None:
    """Export standard JUnit XML for GitHub Actions / GitLab CI / Jenkins."""
    ts = ET.Element(
        "testsuite",
        attrib={
            "name": f"{report.get('service', 'harness')}:{report.get('suite', 'all')}",
            "tests": str(report.get("total", 0)),
            "failures": str(report.get("failed", 0)),
            "time": str(round(float(report.get("duration_ms", 0.0)) / 1000.0, 3)),
        },
    )
    for r in report.get("results") or []:
        tc = ET.SubElement(
            ts,
            "testcase",
            attrib={
                "classname": str(r.get("suite", "e2e")),
                "name": str(r.get("scenario_id", "unnamed")),
                "time": str(round(float(r.get("duration_ms", 0.0)) / 1000.0, 3)),
            },
        )
        if not r.get("passed"):
            fail = ET.SubElement(tc, "failure", attrib={"message": str(r.get("failure_reason", "failed"))[:240]})
            fail.text = json.dumps(
                {"failures": r.get("failures"), "transcript": r.get("transcript"), "log_tail": r.get("server_log_tail")},
                indent=2,
                ensure_ascii=False,
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(ts).write(out_path, encoding="utf-8", xml_declaration=True)
