from __future__ import annotations

from app.integrations.avomap.specs import TravelVideoSpec


def build_browseract_payload(spec: TravelVideoSpec, workflow_name: str) -> dict:
    return {
        "platform": "avomap",
        "task": "render_trip_video",
        "workflow": workflow_name,
        "headless": True,
        "data": {
            "spec_id": spec.cache_key,
            "tenant": spec.tenant,
            "person_id": spec.person_id,
            "date_key": spec.date_key,
            "mode": spec.mode,
            "orientation": spec.orientation,
            "duration_target_sec": spec.duration_target_sec,
            "route_json": spec.route_json,
            "markers_json": spec.markers_json,
            # Preferred path: GPX/KML import mode for deterministic route setup.
            "import_mode": "gpx_kml_preferred",
        },
    }
