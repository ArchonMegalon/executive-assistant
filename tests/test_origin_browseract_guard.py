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
    assert "assert server._origin_live_owner_guard_installed" in dockerfile
    assert "install()" in bootstrap and "os._exit(78)" in bootstrap


def test_bootstrap_failure_exits_instead_of_continuing_unguarded():
    result = subprocess.run([sys.executable, "-c",
        "import runpy, sys; sys.modules['scripts.origin_browseract_guard'] = None; "
        "runpy.run_path(sys.argv[1]); print('must-not-run')",
        "docker/origin-book/sitecustomize.py"], capture_output=True, text=True, check=False)
    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr == "origin_browseract_lifecycle_guard_unavailable\n"


class Process:
    """Only the process observations used by the isolated kill guard."""
    def __init__(self, *, command, pid=100, started=10, parent=None, running=True, uid=1000):
        self.command = command
        self.pid = pid
        self.started = started
        self.owner = parent
        self.running = running
        self.uid = uid

    def cmdline(self):
        return self.command

    def create_time(self):
        return self.started

    def parent(self):
        return self.owner

    def is_running(self):
        return self.running

    def status(self):
        return "running" if self.running else "zombie"

    def uids(self):
        return (self.uid, self.uid, self.uid)


def owned_browser():
    owner = Process(command=["/usr/local/bin/python", "-m", "browser_act_cli.session",
        "--browser-key", "chrome-managed:chrome_local_123", "--port", "59003"])
    return Process(command=["/opt/google/chrome/chrome", "--no-sandbox",
        "--user-data-dir=/browseract/profiles/chrome_local_123"],
        pid=101, started=11, parent=owner)


def test_missing_registry_must_not_kill_browser_with_live_exact_server_parent():
    # The Oct 10 incident had sessions=[] / session_server_state=missing,
    # while the real server and its direct Chrome child were still alive.
    killed = []
    protected = guard.guard_owned_browser_kill(killed.append, lambda: Path("/browseract"))
    with pytest.raises(RuntimeError, match="live_owner_retained"):
        protected(owned_browser())
    assert killed == []


@pytest.mark.parametrize("change", ["dead_owner", "different_owner", "different_profile", "different_uid", "later_parent", "orphan"])
def test_normal_orphan_cleanup_remains_available(change):
    browser = owned_browser()
    if change == "dead_owner":
        browser.owner.running = False
    elif change == "different_owner":
        browser.owner.command = ["python", "-m", "unrelated_service"]
    elif change == "different_profile":
        browser.owner.command[4] = "chrome-managed:chrome_local_456"
    elif change == "different_uid":
        browser.owner.uid = 2000
    elif change == "later_parent":
        browser.owner.started = browser.started + 1
    else:
        browser.owner = None
    killed = []
    guard.guard_owned_browser_kill(killed.append, lambda: Path("/browseract"))(browser)
    assert killed == [browser]


def test_uncertain_process_observation_does_not_authorize_killing(monkeypatch):
    browser = owned_browser()
    def unreadable():
        raise PermissionError("private process details must not be exposed")
    monkeypatch.setattr(browser.owner, "cmdline", unreadable)
    killed = []
    with pytest.raises(RuntimeError, match="owner_observation_unavailable") as error:
        guard.guard_owned_browser_kill(killed.append, lambda: Path("/browseract"))(browser)
    assert "private process" not in str(error.value)
    assert killed == []


def test_live_owner_guard_does_not_cover_other_profile_roots():
    browser = owned_browser()
    browser.command[-1] = "--user-data-dir=/unrelated/profiles/chrome_local_123"
    killed = []
    guard.guard_owned_browser_kill(killed.append, lambda: Path("/browseract"))(browser)
    assert killed == [browser]
