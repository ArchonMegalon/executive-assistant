from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.routes import property_surface_boundary
from app.api.routes.landing_view_models import property_workspace_payload
from app.services import public_branding

_EA_ROOT = Path(__file__).resolve().parents[1]


def _request(path: str, query: str = "", *, host: str = "myexternalbrain.com") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path, query=query, hostname=host), headers={"host": host})


def test_ea_property_app_surface_redirects_to_propertyquarry() -> None:
    with patch.object(property_surface_boundary, "request_brand", return_value={"key": "ea"}):
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/properties", "run_id=abc123")
        )

    assert response is not None
    assert response.status_code == 307
    assert response.headers["location"] == "https://propertyquarry.com/app/properties?run_id=abc123"
    assert response.headers["X-EA-Product-Boundary"] == "propertyquarry"


def test_myexternalbrain_stays_ea_even_when_propertyquarry_default_brand_is_enabled() -> None:
    with patch.dict(os.environ, {"PROPERTYQUARRY_DEFAULT_BRAND": "1"}, clear=False):
        assert public_branding.brand_from_hostname("myexternalbrain.com")["key"] == "ea"
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/properties", "run_id=abc123", host="myexternalbrain.com")
        )

    assert response is not None
    assert response.status_code == 307
    assert response.headers["location"] == "https://propertyquarry.com/app/properties?run_id=abc123"


def test_myexternalbrain_stays_ea_when_ea_hosts_env_omits_production_domain() -> None:
    with patch.dict(
        os.environ,
        {
            "EA_PUBLIC_HOSTS": "localhost,127.0.0.1",
            "PROPERTYQUARRY_DEFAULT_BRAND": "1",
        },
        clear=False,
    ):
        assert public_branding.brand_from_hostname("myexternalbrain.com")["key"] == "ea"
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/properties", "run_id=abc123", host="myexternalbrain.com")
        )

    assert response is not None
    assert response.status_code == 307
    assert response.headers["location"] == "https://propertyquarry.com/app/properties?run_id=abc123"
    assert response.headers["X-EA-Product-Boundary"] == "propertyquarry"


def test_propertyquarry_default_brand_still_supports_unmapped_preview_hosts() -> None:
    with patch.dict(os.environ, {"PROPERTYQUARRY_DEFAULT_BRAND": "1"}, clear=False):
        assert public_branding.brand_from_hostname("preview.internal")["key"] == "propertyquarry"


def test_ea_property_subsurface_redirects_to_propertyquarry() -> None:
    with patch.object(property_surface_boundary, "request_brand", return_value={"key": "ea"}):
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/research/candidate-123", "investment=1")
        )

    assert response is not None
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "https://propertyquarry.com/app/research/candidate-123?investment=1"
    )


def test_property_api_surface_is_not_served_from_ea_brand() -> None:
    with patch.object(property_surface_boundary, "request_brand", return_value={"key": "ea"}):
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/api/signals/property/search/run")
        )

    assert response is not None
    assert response.status_code == 404
    assert response.headers["X-EA-Product-Boundary"] == "propertyquarry"


def test_propertyquarry_brand_keeps_property_surfaces_available() -> None:
    with patch.object(property_surface_boundary, "request_brand", return_value={"key": "propertyquarry"}):
        response = property_surface_boundary.property_surface_boundary_response(
            _request("/app/properties", "run_id=abc123")
        )

    assert response is None


def test_property_setup_header_no_longer_repeats_country_before_brief_fields() -> None:
    template = (_EA_ROOT / "app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    view_model = (_EA_ROOT / "app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "<span>Market</span>" not in template
    assert "<span>Country</span>" not in template
    assert "Which providers this country unlocks" not in view_model
    assert "Country bundle" not in view_model


def test_property_workspace_payload_keeps_propertyquarry_brand_renderable() -> None:
    payload = property_workspace_payload(
        "properties",
        status={"workspace": {}, "channels": {}},
        property_state={"preferences": {}},
    )

    assert "Country" not in [str(row.get("label") or "") for row in payload["stats"]]
    assert payload["hero_highlights"][0]["label"] == "Posture"
    assert payload["hero_highlights"][0]["value"] == "Search"
