from __future__ import annotations

from app.services import proactive_ooda_live_ops_bridge as bridge


def test_runtime_artifact_drift_summary_skips_host_compare_without_coherent_run_receipt() -> None:
    live_bundle = {
        "stage_packet": {
            "packet_ref": "stage_packet:live-packet",
        },
        "safe_work_result": {
            "result_ref": "safe_work_result:live-result",
            "status": "staged_for_user_decision",
        },
        "run_receipt": {
            "notification_status": "sent",
            "item_count": 1,
        },
    }
    host_bundle = {
        "stage_packet": {
            "packet_ref": "stage_packet:stale-host-packet",
        },
        "safe_work_result": {
            "result_ref": "safe_work_result:stale-host-result",
            "status": "staged_for_user_decision",
        },
        "run_receipt": {},
    }

    summary = bridge._runtime_artifact_drift_summary(  # noqa: SLF001
        live_bundle=live_bundle,
        host_bundle=host_bundle,
    )

    assert summary["checked"] is False
    assert summary["present"] is False
    assert summary["status"] == "host_bundle_not_checked"
    assert summary["requires_recovery"] is False
    assert summary["host_artifacts_present"] is True
