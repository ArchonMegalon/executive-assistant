from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json

import pytest

from app.services.provider_accounts import ProviderAccountSlot
from app.services.tough_tongue import ToughTongueConfig
from app.services.tough_tongue_live_ops import (
    CONTRACT_SCHEMA,
    DOCUMENTED_GET_ROUTES,
    NORMALIZATION,
    UNSUPPORTED_DIRECT_RESOURCES,
    ToughTongueDocumentedGetAdapter,
    ToughTongueLiveOpsContract,
    ToughTongueProbeAuthority,
    contract_digest,
    probe_tough_tongue_live_ops,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class Response:
    def __init__(self, payload: object) -> None:
        self.body = BytesIO(json.dumps(payload).encode())

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)


def payload() -> dict[str, object]:
    return {
        "schema": CONTRACT_SCHEMA,
        "provider_key": "tough_tongue",
        "base_url": "https://api.toughtongueai.com/api/public",
        "source_type": "provider_documentation",
        "verified_at": "2026-08-23T10:00:00Z",
        "authority": {
            "operator_verified": True,
            "source_ref_sha256": "sha256:" + "a" * 64,
        },
        "slot_cardinality": 6,
        "maximum_snapshot_age_seconds": 900,
        "premium_plan_values": ["premium"],
        "live_avatar_providers": ["anam", "heygen"],
        "documented_get_allowlist": {
            name: {"method": "GET", "path": path}
            for name, path in DOCUMENTED_GET_ROUTES.items()
        },
        "normalization": NORMALIZATION,
        "unsupported_direct_resources": list(UNSUPPORTED_DIRECT_RESOURCES),
    }


def contract(**changes: object) -> ToughTongueLiveOpsContract:
    raw = payload()
    raw.update(changes)
    return ToughTongueLiveOpsContract.from_payload(
        raw,
        expected_digest=contract_digest(raw),
        configured_base_url="https://api.toughtongueai.com/api/public",
    )


def slots(count: int = 6, *, organization: bool = True) -> tuple[ProviderAccountSlot, ...]:
    return tuple(
        ProviderAccountSlot(
            provider_key="tough_tongue",
            slot_label=f"team-slot-{index}",
            credential=f"secret-token-{index}-abcdefghijklmnop",
            account_ref=f"account-{index}@example.test",
            organization_ref=f"org-{index}" if organization else "",
            plan_name="Premium",
        )
        for index in range(1, count + 1)
    )


def config(**changes: object) -> ToughTongueConfig:
    values: dict[str, object] = {
        "api_key": "",
        "organization_id": "",
        "base_url": "https://api.toughtongueai.com/api/public",
        "login_email": "",
        "forwarding_email": "",
        "account_tier": "Premium",
        "enabled": True,
        "account_verified": True,
        "provider_verified": True,
        "auto_create_sessions": False,
        "allow_outbound_calls": False,
        "allow_meeting_bots": False,
        "allow_purchases": False,
        "allow_publication": False,
        "min_remaining_minutes": 30.0,
        "max_session_minutes": 15.0,
        "account_slots": slots(),
        "aggregate_basis": "unknown_no_sum",
    }
    values.update(changes)
    return ToughTongueConfig(**values)  # type: ignore[arg-type]


def candidates() -> dict[str, str]:
    return {
        "agent": "scenario-build-ghost",
        "voice": "Aoede",
        "function": "build-ghost-tool",
        "scenario": "scenario-build-ghost",
        "avatar": "avatar-build-ghost",
    }


def ready_authority() -> ToughTongueProbeAuthority:
    return ToughTongueProbeAuthority(
        "ready", "2026-08-23T11:59:00Z", "sha256:" + "b" * 64
    )


def no_call(*_args: object, **_kwargs: object) -> Response:
    raise AssertionError("network request was not allowed")


@pytest.mark.parametrize(
    ("config_changes", "authority", "expected_status"),
    (
        ({"enabled": False}, ready_authority(), "disabled"),
        ({"provider_verified": False}, ready_authority(), "unavailable"),
        ({}, ToughTongueProbeAuthority("depleted", "2026-08-23T11:59:00Z", "sha256:" + "b" * 64), "depleted"),
        ({}, ToughTongueProbeAuthority("ready", "2026-08-23T10:00:00Z", "sha256:" + "b" * 64), "stale"),
        ({"account_slots": slots(5)}, ready_authority(), "malformed"),
    ),
)
def test_fail_closed_preflight_states_prove_zero_requests(
    config_changes: dict[str, object],
    authority: ToughTongueProbeAuthority,
    expected_status: str,
) -> None:
    receipt = probe_tough_tongue_live_ops(
        config=config(**config_changes),
        contract=contract(),
        authority=authority,
        preferred_account_ref="account-4@example.test",
        candidate_refs=candidates(),
        opener=no_call,
        now=NOW,
    )

    assert receipt["status"] == expected_status
    assert receipt["ready"] is False
    assert receipt["requests"]["attempted_count"] == 0  # type: ignore[index]
    assert receipt["requests"]["mutation_request_count"] == 0  # type: ignore[index]
    assert receipt["runtime_gates_changed"] is False
    assert receipt["provider_resources_created_or_bound"] is False


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["documented_get_allowlist"]["balance"].update(method="POST"),
        lambda value: value["documented_get_allowlist"]["scenario"].update(path="agents/{resource_ref}"),
        lambda value: value.update(slot_cardinality=5),
        lambda value: value.update(normalization={"remaining_minutes": "wallet.value"}),
    ),
)
def test_contract_rejects_method_path_cardinality_and_normalization_drift(mutation) -> None:
    raw = payload()
    mutation(raw)
    with pytest.raises(ValueError):
        ToughTongueLiveOpsContract.from_payload(
            raw,
            expected_digest=contract_digest(raw),
            configured_base_url="https://api.toughtongueai.com/api/public",
        )


def test_adapter_uses_optional_org_header_and_has_no_mutation_surface() -> None:
    requests: list[object] = []

    def opener(request: object, *, timeout: float) -> Response:
        requests.append(request)
        return Response({"available_minutes": 100, "last_updated": "2026-08-23T11:59:00Z"})

    adapter = ToughTongueDocumentedGetAdapter(
        config=config(account_slots=slots(organization=False)),
        slot=slots(organization=False)[0],
        contract=contract(),
        opener=opener,
    )
    assert adapter.balance(timeout_seconds=2) == (100.0, "2026-08-23T11:59:00Z")
    request = requests[0]
    assert request.get_method() == "GET"  # type: ignore[attr-defined]
    assert request.get_header("X-tt-org") is None  # type: ignore[attr-defined]
    for method in ("create", "update", "delete", "post", "bind", "activate"):
        assert not hasattr(adapter, method)


def test_six_slot_probe_normalizes_and_redacts_but_does_not_overclaim_bindings() -> None:
    observed: list[tuple[str, str | None]] = []

    def opener(request: object, *, timeout: float) -> Response:
        url = request.full_url  # type: ignore[attr-defined]
        org = request.get_header("X-tt-org")  # type: ignore[attr-defined]
        observed.append((url, org))
        if url.endswith("/balance"):
            return Response({"available_minutes": 100, "last_updated": "2026-08-23T11:59:00Z"})
        if url.endswith("/subscriptions"):
            return Response({"subscriptions": [{"status": "active", "product_name": "Premium"}]})
        if url.endswith("/v2/organizations"):
            return Response({"organizations": [{"id": org}]})
        if url.endswith("/scenarios/scenario-build-ghost"):
            return Response({"id": "scenario-build-ghost", "appearance": {"voice": "Aoede"}})
        raise AssertionError(url)

    receipt = probe_tough_tongue_live_ops(
        config=config(),
        contract=contract(),
        authority=ready_authority(),
        preferred_account_ref="account-4@example.test",
        candidate_refs=candidates(),
        opener=opener,
        now=NOW,
    )

    assert receipt["status"] == "unverified"
    assert receipt["reason"] == "tough_tongue_direct_resource_ownership_not_documented"
    assert receipt["slot_cardinality"] == {"expected": 6, "configured": 6, "valid": True}
    assert len(receipt["accounts"]) == 6  # type: ignore[arg-type]
    assert all(row["plan"] == "premium" for row in receipt["accounts"])  # type: ignore[union-attr]
    assert all(row["remaining_minutes"] == 100 for row in receipt["accounts"])  # type: ignore[union-attr]
    assert receipt["resource_ownership"]["scenario"]["verified"] is True  # type: ignore[index]
    assert receipt["resource_ownership"]["voice"]["verified"] is True  # type: ignore[index]
    assert receipt["resource_ownership"]["function"]["verified"] is False  # type: ignore[index]
    assert receipt["resource_ownership"]["avatar"]["verified"] is False  # type: ignore[index]
    assert receipt["requests"]["attempted_count"] == 19  # type: ignore[index]
    assert receipt["requests"]["methods"] == ["GET"]  # type: ignore[index]
    assert all(org and org.startswith("org-") for _, org in observed)

    rendered = json.dumps(receipt, sort_keys=True)
    for index in range(1, 7):
        assert f"secret-token-{index}" not in rendered
        assert f"account-{index}@example.test" not in rendered
        assert f"org-{index}" not in rendered
    for ref in candidates().values():
        assert ref not in rendered


def test_malformed_provider_shape_is_bounded_and_never_persists_body() -> None:
    secret_body = "provider-private-identifier"

    def opener(_request: object, *, timeout: float) -> Response:
        return Response({"available_minutes": secret_body})

    receipt = probe_tough_tongue_live_ops(
        config=config(),
        contract=contract(),
        authority=ready_authority(),
        preferred_account_ref="account-4@example.test",
        candidate_refs=candidates(),
        opener=opener,
        now=NOW,
    )

    assert receipt["status"] == "malformed"
    assert secret_body not in json.dumps(receipt)
    assert receipt["requests"]["attempted_count"] == 1  # type: ignore[index]
    assert receipt["requests"]["response_bodies_persisted"] is False  # type: ignore[index]
