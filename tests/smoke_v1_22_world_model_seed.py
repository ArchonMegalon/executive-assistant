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


class _FakeDB:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, object]] = []
        self.fetchone_calls: list[tuple[str, object]] = []

    def execute(self, query: str, vars=None) -> None:
        self.execute_calls.append((str(query), vars))

    def fetchone(self, query: str, vars=None):
        q = str(query)
        self.fetchone_calls.append((q, vars))
        if "RETURNING artifact_id" in q:
            return {"artifact_id": "art-1"}
        if "RETURNING followup_id" in q:
            return {"followup_id": "fol-1"}
        if "RETURNING decision_window_id" in q:
            return {"decision_window_id": "win-1"}
        return {}


def test_world_model_seed_contract_presence() -> None:
    db_src = (ROOT / "ea/app/db.py").read_text(encoding="utf-8")
    module_src = (ROOT / "ea/app/planner/world_model.py").read_text(encoding="utf-8")
    migration = ROOT / "ea/schema/20260305_v1_22_commitment_runtime_seed.sql"
    assert "CREATE TABLE IF NOT EXISTS commitments" in db_src
    assert "CREATE TABLE IF NOT EXISTS artifacts" in db_src
    assert "CREATE TABLE IF NOT EXISTS followups" in db_src
    assert "CREATE TABLE IF NOT EXISTS decision_windows" in db_src
    assert "def upsert_commitment(" in module_src
    assert "def create_artifact(" in module_src
    assert "def create_followup(" in module_src
    assert "def create_decision_window(" in module_src
    assert migration.exists(), "missing commitment-runtime seed migration"
    _pass("v1.22 world-model seed contract presence")


def test_world_model_seed_behavior() -> None:
    _install_psycopg2_stub()
    import app.planner.world_model as wm

    fake = _FakeDB()
    orig_get_db = wm._get_db
    wm._get_db = lambda: fake
    try:
        ok = wm.upsert_commitment(
            tenant_key="chat_100284",
            commitment_key="travel:chat_100284:abc123",
            domain="travel",
            title="Zurich family trip",
            metadata={"value_eur": 15000},
        )
        artifact_id = wm.create_artifact(
            tenant_key="chat_100284",
            session_id="sess-1",
            commitment_key="travel:chat_100284:abc123",
            artifact_type="travel_decision_pack",
            summary="Travel options summary",
            content={"options": ["keep", "reroute"]},
        )
        followup_id = wm.create_followup(
            tenant_key="chat_100284",
            commitment_key="travel:chat_100284:abc123",
            artifact_id=artifact_id,
            notes="Review airline options today",
        )
        window_id = wm.create_decision_window(
            tenant_key="chat_100284",
            commitment_key="travel:chat_100284:abc123",
            window_label="Rebooking window",
            closes_at="2026-03-06T17:00:00+01:00",
        )
    finally:
        wm._get_db = orig_get_db

    assert ok is True
    assert artifact_id == "art-1"
    assert followup_id == "fol-1"
    assert window_id == "win-1"
    assert fake.execute_calls, "expected upsert execute call"
    assert fake.fetchone_calls, "expected insert returning calls"
    _pass("v1.22 world-model seed behavior")


if __name__ == "__main__":
    test_world_model_seed_contract_presence()
    test_world_model_seed_behavior()
