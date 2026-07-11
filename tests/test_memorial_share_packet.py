from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import public_memorial_share
from app.services.memorial_share_packet import (
    CORRECTION_DISCLOSURE,
    SHARE_DISCLOSURE,
    MemorialSharePacketError,
    build_memorial_share_packet,
)
from scripts import build_memorial_share_packet as share_cli


_SECRET = "do-not-share-9f4fd08e"


def _memorial() -> dict[str, object]:
    return {
        "slug": "manfred",
        "person_name": "Manfred",
        "title": "In Erinnerung an Manfred",
        "provider": {"token": _SECRET},
        "voice_consent": {"raw_form": _SECRET},
        "private_notes": _SECRET,
        "audio_clips": [
            {
                "visibility": "public",
                "approved": True,
                "title": "Eine oeffentliche Erinnerung",
                "asset_relpath": "audio/public-memory.mp3",
                "provider_token": _SECRET,
                "private_transcript": _SECRET,
            },
            {
                "visibility": "private",
                "approved": True,
                "title": _SECRET,
                "asset_relpath": "audio/private-memory.mp3",
            },
            {
                "visibility": "public",
                "review_status": "draft",
                "title": _SECRET,
                "asset_relpath": "audio/draft-memory.mp3",
            },
        ],
    }


def _registry() -> dict[str, object]:
    return {
        "slug": "manfred",
        "raw_provider_response": _SECRET,
        "fliplink_publications": [
            {
                "id": "life-overview",
                "title": "Lebensueberblick",
                "audience": "public",
                "review_status": "published",
                "url": "/memorials/manfred/archive/life-overview",
                "token": _SECRET,
            },
            {
                "id": "family-letters",
                "title": _SECRET,
                "audience": "family",
                "review_status": "published",
                "url": "/memorials/manfred/archive/family-letters",
            },
            {
                "id": "draft-source",
                "title": _SECRET,
                "audience": "public",
                "review_status": "draft",
                "url": "https://provider.invalid/private",
            },
        ],
    }


def _walk_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [
            key for child in value.values() for key in _walk_keys(child)
        ]
    if isinstance(value, list):
        return [key for child in value for key in _walk_keys(child)]
    return []


def test_share_packet_is_public_only_recipient_free_and_unsent_for_both_channels() -> (
    None
):
    packet = build_memorial_share_packet(
        slug="manfred",
        public_origin="https://memorial.example.test/",
        memorial=_memorial(),
        archive_registry=_registry(),
        channels=["telegram", "whatsapp", "telegram"],
        include_archive=True,
        include_audio=True,
    )

    assert packet["state"] == "unsent"
    assert packet["sent"] is False
    assert packet["attempted"] is False
    assert packet["assets"] == [
        {
            "kind": "archive_document",
            "id": "life-overview",
            "title": "Lebensueberblick",
            "url": "https://memorial.example.test/memorials/manfred/archive/life-overview",
        },
        {
            "kind": "audio",
            "id": "audio/public-memory.mp3",
            "title": "Eine oeffentliche Erinnerung",
            "url": "https://memorial.example.test/memorials/files/manfred/audio/public-memory.mp3",
        },
    ]
    assert packet["disclosures"] == {
        "share": SHARE_DISCLOSURE,
        "correction": CORRECTION_DISCLOSURE,
    }
    assert packet["governance"] == {
        "operator_review_required": True,
        "delivery_permitted": False,
        "send_requested": False,
    }
    drafts = packet["drafts"]
    assert [draft["channel"] for draft in drafts] == ["whatsapp", "telegram"]
    assert all(draft["receipt"]["sent"] is False for draft in drafts)
    assert all(draft["receipt"]["attempted"] is False for draft in drafts)
    assert all(
        draft["receipt"]["reason"] == "operator_review_required" for draft in drafts
    )

    serialized = json.dumps(packet, sort_keys=True)
    assert _SECRET not in serialized
    forbidden_key_fragments = {
        "private",
        "raw",
        "provider",
        "consent",
        "token",
        "recipient",
        "chat_id",
    }
    assert not {
        key
        for key in _walk_keys(packet)
        if any(fragment in key.lower() for fragment in forbidden_key_fragments)
    }


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://memorial.example.test",
        "https://localhost",
        "https://127.0.0.1",
        "https://user:secret@memorial.example.test",
        "https://memorial.example.test/a/path",
        "javascript:alert(1)",
    ],
)
def test_share_packet_rejects_nonpublic_or_nonorigin_urls(origin: str) -> None:
    with pytest.raises(MemorialSharePacketError, match="public_origin"):
        build_memorial_share_packet(
            slug="manfred", public_origin=origin, memorial=_memorial()
        )


def test_share_packet_rejects_external_archive_and_traversing_audio_routes() -> None:
    external_registry = _registry()
    external_registry["fliplink_publications"] = [
        {
            "id": "external",
            "title": "External",
            "audience": "public",
            "review_status": "approved",
            "url": "https://archive-provider.example/document",
        }
    ]
    with pytest.raises(MemorialSharePacketError, match="share_route_not_internal"):
        build_memorial_share_packet(
            slug="manfred",
            public_origin="https://memorial.example.test",
            memorial=_memorial(),
            archive_registry=external_registry,
            include_archive=True,
        )

    unsafe_memorial = _memorial()
    unsafe_memorial["audio_clips"] = [
        {
            "visibility": "public",
            "approved": True,
            "title": "Unsafe",
            "asset_relpath": "../private/recording.mp3",
        }
    ]
    with pytest.raises(MemorialSharePacketError, match="share_audio_route_invalid"):
        build_memorial_share_packet(
            slug="manfred",
            public_origin="https://memorial.example.test",
            memorial=unsafe_memorial,
            include_audio=True,
        )


def test_share_packet_is_idempotent_across_input_ordering() -> None:
    memorial_a = _memorial()
    registry_a = _registry()
    first = build_memorial_share_packet(
        slug="manfred",
        public_origin="https://MEMORIAL.example.test/",
        memorial=memorial_a,
        archive_registry=registry_a,
        channels=["telegram", "whatsapp"],
        include_archive=True,
        include_audio=True,
    )
    memorial_b = dict(memorial_a)
    memorial_b["audio_clips"] = list(reversed(list(memorial_a["audio_clips"])))
    registry_b = dict(registry_a)
    registry_b["fliplink_publications"] = list(
        reversed(list(registry_a["fliplink_publications"]))
    )
    second = build_memorial_share_packet(
        slug="manfred",
        public_origin="https://memorial.example.test",
        memorial=memorial_b,
        archive_registry=registry_b,
        channels=["whatsapp", "telegram"],
        include_archive=True,
        include_audio=True,
    )

    assert first == second


def test_public_share_api_returns_governed_drafts_without_inferring_origin(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_memorial_share, "_load_memorial", lambda slug: _memorial()
    )
    monkeypatch.setattr(
        public_memorial_share,
        "_public_memorial_archive_registry",
        lambda slug: _registry(),
    )
    app = FastAPI()
    app.include_router(public_memorial_share.router)
    client = TestClient(app)

    missing_origin = client.post("/memorials/manfred/share-drafts", json={})
    assert missing_origin.status_code == 400
    assert missing_origin.json() == {"detail": "public_origin_required"}

    response = client.post(
        "/memorials/manfred/share-drafts",
        json={
            "public_origin": "https://memorial.example.test",
            "channels": ["telegram", "whatsapp"],
            "include_archive": True,
            "include_audio": True,
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [draft["channel"] for draft in response.json()["drafts"]] == [
        "whatsapp",
        "telegram",
    ]
    assert all(
        draft["receipt"]["state"] == "unsent" for draft in response.json()["drafts"]
    )


def test_share_packet_cli_builds_both_channel_receipts_without_network(
    tmp_path: Path, capsys
) -> None:
    memorial_path = tmp_path / "memorial.json"
    registry_path = tmp_path / "archive_registry.json"
    memorial_path.write_text(json.dumps(_memorial()), encoding="utf-8")
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")

    exit_code = share_cli.main(
        [
            "manfred",
            "--public-origin",
            "https://memorial.example.test",
            "--memorial-file",
            str(memorial_path),
            "--archive-registry-file",
            str(registry_path),
            "--include-archive",
            "--include-audio",
        ]
    )

    assert exit_code == 0
    packet = json.loads(capsys.readouterr().out)
    assert [draft["channel"] for draft in packet["drafts"]] == ["whatsapp", "telegram"]
    assert packet["sent"] is False
    assert packet["governance"]["delivery_permitted"] is False


def test_share_packet_cli_rejects_unsafe_origin_without_echoing_source(
    tmp_path: Path, capsys
) -> None:
    memorial_path = tmp_path / "memorial.json"
    memorial_path.write_text(json.dumps(_memorial()), encoding="utf-8")

    exit_code = share_cli.main(
        [
            "manfred",
            "--public-origin",
            "http://127.0.0.1:8090",
            "--memorial-file",
            str(memorial_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.err) == {"ok": False, "error": "public_origin_invalid"}
    assert _SECRET not in captured.err
