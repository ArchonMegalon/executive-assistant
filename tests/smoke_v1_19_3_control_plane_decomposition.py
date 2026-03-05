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


def test_poll_listener_decomposition_boundaries() -> None:
    poll_path = ROOT / "ea/app/poll_listener.py"
    poll_src = poll_path.read_text(encoding="utf-8")
    callback_src = (ROOT / "ea/app/callback_commands.py").read_text(encoding="utf-8")
    brief_runtime_src = (ROOT / "ea/app/brief_runtime.py").read_text(encoding="utf-8")
    intent_runtime_src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")

    line_count = poll_src.count("\n") + 1
    assert line_count <= 600, f"poll_listener too large: {line_count} lines"

    assert "from app.callback_commands import handle_callback_command as _handle_callback_command" in poll_src
    assert "from app.brief_runtime import run_brief_command as _run_brief_command" in poll_src
    assert "from app.intent_runtime import handle_free_text_intent as _handle_free_text_intent" in poll_src
    assert "from app.auth_runtime import trigger_auth_flow as _trigger_auth_flow" in poll_src
    assert "async def handle_callback(cb):" in poll_src
    assert "async def handle_intent(chat_id: int, msg: dict):" in poll_src
    assert "async def handle_command(chat_id: int, text: str, msg: dict):" in poll_src

    # Heavy callback and free-text runtime logic now lives in dedicated modules.
    assert "if cb['data'].startswith('act:')" not in poll_src
    assert "task_name='Intent: Free Text'" not in poll_src
    assert "def _openclaw_candidates(" not in poll_src
    assert "await _trigger_auth_flow(" in poll_src
    assert "if cb[\"data\"].startswith(\"act:\"):" in callback_src
    assert "task_name=\"Intent: Free Text\"" in intent_runtime_src
    assert "renderer_text_only" in brief_runtime_src

    _pass("v1.19.3 poll-listener decomposition boundaries")


if __name__ == "__main__":
    test_poll_listener_decomposition_boundaries()
