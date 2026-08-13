#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.workllm_governance import (  # noqa: E402
    GovernedWorkLLMManualLane,
)
from app.services.workllm_sidecar import (  # noqa: E402
    WORKLLM_RUN_RECEIPT_SCHEMA,
    WORKLLM_TASK_PACKET_SCHEMA,
    WorkLLMConfig,
    WorkLLMPolicyError,
    WorkLLMSidecar,
    evaluate_workllm_canary,
)

DEFAULT_OUTPUT = (
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
REQUIRED_LOCAL_KEYS = (
    "WORKLLM_BASE_URL",
    "WORKLLM_EMAIL",
    "WORKLLM_PASSWORD",
    "WORKLLM_PROVIDER_VERIFIED",
    "WORKLLM_RUNTIME_ENABLED",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_env_presence(path: Path) -> tuple[dict[str, bool], bool, str]:
    presence = {key: False for key in REQUIRED_LOCAL_KEYS}
    if not path.is_file():
        return presence, False, ""
    mode = stat.S_IMODE(path.stat().st_mode)
    workspace_url = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key not in presence:
            continue
        normalized_value = value.strip().strip("\"'")
        presence[normalized_key] = bool(normalized_value)
        if normalized_key == "WORKLLM_BASE_URL":
            workspace_url = normalized_value
    return presence, mode == 0o600, workspace_url


def _source_manifest() -> list[dict[str, str]]:
    return [
        {
            "ref": "docs/WORKLLM_FLEET_SIDECAR.md",
            "sha256": hashlib.sha256(
                (ROOT / "docs" / "WORKLLM_FLEET_SIDECAR.md").read_bytes()
            ).hexdigest(),
        }
    ]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_contract_canary(workspace_url: str) -> dict[str, bool]:
    fail_closed = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url=workspace_url,
            kill_switch_engaged=True,
        )
    )
    packet = fail_closed.prepare_task_packet(
        lane="multi_model_compare",
        data_classification="internal_nonsecret",
        prepared_context=(
            "Compare approved evidence. Contact: operator@example.test; "
            "api_key=not-a-real-provider-key."
        ),
        source_manifest=_source_manifest(),
        prompt_template_id="fleet-research-critic",
        prompt_template_version="1",
        prompt_text="Return source-bound candidate findings.",
        output_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        max_credits=25,
        task_id="workllm-contract-canary",
        correlation_id="workllm-contract-canary",
        created_at="2026-07-27T00:00:00Z",
    )
    serialized_packet = json.dumps(packet.to_dict(), sort_keys=True)
    redaction_passed = all(
        value not in serialized_packet
        for value in (
            "operator@example.test",
            "not-a-real-provider-key",
        )
    )
    kill_switch_passed = False
    try:
        fail_closed.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=0,
        )
    except WorkLLMPolicyError as exc:
        kill_switch_passed = str(exc) == "workllm_kill_switch_engaged"

    public_only_manual = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url=workspace_url,
            account_verified=True,
            manual_lane_enabled=True,
            kill_switch_engaged=False,
        )
    )
    internal_nonsecret_fail_closed = False
    try:
        public_only_manual.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=0,
        )
    except WorkLLMPolicyError as exc:
        internal_nonsecret_fail_closed = (
            str(exc) == "workllm_internal_nonsecret_disabled"
        )

    bounded_manual = WorkLLMSidecar(
        WorkLLMConfig(
            workspace_url=workspace_url,
            account_verified=True,
            manual_lane_enabled=True,
            internal_nonsecret_enabled=True,
            kill_switch_engaged=False,
        )
    )
    authorization = bounded_manual.authorize_submission(
        packet,
        mode="manual_browser",
        monthly_credits_used=100,
    )
    receipt, redacted_output = bounded_manual.capture_result(
        packet,
        output_text=(
            "Candidate result for reviewer@example.test; "
            "access_token=not-a-real-result-token."
        ),
        mode="manual_browser",
        observed_models=("synthetic-model-label",),
        credits_consumed=1,
        provider_job_ref="synthetic-job-ref",
        provider_interaction_observed=True,
        provider_surface_receipt_sha256=hashlib.sha256(
            b"synthetic-provider-surface"
        ).hexdigest(),
        captured_at="2026-07-27T00:01:00Z",
    )
    serialized_receipt = json.dumps(receipt, sort_keys=True)
    receipt_redaction_passed = all(
        value not in serialized_receipt and value not in redacted_output
        for value in (
            "reviewer@example.test",
            "not-a-real-result-token",
            "synthetic-job-ref",
        )
    )
    no_authority_passed = bool(
        packet.to_dict()["authority"]["canonical_write_allowed"] is False
        and receipt["authority"]["canonical_write_allowed"] is False
        and authorization["canonical_authority"] is False
    )
    api_fail_closed = False
    try:
        bounded_manual.authorize_submission(
            packet,
            mode="api",
            monthly_credits_used=100,
        )
    except WorkLLMPolicyError as exc:
        api_fail_closed = str(exc) == "workllm_api_proof_incomplete"
    synthetic_receipts: list[dict[str, object]] = []
    for index in range(20):
        candidate = json.loads(json.dumps(receipt))
        candidate["task_id"] = f"synthetic-canary-{index:02d}"
        synthetic_receipts.append(
            bounded_manual.mark_reviewed(
                candidate,
                reviewer_ref="synthetic-contract-reviewer",
                decision="accepted_candidate",
                schema_valid=True,
                safety_valid=True,
                reviewed_at="2026-07-27T00:02:00Z",
            )
        )
    canary_evaluation = evaluate_workllm_canary(
        synthetic_receipts,
        mode="manual_browser",
    )
    with tempfile.TemporaryDirectory(prefix="workllm-contract-") as temp_dir:
        temp_root = Path(temp_dir)
        governance_sidecar = WorkLLMSidecar(
            WorkLLMConfig(
                workspace_url=workspace_url,
                account_verified=True,
                manual_lane_enabled=True,
                internal_nonsecret_enabled=True,
                kill_switch_engaged=False,
                receipt_root=temp_root / "runs",
                control_state_file=temp_root / "control" / "state.json",
            )
        )
        governance_packet = governance_sidecar.prepare_task_packet(
            lane="research_synthesis",
            data_classification="internal_nonsecret",
            prepared_context="Synthetic governance proof.",
            source_manifest=_source_manifest(),
            prompt_template_id="governance-proof",
            prompt_template_version="1",
            prompt_text="Return a candidate-only proof result.",
            output_schema={
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "string"}},
            },
            max_credits=10,
            task_id="workllm-governance-canary",
            correlation_id="workllm-governance-canary",
            created_at="2026-07-27T00:03:00Z",
        )
        lane = GovernedWorkLLMManualLane(
            governance_sidecar,
            governance_root=temp_root / "governance",
        )
        lane.stage_packet(
            governance_packet,
            actor_ref="synthetic-governance-actor",
            occurred_at="2026-07-27T00:03:00Z",
        )
        lane.authorize(
            governance_packet,
            actor_ref="synthetic-governance-actor",
            authorized_at="2026-07-27T00:04:00Z",
        )
        governance_capture = lane.capture(
            governance_packet,
            output_text="Synthetic candidate result.",
            actor_ref="synthetic-governance-actor",
            observed_models=("synthetic-model-label",),
            credits_consumed=1,
            provider_surface_receipt_sha256=hashlib.sha256(
                b"synthetic-governance-provider-surface"
            ).hexdigest(),
            captured_at="2026-07-27T00:05:00Z",
        )
        lane.review(
            governance_capture["receipt"],
            actor_ref="synthetic-governance-actor",
            decision="accepted_candidate",
            schema_valid=True,
            safety_valid=True,
            reviewed_at="2026-07-27T00:06:00Z",
        )
        rollback = lane.engage_rollback(
            actor_ref="synthetic-governance-actor",
            reason="Synthetic rollback proof.",
            engaged_at="2026-07-27T00:07:00Z",
        )
        audit_verification = lane.audit.verify()
        credit_summary = lane.credits.summary(
            at="2026-07-27T00:08:00Z"
        )
        persistent_governance = bool(
            audit_verification["valid"] is True
            and audit_verification["event_count"] == 5
            and credit_summary["consumed_credits"] == 1
            and rollback["receipt"]["kill_switch_effective"] is True
            and governance_sidecar.config.kill_switch_active() is True
        )
    return {
        "task_packet_schema": packet.to_dict()["schema"]
        == WORKLLM_TASK_PACKET_SCHEMA,
        "run_receipt_schema": receipt["schema"] == WORKLLM_RUN_RECEIPT_SCHEMA,
        "request_digest": bool(packet.request_sha256),
        "source_binding": receipt["source_binding_status"] == "bound",
        "input_redaction": redaction_passed,
        "output_redaction": receipt_redaction_passed,
        "kill_switch": kill_switch_passed,
        "internal_nonsecret_fail_closed": (
            internal_nonsecret_fail_closed
        ),
        "manual_credit_authorization": authorization["authorized"] is True,
        "api_fail_closed": api_fail_closed,
        "no_canonical_authority": no_authority_passed,
        "canary_evaluator": bool(
            canary_evaluation["promotion_eligible_candidate"] is True
            and canary_evaluation["canonical_promotion_authority"] is False
        ),
        "persistent_credit_audit_review": persistent_governance,
        "durable_rollback_override": bool(
            persistent_governance
            and rollback["receipt"]["canonical_promotion_authority"] is False
        ),
    }


def build_receipt(
    *,
    env_path: Path,
    output_path: Path,
    public_reachability_receipt: Path = PUBLIC_REACHABILITY_RECEIPT,
) -> dict[str, object]:
    presence, env_mode_600, workspace_url = _load_env_presence(env_path)
    canary = _run_contract_canary(workspace_url)
    inventory_text = (ROOT / "LTDs.md").read_text(encoding="utf-8")
    docs_text = (ROOT / "docs" / "WORKLLM_FLEET_SIDECAR.md").read_text(
        encoding="utf-8"
    )
    public_reachability: dict[str, object] = {}
    if public_reachability_receipt.is_file():
        loaded = json.loads(
            public_reachability_receipt.read_text(encoding="utf-8")
        )
        if isinstance(loaded, dict):
            public_reachability = loaded
    tenant_surface_reachable = bool(
        public_reachability.get("verdict")
        == "TENANT_SURFACE_REACHABLE_AUTH_PENDING"
        and public_reachability.get("irreversible_actions_attempted") == []
    )
    local_contract_ready = all(canary.values())
    receipt = {
        "contract_name": "executive_assistant.workllm_sidecar_verification.v1",
        "provider": "workllm",
        "generated_at": _utc_now(),
        "status": "candidate_only",
        "verdict": "CANDIDATE_ONLY",
        "commercial_plan": "AppSumo Tier 4 / Pro (user-reported)",
        "workspace_integration_tier": "Tier 4",
        "workspace_ref_sha256": (
            hashlib.sha256(workspace_url.encode("utf-8")).hexdigest()
            if workspace_url
            else ""
        ),
        "credential_presence": {
            "workspace_url": presence["WORKLLM_BASE_URL"],
            "email": presence["WORKLLM_EMAIL"],
            "password": presence["WORKLLM_PASSWORD"],
            "env_mode_600": env_mode_600,
        },
        "promotion": {
            "account_verified": False,
            "provider_verified": False,
            "manual_lane_promoted": False,
            "api_lane_promoted": False,
            "runtime_enabled": False,
            "organization_memory_enabled": False,
        },
        "checks": {
            "inventory_recorded": "`WorkLLM`" in inventory_text,
            "boundary_documented": "candidate_only" in docs_text,
            "credentials_protected": bool(
                presence["WORKLLM_EMAIL"]
                and presence["WORKLLM_PASSWORD"]
                and env_mode_600
            ),
            "tenant_surface_reachable": tenant_surface_reachable,
            "local_contract_ready": local_contract_ready,
            **canary,
        },
        "evidence_receipts": {
            "public_reachability": {
                "path": (
                    str(public_reachability_receipt.relative_to(ROOT))
                    if public_reachability_receipt.is_relative_to(ROOT)
                    else public_reachability_receipt.name
                ),
                "sha256": (
                    _sha256_file(public_reachability_receipt)
                    if public_reachability_receipt.is_file()
                    else ""
                ),
            }
        },
        "packet_data_classes": ["public", "internal_nonsecret"],
        "default_authorized_data_classes": ["public"],
        "stronger_data_gate": {
            "environment_flag": (
                "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED"
            ),
            "enabled": False,
        },
        "allowed_lanes": [
            "research_synthesis",
            "multi_model_compare",
            "document_qna",
            "spec_contradiction_audit",
            "release_evidence_summary",
            "sop_draft",
        ],
        "authority": {
            "candidate_only": True,
            "canonical_write_allowed": False,
            "repo_write_allowed": False,
            "external_send_allowed": False,
            "publish_allowed": False,
            "approval_allowed": False,
        },
        "blocking_reasons": [
            "Authenticated workspace identity, Tier 4 allocation, and current credit balance are not yet captured.",
            "RBAC, audit, export, deletion, retention, and organization-memory controls are not yet observed.",
            "Internal-nonsecret data remains separately disabled pending stronger provider-control evidence.",
            "A genuine WorkLLM API, service authentication, model provenance, usage telemetry, idempotency, and webhook controls are not proven.",
            "The required 20-run manual canary has not been executed.",
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
            "Verify the local fail-closed WorkLLM sidecar contracts without "
            "contacting WorkLLM or exposing credentials."
        )
    )
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    receipt = build_receipt(
        env_path=Path(args.env),
        output_path=Path(args.output),
    )
    print(
        json.dumps(
            {
                "status": "ok"
                if receipt["checks"]["local_contract_ready"]
                else "failed",
                "verdict": receipt["verdict"],
                "account_verified": receipt["promotion"]["account_verified"],
                "provider_verified": receipt["promotion"]["provider_verified"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["checks"]["local_contract_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
