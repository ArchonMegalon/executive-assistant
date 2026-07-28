#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.provider_registry import ProviderRegistryService  # noqa: E402
from app.services.workllm_sidecar import (  # noqa: E402
    WorkLLMPolicyError,
    WorkLLMTaskPacket,
)

DEFAULT_OUTPUT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_GOAL_AUDIT.generated.json"
)
LOCAL_CONTRACT_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_SIDECAR_CONTRACT.generated.json"
)
PUBLIC_REACHABILITY_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_PUBLIC_REACHABILITY.generated.json"
)
ACCOUNT_VERIFICATION_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_ACCOUNT_VERIFICATION.generated.json"
)
MANUAL_CANARY_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_MANUAL_CANARY.generated.json"
)
API_VERIFICATION_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_API_VERIFICATION.generated.json"
)
BROWSER_HANDOFF_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_BROWSER_HANDOFF.generated.json"
)
PUBLIC_DOCS_RECEIPT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_PUBLIC_DOCS.generated.json"
)

_ENV_KEYS = (
    "WORKLLM_BASE_URL",
    "WORKLLM_EMAIL",
    "WORKLLM_PASSWORD",
    "EA_WORKLLM_ACCOUNT_VERIFIED",
    "WORKLLM_PROVIDER_VERIFIED",
    "EA_WORKLLM_MANUAL_LANE_ENABLED",
    "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED",
    "WORKLLM_RUNTIME_ENABLED",
    "EA_WORKLLM_API_LANE_ENABLED",
    "EA_WORKLLM_KILL_SWITCH",
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_EXPECTED_SITE = "girschele-workspace.workllm.io"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _env_facts(path: Path) -> dict[str, object]:
    values = {key: "" for key in _ENV_KEYS}
    if not path.is_file():
        return {
            "file_present": False,
            "mode_600": False,
            "presence": {key: False for key in _ENV_KEYS},
            "flags": {},
        }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in values:
            values[normalized_key] = value.strip().strip("\"'")
    flags = {}
    for key in (
        "EA_WORKLLM_ACCOUNT_VERIFIED",
        "WORKLLM_PROVIDER_VERIFIED",
        "EA_WORKLLM_MANUAL_LANE_ENABLED",
        "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED",
        "WORKLLM_RUNTIME_ENABLED",
        "EA_WORKLLM_API_LANE_ENABLED",
        "EA_WORKLLM_KILL_SWITCH",
    ):
        raw = values[key] or ("1" if key == "EA_WORKLLM_KILL_SWITCH" else "0")
        flags[key] = raw == "1"
    return {
        "file_present": True,
        "mode_600": stat.S_IMODE(path.stat().st_mode) == 0o600,
        "presence": {key: bool(value) for key, value in values.items()},
        "flags": flags,
    }


def _evidence_ref(path: Path) -> dict[str, str]:
    try:
        display_path = str(path.relative_to(ROOT))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "sha256": _sha256_file(path) if path.is_file() else "",
    }


def _resolve_evidence_path(value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return Path(os.path.abspath(path))


def _file_matches_sha256(path: Path | None, expected: object) -> bool:
    digest = str(expected or "").strip().lower()
    return bool(
        path is not None
        and path.is_file()
        and not path.is_symlink()
        and stat.S_IMODE(path.stat().st_mode) == 0o600
        and _SHA256_RE.fullmatch(digest)
        and _sha256_file(path) == digest
    )


def _normalized_artifact_evidence(
    value: object,
    *,
    base: Path,
) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or not value:
        return None
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        raw_path = str(item.get("path") or "").strip()
        digest = str(item.get("sha256") or "").strip().lower()
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = base / path
        normalized.append(
            {
                "path": str(Path(os.path.abspath(path))),
                "sha256": digest,
            }
        )
    return normalized


def _artifact_evidence_valid(value: object) -> bool:
    normalized = _normalized_artifact_evidence(value, base=ROOT)
    if normalized is None:
        return False
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    for item in normalized:
        path = _resolve_evidence_path(item.get("path"))
        digest = str(item.get("sha256") or "").strip().lower()
        if (
            path is None
            or path in seen_paths
            or digest in seen_hashes
            or not _file_matches_sha256(path, digest)
            or path.stat().st_size <= 0
            or path.stat().st_size > 20 * 1024 * 1024
        ):
            return False
        seen_paths.add(path)
        seen_hashes.add(digest)
    return True


def _account_receipt_provenance_valid(
    receipt: Mapping[str, object] | None,
) -> bool:
    if not receipt:
        return False
    evidence = receipt.get("evidence")
    authority = receipt.get("authority")
    if not isinstance(evidence, Mapping) or not isinstance(
        authority,
        Mapping,
    ):
        return False
    source_path = _resolve_evidence_path(evidence.get("source_path"))
    if not _file_matches_sha256(source_path, evidence.get("source_sha256")):
        return False
    source = _load_json(source_path) if source_path is not None else None
    if not source:
        return False
    final_url = urlparse(str(evidence.get("final_surface_url") or ""))
    screenshot_artifacts = _normalized_artifact_evidence(
        evidence.get("screenshot_artifacts"),
        base=ROOT,
    )
    source_screenshot_artifacts = _normalized_artifact_evidence(
        source.get("screenshot_artifacts"),
        base=source_path.parent,
    )
    screenshots = evidence.get("screenshot_sha256")
    screenshot_hashes = (
        [item["sha256"] for item in screenshot_artifacts]
        if screenshot_artifacts is not None
        else []
    )
    if (
        final_url.scheme != "https"
        or (final_url.hostname or "").lower() != _EXPECTED_SITE
        or not _artifact_evidence_valid(screenshot_artifacts)
        or screenshots != screenshot_hashes
    ):
        return False
    if (
        source.get("schema")
        != "executive_assistant.workllm_browser_account_review.v1"
        or source.get("authenticated") is not True
        or source.get("account_match") is not True
        or source.get("data_uploaded") is not False
        or source.get("irreversible_actions_attempted") != []
        or source.get("account_ref_sha256")
        != receipt.get("account_ref_sha256")
        or source.get("final_surface_url")
        != evidence.get("final_surface_url")
        or source_screenshot_artifacts != screenshot_artifacts
    ):
        return False
    return bool(
        authority.get("canonical_write_allowed") is False
        and authority.get("repo_write_allowed") is False
        and authority.get("external_send_allowed") is False
        and authority.get("publish_allowed") is False
        and authority.get("approval_allowed") is False
    )


def _manual_canary_provenance_valid(
    receipt: Mapping[str, object] | None,
    *,
    account_receipt: Mapping[str, object] | None,
    account_receipt_path: Path = ACCOUNT_VERIFICATION_RECEIPT,
) -> bool:
    if not receipt or not account_receipt:
        return False
    run_count = int(receipt.get("run_count") or 0)
    exact_count_fields = (
        "unique_task_count",
        "receipt_contract_count",
        "source_bound_count",
        "safety_passed_count",
        "reviewed_count",
        "credits_observed_count",
        "provider_observed_count",
        "model_observed_count",
        "accepted_candidate_count",
        "authority_safe_count",
        "real_provider_run_count",
        "governed_lifecycle_count",
    )
    if (
        run_count < 20
        or any(int(receipt.get(key) or 0) != run_count for key in exact_count_fields)
        or float(receipt.get("schema_success_rate") or 0.0) < 0.95
        or receipt.get("failures") != []
        or receipt.get("promotion_eligible_candidate") is not True
        or receipt.get("canonical_promotion_authority") is not False
    ):
        return False
    governance = receipt.get("governance_evidence")
    if not isinstance(governance, Mapping):
        return False
    audit_path = _resolve_evidence_path(
        governance.get("audit_ledger_path")
    )
    credit_path = _resolve_evidence_path(
        governance.get("credit_ledger_path")
    )
    if (
        not _file_matches_sha256(
            audit_path,
            governance.get("audit_ledger_sha256"),
        )
        or not _file_matches_sha256(
            credit_path,
            governance.get("credit_ledger_sha256"),
        )
        or int(governance.get("governed_lifecycle_count") or 0)
        != run_count
        or int(governance.get("audit_event_count") or 0)
        < run_count * 4
        or _SHA256_RE.fullmatch(
            str(governance.get("audit_head_event_sha256") or "")
        )
        is None
    ):
        return False
    manifest_path = _resolve_evidence_path(receipt.get("manifest_path"))
    account_path = _resolve_evidence_path(
        receipt.get("account_verification_receipt_path")
    )
    if not _file_matches_sha256(
        manifest_path,
        receipt.get("manifest_sha256"),
    ) or not _file_matches_sha256(
        account_path,
        receipt.get("account_verification_receipt_sha256"),
    ):
        return False
    if account_path != account_receipt_path.resolve(strict=False):
        return False
    if (
        receipt.get("account_verification_receipt_sha256")
        != _sha256_file(account_receipt_path)
    ):
        return False
    run_evidence = receipt.get("run_evidence")
    if not isinstance(run_evidence, list) or len(run_evidence) != run_count:
        return False
    account_ref = str(account_receipt.get("account_ref_sha256") or "")
    seen_requests: set[str] = set()
    for item in run_evidence:
        if not isinstance(item, Mapping):
            return False
        run_path = _resolve_evidence_path(item.get("run_receipt_path"))
        task_packet_path = _resolve_evidence_path(
            item.get("task_packet_path")
        )
        result_path = _resolve_evidence_path(item.get("result_path"))
        surface_path = _resolve_evidence_path(
            item.get("provider_surface_receipt_path")
        )
        output_surface_path = _resolve_evidence_path(
            item.get("provider_output_surface_artifact_path")
        )
        if not _file_matches_sha256(
            run_path,
            item.get("run_receipt_sha256"),
        ) or not _file_matches_sha256(
            task_packet_path,
            item.get("task_packet_sha256"),
        ) or not _file_matches_sha256(
            result_path,
            item.get("result_sha256"),
        ) or not _file_matches_sha256(
            surface_path,
            item.get("provider_surface_receipt_sha256"),
        ) or not _file_matches_sha256(
            output_surface_path,
            item.get("provider_output_surface_sha256"),
        ):
            return False
        run = _load_json(run_path) if run_path is not None else None
        packet_payload = (
            _load_json(task_packet_path)
            if task_packet_path is not None
            else None
        )
        surface = _load_json(surface_path) if surface_path is not None else None
        if not run or not packet_payload or not surface:
            return False
        try:
            packet = WorkLLMTaskPacket.from_dict(packet_payload)
        except WorkLLMPolicyError:
            return False
        local_artifacts = run.get("local_artifacts")
        surface_hash = str(
            item.get("provider_surface_receipt_sha256") or ""
        )
        output_surface_hash = str(
            item.get("provider_output_surface_sha256") or ""
        )
        request_hash = str(run.get("request_sha256") or "")
        if (
            run.get("schema")
            != "executive_assistant.workllm_run_receipt.v1"
            or run.get("execution_mode") != "manual_browser"
            or run.get("provider_interaction_observed") is not True
            or run.get("evidence_kind") != "provider_observed"
            or run.get("provider_surface_receipt_sha256") != surface_hash
            or packet.task_id != run.get("task_id")
            or packet.request_sha256 != request_hash
            or not isinstance(local_artifacts, Mapping)
            or _resolve_evidence_path(local_artifacts.get("task_packet"))
            != task_packet_path
            or _resolve_evidence_path(local_artifacts.get("result"))
            != result_path
            or _resolve_evidence_path(local_artifacts.get("run_receipt"))
            != run_path
            or run.get("output_sha256") != item.get("result_sha256")
            or surface.get("schema")
            != "executive_assistant.workllm_browser_run_receipt.v1"
            or surface.get("site") != _EXPECTED_SITE
            or surface.get("account_ref_sha256") != account_ref
            or surface.get("request_sha256") != request_hash
            or surface.get("prepared_packet_only") is not True
            or surface.get("output_captured") is not True
            or surface.get("irreversible_actions_attempted") != []
            or surface.get("provider_output_surface_sha256")
            != output_surface_hash
            or run.get("model_provenance_status") != "observed"
            or not isinstance(run.get("observed_models"), list)
            or not run.get("observed_models")
            or run.get("candidate_accepted") is not True
            or _SHA256_RE.fullmatch(output_surface_hash) is None
            or _SHA256_RE.fullmatch(request_hash) is None
            or request_hash in seen_requests
        ):
            return False
        seen_requests.add(request_hash)
    return True


def _status(
    *,
    achieved: bool,
    evidence: list[dict[str, str]],
    detail: str,
    missing: bool = False,
) -> dict[str, object]:
    return {
        "status": (
            "achieved" if achieved else "missing" if missing else "incomplete"
        ),
        "detail": detail,
        "evidence": evidence,
    }


def build_goal_audit(
    *,
    env_path: Path,
    output_path: Path,
    account_verification_receipt: Path = ACCOUNT_VERIFICATION_RECEIPT,
    manual_canary_receipt: Path = MANUAL_CANARY_RECEIPT,
) -> dict[str, object]:
    env = _env_facts(env_path)
    flags = dict(env.get("flags") or {})
    local_contract = _load_json(LOCAL_CONTRACT_RECEIPT)
    public_reachability = _load_json(PUBLIC_REACHABILITY_RECEIPT)
    account_verification = _load_json(account_verification_receipt)
    manual_canary = _load_json(manual_canary_receipt)
    api_verification = _load_json(API_VERIFICATION_RECEIPT)
    docs_path = ROOT / "docs" / "WORKLLM_FLEET_SIDECAR.md"
    petition_path = (
        ROOT
        / "docs"
        / "design-petitions"
        / "WORKLLM_FLEET_SIDECAR_PETITION.md"
    )
    account_runbook_path = (
        ROOT
        / "docs"
        / "runbooks"
        / "WORKLLM_ACCOUNT_REVIEW_OODA.md"
    )
    canary_runbook_path = (
        ROOT
        / "docs"
        / "runbooks"
        / "WORKLLM_MANUAL_CANARY.md"
    )
    account_template_path = (
        ROOT / "config" / "workllm_account_review.example.json"
    )
    browser_run_template_path = (
        ROOT / "config" / "workllm_browser_run_receipt.example.json"
    )
    canary_manifest_template_path = (
        ROOT / "config" / "workllm_canary_manifest.example.json"
    )
    inventory_path = ROOT / "LTDs.md"
    inventory_text = inventory_path.read_text(encoding="utf-8")
    docs_text = docs_path.read_text(encoding="utf-8")

    registry_state = ProviderRegistryService().binding_state("workllm")
    registry_fail_closed = bool(
        registry_state is not None and registry_state.executable is False
    )
    credentials_protected = bool(
        env.get("file_present")
        and env.get("mode_600")
        and env["presence"].get("WORKLLM_BASE_URL")
        and env["presence"].get("WORKLLM_EMAIL")
        and env["presence"].get("WORKLLM_PASSWORD")
    )
    local_checks = dict((local_contract or {}).get("checks") or {})
    local_contract_ready = bool(
        local_contract
        and local_contract.get("verdict") == "CANDIDATE_ONLY"
        and local_checks.get("local_contract_ready") is True
        and local_checks.get("persistent_credit_audit_review") is True
        and local_checks.get("durable_rollback_override") is True
    )
    tenant_reachable = bool(
        public_reachability
        and public_reachability.get("verdict")
        == "TENANT_SURFACE_REACHABLE_AUTH_PENDING"
    )
    account_verified = bool(
        account_verification
        and account_verification.get("contract_name")
        == "executive_assistant.workllm_account_verification.v1"
        and account_verification.get("verdict")
        == "VERIFIED_MANUAL_WORKBENCH"
        and account_verification.get("account_match") is True
        and account_verification.get("authenticated") is True
        and account_verification.get("manual_data_classes") == ["public"]
        and account_verification.get("internal_nonsecret_eligible")
        is False
        and account_verification.get("irreversible_actions_attempted") == []
        and _account_receipt_provenance_valid(account_verification)
    )
    manual_canary_ready = bool(
        manual_canary
        and manual_canary.get("schema")
        == "executive_assistant.workllm_canary_evaluation.v1"
        and manual_canary.get("mode") == "manual_browser"
        and int(manual_canary.get("run_count") or 0) >= 20
        and manual_canary.get("promotion_eligible_candidate") is True
        and manual_canary.get("canonical_promotion_authority") is False
        and _manual_canary_provenance_valid(
            manual_canary,
            account_receipt=account_verification,
            account_receipt_path=account_verification_receipt,
        )
    )
    api_flags_enabled = bool(
        flags.get("WORKLLM_RUNTIME_ENABLED")
        or flags.get("EA_WORKLLM_API_LANE_ENABLED")
    )
    api_proven = bool(
        api_verification
        and api_verification.get("contract_name")
        == "executive_assistant.workllm_api_verification.v1"
        and api_verification.get("verdict") == "VERIFIED_API_CHALLENGER"
        and api_verification.get("api_contract_verified") is True
        and api_verification.get("model_provenance_verified") is True
        and api_verification.get("usage_telemetry_verified") is True
        and api_verification.get("idempotency_verified") is True
        and api_verification.get("retention_controls_verified") is True
        and api_verification.get("webhook_controls_verified") is True
    )
    api_boundary_safe = bool(not api_flags_enabled or api_proven)
    posture_honest = bool(
        "`WorkLLM`" in inventory_text
        and "`Tier 4`" in inventory_text
        and "candidate_only" in docs_text
        and registry_fail_closed
    )
    authority_boundary = bool(
        local_contract_ready
        and (local_contract or {}).get("authority", {}).get(
            "canonical_write_allowed"
        )
        is False
    )
    documentation_complete = bool(
        docs_path.is_file()
        and petition_path.is_file()
        and account_runbook_path.is_file()
        and canary_runbook_path.is_file()
        and account_template_path.is_file()
        and browser_run_template_path.is_file()
        and canary_manifest_template_path.is_file()
        and "## Rollback" in docs_text
        and "## Persistent governance" in docs_text
    )

    requirements = {
        "credential_and_tenant_safety": _status(
            achieved=credentials_protected and tenant_reachable,
            evidence=[
                _evidence_ref(PUBLIC_REACHABILITY_RECEIPT),
                {"path": ".env", "sha256": "redacted_presence_only"},
            ],
            detail=(
                "Protected credential slots and the public tenant sign-in "
                "surface are verified without exposing values."
            ),
        ),
        "authenticated_account_capabilities": _status(
            achieved=account_verified,
            missing=account_verification is None,
            evidence=[
                _evidence_ref(account_verification_receipt),
                _evidence_ref(BROWSER_HANDOFF_RECEIPT),
            ],
            detail=(
                "Authenticated tenant identity, allocation, RBAC, audit, "
                "usage, export, deletion, retention, models, agents, and "
                "organization-memory controls require a governed account "
                "review bound to protected browser-state evidence."
            ),
        ),
        "honest_inventory_and_registry": _status(
            achieved=posture_honest,
            evidence=[
                _evidence_ref(inventory_path),
                {
                    "path": "ea/app/services/provider_registry.py",
                    "sha256": _sha256_file(
                        ROOT / "ea" / "app" / "services" / "provider_registry.py"
                    ),
                },
            ],
            detail=(
                "Commercial Tier 4 and workspace Tier 4 are separated; the "
                "runtime registry remains non-executable."
            ),
        ),
        "local_sidecar_governance": _status(
            achieved=local_contract_ready,
            evidence=[_evidence_ref(LOCAL_CONTRACT_RECEIPT)],
            detail=(
                "Packet, classification, redaction, persistent credits, "
                "hash-chained audit, review, canary, and rollback controls "
                "must all pass."
            ),
        ),
        "authority_boundary": _status(
            achieved=authority_boundary,
            evidence=[_evidence_ref(LOCAL_CONTRACT_RECEIPT)],
            detail=(
                "Repository writes, routing, approvals, publication, and "
                "canonical memory remain outside WorkLLM."
            ),
        ),
        "manual_lane_canary": _status(
            achieved=manual_canary_ready,
            missing=manual_canary is None,
            evidence=[_evidence_ref(manual_canary_receipt)],
            detail=(
                "At least 20 real governed manual runs require receipts, "
                "credit observation, validation, human review, and bound "
                "provider-output surface hashes."
            ),
        ),
        "unattended_api_boundary": _status(
            achieved=api_boundary_safe,
            evidence=[
                _evidence_ref(API_VERIFICATION_RECEIPT),
                _evidence_ref(PUBLIC_DOCS_RECEIPT),
            ],
            detail=(
                "API/runtime flags must remain off unless the full machine "
                "contract and provenance evidence exists."
            ),
        ),
        "documentation_and_handoff": _status(
            achieved=documentation_complete,
            evidence=[
                _evidence_ref(docs_path),
                _evidence_ref(petition_path),
                _evidence_ref(account_runbook_path),
                _evidence_ref(canary_runbook_path),
                _evidence_ref(account_template_path),
                _evidence_ref(browser_run_template_path),
                _evidence_ref(canary_manifest_template_path),
            ],
            detail=(
                "Local operating contract, rollback, promotion gates, and "
                "design-ownership petition are present."
            ),
        ),
    }
    unmet = [
        key
        for key, requirement in requirements.items()
        if requirement["status"] != "achieved"
    ]
    goal_ready = not unmet
    receipt = {
        "contract_name": "executive_assistant.workllm_goal_audit.v1",
        "generated_at": _utc_now(),
        "provider": "workllm",
        "goal_ready": goal_ready,
        "verdict": "COMPLETE" if goal_ready else "INCOMPLETE",
        "requirements": requirements,
        "unmet_requirements": unmet,
        "promotion": {
            "manual_lane_promoted": manual_canary_ready and account_verified,
            "api_lane_promoted": api_flags_enabled and api_proven,
            "canonical_authority": False,
        },
        "runtime_flags": {
            key: bool(value)
            for key, value in flags.items()
        },
        "blocking_reasons": [
            requirements[key]["detail"] for key in unmet
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_path.chmod(0o600)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit every WorkLLM long-running goal requirement against "
            "current local and provider evidence."
        )
    )
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    receipt = build_goal_audit(
        env_path=Path(args.env),
        output_path=Path(args.output),
    )
    print(
        json.dumps(
            {
                "goal_ready": receipt["goal_ready"],
                "verdict": receipt["verdict"],
                "unmet_requirements": receipt["unmet_requirements"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["goal_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
