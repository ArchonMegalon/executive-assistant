from __future__ import annotations

import json

import scripts.run_proactive_ooda as runner
from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import ProactiveOodaService, build_run_receipt
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_ooda_teable_sync import (
    build_proactive_ooda_teable_projection_records,
    build_proactive_ooda_teable_projection_summary,
    sync_proactive_ooda_to_teable,
)
from app.services.tool_execution_teable_adapter import TeableToolAdapter


def _digest_and_safe_work():
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
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result={"message_id": 123},
        stage_packet_refs=("stage_packet:vendor-approval",),
        safe_work_result_refs=(str(result.get("result_ref") or ""),),
    )
    return digest, result, receipt


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
    assert "exec" not in serialized
    assert "opportunity:vendor-approval" not in serialized
    assert records["proactive_ooda_runs"][0]["notification_status"] == "sent"
    assert records["proactive_ooda_items"][0]["stage_kind"] == "approval_packet"
    assert records["proactive_ooda_items"][0]["staged_action_url"] == "https://example.test/approve/vendor-a"
    assert records["proactive_ooda_items"][0]["recommended_label"] == "Vendor A"
    assert records["proactive_ooda_safe_work"][0]["recommended_url"] == "https://example.test/vendor-a"
    assert records["proactive_ooda_safe_work"][0]["shortlist_count"] == 2


def test_proactive_ooda_teable_sync_can_sync_available_tables_and_report_missing_ones(monkeypatch) -> None:
    digest, result, receipt = _digest_and_safe_work()
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
    assert sync["missing_tables"] == ["proactive_ooda_safe_work"]
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
        "_telegram_notify",
        lambda principal_id, text: sent.append((principal_id, text)) or {"message_id": 123},
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
            "--skip-observation-source",
            "--skip-workspace-source",
        ],
    )

    assert runner.main() == 0

    captured = capsys.readouterr()
    assert sent and sent[0][0] == "exec"
    assert sync_calls and sync_calls[0]["principal_id"] == "exec"
    assert '"teable_sync"' in captured.out
    assert '"status": "synced"' in captured.out
