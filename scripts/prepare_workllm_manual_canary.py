#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
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
    WorkLLMConfig,
    WorkLLMSidecar,
    redact_workllm_text,
)

CORPUS_SCHEMA = "executive_assistant.workllm_canary_corpus.v1"
PLAN_SCHEMA = "executive_assistant.workllm_canary_execution_plan.v1"
RECEIPT_SCHEMA = "executive_assistant.workllm_canary_preparation.v1"
DEFAULT_CORPUS = ROOT / "config" / "workllm_manual_canary_corpus.json"
DEFAULT_RUNTIME_ROOT = ROOT / ".runtime" / "workllm" / "canary-prepared"
DEFAULT_OUTPUT = (
    ROOT
    / "ea"
    / "_completion"
    / "workllm"
    / "WORKLLM_CANARY_PREPARATION.generated.json"
)
EXPECTED_LANE_COUNTS = {
    "research_synthesis": 4,
    "multi_model_compare": 4,
    "spec_contradiction_audit": 4,
    "release_evidence_summary": 4,
    "sop_draft": 4,
}
_SAFE_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_utc_timestamp(value: object) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("Z"):
        raise SystemExit("workllm_canary_created_at_invalid")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("workllm_canary_created_at_invalid") from None
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SystemExit("workllm_canary_created_at_invalid")
    return raw


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        or (path.stat().st_mode & 0o777) != 0o600
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


def _load_corpus(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"workllm_canary_corpus_missing:{path}")
    if path.stat().st_size <= 0 or path.stat().st_size > 2 * 1024 * 1024:
        raise SystemExit("workllm_canary_corpus_size_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SystemExit("workllm_canary_corpus_invalid") from None
    if not isinstance(payload, dict):
        raise SystemExit("workllm_canary_corpus_invalid")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    redacted, redactions = redact_workllm_text(serialized)
    if redacted != serialized or redactions:
        raise SystemExit("workllm_canary_corpus_contains_sensitive_data")
    return dict(payload)


def _validate_corpus(
    corpus: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    policy = corpus.get("execution_policy")
    output_schema = corpus.get("output_schema")
    tasks = corpus.get("tasks")
    if (
        corpus.get("schema") != CORPUS_SCHEMA
        or corpus.get("source_kind") != "synthetic_fixture"
        or corpus.get("data_classification") != "public"
        or not isinstance(policy, dict)
        or not isinstance(output_schema, dict)
        or output_schema.get("type") != "object"
        or not isinstance(tasks, list)
        or len(tasks) != 20
    ):
        raise SystemExit("workllm_canary_corpus_contract_invalid")
    if any(value is not False for value in policy.values()) or set(policy) != {
        "external_actions_allowed",
        "organization_memory_allowed",
        "provider_file_upload_allowed",
        "provider_web_search_allowed",
        "repository_access_allowed",
    }:
        raise SystemExit("workllm_canary_execution_policy_invalid")
    normalized_tasks: list[dict[str, object]] = []
    case_ids: set[str] = set()
    lane_counts: Counter[str] = Counter()
    for index, raw_task in enumerate(tasks):
        if not isinstance(raw_task, dict):
            raise SystemExit(f"workllm_canary_task_invalid:{index}")
        case_id = str(raw_task.get("case_id") or "").strip()
        lane = str(raw_task.get("lane") or "").strip().lower()
        title = str(raw_task.get("title") or "").strip()
        context = str(raw_task.get("prepared_context") or "").strip()
        prompt = str(raw_task.get("prompt_text") or "").strip()
        max_credits = raw_task.get("max_credits")
        model_count = raw_task.get("requested_model_count")
        if (
            not re.fullmatch(r"\d{2}", case_id)
            or case_id in case_ids
            or lane not in EXPECTED_LANE_COUNTS
            or not title
            or not context
            or not prompt
            or not isinstance(max_credits, int)
            or isinstance(max_credits, bool)
            or max_credits <= 0
            or max_credits > 10
            or model_count not in {1, 2}
            or (lane == "multi_model_compare" and model_count != 2)
            or (lane != "multi_model_compare" and model_count != 1)
        ):
            raise SystemExit(f"workllm_canary_task_invalid:{index}")
        case_ids.add(case_id)
        lane_counts[lane] += 1
        normalized_tasks.append(dict(raw_task))
    if dict(lane_counts) != EXPECTED_LANE_COUNTS:
        raise SystemExit("workllm_canary_lane_coverage_invalid")
    return normalized_tasks, dict(output_schema)


def prepare_manual_canary(
    *,
    corpus_path: Path,
    runtime_root: Path,
    output_path: Path,
    batch_id: str,
    created_at: str,
) -> dict[str, object]:
    normalized_batch_id = str(batch_id or "").strip()
    if _SAFE_BATCH_ID_RE.fullmatch(normalized_batch_id) is None:
        raise SystemExit("workllm_canary_batch_id_invalid")
    timestamp = _validate_utc_timestamp(created_at)
    corpus = _load_corpus(corpus_path)
    tasks, output_schema = _validate_corpus(corpus)
    try:
        source_ref = str(
            corpus_path.resolve(strict=True).relative_to(ROOT.resolve())
        )
    except (FileNotFoundError, ValueError):
        raise SystemExit("workllm_canary_corpus_must_be_in_repo") from None
    corpus_sha256 = _sha256_file(corpus_path)
    batch_root = runtime_root / normalized_batch_id
    result_root = runtime_root.parent
    config = WorkLLMConfig(
        workspace_url="https://girschele-workspace.workllm.io",
        receipt_root=batch_root,
        control_state_file=batch_root / "control_state.json",
        kill_switch_engaged=True,
    )
    sidecar = WorkLLMSidecar(config)
    lane = GovernedWorkLLMManualLane(
        sidecar,
        governance_root=batch_root / "governance",
    )
    plan_tasks: list[dict[str, object]] = []
    packet_evidence: list[dict[str, str]] = []
    total_credit_ceiling = 0
    correlation_id = normalized_batch_id
    for task in tasks:
        case_id = str(task["case_id"])
        task_id = f"{normalized_batch_id}-{case_id}"
        packet = sidecar.prepare_task_packet(
            lane=str(task["lane"]),
            data_classification="public",
            prepared_context=str(task["prepared_context"]),
            source_manifest=[
                {
                    "ref": source_ref,
                    "sha256": corpus_sha256,
                }
            ],
            prompt_template_id=f"workllm_canary_{task['lane']}",
            prompt_template_version=str(
                corpus.get("prompt_template_version") or "1"
            ),
            prompt_text=str(task["prompt_text"]),
            output_schema=output_schema,
            max_credits=int(task["max_credits"]),
            task_id=task_id,
            correlation_id=correlation_id,
            created_at=timestamp,
        )
        staged = lane.stage_packet(
            packet,
            actor_ref="workllm-canary-preparer",
            occurred_at=timestamp,
        )
        packet_path = Path(str(staged["task_packet_path"]))
        packet_sha256 = _sha256_file(packet_path)
        task_runtime_root = result_root / task_id
        plan_tasks.append(
            {
                "case_id": case_id,
                "lane": packet.lane,
                "max_credits": packet.max_credits,
                "operator_payload": {
                    "output_schema": output_schema,
                    "prepared_context": packet.prepared_context,
                    "prompt_text": str(task["prompt_text"]),
                    "requested_model_count": int(
                        task["requested_model_count"]
                    ),
                },
                "provider_output_capture_path": str(
                    task_runtime_root / "provider_output.txt"
                ),
                "provider_output_surface_artifact_path": str(
                    task_runtime_root / "provider_output_surface.png"
                ),
                "provider_surface_receipt_path": str(
                    task_runtime_root / "provider_surface_receipt.json"
                ),
                "request_sha256": packet.request_sha256,
                "run_receipt_path": str(
                    task_runtime_root / "run_receipt.json"
                ),
                "status": "prepared_not_authorized",
                "stop_condition": "comparison_ready_for_user_decision",
                "task_id": task_id,
                "task_packet_path": str(packet_path),
                "task_packet_sha256": packet_sha256,
                "title": str(task["title"]),
                "work_type": "research",
            }
        )
        packet_evidence.append(
            {
                "request_sha256": packet.request_sha256,
                "task_id": task_id,
                "task_packet_path": str(packet_path),
                "task_packet_sha256": packet_sha256,
            }
        )
        total_credit_ceiling += packet.max_credits
    execution_plan: dict[str, object] = {
        "schema": PLAN_SCHEMA,
        "provider": "workllm",
        "batch_id": normalized_batch_id,
        "prepared_at": timestamp,
        "status": "prepared_not_authorized",
        "corpus_path": str(corpus_path),
        "corpus_sha256": corpus_sha256,
        "result_root": str(result_root),
        "data_classification": "public",
        "source_kind": "synthetic_fixture",
        "task_count": len(plan_tasks),
        "total_credit_ceiling": total_credit_ceiling,
        "provider_interaction_observed": False,
        "credit_reservations_created": 0,
        "submissions_authorized": 0,
        "organization_memory_allowed": False,
        "provider_file_upload_allowed": False,
        "provider_web_search_allowed": False,
        "repository_access_allowed": False,
        "tasks": plan_tasks,
    }
    plan_path = batch_root / "execution_plan.json"
    _secure_write_json(plan_path, execution_plan)
    receipt: dict[str, object] = {
        "contract_name": RECEIPT_SCHEMA,
        "provider": "workllm",
        "prepared_at": timestamp,
        "batch_id": normalized_batch_id,
        "verdict": "PREPARED_NOT_EXECUTED",
        "corpus_path": str(corpus_path),
        "corpus_sha256": corpus_sha256,
        "execution_plan_path": str(plan_path),
        "execution_plan_sha256": _sha256_file(plan_path),
        "result_root": str(result_root),
        "task_count": len(plan_tasks),
        "unique_request_count": len(
            {item["request_sha256"] for item in packet_evidence}
        ),
        "lane_counts": dict(Counter(item["lane"] for item in plan_tasks)),
        "total_credit_ceiling": total_credit_ceiling,
        "packet_evidence": packet_evidence,
        "provider_interaction_observed": False,
        "credit_reservations_created": 0,
        "submissions_authorized": 0,
        "promotion_eligible_candidate": False,
        "canonical_promotion_authority": False,
        "next_gate": "authenticated_account_verification",
    }
    _secure_write_json(output_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage twenty synthetic, source-bound WorkLLM manual-canary "
            "packets without authorizing or contacting the provider."
        )
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--batch-id", default="workllm-canary-v1")
    parser.add_argument("--created-at", default=_utc_now())
    args = parser.parse_args()
    receipt = prepare_manual_canary(
        corpus_path=Path(args.corpus),
        runtime_root=Path(args.runtime_root),
        output_path=Path(args.output),
        batch_id=args.batch_id,
        created_at=args.created_at,
    )
    print(
        json.dumps(
            {
                "verdict": receipt["verdict"],
                "task_count": receipt["task_count"],
                "total_credit_ceiling": receipt[
                    "total_credit_ceiling"
                ],
                "execution_plan": receipt["execution_plan_path"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
