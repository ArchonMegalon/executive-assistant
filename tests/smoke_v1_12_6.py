from __future__ import annotations

import os
import importlib.util
import runpy
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def _print_pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}", flush=True)


def test_opsec_fuzzing() -> None:
    from app.integrations.avomap.sanitizer import sanitize_route_for_export

    stops = [
        {"label": "Tibor Home", "city": "Vienna", "country": "AT", "lat": 48.2082, "lon": 16.3738},
        {"label": "Secret M&A Meeting", "city": "London", "country": "GB", "lat": 51.5074, "lon": -0.1278},
    ]
    sanitized = sanitize_route_for_export(stops, home_base={"lat": 48.2082, "lon": 16.3738})
    assert sanitized[0]["label"] == "Origin"
    assert sanitized[1]["label"] == "Destination"
    # home waypoint must be obfuscated
    assert abs(float(sanitized[0]["lat"]) - 48.2082) > 0.00001
    assert abs(float(sanitized[0]["lon"]) - 16.3738) > 0.00001
    _print_pass("test_opsec_fuzzing")


def test_semantic_cache_hit() -> None:
    from app.integrations.avomap.specs import build_cache_key

    route_a = {
        "stops": [
            {"label": "Origin", "city": "Vienna", "country": "AT", "lat": 48.20111, "lon": 16.36333},
            {"label": "Destination", "city": "Zurich", "country": "CH", "lat": 47.37690, "lon": 8.54170},
        ]
    }
    route_b = {
        "stops": [
            {"label": "Origin", "city": "Vienna", "country": "AT", "lat": 48.20189, "lon": 16.36401},
            {"label": "Destination", "city": "Zurich", "country": "CH", "lat": 47.37712, "lon": 8.54208},
        ]
    }
    k1 = build_cache_key(
        route_json=route_a,
        markers_json=route_a["stops"],
        mode="arrival",
        orientation="portrait",
        duration_target_sec=20,
    )
    k2 = build_cache_key(
        route_json=route_b,
        markers_json=route_b["stops"],
        mode="arrival",
        orientation="portrait",
        duration_target_sec=20,
    )
    assert k1 == k2
    _print_pass("test_semantic_cache_hit")


def test_telegram_size_guard() -> None:
    media_path = EA_ROOT / "app/telegram/media.py"
    spec = importlib.util.spec_from_file_location("ea_telegram_media_smoke", media_path)
    assert spec and spec.loader, "telegram media module missing"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TELEGRAM_MAX_UPLOAD_BYTES = int(getattr(mod, "TELEGRAM_MAX_UPLOAD_BYTES"))
    enforce_video_size_limit = getattr(mod, "enforce_video_size_limit")

    with tempfile.TemporaryDirectory(prefix="ea_v126_media_") as td:
        src = Path(td) / "big.mp4"
        # Sparse file: > 60MB without costly writes
        with open(src, "wb") as f:
            f.seek((60 * 1024 * 1024) - 1)
            f.write(b"\0")
        out_path, meta = enforce_video_size_limit(str(src), max_bytes=TELEGRAM_MAX_UPLOAD_BYTES, dry_run=True)
        assert meta.get("action") == "transcode"
        assert str(out_path).endswith("_tg_1080p.mp4")
    _print_pass("test_telegram_size_guard")


def test_webhook_auth_rejection() -> None:
    from app.integrations.avomap.security import sign_webhook_body, verify_webhook_signature

    body = b'{"status":"completed","spec_id":"abc"}'
    secret = "unit-test-secret"
    good = sign_webhook_body(secret, body)
    assert verify_webhook_signature(secret, body, good) is True
    assert verify_webhook_signature(secret, body, None) is False
    assert verify_webhook_signature(secret, body, "sha256=deadbeef") is False
    _print_pass("test_webhook_auth_rejection")


def test_budget_exhaustion() -> None:
    # Host-safe import path without psycopg2: inject a minimal app.db module.
    fake_db_module = types.ModuleType("app.db")
    fake_db_module.get_db = lambda: None
    sys.modules["app.db"] = fake_db_module

    from app.integrations.avomap.service import AvoMapService
    from app.settings import settings

    class FakeDB:
        def __init__(self) -> None:
            self.exec_calls: list[tuple[str, tuple]] = []

        def fetchall(self, q: str, params: tuple) -> list[dict]:
            if "FROM travel_place_history" in q:
                return []
            return []

        def fetchone(self, q: str, params: tuple) -> dict | None:
            if "SELECT renders_used" in q:
                return {"renders_used": 0}
            if "SUM(renders_used)" in q:
                return {"total_used": int(settings.avomap_daily_render_budget)}
            if "FROM avomap_assets" in q:
                return None
            if "FROM travel_video_specs" in q and "SELECT spec_id, status" in q:
                return None
            return None

        def execute(self, q: str, params: tuple) -> None:
            self.exec_calls.append((q, params))

    svc = AvoMapService(FakeDB(), enabled=True)
    decision = svc.plan_for_briefing(
        tenant="smoke_budget",
        person_id="p1",
        date_key="2026-03-03",
        day_context={
            "home_base": {"lat": 48.2082, "lon": 16.3738},
            "route_stops": [
                {"label": "Origin", "city": "Vienna", "country": "AT"},
                {"label": "Destination", "city": "Zurich", "country": "CH"},
            ],
            "travel_email_hints": ["flight booking"],
        },
    )
    assert decision.get("status") == "budget_exhausted", decision
    _print_pass("test_budget_exhaustion")


def test_day_context_quality() -> None:
    from app.integrations.avomap.service import build_day_context

    ctx = build_day_context(
        calendar_events=[
            {"location": "Hilton Vienna Park, Vienna, Austria", "summary": "Client day"},
            {"summary": "Flight to Zurich Airport"},
            {"summary": "Weekly Team Sync"},  # non-travel and no location: should be ignored
        ],
        travel_emails=[{"subject": "Itinerary", "snippet": "Boarding pass and hotel check-in details"}],
    )

    stops = [s for s in (ctx.get("route_stops") or []) if isinstance(s, dict)]
    hints = [str(h) for h in (ctx.get("travel_email_hints") or [])]
    assert len(stops) >= 2, stops
    cities = [str(s.get("city") or "").lower() for s in stops]
    assert any("vienna" in c for c in cities), cities
    assert any("zurich" in c for c in cities), cities
    assert not any("weekly team sync" in str(s.get("label") or "").lower() for s in stops), stops
    assert len(hints) >= 1, hints
    _print_pass("test_day_context_quality")


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("smoke_v1_12_6_avomap.py")), run_name="__main__")
    test_opsec_fuzzing()
    test_semantic_cache_hit()
    test_telegram_size_guard()
    test_webhook_auth_rejection()
    test_budget_exhaustion()
    test_day_context_quality()
