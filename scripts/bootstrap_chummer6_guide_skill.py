#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
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


def _common_skill_fields() -> dict[str, object]:
    return {
        "task_key": "chummer6_guide_refresh",
        "deliverable_type": "chummer6_guide_refresh_packet",
        "default_risk_class": "low",
        "default_approval_class": "none",
        "workflow_template": "tool_then_artifact",
        "allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"],
        "evidence_requirements": ["repo_readmes", "design_scope", "public_status", "source_prompt"],
        "memory_write_policy": "reviewed_only",
        "memory_reads": ["entities", "relationships", "repo_readmes", "design_scope", "public_status"],
        "input_schema_json": {
            "type": "object",
            "properties": {
                "source_text": {"type": "string"},
                "generation_instruction": {"type": "string"},
                "response_schema_json": {"type": "object"},
                "context_pack": {"type": "object"},
                "goal": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["source_text"],
        },
        "output_schema_json": {
            "type": "object",
            "properties": {
                "deliverable_type": {"const": "chummer6_guide_refresh_packet"},
                "artifact_kind": {"type": "string"},
                "structured_output_json": {"type": "object"},
            },
            "required": ["deliverable_type"],
        },
        "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
        "model_policy_json": {
            "provider": "gemini_vortex",
            "default_model": env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-3-flash-preview",
            "output_mode": "json",
        },
        "tool_policy_json": {"allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"]},
        "human_policy_json": {"review_roles": ["guide_reviewer"]},
        "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
        "budget_policy_json": {
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "structured_generate",
            "artifact_failure_strategy": "retry",
            "artifact_max_attempts": 2,
            "artifact_retry_backoff_seconds": 1,
            "style_epoch_enabled": True,
            "variation_guard_enabled": True,
        },
    }


def build_public_writer_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_public_writer",
            "task_key": "chummer6_public_copy_refresh",
            "name": "Chummer6 Public Writer",
            "description": "Planner-executed public-writer lane for Chummer6 guide copy, audience translation, and reader-safe OODA framing.",
            "memory_writes": ["chummer6_public_copy_fact"],
            "tags": ["chummer6", "guide", "public-writer", "audience", "copy"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "Prompting Systems"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_visual_director_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_visual_director",
            "name": "Chummer6 Visual Director",
            "description": "Planner-executed Chummer6 scene planning, style-epoch selection, scene-ledger guidance, and structured visual-direction skill for the public-facing guide.",
            "memory_writes": ["chummer6_style_epoch", "chummer6_scene_ledger", "chummer6_visual_critic_fact"],
            "tags": ["chummer6", "guide", "visual-direction", "style-epoch", "scene-ledger"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "AI Magicx", "Prompting Systems", "BrowserAct"],
                "media": ["AI Magicx", "Prompting Systems", "BrowserAct"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_public_auditor_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_public_auditor",
            "task_key": "chummer6_public_copy_audit",
            "name": "Chummer6 Public Auditor",
            "description": "Self-audit lane for Chummer6 public-guide copy: visitor-first voice, correct action routing, jargon cleanup, and bounded revision guidance.",
            "memory_writes": ["chummer6_public_audit_fact"],
            "tags": ["chummer6", "guide", "public-audit", "editorial", "qa"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "Prompting Systems"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_scene_auditor_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_scene_auditor",
            "task_key": "chummer6_scene_plan_audit",
            "name": "Chummer6 Scene Auditor",
            "description": "Audit and repair lane for Chummer6 scene plans before rendering: composition diversity, page-role fit, and table-scene relapse prevention.",
            "memory_writes": ["chummer6_scene_audit_fact"],
            "tags": ["chummer6", "guide", "scene-audit", "visual-direction", "qa"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "Prompting Systems"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_visual_auditor_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_visual_auditor",
            "task_key": "chummer6_visual_audit",
            "name": "Chummer6 Visual Auditor",
            "description": "Post-render visual QA lane for Chummer6 guide assets: reject placeholder vibes, detect repetition, and enforce pack-level premium feel.",
            "memory_writes": ["chummer6_visual_audit_fact"],
            "tags": ["chummer6", "guide", "visual-audit", "qa"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "AI Magicx", "Prompting Systems"],
                "media": ["AI Magicx", "Prompting Systems"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_pack_auditor_skill_payload() -> dict[str, object]:
    payload = _common_skill_fields()
    payload.update(
        {
            "skill_key": "chummer6_pack_auditor",
            "task_key": "chummer6_pack_audit",
            "name": "Chummer6 Pack Auditor",
            "description": "Whole-pack audit lane for Chummer6 guide output: editorial drift, scene diversity, style-epoch coherence, and publish readiness checks.",
            "memory_writes": ["chummer6_pack_audit_fact"],
            "tags": ["chummer6", "guide", "pack-audit", "qa"],
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex"],
                "style": ["Gemini Vortex"],
            },
        }
    )
    return payload


def build_skill_payloads() -> list[dict[str, object]]:
    return [
        build_public_writer_skill_payload(),
        build_public_auditor_skill_payload(),
        build_visual_director_skill_payload(),
        build_scene_auditor_skill_payload(),
        build_visual_auditor_skill_payload(),
        build_pack_auditor_skill_payload(),
    ]


def build_skill_payload() -> dict[str, object]:
    # Compatibility wrapper for older callers that still expect one primary skill payload.
    return build_visual_director_skill_payload()


def upsert_skills_via(fn) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for payload in build_skill_payloads():
        results.append(fn(payload))
    return results


def apply_skill_payload(skills, body: dict[str, object]) -> dict[str, object]:
    row = skills.upsert_skill(
        skill_key=str(body.get("skill_key") or ""),
        task_key=str(body.get("task_key") or ""),
        name=str(body.get("name") or ""),
        description=str(body.get("description") or ""),
        deliverable_type=str(body.get("deliverable_type") or ""),
        default_risk_class=str(body.get("default_risk_class") or "low"),
        default_approval_class=str(body.get("default_approval_class") or "none"),
        workflow_template=str(body.get("workflow_template") or "rewrite"),
        allowed_tools=tuple(str(value) for value in (body.get("allowed_tools") or []) if str(value or "").strip()),
        evidence_requirements=tuple(str(value) for value in (body.get("evidence_requirements") or []) if str(value or "").strip()),
        memory_write_policy=str(body.get("memory_write_policy") or "none"),
        memory_reads=tuple(str(value) for value in (body.get("memory_reads") or []) if str(value or "").strip()),
        memory_writes=tuple(str(value) for value in (body.get("memory_writes") or []) if str(value or "").strip()),
        tags=tuple(str(value) for value in (body.get("tags") or []) if str(value or "").strip()),
        input_schema_json=dict(body.get("input_schema_json") or {}),
        output_schema_json=dict(body.get("output_schema_json") or {}),
        authority_profile_json=dict(body.get("authority_profile_json") or {}),
        model_policy_json=dict(body.get("model_policy_json") or {}),
        provider_hints_json=dict(body.get("provider_hints_json") or {}),
        tool_policy_json=dict(body.get("tool_policy_json") or {}),
        human_policy_json=dict(body.get("human_policy_json") or {}),
        evaluation_cases_json=tuple(dict(value) for value in (body.get("evaluation_cases_json") or [])),
        budget_policy_json=dict(body.get("budget_policy_json") or {}),
    )
    return {
        "skill_key": row.skill_key,
        "task_key": row.task_key,
        "workflow_template": row.workflow_template,
        "provider_hints_json": dict(row.provider_hints_json or {}),
    }


def upsert_skill_local(body: dict[str, object]) -> dict[str, object]:
    app_root = str(EA_ROOT / "ea")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    from app.services.skills import SkillCatalogService
    from app.services.task_contracts import build_task_contract_service

    skills = SkillCatalogService(build_task_contract_service())
    return apply_skill_payload(skills, body)


def main() -> int:
    try:
        results = upsert_skills_via(upsert_skill)
        print(json.dumps({"status": "ok", "skill_keys": [row.get("skill_key", "") for row in results], "path": "api"}))
        return 0
    except urllib.error.URLError as exc:
        try:
            results = upsert_skills_via(upsert_skill_local)
            print(json.dumps({"status": "ok", "skill_keys": [row.get("skill_key", "") for row in results], "path": "local", "reason": f"api_unavailable:{exc.reason}"}))
            return 0
        except Exception as local_exc:
            print(json.dumps({"status": "skipped", "reason": f"api_unavailable:{exc.reason}", "local_error": str(local_exc)[:240]}))
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        try:
            results = upsert_skills_via(upsert_skill_local)
            print(json.dumps({"status": "ok", "skill_keys": [row.get("skill_key", "") for row in results], "path": "local", "reason": f"http_{exc.code}", "body": body[:240]}))
            return 0
        except Exception as local_exc:
            print(json.dumps({"status": "skipped", "reason": f"http_{exc.code}", "body": body[:240], "local_error": str(local_exc)[:240]}))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
