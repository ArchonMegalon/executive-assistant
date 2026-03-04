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


def test_skill_inventory_contract() -> None:
    from app.skills.registry import SKILL_REGISTRY, list_skills

    expected = {
        "payments",
        "travel_rescue",
        "guided_intake",
        "draft_and_polish",
        "prompt_compiler",
        "multimodal_burst",
        "evidence_pack_builder",
        "trip_context_pack",
    }
    missing = [key for key in sorted(expected) if key not in SKILL_REGISTRY]
    assert not missing, f"missing skills: {missing}"
    rows = list_skills()
    keys = {str(row.get("key")) for row in rows}
    assert expected.issubset(keys)
    _pass("v1.19.4 skill inventory contract")


def test_generic_skill_dispatch_contract() -> None:
    from app.skills.router import dispatch_skill_operation

    out = dispatch_skill_operation(
        skill_key="travel_rescue",
        operation="plan",
        tenant="chat_100284",
        chat_id=123,
        payload={"trip_id": "demo"},
    )
    assert out.get("ok") is False
    assert out.get("status") == "not_implemented"
    assert out.get("skill") == "travel_rescue"
    assert "oneair" in list(out.get("capabilities") or [])
    plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
    assert plan.get("ok") is True
    assert plan.get("primary") == "oneair"
    assert "avomap" in list(plan.get("fallbacks") or [])
    _pass("v1.19.4 generic skill dispatch contract")


if __name__ == "__main__":
    test_skill_inventory_contract()
    test_generic_skill_dispatch_contract()
