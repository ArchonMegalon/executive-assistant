import copy

import pytest

from scripts import origin_chapter_runtime as runtime
from tests.test_origin_chapter_intake import Queue, executor
from tests.test_origin_chapter_runtime import Browser, configuration


class Clock:
    def __init__(self):
        self.elapsed = 0
        self.after_sleep = lambda: None

    def wall(self):
        return 1000 + self.elapsed

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds
        self.after_sleep()


def watch(config, hub, root, browser, clock, **kwargs):
    return runtime.watch_book(lambda: copy.deepcopy(config), hub, root,
        browser=browser, now=clock.wall, monotonic=clock.monotonic,
        sleep=clock.sleep, poll_interval=15, **kwargs)


def test_waits_for_new_accepted_chapter_without_an_agent_or_another_credit(tmp_path, executor):
    hub, browser, clock = Queue(), Browser(), Clock()
    config = configuration(hub)

    def reader():
        # The worker never marks this itself: emulate the separate native user.
        if clock.elapsed == 15:
            assert hub.first["job"].get("readerAcceptedTextDigest") is None
        if clock.elapsed == 30:
            hub.next()

    clock.after_sleep = reader
    result = watch(config, hub, tmp_path, browser, clock, duration=60)
    assert result["state"] == "watch_finished" and result["watch_polls"] == 4
    assert result["browser_retained"] is False
    assert len(executor) == 2
    assert sum(p["setup"].get("maximum_book_credits", 0) for p in executor) == 1
    assert list(hub.jobs.values())[-1]["job"].get("readerAcceptedTextDigest") is None
    assert [c[0] for c in browser.calls] == ["open", "account", "close"] * 2
    assert browser.calls[0][-1] != browser.calls[3][-1]
    # Process restart does not duplicate the completed chapters.
    watch(config, hub, tmp_path, browser, clock, duration=15)
    assert len(executor) == 2


def test_idle_watch_never_opens_browser(tmp_path, executor):
    hub, browser, clock = Queue(), Browser(), Clock()
    hub.jobs.clear()
    result = watch(configuration(hub), hub, tmp_path, browser, clock, duration=31)
    assert result["watch_polls"] == 3 and clock.elapsed == 31
    assert not browser.calls and not executor


@pytest.mark.parametrize("change", ["revoked", "expiry", "profile", "scope", "budget", "account"])
def test_reload_cannot_expand_or_revoke_authority_then_keep_processing(tmp_path, executor, change):
    hub, browser, clock = Queue(), Browser(), Clock()
    config = configuration(hub)

    def modify():
        hub.next()
        if change == "revoked": config["admission"]["approved"] = False
        if change == "expiry": config["admission"]["expires_at"] += 50
        if change == "profile": config["profile_id"] = "chrome_local_999"
        if change == "scope": config["source_scope"] = "consented_origin"
        if change == "budget": config["admission"]["maximum_chapters"] += 1
        if change == "account": config["admission"]["account_sha256"] = "b" * 64

    clock.after_sleep = modify
    with pytest.raises((ValueError, RuntimeError)):
        watch(config, hub, tmp_path, browser, clock, duration=60)
    assert len(executor) == 1
    assert [c[0] for c in browser.calls] == ["open", "account", "close"]


def test_revocation_during_generation_retains_session_and_never_replays(tmp_path, monkeypatch):
    hub, browser, clock = Queue(), Browser(), Clock()
    config = configuration(hub)
    ticks = []

    def tick(*args, before_cycle, **kwargs):
        before_cycle()
        ticks.append(1)
        return {"state": "provider_busy"}

    monkeypatch.setattr(runtime.intake, "_tick", tick)
    clock.after_sleep = lambda: config["admission"].update(approved=False)
    with pytest.raises(ValueError):
        watch(config, hub, tmp_path, browser, clock, duration=60)
    assert len(ticks) == 1
    assert [c[0] for c in browser.calls] == ["open", "account"]
    config["admission"]["approved"] = True
    with pytest.raises(RuntimeError, match="previous_session_requires_reconciliation"):
        watch(config, hub, tmp_path, browser, clock, duration=60)
    assert len(ticks) == 1


def test_inflight_observation_limit_stops_watch_instead_of_opening_replacement(tmp_path, monkeypatch):
    hub, browser, clock = Queue(), Browser(), Clock()
    ticks = []

    def tick(*args, before_cycle, **kwargs):
        before_cycle()
        ticks.append(1)
        return {"state": "provider_busy"}

    monkeypatch.setattr(runtime.intake, "_tick", tick)
    result = watch(configuration(hub), hub, tmp_path, browser, clock, duration=60, cycles=1)
    assert result["state"] == "provider_busy" and result["browser_retained"] is True
    assert result["watch_polls"] == 1 and len(ticks) == 1 and clock.elapsed == 0


def test_errors_are_not_retried_and_raw_data_not_added_to_results(tmp_path, monkeypatch):
    hub, browser, clock = Queue(), Browser(), Clock()
    calls = []

    def unavailable(*args):
        calls.append(1)
        raise RuntimeError("origin_worker_hub_unavailable_reconcile_same_job")

    hub.pending = unavailable
    with pytest.raises(RuntimeError, match="hub_unavailable"):
        watch(configuration(hub), hub, tmp_path, browser, clock, duration=60)
    assert len(calls) == 1 and clock.elapsed == 0 and not browser.calls


@pytest.mark.parametrize("during", ["hub_read", "account_check"])
def test_expiry_during_preparation_cannot_start_provider_work(tmp_path, executor, during):
    hub, browser, clock = Queue(), Browser(), Clock()
    config = configuration(hub)
    if during == "hub_read":
        original = hub.call
        def read(*args, **kwargs):
            result = original(*args, **kwargs)
            clock.elapsed = 2
            return result
        hub.call = read
    else:
        original = browser.verify_account
        def account(*args):
            original(*args)
            clock.elapsed = 2
        browser.verify_account = account
    with pytest.raises(RuntimeError, match="watch_budget_exhausted"):
        watch(config, hub, tmp_path, browser, clock, duration=1)
    assert not executor and not any(action == "/admit" for action, _ in hub.calls)
    assert [c[0] for c in browser.calls] == ([] if during == "hub_read" else ["open", "account", "close"])


def test_monotonic_limit_survives_wall_clock_rollback(tmp_path):
    hub, browser, clock = Queue(), Browser(), Clock()
    hub.jobs.clear()
    result = runtime.watch_book(lambda: configuration(hub), hub, tmp_path, duration=31,
        poll_interval=15, browser=browser, now=lambda: 1000 - clock.elapsed,
        monotonic=clock.monotonic, sleep=clock.sleep)
    assert result["state"] == "watch_finished" and clock.elapsed == 31


def test_stops_at_original_expiry_or_chapter_limit(tmp_path, executor):
    hub, browser, clock = Queue(), Browser(), Clock()
    config = configuration(hub)
    config["admission"].update(maximum_chapters=1)
    result = watch(config, hub, tmp_path, browser, clock, duration=86400)
    assert result["state"] == "chapter_limit_reached" and len(executor) == 1
    assert clock.elapsed == 15
    hub, browser, clock = Queue(), Browser(), Clock()
    hub.jobs.clear()
    result = watch(configuration(hub), hub, tmp_path / "empty", browser, clock, duration=86400)
    assert result["state"] == "watch_finished" and clock.elapsed == 100


@pytest.mark.parametrize("duration", [0, True, 86401, -1])
def test_invalid_watch_budget_cannot_read_hub(tmp_path, duration):
    hub, browser, clock = Queue(), Browser(), Clock()
    with pytest.raises(ValueError, match="invalid_watch_budget"):
        watch(configuration(hub), hub, tmp_path, browser, clock, duration=duration)
    assert not hub.calls and not browser.calls
