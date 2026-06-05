from __future__ import annotations

from app.api.routes.public_tours import _public_tour_host_brand_label


def test_propertyquarry_tour_brand_label_is_host_specific() -> None:
    assert _public_tour_host_brand_label("propertyquarry.com") == "PropertyQuarry"
    assert _public_tour_host_brand_label("www.propertyquarry.com") == "PropertyQuarry"
    assert _public_tour_host_brand_label("myexternalbrain.com") == "My External Brain"
    assert _public_tour_host_brand_label("example.com", fallback="Custom Brand") == "Custom Brand"
