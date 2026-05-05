from __future__ import annotations

import fcntl
import json
import os
import shlex
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError

_DEFAULT_GEMINI_AUTH_ACCOUNT = "EA_GEMINI_VORTEX_DEFAULT_AUTH"
_GEMINI_FALLBACK_KEY_PREFIX = "GOOGLE_API_KEY_FALLBACK_"
_UTC = timezone.utc


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


def _normalize_cli_model_name(raw_model: str) -> str:
    model = str(raw_model or "").strip()
    if not model:
        return ""
    prefix = "gemini_vortex:"
    if model.startswith(prefix):
        candidate = model[len(prefix) :].strip()
        if candidate:
            return candidate
    return model


def _clean_cli_failure_detail(raw_detail: str) -> str:
    text = str(raw_detail or "").strip()
    if not text:
        return "gemini_vortex_failed"
    filtered: list[str] = []
    skip_trace_hint = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("(node:") and "DeprecationWarning:" in stripped and "punycode" in stripped:
            skip_trace_hint = True
            continue
        if skip_trace_hint and stripped.startswith("(Use `node --trace-deprecation"):
            skip_trace_hint = False
            continue
        skip_trace_hint = False
        if stripped == "YOLO mode is enabled. All tool calls will be automatically approved.":
            continue
        if stripped == "Loaded cached credentials.":
            continue
        filtered.append(stripped)
    cleaned = "\n".join(filtered).strip()
    return cleaned or text


def _provider_ledger_dir() -> Path | None:
    raw = _env_value("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "/tmp/ea_provider_ledger"
    if not raw:
        return None
    try:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value).astimezone(_UTC)
    except Exception:
        return None


def _gemini_fallback_key_env_names() -> tuple[str, ...]:
    entries: list[tuple[int, str]] = []
    for name, value in os.environ.items():
        if not name.startswith(_GEMINI_FALLBACK_KEY_PREFIX):
            continue
        if not str(value or "").strip():
            continue
        suffix = name.removeprefix(_GEMINI_FALLBACK_KEY_PREFIX)
        priority = int(suffix) if suffix.isdigit() else 10_000
        entries.append((priority, name))
    entries.sort(key=lambda item: (item[0], item[1]))
    return tuple(name for _, name in entries)


def _gemini_selection_mode() -> str:
    raw = _env_value("EA_GEMINI_VORTEX_SELECTION_MODE").lower()
    if raw in {"fallback", "round_robin"}:
        return raw
    return "round_robin" if _gemini_fallback_key_env_names() else "fallback"


def _next_round_robin_index(slot_count: int) -> int:
    if slot_count <= 1:
        return 0
    root = _provider_ledger_dir()
    if root is None:
        return 0
    target = root / "gemini_vortex_slot_index"
    try:
        with target.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            raw = handle.read().strip()
            current = int(raw) if raw else -1
            next_index = (current + 1) % slot_count
            handle.seek(0)
            handle.truncate()
            handle.write(str(next_index))
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return next_index
    except Exception:
        return 0


def _slot_env_suffix(slot: str) -> str:
    return str(slot or "default").strip().upper().replace("-", "_")


def _slot_owner(slot: str) -> str:
    return _env_value(f"EA_GEMINI_VORTEX_SLOT_{_slot_env_suffix(slot)}_OWNER")


def _slot_quota_posture(slot: str) -> str:
    return _env_value(f"EA_GEMINI_VORTEX_SLOT_{_slot_env_suffix(slot)}_QUOTA_POSTURE")


def _slot_lease_seconds() -> int:
    raw = _env_value("EA_GEMINI_VORTEX_SLOT_LEASE_SECONDS") or "900"
    try:
        return max(30, int(raw))
    except Exception:
        return 900


def _slot_ledger_path() -> Path | None:
    root = _provider_ledger_dir()
    if root is None:
        return None
    return root / "gemini_vortex_slots.json"


def _load_slot_ledger() -> dict[str, dict[str, Any]]:
    target = _slot_ledger_path()
    if target is None:
        return {}
    try:
        if not target.exists():
            return {}
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    payload: dict[str, dict[str, Any]] = {}
    for slot, item in loaded.items():
        if isinstance(item, dict):
            payload[str(slot)] = dict(item)
    return payload


def _save_slot_ledger(payload: dict[str, dict[str, Any]]) -> None:
    target = _slot_ledger_path()
    if target is None:
        return
    try:
        target.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    except Exception:
        return


def _lease_is_active(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    current = now or datetime.now(_UTC)
    lease_expires_at = _parse_iso(str(entry.get("lease_expires_at") or ""))
    return bool(lease_expires_at and lease_expires_at > current)


@dataclass(frozen=True)
class GeminiAuthSlot:
    slot: str
    account_name: str
    fallback_key_env_name: str | None = None


def gemini_vortex_slot_status() -> list[dict[str, Any]]:
    adapter = GeminiVortexToolAdapter()
    ledger = _load_slot_ledger()
    now = datetime.now(_UTC)
    payload: list[dict[str, Any]] = []
    for slot in adapter._auth_slots():
        entry = dict(ledger.get(slot.slot) or {})
        active_lease = _lease_is_active(entry, now=now)
        payload.append(
            {
                "slot": slot.slot,
                "account_name": slot.account_name,
                "configured": True,
                "slot_owner": _slot_owner(slot.slot),
                "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
                "active_lease": active_lease,
                "lease_holder": str(entry.get("lease_holder") or "") if active_lease else "",
                "lease_expires_at": str(entry.get("lease_expires_at") or "") if active_lease else "",
                "last_used_principal_id": str(entry.get("lease_holder") or ""),
                "last_used_at": str(entry.get("last_used_at") or ""),
                "last_result": str(entry.get("last_result") or ""),
                "last_result_detail": str(entry.get("last_result_detail") or ""),
            }
        )
    return payload


class GeminiVortexToolAdapter:
    def _command_base(self) -> list[str]:
        raw = _env_value("EA_GEMINI_VORTEX_COMMAND") or "gemini"
        return shlex.split(raw)

    def _default_model(self) -> str:
        return _env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-2.5-flash"

    def _timeout_seconds(self, payload: dict[str, Any] | None = None) -> int:
        raw = _env_value("EA_GEMINI_VORTEX_TIMEOUT_SECONDS") or "300"
        try:
            configured_timeout = max(15, int(raw))
        except Exception:
            configured_timeout = 300
        requested_timeout = 0
        if isinstance(payload, dict):
            try:
                requested_timeout = max(0, int(payload.get("timeout_seconds") or 0))
            except Exception:
                requested_timeout = 0
        if requested_timeout > 0:
            return max(15, min(configured_timeout, requested_timeout))
        return configured_timeout

    def _auth_slots(self) -> tuple[GeminiAuthSlot, ...]:
        slots = [GeminiAuthSlot(slot="default", account_name=_DEFAULT_GEMINI_AUTH_ACCOUNT)]
        for index, env_name in enumerate(_gemini_fallback_key_env_names(), start=1):
            slots.append(
                GeminiAuthSlot(
                    slot=f"fallback_{index}",
                    account_name=env_name,
                    fallback_key_env_name=env_name,
                )
            )
        return tuple(slots)

    def _ordered_auth_slots(self) -> tuple[GeminiAuthSlot, ...]:
        slots = self._auth_slots()
        if len(slots) <= 1 or _gemini_selection_mode() != "round_robin":
            return slots
        start = _next_round_robin_index(len(slots))
        return slots[start:] + slots[:start]

    def _select_auth_slots(self, *, principal_id: str) -> tuple[GeminiAuthSlot, ...]:
        ordered = list(self._ordered_auth_slots())
        if not ordered:
            return ()
        clean_principal = str(principal_id or "").strip()
        if not clean_principal:
            return tuple(ordered)
        ledger = _load_slot_ledger()
        now = datetime.now(_UTC)
        same_principal = next(
            (
                slot
                for slot in ordered
                if str((ledger.get(slot.slot) or {}).get("lease_holder") or "") == clean_principal
                and _lease_is_active(dict(ledger.get(slot.slot) or {}), now=now)
            ),
            None,
        )
        if same_principal is not None:
            return tuple([same_principal, *[slot for slot in ordered if slot.slot != same_principal.slot]])
        available = next(
            (
                slot
                for slot in ordered
                if not _lease_is_active(dict(ledger.get(slot.slot) or {}), now=now)
            ),
            None,
        )
        if available is not None:
            return tuple([available, *[slot for slot in ordered if slot.slot != available.slot]])
        return tuple(ordered)

    def _record_slot_usage(
        self,
        slot: GeminiAuthSlot,
        *,
        principal_id: str,
        success: bool,
        detail: str = "",
    ) -> dict[str, str]:
        now = datetime.now(_UTC)
        lease_holder = str(principal_id or "").strip()
        lease_expires_at = (
            (now + timedelta(seconds=_slot_lease_seconds())).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if lease_holder
            else ""
        )
        ledger = _load_slot_ledger()
        ledger[slot.slot] = {
            "account_name": slot.account_name,
            "slot_owner": _slot_owner(slot.slot),
            "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
            "lease_holder": lease_holder,
            "lease_expires_at": lease_expires_at,
            "last_used_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "last_result": "ready" if success else "failed",
            "last_result_detail": str(detail or "").strip()[:400],
        }
        _save_slot_ledger(ledger)
        return {
            "lease_holder": lease_holder,
            "lease_expires_at": lease_expires_at,
            "slot_owner": _slot_owner(slot.slot),
            "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
        }

    def _command_env(self, slot: GeminiAuthSlot) -> dict[str, str]:
        env = dict(os.environ)
        if slot.fallback_key_env_name:
            api_key = _env_value(slot.fallback_key_env_name)
            if api_key:
                env["GOOGLE_API_KEY"] = api_key
                env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        return env

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        source_text = str(payload.get("normalized_text") or payload.get("source_text") or "").strip()
        if not source_text:
            raise ToolExecutionError("source_text_required")
        prompt_parts: list[str] = []
        generation_instruction = str(payload.get("generation_instruction") or payload.get("instructions") or "").strip()
        if generation_instruction:
            prompt_parts.append(generation_instruction)
        goal = str(payload.get("goal") or "").strip()
        if goal:
            prompt_parts.append(f"Goal: {goal}")
        response_schema = payload.get("response_schema_json")
        if isinstance(response_schema, dict) and response_schema:
            prompt_parts.append(
                "Return JSON only. Match this schema contract as closely as possible:\n"
                + json.dumps(response_schema, ensure_ascii=True)
            )
        else:
            prompt_parts.append("Return JSON only. No markdown fences, no commentary.")
        context_pack = payload.get("context_pack")
        if isinstance(context_pack, dict) and context_pack:
            prompt_parts.append("Context pack:\n" + json.dumps(context_pack, ensure_ascii=True))
        prompt_parts.append(source_text)
        return "\n\n".join(part for part in prompt_parts if part).strip()

    def _extract_response_text(self, stdout: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        raw = str(stdout or "").strip()
        if not raw:
            raise ToolExecutionError("gemini_vortex_empty_output")
        try:
            envelope = json.loads(raw)
        except Exception:
            return raw, {}, {}
        if not isinstance(envelope, dict):
            return raw, {}, {}
        response = str(envelope.get("response") or "").strip()
        stats = envelope.get("stats") if isinstance(envelope.get("stats"), dict) else {}
        if response:
            return response, envelope, stats
        return raw, envelope, stats

    def _parse_structured(self, text: str) -> tuple[str, dict[str, Any], str]:
        cleaned = _strip_fences(text)
        try:
            loaded = json.loads(cleaned)
        except Exception:
            return cleaned, {}, "text/plain"
        if isinstance(loaded, dict):
            return json.dumps(loaded, indent=2, ensure_ascii=True), loaded, "application/json"
        return json.dumps(loaded, indent=2, ensure_ascii=True), {"result": loaded}, "application/json"

    def _token_counts(self, stats: dict[str, Any]) -> tuple[int, int]:
        total_in = 0
        total_out = 0
        models = stats.get("models")
        if not isinstance(models, dict):
            return (0, 0)
        for row in models.values():
            if not isinstance(row, dict):
                continue
            tokens = row.get("tokens")
            if not isinstance(tokens, dict):
                continue
            total_in += int(tokens.get("input") or 0)
            total_out += int(tokens.get("candidates") or tokens.get("output") or 0)
        return (total_in, total_out)

    def execute(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        model = _normalize_cli_model_name(str(payload.get("model") or self._default_model()).strip()) or self._default_model()
        principal_id = str((request.context_json or {}).get("principal_id") or payload.get("principal_id") or "").strip()
        command = self._command_base() + [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "yolo",
        ]
        if model:
            command.extend(["-m", model])
        ordered_slots = self._select_auth_slots(principal_id=principal_id)
        completed: subprocess.CompletedProcess[str] | None = None
        selected_slot = ordered_slots[0]
        selected_lease = {
            "lease_holder": "",
            "lease_expires_at": "",
            "slot_owner": _slot_owner(selected_slot.slot),
            "quota_posture": _slot_quota_posture(selected_slot.slot) or "unknown",
        }
        failures: list[str] = []
        for slot in ordered_slots:
            try:
                completed = subprocess.run(
                    command,
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_seconds(payload),
                    env=self._command_env(slot),
                )
                selected_slot = slot
                selected_lease = self._record_slot_usage(slot, principal_id=principal_id, success=True)
                break
            except FileNotFoundError as exc:
                raise ToolExecutionError("gemini_vortex_cli_missing") from exc
            except subprocess.TimeoutExpired as exc:
                raise ToolExecutionError("gemini_vortex_timeout") from exc
            except subprocess.CalledProcessError as exc:
                detail = _clean_cli_failure_detail(exc.stderr or "")
                if detail == "gemini_vortex_failed":
                    detail = _clean_cli_failure_detail(exc.stdout or "")
                self._record_slot_usage(slot, principal_id=principal_id, success=False, detail=detail)
                failures.append(f"{slot.account_name}:{detail[:160]}")
        if completed is None:
            summary = " | ".join(failures) if failures else "gemini_vortex_failed"
            raise ToolExecutionError(f"gemini_vortex_failed:{summary[:400]}")
        response_text, envelope, stats = self._extract_response_text(completed.stdout or "")
        normalized_text, structured_output_json, mime_type = self._parse_structured(response_text)
        tokens_in, tokens_out = self._token_counts(stats)
        action_kind = str(request.action_kind or "content.generate") or "content.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"gemini-vortex:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": model,
                "provider_key_slot": selected_slot.slot,
                "provider_account_name": selected_slot.account_name,
                "lease_holder": selected_lease["lease_holder"],
                "lease_expires_at": selected_lease["lease_expires_at"],
                "slot_owner": selected_lease["slot_owner"],
                "quota_posture": selected_lease["quota_posture"],
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "model": model,
                "prompt_length": len(prompt),
                "mime_type": mime_type,
                "structured": bool(structured_output_json),
                "tool_version": definition.version,
                "provider_key_slot": selected_slot.slot,
                "provider_account_name": selected_slot.account_name,
                "lease_holder": selected_lease["lease_holder"],
                "lease_expires_at": selected_lease["lease_expires_at"],
                "slot_owner": selected_lease["slot_owner"],
                "quota_posture": selected_lease["quota_posture"],
                "selection_mode": _gemini_selection_mode(),
                "response_envelope_keys": sorted(envelope.keys()) if isinstance(envelope, dict) else [],
            },
            model_name=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )
