from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_avatar_readiness_warns_on_honest_portrait_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.verify_memorial_video_call_avatar_ready as avatar_ready

    payload = {
        "video_call_avatar": {
            "enabled": False,
            "kind": "portrait",
            "provider_label": "VidBoard noch nicht live",
            "title": "Manfred Hoza",
            "detail": "Der Video-Avatar ist noch nicht freigegeben. Bis dahin zeigen wir nur die Portraitvorschau.",
            "asset_url": "",
            "poster_url": "",
        }
    }
    html = """
    <html>
      <body>
        <strong>Video Call mit Manfred Hoza</strong>
        <span>Prelive-Vorschau. Kamera ist optional. VidBoard noch nicht live.</span>
        <span id="memorial-video-call-avatar-detail">Der Video-Avatar ist noch nicht freigegeben. Bis dahin zeigen wir nur die Portraitvorschau.</span>
      </body>
    </html>
    """

    def fake_load_public_json(*, base_url: str, slug: str) -> tuple[int, dict[str, object]]:
        return 200, payload

    def fake_load_page_html(*, base_url: str, slug: str) -> tuple[int, str]:
        return 200, html

    monkeypatch.setattr(avatar_ready, "_load_public_json", fake_load_public_json)
    monkeypatch.setattr(avatar_ready, "_load_page_html", fake_load_page_html)

    report = avatar_ready.run_check(base_url="https://example.test", slug="manfred")

    assert report.status == "warn"
    assert any(item.code == "avatar_video_not_published" for item in report.findings)


def test_avatar_readiness_passes_when_public_video_asset_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.verify_memorial_video_call_avatar_ready as avatar_ready

    payload = {
        "video_call_avatar": {
            "enabled": True,
            "kind": "video",
            "provider_label": "VidBoard Avatar bereit",
            "title": "Manfred Hoza als Avatar",
            "detail": "VidBoard-Clip ist fuer den Video Call eingebunden.",
            "asset_url": "/memorials/files/manfred/video/manfred-avatar.mp4",
            "poster_url": "/memorials/files/manfred/video/manfred-avatar-poster.png",
        }
    }
    html = """
    <html>
      <body>
        <span>VidBoard Avatar bereit</span>
        <video id="memorial-video-call-avatar-video" src="/memorials/files/manfred/video/manfred-avatar.mp4" poster="/memorials/files/manfred/video/manfred-avatar-poster.png"></video>
      </body>
    </html>
    """

    def fake_load_public_json(*, base_url: str, slug: str) -> tuple[int, dict[str, object]]:
        return 200, payload

    def fake_load_page_html(*, base_url: str, slug: str) -> tuple[int, str]:
        return 200, html

    def fake_remote_asset(url: str) -> tuple[int, int]:
        return 200, 128

    monkeypatch.setattr(avatar_ready, "_load_public_json", fake_load_public_json)
    monkeypatch.setattr(avatar_ready, "_load_page_html", fake_load_page_html)
    monkeypatch.setattr(avatar_ready, "_check_remote_asset", fake_remote_asset)

    report = avatar_ready.run_check(base_url="https://example.test", slug="manfred")

    assert report.status == "pass"
    assert any(item.code == "avatar_asset_available" for item in report.findings)

