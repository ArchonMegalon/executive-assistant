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


def test_execute_step_metadata_provenance_behavior() -> None:
    _install_psycopg2_stub()
    import app.planner.plan_store as store
    import app.planner.step_executor as step_exec

    orig_resolve = store.resolve_execute_step_metadata
    store.resolve_execute_step_metadata = lambda session_id, fallback=None: {
        "task_type": "run_secondary_research_pass",
        "output_artifact_type": "research_pack",
        "provider_candidates": ["paperguide"],
        "metadata_source": "ledger_execute_step",
        "metadata_provenance": ["ledger_evidence"],
    }

    marks: list[tuple[str, str, dict[str, object]]] = []
    events: list[dict[str, object]] = []

    def _mark_step(session_id: str, step_key: str, status: str, **kwargs) -> None:
        marks.append((str(step_key), str(status), dict(kwargs or {})))

    def _append_event(session_id: str, **kwargs) -> None:
        events.append(dict(kwargs or {}))

    async def _fake_reasoning(**kwargs):
        return "ok"

    async def _fake_ui(msg: str) -> None:
        return None

    try:
        out = asyncio.run(
            step_exec.execute_planned_reasoning_step(
                session_id="sess-provenance",
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

    assert str(out.get("task_type") or "") == "run_secondary_research_pass"
    assert str(out.get("output_artifact_type") or "") == "research_pack"
    assert list(out.get("provider_candidates") or []) == ["paperguide"]
    assert str(out.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_evidence" in list(out.get("metadata_provenance") or [])

    running_rows = [row for row in marks if row[0] == "execute_intent" and row[1] == "running"]
    completed_rows = [row for row in marks if row[0] == "execute_intent" and row[1] == "completed"]
    assert running_rows and completed_rows

    running_evidence = dict(running_rows[0][2].get("evidence") or {})
    assert str(running_evidence.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_evidence" in list(running_evidence.get("metadata_provenance") or [])

    completed_result = dict(completed_rows[0][2].get("result") or {})
    assert str(completed_result.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_evidence" in list(completed_result.get("metadata_provenance") or [])

    completed_events = [evt for evt in events if str(evt.get("event_type") or "") == "execute_intent_completed"]
    assert completed_events
    payload = dict(completed_events[0].get("payload") or {})
    assert str(payload.get("metadata_source") or "") == "ledger_execute_step"
    assert "ledger_evidence" in list(payload.get("metadata_provenance") or [])

    _pass("v1.22 execute-step metadata provenance")


def test_execute_step_metadata_plan_fallback_source() -> None:
    from app.planner.step_executor import _execute_step_metadata

    meta = _execute_step_metadata(
        session_id="",
        plan_steps=[
            {
                "step_key": "execute_intent",
                "task_type": "route_video_render",
                "output_artifact_type": "route_video_asset",
                "provider_candidates": ["avomap"],
            }
        ],
        intent_spec={"task_type": "free_text_response"},
    )
    assert str(meta.get("task_type") or "") == "route_video_render"
    assert str(meta.get("output_artifact_type") or "") == "route_video_asset"
    assert list(meta.get("provider_candidates") or []) == ["avomap"]
    assert str(meta.get("metadata_source") or "") == "plan_steps_execute_step"
    assert "plan_steps_execute_step" in list(meta.get("metadata_provenance") or [])

    _pass("v1.22 execute-step metadata plan fallback source")


if __name__ == "__main__":
    test_execute_step_metadata_provenance_behavior()
    test_execute_step_metadata_plan_fallback_source()
