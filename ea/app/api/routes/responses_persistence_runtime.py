from __future__ import annotations

import os
from typing import Any, Callable


def container_database_url(container: object | None) -> str:
    if container is None:
        return ""
    settings = getattr(container, "settings", None)
    if settings is None:
        return ""
    direct = str(getattr(settings, "database_url", "") or "").strip()
    if direct:
        return direct
    storage = getattr(settings, "storage", None)
    if storage is None:
        return ""
    return str(getattr(storage, "database_url", "") or "").strip()


def response_record_repository(
    *,
    container: object | None,
    response_repository_lock: Any,
    postgres_response_repositories: dict[str, Any],
    postgres_response_record_repository_type: type[Any],
    memory_response_repository: Any,
) -> Any:
    backend = "memory"
    database_url = ""
    if container is not None:
        runtime_profile = getattr(container, "runtime_profile", None)
        backend = str(getattr(runtime_profile, "storage_backend", "memory") or "memory").strip().lower() or "memory"
        database_url = container_database_url(container)
    else:
        backend = str(
            os.environ.get("EA_STORAGE_BACKEND")
            or os.environ.get("EA_LEDGER_BACKEND")
            or "memory"
        ).strip().lower() or "memory"
        database_url = str(os.environ.get("DATABASE_URL") or "").strip()

    if backend == "postgres" and database_url:
        with response_repository_lock:
            repository = postgres_response_repositories.get(database_url)
            if repository is None:
                repository = postgres_response_record_repository_type(database_url)
                postgres_response_repositories[database_url] = repository
        return repository
    return memory_response_repository


def store_response(
    *,
    response_id: str,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    principal_id: str,
    container: object | None,
    background_job: dict[str, object] | None,
    response_record_repository: Callable[..., Any],
) -> None:
    response_record_repository(container=container).store(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id=principal_id,
        background_job=background_job,
    )


def load_response(
    *,
    response_id: str,
    principal_id: str,
    container: object | None,
    response_record_repository: Callable[..., Any],
) -> Any:
    return response_record_repository(container=container).load(
        response_id=response_id,
        principal_id=principal_id,
    )


def store_background_terminal_response(
    *,
    response_id: str,
    principal_id: str,
    container: object | None,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    background_job: dict[str, object] | None,
    background_response_transition_lock: Any,
    load_response: Callable[..., Any],
    store_response: Callable[..., None],
    http_exception_type: type[Exception],
    background_response_has_expired: Callable[..., bool],
    background_failed_response: Callable[..., dict[str, object]],
    background_timeout_failure_message: Callable[[dict[str, object]], str],
) -> dict[str, object]:
    with background_response_transition_lock:
        try:
            stored = load_response(response_id=response_id, principal_id=principal_id, container=container)
        except http_exception_type as exc:
            if int(getattr(exc, "status_code", 0) or 0) != 404:
                raise
            store_response(
                response_id=response_id,
                response_obj=response_obj,
                input_items=input_items,
                history_items=history_items,
                principal_id=principal_id,
                container=container,
                background_job=background_job,
            )
            return response_obj
        current_response = dict(stored.response)
        current_status = str(current_response.get("status") or "").strip().lower()
        if current_status != "in_progress":
            return current_response
        if background_response_has_expired(current_response):
            failed_obj = background_failed_response(
                stored=stored,
                failure_message=background_timeout_failure_message(current_response),
            )
            store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=stored.input_items,
                history_items=stored.history_items,
                principal_id=principal_id,
                container=container,
                background_job=background_job,
            )
            return failed_obj
        store_response(
            response_id=response_id,
            response_obj=response_obj,
            input_items=input_items,
            history_items=history_items,
            principal_id=principal_id,
            container=container,
            background_job=background_job,
        )
        return response_obj
