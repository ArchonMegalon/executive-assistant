from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.proactive_ooda_goal_actions import goal_action_queue_signals
from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action

import scripts.run_proactive_ooda as runner


def _posture(*, generated_at: str = "2026-07-02T04:00:00Z") -> dict[str, object]:
    return {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "generated_at": generated_at,
        "source_state_fingerprint": "source-fingerprint-001",
        "operator_delivery_policy": {
            "default_action_digest_streams": ["office_loop", "office_setup", "recovery"],
        },
        "operator_action_queue": [
            {
                "key": "google_workspace_oauth_setup",
                "operator_stream": "office_setup",
                "proactive_signal_allowed": True,
                "title": "Google Workspace OAuth test-user setup",
                "lens": "detect",
                "evidence_kind": "google_workspace_oauth_test_user_setup",
                "required_next_receipt": "Google Workspace OAuth test-user or verified app access",
                "instruction": "Retry the Full Workspace auth link and choose the approved work Google account.",
                "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
                "next_action_href": "/integrations/google",
                "next_action_label": "Open Google setup",
                "next_action_method": "get",
                "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": True,
                "user_action_required": True,
                "quiet_hours_respected": True,
                "non_action_progress_push_allowed": False,
                "irreversible_actions_consent_gated": True,
                "raw_private_context_exposed": False,
                "raw_secret_exposed": False,
                "raw_token_exposed": False,
                "raw_chat_ids_exposed": False,
                "callback_tokens_exposed": False,
                "missing_setup": ["oauth_access_retry_or_account_selection_required"],
            },
            {
                "key": "proactive_ooda_packet_acceptance",
                "operator_stream": "office_loop",
                "title": "Proactive OODA packet approval outcome",
                "kind": "proactive_ooda_acceptance_followthrough",
                "delivery_policy": "action_required_only",
                "telegram_push_allowed": False,
                "user_action_required": True,
            },
        ],
    }


def _with_source_fingerprint(posture: dict[str, object], value: str) -> dict[str, object]:
    updated = dict(posture)
    updated["source_state_fingerprint"] = value
    return updated


def _media_action_row() -> dict[str, object]:
    return {
        "key": "telegram_audiobook_live_delivery",
        "operator_stream": "media_archive",
        "proactive_signal_allowed": True,
        "title": "Telegram audiobook live delivery receipt",
        "lens": "deliver",
        "evidence_kind": "telegram_audiobook_live_delivery_receipt",
        "required_next_receipt": "passing Telegram audiobook live delivery receipt",
        "instruction": "Choose one Telegram audiobook voice sample.",
        "next_action": "choose_one_telegram_audiobook_voice_sample",
        "next_action_href": "/integrations/telegram",
        "next_action_label": "Open Telegram",
        "next_action_method": "get",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "user_action_required": True,
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_secret_exposed": False,
        "raw_token_exposed": False,
        "raw_chat_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def _property_action_row() -> dict[str, object]:
    return {
        "key": "apartment_shortlist_review",
        "operator_stream": "office_loop",
        "proactive_signal_allowed": True,
        "title": "Apartment shortlist review",
        "lens": "detect",
        "evidence_kind": "property_search_candidate",
        "required_next_receipt": "review apartment candidates",
        "instruction": "Compare the two best apartments and open the property search lane.",
        "next_action": "review_property_candidates",
        "next_action_href": "/app/properties",
        "next_action_label": "Open property shortlist",
        "next_action_method": "get",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "user_action_required": True,
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_secret_exposed": False,
        "raw_token_exposed": False,
        "raw_chat_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def test_goal_action_queue_signal_uses_only_prioritized_action_required_row() -> None:
    signals = goal_action_queue_signals(_posture(), limit=1, public_base_url="https://ea.test")

    assert len(signals) == 1
    signal = signals[0]
    assert signal.channel == "goal_posture"
    assert signal.signal_type == "goal_action_queue"
    assert signal.source_ref.startswith("goal_action_queue:google_workspace_oauth_setup:")
    assert "proactive_ooda_packet_acceptance" not in signal.source_ref
    assert signal.external_id == signal.source_ref

    ooda_loop = signal.payload["ooda_loop"]  # type: ignore[index]
    assert ooda_loop["reviewed"] is True
    assert ooda_loop["decide"]["approval_required"] is True
    stage = ooda_loop["act"]["stage"]
    assert stage["kind"] == "internal_action"
    assert stage["work_type"] == "record_internal_action"
    assert stage["approval_url"] == "https://ea.test/integrations/google"
    assert stage["action_label"] == "Open Google setup"
    assert stage["action_url"] == "https://ea.test/integrations/google"
    assert stage["candidate_items"] == []
    assert "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318" in stage["links"]
    assert signal.payload["raw_private_context_exposed"] is False  # type: ignore[index]
    assert signal.payload["raw_secret_exposed"] is False  # type: ignore[index]
    assert signal.payload["raw_token_exposed"] is False  # type: ignore[index]


def test_goal_action_queue_signal_requires_explicit_opt_in() -> None:
    posture = _posture()
    posture["operator_action_queue"][0].pop("proactive_signal_allowed")  # type: ignore[index]

    assert goal_action_queue_signals(posture, public_base_url="https://ea.test") == ()


def test_goal_action_queue_dedupe_is_stable_across_materialization_time() -> None:
    first = goal_action_queue_signals(_posture(generated_at="2026-07-02T04:00:00Z"), public_base_url="https://ea.test")[0]
    second = goal_action_queue_signals(_posture(generated_at="2026-07-02T05:00:00Z"), public_base_url="https://ea.test")[0]

    assert first.external_id == second.external_id
    assert first.source_ref == second.source_ref


def test_goal_action_queue_dedupe_is_stable_across_source_fingerprint_churn() -> None:
    first = goal_action_queue_signals(
        _with_source_fingerprint(_posture(), "source-fingerprint-before"),
        public_base_url="https://ea.test",
    )[0]
    second = goal_action_queue_signals(
        _with_source_fingerprint(_posture(), "source-fingerprint-after"),
        public_base_url="https://ea.test",
    )[0]

    assert first.external_id == second.external_id
    assert first.source_ref == second.source_ref
    assert first.payload["source_state_fingerprint_hash"] != second.payload["source_state_fingerprint_hash"]  # type: ignore[index]


def test_goal_action_queue_source_ref_changes_when_operator_stream_changes() -> None:
    office_posture = _posture()
    media_posture = _posture()
    media_posture["operator_action_queue"][0]["operator_stream"] = "media_archive"  # type: ignore[index]

    office_signal = goal_action_queue_signals(office_posture, public_base_url="https://ea.test")[0]
    media_signal = goal_action_queue_signals(
        media_posture,
        public_base_url="https://ea.test",
        allowed_operator_streams="all",
    )[0]

    assert office_signal.payload["operator_stream"] == "office_setup"  # type: ignore[index]
    assert media_signal.payload["operator_stream"] == "media_archive"  # type: ignore[index]
    assert office_signal.source_ref != media_signal.source_ref
    assert office_signal.external_id != media_signal.external_id


def test_goal_action_queue_signal_fails_closed_when_row_exposes_sensitive_material() -> None:
    posture = _posture()
    posture["operator_action_queue"][0]["raw_token_exposed"] = True  # type: ignore[index]

    assert goal_action_queue_signals(posture, public_base_url="https://ea.test") == ()


def test_goal_action_queue_signal_defaults_to_office_streams_and_skips_media_rows() -> None:
    posture = _posture()
    posture["operator_action_queue"] = [_media_action_row(), *posture["operator_action_queue"]]  # type: ignore[index]

    signals = goal_action_queue_signals(posture, limit=1, public_base_url="https://ea.test")

    assert len(signals) == 1
    signal = signals[0]
    assert signal.source_ref.startswith("goal_action_queue:google_workspace_oauth_setup:")
    assert signal.payload["operator_stream"] == "office_setup"  # type: ignore[index]


def test_goal_action_queue_signal_can_override_allowed_streams() -> None:
    posture = _posture()
    posture["operator_action_queue"] = [_media_action_row(), *posture["operator_action_queue"]]  # type: ignore[index]

    signals = goal_action_queue_signals(
        posture,
        limit=1,
        public_base_url="https://ea.test",
        allowed_operator_streams=("media_archive",),
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.source_ref.startswith("goal_action_queue:telegram_audiobook_live_delivery:")
    assert signal.payload["operator_stream"] == "media_archive"  # type: ignore[index]


def test_goal_action_queue_signal_builds_decision_ready_stage_packet() -> None:
    digest = ProactiveOodaService(max_items=1).build_digest(
        principal_id="exec",
        signals=goal_action_queue_signals(_posture(), limit=1, public_base_url="https://ea.test"),
    )

    assert len(digest.items) == 1
    assert digest.items[0].approval_required is True
    assert digest.items[0].notify is True

    packet = build_stage_packets(digest)[0]
    result = build_safe_work_result(packet, network_fetch_enabled=False)

    assert packet["stage"]["kind"] == "internal_action"
    assert packet["safe_work_order"]["work_type"] == "record_internal_action"
    assert result["status"] == "staged_for_user_decision"
    assert result["work_type"] == "record_internal_action"
    assert result["recommended_option_or_draft"] == {
        "kind": "internal_action",
        "source": "stage_payload",
        "value": {
            "label": "Open Google setup",
            "method": "get",
            "url": "https://ea.test/integrations/google",
        },
    }
    assert result["staged_action_url"] == "https://ea.test/integrations/google"
    assert result["shortlist"] == []
    assert result["comparison_table"] == []
    assert result["audit"]["status"] == "pass"
    assert result["approval_prompt"].startswith("Open Google setup:")
    assert not result["approval_prompt"].startswith("Approve whether EA should proceed with this staged shortlist")
    assert result["execution_receipt"]["network_fetch_enabled"] is False
    assert result["execution_receipt"]["network_fetch_count"] == 0
    assert result["execution_receipt"]["search_queries_used"] == []
    assert result["execution_receipt"]["research_search_plan"]["mode"] == "internal_action"
    assert result["execution_receipt"]["stop_condition"] == "account_review_ready_for_user_decision"


def test_goal_action_queue_internal_action_bypasses_network_fetch_when_enabled() -> None:
    digest = ProactiveOodaService(max_items=1).build_digest(
        principal_id="exec",
        signals=goal_action_queue_signals(_posture(), limit=1, public_base_url="https://ea.test"),
    )
    packet = build_stage_packets(digest)[0]

    result = build_safe_work_result(packet, network_fetch_enabled=True)

    assert result["work_type"] == "record_internal_action"
    assert result["shortlist"] == []
    assert result["comparison_table"] == []
    assert result["evidence_refs"] == [
        {
            "kind": "internal_action",
            "label": "Open Google setup",
            "method": "get",
            "url": "https://ea.test/integrations/google",
            "url_hash": "3dc372cda2b7299517db24f95c4a25aad6afb2f51adb51579e5651d5e2bcb99a",
        }
    ]
    assert result["execution_receipt"]["network_fetch_enabled"] is False
    assert result["execution_receipt"]["page_checks"] == []
    assert result["execution_receipt"]["search_queries_used"] == []


def test_goal_action_queue_internal_action_requires_action_url() -> None:
    digest = ProactiveOodaService(max_items=1).build_digest(
        principal_id="exec",
        signals=goal_action_queue_signals(_posture(), limit=1, public_base_url="https://ea.test"),
    )
    packet = build_stage_packets(digest)[0]
    packet["stage"]["payload"].pop("action_url")  # type: ignore[index]
    packet["stage"]["payload"].pop("approval_url")  # type: ignore[index]
    packet["stage"]["payload"]["links"] = []  # type: ignore[index]
    packet["safe_work_order"]["input_contract"].pop("action_url")  # type: ignore[index]
    packet["safe_work_order"]["input_contract"]["links"] = []  # type: ignore[index]

    result = build_safe_work_result(packet)

    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert result["audit"]["status"] == "review"
    assert [issue["code"] for issue in result["audit"]["issues"]] == ["internal_action_surface_missing"]
    assert result["execution_receipt"]["stop_condition"] == "quality_gate_failed"


def test_goal_action_queue_internal_action_builds_telegram_action_required_approval_request(tmp_path) -> None:
    digest = ProactiveOodaService(max_items=1).build_digest(
        principal_id="exec",
        signals=goal_action_queue_signals(_posture(), limit=1, public_base_url="https://ea.test"),
    )
    packet = build_stage_packets(digest)[0]
    result = build_safe_work_result(packet, network_fetch_enabled=False)
    packet_path = tmp_path / "packet.json"
    result_path = tmp_path / "result.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")

    approval_request = runner._notification_approval_request(
        stage_packet_paths=[packet_path],
        safe_work_result_paths=[result_path],
    )

    assert approval_request is not None
    assert approval_request["work_type"] == "record_internal_action"
    assert approval_request["notification_policy"] == "action_required_only"
    assert approval_request["operator_action_required"] is True
    assert approval_request_needs_telegram_user_action(approval_request) is True


def test_runner_load_signals_ingests_goal_action_queue_when_enabled(tmp_path) -> None:
    posture_path = tmp_path / "goal_posture.json"
    posture_path.write_text(json.dumps(_posture()), encoding="utf-8")

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            include_goal_action_queue=True,
            goal_posture_json=str(posture_path),
            goal_action_queue_limit=1,
            goal_action_operator_streams="",
            skip_observation_source=True,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    assert [row["signal_type"] for row in rows] == ["goal_action_queue"]
    assert rows[0]["source_ref"].startswith("goal_action_queue:google_workspace_oauth_setup:")


def test_runner_load_signals_ignores_goal_action_queue_without_flag(tmp_path) -> None:
    posture_path = tmp_path / "goal_posture.json"
    posture_path.write_text(json.dumps(_posture()), encoding="utf-8")

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            goal_posture_json=str(posture_path),
            goal_action_queue_limit=1,
            goal_action_operator_streams="",
            skip_observation_source=True,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    assert rows == []


def test_runner_load_signals_ignores_goal_action_queue_without_row_opt_in(tmp_path) -> None:
    posture = _posture()
    posture["operator_action_queue"][0].pop("proactive_signal_allowed")  # type: ignore[index]
    posture_path = tmp_path / "goal_posture.json"
    posture_path.write_text(json.dumps(posture), encoding="utf-8")

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            include_goal_action_queue=True,
            goal_posture_json=str(posture_path),
            goal_action_queue_limit=1,
            goal_action_operator_streams="",
            skip_observation_source=True,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    assert rows == []


def test_runner_load_signals_respects_goal_action_stream_override(tmp_path) -> None:
    posture = _posture()
    posture["operator_action_queue"] = [_media_action_row(), *posture["operator_action_queue"]]  # type: ignore[index]
    posture_path = tmp_path / "goal_posture.json"
    posture_path.write_text(json.dumps(posture), encoding="utf-8")

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            include_goal_action_queue=True,
            goal_posture_json=str(posture_path),
            goal_action_queue_limit=1,
            goal_action_operator_streams="media",
            skip_observation_source=True,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    assert [row["signal_type"] for row in rows] == ["goal_action_queue"]
    assert rows[0]["source_ref"].startswith("goal_action_queue:telegram_audiobook_live_delivery:")


def test_runner_load_signals_filters_property_scoped_goal_action_rows(tmp_path) -> None:
    posture = _posture()
    posture["operator_action_queue"] = [_property_action_row()]  # type: ignore[index]
    posture_path = tmp_path / "goal_posture.json"
    posture_path.write_text(json.dumps(posture), encoding="utf-8")

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            include_goal_action_queue=True,
            goal_posture_json=str(posture_path),
            goal_action_queue_limit=1,
            goal_action_operator_streams="",
            skip_observation_source=True,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    assert rows == []
