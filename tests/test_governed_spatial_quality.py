from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.governed_spatial_quality import (
    INTERACTIVE_QUALITY_RECEIPT_CONTRACT,
    WALKTHROUGH_QUALITY_RECEIPT_CONTRACT,
    GovernedSpatialQualityService,
)
from app.services.governed_spatial_render import DESIGN_AUTHORITY_STATUS


OBSERVED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _walkthrough_metrics(*, artifact_sha256: str = "c" * 64) -> dict[str, object]:
    return {
        "artifact_sha256": artifact_sha256,
        "final_encoded_artifact": True,
        "provenance_refs": ["provenance:fixture:walkthrough:v1"],
        "all_frames_evaluated": True,
        "shot_count": 1,
        "cut_count": 0,
        "teleport_count": 0,
        "collision_failure_count": 0,
        "wall_or_door_clip_count": 0,
        "required_room_count": 7,
        "covered_room_count": 7,
        "stable_room_topology_percent": 100.0,
        "stable_furniture_on_revisit": True,
        "combat_overlay_count": 0,
        "stable_actor_identity": True,
        "stable_actor_transform": True,
        "black_burst_count": 0,
        "blank_burst_count": 0,
        "frozen_burst_count": 0,
        "corrupt_burst_count": 0,
        "repeated_frame_burst_count": 0,
        "container_fps": 60.0,
        "effective_motion_fps": 30.0,
        "max_duplicate_frame_run_during_motion": 2,
        "all_frame_continuity_max_delta": 18.0,
        "rotation_gate": {"status": "pass", "proof_ref": "proof:rotation:fixture:v1"},
        "spatial_drift_gate": {"status": "pass", "proof_ref": "proof:spatial-drift:fixture:v1"},
        "desktop_decode_pass": True,
        "mobile_decode_pass": True,
        "horizontal_overflow": False,
        "layout_shift_detected": False,
        "audio_present": False,
    }


def _interactive_metrics() -> dict[str, object]:
    return {
        "artifact_sha256": "d" * 64,
        "final_encoded_artifact": True,
        "provenance_refs": ["provenance:fixture:interactive:v1"],
        "same_origin": True,
        "nonblank_canvas": True,
        "median_desktop_fps": 55.0,
        "median_mobile_fps": 45.0,
        "sustained_frame_time_spike_count": 0,
        "horizontal_overflow": False,
        "minimum_control_width_css_px": 44.0,
        "minimum_control_height_css_px": 44.0,
        "keyboard_pass": True,
        "touch_pass": True,
        "labels_and_focus_pass": True,
        "reduced_motion_pass": True,
        "offline_recovery_pass": True,
        "retry_pass": True,
        "direct_open_pass": True,
        "back_navigation_pass": True,
        "desktop_decode_pass": True,
        "mobile_decode_pass": True,
        "desktop_browser_proof_ref": "proof:browser:desktop:v1",
        "mobile_browser_proof_ref": "proof:browser:mobile:v1",
        "baseline_device_profile_ref": "profile:baseline-device:v1",
    }


def test_walkthrough_quality_contract_can_pass_without_allowing_ready_projection() -> None:
    receipt = GovernedSpatialQualityService().audit_walkthrough(
        _walkthrough_metrics(),
        observed_at=OBSERVED_AT,
    )

    assert receipt["contract_name"] == WALKTHROUGH_QUALITY_RECEIPT_CONTRACT
    assert receipt["status"] == "pass_local_quality_contract"
    assert receipt["issues"] == []
    assert receipt["metrics"]["room_coverage_percent"] == 100.0
    assert receipt["design_authority_status"] == DESIGN_AUTHORITY_STATUS
    assert receipt["launch_ready_allowed"] is False
    assert receipt["ready_projection_allowed"] is False
    assert receipt["provider_jobs_attempted"] == 0
    assert receipt["provider_credits_consumed"] == 0


@pytest.mark.parametrize("prefix", ["5a1c238", "a665e4e9"])
def test_known_rejected_walkthrough_hash_families_remain_permanently_disqualified(prefix: str) -> None:
    artifact_sha256 = prefix + ("0" * (64 - len(prefix)))

    receipt = GovernedSpatialQualityService().audit_walkthrough(
        _walkthrough_metrics(artifact_sha256=artifact_sha256),
        observed_at=OBSERVED_AT,
    )

    assert receipt["status"] == "disqualified"
    assert receipt["disqualified_reason"] == f"permanently_disqualified_artifact_hash_prefix:{prefix}"
    assert receipt["ready_projection_allowed"] is False


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        (lambda metrics: metrics.update({"cut_count": 1}), "cut_count_must_be_zero"),
        (
            lambda metrics: metrics.update({"covered_room_count": 6}),
            "required_room_coverage_must_be_100_percent",
        ),
        (
            lambda metrics: metrics.update({"container_fps": 60.0, "effective_motion_fps": 24.0}),
            "effective_motion_frame_rate_below_30",
        ),
        (
            lambda metrics: metrics.update({"max_duplicate_frame_run_during_motion": 3}),
            "duplicate_frame_run_exceeds_two",
        ),
        (
            lambda metrics: metrics.update({"all_frame_continuity_max_delta": 18.1}),
            "all_frame_continuity_max_delta_exceeds_18",
        ),
        (
            lambda metrics: metrics.update(
                {"spatial_drift_gate": {"status": "fail", "proof_ref": "proof:spatial-drift:fixture:v1"}}
            ),
            "spatial_drift_gate_proof_required",
        ),
    ],
)
def test_walkthrough_quality_fails_bad_final_artifact_metrics(mutation: object, issue: str) -> None:
    metrics = _walkthrough_metrics()
    assert callable(mutation)
    mutation(metrics)

    receipt = GovernedSpatialQualityService().audit_walkthrough(metrics, observed_at=OBSERVED_AT)

    assert receipt["status"] == "fail"
    assert issue in receipt["issues"]
    assert receipt["ready_projection_allowed"] is False


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("container_fps", float("nan"), "numeric_metric_not_finite:container_fps"),
        (
            "all_frame_continuity_max_delta",
            float("inf"),
            "numeric_metric_not_finite:all_frame_continuity_max_delta",
        ),
        ("cut_count", 0.9, "count_metric_invalid:cut_count"),
        (
            "max_duplicate_frame_run_during_motion",
            -1,
            "count_metric_invalid:max_duplicate_frame_run_during_motion",
        ),
    ],
)
def test_walkthrough_quality_rejects_nonfinite_fractional_or_negative_metrics(
    field: str,
    value: object,
    issue: str,
) -> None:
    metrics = _walkthrough_metrics()
    metrics[field] = value

    receipt = GovernedSpatialQualityService().audit_walkthrough(metrics, observed_at=OBSERVED_AT)

    assert receipt["status"] == "fail"
    assert issue in receipt["issues"]
    assert receipt["ready_projection_allowed"] is False
    assert "NaN" not in str(receipt["metrics"])
    assert "Infinity" not in str(receipt["metrics"])


def test_combat_walkthrough_requires_stable_actor_identity_and_transform() -> None:
    metrics = _walkthrough_metrics()
    metrics.update(
        {
            "combat_overlay_count": 1,
            "stable_actor_identity": False,
            "stable_actor_transform": False,
        }
    )

    receipt = GovernedSpatialQualityService().audit_walkthrough(metrics, observed_at=OBSERVED_AT)

    assert "stable_actor_identity_required" in receipt["issues"]
    assert "stable_actor_transform_required" in receipt["issues"]


def test_interactive_quality_contract_enforces_baseline_browser_thresholds_without_readiness() -> None:
    receipt = GovernedSpatialQualityService().audit_interactive(
        _interactive_metrics(),
        observed_at=OBSERVED_AT,
    )

    assert receipt["contract_name"] == INTERACTIVE_QUALITY_RECEIPT_CONTRACT
    assert receipt["status"] == "pass_local_quality_contract"
    assert receipt["issues"] == []
    assert receipt["launch_ready_allowed"] is False
    assert receipt["ready_projection_allowed"] is False


def test_interactive_quality_reports_measured_degradation_instead_of_lowering_gate() -> None:
    metrics = _interactive_metrics()
    metrics.update(
        {
            "median_desktop_fps": 54.9,
            "median_mobile_fps": 44.9,
            "minimum_control_width_css_px": 43.9,
            "sustained_frame_time_spike_count": 1,
        }
    )

    receipt = GovernedSpatialQualityService().audit_interactive(metrics, observed_at=OBSERVED_AT)

    assert receipt["status"] == "fail"
    assert "median_desktop_fps_below_55" in receipt["issues"]
    assert "median_mobile_fps_below_45" in receipt["issues"]
    assert "control_width_below_44" in receipt["issues"]
    assert "sustained_frame_time_spikes_detected" in receipt["issues"]


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("median_desktop_fps", float("nan"), "numeric_metric_not_finite:median_desktop_fps"),
        ("median_mobile_fps", float("inf"), "numeric_metric_not_finite:median_mobile_fps"),
        ("cut_count", 0.9, "count_metric_invalid:cut_count"),
        (
            "max_duplicate_frame_run_during_motion",
            -1,
            "count_metric_invalid:max_duplicate_frame_run_during_motion",
        ),
    ],
)
def test_interactive_quality_rejects_nonfinite_fractional_or_negative_metrics(
    field: str,
    value: object,
    issue: str,
) -> None:
    metrics = _interactive_metrics()
    metrics[field] = value

    receipt = GovernedSpatialQualityService().audit_interactive(metrics, observed_at=OBSERVED_AT)

    assert receipt["status"] == "fail"
    assert issue in receipt["issues"]
    assert receipt["ready_projection_allowed"] is False
    assert "NaN" not in str(receipt["metrics"])
    assert "Infinity" not in str(receipt["metrics"])
