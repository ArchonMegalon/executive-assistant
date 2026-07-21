from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

from scripts import run_proactive_ooda as script


def test_host_resource_guard_snapshot_detects_runtime_artifact_disk_pressure(tmp_path, monkeypatch) -> None:
    usage = namedtuple("usage", "total used free")(100 * 1024 ** 3, 97 * 1024 ** 3, 3 * 1024 ** 3)
    monkeypatch.setattr(script.shutil, "disk_usage", lambda _path: usage)

    args = SimpleNamespace(
        host_resource_guard=True,
        host_resource_guard_max_usage_percent=95.0,
        host_resource_guard_min_free_gb=10.0,
    )
    snapshot = script._host_resource_guard_snapshot(
        args,
        stage_packet_dir=tmp_path / "stage",
        safe_work_result_dir=tmp_path / "safe",
        receipt_path=tmp_path / "receipt.json",
    )

    assert snapshot["checked"] is True
    assert snapshot["pressure_detected"] is True
    assert snapshot["status"] == "disk_pressure"
    assert snapshot["deferred_reason"] == "deferred_by_host_disk_pressure"
    assert snapshot["blocking_reason"] == "runtime_artifact_volume_usage_and_free_space_threshold_exceeded"
    assert snapshot["available_gb"] == 3.0
    assert snapshot["usage_percent"] == 97.0


def test_main_skips_runtime_artifact_work_when_host_resource_guard_defers(tmp_path, monkeypatch, capsys) -> None:
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
    state_path = tmp_path / "state.json"
    receipt_path = tmp_path / "receipt.json"

    fake_digest = script.ProactiveOodaDigest(
        principal_id="exec",
        generated_at="2026-07-10T04:00:00Z",
        items=(SimpleNamespace(priority="normal", approval_required=False),),
        notified_refs=(),
        notified_markers=(),
    )
    host_guard = {
        "checked": True,
        "enabled": True,
        "scope": "runtime_artifact_volume",
        "status": "disk_pressure",
        "pressure_detected": True,
        "blocking_reason": "runtime_artifact_volume_usage_threshold_exceeded",
        "triggered_thresholds": ["usage_percent_threshold_exceeded"],
        "deferred_reason": "deferred_by_host_disk_pressure",
        "next_action": "recover_runtime_artifact_volume_pressure",
        "usage_percent": 97.0,
        "available_bytes": 3 * 1024 ** 3,
        "available_gb": 3.0,
        "max_usage_percent_threshold": 95.0,
        "min_free_gb_threshold": 10.0,
        "privacy": {"raw_private_path_exposed": False},
    }
    stage_packet_called = False
    safe_work_preview_called = False

    class FakeService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_digest(self, *, principal_id: str, signals: list[dict[str, object]], already_notified_refs: set[str]):
            return fake_digest

    def _persist_stage_packets(**_kwargs):
        nonlocal stage_packet_called
        stage_packet_called = True
        return SimpleNamespace(paths=(), packet_refs=(), errors=())

    def _notification_safe_work_previews(*args, **kwargs):
        nonlocal safe_work_preview_called
        safe_work_preview_called = True
        return ()

    monkeypatch.setattr(script, "ProactiveOodaService", FakeService)
    monkeypatch.setattr(script, "_context_grounded_digest", lambda principal_id, digest: digest)
    monkeypatch.setattr(script, "_recover_sparse_observation_digest", lambda _args, **kwargs: (kwargs["signals"], kwargs["digest"]))
    monkeypatch.setattr(script, "_host_resource_guard_snapshot", lambda *args, **kwargs: dict(host_guard))
    monkeypatch.setattr(script, "persist_stage_packets", _persist_stage_packets)
    monkeypatch.setattr(script, "persist_safe_work_results_from_paths", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("safe-work results should not persist during host-pressure deferral")))
    monkeypatch.setattr(script, "_notification_safe_work_previews", _notification_safe_work_previews)
    monkeypatch.setattr(script, "format_telegram_digest", lambda digest, safe_work_results=(): "host pressure deferred")
    monkeypatch.setattr(script, "digest_to_dict", lambda digest: {"item_count": len(tuple(getattr(digest, "items", ()) or ()))})
    monkeypatch.setattr(
        script,
        "build_run_receipt",
        lambda **kwargs: SimpleNamespace(
            generated_at="2026-07-10T04:00:01Z",
            delivery_guard=kwargs["delivery_guard"],
        ),
    )
    monkeypatch.setattr(
        script,
        "receipt_to_dict",
        lambda receipt: {
            "generated_at": receipt.generated_at,
            "notification_status": "deferred",
            "error_code": "deferred_by_host_disk_pressure",
            "item_count": 1,
            "delivery_guard": dict(receipt.delivery_guard),
            "stage_packet_ref_hashes": [],
            "safe_work_result_ref_hashes": [],
        },
    )
    monkeypatch.setattr(script, "persist_proactive_ooda_receipt", lambda **_kwargs: None)
    monkeypatch.setattr(script, "_cleanup_hidden_property_boundary", lambda _args: {"status": "skipped", "reason": "test", "ran": False, "archived_total": 0})
    monkeypatch.setattr(script, "_cleanup_approval_callbacks", lambda *args, **kwargs: {})
    monkeypatch.setattr(script, "_materialize_followthrough_artifacts", lambda *args, **kwargs: {"operator_status": {"reason": ""}})
    monkeypatch.setattr(script, "_write_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_proactive_ooda.py",
            "--signals-json",
            str(signal_file),
            "--state-path",
            str(state_path),
            "--receipt-path",
            str(receipt_path),
            "--skip-observation-source",
            "--skip-workspace-source",
            "--armed-send",
            "--no-teable-sync",
        ],
    )

    assert script.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert stage_packet_called is False
    assert safe_work_preview_called is False
    assert output["receipt"]["delivery_guard"]["deferred_reason"] == "deferred_by_host_disk_pressure"
    assert output["receipt"]["delivery_guard"]["host_resource_guard"]["pressure_detected"] is True
    assert output["receipt"]["host_resource_guard"]["usage_percent"] == 97.0
