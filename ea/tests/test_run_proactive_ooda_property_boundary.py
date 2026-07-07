from __future__ import annotations

import argparse
from pathlib import Path

from scripts import run_proactive_ooda


def test_cleanup_hidden_property_boundary_runs_for_live_proactive_ooda(monkeypatch: object) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    observed: dict[str, str] = {}

    monkeypatch.setattr(root_module, "assistant_property_lane_enabled", lambda: False)

    def _fake_cleanup(*, state_path: str) -> dict[str, object]:
        observed["state_path"] = state_path
        return {
            "status": "ok",
            "archived_total": 3,
            "stage_packet_total": 1,
            "safe_work_result_total": 1,
            "approval_callback_total": 1,
        }

    monkeypatch.setattr(root_module, "cleanup_hidden_property_runtime_state", _fake_cleanup)

    result = root_module._cleanup_hidden_property_boundary(
        argparse.Namespace(dry_run=False, state_path="state/proactive-test.json")
    )

    assert observed["state_path"] == "state/proactive-test.json"
    assert result["status"] == "ok"
    assert result["ran"] is True
    assert result["reason"] == ""
    assert result["archived_total"] == 3
    assert result["stage_packet_total"] == 1
    assert result["safe_work_result_total"] == 1
    assert result["approval_callback_total"] == 1


def test_cleanup_hidden_property_boundary_skips_dry_run(monkeypatch: object) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    monkeypatch.setattr(root_module, "assistant_property_lane_enabled", lambda: False)

    def _unexpected_cleanup(**_: object) -> dict[str, object]:
        raise AssertionError("cleanup should not run during dry-run")

    monkeypatch.setattr(root_module, "cleanup_hidden_property_runtime_state", _unexpected_cleanup)

    result = root_module._cleanup_hidden_property_boundary(
        argparse.Namespace(dry_run=True, state_path="state/proactive-test.json")
    )

    assert result == {
        "status": "skipped",
        "reason": "dry_run",
        "ran": False,
        "archived_total": 0,
    }


def test_receipt_payload_includes_property_boundary_cleanup(monkeypatch: object) -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    monkeypatch.setattr(root_module, "receipt_to_dict", lambda _receipt: {"notification_status": "skipped"})

    payload = root_module._receipt_payload(
        receipt=object(),
        teable_sync={},
        stage_packet_dir=Path("/tmp/stage"),
        safe_work_result_dir=Path("/tmp/safe"),
        property_boundary_cleanup={"status": "ok", "archived_total": 2, "ran": True, "reason": ""},
    )

    assert payload["property_boundary_cleanup"] == {
        "status": "ok",
        "archived_total": 2,
        "ran": True,
        "reason": "",
    }
