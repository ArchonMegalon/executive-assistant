from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.requests import Request

from app.api.routes import public_tours


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [(b"host", b"tours.example.test")],
            "client": ("127.0.0.1", 49152),
            "server": ("tours.example.test", 443),
        }
    )


def _write_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenes: list[dict[str, object]] | None = None,
) -> tuple[str, dict[str, object]]:
    slug = "reviewed-listing-without-released-scenes-layout-first-abc123"
    root = tmp_path / "public-tours"
    bundle = root / slug
    bundle.mkdir(parents=True)
    payload: dict[str, object] = {
        "slug": slug,
        "display_title": "Reviewed Vienna apartment",
        "title": "Reviewed Vienna apartment",
        "facts": {
            "rooms": 2,
            "area_sqm": 61,
            "total_rent_eur": 1490,
        },
        "scenes": list(scenes or []),
    }
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    return slug, payload


def test_no_released_scenes_render_truthful_polished_fallback() -> None:
    source = public_tours._tour_html(
        {
            "slug": "reviewed-listing-layout-first-abc123",
            "display_title": "Reviewed Vienna apartment",
            "facts": {"rooms": 2, "area_sqm": 61, "total_rent_eur": 1490},
            "scenes": [],
            "_tour_media_disclosure": "No tour media has passed public release review for this listing.",
        },
        hostname="tours.example.test",
    )

    assert 'data-media-state="unreleased"' in source
    assert "Tour media is awaiting release review" in source
    assert "No released scenes" in source
    assert "No tour media has passed public release review" in source
    assert "Open 3D Tour" not in source
    assert "<iframe" not in source
    assert "<video" not in source


def test_page_with_no_scenes_is_200_semantic_and_does_not_claim_released_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug, _payload = _write_bundle(tmp_path, monkeypatch)

    response = public_tours.public_tour_page(
        slug,
        _request(f"/tours/{slug}"),
        container=object(),
    )
    source = response.body.decode("utf-8")

    assert response.status_code == 200
    assert '<main id="main-content">' in source
    assert 'data-media-state="unreleased"' in source
    assert "No tour media has passed public release review" in source
    assert "private, test, or source artifacts" in source
    assert "Open 3D Tour" not in source


def test_scene_removed_by_public_asset_policy_uses_same_safe_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_source = "https://private-source.example.test/unreleased-panorama.jpg"
    slug, _payload = _write_bundle(
        tmp_path,
        monkeypatch,
        scenes=[
            {
                "name": "Unreleased source panorama",
                "source_url": private_source,
                "role": "panorama",
            }
        ],
    )

    response = public_tours.public_tour_page(
        slug,
        _request(f"/tours/{slug}"),
        container=object(),
    )
    source = response.body.decode("utf-8")

    assert response.status_code == 200
    assert 'data-media-state="unreleased"' in source
    assert private_source not in source
    assert "No released scenes" in source


def test_scene_less_released_viewer_keeps_opaque_origin_sandbox() -> None:
    source = public_tours._tour_html(
        {
            "slug": "reviewed-listing-layout-first-abc123",
            "display_title": "Reviewed Vienna apartment",
            "facts": {},
            "scenes": [],
            "_released_generated_viewer_url": (
                "/tours/viewer/reviewed-listing-layout-first-abc123/generated-reconstruction/viewer.html"
            ),
            "_tour_media_disclosure": "Released generated reconstruction; not a captured provider scan.",
        },
        hostname="tours.example.test",
    )

    assert 'data-media-state="released"' in source
    assert "Released interactive reconstruction" in source
    assert 'sandbox="allow-scripts"' in source
    assert "allow-same-origin" not in source
    assert "No released scenes" not in source
