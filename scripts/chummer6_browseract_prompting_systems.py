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
        "User-Agent": "EA-Chummer6-BrowserAct/1.0",
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


def resolve_workflow(kind: str) -> tuple[str, str]:
    normalized = str(kind or "").strip().upper()
    key_prefixes = {
        "REFINE": "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS",
        "PROMPTING_RENDER": "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS",
        "MAGIXAI_RENDER": "CHUMMER6_BROWSERACT_MAGIXAI",
    }
    key_suffixes = {
        "REFINE": "REFINE",
        "PROMPTING_RENDER": "RENDER",
        "MAGIXAI_RENDER": "RENDER",
    }
    prefix = key_prefixes.get(normalized, "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS")
    suffix = key_suffixes.get(normalized, normalized)
    explicit = env_value(f"{prefix}_{suffix}_WORKFLOW_ID")
    if explicit:
        return explicit, "explicit"
    query = env_value(f"{prefix}_{suffix}_WORKFLOW_QUERY")
    default_queries = {
        "REFINE": [
            "chummer6 prompting systems refine",
            "prompting systems refine",
            "prompt refine",
        ],
        "PROMPTING_RENDER": [
            "chummer6 prompting systems render",
            "prompting systems render",
            "image render",
        ],
        "MAGIXAI_RENDER": [
            "chummer6 magicx render",
            "chummer6 ai magicx render",
            "magicx render",
            "aimagicx render",
        ],
    }
    queries = [query] if query else default_queries.get(normalized, [])
    workflows = list_workflows()
    for needle in queries:
        lowered = str(needle or "").strip().lower()
        if not lowered:
            continue
        for entry in workflows:
            workflow_id, name = workflow_fields(entry)
            haystack = " ".join(
                str(entry.get(field) or "")
                for field in ("name", "title", "description", "slug", "workflow_name")
            ).lower()
            if workflow_id and lowered in haystack:
                return workflow_id, name or lowered
    raise RuntimeError(f"browseract:{normalized.lower()}_workflow_not_found")


def _input_payloads(*, prompt: str, target: str, width: int, height: int, output_path: str) -> list[list[dict[str, object]]]:
    return [
        [
            {"name": "prompt", "value": prompt},
            {"name": "target", "value": target},
            {"name": "width", "value": width},
            {"name": "height", "value": height},
            {"name": "output_path", "value": output_path},
        ],
        [
            {"key": "prompt", "value": prompt},
            {"key": "target", "value": target},
            {"key": "width", "value": width},
            {"key": "height", "value": height},
            {"key": "output_path", "value": output_path},
        ],
        [
            {"prompt": prompt, "target": target, "width": width, "height": height, "output_path": output_path},
        ],
    ]


def run_task(*, workflow_id: str, prompt: str, target: str, width: int, height: int, output_path: str) -> dict[str, object]:
    last_error = "browseract:run_task_failed"
    for input_parameters in _input_payloads(prompt=prompt, target=target, width=width, height=height, output_path=output_path):
        try:
            return api_request(
                "POST",
                "/run-task",
                payload={"workflow_id": workflow_id, "input_parameters": input_parameters},
            )
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


def wait_for_task(task_id: str, *, timeout_seconds: int = 600) -> dict[str, object]:
    deadline = time.time() + max(30, int(timeout_seconds))
    last_status = ""
    while time.time() < deadline:
        status_body = api_request("GET", "/get-task-status", query={"task_id": task_id})
        status = _task_status(status_body)
        if status:
            last_status = status
        if status in {"done", "completed", "success", "succeeded", "finished"}:
            return api_request("GET", "/get-task", query={"task_id": task_id})
        if status in {"failed", "error", "cancelled", "canceled"}:
            detail = json.dumps(status_body, ensure_ascii=True)[:400]
            raise RuntimeError(f"browseract:task_failed:{detail}")
        time.sleep(5)
    raise RuntimeError(f"browseract:task_timeout:{last_status or 'unknown'}")


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


def extract_refined_prompt(body: dict[str, object]) -> str:
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
                            item.get("generated_prompt")
                            or item.get("refined_prompt")
                            or item.get("result")
                            or item.get("output")
                            or ""
                        ).strip()
                        if value:
                            candidates.append(value)
            elif len(raw.strip()) > 40:
                candidates.append(raw.strip())
    scored = [
        value for value in candidates
        if len(value) > 40 and "http" not in value.lower() and not value.lower().startswith("task_")
    ]
    if scored:
        scored.sort(key=len, reverse=True)
        best = scored[0]
        if "ready to generate" not in best.lower():
            return best
    raise RuntimeError("browseract:no_refined_prompt")


def extract_image_url(body: dict[str, object]) -> str:
    for value in _collect_strings(body):
        if value.startswith("http://") or value.startswith("https://"):
            lowered = value.lower()
            if any(token in lowered for token in (".png", ".jpg", ".jpeg", ".webp", "image", "render", "download", "cdn")):
                return value
    raise RuntimeError("browseract:no_image_url")


def download(url: str, output_path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-BrowserAct/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)


def cmd_list_workflows() -> int:
    rows = []
    for entry in list_workflows():
        workflow_id, name = workflow_fields(entry)
        rows.append({"workflow_id": workflow_id, "name": name})
    print(json.dumps({"workflows": rows}, indent=2, ensure_ascii=True))
    return 0


def cmd_check(kind: str) -> int:
    workflow_id, name = resolve_workflow(kind)
    print(json.dumps({"status": "ready", "kind": kind.lower(), "workflow_id": workflow_id, "workflow_name": name}, ensure_ascii=True))
    return 0


def cmd_refine(prompt: str, target: str) -> int:
    workflow_id, _name = resolve_workflow("REFINE")
    task = run_task(workflow_id=workflow_id, prompt=prompt, target=target, width=0, height=0, output_path="")
    task_id = _task_id(task)
    print(f"browseract_task_id={task_id}", file=sys.stderr)
    body = wait_for_task(task_id, timeout_seconds=300)
    print(extract_refined_prompt(body))
    return 0


def cmd_render(prompt: str, target: str, output_path: Path, width: int, height: int, *, kind: str) -> int:
    workflow_id, _name = resolve_workflow(kind)
    task = run_task(workflow_id=workflow_id, prompt=prompt, target=target, width=width, height=height, output_path=str(output_path))
    task_id = _task_id(task)
    print(f"browseract_task_id={task_id}", file=sys.stderr)
    body = wait_for_task(task_id, timeout_seconds=900)
    download(extract_image_url(body), output_path)
    print(json.dumps({"status": "rendered", "output": str(output_path)}, ensure_ascii=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="BrowserAct Prompting Systems helper for Chummer6.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-workflows")
    check = sub.add_parser("check")
    check.add_argument("--kind", choices=("refine", "prompting_render", "magixai_render"), required=True)
    refine = sub.add_parser("refine")
    refine.add_argument("--prompt", required=True)
    refine.add_argument("--target", default="")
    render = sub.add_parser("render")
    render.add_argument("--prompt", required=True)
    render.add_argument("--target", default="")
    render.add_argument("--output", required=True)
    render.add_argument("--width", type=int, default=1280)
    render.add_argument("--height", type=int, default=720)
    render.add_argument("--kind", choices=("prompting_render", "magixai_render"), default="prompting_render")
    args = parser.parse_args()
    if args.command == "list-workflows":
        return cmd_list_workflows()
    if args.command == "check":
        return cmd_check(args.kind)
    if args.command == "refine":
        return cmd_refine(args.prompt, args.target)
    if args.command == "render":
        return cmd_render(args.prompt, args.target, Path(args.output), args.width, args.height, kind=args.kind)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
