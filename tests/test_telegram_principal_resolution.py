from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

from app.api.routes import channels
from app.repositories.connector_bindings import ConnectorBinding, InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.proactive_telegram_binding import _candidate_principal_ids
from app.services.telegram_delivery import resolve_primary_telegram_binding
from app.services.tool_runtime import ToolRuntimeService


def _tool_runtime() -> ToolRuntimeService:
    return ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )


def _alias_candidates(*, principal_ids: tuple[str, ...], **_: object) -> tuple[str, ...]:
    ordered: list[str] = []
    for raw in principal_ids:
        normalized = str(raw or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
        if normalized == "cf-email:tibor.girschele@gmail.com" and "exec-1" not in ordered:
            ordered.append("exec-1")
        if normalized == "exec-1" and "cf-email:tibor.girschele@gmail.com" not in ordered:
            ordered.append("cf-email:tibor.girschele@gmail.com")
    return tuple(ordered)


def test_auto_bind_telegram_chat_canonicalizes_default_email_alias(monkeypatch) -> None:
    monkeypatch.setattr(channels.google_oauth_service, "_principal_alias_candidates", _alias_candidates)
    container = SimpleNamespace(tool_runtime=_tool_runtime())

    principal_id = channels._auto_bind_telegram_chat(
        container,
        "246813579",
        config={
            "default_principal_id": "cf-email:tibor.girschele@gmail.com",
            "auto_bind_unknown_chat": True,
            "bot_key": "default",
            "handle": "ea_concierge_bot",
        },
    )

    assert principal_id == "exec-1"
    bindings = container.tool_runtime.list_connector_bindings("exec-1", limit=20)
    assert any(
        binding.connector_name == "telegram_identity"
        and binding.external_account_ref == "246813579"
        and dict(binding.auth_metadata_json or {}).get("auto_bound") is True
        for binding in bindings
    )


def test_resolve_telegram_principal_canonicalizes_existing_alias_binding(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "cf-email:tibor.girschele@gmail.com")
    monkeypatch.setattr(channels.google_oauth_service, "_principal_alias_candidates", _alias_candidates)
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="cf-email:tibor.girschele@gmail.com",
        connector_name="telegram_identity",
        external_account_ref="246813579",
        auth_metadata_json={"default_chat_ref": "246813579", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    container = SimpleNamespace(tool_runtime=runtime)

    principal_id = channels._resolve_telegram_principal(container, "246813579")

    assert principal_id == "exec-1"
    assert channels._telegram_principal_is_registered_user(container, "exec-1") is True


def test_resolve_primary_telegram_binding_supports_alias_binding_for_canonical_principal(monkeypatch) -> None:
    from app.services import telegram_delivery

    monkeypatch.setattr(telegram_delivery.google_oauth_service, "_principal_alias_candidates", _alias_candidates)
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    runtime.upsert_connector_binding(
        principal_id="cf-email:tibor.girschele@gmail.com",
        connector_name="telegram_identity",
        external_account_ref="246813579",
        auth_metadata_json={"default_chat_ref": "246813579", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )

    binding = resolve_primary_telegram_binding(runtime, principal_id="exec-1")

    assert binding is not None
    assert binding.principal_id == "cf-email:tibor.girschele@gmail.com"
    assert str(binding.external_account_ref) == "246813579"


def test_resolve_primary_telegram_binding_prefers_reachable_chat_when_newest_binding_is_dead(monkeypatch) -> None:
    from app.services import proactive_telegram_binding, telegram_delivery

    monkeypatch.setattr(telegram_delivery.google_oauth_service, "_principal_alias_candidates", _alias_candidates)
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    proactive_telegram_binding._CHAT_VALIDATION_CACHE.clear()
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="cf-email:tibor.girschele@gmail.com",
        connector_name="telegram_identity",
        external_account_ref="246813579",
        auth_metadata_json={"default_chat_ref": "246813579", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"type": "private"}}).encode("utf-8")

    def _fake_urlopen(request, timeout=15):
        if "246813579" in request.full_url:
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=io.BytesIO(json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode("utf-8")),
            )
        return _Response()

    monkeypatch.setattr("app.services.proactive_telegram_binding.urllib.request.urlopen", _fake_urlopen)

    binding = resolve_primary_telegram_binding(runtime, principal_id="exec-1")

    assert isinstance(binding, ConnectorBinding)
    assert binding.principal_id == "exec-1"
    assert str(binding.external_account_ref) == "1354554303"


def test_proactive_candidate_principals_expand_email_aliases(monkeypatch) -> None:
    from app.services import proactive_telegram_binding

    monkeypatch.setattr(proactive_telegram_binding.google_oauth_service, "_principal_alias_candidates", _alias_candidates)

    assert _candidate_principal_ids("exec-1") == ["exec-1", "cf-email:tibor.girschele@gmail.com"]
