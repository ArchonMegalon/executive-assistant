from __future__ import annotations

from io import BytesIO
import json
import urllib.error

from app.services.tough_tongue import (
    ToughTongueConfig,
    probe_tough_tongue_balance,
)
from scripts.sync_env_to_teable import _provider_guess


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


def _config(**overrides: object) -> ToughTongueConfig:
    values: dict[str, object] = {
        "api_key": "private-test-token",
        "organization_id": "private-org-ref",
        "base_url": "https://api.toughtongueai.com/api/public",
        "login_email": "login@example.test",
        "forwarding_email": "forward@example.test",
        "account_tier": "4",
        "enabled": False,
        "account_verified": False,
        "provider_verified": False,
        "auto_create_sessions": False,
        "allow_outbound_calls": False,
        "allow_meeting_bots": False,
        "allow_purchases": False,
        "allow_publication": False,
        "min_remaining_minutes": 30.0,
        "max_session_minutes": 15.0,
    }
    values.update(overrides)
    return ToughTongueConfig(**values)  # type: ignore[arg-type]


def test_tough_tongue_probe_is_get_only_and_redacts_credentials() -> None:
    observed: dict[str, object] = {}

    def _open(request: object, *, timeout: float) -> _Response:
        observed["method"] = request.get_method()  # type: ignore[attr-defined]
        observed["url"] = request.full_url  # type: ignore[attr-defined]
        observed["authorization"] = request.get_header("Authorization")  # type: ignore[attr-defined]
        observed["organization"] = request.get_header("X-tt-org")  # type: ignore[attr-defined]
        observed["timeout"] = timeout
        return _Response({"available_minutes": 4109.7, "last_updated": "2026-08-14T13:00:00Z"})

    report = probe_tough_tongue_balance(config=_config(), opener=_open)

    assert report["probe_ok"] is True
    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["remaining"] == 4109.7
    assert observed["method"] == "GET"
    assert observed["url"] == "https://api.toughtongueai.com/api/public/balance"
    assert observed["authorization"] == "Bearer private-test-token"
    assert observed["organization"] == "private-org-ref"
    rendered = json.dumps(report, sort_keys=True)
    assert "private-test-token" not in rendered
    assert "login@example.test" not in rendered
    assert "forward@example.test" not in rendered
    assert report["raw"]["raw_credentials_exposed"] is False  # type: ignore[index]
    assert report["raw"]["organization_configured"] is True  # type: ignore[index]
    assert "private-org-ref" not in rendered


def test_tough_tongue_probe_fails_closed_without_api_key() -> None:
    called = False

    def _open(*_args: object, **_kwargs: object) -> _Response:
        nonlocal called
        called = True
        return _Response({})

    report = probe_tough_tongue_balance(config=_config(api_key=""), opener=_open)

    assert called is False
    assert report["probe_ok"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "tough_tongue_api_key_missing"
    assert report["next_action"] == "create_tough_tongue_personal_access_token_after_operator_approval"


def test_tough_tongue_probe_reports_auth_failure_without_response_body() -> None:
    def _open(request: object, *, timeout: float) -> _Response:
        raise urllib.error.HTTPError(
            request.full_url,  # type: ignore[attr-defined]
            401,
            "Unauthorized private-test-token",
            hdrs=None,
            fp=None,
        )

    report = probe_tough_tongue_balance(config=_config(), opener=_open)

    assert report["probe_ok"] is False
    assert report["status"] == "auth_failed"
    assert report["reason"] == "tough_tongue_auth_failed"
    assert report["raw"]["http_status"] == 401  # type: ignore[index]
    assert "private-test-token" not in json.dumps(report, sort_keys=True)


def test_tough_tongue_execution_requires_every_verification_gate() -> None:
    assert _config(enabled=True, account_verified=True, provider_verified=True).execution_ready is True
    assert _config(
        enabled=True,
        account_verified=True,
        provider_verified=True,
        organization_id="",
    ).execution_ready is False
    assert _config(enabled=True, account_verified=False, provider_verified=True).execution_ready is False
    assert _config(enabled=False, account_verified=True, provider_verified=True).execution_ready is False


def test_tough_tongue_api_key_is_classified_for_teable_recovery() -> None:
    assert _provider_guess("TOUGH_TONGUE_API_KEY") == "tough_tongue"
