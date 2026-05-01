from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum

from app.domain.models import ToolInvocationRequest
from app.services.responses_upstream import UpstreamResult
from app.services.tool_execution_common import ToolExecutionError


_SURVIVAL_CACHE_LOCK = threading.Lock()
_SURVIVAL_CACHE: dict[str, tuple[float, "SurvivalResult"]] = {}
_SURVIVAL_QUEUE_LOCK = threading.Condition(threading.Lock())
_SURVIVAL_ACTIVE_REQUESTS = 0
_SURVIVAL_BACKEND_STATE_LOCK = threading.Lock()
_SURVIVAL_BACKEND_STATE: dict[str, "_BackendFailureState"] = {}


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "off", "no", "n"}:
        return False
    return default


def _to_int(value: object, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(float(str(value)))
    except Exception:
        return default
    if parsed < minimum:
        parsed = minimum
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _extract_textish(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return "\n".join(part for part in (_extract_textish(item) for item in value) if part).strip()
    if isinstance(value, dict):
        for key in ("text", "answer", "summary", "consensus", "recommendation", "message", "output", "result"):
            text = _extract_textish(value.get(key))
            if text:
                return text
        try:
            return json.dumps(value, ensure_ascii=True)
        except Exception:
            return ""
    return ""


def _compact_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _history_item_to_text(item: dict[str, object]) -> str:
    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "message":
        role = str(item.get("role") or "user").strip() or "user"
        content = item.get("content")
        text = ""
        if isinstance(content, list):
            text = "\n\n".join(
                _extract_textish(part.get("text"))
                for part in content
                if isinstance(part, dict) and _extract_textish(part.get("text"))
            ).strip()
        else:
            text = _extract_textish(content)
        if not text:
            return ""
        return f"{role.capitalize()}:\n{text}"
    if item_type == "input_text":
        text = _extract_textish(item.get("text"))
        return f"User:\n{text}" if text else ""
    if item_type == "function_call":
        name = str(item.get("name") or "").strip()
        arguments = str(item.get("arguments") or "").strip()
        if not name:
            return ""
        return f"Assistant tool call:\nTool: {name}\nArguments: {arguments}".strip()
    if item_type == "function_call_output":
        output = _extract_textish(item.get("output"))
        return f"Tool output:\n{output}".strip() if output else ""
    return ""


def _clamp_text(text: str, *, limit: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip()


def _survival_route_order() -> tuple[str, ...]:
    raw = _env("EA_SURVIVAL_ROUTE_ORDER", "onemin,gemini_vortex,gemini_web,chatplayground")
    ordered: list[str] = []
    seen: set[str] = set()
    aliases = {
        "onemin": "onemin",
        "1min": "onemin",
        "onemin_code": "onemin",
        "onemin_text": "onemin",
        "gemini": "gemini_vortex",
        "gemini_cli": "gemini_vortex",
        "gemini_vortex": "gemini_vortex",
        "gemini_web": "gemini_web",
        "browseract_gemini_web": "gemini_web",
        "chatplayground": "chatplayground",
        "chatplayground_audit": "chatplayground",
    }
    for item in raw.split(","):
        normalized = aliases.get(str(item or "").strip().lower().replace("-", "_"), "")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered or ("onemin", "gemini_vortex", "gemini_web", "chatplayground"))


def _survival_cache_ttl_seconds() -> int:
    return _to_int(_env("EA_SURVIVAL_CACHE_TTL_SECONDS", "86400"), 86400, minimum=60, maximum=604800)


def _survival_enabled() -> bool:
    return _to_bool(_env("EA_SURVIVAL_ENABLED", "1"), True)


def _survival_max_active_requests() -> int:
    return _to_int(_env("EA_SURVIVAL_MAX_ACTIVE_REQUESTS", "1"), 1, minimum=1, maximum=4)


def _survival_queue_timeout_seconds() -> int:
    return _to_int(_env("EA_SURVIVAL_QUEUE_TIMEOUT_SECONDS", "900"), 900, minimum=1, maximum=7200)


def _survival_gemini_web_mode() -> str:
    raw = str(_env("EA_SURVIVAL_GEMINI_WEB_MODE", "thinking") or "thinking").strip().lower()
    if raw not in {"thinking", "fast", "pro"}:
        return "thinking"
    return raw


def _survival_gemini_web_deep_think_allowed() -> bool:
    return _to_bool(_env("EA_SURVIVAL_GEMINI_WEB_ALLOW_DEEP_THINK", "0"), False)


def _survival_chatplayground_role() -> str:
    return str(_env("EA_SURVIVAL_CHATPLAYGROUND_SINGLE_ROLE", "factuality") or "factuality").strip() or "factuality"


def _survival_onemin_model() -> str:
    for env_name in ("EA_SURVIVAL_ONEMIN_MODEL", "EA_ONEMIN_TOOL_REVIEW_MODEL", "EA_ONEMIN_TOOL_CODE_MODEL"):
        configured = str(_env(env_name, "") or "").strip()
        if configured:
            return configured
    return "deepseek-chat"


def _ui_challenge_cooldown_seconds() -> int:
    return _to_int(_env("EA_UI_CHALLENGE_COOLDOWN_SECONDS", "1800"), 1800, minimum=30, maximum=86400)


def _ui_challenge_max_consecutive() -> int:
    return _to_int(_env("EA_UI_CHALLENGE_MAX_CONSECUTIVE", "2"), 2, minimum=1, maximum=20)


def _survival_unavailable_cooldown_seconds() -> int:
    return _to_int(_env("EA_SURVIVAL_UNAVAILABLE_COOLDOWN_SECONDS", "900"), 900, minimum=30, maximum=86400)


_SURVIVAL_BACKEND_PROVIDER_KEYS = {
    "chatplayground": "browseract",
    "gemini_web": "browseract",
    "gemini_vortex": "gemini_vortex",
    "onemin": "onemin",
}
_SURVIVAL_BACKEND_HEALTH_ALIASES = {
    "chatplayground": ("chatplayground", "browseract"),
    "gemini_web": ("gemini_web", "browseract", "chatplayground"),
    "gemini_vortex": ("gemini_vortex",),
    "onemin": ("onemin",),
}


def _cache_get(cache_key: str) -> "SurvivalResult" | None:
    if not cache_key:
        return None
    ttl = _survival_cache_ttl_seconds()
    now = time.time()
    with _SURVIVAL_CACHE_LOCK:
        entry = _SURVIVAL_CACHE.get(cache_key)
        if entry is None:
            return None
        expires_at, result = entry
        if expires_at < now:
            _SURVIVAL_CACHE.pop(cache_key, None)
            return None
        return result


def _cache_put(cache_key: str, result: "SurvivalResult") -> None:
    if not cache_key:
        return
    expires_at = time.time() + float(_survival_cache_ttl_seconds())
    with _SURVIVAL_CACHE_LOCK:
        _SURVIVAL_CACHE[cache_key] = (expires_at, result)


def _acquire_survival_slot() -> bool:
    global _SURVIVAL_ACTIVE_REQUESTS
    max_active = _survival_max_active_requests()
    deadline = time.time() + float(_survival_queue_timeout_seconds())
    with _SURVIVAL_QUEUE_LOCK:
        while _SURVIVAL_ACTIVE_REQUESTS >= max_active:
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            _SURVIVAL_QUEUE_LOCK.wait(remaining)
        _SURVIVAL_ACTIVE_REQUESTS += 1
        return True


def _release_survival_slot() -> None:
    global _SURVIVAL_ACTIVE_REQUESTS
    with _SURVIVAL_QUEUE_LOCK:
        if _SURVIVAL_ACTIVE_REQUESTS > 0:
            _SURVIVAL_ACTIVE_REQUESTS -= 1
        _SURVIVAL_QUEUE_LOCK.notify_all()


def _test_reset_survival_state() -> None:
    global _SURVIVAL_ACTIVE_REQUESTS
    with _SURVIVAL_CACHE_LOCK:
        _SURVIVAL_CACHE.clear()
    with _SURVIVAL_BACKEND_STATE_LOCK:
        _SURVIVAL_BACKEND_STATE.clear()
    with _SURVIVAL_QUEUE_LOCK:
        _SURVIVAL_ACTIVE_REQUESTS = 0
        _SURVIVAL_QUEUE_LOCK.notify_all()


def _survival_backend_provider_key(backend: str) -> str:
    return str(_SURVIVAL_BACKEND_PROVIDER_KEYS.get(str(backend or "").strip().lower(), "") or "").strip()


def _survival_backend_health_aliases(backend: str) -> tuple[str, ...]:
    normalized = str(backend or "").strip().lower()
    aliases = _SURVIVAL_BACKEND_HEALTH_ALIASES.get(normalized, (normalized,))
    return tuple(str(item or "").strip() for item in aliases if str(item or "").strip())


def _survival_provider_health_payload(
    provider_health: dict[str, object] | None,
    *,
    backend: str,
) -> tuple[str, dict[str, object]]:
    providers = dict(((provider_health or {}).get("providers")) or {})
    for provider_key in _survival_backend_health_aliases(backend):
        payload = dict(providers.get(provider_key) or {})
        if payload:
            return provider_key, payload
    return "", {}


def _survival_provider_capacity(provider_payload: dict[str, object]) -> dict[str, object]:
    slots = [dict(item) for item in (provider_payload.get("slots") or []) if isinstance(item, dict)]
    configured_slots = int(provider_payload.get("configured_slots") or len(slots) or 0)
    slot_states = [str(slot.get("state") or "").strip().lower() or "unknown" for slot in slots if bool(slot.get("configured", True))]
    ready_slots = sum(1 for state in slot_states if state == "ready")
    degraded_slots = sum(
        1
        for state in slot_states
        if state in {"degraded", "cooldown", "maintenance", "unknown", "rate_limited", "quarantined", "quota_low", "throttled"}
    )
    unavailable_slots = max(0, configured_slots - ready_slots - degraded_slots)
    state = str(provider_payload.get("state") or "").strip().lower()
    if not state:
        if ready_slots > 0:
            state = "ready"
        elif degraded_slots > 0:
            state = "degraded"
        elif configured_slots > 0:
            state = "unknown"
        else:
            state = "missing"
    elif state == "ready" and configured_slots > 0 and ready_slots <= 0:
        state = "degraded" if degraded_slots > 0 else "unavailable"
    return {
        "state": state,
        "configured_slots": configured_slots,
        "ready_slots": ready_slots,
        "degraded_slots": degraded_slots,
        "unavailable_slots": unavailable_slots,
        "detail": str(provider_payload.get("detail") or "").strip(),
    }


def _current_backend_failure(backend: str) -> "UiLaneFailure" | None:
    normalized = str(backend or "").strip().lower()
    if not normalized:
        return None
    now = time.time()
    with _SURVIVAL_BACKEND_STATE_LOCK:
        state = _SURVIVAL_BACKEND_STATE.get(normalized)
        if state is None or state.cooldown_until <= now or not state.last_failure_code:
            return None
        try:
            code = UiLaneFailureCode(state.last_failure_code)
        except ValueError:
            return None
        return UiLaneFailure(
            provider_backend=normalized,
            code=code,
            detail=state.last_failure_detail,
            retryable=True,
            cooldown_seconds=max(0, int(state.cooldown_until - now)),
        )


def _clear_backend_failure_state(backend: str) -> None:
    normalized = str(backend or "").strip().lower()
    if not normalized:
        return
    with _SURVIVAL_BACKEND_STATE_LOCK:
        _SURVIVAL_BACKEND_STATE.pop(normalized, None)


def _record_backend_failure_state(backend: str, failure: "UiLaneFailure") -> None:
    normalized = str(backend or failure.provider_backend or "").strip().lower()
    if not normalized:
        return
    now = time.time()
    with _SURVIVAL_BACKEND_STATE_LOCK:
        state = _SURVIVAL_BACKEND_STATE.get(normalized) or _BackendFailureState()
        if failure.code in {
            UiLaneFailureCode.challenge_required,
            UiLaneFailureCode.challenge_loop,
            UiLaneFailureCode.session_expired,
        }:
            state.consecutive_challenges += 1
            if state.consecutive_challenges >= _ui_challenge_max_consecutive():
                state.last_failure_code = UiLaneFailureCode.challenge_loop.value
            else:
                state.last_failure_code = failure.code.value
            state.cooldown_until = now + float(failure.cooldown_seconds or _ui_challenge_cooldown_seconds())
        else:
            state.consecutive_challenges = 0
            state.last_failure_code = failure.code.value
            state.cooldown_until = now + float(max(0, failure.cooldown_seconds))
        state.last_failure_detail = failure.detail
        state.last_failure_at = now
        _SURVIVAL_BACKEND_STATE[normalized] = state


def _test_record_backend_failure(
    *,
    backend: str,
    code: str,
    detail: str = "",
    cooldown_seconds: int | None = None,
) -> None:
    normalized_code = UiLaneFailureCode(str(code or "").strip().lower())
    if cooldown_seconds is None:
        if normalized_code in {
            UiLaneFailureCode.challenge_required,
            UiLaneFailureCode.challenge_loop,
            UiLaneFailureCode.session_expired,
        }:
            cooldown_seconds = _ui_challenge_cooldown_seconds()
        elif normalized_code == UiLaneFailureCode.lane_unavailable:
            cooldown_seconds = _survival_unavailable_cooldown_seconds()
        else:
            cooldown_seconds = 0
    _record_backend_failure_state(
        backend,
        UiLaneFailure(
            provider_backend=str(backend or "").strip().lower(),
            code=normalized_code,
            detail=str(detail or "").strip(),
            retryable=True,
            cooldown_seconds=int(cooldown_seconds),
        ),
    )


def survival_route_health_snapshot(
    *,
    provider_health: dict[str, object] | None = None,
    browseract_binding_available: bool | None = None,
) -> dict[str, object]:
    route_order = _survival_route_order()
    backends: list[dict[str, object]] = []
    all_provider_hint_order: list[str] = []
    provider_hint_order: list[str] = []
    selected_backend = ""
    selected_provider_key = ""
    selected_health_provider_key = ""
    selected_state = "unavailable"
    for backend in route_order:
        provider_key = _survival_backend_provider_key(backend)
        if provider_key and provider_key not in all_provider_hint_order:
            all_provider_hint_order.append(provider_key)
        health_provider_key, provider_payload = _survival_provider_health_payload(provider_health, backend=backend)
        capacity = _survival_provider_capacity(provider_payload)
        ready_slots = int(capacity.get("ready_slots") or 0)
        configured_slots = int(capacity.get("configured_slots") or 0)
        raw_state = str(capacity.get("state") or "missing").strip().lower() or "missing"
        failure = _current_backend_failure(backend)
        browseract_binding_blocked = (
            browseract_binding_available is False
            and backend in {"chatplayground", "gemini_web"}
        )
        if browseract_binding_blocked:
            advertised_state = "unavailable"
            detail = "browseract_binding_unavailable"
            routable = False
        elif failure is not None:
            advertised_state = "cooldown"
            detail_parts = [f"cooldown_active:{failure.code.value}"]
            if failure.cooldown_seconds > 0:
                detail_parts.append(f"{failure.cooldown_seconds}s")
            if failure.detail:
                detail_parts.append(str(failure.detail))
            detail = " ".join(part for part in detail_parts if part).strip()
            routable = False
        else:
            advertised_state = "ready" if ready_slots > 0 or (configured_slots <= 0 and raw_state == "ready") else raw_state
            detail = str(capacity.get("detail") or "").strip()
            routable = advertised_state == "ready"
        row = {
            "backend": backend,
            "provider_key": provider_key,
            "health_provider_key": health_provider_key or provider_key,
            "state": advertised_state,
            "raw_state": raw_state,
            "detail": detail,
            "routable": routable,
            "configured_slots": configured_slots,
            "ready_slots": ready_slots,
            "degraded_slots": int(capacity.get("degraded_slots") or 0),
            "unavailable_slots": int(capacity.get("unavailable_slots") or 0),
        }
        backends.append(row)
        if routable and provider_key and provider_key not in provider_hint_order:
            provider_hint_order.append(provider_key)
        if routable and not selected_backend:
            selected_backend = backend
            selected_provider_key = provider_key
            selected_health_provider_key = str(row.get("health_provider_key") or provider_key or "").strip()
            selected_state = advertised_state
    if selected_backend:
        reason = (
            f"selected survival backend={selected_backend} "
            f"provider={selected_provider_key or selected_health_provider_key or 'unknown'} state={selected_state}"
        )
    else:
        reason = "no routable survival backends"
        blocked = [
            f"{row['backend']}:{row['state']}{(':' + str(row['detail'])) if row.get('detail') else ''}"
            for row in backends
        ]
        if blocked:
            reason = reason + ": " + "; ".join(blocked)
    return {
        "route_order": route_order,
        "provider_hint_order": tuple(provider_hint_order),
        "route_provider_hint_order": tuple(all_provider_hint_order),
        "backend": selected_backend,
        "health_provider_key": selected_health_provider_key,
        "primary_provider_key": selected_provider_key,
        "state": selected_state if selected_backend else "unavailable",
        "reason": reason,
        "backends": tuple(backends),
    }


@dataclass(frozen=True)
class SurvivalPacket:
    objective: str
    instructions: str | None
    condensed_history: str
    current_input: str
    desired_format: str | None
    fingerprint: str


class UiLaneFailureCode(str, Enum):
    challenge_required = "challenge_required"
    challenge_loop = "challenge_loop"
    session_expired = "session_expired"
    lane_unavailable = "lane_unavailable"
    timeout = "timeout"
    empty_output = "empty_output"


@dataclass(frozen=True)
class UiLaneFailure:
    provider_backend: str
    code: UiLaneFailureCode
    detail: str = ""
    retryable: bool = True
    cooldown_seconds: int = 0


@dataclass
class _BackendFailureState:
    cooldown_until: float = 0.0
    consecutive_challenges: int = 0
    last_failure_code: str = ""
    last_failure_detail: str = ""
    last_failure_at: float = 0.0


@dataclass(frozen=True)
class SurvivalAttempt:
    backend: str
    started_at: float
    completed_at: float | None = None
    status: str = "pending"
    detail: str | None = None


@dataclass(frozen=True)
class SurvivalResult:
    text: str
    provider_key: str
    provider_backend: str
    model: str
    latency_ms: int
    attempts: tuple[SurvivalAttempt, ...]
    cache_hit: bool = False

    def to_upstream_result(self) -> UpstreamResult:
        return UpstreamResult(
            text=self.text,
            provider_key=self.provider_key,
            model=self.model,
            provider_backend=self.provider_backend,
            latency_ms=self.latency_ms,
        )


class SurvivalLaneService:
    def __init__(
        self,
        *,
        tool_execution: object | None,
        tool_runtime: object | None,
        principal_id: str,
    ) -> None:
        self._tool_execution = tool_execution
        self._tool_runtime = tool_runtime
        self._principal_id = str(principal_id or "").strip()

    def build_packet(
        self,
        *,
        instructions: str | None,
        history_items: list[dict[str, object]],
        current_input: str,
        desired_format: str | None,
        prompt_cache_key: str | None,
        previous_response_id: str | None,
    ) -> SurvivalPacket:
        history_lines = [
            line
            for line in (_history_item_to_text(item) for item in history_items[:-1])
            if line
        ]
        condensed_history = _clamp_text("\n\n".join(history_lines).strip(), limit=6000)
        current = _clamp_text(current_input, limit=3000)
        objective = current.splitlines()[0].strip() if current else "continue the current task"
        desired = str(desired_format or "plain_text").strip() or "plain_text"
        fingerprint_source = {
            "principal_id": self._principal_id,
            "instructions": instructions or "",
            "condensed_history": condensed_history,
            "current_input": current,
            "desired_format": desired,
            "previous_response_id": previous_response_id or "",
            "prompt_cache_key": prompt_cache_key or "",
        }
        fingerprint = hashlib.sha256(_compact_json(fingerprint_source).encode("utf-8")).hexdigest()
        return SurvivalPacket(
            objective=objective,
            instructions=instructions,
            condensed_history=condensed_history,
            current_input=current,
            desired_format=desired,
            fingerprint=fingerprint,
        )

    def execute(
        self,
        *,
        instructions: str | None,
        history_items: list[dict[str, object]],
        current_input: str,
        desired_format: str | None = None,
        prompt_cache_key: str | None = None,
        previous_response_id: str | None = None,
    ) -> SurvivalResult:
        if not _survival_enabled():
            raise RuntimeError("survival_lane_disabled")
        packet = self.build_packet(
            instructions=instructions,
            history_items=history_items,
            current_input=current_input,
            desired_format=desired_format,
            prompt_cache_key=prompt_cache_key,
            previous_response_id=previous_response_id,
        )
        cache_key = str(prompt_cache_key or packet.fingerprint).strip()
        cached = _cache_get(cache_key)
        if cached is not None:
            return SurvivalResult(
                text=cached.text,
                provider_key=cached.provider_key,
                provider_backend=cached.provider_backend,
                model=cached.model,
                latency_ms=0,
                attempts=cached.attempts
                + (
                    SurvivalAttempt(
                        backend="cache",
                        started_at=time.time(),
                        completed_at=time.time(),
                        status="completed",
                        detail="cache_hit",
                    ),
                ),
                cache_hit=True,
            )

        if not _acquire_survival_slot():
            raise RuntimeError("survival_queue_timeout")
        try:
            cached = _cache_get(cache_key)
            if cached is not None:
                return SurvivalResult(
                    text=cached.text,
                    provider_key=cached.provider_key,
                    provider_backend=cached.provider_backend,
                    model=cached.model,
                    latency_ms=0,
                    attempts=cached.attempts
                    + (
                        SurvivalAttempt(
                            backend="cache",
                            started_at=time.time(),
                            completed_at=time.time(),
                            status="completed",
                            detail="cache_hit_after_queue",
                        ),
                    ),
                    cache_hit=True,
                )

            attempts: list[SurvivalAttempt] = []
            for backend in _survival_route_order():
                cooldown = self._backend_cooldown_failure(backend)
                if cooldown is not None:
                    now = time.time()
                    attempts.append(
                        SurvivalAttempt(
                            backend=backend,
                            started_at=now,
                            completed_at=now,
                            status="skipped",
                            detail=f"cooldown_active:{cooldown.code.value}",
                        )
                    )
                    continue
                if backend == "onemin":
                    result = self.try_onemin(packet=packet, attempts=attempts)
                elif backend == "gemini_vortex":
                    result = self.try_gemini_vortex(packet=packet, attempts=attempts)
                elif backend == "gemini_web":
                    result = self.try_browseract_gemini_web(packet=packet, attempts=attempts)
                elif backend == "chatplayground":
                    result = self.try_chatplayground_tiebreak(packet=packet, attempts=attempts)
                else:
                    result = None
                if result is not None:
                    _cache_put(cache_key, result)
                    return result
            raise RuntimeError("survival_no_backend_available")
        finally:
            _release_survival_slot()

    def cache_lookup(self, *, cache_key: str) -> SurvivalResult | None:
        return _cache_get(cache_key)

    def cache_store(self, *, cache_key: str, result: SurvivalResult) -> None:
        _cache_put(cache_key, result)

    def try_onemin(
        self,
        *,
        packet: SurvivalPacket,
        attempts: list[SurvivalAttempt],
    ) -> SurvivalResult | None:
        started_at = time.time()
        if self._tool_execution is None:
            attempts.append(
                SurvivalAttempt(
                    backend="onemin",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="tool_execution_unavailable",
                )
            )
            return None
        payload = {
            "prompt": self._render_packet(packet),
            "instructions": (
                "Answer the user's request using the reduced survival packet. "
                "Return only the answer text unless the desired format explicitly asks for something else."
            ),
            "goal": packet.objective,
            "model": _survival_onemin_model(),
        }
        invocation = ToolInvocationRequest(
            session_id=f"survival:{uuid.uuid4().hex}",
            step_id=f"survival-step:{uuid.uuid4().hex}",
            tool_name="provider.onemin.code_generate",
            action_kind="code.generate",
            payload_json=payload,
            context_json={"principal_id": self._principal_id, "manager_allow_reserve": True},
        )
        try:
            result = self._tool_execution.execute_invocation(invocation)
        except ToolExecutionError as exc:
            failure = self._ui_failure_from_detail(str(exc), backend_hint="onemin")
            if failure is not None:
                self._record_backend_failure("onemin", failure)
            attempts.append(
                SurvivalAttempt(
                    backend="onemin",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=(failure.code.value if failure is not None else str(exc)),
                )
            )
            return None
        output_json = dict(result.output_json or {})
        structured = output_json.get("structured_output_json")
        text = ""
        if isinstance(structured, dict):
            text = _extract_textish(structured.get("text")) or _extract_textish(structured.get("answer"))
        if not text:
            text = _extract_textish(output_json.get("normalized_text")) or _extract_textish(output_json.get("preview_text"))
        if not text:
            attempts.append(
                SurvivalAttempt(
                    backend="onemin",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="empty_output",
                )
            )
            return None
        self._clear_backend_failure("onemin")
        attempts.append(
            SurvivalAttempt(
                backend="onemin",
                started_at=started_at,
                completed_at=time.time(),
                status="completed",
                detail="ok",
            )
        )
        return SurvivalResult(
            text=text,
            provider_key="onemin",
            provider_backend=str(output_json.get("provider_backend") or "1min"),
            model=str(result.model_name or output_json.get("model") or _survival_onemin_model()),
            latency_ms=max(0, int((time.time() - started_at) * 1000)),
            attempts=tuple(attempts),
        )

    def try_gemini_vortex(
        self,
        *,
        packet: SurvivalPacket,
        attempts: list[SurvivalAttempt],
    ) -> SurvivalResult | None:
        started_at = time.time()
        if self._tool_execution is None:
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_vortex",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="tool_execution_unavailable",
                )
            )
            return None
        payload = {
            "source_text": self._render_packet(packet),
            "goal": packet.objective,
            "generation_instruction": (
                "Answer the user's request using the reduced survival packet. "
                "Return JSON with a single top-level `text` field only."
            ),
            "response_schema_json": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            "model": _env("EA_SURVIVAL_GEMINI_VORTEX_MODEL", _env("EA_GEMINI_VORTEX_MODEL", "")),
        }
        invocation = ToolInvocationRequest(
            session_id=f"survival:{uuid.uuid4().hex}",
            step_id=f"survival-step:{uuid.uuid4().hex}",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json=payload,
            context_json={"principal_id": self._principal_id},
        )
        try:
            result = self._tool_execution.execute_invocation(invocation)
        except ToolExecutionError as exc:
            failure = self._ui_failure_from_detail(str(exc), backend_hint="gemini_vortex")
            if failure is not None:
                self._record_backend_failure("gemini_vortex", failure)
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_vortex",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=(failure.code.value if failure is not None else str(exc)),
                )
            )
            return None
        output_json = dict(result.output_json or {})
        structured = output_json.get("structured_output_json")
        text = _extract_textish(structured if isinstance(structured, dict) else output_json) or _extract_textish(output_json.get("normalized_text"))
        if not text:
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_vortex",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="empty_output",
                )
            )
            return None
        self._clear_backend_failure("gemini_vortex")
        attempts.append(
            SurvivalAttempt(
                backend="gemini_vortex",
                started_at=started_at,
                completed_at=time.time(),
                status="completed",
                detail="ok",
            )
        )
        return SurvivalResult(
            text=text,
            provider_key="gemini_vortex",
            provider_backend="gemini_vortex_cli",
            model=str(result.model_name or output_json.get("model") or "gemini"),
            latency_ms=max(0, int((time.time() - started_at) * 1000)),
            attempts=tuple(attempts),
        )

    def try_browseract_gemini_web(
        self,
        *,
        packet: SurvivalPacket,
        attempts: list[SurvivalAttempt],
    ) -> SurvivalResult | None:
        started_at = time.time()
        if self._tool_execution is None:
            self._record_backend_failure(
                "gemini_web",
                UiLaneFailure(
                    provider_backend="gemini_web",
                    code=UiLaneFailureCode.lane_unavailable,
                    detail="tool_execution_unavailable",
                    retryable=True,
                    cooldown_seconds=_survival_unavailable_cooldown_seconds(),
                ),
            )
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_web",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="tool_execution_unavailable",
                )
            )
            return None
        binding_id = self._browseract_binding_id()
        if not binding_id:
            self._record_backend_failure(
                "gemini_web",
                UiLaneFailure(
                    provider_backend="gemini_web",
                    code=UiLaneFailureCode.lane_unavailable,
                    detail="browseract_binding_unavailable",
                    retryable=True,
                    cooldown_seconds=_survival_unavailable_cooldown_seconds(),
                ),
            )
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_web",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="browseract_binding_unavailable",
                )
            )
            return None
        invocation = ToolInvocationRequest(
            session_id=f"survival:{uuid.uuid4().hex}",
            step_id=f"survival-step:{uuid.uuid4().hex}",
            tool_name="browseract.gemini_web_generate",
            action_kind="content.generate",
            payload_json={
                "binding_id": binding_id,
                "packet": {
                    "objective": packet.objective,
                    "instructions": packet.instructions,
                    "condensed_history": packet.condensed_history,
                    "current_input": packet.current_input,
                    "desired_format": packet.desired_format,
                    "fingerprint": packet.fingerprint,
                },
                "mode": _survival_gemini_web_mode(),
                "deep_think": _survival_gemini_web_deep_think_allowed(),
                "timeout_seconds": _to_int(_env("EA_SURVIVAL_GEMINI_WEB_TIMEOUT_SECONDS", "600"), 600, minimum=60, maximum=1800),
            },
            context_json={"principal_id": self._principal_id},
        )
        try:
            result = self._tool_execution.execute_invocation(invocation)
        except ToolExecutionError as exc:
            failure = self._ui_failure_from_detail(str(exc), backend_hint="gemini_web")
            if failure is not None:
                self._record_backend_failure("gemini_web", failure)
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_web",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=(failure.code.value if failure is not None else str(exc)),
                )
            )
            return None
        output_json = dict(result.output_json or {})
        text = _extract_textish(output_json.get("text")) or _extract_textish(output_json.get("normalized_text"))
        if not text:
            failure = UiLaneFailure(
                provider_backend="gemini_web",
                code=UiLaneFailureCode.empty_output,
                detail="empty_output",
                retryable=True,
                cooldown_seconds=0,
            )
            attempts.append(
                SurvivalAttempt(
                    backend="gemini_web",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=failure.code.value,
                )
            )
            return None
        self._clear_backend_failure("gemini_web")
        attempts.append(
            SurvivalAttempt(
                backend="gemini_web",
                started_at=started_at,
                completed_at=time.time(),
                status="completed",
                detail="ok",
            )
        )
        return SurvivalResult(
            text=text,
            provider_key="browseract",
            provider_backend="gemini_web",
            model=str(output_json.get("mode_used") or _survival_gemini_web_mode()),
            latency_ms=max(0, int((time.time() - started_at) * 1000)),
            attempts=tuple(attempts),
        )

    def try_chatplayground_tiebreak(
        self,
        *,
        packet: SurvivalPacket,
        attempts: list[SurvivalAttempt],
    ) -> SurvivalResult | None:
        started_at = time.time()
        if self._tool_execution is None:
            self._record_backend_failure(
                "chatplayground",
                UiLaneFailure(
                    provider_backend="chatplayground",
                    code=UiLaneFailureCode.lane_unavailable,
                    detail="tool_execution_unavailable",
                    retryable=True,
                    cooldown_seconds=_survival_unavailable_cooldown_seconds(),
                ),
            )
            attempts.append(
                SurvivalAttempt(
                    backend="chatplayground",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="tool_execution_unavailable",
                )
            )
            return None
        binding_id = self._browseract_binding_id()
        if not binding_id:
            self._record_backend_failure(
                "chatplayground",
                UiLaneFailure(
                    provider_backend="chatplayground",
                    code=UiLaneFailureCode.lane_unavailable,
                    detail="browseract_binding_unavailable",
                    retryable=True,
                    cooldown_seconds=_survival_unavailable_cooldown_seconds(),
                ),
            )
            attempts.append(
                SurvivalAttempt(
                    backend="chatplayground",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="browseract_binding_unavailable",
                )
            )
            return None
        invocation = ToolInvocationRequest(
            session_id=f"survival:{uuid.uuid4().hex}",
            step_id=f"survival-step:{uuid.uuid4().hex}",
            tool_name="browseract.chatplayground_audit",
            action_kind="audit.factuality",
            payload_json={
                "binding_id": binding_id,
                "prompt": self._render_packet(packet),
                "roles": [_survival_chatplayground_role()],
                "scope": "survival",
                "max_chars": 12000,
            },
            context_json={"principal_id": self._principal_id},
        )
        try:
            result = self._tool_execution.execute_invocation(invocation)
        except ToolExecutionError as exc:
            failure = self._ui_failure_from_detail(str(exc), backend_hint="chatplayground")
            if failure is not None:
                self._record_backend_failure("chatplayground", failure)
            attempts.append(
                SurvivalAttempt(
                    backend="chatplayground",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=(failure.code.value if failure is not None else str(exc)),
                )
            )
            return None
        output_json = dict(result.output_json or {})
        structured = output_json.get("structured_output_json")
        if isinstance(structured, dict) and str(structured.get("status") or "").strip().lower() == "fallback":
            attempts.append(
                SurvivalAttempt(
                    backend="chatplayground",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail="fallback_only",
                )
            )
            return None
        text = (
            _extract_textish(output_json.get("consensus"))
            or _extract_textish(output_json.get("summary"))
            or _extract_textish(output_json.get("recommendation"))
            or _extract_textish(output_json.get("normalized_text"))
        )
        if not text:
            failure = UiLaneFailure(
                provider_backend="chatplayground",
                code=UiLaneFailureCode.empty_output,
                detail="empty_output",
                retryable=True,
                cooldown_seconds=0,
            )
            attempts.append(
                SurvivalAttempt(
                    backend="chatplayground",
                    started_at=started_at,
                    completed_at=time.time(),
                    status="failed",
                    detail=failure.code.value,
                )
            )
            return None
        self._clear_backend_failure("chatplayground")
        attempts.append(
            SurvivalAttempt(
                backend="chatplayground",
                started_at=started_at,
                completed_at=time.time(),
                status="completed",
                detail="ok",
            )
        )
        return SurvivalResult(
            text=text,
            provider_key="browseract",
            provider_backend="chatplayground",
            model="chatplayground",
            latency_ms=max(0, int((time.time() - started_at) * 1000)),
            attempts=tuple(attempts),
        )

    def _browseract_binding_id(self) -> str:
        if self._tool_runtime is None:
            return ""
        if self._principal_id:
            try:
                bindings = self._tool_runtime.list_connector_bindings(self._principal_id, limit=100)
            except Exception:
                bindings = []
            for binding in bindings:
                connector_name = str(getattr(binding, "connector_name", "") or "").strip().lower()
                status = str(getattr(binding, "status", "") or "").strip().lower()
                if connector_name != "browseract":
                    continue
                if status and status != "enabled":
                    continue
                return str(getattr(binding, "binding_id", "") or "").strip()
        try:
            bindings = self._tool_runtime.list_connector_bindings_for_connector("browseract", limit=100)
        except Exception:
            return ""
        for binding in bindings:
            status = str(getattr(binding, "status", "") or "").strip().lower()
            if status and status != "enabled":
                continue
            return str(getattr(binding, "binding_id", "") or "").strip()
        return ""

    def _render_packet(self, packet: SurvivalPacket) -> str:
        parts = [f"Objective:\n{packet.objective}"]
        if packet.instructions:
            parts.append(f"Instructions:\n{packet.instructions}")
        if packet.condensed_history:
            parts.append(f"Condensed history:\n{packet.condensed_history}")
        parts.append(f"Current input:\n{packet.current_input}")
        if packet.desired_format:
            parts.append(f"Desired format:\n{packet.desired_format}")
        parts.append("Rules:\n- Continue the task.\n- Be concise and actionable.\n- Do not require extra context unless blocked.")
        return "\n\n".join(part for part in parts if part).strip()

    def _backend_cooldown_failure(self, backend: str) -> UiLaneFailure | None:
        return _current_backend_failure(backend)

    def _clear_backend_failure(self, backend: str) -> None:
        _clear_backend_failure_state(backend)

    def _record_backend_failure(self, backend: str, failure: UiLaneFailure) -> None:
        _record_backend_failure_state(backend, failure)

    def _ui_failure_from_detail(self, detail: str, *, backend_hint: str) -> UiLaneFailure | None:
        normalized = str(detail or "").strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered.startswith("ui_lane_failure:"):
            parts = normalized.split(":", 3)
            backend = backend_hint or (parts[1] if len(parts) > 1 else "")
            code_raw = parts[2] if len(parts) > 2 else ""
            try:
                code = UiLaneFailureCode(str(code_raw or "").strip().lower())
            except ValueError:
                return None
            cooldown = 0
            if code in {
                UiLaneFailureCode.challenge_required,
                UiLaneFailureCode.challenge_loop,
                UiLaneFailureCode.session_expired,
            }:
                cooldown = _ui_challenge_cooldown_seconds()
            elif code == UiLaneFailureCode.lane_unavailable:
                cooldown = _survival_unavailable_cooldown_seconds()
            extra_detail = parts[3] if len(parts) > 3 else normalized
            return UiLaneFailure(
                provider_backend=str(backend or backend_hint or "").strip().lower(),
                code=code,
                detail=extra_detail,
                retryable=(code != UiLaneFailureCode.empty_output),
                cooldown_seconds=cooldown,
            )
        if "session_expired" in lowered:
            return UiLaneFailure(
                provider_backend=backend_hint,
                code=UiLaneFailureCode.session_expired,
                detail=normalized,
                retryable=True,
                cooldown_seconds=_ui_challenge_cooldown_seconds(),
            )
        if "timeout" in lowered:
            return UiLaneFailure(
                provider_backend=backend_hint,
                code=UiLaneFailureCode.timeout,
                detail=normalized,
                retryable=True,
                cooldown_seconds=0,
            )
        if "empty_output" in lowered:
            return UiLaneFailure(
                provider_backend=backend_hint,
                code=UiLaneFailureCode.empty_output,
                detail=normalized,
                retryable=True,
                cooldown_seconds=0,
            )
        if "unavailable" in lowered:
            return UiLaneFailure(
                provider_backend=backend_hint,
                code=UiLaneFailureCode.lane_unavailable,
                detail=normalized,
                retryable=True,
                cooldown_seconds=_survival_unavailable_cooldown_seconds(),
            )
        return None
