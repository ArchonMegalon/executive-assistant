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


def test_flat_property_search_drops_preexisting_candidate_material_when_disabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    packet = {
        "packet_ref": "packet-property-candidates-disabled",
        "approval": {"required": False},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-property-candidates-disabled",
            "work_type": "compare_options",
            "requested_outcome": "Research a shortlist and stage one reversible option for review.",
        },
        "stage": {
            "summary": "Research a shortlist and stage one reversible option for review.",
            "payload": {
                "research_query": "Compare the two best property candidates.",
                "candidate_items": [
                    {"label": "Apartment candidate", "url": "https://example.test/property/1"},
                ],
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=True)

    assert result["status"] == "blocked_needs_research_input"
    assert result["shortlist"] == []
    assert result["recommended_option_or_draft"] == {}
    assert result["execution_receipt"]["network_fetch_enabled"] is False
    issue_codes = {item["code"] for item in result["audit"]["issues"]}
    assert "flat_provider_search_blocked:flat_search_disabled" in issue_codes


def test_flat_property_search_stays_blocked_even_when_feature_flag_is_on(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    packet = {
        "packet_ref": "packet-property-candidates-enabled",
        "approval": {"required": False},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-property-candidates-enabled",
            "work_type": "compare_options",
            "requested_outcome": "Research a shortlist and stage one reversible option for review.",
        },
        "stage": {
            "summary": "Research a shortlist and stage one reversible option for review.",
            "payload": {
                "research_query": "Compare the two best property candidates.",
                "candidate_items": [
                    {"label": "Apartment candidate", "url": "https://example.test/property/1"},
                ],
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet, network_fetch_enabled=True)

    assert result["status"] == "blocked_needs_research_input"
    assert result["shortlist"] == []
    assert result["recommended_option_or_draft"] == {}
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


def test_ambient_transcript_noise_does_not_stage_bogus_search_results() -> None:
    packet = {
        "packet_ref": "packet-ambient-transcript-noise",
        "approval": {"required": False},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-ambient-transcript-noise",
            "work_type": "research",
            "requested_outcome": "Research the request and stage the smallest reversible next step.",
        },
        "stage": {
            "summary": "ambient transcript",
            "payload": {
                "research_query": (
                    "[Mikrofongeraeusche] Nein, hier ist es besser. "
                    "Noah enters pellets and background audio continues."
                ),
                "candidate_items": [
                    {
                        "label": "Songtexte und Lyrics",
                        "url": "https://songtextes.de/",
                        "snippet": "Song lyrics and music text archive.",
                        "reachable": True,
                    },
                    {
                        "label": "Difference between ein, eine, einen",
                        "url": "https://studyflix.de/deutsch/ein-eine-einen-grammar",
                        "snippet": "German language grammar lesson.",
                        "reachable": True,
                    },
                ],
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet)

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["shortlist"] == []
    assert list(result["execution_receipt"]["search_queries_used"]) == []
    issue_codes = {item["code"] for item in result["audit"]["issues"]}
    assert "ambient_transcript_not_decision_ready" in issue_codes


def test_research_backed_draft_prefers_clean_query_over_transcript_noise() -> None:
    packet = {
        "packet_ref": "packet-electrician-clean-draft",
        "approval": {"required": True},
        "safe_work_order": {
            "schema": proactive_ooda_safe_work.SAFE_WORK_ORDER_SCHEMA,
            "work_order_id": "work-electrician-clean-draft",
            "work_type": "draft",
            "requested_outcome": "Research candidates, prepare one inquiry draft, and save it as a Gmail draft.",
        },
        "stage": {
            "summary": "electrician draft",
            "payload": {
                "work_type": "draft",
                "draft_mode": "research_backed_inquiry",
                "draft_request_text": (
                    "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
                    "Ich bin entlassen worden und rede weiter."
                ),
                "research_query": "Elektriker fuer zusaetzliche Steckdosen",
                "search_queries": [
                    "Elektriker fuer zusaetzliche Steckdosen 1200 Wien",
                    "Elektriker fuer zusaetzliche Steckdosen Mikrofonger usche bisschen entlassen",
                ],
                "selection_criteria": ["contact details visible", "reachability", "fit to request"],
                "appointment_type": "Vor Ort Termin",
                "locale": "de",
                "recipient_context": {
                    "location": {"city_terms": ["Wien"], "postal_codes": ["1200"]},
                    "address": "1200 Wien",
                    "phone": "+43 664 7916419",
                },
                "candidate_items": [
                    {
                        "label": "DUE Energie GmbH Elektriker Wien 1200",
                        "url": "https://www.due-energie.at/elektriker-wien-1200/",
                        "snippet": "Elektriker in 1200 Wien fuer Steckdosen, Kontakt und Leistungen.",
                        "contact_email": "office@due-energie.at",
                        "reachable": True,
                    }
                ],
            },
        },
    }

    result = proactive_ooda_safe_work.build_safe_work_result(packet)
    draft = str(result["recommended_option_or_draft"].get("value") or "")

    assert result["status"] == "staged_for_user_decision"
    assert "Elektriker fuer zusaetzliche Steckdosen" in draft
    assert "Adresse: 1200 Wien" in draft
    assert "Telefon: +43 664 7916419" in draft
    assert "Mikrofonger" not in draft
    assert "entlassen" not in draft
    search_queries = " ".join(result["execution_receipt"]["search_queries_used"])
    assert "Mikrofonger" not in search_queries
    assert "entlassen" not in search_queries
