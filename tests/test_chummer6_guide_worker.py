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
        model="gemini-2.5-flash",
        skill_key=worker.VISUAL_DIRECTOR_SKILL_KEY,
    )
    request = captured["request"]

    assert result == {"packet": "guide_refresh", "scene": "receipt over shoulder"}
    assert request.skill_key == "chummer6_visual_director"


def test_ea_json_missing_writer_skill_does_not_fall_back_to_visual_director(monkeypatch) -> None:
    worker = _load_worker_module()
    captured: list[str] = []
    bootstrap_calls: list[bool] = []

    class _Orchestrator:
        def execute_task_artifact(self, request):
            captured.append(request.skill_key)
            raise ValueError("skill_not_found:chummer6_public_writer")

    monkeypatch.setattr(worker, "_ea_orchestrator", lambda: _Orchestrator())
    monkeypatch.setattr(
        worker,
        "ensure_required_chummer6_skills",
        lambda force=False: bootstrap_calls.append(force) or {"status": "ready"},
    )

    with pytest.raises(ValueError, match="skill_not_found:chummer6_public_writer"):
        worker.ea_json("prompt body", model="gemini-groundwork")

    assert captured == ["chummer6_public_writer", "chummer6_public_writer"]
    assert bootstrap_calls == [True]


def test_ea_json_retries_writer_skill_after_bootstrap(monkeypatch) -> None:
    worker = _load_worker_module()
    captured: list[str] = []
    bootstrap_calls: list[bool] = []

    class _Artifact:
        structured_output_json = {"packet": "guide_refresh", "copy": "reader-first"}
        content = ""

    class _Orchestrator:
        def __init__(self) -> None:
            self.calls = 0

        def execute_task_artifact(self, request):
            self.calls += 1
            captured.append(request.skill_key)
            if self.calls == 1:
                raise ValueError("skill_not_found:chummer6_public_writer")
            return _Artifact()

    orchestrator = _Orchestrator()
    monkeypatch.setattr(worker, "_ea_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(
        worker,
        "ensure_required_chummer6_skills",
        lambda force=False: bootstrap_calls.append(force) or {"status": "ready"},
    )

    result = worker.ea_json("prompt body", model="gemini-groundwork")

    assert result == {"packet": "guide_refresh", "copy": "reader-first"}
    assert captured == ["chummer6_public_writer", "chummer6_public_writer"]
    assert bootstrap_calls == [True]


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


def test_public_reader_guard_rejects_unbacked_mechanics_claims() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="unbacked mechanics claim"):
        worker.assert_public_reader_safe(
            {"body": "Roll 8d6 here and beat threshold 3 before the scene advances."},
            context="page:current_status",
        )


def test_public_reader_guard_allows_mechanics_claims_with_receipts() -> None:
    worker = _load_worker_module()

    worker.assert_public_reader_safe(
        {
            "body": "The core receipt shows DV 6P and AP -2 for this outcome.",
            "core_receipt_refs": ["core://receipts/demo-1"],
        },
        context="page:current_status",
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


def test_editorial_pack_audit_rejects_unbacked_mechanics_claims() -> None:
    worker = _load_worker_module()

    with pytest.raises(RuntimeError, match="named_mechanics_value|dice_notation|dv_ap_value"):
        worker.editorial_pack_audit(
            {
                "horizons": {
                    "ghostwire": {
                        "copy": {
                            "table_scene": "Roll 8d6, beat threshold 3, and the replay branch opens."
                        }
                    }
                }
            }
        )


def test_normalize_pages_bundle_requires_real_page_rows() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="missing page bundle row: horizons_index"):
        worker.normalize_pages_bundle({}, items={"horizons_index": worker.PAGE_PROMPTS["horizons_index"]})


def test_normalize_media_override_rejects_unbacked_mechanics_claims() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="unbacked mechanics claim"):
        worker.normalize_media_override(
            "horizon",
            {
                "badge": "GHOSTWIRE",
                "title": "Replay ledger",
                "subtitle": "Find the truth trail",
                "kicker": "Receipts, not vibes",
                "note": "Forensics first.",
                "meta": "preview",
                "visual_prompt": "show DV 6P and AP -2 on the wall beside the operator",
                "overlay_hint": "branch the replay",
                "visual_motifs": ["receipt wall"],
                "overlay_callouts": ["diegetic HUD traces"],
                "scene_contract": {"composition": "over_shoulder_receipt"},
            },
            {"slug": "ghostwire", "title": "GHOSTWIRE"},
        )


def test_normalize_media_override_allows_receipt_backed_mechanics_claims() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "GHOSTWIRE",
            "title": "Replay ledger",
            "subtitle": "Find the truth trail",
            "kicker": "Receipts, not vibes",
            "note": "Forensics first.",
            "meta": "preview",
            "visual_prompt": "show DV 6P and AP -2 on the wall beside the operator",
            "overlay_hint": "branch the replay",
            "visual_motifs": ["receipt wall"],
            "overlay_callouts": ["diegetic HUD traces"],
            "scene_contract": {"composition": "over_shoulder_receipt"},
        },
        {
            "slug": "ghostwire",
            "title": "GHOSTWIRE",
            "core_receipt_refs": ["core://receipts/demo-2"],
        },
    )

    assert normalized["title"] == "Replay ledger"


def test_collect_interest_signals_prefers_public_safe_sources() -> None:
    worker = _load_worker_module()

    signals = worker.collect_interest_signals()
    joined = "\n".join(signals["snippets"])

    assert "[feature:" in joined
    assert "[part:hub]" in joined
    assert "[horizon:karma-forge]" in joined
    assert "design_architecture" not in joined
    assert "design_milestones" not in joined
    assert "hub_readme" not in joined


def test_build_page_prompt_includes_supporting_public_context() -> None:
    worker = _load_worker_module()

    prompt = worker.build_page_prompt("start_here", worker.PAGE_PROMPTS["start_here"])

    assert "Supporting public context" in prompt
    assert "See what is real now" in prompt or "Check the live proof shelf" in prompt


def test_build_horizon_prompt_includes_rollout_access_canon() -> None:
    worker = _load_worker_module()

    prompt = worker.build_horizon_prompt("karma-forge", worker.HORIZONS["karma-forge"])

    assert "Access posture:" in prompt
    assert "Booster nudge:" in prompt
    assert "Free-later intent:" in prompt


def test_copy_quality_findings_flags_generic_copy_and_missing_booster_posture() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "horizon",
        "karma-forge",
        {
            "hook": "A toolkit for the future.",
            "problem": "We are building the foundation.",
            "table_scene": "GM: We will see later.",
            "meanwhile": "- foundation work",
            "why_great": "It helps eventually.",
            "why_waits": "It is not ready yet.",
            "pitch_line": "Keep your long-range plans ready.",
        },
        {
            **worker.HORIZONS["karma-forge"],
            "free_later_intent": "The long-run intent is broader access rather than a permanent paywall.",
        },
    )

    joined = " ".join(findings)
    assert "generic filler" in joined
    assert "booster-first preview posture" in joined
    assert "broad-access or free-later intent" in joined
