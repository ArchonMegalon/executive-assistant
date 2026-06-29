from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_crezlo_batch_principal_defaults_to_runtime_principal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "workspace-owner")
    module = _load_script(ROOT / "scripts" / "run_crezlo_property_tour_batch.py", "run_crezlo_property_tour_batch_defaults")

    args = module.parse_args(
        [
            "--packets",
            str(tmp_path / "packets.json"),
            "--binding-id",
            "crezlo-binding",
        ]
    )

    assert args.principal_id == "workspace-owner"


def test_emailit_scripts_default_to_generic_sender() -> None:
    tour_email = _load_script(
        ROOT / "scripts" / "send_crezlo_property_tour_results_email.py",
        "send_crezlo_property_tour_results_email_defaults",
    )
    outbox = _load_script(ROOT / "scripts" / "process_emailit_delivery_outbox.py", "process_emailit_delivery_outbox_defaults")

    assert tour_email.DEFAULT_SENDER_EMAIL == "no-reply@example.test"
    assert tour_email.DEFAULT_SENDER_NAME == "Executive Assistant"
    assert outbox.DEFAULT_SENDER_EMAIL == "no-reply@example.test"
    assert outbox.DEFAULT_SENDER_NAME == "Executive Assistant"


def test_emailit_outbox_daily_limit_fails_fast_without_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = _load_script(
        ROOT / "scripts" / "process_emailit_delivery_outbox.py",
        "process_emailit_delivery_outbox_daily_limit",
    )
    monkeypatch.setenv("EA_EMAILIT_MAX_429_SLEEP_SECONDS", "30")

    def _rate_limited(request, timeout=0):
        detail = json.dumps({"error": "Daily limit exceeded", "retry_after": 47381}).encode("utf-8")
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(detail))

    sleeps: list[int] = []
    monkeypatch.setattr(outbox.urllib.request, "urlopen", _rate_limited)
    monkeypatch.setattr(outbox.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(outbox.EmailitRateLimitedError) as raised:
        outbox.emailit_send(
            api_key="emailit-key",
            sender_email="sender@example.test",
            sender_name="EA",
            recipient_email="recipient@example.test",
            subject="Subject",
            content="Body",
            metadata={"delivery_id": "delivery-1"},
            idempotency_key="delivery-1",
        )

    assert raised.value.retry_after_seconds == 47381
    assert "Daily limit exceeded" in str(raised.value)
    assert sleeps == []


def test_emailit_outbox_short_429_still_sleeps_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = _load_script(
        ROOT / "scripts" / "process_emailit_delivery_outbox.py",
        "process_emailit_delivery_outbox_short_limit",
    )
    monkeypatch.setenv("EA_EMAILIT_MAX_429_SLEEP_SECONDS", "30")
    calls = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"id": "emailit-message-1"}).encode("utf-8")

    def _urlopen(request, timeout=0):
        calls["count"] += 1
        if calls["count"] == 1:
            detail = json.dumps({"error": "Too many requests", "retry_after": 2}).encode("utf-8")
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(detail))
        return _Response()

    sleeps: list[int] = []
    monkeypatch.setattr(outbox.urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(outbox.time, "sleep", lambda seconds: sleeps.append(seconds))

    receipt = outbox.emailit_send(
        api_key="emailit-key",
        sender_email="sender@example.test",
        sender_name="EA",
        recipient_email="recipient@example.test",
        subject="Subject",
        content="Body",
        metadata={"delivery_id": "delivery-1"},
        idempotency_key="delivery-1",
    )

    assert receipt["id"] == "emailit-message-1"
    assert sleeps == [2]
    assert calls["count"] == 2


def test_emailit_outbox_main_reschedules_provider_rate_limit(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    outbox = _load_script(
        ROOT / "scripts" / "process_emailit_delivery_outbox.py",
        "process_emailit_delivery_outbox_main_rate_limit",
    )
    row = {
        "delivery_id": "delivery-1",
        "channel": "email",
        "recipient": "recipient@example.test",
        "content": "Body",
        "metadata": {
            "principal_id": "principal@example.test",
            "binding_id": "binding-1",
            "subject": "Subject",
        },
        "idempotency_key": "delivery-1",
        "attempt_count": 99,
    }
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        outbox,
        "parse_args",
        lambda: SimpleNamespace(
            host="http://ea.test",
            api_token="token",
            emailit_api_key="emailit-key",
            limit=50,
            default_from_email="default@example.test",
            default_from_name="EA",
            only_principal="",
        ),
    )
    monkeypatch.setattr(outbox, "pending_delivery", lambda host, api_token, limit: [row])
    monkeypatch.setattr(
        outbox,
        "connector_bindings",
        lambda host, api_token, principal_id: {
            "binding-1": {"connector_name": "Emailit", "auth_metadata_json": {"sender_email": "sender@example.test"}}
        },
    )
    monkeypatch.setattr(
        outbox,
        "emailit_send",
        lambda **kwargs: (_ for _ in ()).throw(
            outbox.EmailitRateLimitedError(retry_after_seconds=47381, provider_error="Daily limit exceeded")
        ),
    )

    def _mark_failed(host, api_token, delivery_id, error, *, dead_letter, retry_in_seconds=60):
        seen.update(
            {
                "delivery_id": delivery_id,
                "error": error,
                "dead_letter": dead_letter,
                "retry_in_seconds": retry_in_seconds,
            }
        )
        return {"status": "retry"}

    monkeypatch.setattr(outbox, "mark_failed", _mark_failed)

    assert outbox.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert seen["delivery_id"] == "delivery-1"
    assert seen["dead_letter"] is False
    assert seen["retry_in_seconds"] == 47381
    assert payload["processed"][0]["status"] == "retry"
