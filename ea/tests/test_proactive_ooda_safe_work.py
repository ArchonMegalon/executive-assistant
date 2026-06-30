from __future__ import annotations

from app.services import proactive_ooda_safe_work


def test_flat_property_search_blocker_blocks_non_provider_context() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": False,
            "provider_query_terms": ("Wohnung Wien",),
            "all_text": ("Suche", "eine", "Wohnung", "in", "Wien"),
            "location_context": {"city_terms": ["Wien"]},
        },
        queries=("Wohnung Wien",),
    )

    assert blockers == ["flat_search_disabled"]


def test_flat_property_search_blocker_stays_blocked_without_toggle() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("Wohnung Wien",),
            "all_text": ("Suche", "eine", "Wohnung", "in", "Wien"),
            "location_context": {"city_terms": ["Wien"]},
        },
        queries=("Wohnung Wien",),
    )

    assert blockers == ["flat_search_disabled"]


def test_flat_property_search_blocker_stays_blocked_for_flat_queries_without_any_queries() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": False,
            "provider_query_terms": ("wohnung",),
            "all_text": ("Wohnung",),
            "location_context": {"city_terms": ["Wien"]},
        },
        queries=(),
    )

    assert blockers == ["flat_search_disabled"]


def test_flat_property_search_blocker_allows_nonn_flat_room_context_when_no_flat_signal() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("rauchfangkehrer", "zimmerkamin", "abluftrohr"),
            "all_text": ("fit", "to", "request"),
            "location_context": {"city_terms": ["1200", "Wien"]},
        },
        queries=("Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr",),
    )

    assert blockers == ["provider_search_missing_locality_or_source_scope"]


def test_flat_property_search_blocker_allows_non_flat_wohnzimmer_context() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("wohnzimmer", "anstrich", "tapete"),
            "all_text": ("wir", "suche", "eine", "Lösung", "für", "mein", "Wohnzimmer"),
            "location_context": {"city_terms": ["Wien"]},
            "target_hosts": ("example.com",),
        },
        queries=("Wohnzimmer renovieren in Wien",),
    )

    assert blockers == []


def test_flat_property_search_blocker_allows_generic_purchase_context() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("blumen kaufen",),
            "all_text": ("kauf", "blumen", "für", "meine", "frau"),
            "location_context": {"city_terms": ["Wien"]},
            "target_hosts": ("example.com",),
        },
        queries=("Blumen kaufen in Wien",),
    )

    assert blockers == []


def test_flat_property_search_blocker_allows_recording_studio_context() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("recording studio",),
            "all_text": ("book", "a", "recording", "studio"),
            "location_context": {"city_terms": ["Vienna"]},
            "target_hosts": ("example.com",),
        },
        queries=("Recording studio Vienna",),
    )

    assert blockers == []


def test_flat_property_search_blocker_blocks_house_purchase_context() -> None:
    blockers = proactive_ooda_safe_work._flat_provider_search_blockers(
        context={
            "provider_discovery_relevant": True,
            "provider_query_terms": ("haus kaufen wien",),
            "all_text": ("suche", "haus", "kaufen", "wien"),
            "location_context": {"city_terms": ["Wien"]},
        },
        queries=("Haus kaufen Wien",),
    )

    assert blockers == ["flat_search_disabled"]


def test_flat_property_search_does_not_fetch_network_candidates_when_disabled(
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    call_count = {"research_candidate_items": 0}

    def fail_if_called(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        call_count["research_candidate_items"] += 1
        return []

    monkeypatch.setattr(proactive_ooda_safe_work, "_research_candidate_items", fail_if_called)
    packet = {
        "packet_ref": "packet-flat-search-disabled",
        "approval": {"required": False},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-flat-search-disabled",
            "work_type": "research",
            "requested_outcome": "Research candidate options for a flat search.",
        },
        "stage": {
            "summary": "flat search request",
            "payload": {
                "research_query": "Suche mir bitte eine 2 Zimmer Wohnung in 1200 Wien",
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=True)

    assert call_count["research_candidate_items"] == 0
    assert result["status"] == "blocked_needs_research_input"
    assert result["shortlist"] == []
    assert result["execution_receipt"]["network_fetch_enabled"] is False
    issue_codes = {item["code"] for item in result["audit"]["issues"]}
    assert "flat_provider_search_blocked:flat_search_disabled" in issue_codes


def test_flat_property_search_disabled_by_global_kill_switch(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    call_count = {"fetch_page_check": 0}

    def fail_if_fetch_called(*_args: object, **_kwargs: object) -> dict[str, object]:
        call_count["fetch_page_check"] += 1
        return {
            "url": "",
            "url_hash": "",
            "reachable": True,
            "fetched_at": "",
            "final_url": "",
            "page_title": "",
            "content_type": "",
            "status_code": 200,
            "error_code": "",
            "contact_email": "",
            "contact_emails": [],
        }

    monkeypatch.setattr(proactive_ooda_safe_work, "_fetch_page_check", fail_if_fetch_called)
    packet = {
        "packet_ref": "packet-flat-search-disabled-by-switch",
        "approval": {"required": False},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-flat-search-disabled-by-switch",
            "work_type": "research",
            "requested_outcome": "Find flat options for Berlin.",
        },
        "stage": {
            "summary": "flat search request",
            "payload": {
                "research_query": "flat hunt in Berlin",
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=True)

    assert result["status"] == "blocked_needs_research_input"
    assert result["execution_receipt"]["network_fetch_enabled"] is False
    assert call_count["fetch_page_check"] == 0
