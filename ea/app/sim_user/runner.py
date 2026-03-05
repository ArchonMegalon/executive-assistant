from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any


class ScenarioContractError(ValueError):
    pass


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ScenarioContractError(f"{path.name}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ScenarioContractError(f"{path.name}: scenario payload must be an object")
    return data


def _validate_turn(turn: dict[str, Any], *, idx: int, source: str) -> None:
    actor = str(turn.get("actor") or "").strip().lower()
    text = str(turn.get("text") or "").strip()
    if actor not in {"user", "assistant"}:
        raise ScenarioContractError(f"{source}: turns[{idx}] actor must be user|assistant")
    if not text:
        raise ScenarioContractError(f"{source}: turns[{idx}] text is required")


def _validate_scenario(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    scenario_id = str(data.get("scenario_id") or "").strip()
    persona = str(data.get("persona") or "").strip()
    goal = str(data.get("goal") or "").strip()
    if not scenario_id:
        raise ScenarioContractError(f"{source}: scenario_id is required")
    if not persona:
        raise ScenarioContractError(f"{source}: persona is required")
    if not goal:
        raise ScenarioContractError(f"{source}: goal is required")

    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ScenarioContractError(f"{source}: turns must be a non-empty list")
    for idx, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ScenarioContractError(f"{source}: turns[{idx}] must be an object")
        _validate_turn(turn, idx=idx, source=source)

    expected = data.get("expected")
    if not isinstance(expected, dict):
        raise ScenarioContractError(f"{source}: expected must be an object")
    task_type = str(expected.get("task_type") or "").strip()
    artifact_type = str(expected.get("artifact_type") or "").strip()
    if not task_type:
        raise ScenarioContractError(f"{source}: expected.task_type is required")
    if not artifact_type:
        raise ScenarioContractError(f"{source}: expected.artifact_type is required")

    return {
        "scenario_id": scenario_id,
        "persona": persona,
        "goal": goal,
        "turns": turns,
        "expected": expected,
    }


def load_scenarios(scenario_dir: str) -> list[dict[str, Any]]:
    root = pathlib.Path(str(scenario_dir or "").strip() or "/app/qa/scenarios")
    if not root.exists():
        raise ScenarioContractError(f"scenario directory missing: {root}")
    files = sorted([p for p in root.glob("*.json") if p.is_file()])
    if not files:
        raise ScenarioContractError(f"no scenario files found in {root}")
    out: list[dict[str, Any]] = []
    for path in files:
        raw = _load_json(path)
        out.append(_validate_scenario(raw, source=path.name))
    return out


def run_contract_check(scenario_dir: str) -> dict[str, Any]:
    scenarios = load_scenarios(scenario_dir)
    return {
        "status": "ok",
        "scenario_count": len(scenarios),
        "scenario_ids": [str(x.get("scenario_id") or "") for x in scenarios],
    }


def _render_summary(result: dict[str, Any]) -> str:
    ids = ", ".join(result.get("scenario_ids") or [])
    return f"ea-sim-user contract check passed ({result.get('scenario_count')} scenarios): {ids}"


def _main() -> int:
    scenario_dir = str(os.environ.get("EA_SIM_SCENARIO_DIR") or "/app/qa/scenarios")
    mode = str(os.environ.get("EA_SIM_RUN_MODE") or "contract_only").strip().lower()
    sleep_sec = max(0, int(os.environ.get("EA_SIM_IDLE_SLEEP_SEC") or 0))
    try:
        result = run_contract_check(scenario_dir)
        print(_render_summary(result), flush=True)
    except ScenarioContractError as exc:
        print(f"[ea-sim-user][contract-error] {exc}", flush=True)
        return 2
    except Exception as exc:
        print(f"[ea-sim-user][error] {exc}", flush=True)
        return 1
    if mode == "daemon":
        while True:
            time.sleep(max(5, sleep_sec or 30))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
