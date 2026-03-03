from __future__ import annotations

import math
from typing import Any

TRAVEL_KEYWORDS = (
    "flight",
    "hotel",
    "airport",
    "rail",
    "train",
    "offsite",
    "conference",
    "trip",
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _stop_key(stop: dict[str, Any]) -> str:
    if stop.get("place_key"):
        return str(stop["place_key"]).strip().lower()
    city = str(stop.get("city") or "").strip().lower()
    country = str(stop.get("country") or "").strip().lower()
    label = str(stop.get("label") or "").strip().lower()
    if city or country:
        return f"{city}|{country}"
    return label


def detect_new_place(
    day_context: dict[str, Any],
    recent_place_keys: set[str],
    *,
    min_distance_km: int = 100,
) -> dict[str, Any]:
    route_stops = [s for s in (day_context.get("route_stops") or []) if isinstance(s, dict)]
    hints = [str(x).lower() for x in (day_context.get("travel_email_hints") or [])]

    has_trip_hint = any(any(k in h for k in TRAVEL_KEYWORDS) for h in hints)
    stop_keys = [_stop_key(s) for s in route_stops]
    unique_stops = [k for k in dict.fromkeys(stop_keys) if k]

    unseen_stop = any(k not in recent_place_keys for k in unique_stops)
    base = day_context.get("home_base") or {}
    far_from_base = False
    if route_stops and isinstance(base, dict):
        try:
            lat1 = float(base.get("lat"))
            lon1 = float(base.get("lon"))
            lat2 = float(route_stops[0].get("lat"))
            lon2 = float(route_stops[0].get("lon"))
            far_from_base = _haversine_km(lat1, lon1, lat2, lon2) >= float(min_distance_km)
        except Exception:
            far_from_base = False

    if not route_stops and not has_trip_hint:
        return {"mode": "none", "is_novel": False, "reason": "no_route_or_trip_signal"}
    if not unseen_stop and not far_from_base and not has_trip_hint:
        return {"mode": "none", "is_novel": False, "reason": "not_novel_enough"}

    if len(unique_stops) >= 3:
        mode = "day_route"
    elif len(unique_stops) >= 1:
        mode = "arrival"
    else:
        mode = "context_overview"

    score = 0.0
    if unseen_stop:
        score += 0.45
    if far_from_base:
        score += 0.35
    if has_trip_hint:
        score += 0.20
    return {
        "mode": mode,
        "is_novel": True,
        "reason": "novel_trip_day",
        "novelty_score": round(min(score, 1.0), 3),
        "unique_stops": unique_stops,
    }
