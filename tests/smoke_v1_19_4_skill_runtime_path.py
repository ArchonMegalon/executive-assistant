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


def test_skill_command_wiring_in_poller() -> None:
    src = (ROOT / "ea/app/poll_listener.py").read_text(encoding="utf-8")
    skill_src = (ROOT / "ea/app/skill_commands.py").read_text(encoding="utf-8")
    reg_src = (ROOT / "ea/app/skills/registry.py").read_text(encoding="utf-8")
    assert "if cmd == '/skill':" in src
    assert "from app.skill_commands import handle_skill_command as _handle_skill_command" in src
    assert "create_action(" in skill_src
    assert "build_capability_plan(" in skill_src
    assert "planning_task = str(getattr(contract, \"planning_task_type\"" in skill_src
    assert "planning_task_type" in reg_src
    assert "action_type=f\"skill:{skill_key}\"" in skill_src
    assert "Execute Skill Plan" in skill_src
    _pass("v1.19.4 skill command runtime wiring")


def test_typed_action_callback_wiring() -> None:
    src = (ROOT / "ea/app/callback_commands.py").read_text(encoding="utf-8")
    dispatch_src = (ROOT / "ea/app/skills/runtime_action_exec.py").read_text(encoding="utf-8")
    assert "from app.actions import consume_action" in src
    assert "async def _execute_typed_action_callback(" in src
    assert "execute_typed_action(" in src
    assert "def execute_typed_action(" in dispatch_src
    assert "if action_type.startswith(\"skill:\"):" in dispatch_src
    _pass("v1.19.4 typed-action callback wiring")


def test_typed_action_callback_behavior() -> None:
    from app.skills.runtime_action_exec import execute_typed_action

    out = execute_typed_action(
        tenant_name="chat_100284",
        chat_id=123,
        action_row={
            "action_type": "skill:travel_rescue",
            "payload_json": {"operation": "plan", "payload": {"notes": "demo"}},
        },
        dispatch_skill=lambda **kwargs: {
            "ok": False,
            "status": "not_implemented",
            "skill": "travel_rescue",
            "operation": "plan",
            "plan": {"ok": True, "primary": "oneair", "fallbacks": ["avomap"]},
        },
    )

    text = str(out.get("text") or "").lower()
    assert "skill result" in text
    assert "primary capability" in text
    assert "oneair" in text
    _pass("v1.19.4 typed-action callback behavior")


if __name__ == "__main__":
    test_skill_command_wiring_in_poller()
    test_typed_action_callback_wiring()
    test_typed_action_callback_behavior()
