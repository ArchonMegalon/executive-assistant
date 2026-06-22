from __future__ import annotations

from app.services.proactive_telegram_binding import _chat_id_from_row, _candidate_principal_ids


def test_chat_id_prefers_default_chat_ref_from_metadata() -> None:
    chat_id = _chat_id_from_row(
        external_ref="ea_concierge_bot",
        metadata={"default_chat_ref": "1354554303"},
    )

    assert chat_id == "1354554303"


def test_chat_id_accepts_numeric_external_ref() -> None:
    chat_id = _chat_id_from_row(external_ref="-1001234567890", metadata={})

    assert chat_id == "-1001234567890"


def test_candidate_principals_include_telegram_default(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "cf-email:user@example.test")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "principal-default")

    assert _candidate_principal_ids("principal") == ["principal", "cf-email:user@example.test", "principal-default"]
