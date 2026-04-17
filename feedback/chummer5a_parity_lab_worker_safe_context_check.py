from __future__ import annotations

import json
from pathlib import Path
import re
import traceback

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "next90-m103-ea-parity-lab"
FRONTIER_ID = 4287684466
ACTIVE_RUN_HANDOFF = Path("/docker/fleet/state/chummer_design_supervisor/shard-3/ACTIVE_RUN_HANDOFF.generated.md")
SUCCESSOR_REGISTRY = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
DESIGN_QUEUE = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
FLEET_QUEUE = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
PACK = ROOT / "docs" / "chummer5a_parity_lab" / "CHUMMER5A_PARITY_LAB_PACK.yaml"
CLOSEOUT = ROOT / "docs" / "chummer5a_parity_lab" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
FEEDBACK_NOTE = ROOT / "feedback" / "2026-04-17-chummer5a-parity-lab-worker-safe-pass-202004z.md"


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _active_prompt_path() -> Path:
    text = ACTIVE_RUN_HANDOFF.read_text(encoding="utf-8")
    match = re.search(r"^- Prompt path:\s*(\S+)", text, re.MULTILINE)
    assert match, "active handoff missing prompt path"
    path = Path(match.group(1))
    assert path.exists(), path
    return path


def _task_local_telemetry() -> dict:
    path = _active_prompt_path().parent / "TASK_LOCAL_TELEMETRY.generated.json"
    assert path.exists(), path
    return json.loads(path.read_text(encoding="utf-8"))


def _single_queue_row(queue: dict) -> dict:
    rows = [dict(item) for item in queue.get("items") or [] if dict(item).get("package_id") == PACKAGE_ID]
    assert len(rows) == 1, rows
    return rows[0]


def test_m103_worker_context_uses_task_local_telemetry_without_operator_polling() -> None:
    telemetry = _task_local_telemetry()
    prompt_text = _active_prompt_path().read_text(encoding="utf-8")
    prompt_lower = prompt_text.lower()

    assert telemetry.get("mode") == "implementation_only"
    assert telemetry.get("polling_disabled") is True
    assert telemetry.get("status_query_supported") is False
    assert telemetry.get("successor_registry_path") == SUCCESSOR_REGISTRY.as_posix()
    assert telemetry.get("successor_queue_path") == FLEET_QUEUE.as_posix()
    assert telemetry.get("runtime_handoff_path") == ACTIVE_RUN_HANDOFF.as_posix()

    first_commands = [str(command) for command in telemetry.get("first_commands") or []]
    assert first_commands[0] == "cat TASK_LOCAL_TELEMETRY.generated.json"
    assert any(command.endswith("NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml") for command in first_commands)
    assert any(command.endswith("NEXT_90_DAY_QUEUE_STAGING.generated.yaml") for command in first_commands)
    assert not any("supervisor status" in command.lower() for command in first_commands)
    assert not any("supervisor eta" in command.lower() for command in first_commands)

    queue_item = dict(telemetry.get("queue_item") or {})
    assert queue_item.get("package_id") == PACKAGE_ID
    assert int(queue_item.get("milestone_id") or 0) == 103
    assert queue_item.get("repo") == "executive-assistant"
    assert list(queue_item.get("owned_surfaces") or []) == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]

    assert PACKAGE_ID in prompt_text
    assert "use the shard runtime handoff as the worker-safe resume context" in prompt_lower
    assert "do not query supervisor status or eta from inside the worker run" in prompt_lower
    assert "historical operator status snippets" in prompt_lower


def test_m103_completed_package_rows_remain_closed_without_receipt_refresh() -> None:
    pack = _yaml(PACK)
    closeout = _yaml(CLOSEOUT)
    registry = _yaml(SUCCESSOR_REGISTRY)
    design_row = _single_queue_row(_yaml(DESIGN_QUEUE))
    fleet_row = _single_queue_row(_yaml(FLEET_QUEUE))

    milestone = next(
        dict(item)
        for item in registry.get("milestones") or []
        if int(dict(item).get("id") or 0) == 103
    )
    task_103_1 = next(
        dict(item)
        for item in milestone.get("work_tasks") or []
        if str(dict(item).get("id") or "") == "103.1"
    )

    assert pack.get("status") == "task_proven"
    assert closeout.get("status") == "ea_scope_complete"
    assert task_103_1.get("status") == "complete"
    assert "landed_commit" not in task_103_1

    for row in (design_row, fleet_row):
        assert row.get("status") == "complete"
        assert row.get("completion_action") == "verify_closed_package_only"
        assert int(row.get("frontier_id") or 0) == FRONTIER_ID
        assert "landed_commit" not in row
        assert "recapturing Chummer5a oracle baselines or veteran workflow packs" in str(
            row.get("do_not_reopen_reason") or ""
        )
        assert "python tests/test_chummer5a_parity_lab_pack.py" in set(
            str(item) for item in row.get("proof") or []
        )

    append_policy = dict(closeout.get("repeat_row_append_policy") or {})
    assert append_policy.get("status") == "closed_append_free"
    assert append_policy.get("do_not_append_for_newer_same_package_handoffs") is True
    assert dict(append_policy.get("proof_floor_freeze") or {}).get("latest_guard_commit") == "257a5b7"


def test_m103_worker_safe_feedback_note_records_no_helper_polling() -> None:
    note = FEEDBACK_NOTE.read_text(encoding="utf-8")

    assert f"Package: `{PACKAGE_ID}`" in note
    assert f"Frontier: `{FRONTIER_ID}`" in note
    assert "task-local telemetry and handoff are worker-safe assignment context" in note
    assert "No operator telemetry, active-run helper commands, supervisor status, or supervisor eta was run or cited" in note
    assert "Frozen parity-lab receipts, oracle baselines, workflow packs, compare packs, fixture inventory, and closeout timestamps were not refreshed" in note
    assert "No EA-owned parity-lab extraction work remains" in note


def _run_direct() -> int:
    failed = 0
    ran = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        ran += 1
        try:
            func()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
            traceback.print_exc()
    print(f"ran={ran} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_direct())
