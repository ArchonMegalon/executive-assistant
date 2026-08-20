from __future__ import annotations

from io import BytesIO
import json
import urllib.error

from app.services.tough_tongue import (
    ToughTongueConfig,
    probe_tough_tongue_balance,
)
from app.services.provider_accounts import ProviderAccountSlot
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


def _slot(
    index: int,
    credential: str,
    *,
    account_ref: str = "",
    organization_ref: str = "",
    plan_name: str = "team",
) -> ProviderAccountSlot:
    return ProviderAccountSlot(
        provider_key="tough_tongue",
        slot_label=f"team-slot-{index}",
        credential=credential,
        account_ref=account_ref,
        organization_ref=organization_ref,
        plan_name=plan_name,
    )


def test_tough_tongue_team_probe_deduplicates_duplicate_tokens_and_account_refs() -> None:
    calls = 0

    def _open(_request: object, *, timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        return _Response({"available_minutes": 70, "last_updated": "2026-08-20T10:00:00Z"})

    report = probe_tough_tongue_balance(
        config=_config(
            account_slots=(
                _slot(1, "duplicate-token", account_ref="account-one"),
                _slot(2, "duplicate-token", account_ref="account-two"),
                _slot(3, "different-token", account_ref="account-one"),
            )
        ),
        opener=_open,
    )

    assert calls == 1
    assert report["aggregate"]["configured_count"] == 3  # type: ignore[index]
    assert report["aggregate"]["distinct_count"] == 1  # type: ignore[index]
    assert report["aggregate"]["remaining_total"] == 70.0  # type: ignore[index]
    rendered = json.dumps(report, sort_keys=True)
    assert "duplicate-token" not in rendered
    assert "different-token" not in rendered
    assert "account-one" not in rendered


def test_tough_tongue_team_probe_does_not_double_count_a_shared_organization_pool() -> None:
    calls = 0

    def _open(_request: object, *, timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        return _Response({"available_minutes": 95, "last_updated": "2026-08-20T10:00:00Z"})

    report = probe_tough_tongue_balance(
        config=_config(
            account_slots=(
                _slot(1, "team-token-one", account_ref="account-one", organization_ref="shared-org"),
                _slot(2, "team-token-two", account_ref="account-two", organization_ref="shared-org"),
            )
        ),
        opener=_open,
    )

    assert calls == 2
    assert report["ready"] is True
    assert report["remaining"] == 95.0
    assert report["aggregate"]["aggregate_basis"] == "shared_team_pool"  # type: ignore[index]
    assert report["aggregate"]["shared_pool"] is True  # type: ignore[index]
    assert report["aggregate"]["remaining_total"] == 95.0  # type: ignore[index]


def test_tough_tongue_team_probe_can_be_ready_while_a_slot_is_degraded() -> None:
    def _open(request: object, *, timeout: float) -> _Response:
        authorization = request.get_header("Authorization")  # type: ignore[attr-defined]
        if authorization == "Bearer rejected-token":
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                401,
                "Unauthorized rejected-token",
                hdrs=None,
                fp=None,
            )
        return _Response({"available_minutes": 75, "last_updated": "2026-08-20T11:00:00Z"})

    report = probe_tough_tongue_balance(
        config=_config(
            aggregate_basis="independent_accounts_sum",
            account_slots=(
                _slot(1, "healthy-token", account_ref="account-one", organization_ref="org-one"),
                _slot(2, "rejected-token", account_ref="account-two", organization_ref="org-two"),
            ),
        ),
        opener=_open,
    )

    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["reason"] == "tough_tongue_team_probe_degraded"
    assert report["aggregate"]["remaining_total"] == 75.0  # type: ignore[index]
    assert report["aggregate"]["unavailable_count"] == 1  # type: ignore[index]
    assert report["aggregate"]["degraded"] is True  # type: ignore[index]
    assert "rejected-token" not in json.dumps(report, sort_keys=True)


def test_tough_tongue_team_probe_refuses_to_sum_unknown_pools_and_tracks_mixed_refresh() -> None:
    def _open(request: object, *, timeout: float) -> _Response:
        authorization = request.get_header("Authorization")  # type: ignore[attr-defined]
        if authorization == "Bearer team-token-one":
            return _Response({"available_minutes": 10, "last_updated": "2026-08-19T09:00:00Z"})
        return _Response({"available_minutes": 25, "last_updated": "2026-08-20T09:00:00Z"})

    report = probe_tough_tongue_balance(
        config=_config(
            login_email="team-owner@example.test",
            forwarding_email="team-forward@example.test",
            account_slots=(
                _slot(1, "team-token-one", account_ref="account-one"),
                _slot(2, "team-token-two", account_ref="account-two"),
            ),
        ),
        opener=_open,
    )

    assert report["ready"] is False
    assert report["remaining"] == 25.0
    assert report["aggregate"]["aggregate_basis"] == "unknown_no_sum"  # type: ignore[index]
    assert report["aggregate"]["remaining_total"] is None  # type: ignore[index]
    assert report["aggregate"]["refresh_at_mixed"] is True  # type: ignore[index]
    rendered = json.dumps(report, sort_keys=True)
    assert "team-owner@example.test" not in rendered
    assert "team-forward@example.test" not in rendered
    assert all(row["account_emails_exposed"] is False for row in report["accounts"])  # type: ignore[index]


def test_tough_tongue_env_registry_probes_all_six_governed_team_accounts(monkeypatch) -> None:
    credentials = [f"team-secret-{index}" for index in range(1, 7)]
    account_refs = [f"opaque-account-{index}" for index in range(1, 7)]
    organization_refs = [f"independent-org-{index}" for index in range(1, 7)]
    monkeypatch.setenv("CHUMMER_BUILD_GHOST_TOUGH_TONGUE_API_KEYS", ";".join(credentials))
    monkeypatch.setenv("CHUMMER_BUILD_GHOST_TOUGH_TONGUE_ACCOUNT_REFS", ";".join(account_refs))
    monkeypatch.setenv("TOUGH_TONGUE_ORGANIZATION_IDS", ";".join(organization_refs))
    monkeypatch.setenv("EA_TOUGH_TONGUE_AGGREGATE_BASIS", "independent_accounts_sum")

    calls = 0

    def _open(_request: object, *, timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        return _Response({"available_minutes": 20, "last_updated": "2026-08-20T12:00:00Z"})

    report = probe_tough_tongue_balance(opener=_open)

    assert calls == 6
    assert report["ready"] is True
    assert report["remaining"] == 120.0
    assert report["aggregate"]["configured_count"] == 6  # type: ignore[index]
    assert report["aggregate"]["distinct_count"] == 6  # type: ignore[index]
    assert report["aggregate"]["remaining_total"] == 120.0  # type: ignore[index]
    rendered = json.dumps(report, sort_keys=True)
    assert all(secret not in rendered for secret in credentials)
    assert all(account_ref not in rendered for account_ref in account_refs)
    assert all(organization_ref not in rendered for organization_ref in organization_refs)
