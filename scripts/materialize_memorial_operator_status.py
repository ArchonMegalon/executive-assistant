#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from scripts.source_state_head import resolve_source_state_head, source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head, source_worktree_metadata

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-design" / "product" / "MEMORIAL_OPERATOR_STATUS.generated.json"
WHOLE_PROJECT_GOLD_MAP = ROOT / ".codex-design" / "product" / "WHOLE_PROJECT_GOLD_MAP.generated.json"
DEFAULT_DEPLOY_CONTEXT = ROOT / ".codex-studio" / "published" / "deploy_context.generated.json"
DEFAULT_RELEASE_MANIFEST = ROOT / ".codex-studio" / "published" / "release_manifest.generated.json"
DEFAULT_RELEASE_AUTHORITY_STATUS = ROOT / ".codex-studio" / "published" / "release_authority_status.generated.json"
OUTPUT = DEFAULT_OUTPUT
DEPLOY_CONTEXT = DEFAULT_DEPLOY_CONTEXT
RELEASE_MANIFEST = DEFAULT_RELEASE_MANIFEST
RELEASE_AUTHORITY_STATUS = DEFAULT_RELEASE_AUTHORITY_STATUS
MEANINGFUL_BROWSER_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_realtime_browser_meaningful_public_origin.generated.json"
PUBLIC_VOICE_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_voice_roundtrip_public_origin.generated.json"
PUBLIC_BROWSER_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_realtime_browser_public_origin.generated.json"
ROOM_AUDIO_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_room_audio_public_origin.generated.json"
SPATIAL_TOUR_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_spatial_tour_public_origin.generated.json"
ROOM_AUDIO_ATTESTATION_PACKET = ROOT / ".codex-studio" / "published" / "memorial_room_audio_attestation_packet.generated.json"
STT_PROVIDER_BENCHMARK_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_provider_benchmark.generated.json"
STT_FIXTURE_CANDIDATE_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_fixture_candidate.generated.json"
STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT = (
    ROOT / ".codex-studio" / "published" / "memorial_stt_provider_benchmark_captured_candidate.generated.json"
)
STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT = (
    ROOT / ".codex-studio" / "published" / "memorial_stt_captured_candidate_diagnostic.generated.json"
)
STT_CAPTURE_DISCOVERY_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_capture_discovery.generated.json"
ENV_FILE = ROOT / ".env"
SOURCE_DIRTY_FILE_LIMIT = 10000


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _run_json(script: str | list[str]) -> dict:
    command = [sys.executable]
    if isinstance(script, str):
        command.append(str(ROOT / script))
        script_label = script
    else:
        script_args = list(script)
        if not script_args:
            return {"status": "error", "script": "", "stdout": "", "stderr": "empty_script_args"}
        command.append(str(ROOT / script_args[0]))
        command.extend(script_args[1:])
        script_label = " ".join(script_args)
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        return json.loads(output or "{}")
    except Exception:
        return {"status": "error", "script": script_label, "stdout": proc.stdout[:800], "stderr": proc.stderr[:800]}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _env_file_value(key: str) -> str:
    try:
        for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in raw_line:
                continue
            current_key, value = raw_line.split("=", 1)
            if current_key.strip() == key:
                return value.strip()
    except Exception:
        return ""
    return ""


def _configured_public_origin() -> tuple[str, str]:
    for key in ("EA_PUBLIC_APP_BASE_URL", "PROPERTYQUARRY_PUBLIC_BASE_URL"):
        value = str(os.environ.get(key) or _env_file_value(key) or "").strip().rstrip("/")
        if value:
            return key, value
    return "", ""


def _http_status(url: str) -> tuple[int, str]:
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=20.0) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(240).decode("utf-8", errors="replace")
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(240).decode("utf-8", errors="replace")
        return int(exc.code or 0), body
    except Exception as exc:
        return 0, f"{type(exc).__name__}:{exc}"


def _public_origin_access_status(*, slug: str) -> dict[str, object]:
    source_key, base_url = _configured_public_origin()
    if not base_url:
        return {
            "status": "missing",
            "base_url": "",
            "source_key": "",
            "page_status_code": 0,
            "manifest_status_code": 0,
            "page_probe_url": "",
            "manifest_probe_url": "",
            "next_action": "configure_public_memorial_origin",
            "reason": "public_origin_missing",
        }
    page_url = f"{base_url}/memorials/{slug}"
    manifest_url = f"{base_url}/memorials/{slug}.json"
    page_status, page_detail = _http_status(page_url)
    manifest_status, manifest_detail = _http_status(manifest_url)
    access_blocked = page_status in {401, 403} or manifest_status in {401, 403}
    not_found = page_status == 404 or manifest_status == 404
    if page_status == 200 and manifest_status == 200:
        return {
            "status": "pass",
            "base_url": base_url,
            "source_key": source_key,
            "page_status_code": page_status,
            "manifest_status_code": manifest_status,
            "page_probe_url": page_url,
            "manifest_probe_url": manifest_url,
            "page_detail": page_detail[:160],
            "manifest_detail": manifest_detail[:160],
            "next_action": "maintain_public_memorial_origin_access",
        }
    return {
        "status": "access_blocked" if access_blocked else "blocked",
        "base_url": base_url,
        "source_key": source_key,
        "page_status_code": page_status,
        "manifest_status_code": manifest_status,
        "page_probe_url": page_url,
        "manifest_probe_url": manifest_url,
        "page_detail": page_detail[:160],
        "manifest_detail": manifest_detail[:160],
        "next_action": (
            "allow_anonymous_public_memorial_origin_access"
            if access_blocked
            else "republish_public_memorial_bundle_or_fix_slug"
            if not_found
            else "inspect_public_memorial_origin_http_failure"
        ),
        "reason": (
            "public_origin_access_blocked"
            if access_blocked
            else "public_origin_memorial_not_found"
            if not_found
            else "public_origin_http_probe_failed"
        ),
    }


def _receipt_state(path: Path) -> str:
    payload = _load_json(path)
    if str(payload.get("status") or "").strip().lower() == "pass":
        return "pass"
    if path.exists():
        return "blocked"
    return "missing_or_blocked"


def _receipt_git_head(path: Path) -> str:
    payload = _load_json(path)
    return str(payload.get("git_head") or payload.get("source_git_head") or "").strip()


def _source_dirty_category(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        return "other"
    if normalized.startswith(".env") or normalized.endswith(".env") or "/.env" in normalized:
        return "env_examples"
    if normalized.startswith("docs-public/"):
        return "public_docs"
    if normalized.startswith(".codex-design/product/"):
        return "design_mirror"
    if normalized.startswith(".codex-studio/published/"):
        return "generated_receipts"
    if normalized.startswith("docker-compose") or normalized.startswith("ea/Dockerfile") or normalized in {"Dockerfile", "Dockerfile.operator"}:
        return "deploy_runtime"
    if normalized.startswith("ea/app/api/routes/"):
        return "api_routes"
    if normalized.startswith("ea/app/services/"):
        return "services"
    if normalized.startswith("ea/app/templates/"):
        return "templates"
    if normalized.startswith("ea/app/"):
        return "app_core"
    if normalized.startswith("ea/tests/") or normalized.startswith("tests/"):
        return "tests"
    if normalized.startswith("scripts/") or normalized.startswith("ea/scripts/"):
        return "scripts"
    if normalized.startswith("data/"):
        return "data"
    if normalized.endswith(".md") or normalized in {"README.md", "CHANGELOG.md", "RUNBOOK.md", "RELEASE_CHECKLIST.md", "LTDs.md"}:
        return "docs"
    if normalized in {"Makefile", ".gitignore"}:
        return "repo_config"
    return "other"


def _source_dirty_summary(source_worktree: dict[str, object]) -> dict[str, object]:
    files = [
        str(item).strip()
        for item in list(source_worktree.get("source_dirty_files") or [])
        if str(item).strip()
    ]
    groups: dict[str, dict[str, object]] = {}
    for path in files:
        category = _source_dirty_category(path)
        group = groups.setdefault(category, {"category": category, "visible_count": 0, "sample_files": []})
        group["visible_count"] = int(group.get("visible_count") or 0) + 1
        samples = list(group.get("sample_files") or [])
        if len(samples) < 8:
            samples.append(path)
        group["sample_files"] = samples
    category_order = (
        "api_routes",
        "services",
        "app_core",
        "templates",
        "scripts",
        "deploy_runtime",
        "env_examples",
        "public_docs",
        "docs",
        "tests",
        "design_mirror",
        "generated_receipts",
        "data",
        "repo_config",
        "other",
    )
    ordered_groups = sorted(
        groups.values(),
        key=lambda item: (category_order.index(str(item.get("category"))) if str(item.get("category")) in category_order else 999, str(item.get("category"))),
    )
    visible_count = len(files)
    total_count = int(source_worktree.get("source_dirty_count") or visible_count)
    omitted_count = int(source_worktree.get("source_dirty_omitted_count") or 0)
    return {
        "status": "dirty" if bool(source_worktree.get("source_worktree_dirty")) else "clean",
        "total_count": total_count,
        "visible_count": visible_count,
        "omitted_count": omitted_count,
        "category_count": len(ordered_groups),
        "categories": ordered_groups,
        "recommended_first_action": (
            "review_and_commit_or_stash_source_groups_before_clean_receipts"
            if bool(source_worktree.get("source_worktree_dirty"))
            else "none"
        ),
        "operator_hint": (
            "Start with api_routes/services/scripts/deploy_runtime groups; generated-only receipt changes do not explain clean-clone proof failures."
            if bool(source_worktree.get("source_worktree_dirty"))
            else "Source worktree is clean for clean-clone receipt refresh."
        ),
    }


def _source_cleanup_payload(
    *,
    source_worktree: dict[str, object],
    source_dirty_summary: dict[str, object],
    source_dirty_verifier: dict[str, object],
    next_action: str,
    next_command: str,
) -> dict[str, object]:
    dirty = bool(source_worktree.get("source_worktree_dirty"))
    verifier_status = str(source_dirty_verifier.get("status") or "missing").strip().lower() or "missing"
    verifier_issues = [
        str(item).strip()
        for item in list(source_dirty_verifier.get("issues") or [])
        if str(item).strip()
    ]
    categories = [
        {
            "category": str(item.get("category") or "").strip(),
            "visible_count": int(item.get("visible_count") or 0),
            "drilldown_command": (
                f"scripts/inspect_source_dirty_groups.py --category {str(item.get('category') or '').strip()} --limit 20"
            ),
        }
        for item in list(source_dirty_summary.get("categories") or [])
        if isinstance(item, dict) and str(item.get("category") or "").strip()
    ]
    source_action_names = {
        "commit_or_stash_source_changes_before_clean_receipts",
        "verify_source_dirty_groups_before_source_cleanup",
    }
    source_next_action = str(next_action or "").strip() if str(next_action or "").strip() in source_action_names else ""
    source_next_command = str(next_command or "").strip() if source_next_action else ""
    if not source_next_action and dirty:
        source_next_action = (
            "verify_source_dirty_groups_before_source_cleanup"
            if verifier_status != "pass"
            else "commit_or_stash_source_changes_before_clean_receipts"
        )
        source_next_command = _memorial_next_command_for_action(source_next_action)
    category_drilldown_commands = [
        str(item.get("drilldown_command") or "").strip()
        for item in categories
        if str(item.get("drilldown_command") or "").strip()
    ]
    handoff_commands = [
        "git status --short",
        "scripts/inspect_source_dirty_groups.py --list-categories",
        *category_drilldown_commands[:6],
    ]
    if verifier_status != "pass":
        handoff_commands.append("make verify-source-dirty-groups")
    if source_next_command and source_next_command not in handoff_commands:
        handoff_commands.append(source_next_command)
    status = "ready"
    if dirty:
        status = "blocked"
    if dirty and verifier_status != "pass":
        status = "verifier_blocked"
    return {
        "status": status,
        "source_worktree_dirty": dirty,
        "source_dirty_count": int(source_worktree.get("source_dirty_count") or 0),
        "source_dirty_omitted_count": int(source_worktree.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(source_worktree.get("source_dirty_status_sha256") or ""),
        "summary_status": str(source_dirty_summary.get("status") or "").strip(),
        "category_count": int(source_dirty_summary.get("category_count") or len(categories)),
        "top_categories": categories[:6],
        "category_drilldown_commands": category_drilldown_commands,
        "handoff_commands": handoff_commands,
        "verifier_status": verifier_status,
        "verifier_issues": verifier_issues,
        "next_action": source_next_action,
        "next_command": source_next_command,
    }


def _memorial_public_runtime_status() -> dict[str, object]:
    deploy_context = _load_json(DEPLOY_CONTEXT)
    release_manifest = _load_json(RELEASE_MANIFEST)
    project_mode = str(
        release_manifest.get("project_mode")
        or deploy_context.get("project_mode")
        or ""
    ).strip()
    enabled_modes_raw = list(
        release_manifest.get("enabled_project_modes")
        or deploy_context.get("enabled_project_modes")
        or []
    )
    enabled_modes = [str(item).strip() for item in enabled_modes_raw if str(item).strip()]
    compose_files = [
        str(item).strip()
        for item in list(deploy_context.get("compose_files") or release_manifest.get("compose_files") or [])
        if str(item).strip()
    ]
    compose_overrides = [
        str(item).strip()
        for item in list(deploy_context.get("compose_overrides") or release_manifest.get("compose_overrides") or [])
        if str(item).strip()
    ]
    public_origin = str(
        release_manifest.get("public_origin")
        or deploy_context.get("public_origin")
        or ""
    ).strip()
    memorial_enabled = project_mode == "MEMORIAL" or "MEMORIAL" in enabled_modes
    if memorial_enabled:
        return {
            "status": "pass",
            "project_mode": project_mode,
            "enabled_project_modes": enabled_modes,
            "compose_files": compose_files,
            "compose_overrides": compose_overrides,
            "public_origin": public_origin,
            "next_action": "maintain_memorial_public_runtime",
            "reason": "memorial_runtime_declared",
        }
    if not deploy_context and not release_manifest:
        return {
            "status": "missing",
            "project_mode": project_mode,
            "enabled_project_modes": enabled_modes,
            "compose_files": compose_files,
            "compose_overrides": compose_overrides,
            "public_origin": public_origin,
            "next_action": "materialize_deploy_context_and_release_manifest",
            "reason": "deploy_context_or_release_manifest_missing",
        }
    return {
        "status": "blocked",
        "project_mode": project_mode,
        "enabled_project_modes": enabled_modes,
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
        "public_origin": public_origin,
        "next_action": "deploy_ea_memorial",
        "reason": "public_origin_not_deployed_in_memorial_mode",
    }


def _release_authority_status() -> dict[str, object]:
    payload = _load_json(RELEASE_AUTHORITY_STATUS)
    if not payload:
        payload = _run_json(
            [
                "scripts/materialize_release_authority_status.py",
                "--output",
                str(RELEASE_AUTHORITY_STATUS),
                "--release-manifest",
                str(RELEASE_MANIFEST),
                "--deploy-context",
                str(DEPLOY_CONTEXT),
            ]
        )
    if not isinstance(payload, dict):
        return {
            "status": "missing",
            "state": "missing",
            "authority_posture": "missing",
            "issues": ["release_authority_status_missing"],
            "next_action": "materialize_release_authority_status",
            "detail": "release authority status artifact missing",
        }
    state = str(payload.get("state") or payload.get("status") or "").strip().lower() or "missing"
    posture = str(payload.get("authority_posture") or "").strip().lower() or "missing"
    issues = [
        str(item).strip()
        for item in list(payload.get("issues") or [])
        if str(item).strip()
    ]
    next_action = str(payload.get("next_action") or "").strip()
    status = "pass" if state in {"clear", "pass"} and not issues else "blocked"
    return {
        "status": status,
        "state": state,
        "authority_posture": posture,
        "issues": issues,
        "next_action": next_action or "clear_release_authority_blockers",
        "detail": str(payload.get("summary") or "").strip(),
        "deployment_id": str(payload.get("deployment_id") or "").strip(),
        "deployment_id_source": str(payload.get("deployment_id_source") or "").strip(),
        "dirty_worktree": bool(payload.get("dirty_worktree") is True),
        "deploy_context_commit_sha": str(payload.get("deploy_context_commit_sha") or "").strip(),
        "commit_sha": str(payload.get("commit_sha") or "").strip(),
    }


def _workflow_backing_status(*receipts: Path) -> dict[str, object]:
    for receipt in receipts:
        payload = _load_json(receipt)
        if not payload:
            continue
        run_id = str(payload.get("workflow_run_id") or payload.get("github_run_id") or "").strip()
        artifact_id = str(payload.get("workflow_artifact_id") or payload.get("github_artifact_id") or "").strip()
        if run_id or artifact_id:
            return {
                "status": "yes",
                "available": True,
                "workflow_run_id": run_id,
                "artifact_id": artifact_id,
            }
    return {
        "status": "no",
        "available": False,
        "reason": "no_workflow_receipt_marker_present",
    }


def _public_voice_receipt_semantics() -> dict[str, object]:
    payload = _load_json(PUBLIC_VOICE_RECEIPT)
    metrics = dict(payload.get("metrics") or {})
    direct = str(metrics.get("direct_tts_transcriber") or payload.get("direct_tts_transcriber") or "").strip()
    conversation = str(
        metrics.get("conversation_turn_transcriber") or payload.get("conversation_turn_transcriber") or ""
    ).strip()
    provenance_cache = {direct, conversation} == {"memorial_tts_provenance_cache"}
    return {
        "label": "Memorial public voice provenance proof" if provenance_cache else "Memorial public voice gold proof",
        "transcriber_mode": "provenance_cache" if provenance_cache else "runtime_or_external_stt",
        "direct_tts_transcriber": direct,
        "conversation_turn_transcriber": conversation,
    }


def _spoken_stt_provider_benchmark_status() -> dict[str, object]:
    payload = _load_json(STT_PROVIDER_BENCHMARK_RECEIPT)
    if not payload:
        return {
            "status": "missing_or_blocked",
            "receipt_status": "missing",
            "production_eligible": False,
            "best_provider": "",
            "production_provider": "",
            "top_candidate_provider": "",
            "passed_samples": 0,
            "sample_count": 0,
            "receipt_path": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
            "reason": "stt_provider_benchmark_receipt_missing",
        }
    ranking = [dict(item) for item in list(payload.get("provider_ranking") or []) if isinstance(item, dict)]
    best = ranking[0] if ranking else {}
    production_eligible = bool(best.get("production_eligible"))
    receipt_status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    status = "pass" if receipt_status == "pass" and production_eligible else "blocked"
    provider = str(best.get("provider") or "").strip()
    availability = dict(payload.get("availability") or {})
    cartesia = dict(availability.get("cartesia") or {})
    rows = [dict(item) for item in list(payload.get("rows") or []) if isinstance(item, dict)]
    provider_results = [dict(row.get(provider) or {}) for row in rows if isinstance(row.get(provider), dict)]
    transcribers = sorted(
        {
            str(result.get("transcriber") or "").strip()
            for result in provider_results
            if str(result.get("transcriber") or "").strip()
        }
    )
    production_transcriber = transcribers[0] if len(transcribers) == 1 else ""
    fallback_provider_statuses = [
        {
            "provider": str(item.get("provider") or "").strip(),
            "passed_samples": int(item.get("passed_samples") or 0),
            "sample_count": int(item.get("sample_count") or 0),
            "scored_samples": int(item.get("scored_samples") or 0),
            "avg_token_f1": float(item.get("avg_token_f1") or 0.0),
            "avg_wer": float(item.get("avg_wer") or 1.0),
            "production_eligible": bool(item.get("production_eligible")),
        }
        for item in ranking
        if str(item.get("provider") or "").strip() != provider
    ]
    fallback_production_eligible = any(item["production_eligible"] for item in fallback_provider_statuses)
    synthetic_rows = [
        row
        for row in rows
        if bool(dict(row.get("provenance") or {}).get("synthetic"))
    ]
    ground_truth_fixture_mode = (
        "synthetic_only"
        if rows and len(synthetic_rows) == len(rows)
        else ("mixed_or_captured" if rows else "unknown")
    )
    fixture_quality_status = str(payload.get("fixture_quality_status") or "unknown").strip().lower()
    fixture_quality_failed_codes = [
        str(item).strip()
        for item in list(payload.get("fixture_quality_failed_codes") or [])
        if str(item).strip()
    ]
    next_action = "maintain_memorial_stt_regression_corpus"
    if status == "pass" and ground_truth_fixture_mode == "synthetic_only":
        next_action = "add_real_captured_stt_fixture"
    elif fixture_quality_status == "blocked":
        next_action = "replace_memorial_stt_captured_fixtures"
    elif availability.get("cartesia_configured") is not True:
        next_action = "configure_cartesia_credentials"
    elif not production_eligible:
        next_action = "inspect_provider_accuracy_failures"
    try:
        avg_wer = float(best.get("avg_wer"))
    except (TypeError, ValueError):
        avg_wer = 1.0
    return {
        "status": status,
        "receipt_status": receipt_status,
        "production_eligible": production_eligible,
        "best_provider": provider if production_eligible else "",
        "production_provider": provider if production_eligible else "",
        "top_candidate_provider": provider,
        "provider_label": (production_transcriber or provider) if production_eligible else "no_production_stt_provider",
        "provider_key": provider,
        "production_transcriber": production_transcriber if production_eligible else "",
        "production_transcriber_set": transcribers if production_eligible else [],
        "fallback_provider_statuses": fallback_provider_statuses,
        "fallback_production_eligible": fallback_production_eligible,
        "fallback_health": "pass" if fallback_production_eligible else "blocked",
        "passed_samples": int(best.get("passed_samples") or 0),
        "sample_count": int(best.get("sample_count") or 0),
        "avg_token_f1": float(best.get("avg_token_f1") or 0.0),
        "avg_wer": avg_wer,
        "avg_latency_ms": float(best.get("avg_latency_ms") or 0.0),
        "receipt_path": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
        "availability": availability,
        "fixture_quality_status": fixture_quality_status,
        "fixture_quality_failed_codes": fixture_quality_failed_codes,
        "ground_truth_fixture_mode": ground_truth_fixture_mode,
        "cartesia_credential_status": cartesia,
        "next_action": next_action,
        "scoring": dict(payload.get("scoring") or {}),
    }


def _stt_fixture_candidate_status() -> dict[str, object]:
    payload = _load_json(STT_FIXTURE_CANDIDATE_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
            "next_action": "materialize_candidate_from_pcloud_with_operator_transcript_and_consent",
        }
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    failed_codes = [
        str(item).strip()
        for item in list(payload.get("failed_codes") or [])
        if str(item).strip()
    ]
    audio = dict(payload.get("audio") or {})
    candidate = dict(payload.get("candidate_manifest_entry") or {})
    promotion_gate = dict(payload.get("promotion_gate") or {})
    next_action = "review_candidate_for_fixture_manifest"
    if "input_wav_missing" in failed_codes:
        next_action = "select_error_bundle_with_stored_wav"
    elif "input_wav_too_large" in failed_codes:
        next_action = "cut_short_question_clip_before_fixture_promotion"
    elif "audio_not_wav" in failed_codes or "audio_duration_implausible" in failed_codes:
        next_action = "normalize_captured_audio_before_fixture_promotion"
    elif "expected_text_missing" in failed_codes or "required_tokens_missing" in failed_codes:
        next_action = "add_operator_supplied_ground_truth_transcript"
    elif "speaker_consent_missing" in failed_codes:
        next_action = "record_operator_speaker_consent"
    elif status != "pass":
        next_action = "fix_fixture_candidate_failed_codes"
    elif promotion_gate:
        next_action = str(
            promotion_gate.get("next_action")
            or "run_captured_candidate_benchmark_before_fixture_manifest"
        ).strip()
    return {
        "status": status,
        "receipt_path": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
        "failed_codes": failed_codes,
        "candidate_scope": str(payload.get("candidate_scope") or "").strip(),
        "promotion_gate": promotion_gate,
        "bundle_id": str(dict(payload.get("bundle") or {}).get("id") or "").strip(),
        "sample": str(candidate.get("sample") or "").strip(),
        "synthetic": bool(candidate.get("synthetic")),
        "text_mode": str(payload.get("text_mode") or "").strip(),
        "raw_text_fields": bool(payload.get("raw_text_fields")),
        "audio_bytes": int(audio.get("bytes") or 0),
        "audio_duration_seconds": float(audio.get("duration_seconds") or 0.0),
        "next_action": next_action,
    }


def _captured_candidate_benchmark_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
            "next_action": "run_opt_in_captured_candidate_benchmark",
        }
    ranking = [dict(item) for item in list(payload.get("provider_ranking") or []) if isinstance(item, dict)]
    best = ranking[0] if ranking else {}
    rows = [dict(item) for item in list(payload.get("rows") or []) if isinstance(item, dict)]
    captured_rows = [
        row
        for row in rows
        if bool(dict(row.get("provenance") or {}).get("external_bundle"))
    ]
    captured_full_runtime_rows = [dict(row.get("full_runtime") or {}) for row in captured_rows]
    captured_passed = captured_full_runtime_rows and all(row.get("passed") is True for row in captured_full_runtime_rows)
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    next_action = "promote_captured_candidate_to_fixture_manifest"
    if not captured_rows:
        next_action = "rerun_with_captured_candidate_bundle"
    elif not captured_passed:
        next_action = "inspect_captured_candidate_ground_truth_or_stt_failure"
    elif status != "pass":
        next_action = "inspect_non_captured_provider_failures"
    return {
        "status": status,
        "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
        "best_provider": str(best.get("provider") or "").strip(),
        "production_eligible": bool(best.get("production_eligible")),
        "passed_samples": int(best.get("passed_samples") or 0),
        "sample_count": int(best.get("sample_count") or 0),
        "captured_rows": len(captured_rows),
        "captured_full_runtime_passed": bool(captured_passed),
        "captured_full_runtime_failures": [
            {
                "sample": str(row.get("sample") or "").strip(),
                "variant": str(row.get("variant") or "").strip(),
                "wer": float(dict(row.get("full_runtime") or {}).get("wer") or 1.0),
                "token_f1": float(dict(row.get("full_runtime") or {}).get("token_f1") or 0.0),
                "intent_correct": bool(dict(row.get("full_runtime") or {}).get("intent_correct")),
            }
            for row in captured_rows
            if dict(row.get("full_runtime") or {}).get("passed") is not True
        ],
        "next_action": next_action,
    }


def _captured_candidate_diagnostic_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
            "promotion_allowed": False,
            "next_action": "materialize_captured_candidate_diagnostic",
        }
    blocker_summary = dict(payload.get("blocker_summary") or {})
    return {
        "status": str(payload.get("status") or "blocked").strip().lower() or "blocked",
        "diagnostic_status": str(payload.get("diagnostic_status") or "").strip(),
        "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
        "promotion_allowed": bool(payload.get("promotion_allowed")),
        "may_update_fixture_manifest": bool(payload.get("may_update_fixture_manifest")),
        "captured_row_count": int(payload.get("captured_row_count") or 0),
        "row_failure_codes": [
            str(code).strip()
            for code in list(blocker_summary.get("row_failure_codes") or [])
            if str(code).strip()
        ],
        "full_runtime_failed_rows": [
            {
                "sample": str(dict(row).get("sample") or "").strip(),
                "variant": str(dict(row).get("variant") or "").strip(),
                "failure_codes": [
                    str(code).strip()
                    for code in list(dict(row).get("failure_codes") or [])
                    if str(code).strip()
                ],
                "token_f1": float(dict(row).get("token_f1") or 0.0),
                "wer": float(dict(row).get("wer") or 1.0),
            }
            for row in list(blocker_summary.get("full_runtime_failed_rows") or [])
            if isinstance(row, dict)
        ],
        "privacy": dict(payload.get("privacy") or {}),
        "next_action": str(payload.get("next_action") or "").strip(),
    }


def _stt_capture_discovery_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURE_DISCOVERY_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
            "next_action": "materialize_redacted_capture_discovery_from_selected_pcloud_bundles",
        }
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    failed_codes = [
        str(item).strip()
        for item in list(payload.get("failed_codes") or [])
        if str(item).strip()
    ]
    promotable_count = int(payload.get("promotable_count") or 0)
    matched_count = int(payload.get("matched_count") or 0)
    next_action = "use_promotable_discovered_capture_for_benchmark"
    if matched_count <= 0:
        next_action = "search_additional_pcloud_bundles_for_matching_capture"
    elif promotable_count <= 0 and "audio_too_short_for_expected_text" in failed_codes:
        next_action = "capture_new_real_question_audio_or_fix_truncated_logger"
    elif promotable_count <= 0:
        next_action = "inspect_discovery_failed_codes"
    return {
        "status": status,
        "receipt_path": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
        "target_samples": list(payload.get("target_samples") or []),
        "bundle_count": int(payload.get("bundle_count") or 0),
        "matched_count": matched_count,
        "promotable_count": promotable_count,
        "failed_codes": failed_codes,
        "text_mode": str(payload.get("text_mode") or "").strip(),
        "raw_text_fields": bool(payload.get("raw_text_fields")),
        "next_action": next_action,
    }


def _reconcile_spoken_stt_next_action(
    spoken_stt_status: dict[str, object],
    stt_fixture_candidate: dict[str, object],
    captured_candidate_benchmark: dict[str, object],
    captured_candidate_diagnostic: dict[str, object] | None = None,
) -> dict[str, object]:
    status = dict(spoken_stt_status)
    if str(status.get("next_action") or "") != "add_real_captured_stt_fixture":
        return status
    diagnostic = dict(captured_candidate_diagnostic or {})
    if diagnostic and str(diagnostic.get("status") or "").strip().lower() == "blocked":
        status["real_captured_fixture_status"] = "captured_candidate_diagnostic_blocked"
        status["next_action"] = str(
            diagnostic.get("next_action")
            or "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ).strip()
        return status
    if diagnostic.get("promotion_allowed") is True:
        status["real_captured_fixture_status"] = "captured_candidate_diagnostic_ready"
        status["next_action"] = "promote_captured_candidate_to_fixture_manifest"
        return status
    captured_status = str(captured_candidate_benchmark.get("status") or "").strip().lower()
    captured_rows = _int_value(captured_candidate_benchmark.get("captured_rows"), 0)
    if captured_status == "pass":
        status["real_captured_fixture_status"] = "captured_candidate_benchmark_pass"
        status["next_action"] = "promote_captured_candidate_to_fixture_manifest"
        return status
    if captured_rows > 0:
        status["real_captured_fixture_status"] = "captured_candidate_benchmark_blocked"
        status["next_action"] = "inspect_captured_candidate_ground_truth_or_capture_new_audio"
        return status
    fixture_status = str(stt_fixture_candidate.get("status") or "").strip().lower()
    if fixture_status == "pass":
        status["real_captured_fixture_status"] = "candidate_ready_for_benchmark"
        status["next_action"] = "run_captured_candidate_benchmark_before_fixture_manifest"
    return status


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value if value is not None else default).strip() or str(default)))
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value if value is not None else default).strip() or str(default))
    except (TypeError, ValueError):
        return default


def _spoken_tts_playback_status() -> dict[str, object]:
    voice = _load_json(PUBLIC_VOICE_RECEIPT)
    browser = _load_json(PUBLIC_BROWSER_RECEIPT)
    voice_metrics = dict(voice.get("metrics") or {})
    browser_turn_payload = dict(browser.get("conversation_turn_payload") or {})

    direct_audio_status = str(voice_metrics.get("direct_tts_audio_status") or "").strip().lower()
    conversation_audio_status = str(voice_metrics.get("conversation_turn_audio_status") or "").strip().lower()
    direct_f1 = _float_value(voice_metrics.get("direct_tts_f1"), 0.0)
    conversation_f1 = _float_value(voice_metrics.get("conversation_turn_audio_f1"), 0.0)
    browser_status = str(browser.get("status") or "").strip().lower()
    browser_audio_ready = bool(browser.get("audio_ready_for_ui"))
    browser_audio_payload_ready = bool(browser.get("audio_payload_ready"))
    browser_audio_unavailable = bool(browser.get("audio_unavailable"))
    browser_play_calls = _int_value(browser.get("ui_audio_play_calls"))
    browser_play_ended = _int_value(browser.get("ui_audio_play_ended"))
    browser_play_error = str(browser.get("ui_audio_play_error") or "").strip()
    room_state = _receipt_state(ROOM_AUDIO_RECEIPT)

    failed_codes: list[str] = []
    if str(voice.get("status") or "").strip().lower() != "pass":
        failed_codes.append("public_voice_receipt_not_pass")
    if direct_audio_status != "pass":
        failed_codes.append("direct_tts_audio_not_pass")
    if conversation_audio_status != "pass":
        failed_codes.append("conversation_turn_audio_not_pass")
    if browser_status != "pass":
        failed_codes.append("browser_receipt_not_pass")
    if not browser_audio_ready:
        failed_codes.append("browser_audio_not_ready")
    if browser_audio_unavailable:
        failed_codes.append("browser_audio_unavailable")
    if browser_play_calls < 1:
        failed_codes.append("browser_play_call_missing")
    if browser_play_ended < 1:
        failed_codes.append("browser_play_completion_missing")
    if browser_play_error:
        failed_codes.append("browser_play_error")

    status = "pass" if not failed_codes else "blocked"
    premium_failed_codes = list(failed_codes)
    if room_state != "pass":
        premium_failed_codes.append("room_audio_attestation_not_pass")
    premium_status = "pass" if not premium_failed_codes else "blocked"
    next_action = "maintain_tts_playback_regression"
    if "room_audio_attestation_not_pass" in premium_failed_codes:
        next_action = "collect_real_room_audio_attestation"
    elif failed_codes:
        next_action = "fix_tts_or_browser_playback"

    return {
        "status": status,
        "premium_status": premium_status,
        "receipt_path": _display_path(PUBLIC_VOICE_RECEIPT),
        "browser_receipt_path": _display_path(PUBLIC_BROWSER_RECEIPT),
        "room_audio_receipt_path": _display_path(ROOM_AUDIO_RECEIPT),
        "direct_tts_audio_status": direct_audio_status,
        "conversation_turn_audio_status": conversation_audio_status,
        "direct_tts_f1": direct_f1,
        "conversation_turn_audio_f1": conversation_f1,
        "browser_audio_ready_for_ui": browser_audio_ready,
        "browser_audio_payload_ready": browser_audio_payload_ready,
        "browser_audio_transport": "embedded_payload" if browser_audio_payload_ready else "ui_playback_probe",
        "browser_audio_unavailable": browser_audio_unavailable,
        "browser_play_calls": browser_play_calls,
        "browser_play_ended": browser_play_ended,
        "browser_play_error": browser_play_error,
        "conversation_turn_payload_audio_embedded": bool(str(browser_turn_payload.get("audio_base64") or "").strip()),
        "room_audio_receipt": room_state,
        "failed_codes": list(dict.fromkeys(failed_codes)),
        "premium_failed_codes": list(dict.fromkeys(premium_failed_codes)),
        "next_action": next_action,
    }


def _room_audio_attestation_packet_status() -> dict[str, object]:
    payload = _load_json(ROOM_AUDIO_ATTESTATION_PACKET)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
            "manual_only": True,
            "operator_command": "make materialize-memorial-room-audio-attestation-packet",
            "next_action": "materialize_manual_attestation_packet",
        }
    status = str(payload.get("status") or "").strip().lower() or "blocked"
    proof_target = str(payload.get("proof_target") or "").strip()
    required_env = dict(payload.get("required_env") or {})
    required_checks = [
        dict(item)
        for item in list(payload.get("required_checks") or [])
        if isinstance(item, dict)
    ]
    required_cli_flags = [
        str(item).strip()
        for item in list(payload.get("required_cli_flags") or [])
        if str(item).strip()
    ]
    operator_steps = [
        str(item).strip()
        for item in list(payload.get("operator_steps") or [])
        if str(item).strip()
    ]
    return {
        "status": status,
        "receipt_path": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
        "manual_only": bool(payload.get("manual_only") is True),
        "ci_must_not_auto_assert": bool(payload.get("ci_must_not_auto_assert") is True),
        "proof_target": proof_target,
        "operator_command": str(payload.get("operator_command") or "make materialize-memorial-room-audio-gold-clean").strip(),
        "receipt_command_template": str(payload.get("receipt_command_template") or "").strip(),
        "required_env_keys": sorted(required_env.keys()),
        "required_env": required_env,
        "required_cli_flags": required_cli_flags,
        "operator_steps": operator_steps,
        "required_check_ids": [
            str(item.get("id") or "").strip()
            for item in required_checks
            if str(item.get("id") or "").strip()
        ],
        "next_action": "collect_real_room_audio_attestation",
    }


def _room_audio_receipt_detail() -> dict[str, object]:
    payload = _load_json(ROOM_AUDIO_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(ROOM_AUDIO_RECEIPT),
            "failed_codes": ["room_audio_receipt_missing"],
            "missing_check_ids": [],
            "missing_checks": [],
            "next_action": "collect_real_room_audio_attestation",
        }
    checks = dict(payload.get("checks") or {})
    requirements = dict(payload.get("check_requirements") or {})
    missing_check_ids = [
        str(check_id).strip()
        for check_id, value in checks.items()
        if str(check_id).strip() and value is not True
    ]
    missing_checks = [
        {
            "id": check_id,
            "requirement": str(requirements.get(check_id) or "").strip(),
        }
        for check_id in missing_check_ids
    ]
    failed_codes = [
        str(code).strip()
        for code in list(payload.get("failed_codes") or [])
        if str(code).strip()
    ]
    missing_input_hints = _room_audio_missing_input_hints(failed_codes=failed_codes, missing_check_ids=missing_check_ids)
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    return {
        "status": status,
        "receipt_path": _display_path(ROOM_AUDIO_RECEIPT),
        "source_git_head": str(payload.get("source_git_head") or payload.get("git_head") or "").strip(),
        "head_semantics": str(payload.get("head_semantics") or "").strip(),
        "dirty_worktree": bool(payload.get("dirty_worktree") is True),
        "source_tree_fingerprint": str(payload.get("source_tree_fingerprint") or "").strip(),
        "failed_codes": failed_codes,
        "missing_input_hints": missing_input_hints,
        "missing_check_ids": missing_check_ids,
        "missing_checks": missing_checks,
        "reviewer": str(payload.get("reviewer") or "").strip(),
        "device_label": str(payload.get("device_label") or "").strip(),
        "speaker_label": str(payload.get("speaker_label") or "").strip(),
        "room_label": str(payload.get("room_label") or "").strip(),
        "attestation_source": str(dict(payload.get("manual_attestation") or {}).get("source") or "").strip(),
        "next_action": "collect_real_room_audio_attestation" if status != "pass" else "maintain_room_audio_attestation",
    }


def _room_audio_missing_input_hints(*, failed_codes: list[str], missing_check_ids: list[str]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []

    def add(code: str, kind: str, name: str, description: str) -> None:
        if any(item.get("code") == code and item.get("name") == name for item in hints):
            return
        hints.append({"code": code, "kind": kind, "name": name, "description": description})

    check_requirements = {
        "actual_device_checked": "Confirm the actual public-origin device/browser path.",
        "actual_speaker_checked": "Confirm the intended room speaker/headphones/output route.",
        "first_syllable_not_clipped": "Confirm the first audible syllable was not clipped.",
        "intelligibility_confirmed": "Confirm the answer was understandable without reading text.",
        "answer_text_fallback_visible": "Confirm fallback transcript text stayed visible.",
        "no_internet_search_confirmed": "Confirm the memorial did not search the internet as Manfred.",
        "normal_spoken_turn_confirmed": "Confirm a complete microphone -> STT -> answer -> TTS -> playback turn.",
        "interruption_behavior_confirmed": "Confirm interruption/barge-in behavior was understandable.",
        "retry_path_confirmed": "Confirm a clear retry/recovery path after trouble.",
    }
    for check_id in missing_check_ids:
        flag = "--" + check_id.replace("_", "-")
        add(f"{check_id}_missing", "cli_flag", flag, check_requirements.get(check_id, "Confirm this manual room-audio check."))

    env_hints = {
        "reviewer_missing": ("MEMORIAL_ROOM_REVIEWER", "Set the actual listener/operator name."),
        "reviewer_generic": ("MEMORIAL_ROOM_REVIEWER", "Replace the generic reviewer label with a real listener/operator name."),
        "device_label_missing": ("MEMORIAL_ROOM_DEVICE_LABEL", "Set the exact device, browser, and public-origin path."),
        "device_label_generic": ("MEMORIAL_ROOM_DEVICE_LABEL", "Replace the generic device label with the exact device/browser/public path."),
        "speaker_label_missing": ("MEMORIAL_ROOM_SPEAKER_LABEL", "Set the exact speaker, headphones, or output route."),
        "speaker_label_generic": ("MEMORIAL_ROOM_SPEAKER_LABEL", "Replace the generic speaker label with the actual output route."),
        "room_label_missing": ("MEMORIAL_ROOM_LABEL", "Set the actual room or location."),
        "room_label_generic": ("MEMORIAL_ROOM_LABEL", "Replace the generic room label with the actual room/location."),
        "notes_missing": ("MEMORIAL_ROOM_NOTES", "Record volume, warmth, first syllable, intelligibility, interruption, and retry observations."),
        "manual_attestation_id_missing": ("MEMORIAL_ROOM_ATTESTATION_ID", "Set the signed/manual room review identifier."),
        "manual_attestation_signed_at_missing": ("MEMORIAL_ROOM_ATTESTATION_SIGNED_AT", "Set the signed review timestamp as YYYY-MM-DDTHH:MM:SSZ."),
        "manual_attestation_signed_at_invalid": ("MEMORIAL_ROOM_ATTESTATION_SIGNED_AT", "Use a UTC timestamp ending in Z, for example 2026-06-25T12:00:00Z."),
        "public_origin_required": ("MEMORIAL_PUBLIC_ORIGIN", "Use a real public origin, not localhost."),
        "dirty_worktree": ("source_worktree", "Commit or stash source changes before recording the final clean room-audio receipt."),
    }
    for code in failed_codes:
        if code in env_hints:
            name, description = env_hints[code]
            add(code, "env" if name.startswith("MEMORIAL_") else "source", name, description)
    return hints


def _append_blocked_component(
    blocker_summary: dict[str, object],
    *,
    key: str,
    label: str,
    issues: list[str],
    next_action: str,
) -> dict[str, object]:
    payload = dict(blocker_summary or {})
    blocked_keys = [
        str(item).strip()
        for item in list(payload.get("blocked_component_keys") or [])
        if str(item).strip()
    ]
    blocked_components = [
        dict(item)
        for item in list(payload.get("blocked_components") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]
    if key in blocked_keys:
        return payload
    blocked_keys.append(key)
    blocked_components.append(
        {
            "key": key,
            "code": key,
            "label": label,
            "component": label,
            "issues": [str(item).strip() for item in issues if str(item).strip()],
            "next_action": str(next_action or "").strip(),
            "next_command": _memorial_next_command_for_action(next_action),
        }
    )
    payload["blocked_component_keys"] = blocked_keys
    payload["blocked_components"] = blocked_components
    payload["blocked_commands"] = [
        str(item.get("next_command") or "").strip()
        for item in blocked_components
        if str(item.get("next_command") or "").strip()
    ]
    payload["blocked_count"] = len(blocked_keys)
    return payload


def _memorial_next_command_for_action(action: str) -> str:
    normalized = str(action or "").strip()
    if normalized == "commit_or_stash_source_changes_before_clean_receipts":
        return "scripts/inspect_source_dirty_groups.py --list-categories"
    if normalized == "verify_source_dirty_groups_before_source_cleanup":
        return "make verify-source-dirty-groups"
    if normalized == "clear_release_authority_for_memorial_deploy":
        return "python3 scripts/verify_release_authority.py --pretty"
    if normalized == "deploy_ea_memorial":
        return "make deploy-ea-memorial"
    if normalized in {
        "allow_anonymous_public_memorial_origin_access",
        "republish_public_memorial_bundle_or_fix_slug",
        "inspect_public_memorial_origin_http_failure",
    }:
        return "GET /memorials/manfred and /memorials/manfred.json on the configured public origin"
    if normalized == "refresh_memorial_public_auto_receipts_clean":
        return "make materialize-memorial-public-auto-receipts-clean"
    if normalized in {
        "refresh_public_memorial_voice_receipt",
        "refresh_public_memorial_browser_receipt",
        "refresh_meaningful_memorial_browser_receipt",
    }:
        return "make materialize-memorial-public-auto-receipts-clean"
    if normalized == "refresh_local_memorial_voice_receipt":
        return "make materialize-memorial-public-voice-gold"
    if normalized == "collect_real_room_audio_attestation":
        return "make materialize-memorial-room-audio-gold-clean"
    if normalized == "fix_mounted_memorial_surface_contract":
        return "python3 scripts/verify_project_mode_runtime.py --mode memorial"
    return ""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the Manfred memorial operator-status projection."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--deploy-context", type=Path, default=DEFAULT_DEPLOY_CONTEXT)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument(
        "--release-authority-status",
        type=Path,
        default=DEFAULT_RELEASE_AUTHORITY_STATUS,
    )
    return parser.parse_args(argv)


def _configure_paths(args: argparse.Namespace) -> None:
    global OUTPUT, DEPLOY_CONTEXT, RELEASE_MANIFEST, RELEASE_AUTHORITY_STATUS
    OUTPUT = Path(args.output).expanduser().resolve()
    DEPLOY_CONTEXT = Path(args.deploy_context).expanduser().resolve()
    RELEASE_MANIFEST = Path(args.release_manifest).expanduser().resolve()
    RELEASE_AUTHORITY_STATUS = Path(args.release_authority_status).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_paths(args)
    source_head = resolve_source_state_head(ROOT)
    source_worktree = source_worktree_metadata(ROOT, dirty_path_limit=SOURCE_DIRTY_FILE_LIMIT)
    source_dirty_summary = _source_dirty_summary(source_worktree)
    readiness = _run_json("scripts/verify_memorial_gold_readiness.py")
    whole_project = _run_json("scripts/verify_whole_project_gold_map.py")
    memorial_surface_contract = _run_json(["scripts/verify_project_mode_runtime.py", "--mode", "memorial"])
    whole_project_map = _load_json(WHOLE_PROJECT_GOLD_MAP)
    whole_project_gold = "blocked"
    whole_project_verifier_status = str(whole_project.get("status") or "blocked").strip().lower()
    if (
        whole_project_verifier_status == "pass"
        and whole_project_map.get("gold_claim_allowed") is True
        and str(whole_project_map.get("overall_status") or "").strip().lower() == "gold"
    ):
        whole_project_gold = "pass"
    elif whole_project_map:
        whole_project_gold = "blocked"
    else:
        whole_project_gold = "unknown"

    readiness_status = str(readiness.get("status") or "blocked").strip().lower()
    has_any_readiness_issues = bool(
        list(readiness.get("local_release_issues") or [])
        or list(readiness.get("public_gold_issues") or [])
        or list(readiness.get("public_browser_gold_issues") or [])
        or list(readiness.get("public_meaningful_browser_gold_issues") or [])
        or list(readiness.get("memorial_surface_contract_issues") or [])
        or list(readiness.get("room_audio_issues") or [])
        or list(readiness.get("receipt_set_binding_issues") or [])
    )
    memorial_public_gold_claim_allowed = not has_any_readiness_issues and (
        readiness_status == "pass"
        or (
            readiness.get("memorial_voice_gold_claim_allowed") is True
        )
    )
    memorial_public_gold_allowed = memorial_public_gold_claim_allowed
    final_status = "pass" if memorial_public_gold_allowed else "blocked"
    readiness_next_action = str(readiness.get("next_action") or "inspect_memorial_gold_blockers").strip()
    readiness_next_command = str(readiness.get("next_command") or "").strip()
    source_dirty_verifier = dict(readiness.get("source_dirty_verifier") or {})
    source_dirty_verifier_status = str(source_dirty_verifier.get("status") or "missing").strip().lower()
    memorial_public_gold_next_action = readiness_next_action
    memorial_public_gold_blocker_summary = dict(readiness.get("blocker_summary") or {})
    workflow_backing = _workflow_backing_status(
        PUBLIC_VOICE_RECEIPT,
        PUBLIC_BROWSER_RECEIPT,
        MEANINGFUL_BROWSER_RECEIPT,
        ROOM_AUDIO_RECEIPT,
    )
    spatial_tour_payload = _load_json(SPATIAL_TOUR_RECEIPT)
    spatial_tour_issues = [
        str(item).strip()
        for item in list(readiness.get("public_spatial_tour_issues") or [])
        if str(item).strip()
    ]
    spatial_tour_detail = {
        "status": "pass"
        if spatial_tour_payload and not spatial_tour_issues
        else "missing_or_blocked",
        "scope": "separate_propertyquarry_lane",
        "memorial_gold_dependency": False,
        "receipt_path": _display_path(SPATIAL_TOUR_RECEIPT),
        "contract_name": str(spatial_tour_payload.get("contract_name") or "").strip(),
        "tour_slug": str(spatial_tour_payload.get("tour_slug") or "").strip(),
        "public_base_url": str(spatial_tour_payload.get("public_base_url") or "").strip(),
        "runtime_revision": str(spatial_tour_payload.get("runtime_revision") or "").strip(),
        "package_sha256": str(
            dict(spatial_tour_payload.get("package_binding") or {}).get(
                "package_sha256"
            )
            or ""
        ).strip(),
        "publication_authority": dict(
            spatial_tour_payload.get("publication_authority") or {}
        ),
        "deploy_binding": dict(spatial_tour_payload.get("deploy_binding") or {}),
        "issues": spatial_tour_issues,
    }
    public_voice_semantics = _public_voice_receipt_semantics()
    spoken_stt_status = _spoken_stt_provider_benchmark_status()
    stt_fixture_candidate = _stt_fixture_candidate_status()
    stt_capture_discovery = _stt_capture_discovery_status()
    captured_candidate_benchmark = _captured_candidate_benchmark_status()
    captured_candidate_diagnostic = _captured_candidate_diagnostic_status()
    spoken_stt_status = _reconcile_spoken_stt_next_action(
        spoken_stt_status,
        stt_fixture_candidate,
        captured_candidate_benchmark,
        captured_candidate_diagnostic,
    )
    spoken_tts_status = _spoken_tts_playback_status()
    room_attestation_packet = _room_audio_attestation_packet_status()
    room_audio_receipt_detail = _room_audio_receipt_detail()
    public_runtime_status = _memorial_public_runtime_status()
    public_origin_access = _public_origin_access_status(slug="manfred")
    release_authority_status = _release_authority_status()
    if str(public_runtime_status.get("status") or "").strip().lower() in {"blocked", "missing"}:
        memorial_public_gold_blocker_summary = _append_blocked_component(
            memorial_public_gold_blocker_summary,
            key="public_runtime_mode",
            label="Public runtime mode",
            issues=[str(public_runtime_status.get("reason") or "public_runtime_mode_blocked").strip()],
            next_action=str(public_runtime_status.get("next_action") or "deploy_ea_memorial").strip(),
        )
        if str(release_authority_status.get("status") or "").strip().lower() in {"blocked", "missing"}:
            memorial_public_gold_blocker_summary = _append_blocked_component(
                memorial_public_gold_blocker_summary,
                key="release_authority",
                label="Release authority",
                issues=[
                    str(item).strip()
                    for item in list(release_authority_status.get("issues") or [])
                    if str(item).strip()
                ] or [str(release_authority_status.get("authority_posture") or "release_authority_blocked").strip()],
                next_action="clear_release_authority_for_memorial_deploy",
            )
            memorial_public_gold_next_action = "clear_release_authority_for_memorial_deploy"
        else:
            memorial_public_gold_next_action = str(
                public_runtime_status.get("next_action") or "deploy_ea_memorial"
            ).strip()
    elif str(public_origin_access.get("status") or "").strip().lower() in {"access_blocked", "blocked", "missing"}:
        memorial_public_gold_next_action = str(
            public_origin_access.get("next_action") or "inspect_public_memorial_origin_http_failure"
        ).strip()
    if (
        bool(source_worktree.get("source_worktree_dirty"))
        and memorial_public_gold_next_action == "refresh_memorial_public_auto_receipts_clean"
    ):
        source_worktree_issues = ["source_worktree_dirty"]
        if source_dirty_verifier_status != "pass":
            source_worktree_issues.append("source_dirty_group_verifier_failed")
        memorial_public_gold_blocker_summary = _append_blocked_component(
            memorial_public_gold_blocker_summary,
            key="source_worktree",
            label="Source worktree",
            issues=source_worktree_issues,
            next_action="commit_or_stash_source_changes_before_clean_receipts",
        )
        memorial_public_gold_next_action = (
            "verify_source_dirty_groups_before_source_cleanup"
            if source_dirty_verifier_status != "pass"
            else "commit_or_stash_source_changes_before_clean_receipts"
        )
    memorial_public_gold_next_command = (
        readiness_next_command
        if memorial_public_gold_next_action == readiness_next_action and readiness_next_command
        else _memorial_next_command_for_action(memorial_public_gold_next_action)
    )
    source_cleanup = dict(readiness.get("source_cleanup") or {})
    if not source_cleanup:
        source_cleanup = _source_cleanup_payload(
            source_worktree=source_worktree,
            source_dirty_summary=source_dirty_summary,
            source_dirty_verifier=source_dirty_verifier,
            next_action=memorial_public_gold_next_action,
            next_command=memorial_public_gold_next_command,
        )
    else:
        source_cleanup.setdefault("next_action", "")
        source_cleanup.setdefault("next_command", "")
        if bool(source_worktree.get("source_worktree_dirty")) and not str(source_cleanup.get("next_action") or "").strip():
            source_cleanup["next_action"] = memorial_public_gold_next_action
            source_cleanup["next_command"] = memorial_public_gold_next_command
    payload = {
        "contract_name": "ea.memorial_operator_status",
        "generated_by": "scripts/materialize_memorial_operator_status.py",
        "source_git_head": source_head,
        "head_semantics": "source_state",
        "source_worktree_dirty": bool(source_worktree.get("source_worktree_dirty")),
        "source_dirty_count": int(source_worktree.get("source_dirty_count") or 0),
        "source_dirty_files": list(source_worktree.get("source_dirty_files") or []),
        "source_dirty_omitted_count": int(source_worktree.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(source_worktree.get("source_dirty_status_sha256") or ""),
        "source_dirty_summary": source_dirty_summary,
        "source_dirty_verifier": source_dirty_verifier,
        "source_cleanup": source_cleanup,
        "slug": "manfred",
        "memorial_surface": "conversation_only",
        "spatial_scope": "separate_propertyquarry_lane",
        "status": final_status,
        "current_label": "Memorial public-origin gold: pass" if final_status == "pass" else "Memorial public-origin gold: blocked",
        "local_release_candidate": "pass" if not list(readiness.get("local_release_issues") or []) else "blocked",
        "public_voice_receipt": "pass" if not list(readiness.get("public_gold_issues") or []) else "missing_or_blocked",
        "public_browser_receipt": "pass" if not list(readiness.get("public_browser_gold_issues") or []) else "missing_or_blocked",
        "public_browser_meaningful_receipt": _receipt_state(MEANINGFUL_BROWSER_RECEIPT),
        "public_runtime_mode": str(public_runtime_status.get("status") or "missing_or_blocked").strip(),
        "public_origin_access": str(public_origin_access.get("status") or "missing_or_blocked").strip(),
        "memorial_surface_contract": "pass" if str(memorial_surface_contract.get("status") or "").strip().lower() == "pass" else "missing_or_blocked",
        "room_audio_receipt": "pass" if not list(readiness.get("room_audio_issues") or []) else "missing_or_blocked",
        "public_spatial_tour_receipt": "separate_non_memorial_plane",
        "propertyquarry_spatial_lane": spatial_tour_detail,
        "whole_project_gold": whole_project_gold,
        "memorial_public_gold_next_action": memorial_public_gold_next_action,
        "memorial_public_gold_next_command": memorial_public_gold_next_command,
        "memorial_public_gold_blocker_summary": memorial_public_gold_blocker_summary,
        "operator_notes": [
            "Use labels only: Memorial local release candidate / Memorial public-origin gold: blocked|pass.",
            "Public-origin Memorial gold requires current voice, browser, meaningful-browser, and room receipts for the conversation-only surface.",
            "PropertyQuarry spatial/3D proof is reported as a separate non-Memorial plane and never blocks the Memorial candidate, deploy, public receipt set, or gold label.",
            "If public_runtime_mode is blocked, the configured public origin is not currently deployed in MEMORIAL mode; use make deploy-ea-memorial before treating public memorial routes as publishable.",
            "If release_authority.status is blocked while public_runtime_mode is blocked, clear release authority first; memorial deploy claims must not be refreshed from a dirty tree or stale deploy context.",
            "If local/public/browser memorial receipts are stale or missing, refresh the non-manual proof set first with scripts/materialize_memorial_public_auto_receipts_clean.py before asking for a fresh room/device attestation.",
            "If public_origin_access is access_blocked, the deployed memorial page or manifest is not anonymously reachable at the configured public edge; fix that before trying to refresh the public receipt set again.",
            "memorial_surface_contract is a runtime contract proof that the mounted memorial surface still serves a memorial page and manifest; it is not itself a public-origin gold receipt.",
            "The current public voice receipt is a provenance proof when its transcriber mode is provenance_cache; browser + room receipts carry the intelligibility proof.",
            "source_git_head records the proved source state; a later artifact-only commit may differ without making the proof stale.",
            "whole_project_gold is reported separately and must not block a memorial-specific public-origin pass when unrelated planes remain not_gold.",
            "Manfred premium spoken conversation additionally requires spoken_conversation_stt.status=pass and spoken_conversation_tts.premium_status=pass; memorial public-origin gold alone is not a production STT/TTS claim.",
            "If source_worktree_dirty is true, the receipt is an operator snapshot with pending source changes and must not be used as final release evidence.",
            "If source_dirty_verifier.status is not pass, run make verify-source-dirty-groups before using the source-dirty groups for cleanup or handoff.",
            "source_cleanup is the compact operator handoff for source cleanup status, verifier state, top categories, and the next source-safe command.",
            "If source_worktree_dirty is true and the next proof step is clean receipt refresh, commit or stash source changes first; clean-clone receipt refresh intentionally refuses dirty source inputs.",
            "Use source_dirty_summary to review affected source groups before committing; start with api_routes/services/scripts/deploy_runtime before generated artifacts or docs.",
            "If room_audio_receipt is missing_or_blocked, use room_audio_attestation_packet to collect the required real-room evidence; CI must not auto-assert manual room checks.",
            "If spoken_conversation_stt.ground_truth_fixture_mode is synthetic_only, use stt_fixture_candidate to promote only a consented, plausible captured clip; normalize suspect WAV/WebM captures first.",
            "If stt_capture_discovery matched bundles but has no promotable captures, the logged audio is not enough for real captured STT regression proof.",
            "If captured_candidate_benchmark is blocked, do not promote the captured clip until the operator confirms ground truth or the STT lane recognizes the captured speech.",
            "If captured_candidate_diagnostic is blocked with transcript_hash_mismatch, rerun full-text diagnostics only operator-locally or correct the ground-truth transcript; do not commit raw transcript receipts.",
        ],
        "source_head_note": "source_git_head records the source state the receipts prove. Generated-only follow-up commits may change repository HEAD without invalidating those receipts. source_worktree_dirty records whether source-relevant local changes were present when this operator snapshot was generated.",
        "artifact_paths": {
            "local_release_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"),
            "public_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"),
            "public_browser_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"),
            "public_meaningful_browser_gold_receipt": _display_path(MEANINGFUL_BROWSER_RECEIPT),
            "public_auto_receipts_clean": "scripts/materialize_memorial_public_auto_receipts_clean.py",
            "public_memorial_deploy": "make deploy-ea-memorial",
            "release_authority_probe": "python3 scripts/verify_release_authority.py --pretty",
            "release_authority_status": _display_path(RELEASE_AUTHORITY_STATUS),
            "public_origin_probe": "GET /memorials/manfred and /memorials/manfred.json on the configured public origin",
            "memorial_surface_contract": "scripts/verify_project_mode_runtime.py --mode memorial",
            "room_audio_receipt": _display_path(ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"),
            "propertyquarry_spatial_receipt": _display_path(SPATIAL_TOUR_RECEIPT),
            "room_audio_attestation_packet": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
            "spoken_stt_provider_benchmark": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
            "stt_fixture_candidate": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
            "stt_capture_discovery": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
            "captured_candidate_benchmark": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
            "captured_candidate_diagnostic": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
        },
        "readiness": readiness,
        "evidence_heads": {
            "whole_project_map": str(whole_project_map.get("source_git_head") or whole_project_map.get("git_head") or "").strip(),
            "public_voice_receipt": _receipt_git_head(PUBLIC_VOICE_RECEIPT),
            "public_browser_receipt": _receipt_git_head(PUBLIC_BROWSER_RECEIPT),
            "public_meaningful_browser_receipt": _receipt_git_head(MEANINGFUL_BROWSER_RECEIPT),
            "room_audio_receipt": _receipt_git_head(ROOM_AUDIO_RECEIPT),
            "propertyquarry_spatial_receipt": _receipt_git_head(SPATIAL_TOUR_RECEIPT),
        },
        "workflow_backing": workflow_backing,
        "release_authority": release_authority_status,
        "public_runtime_mode_detail": public_runtime_status,
        "public_origin_access_detail": public_origin_access,
        "memorial_surface_contract_detail": memorial_surface_contract,
        "public_voice_receipt_semantics": public_voice_semantics,
        "room_audio_receipt_detail": room_audio_receipt_detail,
        "propertyquarry_spatial_lane_detail": spatial_tour_detail,
        "room_audio_attestation_packet": room_attestation_packet,
        "spoken_conversation_stt": spoken_stt_status,
        "stt_fixture_candidate": stt_fixture_candidate,
        "stt_capture_discovery": stt_capture_discovery,
        "captured_candidate_benchmark": captured_candidate_benchmark,
        "captured_candidate_diagnostic": captured_candidate_diagnostic,
        "spoken_conversation_tts": spoken_tts_status,
        "whole_project": whole_project,
        "whole_project_map_summary": {
            "overall_status": whole_project_map.get("overall_status", ""),
            "gold_claim_allowed": whole_project_map.get("gold_claim_allowed"),
            "blocking_planes": list(whole_project_map.get("blocking_planes") or []),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": final_status,
                "output": OUTPUT.as_posix(),
                "current_label": payload["current_label"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
