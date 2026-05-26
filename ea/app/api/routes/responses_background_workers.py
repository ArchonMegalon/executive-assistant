from __future__ import annotations

from typing import Any


def cleanup_background_response_workers(
    *,
    background_response_lock: Any,
    background_response_workers: dict[str, Any],
    background_response_starting: set[str],
) -> None:
    with background_response_lock:
        stale_ids = [response_id for response_id, worker in background_response_workers.items() if not worker.is_alive()]
        for response_id in stale_ids:
            background_response_workers.pop(response_id, None)
            background_response_starting.discard(response_id)


def background_response_has_live_worker(
    response_id: str,
    *,
    cleanup_background_response_workers: Any,
    background_response_lock: Any,
    background_response_workers: dict[str, Any],
    background_response_starting: set[str],
) -> bool:
    cleanup_background_response_workers()
    with background_response_lock:
        if response_id in background_response_starting:
            return True
        worker = background_response_workers.get(response_id)
        return bool(worker and worker.is_alive())


def claim_background_response_worker_slot(
    response_id: str,
    *,
    cleanup_background_response_workers: Any,
    background_response_lock: Any,
    background_response_workers: dict[str, Any],
    background_response_starting: set[str],
) -> bool:
    cleanup_background_response_workers()
    with background_response_lock:
        if response_id in background_response_starting:
            return False
        worker = background_response_workers.get(response_id)
        if worker and worker.is_alive():
            return False
        background_response_starting.add(response_id)
        return True


def register_background_response_worker(
    response_id: str,
    worker: Any,
    *,
    background_response_lock: Any,
    background_response_workers: dict[str, Any],
    background_response_starting: set[str],
) -> None:
    with background_response_lock:
        background_response_starting.discard(response_id)
        background_response_workers[response_id] = worker


def release_background_response_worker_slot(
    response_id: str,
    *,
    worker: Any | None,
    background_response_lock: Any,
    background_response_workers: dict[str, Any],
    background_response_starting: set[str],
) -> None:
    with background_response_lock:
        background_response_starting.discard(response_id)
        existing = background_response_workers.get(response_id)
        if existing is None:
            return
        if worker is None or existing is worker or not existing.is_alive():
            background_response_workers.pop(response_id, None)
