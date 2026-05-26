from __future__ import annotations

import threading
import time
from typing import Any, Callable


def build_spawn_background_codex_worker(
    *,
    claim_background_response_worker_slot: Callable[[str], bool],
    background_timeout_seconds_for_response: Callable[[dict[str, object]], float],
    tool_shim_decision: Callable[..., Any],
    tool_shim_decision_type: type[Any],
    upstream_result_type: type[Any],
    generate_upstream_text: Callable[..., Any],
    build_completed_response_from_upstream: Callable[..., tuple[dict[str, object], list[dict[str, object]]]],
    store_background_terminal_response: Callable[..., dict[str, object]],
    capture_responses_debug: Callable[..., None],
    build_failed_response: Callable[..., dict[str, object]],
    response_failure_message: Callable[[dict[str, object]], str],
    release_background_response_worker_slot: Callable[..., None],
    register_background_response_worker: Callable[..., None],
) -> Callable[..., bool]:
    def spawn_background_codex_worker(
        *,
        response_id: str,
        created_at: int,
        model: str,
        response_metadata: dict[str, object],
        instructions: str | None,
        input_items: list[dict[str, object]],
        reasoning: Any | None,
        max_output_tokens: int | None,
        history_items: list[dict[str, object]],
        prompt: str,
        messages: list[dict[str, str]],
        supported_tools: list[dict[str, object]],
        chatplayground_audit_callback: Callable[..., Any] | None,
        chatplayground_audit_callback_only: bool,
        chatplayground_audit_principal_id: str,
        preferred_onemin_labels: tuple[str, ...],
        principal_id: str,
        container: object | None,
        background_job: dict[str, object] | None,
    ) -> bool:
        if not claim_background_response_worker_slot(response_id):
            return False

        def _worker() -> None:
            request_deadline_monotonic = time.monotonic() + background_timeout_seconds_for_response(
                {"created_at": created_at, "metadata": response_metadata}
            )
            try:
                tool_decision: Any | None = None
                if supported_tools:
                    decision = tool_shim_decision(
                        model=model,
                        max_output_tokens=max_output_tokens,
                        instructions=instructions,
                        tools=supported_tools,
                        history_items=history_items,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                        request_deadline_monotonic=request_deadline_monotonic,
                    )
                    if not isinstance(decision, tool_shim_decision_type) or not isinstance(
                        decision.upstream_result, upstream_result_type
                    ):
                        raise RuntimeError("invalid_upstream_result")
                    tool_decision = decision
                    result = decision.upstream_result
                else:
                    result = generate_upstream_text(
                        prompt=prompt,
                        messages=messages,
                        requested_model=model,
                        max_output_tokens=max_output_tokens,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                        preferred_onemin_labels=preferred_onemin_labels,
                        request_deadline_monotonic=request_deadline_monotonic,
                    )
                completed_obj, history_items_to_store = build_completed_response_from_upstream(
                    response_id=response_id,
                    created_at=created_at,
                    model=model,
                    requested_max_output_tokens=max_output_tokens,
                    metadata=response_metadata,
                    instructions=instructions,
                    input_items=input_items,
                    reasoning=reasoning,
                    base_history_items=history_items,
                    result=result,
                    tool_decision=tool_decision,
                )
                final_obj = store_background_terminal_response(
                    response_id=response_id,
                    response_obj=completed_obj,
                    input_items=input_items,
                    history_items=history_items_to_store,
                    principal_id=principal_id,
                    container=container,
                    background_job=background_job,
                )
                if str(final_obj.get("status") or "").strip().lower() == "completed":
                    capture_responses_debug(
                        name="response",
                        payload={
                            "principal_id": principal_id,
                            "codex_profile": str(
                                response_metadata.get("codex_effective_profile")
                                or response_metadata.get("codex_profile")
                                or ""
                            ),
                            "response": final_obj,
                        },
                    )
            except Exception as exc:
                failure_message = str(exc)[:500]
                failed_obj = build_failed_response(
                    response_id=response_id,
                    created_at=created_at,
                    model=model,
                    requested_max_output_tokens=max_output_tokens,
                    metadata=response_metadata,
                    instructions=instructions,
                    input_items=input_items,
                    failure_message=failure_message,
                    visible_text=f"Error: {failure_message}",
                )
                final_obj = store_background_terminal_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=input_items,
                    history_items=history_items,
                    principal_id=principal_id,
                    container=container,
                    background_job=background_job,
                )
                if str(final_obj.get("status") or "").strip().lower() == "failed":
                    capture_responses_debug(
                        name="response_background_failed",
                        payload={
                            "principal_id": principal_id,
                            "codex_profile": str(
                                response_metadata.get("codex_effective_profile")
                                or response_metadata.get("codex_profile")
                                or ""
                            ),
                            "response_id": response_id,
                            "failure_message": response_failure_message(final_obj) or failure_message,
                        },
                    )
            finally:
                release_background_response_worker_slot(response_id)

        worker = threading.Thread(target=_worker, daemon=True)
        try:
            register_background_response_worker(response_id, worker)
            worker.start()
        except Exception:
            release_background_response_worker_slot(response_id)
            raise
        return True

    spawn_background_codex_worker.__name__ = "spawn_background_codex_worker"
    spawn_background_codex_worker.__qualname__ = "spawn_background_codex_worker"
    return spawn_background_codex_worker


def build_ensure_background_response_progress(
    *,
    background_response_transition_lock: Any,
    background_response_has_expired: Callable[..., bool],
    background_failed_response: Callable[..., dict[str, object]],
    background_timeout_failure_message: Callable[[dict[str, object]], str],
    store_response: Callable[..., None],
    background_response_has_live_worker: Callable[[str], bool],
    now_unix: Callable[[], int],
    build_chatplayground_audit_callback: Callable[..., Any],
    spawn_background_codex_worker: Callable[..., bool],
    requested_max_output_tokens_from_response: Callable[[dict[str, object]], int | None],
    default_public_model: str,
    stored_response_type: type[Any],
) -> Callable[..., Any]:
    def ensure_background_response_progress(
        *,
        stored: Any,
        principal_id: str,
        container: object | None,
    ) -> Any:
        with background_response_transition_lock:
            response_obj = dict(stored.response)
            status = str(response_obj.get("status") or "").strip().lower()
            metadata = dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {}
            if status != "in_progress" or not bool(metadata.get("background_response")):
                return stored
            response_id = str(response_obj.get("id") or "")
            if background_response_has_expired(response_obj):
                failed_obj = background_failed_response(
                    stored=stored,
                    failure_message=background_timeout_failure_message(response_obj),
                )
                store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=stored.input_items,
                    history_items=stored.history_items,
                    principal_id=principal_id,
                    container=container,
                    background_job=stored.background_job,
                )
                return stored_response_type(
                    response=failed_obj,
                    input_items=[dict(item) for item in stored.input_items],
                    history_items=[dict(item) for item in stored.history_items],
                    principal_id=stored.principal_id,
                    background_job=dict(stored.background_job) if isinstance(stored.background_job, dict) else None,
                )
            if background_response_has_live_worker(response_id):
                return stored
            replay = dict(stored.background_job or {}) if isinstance(stored.background_job, dict) else {}
            if not replay:
                failed_obj = background_failed_response(stored=stored, failure_message="background_response_replay_unavailable")
                store_response(
                    response_id=response_id,
                    response_obj=failed_obj,
                    input_items=stored.input_items,
                    history_items=stored.history_items,
                    principal_id=principal_id,
                    container=container,
                    background_job=stored.background_job,
                )
                return stored_response_type(
                    response=failed_obj,
                    input_items=[dict(item) for item in stored.input_items],
                    history_items=[dict(item) for item in stored.history_items],
                    principal_id=stored.principal_id,
                    background_job=dict(stored.background_job) if isinstance(stored.background_job, dict) else None,
                )

            response_metadata = metadata
            response_metadata["background_resume_count"] = int(response_metadata.get("background_resume_count") or 0) + 1
            response_metadata["background_last_resumed_at"] = now_unix()
            refreshed_in_progress = {
                **response_obj,
                "metadata": response_metadata,
            }
            store_response(
                response_id=response_id,
                response_obj=refreshed_in_progress,
                input_items=stored.input_items,
                history_items=stored.history_items,
                principal_id=principal_id,
                container=container,
                background_job=replay,
            )
            callback_enabled = bool(replay.get("chatplayground_audit_callback_enabled")) or bool(
                replay.get("chatplayground_audit_callback_only")
            )
            replay_callback = (
                build_chatplayground_audit_callback(container=container, principal_id=principal_id)
                if callback_enabled
                else None
            )
            spawn_background_codex_worker(
                response_id=response_id,
                created_at=int(response_obj.get("created_at") or now_unix()),
                model=str(response_obj.get("model") or default_public_model),
                response_metadata=response_metadata,
                instructions=response_obj.get("instructions") if isinstance(response_obj.get("instructions"), str) else None,
                input_items=[dict(item) for item in stored.input_items],
                reasoning=response_obj.get("reasoning"),
                max_output_tokens=requested_max_output_tokens_from_response(response_obj),
                history_items=[dict(item) for item in stored.history_items],
                prompt=str(replay.get("prompt") or ""),
                messages=[dict(item) for item in list(replay.get("messages") or []) if isinstance(item, dict)],
                supported_tools=[dict(item) for item in list(replay.get("supported_tools") or []) if isinstance(item, dict)],
                chatplayground_audit_callback=replay_callback,
                chatplayground_audit_callback_only=bool(replay.get("chatplayground_audit_callback_only")),
                chatplayground_audit_principal_id=principal_id,
                preferred_onemin_labels=tuple(
                    str(item or "").strip()
                    for item in list(replay.get("preferred_onemin_labels") or [])
                    if str(item or "").strip()
                ),
                principal_id=principal_id,
                container=container,
                background_job=replay,
            )
            return stored_response_type(
                response=refreshed_in_progress,
                input_items=[dict(item) for item in stored.input_items],
                history_items=[dict(item) for item in stored.history_items],
                principal_id=stored.principal_id,
                background_job=replay,
            )

    ensure_background_response_progress.__name__ = "ensure_background_response_progress"
    ensure_background_response_progress.__qualname__ = "ensure_background_response_progress"
    return ensure_background_response_progress


def build_load_response_for_runtime(
    *,
    load_response: Callable[..., Any],
    ensure_background_response_progress: Callable[..., Any],
) -> Callable[..., Any]:
    def load_response_for_runtime(
        *,
        response_id: str,
        principal_id: str,
        container: object | None = None,
    ) -> Any:
        stored = load_response(response_id=response_id, principal_id=principal_id, container=container)
        return ensure_background_response_progress(stored=stored, principal_id=principal_id, container=container)

    load_response_for_runtime.__name__ = "load_response_for_runtime"
    load_response_for_runtime.__qualname__ = "load_response_for_runtime"
    return load_response_for_runtime
