from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import public_tours


def _write_tour(
    root: Path,
    *,
    directory_slug: str,
    manifest_slug: str | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    bundle = root / directory_slug
    bundle.mkdir(parents=True)
    rendered = {
        "slug": manifest_slug or directory_slug,
        "display_title": "Reviewed Vienna apartment",
        "facts": {},
        "scenes": [],
        **dict(payload or {}),
    }
    (bundle / "tour.json").write_text(json.dumps(rendered), encoding="utf-8")
    return rendered


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


@pytest.mark.parametrize(
    "slug",
    [
        "runtime-reconstruction-smoke",
        "runtime_service_direct_proof",
        "debug-reconstruction-browser-tour",
        "probe.viewer.ready",
        "private-showcase-girschele-flat",
        "test-reconstruction-fixture",
        "bridge-direct-probe",
        "check-viewer",
        "generated-reconstruction-expanded-debug",
        "manual-viewer-debug",
        "repro-tour",
        "viewer-probe",
    ],
)
def test_operational_slug_quarantine_covers_only_known_artifact_families(slug: str) -> None:
    assert public_tours._public_tour_slug_is_quarantined(slug) is True


@pytest.mark.parametrize(
    "slug",
    [
        "private-garden-apartment-layout-first-abc123",
        "runtime-views-apartment-layout-first-abc123",
        "debugger-loft-layout-first-abc123",
        "probeweg-12-city-apartment-layout-first-abc123",
        "checkered-viewer-apartment-layout-first-abc123",
        "reproduction-tour-apartment-layout-first-abc123",
    ],
)
def test_natural_language_listing_slugs_are_not_quarantined(slug: str) -> None:
    assert public_tours._public_tour_slug_is_quarantined(slug) is False


@pytest.mark.parametrize(
    ("directory_slug", "manifest_slug"),
    [
        ("runtime-reconstruction-smoke", "reviewed-apartment-layout-first-abc123"),
        ("reviewed-apartment-layout-first-abc123", "manual-viewer-debug"),
    ],
)
def test_requested_or_manifest_operational_slug_fails_closed_for_page_json_and_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_slug: str,
    manifest_slug: str,
) -> None:
    root = tmp_path / "public-tours"
    _write_tour(root, directory_slug=directory_slug, manifest_slug=manifest_slug)
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)

    with pytest.raises(HTTPException) as payload_error:
        public_tours.public_tour_payload(directory_slug)
    assert payload_error.value.status_code == 404
    assert payload_error.value.detail == "tour_not_found"

    with pytest.raises(HTTPException) as asset_error:
        public_tours._asset_file(directory_slug, "preview.jpg")
    assert asset_error.value.status_code == 404
    assert asset_error.value.detail == "tour_not_found"

    page = public_tours.public_tour_page(
        directory_slug,
        _request(f"/tours/{directory_slug}"),
        container=object(),
    )
    assert page.status_code == 404


@pytest.mark.parametrize(
    "slug",
    [
        "private-garden-apartment-layout-first-abc123",
        "runtime-views-apartment-layout-first-abc123",
        "debugger-loft-layout-first-abc123",
    ],
)
def test_natural_language_listing_slugs_remain_loadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> None:
    root = tmp_path / "public-tours"
    expected = _write_tour(root, directory_slug=slug)
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)

    assert public_tours._load_tour(slug) == expected


@pytest.mark.parametrize(
    ("facts", "address"),
    [
        ({"street_address": "Simmeringer Hauptstraße 153-155"}, "Simmeringer Hauptstraße 153-155"),
        (
            {"listing_research_snapshot": {"exact_address": "Teuffenbachstraße 24/4/15"}},
            "Teuffenbachstraße 24/4/15",
        ),
        ({"geocoding": {"geocoded_address": "Sparkassegasse 28"}}, "Sparkassegasse 28"),
        ({"source": {"address_line_1": "Examplegasse 42"}}, "Examplegasse 42"),
        ({"source": {"addressLine2": "Examplegasse 42"}}, "Examplegasse 42"),
    ],
)
def test_nested_credible_exact_address_variants_are_detected(
    facts: dict[str, object],
    address: str,
) -> None:
    payload = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": address,
        "facts": facts,
        "scenes": [],
    }

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug="reviewed-apartment-layout-first-abc123",
    ) is True


def test_exact_address_street_line_cannot_hide_inside_full_geocoded_value() -> None:
    payload = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": "Examplegasse 42",
        "facts": {"geocoded_address": "Examplegasse 42, 1010 Vienna, Austria"},
        "scenes": [],
    }

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=str(payload["slug"]),
    ) is True


@pytest.mark.parametrize(
    "surface",
    [
        "requested_slug",
        "manifest_slug",
        "display_title",
        "title",
        "tour_title",
        "scene_label",
        "scene_url",
        "listing_url",
        "hosted_url",
        "source_url",
    ],
)
def test_exact_address_conflict_covers_every_public_location_surface(surface: str) -> None:
    address = "Simmeringer Hauptstraße 153-155"
    encoded_address = "Simmeringer%20Hauptstra%C3%9Fe%20153-155"
    payload: dict[str, object] = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": "Reviewed Vienna apartment",
        "title": "Reviewed Vienna apartment",
        "tour_title": "Reviewed Vienna apartment",
        "facts": {"street_address": address},
        "scenes": [{"label": "Living room", "source_url": "https://media.example.test/living-room"}],
        "listing_url": "https://listing.example.test/apartment",
        "hosted_url": "https://tours.example.test/apartment",
        "source_virtual_tour_url": "https://viewer.example.test/apartment",
    }
    requested_slug = "reviewed-apartment-layout-first-abc123"
    if surface == "requested_slug":
        requested_slug = "simmeringer-hauptstrae-153-155-layout-first-abc123"
    elif surface == "manifest_slug":
        payload["slug"] = "simmeringer-hauptstrae-153-155-layout-first-abc123"
    elif surface in {"display_title", "title", "tour_title"}:
        payload[surface] = address
    elif surface == "scene_label":
        payload["scenes"] = [{"label": address}]
    elif surface == "scene_url":
        payload["scenes"] = [{"source_url": f"https://media.example.test/{encoded_address}"}]
    elif surface == "source_url":
        payload["source_virtual_tour_url"] = f"https://viewer.example.test/{encoded_address}"
    else:
        payload[surface] = f"https://listing.example.test/{encoded_address}"

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=requested_slug,
    ) is True


def test_exact_location_requires_literal_true_override() -> None:
    payload: dict[str, object] = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": "Examplegasse 42",
        "facts": {"street_address": "Examplegasse 42"},
        "scenes": [],
        "public_exact_location_allowed": "true",
    }

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=str(payload["slug"]),
    ) is True

    payload["public_exact_location_allowed"] = True
    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=str(payload["slug"]),
    ) is False


@pytest.mark.parametrize(
    "facts",
    [
        {"exact_address": "1010 Vienna"},
        {"exact_address": "St. Pölten 3100"},
        {"geocoded_address": "Vienna, Austria"},
        {"contact": {"street_address": "Examplegasse 42"}},
        {"organisation": {"address_line_1": "Examplegasse 42"}},
    ],
)
def test_city_only_and_non_property_addresses_do_not_false_positive(facts: dict[str, object]) -> None:
    payload = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": "Examplegasse 42 apartment in 1010 Vienna",
        "facts": facts,
        "scenes": [],
    }

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=str(payload["slug"]),
    ) is False


def test_number_first_abbreviated_street_remains_credible() -> None:
    payload = {
        "slug": "reviewed-apartment-layout-first-abc123",
        "display_title": "123 Main St",
        "facts": {"street_address": "123 Main St, Vienna"},
        "scenes": [],
    }

    assert public_tours._public_tour_has_exact_location_conflict(
        payload,
        requested_slug=str(payload["slug"]),
    ) is True


def test_exact_location_conflict_is_enforced_by_common_tour_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public-tours"
    slug = "reviewed-apartment-layout-first-abc123"
    payload = _write_tour(
        root,
        directory_slug=slug,
        payload={
            "display_title": "Examplegasse 42",
            "facts": {"street_address": "Examplegasse 42"},
        },
    )
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)

    with pytest.raises(HTTPException) as conflict:
        public_tours._load_tour(slug)
    assert conflict.value.status_code == 404
    assert conflict.value.detail == "tour_not_found"

    payload["public_exact_location_allowed"] = True
    (root / slug / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    assert public_tours._load_tour(slug) == payload
