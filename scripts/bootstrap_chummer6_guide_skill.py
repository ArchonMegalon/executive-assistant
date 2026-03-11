#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
HOST = os.environ.get("EA_SKILL_HOST", "http://127.0.0.1:8080")


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
        "skill_key": "chummer6_guide_refresh",
        "task_key": "chummer6_guide_refresh",
        "name": "Chummer6 Guide Refresh",
        "description": "Generate human-facing Chummer6 guide copy and art from canonical sources, with provider-aware text and media hints.",
        "deliverable_type": "chummer6_guide_refresh_packet",
        "default_risk_class": "low",
        "default_approval_class": "none",
        "workflow_template": "rewrite",
        "allowed_tools": [],
        "evidence_requirements": ["repo_readmes", "design_scope", "public_status"],
        "memory_write_policy": "none",
        "memory_reads": ["entities", "relationships"],
        "memory_writes": [],
        "tags": ["chummer6", "guide", "docs", "media"],
        "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
        "provider_hints_json": {
            "primary": ["1min.AI", "AI Magicx", "Prompting Systems"],
            "research": ["BrowserAct"],
            "output": ["MarkupGo", "AI Magicx", "Prompting Systems"],
            "media": ["AI Magicx", "MarkupGo", "Prompting Systems"],
        },
        "tool_policy_json": {"allowed_tools": []},
        "human_policy_json": {"review_roles": ["guide_reviewer"]},
        "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
        "budget_policy_json": {
            "class": "low",
            "workflow_template": "rewrite",
            "skill_catalog_json": {
                "mode": "downstream_only",
                "capabilities": ["human_guide_copy", "guide_media_rendering", "tone_audit"],
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
