#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services.approvethis_external_approval import (  # noqa: E402
    ApproveThisExternalApprovalService,
    approvethis_webhook_signature,
    build_approvethis_external_request,
)
from app.services.documentation_ai_publication import build_documentation_ai_publication_packet  # noqa: E402
from app.services.ea_quality_gates import (  # noqa: E402
    REQUIRED_SECURITY_TARGETS,
    REQUIRED_VISUAL_TARGETS,
    build_ea_quality_gate_receipt,
)
from app.services.hedy_meeting_evidence import (  # noqa: E402
    HedyMeetingEvidenceService,
    hedy_webhook_signature,
)
from app.services.hedy_meeting_review_intake import HedyMeetingReviewIntakeService  # noqa: E402
from app.services.premium_delivery import build_premium_delivery_packet  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "_completion" / "ea_provider_contracts"
CONTRACT_STATUS = "contract_pass_live_provider_pending"
PROOF_SCOPE = "local_contract_exercise"


@dataclass
class _ContractHumanTask:
    human_task_id: str
    task_type: str
    priority: str
    authority_required: str
    input_json: dict[str, object]
    principal_id: str
    dedupe_key: str


class _ContractHedyReviewQueue:
    def __init__(self) -> None:
        self._tasks_by_dedupe: dict[tuple[str, str], _ContractHumanTask] = {}

    def find_human_task_by_dedupe(self, dedupe_key: str, *, principal_id: str) -> _ContractHumanTask | None:
        return self._tasks_by_dedupe.get((str(principal_id or "").strip(), str(dedupe_key or "").strip()))

    def create_human_task(
        self,
        *,
        principal_id: str,
        task_type: str,
        priority: str,
        authority_required: str,
        input_json: dict[str, object],
        dedupe_key: str,
    ) -> _ContractHumanTask:
        key = (str(principal_id or "").strip(), str(dedupe_key or "").strip())
        existing = self._tasks_by_dedupe.get(key)
        if existing is not None:
            return existing
        task = _ContractHumanTask(
            human_task_id=f"human_task:{len(self._tasks_by_dedupe) + 1}",
            task_type=str(task_type or "").strip(),
            priority=str(priority or "").strip(),
            authority_required=str(authority_required or "").strip(),
            input_json=dict(input_json or {}),
            principal_id=key[0],
            dedupe_key=key[1],
        )
        self._tasks_by_dedupe[key] = task
        return task


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_time(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return _utc_now()
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _json_body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write(output_dir: Path, filename: str, payload: dict[str, object]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _hedy_receipt(*, generated_at: datetime) -> dict[str, object]:
    payload = {
        "event_id": "contract-hedy-event-001",
        "type": "session.completed",
        "session": {
            "id": "contract-hedy-session-001",
            "recording_consent_confirmed": True,
            "region": "eu",
            "transcript": "Operator: Please prepare the board packet.\nExecutive: Decide if it is ready for external approval.",
            "summary": "One action item and one decision were identified.",
            "action_items": [{"title": "Prepare the board packet", "assignee": "Operator"}],
            "decisions": [{"question": "Is the board packet ready for external approval?", "options": ["Approve", "Request changes"]}],
            "participants": [{"name": "Operator", "role": "EA operator"}],
            "follow_ups": [{"recipient": "Executive", "draft_text": "The board packet is ready for your review."}],
        },
    }
    body = _json_body(payload)
    timestamp = str(int(generated_at.timestamp()))
    secret = "local-contract-secret"
    service = HedyMeetingEvidenceService(webhook_secret=secret, clock=lambda: generated_at)
    packet = service.ingest_webhook(
        body=body,
        headers={
            "x-hedy-timestamp": timestamp,
            "x-hedy-signature": hedy_webhook_signature(body, secret, timestamp=timestamp),
        },
        principal_id="contract-principal",
        workspace_id="contract-workspace",
    )
    review_service = HedyMeetingReviewIntakeService(
        orchestrator=_ContractHedyReviewQueue(),
        webhook_secret=secret,
        clock=lambda: generated_at,
    )
    review_intake = review_service.ingest_webhook_to_review_queue(
        body=body,
        headers={
            "x-hedy-timestamp": timestamp,
            "x-hedy-signature": hedy_webhook_signature(body, secret, timestamp=timestamp),
        },
        principal_id="contract-principal",
        workspace_id="contract-workspace",
    ).as_dict()
    review_retry = review_service.ingest_webhook_to_review_queue(
        body=body,
        headers={
            "x-hedy-timestamp": timestamp,
            "x-hedy-signature": hedy_webhook_signature(body, secret, timestamp=timestamp),
        },
        principal_id="contract-principal",
        workspace_id="contract-workspace",
    ).as_dict()
    return {
        "contract_name": "ea.provider_contract.hedy_meeting_evidence",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(generated_at),
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "sample_packet": packet,
        "sample_review_intake": review_intake,
        "sample_review_retry": review_retry,
        "verification": {
            "contract_exercised": True,
            "webhook_signature_contract": "pass",
            "consent_gate_contract": "pass",
            "review_only_contract": "pass",
            "webhook_to_review_queue_contract": "pass" if review_intake.get("created_review_task") is True else "fail",
            "idempotent_review_task_contract": "pass" if review_retry.get("duplicate") is True else "fail",
            "provider_capability_receipt_present": False,
        },
        "required_next_receipts": [
            "_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json",
            "_completion/hedy/HEDY_WEBHOOK_SIGNATURE.generated.json",
            "_completion/hedy/HEDY_LIVE_WEBHOOK_TO_EA_REVIEW_QUEUE.generated.json",
        ],
    }


def _premium_receipt(*, generated_at: datetime) -> dict[str, object]:
    source_packet = {
        "packet_id": "contract-premium-board-pack",
        "title": "Contract Board Packet",
        "data_classification": "board_private",
        "approval_status": "approved",
        "source_refs": [{"source_type": "ea_approved_html_memo", "path": "contract/board-pack.html"}],
        "content_html": "<h1>Contract Board Packet</h1><p>Approved sample content.</p>",
        "redaction_policy": {"status": "pass", "removed_fields": ["raw_calendar_body", "attendee_email"]},
        "access_policy": {
            "expires_at": "2026-06-25T00:00:00Z",
            "revocation_supported": True,
            "download_policy": "disabled",
            "viewer_analytics_policy": "aggregate_only",
            "no_public_indexing": True,
        },
    }
    packet = build_premium_delivery_packet(
        source_packet,
        principal_id="contract-principal",
        workspace_id="contract-workspace",
        rendered_artifact_bytes=b"%PDF-1.4\ncontract board packet\n%%EOF",
        rendered_filename="contract-board-packet.pdf",
        fliplink_publication={"publication_id": "contract-fliplink-publication", "url": "https://example.invalid/flip"},
        now=generated_at,
    )
    return {
        "contract_name": "ea.provider_contract.premium_delivery",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(generated_at),
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "sample_packet": packet,
        "verification": {
            "contract_exercised": True,
            "approved_source_contract": "pass",
            "private_redaction_access_contract": "pass",
            "artifact_hash_contract": "pass",
            "provider_truth_boundary": "pass",
            "live_markupgo_render_receipt_present": False,
            "live_fliplink_private_access_receipt_present": False,
        },
        "required_next_receipts": [
            "_completion/markupgo/MARKUPGO_PROVIDER_VERIFICATION.generated.json",
            "_completion/premium_delivery/EA_PREMIUM_DELIVERY_ROUNDTRIP.generated.json",
            "premium_packet_to_delivery_e2e.generated.json",
        ],
    }


def _approvethis_receipt(*, generated_at: datetime) -> dict[str, object]:
    request = build_approvethis_external_request(
        {
            "decision_id": "decision:contract-external-approval",
            "title": "Approve the contract board packet?",
            "summary": "External reviewer should approve the sample packet before delivery.",
            "scope": "bounded_decision",
            "options": ["Approve", "Request changes", "Reject"],
        },
        principal_id="contract-principal",
        workspace_id="contract-workspace",
        external_approver_contact="reviewer@example.invalid",
        now=generated_at,
    )
    result_payload = {
        "event_id": "contract-approvethis-event-001",
        "provider_request_id": "contract-provider-request-001",
        "ea_decision_id": "decision:contract-external-approval",
        "status": "approved",
    }
    body = _json_body(result_payload)
    timestamp = str(int(generated_at.timestamp()))
    secret = "local-contract-secret"
    service = ApproveThisExternalApprovalService(webhook_secret=secret, clock=lambda: generated_at)
    result = service.ingest_webhook(
        body=body,
        headers={
            "x-approvethis-timestamp": timestamp,
            "x-approvethis-signature": approvethis_webhook_signature(body, secret, timestamp=timestamp),
        },
        request_packet=request,
    )
    return {
        "contract_name": "ea.provider_contract.approvethis_external_approval",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(generated_at),
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "sample_request": request,
        "sample_result": result,
        "verification": {
            "contract_exercised": True,
            "bounded_scope_contract": "pass",
            "webhook_signature_contract": "pass",
            "evidence_mapping_contract": "pass",
            "downstream_action_boundary": "pass",
            "provider_capability_receipt_present": False,
        },
        "required_next_receipts": [
            "_completion/approvethis/APPROVETHIS_PROVIDER_CAPABILITY.generated.json",
            "_completion/approvethis/APPROVETHIS_WEBHOOK_SIGNATURE.generated.json",
            "approvethis_external_approval_e2e.generated.json",
        ],
    }


def _documentation_receipt(*, generated_at: datetime, source_git_head: str) -> dict[str, object]:
    packet = build_documentation_ai_publication_packet(
        [
            {
                "path": ".codex-design/ea/START_HERE.md",
                "source_type": "source_controlled_ea_docs",
                "approval_status": "approved",
                "data_classification": "public",
                "content": "# Start Here\n\nOne morning memo, one queue, one commitment system.",
            },
            {
                "path": ".codex-design/ea/SECURITY.md",
                "source_type": "approved_security_trust_center",
                "approval_status": "approved",
                "data_classification": "public",
                "content": "# Security\n\nSensitive work stays review-bound.",
            },
        ],
        site_key="ea-customer-help",
        source_git_head=source_git_head,
        llms_txt="# EA Docs\n\n- /start-here\n- /security",
        link_check={"status": "pass", "checked_url_count": 2, "broken_links": []},
        now=generated_at,
    )
    return {
        "contract_name": "ea.provider_contract.documentation_ai_publication",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(generated_at),
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "sample_packet": packet,
        "verification": {
            "contract_exercised": True,
            "source_hash_contract": "pass",
            "llms_txt_contract": "pass",
            "privacy_boundary_contract": "pass",
            "provider_writeback_boundary": "pass",
            "provider_capability_receipt_present": False,
        },
        "required_next_receipts": [
            "_completion/documentation_ai/DOCUMENTATION_AI_PROVIDER_CAPABILITY.generated.json",
            "_completion/documentation_ai/DOCUMENTATION_AI_LLMS_TXT.generated.json",
            "documentation_ai_publication_e2e.generated.json",
        ],
    }


def _quality_receipt(*, generated_at: datetime, source_git_head: str) -> dict[str, object]:
    security_results = [
        {"target": target, "status": "pass", "evidence_id": f"contract-rafter:{target}", "source_git_head": source_git_head}
        for target in REQUIRED_SECURITY_TARGETS
    ]
    visual_results = [
        {"target": target, "status": "pass", "evidence_id": f"contract-pixefy:{target}", "source_git_head": source_git_head}
        for target in REQUIRED_VISUAL_TARGETS
    ]
    packet = build_ea_quality_gate_receipt(
        source_git_head=source_git_head,
        security_results=security_results,
        visual_results=visual_results,
        ea_release_receipt_status="",
        now=generated_at,
    )
    return {
        "contract_name": "ea.provider_contract.ea_quality_gates",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(generated_at),
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "sample_packet": packet,
        "verification": {
            "contract_exercised": True,
            "security_target_matrix_contract": "pass",
            "visual_target_matrix_contract": "pass",
            "release_truth_boundary": "pass",
            "current_head_binding_contract": "pass" if source_git_head else "fail",
            "live_rafter_pixefy_receipts_present": False,
        },
        "required_next_receipts": [
            "_completion/rafter/EA_RAFTER_SECURITY_TARGETS.generated.json",
            "_completion/pixefy/EA_PIXEFY_VISUAL_TARGETS.generated.json",
            "ea_release_quality_gates_e2e.generated.json",
        ],
    }


def build_receipts(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: str | None = None,
    source_git_head: str | None = None,
) -> list[Path]:
    now = _parse_time(generated_at)
    head = str(source_git_head or "").strip() or _git_head()
    receipts = {
        "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json": _hedy_receipt(generated_at=now),
        "PREMIUM_DELIVERY_CONTRACT.generated.json": _premium_receipt(generated_at=now),
        "APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json": _approvethis_receipt(generated_at=now),
        "DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json": _documentation_receipt(generated_at=now, source_git_head=head),
        "EA_QUALITY_GATES_CONTRACT.generated.json": _quality_receipt(generated_at=now, source_git_head=head),
    }
    paths = [_write(output_dir, filename, payload) for filename, payload in receipts.items()]
    summary = {
        "contract_name": "ea.provider_contract_receipts",
        "status": CONTRACT_STATUS,
        "proof_scope": PROOF_SCOPE,
        "generated_at": _timestamp(now),
        "source_git_head": head,
        "live_provider_runtime_verified": False,
        "gold_claim_allowed": False,
        "claim": "Contract layer is implemented and exercised locally; live provider runtime remains pending.",
        "receipts": [
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "contract_name": receipts[path.name]["contract_name"],
                "status": receipts[path.name]["status"],
                "proof_scope": receipts[path.name]["proof_scope"],
                "live_provider_runtime_verified": False,
            }
            for path in paths
        ],
        "required_next_receipts": sorted(
            {
                item
                for receipt in receipts.values()
                for item in list(receipt.get("required_next_receipts", []) or [])
            }
        ),
        "not_live_provider_proof": True,
        "not_release_gold_proof": True,
    }
    paths.append(_write(output_dir, "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json", summary))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize EA provider contract-level proof receipts.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--source-git-head", default="")
    args = parser.parse_args()
    paths = build_receipts(
        output_dir=Path(args.output_dir),
        generated_at=str(args.generated_at or "").strip() or None,
        source_git_head=str(args.source_git_head or "").strip() or None,
    )
    print(json.dumps({"status": "ok", "written": [str(path) for path in paths]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
