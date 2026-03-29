from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest


pytest.importorskip("fastapi")


def test_google_signal_loader_retries_without_q_for_metadata_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import google_oauth as google_service

    requests: list[str] = []

    class _Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = json.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def _http_error(url: str, *, code: int, payload: dict[str, object]) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url=url,
            code=code,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "q" in query:
                raise _http_error(
                    url,
                    code=403,
                    payload={
                        "error": {
                            "code": 403,
                            "message": "Metadata scope does not support 'q' parameter",
                        }
                    },
                )
            return _Response({"messages": [{"id": "msg-1", "threadId": "thread-1"}]})
        if "/gmail/v1/users/me/messages/msg-1?" in url:
            return _Response(
                {
                    "threadId": "thread-1",
                    "labelIds": ["INBOX"],
                    "snippet": "Please send the revised board packet tomorrow.",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Investor follow-up"},
                            {"name": "From", "value": "Sofia N. <sofia@example.com>"},
                            {"name": "Date", "value": "Sat, 29 Mar 2026 12:00:00 +0000"},
                            {"name": "Message-ID", "value": "<msg-1@example.com>"},
                            {"name": "In-Reply-To", "value": "<prev@example.com>"},
                            {"name": "References", "value": "<prev@example.com> <older@example.com>"},
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(access_token="token-123", max_results=5)

    assert len(rows) == 1
    row = rows[0]
    assert row.title == "Investor follow-up"
    assert row.source_ref == "gmail-thread:thread-1"
    assert row.payload["message_id"] == "msg-1"
    assert row.payload["rfc822_message_id"] == "<msg-1@example.com>"
    assert row.payload["in_reply_to"] == "<prev@example.com>"
    assert row.payload["references"] == "<prev@example.com> <older@example.com>"

    list_requests = [url for url in requests if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?")]
    assert len(list_requests) == 2
    first_query = urllib.parse.parse_qs(urllib.parse.urlparse(list_requests[0]).query)
    second_query = urllib.parse.parse_qs(urllib.parse.urlparse(list_requests[1]).query)
    assert first_query["q"] == ["newer_than:7d"]
    assert "q" not in second_query

    metadata_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[-1]).query)
    assert metadata_query["metadataHeaders"] == [
        "Subject",
        "From",
        "Date",
        "Message-ID",
        "In-Reply-To",
        "References",
        "List-Unsubscribe",
        "Auto-Submitted",
        "Precedence",
    ]


def test_google_calendar_signal_loader_omits_self_only_attendee_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import google_oauth as google_service

    class _Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = json.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        if url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events?"):
            return _Response(
                {
                    "items": [
                        {
                            "id": "evt-1",
                            "summary": "ADHS psychiater",
                            "status": "confirmed",
                            "start": {"dateTime": "2026-03-30T09:00:00+02:00"},
                            "end": {"dateTime": "2026-03-30T10:00:00+02:00"},
                            "organizer": {"email": "exec@example.com", "self": True},
                            "attendees": [{"email": "exec@example.com", "self": True}],
                            "htmlLink": "https://calendar.google.test/evt-1",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_calendar_signals(
        access_token="token-123",
        max_results=5,
        account_email="exec@example.com",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.counterparty == ""
    assert row.text == "ADHS psychiater"
    assert row.payload["attendees"] == ["exec@example.com"]
    assert row.payload["account_email"] == "exec@example.com"
