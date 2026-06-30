from __future__ import annotations

import json

from scripts.materialize_telegram_business_signal_readiness import build_receipt
from scripts.verify_telegram_business_signal_readiness import verify


def _clear_telegram_business_env(monkeypatch) -> None:
    for key in (
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        "EA_TELEGRAM_BOT_TOKEN",
        "EA_TELEGRAM_INGEST_SECRET",
        "EA_TELEGRAM_BOT_HANDLE",
        "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_PUBLIC_APP_BASE_URL",
        "EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS",
        "EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES",
        "EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_LABELS",
        "EA_TELEGRAM_BUSINESS_LIVE_WEBHOOK_PROBE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_blocked_readiness_receipt_contains_action_required_only_setup_packet(monkeypatch, tmp_path) -> None:
    _clear_telegram_business_env(monkeypatch)

    receipt = build_receipt(include_env_file=None)

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["missing_setup"]
    action = receipt["operator_action"]
    assert action["user_action_required"] is True
    assert action["delivery_policy"] == "action_required_only"
    assert action["telegram_push_allowed"] is True
    assert action["interruption_budget"] == "action_required"
    assert action["non_action_progress_push_allowed"] is False
    assert action["raw_chat_ids_exposed"] is False
    assert action["raw_token_exposed"] is False
    assert action["raw_secret_exposed"] is False
    assert {item["key"] for item in action["setup_checklist"]} == set(receipt["missing_setup"])
    assert "Action needed:" in action["telegram_message"]
    assert receipt["telegram_notification"] == {
        "should_send": True,
        "reason": "user_action_required",
        "delivery_policy": "action_required_only",
        "non_action_progress_push_allowed": False,
        "raw_private_context_exposed": False,
    }

    path = tmp_path / "telegram_business_signal_readiness.generated.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert verify(path) == []


def test_label_allowlist_readiness_receipt_suppresses_raw_labels(monkeypatch, tmp_path) -> None:
    _clear_telegram_business_env(monkeypatch)
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "secret")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://ea.example.test")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "principal")
    monkeypatch.setenv("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_LABELS", "Elisabet Girschele, Developer Circle")

    receipt = build_receipt(include_env_file=None)

    assert receipt["status"] == "pass"
    assert receipt["chat_allowlist"]["allowed_chat_label_count"] == 2
    assert receipt["chat_allowlist"]["raw_chat_labels_exposed"] is False
    assert receipt["setup_status"]["chat_allowlist"]["allowed_chat_label_count"] == 2
    assert receipt["setup_status"]["chat_allowlist"]["raw_chat_labels_exposed"] is False
    assert receipt["operator_action"]["raw_chat_labels_exposed"] is False
    assert "Elisabet" not in json.dumps(receipt)
    assert "Developer Circle" not in json.dumps(receipt)

    path = tmp_path / "telegram_business_signal_readiness.generated.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert verify(path) == []


def test_configured_readiness_receipt_suppresses_telegram_push(monkeypatch, tmp_path) -> None:
    _clear_telegram_business_env(monkeypatch)
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "secret")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://ea.example.test")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "principal")
    monkeypatch.setenv("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES", "hash-one")

    receipt = build_receipt(include_env_file=None)

    assert receipt["status"] == "pass"
    assert receipt["missing_setup"] == []
    action = receipt["operator_action"]
    assert action["user_action_required"] is False
    assert action["delivery_policy"] == "queue_only"
    assert action["telegram_push_allowed"] is False
    assert action["interruption_budget"] == "none"
    assert action["telegram_message"] == ""
    assert receipt["telegram_notification"]["should_send"] is False
    assert receipt["telegram_notification"]["reason"] == "no_operator_action_required"

    path = tmp_path / "telegram_business_signal_readiness.generated.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert verify(path) == []
