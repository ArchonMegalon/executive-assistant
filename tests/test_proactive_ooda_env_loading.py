from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService, build_run_receipt
from app.services.proactive_ooda_stage_packets import build_stage_packets

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier


def test_dotenv_loader_fills_missing_values_without_overriding(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                "EA_PROACTIVE_OODA_PRINCIPAL_ID=from-file",
                'EA_PROACTIVE_OODA_DISCOVERY_JSON="{\\"sources\\":[]}"',
                "EXISTING_VALUE=from-file",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING_VALUE", "from-env")
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)

    runner._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_PRINCIPAL_ID"] == "from-file"
    assert os.environ["EA_PROACTIVE_OODA_DISCOVERY_JSON"] == '{\\"sources\\":[]}'
    assert os.environ["EXISTING_VALUE"] == "from-env"


def test_verify_dotenv_loader_matches_runner(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EA_PROACTIVE_OODA_MAX_ITEMS=2\n", encoding="utf-8")
    monkeypatch.delenv("EA_PROACTIVE_OODA_MAX_ITEMS", raising=False)

    verifier._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_MAX_ITEMS"] == "2"


def test_proactive_ooda_default_principal_is_generic_and_uses_runtime_default(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)

    assert runner._default_principal_id() == "principal-default"
    assert verifier._default_principal_id() == "principal-default"

    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "workspace-owner")
    assert runner._default_principal_id() == "workspace-owner"
    assert verifier._default_principal_id() == "workspace-owner"

    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "proactive-owner")
    assert runner._default_principal_id() == "proactive-owner"
    assert verifier._default_principal_id() == "proactive-owner"


def test_dotenv_loader_ignores_missing_or_unreadable_paths(tmp_path) -> None:
    runner._load_dotenv_if_present(tmp_path / "missing.env")


def test_runner_ingests_all_available_sources_when_workspace_scan_fails(tmp_path, monkeypatch) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:1",
                    "title": "Decision needed today",
                    "summary": "Approve the action.",
                }
            ]
        ),
        encoding="utf-8",
    )

    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(
        google_oauth,
        "list_recent_workspace_signals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_invalid_grant")),
    )

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json=json.dumps(
                {
                    "rules": [
                        {
                            "id": "generic-opportunity",
                            "title": "Prepare useful next step",
                            "summary": "EA can stage the next useful step.",
                            "trigger": {"kind": "always"},
                        }
                    ]
                }
            ),
            skip_observation_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=1,
            calendar_limit=1,
            gmail_query="",
        )
    )

    source_refs = {str(row.get("source_ref") or "") for row in rows}
    assert "manual:1" in source_refs
    assert any(ref.startswith("opportunity:generic-opportunity:") for ref in source_refs)
    assert any(ref.startswith("proactive_source_error:google_workspace:") for ref in source_refs)


def test_runner_load_signals_reuses_opportunity_occurrence_until_condition_resets(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    args = SimpleNamespace(
        signals_json="",
        discovery_json="",
        opportunity_rules_json=json.dumps(
            {
                "rules": [
                    {
                        "id": "cool-weather-window",
                        "title": "Cool-weather opportunity",
                        "summary": "A weather-sensitive errand may be easier now.",
                        "trigger": {
                            "kind": "cooler_weather",
                            "location": "Vienna",
                            "temperature_at_or_below_c": 20,
                            "current_temperature_c": 18,
                        },
                    }
                ]
            }
        ),
        skip_observation_source=True,
        skip_workspace_source=True,
        principal_id="exec",
        observation_limit=0,
        observation_lookback_hours=0,
        email_limit=1,
        calendar_limit=1,
        gmail_query="",
    )
    warm_args = SimpleNamespace(**{**args.__dict__, "opportunity_rules_json": json.dumps(
        {
            "rules": [
                {
                    "id": "cool-weather-window",
                    "title": "Cool-weather opportunity",
                    "summary": "A weather-sensitive errand may be easier now.",
                    "trigger": {
                        "kind": "cooler_weather",
                        "location": "Vienna",
                        "temperature_at_or_below_c": 20,
                        "current_temperature_c": 26,
                    },
                }
            ]
        }
    )})

    first = runner._load_signals(args, state_store=state_store)
    second = runner._load_signals(args, state_store=state_store)
    warm = runner._load_signals(warm_args, state_store=state_store)
    third = runner._load_signals(args, state_store=state_store)

    assert [row["source_ref"] for row in first] == ["opportunity:cool-weather-window:occurrence-1"]
    assert [row["source_ref"] for row in second] == ["opportunity:cool-weather-window:occurrence-1"]
    assert warm == []
    assert [row["source_ref"] for row in third] == ["opportunity:cool-weather-window:occurrence-2"]


def test_runner_notification_text_includes_safe_work_preview() -> None:
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

    text = runner._format_notification_text(digest, safe_work_results=(result,))

    assert "Prepared: One vendor candidate ready for approval." in text
    assert "Recommended: shortlist candidate: Vendor A | https://example.test/vendor-a" in text
    assert "Link: https://example.test/approve/vendor-a" in text
    assert "Shortlist: Vendor A - https://example.test/vendor-a" in text
    assert "Approve: Approve whether EA should proceed with this staged shortlist candidate." in text


def test_runner_main_sends_safe_work_preview_to_telegram(tmp_path, monkeypatch, capsys) -> None:
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
            ]
        ),
        encoding="utf-8",
    )
    sent: list[tuple[str, str]] = []

    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: sent.append((principal_id, text, digest)) or {"message_id": 123},
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
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
            "--stage-packet-dir",
            str(tmp_path / "packets"),
            "--safe-work-result-dir",
            str(tmp_path / "results"),
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    assert runner.main() == 0

    captured = capsys.readouterr()
    assert sent and sent[0][0] == "exec"
    assert sent[0][2] is not None
    assert "Recommended: shortlist candidate: Vendor A | https://example.test/vendor-a" in sent[0][1]
    assert "Link: https://example.test/approve/vendor-a" in sent[0][1]
    assert "Shortlist: Vendor A - https://example.test/vendor-a" in sent[0][1]
    assert '"notification_status": "sent"' in captured.out


def test_runner_quiet_hours_defer_non_high_priority_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-review",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_quiet_hours"


def test_runner_quiet_hours_can_allow_high_priority_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == ""


def test_runner_quiet_hours_can_defer_high_priority_when_configured() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=False,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_quiet_hours"


def test_runner_deferred_digest_clears_notified_refs() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:quiet",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )

    deferred = runner._without_notified_refs(digest)
    receipt = build_run_receipt(digest=deferred, dry_run=False, error_code="deferred_by_quiet_hours")

    assert digest.notified_refs == ("opportunity:quiet",)
    assert digest.notified_markers == ("opportunity:quiet",)
    assert deferred.items == digest.items
    assert deferred.notified_refs == ()
    assert deferred.notified_markers == ()
    assert receipt.notification_status == "deferred"
    assert receipt.notified_ref_hashes == ()


def test_runner_operator_pause_defers_actionable_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:pause",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(paused=True, pause_reason="maintenance")

    reason = runner._operator_pause_defer_reason(args, digest)
    deferred = runner._without_notified_refs(digest)
    receipt = build_run_receipt(digest=deferred, dry_run=False, error_code=reason)

    assert reason == "deferred_by_operator_pause"
    assert deferred.notified_refs == ()
    assert deferred.notified_markers == ()
    assert receipt.notification_status == "deferred"
    assert receipt.notified_ref_hashes == ()


def test_runner_stage_packet_dir_defaults_next_to_state_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    args = SimpleNamespace(stage_packet_dir="", state_path="state/proactive_ooda_notified.json")

    assert runner._stage_packet_dir(args) == tmp_path / "state" / "proactive_ooda_stage_packets"


def test_runner_stage_packet_dir_accepts_relative_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    args = SimpleNamespace(stage_packet_dir="operator/stage-packets", state_path="state/proactive_ooda_notified.json")

    assert runner._stage_packet_dir(args) == tmp_path / "operator" / "stage-packets"


def test_runner_safe_work_result_dir_defaults_next_to_stage_packet_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    args = SimpleNamespace(safe_work_result_dir="")

    assert runner._safe_work_result_dir(args, stage_packet_dir=stage_dir) == (
        tmp_path / "state" / "proactive_ooda_safe_work_results"
    )


def test_runner_safe_work_result_dir_accepts_relative_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    args = SimpleNamespace(safe_work_result_dir="operator/safe-work-results")

    assert runner._safe_work_result_dir(args, stage_packet_dir=stage_dir) == tmp_path / "operator" / "safe-work-results"


def test_runner_interruption_budget_defers_when_window_is_exhausted(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events(
        "exec",
        [
            "2026-06-26T10:00:00+00:00",
            "2026-06-26T11:00:00+00:00",
        ],
    )
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-review",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(
        interruption_budget_limit=2,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
    )

    reason = runner._interruption_budget_defer_reason(
        args,
        state_store=state_store,
        principal_id="exec",
        digest=digest,
        now=datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_interruption_budget"


def test_runner_interruption_budget_allows_high_priority_when_configured(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events("exec", ["2026-06-26T10:00:00+00:00"])
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        interruption_budget_limit=1,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
    )

    reason = runner._interruption_budget_defer_reason(
        args,
        state_store=state_store,
        principal_id="exec",
        digest=digest,
        now=datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert reason == ""


def test_runner_interruption_budget_records_and_prunes_window(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events(
        "exec",
        [
            "2026-06-24T10:00:00+00:00",
            "2026-06-26T10:00:00+00:00",
        ],
    )
    args = SimpleNamespace(interruption_budget_window_hours=24)

    runner._record_interruption_event(
        args,
        state_store=state_store,
        principal_id="exec",
        occurred_at="2026-06-26T12:00:00+00:00",
    )

    assert state_store.load_interruption_events("exec") == (
        "2026-06-26T10:00:00+00:00",
        "2026-06-26T12:00:00+00:00",
    )
