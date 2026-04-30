from __future__ import annotations

import hashlib
import json
import time
import pytest

from app.domain.models import ToolInvocationResult
from app.services import responses_upstream as upstream


class _SlowUrlopenResponse:
    def __init__(
        self,
        *,
        body_chunks: list[bytes] | None = None,
        line_chunks: list[bytes] | None = None,
        tick_seconds: float = 0.0,
        advance_clock=None,
        status: int = 200,
    ) -> None:
        self.status = status
        self._body_chunks = list(body_chunks or [])
        self._line_chunks = list(line_chunks or [])
        self._tick_seconds = float(tick_seconds)
        self._advance_clock = advance_clock
        self.timeouts: list[float] = []

    def __enter__(self) -> _SlowUrlopenResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def settimeout(self, timeout_seconds: float) -> None:
        self.timeouts.append(float(timeout_seconds))

    def read(self, _size: int = -1) -> bytes:
        if not self._body_chunks:
            return b""
        if self._advance_clock is not None:
            self._advance_clock(self._tick_seconds)
        return self._body_chunks.pop(0)

    def readline(self, _size: int = -1) -> bytes:
        if not self._line_chunks:
            return b""
        if self._advance_clock is not None:
            self._advance_clock(self._tick_seconds)
        return self._line_chunks.pop(0)


def test_default_public_model_uses_easy_lane_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magicxai,onemin")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best,review-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.DEFAULT_PUBLIC_MODEL)
    ]

    assert candidates == [
        ("onemin", "gpt-5.4"),
        ("onemin", "gpt-5"),
        ("onemin", "gpt-4o"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
    ]


def test_principal_identity_summary_includes_lane_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_PRINCIPAL_LANE_ROLE_OVERRIDES_JSON", json.dumps({"participant-review-1": "review"}))
    summary = upstream.principal_identity_summary("participant-review-1")

    assert summary["lane_role"] == "review"


def test_blank_requested_model_uses_easy_lane_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("")
    ]

    assert candidates == [
        ("onemin", "gpt-5.4"),
        ("onemin", "gpt-5"),
        ("onemin", "gpt-4o"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
    ]


def test_onemin_nano_model_is_not_treated_as_code_capable() -> None:
    assert upstream._onemin_model_supports_code("gpt-4.1-nano") is False
    assert upstream._onemin_model_supports_code("deepseek-chat") is True


def test_onemin_account_login_credentials_reads_team_hints_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_60_TEAM_ID", "team-60")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_60_TEAM_NAME", "Finland Office")

    credentials = upstream.onemin_account_login_credentials(account_name="ONEMIN_AI_API_KEY_FALLBACK_60")

    assert credentials == {
        "login_email": "",
        "login_password": "",
        "team_id": "team-60",
        "team_name": "Finland Office",
    }


def test_default_core_profile_auto_demotes_to_fast_when_onemin_health_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_DEFAULT_PROFILE", "core")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "state": "ready",
                    "remaining_percent_of_max": 42.0,
                    "unknown_balance_slots": 0,
                    "last_actual_balance_at": "2026-03-22T00:00:00Z",
                    "last_probe_at": "2026-03-22T00:00:00Z",
                }
            }
        },
    )

    assert upstream._effective_request_lane(requested_model="", max_output_tokens=None) == "fast"


def test_explicit_hard_model_stays_hard_even_when_onemin_health_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_DEFAULT_PROFILE", "core")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda: {
            "providers": {
                "onemin": {
                    "state": "degraded",
                    "remaining_percent_of_max": None,
                    "unknown_balance_slots": 5,
                    "last_actual_balance_at": "",
                    "last_probe_at": "",
                }
            }
        },
    )

    assert upstream._effective_request_lane(requested_model="ea-coder-hard", max_output_tokens=None) == "hard"


def test_default_public_model_stays_onemin_only_when_the_primary_backend_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    def fake_call_onemin(*args: object, **kwargs: object) -> upstream.UpstreamResult:
        raise upstream.ResponsesUpstreamError("invalid api key")

    def fake_call_gemini_vortex(*args: object, **kwargs: object) -> upstream.UpstreamResult:
        raise AssertionError("default public model must not fall back to gemini")

    def fake_call_magicx(*args: object, **kwargs: object) -> upstream.UpstreamResult:
        raise AssertionError("default public model must not fall back to magicx")

    monkeypatch.setattr(upstream, "_call_onemin", fake_call_onemin)
    monkeypatch.setattr(upstream, "_call_magicx", fake_call_magicx)
    monkeypatch.setattr(upstream, "_call_gemini_vortex", fake_call_gemini_vortex)

    with pytest.raises(upstream.ResponsesUpstreamError, match="onemin/gpt-5.4:invalid api key"):
        upstream.generate_text(prompt="fallback please", requested_model=upstream.DEFAULT_PUBLIC_MODEL)


def test_fast_public_model_candidates_prefer_gemini_then_magicx_without_onemin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("ea-coder-fast")
    ]

    assert candidates == [
        ("onemin", "gpt-5.4"),
        ("onemin", "gpt-5"),
        ("onemin", "gpt-4o"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
    ]


def test_onemin_required_credits_for_selection_uses_model_family_defaults_before_global_median(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upstream, "_recent_onemin_dispatch_credit_estimate", lambda **_kwargs: None)
    monkeypatch.setattr(
        upstream,
        "_estimate_onemin_request_credits",
        lambda **_kwargs: (57500, "recent_required_credit_median"),
    )

    light_required, light_basis = upstream._onemin_required_credits_for_selection(
        lane=upstream._LANE_FAST,
        model="deepseek-chat",
    )
    hard_required, hard_basis = upstream._onemin_required_credits_for_selection(
        lane=upstream._LANE_FAST,
        model="gpt-5.4",
    )

    assert (light_required, light_basis) == (1200, "model_family_default")
    assert (hard_required, hard_basis) == (50000, "model_family_default")


def test_onemin_required_credits_for_selection_caps_poisoned_light_dispatch_median(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upstream, "_recent_onemin_dispatch_credit_estimate", lambda **_kwargs: 58306)

    required, basis = upstream._onemin_required_credits_for_selection(
        lane="core",
        model="gpt-4.1-nano",
    )

    assert (required, basis) == (1200, "model_family_default_capped_recent_dispatch")


def test_hard_public_model_candidates_downshift_when_live_slot_budget_cannot_cover_hard_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_HARD_MODELS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_HARD_FALLBACK_MODELS", raising=False)
    monkeypatch.setattr(upstream, "_recent_onemin_dispatch_credit_estimate", lambda **_kwargs: None)
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda **_kwargs: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "state": "ready",
                            "estimated_remaining_credits": 1500,
                        }
                    ]
                }
            }
        },
    )

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("ea-coder-hard")
    ]

    assert candidates == [
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-5.4"),
        ("onemin", "gpt-5"),
        ("onemin", "gpt-4o"),
    ]


def test_hard_public_model_candidates_keep_premium_order_when_live_slot_budget_supports_hard_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_HARD_MODELS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_HARD_FALLBACK_MODELS", raising=False)
    monkeypatch.setattr(upstream, "_recent_onemin_dispatch_credit_estimate", lambda **_kwargs: None)
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda **_kwargs: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "state": "ready",
                            "estimated_remaining_credits": 75000,
                        }
                    ]
                }
            }
        },
    )

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("ea-coder-hard")
    ]

    assert candidates == [
        ("onemin", "gpt-5.4"),
        ("onemin", "gpt-5"),
        ("onemin", "gpt-4o"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
    ]


def test_repair_gemini_public_model_uses_gemini_only_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-repair")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.REPAIR_GEMINI_PUBLIC_MODEL)
    ]

    assert candidates == [("gemini_vortex", "gemini-repair")]


def test_hard_lane_code_defaults_are_safe_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_HARD_QUEUE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY", raising=False)

    assert upstream._resolve_hard_defaults() == (8, 120.0, 256)
    assert upstream._lane_max_output_tokens(upstream._LANE_HARD) == 1536
    assert upstream._onemin_max_credits_per_hour() == 80000
    assert upstream._onemin_max_credits_per_day() == 600000


def test_onemin_json_manifest_slots_feed_keys_and_account_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fallback-1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS", "primary,fallback_1,fallback_55")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_RESERVE_SLOTS", "fallback_56")
    monkeypatch.setenv(
        "ONEMIN_DIRECT_API_KEYS_JSON",
        json.dumps(
            [
                {
                    "slot": "fallback_55",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_55",
                    "key": "json-key-55",
                },
                {
                    "slot": "fallback_56",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_56",
                    "key": "json-key-56",
                },
            ]
        ),
    )

    assert upstream._onemin_secret_env_names() == (
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_55",
        "ONEMIN_AI_API_KEY_FALLBACK_56",
    )
    key_names = upstream._onemin_key_names()
    assert key_names == ("primary-key", "fallback-1", "json-key-55", "json-key-56")
    assert upstream._provider_account_name("onemin", key_names=key_names, key="json-key-55") == "ONEMIN_AI_API_KEY_FALLBACK_55"
    assert upstream._onemin_key_slot("json-key-55", key_names=key_names) == "fallback_55"
    assert upstream._provider_secret_from_account_name("ONEMIN_AI_API_KEY_FALLBACK_56") == "json-key-56"


def test_pick_onemin_key_skips_zero_credit_observed_error_even_with_stale_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("dead", "good")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "dead":
            return (0, "observed_error", False, 995.0, 995.0)
        return (245045, "observed_error", False, 995.0, 995.0)

    def fake_recent_success(*, api_key: str, **_: object) -> tuple[float, float, float, int, int]:
        if api_key == "dead":
            return (900.0, 900.0, 900.0, 653, 653)
        return (0.0, 0.0, 0.0, 0, 0)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", fake_recent_success)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5",
        required_credits=653,
    )

    assert pick is not None
    assert pick[0] == "good"


def test_pick_onemin_key_skips_observed_error_below_required_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("low", "good")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "low":
            return (489, "observed_error", False, 995.0, 995.0)
        return (245045, "observed_error", False, 995.0, 995.0)

    def fake_recent_success(*, api_key: str, **_: object) -> tuple[float, float, float, int, int]:
        if api_key == "low":
            return (900.0, 900.0, 900.0, 489, 489)
        return (0.0, 0.0, 0.0, 0, 0)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", fake_recent_success)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5",
        required_credits=653,
    )

    assert pick is not None
    assert pick[0] == "good"


def test_pick_onemin_key_returns_none_when_all_known_balances_are_below_required_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("low_a", "low_b")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "low_a":
            return (4099, "observed_error", False, 995.0, 995.0)
        return (840, "observed_error", False, 995.0, 995.0)

    def fake_recent_success(*, api_key: str, **_: object) -> tuple[float, float, float, int, int]:
        if api_key == "low_a":
            return (900.0, 900.0, 900.0, 4099, 4099)
        return (900.0, 900.0, 900.0, 840, 840)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", fake_recent_success)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5.4",
        required_credits=73111,
    )

    assert pick is None


def test_pick_onemin_key_skips_probe_depleted_slot_even_with_recent_success_and_positive_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("probe-depleted", "healthy")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(upstream, "_onemin_key_names", lambda: keys)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {
            "probe-depleted": upstream.OneminKeyState(key="probe-depleted", last_success_at=995.0),
            "healthy": upstream.OneminKeyState(key="healthy"),
        },
    )
    monkeypatch.setattr(
        upstream,
        "_provider_account_name",
        lambda _provider, key_names, key: f"account-{key}",
    )
    monkeypatch.setattr(
        upstream,
        "_onemin_key_slot",
        lambda key, key_names: f"slot-{key}",
    )
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda **_kwargs: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "account-probe-depleted",
                            "slot": "slot-probe-depleted",
                            "state": "ready",
                            "billing_remaining_credits": 15000,
                            "estimated_remaining_credits": 13297,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the Team only has 139 credits",
                        },
                        {
                            "account_name": "account-healthy",
                            "slot": "slot-healthy",
                            "state": "ready",
                            "remaining_credits": 5000,
                            "last_probe_result": "ok",
                            "last_probe_detail": "OK",
                        },
                    ]
                }
            }
        },
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "probe-depleted":
            return (15000, "actual_billing_usage_page", True, 995.0, 995.0)
        return (5000, "actual_billing_usage_page", True, 995.0, 995.0)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", lambda **_kwargs: (0.0, 0.0, 0.0, 0, 0))

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_FAST,
        model="gpt-5.4",
        required_credits=1726,
    )

    assert pick is not None
    assert pick[0] == "healthy"


def test_pick_onemin_key_keeps_actual_billing_positive_account_routable_despite_observed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("low_actual", "low_other")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )
    monkeypatch.setattr(
        upstream,
        "_provider_account_name",
        lambda _provider, key_names, key: f"account-{key}",
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "low_actual":
            return (4099, "observed_error", False, 995.0, 995.0)
        return (840, "observed_error", False, 995.0, 995.0)

    def fake_recent_success(*, api_key: str, **_: object) -> tuple[float, float, float, int, int]:
        return (0.0, 0.0, 0.0, 0, 0)

    def fake_latest_billing(*, provider_key: str, account_name: str):
        if provider_key == "onemin" and account_name == "account-low_actual":
            return upstream.ProviderBillingSnapshot(
                provider_key="onemin",
                account_name=account_name,
                observed_at="2026-04-28T20:00:00Z",
                remaining_credits=4255550.0,
                max_credits=4450000.0,
                next_topup_at=None,
                topup_amount=None,
                basis="actual_billing_usage_page",
                structured_output_json={"team_name": "Example Team"},
            )
        return None

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", fake_recent_success)
    monkeypatch.setattr(upstream, "_latest_provider_billing_snapshot", fake_latest_billing)
    monkeypatch.setattr(upstream, "_onemin_billing_snapshot_matches_credit_subject", lambda **_kwargs: True)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5.4",
        required_credits=73111,
    )

    assert pick is not None
    assert pick[0] == "low_actual"


def test_pick_onemin_key_prefers_recent_probe_ok_candidate_despite_stale_observed_depletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("probe_ok", "probe_bad")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )
    monkeypatch.setattr(upstream, "_provider_account_name", lambda _provider, key_names, key: f"account-{key}")
    monkeypatch.setattr(upstream, "_onemin_key_slot", lambda key, key_names: f"slot-{key}")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda **_kwargs: {
            "providers": {
                "onemin": {
                    "slots": [
                        {"account_name": "account-probe_ok", "slot": "slot-probe_ok", "last_probe_result": "ok"},
                        {"account_name": "account-probe_bad", "slot": "slot-probe_bad", "last_probe_result": "depleted"},
                    ]
                }
            }
        },
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "probe_ok":
            return (4099, "observed_error", False, 995.0, 995.0)
        return (840, "observed_error", False, 995.0, 995.0)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", lambda **_kwargs: (0.0, 0.0, 0.0, 0, 0))
    monkeypatch.setattr(upstream, "_latest_provider_billing_snapshot", lambda **_kwargs: None)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5.4",
        required_credits=73111,
    )

    assert pick is not None
    assert pick[0] == "probe_ok"


def test_pick_onemin_key_prefers_observed_balance_over_synthetic_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("synthetic", "observed")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {key: upstream.OneminKeyState(key=key) for key in keys},
    )

    def fake_credit_snapshot_state(*, api_key: str, **_: object) -> tuple[int | None, str, bool, float, float]:
        if api_key == "synthetic":
            return (4052633, "max_minus_observed_usage", False, 0.0, 995.0)
        return (245045, "observed_error", False, 995.0, 995.0)

    def fake_recent_success(*, api_key: str, **_: object) -> tuple[float, float, float, int, int]:
        return (900.0, 900.0, 900.0, 2573, 2573)

    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", fake_credit_snapshot_state)
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", fake_recent_success)

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_HARD,
        model="gpt-5",
        required_credits=1144,
    )

    assert pick is not None
    assert pick[0] == "observed"


def test_pick_onemin_key_returns_none_when_only_blocked_keys_remain_for_credit_bound_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ("blocked-a", "blocked-b")

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(upstream, "_now_epoch", lambda: 1000.0)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {
            "blocked-a": upstream.OneminKeyState(key="blocked-a", quarantine_until=1300.0),
            "blocked-b": upstream.OneminKeyState(key="blocked-b", cooldown_until=1250.0),
        },
    )

    pick = upstream._pick_onemin_key(
        allow_reserve=True,
        key_names=keys,
        lane=upstream._LANE_FAST,
        model="gpt-5.4",
        required_credits=1726,
    )

    assert pick is None


def test_groundwork_public_model_uses_gemini_only_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-groundwork")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model,jury-model")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.GROUNDWORK_PUBLIC_MODEL)
    ]

    assert candidates == [("gemini_vortex", "gemini-groundwork")]


def test_groundwork_legacy_alias_routes_to_same_gemini_only_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-groundwork")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model,jury-model")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.GROUNDWORK_PUBLIC_MODEL_ALIAS)
    ]

    assert candidates == [("gemini_vortex", "gemini-groundwork")]


def test_review_light_public_model_uses_single_chatplayground_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_REVIEW_LIGHT_CHATPLAYGROUND_MODELS", "gpt-4.1,gpt-5")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.REVIEW_LIGHT_PUBLIC_MODEL)
    ]

    assert candidates == [("chatplayground", "gpt-4.1")]


def test_provider_prefixed_request_uses_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("magicx:claude-sonnet-4.5")
    ]

    assert candidates == [("magixai", "claude-sonnet-4.5")]


def test_normalize_provider_aliases_for_magicx_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")

    for alias in ("magicxai", "aimagicx", "ai_magicx"):
        candidates = [
            (config.provider_key, model)
            for config, model in upstream._provider_candidates(f"{alias}:grok")
        ]
        assert candidates == [("magixai", "grok")]


def test_audit_model_candidates_route_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model,jury-model")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_4", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_5", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_6", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_7", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_8", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_9", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_10", "")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL)
    ]
    assert candidates == [("chatplayground", "judge-model"), ("chatplayground", "jury-model")]


def test_audit_alias_candidates_route_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_4", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_5", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_6", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_7", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_8", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_9", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_10", "")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL_ALIAS)
    ]
    assert candidates == [("chatplayground", "judge-model")]


def test_audit_model_candidates_include_onemin_if_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "deepseek-chat")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "onemin-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL)
    ]
    assert candidates == [
        ("chatplayground", "judge-model"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-4.1"),
    ]


def test_normalize_provider_aliases_for_onemin_in_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "1min,magicx")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "om-best")

    assert upstream._provider_order() == ("onemin", "magixai")


def test_plain_onemin_model_stays_provider_exact_without_magicx_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5,gpt-4.1")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("gpt-5")
    ]

    assert candidates == [("onemin", "gpt-5")]


def test_plain_magicx_model_skips_onemin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "x-ai/grok-code-fast-1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("x-ai/grok-code-fast-1")
    ]

    assert candidates == [("magixai", "x-ai/grok-code-fast-1")]


def test_gemini_public_model_routes_to_gemini_vortex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-2.5-flash")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.GEMINI_VORTEX_PUBLIC_MODEL)
    ]

    assert candidates == [("gemini_vortex", "gemini-2.5-flash")]


def test_call_gemini_vortex_uses_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-2.5-flash")

    def fake_execute(self, request, definition):  # type: ignore[no-untyped-def]
        assert definition.tool_name == "provider.gemini_vortex.structured_generate"
        assert request.payload_json["model"] == "gemini-2.5-flash"
        assert "say ok" in str(request.payload_json["source_text"])
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=request.action_kind,
            target_ref="gemini-vortex:test",
            output_json={
                "normalized_text": '{\n  "text": "gemini ok"\n}',
                "structured_output_json": {"text": "gemini ok"},
                "model": "gemini-2.5-flash",
                "provider_key_slot": "fallback_1",
                "provider_account_name": "GOOGLE_API_KEY_FALLBACK_1",
            },
            receipt_json={},
            model_name="gemini-2.5-flash",
            tokens_in=5,
            tokens_out=3,
        )

    monkeypatch.setattr(upstream.GeminiVortexToolAdapter, "execute", fake_execute)

    result = upstream.generate_text(prompt="say ok", requested_model=upstream.GEMINI_VORTEX_PUBLIC_MODEL)

    assert result.provider_key == "gemini_vortex"
    assert result.provider_backend == "gemini_vortex_cli"
    assert result.model == "gemini-2.5-flash"
    assert result.provider_key_slot == "fallback_1"
    assert result.provider_account_name == "GOOGLE_API_KEY_FALLBACK_1"
    assert result.text == "gemini ok"
    assert result.tokens_in == 5
    assert result.tokens_out == 3


def test_call_magicx_uses_bearer_auth_and_url_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv(
        "EA_RESPONSES_MAGICX_URLS",
        "https://bad.magicx.local/api/v1/chat,https://good.magicx.local/api/v1/chat",
    )
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MAX_TOKENS", "48")

    calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers, payload))
        if "bad.magicx.local" in url:
            return (405, {"error": "method_not_allowed"})
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="say ok", requested_model=upstream.MAGICX_PUBLIC_MODEL)

    assert result.provider_key == "magixai"
    assert result.model == "openai/gpt-5.1-codex-mini"
    assert result.text == "ok"
    assert [url for url, _, _ in calls] == [
        "https://bad.magicx.local/api/v1/chat",
        "https://good.magicx.local/api/v1/chat",
    ]
    assert calls[0][1]["Authorization"] == "Bearer magicx-key"
    assert calls[0][2]["messages"] == [{"role": "user", "content": "say ok"}]
    assert calls[0][2]["max_tokens"] == 48


def test_call_magicx_preserves_system_and_user_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    upstream.generate_text(
        requested_model=upstream.MAGICX_PUBLIC_MODEL,
        messages=[
            {"role": "system", "content": "follow repo rules"},
            {"role": "developer", "content": "keep it short"},
            {"role": "user", "content": "say ok"},
        ],
    )

    assert calls[0]["messages"] == [
        {"role": "system", "content": "follow repo rules\n\nkeep it short"},
        {"role": "user", "content": "say ok"},
    ]


def test_call_magicx_populates_provider_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-primary")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(requested_model=upstream.MAGICX_PUBLIC_MODEL, prompt="ping")
    assert result.provider_backend == "aimagicx"
    assert result.provider_account_name == "EA_RESPONSES_MAGICX_API_KEY"


def test_call_onemin_populates_provider_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "onemin-secondary")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        assert headers["API-KEY"] == "onemin-primary"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(requested_model=upstream.ONEMIN_PUBLIC_MODEL, prompt="ping")
    assert result.provider_backend == "1min"
    assert result.provider_account_name == "ONEMIN_AI_API_KEY"


def test_call_onemin_records_manager_usage_and_updates_effective_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService, register_onemin_manager

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setattr(upstream, "_estimate_onemin_request_credits", lambda **_kwargs: (150, "test_estimate"))

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        assert headers["API-KEY"] == "onemin-primary"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "remaining_credits": 1000,
            "max_credits": 5000,
            "basis": "actual_provider_api",
        },
        source="test",
    )

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    register_onemin_manager(manager)
    try:
        result = upstream.generate_text(requested_model=upstream.ONEMIN_PUBLIC_MODEL, prompt="ping")
        assert result.text == "ok"

        leases = manager.leases_snapshot()
        assert len(leases) == 1
        assert leases[0]["actual_credits_delta"] == 150
        assert leases[0]["status"] == "released"

        health = upstream._provider_health_report()
        slot = health["providers"]["onemin"]["slots"][0]
        assert slot["billing_remaining_credits"] == 1000
        assert slot["estimated_remaining_credits"] == 850
        assert slot["estimated_credit_basis"] == "actual_provider_api_plus_observed_usage"
    finally:
        register_onemin_manager(None)


def test_call_onemin_prefers_manager_persisted_actual_credits_when_runtime_state_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService, register_onemin_manager

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "low-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "high-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setattr(upstream, "_estimate_onemin_request_credits", lambda **_kwargs: (25662, "test_estimate"))
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda lightweight=False: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "slot_role": "active",
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": 0,
                            "last_probe_result": "depleted",
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "fallback_1",
                            "slot_name": "fallback_1",
                            "credential_id": "fallback_1",
                            "state": "quarantine",
                            "slot_role": "active",
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": 0,
                            "last_probe_result": "depleted",
                        },
                    ]
                }
            }
        },
    )

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    manager._repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY",
                account_label="ONEMIN_AI_API_KEY",
                status="ready",
                remaining_credits=1049,
                max_credits=15000,
                last_billing_snapshot_at="2026-04-28T08:30:00Z",
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 1049.0,
                    "actual_max_credits": 15000.0,
                },
            ),
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_1",
                status="ready",
                remaining_credits=40000,
                max_credits=15000,
                last_billing_snapshot_at="2026-04-28T08:30:00Z",
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 40000.0,
                    "actual_max_credits": 15000.0,
                },
            ),
        ],
        credentials=[
            OneminCredential(
                credential_id="primary",
                account_id="ONEMIN_AI_API_KEY",
                slot_name="primary",
                secret_env_name="ONEMIN_AI_API_KEY",
                state="ready",
                remaining_credits=1049,
            ),
            OneminCredential(
                credential_id="fallback_1",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                slot_name="fallback_1",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_1",
                state="ready",
                remaining_credits=40000,
            ),
        ],
    )
    register_onemin_manager(manager)

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        assert headers["API-KEY"] == "high-key"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    try:
        result = upstream.generate_text(prompt="big request", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
        assert result.text == "ok"
        assert result.provider_account_name == "ONEMIN_AI_API_KEY_FALLBACK_1"
    finally:
        register_onemin_manager(None)


def test_call_onemin_stops_when_manager_reports_no_eligible_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import OneminAccount, OneminCredential
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService, register_onemin_manager

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "low-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "also-low-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setattr(upstream, "_estimate_onemin_request_credits", lambda **_kwargs: (25662, "test_estimate"))
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda lightweight=False: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "slot_role": "active",
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": 0,
                            "last_probe_result": "depleted",
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "fallback_1",
                            "slot_name": "fallback_1",
                            "credential_id": "fallback_1",
                            "state": "quarantine",
                            "slot_role": "active",
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": 0,
                            "last_probe_result": "depleted",
                        },
                    ]
                }
            }
        },
    )

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    manager._repo.replace_state(
        accounts=[
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY",
                account_label="ONEMIN_AI_API_KEY",
                status="ready",
                remaining_credits=1049,
                max_credits=15000,
                last_billing_snapshot_at="2026-04-28T08:30:00Z",
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 1049.0,
                    "actual_max_credits": 15000.0,
                },
            ),
            OneminAccount(
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                account_label="ONEMIN_AI_API_KEY_FALLBACK_1",
                status="ready",
                remaining_credits=894,
                max_credits=15000,
                last_billing_snapshot_at="2026-04-28T08:30:00Z",
                details_json={
                    "credit_basis": "actual_billing_usage_page",
                    "has_actual_billing": True,
                    "actual_remaining_credits": 894.0,
                    "actual_max_credits": 15000.0,
                },
            ),
        ],
        credentials=[
            OneminCredential(
                credential_id="primary",
                account_id="ONEMIN_AI_API_KEY",
                slot_name="primary",
                secret_env_name="ONEMIN_AI_API_KEY",
                state="ready",
                remaining_credits=1049,
            ),
            OneminCredential(
                credential_id="fallback_1",
                account_id="ONEMIN_AI_API_KEY_FALLBACK_1",
                slot_name="fallback_1",
                secret_env_name="ONEMIN_AI_API_KEY_FALLBACK_1",
                state="ready",
                remaining_credits=894,
            ),
        ],
    )
    register_onemin_manager(manager)

    def fail_post_json(**_: object) -> tuple[int, dict[str, object]]:
        raise AssertionError("manager should have blocked blind upstream fallback")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)

    try:
        with pytest.raises(upstream.ResponsesUpstreamError) as excinfo:
            upstream.generate_text(prompt="big request", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
        assert "onemin_no_eligible_account" in str(excinfo.value)
    finally:
        register_onemin_manager(None)


def test_call_onemin_provider_health_bypasses_stale_known_exhaustion_precheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "healthy-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1-nano")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda lightweight=False: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "ready",
                            "slot_role": "active",
                            "estimated_remaining_credits": 4200,
                            "billing_remaining_credits": 4200,
                            "last_probe_result": "ok",
                            "last_probe_detail": "OK",
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(
        upstream,
        "_onemin_known_exhaustion_message",
        lambda **_kwargs: "onemin_exhausted_for_request:453:ONEMIN_AI_API_KEY",
    )

    def fake_post_json(**_: object) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1-nano",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)
    result = upstream.generate_text(prompt="Reply with exactly ok.", requested_model="onemin:gpt-4.1-nano")
    assert result.text == "ok"
    assert result.provider_account_name == "ONEMIN_AI_API_KEY"


def test_call_onemin_uses_lightweight_provider_health_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "healthy-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1-nano")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    provider_health_calls: list[bool] = []

    def fake_provider_health_report(*, lightweight: bool = False) -> dict[str, object]:
        provider_health_calls.append(bool(lightweight))
        return {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "ready",
                            "slot_role": "active",
                            "estimated_remaining_credits": 4200,
                            "billing_remaining_credits": 4200,
                            "last_probe_result": "ok",
                            "last_probe_detail": "OK",
                        }
                    ]
                }
            }
        }

    monkeypatch.setattr(upstream, "_provider_health_report", fake_provider_health_report)

    def fake_post_json(**_: object) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1-nano",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 5,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="Reply with exactly ok.", requested_model="onemin:gpt-4.1-nano")

    assert result.text == "ok"
    assert provider_health_calls == [True]


def test_onemin_provider_health_pick_recovers_quarantined_budget_limited_slot_for_smaller_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "low-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "recoverable-key")

    pick = upstream._onemin_provider_health_pick(
        key_names=upstream._onemin_key_names(),
        provider_health={
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "estimated_remaining_credits": 219,
                            "billing_remaining_credits": 15025,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the Tibor Girschele team only has 219 credits",
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "fallback_1",
                            "slot_name": "fallback_1",
                            "credential_id": "fallback_1",
                            "state": "quarantine",
                            "estimated_remaining_credits": 59,
                            "billing_remaining_credits": 15000,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the franz@chummer.run team only has 1530 credits",
                        },
                    ]
                }
            }
        },
        required_credits=453,
        preferred_onemin_labels=("default",),
    )

    assert pick is not None
    assert pick[0] == "recoverable-key"


def test_onemin_provider_health_pick_rejects_quarantined_slot_with_only_upstream_reset_unknown_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "recoverable-key")

    pick = upstream._onemin_provider_health_pick(
        key_names=upstream._onemin_key_names(),
        provider_health={
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": 4255550,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1078 credits, but the Team only has 0 credits",
                            "upstream_reset_unknown": True,
                        },
                    ]
                }
            }
        },
        required_credits=900,
        preferred_onemin_labels=("default",),
    )

    assert pick is None


def test_onemin_provider_health_pick_rejects_depleted_slot_when_actual_remaining_is_below_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key")

    pick = upstream._onemin_provider_health_pick(
        key_names=upstream._onemin_key_names(),
        provider_health={
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "degraded",
                            "remaining_credits": 219,
                            "estimated_remaining_credits": 4_000_030,
                            "billing_remaining_credits": 4_000_030,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the team only has 219 credits",
                        },
                    ]
                }
            }
        },
        required_credits=10_118,
        preferred_onemin_labels=("default",),
    )

    assert pick is None


def test_onemin_provider_health_pick_rejects_ready_slot_when_probe_budget_signal_is_below_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key")

    pick = upstream._onemin_provider_health_pick(
        key_names=upstream._onemin_key_names(),
        provider_health={
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "ready",
                            "estimated_remaining_credits": 4_029_986,
                            "billing_remaining_credits": 4_029_986,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the Poland Office team only has 141 credits",
                        },
                    ]
                }
            }
        },
        required_credits=1_726,
        preferred_onemin_labels=("default",),
    )

    assert pick is None


def test_onemin_provider_health_pick_rejects_probe_ok_slot_with_zero_actual_remaining_and_no_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key")

    pick = upstream._onemin_provider_health_pick(
        key_names=upstream._onemin_key_names(),
        provider_health={
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "remaining_credits": 0,
                            "required_credits": 1_726,
                            "estimated_remaining_credits": 0,
                            "billing_remaining_credits": None,
                            "last_probe_result": "ok",
                            "last_probe_detail": "OK",
                        },
                    ]
                }
            }
        },
        required_credits=1_726,
        preferred_onemin_labels=("default",),
    )

    assert pick is None


def test_call_onemin_provider_health_uses_quarantine_budget_signal_for_smaller_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "low-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "recoverable-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1-nano")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda lightweight=False: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "quarantine",
                            "estimated_remaining_credits": 219,
                            "billing_remaining_credits": 15025,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the Tibor Girschele team only has 219 credits",
                        },
                        {
                            "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot_env_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                            "slot": "fallback_1",
                            "slot_name": "fallback_1",
                            "credential_id": "fallback_1",
                            "state": "quarantine",
                            "estimated_remaining_credits": 59,
                            "billing_remaining_credits": 15000,
                            "last_probe_result": "depleted",
                            "last_probe_detail": "INSUFFICIENT_CREDITS:The feature requires 1726 credits, but the franz@chummer.run team only has 1530 credits",
                        },
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(upstream, "_onemin_required_credits_for_selection", lambda **_kwargs: (453, "test"))
    monkeypatch.setattr(
        upstream,
        "_onemin_known_exhaustion_message",
        lambda **_kwargs: "onemin_exhausted_for_request:453:ONEMIN_AI_API_KEY,ONEMIN_AI_API_KEY_FALLBACK_1",
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        assert url == "https://api.1min.ai/api/chat-with-ai"
        assert headers["API-KEY"] == "recoverable-key"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1-nano",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="Reply with exactly ok.", requested_model="onemin:gpt-4.1-nano")
    assert result.text == "ok"
    assert result.provider_account_name == "ONEMIN_AI_API_KEY_FALLBACK_1"


def test_call_onemin_manager_falls_back_to_provider_health_ready_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.repositories.onemin_manager import InMemoryOneminManagerRepository
    from app.services.onemin_manager import OneminManagerService, register_onemin_manager

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "healthy-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1-nano")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda lightweight=False: {
            "providers": {
                "onemin": {
                    "slots": [
                        {
                            "account_name": "ONEMIN_AI_API_KEY",
                            "slot_env_name": "ONEMIN_AI_API_KEY",
                            "slot": "primary",
                            "slot_name": "primary",
                            "credential_id": "primary",
                            "state": "ready",
                            "slot_role": "active",
                            "estimated_remaining_credits": 4200,
                            "billing_remaining_credits": 4200,
                            "last_probe_result": "ok",
                            "last_probe_detail": "OK",
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(
        upstream,
        "_onemin_known_exhaustion_message",
        lambda **_kwargs: "onemin_exhausted_for_request:453:ONEMIN_AI_API_KEY",
    )

    manager = OneminManagerService(repo=InMemoryOneminManagerRepository())
    register_onemin_manager(manager)

    def fake_post_json(**_: object) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1-nano",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    try:
        result = upstream.generate_text(prompt="Reply with exactly ok.", requested_model="onemin:gpt-4.1-nano")
        assert result.text == "ok"
        assert result.provider_account_name == "ONEMIN_AI_API_KEY"
    finally:
        register_onemin_manager(None)


def test_latest_onemin_billing_snapshot_keeps_last_actual_when_new_page_is_unparsed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")

    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "observed_at": "2026-03-27T22:00:00Z",
            "remaining_credits": 15003,
            "max_credits": 15000,
            "next_topup_at": "2026-03-31T02:19:47Z",
            "topup_amount": 15000,
            "basis": "actual_billing_usage_page",
        },
        source="test",
    )
    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "observed_at": "2026-03-27T22:10:00Z",
            "basis": "page_seen_but_unparsed",
            "source_url": "https://app.1min.ai/billing-usage",
        },
        source="test",
    )

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]
    assert slot["billing_basis"] == "actual_billing_usage_page"
    assert slot["billing_remaining_credits"] == 15003
    assert slot["billing_topup_amount"] == 15000
    assert slot["billing_next_topup_at"] == "2026-03-31T02:19:47Z"


def test_call_magicx_retries_with_smaller_token_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
        if payload["max_tokens"] == 128:
            return (
                500,
                {
                    "error": (
                        "This request requires more credits, or fewer max_tokens. "
                        "You requested up to 128 tokens, but can only afford 127."
                    )
                },
            )
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(
        prompt="say ok",
        requested_model=upstream.MAGICX_PUBLIC_MODEL,
        max_output_tokens=128,
    )

    assert result.text == "ok"
    assert [payload["max_tokens"] for payload in calls] == [128, 16]


def test_call_onemin_fully_depletes_rotation_keys_without_cross_provider_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "depleted-key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "depleted-key-3")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers.get("API-KEY"):
            calls.append((url, headers["API-KEY"]))
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier chat credits are exhausted",
                            },
                        },
                    },
                },
            )
        calls.append((url, headers["Authorization"]))
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [{"message": {"content": "magicx answer"}}],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    with pytest.raises(upstream.ResponsesUpstreamError, match="INSUFFICIENT_CREDITS"):
        upstream.generate_text(prompt="write fix", requested_model="gpt-4.1")

    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-1"),
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-2"),
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-3"),
    ]


def test_call_onemin_retries_keys_and_falls_back_from_code_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "inactive-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "active-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CODE_MODELS", "gpt-5")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CODE_URL", "https://api.1min.ai/api/features")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        key = headers["API-KEY"]
        calls.append((url, key, payload))
        if key == "inactive-key":
            return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key is not active. Please contact your team administrator to be unblocked"})
        if url.endswith("/api/features"):
            return (
                200,
                {
                    "aiRecord": {
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier code credits are exhausted",
                            }
                        }
                    }
                },
            )
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-5",
                    "aiRecordDetail": {
                        "resultObject": ["chat fallback answer"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="write code", requested_model=upstream.ONEMIN_PUBLIC_MODEL)

    assert result.provider_key == "onemin"
    assert result.model == "gpt-5"
    assert result.text == "chat fallback answer"
    assert calls == [
        (
            "https://api.1min.ai/api/features",
            "inactive-key",
            {"type": "CODE_GENERATOR", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
        (
            "https://api.1min.ai/api/features",
            "active-key",
            {"type": "CODE_GENERATOR", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
        (
            "https://api.1min.ai/api/chat-with-ai",
            "active-key",
            {"type": "UNIFY_CHAT_WITH_AI", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
    ]


def test_call_onemin_flattens_structured_messages_into_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "active-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    upstream.generate_text(
        requested_model=upstream.ONEMIN_PUBLIC_MODEL,
        messages=[
            {"role": "system", "content": "follow repo rules"},
            {"role": "user", "content": "say ok"},
        ],
    )

    assert calls[0]["promptObject"]["prompt"] == "System:\nfollow repo rules\n\nUser:\nsay ok"


def test_onemin_depletion_rotates_cursor_for_future_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fallback-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "unused-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key == "depleted-key":
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier code and chat credits are exhausted",
                            }
                        },
                    }
                },
            )
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["depleted-key rotated"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    first = upstream.generate_text(prompt="first", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert first.text == "depleted-key rotated"
    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key"),
        ("https://api.1min.ai/api/chat-with-ai", "fallback-key"),
    ]


def test_call_onemin_429_rotates_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "burst-key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "burst-key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "burst-key-3")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key == "burst-key-1":
            return (429, {"error": "too many requests"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["rotated response"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rate check", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.provider_key == "onemin"
    assert result.text == "rotated response"
    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "burst-key-1"),
        ("https://api.1min.ai/api/chat-with-ai", "burst-key-2"),
    ]


def test_call_magicx_probe_marks_degraded_when_api_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "unused-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "disabled-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers.get("Authorization", headers.get("API-KEY", ""))))
        if headers.get("Authorization"):
            return (401, {"error": "invalid api key"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "depleted-key rotated"},
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    with pytest.raises(upstream.ResponsesUpstreamError, match="magicx_unavailable"):
        upstream.generate_text(prompt="probe", requested_model=upstream.MAGICX_PUBLIC_MODEL)

    magix_state, magix_detail, _ = upstream._magix_health_state_snapshot()
    assert magix_state == "degraded"
    assert "auth_error" in magix_detail
    assert calls

    calls.clear()
    second = upstream.generate_text(prompt="second", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert second.text == "depleted-key rotated"
    assert calls == [("https://api.1min.ai/api/chat-with-ai", "unused-key")]


def test_provider_health_estimates_onemin_remaining_from_observed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "observed-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY", "100")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY", "0")

    upstream._record_onemin_usage_event(
        api_key="observed-key",
        model="gpt-4.1",
        tokens_in=20,
        tokens_out=10,
    )

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]

    assert slot["estimated_remaining_credits"] == 70
    assert slot["estimated_credit_basis"] == "max_minus_observed_usage"
    assert slot["observed_consumed_credits"] == 30
    assert slot["observed_success_count"] == 1


def test_provider_health_keeps_probe_depleted_zero_credit_slot_in_quarantine_despite_positive_billing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "recoverable-key")

    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "observed_at": "2026-04-30T04:00:00Z",
            "remaining_credits": 4255550,
            "max_credits": 4255550,
            "basis": "actual_billing_usage_page",
        },
        source="test",
    )
    upstream._mark_onemin_failure(
        "recoverable-key",
        "INSUFFICIENT_CREDITS:The feature requires 1078 credits, but the Team only has 0 credits",
    )

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]

    assert slot["raw_state"] == "quarantine"
    assert slot["state"] == "quarantine"
    assert slot["billing_remaining_credits"] == 4255550
    assert slot["upstream_reset_unknown"] is True


def test_provider_health_includes_fleet_jury_service_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()
    monkeypatch.setenv("EA_FLEET_STATUS_BASE_URL", "http://fleet.example")
    monkeypatch.setenv("EA_FLEET_STATUS_API_TOKEN", "fleet-token")

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_json(*, url: str, headers: dict[str, str], timeout_seconds: float):
        calls.append((url, headers))
        return (
            200,
            {
                "active_jury_jobs": 1,
                "queued_jury_jobs": 2,
                "blocked_total_workers": 3,
                "jury_lane_state": "degraded",
            },
        )

    monkeypatch.setattr(upstream, "_get_json", fake_get_json)

    health = upstream._provider_health_report()

    assert calls == [("http://fleet.example/api/cockpit/jury-telemetry", {"Authorization": "Bearer fleet-token"})]
    assert health["jury_service"]["configured"] is True
    assert health["jury_service"]["state"] == "ok"
    assert health["jury_service"]["active_jury_jobs"] == 1
    assert health["jury_service"]["queued_jury_jobs"] == 2
    assert health["jury_service"]["blocked_total_workers"] == 3


def test_magicx_probe_marks_ready_when_probe_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "good-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    assert upstream._magix_is_ready() is True
    state, detail, checked_at = upstream._magix_health_state_snapshot()
    assert state == "ready"
    assert detail == ""
    assert checked_at > 0


def test_magicx_probe_timeout_degrades_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "slow-key")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        raise upstream.ResponsesUpstreamError("request_failed:timeout")

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    assert upstream._magix_is_ready() is False
    state, detail, checked_at = upstream._magix_health_state_snapshot()
    assert state == "degraded"
    assert "request_failed:timeout" in detail
    assert checked_at > 0


def test_call_onemin_uses_fourth_key_when_first_three_429(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "key-3")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "key-4")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key in {"key-1", "key-2", "key-3"}:
            return (429, {"error": "too many requests"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "fourth-key-success"},
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rotating", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.text == "fourth-key-success"
    assert [item[1] for item in calls] == ["key-1", "key-2", "key-3", "key-4"]


def test_deleted_onemin_key_rotates_and_hard_quarantines(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "deleted-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "healthy-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS", "86400")

    calls: list[str] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append(api_key)
        if api_key == "deleted-key":
            return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key has been deleted"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": ["healthy answer"]},
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rotate after delete", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.text == "healthy answer"
    assert calls == ["deleted-key", "healthy-key"]

    health = upstream._provider_health_report()
    deleted_slot = next(slot for slot in health["providers"]["onemin"]["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    assert deleted_slot["state"] == "deleted"
    assert deleted_slot["quarantine_until"] > deleted_slot["last_failure_at"] + 86000


def test_probe_all_onemin_slots_maps_owner_hashes_and_classifies_results(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "probe-ok")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "probe-deleted")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_PROBE_MODEL", "gpt-4.1")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "secret_sha256": hashlib.sha256(b"probe-ok").hexdigest(),
                        "owner_email": "owner@example.com",
                    }
                ]
            }
        ),
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers["API-KEY"] == "probe-ok":
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {"resultObject": "OK"},
                    }
                },
            )
        return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key has been deleted"})

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    probe = upstream.probe_all_onemin_slots(include_reserve=True)

    assert probe["result_counts"] == {"ok": 1, "revoked": 1}
    primary = next(slot for slot in probe["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    deleted = next(slot for slot in probe["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_1")
    assert primary["owner_email"] == "owner@example.com"
    assert primary["result"] == "ok"
    assert deleted["result"] == "revoked"

    health = upstream._provider_health_report()
    onemin = health["providers"]["onemin"]
    health_primary = next(slot for slot in onemin["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    health_deleted = next(slot for slot in onemin["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_1")
    assert onemin["owner_mapped_slots"] == 1
    assert onemin["probe_result_counts"] == {"ok": 1, "revoked": 1}
    assert health_primary["owner_email"] == "owner@example.com"
    assert health_primary["last_probe_result"] == "ok"
    assert health_deleted["last_probe_result"] == "revoked"
    assert health_deleted["state"] == "deleted"


def test_probe_all_onemin_slots_maps_owner_fallbacks_by_slot_and_account(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "probe-slot")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "probe-account")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "slot": "primary",
                        "owner_email": "slot-owner@example.com",
                    },
                    {
                        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_1",
                        "owner_email": "account-owner@example.com",
                    },
                ]
            }
        ),
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "OK"},
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    probe = upstream.probe_all_onemin_slots(include_reserve=True)

    primary = next(slot for slot in probe["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    fallback = next(slot for slot in probe["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY_FALLBACK_1")
    assert primary["owner_email"] == "slot-owner@example.com"
    assert fallback["owner_email"] == "account-owner@example.com"

    health = upstream._provider_health_report()
    assert health["providers"]["onemin"]["owner_mapped_slots"] == 2


def test_onemin_owner_ledger_path_falls_back_to_repo_config(monkeypatch: pytest.MonkeyPatch) -> None:
    original_env = upstream._env
    monkeypatch.setattr(
        upstream,
        "_env",
        lambda name, default="": default if name == "EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH" else original_env(name, default),
    )

    path = upstream._onemin_owner_ledger_path()

    assert path is not None
    assert path.name == "onemin_slot_owners.json"
    assert path.exists()


def test_probe_all_onemin_slots_preserves_slot_order_when_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "slow-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fast-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_PROBE_PARALLELISM", "2")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers["API-KEY"] == "slow-primary":
            time.sleep(0.02)
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "OK"},
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    probe = upstream.probe_all_onemin_slots(include_reserve=True)

    assert [slot["account_name"] for slot in probe["slots"]] == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
    ]


def test_onemin_provider_health_reports_burn_rate_from_recent_successes(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "healthy")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BURN_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BURN_MIN_OBSERVATION_SECONDS", "60")

    now = {"value": 1000.0}

    def fake_now() -> float:
        return float(now["value"])

    monkeypatch.setattr(upstream, "_now_epoch", fake_now)

    upstream._mark_onemin_failure(
        "primary",
        "INSUFFICIENT_CREDITS:The feature requires 30000 credits, but the Team only has 0 credits",
    )

    now["value"] = 1060.0
    upstream._record_onemin_usage_event(
        api_key="primary",
        model="gpt-5",
        tokens_in=100,
        tokens_out=50,
    )

    now["value"] = 1120.0
    upstream._record_onemin_usage_event(
        api_key="primary",
        model="gpt-5",
        tokens_in=120,
        tokens_out=55,
    )

    now["value"] = 1180.0
    health = upstream._provider_health_report()
    onemin = health["providers"]["onemin"]

    assert onemin["estimated_burn_credits_per_hour"] == 1800000.0
    assert onemin["estimated_requests_per_hour"] == 60.0
    assert onemin["estimated_hours_remaining_at_current_pace"] == 0.0
    assert onemin["burn_event_count"] == 2
    assert onemin["burn_estimate_basis"] == "recent_required_credit_median"


def test_generate_text_routes_audit_lane_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")

    calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers, payload))
        return (
            200,
            {
                "consensus": "pass",
                "recommendation": "approved",
                "roles": ["factuality", "adversarial"],
                "disagreements": [],
                "risks": ["none"],
                "model_deltas": [],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="should run full review?",
    )

    assert result.provider_key == "chatplayground"
    assert result.provider_backend == "browseract"
    assert result.provider_account_name == "BROWSERACT_API_KEY"
    assert result.model == "judge-model"
    assert "consensus" in result.text
    assert calls[0][0] == "https://web.chatplayground.ai/api/chat/lmsys"
    assert calls[0][1]["Authorization"] == "Bearer judge-key"


def test_chatplayground_audit_callback_only_falls_back_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_URLS", "https://web.chatplayground.ai/api/chat/lmsys")

    def fail_post_json(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, object]]:
        raise AssertionError("http path should not be used when callback-only mode is enabled")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="should use callback",
        chatplayground_audit_callback_only=True,
    )

    payload = json.loads(result.text)
    assert result.provider_key == "chatplayground"
    assert result.provider_backend == "browseract"
    assert result.provider_key_slot == "unavailable"
    assert payload["consensus"] == "unavailable"
    assert "audit_callback_missing" in payload["risks"]


def test_chatplayground_audit_callback_errors_return_unavailable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_URLS", "https://web.chatplayground.ai/api/chat/lmsys")

    def bad_callback(**kwargs: object) -> object:
        raise RuntimeError("tool-unavailable")

    def fail_post_json(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, object]]:
        raise AssertionError("http path should be skipped when callback raises in audit-only mode")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="audit now",
        chatplayground_audit_callback=bad_callback,
        chatplayground_audit_callback_only=True,
    )

    payload = json.loads(result.text)
    assert result.provider_key == "chatplayground"
    assert result.provider_key_slot == "callback_error"
    assert payload["consensus"] == "unavailable"
    assert "tool-unavailable" in payload["risks"]


def test_chatplayground_audit_unavailable_payload_redacts_full_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_URLS", "https://web.chatplayground.ai/api/chat/lmsys")

    long_prompt = (
        "Conversation so far:\\n\\n"
        + ("very long prior context " * 24)
        + "\\n\\nReturn the next action as JSON only."
    )

    def bad_callback(**kwargs: object) -> object:
        raise RuntimeError("connector_binding_required:browseract.chatplayground_audit")

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt=long_prompt,
        chatplayground_audit_callback=bad_callback,
        chatplayground_audit_callback_only=True,
    )

    payload = json.loads(result.text)
    raw_output = payload["raw_output"]
    assert result.provider_key == "chatplayground"
    assert payload["consensus"] == "unavailable"
    assert raw_output["reason"] == "connector_binding_required:browseract.chatplayground_audit"
    assert raw_output["prompt_chars"] == len(long_prompt)
    assert raw_output["prompt_sha256"] == hashlib.sha256(long_prompt.encode("utf-8")).hexdigest()
    assert raw_output["prompt_preview"].startswith("Conversation so far:")
    assert len(raw_output["prompt_preview"]) <= 160
    assert "very long prior context very long prior context" in raw_output["prompt_preview"]
    assert raw_output.get("prompt") is None
    assert long_prompt not in result.text


def test_chatplayground_request_urls_prefers_web_with_app_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/")
    monkeypatch.delenv("EA_RESPONSES_CHATPLAYGROUND_URLS", raising=False)

    urls = upstream._chatplayground_request_urls()

    assert urls[0] == "https://web.chatplayground.ai/api/chat/lmsys"
    assert urls[1] == "https://web.chatplayground.ai/api/chat"
    assert "https://app.chatplayground.ai/api/chat/lmsys" in urls
    assert "https://app.chatplayground.ai/api/v1/chat/lmsys" in urls
    assert urls[-1] in {
        "https://app.chatplayground.ai/api/v1/chat/lmsys",
        "https://app.chatplayground.ai/",
    }


def test_post_json_enforces_wall_clock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 0.0}

    def advance(seconds: float) -> None:
        clock["now"] += seconds

    response = _SlowUrlopenResponse(
        body_chunks=[b'{"partial":', b' true}'],
        tick_seconds=30.0,
        advance_clock=advance,
    )

    monkeypatch.setattr(upstream, "_now_monotonic", lambda: clock["now"])
    monkeypatch.setattr(upstream.urllib.request, "urlopen", lambda request, timeout: response)

    with pytest.raises(upstream.ResponsesUpstreamError, match=r"request_timeout:45s"):
        upstream._post_json(
            url="https://example.invalid/json",
            headers={},
            payload={"ping": "pong"},
            timeout_seconds=45,
        )

    assert response.timeouts[:2] == pytest.approx([45.0, 15.0])


def test_post_sse_enforces_wall_clock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 0.0}

    def advance(seconds: float) -> None:
        clock["now"] += seconds

    response = _SlowUrlopenResponse(
        line_chunks=[b"event: content\n", b"data: hi\n", b"\n"],
        tick_seconds=20.0,
        advance_clock=advance,
    )
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(upstream, "_now_monotonic", lambda: clock["now"])
    monkeypatch.setattr(upstream.urllib.request, "urlopen", lambda request, timeout: response)

    with pytest.raises(upstream.ResponsesUpstreamError, match=r"request_timeout:45s"):
        upstream._post_sse(
            url="https://example.invalid/sse",
            headers={},
            payload={"ping": "pong"},
            timeout_seconds=45,
            on_event=lambda event, data: events.append((event, data)),
        )

    assert events == [("content", "hi")]
    assert response.timeouts[:3] == pytest.approx([45.0, 25.0, 5.0])


def test_call_onemin_stream_falls_back_to_nonstream_code_and_emits_single_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = upstream.ProviderConfig(
        provider_key="onemin",
        display_name="1min",
        api_keys=("key-1",),
        default_models=("gpt-5.4",),
        timeout_seconds=60,
    )
    chunks: list[str] = []

    monkeypatch.setattr(upstream, "_load_provider_ledgers_once", lambda: None)
    monkeypatch.setattr(upstream, "_ordered_onemin_keys_allow_reserve", lambda _allow_reserve: ("key-1",))
    monkeypatch.setattr(upstream, "_onemin_key_names", lambda: ("key-1",))
    monkeypatch.setattr(upstream, "_clean_onemin_states", lambda _keys: None)
    monkeypatch.setattr(
        upstream,
        "_onemin_states_snapshot",
        lambda _keys: {"key-1": upstream.OneminKeyState(key="key-1")},
    )
    monkeypatch.setattr(upstream, "_provider_account_name", lambda _provider, key_names, key: "account-1")
    monkeypatch.setattr(upstream, "_onemin_key_slot", lambda key, key_names: "slot-1")
    monkeypatch.setattr(
        upstream,
        "_provider_health_report",
        lambda **_kwargs: {
            "providers": {
                "onemin": {
                    "slots": [
                        {"account_name": "account-1", "slot": "slot-1", "last_probe_result": "ok"},
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(upstream, "_onemin_required_credits_for_selection", lambda **_kwargs: (50000, "test"))
    monkeypatch.setattr(upstream, "_onemin_credit_snapshot_state", lambda **_kwargs: (50000, "actual_provider_api", True, 0.0, 0.0))
    monkeypatch.setattr(upstream, "_onemin_recent_success_evidence", lambda **_kwargs: (0.0, 0.0, 0.0, 0, 0))
    monkeypatch.setattr(upstream, "_mark_onemin_request_start", lambda _api_key: None)
    monkeypatch.setattr(upstream, "_mark_onemin_success", lambda _api_key: None)
    monkeypatch.setattr(upstream, "_mark_onemin_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(upstream, "_rotate_onemin_cursor_after_key_usage", lambda _api_key: None)
    monkeypatch.setattr(upstream, "_record_onemin_usage_and_measure_delta", lambda **_kwargs: (None, "test"))
    monkeypatch.setattr(
        upstream,
        "_post_sse",
        lambda **_kwargs: (_ for _ in ()).throw(upstream.ResponsesUpstreamError("http_503:stream_down")),
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int):
        assert headers == {"API-KEY": "key-1"}
        assert timeout_seconds == 60
        assert url == upstream._onemin_code_url()
        assert payload["type"] == "CODE_GENERATOR"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-5.4",
                    "aiRecordDetail": {
                        "resultObject": "ok",
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream._call_onemin(
        config,
        prompt="Reply with exactly ok.",
        model="gpt-5.4",
        on_delta=chunks.append,
    )

    assert result.text == "ok"
    assert result.model == "gpt-5.4"
    assert chunks == ["ok"]
