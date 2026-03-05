from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def _section(src: str, start_marker: str, end_marker: str | None = None) -> str:
    start = src.find(start_marker)
    assert start >= 0, f"missing_marker:{start_marker}"
    if end_marker:
        end = src.find(end_marker, start + len(start_marker))
        assert end >= 0, f"missing_end_marker:{end_marker}"
        return src[start:end]
    return src[start:]


def test_shared_execute_helper_callsites() -> None:
    src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    approved = _section(src, "async def execute_approved_intent_action(", "async def handle_free_text_intent(")
    free_text = _section(src, "async def handle_free_text_intent(")

    for name, section in (("approved", approved), ("free_text", free_text)):
        helper_idx = section.find("_execute_reasoning_with_planner_fallback(")
        assert helper_idx >= 0, f"missing_shared_helper_call:{name}"
        render_idx = section.find('current_step = "render_reply"')
        assert render_idx >= 0, f"missing_render_stage:{name}"
        assert helper_idx < render_idx, f"helper_call_not_before_render:{name}"

    _pass("v1.22 execute helper callsites")


if __name__ == "__main__":
    test_shared_execute_helper_callsites()
