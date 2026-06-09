from __future__ import annotations

from tests.smoke_runtime_api_support import build_client as _client


def test_health_live_stays_simple_without_memorial_probe(monkeypatch) -> None:
    monkeypatch.delenv("EA_HEALTHCHECK_MEMORIAL_SLUG", raising=False)
    client = _client(storage_backend="memory")
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_health_live_includes_memorial_probe_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("EA_HEALTHCHECK_MEMORIAL_SLUG", "manfred")
    from app.api.routes import health

    monkeypatch.setattr(
        health,
        "_probe_public_memorial_surface",
        lambda slug: {"slug": slug, "voice_plugin": "unmixr_clone", "audio_clip_count": 3, "elapsed_ms": 8.4},
    )
    client = _client(storage_backend="memory")
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {
        "status": "live",
        "memorial_slug": "manfred",
        "memorial_voice_plugin": "unmixr_clone",
        "memorial_audio_clip_count": "3",
        "memorial_elapsed_ms": "8.4",
    }
