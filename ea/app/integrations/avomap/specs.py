from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

ALLOWED_MODES = {"arrival", "day_route", "context_overview"}
ALLOWED_ORIENTATIONS = {"portrait", "landscape", "square"}


@dataclass(frozen=True)
class TravelVideoSpec:
    tenant: str
    person_id: str
    date_key: str
    mode: str
    orientation: str
    duration_target_sec: int
    route_json: dict[str, Any]
    markers_json: list[dict[str, Any]]
    signal_json: dict[str, Any]
    cache_key: str


def build_cache_key(
    *,
    route_json: dict[str, Any],
    markers_json: list[dict[str, Any]],
    mode: str,
    orientation: str,
    duration_target_sec: int,
) -> str:
    payload = {
        "route_json": route_json,
        "markers_json": markers_json,
        "mode": mode,
        "orientation": orientation,
        "duration_target_sec": int(duration_target_sec),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_spec(spec: TravelVideoSpec) -> list[str]:
    errs: list[str] = []
    if not str(spec.tenant).strip():
        errs.append("tenant_required")
    if not str(spec.person_id).strip():
        errs.append("person_id_required")
    if not str(spec.date_key).strip():
        errs.append("date_key_required")
    if spec.mode not in ALLOWED_MODES:
        errs.append("invalid_mode")
    if spec.orientation not in ALLOWED_ORIENTATIONS:
        errs.append("invalid_orientation")
    if int(spec.duration_target_sec) <= 0:
        errs.append("duration_target_sec_invalid")
    if not isinstance(spec.route_json, dict):
        errs.append("route_json_invalid")
    if not isinstance(spec.markers_json, list):
        errs.append("markers_json_invalid")
    if not isinstance(spec.signal_json, dict):
        errs.append("signal_json_invalid")
    if not str(spec.cache_key).strip():
        errs.append("cache_key_required")
    return errs
