#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ARTIFACTS = (
    Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"),
    Path(".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"),
    Path(".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json"),
    Path(".codex-design/product/PROJECT_MODES.generated.json"),
    Path(".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"),
    Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"),
    Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
    Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"),
    Path(".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"),
    Path(".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"),
    Path(".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"),
    Path(".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"),
    Path(".codex-studio/published/mymedia_alexa_readiness.generated.json"),
    Path(".codex-studio/published/teable_env_recovery_readiness.generated.json"),
    Path(".codex-studio/published/telegram_video_delivery_operator.generated.json"),
    Path(".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"),
)
MATERIALIZER_COMMANDS = (
    ("scripts/materialize_ea_browser_workflow_proof.py",),
    ("scripts/materialize_memorial_spatial_tour_public_origin.py",),
    ("scripts/materialize_project_mode_manifests.py",),
    ("scripts/materialize_telegram_video_delivery_receipt.py",),
    ("scripts/materialize_memorial_phrase_bank.py",),
    ("scripts/materialize_teable_env_recovery_readiness.py",),
    ("scripts/materialize_mymedia_alexa_readiness.py",),
    ("scripts/materialize_whatsapp_web_action_processor_readiness.py",),
    ("scripts/materialize_proactive_ooda_operator_status.py",),
    ("scripts/materialize_proactive_ooda_gold_acceptance.py",),
    ("scripts/materialize_continuous_improvement_goal_posture.py",),
    ("scripts/materialize_ea_flagship_release_gate.py",),
    ("scripts/materialize_weekly_product_pulse.py",),
    ("scripts/materialize_whole_project_gold_map.py",),
    ("scripts/materialize_memorial_operator_status.py",),
)
VOLATILE_KEYS = {
    "generated_at",
    "as_of",
    "created_at",
    "observed_at",
    "current_head",
    "evidence_heads",
    "mtime_utc",
    "size_bytes",
    "sha256",
    "duration_seconds",
    "git_branch",
    "git_head",
    "source_path",
    "resolved_path",
    "git_repo_root",
    "command",
    "cwd",
    "output_excerpt",
    "python_bin",
    "review_due",
    "run_id",
    "source_tree_fingerprint",
    "state_age_seconds",
    "state_updated_at",
    "sidecar_last_qr_at",
}
HOST_RESOURCE_VOLATILE_KEYS = {
    "available_bytes",
    "available_gb",
    "blocking_reason",
    "triggered_thresholds",
    "usage_percent",
}
LIVE_HOST_CAPACITY_VOLATILE_KEYS = {
    "host_root_available_bytes",
    "host_root_available_gb",
    "host_root_usage_percent",
}
JUNIT_VOLATILE_ATTRIBUTES = {"hostname", "time", "timestamp"}
PYTEST_TERMINAL_DURATION_RE = re.compile(r"(?<=\bin )\d+(?:\.\d+)?s\b")
LIVE_RECEIPT_FOLLOWTHROUGH_REPAIR_ACTION = "repair_proactive_operator_runtime_posture"
LIVE_RECEIPT_EVENTUAL_FOLLOWTHROUGH_KEYS = {
    "followthrough_current_receipt_overlay_applied",
    "followthrough_current_receipt_overlay_components",
    "followthrough_digest_item_count",
    "followthrough_digest_notification_status",
    "followthrough_digest_status",
    "followthrough_goal_posture_queue_count",
    "followthrough_goal_posture_status",
    "followthrough_gold_acceptance_status",
    "followthrough_operator_status",
    "followthrough_run_receipt_path",
    "followthrough_source",
    "followthrough_status",
}
LIVE_RECEIPT_EVENTUAL_FOLLOWTHROUGH_ERRORS = {
    "followthrough_artifacts_missing",
}


def _normalize_junit_xml(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        root = ET.fromstring(value)
    except (ET.ParseError, ValueError):
        return value
    for element in root.iter():
        stable_attributes = {
            key: item
            for key, item in element.attrib.items()
            if key.rsplit("}", 1)[-1] not in JUNIT_VOLATILE_ATTRIBUTES
        }
        element.attrib.clear()
        element.attrib.update(sorted(stable_attributes.items()))
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def _normalize_junit_sha256(*, declared: Any, junit_xml: Any) -> Any:
    if not isinstance(junit_xml, str):
        return declared
    normalized_xml = _normalize_junit_xml(junit_xml)
    if not isinstance(normalized_xml, str):
        return declared
    raw_sha256 = hashlib.sha256(junit_xml.encode("utf-8")).hexdigest()
    return {
        "canonical_sha256": hashlib.sha256(normalized_xml.encode("utf-8")).hexdigest(),
        "declared_matches_raw": str(declared or "").strip() == raw_sha256,
    }


def _normalize_terminal_summary(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return PYTEST_TERMINAL_DURATION_RE.sub("<duration>", value)


def _normalize(value: Any, *, _path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _path and _path[-1] == "live_receipt":
                if key_str in LIVE_RECEIPT_EVENTUAL_FOLLOWTHROUGH_KEYS:
                    # These fields mirror downstream generated receipts from the
                    # live runtime container. Their authoritative host artifacts
                    # are compared separately, so container catch-up is telemetry,
                    # not release-artifact semantic drift.
                    continue
                if key_str == "errors" and isinstance(item, list):
                    normalized[key] = _normalize(
                        [
                            error
                            for error in item
                            if str(error).strip()
                            not in LIVE_RECEIPT_EVENTUAL_FOLLOWTHROUGH_ERRORS
                        ],
                        _path=(*_path, key_str),
                    )
                    continue
                if (
                    key_str == "delivery_next_action"
                    and str(item or "").strip() == LIVE_RECEIPT_FOLLOWTHROUGH_REPAIR_ACTION
                    and any(
                        str(error).strip()
                        in LIVE_RECEIPT_EVENTUAL_FOLLOWTHROUGH_ERRORS
                        for error in list(value.get("errors") or [])
                    )
                ):
                    normalized[key] = ""
                    continue
            if key_str == "junit_xml":
                normalized[key] = _normalize_junit_xml(item)
                continue
            if key_str == "junit_xml_sha256":
                normalized[key] = _normalize_junit_sha256(
                    declared=item,
                    junit_xml=value.get("junit_xml"),
                )
                continue
            if key_str == "terminal_summary":
                normalized[key] = _normalize_terminal_summary(item)
                continue
            if (
                key in VOLATILE_KEYS
                or key_str in VOLATILE_KEYS
                or key_str.endswith("_git_head")
                or key_str.endswith("_ms")
                or key_str.endswith("_ms_max")
                or key_str.endswith("_ms_min")
                or key_str.endswith("_ms_total")
                or key_str.endswith("_ms_std")
                or key_str.endswith("_updated_at")
                or key_str.endswith("_observed_at")
                or key_str.endswith("_age_seconds")
                or key_str in LIVE_HOST_CAPACITY_VOLATILE_KEYS
                or (
                    _path
                    and _path[-1] == "host_resource_guard"
                    and key_str in HOST_RESOURCE_VOLATILE_KEYS
                )
            ):
                continue
            normalized[key] = _normalize(item, _path=(*_path, key_str))
        return normalized
    if isinstance(value, list):
        return [_normalize(item, _path=_path) for item in value]
    return value


def _load_worktree(path: Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_text(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _run_materializers() -> None:
    for command in MATERIALIZER_COMMANDS:
        subprocess.run(
            [sys.executable, *command],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


def main() -> int:
    original_text_by_path: dict[Path, str] = {}
    original_payload_by_path: dict[Path, Any] = {}
    for path in GENERATED_ARTIFACTS:
        try:
            original_text_by_path[path] = _load_text(path)
            original_payload_by_path[path] = json.loads(original_text_by_path[path])
        except Exception as exc:
            print(f"{path}: unable to load generated artifact before materialization: {exc}", file=sys.stderr)
            return 1

    try:
        _run_materializers()
    except Exception as exc:
        print(f"materializers failed: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    semantically_clean: list[Path] = []
    for path in GENERATED_ARTIFACTS:
        try:
            baseline_payload = original_payload_by_path[path]
            worktree_payload = _load_worktree(path)
        except Exception as exc:
            failures.append(f"{path}: unable to load generated artifact: {exc}")
            continue
        if _normalize(baseline_payload) != _normalize(worktree_payload):
            failures.append(f"{path}: semantic drift after materialization")
        else:
            semantically_clean.append(path)

    for path in semantically_clean:
        (ROOT / path).write_text(original_text_by_path[path], encoding="utf-8")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("generated release artifacts are semantically clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
