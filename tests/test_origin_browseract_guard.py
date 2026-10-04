import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from scripts import origin_browseract_guard as guard


def test_orphan_scan_cannot_kill_browser_before_open_registers_session():
    events = []
    entered = threading.Event()
    release = threading.Event()
    scanning = threading.Event()

    async def route(request):
        events.append("starting")
        entered.set()
        await asyncio.to_thread(release.wait, 2)
        events.append("registered")
        return "opened"

    def cleanup():
        scanning.set()
        assert "registered" in events
        events.append("scan")
        return "cleaned"

    opened, scanned = guard.guarded_operations(route, cleanup)
    with ThreadPoolExecutor() as threads:
        opening = threads.submit(asyncio.run, opened(SimpleNamespace(command="browser.open")))
        assert entered.wait(1)
        attempt = threading.Event()

        def scan():
            attempt.set()
            return scanned()

        cleaning = threads.submit(scan)
        assert attempt.wait(1)
        try:
            assert not scanning.wait(0.05)
        finally:
            release.set()
        assert opening.result(2) == "opened"
        assert cleaning.result(2) == "cleaned"
    assert events == ["starting", "registered", "scan"]


def test_open_waits_for_actual_scan_completion_even_if_observer_times_out():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def cleanup():
        entered.set()
        assert release.wait(2)
        calls.append("scan_finished")

    async def route(request):
        calls.append(request.command)

    opened, scanned = guard.guarded_operations(route, cleanup)

    async def run():
        with ThreadPoolExecutor() as threads:
            cleaning = threads.submit(scanned)
            assert entered.wait(1)
            try:
                # Canceling a waiter cannot release a lease owned by the scan.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(opened(SimpleNamespace(command="browser.open")), 0.05)
                assert calls == []
                await opened(SimpleNamespace(command="daemon.health"))
                assert calls == ["daemon.health"]
                next_open = asyncio.create_task(opened(SimpleNamespace(command="browser.open")))
                await asyncio.sleep(0.05)
                assert not next_open.done()
            finally:
                release.set()
            await next_open
            cleaning.result(1)
    asyncio.run(run())
    assert calls == ["daemon.health", "scan_finished", "browser.open"]


@pytest.mark.parametrize("fail_open", [True, False])
def test_errors_propagate_once_and_release_the_lease(fail_open):
    calls = []

    async def route(request):
        calls.append("open")
        if fail_open:
            raise ValueError("open failed")
        return "opened"

    def cleanup(**kwargs):
        calls.append(("cleanup", kwargs))
        if not fail_open:
            raise ValueError("cleanup failed")

    opened, scanned = guard.guarded_operations(route, cleanup)
    if fail_open:
        with pytest.raises(ValueError, match="open failed"):
            asyncio.run(opened(SimpleNamespace(command="browser.open")))
        scanned(processes=[], root_dir="/scoped")
    else:
        with pytest.raises(ValueError, match="cleanup failed"):
            scanned(processes=[], root_dir="/scoped")
        assert asyncio.run(opened(SimpleNamespace(command="browser.open"))) == "opened"
    assert calls.count("open") == 1
    assert calls.count(("cleanup", {"processes": [], "root_dir": "/scoped"})) == 1


def test_canceled_open_releases_lease_without_replay():
    calls = []

    async def route(request):
        calls.append("open")
        await asyncio.Event().wait()

    opened, scanned = guard.guarded_operations(route, lambda: calls.append("scan"))

    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(opened(SimpleNamespace(command="browser.open")), 0.05)
        scanned()
    asyncio.run(run())
    assert calls == ["open", "scan"]


def test_version_drift_fails_before_vendor_import(monkeypatch):
    monkeypatch.setattr(guard, "version", lambda _: "1.4.2")
    with pytest.raises(RuntimeError, match="version_mismatch"):
        guard.install()


def test_guard_is_loaded_in_all_isolated_python_children_and_fails_closed():
    dockerfile = Path("docker/origin-book/Dockerfile").read_text()
    allowed = Path("docker/origin-book/Dockerfile.dockerignore").read_text().splitlines()
    bootstrap = Path("docker/origin-book/sitecustomize.py").read_text()
    assert "PYTHONPATH=/opt/origin-browseract:/opt/browseract:/app" in dockerfile
    assert "scripts/origin_browseract_guard.py" in dockerfile
    assert "!scripts/origin_browseract_guard.py" in allowed
    assert "!docker/origin-book/sitecustomize.py" in allowed
    assert "install()" in bootstrap and "os._exit(78)" in bootstrap


def test_bootstrap_failure_exits_instead_of_continuing_unguarded():
    result = subprocess.run([sys.executable, "-c",
        "import runpy, sys; sys.modules['scripts.origin_browseract_guard'] = None; "
        "runpy.run_path(sys.argv[1]); print('must-not-run')",
        "docker/origin-book/sitecustomize.py"], capture_output=True, text=True, check=False)
    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr == "origin_browseract_lifecycle_guard_unavailable\n"
