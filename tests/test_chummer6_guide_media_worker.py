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


def test_sanitize_media_row_disables_easter_eggs_for_non_showcase_targets() -> None:
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
    assert all("troll" not in entry.lower() for entry in row["visual_motifs"])


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
