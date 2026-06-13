from __future__ import annotations

import json
from pathlib import Path

from tests.product_test_helpers import build_operator_product_client, build_product_client, seed_product_state


ROOT = Path(__file__).resolve().parents[1]


def test_project_mode_switchboard_is_operator_only_and_renders_separate_product_planes() -> None:
    client = build_product_client(principal_id="exec-project-mode-switchboard")
    operator_client = build_operator_product_client(principal_id="operator-project-mode-switchboard")

    response = client.get("/modes")
    assert response.status_code in {401, 403}

    response = operator_client.get("/modes")

    assert response.status_code == 200
    assert "One repo, separate product claims." in response.text
    assert "EA Core" in response.text
    assert "Memorial" in response.text
    assert "Provider Lab" in response.text
    assert "Chummer Release Control" in response.text
    assert "Property" in response.text
    assert 'data-project-mode-switchboard' in response.text
    assert 'class="mode-pill blocked"' in response.text
    assert 'href="/memorials/' not in response.text
    assert 'href="/properties' not in response.text


def test_operator_provider_dashboard_shows_governed_lanes_without_secret_ids() -> None:
    client = build_operator_product_client(principal_id="exec-provider-dashboard")

    response = client.get("/admin/providers")

    assert response.status_code == 200
    assert "What each provider is allowed to do" in response.text
    assert "Poppy AI Public Content Draft Workbench" in response.text
    assert "MagicFit Media Factory Candidate" in response.text
    assert "Unmixr Governed Voice Runtime" in response.text
    assert "Allowed:" in response.text
    assert "Proof gate clear" in response.text
    assert "source-of-truth" not in response.text.lower()
    assert "provider-test-challenger" not in response.text


def test_show_surface_manifest_includes_project_switchboard() -> None:
    manifest = json.loads((ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json").read_text(encoding="utf-8"))

    assert manifest["demo_mode"] == "ea_core"
    assert "/modes" not in manifest["allowed_surfaces"]
    assert "/modes" in manifest["operator_surfaces"]
    assert "/memorials/*" in manifest["forbidden_surfaces"]
    assert "JoggAI" in manifest["forbidden_provider_names"]


def test_project_mode_runtime_verifier_passes_against_ea_core_surface() -> None:
    from scripts.verify_project_mode_runtime import main as verify_runtime

    assert verify_runtime() == 0


def test_plain_deploy_target_is_fail_closed() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "deploy-ea-prod:" in makefile
    assert "deploy-property:" in makefile
    assert "Refusing ambiguous deploy" in makefile
    assert "deploy:\n\tdocker compose" not in makefile


def test_integrations_page_uses_ea_brand_title_not_propertyquarry() -> None:
    client = build_product_client(principal_id="exec-integrations-title")

    response = client.get("/integrations")

    assert response.status_code == 200
    assert "Executive Assistant Integrations" in response.text
    assert "PropertyQuarry Integrations" not in response.text


def test_ea_core_allowed_surfaces_do_not_leak_forbidden_planes() -> None:
    manifest = json.loads((ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json").read_text(encoding="utf-8"))
    forbidden_paths = tuple(str(value).replace("*", "") for value in manifest["forbidden_surfaces"])
    forbidden_provider_names = tuple(str(value) for value in manifest["forbidden_provider_names"])
    client = build_product_client(principal_id="exec-show-surface")
    seed_product_state(client, principal_id="exec-show-surface")

    for path in ("/", "/app/today", "/app/queue", "/app/commitments", "/app/settings"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.text
        for forbidden in forbidden_paths:
            assert f'href="{forbidden}' not in body
            assert f"href='{forbidden}" not in body
        for provider_name in forbidden_provider_names:
            assert provider_name not in body
