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


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
API_BASE = "https://api.browseract.com/v2/workflow"


def load_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


LOCAL_ENV = load_local_env()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or "").strip()


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
    workflow_id, _name = resolve_workflow()
    task = run_task(workflow_id=workflow_id, text=text, target=target)
    task_id = _task_id(task)
    print(f"browseract_task_id={task_id}", file=sys.stderr)
    body = wait_for_task(task_id, timeout_seconds=600)
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
