from __future__ import annotations

import os

import pytest

os.environ.setdefault("EA_INLINE_SYNC_HANDLERS", "1")


def _reset_shared_runtime_state() -> None:
    try:
        from app.services import cloudflare_access

        cloudflare_access._jwks_client.cache_clear()
    except Exception:
        pass
    try:
        from app.services import responses_upstream

        responses_upstream._test_reset_onemin_states()
        responses_upstream._test_reset_fleet_jury_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_environment_and_shared_runtime_state() -> None:
    snapshot = dict(os.environ)
    _reset_shared_runtime_state()
    yield
    current_keys = set(os.environ.keys())
    original_keys = set(snapshot.keys())
    for key in current_keys - original_keys:
        os.environ.pop(key, None)
    for key in original_keys:
        os.environ[key] = snapshot[key]
    _reset_shared_runtime_state()
