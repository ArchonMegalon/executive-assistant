from __future__ import annotations

import json
from datetime import datetime, timezone
from argparse import Namespace
from types import SimpleNamespace

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier
from app.services.proactive_ooda_service import ProactiveSignal


def _stub_empty_workspace(monkeypatch) -> None:
    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(google_oauth, "list_recent_workspace_signals", lambda **_kwargs: Namespace(signals=()))


def test_verify_proactive_ooda_accepts_static_signal_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            armed_send=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "signals_json"
    assert report["signal_count"] == 1
    assert report["actionable_count"] == 1
    assert report["delivery_route"]["ready"] is False
    assert report["delivery_guard"]["delivery_state"] == "eligible"


def test_verify_proactive_ooda_aggregates_static_discovery_and_observations(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )
    discovery_file = tmp_path / "discovery.json"
    discovery_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "market:contract",
                    "title": "Contract review due tomorrow",
                    "summary": "Review the supplier risk before renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:reply",
                signal_type="telegram_message",
                channel="telegram",
                title="Reply needed today",
                summary="Reply to the operator before the deadline.",
            )
        ],
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(discovery_file)}]}),
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "signals_json+discovery_json+postgres_observations"
    assert report["signal_count"] == 3
    assert report["actionable_count"] == 3


def test_runner_load_signals_aggregates_configured_sources_and_observations(tmp_path, monkeypatch) -> None:
    _stub_empty_workspace(monkeypatch)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps([{"source_ref": "static:1", "title": "Approval needed", "summary": "Approve this."}]),
        encoding="utf-8",
    )
    discovery_file = tmp_path / "discovery.json"
    discovery_file.write_text(
        json.dumps([{"source_ref": "discovery:1", "title": "Review needed", "summary": "Review this."}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:1",
                signal_type="office_signal",
                channel="observation",
                title="Decision needed",
                summary="Decide this.",
            )
        ],
    )

    signals = runner._load_signals(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(discovery_file)}]}),
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            email_limit=8,
            calendar_limit=8,
            gmail_query="",
        )
    )

    assert [signal["source_ref"] for signal in signals] == ["static:1", "discovery:1", "observation:1"]


def test_runner_notification_approval_request_builds_record_only_prompt_for_auto_executed_gmail_draft(
    tmp_path,
) -> None:
    stage_path = tmp_path / "packet.json"
    safe_path = tmp_path / "result.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-1",
                "item_index": 1,
                "approval": {"required": False},
                "stage": {
                    "payload": {
                        "auto_execute_action": "save_gmail_draft",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    safe_path.write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-1",
                "source_packet_ref_hash": runner._hash_value("stage_packet:pkt-1"),
                "status": "staged_for_user_decision",
                "approval_prompt": "old prompt should not be reused verbatim",
                "staged_action_url": "https://example.test/vendor-a",
            }
        ),
        encoding="utf-8",
    )

    approval_request = runner._notification_approval_request(
        stage_packet_paths=(stage_path,),
        safe_work_result_paths=(safe_path,),
        auto_execute_results=(
            {
                "packet_ref": "stage_packet:pkt-1",
                "staged_artifact_ref": "safe_work_result:res-1",
                "execution": {
                    "status": "executed",
                    "action": "save_gmail_draft",
                },
            },
        ),
    )

    assert approval_request == {
        "packet_ref": "stage_packet:pkt-1",
        "staged_artifact_ref": "safe_work_result:res-1",
        "approval_prompt": (
            "Approve whether EA should keep this saved Gmail draft as the chosen next step. "
            "The draft is already saved in Gmail for review. "
            "No external send will happen without explicit approval."
        ),
        "staged_action_url": "https://example.test/vendor-a",
        "approved_execution_mode": "record_outcome_only",
        "approved_action": "save_gmail_draft",
    }


def test_runner_notification_approval_request_builds_prompt_for_staged_research_packet_without_approval_gate(
    tmp_path,
) -> None:
    stage_path = tmp_path / "packet-research.json"
    safe_path = tmp_path / "result-research.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-research-1",
                "item_index": 1,
                "approval": {"required": False},
                "stage": {
                    "payload": {
                        "kind": "research_packet",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    safe_path.write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-research-1",
                "source_packet_ref_hash": runner._hash_value("stage_packet:pkt-research-1"),
                "status": "staged_for_user_decision",
                "approval_prompt": "Approve whether EA should keep this staged shortlist candidate.",
                "staged_action_url": "https://example.test/research-a",
            }
        ),
        encoding="utf-8",
    )

    approval_request = runner._notification_approval_request(
        stage_packet_paths=(stage_path,),
        safe_work_result_paths=(safe_path,),
        auto_execute_results=(),
    )

    assert approval_request == {
        "packet_ref": "stage_packet:pkt-research-1",
        "staged_artifact_ref": "safe_work_result:res-research-1",
        "approval_prompt": "Approve whether EA should keep this staged shortlist candidate.",
        "staged_action_url": "https://example.test/research-a",
    }


def test_runner_notification_requires_user_action_rejects_internal_proof_packets() -> None:
    assert not runner._notification_requires_user_action(
        {
            "packet_ref": "stage_packet:proof-1",
            "staged_artifact_ref": "safe_work_result:proof-1",
            "approval_prompt": "Approve whether EA should preserve this proof packet as the canonical live check.",
            "staged_action_url": "https://docs.example.test/proof",
        }
    )
    assert runner._notification_requires_user_action(
        {
            "packet_ref": "stage_packet:draft-1",
            "staged_artifact_ref": "safe_work_result:draft-1",
            "approval_prompt": "Approve whether EA should keep this saved Gmail draft as the chosen next step.",
            "approved_execution_mode": "record_outcome_only",
            "approved_action": "save_gmail_draft",
        }
    )


def test_verify_proactive_ooda_warns_but_passes_when_one_discovery_source_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    good_file = tmp_path / "good.json"
    missing_file = tmp_path / "missing-private-feed.json"
    good_file.write_text(
        json.dumps([{"source_ref": "good:1", "title": "Approval needed", "summary": "Approve this today."}]),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json=json.dumps(
                {
                    "sources": [
                        {"type": "json", "path": str(missing_file), "channel": "teable_admin"},
                        {"type": "json", "path": str(good_file), "channel": "teable_admin"},
                    ]
                }
            ),
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "discovery_json"
    assert report["signal_count"] == 1
    assert report["warnings"][0].startswith("discovery_source_failed:teable_admin:json:FileNotFoundError:")
    assert str(missing_file) not in report["warnings"][0]
    assert "missing-private-feed" not in report["warnings"][0]


def test_verify_proactive_ooda_reports_context_grounding(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "signal_type": "opportunity",
                    "channel": "assistant_opportunity",
                    "title": "Prepare a contextual approval packet",
                    "summary": "Review the reversible candidate.",
                    "payload": {
                        "ooda_loop": {
                            "reviewed": True,
                            "observe": {"summary": "Review the candidate."},
                            "orient": {"summary": "Stored context should influence the result."},
                            "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                            "act": {
                                "summary": "Stage the candidate.",
                                "stage": {
                                    "kind": "approval_packet",
                                    "summary": "One candidate ready for approval.",
                                    "candidate_items": [{"label": "Candidate A", "url": "https://example.test/item-a"}],
                                },
                            },
                        }
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "_context_grounded_digest",
        lambda _principal_id, digest: runner.ground_digest_with_context(
            digest,
            context_pack={
                "summary": "1 active commitment",
                "commitment_risks": [{"summary": "Gift window is open.", "due_at": "2099-06-30T12:00:00+00:00", "severity": "high"}],
            },
            preference_bundle={
                "preference_nodes": [
                    {"domain": "general", "category": "constraint", "key": "require_reversible_before_approval", "value_json": True, "status": "active"}
                ]
            },
            assess_candidate=lambda *_args: {
                "fit_score": 80.0,
                "recommendation": "shortlist",
                "match_reasons_json": ["Matches stored profile"],
                "mismatch_reasons_json": [],
                "blocking_constraints_json": [],
            },
        ),
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
            stage_packet_dir=str(tmp_path / "packets"),
            safe_work_result_dir=str(tmp_path / "results"),
            stage_packets=True,
            safe_work_results=True,
            require_stage_packets=False,
            require_safe_work_results=False,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            skip_workspace_source=True,
            opportunity_rules_json="",
        )
    )

    assert report["ok"] is True
    assert report["context_grounding"]["grounded"] is True
    assert report["context_grounding"]["item_count"] == 1
    assert report["context_grounding"]["grounded_item_count"] == 1
    assert report["context_grounding"]["candidate_assessment_count"] == 1
    assert report["context_grounding"]["requirement_count"] >= 1
    assert report["context_grounding"]["deadline_count"] == 1


def test_verify_proactive_ooda_does_not_call_ungrounded_actionable_item_grounded(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "signal_type": "opportunity",
                    "channel": "assistant_opportunity",
                    "title": "Prepare an approval packet",
                    "summary": "Review the reversible candidate.",
                    "payload": {
                        "ooda_loop": {
                            "reviewed": True,
                            "observe": {"summary": "Review the candidate."},
                            "orient": {"summary": "Stored context should influence the result."},
                            "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                            "act": {
                                "summary": "Stage the candidate.",
                                "stage": {
                                    "kind": "approval_packet",
                                    "summary": "One candidate ready for approval.",
                                    "candidate_items": [{"label": "Candidate A", "url": "https://example.test/item-a"}],
                                },
                            },
                        }
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_context_grounded_digest", lambda _principal_id, digest: digest)

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
            stage_packet_dir=str(tmp_path / "packets"),
            safe_work_result_dir=str(tmp_path / "results"),
            stage_packets=True,
            safe_work_results=True,
            require_stage_packets=False,
            require_safe_work_results=False,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            skip_workspace_source=True,
            opportunity_rules_json="",
        )
    )

    assert report["ok"] is True
    assert report["actionable_count"] == 1
    assert report["context_grounding"]["grounded"] is False
    assert report["context_grounding"]["item_count"] == 1
    assert report["context_grounding"]["grounded_item_count"] == 0
    assert report["context_grounding"]["ungrounded_item_count"] == 1
    assert report["context_grounding"]["applied_context_count"] == 0
    assert verifier._context_grounding_summary(report) == "not grounded (1 actionable items, 0 context facts applied)"


def test_context_grounding_status_requires_every_actionable_item_to_be_grounded() -> None:
    status = verifier._context_grounding_status(  # noqa: SLF001
        SimpleNamespace(
            items=(
                SimpleNamespace(stage_payload={"notes": ["Stored preference applied."]}),
                SimpleNamespace(stage_payload={}),
            )
        )
    )

    assert status["grounded"] is False
    assert status["item_count"] == 2
    assert status["grounded_item_count"] == 1
    assert status["ungrounded_item_count"] == 1
    assert status["applied_context_count"] == 1


def test_verify_proactive_ooda_reports_generic_delivery_route(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "_delivery_status",
        lambda principal_id, *, digest=None: SimpleNamespace(
            ready=True,
            selected_channel="whatsapp",
            selected_transport="whatsapp_web_session",
            selected_by="delivery_preference",
            selected_reason="whatsapp preference selected",
            binding_id="wa-binding-1",
            recipient_ref_hash="a" * 64,
            available_channels=("whatsapp", "telegram"),
            errors=(),
            route_error="whatsapp_web_session_not_ready:qr_required",
            recovery_hint="Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
            next_action="scan_whatsapp_web_qr",
            preference_count=1,
            policy_count=0,
            follow_up_hint_count=0,
        ),
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["delivery_route"]["ready"] is True
    assert report["delivery_route"]["selected_channel"] == "whatsapp"
    assert report["delivery_route"]["selected_transport"] == "whatsapp_web_session"
    assert report["delivery_route"]["route_error"] == "whatsapp_web_session_not_ready:qr_required"
    assert report["delivery_route"]["next_action"] == "scan_whatsapp_web_qr"
    assert "delivery route: ready [whatsapp via whatsapp_web_session (delivery_preference)], available whatsapp, telegram, blocked by whatsapp_web_session_not_ready:qr_required, next action scan_whatsapp_web_qr" in verifier._format_report(report)
    assert "delivery recovery: scan_whatsapp_web_qr (whatsapp_web_session_not_ready:qr_required)" in verifier._format_report(report)


def test_runner_load_signals_continues_after_discovery_failure(tmp_path, monkeypatch) -> None:
    _stub_empty_workspace(monkeypatch)
    missing_file = tmp_path / "missing.json"
    monkeypatch.setattr(
        runner,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:still-loaded",
                signal_type="office_signal",
                channel="observation",
                title="Decision needed",
                summary="Decide this.",
            )
        ],
    )

    signals = runner._load_signals(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(missing_file)}]}),
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            email_limit=8,
            calendar_limit=8,
            gmail_query="",
        )
    )

    source_refs = [signal["source_ref"] for signal in signals]
    assert "observation:still-loaded" in source_refs
    assert any(ref.startswith("proactive_source_error:discovery:") for ref in source_refs)


def test_verify_proactive_ooda_fails_enabled_without_source_or_telegram(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=True,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert "no_signal_source_configured" in report["errors"]
    assert "telegram_notification_not_configured" in report["errors"]


def test_verify_proactive_ooda_reports_unhealthy_workspace_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(
        google_oauth,
        "list_recent_workspace_signals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_invalid_grant")),
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=False,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert report["source_mode"] == "google_workspace_error"
    assert report["workspace_source_checked"] is True
    assert report["workspace_source_healthy"] is False
    assert report["workspace_source_status"] == "unhealthy"
    assert report["workspace_source_reason"] == "google_oauth_invalid_grant"
    assert report["errors"] == ["google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"]


def test_verify_proactive_ooda_reports_workspace_not_configured_without_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(
        google_oauth,
        "list_recent_workspace_signals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_binding_not_found")),
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=False,
            require_source=False,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "none"
    assert report["workspace_source_checked"] is True
    assert report["workspace_source_healthy"] is False
    assert report["workspace_source_status"] == "not_configured"
    assert report["workspace_source_reason"] == "google_oauth_binding_not_found"
    assert report["errors"] == []
    assert "workspace: not configured (google_oauth_binding_not_found)" in verifier._format_report(report)


def test_verify_proactive_ooda_reports_operator_pause_guard(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            paused=True,
            pause_reason="maintenance window",
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["delivery_guard"]["delivery_state"] == "deferred"
    assert report["delivery_guard"]["deferred_reason"] == "deferred_by_operator_pause"
    assert report["delivery_guard"]["operator_paused"] is True
    assert report["delivery_guard"]["pause_reason_present"] is True
    assert "delivery guard: deferred (deferred_by_operator_pause), paused" in verifier._format_report(report)


def test_verify_proactive_ooda_reports_stage_packet_readiness(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            opportunity_rules_json=json.dumps(
                {
                    "rules": [
                        {
                            "id": "stage-readiness",
                            "title": "Prepare approval packet",
                            "summary": "A reversible next step is useful now.",
                            "trigger": {"kind": "always"},
                            "action": "Prepare an approval packet with one candidate.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One candidate ready for approval.",
                                "candidate_items": [{"label": "Candidate A", "url": "https://example.test/a"}],
                            },
                        }
                    ]
                }
            ),
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            stage_packet_dir=str(tmp_path / "packets"),
            stage_packets=True,
            require_stage_packets=True,
            safe_work_result_dir=str(tmp_path / "results"),
            safe_work_results=True,
            require_safe_work_results=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["stage_packets"]["ready"] is True
    assert report["stage_packets"]["output_dir_writable"] is True
    assert report["stage_packets"]["expected_packet_count"] == 1
    assert report["stage_packets"]["packet_count"] == 1
    assert report["stage_packets"]["safe_work_order_count"] == 1
    assert report["safe_work_results"]["ready"] is True
    assert report["safe_work_results"]["output_dir_writable"] is True
    assert report["safe_work_results"]["expected_result_count"] == 1
    assert report["safe_work_results"]["result_count"] == 1
    assert report["safe_work_results"]["schema_valid_count"] == 1
    assert "stage packets: ready, 1/1 packets, 1 work orders, writable" in verifier._format_report(report)
    assert "safe-work results: ready, 1/1 results, 1 schema-valid, writable" in verifier._format_report(report)


def test_verify_proactive_ooda_fails_required_stage_packets_when_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            stage_packet_dir=str(tmp_path / "packets"),
            stage_packets=False,
            require_stage_packets=True,
            safe_work_result_dir=str(tmp_path / "results"),
            safe_work_results=False,
            require_safe_work_results=True,
            require_source=False,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert report["stage_packets"]["ready"] is False
    assert report["safe_work_results"]["ready"] is False
    assert report["errors"] == ["stage_packets_disabled", "safe_work_results_disabled"]
    assert "stage packets: disabled" in verifier._format_report(report)
    assert "safe-work results: disabled" in verifier._format_report(report)


def test_verify_proactive_ooda_fails_required_stage_packets_when_dir_is_unwritable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            stage_packet_dir=str(blocked_path),
            stage_packets=True,
            require_stage_packets=True,
            safe_work_result_dir=str(tmp_path / "results"),
            safe_work_results=True,
            require_safe_work_results=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert report["stage_packets"]["ready"] is False
    assert report["stage_packets"]["packet_count"] == 1
    assert report["stage_packets"]["safe_work_order_count"] == 1
    assert report["safe_work_results"]["ready"] is True
    assert report["safe_work_results"]["result_count"] == 1
    assert report["errors"] == ["stage_packet_dir_unwritable:FileExistsError"]
    assert "stage packets: not ready, 1/1 packets, 1 work orders, unwritable" in verifier._format_report(report)


def test_verify_proactive_ooda_fails_required_safe_work_results_when_dir_is_unwritable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    blocked_path = tmp_path / "blocked-results"
    blocked_path.write_text("not a directory", encoding="utf-8")
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=True,
            paused=False,
            pause_reason="",
            quiet_hours_start="",
            quiet_hours_end="",
            quiet_hours_timezone="UTC",
            quiet_hours_allow_high_priority=True,
            interruption_budget_limit=0,
            interruption_budget_window_hours=24,
            interruption_budget_allow_high_priority=True,
            stage_packet_dir=str(tmp_path / "packets"),
            stage_packets=True,
            require_stage_packets=True,
            safe_work_result_dir=str(blocked_path),
            safe_work_results=True,
            require_safe_work_results=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert report["stage_packets"]["ready"] is True
    assert report["safe_work_results"]["ready"] is False
    assert report["safe_work_results"]["result_count"] == 1
    assert report["errors"] == ["safe_work_result_dir_unwritable:FileExistsError"]
    assert "safe-work results: not ready, 1/1 results, 1 schema-valid, unwritable" in verifier._format_report(report)


def test_verify_proactive_ooda_reports_budget_guard(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Review provider renewal",
                    "summary": "Review the provider renewal notes.",
                }
            ]
        ),
        encoding="utf-8",
    )
    state_store = verifier.JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events("exec", ["2026-06-26T10:00:00+00:00"])
    args = Namespace(
        principal_id="exec",
        signals_json=str(signal_file),
        discovery_json="",
        opportunity_rules_json="",
        state_path=str(tmp_path / "state.json"),
        max_items=5,
        observation_lookback_hours=24,
        observation_limit=50,
        skip_observation_source=True,
        skip_workspace_source=True,
        paused=False,
        pause_reason="",
        quiet_hours_start="",
        quiet_hours_end="",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
        interruption_budget_limit=1,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=False,
        require_source=True,
        require_telegram=False,
        require_receipt_observation=False,
    )

    report = verifier._build_report(args)
    guard = verifier._delivery_guard_status(
        args,
        state_store=state_store,
        digest=verifier.ProactiveOodaService(state_store=state_store).build_digest(
            principal_id="exec",
            signals=json.loads(signal_file.read_text(encoding="utf-8")),
        ),
        now=datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert guard["delivery_state"] == "deferred"
    assert guard["deferred_reason"] == "deferred_by_interruption_budget"
    assert guard["interruption_budget_used"] == 1
    assert guard["interruption_budget_exhausted"] is True
