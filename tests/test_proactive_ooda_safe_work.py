from __future__ import annotations

import json
from io import BytesIO
from datetime import datetime, timedelta, timezone

from app.services.proactive_ooda_safe_work import (
    SAFE_WORK_RESULT_SCHEMA,
    _search_queries,
    _search_results_for_query,
    build_safe_work_result,
    default_safe_work_result_dir,
    persist_safe_work_results,
    persist_safe_work_results_from_paths,
)
from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets, persist_stage_packets


def _packet_with_cart_work() -> dict[str, object]:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-cart",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare a reversible cart candidate",
                "summary": "Private shopping context.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "A reversible cart can be prepared."},
                        "orient": {"summary": "This is useful but must remain approval gated."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Prepare a reversible cart link.",
                            "stage": {
                                "kind": "cart_draft",
                                "summary": "One cart candidate ready for approval.",
                                "artifacts": ["comparison", "cart_or_link", "approval_prompt"],
                                "work_type": "prepare_cart_or_link",
                                "cart_url": "https://example.test/cart/private",
                                "candidate_items": [
                                    {"label": "Candidate A", "url": "https://example.test/item-a"}
                                ],
                                "selection_criteria": ["fits constraints", "reversible before approval"],
                                "constraints": {"budget_max": 100, "currency": "EUR"},
                                "approval_gate": "User must approve before purchase.",
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    return build_stage_packets(digest)[0]


def test_build_safe_work_result_materializes_reversible_cart_contract() -> None:
    packet = _packet_with_cart_work()

    result = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")
    serialized = json.dumps(result, sort_keys=True)

    assert result["schema"] == SAFE_WORK_RESULT_SCHEMA
    assert result["result_ref"].startswith("safe_work_result:proactive-ooda-safe-work-")
    assert result["status"] == "staged_for_user_decision"
    assert result["work_type"] == "prepare_cart_or_link"
    assert result["recommended_option_or_draft"] == {
        "kind": "reversible_cart_or_link",
        "value": "https://example.test/cart/private",
        "source": "stage_payload",
    }
    assert result["staged_action_url"] == "https://example.test/cart/private"
    assert result["shortlist"] == [{"label": "Candidate A", "url": "https://example.test/item-a"}]
    assert result["comparison_table"][0]["recommended"] is True
    assert result["approval"]["required"] is True
    assert result["execution_receipt"]["external_actions_attempted"] == []
    assert result["execution_receipt"]["irreversible_actions_attempted"] == []
    assert "purchase" in result["execution_receipt"]["forbidden_without_explicit_approval"]
    assert "cf-email:user@example.test" not in serialized
    assert "opportunity:private-cart" not in serialized


def test_build_safe_work_result_blocks_when_no_research_input_exists() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {"kind": "research_packet", "summary": "Research is needed."}  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "research"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {"expected_artifacts": [], "private_payload_available": False}  # type: ignore[index]

    result = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["audit"]["status"] == "review"
    assert [issue["code"] for issue in result["audit"]["issues"]] == ["no_decision_ready_material"]
    assert "research further" in result["approval_prompt"]
    assert result["execution_receipt"]["external_actions_attempted"] == []


def test_build_safe_work_result_blocks_reference_page_outreach_draft_from_request_field() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "telegram:rauchfangkehrer-bad-candidate",
                "signal_type": "telegram_message",
                "channel": "telegram",
                "title": "Suche einen Rauchfangkehrer",
                "summary": "Find a chimney sweep and save a Gmail draft.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "EA can proceed if provider fit passes audit.", "approval_required": False},
                        "act": {
                            "summary": "Find a provider and draft the inquiry.",
                            "stage": {
                                "kind": "research_packet",
                                "summary": "Research-backed inquiry draft.",
                                "work_type": "draft",
                                "draft_mode": "research_backed_inquiry",
                                "request": (
                                    "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen "
                                    "Zimmerkamin als Abluftrohr eines Klimageraetes verwenden kann"
                                ),
                                "candidate_items": [
                                    {
                                        "label": "Difference between ein, eine, einen, and einem in German",
                                        "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                                        "snippet": "German language grammar lesson",
                                        "reachable": True,
                                        "page_title": "Difference between ein, eine, einen, and einem in the German language",
                                    }
                                ],
                            },
                            "external_action_policy": "Draft only; do not send externally.",
                        },
                    }
                },
            }
        ],
    )
    packet = build_stage_packets(digest)[0]

    result = build_safe_work_result(packet)
    issue_codes = [issue["code"] for issue in result["audit"]["issues"]]

    assert packet["safe_work_order"]["input_contract"]["request"].startswith("suche mir rauchfangkehrer")
    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["audit"]["status"] == "review"
    assert "top_candidate_not_provider_like" in issue_codes
    assert "draft_not_created" in issue_codes


def test_build_safe_work_result_reflects_non_required_approval_contract() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "observation:assistant-task",
                "signal_type": "telegram_message",
                "channel": "telegram",
                "title": "Save a draft",
                "summary": "Prepare a draft and save it to Gmail.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "EA can proceed.", "approval_required": False},
                        "act": {
                            "summary": "Prepare a draft and save it.",
                            "stage": {
                                "kind": "research_packet",
                                "summary": "One draft reply saved to Gmail for review.",
                                "work_type": "draft",
                                "draft_text": "Draft to review:\n\nHello there.",
                                "auto_execute_action": "save_gmail_draft",
                                "post_approval_action": "save_gmail_draft",
                            },
                            "external_action_policy": "Do not send the draft externally without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    packet = build_stage_packets(digest)[0]

    result = build_safe_work_result(packet)

    assert packet["approval"]["required"] is False
    assert result["approval"]["required"] is False
    assert result["approval_prompt"].startswith("EA can proceed with this staged draft text without extra approval.")


def test_build_safe_work_result_enriches_live_page_checks_and_prefers_reachable_candidate(monkeypatch) -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["cart_url"] = ""  # type: ignore[index]
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {"label": "Candidate A", "url": "https://example.test/item-a"},
        {"label": "Candidate B", "url": "https://example.test/item-b"},
    ]

    class Response:
        def __init__(self, url: str, html: str, status: int = 200):
            self._url = url
            self.status = status
            self.headers = type("Headers", (), {"get": lambda self, key, default=None: "text/html; charset=utf-8" if key == "Content-Type" else default, "get_content_charset": lambda self: "utf-8"})()
            self._body = html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return self._body

        def geturl(self):
            return self._url

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/item-a"):
            raise RuntimeError("first_candidate_unreachable")
        return Response("https://example.test/item-b", "<html><head><title>Candidate B Live</title></head></html>")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = build_safe_work_result(packet, network_fetch_enabled=True, network_fetch_limit=4, network_fetch_timeout_seconds=3)

    assert result["execution_receipt"]["network_fetch_enabled"] is True
    assert result["execution_receipt"]["network_fetch_count"] == 2
    assert result["execution_receipt"]["network_fetch_success_count"] == 1
    assert result["recommended_option_or_draft"]["kind"] == "reversible_cart_or_link"
    assert result["recommended_option_or_draft"]["value"] == "https://example.test/item-b"
    assert result["staged_action_url"] == "https://example.test/item-b"
    assert result["shortlist"][0]["label"] == "Candidate B"
    assert result["shortlist"][0]["reachable"] is True
    assert result["shortlist"][0]["page_title"] == "Candidate B Live"
    assert result["shortlist"][1]["label"] == "Candidate A"
    assert result["shortlist"][1]["reachable"] is False
    assert "Live page checks verified 1/2 URLs." in result["summary"]
    candidate_refs = [ref for ref in result["evidence_refs"] if ref["kind"] == "candidate"]
    assert candidate_refs[0]["page_title"] == "Candidate B Live"
    assert result["comparison_table"][0]["label"] == "Candidate B"
    assert result["comparison_table"][0]["recommended"] is True


def test_build_safe_work_result_prefers_direct_provider_page_over_reference_noise() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:provider-search",
                "title": "Find a provider",
                "summary": "Find a provider and stage one contact candidate.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Proceed.", "approval_required": True},
                        "act": {
                            "summary": "Compare provider candidates.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Provider shortlist ready.",
                                "work_type": "compare_options",
                                "candidate_items": [
                                    {
                                        "label": "Schornsteinfeger – Wikipedia",
                                        "url": "https://de.wikipedia.org/wiki/Schornsteinfeger",
                                        "snippet": "Schornsteinfeger ist ein Handwerksberuf.",
                                        "reachable": True,
                                        "page_title": "Schornsteinfeger – Wikipedia",
                                    },
                                    {
                                        "label": "Zum weissen Rauchfangkehrer – Michelin Guide",
                                        "url": "https://guide.michelin.com/en/vienna/wien/restaurant/zum-weissen-rauchfangkehrer",
                                        "snippet": "Restaurant listing with prices and opening hours.",
                                        "reachable": True,
                                    },
                                    {
                                        "label": "Befundung - Rauchfangkehrermeister Herbert Baumrock",
                                        "url": "https://www.baumrock.at/rauchfangkehrer/leistungen/befundung.html",
                                        "snippet": "Befundung und Kontaktinformationen für Rauchfangkehrerleistungen.",
                                        "reachable": True,
                                        "page_title": "Befundung - der Rauchfangkehrermeister Herbert Baumrock",
                                        "contact_email": "office@baumrock.example.test",
                                    },
                                ],
                                "selection_criteria": [
                                    "reversible before approval",
                                    "contact details visible",
                                    "reachability",
                                    "fit to request",
                                ],
                                "comparison_dimensions": ["reachability", "contact details", "timing"],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    packet = build_stage_packets(digest)[0]

    result = build_safe_work_result(packet)

    assert result["shortlist"][0]["url"] == "https://www.baumrock.at/rauchfangkehrer/leistungen/befundung.html"
    assert result["comparison_table"][0]["recommended"] is True
    assert "contact details visible" in result["comparison_table"][0]["matched_criteria"]
    assert any(
        "encyclopedia result" in item or "not a direct provider page" in item
        for row in result["comparison_table"][1:]
        for item in row["constraint_violations"]
    )


def test_build_safe_work_result_synthesizes_shortlist_from_research_queries(monkeypatch) -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "research_packet",
        "summary": "Research under-wall microphone options.",
        "work_type": "research",
        "selection_criteria": ["wifi", "microphone", "small form factor"],
        "research_query": "small wifi microphone module for wall box",
        "search_queries": [
            "M5Stack Atom VoiceS3R microphone wifi",
            "Seeed ReSpeaker Lite voice assistant wifi",
        ],
        "target_sites": [
            "https://shop.m5stack.com",
            "https://wiki.seeedstudio.com",
        ],
    }
    packet["safe_work_order"]["work_type"] = "research"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["wifi", "microphone", "small form factor"],
        "research_query": "small wifi microphone module for wall box",
        "search_queries": [
            "M5Stack Atom VoiceS3R microphone wifi",
            "Seeed ReSpeaker Lite voice assistant wifi",
        ],
        "target_sites": [
            "https://shop.m5stack.com",
            "https://wiki.seeedstudio.com",
        ],
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    class Response:
        def __init__(self, url: str, html: str, status: int = 200):
            self._url = url
            self.status = status
            self.headers = type(
                "Headers",
                (),
                {
                    "get": lambda self, key, default=None: "text/html; charset=utf-8" if key == "Content-Type" else default,
                    "get_content_charset": lambda self: "utf-8",
                },
            )()
            self._body = html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return self._body

        def geturl(self):
            return self._url

    search_html = """
    <html><body>
      <a class="result__a" href="https://shop.m5stack.com/products/atom-echos3r-smart-speaker-dev-kit">ATOM EchoS3R Smart Speaker Dev Kit</a>
      <div class="result__snippet">Small Wi-Fi development kit with microphone.</div>
      <a class="result__a" href="https://wiki.seeedstudio.com/xiao_respeaker/">ReSpeaker Lite Voice Assistant Kit</a>
      <div class="result__snippet">Dual microphone voice assistant kit.</div>
    </body></html>
    """

    def fake_urlopen(request, timeout):
        if "duckduckgo.com/html/" in request.full_url:
            return Response(request.full_url, search_html)
        if request.full_url == "https://shop.m5stack.com/products/atom-echos3r-smart-speaker-dev-kit":
            return Response(request.full_url, "<html><head><title>ATOM EchoS3R Smart Speaker Dev Kit</title></head></html>")
        if request.full_url == "https://wiki.seeedstudio.com/xiao_respeaker/":
            return Response(request.full_url, "<html><head><title>ReSpeaker Lite Voice Assistant Kit</title></head></html>")
        if request.full_url == "https://shop.m5stack.com":
            return Response(request.full_url, "<html><head><title>M5Stack Shop</title></head></html>")
        if request.full_url == "https://wiki.seeedstudio.com":
            return Response(request.full_url, "<html><head><title>Seeed Studio Wiki</title></head></html>")
        raise RuntimeError(f"unexpected_url:{request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = build_safe_work_result(packet, network_fetch_enabled=True, network_fetch_limit=4, network_fetch_timeout_seconds=3)

    assert result["status"] == "staged_for_user_decision"
    assert result["recommended_option_or_draft"]["kind"] == "shortlist_candidate"
    assert [item["label"] for item in result["shortlist"]] == [
        "ATOM EchoS3R Smart Speaker Dev Kit",
        "ReSpeaker Lite Voice Assistant Kit",
    ]
    assert result["shortlist"][0]["candidate_source"] == "search_result"
    assert result["shortlist"][0]["reachable"] is True
    assert result["shortlist"][0]["page_title"] == "ATOM EchoS3R Smart Speaker Dev Kit"
    assert result["execution_receipt"]["search_candidate_count"] == 2
    assert result["execution_receipt"]["search_queries_used"][0].startswith("site:shop.m5stack.com ")
    assert result["comparison_table"][0]["recommended"] is True


def test_build_safe_work_result_synthesizes_research_backed_draft_from_best_contact(monkeypatch) -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "One researched inquiry draft ready for review before any send.",
        "work_type": "draft",
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": "Find a chimney sweep and ask whether they handle fireplace exhaust assessments.",
        "research_query": "Find a chimney sweep in Vienna",
        "search_queries": ["Find a chimney sweep in Vienna"],
        "selection_criteria": ["contact details visible", "reachability"],
        "subject_hint": "Inquiry: chimney sweep",
        "locale": "en",
    }
    packet["safe_work_order"]["work_type"] = "draft"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "research_query": "Find a chimney sweep in Vienna",
        "search_queries": ["Find a chimney sweep in Vienna"],
        "selection_criteria": ["contact details visible", "reachability"],
        "expected_artifacts": ["shortlist", "draft_text"],
        "private_payload_available": True,
    }

    class Response:
        def __init__(self, url: str, html: str, status: int = 200):
            self._url = url
            self.status = status
            self.headers = type(
                "Headers",
                (),
                {
                    "get": lambda self, key, default=None: "text/html; charset=utf-8" if key == "Content-Type" else default,
                    "get_content_charset": lambda self: "utf-8",
                },
            )()
            self._body = html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return self._body

        def geturl(self):
            return self._url

    search_html = """
    <html><body>
      <a class="result__a" href="https://rauchfang.example.test/contact">Rauchfangkehrer Musterbetrieb</a>
      <div class="result__snippet">Certified chimney sweep in Vienna.</div>
    </body></html>
    """

    def fake_urlopen(request, timeout):
        if "duckduckgo.com/html/" in request.full_url:
            return Response(request.full_url, search_html)
        if request.full_url == "https://rauchfang.example.test/contact":
            return Response(
                request.full_url,
                "<html><head><title>Rauchfangkehrer Musterbetrieb</title></head><body>Contact us at office@rauchfang.example.test</body></html>",
            )
        raise RuntimeError(f"unexpected_url:{request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = build_safe_work_result(packet, network_fetch_enabled=True, network_fetch_limit=4, network_fetch_timeout_seconds=3)

    assert result["status"] == "staged_for_user_decision"
    assert result["recommended_option_or_draft"]["kind"] == "draft_text"
    assert result["recommended_option_or_draft"]["source"] == "candidate_synthesis"
    assert result["recommended_option_or_draft"]["recipient_email"] == "office@rauchfang.example.test"
    assert result["shortlist"][0]["contact_email"] == "office@rauchfang.example.test"


def test_build_safe_work_result_humanizes_german_onsite_provider_draft_with_contact_context() -> None:
    packet = _packet_with_cart_work()
    request_text = (
        "suche mir einen Elektriker fuer einen Vor Ort Termin: Ich brauche eine Unterputz-Steckdose "
        "bei der Abluftoeffnung in einer Regipswand und zusaetzlich eine Doppelsteckdose in einer Betonwand. "
        "Wenn du einen gefunden hast formuliere eine Emailanfrage und speicher sie als Draft in meiner Inbox."
    )
    recipient_context = {
        "address": "Beispielgasse 1/2, 1200 Wien",
        "phone": "+43 664 7916419",
        "location": {
            "phrases": ["1200 Wien"],
            "city_terms": ["Wien"],
            "country_codes": ["AT"],
        },
    }
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "One researched inquiry draft ready for review before any send.",
        "work_type": "draft",
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "Elektriker Unterputz Steckdose 1200 Wien",
        "selection_criteria": ["Vor Ort Termin", "contact details visible", "fit to request"],
        "locale": "de",
        "recipient_context": recipient_context,
        "candidate_items": [
            {
                "label": "Elektro Musterbetrieb Wien",
                "url": "https://elektro.example.at/kontakt",
                "snippet": "Elektriker in Wien fuer Steckdosen, Unterputz und Besichtigung.",
                "reachable": True,
                "contact_email": "office@elektro.example.at",
            }
        ],
    }
    packet["safe_work_order"]["work_type"] = "draft"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "Elektriker Unterputz Steckdose 1200 Wien",
        "selection_criteria": ["Vor Ort Termin", "contact details visible", "fit to request"],
        "recipient_context": recipient_context,
        "expected_artifacts": ["shortlist", "draft_text"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)
    draft = result["recommended_option_or_draft"]["value"]

    assert result["status"] == "staged_for_user_decision"
    assert result["recommended_option_or_draft"]["source"] == "candidate_synthesis"
    assert result["recommended_option_or_draft"]["recipient_email"] == "office@elektro.example.at"
    assert "Vor-Ort-Termin" in draft
    assert "Adresse: Beispielgasse 1/2, 1200 Wien" in draft
    assert "Telefon: +43 664 7916419" in draft
    assert "Regipswand" in draft
    assert "Doppelsteckdose" in draft
    assert "speicher" not in draft.lower()
    assert "inbox" not in draft.lower()
    assert "schicke mir" not in draft.lower()
    assert "Quelle:" not in draft


def test_build_safe_work_result_prefers_local_provider_over_reference_noise_from_recipient_context() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "Provider shortlist ready.",
        "work_type": "compare_options",
        "candidate_items": [
            {
                "label": "Difference between ein, eine, einen, and einem in the German language",
                "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                "snippet": "German language explainer article.",
                "reachable": True,
            },
            {
                "label": "Wiener Rauchfangkehrer Kontakt",
                "url": "https://rauchfangkehrer.example.at/kontakt",
                "snippet": "Rauchfangkehrer in Wien mit Kontakt und Befundung.",
                "reachable": True,
                "contact_email": "office@rauchfangkehrer.example.at",
            },
        ],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": {
            "location": {
                "phrases": ["1200 Wien"],
                "city_terms": ["Wien"],
                "postal_codes": ["1200"],
                "country_codes": ["AT"],
            }
        },
    }
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": {
            "location": {
                "phrases": ["1200 Wien"],
                "city_terms": ["Wien"],
                "postal_codes": ["1200"],
                "country_codes": ["AT"],
            }
        },
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["shortlist"][0]["label"] == "Wiener Rauchfangkehrer Kontakt"
    assert result["comparison_table"][0]["recommended"] is True
    assert "contact details visible" in result["comparison_table"][0]["matched_criteria"]
    assert any(
        "educational or reference page" in value or "not a direct provider page" in value
        for value in result["comparison_table"][1]["constraint_violations"]
    )


def test_build_safe_work_result_blocks_provider_shortlist_when_only_reference_candidate_exists() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "Provider shortlist ready.",
        "work_type": "compare_options",
        "candidate_items": [
            {
                "label": "Difference between ein, eine, einen, and einem in the German language",
                "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                "snippet": "German language grammar explainer article.",
                "reachable": True,
                "contact_email": "contact@planforgermany.com",
            }
        ],
        "research_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr",
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": {
            "location": {
                "phrases": ["1200 Wien"],
                "city_terms": ["Wien"],
                "postal_codes": ["1200"],
                "country_codes": ["AT"],
            }
        },
    }
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "research_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr",
        "search_queries": ["Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": {
            "location": {
                "phrases": ["1200 Wien"],
                "city_terms": ["Wien"],
                "postal_codes": ["1200"],
                "country_codes": ["AT"],
            }
        },
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["staged_action_url"] == ""
    assert result["shortlist"][0]["url"] == "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/"
    assert result["comparison_table"][0]["recommended"] is False
    assert "educational or reference page" in result["comparison_table"][0]["constraint_violations"]
    assert result["audit"]["status"] == "review"
    assert [issue["code"] for issue in result["audit"]["issues"]] == ["no_provider_safe_candidate"]
    assert result["approval_prompt"].startswith("Approve whether EA should research further or change constraints.")


def test_build_safe_work_result_prefers_austrian_provider_over_out_of_country_contact_from_recipient_context() -> None:
    packet = _packet_with_cart_work()
    recipient_context = {
        "location": {
            "phrases": ["1200 Wien"],
            "city_terms": ["Wien"],
            "postal_codes": ["1200"],
            "country_codes": ["AT"],
        }
    }
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "Provider shortlist ready.",
        "work_type": "compare_options",
        "candidate_items": [
            {
                "label": "Sachverstaendiger Ofen- und Luftheizungsbau",
                "url": "https://gutachter-ofenbau.de/",
                "snippet": "Erstellung von Gutachten fuer Ofenbau und Kaminbau.",
                "reachable": True,
                "contact_email": "hs@gutachter-ofenbau.example.test",
            },
            {
                "label": "Befundung - Rauchfangkehrermeister Herbert Baumrock",
                "url": "https://www.baumrock.at/rauchfangkehrer/leistungen/befundung.html",
                "snippet": "Rauchfangkehrer in Wien, Befundung, Gutachten und Abnahme von Feuerstaetten.",
                "reachable": True,
            },
        ],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": recipient_context,
    }
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "research_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr",
        "search_queries": ["Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "comparison_dimensions": ["reachability", "contact details", "timing"],
        "recipient_context": recipient_context,
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["shortlist"][0]["url"] == "https://www.baumrock.at/rauchfangkehrer/leistungen/befundung.html"
    assert "outside stored country context" in result["comparison_table"][1]["constraint_violations"]


def test_build_safe_work_result_does_not_count_search_query_as_candidate_locality() -> None:
    packet = _packet_with_cart_work()
    recipient_context = {
        "location": {
            "phrases": ["1200 Wien"],
            "city_terms": ["Wien"],
            "postal_codes": ["1200"],
            "country_codes": ["AT"],
        }
    }
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "approval_packet",
        "summary": "Provider shortlist ready.",
        "work_type": "compare_options",
        "candidate_items": [
            {
                "label": "Gutachten - Innung der Salzburger Rauchfangkehrer",
                "url": "https://www.rauchfangkehrer-innung.at/leistungen/gutachten/",
                "snippet": "Rauchfangkehrer Gutachten in Salzburg.",
                "reachable": True,
                "source_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien",
            },
            {
                "label": "Befunderstellung - Wiener Rauchfangkehrer",
                "url": "https://www.rauchfangkehrer.wien/taetigkeiten-fuer-ihre-sicherheit/befunderstellung/",
                "snippet": "Wiener Rauchfangkehrer erstellt Befunde und Gutachten fuer Abluftfaenge.",
                "reachable": True,
                "source_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien",
            },
        ],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "recipient_context": recipient_context,
    }
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "research_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr",
        "search_queries": ["Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "recipient_context": recipient_context,
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["shortlist"][0]["url"] == "https://www.rauchfangkehrer.wien/taetigkeiten-fuer-ihre-sicherheit/befunderstellung/"
    assert "city Wien" in result["comparison_table"][0]["matched_criteria"]
    assert all("location 1200 Wien" not in row["matched_criteria"] for row in result["comparison_table"])


def test_build_safe_work_result_blocks_outreach_draft_from_reference_noise() -> None:
    packet = _packet_with_cart_work()
    request_text = (
        "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin "
        "als Abluftrohr eines Klimageraets verwenden kann. "
        "wenn du einen gefunden hast formuliere eine emailanfrage und speicher sie als draft in meiner inbox. "
        "schicke mir hier den link zu ihr."
    )
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "research_packet",
        "summary": "One researched inquiry draft saved to Gmail for review.",
        "work_type": "draft",
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "rauchfangkehrer",
        "search_queries": ["rauchfangkehrer Gutachten Zimmerkamin Abluftrohr", "rauchfangkehrer"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "locale": "de",
        "candidate_items": [
            {
                "label": "Difference between ein, eine, einen, and einem in the German language",
                "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                "snippet": "German language explainer article.",
                "reachable": True,
            }
        ],
    }
    packet["safe_work_order"]["work_type"] = "draft"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "rauchfangkehrer",
        "search_queries": ["rauchfangkehrer Gutachten Zimmerkamin Abluftrohr", "rauchfangkehrer"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "expected_artifacts": ["shortlist", "draft_text"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["staged_action_url"] == ""
    assert result["audit"]["status"] == "review"
    issue_codes = [issue["code"] for issue in result["audit"]["issues"]]
    assert "operator_meta_removed_from_outreach_request" in issue_codes
    assert "top_candidate_not_provider_like" in issue_codes
    assert "draft_not_created" in issue_codes


def test_build_safe_work_result_rejects_reference_page_with_email_from_generic_provider_query() -> None:
    packet = _packet_with_cart_work()
    request_text = (
        "wenn du einen gefunden hast formuliere eine emailanfrage und speicher sie als draft in meiner inbox. "
        "schicke mir hier den link zu ihr."
    )
    packet["stage"]["payload"] = {  # type: ignore[index]
        "kind": "research_packet",
        "summary": "One researched inquiry draft saved to Gmail for review.",
        "work_type": "draft",
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "einen",
        "search_queries": ["einen"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "subject_hint": "Anfrage: einen",
        "locale": "de",
        "candidate_items": [
            {
                "label": "Difference between ein, eine, einen, and einem in the German language",
                "url": "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/",
                "snippet": "German language grammar explainer article.",
                "reachable": True,
                "contact_email": "contact@planforgermany.com",
            }
        ],
    }
    packet["safe_work_order"]["work_type"] = "draft"  # type: ignore[index]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "draft_mode": "research_backed_inquiry",
        "draft_request_text": request_text,
        "research_query": "einen",
        "search_queries": ["einen"],
        "selection_criteria": ["contact details visible", "reachability", "fit to request"],
        "expected_artifacts": ["shortlist", "draft_text"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["recommended_option_or_draft"] == {}
    assert result["comparison_table"][0]["url"] == "https://planforgermany.com/difference-ein-eine-einen-einem-german-language/"
    assert "educational or reference page" in result["comparison_table"][0]["constraint_violations"]
    assert result["audit"]["status"] == "review"
    issue_codes = [issue["code"] for issue in result["audit"]["issues"]]
    assert "top_candidate_not_provider_like" in issue_codes
    assert "draft_not_created" in issue_codes


def test_search_results_for_query_falls_back_to_yahoo_when_duckduckgo_challenges(monkeypatch) -> None:
    class Response:
        def __init__(self, url: str, html: str) -> None:
            self._url = url
            self.headers = type(
                "Headers",
                (),
                {
                    "get": lambda self, key, default=None: "text/html; charset=utf-8" if key == "Content-Type" else default,
                    "get_content_charset": lambda self: "utf-8",
                },
            )()
            self._body = html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return self._body

        def geturl(self):
            return self._url

    calls: list[str] = []
    ddg_html = """
    <html><body>
      <div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>
    </body></html>
    """
    yahoo_html = """
    <html><body>
      <li>
        <div class="dd algo algo-sr relsrch Sr">
          <div class="compTitle">
            <a href="https://r.search.yahoo.com/_ylt=test/RU=https%3a%2f%2fwww.rauchfangkehrer.wien%2frauchfangkehrer%2frauchfangkehrersuche%2f/RK=2/RS=test">
              <h3 class="title">
                Rauchfangkehrersuche: Wiener Rauchfangkehrer
              </h3>
            </a>
          </div>
          <div class="compText">
            <p>Wiener Rauchfangkehrer: Informationen ueber Adressen und Kehrtermine.</p>
          </div>
        </div>
      </li>
    </body></html>
    """

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if "duckduckgo.com" in request.full_url:
            return Response(request.full_url, ddg_html)
        if "search.yahoo.com" in request.full_url:
            return Response(request.full_url, yahoo_html)
        raise RuntimeError(f"unexpected_url:{request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    results = _search_results_for_query(query="Rauchfangkehrer", timeout_seconds=3, limit=3)

    assert len(results) == 1
    assert results[0]["url"] == "https://www.rauchfangkehrer.wien/rauchfangkehrer/rauchfangkehrersuche/"
    assert results[0]["label"] == "Rauchfangkehrersuche: Wiener Rauchfangkehrer"
    assert "Kehrtermine" in results[0]["snippet"]
    assert any("duckduckgo.com" in url for url in calls)
    assert any("search.yahoo.com" in url for url in calls)


def test_search_queries_expand_with_recipient_location_context() -> None:
    queries = _search_queries(
        input_contract={
            "research_query": "rauchfangkehrer",
            "recipient_context": {
                "location": {
                    "phrases": ["1200 Wien"],
                    "city_terms": ["Wien"],
                    "postal_codes": ["1200"],
                    "country_codes": ["AT"],
                }
            },
        },
        stage_payload={},
        limit=4,
    )

    assert queries[0] == "rauchfangkehrer 1200 Wien"
    assert "rauchfangkehrer Wien" in queries
    assert "rauchfangkehrer" in queries


def test_build_safe_work_result_scores_candidates_against_budget_preferences_and_reversibility() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["kind"] = "shortlist"  # type: ignore[index]
    packet["stage"]["payload"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["approval_url"] = ""  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {
            "label": "Candidate A",
            "url": "https://example.test/item-a",
            "price_value": 89,
            "currency": "EUR",
            "reversible_before_approval": True,
            "delivery_days": 4,
            "tags": ["cool weather", "outdoor"],
        },
        {
            "label": "Candidate B",
            "url": "https://example.test/item-b",
            "price_value": 129,
            "currency": "EUR",
            "reversible_before_approval": True,
            "delivery_days": 1,
            "tags": ["outdoor"],
        },
        {
            "label": "Candidate C",
            "url": "https://example.test/item-c",
            "price_value": 79,
            "currency": "USD",
            "reversible_before_approval": False,
            "delivery_days": 2,
            "tags": ["indoor"],
        },
    ]
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["reversible before approval", "price", "timing"],
        "preferences": ["cool weather"],
        "budget": {"max": 100, "currency": "EUR"},
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }

    result = build_safe_work_result(packet)

    assert result["recommended_option_or_draft"]["kind"] == "shortlist_candidate"
    assert result["recommended_option_or_draft"]["value"]["label"] == "Candidate A"
    assert [item["label"] for item in result["shortlist"]] == ["Candidate A", "Candidate B", "Candidate C"]
    assert result["comparison_table"][0]["label"] == "Candidate A"
    assert result["comparison_table"][0]["recommended"] is True
    assert "within budget <= 100" in result["comparison_table"][0]["matched_criteria"]
    assert "reversible before approval" in result["comparison_table"][0]["matched_criteria"]
    assert any("over budget" in value for value in result["comparison_table"][1]["constraint_violations"])
    assert any("currency mismatch" in value for value in result["comparison_table"][2]["constraint_violations"])
    assert any("not reversible" in value for value in result["comparison_table"][2]["constraint_violations"])


def test_build_safe_work_result_uses_profile_assessment_and_timing_window() -> None:
    packet = _packet_with_cart_work()
    packet["stage"]["payload"]["kind"] = "shortlist"  # type: ignore[index]
    packet["stage"]["payload"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["safe_work_order"]["work_type"] = "compare_options"  # type: ignore[index]
    packet["stage"]["payload"]["approval_url"] = ""  # type: ignore[index]
    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    packet["safe_work_order"]["input_contract"] = {  # type: ignore[index]
        "selection_criteria": ["timing", "reversible before approval"],
        "deadline": deadline,
        "expected_artifacts": ["shortlist"],
        "private_payload_available": True,
    }
    packet["stage"]["payload"]["candidate_items"] = [  # type: ignore[index]
        {
            "label": "Candidate A",
            "url": "https://example.test/item-a",
            "delivery_days": 2,
            "reversible_before_approval": True,
            "preference_assessment": {
                "fit_score": 82.0,
                "recommendation": "shortlist",
                "match_reasons_json": ["Matches stored profile"],
                "mismatch_reasons_json": [],
                "blocking_constraints_json": [],
            },
        },
        {
            "label": "Candidate B",
            "url": "https://example.test/item-b",
            "delivery_days": 5,
            "reversible_before_approval": True,
            "preference_assessment": {
                "fit_score": 28.0,
                "recommendation": "reject",
                "match_reasons_json": [],
                "mismatch_reasons_json": ["Conflicts with stored preferences"],
                "blocking_constraints_json": [],
            },
        },
    ]

    result = build_safe_work_result(packet)

    assert [item["label"] for item in result["shortlist"]] == ["Candidate A", "Candidate B"]
    assert result["comparison_table"][0]["label"] == "Candidate A"
    assert "profile fit 82" in result["comparison_table"][0]["matched_criteria"]
    assert any("meets timing window" in value for value in result["comparison_table"][0]["recommendation_reasons"])
    assert any("misses timing window" in value for value in result["comparison_table"][1]["constraint_violations"])
    assert any("Conflicts with stored preferences" in value for value in result["comparison_table"][1]["constraint_violations"])


def test_build_safe_work_result_keeps_stable_result_id_across_regeneration() -> None:
    packet = _packet_with_cart_work()

    first = build_safe_work_result(packet, generated_at="2026-06-26T12:00:00+00:00")
    second = build_safe_work_result(packet, generated_at="2026-06-27T12:00:00+00:00")

    assert first["result_id"] == second["result_id"]
    assert first["result_ref"] == second["result_ref"]


def test_persist_safe_work_results_writes_private_result_files(tmp_path) -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:compare",
                "title": "Compare vendor options",
                "summary": "Review options before renewal.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Compare two vendor options.",
                            "stage": {
                                "kind": "shortlist",
                                "summary": "Two options ready for review.",
                                "work_type": "compare_options",
                                "candidate_items": [{"label": "Option A"}, {"label": "Option B"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_result = persist_stage_packets(digest=digest, output_dir=stage_dir)

    result = persist_safe_work_results(stage_packet_dir=stage_dir, result_dir=result_dir)

    assert not stage_result.errors
    assert not result.errors
    assert len(result.paths) == 1
    assert len(result.result_refs) == 1
    payload = json.loads((result_dir / f"{result.result_refs[0].removeprefix('safe_work_result:')}.json").read_text(encoding="utf-8"))
    assert payload["schema"] == SAFE_WORK_RESULT_SCHEMA
    assert payload["work_type"] == "compare_options"


def test_persist_safe_work_results_from_paths_only_materializes_current_packets(tmp_path) -> None:
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:current",
                "title": "Prepare current packet",
                "summary": "Review this packet.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Stage the current packet.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Current packet ready.",
                                "candidate_items": [{"label": "Current"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            },
            {
                "source_ref": "opportunity:also-current",
                "title": "Prepare second packet",
                "summary": "Review this second packet.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "decide": {"summary": "Approve whether to proceed.", "approval_required": True},
                        "act": {
                            "summary": "Stage the second packet.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Second packet ready.",
                                "candidate_items": [{"label": "Second"}],
                            },
                            "external_action_policy": "Do not commit without explicit approval.",
                        },
                    }
                },
            },
        ],
    )
    stage_result = persist_stage_packets(digest=digest, output_dir=stage_dir)

    result = persist_safe_work_results_from_paths(stage_packet_paths=stage_result.paths[:1], result_dir=result_dir)

    assert not result.errors
    assert len(stage_result.paths) == 2
    assert len(result.paths) == 1
    assert len(result.result_refs) == 1


def test_persist_safe_work_results_from_paths_refreshes_existing_result(tmp_path) -> None:
    packet = _packet_with_cart_work()
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_dir.mkdir()
    stage_path = stage_dir / f"{packet['packet_id']}.json"
    stage_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    first = persist_safe_work_results_from_paths(stage_packet_paths=(stage_path,), result_dir=result_dir)
    second = persist_safe_work_results_from_paths(stage_packet_paths=(stage_path,), result_dir=result_dir)

    assert not first.errors
    assert not second.errors
    assert first.result_refs == second.result_refs
    assert len(list(result_dir.glob("*.json"))) == 1


def test_persist_safe_work_results_from_paths_can_disable_network_fetch(monkeypatch, tmp_path) -> None:
    packet = _packet_with_cart_work()
    stage_dir = tmp_path / "stage"
    result_dir = tmp_path / "results"
    stage_dir.mkdir()
    stage_path = stage_dir / f"{packet['packet_id']}.json"
    stage_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seen: list[str] = []

    def fake_urlopen(request, timeout):
        seen.append(request.full_url)
        return BytesIO(b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = persist_safe_work_results_from_paths(
        stage_packet_paths=(stage_path,),
        result_dir=result_dir,
        network_fetch_enabled=False,
    )

    assert not result.errors
    assert seen == []


def test_default_safe_work_result_dir_sits_next_to_stage_packet_dir(tmp_path) -> None:
    assert default_safe_work_result_dir(tmp_path / "state" / "proactive_ooda_stage_packets") == (
        tmp_path / "state" / "proactive_ooda_safe_work_results"
    )
