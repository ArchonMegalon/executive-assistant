from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.gog import gog_scout


async def run_reasoning_step(
    *,
    container: str,
    prompt: str,
    google_account: str,
    ui_updater: Callable[[str], Awaitable[None]],
    task_name: str,
    timeout_sec: float = 240.0,
    runner: Callable[..., Awaitable[str]] | None = None,
) -> str:
    execute_runner = runner or gog_scout
    return await asyncio.wait_for(
        execute_runner(
            str(container or ""),
            str(prompt or ""),
            str(google_account or ""),
            ui_updater,
            task_name=str(task_name or "Intent Execution"),
        ),
        timeout=float(timeout_sec),
    )


__all__ = ["run_reasoning_step"]
