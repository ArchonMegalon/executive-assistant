from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_capability_router_module_presence() -> None:
    src = (ROOT / "ea/app/skills/capability_router.py").read_text(encoding="utf-8")
    assert "def build_capability_plan(" in src
    assert "_TASK_PRIORITY" in src
    _pass("v1.19.4 capability router module presence")


def test_capability_router_behavior() -> None:
    from app.skills.capability_router import build_capability_plan

    travel = build_capability_plan("travel_rescue")
    assert travel.get("ok") is True
    assert travel.get("primary") == "oneair"
    assert "avomap" in list(travel.get("fallbacks") or [])

    intake = build_capability_plan("collect_structured_intake", preferred="metasurvey")
    assert intake.get("ok") is True
    assert intake.get("primary") == "metasurvey"
    assert "involve_me" in list(intake.get("fallbacks") or [])

    trip_pack = build_capability_plan("trip_context_pack")
    assert trip_pack.get("ok") is True
    assert trip_pack.get("primary") == "oneair"
    assert "avomap" in list(trip_pack.get("fallbacks") or [])

    missing = build_capability_plan("unknown_task_zzz")
    assert missing.get("ok") is False
    assert missing.get("status") == "no_capability_for_task"

    _pass("v1.19.4 capability router behavior")


if __name__ == "__main__":
    test_capability_router_module_presence()
    test_capability_router_behavior()
