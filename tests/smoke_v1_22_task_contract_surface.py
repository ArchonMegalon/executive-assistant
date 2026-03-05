from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


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


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_capability_task_surface_has_task_contracts() -> None:
    _install_psycopg2_stub()
    from app.planner.task_registry import task_or_none
    from app.skills.capability_registry import CAPABILITY_REGISTRY

    task_types: set[str] = set()
    for cap in CAPABILITY_REGISTRY.values():
        task_types.update({str(x or "").strip().lower() for x in cap.task_types if str(x or "").strip()})

    missing = sorted(t for t in task_types if task_or_none(t) is None)
    assert not missing, f"missing_task_contracts:{','.join(missing)}"
    _pass("v1.22 task-contract coverage over capability surface")


def test_capability_tasks_build_a_plan() -> None:
    _install_psycopg2_stub()
    from app.skills.capability_router import build_capability_plan
    from app.skills.capability_registry import CAPABILITY_REGISTRY

    task_types: set[str] = set()
    for cap in CAPABILITY_REGISTRY.values():
        task_types.update({str(x or "").strip().lower() for x in cap.task_types if str(x or "").strip()})

    for task_type in sorted(task_types):
        plan = build_capability_plan(task_type)
        assert bool(plan.get("ok")) is True, f"task_has_no_plan:{task_type}"
        assert str(plan.get("task_contract_key") or "") == task_type, f"task_contract_mismatch:{task_type}"
    _pass("v1.22 capability tasks produce task-contract plans")


if __name__ == "__main__":
    test_capability_task_surface_has_task_contracts()
    test_capability_tasks_build_a_plan()
