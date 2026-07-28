#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.workllm_sidecar import redact_workllm_text  # noqa: E402

DEFAULT_OUTPUT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_ACCOUNT_VERIFICATION.generated.json"
)
EXPECTED_SITE = "girschele-workspace.workllm.io"
EVIDENCE_SCHEMA = "executive_assistant.workllm_browser_account_review.v1"
RECEIPT_SCHEMA = "executive_assistant.workllm_account_verification.v1"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

_REQUIRED_CAPABILITIES = (
    "multi_llm_chat",
    "deep_research",
    "document_chat",
    "multimedia_chat",
    "organization_memory",
    "agents",
)
_REQUIRED_CONTROLS = (
    "rbac_visible",
    "audit_log_visible",
    "usage_reporting_visible",
    "export_control_visible",
    "deletion_control_visible",
    "retention_control_visible",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("workllm_account_secure_write_failed")
        offset += written


def _secure_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() and (
        path.is_symlink()
        or not path.is_file()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise SystemExit("workllm_account_output_path_unsafe")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        encoded = (
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)


def _load_evidence(path: Path) -> dict[str, object]:
    if (
        not path.is_file()
        or path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise SystemExit(f"workllm_account_evidence_missing:{path}")
    if path.stat().st_size <= 0 or path.stat().st_size > 2 * 1024 * 1024:
        raise SystemExit("workllm_account_evidence_size_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SystemExit("workllm_account_evidence_invalid") from None
    if not isinstance(payload, dict):
        raise SystemExit("workllm_account_evidence_invalid")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    redacted, redactions = redact_workllm_text(serialized)
    if redacted != serialized or redactions:
        raise SystemExit("workllm_account_evidence_contains_sensitive_data")
    return dict(payload)


def _validated_utc_timestamp(value: object) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("Z"):
        raise SystemExit("workllm_account_observed_at_invalid")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("workllm_account_observed_at_invalid") from None
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SystemExit("workllm_account_observed_at_invalid")
    return raw


def _validated_surface_url(value: object, *, expected_site: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != expected_site.lower()
        or parsed.username
        or parsed.password
    ):
        raise SystemExit("workllm_account_final_surface_invalid")
    return raw


def _validated_screenshot_artifacts(
    value: object,
    *,
    evidence_path: Path,
) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise SystemExit("workllm_account_screenshot_evidence_missing")
    artifacts: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise SystemExit(
                "workllm_account_screenshot_evidence_invalid"
            )
        raw_path = str(item.get("path") or "").strip()
        expected_sha256 = str(item.get("sha256") or "").strip().lower()
        if not raw_path or _SHA256_RE.fullmatch(expected_sha256) is None:
            raise SystemExit(
                "workllm_account_screenshot_evidence_invalid"
            )
        artifact_candidate = Path(raw_path)
        if not artifact_candidate.is_absolute():
            artifact_candidate = evidence_path.parent / artifact_candidate
        if artifact_candidate.is_symlink():
            raise SystemExit(
                "workllm_account_screenshot_evidence_invalid"
            )
        artifact_path = artifact_candidate.resolve(strict=False)
        if (
            artifact_path in seen_paths
            or expected_sha256 in seen_hashes
            or not artifact_path.is_file()
            or artifact_path.stat().st_size <= 0
            or artifact_path.stat().st_size > 20 * 1024 * 1024
            or stat.S_IMODE(artifact_path.stat().st_mode) != 0o600
            or _sha256_file(artifact_path) != expected_sha256
        ):
            raise SystemExit(
                "workllm_account_screenshot_evidence_invalid"
            )
        seen_paths.add(artifact_path)
        seen_hashes.add(expected_sha256)
        artifacts.append(
            {
                "path": str(artifact_path),
                "sha256": expected_sha256,
            }
        )
    return artifacts


def _boolean_map(
    payload: object,
    *,
    required_keys: tuple[str, ...],
    code: str,
) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise SystemExit(code)
    result: dict[str, bool] = {}
    for key in required_keys:
        value = payload.get(key)
        if not isinstance(value, bool):
            raise SystemExit(f"{code}:{key}")
        result[key] = value
    return result


def build_account_receipt(
    *,
    evidence_path: Path,
    output_path: Path,
    expected_site: str = EXPECTED_SITE,
) -> dict[str, object]:
    evidence = _load_evidence(evidence_path)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise SystemExit("workllm_account_evidence_schema_mismatch")
    if str(evidence.get("site") or "").strip().lower() != expected_site.lower():
        raise SystemExit("workllm_account_site_mismatch")
    if evidence.get("work_type") != "account_review":
        raise SystemExit("workllm_account_work_type_mismatch")
    if evidence.get("authenticated") is not True:
        raise SystemExit("workllm_account_authentication_unverified")
    if evidence.get("account_match") is not True:
        raise SystemExit("workllm_account_context_mismatch")
    if evidence.get("irreversible_actions_attempted") != []:
        raise SystemExit("workllm_account_irreversible_action_observed")
    if evidence.get("data_uploaded") is not False:
        raise SystemExit("workllm_account_review_uploaded_data")
    observed_at = _validated_utc_timestamp(evidence.get("observed_at"))
    final_surface_url = _validated_surface_url(
        evidence.get("final_surface_url"),
        expected_site=expected_site,
    )
    screenshot_artifacts = _validated_screenshot_artifacts(
        evidence.get("screenshot_artifacts"),
        evidence_path=evidence_path,
    )
    account_ref_sha256 = str(
        evidence.get("account_ref_sha256") or ""
    ).strip().lower()
    if _SHA256_RE.fullmatch(account_ref_sha256) is None:
        raise SystemExit("workllm_account_ref_invalid")

    plan = evidence.get("plan")
    if not isinstance(plan, dict):
        raise SystemExit("workllm_account_plan_missing")
    commercial_tier = str(plan.get("commercial_tier") or "").strip()
    if "tier 4" not in commercial_tier.lower():
        raise SystemExit("workllm_account_tier_mismatch")
    monthly_ai_credits = plan.get("monthly_ai_credits")
    if (
        not isinstance(monthly_ai_credits, int)
        or isinstance(monthly_ai_credits, bool)
        or monthly_ai_credits <= 0
    ):
        raise SystemExit("workllm_account_credit_allocation_invalid")
    if not isinstance(plan.get("unlimited_users"), bool):
        raise SystemExit("workllm_account_user_allocation_invalid")

    capabilities = _boolean_map(
        evidence.get("capabilities"),
        required_keys=_REQUIRED_CAPABILITIES,
        code="workllm_account_capability_observation_invalid",
    )
    controls = _boolean_map(
        evidence.get("controls"),
        required_keys=_REQUIRED_CONTROLS,
        code="workllm_account_control_observation_invalid",
    )
    agents = evidence.get("agent_surfaces")
    if not isinstance(agents, dict):
        raise SystemExit("workllm_account_agent_observation_invalid")
    agent_surfaces = {
        "knowledge_agents_visible": agents.get("knowledge_agents_visible")
        is True,
        "task_agents_visible": agents.get("task_agents_visible") is True,
        "workflow_agents_visible": agents.get("workflow_agents_visible")
        is True,
    }
    api = evidence.get("api_observation")
    if not isinstance(api, dict):
        raise SystemExit("workllm_account_api_observation_invalid")
    api_observation = {
        "machine_api_observed": api.get("machine_api_observed") is True,
        "service_auth_observed": api.get("service_auth_observed") is True,
        "usage_endpoint_observed": api.get("usage_endpoint_observed") is True,
        "webhook_signing_observed": api.get("webhook_signing_observed") is True,
        "idempotency_observed": api.get("idempotency_observed") is True,
        "model_identity_observed": api.get("model_identity_observed") is True,
    }
    manual_requirements = {
        "authenticated": True,
        "account_match": True,
        "tier_4_observed": True,
        "positive_credit_allocation": True,
        "multi_llm_chat": capabilities["multi_llm_chat"],
        "deep_research": capabilities["deep_research"],
        "no_upload": True,
        "no_irreversible_actions": True,
    }
    manual_verified = all(manual_requirements.values())
    provider_admin_controls_observed = all(controls.values())
    blockers: list[str] = []
    if not manual_verified:
        blockers.append(
            "The authenticated account does not expose every control required "
            "for a public-only governed manual workbench."
        )
    if not provider_admin_controls_observed:
        blockers.append(
            "One or more provider RBAC, audit, usage, export, deletion, or "
            "retention controls were not observed. Internal-nonsecret data, "
            "organization memory, and retained document uploads remain "
            "disabled."
        )
    else:
        blockers.append(
            "Provider control surfaces were observed, but their effective "
            "retention, deletion, and export policy was not validated. "
            "Internal-nonsecret data remains disabled."
        )
    api_proof_complete = all(api_observation.values())
    if not api_proof_complete:
        blockers.append(
            "A complete machine API, service authentication, usage, model, "
            "idempotency, and signed-webhook contract was not observed."
        )
    receipt = {
        "contract_name": RECEIPT_SCHEMA,
        "provider": "workllm",
        "site": expected_site,
        "verified_at": observed_at,
        "verdict": (
            "VERIFIED_MANUAL_WORKBENCH"
            if manual_verified
            else "ACCOUNT_OBSERVED_MANUAL_BLOCKED"
        ),
        "authenticated": True,
        "account_match": True,
        "account_ref_sha256": account_ref_sha256,
        "commercial_plan": {
            "tier": commercial_tier,
            "monthly_ai_credits": monthly_ai_credits,
            "unlimited_users": bool(plan["unlimited_users"]),
        },
        "capabilities": capabilities,
        "controls": controls,
        "agent_surfaces": agent_surfaces,
        "api_observation": api_observation,
        "manual_requirements": manual_requirements,
        "manual_workbench_verified": manual_verified,
        "manual_data_classes": ["public"],
        "provider_admin_controls_observed": (
            provider_admin_controls_observed
        ),
        "internal_nonsecret_eligible": False,
        "api_lane_eligible": False,
        "organization_memory_eligible": False,
        "data_uploaded": False,
        "irreversible_actions_attempted": [],
        "evidence": {
            "source_path": str(evidence_path),
            "source_sha256": _sha256_file(evidence_path),
            "final_surface_url": final_surface_url,
            "screenshot_artifacts": screenshot_artifacts,
            "screenshot_sha256": [
                item["sha256"] for item in screenshot_artifacts
            ],
        },
        "blocking_reasons": blockers,
        "authority": {
            "canonical_write_allowed": False,
            "repo_write_allowed": False,
            "external_send_allowed": False,
            "publish_allowed": False,
            "approval_allowed": False,
        },
    }
    _secure_write_json(output_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a redacted governed-browser WorkLLM account review and "
            "materialize the account-capability receipt."
        )
    )
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-site", default=EXPECTED_SITE)
    args = parser.parse_args()
    receipt = build_account_receipt(
        evidence_path=Path(args.evidence),
        output_path=Path(args.output),
        expected_site=args.expected_site,
    )
    print(
        json.dumps(
            {
                "verdict": receipt["verdict"],
                "manual_workbench_verified": receipt[
                    "manual_workbench_verified"
                ],
                "api_lane_eligible": receipt["api_lane_eligible"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["manual_workbench_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
