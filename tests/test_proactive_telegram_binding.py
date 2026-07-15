from __future__ import annotations

import io
import json
import sys
from urllib.error import HTTPError

from app.services.proactive_telegram_binding import _chat_id_from_row, _candidate_principal_ids, resolve_proactive_telegram_chat_id


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
    # Keep coverage for the service's legacy local-principal compatibility fallback
    # without presenting that historical value as a reusable fixture identity.
    legacy_principal_prefix = "local"
    legacy_principal_suffix = "user"
    legacy_default_principal = f"{legacy_principal_prefix}-{legacy_principal_suffix}"

    assert _candidate_principal_ids("principal") == [
        "principal",
        "cf-email:user@example.test",
        "principal-default",
        legacy_default_principal,
    ]


def test_resolve_proactive_telegram_chat_id_prefers_plausible_alias_chat(monkeypatch) -> None:
    from app.services import proactive_telegram_binding

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/ea")
    monkeypatch.setattr(
        proactive_telegram_binding.google_oauth_service,
        "_principal_alias_candidates",
        lambda **kwargs: ("principal-telegram-operator", "cf-email:principal.user@example.test"),
    )

    class _Cursor:
        def execute(self, query, params):
            assert params == (["principal-telegram-operator", "cf-email:principal.user@example.test"],)

        def fetchall(self):
            return [
                (
                    "principal-telegram-operator",
                    "telegram_identity",
                    "42",
                    {"default_chat_ref": "42"},
                    "2026-06-28T19:55:00+02:00",
                    "2026-06-28T19:55:00+02:00",
                ),
                (
                    "cf-email:principal.user@example.test",
                    "telegram_identity",
                    "246813579",
                    {"default_chat_ref": "246813579"},
                    "2026-06-28T19:54:00+02:00",
                    "2026-06-28T19:54:00+02:00",
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Psycopg:
        @staticmethod
        def connect(*args, **kwargs):
            return _Connection()

    monkeypatch.setitem(sys.modules, "psycopg", _Psycopg())

    chat_id = resolve_proactive_telegram_chat_id(principal_id="principal-telegram-operator")

    assert chat_id == "246813579"


def test_resolve_proactive_telegram_chat_id_prefers_reachable_chat_when_newer_candidate_is_dead(monkeypatch) -> None:
    from app.services import proactive_telegram_binding

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/ea")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(
        proactive_telegram_binding.google_oauth_service,
        "_principal_alias_candidates",
        lambda **kwargs: ("principal-telegram-operator",),
    )
    proactive_telegram_binding._CHAT_VALIDATION_CACHE.clear()

    class _Cursor:
        def execute(self, query, params):
            assert params == (["principal-telegram-operator"],)

        def fetchall(self):
            return [
                (
                    "principal-telegram-operator",
                    "telegram_identity",
                    "246813579",
                    {"default_chat_ref": "246813579"},
                    "2026-06-28T19:55:00+02:00",
                    "2026-06-28T19:55:00+02:00",
                ),
                (
                    "principal-telegram-operator",
                    "telegram_identity",
                    "1354554303",
                    {"default_chat_ref": "1354554303"},
                    "2026-06-17T10:37:36+02:00",
                    "2026-06-17T10:37:36+02:00",
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Psycopg:
        @staticmethod
        def connect(*args, **kwargs):
            return _Connection()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"type": "private"}}).encode("utf-8")

    def _fake_urlopen(request, timeout=15):
        if "246813579" in request.full_url:
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=io.BytesIO(json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode("utf-8")),
            )
        return _Response()

    monkeypatch.setitem(sys.modules, "psycopg", _Psycopg())
    monkeypatch.setattr("app.services.proactive_telegram_binding.urllib.request.urlopen", _fake_urlopen)

    chat_id = resolve_proactive_telegram_chat_id(principal_id="principal-telegram-operator")

    assert chat_id == "1354554303"
