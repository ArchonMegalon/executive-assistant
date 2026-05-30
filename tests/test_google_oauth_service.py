from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
from types import SimpleNamespace

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


def test_google_signal_loader_preserves_explicit_query_filter(monkeypatch: pytest.MonkeyPatch) -> None:
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

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            return _Response({"messages": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        gmail_query="from:(agent.willhaben.at OR no-reply@agent.willhaben.at)",
    )

    list_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[0]).query)
    assert list_query["q"] == ["newer_than:7d from:(agent.willhaben.at OR no-reply@agent.willhaben.at)"]


def test_google_signal_loader_retries_without_q_on_generic_forbidden_query(monkeypatch: pytest.MonkeyPatch) -> None:
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
                    payload={"error": {"code": 403, "message": "Request had insufficient authentication scopes."}},
                )
            return _Response({"messages": [{"id": "msg-2", "threadId": "thread-2"}]})
        if "/gmail/v1/users/me/messages/msg-2?" in url:
            return _Response(
                {
                    "threadId": "thread-2",
                    "labelIds": ["INBOX"],
                    "snippet": "Neue Anzeige gefunden",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "\"Mietwohnungen\" hat 1 neue Anzeige für dich gefunden"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Sat, 29 Mar 2026 12:00:00 +0000"},
                            {"name": "Message-ID", "value": "<msg-2@example.com>"},
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        account_email="elisabeth.girschele@gmail.com",
        gmail_query="from:(agent.willhaben.at OR no-reply@agent.willhaben.at)",
    )

    list_requests = [url for url in requests if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?")]
    assert len(list_requests) == 2
    first_query = urllib.parse.parse_qs(urllib.parse.urlparse(list_requests[0]).query)
    second_query = urllib.parse.parse_qs(urllib.parse.urlparse(list_requests[1]).query)
    assert first_query["q"] == ["newer_than:7d from:(agent.willhaben.at OR no-reply@agent.willhaben.at)"]
    assert "q" not in second_query
    assert rows[0].payload["from_email"] == "no-reply@agent.willhaben.at"


def test_google_signal_loader_uses_full_message_text_when_modify_scope_granted(monkeypatch: pytest.MonkeyPatch) -> None:
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

    plain_body = base64.urlsafe_b64encode(
        b"Please send the revised board packet to Sofia before 09:00.\nThe updated draft is attached in Drive."
    ).decode("ascii").rstrip("=")

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            return _Response({"messages": [{"id": "msg-2", "threadId": "thread-2"}]})
        if "/gmail/v1/users/me/messages/msg-2?" in url:
            return _Response(
                {
                    "threadId": "thread-2",
                    "labelIds": ["INBOX"],
                    "snippet": "Short snippet only.",
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "Subject", "value": "Board packet follow-up"},
                            {"name": "From", "value": "Sofia N. <sofia@example.com>"},
                            {"name": "Date", "value": "Sat, 29 Mar 2026 12:00:00 +0000"},
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": plain_body},
                            }
                        ],
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        include_message_body=True,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.title == "Board packet follow-up"
    assert "Please send the revised board packet to Sofia before 09:00." in row.text
    assert row.summary.startswith("Please send the revised board packet")
    assert row.payload["body_available"] is True
    assert row.payload["body_source"] == "gmail_full"
    assert "updated draft is attached in Drive" in row.payload["body_text_excerpt"]

    detail_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[-1]).query)
    assert detail_query["format"] == ["full"]


def test_google_signal_loader_extracts_pdf_attachments_when_full_message_access_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import google_oauth as google_service

    pdf_bytes = b"%PDF-1.7 test"
    encoded_pdf = base64.urlsafe_b64encode(pdf_bytes).decode("ascii").rstrip("=")

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
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            return _Response({"messages": [{"id": "msg-pdf-1", "threadId": "thread-pdf-1"}]})
        if "/gmail/v1/users/me/messages/msg-pdf-1?" in url:
            return _Response(
                {
                    "threadId": "thread-pdf-1",
                    "labelIds": ["INBOX"],
                    "snippet": "The attachment is included.",
                    "payload": {
                        "mimeType": "multipart/mixed",
                        "headers": [
                            {"name": "Subject", "value": "Medical approval"},
                            {"name": "From", "value": "KfA <office@example.com>"},
                            {"name": "Date", "value": "Sat, 29 Mar 2026 12:00:00 +0000"},
                        ],
                        "parts": [
                            {
                                "partId": "1",
                                "mimeType": "application/pdf",
                                "filename": "approval.pdf",
                                "body": {"attachmentId": "att-1", "size": len(pdf_bytes)},
                            }
                        ],
                    },
                }
            )
        if "/gmail/v1/users/me/messages/msg-pdf-1/attachments/att-1" in url:
            return _Response({"data": encoded_pdf})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        include_message_body=True,
        account_email="tibor.girschele@gmail.com",
    )

    assert len(rows) == 1
    attachment = rows[0].attachments[0]
    assert attachment.filename == "approval.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.content_bytes == pdf_bytes
    assert rows[0].payload["attachments"][0]["filename"] == "approval.pdf"


def test_google_signal_loader_falls_back_to_raw_message_when_full_body_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    raw_message = (
        b"From: Willhaben <no-reply@agent.willhaben.at>\r\n"
        b"Subject: Eigentumswohnungen Digest\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><a href=\"https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-raw-1\">Top Fit</a></body></html>"
    )
    encoded_raw = base64.urlsafe_b64encode(raw_message).decode("ascii").rstrip("=")

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            return _Response({"messages": [{"id": "msg-raw-1", "threadId": "thread-raw-1"}]})
        if "/gmail/v1/users/me/messages/msg-raw-1?format=full" in url:
            return _Response(
                {
                    "threadId": "thread-raw-1",
                    "labelIds": ["INBOX"],
                    "snippet": "",
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "Subject", "value": "Eigentumswohnungen Digest"},
                            {"name": "From", "value": "Willhaben <no-reply@agent.willhaben.at>"},
                        ],
                        "parts": [],
                    },
                }
            )
        if "/gmail/v1/users/me/messages/msg-raw-1?format=raw" in url:
            return _Response({"raw": encoded_raw})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        include_message_body=True,
        account_email="elisabeth.girschele@gmail.com",
    )

    assert len(rows) == 1
    row = rows[0]
    assert "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-raw-1" in row.text
    assert row.payload["body_available"] is True
    assert row.payload["body_source"] == "gmail_raw"
    assert any("format=raw" in url for url in requests)


def test_google_signal_loader_falls_back_to_metadata_when_full_message_fetch_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return _Response({"messages": [{"id": "msg-3", "threadId": "thread-3"}]})
        if "/gmail/v1/users/me/messages/msg-3?" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if query.get("format") == ["full"]:
                raise _http_error(
                    url,
                    code=403,
                    payload={"error": {"code": 403, "message": "Request had insufficient authentication scopes."}},
                )
            return _Response(
                {
                    "threadId": "thread-3",
                    "labelIds": ["INBOX"],
                    "snippet": "Neue Anzeige gefunden",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "\"Mietwohnungen\" hat 1 neue Anzeige für dich gefunden"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Sat, 29 Mar 2026 12:00:00 +0000"},
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        include_message_body=True,
        account_email="elisabeth.girschele@gmail.com",
    )

    assert len(rows) == 1
    assert rows[0].payload["from_email"] == "no-reply@agent.willhaben.at"
    detail_requests = [url for url in requests if "/gmail/v1/users/me/messages/msg-3?" in url]
    assert len(detail_requests) == 2
    assert urllib.parse.parse_qs(urllib.parse.urlparse(detail_requests[0]).query)["format"] == ["full"]
    assert urllib.parse.parse_qs(urllib.parse.urlparse(detail_requests[1]).query)["format"] == ["metadata"]


def test_google_signal_loader_skips_forbidden_message_details_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            return _Response({"messages": [{"id": "msg-4", "threadId": "thread-4"}]})
        if "/gmail/v1/users/me/messages/msg-4?" in url:
            raise _http_error(
                url,
                code=403,
                payload={"error": {"code": 403, "message": "Forbidden"}},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=5,
        include_message_body=False,
        account_email="elisabeth.girschele@gmail.com",
    )

    assert rows == []


def test_html_to_text_preserves_anchor_urls_for_willhaben_listing_links() -> None:
    from app.services import google_oauth as google_service

    html_body = """
    <div>
      Neue Anzeige:
      <a href="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-apartment-123">Zum Inserat</a>
    </div>
    """

    normalized = google_service._normalize_gmail_body_text(google_service._html_to_text(html_body))

    assert "Zum Inserat" in normalized
    assert "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-apartment-123" in normalized


def test_google_signal_loader_pages_deeper_for_older_unseen_mail(monkeypatch: pytest.MonkeyPatch) -> None:
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

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            page_token = str(query.get("pageToken", [""])[0] or "")
            if not page_token:
                return _Response(
                    {
                        "messages": [{"id": "msg-1", "threadId": "thread-1"}],
                        "nextPageToken": "page-2",
                    }
                )
            if page_token == "page-2":
                return _Response(
                    {
                        "messages": [{"id": "msg-2", "threadId": "thread-2"}],
                        "nextPageToken": "page-3",
                    }
                )
            if page_token == "page-3":
                return _Response({"messages": [{"id": "msg-3", "threadId": "thread-3"}]})
        if "/gmail/v1/users/me/messages/msg-1?" in url:
            return _Response(
                {
                    "threadId": "thread-1",
                    "labelIds": ["INBOX"],
                    "snippet": "Newest mail",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Newest alert"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Fri, 01 May 2026 10:00:00 +0000"},
                        ]
                    },
                }
            )
        if "/gmail/v1/users/me/messages/msg-2?" in url:
            return _Response(
                {
                    "threadId": "thread-2",
                    "labelIds": ["INBOX"],
                    "snippet": "Older mail",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Older alert"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Thu, 30 Apr 2026 10:00:00 +0000"},
                        ]
                    },
                }
            )
        if "/gmail/v1/users/me/messages/msg-3?" in url:
            return _Response(
                {
                    "threadId": "thread-3",
                    "labelIds": ["INBOX"],
                    "snippet": "Oldest unseen mail",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Historical alert"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Wed, 29 Apr 2026 10:00:00 +0000"},
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(access_token="token-123", max_results=5)

    assert [row.source_ref for row in rows] == [
        "gmail-thread:thread-1",
        "gmail-thread:thread-2",
        "gmail-thread:thread-3",
    ]
    list_requests = [url for url in requests if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?")]
    assert len(list_requests) == 3
    parsed_queries = [urllib.parse.parse_qs(urllib.parse.urlparse(url).query) for url in list_requests]
    assert parsed_queries[0]["maxResults"] == ["100"]
    assert "pageToken" not in parsed_queries[0]
    assert parsed_queries[1]["pageToken"] == ["page-2"]
    assert parsed_queries[2]["pageToken"] == ["page-3"]


def test_google_signal_loader_skips_seen_mail_and_continues_paging(monkeypatch: pytest.MonkeyPatch) -> None:
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

    def _fake_urlopen(request, timeout=30):  # type: ignore[no-untyped-def]
        url = str(request.full_url)
        requests.append(url)
        if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            page_token = str(query.get("pageToken", [""])[0] or "")
            if not page_token:
                return _Response(
                    {
                        "messages": [{"id": "msg-1", "threadId": "thread-1"}],
                        "nextPageToken": "page-2",
                    }
                )
            if page_token == "page-2":
                return _Response(
                    {
                        "messages": [{"id": "msg-2", "threadId": "thread-2"}],
                        "nextPageToken": "page-3",
                    }
                )
            if page_token == "page-3":
                return _Response({"messages": [{"id": "msg-3", "threadId": "thread-3"}]})
        if "/gmail/v1/users/me/messages/msg-3?" in url:
            return _Response(
                {
                    "threadId": "thread-3",
                    "labelIds": ["INBOX"],
                    "snippet": "Oldest unseen mail",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Historical alert"},
                            {"name": "From", "value": "willhaben-Suchagent <no-reply@agent.willhaben.at>"},
                            {"name": "Date", "value": "Wed, 29 Apr 2026 10:00:00 +0000"},
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(google_service.urllib.request, "urlopen", _fake_urlopen)

    rows = google_service._list_recent_gmail_signals(
        access_token="token-123",
        max_results=1,
        account_email="elisabeth.girschele@gmail.com",
        seen_source_refs={
            "gmail-thread:elisabeth.girschele@gmail.com:thread-1",
            "gmail-thread:elisabeth.girschele@gmail.com:thread-2",
        },
        seen_external_ids={
            "gmail-message:elisabeth.girschele@gmail.com:msg-1",
            "gmail-message:elisabeth.girschele@gmail.com:msg-2",
        },
    )

    assert [row.external_id for row in rows] == ["gmail-message:elisabeth.girschele@gmail.com:msg-3"]
    detail_requests = [url for url in requests if "/gmail/v1/users/me/messages/msg-" in url]
    assert detail_requests == [next(url for url in requests if "/gmail/v1/users/me/messages/msg-3?" in url)]


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


def test_google_workspace_signal_sync_reads_all_connected_google_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.models import ProviderBindingRecord
    from app.services import google_oauth as google_service

    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    class _Registry:
        def __init__(self) -> None:
            self.rows: dict[str, ProviderBindingRecord] = {
                "exec-google:google_gmail": ProviderBindingRecord(
                    binding_id="exec-google:google_gmail",
                    principal_id="exec-google",
                    provider_key="google_gmail",
                    status="enabled",
                    priority=80,
                    probe_state="ready",
                    probe_details_json={},
                    scope_json={"bundle": "core"},
                    auth_metadata_json={
                        "google_subject": "google-sub-1",
                        "google_email": "tibor@girschele.com",
                        "google_hosted_domain": "girschele.com",
                        "granted_scopes": [
                            google_service.GOOGLE_SCOPE_METADATA,
                            google_service.GOOGLE_SCOPE_CALENDAR_READONLY,
                        ],
                        "refresh_token_ref": "refresh-primary",
                        "token_status": "active",
                    },
                    created_at="2026-05-02T00:00:00Z",
                    updated_at="2026-05-02T00:00:00Z",
                ),
                "exec-google:google_gmail:acct:google-sub-2": ProviderBindingRecord(
                    binding_id="exec-google:google_gmail:acct:google-sub-2",
                    principal_id="exec-google",
                    provider_key="google_gmail",
                    status="enabled",
                    priority=80,
                    probe_state="ready",
                    probe_details_json={},
                    scope_json={"bundle": "verify"},
                    auth_metadata_json={
                        "google_subject": "google-sub-2",
                        "google_email": "office@girschele.com",
                        "google_hosted_domain": "girschele.com",
                        "granted_scopes": [google_service.GOOGLE_SCOPE_METADATA],
                        "refresh_token_ref": "refresh-secondary",
                        "token_status": "active",
                    },
                    created_at="2026-05-02T00:00:00Z",
                    updated_at="2026-05-02T00:00:01Z",
                ),
            }

        def list_persisted_binding_records(self, *, principal_id: str, limit: int = 100):
            return tuple(row for row in self.rows.values() if row.principal_id == principal_id)[:limit]

        def get_persisted_binding_record(self, *, binding_id: str, principal_id: str | None = None):
            row = self.rows.get(binding_id)
            if row is None:
                return None
            if principal_id and row.principal_id != principal_id:
                return None
            return row

        def upsert_binding_record(
            self,
            *,
            binding_id: str | None = None,
            principal_id: str,
            provider_key: str,
            status: str = "enabled",
            priority: int = 100,
            probe_state: str = "unknown",
            probe_details_json: dict[str, object] | None = None,
            scope_json: dict[str, object] | None = None,
            auth_metadata_json: dict[str, object] | None = None,
        ):
            existing = self.rows[str(binding_id)]
            updated = ProviderBindingRecord(
                binding_id=existing.binding_id,
                principal_id=principal_id,
                provider_key=provider_key,
                status=status,
                priority=priority,
                probe_state=probe_state,
                probe_details_json=dict(probe_details_json or {}),
                scope_json=dict(scope_json or {}),
                auth_metadata_json=dict(auth_metadata_json or {}),
                created_at=existing.created_at,
                updated_at="2026-05-02T00:05:00Z",
            )
            self.rows[updated.binding_id] = updated
            return updated

    monkeypatch.setattr(google_service, "_decrypt_secret", lambda value, key: str(value))
    monkeypatch.setattr(
        google_service,
        "_refresh_google_access_token",
        lambda **kwargs: {"access_token": f"token-{kwargs['refresh_token']}", "expires_in": 3600},
    )
    monkeypatch.setattr(
        google_service,
        "_list_recent_gmail_signals",
        lambda **kwargs: [
            google_service.GoogleWorkspaceSignal(
                signal_type="email_thread",
                channel="gmail",
                title=f"Mail for {kwargs['account_email']}",
                summary="",
                text="",
                source_ref=f"gmail-thread:{kwargs['account_email']}:thread-1",
                external_id=f"gmail-message:{kwargs['account_email']}:msg-1",
                counterparty="Counterparty",
                due_at=None,
                payload={"account_email": kwargs["account_email"]},
            )
        ],
    )
    monkeypatch.setattr(
        google_service,
        "_list_recent_calendar_signals",
        lambda **kwargs: [
            google_service.GoogleWorkspaceSignal(
                signal_type="calendar_note",
                channel="calendar",
                title="Board prep",
                summary="",
                text="",
                source_ref=f"calendar-event:{kwargs['account_email']}:evt-1",
                external_id=f"calendar-event:{kwargs['account_email']}:evt-1",
                counterparty="Counterparty",
                due_at=None,
                payload={"account_email": kwargs["account_email"]},
            )
        ]
        if kwargs["account_email"] == "tibor@girschele.com"
        else [],
    )

    container = SimpleNamespace(provider_registry=_Registry())

    packet = google_service.list_recent_workspace_signals(
        container=container,
        principal_id="exec-google",
        email_limit=5,
        calendar_limit=5,
    )

    assert packet.account_email == "tibor@girschele.com"
    assert packet.account_emails == ("tibor@girschele.com", "office@girschele.com")
    assert set(packet.granted_scopes) == {
        google_service.GOOGLE_SCOPE_METADATA,
        google_service.GOOGLE_SCOPE_CALENDAR_READONLY,
    }
    assert [row.source_ref for row in packet.signals] == [
        "gmail-thread:tibor@girschele.com:thread-1",
        "calendar-event:tibor@girschele.com:evt-1",
        "gmail-thread:office@girschele.com:thread-1",
    ]


def test_list_recent_workspace_signals_filters_to_requested_account_and_forwards_gmail_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import google_oauth as google_service

    class _Binding(SimpleNamespace):
        pass

    class _Registry:
        def upsert_binding_record(self, **kwargs):  # type: ignore[no-untyped-def]
            return kwargs

    monkeypatch.setattr(
        google_service,
        "_list_google_binding_records",
        lambda **_: [
            _Binding(
                binding_id="binding-primary",
                status="enabled",
                priority=80,
                scope_json={},
                probe_details_json={},
                auth_metadata_json={
                    "google_email": "tibor@girschele.com",
                    "refresh_token_ref": "refresh-primary",
                    "granted_scopes": [google_service.GOOGLE_SCOPE_METADATA],
                },
            ),
            _Binding(
                binding_id="binding-secondary",
                status="enabled",
                priority=80,
                scope_json={},
                probe_details_json={},
                auth_metadata_json={
                    "google_email": "elisabeth.girschele@gmail.com",
                    "refresh_token_ref": "refresh-secondary",
                    "granted_scopes": [google_service.GOOGLE_SCOPE_METADATA],
                },
            ),
        ],
    )
    monkeypatch.setattr(
        google_service,
        "load_google_oauth_config",
        lambda: SimpleNamespace(
            provider_secret_key="secret",
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    monkeypatch.setattr(google_service, "_decrypt_secret", lambda value, key: value)
    monkeypatch.setattr(
        google_service,
        "_refresh_google_access_token",
        lambda **kwargs: {"access_token": f"token-{kwargs['refresh_token']}", "expires_in": 3600},
    )

    gmail_calls: list[dict[str, object]] = []

    def _fake_list_recent_gmail_signals(**kwargs):  # type: ignore[no-untyped-def]
        gmail_calls.append(dict(kwargs))
        return [
            google_service.GoogleWorkspaceSignal(
                signal_type="email_thread",
                channel="gmail",
                title="Mail",
                summary="",
                text="",
                source_ref=f"gmail-thread:{kwargs['account_email']}:thread-1",
                external_id=f"gmail-message:{kwargs['account_email']}:msg-1",
                counterparty="Counterparty",
                due_at=None,
                payload={"account_email": kwargs["account_email"]},
            )
        ]

    monkeypatch.setattr(google_service, "_list_recent_gmail_signals", _fake_list_recent_gmail_signals)
    monkeypatch.setattr(google_service, "_list_recent_calendar_signals", lambda **kwargs: [])

    packet = google_service.list_recent_workspace_signals(
        container=SimpleNamespace(provider_registry=_Registry()),
        principal_id="exec-google",
        email_limit=5,
        calendar_limit=0,
        account_email_filter="elisabeth.girschele@gmail.com",
        gmail_query="from:(agent.willhaben.at OR no-reply@agent.willhaben.at)",
    )

    assert packet.account_email == "elisabeth.girschele@gmail.com"
    assert packet.account_emails == ("elisabeth.girschele@gmail.com",)
    assert [row.source_ref for row in packet.signals] == [
        "gmail-thread:elisabeth.girschele@gmail.com:thread-1",
    ]
    assert len(gmail_calls) == 1
    assert gmail_calls[0]["account_email"] == "elisabeth.girschele@gmail.com"
    assert gmail_calls[0]["gmail_query"] == "from:(agent.willhaben.at OR no-reply@agent.willhaben.at)"


def test_list_recent_workspace_signals_falls_back_to_local_user_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import ProviderBindingRecord
    from app.services import google_oauth as google_service

    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    class _Registry:
        def __init__(self) -> None:
            self.rows: dict[str, ProviderBindingRecord] = {
                "local-user:google_gmail": ProviderBindingRecord(
                    binding_id="local-user:google_gmail",
                    principal_id="local-user",
                    provider_key="google_gmail",
                    status="enabled",
                    priority=80,
                    probe_state="ready",
                    probe_details_json={},
                    scope_json={"bundle": "core"},
                    auth_metadata_json={
                        "google_subject": "google-sub-local",
                        "google_email": "elisabeth.girschele@gmail.com",
                        "granted_scopes": [google_service.GOOGLE_SCOPE_METADATA],
                        "refresh_token_ref": "refresh-local",
                        "token_status": "active",
                    },
                    created_at="2026-05-30T00:00:00Z",
                    updated_at="2026-05-30T00:00:00Z",
                ),
            }

        def list_persisted_binding_records(self, *, principal_id: str, limit: int = 100):
            return tuple(row for row in self.rows.values() if row.principal_id == principal_id)[:limit]

        def get_persisted_binding_record(self, *, binding_id: str, principal_id: str | None = None):
            row = self.rows.get(binding_id)
            if row is None:
                return None
            if principal_id and row.principal_id != principal_id:
                return None
            return row

        def upsert_binding_record(
            self,
            *,
            binding_id: str,
            principal_id: str,
            provider_key: str,
            status: str = "enabled",
            priority: int = 100,
            probe_state: str = "unknown",
            probe_details_json: dict[str, object] | None = None,
            scope_json: dict[str, object] | None = None,
            auth_metadata_json: dict[str, object] | None = None,
        ):
            updated = ProviderBindingRecord(
                binding_id=binding_id,
                principal_id=principal_id,
                provider_key=provider_key,
                status=status,
                priority=priority,
                probe_state=probe_state,
                probe_details_json=dict(probe_details_json or {}),
                scope_json=dict(scope_json or {}),
                auth_metadata_json=dict(auth_metadata_json or {}),
                created_at=self.rows[binding_id].created_at,
                updated_at="2026-05-30T00:05:00Z",
            )
            self.rows[binding_id] = updated
            return updated

    monkeypatch.setattr(google_service, "_decrypt_secret", lambda value, key: str(value))
    monkeypatch.setattr(
        google_service,
        "_refresh_google_access_token",
        lambda **kwargs: {"access_token": f"token-{kwargs['refresh_token']}", "expires_in": 3600},
    )
    monkeypatch.setattr(
        google_service,
        "_list_recent_gmail_signals",
        lambda **kwargs: [
            google_service.GoogleWorkspaceSignal(
                signal_type="email_thread",
                channel="gmail",
                title="Mail for Elisabeth",
                summary="",
                text="",
                source_ref="gmail-thread:elisabeth.girschele@gmail.com:thread-1",
                external_id="gmail-message:elisabeth.girschele@gmail.com:msg-1",
                counterparty="Counterparty",
                due_at=None,
                payload={"account_email": kwargs["account_email"]},
            )
        ],
    )
    monkeypatch.setattr(google_service, "_list_recent_calendar_signals", lambda **kwargs: [])

    packet = google_service.list_recent_workspace_signals(
        container=SimpleNamespace(provider_registry=_Registry()),
        principal_id="cf-email:tibor.girschele@gmail.com",
        email_limit=5,
        calendar_limit=0,
        account_email_filter="elisabeth.girschele@gmail.com",
    )

    assert packet.account_email == "elisabeth.girschele@gmail.com"
    assert packet.account_emails == ("elisabeth.girschele@gmail.com",)
    assert [row.source_ref for row in packet.signals] == [
        "gmail-thread:elisabeth.girschele@gmail.com:thread-1",
    ]


def test_list_recent_workspace_signals_marks_binding_reauth_required_on_invalid_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import google_oauth as google_service

    class _Binding(SimpleNamespace):
        pass

    class _Registry:
        def __init__(self) -> None:
            self.upserts: list[dict[str, object]] = []

        def upsert_binding_record(self, **kwargs):  # type: ignore[no-untyped-def]
            self.upserts.append(dict(kwargs))
            return kwargs

    monkeypatch.setattr(
        google_service,
        "_list_google_binding_records",
        lambda **_: [
            _Binding(
                binding_id="binding-invalid-grant",
                status="enabled",
                priority=80,
                scope_json={},
                probe_details_json={},
                auth_metadata_json={
                    "google_email": "tibor.girschele@gmail.com",
                    "refresh_token_ref": "refresh-token",
                    "granted_scopes": [google_service.GOOGLE_SCOPE_METADATA],
                    "token_status": "active",
                    "reauth_required_reason": "",
                },
            )
        ],
    )
    monkeypatch.setattr(
        google_service,
        "load_google_oauth_config",
        lambda: SimpleNamespace(
            provider_secret_key="secret",
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    monkeypatch.setattr(google_service, "_decrypt_secret", lambda value, key: value)

    def _raise_invalid_grant(**kwargs):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            google_service.GOOGLE_TOKEN_ENDPOINT,
            400,
            "Bad Request",
            None,
            io.BytesIO(b'{\"error\":\"invalid_grant\",\"error_description\":\"Bad Request\"}'),
        )

    monkeypatch.setattr(google_service, "_refresh_google_access_token", _raise_invalid_grant)

    registry = _Registry()
    with pytest.raises(RuntimeError, match="google_oauth_invalid_grant"):
        google_service.list_recent_workspace_signals(
            container=SimpleNamespace(provider_registry=registry),
            principal_id="exec-google",
            email_limit=5,
            calendar_limit=0,
            account_email_filter="tibor.girschele@gmail.com",
        )

    assert len(registry.upserts) == 1
    assert registry.upserts[0]["probe_state"] == "degraded"
    assert registry.upserts[0]["auth_metadata_json"]["token_status"] == "reauth_required"
    assert registry.upserts[0]["auth_metadata_json"]["reauth_required_reason"] == "google_oauth_invalid_grant"


def test_send_google_gmail_message_marks_binding_reauth_required_on_invalid_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import google_oauth as google_service

    binding = SimpleNamespace(
        binding_id="binding-send-invalid-grant",
        principal_id="exec-google",
        provider_key=google_service.GOOGLE_PROVIDER_KEY,
        status="enabled",
        priority=80,
        probe_state="ready",
        probe_details_json={},
        scope_json={},
        auth_metadata_json={
            "google_email": "tibor.girschele@gmail.com",
            "refresh_token_ref": "refresh-token",
            "granted_scopes": [google_service.GOOGLE_SCOPE_SEND],
            "token_status": "active",
            "reauth_required_reason": "",
        },
    )

    class _Registry:
        def __init__(self) -> None:
            self.upserts: list[dict[str, object]] = []

        def get_persisted_binding_record(self, **kwargs):  # type: ignore[no-untyped-def]
            return binding

        def upsert_binding_record(self, **kwargs):  # type: ignore[no-untyped-def]
            self.upserts.append(dict(kwargs))
            return kwargs

    monkeypatch.setattr(
        google_service,
        "load_google_oauth_config",
        lambda: SimpleNamespace(
            provider_secret_key="secret",
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    monkeypatch.setattr(google_service, "_decrypt_secret", lambda value, key: value)

    def _raise_invalid_grant(**kwargs):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            google_service.GOOGLE_TOKEN_ENDPOINT,
            400,
            "Bad Request",
            None,
            io.BytesIO(b'{\"error\":\"invalid_grant\",\"error_description\":\"Bad Request\"}'),
        )

    monkeypatch.setattr(google_service, "_refresh_google_access_token", _raise_invalid_grant)

    registry = _Registry()
    with pytest.raises(urllib.error.HTTPError):
        google_service.send_google_gmail_message(
            container=SimpleNamespace(provider_registry=registry),
            principal_id="exec-google",
            recipient_email="tibor.girschele@gmail.com",
            subject="Subject",
            body_text="Body",
            binding_id="binding-send-invalid-grant",
        )

    assert len(registry.upserts) == 1
    assert registry.upserts[0]["probe_state"] == "degraded"
    assert registry.upserts[0]["auth_metadata_json"]["token_status"] == "reauth_required"
    assert registry.upserts[0]["auth_metadata_json"]["reauth_required_reason"] == "google_oauth_invalid_grant"
