#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chummer6_runtime_config import load_local_env, load_runtime_overrides

EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
API_BASE = "https://api.browseract.com/v2/workflow"
RUNTIME_DIR = Path("/docker/fleet/state/browseract_bootstrap/runtime")

LOCAL_ENV = load_local_env()
POLICY_ENV = load_runtime_overrides()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


def browseract_key() -> str:
    for key_name in (
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
        "BROWSERACT_API_KEY_FALLBACK_2",
        "BROWSERACT_API_KEY_FALLBACK_3",
    ):
        value = env_value(key_name)
        if value:
            return value
    return ""


def api_request(method: str, path: str, *, payload: dict[str, object] | None = None, query: dict[str, str] | None = None) -> dict[str, object]:
    key = browseract_key()
    if not key:
        raise RuntimeError("browseract:not_configured")
    url = API_BASE.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "EA-Chummer6-BrowserActHumanizer/1.0",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"browseract:http_{exc.code}:{body[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"browseract:urlerror:{exc.reason}") from exc
    try:
        loaded = json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"browseract:non_json:{body[:240]}") from exc
    return loaded if isinstance(loaded, dict) else {"data": loaded}


def list_workflows() -> list[dict[str, object]]:
    body = api_request("GET", "/list-workflows")
    for key in ("workflows", "data", "items", "rows"):
        value = body.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
    if isinstance(body, dict):
        return [body]
    return []


def workflow_fields(entry: dict[str, object]) -> tuple[str, str]:
    workflow_id = str(
        entry.get("workflow_id")
        or entry.get("id")
        or entry.get("_id")
        or entry.get("workflowId")
        or ""
    ).strip()
    name = str(entry.get("name") or entry.get("title") or entry.get("workflow_name") or "").strip()
    return workflow_id, name


def resolve_workflow() -> tuple[str, str]:
    explicit = env_value("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID")
    if explicit:
        return explicit, "explicit"
    query = env_value("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY") or "chummer6 undetectable humanizer"
    lowered = query.lower()
    for entry in list_workflows():
        workflow_id, name = workflow_fields(entry)
        haystack = " ".join(
            str(entry.get(field) or "")
            for field in ("name", "title", "description", "slug", "workflow_name")
        ).lower()
        if workflow_id and lowered in haystack:
            return workflow_id, name or lowered
    raise RuntimeError("browseract:humanizer_workflow_not_found")


def run_task(*, workflow_id: str, text: str, target: str) -> dict[str, object]:
    payloads = [
        {"workflow_id": workflow_id, "input_parameters": [{"name": "text", "value": text}, {"name": "target", "value": target}]},
        {"workflow_id": workflow_id, "input_parameters": [{"name": "prompt", "value": text}, {"name": "target", "value": target}]},
        {"workflow_id": workflow_id, "input_parameters": [{"key": "text", "value": text}, {"key": "target", "value": target}]},
        {"workflow_id": workflow_id, "input_parameters": [{"text": text, "target": target}]},
    ]
    last_error = "browseract:run_task_failed"
    for payload in payloads:
        try:
            return api_request("POST", "/run-task", payload=payload)
        except RuntimeError as exc:
            last_error = str(exc)
            continue
    raise RuntimeError(last_error)


def _task_id(body: dict[str, object]) -> str:
    for key in ("task_id", "id", "_id"):
        value = str(body.get(key) or "").strip()
        if value:
            return value
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("task_id", "id", "_id"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
    raise RuntimeError("browseract:missing_task_id")


def _task_status(body: dict[str, object]) -> str:
    for key in ("status", "task_status", "state"):
        value = str(body.get(key) or "").strip()
        if value:
            return value.lower()
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("status", "task_status", "state"):
            value = str(data.get(key) or "").strip()
            if value:
                return value.lower()
    return ""


def _task_steps(body: dict[str, object]) -> list[dict[str, object]]:
    steps = body.get("steps")
    if isinstance(steps, list):
        return [entry for entry in steps if isinstance(entry, dict)]
    data = body.get("data")
    if isinstance(data, dict):
        nested = data.get("steps")
        if isinstance(nested, list):
            return [entry for entry in nested if isinstance(entry, dict)]
    return []


def _task_step_goals(body: dict[str, object]) -> list[str]:
    goals: list[str] = []
    for step in _task_steps(body):
        goal = str(step.get("step_goal") or "").strip()
        if goal:
            goals.append(goal)
    return goals


def min_words() -> int:
    raw = env_value("CHUMMER6_BROWSERACT_HUMANIZER_MIN_WORDS") or env_value("CHUMMER6_TEXT_HUMANIZER_MIN_WORDS") or "50"
    try:
        return max(1, int(raw))
    except Exception:
        return 50


def humanizer_timeout_seconds() -> int:
    raw = env_value("CHUMMER6_BROWSERACT_HUMANIZER_TIMEOUT_SECONDS") or env_value("CHUMMER6_TEXT_HUMANIZER_TIMEOUT_SECONDS") or "90"
    try:
        return max(30, int(raw))
    except Exception:
        return 90


def auto_repair_enabled() -> bool:
    raw = env_value("CHUMMER6_BROWSERACT_HUMANIZER_AUTO_REPAIR")
    if not raw:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\\-]*", str(text or "")))


def _slugify(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered or "workflow"


def _runtime_workflow_stem() -> str:
    explicit = env_value("CHUMMER6_BROWSERACT_HUMANIZER_RUNTIME_WORKFLOW")
    if explicit:
        return _slugify(explicit)
    workflow_id = env_value("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID")
    if workflow_id:
        return _slugify(workflow_id)
    query = env_value("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY") or "undetectable_humanizer_live"
    if "humanizer" in query.lower():
        return _slugify(query)
    return "undetectable_humanizer_live"


def _candidate_spec_paths() -> list[Path]:
    explicit = env_value("CHUMMER6_BROWSERACT_HUMANIZER_SPEC_PATH")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    stem = _runtime_workflow_stem()
    candidates.extend(
        [
            RUNTIME_DIR / f"{stem}.workflow.json",
            RUNTIME_DIR / "undetectable_humanizer_live.workflow.json",
            RUNTIME_DIR / "undetectable_humanizer_v4.workflow.json",
        ]
    )
    discovered = sorted(RUNTIME_DIR.glob("*humanizer*.workflow.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in discovered:
        if path not in candidates:
            candidates.append(path)
    return [path for path in candidates if path.exists()]


def _load_current_spec() -> tuple[dict[str, object], Path | None]:
    for path in _candidate_spec_paths():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(loaded, dict):
            return dict(loaded), path
    return {}, None


def _repair_goals_from_message(message: str) -> list[str]:
    parts = [part.strip() for part in str(message or "").split("|") if part.strip()]
    return parts[:4]


def _ea_orchestrator():
    app_root = str(EA_ROOT / "ea")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    scripts_root = str(EA_ROOT / "scripts")
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    from app.container import build_container
    from bootstrap_browseract_workflow_repair_skill import apply_skill_payload, build_skill_payload

    container = build_container()
    apply_skill_payload(container.skills, build_skill_payload())
    return container.orchestrator


def _persist_repair_packet(packet: dict[str, object], *, workflow_name: str) -> tuple[Path, Path]:
    slug = _slugify(workflow_name)
    workflow_spec = dict(packet.get("workflow_spec") or {})
    packet_path = RUNTIME_DIR / f"{slug}.repair.packet.json"
    spec_path = RUNTIME_DIR / f"{slug}.repair.workflow.json"
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    spec_path.write_text(json.dumps(workflow_spec, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return packet_path, spec_path


def request_workflow_repair(*, workflow_name: str, purpose: str, tool_url: str, failure_summary: str, failure_goals: list[str], current_spec: dict[str, object], login_url: str = "public") -> dict[str, object]:
    app_root = str(EA_ROOT / "ea")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    from app.domain.models import TaskExecutionRequest

    artifact = _ea_orchestrator().execute_task_artifact(
        TaskExecutionRequest(
            skill_key="browseract_workflow_repair_manager",
            principal_id="ea-browseract-humanizer",
            goal="Repair a failing BrowserAct workflow spec after a runtime execution failure.",
            input_json={
                "workflow_name": workflow_name,
                "purpose": purpose,
                "login_url": login_url,
                "tool_url": tool_url,
                "failure_summary": failure_summary,
                "failing_step_goals": failure_goals,
                "current_workflow_spec_json": current_spec,
                "output_dir": str(RUNTIME_DIR),
            },
        )
    )
    structured = dict(getattr(artifact, "structured_output_json", {}) or {})
    if not structured:
        raise RuntimeError("browseract:repair_empty_artifact")
    packet = dict(structured.get("workflow_spec") and structured or structured.get("result") or structured)
    if "workflow_spec" not in packet:
        raise RuntimeError("browseract:repair_missing_workflow_spec")
    packet_path, spec_path = _persist_repair_packet(packet, workflow_name=workflow_name)
    print(f"browseract_repair_packet={packet_path}", file=sys.stderr)
    print(f"browseract_repair_spec={spec_path}", file=sys.stderr)
    return packet


def maybe_request_workflow_repair(*, failure_summary: str, failure_goals: list[str] | None = None) -> None:
    if not auto_repair_enabled():
        return
    current_spec, spec_path = _load_current_spec()
    workflow_name = str((current_spec.get("workflow_name") if isinstance(current_spec, dict) else "") or _runtime_workflow_stem()).strip() or _runtime_workflow_stem()
    purpose = str((current_spec.get("description") if isinstance(current_spec, dict) else "") or "Repair the Undetectable AI BrowserAct humanizer workflow for Chummer6 copy blocks.").strip()
    tool_url = ""
    if isinstance(current_spec, dict):
        nodes = current_spec.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict) and isinstance(node.get("config"), dict):
                    candidate = str((node.get("config") or {}).get("url") or "").strip()
                    if candidate:
                        tool_url = candidate
                        break
    if not tool_url:
        tool_url = "https://undetectable.ai/ai-humanizer"
    goals = list(failure_goals or [])
    if not goals:
        goals = _repair_goals_from_message(failure_summary)
    try:
        request_workflow_repair(
            workflow_name=workflow_name,
            purpose=purpose,
            tool_url=tool_url,
            login_url="public",
            failure_summary=failure_summary,
            failure_goals=goals,
            current_spec=current_spec,
        )
        if spec_path is not None:
            print(f"browseract_repair_source={spec_path}", file=sys.stderr)
    except Exception as exc:
        print(f"browseract_repair_failed={str(exc)[:240]}", file=sys.stderr)


def wait_for_task(task_id: str, *, timeout_seconds: int = 20) -> dict[str, object]:
    deadline = time.time() + max(30, int(timeout_seconds))
    last_status = ""
    while time.time() < deadline:
        status_body = api_request("GET", "/get-task-status", query={"task_id": task_id})
        status = _task_status(status_body)
        if status:
            last_status = status
        if status in {"done", "completed", "success", "succeeded", "finished"}:
            return api_request("GET", "/get-task", query={"task_id": task_id})
        finished_at = str(status_body.get("finished_at") or "").strip()
        if not finished_at:
            data = status_body.get("data")
            if isinstance(data, dict):
                finished_at = str(data.get("finished_at") or "").strip()
        if finished_at and status not in {"running", "queued", "processing", "in_progress"}:
            return api_request("GET", "/get-task", query={"task_id": task_id})
        if status in {"failed", "error", "cancelled", "canceled"}:
            detail = json.dumps(status_body, ensure_ascii=True)[:400]
            raise RuntimeError(f"browseract:task_failed:{detail}")
        time.sleep(5)
    full = api_request("GET", "/get-task", query={"task_id": task_id})
    goals = " | ".join(_task_step_goals(full)[:3]).strip()
    detail = f":{goals}" if goals else ""
    raise RuntimeError(f"browseract:task_timeout:{last_status or 'unknown'}{detail}")


def _collect_strings(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        normalized = str(value or "").strip()
        if normalized:
            found.append(normalized)
        return found
    if isinstance(value, dict):
        for nested in value.values():
            found.extend(_collect_strings(nested))
        return found
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            found.extend(_collect_strings(nested))
    return found


def _collect_humanized_candidates(body: dict[str, object]) -> list[str]:
    candidates: list[str] = []
    output = body.get("output")
    if isinstance(output, dict):
        raw = output.get("string")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        value = str(
                            item.get("humanized_text")
                            or item.get("rewritten_text")
                            or item.get("result")
                            or item.get("output")
                            or ""
                        ).strip()
                        if value:
                            candidates.append(value)
    return candidates


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']{2,}", text.lower())
        if len(token) >= 5
        and token
        not in {
            "about",
            "above",
            "after",
            "again",
            "among",
            "being",
            "below",
            "could",
            "first",
            "found",
            "from",
            "helps",
            "into",
            "their",
            "there",
            "these",
            "thing",
            "think",
            "those",
            "under",
            "understand",
            "using",
            "where",
            "which",
            "while",
            "would",
            "your",
        }
    }


def extract_humanized_text(body: dict[str, object], original_text: str) -> str:
    candidates = _collect_humanized_candidates(body)
    original_tokens = _token_set(original_text)
    scored: list[tuple[int, int, str]] = []
    for value in candidates:
        lowered = value.lower()
        if len(value) <= 40 or "http" in lowered or lowered.startswith("task_") or "workflow" in lowered:
            continue
        overlap = len(_token_set(value) & original_tokens)
        scored.append((overlap, len(value), value))
    if scored:
        scored.sort(reverse=True)
        best_overlap, _best_len, best_value = scored[0]
        if best_overlap > 0:
            return best_value
        raise RuntimeError("browseract:humanizer_output_mismatch")
    raise RuntimeError("browseract:no_humanized_text")


def cmd_list_workflows() -> int:
    rows = []
    for entry in list_workflows():
        workflow_id, name = workflow_fields(entry)
        rows.append({"workflow_id": workflow_id, "name": name})
    print(json.dumps({"workflows": rows}, indent=2, ensure_ascii=True))
    return 0


def cmd_check() -> int:
    workflow_id, name = resolve_workflow()
    print(json.dumps({"status": "ready", "workflow_id": workflow_id, "workflow_name": name}, ensure_ascii=True))
    return 0


def cmd_humanize(text: str, target: str) -> int:
    if word_count(text) < min_words():
        raise RuntimeError(f"browseract:below_min_words:{word_count(text)}<{min_words()}")
    workflow_id, _name = resolve_workflow()
    try:
        task = run_task(workflow_id=workflow_id, text=text, target=target)
        task_id = _task_id(task)
        print(f"browseract_task_id={task_id}", file=sys.stderr)
        body = wait_for_task(task_id, timeout_seconds=humanizer_timeout_seconds())
    except RuntimeError as exc:
        maybe_request_workflow_repair(failure_summary=str(exc))
        raise
    goals = _task_step_goals(body)
    if any('Input "/text' in goal or "Input '/text" in goal for goal in goals):
        maybe_request_workflow_repair(
            failure_summary="browseract:literal_input_binding:/text",
            failure_goals=goals,
        )
        raise RuntimeError("browseract:literal_input_binding:/text")
    if len(goals) <= 2:
        detail = f"browseract:incomplete_workflow:{' | '.join(goals) or 'no_steps'}"
        maybe_request_workflow_repair(failure_summary=detail, failure_goals=goals)
        raise RuntimeError(detail)
    print(extract_humanized_text(body, text))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="BrowserAct Undetectable Humanizer helper for Chummer6.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-workflows")
    sub.add_parser("check")
    humanize = sub.add_parser("humanize")
    humanize.add_argument("--text", required=True)
    humanize.add_argument("--target", default="")
    args = parser.parse_args()
    if args.command == "list-workflows":
        return cmd_list_workflows()
    if args.command == "check":
        return cmd_check()
    if args.command == "humanize":
        return cmd_humanize(args.text, args.target)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
