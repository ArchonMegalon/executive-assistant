from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_ltd_inventory_file_present_and_populated() -> None:
    inventory = ROOT / "LTD_INVENTORY.md"
    assert inventory.exists(), "missing LTD_INVENTORY.md"
    text = inventory.read_text(encoding="utf-8")
    assert "Capability-Backed LTD Inventory" in text
    assert "Runtime Dependencies (Not LTD Tiered)" in text
    for marker in (
        "BrowserAct",
        "MetaSurvey",
        "AvoMap",
        "ApiX-Drive",
        "OneAir",
        "Prompting.Systems",
        "Undetectable",
        "1minAI",
        "OpenClaw container runtime",
        "LiteLLM route/provider gateway",
    ):
        assert marker in text, f"missing marker in LTD inventory: {marker}"
    _pass("v1.19.4 ltd inventory file presence")


def test_ltd_inventory_references_registered_capability_keys() -> None:
    from app.skills.capability_registry import CAPABILITY_REGISTRY

    text = (ROOT / "LTD_INVENTORY.md").read_text(encoding="utf-8")
    expected = [
        "browseract",
        "metasurvey",
        "avomap",
        "apix_drive",
        "oneair",
        "prompting_systems",
        "undetectable",
        "one_min_ai",
        "ai_magicx",
        "involve_me",
        "paperguide",
        "vizologi",
        "peekshot",
        "approvethis",
    ]
    for key in expected:
        assert key in CAPABILITY_REGISTRY, f"capability missing from registry: {key}"
        assert f"`{key}`" in text, f"capability key missing from LTD inventory doc: {key}"
    _pass("v1.19.4 ltd inventory capability-key mapping")


if __name__ == "__main__":
    test_ltd_inventory_file_present_and_populated()
    test_ltd_inventory_references_registered_capability_keys()
