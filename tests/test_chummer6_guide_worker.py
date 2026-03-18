from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_guide_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("chummer6_guide_worker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chat_json_routes_through_ea_only(monkeypatch) -> None:
    worker = _load_worker_module()
    monkeypatch.setenv("CHUMMER6_TEXT_PROVIDER_ORDER", "ea")
    monkeypatch.delenv("CHUMMER6_TEXT_MODEL", raising=False)
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-groundwork")
    monkeypatch.setattr(
        worker,
        "ea_json",
        lambda prompt, model="gemini-groundwork", skill_key=worker.PUBLIC_WRITER_SKILL_KEY: {
            "prompt": prompt,
            "model": model,
            "skill_key": skill_key,
        },
    )

    result = worker.chat_json("prompt")
    assert result == {
        "prompt": "prompt",
        "model": "gemini-groundwork",
        "skill_key": "chummer6_public_writer",
    }
    assert worker.TEXT_PROVIDER_USED == "ea-groundwork"


def test_chat_json_rejects_legacy_provider_aliases(monkeypatch) -> None:
    worker = _load_worker_module()
    monkeypatch.setenv("CHUMMER6_TEXT_PROVIDER_ORDER", "ea,codex,onemin")

    with pytest.raises(RuntimeError, match="unsupported_chummer6_text_provider:codex,onemin"):
        worker.chat_json("prompt")


def test_ea_json_executes_public_writer_skill_identity_by_default(monkeypatch) -> None:
    worker = _load_worker_module()
    captured: dict[str, object] = {}

    class _Artifact:
        structured_output_json = {"packet": "guide_refresh", "scene": "troll union sticker"}
        content = ""

    class _Orchestrator:
        def execute_task_artifact(self, request):
            captured["request"] = request
            return _Artifact()

    monkeypatch.setattr(worker, "_ea_orchestrator", lambda: _Orchestrator())

    result = worker.ea_json("prompt body", model="gemini-groundwork")
    request = captured["request"]

    assert result == {"packet": "guide_refresh", "scene": "troll union sticker"}
    assert request.skill_key == "chummer6_public_writer"
    assert request.goal == "Generate a structured JSON packet for the chummer6_public_writer worker."
    assert request.input_json["model"] == "gemini-groundwork"


def test_ea_json_can_execute_visual_director_skill_identity(monkeypatch) -> None:
    worker = _load_worker_module()
    captured: dict[str, object] = {}

    class _Artifact:
        structured_output_json = {"packet": "guide_refresh", "scene": "receipt over shoulder"}
        content = ""

    class _Orchestrator:
        def execute_task_artifact(self, request):
            captured["request"] = request
            return _Artifact()

    monkeypatch.setattr(worker, "_ea_orchestrator", lambda: _Orchestrator())

    result = worker.ea_json(
        "prompt body",
        model="gemini-3-flash-preview",
        skill_key=worker.VISUAL_DIRECTOR_SKILL_KEY,
    )
    request = captured["request"]

    assert result == {"packet": "guide_refresh", "scene": "receipt over shoulder"}
    assert request.skill_key == "chummer6_visual_director"


def test_normalize_ooda_coerces_scalar_lists_and_falls_back_to_signal_defaults() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_ooda(
        {
            "observe": {
                "source_signal_tags": "multi_era_rulesets",
                "source_excerpt_labels": "core_readme",
                "audience_needs": "show table value first",
                "user_interest_signals": "receipts over mystery math",
            },
            "orient": {
                "audience": "curious table people",
                "promise": "truth with receipts",
                "tension": "clarity versus repo sermon",
                "visual_direction": "grounded scenes",
                "humor_line": "the dev called this a tiny cleanup pass",
                "why_care": "faster rulings",
                "current_focus": "trustworthy behavior",
                "signals_to_highlight": "multi-era support",
                "banned_terms": "visitor center",
            },
            "decide": {
                "information_order": "lead with value",
                "tone_rules": "stay human",
                "horizon_policy": "pain first",
                "media_strategy": "scene art",
                "overlay_policy": "useful overlays only",
                "cta_strategy": "invite testing",
            },
            "act": {
                "landing_tagline": "Shadowrun rules truth, with receipts.",
                "landing_intro": "Intro.",
                "what_it_is": "What it is.",
                "watch_intro": "Watch it.",
                "horizon_intro": "Horizons.",
            },
        },
        {"tags": ["multi_era_rulesets", "lua_rules"], "snippets": ["[core_readme] Deterministic engine."]},
    )

    assert normalized["observe"]["audience_needs"] == ["show table value first"]
    assert normalized["orient"]["why_care"] == ["faster rulings"]
    assert normalized["observe"]["risks"]
    assert normalized["orient"]["signals_to_highlight"] == ["multi-era support"]


def test_normalize_section_ooda_falls_back_when_fields_are_sparse() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_section_ooda(
        {
            "observe": {
                "reader_question": "Why should I care?",
                "concrete_signals": "receipts, sync, and reruns",
            },
            "orient": {
                "emotional_goal": "make it click",
                "sales_angle": "table benefit first",
            },
            "decide": {},
            "act": {},
        },
        section_type="horizon",
        name="nexus-pan",
        item={"title": "NEXUS-PAN", "hook": "One living table state."},
        global_ooda={"orient": {"signals_to_highlight": ["local-first session resilience"]}},
    )

    assert normalized["observe"]["reader_question"] == "Why should I care?"
    assert normalized["observe"]["concrete_signals"] == ["receipts, sync, and reruns"]
    assert normalized["orient"]["visual_devices"]
    assert normalized["decide"]["image_priority"]
    assert normalized["act"]["visual_prompt_seed"]


def test_public_reader_guard_rejects_maintainer_imperatives() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="forbidden public-copy phrase"):
        worker.assert_public_reader_safe(
            {"body": "Fix Chummer6 first. Do not correct the blueprint because the visitor guide got ahead of itself."},
            context="page:where_to_go_deeper",
        )


def test_editorial_self_audit_rewrites_machine_room_phrases() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "The blueprint lives in the repo topology.",
            fallback="The long-range plan lives in the deeper source docs.",
            context="page:where_to_go_deeper:intro",
        )
        == "The long-range plan lives in the deeper source docs."
    )
    assert (
        worker.editorial_self_audit_text(
            "Workbench and play shell both matter here.",
            context="part:mobile:intro",
        )
        == "prep surface and live-play surface both matter here."
    )


def test_editorial_pack_audit_rejects_maintainer_language() -> None:
    worker = _load_worker_module()

    with pytest.raises(RuntimeError, match="editorial_pack_audit_failed"):
        worker.editorial_pack_audit(
            {
                "pages": {
                    "where_to_go_deeper": {
                        "body": "Fix Chummer6 first and do not correct the blueprint."
                    }
                }
            }
        )


def test_editorial_pack_audit_ignores_banned_term_lists() -> None:
    worker = _load_worker_module()

    result = worker.editorial_pack_audit(
        {
            "ooda": {
                "orient": {
                    "banned_terms": ["correct the blueprint", "visitor center"]
                }
            },
            "pages": {
                "where_to_go_deeper": {
                    "body": "If this guide feels stale or confusing, report it here."
                }
            },
        }
    )

    assert result["status"] == "ok"


def test_normalize_pages_bundle_requires_real_page_rows() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="missing page bundle row: horizons_index"):
        worker.normalize_pages_bundle({}, items={"horizons_index": worker.PAGE_PROMPTS["horizons_index"]})
