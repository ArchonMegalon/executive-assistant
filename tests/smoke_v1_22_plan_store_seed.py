from __future__ import annotations

import asyncio
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


def test_plan_store_module_presence() -> None:
    src = (ROOT / "ea/app/planner/plan_store.py").read_text(encoding="utf-8")
    step_src = (ROOT / "ea/app/planner/step_executor.py").read_text(encoding="utf-8")
    assert "def fetch_session_plan_steps(" in src
    assert "def resolve_execute_step_metadata(" in src
    assert "resolve_execute_step_metadata" in step_src
    _pass("v1.22 plan-store module presence")


def test_plan_store_behavior_and_step_executor_fallback() -> None:
    _install_psycopg2_stub()
    import app.planner.plan_store as store
    import app.planner.step_executor as step_exec

    class _FakeDB:
        def fetchall(self, query: str, vars=None):
            return [
                {
                    "step_order": 1,
                    "step_key": "compile_intent",
                    "step_title": "Compile Intent",
                    "step_kind": "compile",
                    "status": "completed",
                    "preconditions_json": {},
                    "evidence_json": {},
                    "result_json": {},
                    "provider_key": "",
                    "input_refs_json": [],
                    "output_refs_json": [],
                    "attempt_count": 0,
                    "deadline_at": None,
                    "approval_gate_id": None,
                },
                {
                    "step_order": 2,
                    "step_key": "execute_intent",
                    "step_title": "Execute Intent",
                    "step_kind": "execution",
                    "status": "queued",
                    "preconditions_json": {},
                    "evidence_json": {
                        "task_type": "run_secondary_research_pass",
                        "output_artifact_type": "research_pack",
                        "provider_candidates": ["paperguide", "vizologi"],
                    },
                    "result_json": {},
                    "provider_key": "paperguide",
                    "input_refs_json": [],
                    "output_refs_json": [],
                    "attempt_count": 0,
                    "deadline_at": None,
                    "approval_gate_id": None,
                },
            ]

        def fetchone(self, query: str, vars=None):
            return {
                "evidence_json": {
                    "task_type": "run_secondary_research_pass",
                    "output_artifact_type": "research_pack",
                    "provider_candidates": ["paperguide", "vizologi"],
                },
                "provider_key": "paperguide",
            }

    fake_db = _FakeDB()
    orig_get_db_store = store._get_db
    store._get_db = lambda: fake_db
    try:
        rows = store.fetch_session_plan_steps("sess-42")
        assert len(rows) == 2
        meta = store.resolve_execute_step_metadata("sess-42", fallback={"task_type": "free_text_response"})
        assert str(meta.get("task_type") or "") == "run_secondary_research_pass"
        assert str(meta.get("output_artifact_type") or "") == "research_pack"
        assert list(meta.get("provider_candidates") or [])[:1] == ["paperguide"]
        assert str(meta.get("metadata_source") or "") == "ledger_execute_step"
        assert "ledger_evidence" in list(meta.get("metadata_provenance") or [])
    finally:
        store._get_db = orig_get_db_store

    class _ProviderOnlyDB:
        def fetchall(self, query: str, vars=None):
            return []

        def fetchone(self, query: str, vars=None):
            return {
                "evidence_json": {
                    "task_type": "route_video_render",
                    "output_artifact_type": "route_video_asset",
                },
                "provider_key": "avomap",
            }

    provider_only_db = _ProviderOnlyDB()
    store._get_db = lambda: provider_only_db
    try:
        provider_only_meta = store.resolve_execute_step_metadata(
            "sess-provider-only",
            fallback={"task_type": "free_text_response", "output_artifact_type": "chat_response", "provider_candidates": []},
        )
    finally:
        store._get_db = orig_get_db_store
    assert str(provider_only_meta.get("task_type") or "") == "route_video_render"
    assert str(provider_only_meta.get("output_artifact_type") or "") == "route_video_asset"
    assert list(provider_only_meta.get("provider_candidates") or []) == ["avomap"]
    assert str(provider_only_meta.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_provider_key" in list(provider_only_meta.get("metadata_provenance") or [])

    # Step executor should use plan-store fallback metadata when plan_steps is empty.
    orig_resolve = store.resolve_execute_step_metadata
    store.resolve_execute_step_metadata = lambda session_id, fallback=None: {
        "task_type": "run_secondary_research_pass",
        "output_artifact_type": "research_pack",
        "provider_candidates": ["paperguide"],
        "metadata_source": "ledger_execute_step",
        "metadata_provenance": ["ledger_evidence"],
    }
    marks: list[tuple[str, str, dict[str, object]]] = []
    events: list[str] = []

    def _mark_step(session_id: str, step_key: str, status: str, **kwargs) -> None:
        marks.append((str(step_key), str(status), dict(kwargs or {})))

    def _append_event(session_id: str, **kwargs) -> None:
        events.append(str(kwargs.get("event_type") or ""))

    async def _fake_reasoning(**kwargs):
        return "ok"

    async def _fake_ui(msg: str) -> None:
        return None

    try:
        asyncio.run(
            step_exec.execute_planned_reasoning_step(
                session_id="sess-42",
                plan_steps=[],
                intent_spec={},
                prompt="EXECUTE",
                container="openclaw-gateway",
                google_account="",
                ui_updater=_fake_ui,
                task_name="test",
                mark_step=_mark_step,
                append_event=_append_event,
                run_reasoning_step_func=_fake_reasoning,
            )
        )
    finally:
        store.resolve_execute_step_metadata = orig_resolve

    execute_running = [row for row in marks if row[0] == "execute_intent" and row[1] == "running"]
    assert execute_running, "expected execute_intent running mark"
    evidence = dict(execute_running[0][2].get("evidence") or {})
    assert str(evidence.get("task_type") or "") == "run_secondary_research_pass"
    assert str(evidence.get("output_artifact_type") or "") == "research_pack"
    assert list(evidence.get("provider_candidates") or [])[:1] == ["paperguide"]
    assert str(evidence.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_evidence" in list(evidence.get("metadata_provenance") or [])
    _pass("v1.22 plan-store behavior and step-executor fallback")


if __name__ == "__main__":
    test_plan_store_module_presence()
    test_plan_store_behavior_and_step_executor_fallback()
