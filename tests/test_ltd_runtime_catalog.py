from __future__ import annotations

from pathlib import Path

from app.services.browseract_ui_service_catalog import browseract_ui_service_by_alias
from app.services.ltd_runtime_catalog import LtdRuntimeCatalogService, _inventory_markdown_path
from app.services.provider_registry import ProviderRegistryService


def _sample_ltd_markdown() -> str:
    return """
# LTDs

Updated: 2026-05-02

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `12 licenses` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots | Primary API-key lane is already wired. |
| `Emailit` | `Tier 5` | `1 key` | `Owned` |  | `Tier 1` | Local `.env` key plus sender-domain wiring | Transactional delivery already runs through EA. |
| `hedy.ai` | `LTD account` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Credentials captured locally; no active runtime lane yet. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for operator docs and cited answers. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | BrowserAct workspace reader exists even though the direct provider lane is not executable. |
""".strip()


def _catalog(tmp_path: Path) -> LtdRuntimeCatalogService:
    markdown_path = tmp_path / "LTDs.md"
    markdown_path.write_text(_sample_ltd_markdown(), encoding="utf-8")
    return LtdRuntimeCatalogService(
        provider_registry=ProviderRegistryService(),
        markdown_path=markdown_path,
    )


def test_inventory_markdown_path_resolves_repo_and_container_layouts(tmp_path: Path) -> None:
    repo_module = tmp_path / "repo" / "ea" / "app" / "services" / "ltd_runtime_catalog.py"
    repo_module.parent.mkdir(parents=True, exist_ok=True)
    repo_root_inventory = repo_module.parents[3] / "LTDs.md"
    repo_root_inventory.write_text(_sample_ltd_markdown(), encoding="utf-8")
    assert _inventory_markdown_path(module_path=repo_module) == repo_root_inventory

    container_module = tmp_path / "app" / "app" / "services" / "ltd_runtime_catalog.py"
    container_module.parent.mkdir(parents=True, exist_ok=True)
    container_inventory = container_module.parents[2] / "LTDs.md"
    container_inventory.write_text(_sample_ltd_markdown(), encoding="utf-8")
    assert _inventory_markdown_path(module_path=container_module) == container_inventory


def test_browseract_ui_service_aliases_resolve_inventory_service_names() -> None:
    documentation = browseract_ui_service_by_alias("Documentation.AI")
    assert documentation is not None
    assert documentation.service_key == "documentation_ai_workspace_reader"

    apixdrive = browseract_ui_service_by_alias("ApiX-Drive")
    assert apixdrive is not None
    assert apixdrive.service_key == "apixdrive_workspace_reader"

    assert browseract_ui_service_by_alias("BrowserAct") is None


def test_ltd_runtime_catalog_derives_provider_ui_and_runtime_managed_profiles(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    onemin = catalog.get_profile("1min AI")
    assert onemin is not None
    assert onemin.runtime_state == "provider_executable"
    assert onemin.matched_provider_key == "onemin"
    assert {action.action_key for action in onemin.actions} >= {
        "discover_account",
        "background_remove",
        "code_generate",
        "reasoned_patch_review",
        "image_generate",
        "image_upscale",
        "media_transform",
    }

    documentation = catalog.get_profile("Documentation.AI")
    assert documentation is not None
    assert documentation.runtime_state == "browseract_ui_ready"
    assert documentation.browseract_ui_service_key == "documentation_ai_workspace_reader"
    assert {action.action_key for action in documentation.actions} == {
        "discover_account",
        "inspect_workspace",
    }

    markupgo = catalog.get_profile("markupgo")
    assert markupgo is not None
    assert markupgo.runtime_state == "browseract_ui_ready"
    assert markupgo.matched_provider_key == "markupgo"
    assert {action.action_key for action in markupgo.actions} == {
        "discover_account",
        "inspect_workspace",
    }

    emailit = catalog.get_profile("Emailit")
    assert emailit is not None
    assert emailit.runtime_state == "runtime_managed"
    assert {action.action_key for action in emailit.actions} == {
        "delivery_outbox",
        "discover_account",
    }

    hedy = catalog.get_profile("hedy.ai")
    assert hedy is not None
    assert hedy.runtime_state == "browseract_discoverable"
    assert [action.action_key for action in hedy.actions] == ["discover_account"]
