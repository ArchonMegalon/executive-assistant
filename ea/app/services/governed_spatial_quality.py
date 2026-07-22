from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re

from app.services.governed_spatial_render import (
    DEFAULT_CAPABILITY_REGISTRY_PATH,
    DESIGN_AUTHORITY_STATUS,
)


WALKTHROUGH_QUALITY_RECEIPT_CONTRACT = "ea.governed_spatial_walkthrough_quality_receipt.v1"
INTERACTIVE_QUALITY_RECEIPT_CONTRACT = "ea.governed_spatial_interactive_quality_receipt.v1"
PUBLICATION_DECISION_CONTRACT = "governed_spatial_publication_decision_v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[dict[str, object]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [_clean(item) for item in value if _clean(item)] if isinstance(value, list) else []


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_iso(value: datetime | None = None) -> str:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("observed_at_offset_required")
    return resolved.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_ref(value: object) -> bool:
    normalized = _clean(value)
    return bool(normalized and "://" not in normalized and _REF_RE.fullmatch(normalized))


def _finite_number(
    value: object,
    *,
    minimum: float = 0.0,
    maximum: float,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < minimum or resolved > maximum:
        return None
    return resolved


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _numeric_integrity_issues(value: object, *, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = _clean(key)
            nested_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key.endswith("_count") or normalized_key in {
                "shot_count",
                "required_room_count",
                "covered_room_count",
                "max_duplicate_frame_run_during_motion",
            }:
                if _count(nested) is None:
                    issues.append(f"count_metric_invalid:{nested_path}")
            issues.extend(_numeric_integrity_issues(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            issues.extend(_numeric_integrity_issues(nested, path=f"{path}[{index}]"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        resolved = float(value)
        if not math.isfinite(resolved):
            issues.append(f"numeric_metric_not_finite:{path or 'value'}")
        elif resolved < 0:
            issues.append(f"numeric_metric_negative:{path or 'value'}")
    return issues


def _json_safe_metrics(value: object) -> object:
    if isinstance(value, Mapping):
        return {_clean(key): _json_safe_metrics(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe_metrics(nested) for nested in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "invalid_non_finite_number"
    return value


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


class GovernedSpatialQualityService:
    def __init__(
        self,
        *,
        capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY_PATH,
        immutable_artifact_verifier: Callable[[Mapping[str, object]], bool] | None = None,
    ) -> None:
        payload = json.loads(capability_registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("capability_registry_object_required")
        self._disqualified_hash_prefixes = {
            prefix.lower()
            for provider in _rows(payload.get("providers"))
            for prefix in _strings(provider.get("disqualified_artifact_prefixes"))
        }
        self._immutable_artifact_verifier = immutable_artifact_verifier

    @staticmethod
    def _base_issues(metrics: dict[str, object]) -> tuple[str, list[str]]:
        issues: list[str] = []
        artifact_sha256 = _clean(metrics.get("artifact_sha256")).lower()
        if not _SHA256_RE.fullmatch(artifact_sha256):
            issues.append("artifact_sha256_invalid")
        if metrics.get("final_encoded_artifact") is not True:
            issues.append("final_encoded_artifact_required")
        provenance_refs = _strings(metrics.get("provenance_refs"))
        if not provenance_refs or not all(_safe_ref(value) for value in provenance_refs):
            issues.append("artifact_provenance_required")
        return artifact_sha256, issues

    @staticmethod
    def _receipt(
        *,
        contract_name: str,
        artifact_sha256: str,
        metrics: dict[str, object],
        issues: list[str],
        disqualified_reason: str,
        observed_at: datetime | None,
    ) -> dict[str, object]:
        status = "disqualified" if disqualified_reason else ("fail" if issues else "pass_local_quality_contract")
        safe_metrics = _json_safe_metrics(metrics)
        body = {
            "contract_name": contract_name,
            "contract_version": "2026-07-11-draft",
            "generated_at": _utc_iso(observed_at),
            "status": status,
            "design_authority_status": DESIGN_AUTHORITY_STATUS,
            "artifact_sha256": artifact_sha256,
            "metrics_digest": _sha256_json(safe_metrics),
            "issues": _unique(issues),
            "disqualified_reason": disqualified_reason,
            "metrics": deepcopy(safe_metrics),
            "launch_ready_allowed": False,
            "ready_projection_allowed": False,
            "provider_jobs_attempted": 0,
            "provider_credits_consumed": 0,
        }
        return {**body, "receipt_digest": _sha256_json(body)}

    def audit_walkthrough(
        self,
        metrics: Mapping[str, object],
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized = dict(metrics)
        artifact_sha256, issues = self._base_issues(normalized)
        issues.extend(_numeric_integrity_issues(normalized))
        disqualified_prefix = next(
            (prefix for prefix in self._disqualified_hash_prefixes if artifact_sha256.startswith(prefix)),
            "",
        )
        disqualified_reason = (
            f"permanently_disqualified_artifact_hash_prefix:{disqualified_prefix}" if disqualified_prefix else ""
        )
        if normalized.get("all_frames_evaluated") is not True:
            issues.append("all_frames_evaluation_required")
        if _count(normalized.get("shot_count")) != 1:
            issues.append("shot_count_invalid_or_not_one")
        for field in (
            "cut_count",
            "teleport_count",
            "collision_failure_count",
            "wall_or_door_clip_count",
            "black_burst_count",
            "blank_burst_count",
            "frozen_burst_count",
            "corrupt_burst_count",
            "repeated_frame_burst_count",
        ):
            count = _count(normalized.get(field))
            if count is None:
                issues.append(f"{field}_invalid")
            elif count != 0:
                issues.append(f"{field}_must_be_zero")
        required_rooms = _count(normalized.get("required_room_count"))
        covered_rooms = _count(normalized.get("covered_room_count"))
        if required_rooms is None:
            issues.append("required_room_count_invalid")
        if covered_rooms is None:
            issues.append("covered_room_count_invalid")
        coverage_percent = (
            covered_rooms / required_rooms * 100.0
            if required_rooms is not None and covered_rooms is not None and required_rooms > 0
            else 0.0
        )
        normalized["room_coverage_percent"] = round(coverage_percent, 3)
        if required_rooms is None or covered_rooms is None or required_rooms <= 0 or covered_rooms != required_rooms:
            issues.append("required_room_coverage_must_be_100_percent")
        topology_percent = _finite_number(normalized.get("stable_room_topology_percent"), maximum=100.0)
        if topology_percent != 100.0:
            issues.append("stable_room_topology_must_be_100_percent")
        if normalized.get("stable_furniture_on_revisit") is not True:
            issues.append("stable_furniture_on_revisit_required")
        combat_overlay_count = _count(normalized.get("combat_overlay_count"))
        if combat_overlay_count is None:
            issues.append("combat_overlay_count_invalid")
        elif combat_overlay_count > 0:
            if normalized.get("stable_actor_identity") is not True:
                issues.append("stable_actor_identity_required")
            if normalized.get("stable_actor_transform") is not True:
                issues.append("stable_actor_transform_required")
        container_fps = _finite_number(normalized.get("container_fps"), maximum=480.0)
        if container_fps is None:
            issues.append("delivery_frame_rate_invalid")
        elif container_fps < 60.0:
            issues.append("delivery_frame_rate_below_60")
        effective_motion_fps = _finite_number(normalized.get("effective_motion_fps"), maximum=480.0)
        if effective_motion_fps is None:
            issues.append("effective_motion_frame_rate_invalid")
        elif effective_motion_fps < 30.0:
            issues.append("effective_motion_frame_rate_below_30")
        duplicate_run = _count(normalized.get("max_duplicate_frame_run_during_motion"))
        if duplicate_run is None:
            issues.append("max_duplicate_frame_run_invalid")
        elif duplicate_run > 2:
            issues.append("duplicate_frame_run_exceeds_two")
        maximum_delta = _finite_number(normalized.get("all_frame_continuity_max_delta"), maximum=255.0)
        if maximum_delta is None:
            issues.append("all_frame_continuity_max_delta_invalid")
        elif maximum_delta > 18.0:
            issues.append("all_frame_continuity_max_delta_exceeds_18")
        for gate in ("rotation_gate", "spatial_drift_gate"):
            gate_payload = _dict(normalized.get(gate))
            if _clean(gate_payload.get("status")) != "pass" or not _safe_ref(gate_payload.get("proof_ref")):
                issues.append(f"{gate}_proof_required")
        for field in ("desktop_decode_pass", "mobile_decode_pass"):
            if normalized.get(field) is not True:
                issues.append(field)
        for field in ("horizontal_overflow", "layout_shift_detected"):
            if normalized.get(field) is not False:
                issues.append(f"{field}_must_be_false")
        if normalized.get("audio_present") is True:
            if normalized.get("audio_sync_pass") is not True:
                issues.append("audio_sync_required")
            if normalized.get("audio_level_pass") is not True:
                issues.append("audio_level_required")
        return self._receipt(
            contract_name=WALKTHROUGH_QUALITY_RECEIPT_CONTRACT,
            artifact_sha256=artifact_sha256,
            metrics=normalized,
            issues=issues,
            disqualified_reason=disqualified_reason,
            observed_at=observed_at,
        )

    def audit_interactive(
        self,
        metrics: Mapping[str, object],
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized = dict(metrics)
        artifact_sha256, issues = self._base_issues(normalized)
        issues.extend(_numeric_integrity_issues(normalized))
        if normalized.get("same_origin") is not True:
            issues.append("same_origin_required")
        if normalized.get("nonblank_canvas") is not True:
            issues.append("nonblank_canvas_required")
        desktop_fps = _finite_number(normalized.get("median_desktop_fps"), maximum=480.0)
        if desktop_fps is None:
            issues.append("median_desktop_fps_invalid")
        elif desktop_fps < 55.0:
            issues.append("median_desktop_fps_below_55")
        mobile_fps = _finite_number(normalized.get("median_mobile_fps"), maximum=480.0)
        if mobile_fps is None:
            issues.append("median_mobile_fps_invalid")
        elif mobile_fps < 45.0:
            issues.append("median_mobile_fps_below_45")
        spike_count = _count(normalized.get("sustained_frame_time_spike_count"))
        if spike_count is None:
            issues.append("sustained_frame_time_spike_count_invalid")
        elif spike_count != 0:
            issues.append("sustained_frame_time_spikes_detected")
        if normalized.get("horizontal_overflow") is not False:
            issues.append("horizontal_overflow_must_be_false")
        control_width = _finite_number(normalized.get("minimum_control_width_css_px"), maximum=10000.0)
        if control_width is None:
            issues.append("control_width_invalid")
        elif control_width < 44.0:
            issues.append("control_width_below_44")
        control_height = _finite_number(normalized.get("minimum_control_height_css_px"), maximum=10000.0)
        if control_height is None:
            issues.append("control_height_invalid")
        elif control_height < 44.0:
            issues.append("control_height_below_44")
        for field in (
            "keyboard_pass",
            "touch_pass",
            "labels_and_focus_pass",
            "reduced_motion_pass",
            "offline_recovery_pass",
            "retry_pass",
            "direct_open_pass",
            "back_navigation_pass",
            "desktop_decode_pass",
            "mobile_decode_pass",
        ):
            if normalized.get(field) is not True:
                issues.append(field)
        for field in ("desktop_browser_proof_ref", "mobile_browser_proof_ref", "baseline_device_profile_ref"):
            if not _safe_ref(normalized.get(field)):
                issues.append(f"{field}_required")
        return self._receipt(
            contract_name=INTERACTIVE_QUALITY_RECEIPT_CONTRACT,
            artifact_sha256=artifact_sha256,
            metrics=normalized,
            issues=issues,
            disqualified_reason="",
            observed_at=observed_at,
        )

    def evaluate_publication(
        self,
        *,
        output_digest: str,
        quality_receipt: Mapping[str, object],
        rights_state: str,
        provenance_refs: list[str],
        capability_state: str,
        publication_authorization: Mapping[str, object] | None,
        privacy_tombstone: Mapping[str, object] | None,
        immutable_artifact_decision: Mapping[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> dict[str, object]:
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("observed_at_offset_required")
        now = now.astimezone(UTC)
        issues: list[str] = []
        normalized_digest = output_digest.removeprefix("sha256:").lower()
        if not _SHA256_RE.fullmatch(normalized_digest):
            issues.append("output_digest_invalid")
        quality_contract = _clean(quality_receipt.get("contract_name"))
        if quality_contract not in {
            WALKTHROUGH_QUALITY_RECEIPT_CONTRACT,
            INTERACTIVE_QUALITY_RECEIPT_CONTRACT,
        }:
            issues.append("quality_receipt_contract_invalid")
        supplied_receipt_digest = _clean(quality_receipt.get("receipt_digest")).removeprefix("sha256:")
        quality_body = deepcopy(dict(quality_receipt))
        quality_body.pop("receipt_digest", None)
        try:
            computed_receipt_digest = _sha256_json(quality_body)
        except (TypeError, ValueError):
            computed_receipt_digest = ""
        if (
            not _SHA256_RE.fullmatch(supplied_receipt_digest)
            or supplied_receipt_digest != computed_receipt_digest
        ):
            issues.append("quality_receipt_digest_invalid")
        quality_digest = _clean(quality_receipt.get("artifact_sha256")).removeprefix("sha256:").lower()
        if quality_digest != normalized_digest:
            issues.append("quality_output_digest_mismatch")
        if quality_receipt.get("status") != "pass_local_quality_contract":
            issues.append("quality_gate_not_passed")
        if quality_receipt.get("ready_projection_allowed") is not False:
            issues.append("quality_receipt_readiness_posture_invalid")
        if rights_state != "verified":
            issues.append("rights_not_verified")
        if not provenance_refs or not all(_safe_ref(value) for value in provenance_refs):
            issues.append("provenance_not_verified")
        if capability_state != "verified":
            issues.append("capability_not_verified")
        if privacy_tombstone is not None:
            issues.append("privacy_tombstone_active")

        immutable_decision = _dict(immutable_artifact_decision)
        immutable_decision_digest = ""
        if not immutable_decision:
            issues.append("immutable_artifact_decision_missing")
        elif self._immutable_artifact_verifier is None:
            issues.append("immutable_artifact_verifier_absent_launch_ceiling")
        else:
            immutable_binding_issues: list[str] = []
            expected_output_digest = (
                f"sha256:{normalized_digest}" if _SHA256_RE.fullmatch(normalized_digest) else ""
            )
            expected_quality_digest = (
                f"sha256:{supplied_receipt_digest}"
                if _SHA256_RE.fullmatch(supplied_receipt_digest)
                else ""
            )
            if immutable_decision.get("state") != "verified":
                immutable_binding_issues.append("immutable_artifact_decision_not_verified")
            if immutable_decision.get("output_digest") != expected_output_digest:
                immutable_binding_issues.append("immutable_artifact_output_binding_mismatch")
            if immutable_decision.get("quality_receipt_digest") != expected_quality_digest:
                immutable_binding_issues.append("immutable_artifact_quality_binding_mismatch")
            if not _safe_ref(immutable_decision.get("decision_ref")):
                immutable_binding_issues.append("immutable_artifact_decision_ref_invalid")
            issues.extend(immutable_binding_issues)
            if not immutable_binding_issues:
                try:
                    verifier_passed = self._immutable_artifact_verifier(deepcopy(immutable_decision)) is True
                except (TypeError, ValueError):
                    verifier_passed = False
                if not verifier_passed:
                    issues.append("immutable_artifact_decision_verification_failed")
            try:
                immutable_decision_digest = _sha256_json(immutable_decision)
            except (TypeError, ValueError):
                issues.append("immutable_artifact_decision_not_canonicalizable")

        authorization = _dict(publication_authorization)
        if authorization.get("state") != "authorized":
            issues.append("publication_authorization_missing")
        if not _safe_ref(authorization.get("lease_ref")):
            issues.append("publication_lease_ref_invalid")
        try:
            issued_at = datetime.fromisoformat(_clean(authorization.get("issued_at")).replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(_clean(authorization.get("expires_at")).replace("Z", "+00:00"))
            if issued_at.tzinfo is None or expires_at.tzinfo is None:
                raise ValueError("offset_required")
            if not issued_at <= now <= expires_at or expires_at <= issued_at:
                issues.append("publication_authorization_not_current")
        except ValueError:
            issues.append("publication_authorization_timestamps_invalid")

        issues.append("milestone_1_publication_authority_absent")

        decision_material = {
            "output_digest": f"sha256:{normalized_digest}" if _SHA256_RE.fullmatch(normalized_digest) else "",
            "quality_receipt_digest": _clean(quality_receipt.get("receipt_digest")),
            "immutable_artifact_decision_digest": immutable_decision_digest,
            "rights_state": rights_state,
            "capability_state": capability_state,
            "publication_lease_ref_digest": (
                hashlib.sha256(_clean(authorization.get("lease_ref")).encode("utf-8")).hexdigest()
                if authorization.get("lease_ref")
                else ""
            ),
            "privacy_tombstone_active": privacy_tombstone is not None,
            "issues": _unique(issues),
        }
        return {
            "contract_name": PUBLICATION_DECISION_CONTRACT,
            "generated_at": _utc_iso(now),
            "state": "blocked",
            "publication_allowed": False,
            "ready_projection_allowed": False,
            "issues": _unique(issues),
            "output_digest": decision_material["output_digest"],
            "provider_details_exposed": False,
            "decision_digest": _sha256_json(decision_material),
        }
