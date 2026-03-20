from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_guide_media_worker.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_guide_media_worker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_order_filters_fallback_render_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv(
        "CHUMMER6_IMAGE_PROVIDER_ORDER",
        "magixai,media_factory,ooda_compositor,local_raster,onemin,scene_contract_renderer",
    )

    assert media.provider_order() == ["magixai", "media_factory", "onemin"]


def test_provider_order_preserves_explicit_runtime_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_IMAGE_PROVIDER_ORDER", "onemin,magixai,browseract_prompting_systems")

    assert media.provider_order() == ["onemin", "magixai", "browseract_prompting_systems"]


def test_provider_order_defaults_to_magix_then_onemin_before_browseract(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_IMAGE_PROVIDER_ORDER", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    assert media.provider_order() == ["magixai", "media_factory", "onemin", "browseract_magixai", "browseract_prompting_systems"]


def test_resolve_onemin_image_keys_keeps_fallback_rotation_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS", raising=False)
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fallback-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "fallback-2")
    monkeypatch.setattr(media.subprocess, "check_output", lambda *args, **kwargs: "")

    assert media.resolve_onemin_image_keys() == ["primary", "fallback-1", "fallback-2"]


def test_render_with_ooda_rejects_forbidden_fallback_providers(tmp_path: Path) -> None:
    media = _load_module()

    with pytest.raises(RuntimeError, match="scene_contract_renderer:forbidden_fallback"):
        media.render_with_ooda(
            prompt="receipt-first skyline",
            output_path=tmp_path / "out.png",
            width=960,
            height=540,
            spec={"providers": ["scene_contract_renderer"]},
        )


def test_render_with_ooda_delegates_media_factory_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()

    def fake_run_command_provider(name: str, template: list[str], **kwargs):
        assert name == "media_factory"
        assert template
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"png")
        return True, "media_factory:rendered"

    monkeypatch.setattr(media, "run_command_provider", fake_run_command_provider)

    result = media.render_with_ooda(
        prompt="bounded runsite scene",
        output_path=tmp_path / "out.png",
        width=1600,
        height=900,
        spec={"providers": ["media_factory"]},
    )

    assert result["provider"] == "media_factory"
    assert result["status"] == "media_factory:rendered"


def test_canonical_horizon_visual_contract_uses_canon_not_bespoke_fallback_map() -> None:
    media = _load_module()

    row = media.canonical_horizon_visual_contract("runsite", media.CANON_HORIZONS["runsite"])

    assert media.HORIZON_MEDIA_FALLBACKS == {}
    assert row["title"] == "RUNSITE"
    assert row["visual_prompt"]
    assert row["scene_contract"]["composition"] == "district_map"
    assert row["overlay_callouts"]


def test_forbid_legacy_svg_fallback_rejects_svg_targets(tmp_path: Path) -> None:
    media = _load_module()

    with pytest.raises(RuntimeError, match="legacy_svg_fallback_forbidden"):
        media.forbid_legacy_svg_fallback(tmp_path / "old-fallback.svg")


def test_is_credit_exhaustion_message_matches_common_provider_failures() -> None:
    media = _load_module()

    assert media.is_credit_exhaustion_message("INSUFFICIENT_CREDITS")
    assert media.is_credit_exhaustion_message("your balance is too low to continue")
    assert not media.is_credit_exhaustion_message("http_404: not found")


def test_sanitize_scene_humor_drops_readable_meta_jokes_but_keeps_adult_in_world_lines() -> None:
    media = _load_module()

    assert (
        media.sanitize_scene_humor("A worn sticker on the workbench reads: 'IF THE MATH SUCKS, THE CODE FUCKS'.")
        == ""
    )
    assert media.sanitize_scene_humor("A mean bastard of a night, but the rig still holds.") == (
        "A mean bastard of a night, but the rig still holds."
    )


def test_sanitize_media_row_keeps_explicit_easter_eggs_for_non_showcase_targets() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/parts/ui.png",
        row={
            "visual_prompt": "Prep desk scene, a troll monitor sticker is clearly visible on the bezel, grounded and tactile.",
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
    )

    assert "troll" in row["visual_prompt"].lower()
    assert row["scene_contract"]["humor"] == ""
    assert row["scene_contract"]["easter_egg_kind"] == "troll monitor sticker"
    assert any("troll" in entry.lower() for entry in row["visual_motifs"])


def test_sanitize_media_row_keeps_sparse_showcase_easter_egg_targets() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/horizons/karma-forge.png",
        row={
            "visual_prompt": "Rulesmith bench scene with a tiny troll forge patch on the apron.",
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
    )

    assert "easter_egg_kind" in row["scene_contract"]
    assert row["scene_contract"]["humor"] == "The bastard thing finally behaves."


def test_build_safe_onemin_prompt_does_not_force_troll_clause_without_explicit_request() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Grounded archive scene with dossier props.",
        spec={
            "media_row": {
                "visual_prompt": "Grounded archive scene with dossier props.",
                "scene_contract": {
                    "subject": "an archivist",
                    "environment": "a dim archive room",
                    "action": "sorting receipts",
                    "metaphor": "provenance before hype",
                    "composition": "archive_room",
                    "mood": "focused",
                    "props": ["binders", "chips"],
                    "overlays": ["receipt traces"],
                },
            }
        },
    )

    assert "troll motif" not in prompt.lower()


def test_build_safe_onemin_prompt_keeps_troll_clause_when_scene_explicitly_requests_it() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Rulesmith forge scene.",
        spec={
            "media_row": {
                "visual_prompt": "Rulesmith forge scene.",
                "scene_contract": {
                    "subject": "a rulesmith",
                    "environment": "a forge bench",
                    "action": "hammering volatile rules into shape",
                    "composition": "workshop_bench",
                    "mood": "intense",
                    "easter_egg_kind": "troll forge patch",
                    "easter_egg_placement": "on the apron strap",
                    "easter_egg_detail": "classic Chummer troll embroidered as a forge patch",
                    "easter_egg_visibility": "small but visible",
                },
            }
        },
    )

    assert "troll motif" in prompt.lower()


def test_build_safe_pollinations_prompt_does_not_force_troll_clause_without_explicit_request() -> None:
    media = _load_module()

    prompt = media.build_safe_pollinations_prompt(
        prompt="Grounded archive scene with dossier props.",
        spec={
            "media_row": {
                "visual_prompt": "Grounded archive scene with dossier props.",
                "scene_contract": {
                    "subject": "an archivist",
                    "environment": "a dim archive room",
                    "action": "sorting receipts",
                    "metaphor": "provenance before hype",
                    "composition": "archive_room",
                    "mood": "focused",
                },
            }
        },
    )

    assert "troll motif" not in prompt.lower()


def test_contains_machine_overlay_language_flags_overliteralized_diagnostic_tokens() -> None:
    media = _load_module()

    assert media.contains_machine_overlay_language("Display Link Verified telemetry between screens.")
    assert media.contains_machine_overlay_language("Weapon diagnostics explain the damage modifiers.")
    assert media.contains_machine_overlay_language("Ares Predator smartlink electronics and barrel rifling.")


def test_scene_rows_for_style_epoch_can_refuse_stale_fallback_rows() -> None:
    media = _load_module()
    ledger = {
        "assets": [
            {
                "target": "assets/hero/chummer6-hero.png",
                "composition": "over_shoulder_receipt",
                "style_epoch": {"epoch": 1, "run_id": "style-001"},
            }
        ]
    }

    rows = media.scene_rows_for_style_epoch(
        ledger,
        style_epoch={"epoch": 2, "run_id": "style-002"},
        allow_fallback=False,
    )

    assert rows == []


def test_build_safe_onemin_prompt_can_carry_smartlink_and_lore_background_cues() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Rainy transit threshold scene.",
        spec={
            "media_row": {
                "visual_prompt": "Rainy transit threshold scene with one reconnecting operator.",
                "scene_contract": {
                    "subject": "one reconnecting operator",
                    "environment": "a rainy transit checkpoint",
                    "action": "checking whether the ambush lane is still live",
                    "metaphor": "trust rebuilt under pressure",
                    "composition": "transit_checkpoint",
                    "mood": "tense and focused",
                },
            }
        },
    )

    lowered = prompt.lower()
    assert "smartlink" in lowered or "threat posture" in lowered or "line-of-fire" in lowered
    assert "dragon-warning mural" in lowered or "crossed-out draconic pictograms" in lowered


def test_build_safe_onemin_prompt_can_carry_lore_scars_inside_dossier_or_workshop_scenes() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Safehouse publishing desk scene.",
        spec={
            "media_row": {
                "visual_prompt": "A campaign writer marks up a district guide on a rugged slate at a cluttered desk.",
                "scene_contract": {
                    "subject": "a campaign writer marking up a district guide on a rugged slate",
                    "environment": "a safehouse desk covered in physical maps and coffee rings",
                    "action": "turning loose notes into a dossier that still points back to source",
                    "metaphor": "leaked field manual",
                    "composition": "dossier_desk",
                    "mood": "focused and suspicious",
                },
            }
        },
    )

    lowered = prompt.lower()
    assert "anti-dragon sigil" in lowered or "runner superstition sticker" in lowered or "talismonger ward mark" in lowered


def test_refine_prompt_with_ooda_uses_external_refiner_when_available_without_requiring_it(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_PROMPT_REFINEMENT_REQUIRED", raising=False)
    monkeypatch.setattr(media, "env_value", lambda name: "wf-123" if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID" else "")
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('refined prompt from external lane')"])

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "refined prompt from external lane"


def test_refine_prompt_with_ooda_falls_back_to_local_prompt_on_timeout_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_PROMPT_REFINEMENT_REQUIRED", raising=False)
    monkeypatch.setattr(media, "env_value", lambda name: "wf-123" if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID" else "")
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('never reached')"])

    def _timeout(*args, **kwargs):
        raise media.subprocess.TimeoutExpired(cmd="refiner", timeout=media.prompt_refinement_timeout_seconds())

    monkeypatch.setattr(media.subprocess, "run", _timeout)

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "base prompt"


def test_sanitize_media_row_strips_machine_overlay_labels_from_render_prompts() -> None:
    media = _load_module()

    row = media.sanitize_media_row(
        target="assets/horizons/jackpoint.png",
        row={
            "visual_prompt": (
                "Dossier desk scene with receipt threads and hard evidence. "
                "Hovering digital 'VERIFIED' stamps glow in the air with metadata strings."
            ),
            "overlay_hint": "HUD style: Data-dossier classification stamps and rotating provenance hashes in the corners.",
            "visual_motifs": ["dossier desk", "receipt threads", "SIG_MATCH: 99.8%"],
            "overlay_callouts": ["receipt markers", "PROVENANCE VERIFIED", "HW_ID: 0x882_DECK"],
            "scene_contract": {
                "subject": "a fixer sorting a dossier",
                "environment": "a dim archive desk",
                "action": "sorting evidence",
                "metaphor": "dossier evidence wall",
                "props": ["dossiers", "chips"],
                "overlays": ["receipt markers", "AUDIT_PASS: 100%"],
                "composition": "desk_still_life",
                "palette": "cyan",
                "mood": "focused",
                "humor": "",
            },
        },
    )

    assert row["visual_motifs"] == ["dossier desk", "receipt threads"]
    assert row["overlay_callouts"] == ["receipt markers"]
    assert row["scene_contract"]["overlays"] == ["receipt markers"]
    assert "verified" not in row["visual_prompt"].lower()
    assert "metadata" not in row["visual_prompt"].lower()
    assert row["overlay_hint"] == ""
