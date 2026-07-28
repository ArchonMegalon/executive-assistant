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

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for import_root in (ROOT, EA_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.services.workllm_governance import (  # noqa: E402
    WORKLLM_CREDIT_LEDGER_SCHEMA,
    WorkLLMAuditLedger,
    WorkLLMGovernanceError,
)
from app.services.workllm_sidecar import (  # noqa: E402
    WORKLLM_RUN_RECEIPT_SCHEMA,
    WorkLLMTaskPacket,
    evaluate_workllm_canary,
    redact_workllm_text,
)

from scripts.audit_workllm_goal import (  # noqa: E402
    _account_receipt_provenance_valid,
)

DEFAULT_OUTPUT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_MANUAL_CANARY.generated.json"
)
MANIFEST_SCHEMA = "executive_assistant.workllm_canary_manifest.v1"
SURFACE_RECEIPT_SCHEMA = (
    "executive_assistant.workllm_browser_run_receipt.v1"
)
EXPECTED_SITE = "girschele-workspace.workllm.io"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_payload(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("workllm_canary_secure_write_failed")
        offset += written


def _secure_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() and (
        path.is_symlink()
        or not path.is_file()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise SystemExit("workllm_canary_output_path_unsafe")
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


def _require_protected_file(
    path: Path,
    *,
    code: str,
    max_bytes: int,
) -> None:
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size <= 0
        or path.stat().st_size > max_bytes
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise SystemExit(f"{code}_invalid:{path}")


def _load_redacted_json(path: Path, *, code: str) -> dict[str, object]:
    _require_protected_file(path, code=code, max_bytes=2 * 1024 * 1024)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SystemExit(f"{code}_invalid:{path}") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"{code}_invalid:{path}")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    redacted, redactions = redact_workllm_text(serialized)
    if redacted != serialized or redactions:
        raise SystemExit(f"{code}_contains_sensitive_data:{path}")
    return dict(payload)


def _resolve_path(value: object, *, base: Path, code: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit(f"{code}_missing")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    return Path(os.path.abspath(candidate))


def _validated_local_run_artifacts(
    *,
    run_receipt: dict[str, object],
    run_path: Path,
    index: int,
) -> dict[str, str]:
    artifacts = run_receipt.get("local_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "task_packet",
        "result",
        "run_receipt",
    }:
        raise SystemExit(f"workllm_run_artifacts_invalid:{index}")
    packet_path = _resolve_path(
        artifacts.get("task_packet"),
        base=run_path.parent,
        code=f"workllm_run_task_packet:{index}",
    )
    result_path = _resolve_path(
        artifacts.get("result"),
        base=run_path.parent,
        code=f"workllm_run_result:{index}",
    )
    declared_run_path = _resolve_path(
        artifacts.get("run_receipt"),
        base=run_path.parent,
        code=f"workllm_run_receipt_artifact:{index}",
    )
    if declared_run_path != run_path:
        raise SystemExit(f"workllm_run_receipt_artifact_mismatch:{index}")
    packet_payload = _load_redacted_json(
        packet_path,
        code=f"workllm_run_task_packet:{index}",
    )
    packet = WorkLLMTaskPacket.from_dict(packet_payload)
    _require_protected_file(
        result_path,
        code=f"workllm_run_result:{index}",
        max_bytes=2 * 1024 * 1024,
    )
    try:
        result_text = result_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise SystemExit(f"workllm_run_result_invalid:{index}") from None
    redacted_result, result_redactions = redact_workllm_text(result_text)
    output_sha256 = str(
        run_receipt.get("output_sha256") or ""
    ).strip().lower()
    if (
        packet.task_id != run_receipt.get("task_id")
        or packet.request_sha256 != run_receipt.get("request_sha256")
        or redacted_result != result_text
        or result_redactions
        or _SHA256_RE.fullmatch(output_sha256) is None
        or hashlib.sha256(result_text.encode("utf-8")).hexdigest()
        != output_sha256
    ):
        raise SystemExit(f"workllm_run_artifacts_invalid:{index}")
    return {
        "task_packet_path": str(packet_path),
        "task_packet_sha256": _sha256_file(packet_path),
        "result_path": str(result_path),
        "result_sha256": _sha256_file(result_path),
    }


def _validated_utc_timestamp(value: object, *, index: int) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("Z"):
        raise SystemExit(
            f"workllm_provider_surface_observed_at_invalid:{index}"
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(
            f"workllm_provider_surface_observed_at_invalid:{index}"
        ) from None
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SystemExit(
            f"workllm_provider_surface_observed_at_invalid:{index}"
        )
    return raw


def _validated_governance_evidence(
    *,
    manifest: dict[str, object],
    manifest_path: Path,
    run_receipts: list[dict[str, object]],
) -> dict[str, object]:
    governance = manifest.get("governance")
    if not isinstance(governance, dict):
        raise SystemExit("workllm_canary_governance_missing")
    audit_path = _resolve_path(
        governance.get("audit_ledger"),
        base=manifest_path.parent,
        code="workllm_canary_audit_ledger",
    )
    credit_path = _resolve_path(
        governance.get("credit_ledger"),
        base=manifest_path.parent,
        code="workllm_canary_credit_ledger",
    )
    if (
        audit_path.name != "audit.jsonl"
        or credit_path.name != "credit_ledger.json"
        or audit_path.parent != credit_path.parent
    ):
        raise SystemExit("workllm_canary_governance_path_invalid")
    _require_protected_file(
        audit_path,
        code="workllm_canary_audit_ledger",
        max_bytes=20 * 1024 * 1024,
    )
    credit = _load_redacted_json(
        credit_path,
        code="workllm_canary_credit_ledger",
    )
    reservations = credit.get("reservations")
    if (
        credit.get("schema") != WORKLLM_CREDIT_LEDGER_SCHEMA
        or not isinstance(reservations, dict)
    ):
        raise SystemExit("workllm_canary_credit_ledger_invalid")
    ledger = WorkLLMAuditLedger(audit_path.parent)
    try:
        audit_verification = ledger.verify()
    except WorkLLMGovernanceError:
        raise SystemExit("workllm_canary_audit_ledger_invalid") from None
    expected_lifecycle = (
        "task_prepared",
        "submission_authorized",
        "result_captured",
        "review_completed",
    )
    lifecycle_count = 0
    total_credits_consumed = 0
    for index, run in enumerate(run_receipts):
        task_id = str(run.get("task_id") or "")
        request_sha256 = str(run.get("request_sha256") or "")
        credits_consumed = run.get("credits_consumed")
        reservation = reservations.get(task_id)
        if (
            not isinstance(credits_consumed, int)
            or isinstance(credits_consumed, bool)
            or credits_consumed < 0
            or not isinstance(reservation, dict)
            or reservation.get("request_sha256") != request_sha256
            or reservation.get("status") != "consumed"
            or reservation.get("consumed_credits") != credits_consumed
        ):
            raise SystemExit(
                f"workllm_canary_credit_evidence_invalid:{index}"
            )
        try:
            events = ledger.entries_for_task(task_id)
        except WorkLLMGovernanceError:
            raise SystemExit(
                f"workllm_canary_audit_lifecycle_invalid:{index}"
            ) from None
        lifecycle_position = 0
        final_receipt_bound = False
        for event in events:
            details = event.get("details")
            if not isinstance(details, dict):
                continue
            if details.get("request_sha256") != request_sha256:
                continue
            event_type = str(event.get("event_type") or "")
            if (
                lifecycle_position < len(expected_lifecycle)
                and event_type
                == expected_lifecycle[lifecycle_position]
            ):
                lifecycle_position += 1
            if (
                event_type == "review_completed"
                and event.get("receipt_sha256")
                == _sha256_payload(run)
            ):
                final_receipt_bound = True
        if (
            lifecycle_position != len(expected_lifecycle)
            or not final_receipt_bound
        ):
            raise SystemExit(
                f"workllm_canary_audit_lifecycle_invalid:{index}"
            )
        lifecycle_count += 1
        total_credits_consumed += int(credits_consumed)
    return {
        "audit_ledger_path": str(audit_path),
        "audit_ledger_sha256": _sha256_file(audit_path),
        "audit_event_count": audit_verification["event_count"],
        "audit_head_event_sha256": audit_verification[
            "head_event_sha256"
        ],
        "credit_ledger_path": str(credit_path),
        "credit_ledger_sha256": _sha256_file(credit_path),
        "governed_lifecycle_count": lifecycle_count,
        "total_credits_consumed": total_credits_consumed,
    }


def build_manual_canary_receipt(
    *,
    manifest_path: Path,
    output_path: Path,
) -> dict[str, object]:
    manifest = _load_redacted_json(
        manifest_path,
        code="workllm_canary_manifest",
    )
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit("workllm_canary_manifest_schema_mismatch")
    if manifest.get("mode") != "manual_browser":
        raise SystemExit("workllm_canary_mode_mismatch")
    account_path = _resolve_path(
        manifest.get("account_verification_receipt"),
        base=manifest_path.parent,
        code="workllm_account_verification_receipt",
    )
    account = _load_redacted_json(
        account_path,
        code="workllm_account_verification_receipt",
    )
    if (
        account.get("contract_name")
        != "executive_assistant.workllm_account_verification.v1"
        or account.get("verdict") != "VERIFIED_MANUAL_WORKBENCH"
        or account.get("manual_workbench_verified") is not True
        or account.get("manual_data_classes") != ["public"]
        or account.get("internal_nonsecret_eligible") is not False
        or not _account_receipt_provenance_valid(account)
    ):
        raise SystemExit("workllm_account_not_verified_for_canary")
    account_ref_sha256 = str(
        account.get("account_ref_sha256") or ""
    ).strip().lower()
    if _SHA256_RE.fullmatch(account_ref_sha256) is None:
        raise SystemExit("workllm_account_ref_invalid")

    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise SystemExit("workllm_canary_runs_invalid")
    run_receipts: list[dict[str, object]] = []
    run_evidence: list[dict[str, str]] = []
    for index, raw_run in enumerate(runs):
        if not isinstance(raw_run, dict):
            raise SystemExit(f"workllm_canary_run_invalid:{index}")
        run_path = _resolve_path(
            raw_run.get("run_receipt"),
            base=manifest_path.parent,
            code=f"workllm_run_receipt:{index}",
        )
        surface_path = _resolve_path(
            raw_run.get("provider_surface_receipt"),
            base=manifest_path.parent,
            code=f"workllm_provider_surface_receipt:{index}",
        )
        output_surface_path = _resolve_path(
            raw_run.get("provider_output_surface_artifact"),
            base=manifest_path.parent,
            code=f"workllm_provider_output_surface_artifact:{index}",
        )
        run_receipt = _load_redacted_json(
            run_path,
            code=f"workllm_run_receipt:{index}",
        )
        surface_receipt = _load_redacted_json(
            surface_path,
            code=f"workllm_provider_surface_receipt:{index}",
        )
        local_artifact_evidence = _validated_local_run_artifacts(
            run_receipt=run_receipt,
            run_path=run_path,
            index=index,
        )
        if run_receipt.get("schema") != WORKLLM_RUN_RECEIPT_SCHEMA:
            raise SystemExit(f"workllm_run_receipt_schema_mismatch:{index}")
        if surface_receipt.get("schema") != SURFACE_RECEIPT_SCHEMA:
            raise SystemExit(
                f"workllm_provider_surface_schema_mismatch:{index}"
            )
        if (
            str(surface_receipt.get("site") or "").strip().lower()
            != EXPECTED_SITE
        ):
            raise SystemExit(
                f"workllm_provider_surface_site_mismatch:{index}"
            )
        if surface_receipt.get("work_type") != "research":
            raise SystemExit(
                f"workllm_provider_surface_work_type_mismatch:{index}"
            )
        if surface_receipt.get("prepared_packet_only") is not True:
            raise SystemExit(
                f"workllm_provider_surface_packet_boundary_failed:{index}"
            )
        if surface_receipt.get("output_captured") is not True:
            raise SystemExit(
                f"workllm_provider_surface_output_missing:{index}"
            )
        _validated_utc_timestamp(
            surface_receipt.get("observed_at"),
            index=index,
        )
        output_surface_sha256 = str(
            surface_receipt.get("provider_output_surface_sha256") or ""
        ).strip().lower()
        if _SHA256_RE.fullmatch(output_surface_sha256) is None:
            raise SystemExit(
                f"workllm_provider_output_surface_evidence_missing:{index}"
            )
        if surface_receipt.get("irreversible_actions_attempted") != []:
            raise SystemExit(
                f"workllm_provider_surface_irreversible_action:{index}"
            )
        if (
            surface_receipt.get("stop_condition")
            != "comparison_ready_for_user_decision"
        ):
            raise SystemExit(
                f"workllm_provider_surface_stop_condition_invalid:{index}"
            )
        if surface_receipt.get("account_ref_sha256") != account_ref_sha256:
            raise SystemExit(
                f"workllm_provider_surface_account_mismatch:{index}"
            )
        if (
            surface_receipt.get("request_sha256")
            != run_receipt.get("request_sha256")
        ):
            raise SystemExit(
                f"workllm_provider_surface_request_mismatch:{index}"
            )
        surface_sha256 = _sha256_file(surface_path)
        if (
            run_receipt.get("provider_surface_receipt_sha256")
            != surface_sha256
        ):
            raise SystemExit(
                f"workllm_provider_surface_digest_mismatch:{index}"
            )
        _require_protected_file(
            output_surface_path,
            code=f"workllm_provider_output_surface_artifact:{index}",
            max_bytes=20 * 1024 * 1024,
        )
        if _sha256_file(output_surface_path) != output_surface_sha256:
            raise SystemExit(
                f"workllm_provider_output_surface_digest_mismatch:{index}"
            )
        run_receipts.append(run_receipt)
        run_evidence.append(
            {
                **local_artifact_evidence,
                "run_receipt_path": str(run_path),
                "run_receipt_sha256": _sha256_file(run_path),
                "provider_surface_receipt_path": str(surface_path),
                "provider_surface_receipt_sha256": surface_sha256,
                "provider_output_surface_artifact_path": str(
                    output_surface_path
                ),
                "provider_output_surface_sha256": output_surface_sha256,
            }
        )
    evaluation = evaluate_workllm_canary(
        run_receipts,
        mode="manual_browser",
    )
    governance_evidence = _validated_governance_evidence(
        manifest=manifest,
        manifest_path=manifest_path,
        run_receipts=run_receipts,
    )
    evaluation["manifest_path"] = str(manifest_path)
    evaluation["manifest_sha256"] = _sha256_file(manifest_path)
    evaluation["account_verification_receipt_path"] = str(account_path)
    evaluation["account_verification_receipt_sha256"] = _sha256_file(
        account_path
    )
    evaluation["real_provider_run_count"] = len(run_evidence)
    evaluation["run_evidence"] = run_evidence
    evaluation["governance_evidence"] = governance_evidence
    evaluation["governed_lifecycle_count"] = governance_evidence[
        "governed_lifecycle_count"
    ]
    evaluation["canonical_promotion_authority"] = False
    _secure_write_json(output_path, evaluation)
    return evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate explicit WorkLLM manual-run and browser-surface receipts "
            "without discovering files or accepting synthetic evidence."
        )
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    receipt = build_manual_canary_receipt(
        manifest_path=Path(args.manifest),
        output_path=Path(args.output),
    )
    print(
        json.dumps(
            {
                "promotion_eligible_candidate": receipt[
                    "promotion_eligible_candidate"
                ],
                "run_count": receipt["run_count"],
                "failures": receipt["failures"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["promotion_eligible_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
