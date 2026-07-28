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
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for import_root in (ROOT, EA_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.services.workllm_governance import (  # noqa: E402
    GovernedWorkLLMManualLane,
)
from app.services.workllm_sidecar import (  # noqa: E402
    WORKLLM_RUN_RECEIPT_SCHEMA,
    WorkLLMConfig,
    WorkLLMSidecar,
    WorkLLMTaskPacket,
    redact_workllm_text,
)

from scripts.audit_workllm_goal import (  # noqa: E402
    ACCOUNT_VERIFICATION_RECEIPT,
    MANUAL_CANARY_RECEIPT,
    _account_receipt_provenance_valid,
)
from scripts.evaluate_workllm_manual_canary import (  # noqa: E402
    build_manual_canary_receipt,
)
from scripts.prepare_workllm_manual_canary import (  # noqa: E402
    PLAN_SCHEMA,
)

SURFACE_RECEIPT_SCHEMA = (
    "executive_assistant.workllm_browser_run_receipt.v1"
)
MANIFEST_SCHEMA = "executive_assistant.workllm_canary_manifest.v1"
EXPECTED_SITE = "girschele-workspace.workllm.io"
DEFAULT_PLAN = (
    ROOT
    / ".runtime"
    / "workllm"
    / "canary-prepared"
    / "workllm-canary-v1"
    / "execution_plan.json"
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CREDIT_DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
_CANDIDATE_OUTPUT_FIELDS = {
    "summary",
    "findings",
    "contradictions",
    "uncertainties",
    "recommendation",
    "authority_statement",
}
_KNOWN_ENV_KEYS = {
    "WORKLLM_BASE_URL",
    "EA_WORKLLM_ACCOUNT_VERIFIED",
    "WORKLLM_PROVIDER_VERIFIED",
    "EA_WORKLLM_MANUAL_LANE_ENABLED",
    "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED",
    "WORKLLM_RUNTIME_ENABLED",
    "EA_WORKLLM_API_LANE_ENABLED",
    "EA_WORKLLM_KILL_SWITCH",
    "EA_WORKLLM_API_CONTRACT_VERIFIED",
    "EA_WORKLLM_MODEL_PROVENANCE_VERIFIED",
    "EA_WORKLLM_USAGE_TELEMETRY_VERIFIED",
    "EA_WORKLLM_IDEMPOTENCY_VERIFIED",
    "EA_WORKLLM_RETENTION_CONTROLS_VERIFIED",
    "EA_WORKLLM_WEBHOOK_CONTROLS_VERIFIED",
    "EA_WORKLLM_MONTHLY_CREDIT_LIMIT",
    "EA_WORKLLM_SOFT_CREDIT_LIMIT",
    "EA_WORKLLM_HARD_CREDIT_LIMIT",
    "EA_WORKLLM_MAX_TASK_CREDITS",
    "EA_WORKLLM_MAX_CONTEXT_BYTES",
    "EA_WORKLLM_RECEIPT_ROOT",
    "EA_WORKLLM_CONTROL_STATE_FILE",
}


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_utc_timestamp(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == UTC.utcoffset(parsed)


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


def _load_json(
    path: Path,
    *,
    code: str,
    require_mode_600: bool = True,
    max_bytes: int = 2 * 1024 * 1024,
    require_redacted: bool = False,
) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"{code}_missing:{path}")
    if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise SystemExit(f"{code}_size_invalid:{path}")
    if require_mode_600 and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise SystemExit(f"{code}_mode_invalid:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SystemExit(f"{code}_invalid:{path}") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"{code}_invalid:{path}")
    if require_redacted:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        redacted, redactions = redact_workllm_text(serialized)
        if redacted != serialized or redactions:
            raise SystemExit(f"{code}_contains_sensitive_data:{path}")
    return dict(payload)


def _load_env_config(path: Path) -> WorkLLMConfig:
    if (
        not path.is_file()
        or path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
    ):
        raise SystemExit("workllm_canary_env_missing_or_unprotected")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in _KNOWN_ENV_KEYS:
            values[normalized_key] = value.strip().strip("\"'")

    def flag(name: str, default: str = "0") -> bool:
        raw = values.get(name, default)
        if raw not in {"0", "1"}:
            raise SystemExit(f"workllm_canary_env_flag_invalid:{name}")
        return raw == "1"

    def integer(name: str, default: int) -> int:
        try:
            return int(values.get(name, str(default)))
        except ValueError:
            raise SystemExit(
                f"workllm_canary_env_integer_invalid:{name}"
            ) from None

    def runtime_path(name: str, default: str) -> Path:
        candidate = Path(values.get(name, default))
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate.resolve(strict=False)

    return WorkLLMConfig(
        workspace_url=values.get("WORKLLM_BASE_URL", ""),
        account_verified=flag("EA_WORKLLM_ACCOUNT_VERIFIED"),
        provider_verified=flag("WORKLLM_PROVIDER_VERIFIED"),
        manual_lane_enabled=flag("EA_WORKLLM_MANUAL_LANE_ENABLED"),
        internal_nonsecret_enabled=flag(
            "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED"
        ),
        runtime_enabled=flag("WORKLLM_RUNTIME_ENABLED"),
        api_lane_enabled=flag("EA_WORKLLM_API_LANE_ENABLED"),
        kill_switch_engaged=flag("EA_WORKLLM_KILL_SWITCH", "1"),
        api_contract_verified=flag("EA_WORKLLM_API_CONTRACT_VERIFIED"),
        model_provenance_verified=flag(
            "EA_WORKLLM_MODEL_PROVENANCE_VERIFIED"
        ),
        usage_telemetry_verified=flag(
            "EA_WORKLLM_USAGE_TELEMETRY_VERIFIED"
        ),
        idempotency_verified=flag("EA_WORKLLM_IDEMPOTENCY_VERIFIED"),
        retention_controls_verified=flag(
            "EA_WORKLLM_RETENTION_CONTROLS_VERIFIED"
        ),
        webhook_controls_verified=flag(
            "EA_WORKLLM_WEBHOOK_CONTROLS_VERIFIED"
        ),
        monthly_credit_limit=integer(
            "EA_WORKLLM_MONTHLY_CREDIT_LIMIT",
            8000,
        ),
        soft_credit_limit=integer("EA_WORKLLM_SOFT_CREDIT_LIMIT", 6400),
        hard_credit_limit=integer("EA_WORKLLM_HARD_CREDIT_LIMIT", 7200),
        max_task_credits=integer("EA_WORKLLM_MAX_TASK_CREDITS", 250),
        max_context_bytes=integer(
            "EA_WORKLLM_MAX_CONTEXT_BYTES",
            64 * 1024,
        ),
        receipt_root=runtime_path(
            "EA_WORKLLM_RECEIPT_ROOT",
            ".runtime/workllm",
        ),
        control_state_file=runtime_path(
            "EA_WORKLLM_CONTROL_STATE_FILE",
            ".runtime/workllm/control_state.json",
        ),
    )


def _load_plan(
    path: Path,
    *,
    config: WorkLLMConfig,
) -> dict[str, object]:
    plan = _load_json(path, code="workllm_canary_plan")
    tasks = plan.get("tasks")
    result_root = Path(str(plan.get("result_root") or "")).resolve(
        strict=False
    )
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("provider") != "workllm"
        or plan.get("status") != "prepared_not_authorized"
        or plan.get("provider_interaction_observed") is not False
        or plan.get("credit_reservations_created") != 0
        or plan.get("submissions_authorized") != 0
        or plan.get("organization_memory_allowed") is not False
        or plan.get("provider_file_upload_allowed") is not False
        or plan.get("provider_web_search_allowed") is not False
        or plan.get("repository_access_allowed") is not False
        or not isinstance(tasks, list)
        or len(tasks) != 20
        or result_root != config.receipt_root.resolve(strict=False)
    ):
        raise SystemExit("workllm_canary_plan_contract_invalid")
    if config.workspace_url != f"https://{EXPECTED_SITE}":
        raise SystemExit("workllm_canary_workspace_mismatch")
    batch_id = str(plan.get("batch_id") or "").strip()
    case_ids: set[str] = set()
    task_ids: set[str] = set()
    request_hashes: set[str] = set()
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            raise SystemExit("workllm_canary_plan_contract_invalid")
        case_id = str(raw_task.get("case_id") or "").strip()
        task_id = str(raw_task.get("task_id") or "").strip()
        request_sha256 = str(
            raw_task.get("request_sha256") or ""
        ).strip().lower()
        task_root = result_root / task_id
        expected_paths = {
            "provider_output_capture_path": task_root
            / "provider_output.txt",
            "provider_output_surface_artifact_path": task_root
            / "provider_output_surface.png",
            "provider_surface_receipt_path": task_root
            / "provider_surface_receipt.json",
            "run_receipt_path": task_root / "run_receipt.json",
            "task_packet_path": path.parent
            / task_id
            / "task_packet.json",
        }
        if (
            not re.fullmatch(r"\d{2}", case_id)
            or task_id != f"{batch_id}-{case_id}"
            or _SHA256_RE.fullmatch(request_sha256) is None
            or case_id in case_ids
            or task_id in task_ids
            or request_sha256 in request_hashes
            or any(
                Path(str(raw_task.get(key) or "")).resolve(strict=False)
                != expected.resolve(strict=False)
                for key, expected in expected_paths.items()
            )
        ):
            raise SystemExit("workllm_canary_plan_contract_invalid")
        case_ids.add(case_id)
        task_ids.add(task_id)
        request_hashes.add(request_sha256)
    return plan


def _load_case(
    plan: dict[str, object],
    *,
    case_id: str,
    config: WorkLLMConfig,
) -> tuple[dict[str, object], WorkLLMTaskPacket]:
    tasks = plan["tasks"]
    matches = [
        dict(item)
        for item in tasks
        if isinstance(item, dict) and item.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise SystemExit(f"workllm_canary_case_not_found:{case_id}")
    task = matches[0]
    packet_path = Path(str(task.get("task_packet_path") or ""))
    if not packet_path.is_file() or packet_path.is_symlink():
        raise SystemExit(f"workllm_canary_task_packet_missing:{case_id}")
    if (
        stat.S_IMODE(packet_path.stat().st_mode) != 0o600
        or _sha256_file(packet_path)
        != str(task.get("task_packet_sha256") or "")
    ):
        raise SystemExit(
            f"workllm_canary_task_packet_evidence_invalid:{case_id}"
        )
    packet_payload = _load_json(
        packet_path,
        code=f"workllm_canary_task_packet:{case_id}",
    )
    packet = WorkLLMTaskPacket.from_dict(
        packet_payload,
        max_task_credits=config.max_task_credits,
        max_context_bytes=config.max_context_bytes,
    )
    if (
        packet.request_sha256 != task.get("request_sha256")
        or packet.task_id != task.get("task_id")
        or packet.data_classification != "public"
    ):
        raise SystemExit(
            f"workllm_canary_task_packet_binding_invalid:{case_id}"
        )
    return task, packet


def _load_account(path: Path) -> dict[str, object]:
    account = _load_json(
        path,
        code="workllm_account_verification",
        require_redacted=True,
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
        raise SystemExit("workllm_account_verification_invalid")
    return account


def _lane(config: WorkLLMConfig) -> GovernedWorkLLMManualLane:
    return GovernedWorkLLMManualLane(
        WorkLLMSidecar(config),
        governance_root=config.receipt_root / "governance",
    )


def authorize_case(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    account_path: Path,
    actor_ref: str,
    occurred_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    _load_account(account_path)
    task, packet = _load_case(plan, case_id=case_id, config=config)
    lane = _lane(config)
    staged = lane.stage_packet(
        packet,
        actor_ref=actor_ref,
        occurred_at=occurred_at,
    )
    authorization = lane.authorize(
        packet,
        actor_ref=actor_ref,
        authorized_at=occurred_at,
    )
    receipt: dict[str, object] = {
        "schema": "executive_assistant.workllm_canary_authorization.v1",
        "authorized_at": occurred_at,
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "max_credits": packet.max_credits,
        "task_packet_sha256": task["task_packet_sha256"],
        "staging_audit_event_sha256": staged["audit_event_sha256"],
        "authorization_audit_event_sha256": authorization[
            "audit_event_sha256"
        ],
        "credit_reservation_status": authorization["reservation"]["status"],
        "provider_interaction_observed": False,
        "canonical_promotion_authority": False,
    }
    authorization_path = (
        config.receipt_root
        / packet.task_id
        / "authorization_receipt.json"
    )
    _secure_write_json(authorization_path, receipt)
    return {**receipt, "authorization_receipt_path": str(authorization_path)}


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


def _validated_surface_receipt(
    *,
    path: Path,
    artifact_path: Path,
    account_ref_sha256: str,
    request_sha256: str,
) -> dict[str, object]:
    surface = _load_json(
        path,
        code="workllm_provider_surface_receipt",
        require_redacted=True,
    )
    _require_protected_file(
        artifact_path,
        code="workllm_provider_output_surface_artifact",
        max_bytes=20 * 1024 * 1024,
    )
    output_surface_sha256 = str(
        surface.get("provider_output_surface_sha256") or ""
    ).strip().lower()
    if (
        surface.get("schema") != SURFACE_RECEIPT_SCHEMA
        or surface.get("site") != EXPECTED_SITE
        or surface.get("work_type") != "research"
        or surface.get("account_ref_sha256") != account_ref_sha256
        or surface.get("request_sha256") != request_sha256
        or surface.get("prepared_packet_only") is not True
        or surface.get("output_captured") is not True
        or not _is_utc_timestamp(surface.get("observed_at"))
        or surface.get("irreversible_actions_attempted") != []
        or surface.get("stop_condition")
        != "comparison_ready_for_user_decision"
        or _SHA256_RE.fullmatch(output_surface_sha256) is None
        or _sha256_file(artifact_path) != output_surface_sha256
    ):
        raise SystemExit("workllm_provider_surface_receipt_invalid")
    return surface


def stage_browser_capture(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    account_path: Path,
    provider_output_text: str,
    provider_output_surface_artifact_path: Path,
    provider_credits_observed: str,
    observed_at: str,
    provider_credit_observation_scope: str = "direct_case_delta",
    shared_batch_case_ids: list[str] | None = None,
    provider_attempt_count: int = 1,
    aborted_attempt_credits_observed: str = "0",
    provider_quality_caveats: list[str] | None = None,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    account = _load_account(account_path)
    task, packet = _load_case(plan, case_id=case_id, config=config)
    run_receipt_path = Path(str(task["run_receipt_path"]))
    if run_receipt_path.exists():
        raise SystemExit("workllm_browser_capture_already_finalized")
    expected_artifact_path = Path(
        str(task["provider_output_surface_artifact_path"])
    ).resolve(strict=False)
    if (
        provider_output_surface_artifact_path.resolve(strict=False)
        != expected_artifact_path
    ):
        raise SystemExit("workllm_canary_capture_path_mismatch")
    _require_protected_file(
        provider_output_surface_artifact_path,
        code="workllm_provider_output_surface_artifact",
        max_bytes=20 * 1024 * 1024,
    )
    if not _is_utc_timestamp(observed_at):
        raise SystemExit("workllm_browser_observed_at_invalid")
    duplicate_keys: list[str] = []
    conflicting_duplicate_keys: list[str] = []

    def preserve_duplicate_evidence(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        restored: dict[str, object] = {}
        for key, value in pairs:
            if key in restored:
                duplicate_keys.append(key)
                if restored[key] != value:
                    conflicting_duplicate_keys.append(key)
            restored[key] = value
        return restored

    try:
        output = json.loads(
            provider_output_text,
            object_pairs_hook=preserve_duplicate_evidence,
        )
    except json.JSONDecodeError:
        raise SystemExit("workllm_provider_output_contract_invalid") from None
    if (
        not isinstance(output, dict)
        or conflicting_duplicate_keys
        or set(output) != _CANDIDATE_OUTPUT_FIELDS
        or not isinstance(output.get("summary"), str)
        or not isinstance(output.get("recommendation"), str)
        or output.get("authority_statement")
        != "Candidate only; no action taken."
        or any(
            not isinstance(output.get(field), list)
            or any(not isinstance(item, str) for item in output[field])
            for field in ("findings", "contradictions", "uncertainties")
        )
    ):
        raise SystemExit("workllm_provider_output_contract_invalid")
    serialized_output = json.dumps(
        output,
        ensure_ascii=False,
        sort_keys=True,
    )
    redacted_output, redactions = redact_workllm_text(serialized_output)
    if redacted_output != serialized_output or redactions:
        raise SystemExit("workllm_provider_output_contains_sensitive_data")
    normalized_credits = provider_credits_observed.strip()
    if _CREDIT_DECIMAL_RE.fullmatch(normalized_credits) is None:
        raise SystemExit("workllm_provider_credits_observed_invalid")
    try:
        observed_credits = Decimal(normalized_credits)
    except InvalidOperation:
        raise SystemExit(
            "workllm_provider_credits_observed_invalid"
        ) from None
    credits_accounted = int(
        observed_credits.to_integral_value(rounding=ROUND_CEILING)
    )
    if credits_accounted > packet.max_credits:
        raise SystemExit("workllm_provider_credits_exceed_reservation")
    normalized_aborted_credits = aborted_attempt_credits_observed.strip()
    if (
        provider_attempt_count < 1
        or _CREDIT_DECIMAL_RE.fullmatch(normalized_aborted_credits) is None
        or (
            provider_attempt_count == 1
            and Decimal(normalized_aborted_credits) != 0
        )
        or Decimal(normalized_aborted_credits) > observed_credits
    ):
        raise SystemExit("workllm_provider_attempt_evidence_invalid")
    normalized_batch_case_ids = sorted(
        {item.strip() for item in (shared_batch_case_ids or []) if item.strip()}
    )
    normalized_quality_caveats = sorted(
        {
            item.strip()
            for item in (provider_quality_caveats or [])
            if item.strip()
        }
    )
    if provider_credit_observation_scope == "direct_case_delta":
        if normalized_batch_case_ids:
            raise SystemExit("workllm_provider_credit_scope_invalid")
    elif provider_credit_observation_scope == "shared_batch_delta":
        if (
            len(normalized_batch_case_ids) < 2
            or case_id not in normalized_batch_case_ids
            or any(
                re.fullmatch(r"\d{2}", item) is None
                for item in normalized_batch_case_ids
            )
        ):
            raise SystemExit("workllm_provider_credit_scope_invalid")
    else:
        raise SystemExit("workllm_provider_credit_scope_invalid")

    provider_output_path = Path(
        str(task["provider_output_capture_path"])
    )
    provider_surface_receipt_path = Path(
        str(task["provider_surface_receipt_path"])
    )
    _secure_write_json(provider_output_path, dict(output))
    surface: dict[str, object] = {
        "schema": SURFACE_RECEIPT_SCHEMA,
        "site": EXPECTED_SITE,
        "work_type": "research",
        "account_ref_sha256": account["account_ref_sha256"],
        "request_sha256": packet.request_sha256,
        "prepared_packet_only": True,
        "output_captured": True,
        "observed_at": observed_at,
        "provider_output_surface_sha256": _sha256_file(
            provider_output_surface_artifact_path
        ),
        "irreversible_actions_attempted": [],
        "stop_condition": "comparison_ready_for_user_decision",
        "credit_accounting_policy": "ceiling_to_integer",
        "credits_accounted": credits_accounted,
        "provider_credits_observed": normalized_credits,
        "provider_attempt_count": provider_attempt_count,
        "aborted_attempt_credits_observed": normalized_aborted_credits,
        "provider_quality_caveats": normalized_quality_caveats,
        "provider_credit_observation_scope": (
            provider_credit_observation_scope
        ),
        "shared_batch_case_ids": normalized_batch_case_ids,
        "provider_output_normalizations": (
            ["identical_duplicate_key_collapsed"]
            if duplicate_keys
            else []
        ),
        "provider_output_duplicate_keys": sorted(set(duplicate_keys)),
    }
    _secure_write_json(provider_surface_receipt_path, surface)
    return {
        "schema": "executive_assistant.workllm_browser_capture_stage.v1",
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "provider_output_path": str(provider_output_path),
        "provider_surface_receipt_path": str(
            provider_surface_receipt_path
        ),
        "provider_output_surface_sha256": surface[
            "provider_output_surface_sha256"
        ],
        "provider_credits_observed": normalized_credits,
        "credits_accounted": credits_accounted,
        "canonical_promotion_authority": False,
    }


def capture_case(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    account_path: Path,
    actor_ref: str,
    provider_output_path: Path,
    provider_surface_receipt_path: Path,
    provider_output_surface_artifact_path: Path,
    observed_models: list[str],
    credits_consumed: int,
    provider_job_ref: str,
    captured_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    account = _load_account(account_path)
    task, packet = _load_case(plan, case_id=case_id, config=config)
    expected_paths = {
        "provider_output_capture_path": provider_output_path,
        "provider_surface_receipt_path": provider_surface_receipt_path,
        "provider_output_surface_artifact_path": (
            provider_output_surface_artifact_path
        ),
    }
    if any(
        Path(str(task.get(key) or "")).resolve(strict=False)
        != value.resolve(strict=False)
        for key, value in expected_paths.items()
    ):
        raise SystemExit("workllm_canary_capture_path_mismatch")
    _require_protected_file(
        provider_output_path,
        code="workllm_provider_output",
        max_bytes=2 * 1024 * 1024,
    )
    surface = _validated_surface_receipt(
        path=provider_surface_receipt_path,
        artifact_path=provider_output_surface_artifact_path,
        account_ref_sha256=str(account["account_ref_sha256"]),
        request_sha256=packet.request_sha256,
    )
    normalized_models = [
        item.strip() for item in observed_models if item.strip()
    ]
    if not normalized_models:
        raise SystemExit("workllm_observed_model_missing")
    lane = _lane(config)
    captured = lane.capture(
        packet,
        output_text=provider_output_path.read_text(encoding="utf-8"),
        actor_ref=actor_ref,
        observed_models=normalized_models,
        credits_consumed=credits_consumed,
        provider_job_ref=provider_job_ref,
        provider_surface_receipt_sha256=_sha256_file(
            provider_surface_receipt_path
        ),
        captured_at=captured_at,
    )
    receipt = dict(captured["receipt"])
    return {
        "schema": "executive_assistant.workllm_canary_capture.v1",
        "captured_at": captured_at,
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "run_receipt_path": str(task["run_receipt_path"]),
        "run_receipt_sha256": _sha256_file(
            Path(str(task["run_receipt_path"]))
        ),
        "provider_surface_receipt_sha256": _sha256_file(
            provider_surface_receipt_path
        ),
        "provider_output_surface_sha256": surface[
            "provider_output_surface_sha256"
        ],
        "credits_consumed": receipt["credits_consumed"],
        "observed_models": receipt["observed_models"],
        "audit_event_sha256": captured["audit_event_sha256"],
        "canonical_promotion_authority": False,
    }


def _validated_run_receipt(
    *,
    path: Path,
    packet: WorkLLMTaskPacket,
) -> dict[str, object]:
    run = _load_json(
        path,
        code="workllm_run_receipt",
        require_redacted=True,
    )
    authority = run.get("authority")
    local_artifacts = run.get("local_artifacts")
    observed_models = run.get("observed_models")
    credits_consumed = run.get("credits_consumed")
    if (
        run.get("schema") != WORKLLM_RUN_RECEIPT_SCHEMA
        or run.get("task_id") != packet.task_id
        or run.get("request_sha256") != packet.request_sha256
        or run.get("execution_mode") != "manual_browser"
        or run.get("provider_interaction_observed") is not True
        or run.get("evidence_kind") != "provider_observed"
        or run.get("model_provenance_status") != "observed"
        or not isinstance(observed_models, list)
        or not observed_models
        or any(not str(item or "").strip() for item in observed_models)
        or not isinstance(credits_consumed, int)
        or isinstance(credits_consumed, bool)
        or credits_consumed < 0
        or credits_consumed > packet.max_credits
        or not isinstance(authority, dict)
        or authority.get("candidate_only") is not True
        or authority.get("canonical_write_allowed") is not False
        or authority.get("repo_write_allowed") is not False
        or authority.get("external_send_allowed") is not False
        or authority.get("publish_allowed") is not False
        or authority.get("approval_allowed") is not False
        or not isinstance(local_artifacts, dict)
        or set(local_artifacts)
        != {"task_packet", "result", "run_receipt"}
    ):
        raise SystemExit("workllm_run_receipt_invalid")
    expected_run_root = path.parent.resolve(strict=False)
    packet_path = Path(
        str(local_artifacts["task_packet"])
    ).resolve(strict=False)
    result_path = Path(str(local_artifacts["result"])).resolve(strict=False)
    declared_run_path = Path(
        str(local_artifacts["run_receipt"])
    ).resolve(strict=False)
    if (
        expected_run_root.name != packet.task_id
        or packet_path != expected_run_root / "task_packet.json"
        or result_path != expected_run_root / "result.txt"
        or declared_run_path != path.resolve(strict=False)
    ):
        raise SystemExit("workllm_run_artifact_path_invalid")
    packet_payload = _load_json(
        packet_path,
        code="workllm_run_task_packet",
        require_redacted=True,
    )
    restored_packet = WorkLLMTaskPacket.from_dict(packet_payload)
    _require_protected_file(
        result_path,
        code="workllm_run_result",
        max_bytes=2 * 1024 * 1024,
    )
    try:
        result_text = result_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise SystemExit("workllm_run_result_invalid") from None
    redacted_result, result_redactions = redact_workllm_text(result_text)
    output_sha256 = str(run.get("output_sha256") or "").strip().lower()
    if (
        restored_packet != packet
        or redacted_result != result_text
        or result_redactions
        or _SHA256_RE.fullmatch(output_sha256) is None
        or hashlib.sha256(result_text.encode("utf-8")).hexdigest()
        != output_sha256
    ):
        raise SystemExit("workllm_run_artifact_binding_invalid")
    return run


def review_case(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    actor_ref: str,
    decision: str,
    schema_status: str,
    safety_status: str,
    reviewed_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    task, packet = _load_case(plan, case_id=case_id, config=config)
    run_path = Path(str(task["run_receipt_path"]))
    run = _validated_run_receipt(path=run_path, packet=packet)
    reviewed = _lane(config).review(
        run,
        actor_ref=actor_ref,
        decision=decision,
        schema_valid=schema_status == "passed",
        safety_valid=safety_status == "passed",
        reviewed_at=reviewed_at,
    )
    receipt = dict(reviewed["receipt"])
    return {
        "schema": "executive_assistant.workllm_canary_review.v1",
        "reviewed_at": reviewed_at,
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "decision": decision,
        "schema_validation_status": receipt["schema_validation_status"],
        "safety_validation_status": receipt["safety_validation_status"],
        "candidate_accepted": receipt["candidate_accepted"],
        "run_receipt_path": str(reviewed["receipt_path"]),
        "run_receipt_sha256": _sha256_file(
            Path(str(reviewed["receipt_path"]))
        ),
        "audit_event_sha256": reviewed["audit_event_sha256"],
        "canonical_promotion_authority": False,
    }


def rebind_surface_evidence(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    account_path: Path,
    reason: str,
    rebound_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    account = _load_account(account_path)
    task, packet = _load_case(plan, case_id=case_id, config=config)
    run_path = Path(str(task["run_receipt_path"]))
    surface_path = Path(str(task["provider_surface_receipt_path"]))
    output_path = Path(str(task["provider_output_capture_path"]))
    artifact_path = Path(
        str(task["provider_output_surface_artifact_path"])
    )
    run = _validated_run_receipt(path=run_path, packet=packet)
    _validated_surface_receipt(
        path=surface_path,
        artifact_path=artifact_path,
        account_ref_sha256=str(account["account_ref_sha256"]),
        request_sha256=packet.request_sha256,
    )
    _require_protected_file(
        output_path,
        code="workllm_provider_output",
        max_bytes=2 * 1024 * 1024,
    )
    result_path = Path(str(run["local_artifacts"]["result"]))
    if (
        output_path.read_bytes() != result_path.read_bytes()
        or not reason.strip()
        or not _is_utc_timestamp(rebound_at)
    ):
        raise SystemExit("workllm_surface_evidence_rebind_invalid")
    prior_sha256 = str(
        run.get("provider_surface_receipt_sha256") or ""
    ).strip()
    current_sha256 = _sha256_file(surface_path)
    if prior_sha256 == current_sha256:
        raise SystemExit("workllm_surface_evidence_rebind_not_required")
    run["provider_surface_receipt_sha256"] = current_sha256
    run["surface_evidence_rebinding"] = {
        "canonical_promotion_authority": False,
        "current_provider_surface_receipt_sha256": current_sha256,
        "prior_provider_surface_receipt_sha256": prior_sha256,
        "reason": reason.strip(),
        "rebound_at": rebound_at,
    }
    run["human_review"] = {
        "decision": "",
        "reviewed_at": "",
        "reviewer_ref_sha256": "",
        "status": "pending",
    }
    run["candidate_accepted"] = False
    run["schema_validation_status"] = "pending"
    run["safety_validation_status"] = "pending"
    _secure_write_json(run_path, run)
    return {
        "schema": "executive_assistant.workllm_surface_rebind.v1",
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "prior_provider_surface_receipt_sha256": prior_sha256,
        "current_provider_surface_receipt_sha256": current_sha256,
        "run_receipt_path": str(run_path),
        "run_receipt_sha256": _sha256_file(run_path),
        "review_required": True,
        "canonical_promotion_authority": False,
    }


def cancel_case(
    *,
    plan_path: Path,
    case_id: str,
    env_path: Path,
    actor_ref: str,
    reason: str,
    cancelled_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    _, packet = _load_case(plan, case_id=case_id, config=config)
    cancelled = _lane(config).cancel(
        packet,
        actor_ref=actor_ref,
        reason=reason,
        cancelled_at=cancelled_at,
    )
    cancellation = dict(cancelled["cancellation"])
    return {
        "schema": "executive_assistant.workllm_canary_cancellation.v1",
        "cancelled_at": cancelled_at,
        "case_id": case_id,
        "task_id": packet.task_id,
        "request_sha256": packet.request_sha256,
        "credit_reservation_status": cancellation["status"],
        "audit_event_sha256": cancelled["audit_event_sha256"],
        "canonical_promotion_authority": False,
    }


def engage_rollback(
    *,
    env_path: Path,
    actor_ref: str,
    reason: str,
    engaged_at: str,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    rollback = _lane(config).engage_rollback(
        actor_ref=actor_ref,
        reason=reason,
        engaged_at=engaged_at,
    )
    receipt = dict(rollback["receipt"])
    return {
        "schema": receipt["schema"],
        "engaged_at": receipt["engaged_at"],
        "kill_switch_effective": receipt["kill_switch_effective"],
        "receipt_path": rollback["receipt_path"],
        "control_state_path": rollback["control_state_path"],
        "audit_event_sha256": rollback["audit_event_sha256"],
        "canonical_promotion_authority": False,
    }


def finalize_canary(
    *,
    plan_path: Path,
    env_path: Path,
    account_path: Path,
    manifest_path: Path,
    output_path: Path,
) -> dict[str, object]:
    config = _load_env_config(env_path)
    plan = _load_plan(plan_path, config=config)
    account = _load_account(account_path)
    governance_root = config.receipt_root / "governance"
    runs: list[dict[str, str]] = []
    for task in plan["tasks"]:
        if not isinstance(task, dict):
            raise SystemExit("workllm_canary_plan_contract_invalid")
        case_id = str(task.get("case_id") or "")
        _, packet = _load_case(plan, case_id=case_id, config=config)
        run_path = Path(str(task.get("run_receipt_path") or ""))
        surface_path = Path(
            str(task.get("provider_surface_receipt_path") or "")
        )
        output_surface_path = Path(
            str(
                task.get("provider_output_surface_artifact_path")
                or ""
            )
        )
        run = _validated_run_receipt(path=run_path, packet=packet)
        if (
            run.get("schema_validation_status") != "passed"
            or run.get("safety_validation_status") != "passed"
            or not isinstance(run.get("human_review"), dict)
            or run["human_review"].get("status") != "completed"
            or run["human_review"].get("decision")
            != "accepted_candidate"
            or run.get("candidate_accepted") is not True
        ):
            raise SystemExit(
                f"workllm_canary_run_not_reviewed:{case_id}"
            )
        _validated_surface_receipt(
            path=surface_path,
            artifact_path=output_surface_path,
            account_ref_sha256=str(account["account_ref_sha256"]),
            request_sha256=packet.request_sha256,
        )
        runs.append(
            {
                "run_receipt": str(run_path),
                "provider_surface_receipt": str(surface_path),
                "provider_output_surface_artifact": str(
                    output_surface_path
                ),
            }
        )
    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "mode": "manual_browser",
        "account_verification_receipt": str(account_path),
        "governance": {
            "audit_ledger": str(governance_root / "audit.jsonl"),
            "credit_ledger": str(
                governance_root / "credit_ledger.json"
            ),
        },
        "runs": runs,
    }
    _secure_write_json(manifest_path, manifest)
    return build_manual_canary_receipt(
        manifest_path=manifest_path,
        output_path=output_path,
    )


def _add_common_case_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--actor-ref", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operate one prepared WorkLLM manual-canary case through local "
            "authorization, capture, review, or final evaluation."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    authorize_parser = subparsers.add_parser("authorize")
    _add_common_case_arguments(authorize_parser)
    authorize_parser.add_argument(
        "--account-receipt",
        default=str(ACCOUNT_VERIFICATION_RECEIPT),
    )
    authorize_parser.add_argument("--occurred-at", default=_utc_now())

    capture_parser = subparsers.add_parser("capture")
    _add_common_case_arguments(capture_parser)
    capture_parser.add_argument(
        "--account-receipt",
        default=str(ACCOUNT_VERIFICATION_RECEIPT),
    )
    capture_parser.add_argument("--provider-output", required=True)
    capture_parser.add_argument(
        "--provider-surface-receipt",
        required=True,
    )
    capture_parser.add_argument(
        "--provider-output-surface-artifact",
        required=True,
    )
    capture_parser.add_argument(
        "--observed-model",
        action="append",
        default=[],
    )
    capture_parser.add_argument("--credits-consumed", type=int, required=True)
    capture_parser.add_argument("--provider-job-ref", default="")
    capture_parser.add_argument("--captured-at", default=_utc_now())

    stage_browser_parser = subparsers.add_parser("stage-browser")
    _add_common_case_arguments(stage_browser_parser)
    stage_browser_parser.add_argument(
        "--account-receipt",
        default=str(ACCOUNT_VERIFICATION_RECEIPT),
    )
    stage_browser_parser.add_argument(
        "--provider-output-surface-artifact",
        required=True,
    )
    stage_browser_parser.add_argument(
        "--provider-credits-observed",
        required=True,
    )
    stage_browser_parser.add_argument(
        "--provider-credit-observation-scope",
        choices=("direct_case_delta", "shared_batch_delta"),
        default="direct_case_delta",
    )
    stage_browser_parser.add_argument(
        "--shared-batch-case-id",
        action="append",
        default=[],
    )
    stage_browser_parser.add_argument(
        "--provider-attempt-count",
        type=int,
        default=1,
    )
    stage_browser_parser.add_argument(
        "--aborted-attempt-credits-observed",
        default="0",
    )
    stage_browser_parser.add_argument(
        "--provider-quality-caveat",
        action="append",
        default=[],
    )
    stage_browser_parser.add_argument("--observed-at", default=_utc_now())

    review_parser = subparsers.add_parser("review")
    _add_common_case_arguments(review_parser)
    review_parser.add_argument(
        "--decision",
        choices=("accepted_candidate", "needs_changes", "rejected"),
        required=True,
    )
    review_parser.add_argument(
        "--schema-status",
        choices=("passed", "failed"),
        required=True,
    )
    review_parser.add_argument(
        "--safety-status",
        choices=("passed", "failed"),
        required=True,
    )
    review_parser.add_argument("--reviewed-at", default=_utc_now())

    rebind_parser = subparsers.add_parser("rebind-surface")
    _add_common_case_arguments(rebind_parser)
    rebind_parser.add_argument(
        "--account-receipt",
        default=str(ACCOUNT_VERIFICATION_RECEIPT),
    )
    rebind_parser.add_argument("--reason", required=True)
    rebind_parser.add_argument("--rebound-at", default=_utc_now())

    cancel_parser = subparsers.add_parser("cancel")
    _add_common_case_arguments(cancel_parser)
    cancel_parser.add_argument("--reason", required=True)
    cancel_parser.add_argument("--cancelled-at", default=_utc_now())

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--env", default=str(ROOT / ".env"))
    rollback_parser.add_argument("--actor-ref", required=True)
    rollback_parser.add_argument("--reason", required=True)
    rollback_parser.add_argument("--engaged-at", default=_utc_now())

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    finalize_parser.add_argument("--env", default=str(ROOT / ".env"))
    finalize_parser.add_argument(
        "--account-receipt",
        default=str(ACCOUNT_VERIFICATION_RECEIPT),
    )
    finalize_parser.add_argument(
        "--manifest",
        default=(
            str(DEFAULT_PLAN.parent / "workllm_canary_manifest.json")
        ),
    )
    finalize_parser.add_argument(
        "--output",
        default=str(MANUAL_CANARY_RECEIPT),
    )
    args = parser.parse_args()
    if args.command == "authorize":
        result = authorize_case(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            account_path=Path(args.account_receipt),
            actor_ref=args.actor_ref,
            occurred_at=args.occurred_at,
        )
    elif args.command == "stage-browser":
        provider_output_text = sys.stdin.read(2 * 1024 * 1024 + 1)
        if len(provider_output_text.encode("utf-8")) > 2 * 1024 * 1024:
            raise SystemExit("workllm_provider_output_size_invalid")
        result = stage_browser_capture(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            account_path=Path(args.account_receipt),
            provider_output_text=provider_output_text,
            provider_output_surface_artifact_path=Path(
                args.provider_output_surface_artifact
            ),
            provider_credits_observed=args.provider_credits_observed,
            observed_at=args.observed_at,
            provider_credit_observation_scope=(
                args.provider_credit_observation_scope
            ),
            shared_batch_case_ids=list(args.shared_batch_case_id),
            provider_attempt_count=args.provider_attempt_count,
            aborted_attempt_credits_observed=(
                args.aborted_attempt_credits_observed
            ),
            provider_quality_caveats=list(args.provider_quality_caveat),
        )
    elif args.command == "capture":
        result = capture_case(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            account_path=Path(args.account_receipt),
            actor_ref=args.actor_ref,
            provider_output_path=Path(args.provider_output),
            provider_surface_receipt_path=Path(
                args.provider_surface_receipt
            ),
            provider_output_surface_artifact_path=Path(
                args.provider_output_surface_artifact
            ),
            observed_models=list(args.observed_model),
            credits_consumed=args.credits_consumed,
            provider_job_ref=args.provider_job_ref,
            captured_at=args.captured_at,
        )
    elif args.command == "review":
        result = review_case(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            actor_ref=args.actor_ref,
            decision=args.decision,
            schema_status=args.schema_status,
            safety_status=args.safety_status,
            reviewed_at=args.reviewed_at,
        )
    elif args.command == "rebind-surface":
        result = rebind_surface_evidence(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            account_path=Path(args.account_receipt),
            reason=args.reason,
            rebound_at=args.rebound_at,
        )
    elif args.command == "cancel":
        result = cancel_case(
            plan_path=Path(args.plan),
            case_id=args.case_id,
            env_path=Path(args.env),
            actor_ref=args.actor_ref,
            reason=args.reason,
            cancelled_at=args.cancelled_at,
        )
    elif args.command == "rollback":
        result = engage_rollback(
            env_path=Path(args.env),
            actor_ref=args.actor_ref,
            reason=args.reason,
            engaged_at=args.engaged_at,
        )
    else:
        result = finalize_canary(
            plan_path=Path(args.plan),
            env_path=Path(args.env),
            account_path=Path(args.account_receipt),
            manifest_path=Path(args.manifest),
            output_path=Path(args.output),
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == "finalize":
        return 0 if result["promotion_eligible_candidate"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
