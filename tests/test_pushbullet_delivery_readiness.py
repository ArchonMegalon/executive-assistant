from __future__ import annotations

import json

from scripts import materialize_pushbullet_delivery_readiness as materializer
from scripts import verify_pushbullet_delivery_readiness as verifier


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _patch_source_state(monkeypatch) -> None:
    monkeypatch.setattr(materializer, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(materializer, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: "source-head")
    monkeypatch.setattr(verifier, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def test_pushbullet_readiness_blocks_missing_second_client_token(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "Elisabeth.Girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "blocked_setup_required"
    assert receipt["multi_client_expected"] is True
    assert receipt["required_client_keys"] == ["default", "elisabeth"]
    assert receipt["client_count"] == 2
    assert receipt["client_coverage"]["missing_client_keys"] == []
    assert receipt["client_coverage"]["missing_token_keys"] == ["elisabeth"]
    assert receipt["client_coverage"]["multi_client_ready"] is False
    assert "pushbullet_token_missing:elisabeth" in receipt["missing_setup"]
    assert receipt["operator_action"]["user_action_required"] is True
    assert receipt["operator_action"]["telegram_push_allowed"] is True
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is False
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is False
    assert "Elisabeth.Girschele@gmail.com" not in serialized
    assert "tibor@example.test" not in serialized
    assert "default-token" not in serialized
    assert "raw_token_exposed" in serialized
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_blocks_missing_primary_client(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["required_client_keys"] == ["default", "elisabeth"]
    assert receipt["client_coverage"]["missing_client_keys"] == ["default"]
    assert "pushbullet_client_missing:default" in receipt["missing_setup"]
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is False
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is False
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_ready_configured_when_token_present(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )

    assert receipt["status"] == "ready_configured"
    assert receipt["missing_setup"] == []
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["delivery_claim"]["pushbullet_note_delivery_ready"] is True
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is True
    assert receipt["delivery_claim"]["live_token_account_verified"] is False
    assert "push-token" not in json.dumps(receipt, sort_keys=True)
    assert "default-token" not in json.dumps(receipt, sort_keys=True)
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_readiness_live_probe_can_verify_token_account(monkeypatch) -> None:
    _patch_source_state(monkeypatch)

    def _fake_urlopen(_request, timeout=20):
        return _FakeResponse({"iden": "user-1", "email_normalized": "elisabeth.girschele@gmail.com"})

    def _fake_probe(client_key, *args, **kwargs):
        return {
            "status": "pass",
            "reason": "",
            "client_key": client_key,
            "user_id_hash": f"user-hash-{client_key}",
            "email_sha256": f"email-hash-{client_key}",
            "email_domain": "gmail.com",
            "expected_email_matches": True,
            "raw_email_exposed": False,
            "raw_token_exposed": False,
        }

    monkeypatch.setattr(materializer, "probe_pushbullet_client", _fake_probe)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
        probe_live=True,
    )

    assert receipt["status"] == "ready_live_verified"
    assert [probe["client_key"] for probe in receipt["live_probes"]] == ["default", "elisabeth"]
    assert receipt["live_probes"][0]["status"] == "pass"
    assert receipt["delivery_claim"]["multi_client_delivery_ready"] is True
    assert receipt["delivery_claim"]["live_token_account_verified"] is True
    assert verifier.verify_receipt_for_test(receipt) == []


def test_pushbullet_verifier_rejects_secret_leak_flags(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN": "default-token",
            "PUSHBULLET_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )
    receipt["clients"][0]["raw_email_exposed"] = True
    receipt["privacy"]["raw_token_exposed"] = True
    receipt["operator_action"]["raw_private_context_exposed"] = True

    issues = verifier.verify_receipt_for_test(receipt)

    assert "clients[0].raw_email_exposed must be false" in issues
    assert "privacy.raw_token_exposed must be false" in issues
    assert "operator_action.raw_private_context_exposed must be false" in issues


def test_pushbullet_verifier_rejects_ready_single_client_overclaim(monkeypatch) -> None:
    _patch_source_state(monkeypatch)
    receipt = materializer.build_receipt(
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        required_clients=("elisabeth",),
    )
    receipt["status"] = "ready_configured"
    receipt["missing_setup"] = []
    receipt["operator_action"]["missing_setup"] = []
    receipt["operator_action"]["user_action_required"] = False
    receipt["operator_action"]["telegram_push_allowed"] = False
    receipt["operator_action"]["interruption_budget"] = "none"
    receipt["operator_action"]["delivery_policy"] = "queue_only"
    receipt["delivery_claim"]["pushbullet_note_delivery_ready"] = True
    receipt["delivery_claim"]["multi_client_delivery_ready"] = True

    issues = verifier.verify_receipt_for_test(receipt)

    assert "missing_setup must include pushbullet_client_missing:default" in issues
    assert "ready Pushbullet receipt must cover every expected multi-client account" in issues
    assert "multi_client_delivery_ready must match status and expected-client coverage" in issues
