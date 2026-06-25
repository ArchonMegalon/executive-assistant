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
    assert 'class="mode-pill ready"' in response.text
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


def test_project_mode_runtime_verifier_passes_against_memorial_surface() -> None:
    from scripts.verify_project_mode_runtime import main as verify_runtime

    assert verify_runtime(["--mode", "memorial"]) == 0


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


def test_ea_public_pages_do_not_fall_back_to_propertyquarry_brand_copy() -> None:
    client = build_product_client(principal_id="exec-public-brand-copy")

    product = client.get("/product")
    landing = client.get("/")
    get_started = client.get("/get-started")
    security = client.get("/security")
    integrations = client.get("/integrations")
    pricing = client.get("/pricing")
    docs = client.get("/docs")
    register = client.get("/register", follow_redirects=False)
    google = client.get("/integrations/google")
    whatsapp = client.get("/integrations/whatsapp")

    assert product.status_code == 200
    assert landing.status_code == 200
    assert get_started.status_code == 200
    assert security.status_code == 200
    assert integrations.status_code == 200
    assert pricing.status_code == 200
    assert docs.status_code == 200
    assert register.status_code == 307
    assert google.status_code == 200
    assert whatsapp.status_code == 200
    assert "Run one office loop without rebuilding it by hand each morning." in product.text
    assert "PropertyQuarry is designed for the daily loop" not in product.text
    assert "Run one office loop without rebuilding it by hand each morning." in landing.text
    assert "PropertyQuarry turns fragmented property search" not in landing.text
    assert "See the office loop before you spend time configuring it." in get_started.text
    assert "Get to the first useful office loop quickly." in get_started.text
    assert "Connect the first real signal" in get_started.text
    assert "Choose the property workflow" not in get_started.text
    assert "PropertyQuarry Workspace" not in get_started.text
    assert "Executive Assistant Security" in security.text
    assert "See what Executive Assistant can do before you let it act." in security.text
    assert "PropertyQuarry can do before you let it act." not in security.text
    assert "Executive Assistant Integrations" in integrations.text
    assert "Connect only what improves the office loop." in integrations.text
    assert "PropertyQuarry can identify" not in integrations.text
    assert "See the office loop before you spend time configuring it." in pricing.text
    assert "Executive Assistant Pricing" not in pricing.text
    assert "Choose the plan that matches the office load, review needs, and delivery posture." not in pricing.text
    assert "See what Executive Assistant can do before you let it act." in docs.text
    assert "Executive Assistant Docs" not in docs.text
    assert register.headers["location"] == "/get-started"
    assert "PropertyQuarry only needs Google identity" not in google.text
    assert "live assistant path" not in whatsapp.text


def test_google_connected_template_uses_configured_propertyquarry_register_url() -> None:
    template = (ROOT / "ea/app/templates/google_connected.html").read_text(encoding="utf-8")

    assert "propertyquarry_register_ready_url" in template
    assert "https://propertyquarry.com/register?ready=1" not in template


def test_ea_public_home_is_indexable_and_contains_growth_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    client = build_product_client(principal_id="exec-public-growth")

    response = client.get("/", headers={"host": "myexternalbrain.com", "x-forwarded-host": "myexternalbrain.com", "x-forwarded-proto": "https"})

    assert response.status_code == 200
    assert response.headers.get("X-Robots-Tag") is None
    assert '<meta name="robots" content="index,follow,max-image-preview:large">' in response.text
    assert '<link rel="canonical" href="https://myexternalbrain.com/">' in response.text
    assert '<meta name="description" content="Executive Assistant gives one office a morning memo, decision queue, commitment ledger, and review-first approvals in one Today view.">' in response.text
    assert '"@type":"FAQPage"' in response.text
    assert '"@type":"WebApplication"' in response.text
    assert "What shows up first each morning?" in response.text


def test_public_robots_txt_allows_public_pages_and_blocks_private_surfaces(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    client = build_product_client(principal_id="exec-public-robots")

    response = client.get("/robots.txt", headers={"host": "myexternalbrain.com", "x-forwarded-host": "myexternalbrain.com", "x-forwarded-proto": "https"})

    assert response.status_code == 200
    lines = set(response.text.splitlines())
    assert "Disallow: /app" in lines
    assert "Disallow: /admin" in lines
    assert "Disallow: /sign-in" in lines
    assert "Disallow: /register" in lines
    assert "Disallow: /memorials" in lines
    assert "Disallow: /" not in lines


def test_ea_register_is_only_a_continuation_into_get_started() -> None:
    client = build_product_client(principal_id="exec-register-redirect")

    response = client.get("/register", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/get-started"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive, nosnippet"


def test_ea_workspace_settings_surfaces_do_not_fall_back_to_propertyquarry_labels() -> None:
    client = build_product_client(principal_id="exec-settings-brand-copy")
    seed_product_state(client, principal_id="exec-settings-brand-copy")

    google = client.get("/app/settings/google")
    usage = client.get("/app/settings/usage")
    trust = client.get("/app/settings/trust")
    access = client.get("/app/settings/access")
    invitations = client.get("/app/settings/invitations")

    assert google.status_code == 200
    assert usage.status_code == 200
    assert trust.status_code == 200
    assert access.status_code == 200
    assert invitations.status_code == 200
    assert "PropertyQuarry Google connection" not in google.text
    assert "PropertyQuarry Workspace" not in google.text
    assert "PropertyQuarry usage" not in usage.text
    assert "PropertyQuarry trust" not in trust.text
    assert "Release authority" in trust.text
    assert "Authority posture" in trust.text
    assert "Release label" in trust.text
    assert "Release next action" in trust.text
    assert "What release trust is anchored to" in trust.text
    assert "PropertyQuarry access" not in access.text
    assert "PropertyQuarry invitations" not in invitations.text
    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "What the release proof says right now" not in settings.text
    assert "What needs support before the loop slips" not in settings.text


def test_ea_setup_start_opens_live_today_instead_of_bouncing_back_to_setup() -> None:
    client = build_product_client(principal_id="exec-setup-today-first")

    started = client.post(
        "/setup/start",
        data={
            "workspace_name": "Founder Office",
            "workspace_mode": "personal",
            "timezone": "Europe/Vienna",
            "region": "AT",
            "language": "en",
            "selected_channels": "google",
        },
        follow_redirects=False,
    )

    assert started.status_code == 303
    assert started.headers["location"].startswith("/workspace-access/")

    today = client.get(started.headers["location"], follow_redirects=True)

    assert today.status_code == 200
    assert "Workspace created" in today.text
    assert "Start with Today, not more setup." in today.text
    assert "Connect Google later" in today.text


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


def test_ea_core_does_not_expose_memorial_nested_operator_routes() -> None:
    client = build_product_client(principal_id="exec-memorial-mode-operator-surface")
    blocked_get_paths: tuple[str, ...] = (
        "/memorials/manfred",
        "/memorials/manfred/archive",
        "/memorials/manfred/archive.json",
        "/memorials/manfred/warmup",
        "/memorials/manfred/warmup-status",
        "/memorials/manfred/operator-status",
        "/memorials/manfred/video-meeting/status",
        "/memorials/manfred/video-meeting/session",
        "/memorials/manfred/video-meeting/provider-callback",
        "/memorials/manfred/playback-telemetry",
        "/memorials/manfred/realtime",
        "/memorials/manfred/realtime/webrtc",
        "/memorials/manfred/voice-config",
        "/memorials/manfred/voice-ab",
        "/memorials/manfred/voice-ab/rate",
        "/memorials/manfred/voice-ab-admin",
        "/memorials/manfred/voice-ab-admin/finalize",
        "/memorials/manfred/voice-ab-admin/maintain",
        "/memorials/manfred/voice-profile",
        "/memorials/manfred/voice-profile/build",
        "/memorials/manfred/voice-clone",
        "/memorials/manfred/chat",
        "/memorials/manfred/speech-transcribe",
        "/memorials/manfred/speech-synthesize",
        "/memorials/manfred/conversation-turn",
        "/memorials/manfred/personal-memory",
        "/memorials/files/manfred/memorial.json",
        "/memorials/files/manfred/tts_voice.json",
        "/memorials/manfred/app.webmanifest",
        "/memorials/manfred/service-worker.js",
        "/memorials/manfred/icon-180.png",
        "/memorials/manfred/icon.svg",
    )
    for path in blocked_get_paths:
        response = client.get(path, follow_redirects=False)
        assert response.status_code in {401, 403, 404, 405, 409}

    blocked_post_paths: tuple[str, ...] = (
        "/memorials/manfred/warmup",
        "/memorials/manfred/voice-clone",
        "/memorials/manfred/voice-ab/rate",
        "/memorials/manfred/voice-ab-admin/finalize",
        "/memorials/manfred/voice-ab-admin/maintain",
        "/memorials/manfred/voice-config",
        "/memorials/manfred/voice-profile/build",
        "/memorials/manfred/conversation-turn",
        "/memorials/manfred/personal-memory",
        "/memorials/manfred/video-meeting/session",
        "/memorials/manfred/video-meeting/provider-callback",
        "/memorials/manfred/playback-telemetry",
        "/memorials/manfred/speech-transcribe",
        "/memorials/manfred/speech-synthesize",
        "/memorials/manfred/chat",
    )
    for path in blocked_post_paths:
        response = client.post(path, json={}, follow_redirects=False)
        assert response.status_code in {401, 403, 404, 405, 409}
