from __future__ import annotations

from app.services.property_market_catalog import (
    default_language_for_country,
    default_platforms_for_country,
    generated_source_specs,
    language_label,
    listing_mode_label,
    normalize_property_search_preferences,
    property_type_label,
    provider_options,
    provider_listing_markers_for_host,
)


def test_provider_options_are_filtered_by_country() -> None:
    germany = provider_options(country_code="DE")

    assert any(row["value"] == "immoscout_de" for row in germany)
    assert any(row["value"] == "immowelt" for row in germany)
    assert all("Germany" in str(row.get("description") or "") for row in germany)


def test_normalize_property_search_preferences_defaults_country_and_language() -> None:
    payload = normalize_property_search_preferences({"location_query": "Berlin"})

    assert payload["country_code"] == "AT"
    assert payload["region_code"] == ""
    assert payload["language_code"] == "de"
    assert payload["listing_mode"] == "rent"
    assert payload["property_type"] == "any"


def test_generated_source_specs_use_country_platform_defaults() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Berlin",
            "keywords": "lift balcony",
        },
        selected_platforms=(),
        principal_id="exec-property-de",
        default_person_id="self",
        max_results=4,
    )

    assert tuple(row["platform"] for row in specs[:2])[:1]
    assert specs[0]["country_code"] == "DE"
    assert specs[0]["listing_mode"] == "buy"
    assert "Berlin" in str(specs[0]["label"])
    assert "berlin" in str(specs[0]["url"]).lower()


def test_market_labels_are_human_readable() -> None:
    assert language_label("fr", country_code="FR") == "Français"
    assert listing_mode_label("buy") == "Buy"
    assert property_type_label("house") == "House"


def test_generated_source_specs_build_provider_specific_market_urls() -> None:
    uk_specs = generated_source_specs(
        preferences={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "London",
            "min_rooms": 3,
            "max_price_eur": 950000,
        },
        selected_platforms=("rightmove", "zoopla"),
        principal_id="exec-property-uk",
        default_person_id="self",
        max_results=3,
    )
    france_specs = generated_source_specs(
        preferences={
            "country_code": "FR",
            "language_code": "fr",
            "listing_mode": "rent",
            "location_query": "Paris",
            "min_rooms": 2,
        },
        selected_platforms=("bienici",),
        principal_id="exec-property-fr",
        default_person_id="self",
        max_results=3,
    )
    netherlands_specs = generated_source_specs(
        preferences={
            "country_code": "NL",
            "language_code": "nl",
            "listing_mode": "buy",
            "location_query": "Amsterdam",
            "property_type": "house",
        },
        selected_platforms=("funda",),
        principal_id="exec-property-nl",
        default_person_id="self",
        max_results=3,
    )

    assert "searchLocation=London" in str(uk_specs[0]["url"])
    assert "q=London" in str(uk_specs[1]["url"])
    assert "price_max=950000" in str(uk_specs[1]["url"])
    assert "bienici.com/recherche/location/paris" in str(france_specs[0]["url"]).lower()
    assert "minRooms=2" in str(france_specs[0]["url"])
    assert "funda.nl/zoeken/koop/amsterdam/" in str(netherlands_specs[0]["url"]).lower()
    assert "object_type=house" in str(netherlands_specs[0]["url"])


def test_default_platforms_for_country_are_stable() -> None:
    assert default_platforms_for_country("UK") == ("rightmove", "zoopla", "onthemarket")
    assert default_platforms_for_country("PT") == ("idealista_pt", "imovirtual", "casa_sapo")
    assert default_language_for_country("SE") == "sv"


def test_provider_listing_markers_follow_provider_host() -> None:
    markers = provider_listing_markers_for_host("www.realtor.com")

    assert "/realestateandhomes-detail/" in markers


def test_generated_source_specs_cover_new_country_bundles() -> None:
    portugal_specs = generated_source_specs(
        preferences={
            "country_code": "PT",
            "language_code": "pt",
            "listing_mode": "buy",
            "location_query": "Lisbon",
        },
        selected_platforms=("idealista_pt", "imovirtual"),
        principal_id="exec-property-pt",
        default_person_id="self",
        max_results=3,
    )
    ireland_specs = generated_source_specs(
        preferences={
            "country_code": "IE",
            "language_code": "en",
            "listing_mode": "rent",
            "location_query": "Dublin",
        },
        selected_platforms=("daft_ie",),
        principal_id="exec-property-ie",
        default_person_id="self",
        max_results=3,
    )
    australia_specs = generated_source_specs(
        preferences={
            "country_code": "AU",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "Sydney",
            "min_rooms": 2,
        },
        selected_platforms=("domain_au",),
        principal_id="exec-property-au",
        default_person_id="self",
        max_results=3,
    )

    assert "idealista.pt/en/comprar-casas/lisbon/" in str(portugal_specs[0]["url"]).lower()
    assert "imovirtual.com" in str(portugal_specs[1]["url"]).lower()
    assert "daft.ie/property-for-rent/dublin" in str(ireland_specs[0]["url"]).lower()
    assert "domain.com.au" in str(australia_specs[0]["url"]).lower()
    assert "suburb=Sydney" in str(australia_specs[0]["url"])
