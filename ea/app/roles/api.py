import asyncio
import threading

import uvicorn

# Keep legacy role entrypoint aligned with the deployed API app.
from app.main import app


def _start_uvicorn() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")


async def run_api() -> None:
    print("==================================================", flush=True)
    print("🌐 EA OS API: ONLINE (Listening on Port 8090...)", flush=True)
    print("==================================================", flush=True)
    server_thread = threading.Thread(target=_start_uvicorn, daemon=True)
    server_thread.start()
    while True:
        await asyncio.sleep(3600)
