from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.api.routes.landing_browser import _workspace_session_cookie_kwargs
from app.api.routes.landing_content import public_nav_for_brand
from app.api.routes.landing_view_models import channel_cards as _channel_cards
from app.api.routes.landing_view_models import humanize as _humanize
from app.api.routes.landing_view_models import list_rows as _list_rows
from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.public_branding import request_brand
from app.services.public_clickrank import clickrank_head_snippet as _clickrank_head_snippet, request_hostname as _request_hostname
from app.services.public_rybbit import rybbit_head_snippet as _rybbit_head_snippet

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
templates.env.globals["clickrank_head_snippet"] = lambda request=None: Markup(_clickrank_head_snippet(_request_hostname(request)))
templates.env.globals["rybbit_head_snippet"] = lambda request=None: Markup(_rybbit_head_snippet(_request_hostname(request)))


def _principal_for_page(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    if access_identity is not None:
        return access_identity.principal_id
    return ""


def _anonymous_onboarding_status(request: Request | None = None) -> dict[str, object]:
    brand = request_brand(request) if request is not None else {"key": "ea", "name": "Executive Assistant"}
    return {
        "principal_id": "",
        "status": "anonymous",
        "workspace": {"name": str(brand.get("name") or "Executive Assistant")},
        "selected_channels": [],
        "privacy": {},
        "assistant_modes": [],
        "featured_domains": [],
        "storage_posture": {},
        "channels": {},
        "brief_preview": {},
        "next_step": "Sign in to start a workspace or view the current one.",
        "onboarding_id": "",
    }


def _load_status(
    *,
    request: Request,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> tuple[str, dict[str, object]]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity)
    if not principal_id:
        return "", _anonymous_onboarding_status(request)
    return principal_id, container.onboarding.status(principal_id=principal_id)


def _public_app_base_url(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-host") or "").strip().lower().rstrip(".")
    request_host = str(request.url.hostname or "").strip().lower().rstrip(".")
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip() or request.url.scheme
    effective_host = forwarded or request_host
    if effective_host in {"propertyquarry.com", "www.propertyquarry.com"}:
        host = forwarded or request_host
        return f"https://{host}"
    from os import environ

    explicit = str(environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if forwarded:
        forwarded_proto = _first_forwarded_https_or_first_token(forwarded_proto)
    if forwarded:
        return f"{forwarded_proto}://{forwarded}"
    return str(request.base_url).rstrip("/")


def _first_forwarded_https_or_first_token(raw: str) -> str:
    tokens = [token.strip().lower() for token in str(raw or "").split(",") if token.strip()]
    if "https" in tokens:
        return "https"
    if "wss" in tokens:
        return "wss"
    return tokens[0] if tokens else ""


def _public_page_url(request: Request, path: str = "") -> str:
    brand = request_brand(request)
    base = str(brand.get("public_base_url") or "").strip().rstrip("/")
    if not base:
        base = _public_app_base_url(request)
    normalized_path = "/" + str(path or request.url.path or "/").lstrip("/")
    if normalized_path == "//":
        normalized_path = "/"
    return f"{base}{normalized_path}"


def _faq_schema_entries(rows: tuple[dict[str, str], ...] | list[dict[str, str]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if not question or not answer:
            continue
        entries.append(
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": answer,
                },
            }
        )
    return entries


def _public_page_schema(
    *,
    request: Request,
    page_title: str,
    page_description: str,
    path: str,
    faq_rows: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
) -> tuple[str, ...]:
    brand = request_brand(request)
    canonical_url = _public_page_url(request, path)
    is_ea = str(brand.get("key") or "") == "ea"
    blocks: list[dict[str, object]] = [
        {
            "@context": "https://schema.org",
            "@type": "WebApplication" if is_ea else "WebPage",
            "name": page_title,
            "description": page_description,
            "url": canonical_url,
            **({"applicationCategory": "BusinessApplication"} if is_ea else {}),
        }
    ]
    faq_entries = _faq_schema_entries(faq_rows)
    if faq_entries:
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": faq_entries,
            }
        )
    return tuple(json.dumps(block, ensure_ascii=False, separators=(",", ":")) for block in blocks)


def _public_page_context(
    *,
    request: Request,
    page_title: str,
    page_description: str,
    path: str,
    indexable: bool = True,
    faq_rows: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
) -> dict[str, object]:
    canonical_url = _public_page_url(request, path)
    return {
        "meta_description": page_description,
        "canonical_url": canonical_url,
        "og_title": page_title,
        "og_description": page_description,
        "og_url": canonical_url,
        "og_type": "website",
        "twitter_card": "summary_large_image",
        "robots_meta_content": "index,follow,max-image-preview:large" if indexable else "noindex,nofollow,noarchive,nosnippet",
        "structured_data_blocks": _public_page_schema(
            request=request,
            page_title=page_title,
            page_description=page_description,
            path=path,
            faq_rows=faq_rows,
        ),
    }


def _public_context(
    *,
    request: Request,
    current_nav: str,
    page_title: str,
    principal_id: str,
    status: dict[str, object],
    access_identity: CloudflareAccessIdentity | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    default_first_brief = (
        (
            "Connect Google sign-in if you want easier return access from the same account.",
            "Keep one reviewable office loop before widening the channel footprint.",
            "Make approvals and memory rules explicit before automating actions.",
        )
        if str(brand.get("key") or "") == "ea"
        else (
            "Connect Google sign-in if you want easier return access from the same account.",
            "Keep one reviewable property workflow before widening the channel footprint.",
            "Make approvals and memory rules explicit before automating actions.",
        )
    )
    default_suggested_actions = (
        (
            "Turn the workspace posture into a useful morning memo and decision loop.",
            "Add more channels only after the first loop already feels useful.",
        )
        if str(brand.get("key") or "") == "ea"
        else (
            "Turn the workspace posture into a useful shortlist and research loop.",
            "Add more channels only after the first loop already feels useful.",
        )
    )
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    preview = dict(status.get("brief_preview") or {})
    selected_channels = [str(row) for row in (status.get("selected_channels") or []) if str(row).strip()]
    context: dict[str, object] = {
        "page_title": page_title,
        "brand": brand,
        "public_nav": public_nav_for_brand(str(brand.get("key") or "")),
        "current_nav": current_nav,
        "access_identity": access_identity,
        "principal_id": principal_id,
        "status": status,
        "workspace": workspace,
        "privacy": dict(status.get("privacy") or {}),
        "channels": channels,
        "channel_cards": _channel_cards(channels),
        "selected_channels_label": ", ".join(selected_channels) if selected_channels else "Google sign-in recommended",
        "workspace_mode_label": _humanize(str(workspace.get("mode") or "personal")),
        "brief_headline": str(preview.get("headline") or "Turn your channels into a prioritized day."),
        "first_brief_items": _list_rows(
            preview.get("first_brief_preview") or preview.get("first_brief"),
            default_first_brief,
        ),
        "suggested_actions": _list_rows(
            preview.get("suggested_actions"),
            default_suggested_actions,
        ),
        "trust_notes": _list_rows(
            preview.get("trust_notes"),
            (
                "Each channel says clearly what the assistant can actually do today.",
                "Approvals and workspace memory stay visible product features, not hidden implementation details.",
            ),
        ),
        "top_contacts": _list_rows(preview.get("top_contacts"), ("No contact memory yet.",)),
        "top_themes": _list_rows(preview.get("top_themes"), ("No themes yet.",)),
    }
    if extra:
        context.update(extra)
    return context


def _activation_preview_for_brand(brand_key: str, status: dict[str, object]) -> dict[str, list[str]]:
    preview = dict(status.get("brief_preview") or {})
    if str(brand_key or "").strip().lower() == "ea":
        return {
            "brief": _list_rows(
                preview.get("first_brief_preview") or preview.get("first_brief"),
                (
                    "Morning memo shows what changed since the last office cycle.",
                    "Queue shows what needs a decision now.",
                    "Commitments keep follow-ups visible until they close.",
                ),
            ),
            "queue": _list_rows(
                preview.get("suggested_actions"),
                (
                    "Review one decision before noon.",
                    "Keep one follow-up from slipping.",
                    "Approve one draft before anything sends.",
                ),
            ),
            "commitments": _list_rows(
                preview.get("trust_notes"),
                (
                    "Nothing sends without review.",
                    "Evidence stays attached to repeated decisions.",
                ),
            ),
        }
    return {
        "brief": _list_rows(
            preview.get("first_brief_preview") or preview.get("first_brief"),
            (
                "Shortlist shows which properties actually fit.",
                "Review shows what still needs checking.",
                "Research keeps missing facts visible until they close.",
            ),
        ),
        "queue": _list_rows(
            preview.get("suggested_actions"),
            (
                "Review one candidate in more detail.",
                "Check one missing building fact.",
                "Decide which property deserves deeper research next.",
            ),
        ),
        "commitments": _list_rows(
            preview.get("trust_notes"),
            (
                "No property gets promoted without visible evidence.",
                "Preferences stay attached to the shortlist instead of disappearing.",
            ),
        ),
    }


def _console_shell_context(
    *,
    request: Request,
    page_title: str,
    current_nav: str,
    context,
    console_title: str,
    console_summary: str,
    nav_groups: tuple[dict[str, object], ...],
    workspace_label: str,
    cards: list[dict[str, object]],
    stats: list[dict[str, str]],
    console_form: dict[str, object] | None = None,
    activation_banner: dict[str, str] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    workspace_context_label = "Property workspace" if brand["key"] == "propertyquarry" else "Office status"
    if context.access_email:
        workspace_context_label = context.access_email
    elif context.operator_id:
        workspace_context_label = "Operator access"
    return {
        "page_title": page_title,
        "brand": brand,
        "current_nav": current_nav,
        "nav_groups": nav_groups,
        "console_title": console_title,
        "console_summary": console_summary,
        "workspace_label": workspace_label,
        "cards": cards,
        "stats": stats,
        "console_form": console_form or {},
        "activation_banner": activation_banner or {},
        "principal_id": context.principal_id,
        "access_email": context.access_email,
        "operator_id": context.operator_id,
        "workspace_context_label": workspace_context_label,
        "base_console_template": "base_console_property.html" if brand["key"] == "propertyquarry" else "base_console_ea.html",
    }


def _today_activation_banner(*, request: Request, status: dict[str, object]) -> dict[str, str]:
    brand = request_brand(request)
    if brand["key"] != "ea":
        return {}
    activation = str(request.query_params.get("activation") or "").strip().lower()
    if activation not in {"workspace_created", "google_connected"}:
        return {}
    google = dict(dict(status.get("channels") or {}).get("google") or {})
    google_connected = bool(google.get("connected")) or bool(str(google.get("account_email") or "").strip())
    google_status = str(google.get("status") or "").strip().lower()
    if google_status in {"connected", "enabled", "active", "ready"}:
        google_connected = True
    if activation == "google_connected":
        return {
            "kicker": "Today is live",
            "title": "Google is connected. Use Today as the proof surface.",
            "body": "Check whether the memo, queue, and timing are actually better now. If Today did not improve, reduce scope instead of adding more setup.",
            "primary_href": "/app/queue",
            "primary_label": "Review queue",
            "secondary_href": "/app/settings/google",
            "secondary_label": "Google settings",
        }
    banner = {
        "kicker": "Workspace created",
        "title": "Start with Today, not more setup.",
        "body": "This is the first live office loop. Check what changed, what needs a decision, and what must stay visible before you widen channels or automation.",
        "primary_href": "/app/queue",
        "primary_label": "Open queue",
    }
    if not google_connected:
        banner["secondary_href"] = "/app/actions/google/connect?return_to=/app/today?activation=google_connected"
        banner["secondary_label"] = "Connect Google later"
    else:
        banner["secondary_href"] = "/app/settings"
        banner["secondary_label"] = "Office settings"
    return banner


def _render_public_template(request: Request, template_name: str, *, indexable: bool = False, **context: Any) -> HTMLResponse:
    context.setdefault("request", request)
    context.setdefault("brand", request_brand(request))
    context.setdefault("robots_meta_content", "index,follow,max-image-preview:large" if indexable else "noindex,nofollow,noarchive,nosnippet")
    response = templates.TemplateResponse(request, template_name, context)
    if not indexable:
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def _render_secure_link_page(
    request: Request,
    *,
    page_title: str,
    current_nav: str,
    link_kicker: str,
    link_title: str,
    link_summary: str,
    link_detail_title: str,
    link_status_label: str,
    link_rows: list[dict[str, str]],
    primary_action_href: str,
    primary_action_label: str,
    primary_action_method: str = "get",
    primary_action_fields: dict[str, str] | None = None,
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    response = _render_public_template(
        request,
        "workspace_link.html",
        **_public_context(
            request=request,
            current_nav=current_nav,
            page_title=page_title,
            principal_id="",
            status=_anonymous_onboarding_status(request),
            access_identity=None,
            extra={
                "link_kicker": link_kicker,
                "link_title": link_title,
                "link_summary": link_summary,
                "link_detail_title": link_detail_title,
                "link_status_label": link_status_label,
                "link_rows": link_rows,
                "primary_action_href": primary_action_href,
                "primary_action_label": primary_action_label,
                "primary_action_method": primary_action_method,
                "primary_action_fields": primary_action_fields or {},
                "secondary_action_href": secondary_action_href,
                "secondary_action_label": secondary_action_label,
            },
        ),
    )
    response.status_code = status_code
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response

