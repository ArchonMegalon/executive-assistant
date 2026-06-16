from __future__ import annotations

from app.container import AppContainer
from app.product.service import build_product_service
from app.services.property_billing import payfunnels_configured, paypal_configured, property_commercial_snapshot
from app.services.property_market_catalog import (
    country_label as property_country_label,
    country_options as property_country_options,
    default_language_for_country,
    default_platforms_for_country,
    investment_research_mode_label as property_investment_research_mode_label,
    investment_research_mode_options as property_investment_research_mode_options,
    language_label as property_language_label,
    language_options as property_language_options,
    listing_mode_label as property_listing_mode_label,
    listing_mode_options as property_listing_mode_options,
    normalize_country_code,
    normalize_property_search_preferences,
    property_type_label as property_type_label_for_value,
    property_type_options as property_type_options_catalog,
    provider_options as property_provider_options,
)


def property_console_context(
    *,
    container: AppContainer,
    principal_id: str,
    status: dict[str, object],
    run_id: str = "",
) -> dict[str, object]:
    product = build_product_service(container)
    raw_property_preferences = dict(status.get("property_search_preferences") or {})
    preferences = normalize_property_search_preferences(dict(raw_property_preferences.get("raw_preferences") or raw_property_preferences))
    selected_country = normalize_country_code(preferences.get("country_code"))
    commercial = property_commercial_snapshot(preferences)
    payfunnels_plus = payfunnels_configured(plan_key="plus")
    paypal_enabled = paypal_configured()
    selected_platforms = {
        str(value or "").strip().lower()
        for value in (preferences.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    if not selected_platforms:
        selected_platforms = set(default_platforms_for_country(selected_country))
    country_provider_options = [dict(option) for option in property_provider_options(country_code=selected_country)]
    run_payload: dict[str, object] = {}
    normalized_run_id = str(run_id or "").strip()
    if normalized_run_id:
        try:
            run_payload = dict(
                product.get_property_search_run_status(
                    principal_id=principal_id,
                    run_id=normalized_run_id,
                )
                or {}
            )
        except Exception:
            run_payload = {}

    recent_matches: list[dict[str, object]] = []
    learning_summary: dict[str, object] = {}
    preference_bundle: dict[str, object] = {}
    preference_person_id = str(preferences.get("preference_person_id") or "self").strip() or "self"
    try:
        for handoff in product.list_handoffs(principal_id=principal_id, limit=12, status=None):
            task_type = str(getattr(handoff, "task_type", "") or "").strip()
            if task_type not in {"property_tour_followup", "property_alert_review"}:
                continue
            hosted_url = str(getattr(handoff, "tour_url", "") or "").strip()
            review_url = str(getattr(handoff, "editor_url", "") or "").strip()
            title = str(getattr(handoff, "summary", "") or "").strip() or str(getattr(handoff, "id", "") or "").strip() or "Property match"
            detail_parts = [
                str(getattr(handoff, "delivery_reason", "") or "").strip(),
                str(getattr(handoff, "counterparty", "") or "").strip(),
                str(getattr(handoff, "blocked_reason", "") or "").strip(),
            ]
            detail = " | ".join(part for part in detail_parts if part) or "Recent property follow-up."
            row: dict[str, object] = {
                "title": title,
                "detail": detail,
                "tag": "Hosted tour" if hosted_url else "Review",
            }
            if hosted_url:
                row["action_href"] = hosted_url
                row["action_method"] = "get"
                row["action_label"] = "Open 360"
            if review_url:
                if hosted_url:
                    row["secondary_action_href"] = review_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Review brief"
                else:
                    row["action_href"] = review_url
                    row["action_method"] = "get"
                    row["action_label"] = "Review brief"
            recent_matches.append(row)
            if len(recent_matches) >= 6:
                break
    except Exception:
        recent_matches = []
    try:
        preference_bundle = dict(
            product.get_preference_profile(
                principal_id=principal_id,
                person_id=preference_person_id,
            )
            or {}
        )
    except Exception:
        preference_bundle = {}
    try:
        learning_summary = dict(
            product.property_feedback_learning_summary(
                principal_id=principal_id,
                person_id=preference_person_id,
                domain="willhaben",
            )
            or {}
        )
    except Exception:
        learning_summary = {}

    return {
        "platform_options": country_provider_options,
        "platform_catalog_by_country": {
            str(option.get("value") or "").strip(): property_provider_options(country_code=str(option.get("value") or "").strip())
            for option in property_country_options()
        },
        "default_language_by_country": {
            str(option.get("value") or "").strip(): default_language_for_country(str(option.get("value") or "").strip())
            for option in property_country_options()
        },
        "country_options": property_country_options(),
        "language_options": property_language_options(),
        "listing_mode_options": property_listing_mode_options(),
        "investment_research_mode_options": property_investment_research_mode_options(),
        "property_type_options": property_type_options_catalog(),
        "country_label": property_country_label(selected_country),
        "language_label": property_language_label(preferences.get("language_code"), country_code=selected_country),
        "listing_mode_label": property_listing_mode_label(preferences.get("listing_mode")),
        "investment_research_mode_label": property_investment_research_mode_label(preferences.get("investment_research_mode")),
        "property_type_label": property_type_label_for_value(preferences.get("property_type")),
        "provider_total_for_country": len(country_provider_options),
        "preferences": preferences,
        "selected_platforms": list(selected_platforms),
        "run": run_payload,
        "recent_matches": recent_matches,
        "learning_summary": learning_summary,
        "preference_bundle": preference_bundle,
        "preference_person_id": preference_person_id,
        "start_endpoint": "/app/api/signals/property/search/run",
        "preferences_endpoint": "/v1/onboarding/property-search/preferences",
        "commercial": commercial,
        "billing_checkout_provider": ("payfunnels" if payfunnels_plus else ("paypal" if paypal_enabled else "")),
        "billing_checkout_provider_label": ("PayFunnels" if payfunnels_plus else ("PayPal" if paypal_enabled else "")),
        "billing_checkout_enabled": bool(payfunnels_plus or paypal_enabled),
        "billing_checkout_enabled_plans": (
            ["plus"]
            if payfunnels_plus
            else (["plus", "agent"] if paypal_enabled else [])
        ),
        "billing_order_endpoint": (
            "/app/api/signals/property/billing/payfunnels/order"
            if payfunnels_plus
            else "/app/api/signals/property/billing/paypal/order"
        ),
    }
