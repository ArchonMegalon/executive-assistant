from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services import pushbullet_relay


def _env() -> dict[str, str]:
    return {
        "PB_TOKEN": "tibor-token",
        "PUSHBULLET_EMAIL": "tibor@example.test",
        "PB_TOKEN_ELISABETH": "elisabeth-token",
        "PUSHBULLET_ELISABETH_EMAIL": "elisabeth@example.test",
        "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT": "default",
        "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT": "elisabeth",
    }


def _pass_probe(client_key: str, *args, **kwargs) -> dict[str, object]:
    return {
        "status": "pass",
        "reason": "",
        "client_key": client_key,
        "user_id_hash": f"user-hash-{client_key}",
        "email_sha256": f"email-hash-{client_key}",
        "email_domain": "example.test",
        "expected_email_matches": True,
        "raw_email_exposed": False,
        "raw_token_exposed": False,
    }


def test_run_pushbullet_relay_primes_rules_without_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "pushbullet-relay.json"
    calls: list[str] = []

    def _fake_list_pushes(*args, **kwargs):
        calls.append("listed")
        return ()

    monkeypatch.setattr(pushbullet_relay, "list_pushbullet_pushes", _fake_list_pushes)
    monkeypatch.setattr(pushbullet_relay, "probe_pushbullet_client", _pass_probe)

    summary = pushbullet_relay.run_pushbullet_relay_once(
        state_path=state_path,
        env=_env(),
        observed_at=datetime(2026, 7, 7, 10, 0, tzinfo=UTC),
    )

    assert summary["primed_rule_count"] == 2
    assert summary["forwarded_total"] == 0
    assert calls == []
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert sorted(saved["rules"]) == ["primary_paypal_to_secondary", "secondary_all_to_primary"]


def test_run_pushbullet_relay_forwards_expected_messages_and_suppresses_pair_loops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "pushbullet-relay.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": {
                    "primary_paypal_to_secondary": {
                        "modified_after": 1.0,
                        "seen_push_idens": [],
                    },
                    "secondary_all_to_primary": {
                        "modified_after": 1.0,
                        "seen_push_idens": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    pushes = {
        "default": (
            {
                "iden": "paypal-1",
                "type": "note",
                "title": "PayPal",
                "body": "Your PayPal verification code is 123456.",
                "modified": 10.0,
                "sender_email_normalized": "service@paypal.com",
                "receiver_email_normalized": "tibor@example.test",
            },
            {
                "iden": "echo-1",
                "type": "note",
                "title": "Previous relay",
                "body": "Should not bounce back.",
                "modified": 11.0,
                "sender_email_normalized": "tibor@example.test",
                "receiver_email_normalized": "elisabeth@example.test",
            },
            {
                "iden": "other-1",
                "type": "note",
                "title": "Random",
                "body": "No PayPal keyword here.",
                "modified": 12.0,
                "sender_email_normalized": "friend@example.test",
                "receiver_email_normalized": "tibor@example.test",
            },
        ),
        "elisabeth": (
            {
                "iden": "elisabeth-1",
                "type": "note",
                "title": "Need this forwarded",
                "body": "Generic note.",
                "modified": 20.0,
                "sender_email_normalized": "friend@example.test",
                "receiver_email_normalized": "elisabeth@example.test",
            },
            {
                "iden": "elisabeth-echo-1",
                "type": "note",
                "title": "From Tibor",
                "body": "Already between the pair.",
                "modified": 21.0,
                "sender_email_normalized": "tibor@example.test",
                "receiver_email_normalized": "elisabeth@example.test",
            },
        ),
    }
    sent: list[dict[str, str]] = []

    def _fake_list_pushes(client_key: str, **_kwargs):
        return pushes[client_key]

    def _fake_send_pushbullet_note(*, client_key: str, title: str, body: str, url: str = "", target_email: str = "", **_kwargs):
        sent.append(
            {
                "client_key": client_key,
                "title": title,
                "body": body,
                "url": url,
                "target_email": target_email,
            }
        )
        return object()

    monkeypatch.setattr(pushbullet_relay, "list_pushbullet_pushes", _fake_list_pushes)
    monkeypatch.setattr(pushbullet_relay, "send_pushbullet_note", _fake_send_pushbullet_note)
    monkeypatch.setattr(pushbullet_relay, "probe_pushbullet_client", _pass_probe)

    summary = pushbullet_relay.run_pushbullet_relay_once(
        state_path=state_path,
        env=_env(),
        observed_at=datetime(2026, 7, 7, 10, 5, tzinfo=UTC),
    )

    assert summary["forwarded_total"] == 2
    assert sent == [
        {
            "client_key": "default",
            "title": "PayPal",
            "body": "Your PayPal verification code is 123456.",
            "url": "",
            "target_email": "elisabeth@example.test",
        },
        {
            "client_key": "elisabeth",
            "title": "Need this forwarded",
            "body": "Generic note.",
            "url": "",
            "target_email": "tibor@example.test",
        },
    ]
    rules = {row["key"]: row for row in summary["rules"]}
    assert rules["primary_paypal_to_secondary"]["forwarded"] == 1
    assert rules["primary_paypal_to_secondary"]["skipped"] == 2
    assert rules["secondary_all_to_primary"]["forwarded"] == 1
    assert rules["secondary_all_to_primary"]["skipped"] == 1

    second = pushbullet_relay.run_pushbullet_relay_once(
        state_path=state_path,
        env=_env(),
        observed_at=datetime(2026, 7, 7, 10, 6, tzinfo=UTC),
    )
    assert second["forwarded_total"] == 0


def test_run_pushbullet_relay_suppresses_gmail_dot_alias_pair_loops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "pushbullet-relay.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": {
                    "secondary_all_to_primary": {
                        "modified_after": 1.0,
                        "seen_push_idens": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    sent: list[dict[str, str]] = []

    monkeypatch.setattr(
        pushbullet_relay,
        "list_pushbullet_pushes",
        lambda client_key, **_kwargs: (
            {
                "iden": "loop-1",
                "type": "note",
                "title": "From Tibor",
                "body": "Already between the pair.",
                "modified": 21.0,
                "sender_email": "Tibor.Girschele@gmail.com",
                "receiver_email": "Elisabeth.Girschele@gmail.com",
            },
        ),
    )
    monkeypatch.setattr(
        pushbullet_relay,
        "send_pushbullet_note",
        lambda **kwargs: sent.append(kwargs) or object(),
    )
    monkeypatch.setattr(pushbullet_relay, "probe_pushbullet_client", _pass_probe)

    summary = pushbullet_relay.run_pushbullet_relay_once(
        state_path=state_path,
        env={
            "PB_TOKEN_ELISABETH": "elisabeth-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
            "PUSHBULLET_TIBOR_EMAIL": "tibor.girschele@gmail.com",
            "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED": "0",
            "EA_PUSHBULLET_RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED": "1",
            "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT": "tibor",
            "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT": "elisabeth",
        },
        observed_at=datetime(2026, 7, 7, 10, 7, tzinfo=UTC),
    )

    assert summary["forwarded_total"] == 0
    assert sent == []
    rules = {row["key"]: row for row in summary["rules"]}
    assert rules["secondary_all_to_primary"]["skipped"] == 1


def test_run_pushbullet_relay_blocks_rule_when_source_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "pushbullet-relay.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": {
                    "primary_paypal_to_secondary": {
                        "modified_after": 1.0,
                        "seen_push_idens": [],
                    },
                    "secondary_all_to_primary": {
                        "modified_after": 1.0,
                        "seen_push_idens": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    listed: list[str] = []

    def _fake_probe(client_key: str, *args, **kwargs) -> dict[str, object]:
        if client_key == "tibor":
            return {
                "status": "blocked",
                "reason": "pushbullet_account_email_mismatch",
                "client_key": client_key,
                "user_id_hash": "user-hash-elisabeth",
                "email_sha256": "email-hash-elisabeth",
                "email_domain": "example.test",
                "expected_email_matches": False,
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            }
        return _pass_probe(client_key)

    def _fake_list_pushes(client_key: str, **_kwargs):
        listed.append(client_key)
        return ()

    monkeypatch.setattr(pushbullet_relay, "probe_pushbullet_client", _fake_probe)
    monkeypatch.setattr(pushbullet_relay, "list_pushbullet_pushes", _fake_list_pushes)

    summary = pushbullet_relay.run_pushbullet_relay_once(
        state_path=state_path,
        env={
            "PB_TOKEN_TIBOR": "tibor-token",
            "PUSHBULLET_TIBOR_EMAIL": "tibor@example.test",
            "PB_TOKEN_ELISABETH": "elisabeth-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth@example.test",
            "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT": "tibor",
            "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT": "elisabeth",
            "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED": "1",
            "EA_PUSHBULLET_RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED": "1",
        },
        observed_at=datetime(2026, 7, 7, 10, 8, tzinfo=UTC),
    )

    assert summary["blocked_rule_count"] == 1
    assert summary["errors"] == 1
    assert listed == ["elisabeth"]
    rules = {row["key"]: row for row in summary["rules"]}
    assert rules["primary_paypal_to_secondary"]["blocked"] is True
    assert rules["primary_paypal_to_secondary"]["blocked_reason"] == (
        "pushbullet_source_probe_failed:tibor:pushbullet_account_email_mismatch"
    )
    assert rules["secondary_all_to_primary"]["blocked"] is False
