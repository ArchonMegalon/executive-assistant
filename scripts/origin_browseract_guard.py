"""Container-only compatibility guard for pinned BrowserAct 1.1.0.

Its periodic orphan scan can race browser.open before the new public session is
registered. Serialize those two operations inside each command daemon. Keep the
vendor scan, lifecycle checks, timeouts and error handling; never retry a command.
"""
from __future__ import annotations

import asyncio
from importlib.metadata import version
import threading


def guarded_operations(route, cleanup):
    lease = threading.Lock()

    async def guarded_route(request):
        if request.command != "browser.open":
            return await route(request)
        # Never block the daemon event loop on the maintenance thread. This is
        # acquisition of a real mutex, not a startup delay/readiness estimate.
        while not lease.acquire(blocking=False):
            await asyncio.sleep(0.025)
        try:
            return await route(request)
        finally:
            lease.release()

    def guarded_cleanup(*args, **kwargs):
        # The upstream job timeout may abandon its wait, but the thread itself
        # retains this lease until the actual scan/kill operation has finished.
        with lease:
            return cleanup(*args, **kwargs)

    return guarded_route, guarded_cleanup


def install() -> None:
    if version("browser-act-cli") != "1.1.0":
        raise RuntimeError("origin_browseract_guard_version_mismatch")
    from browser_act_cli.command_daemon import server
    from browser_act_cli.command_daemon.session import orphan_private_browser_cleanup as orphan

    if getattr(server, "_origin_lifecycle_guard_installed", False):
        return
    route = server._route_request_async
    cleanup = orphan.cleanup_orphan_private_browsers
    if not asyncio.iscoroutinefunction(route) or not callable(cleanup):
        raise RuntimeError("origin_browseract_guard_contract_mismatch")
    server._route_request_async, orphan.cleanup_orphan_private_browsers = guarded_operations(route, cleanup)
    server._origin_lifecycle_guard_installed = True
