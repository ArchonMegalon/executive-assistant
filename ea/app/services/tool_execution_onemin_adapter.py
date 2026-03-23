from __future__ import annotations

import json
import os
import uuid
from typing import Any

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw


def _parse_structured(text: str) -> tuple[str, dict[str, Any], str]:
    cleaned = _strip_fences(text)
    try:
        loaded = json.loads(cleaned)
    except Exception:
        return cleaned, {}, "text/plain"
    if isinstance(loaded, dict):
        return json.dumps(loaded, indent=2, ensure_ascii=True), loaded, "application/json"
    return json.dumps(loaded, indent=2, ensure_ascii=True), {"result": loaded}, "application/json"


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "prompt", "source_text", "normalized_text", "diff_text", "instructions", "goal"):
            text = _extract_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


def _collect_asset_urls(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        candidate = value.strip()
        lowered = candidate.lower()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            found.append(candidate)
        elif (
            candidate.startswith("/")
            and any(token in lowered for token in ("/asset/", "/image/", "/render/", "/download/"))
        ):
            found.append("https://api.1min.ai" + candidate)
    elif isinstance(value, dict):
        for key in ("url", "image_url", "download_url", "image", "imageUrl", "asset_url", "assetUrl"):
            if key in value:
                found.extend(_collect_asset_urls(value.get(key)))
        for nested in value.values():
            found.extend(_collect_asset_urls(nested))
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            found.extend(_collect_asset_urls(nested))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in found:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


class OneminToolAdapter:
    def _request_principal_id(self, request: ToolInvocationRequest) -> str:
        context_json = dict(request.context_json or {})
        return str(context_json.get("principal_id") or "").strip()

    def _manager_candidates(
        self,
        *,
        upstream: Any,
        key_names: tuple[str, ...],
        filtered_key_names: tuple[str, ...],
        active_key_names: tuple[str, ...],
    ) -> list[dict[str, object]]:
        provider_health = upstream._provider_health_report()
        onemin_slots = list((((provider_health.get("providers") or {}).get("onemin") or {}).get("slots") or []))
        slot_by_account = {
            str(slot.get("account_name") or "").strip(): dict(slot)
            for slot in onemin_slots
            if isinstance(slot, dict) and str(slot.get("account_name") or "").strip()
        }
        slot_by_name = {
            str(slot.get("slot") or "").strip(): dict(slot)
            for slot in onemin_slots
            if isinstance(slot, dict) and str(slot.get("slot") or "").strip()
        }
        state_snapshot = upstream._onemin_states_snapshot(filtered_key_names)
        manager_candidates: list[dict[str, object]] = []
        for selected_key in filtered_key_names:
            account_name = upstream._provider_account_name("onemin", key_names=key_names, key=selected_key)
            slot_name = upstream._onemin_key_slot(selected_key, key_names=key_names)
            slot_row = slot_by_account.get(account_name) or slot_by_name.get(slot_name) or {}
            state = state_snapshot.get(selected_key)
            if state is None:
                state = upstream.OneminKeyState(key=selected_key)
            manager_candidates.append(
                {
                    "api_key": selected_key,
                    "account_id": account_name,
                    "account_name": account_name,
                    "credential_id": slot_name or account_name,
                    "slot_name": slot_name,
                    "secret_env_name": str(slot_row.get("slot_env_name") or account_name or ""),
                    "slot_role": slot_row.get("slot_role")
                    or upstream._onemin_slot_role_for_key(
                        selected_key,
                        active_keys=active_key_names,
                        reserve_keys=upstream._onemin_reserve_keys(),
                    ),
                    "state": slot_row.get("state") or upstream._onemin_key_state_label(state, now=upstream._now_epoch()),
                    "estimated_remaining_credits": slot_row.get("estimated_remaining_credits"),
                    "billing_remaining_credits": slot_row.get("billing_remaining_credits"),
                    "billing_max_credits": slot_row.get("billing_max_credits"),
                    "billing_next_topup_at": slot_row.get("billing_next_topup_at"),
                    "failure_count": state.failure_count,
                    "last_success_at": state.last_success_at,
                    "last_used_at": state.last_used_at,
                    "last_error": state.last_error,
                }
            )
        return manager_candidates

    def _default_code_model(self) -> str:
        from app.services import responses_upstream as upstream

        return _env_value("EA_ONEMIN_TOOL_CODE_MODEL") or next(iter(upstream._onemin_hard_models()), "gpt-5")

    def _default_review_model(self) -> str:
        from app.services import responses_upstream as upstream

        return _env_value("EA_ONEMIN_TOOL_REVIEW_MODEL") or next(iter(upstream._onemin_review_models()), "deepseek-chat")

    def _default_image_model(self) -> str:
        return _env_value("EA_ONEMIN_TOOL_IMAGE_MODEL") or "gpt-image-1-mini"

    def _default_media_model(self) -> str:
        return _env_value("EA_ONEMIN_TOOL_MEDIA_MODEL") or self._default_image_model()

    def _build_code_prompt(self, payload: dict[str, Any]) -> str:
        prompt = _extract_text(payload.get("prompt") or payload.get("source_text") or payload.get("normalized_text"))
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.onemin.code_generate")
        instructions = _extract_text(payload.get("instructions"))
        goal = _extract_text(payload.get("goal"))
        context_pack = payload.get("context_pack")
        parts: list[str] = []
        if instructions:
            parts.append(instructions)
        if goal:
            parts.append(f"Goal: {goal}")
        if isinstance(context_pack, dict) and context_pack:
            parts.append("Context:\n" + json.dumps(context_pack, ensure_ascii=True))
        parts.append(prompt)
        return "\n\n".join(part for part in parts if part).strip()

    def _build_review_prompt(self, payload: dict[str, Any]) -> str:
        diff_text = _extract_text(payload.get("diff_text"))
        source_text = _extract_text(payload.get("source_text") or payload.get("normalized_text") or payload.get("prompt"))
        if not diff_text and not source_text:
            raise ToolExecutionError("review_material_required:provider.onemin.reasoned_patch_review")
        focus = _extract_text(payload.get("review_focus"))
        instructions = _extract_text(payload.get("instructions"))
        goal = _extract_text(payload.get("goal")) or "Review the proposed patch and call out concrete risks."
        parts = [
            instructions or "Perform a bounded technical review and prioritize concrete defects, regressions, and missing guards.",
            f"Goal: {goal}",
            f"Focus: {focus}" if focus else "",
            "Diff:\n" + diff_text if diff_text else "",
            "Additional material:\n" + source_text if source_text else "",
            "Return a concise review. Prefer findings first.",
        ]
        return "\n\n".join(part for part in parts if part).strip()

    def _call_text(
        self,
        *,
        prompt: str,
        model: str,
        lane: str,
        principal_id: str = "",
    ):
        from app.services import responses_upstream as upstream

        config = upstream._provider_configs().get("onemin")
        if config is None or not config.api_keys:
            raise ToolExecutionError("onemin_missing_api_key")
        try:
            return upstream._call_onemin(
                config,
                prompt=prompt,
                messages=None,
                model=model,
                max_output_tokens=None,
                lane=lane,
                principal_id=principal_id,
            )
        except upstream.ResponsesUpstreamError as exc:
            raise ToolExecutionError(f"onemin_failed:{str(exc)[:400]}") from exc

    def _call_feature(
        self,
        *,
        feature_payload: dict[str, object],
        lane: str,
        capability: str,
        principal_id: str = "",
    ) -> tuple[dict[str, Any], str, str, str, int, int]:
        from app.services import responses_upstream as upstream
        from app.services.onemin_manager import active_onemin_manager

        config = upstream._provider_configs().get("onemin")
        if config is None or not config.api_keys:
            raise ToolExecutionError("onemin_missing_api_key")

        key_names = tuple(config.api_keys)
        active_key_names = upstream._ordered_onemin_keys_allow_reserve(False)
        all_key_names = upstream._ordered_onemin_keys_allow_reserve(True)
        allow_reserve = False
        tested: set[str] = set()
        errors: list[str] = []
        selection_request_id = f"onemin-tool-{uuid.uuid4().hex[:16]}"
        manager = active_onemin_manager()

        while len(tested) < len(all_key_names):
            candidate_key_names = active_key_names if not allow_reserve else all_key_names
            filtered_key_names = tuple(key for key in candidate_key_names if key not in tested)
            manager_lease_id = ""
            manager_selection: dict[str, object] | None = None
            if manager is not None and filtered_key_names:
                manager_selection = manager.reserve_for_candidates(
                    candidates=self._manager_candidates(
                        upstream=upstream,
                        key_names=key_names,
                        filtered_key_names=filtered_key_names,
                        active_key_names=active_key_names,
                    ),
                    lane=lane,
                    capability=capability,
                    principal_id=principal_id,
                    request_id=selection_request_id,
                    estimated_credits=None,
                    allow_reserve=allow_reserve,
                )
            if manager_selection is not None:
                api_key = str(manager_selection.get("api_key") or "")
                wait_until = 0.0
                manager_lease_id = str(manager_selection.get("lease_id") or "")
            else:
                key_pick = upstream._pick_onemin_key(allow_reserve=allow_reserve)
                if key_pick is None:
                    if not allow_reserve and len(all_key_names) > len(active_key_names):
                        allow_reserve = True
                        continue
                    break
                api_key, wait_until, _ = key_pick
            if api_key in tested:
                if (
                    not allow_reserve
                    and len(all_key_names) > len(active_key_names)
                    and all(key in tested for key in active_key_names)
                ):
                    allow_reserve = True
                upstream._rotate_onemin_cursor_after_key_usage(api_key)
                continue
            tested.add(api_key)
            if wait_until > 0:
                errors.append(f"cooldown_until_{int(wait_until)}")
                upstream._rotate_onemin_cursor_after_key_usage(api_key)
                continue

            def _release_failed(error_text: str) -> None:
                nonlocal manager_lease_id
                if manager is not None and manager_lease_id:
                    manager.release_lease(
                        lease_id=manager_lease_id,
                        status="failed",
                        error=str(error_text or "").strip() or "onemin_feature_failed",
                    )
                    manager_lease_id = ""

            upstream._mark_onemin_request_start(api_key)
            key_slot = upstream._onemin_key_slot(api_key, key_names=key_names)
            account_name = upstream._provider_account_name("onemin", key_names=key_names, key=api_key)
            started_at = upstream._now_ms()
            try:
                status, payload = upstream._post_json(
                    url=upstream._onemin_code_url(),
                    headers={"API-KEY": api_key},
                    payload=feature_payload,
                    timeout_seconds=config.timeout_seconds,
                )
            except upstream.ResponsesUpstreamError as exc:
                detail = str(exc or "").strip() or "request_failed"
                upstream._mark_onemin_failure(
                    api_key,
                    detail,
                    temporary_quarantine=False,
                )
                _release_failed(detail)
                errors.append(f"{key_slot}:{detail}")
                continue
            except Exception as exc:
                _release_failed(str(exc))
                raise
            latency_ms = upstream._now_ms() - started_at
            if status < 200 or status >= 300:
                detail = upstream._trim_error_payload(payload)
                if upstream._is_auth_error(detail):
                    quarantine_seconds = (
                        upstream._deleted_onemin_key_quarantine_seconds()
                        if upstream._is_deleted_onemin_key_error(detail)
                        else None
                    )
                    upstream._mark_onemin_failure(
                        api_key,
                        detail,
                        temporary_quarantine=True,
                        quarantine_seconds=quarantine_seconds,
                    )
                else:
                    upstream._mark_onemin_failure(
                        api_key,
                        detail,
                        temporary_quarantine=False,
                    )
                _release_failed(detail)
                errors.append(f"{key_slot}:http_{status}:{detail}")
                continue
            if not isinstance(payload, dict):
                upstream._mark_onemin_failure(api_key, "invalid_payload", temporary_quarantine=False)
                _release_failed("invalid_payload")
                errors.append(f"{key_slot}:invalid_payload")
                continue

            onemin_error = upstream._extract_onemin_error(payload)
            if onemin_error:
                if upstream._is_auth_error(onemin_error):
                    quarantine_seconds = (
                        upstream._deleted_onemin_key_quarantine_seconds()
                        if upstream._is_deleted_onemin_key_error(onemin_error)
                        else None
                    )
                    upstream._mark_onemin_failure(
                        api_key,
                        onemin_error,
                        temporary_quarantine=True,
                        quarantine_seconds=quarantine_seconds,
                    )
                else:
                    upstream._mark_onemin_failure(api_key, onemin_error, temporary_quarantine=False)
                _release_failed(onemin_error)
                errors.append(f"{key_slot}:{onemin_error}")
                continue

            resolved_model = upstream._extract_onemin_model(payload) or str(feature_payload.get("model") or "").strip()
            tokens_in = 0
            tokens_out = 0
            usage = payload.get("usage")
            if isinstance(usage, dict):
                tokens_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                tokens_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            upstream._record_onemin_usage_event(
                api_key=api_key,
                model=resolved_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                lane=lane,
            )
            upstream._mark_onemin_success(api_key)
            if manager is not None and manager_lease_id:
                manager.record_usage(lease_id=manager_lease_id, actual_credits_delta=None, status="success")
                manager.release_lease(lease_id=manager_lease_id, status="released")
            return payload, account_name, key_slot, resolved_model, tokens_in, tokens_out

        raise ToolExecutionError(f"onemin_feature_failed:{'; '.join(errors)[:400] or 'unavailable'}")

    def execute_code_generate(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_code_prompt(payload)
        model = str(payload.get("model") or self._default_code_model()).strip() or self._default_code_model()
        result = self._call_text(
            prompt=prompt,
            model=model,
            lane="hard",
            principal_id=self._request_principal_id(request),
        )
        normalized_text, structured_output_json, mime_type = _parse_structured(result.text)
        action_kind = str(request.action_kind or "code.generate") or "code.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"onemin:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": result.model,
                "provider_backend": result.provider_backend or "1min",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "onemin",
                "provider_backend": result.provider_backend or "1min",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "model": result.model,
                "tool_version": definition.version,
            },
            model_name=result.model,
            tokens_in=int(result.tokens_in or 0),
            tokens_out=int(result.tokens_out or 0),
            cost_usd=0.0,
        )

    def execute_reasoned_patch_review(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_review_prompt(payload)
        model = str(payload.get("model") or self._default_review_model()).strip() or self._default_review_model()
        result = self._call_text(
            prompt=prompt,
            model=model,
            lane="review",
            principal_id=self._request_principal_id(request),
        )
        normalized_text, structured_output_json, mime_type = _parse_structured(result.text)
        action_kind = str(request.action_kind or "code.review") or "code.review"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"onemin:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": result.model,
                "provider_backend": result.provider_backend or "1min",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "onemin",
                "provider_backend": result.provider_backend or "1min",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "model": result.model,
                "tool_version": definition.version,
            },
            model_name=result.model,
            tokens_in=int(result.tokens_in or 0),
            tokens_out=int(result.tokens_out or 0),
            cost_usd=0.0,
        )

    def execute_image_generate(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = _extract_text(payload.get("prompt"))
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.onemin.image_generate")
        model = str(payload.get("model") or self._default_image_model()).strip() or self._default_image_model()
        prompt_object: dict[str, object] = {
            "prompt": prompt,
            "n": int(payload.get("n") or 1),
            "quality": str(payload.get("quality") or "low"),
            "output_format": str(payload.get("output_format") or "png"),
        }
        size = str(payload.get("size") or "").strip()
        aspect_ratio = str(payload.get("aspect_ratio") or "").strip()
        if size:
            prompt_object["size"] = size
        if aspect_ratio:
            prompt_object["aspect_ratio"] = aspect_ratio
        feature_payload = {
            "type": "IMAGE_GENERATOR",
            "model": model,
            "promptObject": prompt_object,
        }
        raw_response, account_name, key_slot, resolved_model, tokens_in, tokens_out = self._call_feature(
            feature_payload=feature_payload,
            lane="hard",
            capability="image_generate",
            principal_id=self._request_principal_id(request),
        )
        asset_urls = _collect_asset_urls(raw_response)
        normalized_text = json.dumps(
            {
                "asset_urls": asset_urls,
                "model": resolved_model,
                "provider_account_name": account_name,
            },
            ensure_ascii=True,
        )
        action_kind = str(request.action_kind or "image.generate") or "image.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"onemin:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": {
                    "asset_urls": asset_urls,
                    "raw_response": raw_response,
                },
                "preview_text": _preview_text(asset_urls[0] if asset_urls else normalized_text),
                "mime_type": "application/json",
                "model": resolved_model,
                "asset_urls": asset_urls,
                "provider_backend": "1min",
                "provider_account_name": account_name,
                "provider_key_slot": key_slot,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "onemin",
                "provider_backend": "1min",
                "provider_account_name": account_name,
                "provider_key_slot": key_slot,
                "model": resolved_model,
                "feature_type": "IMAGE_GENERATOR",
                "tool_version": definition.version,
            },
            model_name=resolved_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )

    def execute_media_transform(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        feature_type = str(payload.get("feature_type") or "").strip().upper()
        prompt = _extract_text(payload.get("prompt") or payload.get("source_text"))
        if not feature_type:
            raise ToolExecutionError("feature_type_required:provider.onemin.media_transform")
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.onemin.media_transform")
        model = str(payload.get("model") or self._default_media_model()).strip() or self._default_media_model()
        prompt_object = dict(payload.get("prompt_object") or {})
        prompt_object.setdefault("prompt", prompt)
        feature_payload = {
            "type": feature_type,
            "model": model,
            "promptObject": prompt_object,
        }
        raw_response, account_name, key_slot, resolved_model, tokens_in, tokens_out = self._call_feature(
            feature_payload=feature_payload,
            lane="hard",
            capability="media_transform",
            principal_id=self._request_principal_id(request),
        )
        asset_urls = _collect_asset_urls(raw_response)
        response_text = _extract_text(raw_response)
        normalized_text = json.dumps(
            {
                "feature_type": feature_type,
                "asset_urls": asset_urls,
                "text": response_text,
                "model": resolved_model,
                "provider_account_name": account_name,
            },
            ensure_ascii=True,
        )
        action_kind = str(request.action_kind or "media.transform") or "media.transform"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"onemin:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": {
                    "feature_type": feature_type,
                    "asset_urls": asset_urls,
                    "text": response_text,
                    "raw_response": raw_response,
                },
                "preview_text": _preview_text(response_text or (asset_urls[0] if asset_urls else normalized_text)),
                "mime_type": "application/json",
                "model": resolved_model,
                "asset_urls": asset_urls,
                "provider_backend": "1min",
                "provider_account_name": account_name,
                "provider_key_slot": key_slot,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "onemin",
                "provider_backend": "1min",
                "provider_account_name": account_name,
                "provider_key_slot": key_slot,
                "model": resolved_model,
                "feature_type": feature_type,
                "tool_version": definition.version,
            },
            model_name=resolved_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )
