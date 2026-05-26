from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends
from fastapi.responses import JSONResponse
from starlette.responses import Response


def codex_profiles_response_payload(
    *,
    container: Any,
    context: Any,
    provider_health: dict[str, object],
    include_sensitive: bool,
    safe_provider_health: dict[str, object],
    codex_profiles: Callable[..., list[dict[str, object]]],
    attach_provider_slot_state: Callable[..., list[dict[str, object]]],
    provider_registry_payload: Callable[..., dict[str, object]],
    codex_governance_payload: Callable[[], dict[str, object]],
    principal_identity_summary: Callable[[str], dict[str, object]],
) -> dict[str, object]:
    profiles = [
        {**profile, "provider_hint_order": list(profile["provider_hint_order"])}
        for profile in codex_profiles(
            container=container,
            principal_id=context.principal_id,
            provider_health=provider_health,
        )
    ]
    return {
        "principal": principal_identity_summary(context.principal_id),
        "governance": codex_governance_payload(),
        "profiles": attach_provider_slot_state(
            profiles,
            provider_health=safe_provider_health,
            include_sensitive=include_sensitive,
        ),
        "provider_health": safe_provider_health,
        "provider_registry": provider_registry_payload(
            container=container,
            principal_id=context.principal_id,
            provider_health=safe_provider_health,
            include_sensitive=include_sensitive,
        ),
    }


def codex_status_response_payload(
    *,
    window: str,
    compact: bool,
    context: Any,
    is_operator_context: Callable[[Any], bool],
    provider_health_snapshot: Callable[..., dict[str, object]],
    codex_status_report: Callable[..., dict[str, object]],
    codex_governance_payload: Callable[[], dict[str, object]],
) -> dict[str, object]:
    profile_health = provider_health_snapshot(lightweight=(not is_operator_context(context)))
    if is_operator_context(context):
        report = codex_status_report(window=window, provider_health=profile_health, compact=compact)
    else:
        report = dict(
            codex_status_report(
                window=window,
                principal_id=context.principal_id,
                provider_health=profile_health,
                compact=compact,
            )
        )
        report["fleet_burn"] = {}
    report["governance"] = codex_governance_payload()
    return report


def build_list_codex_profiles_handler(
    *,
    get_container: Callable[..., Any],
    get_request_context: Callable[..., Any],
    is_operator_context: Callable[[Any], bool],
    provider_health_snapshot: Callable[..., dict[str, object]],
    redacted_provider_health: Callable[..., dict[str, object]],
    codex_profiles: Callable[..., list[dict[str, object]]],
    attach_provider_slot_state: Callable[..., list[dict[str, object]]],
    provider_registry_payload: Callable[..., dict[str, object]],
    codex_governance_payload: Callable[[], dict[str, object]],
    principal_identity_summary: Callable[[str], dict[str, object]],
) -> Callable[..., Response]:
    def list_codex_profiles(
        container: Any = Depends(get_container),
        context: Any = Depends(get_request_context),
    ) -> Response:
        include_sensitive = is_operator_context(context)
        provider_health = provider_health_snapshot(lightweight=(not include_sensitive))
        safe_provider_health = redacted_provider_health(provider_health, include_sensitive=include_sensitive)
        return JSONResponse(
            codex_profiles_response_payload(
                container=container,
                context=context,
                provider_health=provider_health,
                include_sensitive=include_sensitive,
                safe_provider_health=safe_provider_health,
                codex_profiles=codex_profiles,
                attach_provider_slot_state=attach_provider_slot_state,
                provider_registry_payload=provider_registry_payload,
                codex_governance_payload=codex_governance_payload,
                principal_identity_summary=principal_identity_summary,
            )
        )

    list_codex_profiles.__name__ = "list_codex_profiles"
    list_codex_profiles.__qualname__ = "list_codex_profiles"
    return list_codex_profiles


def build_get_codex_status_handler(
    *,
    get_request_context: Callable[..., Any],
    is_operator_context: Callable[[Any], bool],
    provider_health_snapshot: Callable[..., dict[str, object]],
    codex_status_report: Callable[..., dict[str, object]],
    codex_governance_payload: Callable[[], dict[str, object]],
) -> Callable[..., Response]:
    def get_codex_status(
        window: str = "1h",
        refresh: bool = False,
        compact: bool = False,
        context: Any = Depends(get_request_context),
    ) -> Response:
        _ = refresh
        return JSONResponse(
            codex_status_response_payload(
                window=window,
                compact=compact,
                context=context,
                is_operator_context=is_operator_context,
                provider_health_snapshot=provider_health_snapshot,
                codex_status_report=codex_status_report,
                codex_governance_payload=codex_governance_payload,
            )
        )

    get_codex_status.__name__ = "get_codex_status"
    get_codex_status.__qualname__ = "get_codex_status"
    return get_codex_status
