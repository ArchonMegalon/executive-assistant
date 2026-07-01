from __future__ import annotations

import json

import scripts.bootstrap_proactive_ooda_teable_tables as teable_bootstrap
import scripts.run_proactive_ooda as runner
from app.services.proactive_ooda_approval_outcomes import build_proactive_ooda_approval_outcome_payload
from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import ProactiveOodaService, build_run_receipt
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_ooda_teable_sync import (
    build_proactive_ooda_approval_outcome_projection_records,
    build_proactive_ooda_teable_projection_records,
    build_proactive_ooda_teable_projection_summary,
    sync_proactive_ooda_approval_outcome_to_teable,
    sync_proactive_ooda_to_teable,
)
from app.services.tool_execution_teable_adapter import TeableToolAdapter


def _digest_and_safe_work(*, include_approval_surface: bool = False):
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-approval",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare one vendor approval packet",
                "summary": "A reversible vendor choice is ready.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Review the vendor shortlist."},
                        "orient": {"summary": "A reversible option can be staged before approval."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Prepare the best approval link.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One vendor candidate ready for approval.",
                                "approval_url": "https://example.test/approve/vendor-a",
                                "candidate_items": [
                                    {"label": "Vendor A", "url": "https://example.test/vendor-a"},
                                    {"label": "Vendor B", "url": "https://example.test/vendor-b"},
                                ],
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    packet = build_stage_packets(digest)[0]
    result = build_safe_work_result(packet)
    result["execution_receipt"]["network_fetch_enabled"] = True
    result["execution_receipt"]["search_candidate_count"] = 2
    result["execution_receipt"]["search_queries_used"] = [
        "site:example.test vendor approval packet",
        "best reversible vendor option",
    ]
    result["execution_receipt"]["context_fit_receipt"] = {
        "schema": "proactive_ooda.context_fit_receipt.v1",
        "provider_discovery_relevant": True,
        "location_context_present": True,
        "locality_context_applied": True,
        "country_context_applied": True,
        "location_phrase_count": 1,
        "city_term_count": 1,
        "postal_code_count": 1,
        "country_code_count": 1,
        "country_name_count": 1,
        "locality_context_hashes": ["a" * 64, "b" * 64, "c" * 64],
        "country_context_hashes": ["d" * 64, "e" * 64],
        "provider_query_term_count": 2,
        "provider_search_query_too_generic": False,
        "raw_location_context_stored": False,
        "raw_recipient_context_stored": False,
        "raw_principal_id_stored": False,
    }
    notification_result = {
        "message_id": 123,
        "route_error": "whatsapp_web_session_not_ready:qr_required",
        "recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
        "next_action": "scan_whatsapp_web_qr",
    }
    if include_approval_surface:
        notification_result["approval_surface"] = {
            "present": True,
            "channel": "telegram",
            "status": "pending",
            "callback_token_sha256": "b" * 64,
            "expires_at": "2026-07-05T10:00:00Z",
            "packet_ref_sha256": "c" * 64,
            "staged_artifact_sha256": "d" * 64,
            "approval_prompt_sha256": "e" * 64,
            "staged_action_url_sha256": "f" * 64,
            "inline_button_count": 3,
            "url_button_count": 1,
            "message_ids": ["124"],
            "delivery_error_code": "",
            "privacy": {
                "raw_callback_token_stored": False,
                "raw_packet_ref_stored": False,
                "raw_staged_artifact_ref_stored": False,
                "raw_approval_prompt_stored": False,
                "raw_staged_action_url_stored": False,
            },
        }
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result=notification_result,
        stage_packet_refs=("stage_packet:vendor-approval",),
        safe_work_result_refs=(str(result.get("result_ref") or ""),),
    )
    return digest, result, receipt


def test_proactive_ooda_teable_bootstrap_merges_shell_quoted_existing_config(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'TEABLE_TABLE_SYNC_CONFIG_JSON="{\\"preference_review_queue\\":{\\"table_id\\":\\"tbl_pref\\",\\"key_field\\":\\"projection_id\\",\\"field_key_type\\":\\"name\\"}}"\n',
        encoding="utf-8",
    )

    assert teable_bootstrap._load_table_config(env_file=env_file) == {
        "preference_review_queue": {
            "table_id": "tbl_pref",
            "key_field": "projection_id",
            "field_key_type": "name",
        }
    }

    teable_bootstrap._write_table_config(
        env_file=env_file,
        mappings={
            "proactive_ooda_runs": {
                "table_id": "tbl_runs",
                "key_field": "projection_id",
                "field_key_type": "name",
            }
        },
    )

    raw = next(
        line.split("=", 1)[1]
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("TEABLE_TABLE_SYNC_CONFIG_JSON=")
    )
    config = json.loads(raw)
    assert config["preference_review_queue"]["table_id"] == "tbl_pref"
    assert config["proactive_ooda_runs"]["table_id"] == "tbl_runs"


def test_proactive_ooda_teable_projection_keeps_important_artifacts_without_raw_refs() -> None:
    digest, result, receipt = _digest_and_safe_work()

    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )
    summary = build_proactive_ooda_teable_projection_summary(records)
    serialized = json.dumps(records, sort_keys=True)

    assert set(records) == {"proactive_ooda_runs", "proactive_ooda_items", "proactive_ooda_safe_work"}
    assert summary["record_count"] == 3
    assert summary["suppressed_item_count"] == 0
    assert summary["suppressed_safe_work_review_count"] == 0
    assert summary["suppressed_projection_reasons"] == []
    assert summary["suppressed_safe_work_issue_codes"] == []
    assert "exec" not in serialized
    assert "opportunity:vendor-approval" not in serialized
    assert records["proactive_ooda_runs"][0]["notification_status"] == "sent"
    assert records["proactive_ooda_runs"][0]["delivery_channel"] == "telegram"
    assert records["proactive_ooda_runs"][0]["delivery_transport"] == "telegram"
    assert records["proactive_ooda_runs"][0]["delivery_message_count"] == 1
    assert records["proactive_ooda_runs"][0]["delivery_message_ids"] == ["123"]
    assert records["proactive_ooda_runs"][0]["delivery_route_error"] == "whatsapp_web_session_not_ready:qr_required"
    assert records["proactive_ooda_runs"][0]["delivery_next_action"] == "scan_whatsapp_web_qr"
    assert records["proactive_ooda_runs"][0]["delivery_next_action_href"] == "https://myexternalbrain.com/integrations/whatsapp"
    assert records["proactive_ooda_runs"][0]["delivery_next_action_label"] == "Open WhatsApp pairing"
    assert records["proactive_ooda_runs"][0]["delivery_next_action_method"] == "get"
    assert records["proactive_ooda_runs"][0]["suppressed_item_count"] == 0
    assert records["proactive_ooda_runs"][0]["suppressed_projection_reasons"] == []
    assert records["proactive_ooda_items"][0]["stage_kind"] == "approval_packet"
    assert records["proactive_ooda_items"][0]["staged_action_url"] == "https://example.test/approve/vendor-a"
    assert records["proactive_ooda_items"][0]["recommended_label"] == "Vendor A"
    assert records["proactive_ooda_items"][0]["search_candidate_count"] == 2
    assert records["proactive_ooda_items"][0]["search_query_count"] == 2
    assert records["proactive_ooda_items"][0]["context_fit_location_context_present"] is True
    assert records["proactive_ooda_items"][0]["context_fit_locality_context_applied"] is True
    assert records["proactive_ooda_items"][0]["context_fit_country_context_applied"] is True
    assert records["proactive_ooda_items"][0]["privacy_raw_location_context_stored"] is False
    assert records["proactive_ooda_items"][0]["privacy_raw_recipient_context_stored"] is False
    assert records["proactive_ooda_safe_work"][0]["recommended_url"] == "https://example.test/vendor-a"
    assert records["proactive_ooda_safe_work"][0]["shortlist_count"] == 2
    assert records["proactive_ooda_safe_work"][0]["network_fetch_enabled"] is True
    assert records["proactive_ooda_safe_work"][0]["search_candidate_count"] == 2
    assert records["proactive_ooda_safe_work"][0]["search_query_count"] == 2
    assert records["proactive_ooda_safe_work"][0]["search_queries_used"] == [
        "site:example.test vendor approval packet",
        "best reversible vendor option",
    ]
    assert records["proactive_ooda_safe_work"][0]["context_fit_provider_discovery_relevant"] is True
    assert records["proactive_ooda_safe_work"][0]["context_fit_location_context_present"] is True
    assert records["proactive_ooda_safe_work"][0]["context_fit_locality_context_applied"] is True
    assert records["proactive_ooda_safe_work"][0]["context_fit_country_context_applied"] is True
    assert records["proactive_ooda_safe_work"][0]["context_fit_location_phrase_count"] == 1
    assert records["proactive_ooda_safe_work"][0]["context_fit_city_term_count"] == 1
    assert records["proactive_ooda_safe_work"][0]["context_fit_postal_code_count"] == 1
    assert records["proactive_ooda_safe_work"][0]["context_fit_country_code_count"] == 1
    assert records["proactive_ooda_safe_work"][0]["context_fit_country_name_count"] == 1
    assert records["proactive_ooda_safe_work"][0]["context_fit_locality_context_hashes"] == ["a" * 64, "b" * 64, "c" * 64]
    assert records["proactive_ooda_safe_work"][0]["context_fit_country_context_hashes"] == ["d" * 64, "e" * 64]
    assert records["proactive_ooda_safe_work"][0]["context_fit_provider_query_term_count"] == 2
    assert records["proactive_ooda_safe_work"][0]["context_fit_provider_search_query_too_generic"] is False
    assert records["proactive_ooda_safe_work"][0]["privacy_raw_location_context_stored"] is False
    assert records["proactive_ooda_safe_work"][0]["privacy_raw_recipient_context_stored"] is False
    assert "1200 Wien" not in serialized


def test_proactive_ooda_teable_projection_suppresses_non_deliverable_safe_work_noise() -> None:
    digest, result, receipt = _digest_and_safe_work()
    result = {
        **result,
        "status": "blocked_needs_research_input",
        "recommended_option_or_draft": {},
        "staged_action_url": "",
        "shortlist": [],
        "comparison_table": [],
        "audit": {
            "status": "review",
            "issues": [
                {
                    "code": "no_decision_ready_material",
                    "severity": "warn",
                    "detail": "No decision-ready material should be projected as an item.",
                }
            ],
        },
    }

    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )
    summary = build_proactive_ooda_teable_projection_summary(records)

    assert set(records) == {"proactive_ooda_runs", "proactive_ooda_items", "proactive_ooda_safe_work"}
    assert records["proactive_ooda_items"] == []
    assert records["proactive_ooda_safe_work"] == []
    assert summary["record_count"] == 1
    assert summary["suppressed_item_count"] == 1
    assert summary["suppressed_safe_work_review_count"] == 1
    assert summary["suppressed_projection_reasons"] == ["safe_work_audit_review"]
    assert summary["suppressed_safe_work_issue_codes"] == ["no_decision_ready_material"]
    run_row = records["proactive_ooda_runs"][0]
    assert run_row["suppressed_item_count"] == 1
    assert run_row["suppressed_safe_work_review_count"] == 1
    assert run_row["suppressed_projection_reasons"] == ["safe_work_audit_review"]
    assert run_row["suppressed_safe_work_issue_codes"] == ["no_decision_ready_material"]


def test_proactive_ooda_teable_projection_suppresses_single_official_info_link_materiality() -> None:
    digest, result, receipt = _digest_and_safe_work()
    candidate = {
        "label": "Official City of Vienna information portal",
        "source": "official_site",
        "url": "https://www.wien.gv.at/english/",
    }
    result = {
        **result,
        "work_type": "compare_options",
        "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": candidate},
        "shortlist": [candidate],
        "comparison_table": [candidate],
        "audit": {"status": "pass", "issues": []},
    }

    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )
    summary = build_proactive_ooda_teable_projection_summary(records)

    assert records["proactive_ooda_items"] == []
    assert records["proactive_ooda_safe_work"] == []
    assert summary["suppressed_item_count"] == 1
    assert summary["suppressed_safe_work_review_count"] == 1
    assert summary["suppressed_projection_reasons"] == ["safe_work_audit_review"]
    assert summary["suppressed_safe_work_issue_codes"] == ["single_official_info_link_not_decision_ready"]


def test_proactive_ooda_teable_projection_keeps_browser_handoff_safe_work_as_actionable() -> None:
    digest, result, receipt = _digest_and_safe_work()
    result = {
        **result,
        "status": "blocked_human_handoff_required",
        "audit": {
            "status": "review",
            "issues": [{"code": "browser_handoff_required", "severity": "info"}],
        },
        "browser_action_receipt": {
            "status": "blocked_human_handoff_required",
            "user_action_required": True,
        },
    }

    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )
    summary = build_proactive_ooda_teable_projection_summary(records)

    assert summary["record_count"] == 3
    assert records["proactive_ooda_runs"][0]["suppressed_item_count"] == 0
    assert records["proactive_ooda_items"][0]["safe_work_status"] == "blocked_human_handoff_required"
    assert records["proactive_ooda_safe_work"][0]["status"] == "blocked_human_handoff_required"


def test_proactive_ooda_teable_projection_includes_pending_approval_surface_without_raw_refs() -> None:
    digest, result, receipt = _digest_and_safe_work(include_approval_surface=True)

    records = build_proactive_ooda_teable_projection_records(
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )
    serialized = json.dumps(records, sort_keys=True)

    assert set(records) == {
        "proactive_ooda_runs",
        "proactive_ooda_items",
        "proactive_ooda_safe_work",
        "proactive_ooda_approval_surfaces",
    }
    run_row = records["proactive_ooda_runs"][0]
    surface_row = records["proactive_ooda_approval_surfaces"][0]
    assert run_row["approval_surface_present"] is True
    assert run_row["approval_surface_status"] == "pending"
    assert run_row["approval_surface_message_count"] == 1
    assert surface_row["status"] == "pending"
    assert surface_row["callback_token_sha256"] == "b" * 64
    assert surface_row["message_ids"] == ["124"]
    assert '"callback_token":' not in serialized
    assert "stage_packet:vendor-approval" not in serialized


def test_proactive_ooda_teable_bootstrap_schema_includes_delivery_route_fields() -> None:
    run_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_runs"]]

    assert "delivery_channel" in run_fields
    assert "delivery_transport" in run_fields
    assert "delivery_selected_by" in run_fields
    assert "delivery_recipient_hash" in run_fields
    assert "delivery_message_count" in run_fields
    assert "delivery_message_ids" in run_fields
    assert "delivery_outbox_id_hash" in run_fields
    assert "delivery_route_error" in run_fields
    assert "delivery_recovery_hint" in run_fields
    assert "delivery_next_action" in run_fields
    assert "delivery_next_action_href" in run_fields
    assert "delivery_next_action_label" in run_fields
    assert "delivery_next_action_method" in run_fields
    assert "suppressed_item_count" in run_fields
    assert "suppressed_safe_work_review_count" in run_fields
    assert "suppressed_projection_reasons" in run_fields
    assert "suppressed_safe_work_issue_codes" in run_fields


def test_proactive_ooda_teable_bootstrap_schema_includes_search_projection_fields() -> None:
    item_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_items"]]
    safe_work_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_safe_work"]]

    assert "search_candidate_count" in item_fields
    assert "search_query_count" in item_fields
    assert "network_fetch_enabled" in safe_work_fields
    assert "search_candidate_count" in safe_work_fields
    assert "search_query_count" in safe_work_fields
    assert "search_queries_used" in safe_work_fields
    assert "context_fit_location_context_present" in item_fields
    assert "context_fit_locality_context_applied" in item_fields
    assert "context_fit_country_context_applied" in item_fields
    assert "context_fit_provider_discovery_relevant" in safe_work_fields
    assert "context_fit_location_context_present" in safe_work_fields
    assert "context_fit_locality_context_applied" in safe_work_fields
    assert "context_fit_country_context_applied" in safe_work_fields
    assert "context_fit_location_phrase_count" in safe_work_fields
    assert "context_fit_locality_context_hashes" in safe_work_fields
    assert "privacy_raw_location_context_stored" in safe_work_fields
    assert "privacy_raw_recipient_context_stored" in safe_work_fields


def test_proactive_ooda_teable_bootstrap_schema_includes_approval_outcome_projection_fields() -> None:
    run_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_runs"]]
    safe_work_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_safe_work"]]
    approval_surface_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_approval_surfaces"]]
    approval_fields = [field["name"] for field in teable_bootstrap.PROACTIVE_OODA_TABLES["proactive_ooda_approval_outcomes"]]

    assert "approval_outcome_recorded" in run_fields
    assert "approval_outcome_accepted" in run_fields
    assert "approval_surface_present" in run_fields
    assert "approval_surface_status" in run_fields
    assert "approval_outcome_status" in safe_work_fields
    assert "approval_outcome_source_kind" in safe_work_fields
    assert "callback_token_sha256" in approval_surface_fields
    assert "decision_recorded" in approval_surface_fields
    assert "decision_recorded_at" in approval_surface_fields
    assert "run_projection_id" in approval_fields
    assert "safe_work_projection_id" in approval_fields
    assert "packet_ref_sha256" in approval_fields
    assert "staged_artifact_sha256" in approval_fields


def test_proactive_ooda_approval_outcome_projection_records_link_run_and_safe_work_without_raw_refs() -> None:
    _digest, result, receipt = _digest_and_safe_work(include_approval_surface=True)
    approval_outcome = build_proactive_ooda_approval_outcome_payload(
        principal_id="exec",
        outcome="approved",
        source_kind="operator",
        evidence="Approved after reviewing the live shortlist.",
        actor="operator-admin-1",
        packet_ref="stage_packet:vendor-approval",
        staged_artifact_ref=str(result.get("result_ref") or "safe_work_result:res-1"),
        recorded_at="2026-06-27T10:00:00Z",
    )

    records = build_proactive_ooda_approval_outcome_projection_records(
        receipt=receipt,
        safe_work_result=result,
        approval_outcome=approval_outcome,
    )
    serialized = json.dumps(records, sort_keys=True)

    assert set(records) == {
        "proactive_ooda_runs",
        "proactive_ooda_safe_work",
        "proactive_ooda_approval_surfaces",
        "proactive_ooda_approval_outcomes",
    }
    run_row = records["proactive_ooda_runs"][0]
    safe_work_row = records["proactive_ooda_safe_work"][0]
    approval_surface_row = records["proactive_ooda_approval_surfaces"][0]
    approval_row = records["proactive_ooda_approval_outcomes"][0]
    assert run_row["approval_outcome_recorded"] is True
    assert run_row["approval_outcome_accepted"] is True
    assert run_row["delivery_next_action"] == "scan_whatsapp_web_qr"
    assert run_row["delivery_next_action_href"] == "https://myexternalbrain.com/integrations/whatsapp"
    assert run_row["approval_surface_status"] == "approved"
    assert safe_work_row["approval_outcome_status"] == "accepted_redacted"
    assert approval_surface_row["status"] == "approved"
    assert approval_surface_row["decision_recorded"] is True
    assert approval_row["accepted"] is True
    assert approval_row["run_projection_id"] == run_row["projection_id"]
    assert approval_row["safe_work_projection_id"] == safe_work_row["projection_id"]
    assert "Approved after reviewing the live shortlist." not in serialized
    assert "operator-admin-1" not in serialized
    assert "stage_packet:vendor-approval" not in serialized


def test_proactive_ooda_approval_outcome_sync_can_sync_available_tables_and_report_missing_ones(monkeypatch) -> None:
    _digest, result, receipt = _digest_and_safe_work(include_approval_surface=True)
    approval_outcome = build_proactive_ooda_approval_outcome_payload(
        principal_id="exec",
        outcome="approved",
        source_kind="operator",
        evidence="Approved after reviewing the live shortlist.",
        actor="operator-admin-1",
        packet_ref="stage_packet:vendor-approval",
        staged_artifact_ref=str(result.get("result_ref") or "safe_work_result:res-1"),
        recorded_at="2026-06-27T10:00:00Z",
    )
    monkeypatch.setenv("TEABLE_API_KEY", "test-teable-key")
    monkeypatch.setenv(
        "TEABLE_TABLE_SYNC_CONFIG_JSON",
        json.dumps(
            {
                "proactive_ooda_runs": {
                    "table_id": "tbl_proactive_ooda_runs",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                },
                "proactive_ooda_approval_outcomes": {
                    "table_id": "tbl_proactive_ooda_approval_outcomes",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                },
            }
        ),
    )
    observed: list[tuple[str, str, dict[str, object] | None]] = []

    def _request_json(self, *, method: str, url: str, api_key: str, body: dict[str, object] | None = None) -> dict[str, object]:
        assert api_key == "test-teable-key"
        observed.append((method, url, body))
        if method == "GET":
            return {"records": []}
        if method == "POST":
            return {"records": [{"id": "rec-1"}]}
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(TeableToolAdapter, "_request_json", _request_json)

    sync = sync_proactive_ooda_approval_outcome_to_teable(
        receipt=receipt,
        safe_work_result=result,
        approval_outcome=approval_outcome,
    )

    assert sync["status"] == "partial"
    assert sync["sync_attempted"] is True
    assert sync["missing_tables"] == ["proactive_ooda_approval_surfaces", "proactive_ooda_safe_work"]
    assert sync["tool_execution"]["output_json"]["synced_tables"] == [
        "proactive_ooda_runs",
        "proactive_ooda_approval_outcomes",
    ]
    assert any("/api/table/tbl_proactive_ooda_runs/record?" in item[1] for item in observed)
    assert any("/api/table/tbl_proactive_ooda_approval_outcomes/record?" in item[1] for item in observed)


def test_proactive_ooda_teable_bootstrap_adds_missing_fields_with_direct_field_payload(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _request_json(*, method: str, url: str, api_key: str, body: dict[str, object] | None = None) -> object:
        calls.append({"method": method, "url": url, "body": body})
        if method == "GET":
            return [{"name": "projection_id", "type": "singleLineText"}]
        return {"id": "fld-created"}

    monkeypatch.setattr(teable_bootstrap, "_request_json", _request_json)

    created = teable_bootstrap._ensure_fields(
        base_url="https://app.teable.test",
        api_key="test-token",
        table_id="tbl-proactive",
        fields=[
            {"name": "projection_id", "type": "singleLineText"},
            {"name": "delivery_channel", "type": "singleLineText"},
        ],
    )

    assert created == 1
    assert calls[1]["body"] == {"name": "delivery_channel", "type": "singleLineText"}


def test_proactive_ooda_teable_sync_can_sync_available_tables_and_report_missing_ones(monkeypatch) -> None:
    digest, result, receipt = _digest_and_safe_work(include_approval_surface=True)
    monkeypatch.setenv("TEABLE_API_KEY", "test-teable-key")
    monkeypatch.setenv(
        "TEABLE_TABLE_SYNC_CONFIG_JSON",
        json.dumps(
            {
                "proactive_ooda_runs": {
                    "table_id": "tbl_proactive_ooda_runs",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                },
                "proactive_ooda_items": {
                    "table_id": "tbl_proactive_ooda_items",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                },
            }
        ),
    )
    observed: list[tuple[str, str, dict[str, object] | None]] = []

    def _request_json(self, *, method: str, url: str, api_key: str, body: dict[str, object] | None = None) -> dict[str, object]:
        assert api_key == "test-teable-key"
        observed.append((method, url, body))
        if method == "GET":
            return {"records": []}
        if method == "POST":
            return {"records": [{"id": "rec-1"}]}
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(TeableToolAdapter, "_request_json", _request_json)

    sync = sync_proactive_ooda_to_teable(
        principal_id="exec",
        digest=digest,
        receipt=receipt,
        safe_work_results=(result,),
    )

    assert sync["status"] == "partial"
    assert sync["sync_attempted"] is True
    assert sync["missing_tables"] == ["proactive_ooda_approval_surfaces", "proactive_ooda_safe_work"]
    assert sync["tool_execution"]["output_json"]["synced_tables"] == ["proactive_ooda_runs", "proactive_ooda_items"]
    assert any("/api/table/tbl_proactive_ooda_runs/record?" in item[1] for item in observed)
    assert any("/api/table/tbl_proactive_ooda_items/record?" in item[1] for item in observed)


def test_runner_main_emits_teable_sync_result_when_enabled(tmp_path, monkeypatch, capsys) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "opportunity:vendor-approval",
                    "signal_type": "opportunity",
                    "channel": "assistant_opportunity",
                    "title": "Prepare one vendor approval packet",
                    "summary": "A reversible vendor choice is ready.",
                }
            ]
        ),
        encoding="utf-8",
    )
    sent: list[tuple[str, str]] = []
    sync_calls: list[dict[str, object]] = []

    monkeypatch.setenv("EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED", "1")
    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: sent.append((principal_id, text, digest)) or {"message_id": 123},
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "sync_proactive_ooda_to_teable",
        lambda **kwargs: sync_calls.append(dict(kwargs)) or {"status": "synced", "sync_attempted": True, "blocked_reason": ""},
    )
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_proactive_ooda.py",
            "--principal-id",
            "exec",
            "--signals-json",
            str(signal_file),
            "--state-path",
            str(tmp_path / "state.json"),
            "--armed-send",
            "--no-action-required-delivery-only",
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    assert runner.main() == 0

    captured = capsys.readouterr()
    assert sent and sent[0][0] == "exec"
    assert sent[0][2] is not None
    assert sync_calls and sync_calls[0]["principal_id"] == "exec"
    assert '"teable_sync"' in captured.out
    assert '"status": "synced"' in captured.out
