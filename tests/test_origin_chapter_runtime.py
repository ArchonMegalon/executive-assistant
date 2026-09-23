import copy
import subprocess

import pytest

from scripts import origin_chapter_runtime as runtime
from tests.test_origin_chapter_intake import Queue, admission, executor


def configuration(hub):
    approved = admission(hub)
    del approved["browser_session"]
    return {"profile_id": "chrome_local_12345", "profile_use_approved": True,
        "source_scope": "synthetic_only", "admission": approved}


class Browser:
    def __init__(self): self.calls = []
    def open(self, profile, session): self.calls.append(("open", profile, session))
    def verify_account(self, session, account): self.calls.append(("account", account, session))
    def close(self, session): self.calls.append(("close", session))


def run(config, hub, root, browser, **kwargs):
    return runtime.run_bounded(config, hub, root, browser=browser, now=lambda: 1000,
        sleep=lambda _: None, **kwargs)


def test_actual_intake_opens_only_its_fresh_window_checks_account_and_closes_after_result(tmp_path, executor):
    hub, browser = Queue(), Browser()
    result = run(configuration(hub), hub, tmp_path, browser)
    assert result["state"] == "review_required" and result["browser_retained"] is False
    session = result["browser_session"]
    assert session.startswith("origin-book-")
    assert browser.calls == [("open", "chrome_local_12345", session), ("account", "a" * 64, session), ("close", session)]
    assert executor[0]["setup"]["browser_session"] == session
    assert hub.first["job"].get("readerAcceptedTextDigest") is None
    browser.calls.clear()
    assert run(configuration(hub), hub, tmp_path, browser)["state"] == "idle"
    assert not browser.calls


def test_empty_book_does_not_open_browser_or_create_lifecycle_record(tmp_path, executor):
    hub, browser = Queue(), Browser()
    hub.jobs.clear()
    result = run(configuration(hub), hub, tmp_path, browser)
    assert result == {"state": "idle", "browser_session": None, "browser_retained": False, "publication_authorized": False}
    assert not list((tmp_path / "firstbook-private-writes").glob("owned-session-*"))
    assert browser.calls == executor == []


@pytest.mark.parametrize("change", ["unapproved", "foreign-session", "invalid-profile", "expired", "invalid-scope"])
def test_bad_configuration_stops_before_hub_or_browser(tmp_path, executor, change):
    hub, browser = Queue(), Browser()
    config = configuration(hub)
    if change == "unapproved": config["profile_use_approved"] = False
    if change == "foreign-session": config["admission"]["browser_session"] = "someone-elses-live-window"
    if change == "invalid-profile": config["profile_id"] = "--help"
    if change == "expired": config["admission"]["expires_at"] = 999
    if change == "invalid-scope": config["source_scope"] = "any-data"
    with pytest.raises(ValueError): run(config, hub, tmp_path, browser)
    assert not hub.calls and not browser.calls and not executor


def test_wrong_account_closes_only_owned_window_before_provider_work(tmp_path, executor):
    hub, browser = Queue(), Browser()
    def wrong(*args): raise RuntimeError("firstbook_capture_account_mismatch")
    browser.verify_account = wrong
    with pytest.raises(RuntimeError, match="account_mismatch"):
        run(configuration(hub), hub, tmp_path, browser)
    assert [call[0] for call in browser.calls] == ["open", "close"]
    assert not any(action == "/admit" for action, _ in hub.calls)
    assert not executor


def test_inflight_budget_exhaustion_preserves_window_and_blocks_automatic_replacement(tmp_path, monkeypatch):
    hub, browser = Queue(), Browser()
    ticks = []
    def tick(*args, before_cycle, **kwargs):
        before_cycle()
        ticks.append(1)
        return {"state": "provider_busy"}
    monkeypatch.setattr(runtime.intake, "_tick", tick)
    result = run(configuration(hub), hub, tmp_path, browser, cycles=2)
    assert result["browser_retained"] is True and len(ticks) == 2
    assert [call[0] for call in browser.calls] == ["open", "account"]
    before = copy.deepcopy(browser.calls)
    with pytest.raises(RuntimeError, match="previous_session_requires_reconciliation"):
        run(configuration(hub), hub, tmp_path, browser)
    assert browser.calls == before


@pytest.mark.parametrize("state", ["generation_dispatched", "framework_dispatched", "advance_dispatched", "credit_dispatched"])
def test_observation_keeps_same_window_and_lock_until_review(tmp_path, monkeypatch, state):
    hub, browser = Queue(), Browser()
    states = iter([state, "review_required"])
    def tick(*args, before_cycle, **kwargs):
        before_cycle()
        return {"state": next(states)}
    monkeypatch.setattr(runtime.intake, "_tick", tick)
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        with pytest.raises(RuntimeError, match="cycle_busy"):
            runtime.intake.run_once(admission(hub), hub, tmp_path, now=lambda: 1000)
    result = runtime.run_bounded(configuration(hub), hub, tmp_path, browser=browser,
        cycles=2, interval=2, now=lambda: 1000, sleep=sleep)
    assert waits == [2]
    assert result["state"] == "review_required" and result["browser_retained"] is False
    assert [call[0] for call in browser.calls] == ["open", "account", "close"]


def test_uncertain_open_does_not_close_or_retry_an_unconfirmed_window(tmp_path):
    hub, browser = Queue(), Browser()
    def lost(profile, session):
        browser.calls.append(("open", profile, session))
        raise RuntimeError("open acknowledgement lost")
    browser.open = lost
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        run(configuration(hub), hub, tmp_path, browser)
    with pytest.raises(RuntimeError, match="previous_session_requires_reconciliation"):
        run(configuration(hub), hub, tmp_path, browser)
    assert len(browser.calls) == 1 and not any(action == "/admit" for action, _ in hub.calls)


def test_error_after_work_starts_preserves_window_and_original_work(tmp_path, monkeypatch):
    hub, browser = Queue(), Browser()
    def failure(*args): raise RuntimeError("uncertain provider result")
    monkeypatch.setattr(runtime.intake.cycle, "_step", failure)
    with pytest.raises(RuntimeError, match="uncertain provider result"):
        run(configuration(hub), hub, tmp_path, browser)
    assert [call[0] for call in browser.calls] == ["open", "account"]
    path = tmp_path / "firstbook-private-writes" / ("intake-" + hub.first["bookRef"] + ".json")
    assert runtime.worker.writer._load(path)["jobs"][0]["state"] == "working"


def test_uncertain_close_is_not_recorded_as_successful_cleanup(tmp_path, executor):
    hub, browser = Queue(), Browser()
    def lost(session):
        browser.calls.append(("close", session))
        raise RuntimeError("close acknowledgement lost")
    browser.close = lost
    with pytest.raises(RuntimeError, match="close acknowledgement lost"):
        run(configuration(hub), hub, tmp_path, browser)
    with pytest.raises(RuntimeError, match="previous_session_requires_reconciliation"):
        run(configuration(hub), hub, tmp_path, browser)
    assert [call[0] for call in browser.calls] == ["open", "account", "close"]


def test_driver_uses_exact_non_shell_open_and_close_and_redacts_failures(monkeypatch):
    calls = []
    def execute(args, **kwargs):
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 45}
        calls.append(args)
        text = ("session_name=owned\nbrowser_type=chrome\nurl=https://app.firstbook.ai/" if "open" in args
                else "session_name=owned closed=true")
        return subprocess.CompletedProcess(args, 0, stdout=text)
    monkeypatch.setattr(runtime.subprocess, "run", execute)
    browser = runtime.Browser()
    browser.open("chrome_local_123", "owned")
    browser.close("owned")
    assert calls == [["browser-act", "--session", "owned", "browser", "open", "chrome_local_123", "https://app.firstbook.ai/"],
                     ["browser-act", "session", "close", "owned"]]
    def failure(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, output="private page data")
    monkeypatch.setattr(runtime.subprocess, "run", failure)
    with pytest.raises(RuntimeError, match="browser_command_uncertain") as error:
        browser.open("chrome_local_123", "owned")
    assert "private" not in str(error.value)


@pytest.mark.parametrize("kind,output", [("open", "session_name=foreign\nbrowser_type=chrome\nurl=https://app.firstbook.ai/"),
    ("close", "session_name=owned closed=false")])
def test_unverified_lifecycle_response_is_rejected(monkeypatch, kind, output):
    monkeypatch.setattr(runtime.Browser, "_command", lambda *a: output)
    with pytest.raises(RuntimeError, match="not_verified"):
        if kind == "open": runtime.Browser().open("chrome_local_123", "owned")
        else: runtime.Browser().close("owned")
