from __future__ import annotations

import os
from typing import Any, Callable

import fastapi.dependencies.utils
import fastapi.routing
import starlette.concurrency
import starlette.routing

_INSTALLED = False


async def _inline_run_in_threadpool(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


def inline_sync_handlers_enabled() -> bool:
    raw = str(os.environ.get("EA_INLINE_SYNC_HANDLERS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def install_inline_threadpool_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool
    starlette.routing.run_in_threadpool = _inline_run_in_threadpool
    fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
    fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
    _INSTALLED = True
