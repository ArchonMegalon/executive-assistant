from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.materialize_governed_spatial_render_checkpoint import (  # noqa: E402
    CANONICAL_AUTHORITY_BLOCKER_CONTRACT,
    CANONICAL_AUTHORITY_FOLLOW_UP,
    CANONICAL_AUTHORITY_NEXT_ACTION,
    CANONICAL_AUTHORITY_SOURCE,
    CANONICAL_SOURCE_VALIDATION_BLOCKED,
    DEFAULT_OUTPUT,
)
from scripts.materialize_governed_spatial_render_design_review import (  # noqa: E402
    CANONICAL_REVIEW_STATUS,
    verify_design_review_receipt_payload,
)


EXPECTED_CHUMMER_REVIEW_FILES = [
    "chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md"
]
EXPECTED_DESIGN_FOLLOW_UP = (
    "complete_10_amendments_and_propertyquarry_authority_then_independent_re_review:"
    "ea-governed-spatial-render-contract-v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_BLOCKER_REASONS = frozenset(
    {
        "canonical_design_review_invalid",
        "canonical_input_hash_drift",
        "canonical_input_missing",
        "decision_authority_marker_missing",
        "decision_canonical_binding_missing",
        "decision_evidence_binding_missing",
        "decision_hash_drift",
        "decision_heading_invalid",
        "decision_metadata_invalid",
        "decision_missing",
        "handoff_hash_drift",
        "handoff_missing",
        "petition_hash_drift",
        "petition_missing",
    }
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[dict[str, object]]:
    return (
        [dict(row) for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _redacted_issue(value: object) -> tuple[str, str]:
    raw = _clean(value)
    candidate = raw.split(":", 1)[0]
    reason = (
        candidate
        if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", candidate)
        else "unclassified"
    )
    return reason, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _nested_validation_fingerprints(value: object) -> dict[str, list[str]]:
    fingerprints: dict[str, list[str]] = {}
    for row in _rows(value):
        reason = _clean(row.get("reason"))
        fingerprint = _clean(row.get("fingerprint"))
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason)
            or not _SHA256_RE.fullmatch(fingerprint)
        ):
            continue
        fingerprints.setdefault(reason, []).append(fingerprint)
    return fingerprints


def _url_paths(value: object, *, path: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            paths.extend(_url_paths(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_url_paths(nested, path=f"{path}[{index}]"))
    elif isinstance(value, str) and "://" in value:
        paths.append(path or "value")
    return paths


def verify_checkpoint(path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    issues: list[str] = []
    issue_fingerprints: list[dict[str, str]] = []
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "fail",
            "issues": [f"checkpoint_unreadable:{type(exc).__name__}"],
            "path": str(path),
        }
    if not isinstance(receipt, dict):
        return {
            "status": "fail",
            "issues": ["checkpoint_object_required"],
            "path": str(path),
        }
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        issues.append("checkpoint_permissions_or_link_invalid")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if _clean(receipt.get("receipt_digest")) != _sha256_json(body):
        issues.append("checkpoint_receipt_digest_invalid")
    if (
        receipt.get("contract_name")
        != "ea.governed_spatial_render_section18_checkpoint.v1"
    ):
        issues.append("checkpoint_contract_invalid")
    if receipt.get("status") != "intermediate_blocked":
        issues.append("checkpoint_status_overclaim")
    authority_blocker = _dict(receipt.get("design_authority_blocker"))
    authority_source_blocked = bool(authority_blocker)
    expected_authority_status = (
        CANONICAL_SOURCE_VALIDATION_BLOCKED
        if authority_source_blocked
        else CANONICAL_REVIEW_STATUS
    )
    expected_design_follow_up = (
        CANONICAL_AUTHORITY_FOLLOW_UP
        if authority_source_blocked
        else EXPECTED_DESIGN_FOLLOW_UP
    )
    if receipt.get("design_authority_status") != expected_authority_status:
        issues.append("design_authority_status_overclaim")
    if receipt.get("required_design_follow_up") != expected_design_follow_up:
        issues.append("required_design_follow_up_invalid")
    if receipt.get("launch_recommendation") != "no":
        issues.append("launch_recommendation_must_be_no")
    for field in (
        "live_untouched",
        "propertyquarry_live_untouched",
        "chummer_live_untouched",
    ):
        if receipt.get(field) is not True:
            issues.append(f"{field}_must_be_true")

    files = _dict(receipt.get("files_changed_by_repo"))
    if files.get("propertyquarry") != []:
        issues.append("propertyquarry_change_claim_not_allowed")
    if files.get("chummer") != EXPECTED_CHUMMER_REVIEW_FILES:
        issues.append("chummer_change_claim_not_allowed")

    design_review = _dict(receipt.get("canonical_design_review"))
    if authority_source_blocked:
        blocker_body = {
            key: value
            for key, value in authority_blocker.items()
            if key != "receipt_digest"
        }
        if authority_blocker.get("receipt_digest") != _sha256_json(blocker_body):
            issues.append("canonical_authority_blocker_digest_invalid")
        if (
            authority_blocker.get("contract_name")
            != CANONICAL_AUTHORITY_BLOCKER_CONTRACT
        ):
            issues.append("canonical_authority_blocker_contract_invalid")
        if authority_blocker.get("status") != "blocked":
            issues.append("canonical_authority_blocker_status_invalid")
        if authority_blocker.get("reason") not in _CANONICAL_BLOCKER_REASONS:
            issues.append("canonical_authority_blocker_reason_invalid")
        if authority_blocker.get("authority_source") != CANONICAL_AUTHORITY_SOURCE:
            issues.append("canonical_authority_blocker_source_invalid")
        if not _SHA256_RE.fullmatch(
            _clean(authority_blocker.get("failure_fingerprint"))
        ):
            issues.append("canonical_authority_blocker_fingerprint_invalid")
        if authority_blocker.get("next_action") != CANONICAL_AUTHORITY_NEXT_ACTION:
            issues.append("canonical_authority_blocker_next_action_invalid")
        for field in (
            "implementation_authorized",
            "provider_execution_authorized",
            "quota_authorized",
            "publication_authorized",
            "serving_authorized",
            "launch_ready_allowed",
            "raw_failure_detail_exposed",
        ):
            if authority_blocker.get(field) is not False:
                issues.append(f"canonical_authority_blocker_overclaim:{field}")

        review_body = {
            key: value
            for key, value in design_review.items()
            if key != "receipt_digest"
        }
        if design_review.get("receipt_digest") != _sha256_json(review_body):
            issues.append("blocked_design_review_digest_invalid")
        if (
            design_review.get("contract_name")
            != "ea.governed_spatial_render_design_review_unavailable.v1"
        ):
            issues.append("blocked_design_review_contract_invalid")
        if design_review.get("status") != "source_validation_blocked":
            issues.append("blocked_design_review_status_invalid")
        if design_review.get("authority_source") != CANONICAL_AUTHORITY_SOURCE:
            issues.append("blocked_design_review_source_invalid")
        if design_review.get("authority_blocker_digest") != authority_blocker.get(
            "receipt_digest"
        ):
            issues.append("blocked_design_review_binding_invalid")
        decision = _dict(design_review.get("decision"))
        if (
            decision.get("disposition") != "unverified"
            or decision.get("implementation_state") != "blocked"
        ):
            issues.append("blocked_design_review_decision_invalid")
        if decision.get("independent_review") is not False:
            issues.append("blocked_design_review_independence_overclaim")
        for field in (
            "implementation_authorized",
            "provider_execution_authorized",
            "quota_authorized",
            "product_bridge_registration_authorized",
            "live_change_authorized",
        ):
            if design_review.get(field) is not False:
                issues.append(f"blocked_design_review_overclaim:{field}")
        if design_review.get("independent_re_review_required") is not True:
            issues.append("blocked_design_review_rereview_required")
        if design_review.get("launch_recommendation") != "no":
            issues.append("blocked_design_review_launch_overclaim")
    else:
        review_verification = verify_design_review_receipt_payload(design_review)
        if review_verification.get("status") != "pass":
            nested_fingerprints = _nested_validation_fingerprints(
                review_verification.get("validation_failure_fingerprints")
            )
            for issue in review_verification.get("issues", []):
                reason, fallback_fingerprint = _redacted_issue(issue)
                matching_fingerprints = nested_fingerprints.get(reason, [])
                fingerprint = (
                    matching_fingerprints.pop(0)
                    if matching_fingerprints
                    else fallback_fingerprint
                )
                issues.append(f"canonical_design_review_invalid:{reason}")
                issue_fingerprints.append(
                    {
                        "scope": "canonical_design_review",
                        "reason": reason,
                        "fingerprint": fingerprint,
                    }
                )

    provider_execution = _dict(receipt.get("provider_execution"))
    if provider_execution.get("jobs_attempted") != 0:
        issues.append("provider_jobs_attempted_must_be_zero")
    if provider_execution.get("credits_consumed") != 0:
        issues.append("provider_credits_consumed_must_be_zero")
    if provider_execution.get("quota_authorized") is not False:
        issues.append("quota_authorized_must_be_false")

    capability_index = _dict(receipt.get("capability_index"))
    if capability_index.get("design_authority_status") != expected_authority_status:
        issues.append("capability_design_status_overclaim")
    expected_disposition = "unverified" if authority_source_blocked else "revise"
    if capability_index.get("design_review_disposition") != expected_disposition:
        issues.append("capability_design_disposition_overclaim")
    for provider in _rows(capability_index.get("providers")):
        if provider.get("quota_posture") == "build_allowed":
            issues.append(
                f"provider_build_posture_overclaim:{_clean(provider.get('provider_key'))}"
            )

    composition = _dict(receipt.get("example_compose_receipt"))
    composition_quota = _dict(composition.get("quota"))
    if composition.get("status") != "accepted":
        issues.append("fixture_composition_not_accepted")
    if composition_quota.get("consume_quota") is not False:
        issues.append("fixture_composition_quota_overclaim")
    if (
        composition_quota.get("provider_attempts") != 0
        or composition_quota.get("credits_consumed") != 0
    ):
        issues.append("fixture_composition_not_zero_burn")

    build = _dict(receipt.get("example_build_receipt"))
    if build.get("status") != "blocked":
        issues.append("fixture_build_must_be_blocked")
    blocked_reasons = set(
        build.get("blocked_reasons")
        if isinstance(build.get("blocked_reasons"), list)
        else []
    )
    for reason in (
        "explicit_quota_authorization_required",
        "governed_spatial_build_disabled",
        "trusted_immutable_artifact_verification_unavailable",
    ):
        if reason not in blocked_reasons:
            issues.append(f"fixture_build_missing_block:{reason}")
    build_provider = _dict(build.get("provider_private"))
    build_quota = _dict(build.get("quota"))
    build_audit = _dict(build.get("audit"))
    projection = _dict(build.get("product_projection"))
    if (
        build_provider.get("provider_jobs_attempted") != 0
        or build_provider.get("provider_credits_consumed") != 0
    ):
        issues.append("fixture_build_provider_execution_overclaim")
    if build_provider.get("trusted_artifact_verified") is not False:
        issues.append("fixture_build_trusted_artifact_overclaim")
    if build_provider.get("existing_artifact_reused") is not False:
        issues.append("fixture_build_artifact_reuse_overclaim")
    if (
        build_quota.get("provider_attempts") != 0
        or build_quota.get("provider_credits_consumed") != 0
    ):
        issues.append("fixture_build_quota_burn_overclaim")
    if build_audit.get("provider_job_enqueued") is not False:
        issues.append("fixture_build_enqueue_overclaim")
    if projection.get("state") != "blocked" or projection.get("artifact_ref") not in {
        "",
        None,
    }:
        issues.append("fixture_product_projection_overclaim")

    integrity = _dict(receipt.get("receipt_store_integrity"))
    if integrity.get("status") != "pass" or integrity.get("persistent") is not True:
        issues.append("receipt_store_integrity_missing")
    quality = _dict(receipt.get("quality_metrics"))
    if quality.get("product_walkthrough_artifact_accepted") is not False:
        issues.append("product_walkthrough_acceptance_overclaim")
    if any(
        quality.get(field) is not None
        for field in ("room_coverage_percent", "cut_count", "delivery_fps")
    ):
        issues.append("product_quality_metric_overclaim")
    browser = _dict(receipt.get("browser_receipts"))
    if (
        browser.get("post_ea_desktop_receipt") != "not_run"
        or browser.get("post_ea_mobile_receipt") != "not_run"
    ):
        issues.append("post_ea_browser_receipt_overclaim")
    if (
        receipt.get("style_videos") != []
        or receipt.get("telegram_delivery_receipts") != []
    ):
        issues.append("style_video_or_telegram_overclaim")
    for eta_delivery in _rows(receipt.get("eta_telegram_delivery_receipts")):
        if (
            eta_delivery.get("sent") is not True
            or eta_delivery.get("style_video_delivery") is not False
        ):
            issues.append("eta_telegram_delivery_receipt_invalid")
        if eta_delivery.get("contains_provider_credentials") is not False:
            issues.append("eta_telegram_delivery_contains_credentials")
    canary = _dict(receipt.get("canary"))
    if (
        canary.get("status") != "not_started"
        or canary.get("start")
        or canary.get("end")
    ):
        issues.append("canary_overclaim")
    tests = _dict(receipt.get("tests"))
    if tests.get("focused_failed") != 0:
        issues.append("focused_test_failures_present")
    if (
        tests.get("cross_repo_tests_run") is not False
        or tests.get("browser_tests_run_after_ea_integration") is not False
    ):
        issues.append("test_scope_overclaim")
    url_paths = _url_paths(receipt)
    if url_paths:
        issues.extend(f"raw_url_exposed:{path_value}" for path_value in url_paths)
    for field in (
        "raw_provider_urls_exposed",
        "raw_provider_account_ids_exposed",
        "raw_provider_task_ids_exposed",
    ):
        if composition.get(field) is not False or build.get(field) is not False:
            issues.append(f"provider_sensitive_projection_flag_invalid:{field}")
    return {
        "contract_name": "ea.governed_spatial_render_checkpoint_verification.v1",
        "status": "pass" if not issues else "fail",
        "issues": list(dict.fromkeys(issues)),
        "issue_fingerprints": issue_fingerprints,
        "path": str(path),
        "receipt_digest": receipt.get("receipt_digest", ""),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the fail-closed governed spatial-render checkpoint."
    )
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = verify_checkpoint(args.path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
