from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService, build_run_receipt
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_signal_discovery import observation_row_to_signal

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier


def test_env_example_includes_pending_approval_projection_tables() -> None:
    env_path = runner.ROOT / ".env.example"
    raw = env_path.read_text(encoding="utf-8")
    prefix = "TEABLE_TABLE_SYNC_CONFIG_JSON="
    config_line = next(line for line in raw.splitlines() if line.startswith(prefix))
    config = json.loads(config_line[len(prefix) :])

    assert "proactive_ooda_approval_surfaces" in config
    assert "proactive_ooda_approval_outcomes" in config


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


def test_runner_skips_unconfigured_workspace_source_without_noise(tmp_path, monkeypatch) -> None:
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
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_binding_not_found")),
    )

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
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
    assert source_refs == {"manual:1"}
    assert not any(ref.startswith("proactive_source_error:google_workspace:") for ref in source_refs)


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


def test_runner_load_signals_suppresses_matching_topic_after_stop_message(tmp_path, monkeypatch) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:mic",
                    "title": "Research under-wall microphone options",
                    "summary": "Compare small wall-box Wi-Fi microphone nodes.",
                },
                {
                    "source_ref": "manual:flowers",
                    "title": "Review florist shortlist",
                    "summary": "Compare two florist options for next week.",
                },
            ]
        ),
        encoding="utf-8",
    )
    suppression_signal = observation_row_to_signal(
        observation_id="obs-stop-topic",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={"text": "Höre auf mit den unter Wand microfonen."},
        created_at="2026-06-20T10:00:00+00:00",
    )
    assert suppression_signal is not None
    monkeypatch.setattr(runner, "discover_postgres_observation_signals", lambda **_kwargs: [suppression_signal])

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json="",
            skip_observation_source=False,
            skip_workspace_source=True,
            principal_id="exec",
            observation_limit=10,
            observation_lookback_hours=24,
            email_limit=0,
            calendar_limit=0,
            gmail_query="",
        )
    )

    source_refs = {str(row.get("source_ref") or "") for row in rows}
    assert "manual:mic" not in source_refs
    assert "manual:flowers" in source_refs
    assert any(ref.startswith("observation:obs-stop-topic") for ref in source_refs)


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

    assert "Ready: One vendor candidate ready for approval." in text
    assert "Recommendation: Vendor A - https://example.test/vendor-a" in text
    assert "Open: https://example.test/approve/vendor-a" in text
    assert "Options: Vendor A - https://example.test/vendor-a" in text
    assert "Please decide: Approve whether EA should proceed with this staged shortlist candidate." in text


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
            "--armed-send",
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    assert runner.main() == 0

    captured = capsys.readouterr()
    assert sent and sent[0][0] == "exec"
    assert sent[0][2] is not None
    assert "Recommendation: Vendor A - https://example.test/vendor-a" in sent[0][1]
    assert "Open: https://example.test/approve/vendor-a" in sent[0][1]
    assert "Options: Vendor A - https://example.test/vendor-a" in sent[0][1]
    assert "Priority:" not in sent[0][1]
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


def test_runner_unarmed_send_defers_actionable_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:unarmed",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(armed_send=False)

    reason = runner._unarmed_send_defer_reason(args, digest)
    deferred = runner._without_notified_refs(digest)
    receipt = build_run_receipt(digest=deferred, dry_run=False, error_code=reason)

    assert reason == "deferred_by_unarmed_send"
    assert deferred.notified_refs == ()
    assert deferred.notified_markers == ()
    assert receipt.notification_status == "deferred"
    assert receipt.notified_ref_hashes == ()


def test_runner_stage_packet_dir_defaults_next_to_state_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    args = SimpleNamespace(stage_packet_dir="", state_path="state/proactive_ooda_notified.json")

    assert runner._stage_packet_dir(args) == tmp_path / "state" / "proactive_ooda_stage_packets"


def test_runner_defaults_receipt_path_next_to_state_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_proactive_ooda.py",
            "--principal-id",
            "exec",
            "--signals-json",
            str(tmp_path / "signals.json"),
            "--state-path",
            str(tmp_path / "state.json"),
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )
    (tmp_path / "signals.json").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "sync_proactive_ooda_to_teable", lambda **_kwargs: {"status": "disabled", "sync_attempted": False, "blocked_reason": ""})

    assert runner.main() == 0

    receipt = json.loads((tmp_path / "proactive_ooda_latest_run.generated.json").read_text(encoding="utf-8"))
    assert receipt["notification_status"] == "skipped_no_items"


def test_runner_main_unarmed_send_stages_without_notifying(tmp_path, monkeypatch, capsys) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:stage-only",
                    "title": "Decision needed today",
                    "summary": "Approve the staged vendor comparison.",
                }
            ]
        ),
        encoding="utf-8",
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: sent.append((principal_id, text, digest)) or {"message_id": "telegram-should-not-send"},
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "sync_proactive_ooda_to_teable", lambda **_kwargs: {"status": "disabled", "sync_attempted": False, "blocked_reason": ""})
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
    receipt = json.loads((tmp_path / "proactive_ooda_latest_run.generated.json").read_text(encoding="utf-8"))
    assert sent == []
    assert receipt["notification_status"] == "deferred"
    assert receipt["error_code"] == "deferred_by_unarmed_send"
    assert list((tmp_path / "packets").glob("*.json"))
    assert '"notification_status": "deferred"' in captured.out


def test_runner_main_defers_when_safe_work_has_no_decision_ready_material(tmp_path, monkeypatch, capsys) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:empty-safe-work",
                    "signal_type": "opportunity",
                    "channel": "assistant_opportunity",
                    "title": "FYI only",
                    "summary": "A notification happened, but there is no useful next action.",
                    "payload": {
                        "ooda_loop": {
                            "reviewed": True,
                            "observe": {"summary": "A notification happened."},
                            "orient": {"summary": "No useful next action is available yet."},
                            "decide": {"summary": "Do nothing unless more context appears.", "approval_required": False},
                            "act": {
                                "summary": "Draft a concise reply or follow-up, but do not send without instruction.",
                                "stage": {"kind": "decision_packet", "summary": "No useful staged material."},
                            },
                        }
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    sent: list[tuple[str, str, object]] = []
    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: sent.append((principal_id, text, digest)) or {"message_id": "telegram-should-not-send"},
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "sync_proactive_ooda_to_teable", lambda **_kwargs: {"status": "disabled", "sync_attempted": False, "blocked_reason": ""})
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
            "--armed-send",
        ],
    )

    assert runner.main() == 0

    captured = capsys.readouterr()
    receipt = json.loads((tmp_path / "proactive_ooda_latest_run.generated.json").read_text(encoding="utf-8"))
    safe_work = json.loads(next((tmp_path / "results").glob("*.json")).read_text(encoding="utf-8"))
    assert sent == []
    assert receipt["notification_status"] == "deferred"
    assert receipt["error_code"] == "no_decision_ready_safe_work"
    assert safe_work["status"] == "blocked_needs_research_input"
    assert safe_work["audit"]["issues"][0]["code"] == "no_decision_ready_material"
    assert '"notification_status": "deferred"' in captured.out


def test_runner_archives_each_receipt_next_to_state_path(tmp_path, monkeypatch) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:archive-proof",
                    "title": "Decision needed today",
                    "summary": "Approve the staged vendor comparison.",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: {"message_id": "telegram-archive-1"},
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "sync_proactive_ooda_to_teable", lambda **_kwargs: {"status": "disabled", "sync_attempted": False, "blocked_reason": ""})
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
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    assert runner.main() == 0

    archive_dir = tmp_path / "proactive_ooda_run_receipts"
    archives = sorted(archive_dir.glob("*.json"))
    assert len(archives) == 1
    archived_receipt = json.loads(archives[0].read_text(encoding="utf-8"))
    assert archived_receipt["notification_status"] == "deferred"
    assert archived_receipt["error_code"] == "no_user_action_required"
    assert archived_receipt["item_count"] == 1


def test_runner_auto_execute_candidates_require_safe_work_audit_pass(tmp_path) -> None:
    stage_path = tmp_path / "packets" / "pkt.json"
    result_path = tmp_path / "results" / "res.json"
    packet_ref = "stage_packet:pkt"
    result_ref = "safe_work_result:res"
    stage_path.parent.mkdir(parents=True)
    result_path.parent.mkdir(parents=True)
    stage_path.write_text(
        json.dumps(
            {
                "packet_ref": packet_ref,
                "item_index": 1,
                "approval": {"required": False},
                "stage": {"payload": {"auto_execute_action": "save_gmail_draft"}},
            }
        ),
        encoding="utf-8",
    )
    result_path.write_text(
        json.dumps(
            {
                "result_ref": result_ref,
                "source_packet_ref_hash": runner._hash_value(packet_ref),
                "status": "staged_for_user_decision",
                "audit": {
                    "status": "review",
                    "issues": [{"code": "top_candidate_not_provider_like"}],
                },
            }
        ),
        encoding="utf-8",
    )

    assert runner._proactive_ooda_auto_execute_candidates(
        stage_packet_paths=(stage_path,),
        safe_work_result_paths=(result_path,),
    ) == ()

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["audit"] = {"status": "pass", "issues": []}
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    assert runner._proactive_ooda_auto_execute_candidates(
        stage_packet_paths=(stage_path,),
        safe_work_result_paths=(result_path,),
    ) == (
        {
            "packet_ref": packet_ref,
            "staged_artifact_ref": result_ref,
            "result_id": result_ref,
        },
    )


def test_runner_main_preserves_safe_delivery_error_detail_in_receipt(tmp_path, monkeypatch) -> None:
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
    receipt_path = tmp_path / "receipt.json"
    monkeypatch.setattr(
        runner,
        "_deliver_notification",
        lambda principal_id, text, *, digest=None: (_ for _ in ()).throw(RuntimeError("whatsapp_web_session_not_ready:qr_required")),
    )
    monkeypatch.setattr(runner, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "sync_proactive_ooda_to_teable", lambda **_kwargs: {"status": "disabled", "sync_attempted": False, "blocked_reason": ""})
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
            "--receipt-path",
            str(receipt_path),
            "--armed-send",
            "--no-action-required-delivery-only",
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    try:
        runner.main()
        raise AssertionError("runner.main should have raised")
    except RuntimeError as exc:
        assert str(exc) == "proactive_ooda_notification_failed:whatsapp_web_session_not_ready:qr_required"

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["error_code"] == "whatsapp_web_session_not_ready:qr_required"
    assert receipt["delivery_route_error"] == "whatsapp_web_session_not_ready:qr_required"
    assert receipt["delivery_next_action"] == "scan_whatsapp_web_qr"


def test_deliver_notification_falls_back_when_build_container_bootstrap_fails(monkeypatch) -> None:
    from app import container as app_container

    calls: list[dict[str, object]] = []

    def _raise_bootstrap_failure():
        raise RuntimeError("provider_registry_bootstrap_failed")

    def _fallback_send(**kwargs):
        calls.append(dict(kwargs))
        return {"message_id": "telegram-1"}

    monkeypatch.setattr(app_container, "build_container", _raise_bootstrap_failure)
    monkeypatch.setattr(runner, "send_proactive_ooda_notification", _fallback_send)

    receipt = runner._deliver_notification(
        "exec",
        "Decision packet text",
        digest=SimpleNamespace(items=(), principal_id="exec"),
    )

    assert receipt == {"message_id": "telegram-1"}
    assert calls == [
        {
            "principal_id": "exec",
            "text": "Decision packet text",
            "digest": SimpleNamespace(items=(), principal_id="exec"),
        }
    ]


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


def test_verifier_delivery_guard_reports_unarmed_send_state(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:guard",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(
        principal_id="exec",
        paused=False,
        pause_reason="",
        armed_send=False,
        quiet_hours_start="",
        quiet_hours_end="",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
        interruption_budget_limit=0,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
    )

    status = verifier._delivery_guard_status(args, state_store=state_store, digest=digest)

    assert status["delivery_state"] == "deferred"
    assert status["deferred_reason"] == "deferred_by_unarmed_send"
    assert status["armed_send"] is False
