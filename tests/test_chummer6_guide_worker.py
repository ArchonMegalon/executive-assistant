from __future__ import annotations

import json
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


def test_humanize_text_falls_back_to_brain_when_external_humanizer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    source = (
        "Chummer6 is still concept-stage. The proof shelf is real, the limits are real, and the next step should be honest "
        "instead of dressed up like a finished product."
    )
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_REQUIRED", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_WORDS", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_SENTENCES", "1")
    monkeypatch.setenv(
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND",
        "python3 -c \"import sys; sys.exit(1)\""
    )
    monkeypatch.setattr(
        worker,
        "chat_json",
        lambda prompt, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY: {
            "humanized": "Chummer6 is still concept-stage. What matters is that the proof shelf is real, the limits are visible, and the next step is stated plainly instead of pretending the product is finished."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "proof shelf" in result.lower()
    assert "concept" in result.lower()
    assert worker.HUMANIZER_EXTERNAL_LOCKED_OUT is True


def test_humanize_text_rejects_aiish_external_output_before_brain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    source = (
        "Chummer6 is still concept-stage, rough, and inspectable. The point is to show real receipts now, not sell a seamless journey."
    )
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_REQUIRED", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_WORDS", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_SENTENCES", "1")
    monkeypatch.setenv(
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND",
        "python3 -c \"print('A seamless toolkit for an ever-evolving journey into dynamic Shadowrun innovation.')\""
    )
    monkeypatch.setattr(
        worker,
        "chat_json",
        lambda prompt, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY: {
            "humanized": "Chummer6 is still rough and concept-stage. The useful part is that the receipts are real now, and the copy does not pretend this thing is polished."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "seamless toolkit" not in result.lower()
    assert "receipts" in result.lower()


def test_humanize_text_uses_brain_when_required_without_external_humanizer(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    source = (
        "The current build is still concept-stage, but a player can inspect what the math did and where the numbers came from."
    )
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_REQUIRED", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_WORDS", "1")
    monkeypatch.setenv("CHUMMER6_TEXT_HUMANIZER_MIN_SENTENCES", "1")
    monkeypatch.delenv("CHUMMER6_BROWSERACT_HUMANIZER_COMMAND", raising=False)
    monkeypatch.delenv("CHUMMER6_TEXT_HUMANIZER_COMMAND", raising=False)
    monkeypatch.delenv("CHUMMER6_BROWSERACT_HUMANIZER_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("CHUMMER6_TEXT_HUMANIZER_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID", raising=False)
    monkeypatch.delenv("CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY", raising=False)
    monkeypatch.setattr(worker, "external_humanizer_ready", lambda: False)
    monkeypatch.setattr(
        worker,
        "chat_json",
        lambda prompt, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY: {
            "humanized": "The current build is still concept-stage, but a player can already inspect the math and see where the numbers came from."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "concept" in result.lower()
    assert "inspect the math" in result.lower()


def test_recent_scene_rows_for_style_epoch_can_refuse_stale_fallback_rows(tmp_path: Path) -> None:
    worker = _load_worker_module()
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "target": "assets/hero/chummer6-hero.png",
                        "composition": "over_shoulder_receipt",
                        "style_epoch": {"epoch": 1, "run_id": "style-001"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    original = worker.SCENE_LEDGER_PATH
    worker.SCENE_LEDGER_PATH = ledger_path
    try:
        rows = worker.recent_scene_rows_for_style_epoch(
            style_epoch={"epoch": 2, "run_id": "style-002"},
            allow_fallback=False,
        )
    finally:
        worker.SCENE_LEDGER_PATH = original

    assert rows == []


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
                "what_it_is": "A scriptable character engine built for multi-era support with deterministic logic.",
                "watch_intro": "Watch it.",
                "horizon_intro": "Horizons.",
            },
        },
        {"tags": ["multi_era_rulesets", "lua_rules"], "snippets": ["[core_readme] Deterministic engine."]},
    )

    assert normalized["observe"]["audience_needs"] == ["show table value first"]
    assert normalized["observe"]["source_signal_tags"] == ["future_rules_coverage"]
    assert normalized["observe"]["user_interest_signals"] == ["receipts over mystery math"]
    assert normalized["orient"]["why_care"] == [
        "a clearer trust path for rulings tools",
        "less trust-me math through visible receipts",
        "a saner long-range path from prep to live play",
    ]
    assert normalized["observe"]["risks"]
    assert normalized["orient"]["signals_to_highlight"] == [
        "future rules coverage should be shown honestly",
        "edge-case handling should come with receipts instead of trust-me copy",
    ]
    assert normalized["orient"]["humor_line"] == "Keep the wit dry, adult, and secondary to the actual point."
    assert normalized["act"]["landing_tagline"] == "An idea for less mystical Shadowrun rulings."
    assert normalized["act"]["what_it_is"] == (
        "Chummer6 is an idea about inspecting Shadowrun rulings instead of trusting folklore math or lucky table memory."
    )


def test_editorial_self_audit_rejects_ooda_math_certainty_and_scope_leaks() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "A scriptable multi-era engine with deterministic logic.",
            fallback="A rough idea that is trying to show where the receipts could come from.",
            context="ooda:act:what_it_is",
        )
        == "A rough idea that is trying to show where the receipts could come from."
    )
    assert (
        worker.editorial_self_audit_text(
            "The math is clear now.",
            fallback="Trust is still being earned through proofs and receipts.",
            context="ooda:act:landing_intro",
        )
        == "Trust is still being earned through proofs and receipts."
    )
    assert (
        worker.editorial_self_audit_text(
            "Every bonus, penalty, and threshold has a clear provenance.",
            fallback="Chummer6 is still an idea about making rulings easier to inspect instead of asking for trust-me math.",
            context="ooda:act:what_it_is",
        )
        == "Chummer6 is still an idea about making rulings easier to inspect instead of asking for trust-me math."
    )


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


def test_normalize_media_override_strips_unbacked_overlay_callouts_but_keeps_packet() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "part",
        {
            "badge": "UI",
            "title": "Prep desk",
            "subtitle": "Build and inspect",
            "kicker": "Proof first",
            "note": "Useful now.",
            "meta": "preview",
            "visual_prompt": "Prep desk scene with visible receipt traces.",
            "overlay_hint": "receipt traces",
            "visual_motifs": ["prep desk"],
            "overlay_callouts": ["receipt traces", "AP -2 smartlink feed", "LOADOUT_VALID", "LIFESTYLE: STREET"],
            "scene_contract": {
                "subject": "a player building a runner",
                "environment": "a prep desk",
                "action": "checking a build",
                "metaphor": "receipt-first prep",
                "props": ["laptop", "notes"],
                "overlays": ["receipt traces"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
            },
        },
        {"slug": "ui", "title": "UI"},
    )

    assert normalized["overlay_callouts"] == [
        "build-state deltas",
        "inspection brackets",
        "shared component echoes",
    ]
    assert "AP -2 smartlink feed" not in normalized["overlay_callouts"]
    assert "LOADOUT_VALID" not in normalized["overlay_callouts"]


def test_normalize_media_override_strips_machine_overlay_labels_from_scene_contract() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "JACKPOINT",
            "title": "JackPoint",
            "subtitle": "Readable packets",
            "kicker": "Receipts survive",
            "note": "Future-facing.",
            "meta": "preview",
            "visual_prompt": (
                "A dossier desk with live evidence threads and receipt markers. "
                "Hovering digital 'VERIFIED' stamps glow in the air with metadata strings."
            ),
            "overlay_hint": "HUD style: Data-dossier classification stamps and rotating provenance hashes in the corners.",
            "visual_motifs": ["dossier desk", "receipt threads"],
            "overlay_callouts": ["receipt markers", "SIG_MATCH: 99.8%"],
            "scene_contract": {
                "subject": "a fixer sorting a dossier",
                "environment": "a dim archive desk",
                "action": "sorting evidence",
                "metaphor": "dossier evidence wall",
                "props": ["dossiers", "chips"],
                "overlays": ["receipt markers", "PROVENANCE VERIFIED", "HW_ID: 0x882_DECK"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
            },
        },
        {"slug": "jackpoint", "title": "JackPoint"},
    )

    assert normalized["overlay_hint"] == "source anchors and redaction bars"
    assert normalized["overlay_callouts"] == [
        "source anchors",
        "redaction bars",
        "evidence pins",
    ]
    assert "SIG_MATCH: 99.8%" not in normalized["overlay_callouts"]
    assert normalized["scene_contract"]["overlays"] == ["source anchors", "redaction bars", "evidence pins"]
    assert "verified" not in normalized["visual_prompt"].lower()
    assert "metadata" not in normalized["visual_prompt"].lower()
    assert "hash" not in normalized["overlay_hint"].lower()
    assert "hud style:" not in normalized["overlay_hint"].lower()


def test_normalize_media_override_strips_non_sparse_easter_eggs_but_keeps_meta_humor_out() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "part",
        {
            "badge": "UI",
            "title": "Prep desk",
            "subtitle": "Build and inspect",
            "kicker": "Proof first",
            "note": "Useful now.",
            "meta": "preview",
            "visual_prompt": "Prep desk scene with a troll monitor sticker clearly visible on the bezel.",
            "overlay_hint": "receipt traces",
            "visual_motifs": ["prep desk", "troll monitor sticker"],
            "overlay_callouts": ["receipt traces"],
            "scene_contract": {
                "subject": "a player building a runner",
                "environment": "a prep desk",
                "action": "checking gear",
                "metaphor": "receipt-first prep",
                "props": ["laptop", "troll monitor sticker"],
                "overlays": ["receipt traces"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
                "humor": "A worn sticker on the monitor reads: 'NOT MY BUG'.",
                "easter_egg_kind": "troll monitor sticker",
                "easter_egg_placement": "upper-left bezel",
                "easter_egg_detail": "classic Chummer troll sticker",
                "easter_egg_visibility": "obvious",
            },
        },
        {"slug": "ui", "title": "UI"},
    )

    assert normalized["scene_contract"]["humor"] == ""
    assert "easter_egg_kind" not in normalized["scene_contract"]
    assert "troll" not in normalized["visual_prompt"].lower()
    assert not any("troll" in entry.lower() for entry in normalized["visual_motifs"])


def test_normalize_media_override_strips_flagship_horizon_easter_egg_and_humor_softness() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "KARMA FORGE",
            "title": "Forge",
            "subtitle": "Shape the dangerous rules",
            "kicker": "Bench first",
            "note": "Preview lane.",
            "meta": "horizon",
            "visual_prompt": "Rulesmith bench scene with a troll forge patch on the apron.",
            "overlay_hint": "rollback markers",
            "visual_motifs": ["rulesmith bench", "forge sparks"],
            "overlay_callouts": ["rollback markers"],
            "scene_contract": {
                "subject": "a rulesmith at a bench",
                "environment": "an industrial workshop",
                "action": "hammering volatile rules into shape",
                "metaphor": "forge sparks and molten rules",
                "props": ["forge tools", "receipt traces"],
                "overlays": ["rollback markers"],
                "composition": "workshop_bench",
                "palette": "rust amber",
                "mood": "intense",
                "humor": "The bastard thing finally behaves.",
                "easter_egg_kind": "troll forge patch",
                "easter_egg_placement": "on the apron strap",
                "easter_egg_detail": "classic Chummer troll embroidered as a forge patch",
                "easter_egg_visibility": "small but visible",
            },
        },
        {"slug": "karma-forge", "title": "KARMA FORGE"},
    )

    assert "easter_egg_kind" not in normalized["scene_contract"]
    assert normalized["scene_contract"]["humor"] == ""


def test_media_humor_allowed_respects_explicit_forbid_policy() -> None:
    worker = _load_worker_module()

    assert (
        worker.media_humor_allowed(
            kind="horizon",
            item={"slug": "karma-forge"},
            contract={"humor_policy": "forbid"},
        )
        is False
    )


def test_visual_contract_for_target_loads_first_contact_page_index_and_flagship_profiles() -> None:
    worker = _load_worker_module()

    hero_contract = worker.visual_contract_for_target("assets/hero/chummer6-hero.png")
    horizons_contract = worker.visual_contract_for_target("assets/pages/horizons-index.png")
    forge_contract = worker.visual_contract_for_target("assets/horizons/karma-forge.png")

    assert hero_contract["density_target"] == "high"
    assert hero_contract["person_count_target"] == "duo_or_team"
    assert horizons_contract["visual_density_profile"] == "page_index"
    assert horizons_contract["required_overlay_density"] == "medium"
    assert forge_contract["flash_level"] == "bold"
    assert forge_contract["person_count_target"] == "duo_preferred"


def test_variation_guardrails_include_visual_contract_requirements_for_hero() -> None:
    worker = _load_worker_module()

    rules = worker.variation_guardrails_for("assets/hero/chummer6-hero.png", [])
    joined = "\n".join(rules).lower()

    assert "flagship poster style epoch" in joined
    assert "packed and layered" in joined
    assert "two to four people" in joined
    assert "garage clinic" in joined or "getaway-van triage" in joined
    assert "lore crumb on a prop or wall" in joined
    assert "overlay ooda mode: medscan_diagnostic" in joined
    assert "pseudo-text" in joined or "fake lettering" in joined


def test_media_humor_allowed_respects_flagship_visual_contract() -> None:
    worker = _load_worker_module()

    assert worker.media_humor_allowed(kind="horizon", item={"slug": "karma-forge"}, contract={}) is False


def test_critical_visual_findings_require_shadowrun_lore_markers_for_hero() -> None:
    worker = _load_worker_module()

    findings = worker.critical_visual_findings_for_target(
        "assets/hero/chummer6-hero.png",
        {
            "visual_motifs": ["trust check", "inspection pressure", "streetdoc assist", "triage action"],
            "overlay_callouts": ["fit check", "upgrade state", "triage lane", "trust mark"],
            "scene_contract": {
                "composition": "clinic_intake",
                "subject": "streetdoc patches a runner in a clinic intake lane",
                "props": ["med pouch", "prep chair", "injector tray", "gear rail"],
                "overlays": ["fit check", "upgrade state", "trust mark", "triage lane"],
            },
        },
    )

    assert "critical_lore:missing_metahuman_cue" in findings
    assert "critical_cast:missing_troll_patient" in findings
    assert "critical_lore:missing_streetdoc_garage_clinic" in findings
    assert "critical_anchor_missing:cyberware" in findings
    assert "critical_scene:missing_cyberware_surgery" in findings
    assert "critical_detail:missing_troll_microtexture" in findings
    assert "critical_overlay:missing_medscan_posture" in findings


def test_critical_visual_findings_require_actionful_forge_review_scene() -> None:
    worker = _load_worker_module()

    findings = worker.critical_visual_findings_for_target(
        "assets/horizons/karma-forge.png",
        {
            "visual_motifs": ["generic workshop", "quiet paperwork", "approval drift", "orange glow"],
            "overlay_callouts": ["receipt traces", "quiet review"],
            "scene_contract": {
                "composition": "approval_rail",
                "subject": "two operators talk quietly in a generic workshop",
                "environment": "a quiet workshop bench with paperwork and diffuse orange glow",
                "action": "reviewing the packet in place",
                "props": ["paperwork stack", "workbench", "soft glow"],
                "overlays": ["receipt traces", "quiet review", "approval drift"],
            },
        },
    )

    assert "critical_scene:generic_workshop_drift" in findings
    assert "critical_scene:missing_action_posture" in findings
    assert "critical_overlay:missing_forge_review_ar" in findings


def test_overlay_mode_for_target_tracks_flagship_assets() -> None:
    worker = _load_worker_module()

    assert worker.overlay_mode_for_target("assets/hero/chummer6-hero.png") == "medscan_diagnostic"
    assert worker.overlay_mode_for_target("assets/pages/horizons-index.png") == "ambient_diegetic"
    assert worker.overlay_mode_for_target("assets/horizons/karma-forge.png") == "forge_review_ar"


def test_normalize_media_override_biases_hero_and_karma_forge_away_from_quiet_solo_defaults() -> None:
    worker = _load_worker_module()

    hero = worker.normalize_media_override(
        "hero",
        {
            "badge": "TRUST CHECK",
            "title": "Chummer6",
            "subtitle": "Let the build show its work before the table has to improvise trust.",
            "kicker": "See the upgrade pressure before it goes live.",
            "note": "Concept-stage only. If anything looks usable, treat it as accidental spillover rather than support.",
            "meta": "Idea stage | accidental public traces only",
            "visual_prompt": "Quiet operator in a dim bay.",
            "overlay_hint": "BUILD_TRACE",
            "visual_motifs": [],
            "overlay_callouts": [],
            "scene_contract": {},
        },
        {},
    )
    hero["visual_prompt"] = "An ork streetdoc patches a wounded runner in an improvised garage clinic with hacked cyberware gear, tool chest grime, and visible BOD AGI REA ESS EDGE rails."
    hero["overlay_hint"] = "BOD AGI REA ESS EDGE UPGRADING"
    hero["visual_motifs"] = ["garage clinic grime", "streetdoc assist", "attribute rail", "runner life", "cyberware surgery"]
    hero["overlay_callouts"] = ["BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING"]
    hero["scene_contract"].update(
        {
            "subject": "an ork streetdoc patches a wounded runner while a teammate assists",
            "environment": "an improvised garage clinic with tool chest grime, tarp dividers, work lamps, extension cords, and hacked cyberware gear",
            "props": ["tool chest", "med-gel", "cyberware part", "six-sided dice", "magical focus"],
            "overlays": ["BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING"],
        }
    )
    forge = worker.normalize_media_override(
        "horizon",
        {
            "badge": "FLAGSHIP",
            "title": "KARMA FORGE",
            "subtitle": "Governed rules evolution under pressure.",
            "kicker": "Approval and rollback before folklore.",
            "note": "An expensive experiment lane. Even a careful run here can still end in a dead lane rather than a durable feature.",
            "meta": "Concept lane | expensive experiments, no promises",
            "visual_prompt": "One operator at a glowing console.",
            "overlay_hint": "VALIDATION",
            "visual_motifs": [],
            "overlay_callouts": [],
            "scene_contract": {},
        },
        {"slug": "karma-forge", "title": "KARMA FORGE"},
    )
    forge["visual_prompt"] = "A rulesmith and reviewer stand at an industrial rules lab approval rail with DIFF APPROVAL PROVENANCE and ROLLBACK overlays."
    forge["overlay_hint"] = "DIFF APPROVAL PROVENANCE ROLLBACK"
    forge["visual_motifs"] = ["rules lab", "approval rail", "rollback rig", "review witness"]
    forge["overlay_callouts"] = ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"]
    forge["scene_contract"].update(
        {
            "subject": "a rulesmith and reviewer reconcile a forged rules packet",
            "environment": "an industrial rules lab with an approval rail, rollback rig, provenance seals, and rule cassettes",
            "props": ["rule cassette", "approval seal", "diff strip", "rollback rig"],
            "overlays": ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"],
        }
    )

    assert "streetdoc" in hero["scene_contract"]["subject"]
    assert "runner" in hero["scene_contract"]["subject"]
    assert "BOD" in hero["scene_contract"]["overlays"]
    assert "UPGRADING" in hero["scene_contract"]["overlays"]
    assert "rulesmith and reviewer" in forge["scene_contract"]["subject"]
    assert "approval rail" in forge["scene_contract"]["environment"]


def test_scene_plan_pack_audit_rejects_quiet_single_person_hero_metadata() -> None:
    worker = _load_worker_module()

    with pytest.raises(RuntimeError, match="scene_plan_audit_failed:critical_targets"):
        worker.scene_plan_pack_audit(
            {
                "media": {
                    "hero": {
                        "visual_prompt": "One operator in a dim bay beside a wall of vague props.",
                        "overlay_hint": "receipt traces",
                        "visual_motifs": ["quiet mood", "neon melancholy"],
                        "overlay_callouts": ["receipt traces"],
                        "scene_contract": {
                            "subject": "one operator alone at a vague prop wall",
                            "environment": "a dim bay with empty corners",
                            "action": "thinking quietly before the next move",
                            "metaphor": "brooding profile",
                            "composition": "solo_operator",
                            "props": ["one vague wall"],
                            "overlays": ["receipt traces"],
                        },
                    },
                    "parts": {},
                    "horizons": {},
                }
            }
        )


def test_scene_plan_pack_audit_rejects_generic_single_operator_karma_forge_metadata() -> None:
    worker = _load_worker_module()

    with pytest.raises(RuntimeError, match="scene_plan_audit_failed:critical_targets"):
        worker.scene_plan_pack_audit(
            {
                "media": {
                    "hero": {},
                    "parts": {},
                    "horizons": {
                        "karma-forge": {
                            "title": "KARMA FORGE",
                            "visual_prompt": "One operator at a glowing console in a quiet workshop.",
                            "overlay_hint": "receipt traces",
                            "visual_motifs": ["orange glow", "card tinkering"],
                            "overlay_callouts": ["receipt traces"],
                            "scene_contract": {
                                "subject": "one operator alone at a console",
                                "environment": "a quiet desk still life with orange glow props",
                                "action": "tinkering with rules cards in private",
                                "metaphor": "generic glowing workshop",
                                "composition": "solo_operator",
                                "props": ["glow cards"],
                                "overlays": ["receipt traces"],
                            },
                        }
                    },
                }
            }
        )


def test_scene_plan_pack_audit_accepts_dense_hero_and_karma_forge_defaults() -> None:
    worker = _load_worker_module()

    hero = worker.normalize_media_override(
        "hero",
        {
            "badge": "Streetdoc Scan",
            "title": "Chummer6",
            "subtitle": "Let the build show its work before the table improvises trust.",
            "kicker": "See the upgrade pressure before it goes live.",
            "note": "Concept-stage only. If anything looks usable, treat it as accidental spillover rather than support.",
            "meta": "Idea stage | accidental public traces only",
            "visual_prompt": "An ork streetdoc patches an ugly hairy troll runner inside an improvised garage clinic with hacked med gear and visible BOD AGI REA ESS EDGE rails.",
            "overlay_hint": "BOD AGI REA ESS EDGE UPGRADING",
            "visual_motifs": ["garage clinic grime", "streetdoc assist", "attribute rail", "runner life"],
            "overlay_callouts": ["BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING"],
            "scene_contract": {
                "subject": "an ork streetdoc patches an ugly hairy troll runner while a teammate assists",
                "environment": "an improvised garage clinic with tool chest grime, tarp dividers, work lamps, and extension cords",
                "props": ["tool chest", "med-gel", "cyberware part", "six-sided dice", "magical focus"],
                "overlays": ["BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING"],
            },
        },
        {},
    )
    hero["visual_prompt"] = "An ork streetdoc patches an ugly hairy troll runner inside an improvised garage clinic with hacked cyberware gear, visible tusks, rough scarred skin, matted hair, and visible BOD AGI REA ESS EDGE rails."
    hero["overlay_hint"] = "medscan diagnostic rail with AGI/ESS upgrade markers, cyberlimb calibration, wound stabilization, and neural link resync"
    hero["visual_motifs"] = ["garage clinic grime", "streetdoc assist", "attribute rail", "runner life", "cyberware surgery"]
    hero["overlay_callouts"] = ["Wound stabilized", "Cyberlimb calibration", "Neural link resync"]
    hero["scene_contract"].update(
        {
            "subject": "an ork streetdoc and ugly hairy troll runner in a garage clinic while a teammate assists",
            "environment": "an improvised garage clinic with tool chest grime, tarp dividers, work lamps, extension cords, and hacked cyberware gear",
            "action": "stabilizing an ugly hairy troll runner with tusks, rough scarred skin, dermal texture, and matted hair while calibrating a patched cyberlimb under pressure",
            "props": ["tool chest", "med-gel", "cyberware part", "six-sided dice", "magical focus"],
            "overlays": ["BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING"],
        }
    )
    forge = worker.normalize_media_override(
        "horizon",
        {
            "badge": "Flagship",
            "title": "KARMA FORGE",
            "subtitle": "Governed rules evolution under pressure.",
            "kicker": "Approval and rollback before folklore.",
            "note": "An expensive experiment lane. Even a careful run here can still end in a dead lane rather than a durable feature.",
            "meta": "Concept lane | expensive experiments, no promises",
            "visual_prompt": "A rulesmith and reviewer stand at an industrial rules lab approval rail with DIFF APPROVAL PROVENANCE and ROLLBACK overlays.",
            "overlay_hint": "DIFF APPROVAL PROVENANCE ROLLBACK",
            "visual_motifs": ["rules lab", "approval rail", "rollback rig", "review witness"],
            "overlay_callouts": ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"],
            "scene_contract": {
                "subject": "a rulesmith and reviewer reconcile a forged rules packet",
                "environment": "an industrial rules lab with an approval rail, rollback rig, provenance seals, and rule cassettes",
                "props": ["rule cassette", "approval seal", "diff strip", "rollback rig"],
                "overlays": ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"],
            },
        },
        {"slug": "karma-forge", "title": "KARMA FORGE"},
    )
    forge["visual_prompt"] = "A rulesmith and reviewer stand at an industrial rules lab approval rail with DIFF APPROVAL PROVENANCE and ROLLBACK overlays."
    forge["overlay_hint"] = "forge review rails with provenance seals, rollback vectors, approval chips, and witness lock"
    forge["visual_motifs"] = ["rules lab", "approval rail", "rollback rig", "review witness"]
    forge["overlay_callouts"] = ["Approval rail", "Provenance seal", "Rollback vector", "Witness lock"]
    forge["scene_contract"].update(
        {
            "subject": "a rulesmith and reviewer reconcile a forged rules packet",
            "environment": "an industrial rules lab with an approval rail, rollback rig, provenance seals, and rule cassettes",
            "action": "forcing unstable rule cassettes through the approval rail while a reviewer locks witness control",
            "props": ["rule cassette", "approval seal", "diff strip", "rollback rig"],
            "overlays": ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"],
        }
    )

    result = worker.scene_plan_pack_audit(
        {
            "media": {
                "hero": hero,
                "parts": {},
                "horizons": {"karma-forge": forge},
            }
        }
    )

    assert result["status"] == "ok"
    assert result["critical_target_findings"] == []


def test_copy_quality_findings_rejects_internal_part_posture_language() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "part",
        "hub",
        {
            "when": "If there is ever a hosted front door, hub is the layer that would have to keep it coherent.",
            "why": "It represents the hosted identity and coordination story the concept would need later.",
            "now": "For now it mostly means public posture and a few hosted traces.",
        },
        worker.PARTS["hub"],
    )

    assert any("visible public jobs" in finding for finding in findings)


def test_fallback_horizon_copy_translates_booster_lane_into_plain_preview_language() -> None:
    worker = _load_worker_module()

    row = worker.fallback_horizon_copy("karma-forge", worker.HORIZONS["karma-forge"])

    assert "booster lane" not in row["why_waits"].lower()
    assert "optional paid preview" in row["why_waits"].lower()


def test_normalize_media_override_strips_overliteralized_weapon_diagnostics_and_reanchors_scene() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "hero",
        {
            "badge": "PROTOCOL: CORE VERITY",
            "title": "No More Trust-Me Math",
            "subtitle": "An idea trace, not a finished tool.",
            "kicker": "Inspect the direction.",
            "note": "Concept-stage only.",
            "meta": "concept",
            "visual_prompt": (
                "A weathered runner checks a customized Ares Predator pistol while a holographic HUD highlights "
                "smartlink electronics, barrel rifling, and the weapon's accuracy and damage modifiers."
            ),
            "overlay_hint": "Display 'Link Verified' telemetry beside the weapon.",
            "visual_motifs": ["runner", "receipt traces"],
            "overlay_callouts": ["receipt traces", "EVIDENCE CHAIN"],
            "scene_contract": {"composition": "city_edge"},
        },
        {},
    )

    lowered_prompt = normalized["visual_prompt"].lower()
    assert "ares predator" not in lowered_prompt
    assert "barrel rifling" not in lowered_prompt
    assert "damage modifiers" not in lowered_prompt
    assert "link verified" not in normalized["overlay_hint"].lower()
    assert normalized["scene_contract"]["composition"] == "clinic_intake"
    assert "cyberlimb calibration" in " ".join(normalized["scene_contract"]["overlays"]).lower()


def test_normalize_media_override_reanchors_generic_horizon_scene_contract_and_status_labels() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "SECURE_ARCHIVE",
            "title": "RUNBOOK PRESS",
            "subtitle": "Long-form Publishing",
            "kicker": "Dossier Engine",
            "note": "Linked to source truth.",
            "meta": "LUA_DRIVEN | HASH_VERIFIED | ZERO_DRIFT",
            "visual_prompt": "A data-broker inspects a ruggedized district guide on a cracked data-slate.",
            "overlay_hint": "Mock 'Approval Chain' stamps and layout guides",
            "visual_motifs": [
                "a cyberpunk protagonist",
                "Rust amber typography",
                "Ruggedized hardware surfaces",
            ],
            "overlay_callouts": [
                "Source Truth Verified",
                "Artifact Ready for Print",
            ],
            "scene_contract": {
                "subject": "a cyberpunk protagonist",
                "environment": "a dangerous but inviting cyberpunk scene",
                "action": "framing the next move before the chrome starts smoking",
                "metaphor": "scene-aware cyberpunk guide art",
                "props": ["wet chrome", "holographic receipts", "rain haze"],
                "overlays": ["signal arcs"],
                "composition": "horizon_boulevard",
                "palette": "cyan-magenta neon",
                "mood": "dangerous, curious, and slightly amused",
            },
        },
        {"slug": "runbook-press", "title": "RUNBOOK PRESS"},
    )

    assert normalized["meta"] == "Flagship lane | publication with receipts"
    assert normalized["scene_contract"]["subject"] == "a campaign writer pushing raw district material through a rail-side proof room"
    assert normalized["scene_contract"]["composition"] == "proof_room"
    assert "Source Truth Verified" not in normalized["overlay_callouts"]
    assert "Artifact Ready for Print" not in normalized["overlay_callouts"]
    assert "a cyberpunk protagonist" not in normalized["visual_motifs"]


def test_normalize_media_override_derives_horizon_asset_key_from_title_when_slug_missing() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "BOOSTER_FIRST",
            "title": "KARMA FORGE",
            "subtitle": "Logic Foundry & Ruleset Governance",
            "kicker": "CUSTOM LOGIC, GOVERNED",
            "note": "The math is the law; the Forge is where you rewrite it.",
            "meta": "Concept lane | future-facing and unpromised",
            "visual_prompt": "Close-up of a scarred dwarf technician in a leather apron, using a petrol-cyan laser to etch glowing Shadowrun logic into a rust-amber core, heavy film grain, 35mm handheld, damp interior workshop.",
            "overlay_hint": "VALIDATING_RULES_SIGNATURE",
            "visual_motifs": [],
            "overlay_callouts": [],
            "scene_contract": {
                "subject": "a cyberpunk protagonist",
                "environment": "a dangerous but inviting cyberpunk scene",
                "action": "framing the next move before the chrome starts smoking",
                "metaphor": "scene-aware cyberpunk guide art",
                "composition": "single_protagonist",
            },
        },
        {"title": "KARMA FORGE"},
    )

    assert normalized["badge"] == "Expensive Lane"
    assert normalized["kicker"] == "house rules with rollback dreams"
    assert normalized["note"] == "A governed change lane with approval, rollback, and explicit risk controls."
    assert normalized["meta"] == "Flagship lane | governed rule evolution"
    assert normalized["overlay_hint"] == "forge review rails with provenance seals, rollback vectors, approval chips, and witness lock"
    assert normalized["scene_contract"]["subject"] == "a standing rulesmith and skeptical reviewer forcing unstable house-rule packs through an industrial approval rail while the apparatus looms larger than they do"
    assert normalized["scene_contract"]["environment"] == "an improvised industrial rules lab with approval rails, rollback rig hardware, provenance seals, consequence chambers, assay racks, cassette bins, gantry hooks, sample lockers, and hard sodium spill"
    assert normalized["scene_contract"]["composition"] == "approval_rail"


def test_normalize_media_override_preserves_curated_scene_contract_for_known_horizon_assets() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "horizon",
        {
            "badge": "ARCHIVAL-GOVERNANCE",
            "title": "RUNBOOK PRESS",
            "subtitle": "LONG-FORM PUBLISHING LANE",
            "kicker": "CODE-GOVERNED LORE",
            "note": "The professional weight and authority of a physical handbook.",
            "meta": "Concept lane | future-facing and unpromised",
            "visual_prompt": "A cybernetic archivist in a heavy charcoal trench coat, Forge visual device showing glowing rust-amber data-shards merging into a digital book spine. Rainy night dockside storage unit setting, flickering fluorescent light, damp concrete. Documentary cyberpunk realism, 35mm film grain.",
            "overlay_hint": "HUD callouts for 'Provenance Verified' and 'Governance Applied'.",
            "visual_motifs": [],
            "overlay_callouts": [],
            "scene_contract": {
                "subject": "an archivist sorting volatile evidence into usable shape",
                "environment": "a dangerous but inviting cyberpunk scene",
                "action": "hammering volatile rules into controlled shape",
                "metaphor": "forge sparks and molten rules",
                "composition": "workshop_bench",
            },
        },
        {"title": "RUNBOOK PRESS"},
    )

    assert normalized["badge"] == "Handbook Lane"
    assert normalized["kicker"] == "books that still remember the source"
    assert normalized["note"] == "A handbook lane that preserves source memory through publication."


def test_normalize_media_override_clamps_statusish_badges_notes_and_overlay_hints() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_media_override(
        "hero",
        {
            "badge": "Tactical Dossier",
            "title": "Math With Receipts",
            "subtitle": "An idea trace, not a finished tool.",
            "kicker": "Inspect the direction.",
            "note": "PROTOTYPE LOGIC",
            "meta": "concept",
            "visual_prompt": "One runner checks a suspect ruling in the rain while a receipt trail blooms over the evidence.",
            "overlay_hint": "Dossier metadata HUD",
            "visual_motifs": ["runner", "receipt traces"],
            "overlay_callouts": ["receipt traces"],
            "scene_contract": {"composition": "over_shoulder_receipt"},
        },
        {},
    )

    assert normalized["badge"] == "Streetdoc Scan"
    assert normalized["note"] == "Early-access surface. Treat visible artifacts as inspectable evidence with active boundaries."
    assert "metadata hud" not in normalized["overlay_hint"].lower()
    assert "medscan diagnostic rail" in normalized["overlay_hint"].lower()
    assert "trust check" not in normalized["overlay_hint"].lower()
    assert "concept" in normalized["meta"].lower()
    assert normalized["overlay_callouts"] == [
        "cyberlimb calibration",
        "Wound stabilized",
        "Neural link resync",
    ]
    assert "runner" in normalized["scene_contract"]["subject"].lower()
    assert "calibrating" in normalized["scene_contract"]["action"].lower() or "upgrade" in normalized["scene_contract"]["action"].lower()
    assert normalized["scene_contract"]["composition"] == "clinic_intake"


def test_collect_interest_signals_prefers_public_safe_sources() -> None:
    worker = _load_worker_module()

    signals = worker.collect_interest_signals()
    joined = "\n".join(signals["snippets"])

    assert "[feature:" in joined
    assert "[part:hub]" in joined
    assert "[horizon:karma-forge]" in joined
    assert "feature:get_the_poc" not in joined
    assert "feature:sign_in_follow" not in joined
    assert "deterministic rules truth" not in joined.lower()
    assert "design_architecture" not in joined
    assert "design_milestones" not in joined
    assert "hub_readme" not in joined
    assert "help:booster_lane" not in joined


def test_page_supporting_context_does_not_globalize_booster_copy() -> None:
    worker = _load_worker_module()

    for page_id in ("start_here", "public_surfaces", "where_to_go_deeper"):
        joined = "\n".join(worker.page_supporting_context(page_id)).lower()
        assert "booster" not in joined


def test_page_supporting_context_filters_old_product_signals_from_root_pages() -> None:
    worker = _load_worker_module()

    joined = "\n".join(worker.page_supporting_context("start_here")).lower()

    assert "get the poc" not in joined
    assert "current drop" not in joined
    assert "deterministic rules truth" not in joined


def test_page_prompts_include_faq_and_help_ids() -> None:
    worker = _load_worker_module()

    assert "faq" in worker.PAGE_PROMPTS
    assert "how_can_i_help" in worker.PAGE_PROMPTS
    assert worker.PAGE_PROMPTS["faq"]["source"]
    assert worker.PAGE_PROMPTS["how_can_i_help"]["source"]
    assert "Do I need an account to download the current preview?" in worker.PAGE_PROMPTS["faq"]["source"]
    assert "one clear public download" in worker.PAGE_PROMPTS["how_can_i_help"]["source"]


def test_copy_quality_findings_requires_concrete_public_surface_on_first_contact_pages() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "start_here",
        {
            "title": "Start Here",
            "lead": "Chummer6 is the clean answer to Shadowrun math chaos.",
            "body": "Everything is ready for your next session and the future is already lined up.",
            "cta": "Jump in.",
        },
        {"title": "Start Here"},
    )

    joined = " ".join(findings).lower()
    assert "visible public surface" in joined or "future lane" in joined


def test_copy_quality_findings_flags_risky_page_specific_claims_outside_context() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "public_surfaces",
        {
            "intro": "The public workbench is visible now.",
            "body": "The current preview already verifies gear limits and character integrity with total precision on your phone.",
            "kicker": "Check it out.",
        },
        worker.PAGE_PROMPTS["public_surfaces"],
    )

    joined = " ".join(findings).lower()
    assert "do not invent exact present-tense feature claims" in joined


def test_copy_quality_findings_flags_unsupported_root_page_scope_leakage() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "current_status",
        {
            "intro": "The mobile-ready interface already handles live data across a multi-era engine.",
            "body": "Tonight you can validate augmentations, combat turns, and karma spend with lua-scripted precision.",
            "kicker": "Take it for a spin.",
        },
        worker.PAGE_PROMPTS["current_status"],
    )

    joined = " ".join(findings).lower()
    assert "do not invent exact present-tense feature claims" in joined
    assert "avoid specific subsystem, edition, or character-sheet examples" in joined


def test_copy_quality_findings_flags_math_certainty_on_root_pages() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "what_chummer6_is",
        {
            "intro": "Chummer6 already delivers rules truth.",
            "body": "The deterministic rules engine now settles every stat and threshold.",
            "kicker": "Trust the math.",
        },
        worker.PAGE_PROMPTS["what_chummer6_is"],
    )

    joined = " ".join(findings).lower()
    assert "rules math is already settled" in joined


def test_copy_quality_findings_flags_totalizing_math_claims_on_root_pages() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "what_chummer6_is",
        {
            "intro": "Chummer6 replaces trust-me math with visible proof.",
            "body": "Every bonus, penalty, and threshold in the current drop carries a provenance receipt.",
            "kicker": "Check the proof shelf before you trust it.",
        },
        worker.PAGE_PROMPTS["what_chummer6_is"],
    )

    joined = " ".join(findings).lower()
    assert "avoid universal math claims on root pages" in joined


def test_copy_quality_findings_flags_grid_and_receipt_overclaims_on_root_pages() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "public_surfaces",
        {
            "intro": "This page maps the visible proof shelf and the current POC drop.",
            "body": "The local-first build already works without a grid connection, keeps your data on your device, and every functioning mechanic includes a receipt you can trust.",
            "kicker": "Download the build and trust the math.",
        },
        worker.PAGE_PROMPTS["public_surfaces"],
    )

    joined = " ".join(findings).lower()
    assert "do not invent exact present-tense feature claims" in joined
    assert "avoid universal math claims on root pages" in joined
    assert "rules math is already settled" in joined


def test_copy_quality_findings_requires_public_surfaces_intro_to_name_surfaces() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "public_surfaces",
        {
            "intro": "Chummer6 keeps the receipts visible.",
            "body": "You can read the guide, inspect the proof shelf, check the horizon shelf, and hit the issue tracker.",
            "kicker": "Start with what is real.",
        },
        worker.PAGE_PROMPTS["public_surfaces"],
    )

    joined = " ".join(findings).lower()
    assert "public_surfaces should open by naming the visible surfaces" in joined


def test_copy_quality_findings_requires_help_page_to_open_with_help_action() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "how_can_i_help",
        {
            "intro": "Chummer6 is a rough local-first prep surface.",
            "body": "Grab the current drop, test it, and file issues when the math breaks.",
            "kicker": "Help us by stress-testing what is real.",
        },
        worker.PAGE_PROMPTS["how_can_i_help"],
    )

    joined = " ".join(findings).lower()
    assert "how_can_i_help should open with a concrete help action" in joined


def test_copy_quality_findings_requires_faq_page_to_open_like_answers() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "faq",
        {
            "intro": "Chummer6 is a rough local-first prep surface.",
            "body": "You can use it today, and the current drop is on the releases page.",
            "kicker": "Check what works and report what breaks.",
        },
        worker.PAGE_PROMPTS["faq"],
    )

    joined = " ".join(findings).lower()
    assert "faq should open like practical user questions are being answered" in joined


def test_copy_quality_findings_flags_frozen_bad_root_opening_patterns() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "readme",
        {
            "intro": "Stop burning your prep time arguing over whether a smartlink bonus stacks with your custom optics.",
            "body": "Check the proof shelf and current drop.",
            "kicker": "Keep it rough and honest.",
        },
        worker.PAGE_PROMPTS["readme"],
    )

    joined = " ".join(findings).lower()
    assert "frozen bad-opening patterns" in joined


def test_copy_quality_findings_flags_readme_imperative_opening_without_concept_posture() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "readme",
        {
            "intro": "Stop guessing your dice pools. Start auditing them.",
            "body": "Check the public guide and the accidental traces.",
            "kicker": "Stay skeptical.",
        },
        worker.PAGE_PROMPTS["readme"],
    )

    joined = " ".join(findings).lower()
    assert "command-style invitation" in joined


def test_copy_quality_findings_flags_soft_synthetic_page_phrasing() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "what_chummer6_is",
        {
            "intro": "Chummer6 is a character engine.",
            "body": "This session shell is a local-first system for proof.",
            "kicker": "Check it out.",
        },
        worker.PAGE_PROMPTS["what_chummer6_is"],
    )

    joined = " ".join(findings).lower()
    assert "replace synthetic product phrasing" in joined


def test_copy_quality_findings_flags_proof_of_concept_pitch_on_root_pages() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "what_chummer6_is",
        {
            "intro": "Chummer6 is a local-first rules prep surface.",
            "body": "You can run the current Proof of Concept or download the current drop to see it in action.",
            "kicker": "Judge the engine directly.",
        },
        worker.PAGE_PROMPTS["what_chummer6_is"],
    )

    joined = " ".join(findings).lower()
    assert "runnable proof-of-concept" in joined


def test_fallback_page_copy_is_reader_safe_for_what_chummer6_is() -> None:
    worker = _load_worker_module()

    row = worker.fallback_page_copy("what_chummer6_is", worker.PAGE_PROMPTS["what_chummer6_is"], {})

    assert row["intro"]
    assert "shadowrun tooling" in row["intro"].lower() or "receipts" in row["body"].lower()
    worker.assert_public_reader_safe(row, context="page:what_chummer6_is:fallback")


def test_fallback_page_copy_covers_faq_and_help_pages() -> None:
    worker = _load_worker_module()

    faq_row = worker.fallback_page_copy("faq", worker.PAGE_PROMPTS["faq"], {})
    help_row = worker.fallback_page_copy("how_can_i_help", worker.PAGE_PROMPTS["how_can_i_help"], {})

    assert "what can you inspect and use right now" in faq_row["intro"].lower()
    assert "reproducible evidence" in help_row["kicker"].lower() or "user pain" in help_row["kicker"].lower()
    assert "booster" not in json.dumps({"faq": faq_row, "help": help_row}).lower()
    worker.assert_public_reader_safe(faq_row, context="page:faq:fallback")
    worker.assert_public_reader_safe(help_row, context="page:how_can_i_help:fallback")


def test_fallback_page_copy_covers_index_and_deeper_pages() -> None:
    worker = _load_worker_module()

    deeper = worker.fallback_page_copy("where_to_go_deeper", worker.PAGE_PROMPTS["where_to_go_deeper"], {})
    parts = worker.fallback_page_copy("parts_index", worker.PAGE_PROMPTS["parts_index"], {})
    horizons = worker.fallback_page_copy("horizons_index", worker.PAGE_PROMPTS["horizons_index"], {})

    assert "guide" in deeper["kicker"].lower() or "proof" in deeper["kicker"].lower()
    assert "part" in parts["intro"].lower()
    assert "next lanes" in horizons["intro"].lower()
    worker.assert_public_reader_safe(deeper, context="page:where_to_go_deeper:fallback")
    worker.assert_public_reader_safe(parts, context="page:parts_index:fallback")
    worker.assert_public_reader_safe(horizons, context="page:horizons_index:fallback")


def test_fallback_part_copy_is_reader_safe_for_core() -> None:
    worker = _load_worker_module()

    row = worker.fallback_part_copy("core", worker.PARTS["core"])

    assert "idea" in row["when"].lower() or "trust" in row["why"].lower()
    worker.assert_public_reader_safe(row, context="part:core:fallback")


def test_fallback_horizon_copy_keeps_karma_forge_booster_honesty() -> None:
    worker = _load_worker_module()

    row = worker.fallback_horizon_copy("karma-forge", worker.HORIZONS["karma-forge"])

    lowered = json.dumps(row).lower()
    assert "optional paid preview" in lowered or "preview" in lowered
    assert "not" in row["why_waits"].lower() or "not" in row["meanwhile"].lower()
    worker.assert_public_reader_safe(row, context="horizon:karma-forge:fallback")


def test_fallback_horizon_copy_keeps_non_karma_horizons_free_of_booster_copy() -> None:
    worker = _load_worker_module()

    row = worker.fallback_horizon_copy("jackpoint", worker.HORIZONS["jackpoint"])

    lowered = json.dumps(row).lower()
    assert "booster" not in lowered
    assert "participate" not in lowered
    worker.assert_public_reader_safe(row, context="horizon:jackpoint:fallback")


def test_fallback_horizon_copy_uses_varied_scene_lengths() -> None:
    worker = _load_worker_module()

    counts = {
        name: len(
            [
                line
                for line in worker.fallback_horizon_copy(name, worker.HORIZONS[name])["table_scene"].splitlines()
                if line.strip()
            ]
        )
        for name in ("nexus-pan", "alice", "karma-forge", "jackpoint", "runsite", "runbook-press", "table-pulse")
    }

    assert len(set(counts.values())) >= 3


def test_media_easter_egg_allowed_is_sparse_by_default_but_respects_force_policy() -> None:
    worker = _load_worker_module()

    assert worker.media_easter_egg_allowed(kind="hero", item={}, contract={}) is False
    assert worker.media_easter_egg_allowed(kind="part", item={"slug": "ui"}, contract={}) is False
    assert worker.media_easter_egg_allowed(
        kind="part",
        item={"slug": "ui"},
        contract={"easter_egg_policy": "deny"},
    ) is False
    assert worker.media_easter_egg_allowed(
        kind="part",
        item={"slug": "ui"},
        contract={"easter_egg_policy": "force"},
    ) is True


def test_part_supporting_context_does_not_inject_booster_copy_into_hub() -> None:
    worker = _load_worker_module()

    joined = "\n".join(worker.part_supporting_context("hub")).lower()
    assert "booster" not in joined
    assert "participate" not in joined


def test_build_page_prompt_includes_supporting_public_context() -> None:
    worker = _load_worker_module()

    prompt = worker.build_page_prompt("start_here", worker.PAGE_PROMPTS["start_here"])

    assert "Supporting public context" in prompt
    assert (
        "See what is real now" in prompt
        or "Check the live proof shelf" in prompt
        or "Live now" in prompt
        or "Preview releases, channels, and notes" in prompt
    )


def test_build_horizon_prompt_includes_rollout_access_canon() -> None:
    worker = _load_worker_module()

    prompt = worker.build_horizon_prompt("karma-forge", worker.HORIZONS["karma-forge"])

    assert "Access posture:" in prompt
    assert "Booster nudge:" in prompt
    assert "Free-later intent:" in prompt
    assert "Booster API scope note:" in prompt
    assert "Booster outcome note:" in prompt
    assert "avoid the default symmetrical five-line GM/player exchange" in prompt


def test_build_media_prompt_hardens_hero_and_forge_scene_requirements() -> None:
    worker = _load_worker_module()

    hero_prompt = worker.build_media_prompt("hero", "hero", {})
    forge_prompt = worker.build_media_prompt("horizon", "karma-forge", worker.HORIZONS["karma-forge"])

    assert "ugly troll patient" in hero_prompt
    assert "improvised garage clinic" in hero_prompt
    assert "white-coat doctor staging" in hero_prompt
    assert "standing rulesmith plus reviewer or witness" in forge_prompt
    assert "industrial approval rail" in forge_prompt
    assert "quiet workbench or paperwork table" in forge_prompt


def test_build_horizons_bundle_prompt_requires_scene_cadence_variation() -> None:
    worker = _load_worker_module()

    prompt = worker.build_horizons_bundle_prompt(
        items={"karma-forge": worker.HORIZONS["karma-forge"], "jackpoint": worker.HORIZONS["jackpoint"]},
        global_ooda={},
        section_oodas={},
        style_epoch={},
        recent_scenes=[],
    )

    assert "vary `table_scene` cadence across the set" in prompt
    assert "mix beat counts, speaker mixes" in prompt


def test_non_karma_horizons_do_not_carry_booster_rollout_context() -> None:
    worker = _load_worker_module()

    rollout = worker.horizon_rollout_context("jackpoint", worker.HORIZONS["jackpoint"])

    assert rollout == {
        "access_posture": "",
        "resource_burden": "",
        "booster_nudge": "",
        "free_later_intent": "",
        "booster_api_scope_note": "",
        "booster_outcome_note": "",
    }


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

    joined = " ".join(findings).lower()
    assert "generic filler" in joined
    assert "booster-first preview posture" in joined
    assert "broad-access or free-later intent" in joined
    assert "expensive and review-heavy even in preview" in joined
    assert "may still produce nothing useful or shippable" in joined


def test_copy_quality_findings_does_not_force_booster_copy_for_non_karma_horizons() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "horizon",
        "jackpoint",
        {
            "hook": "Finished briefings that keep their receipts.",
            "problem": "I want dossiers and recaps that do not lie to me.",
            "table_scene": "\n".join(
                [
                    "GM: The packet lands before the van does.",
                    "Face: Good. I need the lie polished, not invented.",
                    "Rigger: The route overlay finally reads like a real plan.",
                    "Decker: And the citations still point back to the real evidence.",
                    "GM: That is the whole point.",
                ]
            ),
            "meanwhile": "- Proof stays attached to the pretty version.\n- The brief reads fast without losing receipts.",
            "why_great": "It turns grim notes into artifacts people can actually use at the table.",
            "why_waits": "The packaging only matters if provenance survives the polish.",
            "pitch_line": "Make the packet look finished without making the facts up.",
        },
        worker.HORIZONS["jackpoint"],
    )

    joined = " ".join(findings).lower()
    assert "booster-first preview posture" not in joined
    assert "free-later" not in joined


def test_copy_quality_findings_flags_horizon_shape_drift() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "horizon",
        "karma-forge",
        {
            "hook": "Custom rules with receipts.",
            "problem": "House rules usually break the sheet.",
            "table_scene": "GM: Use the house rules tonight.\nPlayer: Okay.",
            "meanwhile": "Sandboxing scripts and compatibility checks.",
            "why_great": "It keeps the math inspectable.",
            "why_waits": "It is booster-first while safety work lands.",
            "pitch_line": "Help us make it broader later.",
        },
        worker.HORIZONS["karma-forge"],
    )

    joined = " ".join(findings)
    assert "table_scene" in joined
    assert "meanwhile" in joined


def test_copy_quality_findings_flags_truncated_public_copy() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "current_phase",
        {
            "intro": "The current phase is grounded trust work.",
            "body": "The current phase is still grounded tr…",
            "kicker": "Trust work first, product posture later.",
        },
        worker.PAGE_PROMPTS["current_phase"],
    )

    joined = " ".join(findings).lower()
    assert "truncated public copy" in joined


def test_global_ooda_defaults_do_not_force_trolls_or_edgy_dev_snark() -> None:
    worker = _load_worker_module()

    defaults = worker._global_ooda_defaults({"tags": ["multi_era_rulesets"], "snippets": []})
    orient = defaults["orient"]
    decide = defaults["decide"]
    act = defaults["act"]

    assert "troll reference per image" not in orient["visual_direction"].lower()
    assert "accelerants" not in orient["humor_line"].lower()
    assert "growth funnel with a knife" not in decide["cta_strategy"].lower()
    assert "future troublemakers" not in act["horizon_intro"].lower()


def test_humanized_candidate_findings_rejects_new_root_page_overclaims() -> None:
    worker = _load_worker_module()

    source = (
        "You can inspect the proof shelf, grab the current drop from releases, "
        "and judge what is real before the project earns bigger promises."
    )
    candidate = (
        "You can inspect the proof shelf while the build works without a grid connection, "
        "and every result already includes trustworthy math receipts."
    )

    findings = worker.humanized_candidate_findings(source, candidate)

    assert "introduced_math_certainty" in findings
    assert "introduced_totalizing_claim" in findings
    assert "introduced_specific_claim" in findings


def test_finalize_copy_row_repairs_humanizer_reintroduced_page_overclaim(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()

    def fake_humanize(mapping, keys, *, target_prefix: str, brain_only: bool):
        if not brain_only:
            mapping["body"] = "The build works without a grid connection, keeps your data on your device, and every result includes a trustworthy receipt."
        return mapping

    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", fake_humanize)
    monkeypatch.setattr(
        worker,
        "polish_copy_row",
        lambda **kwargs: worker.fallback_page_copy("public_surfaces", worker.PAGE_PROMPTS["public_surfaces"], {}),
    )

    finalized = worker.finalize_copy_row(
        section_type="page",
        name="public_surfaces",
        row={
            "intro": "The public surfaces are the guide, the proof shelf, the current drop, the horizon shelf, and the issue tracker.",
            "body": "Use them to inspect what is real now.",
            "kicker": "Start with what is visible.",
        },
        item=worker.PAGE_PROMPTS["public_surfaces"],
        global_ooda={},
        section_ooda={},
        model=worker.DEFAULT_MODEL,
        humanize_keys=("intro", "body", "kicker"),
        target_prefix="guide:page:public_surfaces",
        prefer_brain_humanizer=False,
    )

    lowered = json.dumps(finalized).lower()
    assert "works without a grid connection" not in lowered
    assert "every result includes" not in lowered
    assert "public surfaces" in finalized["intro"].lower()


def test_finalize_copy_row_prefers_curated_part_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()

    def fake_humanize(mapping, keys, *, target_prefix: str, brain_only: bool):
        if not brain_only:
            mapping["why"] = "It settles arguments today with deterministic smartlink math and every point of karma already accounted for."
        return mapping

    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", fake_humanize)

    finalized = worker.finalize_copy_row(
        section_type="part",
        name="core",
        row={
            "when": "A number looks wrong.",
            "why": "Bad generated copy.",
            "now": "More bad generated copy.",
        },
        item=worker.PARTS["core"],
        global_ooda={},
        section_ooda={},
        model=worker.DEFAULT_MODEL,
        humanize_keys=("when", "why", "now"),
        target_prefix="guide:part:core",
        prefer_brain_humanizer=False,
    )

    lowered = json.dumps(finalized).lower()
    assert "smartlink" not in lowered
    assert "karma" not in lowered
    assert "trust" in finalized["why"].lower() or "responsibility" in finalized["why"].lower()


def test_finalize_copy_row_prefers_curated_horizon_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()

    def fake_humanize(mapping, keys, *, target_prefix: str, brain_only: bool):
        if not brain_only:
            mapping["why_waits"] = "Booster lane, maybe, sure, whatever."
        return mapping

    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", fake_humanize)

    finalized = worker.finalize_copy_row(
        section_type="horizon",
        name="jackpoint",
        row={
            "hook": "Bad generated copy.",
            "problem": "Bad generated copy.",
            "table_scene": "- bad",
            "meanwhile": "- bad",
            "why_great": "Bad generated copy.",
            "why_waits": "Bad generated copy.",
            "pitch_line": "Bad generated copy.",
        },
        item=worker.HORIZONS["jackpoint"],
        global_ooda={},
        section_ooda={},
        model=worker.DEFAULT_MODEL,
        humanize_keys=("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line"),
        target_prefix="guide:horizon:jackpoint",
        prefer_brain_humanizer=False,
    )

    lowered = json.dumps(finalized).lower()
    assert "booster" not in lowered
    assert "packet" in lowered or "receipt" in lowered


def test_section_ooda_defaults_no_longer_force_troll_easter_eggs() -> None:
    worker = _load_worker_module()

    defaults = worker._section_ooda_defaults(
        section_type="page",
        name="start_here",
        item=worker.PAGE_PROMPTS["start_here"],
        global_ooda={},
    )

    visual_devices = " ".join(defaults["orient"]["visual_devices"]).lower()
    assert "troll easter egg" not in visual_devices


def test_section_ooda_defaults_rebrief_index_pages_as_environment_first_maps() -> None:
    worker = _load_worker_module()

    parts_defaults = worker._section_ooda_defaults(
        section_type="page",
        name="parts_index",
        item=worker.PAGE_PROMPTS["parts_index"],
        global_ooda={},
    )
    horizons_defaults = worker._section_ooda_defaults(
        section_type="page",
        name="horizons_index",
        item=worker.PAGE_PROMPTS["horizons_index"],
        global_ooda={},
    )

    assert "differentiated work zones" in parts_defaults["act"]["visual_prompt_seed"]
    assert "no centered signboard" in parts_defaults["act"]["visual_prompt_seed"]
    assert "at least four differentiated future lanes" in horizons_defaults["act"]["visual_prompt_seed"]
    assert "no lone centered silhouette" in horizons_defaults["act"]["visual_prompt_seed"]


def test_editorial_self_audit_rejects_overplayed_ooda_snark() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "Invite readers without sounding like a growth funnel with a knife.",
            fallback="Invite readers without sounding pushy or synthetic.",
            context="ooda:decide:cta_strategy",
        )
        == "Invite readers without sounding pushy or synthetic."
    )


def test_editorial_self_audit_rejects_soft_ooda_filler() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "This is the version worth watching once the future tech we are tracking becomes clearer.",
            fallback="If you care about receipts and recoverable sessions, this is the version worth watching.",
            context="ooda:act:watch_intro",
        )
        == "If you care about receipts and recoverable sessions, this is the version worth watching."
    )


def test_editorial_self_audit_rejects_ooda_product_overclaim_language() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "A deterministic character and rules assistant designed for local-first play that survives device churn.",
            fallback="An idea for less mystical Shadowrun rulings.",
            context="ooda:act:what_it_is",
        )
        == "An idea for less mystical Shadowrun rulings."
    )


def test_editorial_self_audit_rejects_ooda_command_slogan_taglines() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "Stop guessing. Start auditing.",
            fallback="An idea for less mystical Shadowrun rulings.",
            context="ooda:act:landing_tagline",
        )
        == "An idea for less mystical Shadowrun rulings."
    )


def test_editorial_self_audit_rejects_section_ooda_drift_under_page_context() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "Stop guessing. This is the proof of concept that fixes the drift.",
            fallback="Start with the idea, not the illusion of a product.",
            context="page:what_chummer6_is:orient:sales_angle",
        )
        == "Start with the idea, not the illusion of a product."
    )


def test_editorial_self_audit_rejects_section_ooda_fake_status_or_year_range_claims() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "A runner slots a Lua-chip into the rig while Validation Passed alerts confirm 2050-2080 compatibility.",
            fallback="A runner works a dangerous bench while the concept stays obviously unproven.",
            context="horizon:karma-forge:orient:scene_logic",
        )
        == "A runner works a dangerous bench while the concept stays obviously unproven."
    )


def test_editorial_self_audit_rejects_page_level_exact_feature_overclaims() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "This local-first assistant survives device churn, offline sessions, and lets you audit every DV.",
            fallback="Start with the guide and the proof shelf, then judge the rest cautiously.",
            context="page:start_here:body",
        )
        == "Start with the guide and the proof shelf, then judge the rest cautiously."
    )


def test_copy_quality_findings_flags_readme_command_slogans() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "page",
        "readme",
        {
            "intro": "An idea with receipts, maybe.",
            "body": "Stop guessing. Start auditing. If something escaped into public view, maybe it helps.",
            "kicker": "Treat it as spillover.",
        },
        worker.PAGE_PROMPTS["readme"],
    )

    joined = "\n".join(findings).lower()
    assert "command-slogan" in joined or "command" in joined


def test_editorial_self_audit_rejects_mechanics_values_inside_section_ooda_fields() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "Make the reader feel safe that DV 6P and AP -2 are already handled.",
            fallback="Make the reader feel like the proof trail is becoming more trustworthy than table folklore.",
            context="hero:hero:orient:emotional_goal",
        )
        == "Make the reader feel like the proof trail is becoming more trustworthy than table folklore."
    )


def test_normalize_ooda_compacts_list_shaped_decide_fields() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_ooda(
        {
            "decide": {
                "information_order": ["value", "proof", "download"],
                "tone_rules": ["plain", "concrete", "human"],
            },
            "act": {
                "landing_tagline": "Truth with receipts.",
                "landing_intro": "Intro.",
                "what_it_is": "What it is.",
                "watch_intro": "Watch.",
                "horizon_intro": "Future.",
            },
        },
        {"tags": ["offline_play"], "snippets": []},
    )

    assert normalized["decide"]["information_order"] == "value -> proof -> download"
    assert normalized["decide"]["tone_rules"] == "plain; concrete; human"


def test_normalize_horizon_meanwhile_coerces_bullets() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_horizon_meanwhile(
        "Validating the scripted rules engine for heavy table use, securing the registry to keep homebrew rules from leaking into public builds, and building the safety nets that prevent custom math from breaking during core updates."
    )

    lines = [line for line in normalized.splitlines() if line.strip()]
    assert 2 <= len(lines) <= 4
    assert all(line.startswith("- ") for line in lines)


def test_extract_json_accepts_first_valid_object_before_trailing_junk() -> None:
    worker = _load_worker_module()

    loaded = worker.extract_json('{"alpha": 1}\n{"beta": 2}')

    assert loaded == {"alpha": 1}


def test_normalize_horizon_meanwhile_splits_sentences_into_multiple_bullets() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_horizon_meanwhile(
        "Ensuring custom rule-slabs never drift into vibe-based math. Refining the registry so homebrew does not orphan character data. Testing sync logic for live session updates."
    )

    lines = [line for line in normalized.splitlines() if line.strip()]
    assert len(lines) >= 2
    assert all(line.startswith("- ") for line in lines)


def test_normalize_horizon_meanwhile_accepts_json_array_strings() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_horizon_meanwhile(
        '["- Editorial polish stays tied to source proof.","- Editorial polish stays tied to source proof.","- Finished packets still need receipts."]'
    )

    lines = [line for line in normalized.splitlines() if line.strip()]
    assert lines == [
        "- Editorial polish stays tied to source proof",
        "- Finished packets still need receipts",
    ]


def test_normalize_horizon_meanwhile_cleans_nested_literal_list_strings() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_horizon_meanwhile(
        "- ['Later revisions still point back to the source.', 'Updates should not turn the book into salvage work.']"
    )

    assert normalized.splitlines() == [
        "- Later revisions still point back to the source",
        "- Updates should not turn the book into salvage work",
    ]


def test_copy_quality_findings_flags_second_person_in_part_copy() -> None:
    worker = _load_worker_module()

    findings = worker.copy_quality_findings(
        "part",
        "hub-registry",
        {
            "when": "If you find rough artifacts later, you will want labels.",
            "why": "It keeps rumor from replacing a shelf.",
            "now": "Today your lucky leaks would still need sorting before they turn into folklore.",
        },
        {"title": "Hub Registry"},
    )

    assert any("second-person" in finding.lower() or "detached public voice" in finding.lower() for finding in findings)


def test_normalize_horizons_bundle_falls_back_when_media_block_is_incomplete() -> None:
    worker = _load_worker_module()

    copy_rows, media_rows = worker.normalize_horizons_bundle(
        {
            "karma-forge": {
                "copy": {
                    "hook": "Hook.",
                    "problem": "Problem.",
                    "table_scene": "GM: One.\nPlayer: Two.\nRigger: Three.\nFace: Four.\nChummer6: Five.",
                    "meanwhile": "- One\n- Two",
                    "why_great": "Why great.",
                    "why_waits": "Why waits.",
                    "pitch_line": "Pitch.",
                },
                "media": {
                    "title": "Broken media row without badge",
                },
            }
        },
        items={"karma-forge": worker.HORIZONS["karma-forge"]},
    )

    assert copy_rows["karma-forge"]["hook"] == "Hook."
    assert media_rows["karma-forge"]["badge"]
    assert media_rows["karma-forge"]["visual_prompt"]


def test_selected_mapping_keeps_requested_order_subset() -> None:
    worker = _load_worker_module()

    subset = worker.selected_mapping(
        worker.PAGE_PROMPTS,
        ["start_here", "current_status"],
    )

    assert list(subset.keys()) == ["start_here", "current_status"]


def test_selected_mapping_rejects_unknown_ids() -> None:
    worker = _load_worker_module()

    with pytest.raises(ValueError, match="unknown_chummer6_section_ids:not-real"):
        worker.selected_mapping(worker.PAGE_PROMPTS, ["start_here", "not-real"])


def test_generate_overrides_can_regenerate_only_selected_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "normalize_section_ooda", lambda *args, **kwargs: {})
    monkeypatch.setattr(worker, "normalize_section_oodas_bundle", lambda *args, **kwargs: {name: {} for name in kwargs["section_items"].keys()})
    monkeypatch.setattr(worker, "normalize_media_override", lambda kind, media, item: {"badge": "Hero"})
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "run_skill_audit", lambda **kwargs: {"status": "ok"})
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "variation_guardrails_for", lambda *args, **kwargs: {})

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        if "top-level keys observe, orient, decide, act" in prompt:
            return {"observe": {}, "orient": {}, "decide": {}, "act": {}}
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {
                "start_here": {"intro": "Start.", "body": "Body.", "kicker": "Kick."},
                "current_status": {"intro": "Status.", "body": "Today.", "kicker": "Proof."},
            }
        if "section_oodas" in prompt.lower() or "section_ooda" in prompt.lower():
            return {"start_here": {}, "current_status": {}}
        return {"badge": "Hero", "title": "Chummer6"}

    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        model="ea-groundwork",
        page_ids=["start_here", "current_status"],
    )

    assert set(overrides["pages"].keys()) == {"start_here", "current_status"}
    assert overrides["parts"] == {}
    assert overrides["horizons"] == {}


def test_generate_overrides_can_reuse_existing_global_ooda(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    chat_calls: list[str] = []

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "normalize_section_oodas_bundle", lambda *args, **kwargs: {name: {} for name in kwargs["section_items"].keys()})
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "run_skill_audit", lambda **kwargs: {"status": "ok"})
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        chat_calls.append(prompt)
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {
                "start_here": {"intro": "Start.", "body": "Body.", "kicker": "Kick."},
            }
        return {"start_here": {}}

    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        reused_ooda={"observe": {}, "orient": {}, "decide": {}, "act": {}},
        page_ids=["start_here"],
    )

    assert set(overrides["pages"].keys()) == {"start_here"}
    assert all("top-level keys observe, orient, decide, act" not in prompt for prompt in chat_calls)


def test_generate_overrides_can_skip_skill_audits_for_partial_regen(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    audit_calls: list[str] = []

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "normalize_section_oodas_bundle", lambda *args, **kwargs: {name: {} for name in kwargs["section_items"].keys()})
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})

    def fake_run_skill_audit(**kwargs):
        audit_calls.append(kwargs["label"])
        return {"status": "ok"}

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {
                "start_here": {"intro": "Start.", "body": "Body.", "kicker": "Kick."},
            }
        return {"start_here": {}}

    monkeypatch.setattr(worker, "run_skill_audit", fake_run_skill_audit)
    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        reused_ooda={"observe": {}, "orient": {}, "decide": {}, "act": {}},
        page_ids=["start_here"],
        run_skill_audits=False,
    )

    assert audit_calls == []
    assert overrides["meta"]["public_skill_audit"]["status"] == "skipped"
    assert overrides["meta"]["pack_skill_audit"]["reason"] == "partial_regen"


def test_generate_overrides_falls_back_to_default_global_ooda_when_writer_returns_non_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _load_worker_module()

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": ["multi_era_rulesets"], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "normalize_section_oodas_bundle", lambda *args, **kwargs: {name: {} for name in kwargs["section_items"].keys()})
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        if "top-level keys observe, orient, decide, act" in prompt:
            raise ValueError("response did not contain a JSON object")
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {
                "start_here": {"intro": "Start.", "body": "Body.", "kicker": "Kick."},
            }
        return {"start_here": {}}

    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        page_ids=["start_here"],
        run_skill_audits=False,
    )

    assert overrides["ooda"]["act"]["landing_tagline"] == "An idea for less mystical Shadowrun rulings."
    assert overrides["pages"]["start_here"]["intro"] == "If you only look once, use this page to choose the next shelf."


def test_generate_overrides_can_force_single_page_batches_for_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    copy_prompts: list[str] = []

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})

    def fake_build_section_oodas_bundle_prompt(section_type, batch, **kwargs):
        raise AssertionError("focused quality page runs should skip page OODA generation")

    def fake_build_pages_bundle_prompt(*, items, **kwargs):
        prompt = f"PAGES:{','.join(items.keys())}"
        copy_prompts.append(prompt)
        return prompt

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        if prompt.startswith("OODA:"):
            names = [part for part in prompt.split(":", 1)[1].split(",") if part]
            return {name: {} for name in names}
        if prompt.startswith("PAGES:"):
            names = [part for part in prompt.split(":", 1)[1].split(",") if part]
            return {
                name: {"intro": f"{name} intro", "body": f"{name} body", "kicker": f"{name} kicker"}
                for name in names
            }
        return {"observe": {}, "orient": {}, "decide": {}, "act": {}}

    monkeypatch.setattr(worker, "build_section_oodas_bundle_prompt", fake_build_section_oodas_bundle_prompt)
    monkeypatch.setattr(worker, "build_pages_bundle_prompt", fake_build_pages_bundle_prompt)
    monkeypatch.setattr(worker, "normalize_section_oodas_bundle", lambda result, **kwargs: dict(result))
    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        reused_ooda={"observe": {}, "orient": {}, "decide": {}, "act": {}},
        page_ids=["start_here", "current_status"],
        run_skill_audits=False,
        prefer_page_quality=True,
    )

    assert set(overrides["pages"].keys()) == {"start_here", "current_status"}
    assert copy_prompts == ["PAGES:start_here", "PAGES:current_status"]


def test_generate_overrides_repairs_single_page_bundle_without_requested_key(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    prompts: list[str] = []

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(
        worker,
        "fallback_page_copy",
        lambda name, item, global_ooda: {
            "intro": "Start with the idea, not the illusion of a product.",
            "body": "Read the guide, skim the horizon shelf, and treat any artifact you find as accidental spillover.",
            "kicker": "Concept means maybe; any useful artifact is a bonus, not a promise.",
        },
    )

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        prompts.append(prompt)
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {
                "intro": "Direct intro",
                "body": "Direct body",
                "kicker": "Direct kicker",
            }
        return {"observe": {}, "orient": {}, "decide": {}, "act": {}}

    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        reused_ooda={"observe": {}, "orient": {}, "decide": {}, "act": {}},
        page_ids=["start_here"],
        run_skill_audits=False,
        prefer_page_quality=True,
    )

    assert overrides["pages"]["start_here"]["intro"] == "Start with the idea, not the illusion of a product."
    assert any("Each page id must map to an object with keys intro, body, kicker." in prompt for prompt in prompts)


def test_generate_overrides_retries_single_page_prompt_before_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    prompts: list[str] = []

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields_with_mode", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})

    monkeypatch.setattr(worker, "fallback_page_copy", lambda name, item, global_ooda: {})

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        prompts.append(prompt)
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {"wrong_key": "miss"}
        if "guide page `public_surfaces`" in prompt:
            return {
                "intro": "The public surfaces are visible.",
                "body": "You can read the guide, inspect the proof shelf, and treat any stray artifact as provisional evidence instead of a product promise.",
                "kicker": "Start with what is real now.",
            }
        return {"observe": {}, "orient": {}, "decide": {}, "act": {}}

    monkeypatch.setattr(worker, "chat_json", fake_chat_json)

    overrides = worker.generate_overrides(
        include_parts=False,
        include_horizons=False,
        include_hero_media=False,
        model="ea-groundwork",
        reused_ooda={"observe": {}, "orient": {}, "decide": {}, "act": {}},
        page_ids=["public_surfaces"],
        run_skill_audits=False,
        prefer_page_quality=True,
    )

    assert overrides["pages"]["public_surfaces"]["intro"] == "The public surfaces are visible."
    assert any("guide page `public_surfaces`" in prompt for prompt in prompts)
