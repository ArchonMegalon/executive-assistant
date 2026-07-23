from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes.memorial_memory_room import render_memorial_memory_room


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_ENABLE_PUBLIC_MEMORIALS"] = "1"
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    from app.api.app import create_app

    return TestClient(create_app(), base_url="https://myexternalbrain.com")


def _memorial_payload() -> dict[str, object]:
    return {
        "slug": "manfred",
        "person_name": 'Manfred <img src=x onerror="window.personPwned=1">',
        "title": "Erinnerungen an Manfred",
        "subtitle": "Eine ruhige Erinnerungsseite.",
        "memory_cards": [
            {
                "public": True,
                "visibility": "public",
                "title": '<script>window.roomPwned=1</script>Freigegebene Spur',
                "body": "Ein freigegebener Erinnerungstext.",
                "source_label": "Familienfreigabe",
            },
            {
                "public": False,
                "visibility": "private",
                "title": "PRIVATE_MEMORY_MUST_NOT_ESCAPE",
                "body": "PRIVATE_BODY_MUST_NOT_ESCAPE",
            },
        ],
        "external_sources": [
            {
                "public": True,
                "approved": True,
                "label": "Provider URL must not enter the room",
                "url": "https://provider.invalid/private-tour",
            }
        ],
    }


def test_memory_room_route_is_first_party_sanitized_and_hardened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorial_surface

    monkeypatch.setattr(
        public_memorial_surface,
        "_load_public_surface_memorial",
        lambda slug: _memorial_payload(),
    )
    client = _client()

    response = client.get("/memorials/manfred/memory-room")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "connect-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"].startswith("microphone=()")
    assert "set-cookie" not in response.headers
    assert '<html lang="de">' in response.text
    assert "Symbolischer Raum" in response.text
    assert "keine Rekonstruktion eines realen Ortes" in response.text
    assert "Freigegebene Spur" in response.text
    assert "PRIVATE_MEMORY_MUST_NOT_ESCAPE" not in response.text
    assert "PRIVATE_BODY_MUST_NOT_ESCAPE" not in response.text
    assert "provider.invalid" not in response.text
    assert "&lt;script&gt;window.roomPwned=1&lt;/script&gt;" in response.text
    assert "<script>window.roomPwned=1</script>" not in response.text
    assert "<img src=x" not in response.text
    assert 'onerror="window.personPwned=1"' not in response.text
    assert "script src=" not in response.text
    assert "<iframe" not in response.text
    assert "fetch(" not in response.text
    assert "WebSocket" not in response.text
    assert "localStorage" not in response.text

    head = client.head("/memorials/manfred/memory-room")
    assert head.status_code == 200
    assert head.content == b""
    assert "set-cookie" not in head.headers


def test_memory_room_renderer_is_bounded_and_keeps_a_no_js_reading_path() -> None:
    payload = {
        "person_name": "Manfred",
        "memory_cards": [
            {
                "title": f"Spur {index}",
                "body": "x" * 900,
                "source_label": "Freigegeben",
            }
            for index in range(20)
        ],
    }

    rendered = render_memorial_memory_room(payload, slug="manfred")

    assert rendered.count('class="memory-entry"') == 12
    assert "Spur 11" in rendered
    assert "Spur 12" not in rendered
    assert "x" * 520 not in rendered
    assert "<noscript>" in rendered
    assert "Alle freigegebenen Erinnerungen bleiben vollständig" in rendered
    assert 'touch-action:pan-y pinch-zoom' in rendered
    assert "requestAnimationFrame" not in rendered
    assert "setInterval" not in rendered
    assert "infinite" not in rendered


def test_manfred_page_keeps_memory_room_outside_conversation_only_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorial_surface

    monkeypatch.setattr(
        public_memorial_surface,
        "_load_public_surface_memorial",
        lambda slug: _memorial_payload(),
    )
    monkeypatch.setattr(public_memorial_surface, "_load_private_profile", lambda slug: {})
    response = _client().get("/memorials/manfred")

    assert response.status_code == 200
    assert 'data-public-memorial-surface="conversation-only"' in response.text
    assert 'id="memorial-conversation-region"' in response.text
    assert 'href="/memorials/manfred/memory-room"' not in response.text
    assert "Freigegebene Spuren in 3D" not in response.text
    assert "keine Rekonstruktion eines realen Ortes" not in response.text


def test_memory_room_transport_and_error_paths_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorial_surface

    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setattr(
        public_memorial_surface,
        "_load_public_surface_memorial",
        lambda slug: _memorial_payload(),
    )
    client = _client()

    redirect = client.get(
        "http://myexternalbrain.com/memorials/manfred/memory-room?from=memorial",
        follow_redirects=False,
    )
    assert redirect.status_code == 308
    assert redirect.headers["location"] == (
        "https://myexternalbrain.com/memorials/manfred/memory-room?from=memorial"
    )

    rejected = client.get("https://attacker.example/memorials/manfred/memory-room")
    assert rejected.status_code == 421

    def _missing(slug: str) -> dict[str, object]:
        raise HTTPException(status_code=404, detail="PRIVATE_PATH_MUST_NOT_ESCAPE")

    monkeypatch.setattr(
        public_memorial_surface,
        "_load_public_surface_memorial",
        _missing,
    )
    missing = client.get("/memorials/missing/memory-room")
    assert missing.status_code == 404
    assert "PRIVATE_PATH_MUST_NOT_ESCAPE" not in missing.text
    assert "Diese Seite ist gerade nicht erreichbar" in missing.text
    assert missing.headers["x-frame-options"] == "DENY"
