from __future__ import annotations

import asyncio
import marshal
import time
import types


def test_cached_provider_health_snapshot_uses_disk_backing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 3}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=payload)

    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        responses_route._PROVIDER_HEALTH_CACHE.clear()
        responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)

    assert cached == payload
    assert age_seconds is not None
    assert age_seconds >= 0.0


def test_provider_health_snapshot_async_uses_disk_cache_when_refresh_in_flight(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 5}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=payload)

    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        responses_route._PROVIDER_HEALTH_CACHE.clear()
        responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = True

    try:
        result = asyncio.run(responses_route._provider_health_snapshot_async(lightweight=True))
    finally:
        with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
            responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False

    assert result["providers"]["onemin"]["state"] == "ready"
    assert result["provider_health_snapshot"]["status"] == "cached"
    assert result["provider_health_snapshot"]["reason"] in {
        "fresh provider-health cache",
        "live refresh already in flight",
    }
    assert result["provider_health_snapshot"]["stale"] is False


def test_provider_health_snapshot_async_marks_stale_cache_and_starts_background_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 5}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=payload)
    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        entry = dict(responses_route._PROVIDER_HEALTH_CACHE.get(True) or {})
        entry["cached_at"] = time.time() - 120.0
        responses_route._PROVIDER_HEALTH_CACHE[True] = entry

    monkeypatch.setattr(responses_route, "_provider_health_snapshot_stale_age_seconds", lambda: 60.0)
    started = {"count": 0}

    def _fake_start(loop, *, lightweight):
        started["count"] += 1
        return object()

    monkeypatch.setattr(responses_route, "_start_provider_health_refresh", _fake_start)

    result = asyncio.run(responses_route._provider_health_snapshot_async(lightweight=True))

    assert started["count"] == 1
    assert result["provider_health_snapshot"]["status"] == "cached"
    assert result["provider_health_snapshot"]["stale"] is True
    assert result["provider_health_snapshot"]["reason"] == "stale provider-health cache; background refresh started"


def test_provider_health_snapshot_async_waits_on_stale_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    cached_payload = {"providers": {"onemin": {"state": "degraded", "configured_slots": 5}}}
    refreshed_payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 5}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=cached_payload)
    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        entry = dict(responses_route._PROVIDER_HEALTH_CACHE.get(True) or {})
        entry["cached_at"] = time.time() - 120.0
        responses_route._PROVIDER_HEALTH_CACHE[True] = entry

    monkeypatch.setattr(responses_route, "_provider_health_snapshot_stale_age_seconds", lambda: 60.0)

    async def _run() -> dict[str, object]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(refreshed_payload)
        monkeypatch.setattr(
            responses_route,
            "_start_provider_health_refresh",
            lambda loop, *, lightweight: future,
        )
        return await responses_route._provider_health_snapshot_async(lightweight=True, wait_on_stale=True)

    result = asyncio.run(_run())

    assert result["providers"]["onemin"]["state"] == "ready"
    assert result["provider_health_snapshot"]["status"] == "live"
    assert result["provider_health_snapshot"]["reason"] == "waited for stale provider-health refresh"
    assert result["provider_health_snapshot"]["stale"] is False


def test_provider_health_snapshot_async_waits_on_existing_stale_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    cached_payload = {"providers": {"onemin": {"state": "degraded", "configured_slots": 5}}}
    refreshed_payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 5}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=cached_payload)
    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        entry = dict(responses_route._PROVIDER_HEALTH_CACHE.get(True) or {})
        entry["cached_at"] = time.time() - 120.0
        responses_route._PROVIDER_HEALTH_CACHE[True] = entry

    monkeypatch.setattr(responses_route, "_provider_health_snapshot_stale_age_seconds", lambda: 60.0)

    async def _run() -> dict[str, object]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(refreshed_payload)
        with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
            responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = True
            responses_route._PROVIDER_HEALTH_REFRESH_FUTURES[True] = future
        try:
            monkeypatch.setattr(
                responses_route,
                "_start_provider_health_refresh",
                lambda loop, *, lightweight: None,
            )
            return await responses_route._provider_health_snapshot_async(lightweight=True, wait_on_stale=True)
        finally:
            with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
                responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False
                responses_route._PROVIDER_HEALTH_REFRESH_FUTURES[True] = None

    result = asyncio.run(_run())

    assert result["providers"]["onemin"]["state"] == "ready"
    assert result["provider_health_snapshot"]["status"] == "live"
    assert result["provider_health_snapshot"]["reason"] == "waited for stale provider-health refresh"


def test_cached_provider_health_snapshot_uses_recent_disk_cache_even_if_signature_changes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 4}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=payload)

    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        responses_route._PROVIDER_HEALTH_CACHE.clear()
        responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False

    monkeypatch.setenv("EA_PROVIDER_HEALTH_LIGHTWEIGHT_TIMEOUT_SECONDS", "17")

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)

    assert cached == payload
    assert age_seconds is not None
    assert age_seconds >= 0.0


def test_cached_provider_health_snapshot_invalidates_when_capacity_env_changes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", "13")
    from app.api.routes import responses as responses_route

    payload = {
        "providers": {
            "onemin": {
                "state": "ready",
                "configured_slots": 4,
                "hard_max_active_requests": 13,
            }
        }
    }
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=payload)

    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        responses_route._PROVIDER_HEALTH_CACHE.clear()
        responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False

    monkeypatch.setenv("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", "20")

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)

    assert cached is None
    assert age_seconds is None


def test_provider_health_env_signature_stable_across_equivalent_code_objects(monkeypatch) -> None:
    from app.api.routes import responses as responses_route

    original = responses_route._provider_health_report
    original_signature = responses_route._provider_health_env_signature()
    cloned_code = marshal.loads(marshal.dumps(original.__code__))
    cloned = types.FunctionType(
        cloned_code,
        original.__globals__,
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    cloned.__kwdefaults__ = getattr(original, "__kwdefaults__", None)
    cloned.__qualname__ = getattr(original, "__qualname__", cloned.__qualname__)
    cloned.__module__ = getattr(original, "__module__", cloned.__module__)

    monkeypatch.setattr(responses_route, "_provider_health_report", cloned)

    assert responses_route._provider_health_env_signature() == original_signature


def test_provider_health_env_signature_ignores_runtime_timeout_knobs(monkeypatch) -> None:
    from app.api.routes import responses as responses_route

    original_signature = responses_route._provider_health_env_signature()
    monkeypatch.setenv("EA_PROVIDER_HEALTH_LIGHTWEIGHT_TIMEOUT_SECONDS", "13")
    monkeypatch.setenv("EA_PROVIDER_HEALTH_ROUTE_TIMEOUT_SECONDS", "21")

    assert responses_route._provider_health_env_signature() == original_signature


def test_provider_capacity_summary_preserves_live_ready_slot_count_and_state_counts() -> None:
    from app.api.routes import responses as responses_route

    summary = responses_route._provider_capacity_summary(
        {
            "configured_slots": 74,
            "ready_slot_count": 5,
            "live_ready_slot_count": 2,
            "slot_state_counts": {"ready": 5, "degraded": 69},
            "live_remaining_credits_total": 12663.0,
            "actual_remaining_credits_total": 118681415.0,
            "live_positive_balance_slot_count": 66,
        }
    )

    assert summary["ready_slots"] == 5
    assert summary["live_ready_slot_count"] == 2
    assert summary["slot_state_counts"] == {"ready": 5, "degraded": 69}
    assert summary["live_positive_balance_slot_count"] == 66


def test_prewarm_provider_health_snapshot_cache_populates_cache_when_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 3}}}
    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        responses_route._PROVIDER_HEALTH_CACHE.clear()
        responses_route._PROVIDER_HEALTH_REFRESH_IN_FLIGHT[True] = False

    monkeypatch.setattr(responses_route, "_provider_health_snapshot", lambda *, lightweight: payload)

    asyncio.run(responses_route.prewarm_provider_health_snapshot_cache(lightweight=True, timeout_seconds=0.5))

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)
    assert cached == payload
    assert age_seconds is not None


def test_prewarm_provider_health_snapshot_cache_refreshes_stale_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    original_payload = {"providers": {"onemin": {"state": "degraded", "configured_slots": 3}}}
    refreshed_payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 3}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=original_payload)
    with responses_route._PROVIDER_HEALTH_CACHE_LOCK:
        entry = dict(responses_route._PROVIDER_HEALTH_CACHE.get(True) or {})
        entry["cached_at"] = time.time() - 120.0
        responses_route._PROVIDER_HEALTH_CACHE[True] = entry
    monkeypatch.setattr(responses_route, "_provider_health_cache_refresh_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(responses_route, "_provider_health_snapshot", lambda *, lightweight: refreshed_payload)

    asyncio.run(responses_route.prewarm_provider_health_snapshot_cache(lightweight=True, timeout_seconds=0.5))

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)
    assert cached == refreshed_payload
    assert age_seconds is not None
    assert age_seconds < 60.0


def test_prewarm_provider_health_snapshot_cache_refreshes_even_fresh_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PROVIDER_HEALTH_CACHE_DIR", str(tmp_path))
    from app.api.routes import responses as responses_route

    original_payload = {"providers": {"onemin": {"state": "degraded", "configured_slots": 3}}}
    refreshed_payload = {"providers": {"onemin": {"state": "ready", "configured_slots": 3}}}
    responses_route.remember_provider_health_snapshot_cache(lightweight=True, payload=original_payload)
    monkeypatch.setattr(responses_route, "_provider_health_snapshot", lambda *, lightweight: refreshed_payload)

    asyncio.run(responses_route.prewarm_provider_health_snapshot_cache(lightweight=True, timeout_seconds=0.5))

    cached, age_seconds = responses_route._cached_provider_health_snapshot(lightweight=True)
    assert cached == refreshed_payload
    assert age_seconds is not None
