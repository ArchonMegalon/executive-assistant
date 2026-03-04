from __future__ import annotations

import asyncio

from app.workers.event_worker import poll_external_events


async def run_event_worker() -> None:
    await poll_external_events()


if __name__ == "__main__":
    asyncio.run(run_event_worker())
