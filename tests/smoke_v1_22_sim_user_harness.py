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


def test_sim_user_compose_wiring() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ea-sim-user:" in compose
    assert "- qa" in compose
    assert "app.sim_user.runner" in compose
    assert "- ./qa:/app/qa:ro" in compose
    _pass("v1.22 sim-user compose wiring")


def test_sim_user_scenario_contract() -> None:
    from app.sim_user.runner import load_scenarios, run_contract_check

    scenarios = load_scenarios(str(ROOT / "qa/scenarios"))
    ids = {str(x.get("scenario_id") or "") for x in scenarios}
    assert "cooperative_user" in ids
    assert "adversarial_confused_user" in ids
    for row in scenarios:
        expected = row.get("expected") or {}
        assert str(expected.get("task_type") or "").strip()
        assert str(expected.get("artifact_type") or "").strip()
    result = run_contract_check(str(ROOT / "qa/scenarios"))
    assert int(result.get("scenario_count") or 0) >= 2
    _pass("v1.22 sim-user scenario contract")


if __name__ == "__main__":
    test_sim_user_compose_wiring()
    test_sim_user_scenario_contract()
