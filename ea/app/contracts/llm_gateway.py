from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from app.llm import ask_llm
from app.llm_gateway.policy import is_egress_denied
from app.llm_gateway.trust_boundary import validate_model_output


DEFAULT_SYSTEM_PROMPT = "Du bist ein präziser Executive Assistant."
_SECRET_PAT = re.compile(
    r"(?i)\b("
    r"sk-[a-z0-9]{10,}|"
    r"AIza[0-9A-Za-z\-_]{20,}|"
    r"Bearer\s+[A-Za-z0-9\-\._=]{12,}|"
    r"xox[baprs]-[A-Za-z0-9\-]{8,}"
    r")\b"
)
_CONTROL_CHARS_PAT = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+")
_RAW_DOC_PAT = re.compile(
    r"(?i)(^%pdf-|^-----begin [a-z ]+-----|content-type:\s*application/pdf|data:application/pdf;base64,)"
)
_BLOCKED_COPY = "I cannot help with hidden tool/runtime instructions. Please restate the request in plain user terms."
_FALLBACK_COPY = "I could not complete the model step safely. Please retry in a moment."
_RAW_DOC_BLOCKED_COPY = "I cannot process raw document payloads in this flow. Provide a short summary request instead."
_MAX_OUTPUT_CHARS_DEFAULT = 12000


@dataclass(frozen=True)
class TaskPolicy:
    task_type: str
    allow_json: bool
    allow_raw_docs: bool
    user_surface: bool


_TASK_POLICIES: dict[str, TaskPolicy] = {
    "briefing_compose": TaskPolicy(
        task_type="briefing_compose",
        allow_json=False,
        allow_raw_docs=False,
        user_surface=True,
    ),
    "profile_summary": TaskPolicy(
        task_type="profile_summary",
        allow_json=False,
        allow_raw_docs=False,
        user_surface=True,
    ),
    "future_reasoning": TaskPolicy(
        task_type="future_reasoning",
        allow_json=False,
        allow_raw_docs=False,
        user_surface=True,
    ),
    "operator_only": TaskPolicy(
        task_type="operator_only",
        allow_json=True,
        allow_raw_docs=True,
        user_surface=False,
    ),
}


def _safe_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        raw = int(str(os.getenv(name, str(default))).strip())
    except Exception:
        raw = default
    return max(minimum, min(maximum, raw))


def _sanitize_prompt(text: str, *, max_chars: int) -> str:
    cleaned = _CONTROL_CHARS_PAT.sub(" ", str(text or "")).strip()
    cleaned = _SECRET_PAT.sub("[redacted_secret]", cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars].rstrip()} [truncated]"


def _contains_raw_document_payload(text: str) -> bool:
    body = str(text or "")
    if not body:
        return False
    if _RAW_DOC_PAT.search(body):
        return True
    # Heuristic: very long, multi-line payloads in user-facing tasks are likely
    # raw dumps and should be blocked unless explicitly allowlisted.
    if len(body) >= 15000 and body.count("\n") >= 80:
        return True
    return False


def _normalize_task_type(task_type: str | None) -> str:
    raw = str(task_type or "").strip().lower()
    if not raw:
        return ""
    if raw in _TASK_POLICIES:
        return raw
    if raw in ("briefing", "summary"):
        return "briefing_compose"
    if raw in ("profile", "profile_context"):
        return "profile_summary"
    return ""


def _allow_implicit_task_type() -> bool:
    # Transitional override only. Production should require explicit task_type.
    return str(os.getenv("EA_LLM_GATEWAY_ALLOW_IMPLICIT_TASK_TYPE", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _policy_for(task_type: str) -> TaskPolicy:
    return _TASK_POLICIES.get(task_type, _TASK_POLICIES["briefing_compose"])


def _audit_egress(
    *,
    purpose: str,
    task_type: str,
    correlation_id: str,
    data_class: str,
    prompt_chars: int,
    system_chars: int,
    redaction_applied: bool,
    verdict: str,
    tenant: str = "",
    person_id: str = "",
) -> None:
    path = os.getenv("EA_LLM_GATEWAY_AUDIT_PATH", "/attachments/llm_egress_audit.jsonl")
    db_audit_enabled = str(os.getenv("EA_LLM_GATEWAY_DB_AUDIT_ENABLED", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    row = {
        "ts": int(time.time()),
        "purpose": str(purpose or "user_assist"),
        "task_type": str(task_type or "briefing_compose"),
        "correlation_id": str(correlation_id or "")[:120],
        "data_class": str(data_class or "derived_summary"),
        "tenant": str(tenant or "")[:120],
        "person_id": str(person_id or "")[:120],
        "prompt_chars": int(prompt_chars),
        "system_chars": int(system_chars),
        "redaction_applied": bool(redaction_applied),
        "verdict": str(verdict or "ok"),
    }
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if db_audit_enabled:
        try:
            from app.db import log_to_db

            log_to_db(
                tenant=None,
                component="llm_gateway",
                event_type="egress_audit",
                message=f"{row['task_type']}:{row['verdict']}",
                payload=row,
            )
        except Exception:
            pass


def ask_text(
    prompt: str,
    *,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    task_type: str | None = None,
    purpose: str = "user_assist",
    correlation_id: str = "",
    data_class: str = "derived_summary",
    tenant: str = "",
    person_id: str = "",
    allow_json: bool | None = None,
) -> str:
    """
    Contract boundary for feature-layer LLM requests.
    Adds prompt sanitization, bounded prompt sizes, task policy checks,
    output validation, and egress audit metadata logging.
    """
    max_prompt = _safe_int_env("EA_LLM_GATEWAY_MAX_PROMPT_CHARS", default=12000, minimum=512, maximum=50000)
    max_system = _safe_int_env("EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS", default=4000, minimum=128, maximum=12000)
    max_output = _safe_int_env(
        "EA_LLM_GATEWAY_MAX_OUTPUT_CHARS",
        default=_MAX_OUTPUT_CHARS_DEFAULT,
        minimum=256,
        maximum=50000,
    )
    safe_prompt = _sanitize_prompt(str(prompt or ""), max_chars=max_prompt)
    safe_system = _sanitize_prompt(str(system_prompt or DEFAULT_SYSTEM_PROMPT), max_chars=max_system)
    redaction_applied = safe_prompt != str(prompt or "") or safe_system != str(system_prompt or DEFAULT_SYSTEM_PROMPT)
    tenant_key = str(tenant or "").strip()
    person_key = str(person_id or "").strip()
    if not safe_system:
        safe_system = DEFAULT_SYSTEM_PROMPT
    if not safe_prompt:
        safe_prompt = "Provide a concise, user-safe summary."
    normalized_task_type = _normalize_task_type(task_type)
    if not normalized_task_type:
        if _allow_implicit_task_type():
            normalized_task_type = "briefing_compose"
        else:
            _audit_egress(
                purpose=purpose,
                task_type="missing",
                correlation_id=correlation_id,
                data_class=data_class,
                prompt_chars=len(safe_prompt),
                system_chars=len(safe_system),
                redaction_applied=redaction_applied,
                verdict="blocked_missing_task_type",
                tenant=tenant_key,
                person_id=person_key,
            )
            return _BLOCKED_COPY
    policy = _policy_for(normalized_task_type)
    if is_egress_denied(
        tenant=tenant_key or "*",
        person_id=person_key,
        task_type=policy.task_type,
        data_class=str(data_class or "derived_summary"),
    ):
        _audit_egress(
            purpose=purpose,
            task_type=policy.task_type,
            correlation_id=correlation_id,
            data_class=data_class,
            prompt_chars=len(safe_prompt),
            system_chars=len(safe_system),
            redaction_applied=redaction_applied,
            verdict="blocked_policy",
            tenant=tenant_key,
            person_id=person_key,
        )
        return _BLOCKED_COPY
    if (not policy.allow_raw_docs) and _contains_raw_document_payload(safe_prompt):
        _audit_egress(
            purpose=purpose,
            task_type=policy.task_type,
            correlation_id=correlation_id,
            data_class=data_class,
            prompt_chars=len(safe_prompt),
            system_chars=len(safe_system),
            redaction_applied=redaction_applied,
            verdict="blocked_raw_document_payload",
            tenant=tenant_key,
            person_id=person_key,
        )
        return _RAW_DOC_BLOCKED_COPY

    try:
        model_output = ask_llm(safe_prompt, system_prompt=safe_system)
    except Exception:
        _audit_egress(
            purpose=purpose,
            task_type=policy.task_type,
            correlation_id=correlation_id,
            data_class=data_class,
            prompt_chars=len(safe_prompt),
            system_chars=len(safe_system),
            redaction_applied=redaction_applied,
            verdict="provider_error",
            tenant=tenant_key,
            person_id=person_key,
        )
        return _FALLBACK_COPY

    text = str(model_output or "").strip()
    if not text:
        _audit_egress(
            purpose=purpose,
            task_type=policy.task_type,
            correlation_id=correlation_id,
            data_class=data_class,
            prompt_chars=len(safe_prompt),
            system_chars=len(safe_system),
            redaction_applied=redaction_applied,
            verdict="empty_output",
            tenant=tenant_key,
            person_id=person_key,
        )
        return _FALLBACK_COPY
    if len(text) > max_output:
        text = f"{text[:max_output].rstrip()} [truncated]"

    effective_allow_json = bool(allow_json) if allow_json is not None else policy.allow_json
    verdict = validate_model_output(
        task_type=policy.task_type,
        model_output=text,
        allow_json=effective_allow_json,
        user_surface=policy.user_surface,
    )
    _audit_egress(
        purpose=purpose,
        task_type=policy.task_type,
        correlation_id=correlation_id,
        data_class=data_class,
        prompt_chars=len(safe_prompt),
        system_chars=len(safe_system),
        redaction_applied=redaction_applied,
        verdict=verdict,
        tenant=tenant_key,
        person_id=person_key,
    )
    if verdict != "ok":
        return _BLOCKED_COPY
    return text
