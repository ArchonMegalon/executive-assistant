#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

try:
    from scripts.inspect_source_dirty_groups import PRIORITY_CATEGORY_REASONS
    from scripts.materialize_memorial_operator_status import _source_dirty_summary
    from scripts.memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from scripts.source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
        source_worktree_metadata,
    )
    from scripts.verify_source_dirty_groups import VERIFY_CONTRACT_NAME, _validate_report as _validate_source_dirty_report
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from inspect_source_dirty_groups import PRIORITY_CATEGORY_REASONS
    from materialize_memorial_operator_status import _source_dirty_summary
    from memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from source_state_head import resolve_source_state_head, resolve_source_worktree_fingerprint, source_worktree_metadata
    from verify_source_dirty_groups import VERIFY_CONTRACT_NAME, _validate_report as _validate_source_dirty_report


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRTY_FILE_LIMIT = 10000
LOCAL_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
PUBLIC_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
MEANINGFUL_BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json"
ROOM_RECEIPT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
SPATIAL_RECEIPT = ROOT / ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
}
SOURCE_STATE_FINGERPRINT_SEMANTICS = "worktree_source_files_sha256_excluding_generated_only_paths"
BROWSER_RECEIPT_CONTRACT_VERSION = 3


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _run_script_json(script_args: list[str]) -> dict[str, Any]:
    if not script_args:
        return {"status": "error", "error": "empty_script_args"}
    proc = subprocess.run(
        [sys.executable, str(ROOT / script_args[0]), *script_args[1:]],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        payload = json.loads(output or "{}")
    except Exception:
        return {
            "status": "error",
            "script": " ".join(script_args),
            "stdout": proc.stdout[:800],
            "stderr": proc.stderr[:800],
        }
    return dict(payload) if isinstance(payload, dict) else {"status": "error", "payload_type": type(payload).__name__}


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _source_fingerprint() -> str:
    return resolve_source_worktree_fingerprint(ROOT)


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


_RESERVED_PUBLIC_HOST_SUFFIXES = frozenset(
    {
        "alt",
        "arpa",
        "example",
        "example.com",
        "example.net",
        "example.org",
        "home.arpa",
        "internal",
        "invalid",
        "lan",
        "local",
        "localdomain",
        "localhost",
        "onion",
        "test",
    }
)


def _dns_host_resolves_globally(hostname: str) -> bool:
    try:
        canonical = hostname.encode("idna").decode("ascii").rstrip(".").lower()
    except UnicodeError:
        return False
    if not canonical or "." not in canonical or any(
        canonical == suffix or canonical.endswith(f".{suffix}")
        for suffix in _RESERVED_PUBLIC_HOST_SUFFIXES
    ):
        return False
    try:
        records = socket.getaddrinfo(
            canonical,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return False
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        for family, _socket_type, _protocol, _canonical_name, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            addresses.add(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
    except (IndexError, TypeError, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


def _public_hostname_allowed(hostname: str) -> bool:
    if not hostname or "%" in hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return _dns_host_resolves_globally(hostname)


def _is_https_public_origin(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").rstrip(".").lower()
    return bool(
        parsed.scheme.lower() == "https"
        and hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
        and _public_hostname_allowed(hostname)
    )


def _metric(receipt: dict[str, Any], key: str) -> float:
    try:
        return float(dict(receipt.get("metrics") or {}).get(key) or 0.0)
    except Exception:
        return 0.0


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _receipt_source_head(receipt: dict[str, Any]) -> str:
    return str(receipt.get("source_git_head") or receipt.get("git_head") or "")


def _receipt_source_state_current(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
) -> bool:
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    return bool(
        receipt.get("head_semantics") == "source_state"
        and receipt.get("source_state_fingerprint_semantics") == SOURCE_STATE_FINGERPRINT_SEMANTICS
        and recorded_fingerprint
        and current_fingerprint
        and recorded_fingerprint == current_fingerprint
        and _fresh_enough(_receipt_source_head(receipt), current_head=current_head)
    )


def _generated_only_receipt_delta_ok(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
) -> bool:
    return _receipt_source_state_current(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    )


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except Exception:
        return float(default)


def _check_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
    public_required: bool,
    direct_min_f1: float,
    conversation_min_f1: float,
    max_conversation_turn_ms: float | None = None,
    max_speech_transcribe_ms: float | None = None,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_voice_roundtrip_exit_gate":
        issues.append("contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("receipt_status_not_pass")
    if current_head and not _receipt_source_state_current(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("receipt_generated_from_dirty_worktree")
    if receipt.get("failed_codes"):
        issues.append("receipt_failed_codes_present")
    if receipt.get("warned_codes"):
        issues.append("receipt_warned_codes_present")
    if public_required:
        if not _is_https_public_origin(str(receipt.get("base_url") or "")):
            issues.append("public_origin_must_be_nonlocal_https")
        runtime_revision = str(receipt.get("runtime_source_revision") or "").strip()
        if not _is_source_revision(runtime_revision):
            issues.append("public_runtime_source_revision_missing_or_invalid")
        elif (
            _is_source_revision(_receipt_source_head(receipt))
            and runtime_revision != _receipt_source_head(receipt)
        ):
            issues.append("public_runtime_source_revision_source_mismatch")
        if receipt.get("gold_mode") is not True:
            issues.append("public_gold_receipt_must_use_gold_mode")
        if receipt.get("require_public_origin") is not True:
            issues.append("public_gold_receipt_must_require_public_origin")
        if receipt.get("gold_claim_allowed") is not True:
            issues.append("public_gold_claim_not_allowed_by_receipt")
    if _metric(receipt, "direct_tts_f1") < direct_min_f1:
        issues.append("direct_tts_f1_below_gold_threshold")
    if _metric(receipt, "conversation_turn_audio_f1") < conversation_min_f1:
        issues.append("conversation_turn_audio_f1_below_gold_threshold")
    if max_conversation_turn_ms is not None and _metric(receipt, "conversation_turn_total_ms") > float(max_conversation_turn_ms):
        issues.append("conversation_turn_total_ms_above_gold_threshold")
    if max_speech_transcribe_ms is not None and _metric(receipt, "speech_transcribe_ms") > float(max_speech_transcribe_ms):
        issues.append("speech_transcribe_ms_above_gold_threshold")
    raw_checks = receipt.get("checks") or []
    checks = list(raw_checks) if isinstance(raw_checks, list) else []
    if not isinstance(raw_checks, list):
        issues.append("receipt_checks_invalid")
    check_codes = {str(item.get("code") or "") for item in checks if isinstance(item, dict)}
    if "present_world_route_ok" not in check_codes:
        issues.append("local_source_current_world_check_missing")
    serialized = json.dumps(receipt, ensure_ascii=False).lower()
    if "present_world_search" in serialized:
        issues.append("present_world_search_reference_forbidden")
    return issues


def _check_browser_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
    max_first_answer_ms: float,
    require_live_stt: bool = True,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["browser_receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_realtime_browser_exit_gate":
        issues.append("browser_contract_name_invalid")
    if receipt.get("contract_version") != BROWSER_RECEIPT_CONTRACT_VERSION:
        issues.append("browser_contract_version_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("browser_receipt_status_not_pass")
    if current_head and not _receipt_source_state_current(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("browser_receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("browser_receipt_generated_from_dirty_worktree")
    if not _is_https_public_origin(str(receipt.get("base_url") or "")):
        issues.append("browser_public_origin_must_be_nonlocal_https")
    runtime_revision = str(receipt.get("runtime_source_revision") or "").strip()
    if not _is_source_revision(runtime_revision):
        issues.append("browser_runtime_source_revision_missing_or_invalid")
    elif (
        _is_source_revision(_receipt_source_head(receipt))
        and runtime_revision != _receipt_source_head(receipt)
    ):
        issues.append("browser_runtime_source_revision_source_mismatch")
    if receipt.get("gold_mode") is not True:
        issues.append("browser_gold_receipt_must_use_gold_mode")
    if receipt.get("require_public_origin") is not True:
        issues.append("browser_gold_receipt_must_require_public_origin")
    if receipt.get("gold_claim_allowed") is not True:
        issues.append("browser_gold_claim_not_allowed_by_receipt")
    mode = str(receipt.get("speech_transcribe_mode") or "").strip().lower()
    if require_live_stt and mode != "live":
        issues.append("browser_gold_receipt_must_use_live_stt")
    if not require_live_stt and mode not in {"text_prompt", "live"}:
        issues.append("browser_meaningful_receipt_mode_invalid")
    if receipt.get("failed_codes"):
        issues.append("browser_failed_codes_present")
    first_answer_ms = _safe_float(receipt.get("first_answer_ms"))
    if first_answer_ms is None:
        issues.append("browser_first_answer_ms_invalid")
    elif first_answer_ms > float(max_first_answer_ms):
        issues.append("browser_first_answer_ms_above_gold_threshold")
    if not bool(receipt.get("audio_ready_for_ui")):
        issues.append("browser_audio_not_ready_for_ui")
    if not bool(receipt.get("answer_text_visible")):
        issues.append("browser_answer_text_not_visible")
    if not bool(receipt.get("ui_audio_play_calls")):
        issues.append("browser_audio_playback_not_started")
    if not bool(receipt.get("ui_audio_play_ended")) and not receipt.get("ui_audio_play_error"):
        issues.append("browser_audio_playback_not_completed")
    if not bool(receipt.get("answer_semantic_passed")):
        issues.append("browser_answer_semantics_not_proven")
    return issues


def _check_room_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["room_receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_room_audio_public_origin":
        issues.append("room_contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("room_receipt_status_not_pass")
    if current_head and not _receipt_source_state_current(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("room_receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    ):
        issues.append("room_receipt_generated_from_dirty_worktree")
    if not _is_https_public_origin(str(receipt.get("base_url") or "")):
        issues.append("room_public_origin_must_be_nonlocal_https")
    runtime_revision = str(receipt.get("runtime_source_revision") or "").strip()
    if not _is_source_revision(runtime_revision):
        issues.append("room_runtime_source_revision_missing_or_invalid")
    elif (
        _is_source_revision(_receipt_source_head(receipt))
        and runtime_revision != _receipt_source_head(receipt)
    ):
        issues.append("room_runtime_source_revision_source_mismatch")
    if receipt.get("require_public_origin") is not True:
        issues.append("room_receipt_must_require_public_origin")
    if str(receipt.get("proof_type") or "").strip() != "manual_room_attestation":
        issues.append("room_manual_attestation_proof_type_missing")
    raw_attestation = receipt.get("manual_attestation")
    if not isinstance(raw_attestation, dict):
        issues.append("room_manual_attestation_invalid")
        attestation: dict[str, Any] = {}
    else:
        attestation = dict(raw_attestation)
    if not str(attestation.get("attestation_id") or "").strip():
        issues.append("room_manual_attestation_id_missing")
    if not str(attestation.get("signed_at") or "").strip():
        issues.append("room_manual_attestation_signed_at_missing")
    if attestation.get("ci_must_not_auto_assert") is not True:
        issues.append("room_manual_attestation_ci_guard_missing")
    required = {
        "actual_device_checked",
        "actual_speaker_checked",
        "first_syllable_not_clipped",
        "intelligibility_confirmed",
        "answer_text_fallback_visible",
        "no_internet_search_confirmed",
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
        "retry_path_confirmed",
    }
    raw_checks = receipt.get("checks")
    if not isinstance(raw_checks, dict):
        issues.append("room_checks_invalid")
        checks: dict[str, Any] = {}
    else:
        checks = dict(raw_checks)
    for key in sorted(required):
        if checks.get(key) is not True:
            issues.append(f"room_{key}_missing")
    if not str(receipt.get("reviewer") or "").strip():
        issues.append("room_reviewer_missing")
    return issues


def _check_spatial_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    current_fingerprint: str,
) -> list[str]:
    return validate_memorial_spatial_public_origin_receipt(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    )


def _check_memorial_surface_contract(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not payload:
        return ["memorial_surface_contract_missing_or_invalid"]
    if str(payload.get("mode") or "").strip().lower() != "memorial":
        issues.append("memorial_surface_contract_mode_invalid")
    if str(payload.get("status") or "").strip().lower() != "pass":
        issues.append("memorial_surface_contract_status_not_pass")
    return issues


def _blocker_summary(
    *,
    local_issues: list[str],
    public_issues: list[str],
    browser_issues: list[str],
    meaningful_browser_issues: list[str],
    memorial_surface_contract_issues: list[str],
    room_issues: list[str],
    receipt_set_issues: list[str] | None = None,
    spatial_issues: list[str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if local_issues:
        blockers.append(
            {
                "key": "local_release_receipt",
                "label": "Local release receipt",
                "issues": list(local_issues),
                "next_action": "refresh_local_memorial_voice_receipt",
            }
        )
    if public_issues:
        blockers.append(
            {
                "key": "public_voice_receipt",
                "label": "Public voice receipt",
                "issues": list(public_issues),
                "next_action": "refresh_public_memorial_voice_receipt",
            }
        )
    if browser_issues:
        blockers.append(
            {
                "key": "public_browser_receipt",
                "label": "Public browser receipt",
                "issues": list(browser_issues),
                "next_action": "refresh_public_memorial_browser_receipt",
            }
        )
    if meaningful_browser_issues:
        blockers.append(
            {
                "key": "meaningful_browser_receipt",
                "label": "Meaningful browser receipt",
                "issues": list(meaningful_browser_issues),
                "next_action": "refresh_meaningful_memorial_browser_receipt",
            }
        )
    if memorial_surface_contract_issues:
        blockers.append(
            {
                "key": "memorial_surface_contract",
                "label": "Mounted memorial surface contract",
                "issues": list(memorial_surface_contract_issues),
                "next_action": "fix_mounted_memorial_surface_contract",
            }
        )
    if room_issues:
        blockers.append(
            {
                "key": "room_audio_receipt",
                "label": "Room audio receipt",
                "issues": list(room_issues),
                "next_action": "collect_real_room_audio_attestation",
            }
        )
    if spatial_issues:
        blockers.append(
            {
                "key": "public_spatial_tour_receipt",
                "label": "Public spatial-tour receipt",
                "issues": list(spatial_issues),
                "next_action": "refresh_memorial_public_auto_receipts_clean",
            }
        )
    if receipt_set_issues:
        blockers.append(
            {
                "key": "receipt_set_binding",
                "label": "Public receipt-set binding",
                "issues": list(receipt_set_issues),
                "next_action": "refresh_memorial_public_auto_receipts_clean",
            }
        )
    for blocker in blockers:
        key = str(blocker.get("key") or "").strip()
        label = str(blocker.get("label") or "").strip()
        blocker.setdefault("code", key)
        blocker.setdefault("component", label or key)
        next_action = str(blocker.get("next_action") or "").strip()
        blocker["next_command"] = _next_command_for_action(next_action)
    return {
        "blocked_components": blockers,
        "blocked_component_keys": [str(item["key"]) for item in blockers],
        "blocked_commands": [
            str(item.get("next_command") or "").strip()
            for item in blockers
            if str(item.get("next_command") or "").strip()
        ],
        "blocked_count": len(blockers),
    }


def _source_dirty_drilldown_command(category: str) -> str:
    normalized = str(category or "").strip()
    if not normalized:
        return ""
    return f"scripts/inspect_source_dirty_groups.py --category {normalized} --limit 20"


def _source_dirty_report_from_summary(
    *,
    source_worktree: dict[str, Any],
    source_dirty_summary: dict[str, Any],
) -> dict[str, Any]:
    status = "dirty" if bool(source_worktree.get("source_worktree_dirty")) else "clean"
    summary = dict(source_dirty_summary or {})
    categories: list[dict[str, Any]] = []
    drilldown_commands: list[str] = []
    for item in list(summary.get("categories") or []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        category = str(row.get("category") or "").strip()
        command = _source_dirty_drilldown_command(category)
        if command:
            row["drilldown_command"] = command
            if command not in drilldown_commands:
                drilldown_commands.append(command)
        categories.append(row)
    summary["categories"] = categories
    priority_groups = [
        {
            "category": category,
            "visible_count": int(row.get("visible_count") or 0),
            "reason": PRIORITY_CATEGORY_REASONS[category],
            "drilldown_command": str(row.get("drilldown_command") or _source_dirty_drilldown_command(category)).strip(),
        }
        for row in categories
        for category in [str(row.get("category") or "").strip()]
        if category in PRIORITY_CATEGORY_REASONS and int(row.get("visible_count") or 0) > 0
    ]
    if status == "dirty":
        recommended_commands = [
            "git status --short",
            "scripts/inspect_source_dirty_groups.py --list-categories",
            "scripts/inspect_source_dirty_groups.py --category <category> --limit 20",
            "make inspect-source-dirty-groups",
            "commit or stash source groups before clean receipt refresh",
            "make materialize-memorial-public-auto-receipts-clean",
        ]
    else:
        recommended_commands = [
            "make materialize-memorial-public-auto-receipts-clean",
            "make materialize-memorial-public-gold",
        ]
    return {
        "contract_name": "ea.source_dirty_groups.v1",
        "status": status,
        "source_worktree": dict(source_worktree or {}),
        "source_dirty_summary": summary,
        "priority_groups": priority_groups,
        "recommended_commands": recommended_commands,
        "category_drilldown_commands": drilldown_commands,
    }


def _source_dirty_verifier_payload(
    *,
    source_worktree: dict[str, Any],
    source_dirty_summary: dict[str, Any],
) -> dict[str, Any]:
    report = _source_dirty_report_from_summary(
        source_worktree=source_worktree,
        source_dirty_summary=source_dirty_summary,
    )
    issues = _validate_source_dirty_report(report)
    summary = dict(report.get("source_dirty_summary") or {})
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    return {
        "contract_name": VERIFY_CONTRACT_NAME,
        "status": "pass" if not issues else "blocked",
        "issues": issues,
        "source_dirty_status": report.get("status") or "",
        "source_dirty_count": int(summary.get("total_count") or source_worktree.get("source_dirty_count") or 0),
        "category_count": len(categories),
        "priority_group_count": len(list(report.get("priority_groups") or [])),
    }


def _source_cleanup_payload(
    *,
    source_worktree: dict[str, Any],
    source_dirty_summary: dict[str, Any],
    source_dirty_verifier: dict[str, Any],
    next_action: str,
    next_command: str,
) -> dict[str, Any]:
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
            "drilldown_command": _source_dirty_drilldown_command(str(item.get("category") or "").strip()),
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
        source_next_command = _next_command_for_action(source_next_action)
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


def _append_source_worktree_blocker(
    summary: dict[str, Any],
    source_worktree: dict[str, Any],
    *,
    source_dirty_verifier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not bool(source_worktree.get("source_worktree_dirty")):
        return summary
    blockers = [dict(item) for item in list(summary.get("blocked_components") or []) if isinstance(item, dict)]
    if any(str(item.get("key") or "") == "source_worktree" for item in blockers):
        return summary
    issues = ["source_worktree_dirty"]
    if source_dirty_verifier and str(source_dirty_verifier.get("status") or "") != "pass":
        issues.append("source_dirty_group_verifier_failed")
    blockers.append(
        {
            "key": "source_worktree",
            "code": "source_worktree",
            "label": "Source worktree",
            "component": "Source worktree",
            "issues": issues,
            "next_action": "commit_or_stash_source_changes_before_clean_receipts",
            "next_command": _next_command_for_action("commit_or_stash_source_changes_before_clean_receipts"),
        }
    )
    return {
        **summary,
        "blocked_components": blockers,
        "blocked_component_keys": [str(item["key"]) for item in blockers],
        "blocked_commands": [
            str(item.get("next_command") or "").strip()
            for item in blockers
            if str(item.get("next_command") or "").strip()
        ],
        "blocked_count": len(blockers),
    }


def _next_action_from_summary(summary: dict[str, Any]) -> str:
    blockers = [dict(item) for item in list(summary.get("blocked_components") or []) if isinstance(item, dict)]
    if not blockers:
        return "maintain_memorial_public_origin_gold"
    surface = next((item for item in blockers if item.get("key") == "memorial_surface_contract"), None)
    if surface is not None:
        return str(surface.get("next_action") or "fix_mounted_memorial_surface_contract")
    auto_receipt_keys = {
        "public_voice_receipt",
        "public_browser_receipt",
        "meaningful_browser_receipt",
        "receipt_set_binding",
        "public_spatial_tour_receipt",
    }
    blocked_keys = {str(item.get("key") or "").strip() for item in blockers}
    if blocked_keys & auto_receipt_keys:
        return "refresh_memorial_public_auto_receipts_clean"
    local = next((item for item in blockers if item.get("key") == "local_release_receipt"), None)
    if local is not None:
        return str(local.get("next_action") or "refresh_local_memorial_voice_receipt")
    room = next((item for item in blockers if item.get("key") == "room_audio_receipt"), None)
    if room is not None:
        return str(room.get("next_action") or "collect_real_room_audio_attestation")
    return str(blockers[0].get("next_action") or "inspect_memorial_gold_blockers")


def _next_command_for_action(action: str) -> str:
    normalized = str(action or "").strip()
    if normalized == "commit_or_stash_source_changes_before_clean_receipts":
        return "scripts/inspect_source_dirty_groups.py --list-categories"
    if normalized == "verify_source_dirty_groups_before_source_cleanup":
        return "make verify-source-dirty-groups"
    if normalized == "refresh_memorial_public_auto_receipts_clean":
        return "make materialize-memorial-public-auto-receipts-clean"
    if normalized in {
        "refresh_public_memorial_voice_receipt",
        "refresh_public_memorial_browser_receipt",
        "refresh_meaningful_memorial_browser_receipt",
        "refresh_public_memorial_spatial_tour_receipt",
    }:
        return "make materialize-memorial-public-auto-receipts-clean"
    if normalized == "refresh_local_memorial_voice_receipt":
        return "make materialize-memorial-public-voice-gold"
    if normalized == "collect_real_room_audio_attestation":
        return "make materialize-memorial-room-audio-gold-clean"
    if normalized == "fix_mounted_memorial_surface_contract":
        return "python3 scripts/verify_project_mode_runtime.py --mode memorial"
    if normalized == "maintain_memorial_public_origin_gold":
        return "make verify-memorial-gold-readiness"
    return ""


def _should_require_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _meaningful_browser_receipt_required() -> bool:
    return not _should_require_truthy(
        os.getenv("MEMORIAL_DIAGNOSTIC_SKIP_MEANINGFUL_BROWSER_RECEIPT")
    )


def _normalized_receipt_origin(value: object) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    scheme = str(parsed.scheme or "").lower()
    hostname = str(parsed.hostname or "").rstrip(".").lower()
    if not scheme or not hostname:
        return ""
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    rendered_port = "" if port in {None, default_port} else f":{port}"
    return f"{scheme}://{rendered_host}{rendered_port}"


def _is_source_revision(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 40 and text == text.lower() and all(
        character in "0123456789abcdef" for character in text
    )


def _receipt_set_binding_issues(
    receipts: dict[str, dict[str, Any]],
    *,
    expected_slug: str,
    current_head: str,
) -> list[str]:
    issues: list[str] = []
    origins: set[str] = set()
    revisions: set[str] = set()
    source_fingerprints: set[str] = set()
    expected_slug = str(expected_slug or "").strip()

    for label, receipt in receipts.items():
        slug = str(receipt.get("slug") or "").strip()
        if not slug:
            issues.append(f"receipt_set_{label}_slug_missing")
        elif slug != expected_slug:
            issues.append(f"receipt_set_{label}_slug_mismatch")

        origin = _normalized_receipt_origin(receipt.get("base_url"))
        if not origin:
            issues.append(f"receipt_set_{label}_origin_missing_or_invalid")
        else:
            origins.add(origin)

        revision = str(receipt.get("runtime_source_revision") or "").strip()
        if not _is_source_revision(revision):
            issues.append(f"receipt_set_{label}_runtime_revision_missing_or_invalid")
        else:
            revisions.add(revision)
            receipt_source_head = _receipt_source_head(receipt).strip()
            if _is_source_revision(receipt_source_head) and revision != receipt_source_head:
                issues.append(f"receipt_set_{label}_runtime_revision_source_mismatch")

        fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
        if not fingerprint:
            issues.append(f"receipt_set_{label}_source_fingerprint_missing")
        else:
            source_fingerprints.add(fingerprint)

    if len(origins) > 1:
        issues.append("receipt_set_origin_mismatch")
    if len(revisions) > 1:
        issues.append("receipt_set_runtime_revision_mismatch")
    if len(source_fingerprints) > 1:
        issues.append("receipt_set_source_fingerprint_mismatch")
    if _is_source_revision(current_head) and revisions and revisions != {current_head}:
        issues.append("receipt_set_runtime_revision_not_current_head")
    return list(dict.fromkeys(issues))


def main() -> int:
    current_head = _git_head()
    current_fingerprint = _source_fingerprint()
    max_conversation_turn_ms = _float_env("MEMORIAL_GOLD_MAX_CONVERSATION_TURN_MS", 4500.0)
    max_speech_transcribe_ms = _float_env("MEMORIAL_GOLD_MAX_SPEECH_TRANSCRIBE_MS", 2500.0)
    max_browser_first_answer_ms = _float_env("MEMORIAL_GOLD_MAX_BROWSER_FIRST_ANSWER_MS", 4500.0)
    local = _json(LOCAL_RECEIPT)
    local_issues = _check_receipt(
        local,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        public_required=False,
        direct_min_f1=0.90,
        conversation_min_f1=0.90,
    )

    public_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_VOICE_RECEIPT") or PUBLIC_RECEIPT)
    public = _json(public_receipt_path)
    public_issues = _check_receipt(
        public,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        public_required=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
        max_conversation_turn_ms=max_conversation_turn_ms,
        max_speech_transcribe_ms=max_speech_transcribe_ms,
    )
    browser_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_BROWSER_RECEIPT") or BROWSER_RECEIPT)
    browser = _json(browser_receipt_path)
    browser_issues = _check_browser_receipt(
        browser,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        max_first_answer_ms=max_browser_first_answer_ms,
    )

    meaningful_browser_issues: list[str] = []
    meaningful_browser_receipt: dict[str, Any] = {}
    meaningful_browser_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_MEANINGFUL_BROWSER_RECEIPT") or MEANINGFUL_BROWSER_RECEIPT)
    meaningful_browser_required = _meaningful_browser_receipt_required()
    if meaningful_browser_required:
        meaningful_browser_receipt = _json(meaningful_browser_receipt_path)
        meaningful_browser_issues = _check_browser_receipt(
            meaningful_browser_receipt,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
            max_first_answer_ms=_float_env(
                "MEMORIAL_GOLD_MAX_MEANINGFUL_BROWSER_FIRST_ANSWER_MS",
                8000.0,
            ),
            require_live_stt=False,
        )
    else:
        meaningful_browser_issues = [
            "meaningful_browser_receipt_skipped_for_diagnostic_only"
        ]
    room_receipt_path = Path(os.getenv("MEMORIAL_ROOM_AUDIO_RECEIPT") or ROOM_RECEIPT)
    room = _json(room_receipt_path)
    room_issues = _check_room_receipt(
        room,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    )
    spatial_receipt_path = Path(
        os.getenv("MEMORIAL_SPATIAL_TOUR_PUBLIC_ORIGIN_RECEIPT")
        or SPATIAL_RECEIPT
    )
    spatial = _json(spatial_receipt_path)
    spatial_issues = _check_spatial_receipt(
        spatial,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    )
    public_voice_bound_receipts = {
        "public_voice": public,
        "public_browser": browser,
        "room_audio": room,
    }
    if meaningful_browser_required:
        public_voice_bound_receipts["meaningful_browser"] = meaningful_browser_receipt
    public_voice_receipt_set_issues = _receipt_set_binding_issues(
        public_voice_bound_receipts,
        expected_slug="manfred",
        current_head=current_head,
    )
    flagship_bound_receipts = {
        **public_voice_bound_receipts,
        "spatial_tour": {
            "slug": spatial.get("slug"),
            "base_url": spatial.get("public_base_url"),
            "runtime_source_revision": spatial.get("runtime_revision"),
            "source_git_head": spatial.get("source_git_head"),
            "source_state_fingerprint": spatial.get("source_state_fingerprint"),
        },
    }
    receipt_set_issues = _receipt_set_binding_issues(
        flagship_bound_receipts,
        expected_slug="manfred",
        current_head=current_head,
    )
    memorial_surface_contract = _run_script_json(["scripts/verify_project_mode_runtime.py", "--mode", "memorial"])
    memorial_surface_contract_issues = _check_memorial_surface_contract(memorial_surface_contract)
    public_voice_gold_issues = list(
        dict.fromkeys(
            [
                *public_issues,
                *browser_issues,
                *meaningful_browser_issues,
                *memorial_surface_contract_issues,
                *room_issues,
                *public_voice_receipt_set_issues,
            ]
        )
    )
    flagship_experience_gold_issues = list(
        dict.fromkeys(
            [
                *public_voice_gold_issues,
                *spatial_issues,
                *receipt_set_issues,
            ]
        )
    )
    public_voice_blocker_summary = _blocker_summary(
        local_issues=[],
        public_issues=public_issues,
        browser_issues=browser_issues,
        meaningful_browser_issues=meaningful_browser_issues,
        memorial_surface_contract_issues=memorial_surface_contract_issues,
        room_issues=room_issues,
        receipt_set_issues=public_voice_receipt_set_issues,
        spatial_issues=[],
    )
    blocker_summary = _blocker_summary(
        local_issues=local_issues,
        public_issues=public_issues,
        browser_issues=browser_issues,
        meaningful_browser_issues=meaningful_browser_issues,
        memorial_surface_contract_issues=memorial_surface_contract_issues,
        room_issues=room_issues,
        receipt_set_issues=receipt_set_issues,
        spatial_issues=spatial_issues,
    )
    public_voice_next_action = _next_action_from_summary(
        public_voice_blocker_summary
    )
    next_action = _next_action_from_summary(blocker_summary)
    source_worktree = dict(source_worktree_metadata(ROOT, dirty_path_limit=SOURCE_DIRTY_FILE_LIMIT))
    source_dirty_summary = _source_dirty_summary(source_worktree)
    source_dirty_verifier = _source_dirty_verifier_payload(
        source_worktree=source_worktree,
        source_dirty_summary=source_dirty_summary,
    )
    if next_action == "refresh_memorial_public_auto_receipts_clean" and bool(source_worktree.get("source_worktree_dirty")):
        blocker_summary = _append_source_worktree_blocker(
            blocker_summary,
            source_worktree,
            source_dirty_verifier=source_dirty_verifier,
        )
        next_action = (
            "verify_source_dirty_groups_before_source_cleanup"
            if str(source_dirty_verifier.get("status") or "") != "pass"
            else "commit_or_stash_source_changes_before_clean_receipts"
        )
    if (
        public_voice_next_action == "refresh_memorial_public_auto_receipts_clean"
        and bool(source_worktree.get("source_worktree_dirty"))
    ):
        public_voice_blocker_summary = _append_source_worktree_blocker(
            public_voice_blocker_summary,
            source_worktree,
            source_dirty_verifier=source_dirty_verifier,
        )
        public_voice_next_action = (
            "verify_source_dirty_groups_before_source_cleanup"
            if str(source_dirty_verifier.get("status") or "") != "pass"
            else "commit_or_stash_source_changes_before_clean_receipts"
        )

    public_voice_gold_status = (
        "pass" if not public_voice_gold_issues else "blocked"
    )
    flagship_experience_gold_status = (
        "pass" if not flagship_experience_gold_issues else "blocked"
    )
    status = (
        "pass"
        if not local_issues and flagship_experience_gold_status == "pass"
        else "blocked"
    )
    next_command = _next_command_for_action(next_action)
    public_voice_next_command = _next_command_for_action(
        public_voice_next_action
    )
    source_cleanup = _source_cleanup_payload(
        source_worktree=source_worktree,
        source_dirty_summary=source_dirty_summary,
        source_dirty_verifier=source_dirty_verifier,
        next_action=next_action,
        next_command=next_command,
    )
    payload = {
        "status": status,
        "current_head": current_head,
        "claim_labels": {
            "ea_receipt_set": "EA receipt-set gold",
            "memorial_local": "Memorial local release candidate",
            "memorial_public_voice": "Memorial public-origin voice gold",
            "memorial_flagship": "Memorial flagship experience gold",
            "memorial_public": "Memorial flagship experience gold",
        },
        "public_voice_gold_status": public_voice_gold_status,
        "public_voice_gold_claim_allowed": (
            public_voice_gold_status == "pass"
            and meaningful_browser_required
        ),
        "public_voice_gold_issues": public_voice_gold_issues,
        "public_voice_receipt_set_binding_issues": (
            public_voice_receipt_set_issues
        ),
        "public_voice_blocker_summary": public_voice_blocker_summary,
        "public_voice_next_action": public_voice_next_action,
        "public_voice_next_command": public_voice_next_command,
        "flagship_experience_gold_status": flagship_experience_gold_status,
        "flagship_experience_gold_claim_allowed": (
            flagship_experience_gold_status == "pass"
            and meaningful_browser_required
        ),
        "flagship_experience_gold_issues": (
            flagship_experience_gold_issues
        ),
        "local_release_receipt": _display_path(LOCAL_RECEIPT),
        "local_release_issues": local_issues,
        "public_gold_receipt": _display_path(public_receipt_path),
        "public_gold_issues": public_issues,
        "public_browser_gold_receipt": _display_path(browser_receipt_path),
        "public_browser_gold_issues": browser_issues,
        "public_meaningful_browser_gold_receipt": _display_path(meaningful_browser_receipt_path),
        "public_meaningful_browser_gold_required": meaningful_browser_required,
        "public_meaningful_browser_diagnostic_override": not meaningful_browser_required,
        "public_meaningful_browser_gold_issues": meaningful_browser_issues,
        "memorial_surface_contract": "scripts/verify_project_mode_runtime.py --mode memorial",
        "memorial_surface_contract_issues": memorial_surface_contract_issues,
        "room_audio_receipt": _display_path(room_receipt_path),
        "room_audio_issues": room_issues,
        "public_spatial_tour_receipt": _display_path(spatial_receipt_path),
        "public_spatial_tour_issues": spatial_issues,
        "receipt_set_binding_issues": receipt_set_issues,
        "receipt_set_runtime_source_revision": (
            str(public.get("runtime_source_revision") or "").strip()
            if not receipt_set_issues
            else ""
        ),
        "blocker_summary": blocker_summary,
        "next_action": next_action,
        "next_command": next_command,
        "source_worktree_dirty": bool(source_worktree.get("source_worktree_dirty")),
        "source_dirty_count": int(source_worktree.get("source_dirty_count") or 0),
        "source_dirty_files": list(source_worktree.get("source_dirty_files") or []),
        "source_dirty_omitted_count": int(source_worktree.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(source_worktree.get("source_dirty_status_sha256") or ""),
        "source_dirty_summary": source_dirty_summary,
        "source_dirty_verifier": source_dirty_verifier,
        "source_cleanup": source_cleanup,
        "gold_thresholds": {
            "direct_tts_f1_min": 0.92,
            "conversation_turn_audio_f1_min": 0.90,
            "conversation_turn_total_ms_max": max_conversation_turn_ms,
            "speech_transcribe_ms_max": max_speech_transcribe_ms,
            "browser_first_answer_ms_max": max_browser_first_answer_ms,
        },
        "memorial_voice_gold_claim_allowed": (
            public_voice_gold_status == "pass"
            and meaningful_browser_required
        ),
        "memorial_voice_gold_claim_semantics": (
            "legacy_alias_of_public_voice_gold_claim_allowed"
        ),
        "labels": {
            "local_receipt": "Memorial voice release-candidate proof",
            "public_receipt": "Memorial public voice provenance proof",
            "browser_receipt": "Memorial public browser realtime proof",
            "surface_contract": "Memorial mounted public surface contract proof",
            "room_receipt": "Memorial public room/device playback proof",
            "spatial_tour_receipt": "Memorial public 3D-tour origin and exact-byte proof",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
