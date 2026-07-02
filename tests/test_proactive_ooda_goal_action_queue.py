from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.proactive_ooda_goal_actions import goal_action_queue_signals
from app.services.proactive_ooda_service import ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_ooda_safe_work import build_safe_work_result

import scripts.run_proactive_ooda as runner


def _posture(*, generated_at: str = "2026-07-02T04:00:00Z") -> dict[str, object]:
    return {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "generated_at": generated_at,
        "source_state_fingerprint": "source-fingerprint-001",
        "operator_action_queue": [
            {
                "key": "google_workspace_oauth_setup",
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
                "title": "Proactive OODA packet approval outcome",
                "delivery_policy": "queue_only",
                "telegram_push_allowed": False,
                "user_action_required": False,
            },
        ],
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
    assert stage["kind"] == "approval_packet"
    assert stage["approval_url"] == "https://ea.test/integrations/google"
    assert stage["candidate_items"] == [
        {
            "label": "Open Google setup",
            "url": "https://ea.test/integrations/google",
            "candidate_source": "goal_action_queue",
            "title": "Google Workspace OAuth test-user setup",
        }
    ]
    assert "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318" in stage["links"]
    assert signal.payload["raw_private_context_exposed"] is False  # type: ignore[index]
    assert signal.payload["raw_secret_exposed"] is False  # type: ignore[index]
    assert signal.payload["raw_token_exposed"] is False  # type: ignore[index]


def test_goal_action_queue_dedupe_is_stable_across_materialization_time() -> None:
    first = goal_action_queue_signals(_posture(generated_at="2026-07-02T04:00:00Z"), public_base_url="https://ea.test")[0]
    second = goal_action_queue_signals(_posture(generated_at="2026-07-02T05:00:00Z"), public_base_url="https://ea.test")[0]

    assert first.external_id == second.external_id
    assert first.source_ref == second.source_ref


def test_goal_action_queue_signal_fails_closed_when_row_exposes_sensitive_material() -> None:
    posture = _posture()
    posture["operator_action_queue"][0]["raw_token_exposed"] = True  # type: ignore[index]

    assert goal_action_queue_signals(posture, public_base_url="https://ea.test") == ()


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

    assert packet["stage"]["kind"] == "approval_packet"
    assert packet["safe_work_order"]["work_type"] == "prepare_shortlist"
    assert result["status"] == "staged_for_user_decision"
    assert result["staged_action_url"] == "https://ea.test/integrations/google"
    assert result["audit"]["status"] == "pass"


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
