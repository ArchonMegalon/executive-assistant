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
