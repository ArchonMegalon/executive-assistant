"""Fail-closed contracts for the non-canonical WorkLLM fleet sidecar.

This module intentionally contains no HTTP client and no browser automation.
It prepares minimized task packets, enforces promotion and credit gates, and
materializes local receipts around results captured by a governed operator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

WORKLLM_TASK_PACKET_SCHEMA = "executive_assistant.workllm_task_packet.v1"
WORKLLM_RUN_RECEIPT_SCHEMA = "executive_assistant.workllm_run_receipt.v1"

ALLOWED_LANES = frozenset(
    {
        "research_synthesis",
        "multi_model_compare",
        "document_qna",
        "spec_contradiction_audit",
        "release_evidence_summary",
        "sop_draft",
    }
)
ALLOWED_DATA_CLASSIFICATIONS = frozenset({"public", "internal_nonsecret"})
ALLOWED_EXECUTION_MODES = frozenset({"manual_browser", "api"})
ALLOWED_REVIEW_DECISIONS = frozenset({"accepted_candidate", "rejected", "needs_changes"})

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FORBIDDEN_SOURCE_MARKERS = (
    "/.env",
    ".env.",
    "secrets/",
    "secret/",
    "credentials/",
    "private_person_profiles/",
    "raw_gmail/",
    "raw_calendar/",
    "people_memory/",
)
_REDACTION_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
            r"(?:\.[A-Za-z0-9_-]{8,})?\b"
        ),
        "[REDACTED_JWT]",
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|"
            r"refresh[_-]?token|client[_-]?secret|secret)\b"
            r"(\s*[:=]\s*)"
            r"(?!\[REDACTED_)([^\s,;\"']{4,}|[\"'][^\"'\r\n]{4,}[\"'])"
        ),
        r"\1\2[REDACTED_SECRET]",
    ),
    (
        "email_address",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[REDACTED_EMAIL]",
    ),
    (
        "url_secret",
        re.compile(
            r"(?i)([?&](?:token|key|secret|password|signature)=)"
            r"[^&#\s]+"
        ),
        r"\1[REDACTED_SECRET]",
    ),
)
_REDACTION_CODES = frozenset(code for code, _, _ in _REDACTION_RULES)


class WorkLLMPolicyError(ValueError):
    """Raised when a packet or route would cross the WorkLLM boundary."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validated_utc_timestamp(value: object, *, code: str) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("Z"):
        raise WorkLLMPolicyError(code)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise WorkLLMPolicyError(code) from None
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise WorkLLMPolicyError(code)
    return raw


def _flag(name: str, default: str = "0") -> bool:
    value = str(os.environ.get(name, default)).strip()
    if value not in {"0", "1"}:
        raise WorkLLMPolicyError(f"workllm_configuration_invalid:{name}")
    return value == "1"


def _integer(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        raise WorkLLMPolicyError(f"workllm_configuration_invalid:{name}") from None


def _normalize_workspace_url(value: object) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise WorkLLMPolicyError("workllm_workspace_url_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkLLMPolicyError("workllm_workspace_url_unsafe")
    if parsed.path not in {"", "/"}:
        raise WorkLLMPolicyError("workllm_workspace_url_unsafe")
    return f"https://{parsed.hostname.lower()}"


def _workspace_hash(workspace_url: str) -> str:
    normalized = _normalize_workspace_url(workspace_url)
    return _sha256_text(normalized) if normalized else ""


def redact_workllm_text(value: object) -> tuple[str, tuple[str, ...]]:
    """Redact high-confidence secret and identity patterns from prepared text."""

    redacted = str(value or "")
    applied: list[str] = []
    for code, pattern, replacement in _REDACTION_RULES:
        updated, count = pattern.subn(replacement, redacted)
        if count:
            applied.append(code)
            redacted = updated
    return redacted, tuple(applied)


def _validate_source_ref(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    lowered = f"/{normalized.lower().lstrip('/')}"
    if (
        not normalized
        or normalized.startswith("/")
        or "://" in normalized
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or any(marker in lowered for marker in _FORBIDDEN_SOURCE_MARKERS)
    ):
        raise WorkLLMPolicyError("workllm_source_ref_forbidden")
    return normalized


def _validate_sha256(value: object, *, code: str) -> str:
    normalized = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise WorkLLMPolicyError(code)
    return normalized


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("workllm_secure_write_failed")
        offset += written


def _secure_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.exists() and (
        path.is_symlink()
        or not path.is_file()
        or (path.stat().st_mode & 0o777) != 0o600
    ):
        raise WorkLLMPolicyError("workllm_receipt_path_unsafe")
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
        encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)


def _secure_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.exists() and (
        path.is_symlink()
        or not path.is_file()
        or (path.stat().st_mode & 0o777) != 0o600
    ):
        raise WorkLLMPolicyError("workllm_receipt_path_unsafe")
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
        _write_all(descriptor, value.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)


@dataclass(frozen=True)
class WorkLLMConfig:
    workspace_url: str = ""
    account_verified: bool = False
    provider_verified: bool = False
    manual_lane_enabled: bool = False
    internal_nonsecret_enabled: bool = False
    runtime_enabled: bool = False
    api_lane_enabled: bool = False
    kill_switch_engaged: bool = True
    api_contract_verified: bool = False
    model_provenance_verified: bool = False
    usage_telemetry_verified: bool = False
    idempotency_verified: bool = False
    retention_controls_verified: bool = False
    webhook_controls_verified: bool = False
    monthly_credit_limit: int = 8000
    soft_credit_limit: int = 6400
    hard_credit_limit: int = 7200
    max_task_credits: int = 250
    max_context_bytes: int = 64 * 1024
    receipt_root: Path = Path(".runtime/workllm")
    control_state_file: Path | None = None

    def __post_init__(self) -> None:
        normalized_url = _normalize_workspace_url(self.workspace_url)
        object.__setattr__(self, "workspace_url", normalized_url)
        if (
            self.monthly_credit_limit <= 0
            or self.soft_credit_limit <= 0
            or self.hard_credit_limit <= 0
            or self.max_task_credits <= 0
            or self.max_context_bytes <= 0
            or self.soft_credit_limit > self.hard_credit_limit
            or self.hard_credit_limit > self.monthly_credit_limit
            or self.max_task_credits > self.hard_credit_limit
        ):
            raise WorkLLMPolicyError("workllm_credit_configuration_invalid")

    @classmethod
    def from_environment(cls) -> WorkLLMConfig:
        return cls(
            workspace_url=str(os.environ.get("WORKLLM_BASE_URL") or "").strip(),
            account_verified=_flag("EA_WORKLLM_ACCOUNT_VERIFIED"),
            provider_verified=_flag("WORKLLM_PROVIDER_VERIFIED"),
            manual_lane_enabled=_flag("EA_WORKLLM_MANUAL_LANE_ENABLED"),
            internal_nonsecret_enabled=_flag(
                "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED"
            ),
            runtime_enabled=_flag("WORKLLM_RUNTIME_ENABLED"),
            api_lane_enabled=_flag("EA_WORKLLM_API_LANE_ENABLED"),
            kill_switch_engaged=_flag("EA_WORKLLM_KILL_SWITCH", "1"),
            api_contract_verified=_flag("EA_WORKLLM_API_CONTRACT_VERIFIED"),
            model_provenance_verified=_flag(
                "EA_WORKLLM_MODEL_PROVENANCE_VERIFIED"
            ),
            usage_telemetry_verified=_flag(
                "EA_WORKLLM_USAGE_TELEMETRY_VERIFIED"
            ),
            idempotency_verified=_flag("EA_WORKLLM_IDEMPOTENCY_VERIFIED"),
            retention_controls_verified=_flag(
                "EA_WORKLLM_RETENTION_CONTROLS_VERIFIED"
            ),
            webhook_controls_verified=_flag(
                "EA_WORKLLM_WEBHOOK_CONTROLS_VERIFIED"
            ),
            monthly_credit_limit=_integer("EA_WORKLLM_MONTHLY_CREDIT_LIMIT", 8000),
            soft_credit_limit=_integer("EA_WORKLLM_SOFT_CREDIT_LIMIT", 6400),
            hard_credit_limit=_integer("EA_WORKLLM_HARD_CREDIT_LIMIT", 7200),
            max_task_credits=_integer("EA_WORKLLM_MAX_TASK_CREDITS", 250),
            max_context_bytes=_integer(
                "EA_WORKLLM_MAX_CONTEXT_BYTES", 64 * 1024
            ),
            receipt_root=Path(
                str(
                    os.environ.get("EA_WORKLLM_RECEIPT_ROOT")
                    or ".runtime/workllm"
                )
            ).expanduser(),
            control_state_file=Path(
                str(
                    os.environ.get("EA_WORKLLM_CONTROL_STATE_FILE")
                    or ".runtime/workllm/control_state.json"
                )
            ).expanduser(),
        )

    def kill_switch_active(self) -> bool:
        if self.kill_switch_engaged:
            return True
        path = self.control_state_file
        if path is None:
            return False
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        if not isinstance(payload, Mapping):
            return True
        if payload.get("schema") != "executive_assistant.workllm_control_state.v1":
            return True
        return True

    @property
    def api_proof_complete(self) -> bool:
        return all(
            (
                self.provider_verified,
                self.runtime_enabled,
                self.api_lane_enabled,
                self.api_contract_verified,
                self.model_provenance_verified,
                self.usage_telemetry_verified,
                self.idempotency_verified,
                self.retention_controls_verified,
                self.webhook_controls_verified,
            )
        )

    def public_posture(self) -> dict[str, object]:
        return {
            "workspace_ref_sha256": _workspace_hash(self.workspace_url),
            "account_verified": self.account_verified,
            "provider_verified": self.provider_verified,
            "manual_lane_enabled": self.manual_lane_enabled,
            "internal_nonsecret_enabled": self.internal_nonsecret_enabled,
            "runtime_enabled": self.runtime_enabled,
            "api_lane_enabled": self.api_lane_enabled,
            "kill_switch_engaged": self.kill_switch_active(),
            "api_proof_complete": self.api_proof_complete,
            "monthly_credit_limit": self.monthly_credit_limit,
            "soft_credit_limit": self.soft_credit_limit,
            "hard_credit_limit": self.hard_credit_limit,
            "max_task_credits": self.max_task_credits,
        }


@dataclass(frozen=True)
class WorkLLMSourceReference:
    ref: str
    sha256: str

    @classmethod
    def build(cls, *, ref: object, sha256: object) -> WorkLLMSourceReference:
        return cls(
            ref=_validate_source_ref(ref),
            sha256=_validate_sha256(
                sha256,
                code="workllm_source_sha256_invalid",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "sha256": self.sha256}


@dataclass(frozen=True)
class WorkLLMTaskPacket:
    task_id: str
    correlation_id: str
    created_at: str
    lane: str
    data_classification: str
    prepared_context: str
    redactions: tuple[str, ...]
    source_manifest: tuple[WorkLLMSourceReference, ...]
    prompt_template_id: str
    prompt_template_version: str
    prompt_sha256: str
    output_schema: Mapping[str, object]
    max_credits: int
    request_sha256: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        *,
        max_task_credits: int = 250,
        max_context_bytes: int = 64 * 1024,
    ) -> WorkLLMTaskPacket:
        """Restore a persisted packet only when its full contract is canonical."""

        if (
            payload.get("schema") != WORKLLM_TASK_PACKET_SCHEMA
            or payload.get("provider") != "workllm"
        ):
            raise WorkLLMPolicyError("workllm_task_packet_schema_mismatch")
        prompt_template = payload.get("prompt_template")
        budget = payload.get("budget")
        sources_payload = payload.get("source_manifest")
        redactions_payload = payload.get("redactions")
        output_schema = payload.get("output_schema")
        if (
            not isinstance(prompt_template, Mapping)
            or not isinstance(budget, Mapping)
            or not isinstance(sources_payload, list)
            or not sources_payload
            or not isinstance(redactions_payload, list)
            or not isinstance(output_schema, Mapping)
        ):
            raise WorkLLMPolicyError("workllm_task_packet_invalid")
        task_id = str(payload.get("task_id") or "").strip()
        correlation_id = str(payload.get("correlation_id") or "").strip()
        lane = str(payload.get("lane") or "").strip().lower()
        data_classification = str(
            payload.get("data_classification") or ""
        ).strip().lower()
        prepared_context = str(payload.get("prepared_context") or "")
        created_at = _validated_utc_timestamp(
            payload.get("created_at"),
            code="workllm_task_packet_created_at_invalid",
        )
        prompt_template_id = str(prompt_template.get("id") or "").strip()
        prompt_template_version = str(
            prompt_template.get("version") or ""
        ).strip()
        prompt_sha256 = _validate_sha256(
            prompt_template.get("sha256"),
            code="workllm_prompt_sha256_invalid",
        )
        request_sha256 = _validate_sha256(
            payload.get("request_sha256"),
            code="workllm_request_sha256_invalid",
        )
        max_credits = budget.get("max_credits")
        if (
            _SAFE_TASK_ID_RE.fullmatch(task_id) is None
            or _SAFE_TASK_ID_RE.fullmatch(correlation_id) is None
            or lane not in ALLOWED_LANES
            or data_classification not in ALLOWED_DATA_CLASSIFICATIONS
            or not created_at
            or not prepared_context.strip()
            or len(prepared_context.encode("utf-8")) > max_context_bytes
            or not prompt_template_id
            or not prompt_template_version
            or output_schema.get("type") != "object"
            or not isinstance(max_credits, int)
            or isinstance(max_credits, bool)
            or max_credits <= 0
            or max_credits > max_task_credits
        ):
            raise WorkLLMPolicyError("workllm_task_packet_invalid")
        if any(not isinstance(item, Mapping) for item in sources_payload):
            raise WorkLLMPolicyError("workllm_task_packet_invalid")
        if (
            any(not isinstance(item, str) for item in redactions_payload)
            or len(set(redactions_payload)) != len(redactions_payload)
            or any(item not in _REDACTION_CODES for item in redactions_payload)
        ):
            raise WorkLLMPolicyError("workllm_task_packet_invalid")
        redacted_context, restored_redactions = redact_workllm_text(
            prepared_context
        )
        if redacted_context != prepared_context or restored_redactions:
            raise WorkLLMPolicyError(
                "workllm_task_packet_contains_sensitive_data"
            )
        packet = cls(
            task_id=task_id,
            correlation_id=correlation_id,
            created_at=created_at,
            lane=lane,
            data_classification=data_classification,
            prepared_context=prepared_context,
            redactions=tuple(redactions_payload),
            source_manifest=tuple(
                WorkLLMSourceReference.build(
                    ref=item.get("ref"),
                    sha256=item.get("sha256"),
                )
                for item in sources_payload
            ),
            prompt_template_id=prompt_template_id,
            prompt_template_version=prompt_template_version,
            prompt_sha256=prompt_sha256,
            output_schema=dict(output_schema),
            max_credits=max_credits,
            request_sha256=request_sha256,
        )
        packet.verify_digest()
        if packet.to_dict() != dict(payload):
            raise WorkLLMPolicyError("workllm_task_packet_noncanonical")
        return packet

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORKLLM_TASK_PACKET_SCHEMA,
            "provider": "workllm",
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "lane": self.lane,
            "data_classification": self.data_classification,
            "prepared_context": self.prepared_context,
            "redactions": list(self.redactions),
            "source_manifest": [item.to_dict() for item in self.source_manifest],
            "prompt_template": {
                "id": self.prompt_template_id,
                "version": self.prompt_template_version,
                "sha256": self.prompt_sha256,
            },
            "output_schema": dict(self.output_schema),
            "budget": {
                "max_credits": self.max_credits,
                "auto_top_up": False,
            },
            "authority": {
                "candidate_only": True,
                "canonical_write_allowed": False,
                "repo_write_allowed": False,
                "external_send_allowed": False,
                "publish_allowed": False,
                "approval_allowed": False,
            },
            "retention": {
                "organization_memory_write_allowed": False,
                "provider_retention_requested": "none",
                "local_receipt_required": True,
            },
            "request_sha256": self.request_sha256,
        }

    def verify_digest(self) -> None:
        payload = self.to_dict()
        supplied = str(payload.pop("request_sha256"))
        expected = _sha256_text(_canonical_json(payload))
        if supplied != expected:
            raise WorkLLMPolicyError("workllm_task_packet_digest_mismatch")


class WorkLLMSidecar:
    """Prepare and receipt bounded WorkLLM work without executing the provider."""

    def __init__(self, config: WorkLLMConfig | None = None) -> None:
        self.config = config or WorkLLMConfig.from_environment()

    def prepare_task_packet(
        self,
        *,
        lane: str,
        data_classification: str,
        prepared_context: str,
        source_manifest: Sequence[Mapping[str, object]],
        prompt_template_id: str,
        prompt_template_version: str,
        prompt_text: str,
        output_schema: Mapping[str, object],
        max_credits: int,
        task_id: str | None = None,
        correlation_id: str | None = None,
        created_at: str | None = None,
    ) -> WorkLLMTaskPacket:
        normalized_lane = str(lane or "").strip().lower()
        if normalized_lane not in ALLOWED_LANES:
            raise WorkLLMPolicyError("workllm_lane_forbidden")
        normalized_classification = str(data_classification or "").strip().lower()
        if normalized_classification not in ALLOWED_DATA_CLASSIFICATIONS:
            raise WorkLLMPolicyError("workllm_data_classification_forbidden")
        normalized_task_id = str(task_id or uuid.uuid4()).strip()
        normalized_correlation_id = str(
            correlation_id or normalized_task_id
        ).strip()
        if (
            _SAFE_TASK_ID_RE.fullmatch(normalized_task_id) is None
            or _SAFE_TASK_ID_RE.fullmatch(normalized_correlation_id) is None
        ):
            raise WorkLLMPolicyError("workllm_task_identifier_invalid")
        if not prompt_template_id.strip() or not prompt_template_version.strip():
            raise WorkLLMPolicyError("workllm_prompt_template_identity_missing")
        if not str(prompt_text or "").strip():
            raise WorkLLMPolicyError("workllm_prompt_template_missing")
        if not isinstance(output_schema, Mapping) or output_schema.get("type") != "object":
            raise WorkLLMPolicyError("workllm_output_schema_invalid")
        if max_credits <= 0 or max_credits > self.config.max_task_credits:
            raise WorkLLMPolicyError("workllm_task_credit_limit_invalid")
        redacted_context, redactions = redact_workllm_text(prepared_context)
        if not redacted_context.strip():
            raise WorkLLMPolicyError("workllm_prepared_context_missing")
        if len(redacted_context.encode("utf-8")) > self.config.max_context_bytes:
            raise WorkLLMPolicyError("workllm_prepared_context_too_large")
        sources = tuple(
            WorkLLMSourceReference.build(
                ref=item.get("ref"),
                sha256=item.get("sha256"),
            )
            for item in source_manifest
        )
        if not sources:
            raise WorkLLMPolicyError("workllm_source_manifest_missing")
        provisional = WorkLLMTaskPacket(
            task_id=normalized_task_id,
            correlation_id=normalized_correlation_id,
            created_at=_validated_utc_timestamp(
                created_at or _utc_now(),
                code="workllm_task_packet_created_at_invalid",
            ),
            lane=normalized_lane,
            data_classification=normalized_classification,
            prepared_context=redacted_context,
            redactions=redactions,
            source_manifest=sources,
            prompt_template_id=prompt_template_id.strip(),
            prompt_template_version=prompt_template_version.strip(),
            prompt_sha256=_sha256_text(str(prompt_text)),
            output_schema=dict(output_schema),
            max_credits=max_credits,
            request_sha256="",
        )
        digest_payload = provisional.to_dict()
        digest_payload.pop("request_sha256")
        packet = replace(
            provisional,
            request_sha256=_sha256_text(_canonical_json(digest_payload)),
        )
        packet.verify_digest()
        return packet

    def authorize_submission(
        self,
        packet: WorkLLMTaskPacket,
        *,
        mode: str,
        monthly_credits_used: int,
    ) -> dict[str, object]:
        packet.verify_digest()
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in ALLOWED_EXECUTION_MODES:
            raise WorkLLMPolicyError("workllm_execution_mode_forbidden")
        if monthly_credits_used < 0:
            raise WorkLLMPolicyError("workllm_credit_usage_invalid")
        if self.config.kill_switch_active():
            raise WorkLLMPolicyError("workllm_kill_switch_engaged")
        projected = monthly_credits_used + packet.max_credits
        if projected > self.config.hard_credit_limit:
            raise WorkLLMPolicyError("workllm_hard_credit_limit_exceeded")
        if normalized_mode == "manual_browser":
            if not self.config.account_verified:
                raise WorkLLMPolicyError("workllm_account_unverified")
            if not self.config.manual_lane_enabled:
                raise WorkLLMPolicyError("workllm_manual_lane_disabled")
        elif not self.config.api_proof_complete:
            raise WorkLLMPolicyError("workllm_api_proof_incomplete")
        if (
            packet.data_classification == "internal_nonsecret"
            and not self.config.internal_nonsecret_enabled
        ):
            raise WorkLLMPolicyError(
                "workllm_internal_nonsecret_disabled"
            )
        return {
            "authorized": True,
            "mode": normalized_mode,
            "task_id": packet.task_id,
            "request_sha256": packet.request_sha256,
            "projected_monthly_credits": projected,
            "soft_limit_exceeded": projected > self.config.soft_credit_limit,
            "hard_limit": self.config.hard_credit_limit,
            "canonical_authority": False,
        }

    def capture_result(
        self,
        packet: WorkLLMTaskPacket,
        *,
        output_text: str,
        mode: str,
        observed_models: Sequence[str] = (),
        credits_consumed: int | None = None,
        provider_job_ref: str = "",
        provider_interaction_observed: bool = False,
        provider_surface_receipt_sha256: str = "",
        captured_at: str | None = None,
    ) -> tuple[dict[str, object], str]:
        packet.verify_digest()
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in ALLOWED_EXECUTION_MODES:
            raise WorkLLMPolicyError("workllm_execution_mode_forbidden")
        if credits_consumed is not None and (
            credits_consumed < 0 or credits_consumed > packet.max_credits
        ):
            raise WorkLLMPolicyError("workllm_result_credit_usage_invalid")
        surface_receipt_sha256 = str(
            provider_surface_receipt_sha256 or ""
        ).strip().lower()
        if provider_interaction_observed:
            surface_receipt_sha256 = _validate_sha256(
                surface_receipt_sha256,
                code="workllm_provider_surface_receipt_invalid",
            )
        elif surface_receipt_sha256:
            raise WorkLLMPolicyError(
                "workllm_provider_interaction_unverified"
            )
        redacted_output, output_redactions = redact_workllm_text(output_text)
        if not redacted_output.strip():
            raise WorkLLMPolicyError("workllm_result_missing")
        models = tuple(
            dict.fromkeys(
                value
                for item in observed_models
                if (value := str(item or "").strip())
            )
        )
        receipt: dict[str, object] = {
            "schema": WORKLLM_RUN_RECEIPT_SCHEMA,
            "provider": "workllm",
            "workspace_ref_sha256": _workspace_hash(self.config.workspace_url),
            "task_id": packet.task_id,
            "correlation_id": packet.correlation_id,
            "request_sha256": packet.request_sha256,
            "captured_at": _validated_utc_timestamp(
                captured_at or _utc_now(),
                code="workllm_result_captured_at_invalid",
            ),
            "execution_mode": normalized_mode,
            "provider_interaction_observed": bool(
                provider_interaction_observed
            ),
            "provider_surface_receipt_sha256": surface_receipt_sha256,
            "evidence_kind": (
                "provider_observed"
                if provider_interaction_observed
                else "synthetic_or_unverified"
            ),
            "provider_job_ref_sha256": (
                _sha256_text(provider_job_ref.strip())
                if provider_job_ref.strip()
                else ""
            ),
            "observed_models": list(models),
            "model_provenance_status": "observed" if models else "unknown",
            "credits_consumed": credits_consumed,
            "output_sha256": _sha256_text(redacted_output),
            "output_redactions": list(output_redactions),
            "source_manifest": [item.to_dict() for item in packet.source_manifest],
            "source_binding_status": "bound",
            "schema_validation_status": "pending",
            "safety_validation_status": "pending",
            "human_review": {
                "status": "pending",
                "decision": "",
                "reviewer_ref_sha256": "",
                "reviewed_at": "",
            },
            "retention": {
                "provider_export_status": "unknown",
                "provider_deletion_status": "unknown",
                "organization_memory_write_observed": False,
            },
            "authority": {
                "candidate_only": True,
                "canonical_write_allowed": False,
                "repo_write_allowed": False,
                "external_send_allowed": False,
                "publish_allowed": False,
                "approval_allowed": False,
            },
            "local_artifacts": {},
        }
        return receipt, redacted_output

    def persist_manual_result(
        self,
        packet: WorkLLMTaskPacket,
        *,
        output_text: str,
        observed_models: Sequence[str] = (),
        credits_consumed: int | None = None,
        provider_job_ref: str = "",
        provider_interaction_observed: bool = False,
        provider_surface_receipt_sha256: str = "",
        captured_at: str | None = None,
    ) -> dict[str, object]:
        receipt, redacted_output = self.capture_result(
            packet,
            output_text=output_text,
            mode="manual_browser",
            observed_models=observed_models,
            credits_consumed=credits_consumed,
            provider_job_ref=provider_job_ref,
            provider_interaction_observed=provider_interaction_observed,
            provider_surface_receipt_sha256=provider_surface_receipt_sha256,
            captured_at=captured_at,
        )
        run_dir = self.config.receipt_root / packet.task_id
        packet_path = run_dir / "task_packet.json"
        output_path = run_dir / "result.txt"
        receipt_path = run_dir / "run_receipt.json"
        local_artifacts = {
            "task_packet": str(packet_path),
            "result": str(output_path),
            "run_receipt": str(receipt_path),
        }
        receipt["local_artifacts"] = local_artifacts
        _secure_write_json(packet_path, packet.to_dict())
        _secure_write_text(output_path, redacted_output)
        _secure_write_json(receipt_path, receipt)
        return receipt

    def mark_reviewed(
        self,
        receipt: Mapping[str, object],
        *,
        reviewer_ref: str,
        decision: str,
        schema_valid: bool,
        safety_valid: bool,
        reviewed_at: str | None = None,
    ) -> dict[str, object]:
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in ALLOWED_REVIEW_DECISIONS:
            raise WorkLLMPolicyError("workllm_review_decision_invalid")
        normalized_reviewer = str(reviewer_ref or "").strip()
        if not normalized_reviewer:
            raise WorkLLMPolicyError("workllm_reviewer_ref_missing")
        updated = json.loads(json.dumps(dict(receipt)))
        updated["schema_validation_status"] = "passed" if schema_valid else "failed"
        updated["safety_validation_status"] = "passed" if safety_valid else "failed"
        updated["human_review"] = {
            "status": "completed",
            "decision": normalized_decision,
            "reviewer_ref_sha256": _sha256_text(normalized_reviewer),
            "reviewed_at": _validated_utc_timestamp(
                reviewed_at or _utc_now(),
                code="workllm_reviewed_at_invalid",
            ),
        }
        updated["candidate_accepted"] = bool(
            normalized_decision == "accepted_candidate"
            and schema_valid
            and safety_valid
        )
        updated["canonical_promotion_authority"] = False
        return updated


def evaluate_workllm_canary(
    receipts: Sequence[Mapping[str, object]],
    *,
    mode: str,
    minimum_runs: int = 20,
) -> dict[str, object]:
    """Evaluate canary receipts without granting route-promotion authority."""

    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in ALLOWED_EXECUTION_MODES:
        raise WorkLLMPolicyError("workllm_execution_mode_forbidden")
    if minimum_runs < 20:
        raise WorkLLMPolicyError("workllm_canary_minimum_too_small")
    items = [dict(receipt) for receipt in receipts]
    task_ids = [str(item.get("task_id") or "").strip() for item in items]
    unique_task_ids = {task_id for task_id in task_ids if task_id}
    receipt_contract_count = sum(
        item.get("schema") == WORKLLM_RUN_RECEIPT_SCHEMA for item in items
    )
    mode_match_count = sum(
        str(item.get("execution_mode") or "").strip().lower() == normalized_mode
        for item in items
    )
    source_bound_count = sum(
        item.get("source_binding_status") == "bound" for item in items
    )
    schema_passed_count = sum(
        item.get("schema_validation_status") == "passed" for item in items
    )
    safety_passed_count = sum(
        item.get("safety_validation_status") == "passed" for item in items
    )
    reviewed_count = sum(
        isinstance(item.get("human_review"), Mapping)
        and item["human_review"].get("status") == "completed"
        for item in items
    )
    credits_observed_count = sum(
        isinstance(item.get("credits_consumed"), int)
        and not isinstance(item.get("credits_consumed"), bool)
        and int(item["credits_consumed"]) >= 0
        for item in items
    )
    model_observed_count = sum(
        item.get("model_provenance_status") == "observed"
        and isinstance(item.get("observed_models"), list)
        and bool(item["observed_models"])
        for item in items
    )
    provider_observed_count = sum(
        item.get("provider_interaction_observed") is True
        and item.get("evidence_kind") == "provider_observed"
        and _SHA256_RE.fullmatch(
            str(item.get("provider_surface_receipt_sha256") or "")
        )
        is not None
        for item in items
    )
    accepted_candidate_count = sum(
        item.get("candidate_accepted") is True
        and isinstance(item.get("human_review"), Mapping)
        and item["human_review"].get("decision") == "accepted_candidate"
        for item in items
    )
    authority_safe_count = 0
    for item in items:
        authority = item.get("authority")
        if not isinstance(authority, Mapping):
            continue
        if (
            authority.get("candidate_only") is True
            and authority.get("canonical_write_allowed") is False
            and authority.get("repo_write_allowed") is False
            and authority.get("external_send_allowed") is False
            and authority.get("publish_allowed") is False
            and authority.get("approval_allowed") is False
        ):
            authority_safe_count += 1
    run_count = len(items)
    schema_success_rate = (
        round(schema_passed_count / run_count, 4) if run_count else 0.0
    )
    failures: list[str] = []
    if run_count < minimum_runs:
        failures.append("minimum_run_count_not_met")
    if len(unique_task_ids) != run_count:
        failures.append("task_ids_missing_or_duplicated")
    if receipt_contract_count != run_count:
        failures.append("receipt_contract_incomplete")
    if mode_match_count != run_count:
        failures.append("execution_mode_mismatch")
    if source_bound_count != run_count:
        failures.append("source_binding_incomplete")
    if schema_success_rate < 0.95:
        failures.append("schema_success_below_95_percent")
    if safety_passed_count != run_count:
        failures.append("safety_validation_incomplete")
    if reviewed_count != run_count:
        failures.append("human_review_incomplete")
    if credits_observed_count != run_count:
        failures.append("credit_observation_incomplete")
    if provider_observed_count != run_count:
        failures.append("provider_interaction_evidence_incomplete")
    if model_observed_count != run_count:
        failures.append("model_provenance_incomplete")
    if accepted_candidate_count != run_count:
        failures.append("candidate_acceptance_incomplete")
    if authority_safe_count != run_count:
        failures.append("authority_boundary_violation")
    return {
        "schema": "executive_assistant.workllm_canary_evaluation.v1",
        "provider": "workllm",
        "mode": normalized_mode,
        "minimum_runs": minimum_runs,
        "run_count": run_count,
        "unique_task_count": len(unique_task_ids),
        "receipt_contract_count": receipt_contract_count,
        "source_bound_count": source_bound_count,
        "schema_passed_count": schema_passed_count,
        "schema_success_rate": schema_success_rate,
        "safety_passed_count": safety_passed_count,
        "reviewed_count": reviewed_count,
        "credits_observed_count": credits_observed_count,
        "model_observed_count": model_observed_count,
        "provider_observed_count": provider_observed_count,
        "accepted_candidate_count": accepted_candidate_count,
        "authority_safe_count": authority_safe_count,
        "failures": failures,
        "promotion_eligible_candidate": not failures,
        "canonical_promotion_authority": False,
    }
