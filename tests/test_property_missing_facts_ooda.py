from app.api.routes.landing import _property_packet_missing_rows, _property_rooms_display
from app.product.service import _property_enrich_missing_fact_research, _property_justiz_edikte_facts


def test_missing_rooms_with_floorplan_creates_ooda_research_item() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True, "floorplan_count": 1, "sale_channel": "judicial_auction"},
        property_url="https://edikte2.justiz.gv.at/example",
        title="Auction apartment",
        summary="Good floorplan evidence but no structured room count.",
    )

    assert facts["rooms_label"] == "Rooms under research"
    assert facts["rooms_research_status"] == "queued_missing_fact_ooda"
    assert facts["missing_facts_json"] == ["rooms"]
    research = facts["missing_fact_research"]
    assert research["status"] == "queued"
    assert research["items"][0]["field"] == "rooms"
    assert research["items"][0]["ooda"]["act"].startswith("Queue missing-fact research")
    assert _property_rooms_display(facts) == "Rooms under research"


def test_missing_rooms_ooda_fills_medium_confidence_room_count_from_text() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True, "floorplan_count": 1},
        property_url="https://example.test/listing",
        title="3 Zimmer Wohnung mit Grundriss",
        summary="Wohnung mit Balkon.",
    )

    assert facts["rooms"] == 3
    assert facts["rooms_label"] == "3 rooms"
    assert facts["rooms_research_status"] == "filled_by_missing_fact_ooda"
    assert facts["missing_fact_research"]["status"] == "completed"
    assert facts["missing_fact_research"]["items"][0]["status"] == "filled"
    assert "missing_facts_json" not in facts


def test_justiz_edikte_parser_extracts_rooms_when_text_contains_room_fact() -> None:
    facts = _property_justiz_edikte_facts(
        "https://edikte2.justiz.gv.at/edikte/ex/example",
        "<html><title>Edikt</title></html>",
        "Schätzwert EUR 300.000. Die Wohnung hat 4 Zimmer und 91 m² Wohnfläche.",
    )

    assert facts["provider_channel"] == "justiz_edikte_at"
    assert facts["rooms"] == 4
    assert facts["rooms_label"] == "4 rooms"


def test_packet_missing_rows_surface_missing_fact_ooda() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True},
        property_url="https://example.test/floorplan.zip",
        title="Floorplan bundle",
        summary="No structured room count.",
    )

    rows = _property_packet_missing_rows(facts=facts, preferences={})

    assert any(row["title"] == "Rooms" and row["tag"] == "OODA" for row in rows)
