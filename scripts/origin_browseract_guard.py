"""Container-only compatibility guard for pinned BrowserAct 1.1.0.

Its periodic orphan scan can race browser.open before the new public session is
registered. Serialize those two operations inside each command daemon. A lost
registry entry also must not authorize killing a browser whose exact live
session-server parent still owns it. Keep ordinary orphan cleanup, timeouts and
error handling; never retry a command or reset provider custody.
"""
from __future__ import annotations

import asyncio
from importlib.metadata import version
from pathlib import Path
import re
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


def guard_owned_browser_kill(kill, runtime_root):
    def protected_kill(process):
        try:
            command = process.cmdline()
            profiles = [arg.removeprefix("--user-data-dir=") for arg in command
                        if arg.startswith("--user-data-dir=")]
            profile = Path(profiles[0]) if len(profiles) == 1 else None
            retained = False
            if (profile is not None and re.fullmatch(r"chrome_local_[0-9]{1,32}", profile.name)
                and profile == Path(runtime_root()) / "profiles" / profile.name):
                parent = process.parent()
                if parent is not None and parent.is_running() and parent.status() != "zombie":
                    owner = parent.cmdline()
                    keys = [owner[i + 1] for i, arg in enumerate(owner[:-1]) if arg == "--browser-key"]
                    # An actual parent process, not a journal, stale PID, shell
                    # command containing this text, or another profile's server.
                    retained = (owner[1:3] == ["-m", "browser_act_cli.session"]
                        and keys == ["chrome-managed:" + profile.name]
                        and parent.uids() == process.uids()
                        and parent.create_time() <= process.create_time()
                        and process.is_running())
        except Exception:
            # Process observation failure is not evidence that a paid writer
            # is orphaned. The vendor records this as failed, never killed.
            raise RuntimeError("origin_browseract_owner_observation_unavailable") from None
        if retained:
            raise RuntimeError("origin_browseract_live_owner_retained")
        return kill(process)

    return protected_kill


def install() -> None:
    if version("browser-act-cli") != "1.1.0":
        raise RuntimeError("origin_browseract_guard_version_mismatch")
    from browser_act_cli.command_daemon import server
    from browser_act_cli.command_daemon.session import orphan_private_browser_cleanup as orphan

    if getattr(server, "_origin_lifecycle_guard_installed", False):
        return
    route = server._route_request_async
    cleanup = orphan.cleanup_orphan_private_browsers
    kill = getattr(orphan, "_kill_process_tree", None)
    root = getattr(orphan, "_runtime_root", None)
    if not asyncio.iscoroutinefunction(route) or not all(callable(f) for f in (cleanup, kill, root)):
        raise RuntimeError("origin_browseract_guard_contract_mismatch")
    server._route_request_async, orphan.cleanup_orphan_private_browsers = guarded_operations(route, cleanup)
    orphan._kill_process_tree = guard_owned_browser_kill(kill, lambda: root(None))
    server._origin_lifecycle_guard_installed = True
    server._origin_live_owner_guard_installed = True
