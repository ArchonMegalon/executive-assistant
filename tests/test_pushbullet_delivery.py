from __future__ import annotations

import json

from app.services import pushbullet_delivery


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_discover_pushbullet_clients_finds_named_second_client_without_exposing_email() -> None:
    clients = pushbullet_delivery.discover_pushbullet_clients(
        {
            "PB_TOKEN_ELISABETH": "",
            "PUSHBULLET_ELISABETH_EMAIL": "Elisabeth.Girschele@gmail.com",
        }
    )

    assert len(clients) == 1
    client = clients[0]
    assert client.client_key == "elisabeth"
    assert client.token_env == "PB_TOKEN_ELISABETH"
    assert client.token_present is False
    assert client.email_domain == "gmail.com"
    assert client.email_sha256
    assert "Elisabeth" not in json.dumps(client.__dict__, sort_keys=True)


def test_probe_pushbullet_client_verifies_account_hash_without_raw_email() -> None:
    captured: list[object] = []

    def _fake_urlopen(request, timeout=20):
        captured.append((request, timeout))
        return _FakeResponse({"iden": "user-1", "email_normalized": "elisabeth.girschele@gmail.com"})

    probe = pushbullet_delivery.probe_pushbullet_client(
        "elisabeth",
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        opener=_fake_urlopen,
    )

    assert probe["status"] == "pass"
    assert probe["expected_email_matches"] is True
    assert probe["raw_email_exposed"] is False
    assert probe["raw_token_exposed"] is False
    assert "elisabeth.girschele@gmail.com" not in json.dumps(probe, sort_keys=True)
    request, timeout = captured[0]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "https://api.pushbullet.com/v2/users/me"
    assert headers["access-token"] == "push-token"
    assert timeout == 20.0


def test_send_pushbullet_note_posts_sanitized_note_payload() -> None:
    captured: list[object] = []

    def _fake_urlopen(request, timeout=20):
        captured.append((request, timeout))
        return _FakeResponse({"iden": "push-1"})

    receipt = pushbullet_delivery.send_pushbullet_note(
        client_key="elisabeth",
        title="EA action needed",
        body="Open the auth link.",
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        opener=_fake_urlopen,
    )

    assert receipt.status == "sent"
    assert receipt.client_key == "elisabeth"
    assert receipt.delivery_transport == "pushbullet"
    assert receipt.push_type == "note"
    assert receipt.push_id_hash
    request, _timeout = captured[0]
    headers = {key.lower(): value for key, value in request.header_items()}
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.pushbullet.com/v2/pushes"
    assert headers["access-token"] == "push-token"
    assert payload == {"type": "note", "title": "EA action needed", "body": "Open the auth link."}


def test_send_pushbullet_link_uses_link_type_when_url_present() -> None:
    captured: list[dict[str, object]] = []

    def _fake_urlopen(request, timeout=20):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse({"iden": "push-2"})

    receipt = pushbullet_delivery.send_pushbullet_note(
        client_key="elisabeth",
        title="EA link",
        body="Open this.",
        url="https://myexternalbrain.com/app/actions/google/connect",
        env={
            "PB_TOKEN_ELISABETH": "push-token",
            "PUSHBULLET_ELISABETH_EMAIL": "elisabeth.girschele@gmail.com",
        },
        opener=_fake_urlopen,
    )

    assert receipt.push_type == "link"
    assert captured[0]["type"] == "link"
    assert captured[0]["url"] == "https://myexternalbrain.com/app/actions/google/connect"
