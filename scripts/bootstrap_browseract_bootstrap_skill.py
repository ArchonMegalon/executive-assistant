#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
HOST = os.environ.get("EA_SKILL_HOST", "http://127.0.0.1:8090")


def env_value(name: str) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return ""


def upsert_skill(body: dict[str, object]) -> dict[str, object]:
    token = env_value("EA_API_TOKEN")
    request = urllib.request.Request(
        f"{HOST}/v1/skills",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    skill = {
        "skill_key": "browseract_bootstrap_manager",
        "task_key": "browseract_bootstrap_manager",
        "name": "BrowserAct Bootstrap Manager",
        "description": "Build prepared BrowserAct workflow specs and architect packets for stage-0 workflow materialization.",
        "deliverable_type": "browseract_workflow_spec_packet",
        "default_risk_class": "medium",
        "default_approval_class": "operator",
        "workflow_template": "artifact_then_memory_candidate",
        "allowed_tools": [],
        "evidence_requirements": ["target_domain_brief", "workflow_spec", "browseract_seed_state"],
        "memory_write_policy": "none",
        "memory_reads": ["entities", "relationships"],
        "memory_writes": [],
        "tags": ["browseract", "bootstrap", "workflow", "architect"],
        "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
        "provider_hints_json": {
            "primary": ["BrowserAct"],
            "secondary": ["Codex"],
            "notes": ["Stage-0 architect compiles prepared specs into BrowserAct workflows."],
        },
        "tool_policy_json": {"allowed_tools": []},
        "human_policy_json": {"review_roles": ["automation_architect"]},
        "evaluation_cases_json": [{"case_key": "browseract_bootstrap_manager_golden", "priority": "medium"}],
        "budget_policy_json": {
            "class": "medium",
            "workflow_template": "artifact_then_memory_candidate",
            "skill_catalog_json": {
                "mode": "spec_compiler",
                "capabilities": ["workflow_spec", "builder_packet", "seed_validation"],
            },
        },
    }
    try:
        result = upsert_skill(skill)
    except urllib.error.URLError as exc:
        print(json.dumps({"status": "skipped", "reason": f"api_unavailable:{exc.reason}"}))
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        print(json.dumps({"status": "skipped", "reason": f"http_{exc.code}", "body": body[:240]}))
        return 0
    print(json.dumps({"status": "ok", "skill_key": result.get("skill_key", "")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
