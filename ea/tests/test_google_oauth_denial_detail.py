from __future__ import annotations

from app.api.routes.landing_setup import _google_oauth_denial_detail


def test_google_oauth_access_denied_names_expected_test_user_blocker() -> None:
    detail = _google_oauth_denial_detail(
        error="access_denied",
        state_payload={"expected_google_email": "work.owner@example.test"},
    )

    assert "work.owner@example.test" in detail
    assert "OAuth test user" in detail
    assert "Full Workspace link" in detail


def test_google_location_history_access_denied_keeps_portability_detail() -> None:
    detail = _google_oauth_denial_detail(
        error="access_denied",
        state_payload={"oauth_lane": "google_location_history"},
    )

    assert "Data Portability consent" in detail
    assert "OAuth test user" in detail


def test_google_oauth_non_access_denied_preserves_google_description() -> None:
    detail = _google_oauth_denial_detail(
        error="temporarily_unavailable",
        error_description="Google provider is temporarily unavailable.",
    )

    assert detail == "Google provider is temporarily unavailable."
