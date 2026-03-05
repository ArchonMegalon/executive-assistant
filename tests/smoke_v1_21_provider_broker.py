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


def test_provider_broker_module_presence() -> None:
    src = (ROOT / "ea/app/planner/provider_broker.py").read_text(encoding="utf-8")
    assert "def rank_task_capabilities(" in src
    assert "task_or_none" in src
    assert "score" in src
    _pass("v1.21 provider-broker module presence")


def test_provider_broker_ranking_behavior() -> None:
    _install_psycopg2_stub()
    from app.planner.provider_broker import rank_task_capabilities
    from app.skills.capability_router import build_capability_plan

    ranked = rank_task_capabilities(
        task_type="travel_rescue",
        candidates=["browseract", "avomap", "oneair"],
        preferred=None,
    )
    assert ranked and ranked[0]["capability"] == "oneair"
    assert any("task_priority" in list(row.get("reasons") or []) for row in ranked)

    pref_ranked = rank_task_capabilities(
        task_type="travel_rescue",
        candidates=["browseract", "avomap", "oneair"],
        preferred="avomap",
    )
    assert pref_ranked and pref_ranked[0]["capability"] == "avomap"
    assert "preferred_override" in list(pref_ranked[0].get("reasons") or [])

    plan = build_capability_plan("travel_rescue", preferred="avomap")
    assert plan.get("ok") is True
    assert plan.get("primary") == "avomap"
    ranking = list(plan.get("ranking") or [])
    assert ranking and str(ranking[0].get("capability")) == "avomap"
    _pass("v1.21 provider-broker ranking behavior")


if __name__ == "__main__":
    test_provider_broker_module_presence()
    test_provider_broker_ranking_behavior()
