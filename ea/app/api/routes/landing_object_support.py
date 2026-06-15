from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from app.api.dependencies import RequestContext
from app.api.routes.landing_content import app_nav_groups_for_brand
from app.api.routes.landing_public_support import _console_shell_context, _render_public_template
from app.services.public_branding import request_brand


def _object_detail_row(
    title: str,
    detail: str,
    tag: str,
    href: str = "",
    action_href: str = "",
    action_label: str = "",
    action_value: str = "",
    action_method: str = "",
    return_to: str = "",
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    secondary_action_value: str = "",
    secondary_action_method: str = "",
    secondary_return_to: str = "",
    tertiary_action_href: str = "",
    tertiary_action_label: str = "",
    tertiary_action_value: str = "",
    tertiary_action_method: str = "",
    tertiary_return_to: str = "",
    quaternary_action_href: str = "",
    quaternary_action_label: str = "",
    quaternary_action_value: str = "",
    quaternary_action_method: str = "",
    quaternary_return_to: str = "",
) -> dict[str, str]:
    row = {
        "title": str(title or "").strip(),
        "detail": str(detail or "").strip(),
        "tag": str(tag or "").strip(),
    }
    if href:
        row["href"] = href
    if action_href:
        row["action_href"] = action_href
    if action_label:
        row["action_label"] = action_label
    if action_value:
        row["action_value"] = action_value
    if action_method:
        row["action_method"] = action_method
    if return_to:
        row["return_to"] = return_to
    if secondary_action_href:
        row["secondary_action_href"] = secondary_action_href
    if secondary_action_label:
        row["secondary_action_label"] = secondary_action_label
    if secondary_action_value:
        row["secondary_action_value"] = secondary_action_value
    if secondary_action_method:
        row["secondary_action_method"] = secondary_action_method
    if secondary_return_to:
        row["secondary_return_to"] = secondary_return_to
    if tertiary_action_href:
        row["tertiary_action_href"] = tertiary_action_href
    if tertiary_action_label:
        row["tertiary_action_label"] = tertiary_action_label
    if tertiary_action_value:
        row["tertiary_action_value"] = tertiary_action_value
    if tertiary_action_method:
        row["tertiary_action_method"] = tertiary_action_method
    if tertiary_return_to:
        row["tertiary_return_to"] = tertiary_return_to
    if quaternary_action_href:
        row["quaternary_action_href"] = quaternary_action_href
    if quaternary_action_label:
        row["quaternary_action_label"] = quaternary_action_label
    if quaternary_action_value:
        row["quaternary_action_value"] = quaternary_action_value
    if quaternary_action_method:
        row["quaternary_action_method"] = quaternary_action_method
    if quaternary_return_to:
        row["quaternary_return_to"] = quaternary_return_to
    return row


def _evidence_detail_rows(items) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, str]] = []
    for item in items or ():
        rows.append(
            _object_detail_row(
                str(getattr(item, "note", "") or getattr(item, "ref", "") or "Supporting evidence"),
                str(getattr(item, "ref", "") or "No external reference attached."),
                str(getattr(item, "source_type", "") or "Evidence"),
            )
        )
    if rows:
        return rows
    return [_object_detail_row("No supporting evidence yet", "This object has no attached evidence refs yet.", "Pending")]


def _render_console_object_detail(
    *,
    request: Request,
    context: RequestContext,
    workspace_label: str,
    page_title: str,
    current_nav: str,
    console_title: str,
    console_summary: str,
    object_kind: str,
    object_title: str,
    object_summary: str,
    object_meta: list[dict[str, str]],
    object_media: dict[str, object] | None = None,
    object_ooda_title: str = "",
    object_ooda_copy: str = "",
    object_ooda_rows: list[dict[str, str]] | None = None,
    object_sidebar_title: str = "",
    object_sidebar_copy: str = "",
    object_sidebar_rows: list[dict[str, str]] | None = None,
    object_sections: list[dict[str, object]] | None = None,
    object_sidebar_form: dict[str, object] | None = None,
    object_feedback: dict[str, object] | None = None,
) -> HTMLResponse:
    return _render_public_template(
        request,
        "app/object_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=page_title,
                current_nav=current_nav,
                context=context,
                console_title=console_title,
                console_summary=console_summary,
                nav_groups=app_nav_groups_for_brand(request_brand(request)["key"]),
                workspace_label=workspace_label,
                cards=[],
                stats=[{"label": item["label"], "value": item["value"]} for item in object_meta],
            ),
            "object_kind": object_kind,
            "object_title": object_title,
            "object_summary": object_summary,
            "object_meta": object_meta,
            "object_media": object_media or {},
            "object_ooda_title": object_ooda_title,
            "object_ooda_copy": object_ooda_copy,
            "object_ooda_rows": object_ooda_rows or [],
            "object_sidebar_title": object_sidebar_title,
            "object_sidebar_copy": object_sidebar_copy,
            "object_sidebar_rows": object_sidebar_rows or [],
            "object_sections": object_sections or [],
            "object_sidebar_form": object_sidebar_form or {},
            "object_feedback": object_feedback or {},
        },
    )
