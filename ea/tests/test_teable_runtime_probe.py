from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

import pytest

from app.product import service as product_service_module
from app.product.service import ProductService


def _service() -> ProductService:
    return ProductService(SimpleNamespace(preference_profiles=SimpleNamespace()))


def test_teable_runtime_probe_timeout_defaults_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service()
    monkeypatch.delenv("TEABLE_RUNTIME_PROBE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TEABLE_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TEABLE_TABLE_SYNC_REQUEST_TIMEOUT_SECONDS", raising=False)

    assert service._teable_runtime_probe_timeout_seconds() == 3.0

    monkeypatch.setenv("TEABLE_RUNTIME_PROBE_TIMEOUT_SECONDS", "0.1")
    assert service._teable_runtime_probe_timeout_seconds() == 0.5

    monkeypatch.setenv("TEABLE_RUNTIME_PROBE_TIMEOUT_SECONDS", "999")
    assert service._teable_runtime_probe_timeout_seconds() == 15.0

    monkeypatch.setenv("TEABLE_RUNTIME_PROBE_TIMEOUT_SECONDS", "bad")
    assert service._teable_runtime_probe_timeout_seconds() == 3.0


def test_teable_runtime_probe_reports_timeout_without_fallback_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service()
    calls: list[tuple[str, float]] = []

    def _timeout_urlopen(request: object, *, timeout: float) -> object:
        calls.append((str(getattr(request, "full_url", "")), timeout))
        raise TimeoutError("probe timed out")

    monkeypatch.setenv("TEABLE_API_KEY", "test-token")
    monkeypatch.setattr(product_service_module.urllib.request, "urlopen", _timeout_urlopen)

    reachable, reason = service._teable_sync_runtime_available(
        base_url="https://teable.example",
        timeout_seconds=0.5,
    )

    assert reachable is False
    assert reason == "teable_runtime_probe_timeout"
    assert calls == [("https://teable.example/healthz", 0.5)]


def test_teable_runtime_probe_uses_auth_user_fallback_after_missing_healthz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[str, float]] = []

    class _Response:
        status = 200

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"email": "ops@example.com"}).encode("utf-8")

    def _urlopen(request: object, *, timeout: float) -> object:
        url = str(getattr(request, "full_url", ""))
        calls.append((url, timeout))
        if url.endswith("/healthz"):
            raise urllib.error.HTTPError(url, 404, "not found", hdrs=None, fp=None)
        return _Response()

    monkeypatch.setenv("TEABLE_API_KEY", "test-token")
    monkeypatch.setattr(product_service_module.urllib.request, "urlopen", _urlopen)

    reachable, reason = service._teable_sync_runtime_available(
        base_url="https://teable.example",
        timeout_seconds=0.75,
    )

    assert reachable is True
    assert reason == ""
    assert calls == [
        ("https://teable.example/healthz", 0.75),
        ("https://teable.example/api/auth/user", 0.75),
    ]


def test_preference_teable_preview_surfaces_probe_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_timeout: list[float] = []

    class _PreferenceProfiles:
        def build_teable_projection_records(self, **_: object) -> dict[str, list[dict[str, object]]]:
            return {
                "preference_review_queue": [
                    {
                        "projection_id": "pref-1",
                        "person_id": "self",
                        "domain": "office_routing",
                        "category": "constraint",
                        "key": "primary_work_google_workspace_email",
                    }
                ]
            }

    class _ProviderRegistry:
        def binding_state(self, *_: object, **__: object) -> object:
            return SimpleNamespace(
                state="enabled",
                display_name="Teable",
                enabled=True,
                executable=True,
                binding_id="teable-binding",
                secret_configured=True,
                updated_at="2026-07-01T08:00:00Z",
            )

        def candidate_routes_by_capability_with_context(self, *_: object, **__: object) -> tuple[object, ...]:
            return (
                SimpleNamespace(
                    provider_key="teable",
                    executable=True,
                    tool_name="provider.teable.table_sync",
                ),
            )

    container = SimpleNamespace(
        preference_profiles=_PreferenceProfiles(),
        provider_registry=_ProviderRegistry(),
    )
    service = ProductService(container)

    def _probe(*, base_url: str, timeout_seconds: float | None = None) -> tuple[bool, str]:
        captured_timeout.append(float(timeout_seconds or 0.0))
        return False, "teable_runtime_probe_timeout"

    monkeypatch.setenv(
        "TEABLE_TABLE_SYNC_CONFIG_JSON",
        json.dumps({"preference_review_queue": {"table_id": "tbl-pref", "key_field": "projection_id"}}),
    )
    monkeypatch.setenv("TEABLE_RUNTIME_PROBE_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setattr(service, "_teable_sync_runtime_available", _probe)

    preview = service.preference_teable_sync_preview(
        principal_id="cf-email:tibor.girschele@gmail.com",
        person_id="self",
    )

    assert preview["status"] == "blocked"
    assert preview["blocked_reason"] == "teable_runtime_probe_timeout"
    assert dict(preview["provider"])["runtime_probe_timeout_seconds"] == 0.5
    assert captured_timeout == [0.5]
