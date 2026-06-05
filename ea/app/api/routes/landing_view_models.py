from __future__ import annotations

import hashlib
from typing import Any


def _csv_values(value: object) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for raw in str(value or "").split(","):
        normalized = str(raw or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(normalized)
    return values


def _merge_option_catalog(
    base: list[dict[str, str]],
    selected_values: list[str],
) -> list[dict[str, str]]:
    values = {str(item.get("value") or "").strip().lower() for item in base if str(item.get("value") or "").strip()}
    merged = list(base)
    for value in selected_values:
        normalized = str(value or "").strip()
        if not normalized or normalized.lower() in values:
            continue
        merged.append({"value": normalized, "label": normalized, "detail": "Saved preference"})
        values.add(normalized.lower())
    return merged


def _property_preference_schema() -> dict[str, object]:
    from app.api.routes.product_api_contracts import _PROPERTY_PREFERENCE_VALUE_SPECS

    category_labels = {
        "constraint": "Hard rule",
        "soft_preference": "Preference",
        "aversion": "Avoid",
    }
    value_hints = {
        "bool": "Leave empty for yes, or enter true/false.",
        "positive_number": "Enter a number.",
        "text_list": "Enter comma-separated values.",
    }
    categories: dict[str, dict[str, object]] = {}
    for category, key in sorted(_PROPERTY_PREFERENCE_VALUE_SPECS):
        value_kind = str(_PROPERTY_PREFERENCE_VALUE_SPECS[(category, key)])
        bucket = categories.setdefault(
            category,
            {
                "label": category_labels.get(category, category.replace("_", " ").title()),
                "keys": [],
            },
        )
        bucket["keys"].append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "value_kind": value_kind,
                "hint": value_hints.get(value_kind, "Enter a value."),
            }
        )
    return {"categories": categories}


def _property_region_options(country_code: str) -> list[dict[str, str]]:
    catalogs: dict[str, list[dict[str, str]]] = {
        "AT": [
            {"value": "vienna", "label": "Vienna", "detail": "Wien and the close commuter ring"},
            {"value": "lower_austria", "label": "Lower Austria", "detail": "St. Poelten, Baden, Krems, Wiener Neustadt"},
            {"value": "upper_austria", "label": "Upper Austria", "detail": "Linz, Wels, Steyr"},
            {"value": "styria", "label": "Styria", "detail": "Graz and the southern corridor"},
            {"value": "salzburg", "label": "Salzburg", "detail": "City and surroundings"},
            {"value": "tyrol", "label": "Tyrol", "detail": "Innsbruck and Tyrolean centres"},
            {"value": "vorarlberg", "label": "Vorarlberg", "detail": "Bregenz, Dornbirn, Feldkirch"},
            {"value": "carinthia", "label": "Carinthia", "detail": "Klagenfurt and Villach"},
            {"value": "burgenland", "label": "Burgenland", "detail": "Eisenstadt and the eastern commuter belt"},
        ],
    }
    return list(catalogs.get(str(country_code or "").strip().upper(), []))


def _property_location_options(country_code: str, region_code: str = "") -> list[dict[str, str]]:
    austria_catalogs: dict[str, list[dict[str, str]]] = {
        "vienna": [
            {"value": "1010 Vienna", "label": "1010 Vienna", "detail": "Innere Stadt"},
            {"value": "1020 Vienna", "label": "1020 Vienna", "detail": "Leopoldstadt"},
            {"value": "1030 Vienna", "label": "1030 Vienna", "detail": "Landstrasse"},
            {"value": "1040 Vienna", "label": "1040 Vienna", "detail": "Wieden"},
            {"value": "1050 Vienna", "label": "1050 Vienna", "detail": "Margareten"},
            {"value": "1060 Vienna", "label": "1060 Vienna", "detail": "Mariahilf"},
            {"value": "1070 Vienna", "label": "1070 Vienna", "detail": "Neubau"},
            {"value": "1080 Vienna", "label": "1080 Vienna", "detail": "Josefstadt"},
            {"value": "1090 Vienna", "label": "1090 Vienna", "detail": "Alsergrund"},
            {"value": "1120 Vienna", "label": "1120 Vienna", "detail": "Meidling"},
            {"value": "1180 Vienna", "label": "1180 Vienna", "detail": "Waehring"},
            {"value": "1190 Vienna", "label": "1190 Vienna", "detail": "Doebling"},
            {"value": "1200 Vienna", "label": "1200 Vienna", "detail": "Brigittenau"},
            {"value": "1210 Vienna", "label": "1210 Vienna", "detail": "Floridsdorf"},
            {"value": "1220 Vienna", "label": "1220 Vienna", "detail": "Donaustadt"},
            {"value": "1230 Vienna", "label": "1230 Vienna", "detail": "Liesing"},
            {"value": "Klosterneuburg", "label": "Klosterneuburg", "detail": "Vienna outskirts"},
            {"value": "Mödling", "label": "Mödling", "detail": "South of Vienna"},
            {"value": "Purkersdorf", "label": "Purkersdorf", "detail": "West of Vienna"},
        ],
        "lower_austria": [
            {"value": "St. Poelten", "label": "St. Poelten", "detail": "Capital of Lower Austria"},
            {"value": "Krems", "label": "Krems", "detail": "Wachau corridor"},
            {"value": "Baden", "label": "Baden", "detail": "South of Vienna"},
            {"value": "Wiener Neustadt", "label": "Wiener Neustadt", "detail": "Southern rail corridor"},
            {"value": "Tulln", "label": "Tulln", "detail": "North-west of Vienna"},
        ],
        "upper_austria": [
            {"value": "Linz", "label": "Linz", "detail": "Capital of Upper Austria"},
            {"value": "Wels", "label": "Wels", "detail": "Central Upper Austria"},
            {"value": "Steyr", "label": "Steyr", "detail": "Industrial corridor"},
        ],
        "styria": [
            {"value": "Graz", "label": "Graz", "detail": "Capital of Styria"},
            {"value": "Leoben", "label": "Leoben", "detail": "Upper Styrian centre"},
            {"value": "Kapfenberg", "label": "Kapfenberg", "detail": "North of Graz corridor"},
        ],
        "salzburg": [
            {"value": "Salzburg", "label": "Salzburg", "detail": "City-wide"},
            {"value": "Hallein", "label": "Hallein", "detail": "South of Salzburg"},
        ],
        "tyrol": [
            {"value": "Innsbruck", "label": "Innsbruck", "detail": "City-wide"},
            {"value": "Hall in Tirol", "label": "Hall in Tirol", "detail": "East of Innsbruck"},
        ],
        "vorarlberg": [
            {"value": "Dornbirn", "label": "Dornbirn", "detail": "Rheintal centre"},
            {"value": "Bregenz", "label": "Bregenz", "detail": "Lake Constance"},
            {"value": "Feldkirch", "label": "Feldkirch", "detail": "Southern Vorarlberg"},
        ],
        "carinthia": [
            {"value": "Klagenfurt", "label": "Klagenfurt", "detail": "Capital of Carinthia"},
            {"value": "Villach", "label": "Villach", "detail": "West Carinthia"},
        ],
        "burgenland": [
            {"value": "Eisenstadt", "label": "Eisenstadt", "detail": "Capital of Burgenland"},
            {"value": "Neusiedl am See", "label": "Neusiedl am See", "detail": "North Burgenland"},
        ],
    }
    catalogs: dict[str, list[dict[str, str]]] = {
        "AT": list(austria_catalogs.get(str(region_code or "").strip().lower() or "vienna", austria_catalogs["vienna"])),
        "DE": [
            {"value": "Berlin Mitte", "label": "Berlin Mitte", "detail": "Central Berlin"},
            {"value": "Berlin Prenzlauer Berg", "label": "Berlin Prenzlauer Berg", "detail": "Family-friendly"},
            {"value": "Berlin Charlottenburg", "label": "Berlin Charlottenburg", "detail": "West Berlin"},
            {"value": "Munich", "label": "Munich", "detail": "City-wide"},
            {"value": "Hamburg", "label": "Hamburg", "detail": "City-wide"},
        ],
        "ES": [
            {"value": "Barcelona", "label": "Barcelona", "detail": "City-wide"},
            {"value": "Eixample", "label": "Eixample", "detail": "Central Barcelona"},
            {"value": "Madrid", "label": "Madrid", "detail": "City-wide"},
            {"value": "Valencia", "label": "Valencia", "detail": "City-wide"},
        ],
        "IT": [
            {"value": "Milan", "label": "Milan", "detail": "City-wide"},
            {"value": "Rome", "label": "Rome", "detail": "City-wide"},
            {"value": "Bologna", "label": "Bologna", "detail": "City-wide"},
        ],
        "FR": [
            {"value": "Paris", "label": "Paris", "detail": "City-wide"},
            {"value": "Lyon", "label": "Lyon", "detail": "City-wide"},
            {"value": "Marseille", "label": "Marseille", "detail": "City-wide"},
        ],
        "NL": [
            {"value": "Amsterdam", "label": "Amsterdam", "detail": "City-wide"},
            {"value": "Rotterdam", "label": "Rotterdam", "detail": "City-wide"},
            {"value": "Utrecht", "label": "Utrecht", "detail": "City-wide"},
        ],
        "UK": [
            {"value": "London", "label": "London", "detail": "City-wide"},
            {"value": "Manchester", "label": "Manchester", "detail": "City-wide"},
            {"value": "Bristol", "label": "Bristol", "detail": "City-wide"},
        ],
        "US": [
            {"value": "Brooklyn", "label": "Brooklyn", "detail": "New York City"},
            {"value": "Queens", "label": "Queens", "detail": "New York City"},
            {"value": "Jersey City", "label": "Jersey City", "detail": "New Jersey"},
            {"value": "San Francisco", "label": "San Francisco", "detail": "Bay Area"},
            {"value": "Boston", "label": "Boston", "detail": "City-wide"},
        ],
    }
    normalized_country = str(country_code or "").strip().upper()
    if normalized_country == "GB":
        normalized_country = "UK"
    return list(catalogs.get(normalized_country, []))


def _property_keyword_options() -> list[dict[str, str]]:
    return [
        {"value": "lift", "label": "Lift", "detail": "Elevator in the building"},
        {"value": "balcony", "label": "Balcony", "detail": "Outdoor private space"},
        {"value": "terrace", "label": "Terrace", "detail": "Large outdoor space"},
        {"value": "family", "label": "Family-friendly", "detail": "Good fit for children"},
        {"value": "playground nearby", "label": "Playground nearby", "detail": "Walkable play options"},
        {"value": "supermarket nearby", "label": "Supermarket nearby", "detail": "Daily errands close by"},
        {"value": "pharmacy nearby", "label": "Pharmacy nearby", "detail": "Healthcare basics nearby"},
        {"value": "underground nearby", "label": "Underground nearby", "detail": "Fast transit access"},
        {"value": "no gas", "label": "No gas heating", "detail": "Avoid gas-based systems"},
        {"value": "district heating", "label": "District heating", "detail": "Prefer Fernwärme"},
        {"value": "parking", "label": "Parking", "detail": "Car-friendly"},
        {"value": "pets allowed", "label": "Pets allowed", "detail": "Pet-friendly rules"},
        {"value": "quiet", "label": "Quiet", "detail": "Lower street noise"},
        {"value": "bright", "label": "Bright", "detail": "Good natural light"},
    ]


def humanize(value: str) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"


def status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "ready_to_connect", "ready_for_brief", "completed", "started", "available"}:
        return "good"
    if normalized in {"planned_business", "export_planned", "guided_manual", "bot_link_requested", "export_intake_complete", "import_acknowledged", "in_progress"}:
        return "warn"
    if normalized in {"credentials_missing", "planned_not_available", "not_selected", "anonymous"}:
        return "muted"
    return "muted"


def list_rows(values: object, fallback: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    if isinstance(values, (list, tuple, set)):
        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                rows.append(normalized)
    elif values:
        normalized = str(values).strip()
        if normalized:
            rows.append(normalized)
    return rows or [str(row) for row in fallback]


def row_item(title: str, detail: str, tag: str) -> dict[str, str]:
    return {"title": title, "detail": detail, "tag": tag}


def string_rows(values: object, fallback: tuple[str, ...], *, tag: str, detail: str) -> list[dict[str, str]]:
    return [row_item(value, detail, tag) for value in list_rows(values, fallback)]


def _compact_when(value: str | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback
    if "T" in normalized:
        return normalized.split("T", 1)[0]
    return normalized


def _property_candidate_ref(candidate: dict[str, object]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "tour_url", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def approval_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        reason = str(getattr(value, "reason", "") or "").strip()
        action_json = dict(getattr(value, "requested_action_json", {}) or {})
        action_name = humanize(str(action_json.get("action") or action_json.get("event_type") or "review"))
        title = reason or f"{action_name.capitalize()} needs approval"
        detail = " · ".join(
            part
            for part in (
                "Pending approval",
                action_name if action_name and action_name != "review" else "",
                f"Expires {_compact_when(getattr(value, 'expires_at', None), 'soon')}"
                if getattr(value, "expires_at", None)
                else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Pending approval", "Approval"))
    return rows


def human_task_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        raw_title = str(getattr(value, "brief", "") or "").strip()
        task_type = str(getattr(value, "task_type", "") or "follow_up")
        fallback_title = "Commitment" if task_type == "follow_up" else humanize(task_type).capitalize()
        title = raw_title or fallback_title
        priority = humanize(str(getattr(value, "priority", "") or "open"))
        role_required = humanize(str(getattr(value, "role_required", "") or "review"))
        why_human = str(getattr(value, "why_human", "") or "").strip()
        due_label = _compact_when(getattr(value, "sla_due_at", None), "")
        detail = " · ".join(
            part
            for part in (
                f"{priority.capitalize()} priority" if priority else "",
                role_required if role_required and role_required != "review" else "",
                f"Due {due_label}" if due_label else "",
                why_human if why_human else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Waiting on human review", "Task"))
    return rows


def delivery_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        recipient = str(getattr(value, "recipient", "") or "").strip()
        channel = humanize(str(getattr(value, "channel", "") or "delivery")).capitalize()
        title = recipient or f"{channel} delivery"
        attempt_count = int(getattr(value, "attempt_count", 0) or 0)
        next_attempt_at = _compact_when(getattr(value, "next_attempt_at", None), "")
        last_error = str(getattr(value, "last_error", "") or "").strip()
        detail = " · ".join(
            part
            for part in (
                channel,
                f"Attempt {attempt_count + 1}",
                f"Retry {next_attempt_at}" if next_attempt_at else "",
                last_error[:80] if last_error else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Queued for delivery", "Queued"))
    return rows


def channel_cards(channels: dict[str, Any]) -> list[dict[str, str]]:
    ordered = (
        ("google", "Google sign-in", "/integrations/google"),
        ("telegram", "Telegram", "/integrations/telegram"),
        ("whatsapp", "WhatsApp", "/integrations/whatsapp"),
    )
    cards: list[dict[str, str]] = []
    for key, label, href in ordered:
        channel = dict(channels.get(key) or {})
        cards.append(
            {
                "label": label,
                "href": href,
                "status": humanize(str(channel.get("status") or "not_selected")),
                "tone": status_tone(str(channel.get("status") or "not_selected")),
                "detail": str(channel.get("detail") or "Not configured yet."),
                "summary": str(channel.get("bundle_summary") or channel.get("history_import_posture") or ""),
            }
        )
    return cards


def app_section_payload(
    section: str,
    status: dict[str, object],
    *,
    live_feed: dict[str, object] | None = None,
    property_context: dict[str, object] | None = None,
) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    delivery_preferences = dict(status.get("delivery_preferences") or {})
    morning_memo = dict(delivery_preferences.get("morning_memo") or {})
    preview = dict(status.get("brief_preview") or {})
    channels = dict(status.get("channels") or {})
    cards = channel_cards(channels)
    selected = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    live = dict(live_feed or {})
    approvals = list(live.get("approvals") or [])
    human_tasks = list(live.get("human_tasks") or [])
    pending_delivery = list(live.get("pending_delivery") or [])
    status_label = humanize(str(status.get("status") or "draft"))
    ready_channels = sum(1 for card in cards if card["tone"] == "good")
    selected_count = len(selected) or len([card for card in cards if card["status"] != "not selected"]) or 0
    stats = [
        {"label": "Approvals", "value": str(len(approvals))},
        {"label": "Human tasks", "value": str(len(human_tasks))},
        {"label": "Queued delivery", "value": str(len(pending_delivery))},
        {
            "label": "Channels ready",
            "value": f"{ready_channels}/{selected_count}" if selected_count else str(ready_channels),
        },
    ]
    first_brief = list_rows(
        preview.get("first_brief_preview") or preview.get("first_brief"),
        ("Connect Google sign-in if you want a faster return path and verified account access.",),
    )
    suggested = list_rows(preview.get("suggested_actions"), ("Finish onboarding and request the first memo.",))
    trust_notes = list_rows(preview.get("trust_notes"), ("Keep approvals and retention rules explicit.",))
    people = list_rows(preview.get("top_contacts"), ("No people surfaced yet.",))
    themes = list_rows(preview.get("top_themes"), ("No themes surfaced yet.",))
    approvals_items = approval_rows(approvals)
    human_task_items = human_task_rows(human_tasks)
    pending_delivery_items = delivery_rows(pending_delivery)
    live_queue = (approvals_items + human_task_items)[:6]
    privacy_lines = [
        f"Retention: {humanize(str(privacy.get('retention_mode') or 'not set'))}",
        f"Drafts: {'allowed' if privacy.get('allow_drafts') else 'manual only'}",
        f"Action suggestions: {'allowed' if privacy.get('allow_action_suggestions') else 'off'}",
        f"Automatic briefs: {'allowed' if privacy.get('allow_auto_briefs') else 'off'}",
    ]
    if privacy.get("allow_auto_briefs"):
        privacy_lines.append(
            "Memo schedule: "
            + " · ".join(
                part
                for part in (
                    humanize(str(morning_memo.get("cadence") or "daily_morning")),
                    f"{morning_memo.get('delivery_time_local') or '08:00'} {morning_memo.get('timezone') or workspace.get('timezone') or 'UTC'}",
                    str(morning_memo.get("resolved_recipient_email") or "waiting for recipient"),
                )
                if str(part or "").strip()
            )
        )
    channel_lines = [f"{card['label']}: {card['status']} — {card['detail']}" for card in cards]
    channel_items = [row_item(card["label"], card["detail"], card["status"]) for card in cards]
    identity_posture_items = [
        row_item(
            "Keep identity boring",
            "Return through a secure email link, invite, or SSO before widening channel setup.",
            "Recommended",
        ),
        row_item(
            "Connect Google for workspace context",
            "Treat Google as optional account access first; only widen scopes later if the product truly needs them.",
            "Linked",
        ),
        row_item(
            "Link messaging channels later",
            "Treat Telegram and WhatsApp as optional linked channels, not the workspace core.",
            "Linked",
        ),
        row_item(
            "Keep work bounded",
            "Approvals, human tasks, and queued delivery stay explicit instead of hiding behind automation copy.",
            "Guardrail",
        ),
    ]
    follow_up_context_items = [
        row_item(title, "Keep the underlying promise, thread, or deadline attached to the work item.", "Context")
        for title in trust_notes
    ]
    property_state = dict(property_context or {})
    property_preferences = dict(property_state.get("preferences") or {})
    property_run = dict(property_state.get("run") or {})
    property_summary = dict(property_run.get("summary") or {})
    property_country_label = str(property_state.get("country_label") or "Austria")
    property_language_label = str(property_state.get("language_label") or "Deutsch")
    property_listing_mode_label = str(property_state.get("listing_mode_label") or "Rent")
    property_investment_research_mode_label = str(property_state.get("investment_research_mode_label") or "Off")
    property_type_label = str(property_state.get("property_type_label") or "Any type")
    property_provider_total_for_country = int(property_state.get("provider_total_for_country") or 0)
    selected_location_values = _csv_values(property_preferences.get("location_query"))
    selected_keyword_values = _csv_values(property_preferences.get("keywords"))
    selected_region_code = str(property_preferences.get("region_code") or "").strip().lower()
    selected_all_of_vienna = bool(property_preferences.get("all_of_vienna"))
    country_options = [dict(option) for option in list(property_state.get("country_options") or []) if isinstance(option, dict)]
    language_options = [dict(option) for option in list(property_state.get("language_options") or []) if isinstance(option, dict)]
    listing_mode_options = [dict(option) for option in list(property_state.get("listing_mode_options") or []) if isinstance(option, dict)]
    investment_research_mode_options = [dict(option) for option in list(property_state.get("investment_research_mode_options") or []) if isinstance(option, dict)]
    property_type_options = [dict(option) for option in list(property_state.get("property_type_options") or []) if isinstance(option, dict)]
    selected_platforms = {
        str(value or "").strip()
        for value in (property_state.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    platform_options = [
        dict(option)
        for option in list(property_state.get("platform_options") or [])
        if isinstance(option, dict)
    ]
    region_options = _property_region_options(str(property_preferences.get("country_code") or "AT"))
    if not selected_region_code and region_options:
        selected_region_code = str(region_options[0].get("value") or "").strip().lower()
    if (
        str(property_preferences.get("country_code") or "AT").strip().upper() == "AT"
        and selected_region_code == "vienna"
        and not selected_location_values
        and str(property_preferences.get("location_query") or "").strip().lower() in {"vienna", "wien"}
    ):
        selected_all_of_vienna = True
    location_options = _merge_option_catalog(
        _property_location_options(
            str(property_preferences.get("country_code") or "AT"),
            selected_region_code,
        ),
        selected_location_values,
    )
    keyword_options = _merge_option_catalog(_property_keyword_options(), selected_keyword_values)
    property_selected_platform_labels = [
        str(option.get("label") or option.get("value") or "").strip()
        for option in platform_options
        if str(option.get("value") or "").strip() in selected_platforms
    ]
    property_market_summary_items = [
        row_item("Country", property_country_label, "Market"),
        row_item("Research language", property_language_label, "Research"),
        row_item("Search mode", property_listing_mode_label, "Mode"),
        row_item("Investment research", property_investment_research_mode_label, "Underwriting"),
        row_item("Property type", property_type_label, "Type"),
    ]
    if str(property_preferences.get("location_query") or "").strip():
        property_market_summary_items.append(
            row_item("Location query", str(property_preferences.get("location_query") or "").strip(), "Target")
        )
    if str(property_preferences.get("keywords") or "").strip():
        property_market_summary_items.append(
            row_item("Research focus", str(property_preferences.get("keywords") or "").strip(), "Focus")
        )
    property_platform_rows = [
        row_item(
            str(option.get("label") or option.get("value") or "Platform"),
            "Included in the dedicated crawl lane." if str(option.get("value") or "").strip() in selected_platforms else "Available to add to the crawl lane.",
            "Selected" if str(option.get("value") or "").strip() in selected_platforms else "Available",
        )
        for option in platform_options
    ]
    property_recent_matches = [
        dict(item)
        for item in list(property_state.get("recent_matches") or [])
        if isinstance(item, dict)
    ]
    property_event_rows = [
        row_item(
            str(event.get("step") or "Update").replace("_", " ").capitalize(),
            str(event.get("message") or "No message").strip(),
            str(event.get("status") or "queued").replace("_", " "),
        )
        for event in list(property_run.get("events") or [])[-6:]
        if isinstance(event, dict)
    ]
    active_run_id = str(property_run.get("run_id") or "").strip()

    def _packet_url_for_candidate(candidate: dict[str, object], *, source_label: str) -> str:
        candidate_for_ref = dict(candidate)
        candidate_for_ref.setdefault("source_label", source_label)
        packet_ref = _property_candidate_ref(candidate_for_ref)
        packet_url = f"/app/research/{packet_ref}"
        if active_run_id:
            packet_url = f"{packet_url}?run_id={active_run_id}"
        return packet_url

    enriched_sources: list[dict[str, object]] = []
    for source in list(property_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_row = dict(source)
        source_label = str(source_row.get("source_label") or source_row.get("source_url") or "Source").strip()
        enriched_candidates: list[dict[str, object]] = []
        for candidate in list(source_row.get("top_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            candidate_row = dict(candidate)
            candidate_row.setdefault("source_label", source_label)
            if not str(candidate_row.get("packet_url") or "").strip():
                candidate_row["packet_url"] = _packet_url_for_candidate(candidate_row, source_label=source_label)
            enriched_candidates.append(candidate_row)
        source_row["top_candidates"] = enriched_candidates
        enriched_sources.append(source_row)
    if enriched_sources:
        property_summary["sources"] = enriched_sources
        property_run["summary"] = property_summary

    property_source_rows = [
        row_item(
            str(source.get("source_label") or source.get("source_url") or "Source").strip(),
            " | ".join(
                part
                for part in (
                    f"{int(source.get('listing_total') or 0)} listings",
                    f"{int(source.get('high_fit_total') or 0)} high-fit",
                    f"{int(source.get('filtered_floorplan_total') or 0)} without floor plan"
                    if int(source.get('filtered_floorplan_total') or 0)
                    else "",
                    f"{int(source.get('tour_created_total') or 0)} hosted tours",
                    f"{int(source.get('notified_total') or 0)} client alerts",
                    f"{int(source.get('email_notified_total') or 0)} email" if int(source.get('email_notified_total') or 0) else "",
                    f"top score {float(source.get('top_fit_score') or 0.0):.2f}" if source.get("top_fit_score") is not None else "",
                )
                if part
            ),
            "Scanned",
        )
        for source in list(property_summary.get("sources") or [])
        if isinstance(source, dict)
    ]
    property_shortlist_rows: list[dict[str, str]] = []
    property_shortlist_cards: list[dict[str, object]] = []
    for source in list(property_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for candidate in list(source.get("top_candidates") or [])[:5]:
            if not isinstance(candidate, dict):
                continue
            title = str(candidate.get("title") or candidate.get("property_url") or "Property candidate").strip() or "Property candidate"
            detail_parts = [
                str(candidate.get("fit_summary") or "").strip(),
                source_label,
            ]
            match_reasons = [
                str(item or "").strip()
                for item in list(candidate.get("match_reasons") or [])
                if str(item or "").strip()
            ]
            mismatch_reasons = [
                str(item or "").strip()
                for item in list(candidate.get("mismatch_reasons") or [])
                if str(item or "").strip()
            ]
            if match_reasons:
                detail_parts.append(f"Why it fits: {match_reasons[0]}")
            elif mismatch_reasons:
                detail_parts.append(f"Watch-out: {mismatch_reasons[0]}")
            row: dict[str, str] = {
                "title": title,
                "detail": " | ".join(part for part in detail_parts if part) or source_label,
                "tag": str(candidate.get("recommendation") or "candidate").replace("_", " ").title(),
            }
            review_url = str(candidate.get("review_url") or "").strip()
            tour_url = str(candidate.get("tour_url") or "").strip()
            property_url = str(candidate.get("property_url") or "").strip()
            packet_ref = _property_candidate_ref(
                {
                    "title": title,
                    "property_url": property_url,
                    "review_url": review_url,
                    "tour_url": tour_url,
                    "source_label": source_label,
                }
            )
            packet_url = f"/app/research/{packet_ref}"
            if active_run_id:
                packet_url = f"{packet_url}?run_id={active_run_id}"
            if review_url:
                row["action_href"] = packet_url
                row["action_method"] = "get"
                row["action_label"] = "Review packet"
                row["secondary_action_href"] = review_url
                row["secondary_action_method"] = "get"
                row["secondary_action_label"] = "Hosted review"
            else:
                row["action_href"] = packet_url
                row["action_method"] = "get"
                row["action_label"] = "Review packet"
            if tour_url:
                if row.get("secondary_action_href"):
                    row["tertiary_action_href"] = tour_url
                    row["tertiary_action_method"] = "get"
                    row["tertiary_action_label"] = "Open 360"
                elif row.get("action_href"):
                    row["secondary_action_href"] = tour_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Open 360"
                else:
                    row["action_href"] = tour_url
                    row["action_method"] = "get"
                    row["action_label"] = "Open 360"
            if property_url:
                if row.get("tertiary_action_href"):
                    row["quaternary_action_href"] = property_url
                    row["quaternary_action_method"] = "get"
                    row["quaternary_action_label"] = "Source"
                elif row.get("secondary_action_href"):
                    row["tertiary_action_href"] = property_url
                    row["tertiary_action_method"] = "get"
                    row["tertiary_action_label"] = "Source"
                elif row.get("action_href"):
                    row["secondary_action_href"] = property_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Source"
                else:
                    row["action_href"] = property_url
                    row["action_method"] = "get"
                    row["action_label"] = "Source"
            property_shortlist_rows.append(row)
            property_shortlist_cards.append(
                {
                    "title": title,
                    "source_label": source_label,
                    "detail": row["detail"],
                    "tag": row["tag"],
                    "fit_summary": str(candidate.get("fit_summary") or "").strip(),
                    "recommendation": str(candidate.get("recommendation") or "").strip(),
                    "property_url": property_url,
                    "packet_url": packet_url,
                    "review_url": review_url,
                    "tour_url": tour_url,
                    "match_reasons": match_reasons,
                    "mismatch_reasons": mismatch_reasons,
                    "property_facts": dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {},
                    "assessment": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                }
            )
    property_shortlist_rows.sort(
        key=lambda item: (
            "shortlist" not in str(item.get("tag") or "").lower(),
            "view if compelling" not in str(item.get("tag") or "").lower(),
            str(item.get("title") or ""),
        )
    )
    property_shortlist_rows = property_shortlist_rows[:8]
    property_shortlist_cards = property_shortlist_cards[:6]
    property_learning_summary = dict(property_state.get("learning_summary") or {})
    property_learning_rows = [
        row_item(entry, "Learned positive preference from explicit filters or listing feedback.", "Learnt")
        for entry in list(property_learning_summary.get("likes") or [])[:4]
        if str(entry or "").strip()
    ]
    property_learning_rows.extend(
        row_item(entry, "Negative preference that should suppress future shortlist candidates.", "Avoid")
        for entry in list(property_learning_summary.get("dislikes") or [])[:4]
        if str(entry or "").strip()
    )
    property_learning_rows.extend(
        row_item(entry, "Hard rule that should fail or demote mismatching listings.", "Rule")
        for entry in list(property_learning_summary.get("hard_rules") or [])[:3]
        if str(entry or "").strip()
    )
    property_recent_feedback_rows = [
        row_item(
            str(entry.get("reaction") or "feedback").strip().title(),
            " | ".join(
                part
                for part in (
                    ", ".join(str(item or "").strip() for item in list(entry.get("reasons") or [])[:3] if str(item or "").strip()),
                    str(entry.get("note") or "").strip(),
                    str(entry.get("recorded_at") or "").strip()[:10],
                )
                if part
            )
            or "Structured feedback recorded.",
            "Feedback",
        )
        for entry in list(property_learning_summary.get("recent_feedback") or [])[:4]
        if isinstance(entry, dict)
    ]
    try:
        property_plan_max_results = max(1, int(property_state.get("commercial", {}).get("max_results_per_source") or 2))
    except Exception:
        property_plan_max_results = 2
    try:
        property_plan_max_match_score = max(1, min(100, int(property_state.get("commercial", {}).get("max_match_score") or 45)))
    except Exception:
        property_plan_max_match_score = 45
    property_visible_max_match_score = 80
    property_visible_max_results_per_source = 10
    selected_listing_mode = str(property_preferences.get("listing_mode") or "rent").strip().lower() or "rent"

    def _positive_int(value: object, *, default: int = 0) -> int:
        try:
            parsed = int(float(str(value or "").strip()))
        except Exception:
            return default
        return max(0, parsed)

    def _eur_short(value: int) -> str:
        if value >= 1_000_000:
            return f"EUR {value // 1_000_000}M"
        if value >= 1_000:
            return f"EUR {value // 1_000}k"
        return f"EUR {value}"

    property_price_value = _positive_int(property_preferences.get("max_price_eur"))
    property_price_range_presets = {
        "rent": {"max": 6000, "step": 100, "scaleMaxLabel": "EUR 6k"},
        "buy": {"max": 2_000_000, "step": 25_000, "scaleMaxLabel": "EUR 2M"},
        "any": {"max": 2_000_000, "step": 25_000, "scaleMaxLabel": "EUR 2M"},
    }
    property_price_preset = property_price_range_presets.get(selected_listing_mode) or property_price_range_presets["rent"]
    property_price_slider_max = max(int(property_price_preset["max"]), property_price_value)
    property_price_slider_step = int(property_price_preset["step"])
    property_min_rooms_value = min(8, _positive_int(property_preferences.get("min_rooms")))
    property_min_area_value = min(250, _positive_int(property_preferences.get("min_area_m2")))
    try:
        property_results_value = int(property_preferences.get("max_results_per_source") or property_plan_max_results)
    except Exception:
        property_results_value = property_plan_max_results
    property_results_value = max(1, min(property_results_value, property_plan_max_results))
    try:
        property_min_match_score_value = int(property_preferences.get("min_match_score") or min(65, property_plan_max_match_score))
    except Exception:
        property_min_match_score_value = min(65, property_plan_max_match_score)
    property_min_match_score_value = max(1, min(property_min_match_score_value, property_plan_max_match_score))
    property_min_match_tooltip = (
        "Minimum personal fit score a listing must beat before it can enter the shortlist. "
        "Raising it usually improves precision, but can make searches much slower and increases backend crawl and scoring load."
    )
    property_min_match_upgrade_hint = (
        f"Current plan cap {property_plan_max_match_score}; Agent unlocks {property_visible_max_match_score}."
        if property_plan_max_match_score < property_visible_max_match_score
        else ""
    )
    profile_manage_href = f"/app/profile?run_id={active_run_id}" if active_run_id else "/app/profile"
    property_form = {
        "variant": "property_search",
        "title": "Run a premium market sweep",
        "eyebrow": "Flagship property desk",
        "copy": "Set the market, shape the shortlist, choose the providers, then launch one visible research run with ranking, hosted review pages, and client-ready alerts.",
        "submit_label": "Launch search",
        "fields": [
            {
                "type": "select",
                "name": "country_code",
                "label": "Country",
                "value": str(property_preferences.get("country_code") or "AT"),
                "options": country_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "language_code",
                "label": "Research language",
                "value": str(property_preferences.get("language_code") or "de"),
                "options": language_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "listing_mode",
                "label": "Search mode",
                "value": selected_listing_mode,
                "options": listing_mode_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "property_type",
                "label": "Property type",
                "value": str(property_preferences.get("property_type") or "any"),
                "options": property_type_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "investment_research_mode",
                "label": "Investment research",
                "value": str(property_preferences.get("investment_research_mode") or "off"),
                "options": investment_research_mode_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "region_code",
                "label": "State or metro area",
                "value": selected_region_code,
                "options": region_options,
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "all_of_vienna",
                "label": "All of Vienna",
                "value": "true",
                "checked": selected_all_of_vienna,
                "step": "areas",
            },
            {
                "type": "checkbox_group",
                "name": "location_query",
                "label": "Target areas",
                "options": location_options,
                "values": selected_location_values,
                "hidden": selected_all_of_vienna
                and str(property_preferences.get("country_code") or "AT").strip().upper() == "AT"
                and selected_region_code == "vienna",
                "step": "areas",
            },
            {
                "type": "checkbox_group",
                "name": "selected_platforms",
                "label": "Platforms",
                "options": platform_options,
                "values": list(selected_platforms),
                "step": "providers",
            },
            {
                "type": "checkbox_group",
                "name": "keywords",
                "label": "What matters",
                "options": keyword_options,
                "values": selected_keyword_values,
                "step": "areas",
            },
            {
                "type": "text",
                "name": "preference_person_id",
                "label": "Preference profile",
                "value": str(property_preferences.get("preference_person_id") or "self"),
                "placeholder": "self",
                "manage_href": profile_manage_href,
                "manage_label": "Manage feedback preferences",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "use_stored_feedback_preferences",
                "label": "Use stored feedback preferences",
                "value": "true",
                "checked": bool(property_preferences.get("use_stored_feedback_preferences", True)),
                "manage_href": profile_manage_href,
                "manage_label": "Manage",
                "step": "areas",
            },
            {
                "type": "range",
                "name": "max_price_eur",
                "label": "Max budget",
                "value": str(property_price_value),
                "min": "0",
                "max": str(property_price_slider_max),
                "visual_max": str(property_price_slider_max),
                "range_step": str(property_price_slider_step),
                "format": "currency_eur",
                "empty_label": "Any budget",
                "scale_min_label": "No max",
                "scale_max_label": _eur_short(property_price_slider_max),
                "tooltip": "Set a hard budget ceiling. Leave it at Any budget when you want PropertyQuarry to rank first and filter price later.",
                "range_preset": "listing_mode_price",
                "range_presets": property_price_range_presets,
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_rooms",
                "label": "Min rooms",
                "value": str(property_min_rooms_value),
                "min": "0",
                "max": "8",
                "visual_max": "8",
                "range_step": "1",
                "format": "rooms",
                "empty_label": "Any rooms",
                "scale_min_label": "Any",
                "scale_max_label": "8+ rooms",
                "tooltip": "Minimum room count. Keep this open when layout quality matters more than the advertised room number.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_area_m2",
                "label": "Min area",
                "value": str(property_min_area_value),
                "min": "0",
                "max": "250",
                "visual_max": "250",
                "range_step": "5",
                "format": "area_m2",
                "empty_label": "Any size",
                "scale_min_label": "Any",
                "scale_max_label": "250+ m2",
                "tooltip": "Minimum usable area. Larger minimums reduce weak matches but can make the crawl skip sparse auction or cooperative listings.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "max_results_per_source",
                "label": "Max results per source",
                "value": str(property_results_value),
                "min": "1",
                "max": str(property_visible_max_results_per_source),
                "selectable_max": str(property_plan_max_results),
                "visual_max": str(property_visible_max_results_per_source),
                "range_step": "1",
                "format": "count",
                "suffix": "",
                "upgrade_hint": (
                    f"Current plan cap {property_plan_max_results}; Agent unlocks {property_visible_max_results_per_source}."
                    if property_plan_max_results < property_visible_max_results_per_source
                    else ""
                ),
                "tooltip": "How many strong matches each provider may return. Higher values increase review depth and processing work.",
                "step": "providers",
            },
            {
                "type": "range",
                "name": "min_match_score",
                "label": "Match score",
                "value": str(property_min_match_score_value),
                "min": "1",
                "max": str(property_visible_max_match_score),
                "selectable_max": str(property_plan_max_match_score),
                "visual_max": str(property_visible_max_match_score),
                "range_step": "1",
                "suffix": f"/{property_visible_max_match_score}",
                "upgrade_hint": property_min_match_upgrade_hint,
                "tooltip": property_min_match_tooltip,
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "require_floorplan",
                "label": "Serious listings only - floor plan required",
                "value": "true",
                "checked": bool(property_preferences.get("require_floorplan")),
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "force_refresh",
                "label": "Force fresh crawl",
                "value": "true",
                "checked": bool(property_preferences.get("force_refresh")),
                "step": "providers",
            },
        ],
        "meta": {
            "preferences_endpoint": str(property_state.get("preferences_endpoint") or ""),
            "start_endpoint": str(property_state.get("start_endpoint") or ""),
            "run_id": str(property_run.get("run_id") or ""),
            "initial_run": property_run,
            "platform_catalog_by_country": dict(property_state.get("platform_catalog_by_country") or {}),
            "default_language_by_country": dict(property_state.get("default_language_by_country") or {}),
            "region_catalog_by_country": {
                option.get("value"): _property_region_options(str(option.get("value") or ""))
                for option in country_options
                if str(option.get("value") or "").strip()
            },
            "location_catalog_by_country_region": {
                str(option.get("value") or ""): {
                    str(region.get("value") or ""): _property_location_options(str(option.get("value") or ""), str(region.get("value") or ""))
                    for region in _property_region_options(str(option.get("value") or ""))
                }
                for option in country_options
                if str(option.get("value") or "").strip()
            },
            "supports_all_of_vienna": True,
            "commercial": dict(property_state.get("commercial") or {}),
            "billing_checkout_enabled": bool(property_state.get("billing_checkout_enabled")),
            "billing_checkout_enabled_plans": list(property_state.get("billing_checkout_enabled_plans") or []),
            "billing_checkout_provider": str(property_state.get("billing_checkout_provider") or ""),
            "billing_checkout_provider_label": str(property_state.get("billing_checkout_provider_label") or ""),
            "billing_order_endpoint": str(property_state.get("billing_order_endpoint") or ""),
            "feedback_person_id": str(property_preferences.get("preference_person_id") or "self"),
            "shortlist_candidates": property_shortlist_cards,
            "wizard_steps": [
                {
                    "key": "search",
                    "label": "Search posture",
                    "detail": "Choose the market, the buying posture, and the guardrails before the crawl fans out.",
                },
                {
                    "key": "areas",
                    "label": "Areas and priorities",
                    "detail": "Select the districts and the property traits that should actually drive the ranking.",
                },
                {
                    "key": "providers",
                    "label": "Providers and launch",
                    "detail": "Pick the portals, confirm the run cap, then save or launch the visible crawl.",
                },
            ],
        },
    }

    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": str(
                preview.get("headline")
                or status.get("next_step")
                or "Start with the operating memo, clear the decision queue, and keep commitments from drifting."
            ),
            "cards": [
                {
                    "eyebrow": "Live queue",
                    "title": "What needs action now",
                    "body": "The day opens on real approvals and human tasks instead of a motivational dashboard.",
                    "items": live_queue
                    or string_rows(
                        first_brief,
                        ("Connect Google sign-in if you want easier return access from the same account.",),
                        tag="Next",
                        detail="This is the shortest path to a real working day.",
                    ),
                },
                {
                    "eyebrow": "Outbound work",
                    "title": "What is queued to leave the office loop",
                    "body": "Pending delivery stays visible so drafts, approvals, and sends never blur together.",
                    "items": pending_delivery_items
                    or string_rows(
                        suggested,
                        ("No queued delivery yet.",),
                        tag="Review",
                        detail="Once a draft or action is ready, it will show up here.",
                    ),
                },
                {
                    "eyebrow": "Brief signal",
                    "title": "What is shaping the day",
                    "body": "The memo stays narrative, but it still points at work that exists.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="Use the memo to set the order of operations."),
                },
                {
                    "eyebrow": "Identity and channels",
                    "title": "Keep setup boring and useful",
                    "body": "Identity stays simple. Channels widen coverage only after the first loop works.",
                    "items": identity_posture_items,
                },
            ],
        },
        "queue": {
            "title": "Decision Queue",
            "summary": str(preview.get("headline") or "Turn the day into decisions: approve, assign, defer, or close."),
            "cards": [
                {
                    "eyebrow": "Decision pressure",
                    "title": "What changed",
                    "body": "The queue explains what changed, why it matters, and what decision belongs next.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="This is the current ranked memo item."),
                },
                {
                    "eyebrow": "Themes",
                    "title": "Recurring topics",
                    "body": "Themes help the user understand the day without reopening every thread.",
                    "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="This theme is active in the current workspace."),
                },
                {
                    "eyebrow": "Live queue",
                    "title": "What the queue clears",
                    "body": "A useful queue terminates in real approvals, assignments, or outbound actions.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live review items yet.",),
                        tag="Queue",
                        detail="Once the office loop starts moving, the memo points here.",
                    ),
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "People affected by the queue",
                    "body": "Stakeholders only matter if they stay attached to the decisions and commitments in front of the team.",
                    "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="This person is active in the current memo."),
                },
            ],
        },
        "commitments": {
            "title": "Commitments",
            "summary": "Messages, meetings, and notes only matter when they update a commitment, create a decision, or close a loop.",
            "cards": [
                {
                    "eyebrow": "Commitment pressure",
                    "title": "What is in motion",
                    "body": "This surface shows which commitments are active, which decisions are waiting, and which drafts are holding things up.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live commitment queue yet.",),
                        tag="Draft",
                        detail="Once drafts or approvals exist, they will appear here.",
                    ),
                },
                {
                    "eyebrow": "Queued delivery",
                    "title": "What is waiting to leave",
                    "body": "Outbound work is part of the commitment loop, not hidden afterthought state.",
                    "items": pending_delivery_items
                    or string_rows(
                        channel_lines,
                        ("No delivery queue yet.",),
                        tag="Ready",
                        detail="Connected channels determine what the queue can actually move.",
                    ),
                },
                {
                    "eyebrow": "Decision pressure",
                    "title": "What will bubble up next",
                    "body": "The commitment ledger gets its order from pressure and deadlines, not from unread-count theater.",
                    "items": string_rows(first_brief, ("No priorities surfaced yet.",), tag="Memo", detail="This is the current upstream signal for the commitment queue."),
                },
            ],
        },
        "people": {
            "title": "People Graph",
            "summary": "The product moat lives in the relationship system: people, recurring themes, open loops, and office pressure that survive beyond one session.",
            "cards": [
                {"eyebrow": "Stakeholders", "title": "Who matters right now", "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="These people are shaping the current office loop.")},
                {"eyebrow": "Relationship themes", "title": "What keeps recurring", "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="Recurring pressure and themes stay durable in the workspace.")},
                {"eyebrow": "Rules", "title": "What the office memory may keep", "items": string_rows(privacy_lines, ("No retention policy set yet.",), tag="Policy", detail="These rules bound what the workspace retains.")},
            ],
        },
        "evidence": {
            "title": "Evidence",
            "summary": "Evidence explains why something surfaced: which signal, which channel, which context, and which rule put it in front of the team.",
            "cards": [
                {"eyebrow": "Memo evidence", "title": "Why items surfaced", "items": string_rows(first_brief, ("No evidence rows surfaced yet.",), tag="Evidence", detail="This is one of the signals behind the current operating view.")},
                {"eyebrow": "Trust notes", "title": "What keeps the surface explainable", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Rule", detail="These constraints explain why the assistant behaved this way.")},
                {"eyebrow": "Channel sources", "title": "Where the evidence came from", "items": channel_items},
            ],
        },
        "channels": {
            "title": "Channels",
            "summary": "Channels widen coverage. They never redefine the product core or become the main story of the workspace.",
            "cards": [
                {"eyebrow": "Google", "title": cards[0]["label"], "items": [cards[0]["detail"], cards[0]["summary"] or "Google sign-in is the recommended first connection."]},
                {"eyebrow": "Telegram", "title": cards[1]["label"], "items": [cards[1]["detail"], cards[1]["summary"] or "Personal identity and bot install stay distinct."]},
                {"eyebrow": "WhatsApp", "title": cards[2]["label"], "items": [cards[2]["detail"], cards[2]["summary"] or "Business onboarding and export intake stay separate."]},
            ],
        },
        "automations": {
            "title": "Policies",
            "summary": "Policies stay understandable: what the assistant may read, draft, send, remember, and escalate.",
            "cards": [
                {"eyebrow": "Assistant posture", "title": "Current rules", "items": privacy_lines},
                {"eyebrow": "Suggested changes", "title": "What to unlock next", "items": suggested},
                {"eyebrow": "Guardrails", "title": "Why these rules exist", "items": trust_notes},
            ],
        },
        "activity": {
            "title": "Audit",
            "summary": "Audit explains what changed, what left the system, and which rule or review point allowed it.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current state", "items": string_rows([f"Status: {status_label}", f"Setup state: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"], ("No workspace state yet.",), tag="State", detail="This is the current workspace status.")},
                {"eyebrow": "Channels", "title": "Recent changes", "items": channel_items},
                {"eyebrow": "Trust", "title": "Why this feed matters", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Context", detail="This keeps the activity feed understandable.")},
            ],
        },
        "settings": {
            "title": "Rules",
            "summary": "Rules stay boring and explicit once the first working loop already exists.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current workspace posture", "items": string_rows([f"Name: {workspace.get('name') or 'PropertyQuarry'}", f"Mode: {humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"], ("No workspace posture yet.",), tag="Workspace", detail="These are the current office defaults.")},
                {"eyebrow": "Policy", "title": "Assistant behavior", "items": string_rows(privacy_lines, ("No privacy posture set yet.",), tag="Rule", detail="These controls shape what the assistant may do.")},
                {"eyebrow": "Channels", "title": "Selected linked channels", "items": channel_items},
            ],
        },
        "properties": {
            "title": "Properties",
            "summary": (
                str(property_run.get("message") or "").strip()
                or "Run a dedicated cross-platform property crawl, keep the progress visible, and surface hosted 3D-tour matches instead of raw listing noise."
            ),
            "cards": [
                {
                    "eyebrow": "Search posture",
                    "title": "What this search is optimizing for",
                    "body": "The crawl posture stays explicit: market, research language, target location, property shape, and who the ranking is trying to satisfy.",
                    "items": property_market_summary_items
                    + [
                        row_item(
                            "Preference profile",
                            str(property_preferences.get("preference_person_id") or "self"),
                            "Profile",
                        ),
                        row_item(
                            "Active providers",
                            ", ".join(property_selected_platform_labels) if property_selected_platform_labels else "No platforms saved yet.",
                            "Profile",
                        ),
                        row_item(
                            "Result cap per source",
                            str(property_preferences.get("max_results_per_source") or "3"),
                            "Guardrail",
                        ),
                    ],
                },
                {
                    "eyebrow": "Market coverage",
                    "title": "Which providers this country unlocks",
                    "body": "Each market switches the provider catalog. The saved selection should be a deliberate subset, not a hard-coded Austria-only list.",
                    "items": [
                        row_item(
                            "Country bundle",
                            f"{property_country_label} | {property_provider_total_for_country or len(platform_options)} supported providers",
                            "Coverage",
                        ),
                        row_item(
                            "Selected now",
                            str(len(property_selected_platform_labels) or 0),
                            "Selection",
                        ),
                    ] + (property_platform_rows[:4] if property_platform_rows else []),
                },
                {
                    "eyebrow": "Shortlist",
                    "title": "Ranked review desk",
                    "body": "The strongest matches stay review-ready: fit, risk, 360 status, packet link, and the next useful action are visible before operational crawl details.",
                    "items": property_shortlist_rows
                    or property_recent_matches
                    or [
                        row_item(
                            "No shortlist candidates yet",
                            "Run the first crawl to generate a ranked set of review packets and hosted 360 tours.",
                            "Waiting",
                        )
                    ],
                },
                {
                    "eyebrow": "Run status",
                    "title": "Current crawl",
                    "body": str(property_run.get("message") or "Start a crawl to see source-by-source progress, shortlisted hosted tours, and what actually got sent."),
                    "items": property_source_rows
                    or property_event_rows
                    or [
                        row_item(
                            "No active crawl yet",
                            "Save the defaults and start the first dedicated run from the right-side lane.",
                            "Queued",
                        )
                    ],
                },
                {
                    "eyebrow": "Learning loop",
                    "title": "What the product has learned from feedback",
                    "body": "Paid research only gets stronger if the system remembers what helped, what failed, and which hard rules should suppress future noise.",
                    "items": property_learning_rows
                    or property_recent_feedback_rows
                    or [
                        row_item(
                            "No learned preferences yet",
                            "Use the hosted review packets to record feedback. The learned likes, dislikes, and hard rules will surface here.",
                            "Waiting",
                        )
                    ],
                },
                {
                    "eyebrow": "Recent matches",
                    "title": "Hosted pages already delivered",
                    "body": "Strong matches should resolve to branded hosted property pages or review packets, not raw portal links.",
                    "items": property_recent_matches
                    or property_event_rows
                    or [
                        row_item(
                            "No hosted property follow-ups yet",
                            "Once a high-fit listing yields a hosted page or review follow-up, it will appear here.",
                            "Waiting",
                        )
                    ],
                },
            ],
            "stats": [
                {"label": "Country", "value": property_country_label},
                {"label": "Providers", "value": str(len(property_selected_platform_labels) or 0)},
                {"label": "Sources", "value": str(int(property_summary.get("sources_total") or 0))},
                {"label": "Listings", "value": str(int(property_summary.get("listing_total") or 0))},
                {"label": "Hosted tours", "value": str(int(property_summary.get("tour_created_total") or 0) + int(property_summary.get("tour_existing_total") or 0))},
            ],
            "console_form": property_form,
        },
    }
    payload = dict(mapping[section])
    payload.setdefault("stats", stats)
    return payload


def property_workspace_payload(
    section: str,
    *,
    status: dict[str, object],
    property_state: dict[str, object],
) -> dict[str, object]:
    base = app_section_payload("properties", status, live_feed=(), property_context=property_state)
    cards = list(base.get("cards") or [])
    cards_by_eyebrow = {
        str(card.get("eyebrow") or "").strip().lower(): dict(card)
        for card in cards
        if isinstance(card, dict)
    }
    cards_by_title = {
        str(card.get("title") or "").strip().lower(): dict(card)
        for card in cards
        if isinstance(card, dict)
    }
    property_form = dict(base.get("console_form") or {})
    property_meta = dict(property_form.get("meta") or {})
    commercial = dict(property_state.get("commercial") or {})
    property_preferences = dict(property_state.get("preferences") or {})
    preference_person_id = str(property_state.get("preference_person_id") or property_preferences.get("preference_person_id") or "self").strip() or "self"
    preference_bundle = dict(property_state.get("preference_bundle") or {})
    raw_preference_nodes = [
        dict(row)
        for row in list(preference_bundle.get("preference_nodes") or [])
        if isinstance(row, dict)
    ]
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    google = dict(channels.get("google") or {})
    current_plan_label = str(commercial.get("current_plan_label") or "Free").strip() or "Free"
    search_posture_card = cards_by_eyebrow.get("search posture", {})
    market_coverage_card = cards_by_eyebrow.get("market coverage", {})
    shortlist_card = cards_by_eyebrow.get("shortlist", {})
    run_card = cards_by_eyebrow.get("run status", {})
    learning_card = cards_by_eyebrow.get("learning loop", {})
    recent_matches_card = cards_by_eyebrow.get("recent matches", {})
    shortlist_candidates = list(property_meta.get("shortlist_candidates") or [])
    run_payload = dict(property_state.get("run") or {})
    run_events = list(run_payload.get("events") or [])
    run_summary = dict(run_payload.get("summary") or {})
    selected_locations = _csv_values(property_preferences.get("location_query"))
    selected_keywords = _csv_values(property_preferences.get("keywords"))
    selected_platforms = [str(value).strip() for value in list(property_state.get("selected_platforms") or []) if str(value).strip()]
    run_id = str(run_payload.get("run_id") or "").strip()
    run_suffix = f"?run_id={run_id}" if run_id else ""
    search_posture_items = list(search_posture_card.get("items") or [])
    packet_ready_total = sum(
        1
        for candidate in shortlist_candidates
        if str(candidate.get("packet_url") or candidate.get("review_url") or "").strip()
    )
    tour_ready_total = sum(1 for candidate in shortlist_candidates if str(candidate.get("tour_url") or "").strip())
    run_status_label = str(run_payload.get("status") or "not started").replace("_", " ").strip().title() or "Not started"
    run_message = str(run_payload.get("message") or "").strip()
    run_status_value = str(run_payload.get("status") or "").strip().lower()
    run_in_progress = bool(run_id and run_status_value and run_status_value not in {"processed", "completed", "failed", "noop", "cancelled", "not started"})

    def _preference_value_label(value: object) -> str:
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip()) or "empty list"
        if isinstance(value, dict):
            return ", ".join(f"{key}: {item}" for key, item in value.items() if str(key).strip()) or "empty object"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value if value is not None else "").strip() or "empty"

    def _preference_key_label(row: dict[str, object]) -> str:
        key = str(row.get("key") or "").strip().replace("_", " ")
        category = str(row.get("category") or "").strip().replace("_", " ")
        return (key or "Preference").title() + (f" ({category.title()})" if category else "")

    preference_manager_nodes = [
        {
            "node_id": str(row.get("node_id") or "").strip(),
            "domain": str(row.get("domain") or "").strip() or "willhaben",
            "category": str(row.get("category") or "").strip() or "soft_preference",
            "key": str(row.get("key") or "").strip(),
            "label": _preference_key_label(row),
            "value_label": _preference_value_label(row.get("value_json")),
            "value_json": row.get("value_json"),
            "strength": str(row.get("strength") or "medium").strip() or "medium",
            "confidence": row.get("confidence") or 0,
            "source_mode": str(row.get("source_mode") or "").strip(),
            "status": str(row.get("status") or "").strip().lower() or "active",
            "updated_at": str(row.get("updated_at") or "").strip(),
        }
        for row in raw_preference_nodes
        if str(row.get("node_id") or "").strip()
    ]
    preference_manager_nodes.sort(key=lambda row: (str(row.get("status") or "") != "active", str(row.get("label") or "").lower()))
    preference_manager = {
        "person_id": preference_person_id,
        "nodes": preference_manager_nodes,
        "active_nodes": [row for row in preference_manager_nodes if str(row.get("status") or "") == "active"],
        "schema": _property_preference_schema(),
        "bundle_endpoint": f"/app/api/people/{preference_person_id}/preference-profile",
        "node_endpoint": f"/app/api/people/{preference_person_id}/preference-profile/nodes",
        "archive_endpoint_template": f"/app/api/people/{preference_person_id}/preference-profile/nodes/__NODE_ID__/archive",
    }

    def _tour_source_gap_detail(candidate: dict[str, object]) -> str:
        blocked_reason = str(candidate.get("blocked_reason") or "").strip()
        if blocked_reason:
            reason_map = {
                "listing_360_media_missing": "Floorplan or source 360 media missing: the listing does not expose usable tour material yet.",
                "pure_360_assets_unavailable": "Source 360 assets are not accessible enough to rebuild a hosted PropertyQuarry tour.",
                "property_tour_fallback_disabled": "Generated fallback tours are disabled until source floorplan or 360 material is available.",
            }
            return reason_map.get(blocked_reason, blocked_reason.replace("_", " "))
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}

        def _false_flag(value: object) -> bool:
            return str(value or "").strip().lower() in {"0", "false", "no", "none", "null"}

        def _zero_count(*keys: str) -> bool:
            for key in keys:
                raw_value = facts.get(key)
                if raw_value in (None, ""):
                    continue
                try:
                    return float(str(raw_value).strip()) <= 0.0
                except Exception:
                    continue
            return False

        if _false_flag(facts.get("has_floorplan")) or _zero_count("floorplan_count", "floorplans_count"):
            return "Floorplan missing: this listing exposes no floorplan or source 360 media, so PropertyQuarry cannot generate a hosted tour yet."
        if _false_flag(facts.get("has_360")) or _zero_count("media_count", "image_count"):
            return "Tour source media missing: the source did not expose a 360, floorplan, or usable room media."
        return "Floorplan or source 360 media missing, so PropertyQuarry cannot generate a hosted tour yet."

    def _candidate_fact_line(candidate: dict[str, object]) -> str:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        parts: list[str] = []
        price_value = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price")
            or facts.get("price_eur")
            or ""
        ).strip()
        rooms_value = str(facts.get("rooms") or facts.get("room_count") or "").strip()
        area_value = str(facts.get("area_m2") or facts.get("living_area_m2") or "").strip()
        if price_value:
            parts.append(price_value)
        if rooms_value:
            parts.append(f"{rooms_value} rooms")
        if area_value:
            parts.append(f"{area_value} m2")
        return " | ".join(parts)

    compare_rows = []
    for candidate in shortlist_candidates[:3]:
        fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "").strip()
        fact_line = _candidate_fact_line(candidate)
        detail = " | ".join(part for part in (fit_summary, fact_line) if part) or "Open the packet to inspect the ranking and the evidence."
        compare_rows.append(
            {
                "title": str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate",
                "detail": detail,
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open packet",
                "secondary_action_href": str(candidate.get("tour_url") or candidate.get("review_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("tour_url") or candidate.get("review_url")) else "",
                "secondary_action_label": "Open 360" if candidate.get("tour_url") else ("Hosted review" if candidate.get("review_url") else ""),
            }
        )

    def _tour_status_line(candidate: dict[str, object]) -> str:
        if str(candidate.get("tour_url") or "").strip():
            return "Ready | Live now"
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_minutes = int(candidate.get("tour_eta_minutes") or 0) if str(candidate.get("tour_eta_minutes") or "").strip() else 0
        if status in {"queued", "pending"}:
            return f"Queued | ETA about {eta_minutes or 10} min"
        if status in {"processing", "running", "in_progress", "started"}:
            return f"Rendering | ETA about {eta_minutes or 5} min"
        if status in {"created", "existing"}:
            return "Ready"
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return f"Blocked | {_tour_source_gap_detail(candidate)}"
        blocked_reason = str(candidate.get("blocked_reason") or "").strip()
        if blocked_reason:
            return f"Blocked | {blocked_reason.replace('_', ' ')}"
        return f"Unavailable | {_tour_source_gap_detail(candidate)}"

    def _distance_line(candidate: dict[str, object]) -> str:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        specs = (
            ("Playground", facts.get("nearest_playground_m") or facts.get("distance_playground_m")),
            ("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("distance_pharmacy_m")),
            ("Supermarket", facts.get("nearest_supermarket_m") or facts.get("distance_supermarket_m")),
            ("Underground", facts.get("nearest_subway_m") or facts.get("distance_underground_m")),
        )
        parts: list[str] = []
        for label, raw_value in specs:
            if raw_value in (None, "", []):
                continue
            try:
                meters = int(float(raw_value))
            except Exception:
                continue
            bike_minutes = max(1, int(round(float(meters) / 330.0)))
            parts.append(f"{label} {meters} m | {bike_minutes} min bike")
        return " · ".join(parts[:3])

    results_table_rows = []
    workbench_results: list[dict[str, object]] = []

    def _money_per_sqm_line(facts: dict[str, object]) -> str:
        raw_price = facts.get("price_eur") or facts.get("purchase_price_eur")
        raw_area = facts.get("area_m2") or facts.get("living_area_m2")
        try:
            price = float(raw_price)
            area = float(raw_area)
        except Exception:
            return ""
        if price <= 0 or area <= 0:
            return ""
        return f"EUR {price / area:,.0f}/m2"

    def _missing_fact_items(facts: dict[str, object]) -> list[dict[str, object]]:
        research = facts.get("missing_fact_research")
        if not isinstance(research, dict):
            return []
        items = research.get("items")
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _missing_fact_item(facts: dict[str, object], field: str) -> dict[str, object]:
        normalized = str(field or "").strip()
        for item in _missing_fact_items(facts):
            if str(item.get("field") or "").strip() == normalized:
                return item
        return {}

    def _rooms_layout_part(facts: dict[str, object]) -> str:
        label = str(facts.get("rooms_label") or "").strip()
        if label:
            return label
        raw_value = facts.get("rooms") or facts.get("room_count")
        if raw_value:
            return f"{raw_value} rooms"
        item = _missing_fact_item(facts, "rooms")
        if item:
            return str(item.get("display_value") or "Rooms under research").strip() or "Rooms under research"
        return ""

    def _risk_summary(candidate: dict[str, object], facts: dict[str, object]) -> dict[str, str]:
        mismatch = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
        missing: list[str] = []
        if not str(candidate.get("tour_url") or "").strip():
            tour_status = str(candidate.get("tour_status") or "").strip().lower()
            if tour_status in {"blocked", "failed", "skipped", "not_applicable"}:
                missing.append("floorplan/360 source media")
            else:
                missing.append("360 pending")
        if not (facts.get("street_address") or facts.get("address")):
            missing.append("address")
        if not (facts.get("heating") or facts.get("heating_type")):
            missing.append("heating")
        for item in _missing_fact_items(facts):
            if str(item.get("status") or "").strip().lower() != "filled":
                missing.append(str(item.get("label") or item.get("field") or "research fact").strip())
        if mismatch:
            return {"level": "medium", "summary": mismatch[0]}
        if len(missing) >= 2:
            return {"level": "medium", "summary": "Missing " + ", ".join(missing[:3])}
        if missing:
            return {"level": "low", "summary": "Missing " + missing[0]}
        return {"level": "low", "summary": "No major packet risk flagged yet."}

    def _candidate_ooda_rows(candidate: dict[str, object], facts: dict[str, object]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for label, raw_value in (
            ("Playground", facts.get("nearest_playground_m") or facts.get("distance_playground_m")),
            ("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("distance_pharmacy_m")),
            ("Supermarket", facts.get("nearest_supermarket_m") or facts.get("distance_supermarket_m")),
            ("Underground", facts.get("nearest_subway_m") or facts.get("distance_underground_m")),
        ):
            if raw_value in (None, "", []):
                continue
            try:
                meters = int(float(raw_value))
            except Exception:
                continue
            rows.append(
                {
                    "label": label,
                    "value": f"{meters} m",
                    "detail": f"about {max(1, int(round(float(meters) / 330.0)))} min by bike",
                }
            )
        match_reasons = [str(item).strip() for item in list(candidate.get("match_reasons") or []) if str(item).strip()]
        mismatch_reasons = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
        rows.insert(
            0,
            {
                "label": "Decide",
                "value": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(),
                "detail": match_reasons[0] if match_reasons else (mismatch_reasons[0] if mismatch_reasons else "Open the packet for the full decision read."),
            },
        )
        for item in _missing_fact_items(facts):
            if str(item.get("status") or "").strip().lower() == "filled":
                continue
            ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
            label = str(item.get("label") or item.get("field") or "Missing fact").strip()
            rows.append(
                {
                    "label": "Research",
                    "value": str(item.get("display_value") or label).strip(),
                    "detail": str(ooda.get("act") or item.get("evidence") or "Missing-fact OODA queued.").strip(),
                }
            )
        return rows[:6]

    def _tour_payload(candidate: dict[str, object]) -> dict[str, str]:
        tour_url = str(candidate.get("tour_url") or "").strip()
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_minutes = str(candidate.get("tour_eta_minutes") or "").strip()
        if tour_url:
            embed_url = "" if "myexternalbrain.com" in tour_url.lower() else tour_url
            return {"status": "ready", "label": "360 ready", "url": tour_url, "embed_url": embed_url, "eta_label": ""}
        if status in {"queued", "pending"}:
            return {"status": "queued", "label": "360 queued", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '10'} min"}
        if status in {"processing", "running", "in_progress", "started"}:
            return {"status": "processing", "label": "360 rendering", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '5'} min"}
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return {"status": "blocked", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}
        return {"status": "missing", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}

    for candidate in shortlist_candidates:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        price_line = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price_eur")
            or ""
        ).strip() or "n/a"
        layout_parts = [
            _rooms_layout_part(facts),
            f"{facts.get('area_m2') or facts.get('area_sqm')} m2" if (facts.get("area_m2") or facts.get("area_sqm")) else "",
            str(facts.get("postal_name") or "").strip(),
        ]
        packet_url = str(candidate.get("packet_url") or candidate.get("review_url") or "").strip()
        packet_label = "Review packet" if packet_url else "Pending"
        tour_status_line = _tour_status_line(candidate)
        ooda_detail = _distance_line(candidate)
        candidate_ref = str(packet_url or "").split("/app/research/", 1)[-1].split("?", 1)[0] if "/app/research/" in packet_url else _property_candidate_ref(candidate)
        tour_payload = _tour_payload(candidate)
        ooda_rows = _candidate_ooda_rows(candidate, facts)
        risk_payload = _risk_summary(candidate, facts)
        match_reasons = [str(item).strip() for item in list(candidate.get("match_reasons") or []) if str(item).strip()]
        mismatch_reasons = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
        investment_payload = {
            "enabled": str(property_preferences.get("listing_mode") or "").strip().lower() == "buy",
            "price_per_sqm": _money_per_sqm_line(facts),
            "headline": "Open packet for full underwriting" if str(property_preferences.get("listing_mode") or "").strip().lower() == "buy" else "",
        }
        workbench_results.append(
            {
                "candidate_ref": candidate_ref,
                "rank": len(workbench_results) + 1,
                "title": str(candidate.get("title") or "Candidate").strip() or "Candidate",
                "source_label": str(candidate.get("source_label") or "").strip(),
                "location_label": str(facts.get("postal_name") or facts.get("city") or facts.get("address") or "").strip(),
                "price_display": price_line,
                "price_per_sqm_display": investment_payload["price_per_sqm"],
                "layout_display": " | ".join(part for part in layout_parts if part) or "n/a",
                "fit_label": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(),
                "fit_summary": str(candidate.get("fit_summary") or "").strip(),
                "tour": tour_payload,
                "ooda": {
                    "summary": ooda_detail or (match_reasons[0] if match_reasons else "Open the packet to inspect OODA."),
                    "rows": ooda_rows,
                },
                "risk": risk_payload,
                "investment": investment_payload,
                "match_reasons": match_reasons,
                "mismatch_reasons": mismatch_reasons,
                "packet_url": packet_url,
                "review_url": str(candidate.get("review_url") or "").strip(),
                "source_url": str(candidate.get("property_url") or "").strip(),
            }
        )
        results_table_rows.append(
            {
                "cells": [
                    {"title": "Open 360" if str(candidate.get("tour_url") or "").strip() else tour_status_line, "detail": tour_status_line if str(candidate.get("tour_url") or "").strip() else "", "href": str(candidate.get("tour_url") or "").strip()},
                    {"title": str(candidate.get("title") or "Candidate").strip() or "Candidate", "detail": str(candidate.get("source_label") or "").strip()},
                    {"title": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(), "detail": str(candidate.get("fit_summary") or "").strip()},
                    {"title": price_line, "detail": ""},
                    {"title": " | ".join(part for part in layout_parts if part) or "n/a", "detail": ""},
                    {"title": ooda_detail or "Packet explains the neighbourhood fit.", "detail": "", "href": packet_url},
                    {"title": packet_label, "detail": packet_url or str(candidate.get("property_url") or "").strip(), "href": packet_url},
                ],
                "packet_url": packet_url,
                "tour_url": str(candidate.get("tour_url") or "").strip(),
                "source_url": str(candidate.get("property_url") or "").strip(),
            }
        )

    hero_actions = {
        "properties": [
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist", "tone": "primary"},
            {"href": f"/app/research{run_suffix}", "label": "Open research"},
            {"href": f"/app/billing{run_suffix}", "label": "Plans"},
        ],
        "shortlist": [
            {"href": f"/app/research{run_suffix}", "label": "Open research", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            {"href": f"/app/alerts{run_suffix}", "label": "Alerts"},
        ],
        "research": [
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            {"href": f"/app/alerts{run_suffix}", "label": "Alerts"},
        ],
        "profile": [
            {"href": f"/app/properties{run_suffix}", "label": "Refine search", "tone": "primary"},
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
            {"href": f"/app/settings{run_suffix}", "label": "Settings"},
        ],
        "alerts": [
            {"href": f"/app/properties{run_suffix}", "label": "Open search desk", "tone": "primary"},
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
            {"href": f"/app/settings{run_suffix}", "label": "Notifications"},
        ],
        "billing": [
            {"href": "/pricing", "label": "Open pricing", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Back to search"},
            {"href": "/security", "label": "Security"},
        ],
        "settings": [
            {"href": f"/app/properties{run_suffix}", "label": "Back to search", "tone": "primary"},
            {"href": "/security", "label": "Open security"},
            {"href": "/pricing", "label": "Open pricing"},
        ],
    }
    hero_highlights = {
        "properties": [
            {
                "label": "Market",
                "value": str(property_state.get("country_label") or "Austria"),
                "detail": str(search_posture_items[0].get("detail") or "").strip() if search_posture_items else "",
                "href": f"/app/properties{run_suffix}",
            },
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "Choose the target districts.", "href": f"/app/profile{run_suffix}"},
            {"label": "Priorities", "value": str(len(selected_keywords) or 0), "detail": ", ".join(selected_keywords[:3]) or "Record what should drive the ranking.", "href": f"/app/profile{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "The selected portals for the next sweep.", "href": f"/app/properties{run_suffix}"},
        ],
        "shortlist": [
            {"label": "Candidates", "value": str(len(shortlist_candidates)), "detail": "Ranked properties worth direct review now.", "href": f"/app/shortlist{run_suffix}"},
            {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal packets ready before the raw portal listing.", "href": f"/app/research{run_suffix}"},
            {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted or embedded tours already available.", "href": f"/app/research{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest run status.", "href": f"/app/properties{run_suffix}"},
        ],
        "research": [
            {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal dossiers ready for inspection.", "href": f"/app/research{run_suffix}"},
            {"label": "Tours", "value": str(tour_ready_total), "detail": "Candidates already backed by a 360 or hosted tour.", "href": f"/app/research{run_suffix}"},
            {"label": "Signals", "value": str(int(run_summary.get("listing_total") or 0)), "detail": "Raw listings considered in the latest run.", "href": f"/app/properties{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest research pass.", "href": f"/app/properties{run_suffix}"},
        ],
        "profile": [
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "No areas saved yet.", "href": f"/app/profile{run_suffix}"},
            {"label": "Priorities", "value": str(len(selected_keywords) or 0), "detail": ", ".join(selected_keywords[:3]) or "No ranking preferences saved yet.", "href": f"/app/profile{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "Current active provider set.", "href": f"/app/properties{run_suffix}"},
            {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": f"/app/billing{run_suffix}"},
        ],
        "alerts": [
            {"label": "Delivered", "value": str(len(recent_matches_card.get("items") or [])), "detail": "Hosted pages or packets already sent.", "href": f"/app/alerts{run_suffix}"},
            {"label": "Run events", "value": str(len(run_events[-4:])), "detail": "Recent run updates visible to the user.", "href": f"/app/alerts{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "Portals currently feeding the alert lane.", "href": f"/app/properties{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest saved-search sweep.", "href": f"/app/properties{run_suffix}"},
        ],
        "billing": [
            {"label": "Plan", "value": current_plan_label, "detail": "Current commercial posture.", "href": f"/app/billing{run_suffix}"},
            {"label": "Depth", "value": str(commercial.get("research_depth") or "deep").title(), "detail": "How deep the research lane runs.", "href": f"/app/billing{run_suffix}"},
            {"label": "Providers", "value": str(commercial.get("max_platforms") or "Multi"), "detail": "Maximum provider breadth for this plan.", "href": f"/app/billing{run_suffix}"},
            {"label": "Per source", "value": str(commercial.get("max_results_per_source") or 2), "detail": "Maximum ranked results per provider.", "href": f"/app/billing{run_suffix}"},
        ],
        "settings": [
            {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": f"/app/settings{run_suffix}"},
            {"label": "Workspace", "value": str(workspace.get("name") or "PropertyQuarry"), "detail": str(workspace.get("timezone") or "Europe/Vienna"), "href": f"/app/settings{run_suffix}"},
            {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": f"/app/billing{run_suffix}"},
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": f"/app/profile{run_suffix}"},
        ],
    }
    preference_rows = [
        row_item(
            "Workspace",
            str(workspace.get("name") or "PropertyQuarry"),
            "Workspace",
        ),
        row_item(
            "Google sign-in",
            str(google.get("connected_account_email") or google.get("status") or "Not connected"),
            "Connection",
        ),
        row_item(
            "Timezone",
            str(workspace.get("timezone") or "Europe/Vienna"),
            "Preference",
        ),
        row_item(
            "Active plan",
            current_plan_label,
            "Plan",
        ),
    ]
    settings_connection_rows = [
        row_item(
            "Google sign-in",
            "Identity-only return access. PropertyQuarry should not widen this into office sync on the settings surface.",
            "Connection",
        ),
        row_item(
            "Notification delivery",
            "Good matches can leave through Telegram or email once the shortlist is credible enough to notify.",
            "Alerts",
        ),
        row_item(
            "Workspace posture",
            "Billing, saved defaults, and security should stay explicit and product-specific.",
            "Control",
        ),
    ]
    alerts_rows = list(recent_matches_card.get("items") or []) + [
        row_item(
            str(event.get("step") or "Run update").replace("_", " ").strip().title(),
            str(event.get("message") or "No further detail.").strip() or "No further detail.",
            str(event.get("status") or "Update").replace("_", " ").strip().title(),
        )
        for event in run_events[-4:]
        if isinstance(event, dict)
    ]
    if not alerts_rows:
        alerts_rows = [
            row_item(
                "No client alerts yet",
                "Hosted pages and review packets will surface here once the first high-fit matches are ready.",
                "Waiting",
            )
        ]
    billing_rows = [
        row_item(
            "Current plan",
            f"{current_plan_label} | {str(commercial.get('research_depth') or 'deep')} research",
            "Plan",
        ),
        row_item(
            "Coverage",
            f"{commercial.get('max_platforms') or 'Multi'} provider lane | up to {commercial.get('max_results_per_source') or 2} results per provider",
            "Limits",
        ),
        row_item(
            "Checkout",
            str(property_state.get("billing_checkout_provider_label") or "Unavailable"),
            "Provider",
        ),
    ]
    if commercial.get("active_until"):
        billing_rows.append(
            row_item(
                "Access window",
                str(commercial.get("active_until") or "").strip(),
                "Status",
            )
        )
    research_rows = []
    for candidate in shortlist_candidates[:6]:
        title = str(candidate.get("title") or "Research packet").strip() or "Research packet"
        reasons = list(candidate.get("match_reasons") or [])[:2]
        mismatches = list(candidate.get("mismatch_reasons") or [])[:2]
        detail_parts = []
        if candidate.get("fit_summary"):
            detail_parts.append(str(candidate.get("fit_summary") or "").strip())
        if reasons:
            detail_parts.append("; ".join(str(reason).strip() for reason in reasons if str(reason).strip()))
        if mismatches:
            detail_parts.append("Risks: " + "; ".join(str(reason).strip() for reason in mismatches if str(reason).strip()))
        research_rows.append(
            {
                "title": title,
                "detail": " | ".join(part for part in detail_parts if part) or "Open the packet to inspect the fit and missing evidence.",
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Packet").strip() or "Packet",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open packet",
                "secondary_action_href": str(candidate.get("review_url") or candidate.get("tour_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("review_url") or candidate.get("tour_url")) else "",
                "secondary_action_label": "Hosted review" if candidate.get("review_url") else ("Open 360" if candidate.get("tour_url") else ""),
            }
        )
    if not research_rows:
        research_rows = list(recent_matches_card.get("items") or []) or [
            row_item(
                "No research packets yet",
                "The first finished run will promote the strongest matches into full review packets here.",
                "Waiting",
            )
        ]
    saved_search_rows = [
        {
            "title": "Current saved search",
            "detail": " | ".join(
                part for part in (
                    str(property_state.get("country_label") or "").strip(),
                    f"{len(selected_locations)} target area(s)" if selected_locations else "",
                    f"{len(selected_platforms)} provider(s)" if selected_platforms else "",
                ) if part
            ) or "No saved search brief yet.",
            "tag": "Saved",
            "action_href": f"/app/properties{run_suffix}",
            "action_method": "get",
            "action_label": "Refine brief",
        },
        {
            "title": "Latest run posture",
            "detail": run_message or "Open the search desk to launch or monitor the next sweep.",
            "tag": run_status_label,
            "action_href": f"/app/properties{run_suffix}",
            "action_method": "get",
            "action_label": "Open search desk",
        },
        {
            "title": "Delivery path",
            "detail": "Telegram and email stay secondary until the shortlist is credible enough to notify.",
            "tag": "Alerts",
            "action_href": f"/app/settings{run_suffix}",
            "action_method": "get",
            "action_label": "Review settings",
        },
    ]

    sections: dict[str, dict[str, object]] = {
        "properties": {
            "title": "Results" if run_status_value in {"processed", "completed"} and results_table_rows else ("Live search" if run_in_progress else "Search Brief"),
            "summary": (
                "Review the final ranked result table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "The search brief is locked while the run is active. Keep the visible progress and source-by-source status in front of the user."
                    if run_in_progress
                    else str(base.get("summary") or "Define the search brief, launch the run, and keep the crawl visible.")
                )
            ),
            "hero_kicker": "Results" if run_status_value in {"processed", "completed"} and results_table_rows else ("Live search" if run_in_progress else "Search brief"),
            "hero_title": (
                "Review the finished shortlist in one table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else ("Keep the run visible until the shortlist is ready." if run_in_progress else "Shape the next market sweep before the crawlers fan out.")
            ),
            "hero_summary": (
                "Once the run is done, keep the result surface simple: one ranked table, packet links, and clear 360 status."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "Hide the search form while the run is active. Show only progress, source events, and the first usable signals until the final ranked table is ready."
                    if run_in_progress
                    else "Pick the market, region, buying posture, shortlist priorities, and provider set once so the run starts from an explicit brief instead of a stack of browser tabs."
                )
            ),
            "hero_actions": [{"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"}, {"href": f"/app/research{run_suffix}", "label": "Open research"}] if run_in_progress else (hero_actions["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"href": f"/app/research{run_suffix}", "label": "Open research", "tone": "primary"},
                {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
                {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            ]),
            "hero_highlights": [
                {"label": "Run state", "value": run_status_label, "detail": run_message or "The current live run status."},
                {"label": "Sources", "value": str(int(run_summary.get("sources_total") or 0)), "detail": "Provider lanes in the current sweep."},
                {"label": "Listings", "value": str(int(run_summary.get("listing_total") or 0)), "detail": "Listings recovered so far."},
                {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted tours already available."},
            ] if run_in_progress else (hero_highlights["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"label": "Results", "value": str(len(results_table_rows)), "detail": "Final ranked candidates in this run."},
                {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal review packets ready now."},
                {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted tours available right now."},
                {"label": "Run state", "value": run_status_label, "detail": run_message or "Latest run complete."},
            ]),
            "primary_cards": [] if (run_status_value in {"processed", "completed"} and results_table_rows) or run_in_progress else [search_posture_card, market_coverage_card],
            "secondary_cards": [] if run_status_value in {"processed", "completed"} and results_table_rows else ([run_card] if run_in_progress else [run_card, recent_matches_card]),
            "console_form": property_form,
            "show_brief_form": not ((run_status_value in {"processed", "completed"} and results_table_rows) or run_in_progress),
            "show_run_panel": run_in_progress,
            "show_shortlist_cards": False,
            "show_results_table": run_status_value in {"processed", "completed"} and bool(results_table_rows),
            "results_table_headers": ["360", "Candidate", "Fit", "Price", "Layout", "OODA", "Review"],
            "results_table_rows": results_table_rows,
        },
        "shortlist": {
            "title": "Shortlist",
            "summary": "Keep the strongest candidates in one ranked lane and record preference feedback directly on the cards.",
            "hero_kicker": "Shortlist",
            "hero_title": "Review the properties that deserve attention now.",
            "hero_summary": "Start with fit, risks, packet link, 360 link, and one-step feedback. Crawl counters stay secondary.",
            "hero_actions": hero_actions["shortlist"],
            "hero_highlights": hero_highlights["shortlist"],
            "primary_cards": [
                {
                    "eyebrow": "At a glance",
                    "title": "Compare the top shortlist before opening deeper packets",
                    "body": "The first scan should show which candidate looks strongest right now without forcing the user to open five pages.",
                    "items": compare_rows or [row_item("No shortlisted candidates yet", "Finish a run to compare the first candidates here.", "Waiting")],
                },
                shortlist_card,
            ],
            "secondary_cards": [run_card, market_coverage_card],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": True,
        },
        "research": {
            "title": "Research",
            "summary": "Turn high-fit candidates into property dossiers with evidence, packets, and hosted follow-ups.",
            "hero_kicker": "Research packets",
            "hero_title": "Inspect the evidence before you open the raw listing.",
            "hero_summary": "This lane should feel like a property dossier desk: fit reasons, missing facts, packet links, and hosted tours where they exist.",
            "hero_actions": hero_actions["research"],
            "hero_highlights": hero_highlights["research"],
            "primary_cards": [
                {
                    "eyebrow": "Research packets",
                    "title": "Open the strongest packets first",
                    "body": "Hosted packet links and 360 tours stay primary. Raw portal links remain secondary.",
                    "items": research_rows,
                }
            ],
            "secondary_cards": [recent_matches_card, run_card],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "profile": {
            "title": "Profile Learning",
            "summary": "Show what the ranking learned, what should be suppressed next time, and which rules remain explicit.",
            "hero_kicker": "Profile learning",
            "hero_title": "Make the learning loop visible and editable.",
            "hero_summary": "Likes, dislikes, and hard rules must survive beyond one run. This lane is where the ranking becomes personal instead of repeating the same weak matches.",
            "hero_actions": hero_actions["profile"],
            "hero_highlights": hero_highlights["profile"],
            "primary_cards": [learning_card],
            "secondary_cards": [
                {
                    "eyebrow": "Saved posture",
                    "title": "Current profile state",
                    "body": "The saved search posture should be easy to inspect without reopening the full brief.",
                    "items": list(search_posture_card.get("items") or []),
                },
                {
                    "eyebrow": "Account",
                    "title": "Who this profile belongs to",
                    "body": "Identity and connection state stay narrow and explicit on PropertyQuarry.",
                    "items": preference_rows,
                },
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "alerts": {
            "title": "Alerts",
            "summary": "Track what has already been delivered and which run events are preparing the next outbound packet.",
            "hero_kicker": "Alerts",
            "hero_title": "See what has been sent and what is about to leave.",
            "hero_summary": "Alerts are product output, not hidden queue state. Keep hosted matches, review packets, and run updates visible in one lane.",
            "hero_actions": hero_actions["alerts"],
            "hero_highlights": hero_highlights["alerts"],
            "primary_cards": [
                {
                    "eyebrow": "Client alerts",
                    "title": "Recent outbound property follow-ups",
                    "body": "Hosted pages, review briefs, and run updates that mattered enough to notify the client.",
                    "items": alerts_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Saved search",
                    "title": "The alert lane should still expose the search brief driving it",
                    "body": "Recurring alerts are only useful when the user can still see and revise the search posture behind them.",
                    "items": saved_search_rows,
                },
                run_card,
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "billing": {
            "title": "Billing",
            "summary": "Keep plan state, checkout path, and usage posture visible without mixing them into the shortlist surface.",
            "hero_kicker": "Billing",
            "hero_title": "Control the research tier without losing the search context.",
            "hero_summary": "The billing lane should explain what the current plan unlocks, what is capped, and how the next upgrade changes the search depth.",
            "hero_actions": hero_actions["billing"],
            "hero_highlights": hero_highlights["billing"],
            "primary_cards": [
                {
                    "eyebrow": "Plan posture",
                    "title": "Current commercial state",
                    "body": "Free should prove the product. Paid should expand research, provider breadth, and automation cleanly.",
                    "items": billing_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Upgrade impact",
                    "title": "What changes with the next tier",
                    "body": "Keep the plan delta legible before you open checkout.",
                    "items": [
                        row_item(
                            str(plan.get("display_name") or "Plan"),
                            ", ".join(str(feature).strip() for feature in list(plan.get("features") or [])[:3] if str(feature).strip()) or "No plan details available.",
                            "Plan",
                        )
                        for plan in list(commercial.get("plan_catalog") or [])
                        if isinstance(plan, dict)
                    ] or [row_item("No upgrade catalog yet", "Plan metadata will appear here once the billing catalog is available.", "Waiting")],
                }
            ],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
            "show_billing_cards": True,
        },
        "settings": {
            "title": "Settings",
            "summary": "Keep account identity, saved defaults, and connection state narrow and product-specific.",
            "hero_kicker": "Settings",
            "hero_title": "Adjust the product without falling back into assistant tooling.",
            "hero_summary": "PropertyQuarry settings should cover the search profile, Google return access, billing posture, and notifications. Nothing here should look like office sync.",
            "hero_actions": hero_actions["settings"],
            "hero_highlights": hero_highlights["settings"],
            "primary_cards": [
                {
                    "eyebrow": "Connections",
                    "title": "Identity and return access",
                    "body": "Google is optional identity and easier return access. It is not an office sync contract here.",
                    "items": preference_rows + settings_connection_rows,
                },
                {
                    "eyebrow": "Saved defaults",
                    "title": "Current search brief state",
                    "body": "The saved brief stays visible so you can change the product posture before the next run.",
                    "items": list(search_posture_card.get("items") or []),
                },
                {
                    "eyebrow": "Operating posture",
                    "title": "Where the next change belongs",
                    "body": "Settings should tell the user what to change next instead of leaking inherited assistant concepts.",
                    "items": [
                        row_item("Search brief", "Go back to Search when the market, provider mix, or shortlist depth needs adjustment.", "Search"),
                        row_item("Billing", "Use Billing when you need more providers, deeper research, or more sustained automation.", "Billing"),
                        row_item("Security", "Use the public security page to inspect retention and identity posture on this product.", "Trust"),
                    ],
                },
            ],
            "secondary_cards": [billing_rows and {
                "eyebrow": "Plan",
                "title": "Commercial posture",
                "body": "Plan limits and research depth stay visible here too.",
                "items": billing_rows,
            } or {}, {
                "eyebrow": "Public surfaces",
                "title": "Product-facing controls",
                "body": "The user should understand where the public contract lives too.",
                "items": [
                    {
                        "title": "Pricing",
                        "detail": "Inspect the current plan ladder and commercial delta on the public product page.",
                        "tag": "Public",
                        "action_href": "/pricing",
                        "action_method": "get",
                        "action_label": "Open pricing",
                    },
                    {
                        "title": "Security",
                        "detail": "Review trust, identity, and data-posture language on the public product page.",
                        "tag": "Public",
                        "action_href": "/security",
                        "action_method": "get",
                        "action_label": "Open security",
                    },
                ],
            }],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
    }

    payload = dict(sections.get(section, sections["properties"]))
    payload["stats"] = list(base.get("stats") or [])
    payload["current_plan_label"] = current_plan_label
    payload["run_payload"] = run_payload
    payload["run_summary"] = run_summary
    payload["preference_manager"] = preference_manager
    payload["decision_workbench"] = {
        "run": {
            "run_id": run_id,
            "status": run_status_value or "not_started",
            "status_label": run_status_label,
            "progress": int(run_payload.get("progress") or 0),
            "message": run_message,
            "status_url": str(run_payload.get("status_url") or "").strip(),
            "summary": run_summary,
            "events": run_events[-8:],
        },
        "brief": {
            "country": str(property_state.get("country_label") or "Austria"),
            "mode": str(property_preferences.get("listing_mode") or "rent").strip().title(),
            "region": str(property_state.get("region_label") or property_preferences.get("region_code") or "").strip(),
            "areas": selected_locations,
            "priorities": selected_keywords,
            "providers": selected_platforms,
            "plan": current_plan_label,
            "research_depth": str(commercial.get("research_depth") or "deep").strip(),
        },
        "endpoints": {
            "preferences": str(property_meta.get("preferences_endpoint") or "").strip(),
            "start": str(property_meta.get("start_endpoint") or "").strip(),
            "billing_order": str(property_meta.get("billing_order_endpoint") or "").strip(),
        },
        "recent_packets": [
            {
                "title": str(item.get("title") or item.get("label") or "Review packet").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "tag": str(item.get("tag") or "Packet").strip(),
                "url": str(item.get("action_href") or "").strip(),
            }
            for item in list(recent_matches_card.get("items") or [])[:5]
            if isinstance(item, dict)
        ],
        "results": workbench_results,
        "selected_candidate_ref": workbench_results[0]["candidate_ref"] if workbench_results else "",
        "show_brief_default": not (run_in_progress or (run_status_value in {"processed", "completed"} and bool(workbench_results))),
    }
    return payload


def admin_section_payload(section: str) -> dict[str, object]:
    mapping: dict[str, dict[str, object]] = {
        "policies": {
            "title": "Policies",
            "summary": "Operator-only controls for approval rules, task contracts, and promoted skills.",
            "cards": [
                {"eyebrow": "Policy", "title": "Runtime policy endpoints", "items": ["/v1/policy", "/v1/tasks/contracts", "/v1/skills"]},
                {"eyebrow": "Why it matters", "title": "Keep the product shell separate", "items": ["Buyers see the assistant workflow.", "Admins see the policy plane."]},
            ],
        },
        "providers": {
            "title": "Providers",
            "summary": "Bindings, 1min state, and control-plane views belong here, not in the main buyer navigation.",
            "cards": [
                {"eyebrow": "Provider APIs", "title": "Registry and health", "items": ["/v1/providers/registry", "/v1/providers/states", "/v1/providers/onemin/aggregate"]},
                {"eyebrow": "Operational focus", "title": "What this surface is for", "items": ["Capacity admission", "Binding state", "Runway and burn"]},
            ],
        },
        "audit-trail": {
            "title": "Audit Trail",
            "summary": "Evidence, telemetry, and delivery state stay visible to admins without leaking into the public product story.",
            "cards": [
                {"eyebrow": "Audit", "title": "Trace surfaces", "items": ["/v1/runtime/lanes/telemetry", "/v1/evidence", "/v1/delivery/pending"]},
                {"eyebrow": "Goal", "title": "What this surface needs", "items": ["Receipts", "Execution state", "Delivery confirmations"]},
            ],
        },
        "operators": {
            "title": "Operators",
            "summary": "Admin identity, backlog, and approval work stay in the admin surface.",
            "cards": [
                {"eyebrow": "Human runtime", "title": "Admin endpoints", "items": ["/v1/human/operators", "/v1/human/tasks"]},
                {"eyebrow": "Trust boundary", "title": "Why this is separate", "items": ["Admin identity is separate from the customer workspace surface.", "Audit trails depend on trusted admin records."]},
            ],
        },
        "api": {
            "title": "Runtime",
            "summary": "The operator-center contract belongs in the admin surface, not on the public product pages.",
            "cards": [
                {"eyebrow": "OpenAPI", "title": "Schemas and runtime entrypoints", "items": ["/openapi.json", "/v1/plans/compile", "/v1/rewrite", "/v1/responses"]},
                {"eyebrow": "Docs", "title": "Reference material", "items": ["README", "ARCHITECTURE_MAP", "CI smoke suite"]},
            ],
        },
    }
    payload = mapping[section]
    return {
        "stats": [
            {"label": "Surface", "value": "admin"},
            {"label": "Access", "value": "admin-only"},
            {"label": "Audience", "value": "admins"},
            {"label": "Goal", "value": "operator center"},
        ],
        **payload,
    }
