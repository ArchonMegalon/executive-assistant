from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PORTABLE_FIXTURE_FILES = (
    "tests/test_telegram_delivery_service.py",
    "tests/test_proactive_telegram_binding.py",
    "tests/e2e/test_telegram_bot_workflows.py",
    "tests/e2e/test_telegram_bot_outbound_workflows.py",
    "tests/test_whatsapp_web_session_activation_script.py",
    "tests/test_whatsapp_web_session_activation_watch_script.py",
    "tests/test_whatsapp_delivery_outbox.py",
    "tests/test_whatsapp_delivery_router.py",
    "tests/test_whatsapp_web_route_persistence_script.py",
    "tests/test_whatsapp_web_session_delivery.py",
    "tests/test_whatsapp_web_session_live_send_script.py",
    "tests/test_whatsapp_web_session_readiness.py",
    "tests/test_whatsapp_web_session_readiness_script.py",
    "tests/test_whatsapp_web_session_teable_sync.py",
    "tests/test_whatsapp_web_teable_sync_readiness_script.py",
    "tests/test_whatsapp_web_session_bootstrap.py",
    "tests/test_runner.py",
    "tests/test_registration_contracts.py",
    "tests/test_google_oauth_service.py",
    "tests/test_ltd_provider_governance.py",
    "tests/test_blip_operator_capture_packet.py",
    "tests/test_responses_upstream.py",
    "tests/test_sync_env_to_teable.py",
    "tests/test_tool_execution.py",
)

SMOKE_RUNTIME_FIXTURE_FILES = (
    "tests/smoke_runtime_api_support.py",
    "tests/smoke_runtime_api_suite_3.py",
    "tests/smoke_runtime_api_suite_4.py",
    "tests/test_runner.py",
    "tests/test_telegram_delivery_service.py",
    "tests/test_proactive_telegram_binding.py",
)

DEFAULT_PRINCIPAL_FIXTURE_FILES = (
    "tests/test_di_container.py",
    "tests/test_product_api_contracts.py",
    "tests/test_providers_api_contracts.py",
    "tests/test_product_entitlement_contracts.py",
    "tests/e2e/test_product_workflows.py",
    "tests/test_google_oauth_service.py",
)

PROVIDER_API_IDENTITY_FIXTURE_FILES = (
    "tests/test_providers_api_contracts.py",
    "tests/test_product_api_contracts.py",
)

REPO_IDENTITY_FIXTURE_FILES = (
    "LTDs.md",
    ".env.example",
    ".env.local.example",
)

REPO_IDENTITY_FIXTURE_GLOBS = (
    "state/onemin_browseract_refresh_*.json",
)

MEMORIAL_ARCHIVE_PORTABILITY_GLOBS = (
    "memorial_archive/manfred/**/*.json",
    "memorial_archive/manfred/**/*.html",
)

DISALLOWED_FIXTURE_LITERALS = (
    "tibor.girschele" + "@gmail.com",
    "elisabeth.girschele" + "@gmail.com",
    "elizabeth.girschele@gmail.com",
    "the.girscheles" + "@gmail.com",
    "myexternalbrain" + ".com",
    "propertyquarry" + ".com",
    "packets.propertyquarry" + ".com",
    "Tibor WhatsApp",
    "tibor-wa-web",
    "tibor-whatsapp-web-session",
    "+43" + "68120864006",
    "tenant-tibor",
    "tibor_" + "concierge_bot",
    "tibor" + "@example.com",
    "+43" + "6641112223",
    "+43" + "664000000",
    "browser-profile://ea/whatsapp-web/" + "tibor",
    "session-" + "tibor",
    "Tibor " + "Girschele",
    "Tibor " + "Property Workspace",
    "Tibor.Girschele" + "@Gmail.com",
    "kleinhirn" + "@girschele" + ".com",
    "sprachenzentrum" + "@girschele" + ".com",
    "tibor" + "@myexternalbrain" + ".com",
    "property" + "@propertyquarry" + ".com",
    "https://myexternalbrain" + ".com",
    "https://propertyquarry" + ".com",
    "tibor" + "@girschele" + ".com",
    "office" + "@girschele" + ".com",
    "girschele" + ".com",
)

DISALLOWED_SMOKE_PRINCIPAL_LITERALS = (
    "exec" + "-1",
    "local" + "-user",
)

DISALLOWED_DEFAULT_PRINCIPAL_LITERALS = (
    "local" + "-user",
)

DISALLOWED_PERSONAL_IDENTITY_LITERALS = (
    "tibor.girschele" + "@gmail.com",
    "elisabeth.girschele" + "@gmail.com",
    "tibor_" + "concierge_bot",
    "Tibor " + "Girschele",
    "Tibor" + "'s Concierge",
    "tibor" + "@girschele" + ".com",
    "office" + "@girschele" + ".com",
)


def test_cleaned_fixture_cluster_uses_portable_identities() -> None:
    offenders: list[str] = []
    for relative_path in PORTABLE_FIXTURE_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for literal in DISALLOWED_FIXTURE_LITERALS:
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []


def test_provider_api_contract_fixtures_do_not_use_personal_identities() -> None:
    offenders: list[str] = []
    for relative_path in PROVIDER_API_IDENTITY_FIXTURE_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for literal in DISALLOWED_PERSONAL_IDENTITY_LITERALS:
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []


def test_repo_inventory_and_state_fixtures_do_not_use_personal_identities() -> None:
    offenders: list[str] = []
    paths = [REPO_ROOT / relative_path for relative_path in REPO_IDENTITY_FIXTURE_FILES]
    for pattern in REPO_IDENTITY_FIXTURE_GLOBS:
        paths.extend(sorted(REPO_ROOT.glob(pattern)))

    for path in paths:
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT)
        for literal in DISALLOWED_PERSONAL_IDENTITY_LITERALS:
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []


def test_smoke_runtime_fixtures_use_portable_default_principals() -> None:
    offenders: list[str] = []
    for relative_path in SMOKE_RUNTIME_FIXTURE_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for literal in DISALLOWED_SMOKE_PRINCIPAL_LITERALS:
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []


def test_default_principal_fixtures_do_not_use_legacy_local_user() -> None:
    offenders: list[str] = []
    for relative_path in DEFAULT_PRINCIPAL_FIXTURE_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for literal in DISALLOWED_DEFAULT_PRINCIPAL_LITERALS:
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []


def _retired_memorial_archive_artifacts_use_portable_public_contacts() -> None:
    offenders: list[str] = []
    paths: list[Path] = []
    for pattern in MEMORIAL_ARCHIVE_PORTABILITY_GLOBS:
        paths.extend(sorted(REPO_ROOT.glob(pattern)))

    for path in paths:
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT)
        for literal in (
            "myexternalbrain" + ".com",
            "memorial" + "@myexternalbrain" + ".com",
            "/docker/EA/memorial_archive",
        ):
            if literal in text:
                offenders.append(f"{relative_path}: {literal}")

    assert offenders == []
