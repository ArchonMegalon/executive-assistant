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
        "Chummer6 is pre-alpha. The proof shelf is real, the limits are real, and the next step should be honest "
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
            "humanized": "Chummer6 is still pre-alpha. What matters is that the proof shelf is real, the limits are visible, and the next step is stated plainly instead of pretending the product is finished."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "proof shelf" in result.lower()
    assert "pre-alpha" in result.lower()
    assert worker.HUMANIZER_EXTERNAL_LOCKED_OUT is True


def test_humanize_text_rejects_aiish_external_output_before_brain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    source = (
        "Chummer6 is pre-alpha, rough, and inspectable. The point is to show real receipts now, not sell a seamless journey."
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
            "humanized": "Chummer6 is still rough and pre-alpha. The useful part is that the receipts are real now, and the copy does not pretend this thing is polished."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "seamless toolkit" not in result.lower()
    assert "receipts" in result.lower()


def test_humanize_text_uses_brain_when_required_without_external_humanizer(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    source = (
        "The current build is pre-alpha, but a player can still inspect what the math did and where the numbers came from."
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
            "humanized": "The current build is still pre-alpha, but a player can already inspect the math and see where the numbers came from."
        },
    )

    result = worker.humanize_text(source, target="guide:start_here:intro")

    assert "pre-alpha" in result.lower()
    assert "inspect the math" in result.lower()


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
    assert normalized["orient"]["why_care"] == ["faster rulings"]
    assert normalized["observe"]["risks"]
    assert normalized["orient"]["signals_to_highlight"] == ["future rules coverage should be shown honestly"]
    assert normalized["orient"]["humor_line"] == "Keep the wit dry, adult, and secondary to the actual point."
    assert normalized["act"]["landing_tagline"] == "Shadowrun math, shown with receipts."
    assert normalized["act"]["what_it_is"] == (
        "Chummer6 is a local-first Shadowrun rules workbench that is trying to show its work instead of asking you to trust mystery math."
    )


def test_editorial_self_audit_rejects_ooda_math_certainty_and_scope_leaks() -> None:
    worker = _load_worker_module()

    assert (
        worker.editorial_self_audit_text(
            "A scriptable multi-era engine with deterministic logic.",
            fallback="A rough local-first workbench that is trying to show its work.",
            context="ooda:act:what_it_is",
        )
        == "A rough local-first workbench that is trying to show its work."
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
            fallback="Chummer6 is a local-first Shadowrun rules workbench that is trying to show its work instead of asking you to trust mystery math.",
            context="ooda:act:what_it_is",
        )
        == "Chummer6 is a local-first Shadowrun rules workbench that is trying to show its work instead of asking you to trust mystery math."
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


def test_normalize_media_override_keeps_scene_fit_easter_eggs_but_strips_meta_humor() -> None:
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
    assert normalized["scene_contract"]["easter_egg_kind"] == "troll monitor sticker"
    assert "troll" in normalized["visual_prompt"].lower()
    assert any("troll" in entry.lower() for entry in normalized["visual_motifs"])


def test_normalize_media_override_keeps_sparse_showcase_easter_egg_target() -> None:
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

    assert "easter_egg_kind" in normalized["scene_contract"]


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
    assert "help:booster_lane" not in joined


def test_page_supporting_context_does_not_globalize_booster_copy() -> None:
    worker = _load_worker_module()

    for page_id in ("start_here", "public_surfaces", "where_to_go_deeper"):
        joined = "\n".join(worker.page_supporting_context(page_id)).lower()
        assert "booster" not in joined


def test_page_prompts_include_faq_and_help_ids() -> None:
    worker = _load_worker_module()

    assert "faq" in worker.PAGE_PROMPTS
    assert "how_can_i_help" in worker.PAGE_PROMPTS
    assert worker.PAGE_PROMPTS["faq"]["source"]
    assert worker.PAGE_PROMPTS["how_can_i_help"]["source"]


def test_copy_quality_findings_requires_pre_alpha_posture_on_first_contact_pages() -> None:
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
    assert "pre-alpha" in joined


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


def test_fallback_page_copy_is_reader_safe_for_what_chummer6_is() -> None:
    worker = _load_worker_module()

    row = worker.fallback_page_copy("what_chummer6_is", worker.PAGE_PROMPTS["what_chummer6_is"], {})

    assert row["intro"]
    assert "local-first" in row["intro"].lower() or "local-first" in row["body"].lower()
    worker.assert_public_reader_safe(row, context="page:what_chummer6_is:fallback")


def test_fallback_page_copy_covers_faq_and_help_pages() -> None:
    worker = _load_worker_module()

    faq_row = worker.fallback_page_copy("faq", worker.PAGE_PROMPTS["faq"], {})
    help_row = worker.fallback_page_copy("how_can_i_help", worker.PAGE_PROMPTS["how_can_i_help"], {})

    assert "can you use it now" in faq_row["intro"].lower()
    assert "download" in help_row["kicker"].lower()
    assert "booster" not in json.dumps({"faq": faq_row, "help": help_row}).lower()
    worker.assert_public_reader_safe(faq_row, context="page:faq:fallback")
    worker.assert_public_reader_safe(help_row, context="page:how_can_i_help:fallback")


def test_media_easter_egg_allowed_is_optional_not_whitelist_only() -> None:
    worker = _load_worker_module()

    assert worker.media_easter_egg_allowed(kind="part", item={"slug": "ui"}, contract={}) is True
    assert worker.media_easter_egg_allowed(
        kind="part",
        item={"slug": "ui"},
        contract={"easter_egg_policy": "deny"},
    ) is False


def test_part_supporting_context_does_not_inject_booster_copy_into_hub() -> None:
    worker = _load_worker_module()

    joined = "\n".join(worker.part_supporting_context("hub")).lower()
    assert "booster" not in joined
    assert "participate" not in joined


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
    assert "Booster API scope note:" in prompt
    assert "Booster outcome note:" in prompt


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
    assert "api-side consumption for development" in joined
    assert "does not promise a useful or shippable result" in joined


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


def test_normalize_horizon_meanwhile_splits_sentences_into_multiple_bullets() -> None:
    worker = _load_worker_module()

    normalized = worker.normalize_horizon_meanwhile(
        "Ensuring custom rule-slabs never drift into vibe-based math. Refining the registry so homebrew does not orphan character data. Testing sync logic for live session updates."
    )

    lines = [line for line in normalized.splitlines() if line.strip()]
    assert len(lines) >= 2
    assert all(line.startswith("- ") for line in lines)


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

    monkeypatch.setattr(worker, "collect_interest_signals", lambda: {"tags": [], "snippets": []})
    monkeypatch.setattr(worker, "resolve_style_epoch", lambda increment=True: {"epoch": 1})
    monkeypatch.setattr(worker, "scene_ledger_summary", lambda rows: [])
    monkeypatch.setattr(worker, "recent_scene_rows", lambda: [])
    monkeypatch.setattr(worker, "normalize_ooda", lambda result, signals: {"act": {}, "decide": {}, "orient": {}, "observe": {}})
    monkeypatch.setattr(worker, "humanize_mapping_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "polish_copy_row", lambda **kwargs: kwargs["row"])
    monkeypatch.setattr(worker, "scene_plan_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "editorial_pack_audit", lambda overrides: {"status": "ok"})
    monkeypatch.setattr(worker, "fallback_page_copy", lambda name, item, global_ooda: {"intro": "Fallback intro", "body": "Fallback body", "kicker": "Fallback kicker"})

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
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

    assert overrides["pages"]["start_here"]["intro"] == "Direct intro"
    assert overrides["pages"]["start_here"]["body"] == "Direct body"


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

    def should_not_fallback(name, item, global_ooda):
        raise AssertionError("fallback should not be used when single-page retry succeeds")

    monkeypatch.setattr(worker, "fallback_page_copy", should_not_fallback)

    def fake_chat_json(prompt, *, model=worker.DEFAULT_MODEL, skill_key=worker.PUBLIC_WRITER_SKILL_KEY):
        prompts.append(prompt)
        if "Each page id must map to an object with keys intro, body, kicker." in prompt:
            return {"wrong_key": "miss"}
        if "guide page `public_surfaces`" in prompt:
            return {
                "intro": "The public surfaces are visible.",
                "body": "You can read the guide, inspect the proof shelf, and grab the current drop.",
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
