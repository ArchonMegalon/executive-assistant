from __future__ import annotations

from pathlib import Path

import yaml


def test_companion_trigger_registry_is_mirrored_and_governed() -> None:
    path = Path(".codex-design/product/COMPANION_TRIGGER_REGISTRY.yaml")
    assert path.is_file()

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["product"] == "chummer"
    assert payload["surface"] == "companion"
    assert payload["global_rules"]["trigger_truth_owner"] == "chummer_owned_state"
    assert payload["global_rules"]["ea_position"] == "downstream_compile_only"
    assert {
        "ea_unavailable_must_not_block_runtime",
        "media_unavailable_must_not_block_runtime",
        "llm_unavailable_must_not_block_runtime",
    } <= set(payload["global_rules"]["runtime_blockers"])

    trigger_classes = payload["trigger_classes"]
    assert len(trigger_classes) >= 17
    ids = [str(item["id"]) for item in trigger_classes]
    assert len(ids) == len(set(ids))
    assert {
        "build_archetype_drift",
        "support_fix_confirmation",
        "restore_conflict_warning",
        "player_safe_recap_offer",
    } <= set(ids)
    for item in trigger_classes:
        assert item["source_facts"], item["id"]
        assert item["allowed_surfaces"], item["id"]
        assert item["render_modes"], item["id"]
        assert "cooldown_scope" in item["suppression"], item["id"]
        assert "max_impressions_per_day" in item["suppression"], item["id"]


def test_companion_trigger_registry_is_named_in_product_front_door() -> None:
    readme = Path(".codex-design/product/README.md").read_text(encoding="utf-8")
    operations = Path(".codex-design/product/COMPANION_LINE_PACK_AND_TRIGGER_OPERATIONS.md").read_text(encoding="utf-8")

    assert "COMPANION_TRIGGER_REGISTRY.yaml" in readme
    assert "COMPANION_TRIGGER_REGISTRY.yaml" in operations
