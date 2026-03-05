from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def _install_psycopg2_stub() -> None:
    if "psycopg2" in sys.modules:
        return
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_pool_mod = types.ModuleType("psycopg2.pool")
    fake_extras_mod = types.ModuleType("psycopg2.extras")

    class _ThreadedConnectionPool:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def getconn(self):
            raise RuntimeError("psycopg2 stub: no db connection available")

        def putconn(self, conn) -> None:
            return None

    fake_pool_mod.ThreadedConnectionPool = _ThreadedConnectionPool
    fake_psycopg2.pool = fake_pool_mod
    fake_extras_mod.RealDictCursor = object
    sys.modules["psycopg2"] = fake_psycopg2
    sys.modules["psycopg2.pool"] = fake_pool_mod
    sys.modules["psycopg2.extras"] = fake_extras_mod


def test_task_registry_module_and_contracts_present() -> None:
    src = (ROOT / "ea/app/planner/task_registry.py").read_text(encoding="utf-8")
    assert "class TaskContract" in src
    assert "TASK_REGISTRY" in src
    assert "travel_rescue" in src
    assert "trip_context_pack" in src
    assert "collect_structured_intake" in src
    assert "typed_safe_action" in src
    assert "run_secondary_research_pass" in src
    assert "bridge_external_event" in src
    assert "approval_router" in src
    _pass("v1.21 task-contract registry module presence")


def test_capability_router_uses_task_contract_priority() -> None:
    _install_psycopg2_stub()
    from app.planner.task_registry import list_task_contracts, task_or_raise
    from app.skills.capability_router import build_capability_plan

    contracts = list_task_contracts()
    assert contracts and any(str(row.get("key")) == "travel_rescue" for row in contracts)
    travel_contract = task_or_raise("travel_rescue")
    assert list(travel_contract.provider_priority)[:2] == ["oneair", "avomap"]

    travel_plan = build_capability_plan("travel_rescue")
    assert bool(travel_plan.get("ok")) is True
    assert str(travel_plan.get("task_contract_key")) == "travel_rescue"
    assert str(travel_plan.get("task_contract_output_artifact_type")) == "travel_decision_pack"
    assert str(travel_plan.get("primary")) in set(travel_contract.provider_priority)

    tone_plan = build_capability_plan("polish_human_tone")
    assert bool(tone_plan.get("ok")) is True
    assert str(tone_plan.get("task_contract_key")) == "polish_human_tone"
    assert str(tone_plan.get("task_contract_approval_default")) == "none"

    approval_plan = build_capability_plan("approval_router")
    assert bool(approval_plan.get("ok")) is True
    assert str(approval_plan.get("primary")) == "approvethis"
    assert str(approval_plan.get("task_contract_approval_default")) == "explicit_callback_required"

    bridge_plan = build_capability_plan("bridge_external_event")
    assert bool(bridge_plan.get("ok")) is True
    assert str(bridge_plan.get("primary")) in {"apix_drive", "browseract"}
    _pass("v1.21 task-contract capability planning behavior")


if __name__ == "__main__":
    test_task_registry_module_and_contracts_present()
    test_capability_router_uses_task_contract_priority()
