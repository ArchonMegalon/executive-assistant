from __future__ import annotations

import importlib.util
import json
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


def test_provider_order_defaults_to_non_onemin_media_providers_before_onemin(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_IMAGE_PROVIDER_ORDER", raising=False)
    monkeypatch.setattr(media, "LOCAL_ENV", {})
    monkeypatch.setattr(media, "POLICY_ENV", {})

    assert media.provider_order() == ["media_factory", "browseract_prompting_systems", "browseract_magixai", "magixai", "onemin"]


def test_run_onemin_api_provider_uses_manager_reserved_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "resolve_onemin_image_slots",
        lambda: [
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_22", "key": "key-22"},
            {"env_name": "ONEMIN_AI_API_KEY_FALLBACK_23", "key": "key-23"},
        ],
    )
    monkeypatch.setattr(
        media,
        "_reserve_onemin_image_slot",
        lambda **kwargs: {
            "lease_id": "lease-1",
            "secret_env_name": "ONEMIN_AI_API_KEY_FALLBACK_23",
            "account_id": "ONEMIN_AI_API_KEY_FALLBACK_23",
        },
    )
    released: list[tuple[str, str, int | None, str]] = []
    monkeypatch.setattr(
        media,
        "_release_onemin_image_slot",
        lambda *, lease_id, status, actual_credits_delta=None, error="": released.append(
            (lease_id, status, actual_credits_delta, error)
        ),
    )
    monkeypatch.setattr(media, "onemin_model_candidates", lambda: ["gpt-image-1-mini"])
    monkeypatch.setattr(
        media,
        "onemin_payloads",
        lambda model, **kwargs: [{"type": "IMAGE_GENERATOR", "model": model, "promptObject": {"size": "1024x1024"}}],
    )
    monkeypatch.setattr(media, "_estimate_onemin_image_credits", lambda **kwargs: 900)
    monkeypatch.setattr(
        media,
        "_download_remote_image",
        lambda url, output_path, name="onemin": ((output_path.write_bytes(b"png"), True)[1], "downloaded"),
    )

    class _Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"url": "https://example.test/image.png"}).encode("utf-8")

    seen_api_keys: list[str] = []

    def fake_urlopen(request, timeout=0):
        headers = {str(key).lower(): value for key, value in request.header_items()}
        seen_api_keys.append(str(headers.get("api-key", "")))
        return _Response()

    monkeypatch.setattr(media.urllib.request, "urlopen", fake_urlopen)

    ok, detail = media.run_onemin_api_provider(
        prompt="render scene",
        output_path=tmp_path / "out.png",
        width=1024,
        height=1024,
    )

    assert ok is True
    assert detail == "downloaded"
    assert seen_api_keys == ["key-23"]
    assert released[0] == ("lease-1", "released", 900, "")


def test_reserve_onemin_image_slot_allows_reserve_pool_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    seen: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        media,
        "_ea_local_json_post",
        lambda path, payload: (seen.append((path, dict(payload))), {"lease_id": "lease-1"})[1],
    )

    payload = media._reserve_onemin_image_slot(width=1536, height=1024)

    assert payload == {"lease_id": "lease-1"}
    assert seen == [
        (
            "/v1/providers/onemin/reserve-image",
            {
                "request_id": seen[0][1]["request_id"],
                "estimated_credits": media._estimate_onemin_image_credits(width=1536, height=1024),
                "allow_reserve": True,
            },
        )
    ]


def test_reserve_onemin_image_slot_can_disable_reserve_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    seen: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("CHUMMER6_ONEMIN_ALLOW_RESERVE", "0")
    monkeypatch.setattr(
        media,
        "_ea_local_json_post",
        lambda path, payload: (seen.append((path, dict(payload))), {"lease_id": "lease-2"})[1],
    )

    payload = media._reserve_onemin_image_slot(width=1024, height=1024)

    assert payload == {"lease_id": "lease-2"}
    assert seen == [
        (
            "/v1/providers/onemin/reserve-image",
            {
                "request_id": seen[0][1]["request_id"],
                "estimated_credits": media._estimate_onemin_image_credits(width=1024, height=1024),
                "allow_reserve": False,
            },
        )
    ]


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


def test_sanitize_media_row_strips_explicit_easter_eggs_for_non_sparse_targets() -> None:
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

    assert "troll" not in row["visual_prompt"].lower()
    assert row["scene_contract"]["humor"] == ""
    assert "easter_egg_kind" not in row["scene_contract"]
    assert not any("troll" in entry.lower() for entry in row["visual_motifs"])


def test_sanitize_media_row_strips_sparse_showcase_easter_egg_targets_from_karma_forge() -> None:
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

    assert "easter_egg_kind" not in row["scene_contract"]
    assert row["scene_contract"]["humor"] == ""


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


def test_first_contact_targets_do_not_get_sparse_karma_forge_easter_egg_allowance() -> None:
    media = _load_module()

    assert media.easter_egg_allowed_for_target("assets/horizons/karma-forge.png") is False


def test_build_safe_onemin_prompt_does_not_force_human_presence_for_environment_map_targets() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Wide work-zone map scene.",
        spec={
            "target": "assets/pages/parts-index.png",
            "media_row": {
                "scene_contract": {
                    "subject": "a walkable room map",
                    "environment": "an open warehouse floor with several work zones",
                    "action": "connecting the zones with route lines",
                    "metaphor": "a walkable map of work zones instead of a menu",
                    "composition": "district_map",
                    "mood": "grounded",
                },
            },
        },
    )

    assert "Human presence must be obvious" not in prompt


def test_build_safe_onemin_prompt_does_not_keep_troll_clause_for_karma_forge_even_when_requested() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Rulesmith forge scene.",
        spec={
            "target": "assets/horizons/karma-forge.png",
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

    assert "troll motif" not in prompt.lower()


def test_build_safe_onemin_prompt_does_not_force_troll_clause_for_non_sparse_targets_even_with_explicit_fields() -> None:
    media = _load_module()

    prompt = media.build_safe_onemin_prompt(
        prompt="Prep desk scene with receipts.",
        spec={
            "target": "assets/parts/ui.png",
            "media_row": {
                "visual_prompt": "Prep desk scene with receipts.",
                "scene_contract": {
                    "subject": "a player building a runner",
                    "environment": "a prep desk",
                    "action": "checking gear",
                    "composition": "desk_still_life",
                    "mood": "focused",
                    "easter_egg_kind": "troll monitor sticker",
                    "easter_egg_placement": "upper-left bezel",
                    "easter_egg_detail": "classic Chummer troll sticker",
                    "easter_egg_visibility": "obvious",
                },
            },
        },
    )

    assert "troll motif" not in prompt.lower()


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


def test_build_safe_pollinations_prompt_adds_hero_and_map_specific_hard_blocks() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_pollinations_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a prep wall threshold",
                    "action": "checking whether the build trail deserves trust",
                    "composition": "street_front",
                    "mood": "tense",
                },
            },
        },
    )
    horizons_prompt = media.build_safe_pollinations_prompt(
        prompt="Wide horizon map.",
        spec={
            "target": "assets/pages/horizons-index.png",
            "media_row": {
                "scene_contract": {
                    "subject": "future lanes",
                    "environment": "a rain-slick interchange",
                    "action": "splitting into possible routes",
                    "composition": "horizon_boulevard",
                    "mood": "grounded",
                },
            },
        },
    )

    assert "no crate desk" in hero_prompt.lower()
    assert "no central signboard" in horizons_prompt.lower()


def test_build_safe_onemin_prompt_adds_target_specific_layout_blocks() -> None:
    media = _load_module()

    hero_prompt = media.build_safe_onemin_prompt(
        prompt="Hero prep scene.",
        spec={
            "target": "assets/hero/chummer6-hero.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a prep wall threshold",
                    "action": "checking whether the build trail deserves trust",
                    "composition": "street_front",
                    "mood": "tense",
                },
            },
        },
    )
    what_prompt = media.build_safe_onemin_prompt(
        prompt="What-is scene.",
        spec={
            "target": "assets/pages/what-chummer6-is.png",
            "media_row": {
                "scene_contract": {
                    "subject": "one runner",
                    "environment": "a review bay",
                    "action": "cross-checking receipts on a standing trace surface",
                    "composition": "review_bay",
                    "mood": "focused",
                },
            },
        },
    )

    assert "no seated alley brood" in hero_prompt.lower()
    assert "no face-only portrait" in what_prompt.lower()


def test_page_media_row_does_not_literalize_page_id_as_metaphor() -> None:
    media = _load_module()

    loaded = media.load_media_overrides()
    pages = loaded["pages"]
    section_ooda = loaded["section_ooda"]["pages"]

    def page_media_row(page_id: str, *, role: str, composition_hint: str):
        page_row = pages.get(page_id)
        ooda_row = section_ooda.get(page_id)
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
        orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
        decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
        interests = observe.get("likely_interest") if isinstance(observe.get("likely_interest"), list) else []
        concrete = observe.get("concrete_signals") if isinstance(observe.get("concrete_signals"), list) else []
        return {
            "title": role,
            "subtitle": str(page_row.get("intro", "")).strip(),
            "kicker": str(page_row.get("kicker", "")).strip(),
            "note": str(page_row.get("body", "")).strip(),
            "overlay_hint": str(decide.get("overlay_priority", "")).strip() or str(orient.get("visual_devices", "")).strip(),
            "visual_prompt": str(act.get("visual_prompt_seed", "")).strip(),
            "visual_motifs": [str(entry).strip() for entry in interests if str(entry).strip()],
            "overlay_callouts": [str(entry).strip() for entry in concrete if str(entry).strip()],
            "scene_contract": {
                "subject": str(orient.get("focal_subject") or "a cyberpunk protagonist").strip(),
                "environment": str(orient.get("scene_logic") or str(page_row.get("body", "")).strip()).strip(),
                "action": str(act.get("paragraph_seed", "")).strip() or str(act.get("one_liner", "")).strip(),
                "metaphor": "",
                "props": [],
                "overlays": [],
                "composition": composition_hint,
                "palette": str(orient.get("visual_devices", "")).strip(),
                "mood": str(orient.get("emotional_goal", "")).strip(),
                "humor": "",
            },
        }

    row = page_media_row("current_status", role="current-status banner", composition_hint="street_front")
    assert row["scene_contract"]["metaphor"] == ""


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
    assert "dragon-warning pictograms" in lowered or "crossed-out draconic pictograms" in lowered


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


def test_sanitize_prompt_for_provider_onemin_keeps_shadowrun_lore_and_gear_terms() -> None:
    media = _load_module()

    prompt = media.sanitize_prompt_for_provider(
        "Shadowrun runner with a weapon checks smartlink threat posture in a rainy alley.",
        provider="onemin",
    )

    lowered = prompt.lower()
    assert "shadowrun" in lowered
    assert "runner" in lowered
    assert "weapon" in lowered
    assert "no weapons" not in lowered


def test_build_render_accounting_summarizes_provider_attempts() -> None:
    media = _load_module()

    report = media.build_render_accounting(
        [
            {
                "target": "assets/hero/chummer6-hero.png",
                "provider": "onemin",
                "status": "onemin:http_200",
                "attempts": ["magixai:not_configured", "onemin:http_200", "normalize_banner_size:applied:960x540"],
            },
            {
                "target": "assets/horizons/jackpoint.png",
                "provider": "media_factory",
                "status": "media_factory:rendered",
                "attempts": ["media_factory:rendered", "normalize_banner_size:applied:960x540"],
            },
        ]
    )

    assert report["asset_count"] == 2
    assert report["providers"]["onemin"]["successes"] == 1
    assert report["providers"]["magixai"]["estimated_billable_attempts"] == 0
    assert report["providers"]["media_factory"]["attempts"] == 1


def test_first_contact_target_variant_count_and_overlay_gate() -> None:
    media = _load_module()

    assert media.first_contact_target("assets/hero/chummer6-hero.png") is True
    assert media.first_contact_variant_count(target="assets/hero/chummer6-hero.png") == 5
    assert media.first_contact_variant_count(target="assets/parts/ui.png") == 1


def test_first_contact_target_variant_count_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setenv("CHUMMER6_FIRST_CONTACT_VARIANTS", "8")

    assert media.first_contact_variant_count(target="assets/pages/horizons-index.png") == 8


def test_target_visual_contract_loads_density_profile_and_blocks_flagship_humor() -> None:
    media = _load_module()

    hero_contract = media.target_visual_contract("assets/hero/chummer6-hero.png")
    contract = media.target_visual_contract("assets/horizons/karma-forge.png")

    assert hero_contract["person_count_target"] == "duo_or_team"
    assert contract["density_target"] == "high"
    assert contract["overlay_density"] == "high"
    assert contract["person_count_target"] == "duo_preferred"
    assert "approval or provenance logic" in contract["must_show_semantic_anchors"]
    assert media.humor_allowed_for_target(target="assets/horizons/karma-forge.png", contract={}) is False


def test_visual_contract_prompt_parts_add_cast_density_clauses() -> None:
    media = _load_module()

    hero_parts = media.visual_contract_prompt_parts(target="assets/hero/chummer6-hero.png")
    forge_parts = media.visual_contract_prompt_parts(target="assets/horizons/karma-forge.png")

    assert any("two to four people" in part.lower() for part in hero_parts)
    assert any("visible reviewer" in part.lower() or "second pair of hands" in part.lower() for part in forge_parts)


def test_infer_cast_signature_recognizes_duo_operator_relationships() -> None:
    media = _load_module()

    assert media.infer_cast_signature({"subject": "a streetdoc and a runner locked in an upgrade trust check"}) == "duo"
    assert media.infer_cast_signature({"subject": "a crew waiting behind the rail"}) == "group"


def test_row_has_stale_override_drift_rejects_quiet_solo_hero_prompt() -> None:
    media = _load_module()

    stale = media.row_has_stale_override_drift(
        target="assets/hero/chummer6-hero.png",
        row={
            "visual_prompt": "One man in profile beside a vague board in a quiet gear bay.",
            "scene_contract": {
                "subject": "one standing runner alone at a prep wall",
                "composition": "clinic_intake",
            },
        },
    )

    assert stale is True


def test_visual_audit_score_flags_dead_negative_space(tmp_path: Path) -> None:
    media = _load_module()
    pytest.importorskip("PIL")
    from PIL import Image

    image_path = tmp_path / "empty.png"
    Image.new("RGB", (960, 540), (5, 5, 5)).save(image_path)

    score, notes = media.visual_audit_score(
        image_path=image_path,
        target="assets/pages/horizons-index.png",
    )

    assert score < 0
    assert "visual_audit:dead_negative_space" in notes


def test_refine_prompt_with_ooda_uses_external_refiner_when_available_without_requiring_it(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.delenv("CHUMMER6_PROMPT_REFINEMENT_REQUIRED", raising=False)
    monkeypatch.setattr(media, "env_value", lambda name: "wf-123" if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID" else "")
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('refined prompt from external lane')"])

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "refined prompt from external lane"


def test_refine_prompt_with_ooda_can_disable_external_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    media = _load_module()
    monkeypatch.setattr(
        media,
        "env_value",
        lambda name: "1"
        if name == "CHUMMER6_DISABLE_PROMPT_REFINEMENT"
        else "wf-123"
        if name == "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID"
        else "",
    )
    monkeypatch.setattr(media, "shlex_command", lambda name: ["python3", "-c", "print('should not run')"])

    refined = media.refine_prompt_with_ooda(prompt="base prompt", target="assets/pages/start-here.png")

    assert refined == "base prompt"


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
