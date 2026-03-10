from __future__ import annotations

import logging
import signal
import time

import uvicorn

from app.container import build_container
from app.logging_utils import configure_logging
from app.settings import get_settings

_IDLE_BACKOFF_START_SECONDS = 1.0
_IDLE_BACKOFF_MAX_SECONDS = 15.0
_ERROR_BACKOFF_SECONDS = 2.0


def _run_api() -> None:
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level=s.log_level.lower())


def _run_execution_worker(role: str) -> None:
    stop = {"flag": False}

    def _handle_stop(signum, frame):  # type: ignore[no-untyped-def]
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log = logging.getLogger("ea.runner")
    container = build_container()
    idle_backoff_seconds = _IDLE_BACKOFF_START_SECONDS
    log.info("role=%s started worker loop", role)
    while not stop["flag"]:
        try:
            artifact = container.orchestrator.run_next_queue_item(lease_owner=role)
        except Exception:
            log.exception("role=%s queue execution failed; retrying in %.1fs", role, _ERROR_BACKOFF_SECONDS)
            time.sleep(_ERROR_BACKOFF_SECONDS)
            continue
        if artifact is None:
            log.debug("role=%s idle; sleeping %.1fs before next lease attempt", role, idle_backoff_seconds)
            time.sleep(idle_backoff_seconds)
            idle_backoff_seconds = min(idle_backoff_seconds * 2.0, _IDLE_BACKOFF_MAX_SECONDS)
            continue
        idle_backoff_seconds = _IDLE_BACKOFF_START_SECONDS
        log.info(
            "role=%s completed queued item session=%s artifact=%s; idle backoff reset",
            role,
            artifact.execution_session_id,
            artifact.artifact_id,
        )
    log.info("role=%s stopped worker loop", role)


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    if s.role == "api":
        _run_api()
        return
    _run_execution_worker(s.role)


if __name__ == "__main__":
    main()
