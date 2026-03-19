from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path("/docker/EA/scripts/chummer6_browseract_humanizer.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_browseract_humanizer", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_humanized_text_accepts_matching_row() -> None:
    module = _load_module()
    original = (
        "Chummer6 is a pre-alpha Shadowrun rules engine with receipts, local-first behavior, "
        "and a proof shelf that is rough but inspectable."
    )
    body = {
        "output": {
            "string": """[
              {
                "original_text": "Chummer6 is a pre-alpha Shadowrun rules engine with receipts, local-first behavior, and a proof shelf that is rough but inspectable.",
                "humanized_text": "Chummer6 is still pre-alpha, but the useful part is already visible: local-first behavior, real receipts, and a proof shelf you can inspect instead of blindly trusting."
              }
            ]"""
        }
    }

    humanized = module.extract_humanized_text(body, original)

    assert "Chummer6" in humanized
    assert "proof shelf" in humanized.lower()


def test_extract_humanized_text_rejects_mismatched_original_binding() -> None:
    module = _load_module()
    original = (
        "Chummer6 is a pre-alpha Shadowrun rules engine with receipts, local-first behavior, "
        "and a proof shelf that is rough but inspectable."
    )
    body = {
        "output": {
            "string": """[
              {
                "original_text": "Discover the Magic of New York City: A Destination Like No Other.",
                "humanized_text": "The Soul of New York City is more than a travel destination."
              }
            ]"""
        }
    }

    try:
        module.extract_humanized_text(body, original)
    except RuntimeError as exc:
        assert str(exc) == "browseract:input_binding_mismatch"
    else:
        raise AssertionError("expected browseract:input_binding_mismatch")


def test_extract_humanized_text_rejects_low_overlap_candidate() -> None:
    module = _load_module()
    original = (
        "Chummer6 keeps the math inspectable, local-first, and grounded in receipts instead of vibes."
    )
    body = {
        "output": {
            "string": """[
              {
                "original_text": "Chummer6 keeps the math inspectable, local-first, and grounded in receipts instead of vibes.",
                "humanized_text": "A premium digital destination for modern productivity and lifestyle insights."
              }
            ]"""
        }
    }

    try:
        module.extract_humanized_text(body, original)
    except RuntimeError as exc:
        assert str(exc) == "browseract:humanizer_output_mismatch"
    else:
        raise AssertionError("expected browseract:humanizer_output_mismatch")


def test_extract_humanized_text_accepts_output_text_shape() -> None:
    module = _load_module()
    original = module.probe_text()
    body = {
        "output": {
            "string": json.dumps(
                [
                    {
                        "input_text": original,
                        "output_text": "Chummer6 gives Shadowrun players and GMs a more dependable way to handle rules, prep, and character work without hiding the math behind vague promises.",
                    }
                ]
            )
        }
    }

    humanized = module.extract_humanized_text(body, original)

    assert "Shadowrun" in humanized
    assert humanized != original


def test_extract_humanized_text_accepts_generic_text_list_and_skips_original_clone() -> None:
    module = _load_module()
    original = module.probe_text()
    body = {
        "output": {
            "string": json.dumps(
                [
                    {"text": original, "word_count": 74},
                    {
                        "text": "Chummer6 is a more grounded Shadowrun tool for people who want local-first prep, inspectable rules math, and fewer black-box surprises at the table.",
                        "word_count": 26,
                    },
                ]
            )
        }
    }

    humanized = module.extract_humanized_text(body, original)

    assert "local-first" in humanized
    assert humanized != original


def test_cmd_check_reports_unhealthy_when_probe_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_workflow", lambda: ("wf-1", "broken-humanizer"))
    monkeypatch.setattr(module, "run_task", lambda **_: {"task_id": "task-1"})
    monkeypatch.setattr(module, "_task_id", lambda body: "task-1")
    monkeypatch.setattr(module, "wait_for_task", lambda *_, **__: {"output": {"string": "[]"}})

    rc = module.cmd_check()
    captured = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert captured["status"] == "unhealthy"
    assert captured["workflow_id"] == "wf-1"


def test_cmd_check_reports_ready_when_probe_passes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_workflow", lambda: ("wf-2", "healthy-humanizer"))
    monkeypatch.setattr(module, "run_task", lambda **_: {"task_id": "task-2"})
    monkeypatch.setattr(module, "_task_id", lambda body: "task-2")
    monkeypatch.setattr(
        module,
        "wait_for_task",
        lambda *_, **__: {
            "output": {
                "string": json.dumps(
                    [
                        {
                            "original_text": module.probe_text(),
                            "humanized_text": "Chummer6 gives Shadowrun players and GMs a more transparent way to handle rules support and session prep, with local-first continuity and receipts instead of black-box trust.",
                        }
                    ]
                )
            }
        },
    )

    rc = module.cmd_check()
    captured = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert captured["status"] == "ready"
    assert captured["workflow_id"] == "wf-2"


def test_cmd_check_uses_humanizer_timeout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    waited: dict[str, object] = {}
    monkeypatch.setattr(module, "resolve_workflow", lambda: ("wf-3", "healthy-humanizer"))
    monkeypatch.setattr(module, "run_task", lambda **_: {"task_id": "task-3"})
    monkeypatch.setattr(module, "_task_id", lambda body: "task-3")
    monkeypatch.setattr(module, "humanizer_timeout_seconds", lambda: 123)

    def fake_wait(task_id: str, *, timeout_seconds: int = 0):
        waited["timeout_seconds"] = timeout_seconds
        return {
            "output": {
                "string": json.dumps(
                    [
                        {
                            "input_text": module.probe_text(),
                            "output_text": "Chummer6 keeps the useful part visible: Shadowrun rules truth, local-first prep, and receipts instead of blind trust.",
                        }
                    ]
                )
            }
        }

    monkeypatch.setattr(module, "wait_for_task", fake_wait)

    rc = module.cmd_check()
    captured = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert captured["status"] == "ready"
    assert waited["timeout_seconds"] == 123


def test_emit_builder_packet_creates_builder_packet(tmp_path: Path) -> None:
    module = _load_module()
    spec_path = tmp_path / "undetectable_humanizer_live.workflow.json"
    spec_path.write_text(
        json.dumps(
            {
                "workflow_name": "undetectable_humanizer_live",
                "description": "Repair test workflow.",
                "publish": True,
                "mcp_ready": False,
                "inputs": [{"name": "text", "description": "text"}],
                "nodes": [
                    {"id": "open_tool", "label": "Open Tool", "type": "visit_page", "config": {"url": "https://undetectable.ai/ai-humanizer"}},
                    {"id": "output_result", "label": "Output Result", "type": "output", "config": {"field_name": "humanized_text"}},
                ],
                "edges": [{"source": "open_tool", "target": "output_result"}],
            }
        ),
        encoding="utf-8",
    )

    builder_path = module._emit_builder_packet(spec_path)

    assert builder_path is not None
    packet = json.loads(builder_path.read_text(encoding="utf-8"))
    assert packet["workflow_name"] == "undetectable_humanizer_live"
    assert len(packet["nodes"]) == 2
