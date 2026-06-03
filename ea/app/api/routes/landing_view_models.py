from __future__ import annotations

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


def _property_location_options(country_code: str) -> list[dict[str, str]]:
    catalogs: dict[str, list[dict[str, str]]] = {
        "AT": [
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
        "GB": [
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
    return list(catalogs.get(str(country_code or "").strip().upper(), []))


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
    property_type_label = str(property_state.get("property_type_label") or "Any type")
    property_provider_total_for_country = int(property_state.get("provider_total_for_country") or 0)
    selected_location_values = _csv_values(property_preferences.get("location_query"))
    selected_keyword_values = _csv_values(property_preferences.get("keywords"))
    country_options = [dict(option) for option in list(property_state.get("country_options") or []) if isinstance(option, dict)]
    language_options = [dict(option) for option in list(property_state.get("language_options") or []) if isinstance(option, dict)]
    listing_mode_options = [dict(option) for option in list(property_state.get("listing_mode_options") or []) if isinstance(option, dict)]
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
    location_options = _merge_option_catalog(_property_location_options(str(property_preferences.get("country_code") or "AT")), selected_location_values)
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
    property_source_rows = [
        row_item(
            str(source.get("source_label") or source.get("source_url") or "Source").strip(),
            " | ".join(
                part
                for part in (
                    f"{int(source.get('listing_total') or 0)} listings",
                    f"{int(source.get('high_fit_total') or 0)} high-fit",
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
        for candidate in list(source.get("top_candidates") or [])[:3]:
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
            if review_url:
                row["action_href"] = review_url
                row["action_method"] = "get"
                row["action_label"] = "Review packet"
            if tour_url:
                if row.get("action_href"):
                    row["secondary_action_href"] = tour_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Open 360"
                else:
                    row["action_href"] = tour_url
                    row["action_method"] = "get"
                    row["action_label"] = "Open 360"
            if property_url:
                if row.get("secondary_action_href"):
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
        property_results_value = int(property_preferences.get("max_results_per_source") or property_plan_max_results)
    except Exception:
        property_results_value = property_plan_max_results
    property_results_value = max(1, min(property_results_value, property_plan_max_results))
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
            },
            {
                "type": "select",
                "name": "language_code",
                "label": "Research language",
                "value": str(property_preferences.get("language_code") or "de"),
                "options": language_options,
            },
            {
                "type": "select",
                "name": "listing_mode",
                "label": "Search mode",
                "value": str(property_preferences.get("listing_mode") or "rent"),
                "options": listing_mode_options,
            },
            {
                "type": "select",
                "name": "property_type",
                "label": "Property type",
                "value": str(property_preferences.get("property_type") or "any"),
                "options": property_type_options,
            },
            {
                "type": "checkbox_group",
                "name": "location_query",
                "label": "Target areas",
                "options": location_options,
                "values": selected_location_values,
            },
            {
                "type": "checkbox_group",
                "name": "selected_platforms",
                "label": "Platforms",
                "options": platform_options,
                "values": list(selected_platforms),
            },
            {
                "type": "checkbox_group",
                "name": "keywords",
                "label": "What matters",
                "options": keyword_options,
                "values": selected_keyword_values,
            },
            {
                "type": "text",
                "name": "preference_person_id",
                "label": "Preference profile",
                "value": str(property_preferences.get("preference_person_id") or "self"),
                "placeholder": "self",
            },
            {
                "type": "number",
                "name": "max_price_eur",
                "label": "Max budget",
                "value": str(property_preferences.get("max_price_eur") or ""),
                "min": "1",
            },
            {
                "type": "number",
                "name": "min_rooms",
                "label": "Min rooms",
                "value": str(property_preferences.get("min_rooms") or ""),
                "min": "1",
            },
            {
                "type": "number",
                "name": "min_area_m2",
                "label": "Min area m2",
                "value": str(property_preferences.get("min_area_m2") or ""),
                "min": "1",
            },
            {
                "type": "number",
                "name": "max_results_per_source",
                "label": "Max results per source",
                "value": str(property_results_value),
                "min": "1",
                "max": str(property_plan_max_results),
            },
            {
                "type": "checkbox",
                "name": "force_refresh",
                "label": "Force fresh crawl",
                "value": "true",
                "checked": bool(property_preferences.get("force_refresh")),
            },
        ],
        "meta": {
            "preferences_endpoint": str(property_state.get("preferences_endpoint") or ""),
            "start_endpoint": str(property_state.get("start_endpoint") or ""),
            "run_id": str(property_run.get("run_id") or ""),
            "initial_run": property_run,
            "platform_catalog_by_country": dict(property_state.get("platform_catalog_by_country") or {}),
            "default_language_by_country": dict(property_state.get("default_language_by_country") or {}),
            "commercial": dict(property_state.get("commercial") or {}),
            "billing_checkout_enabled": bool(property_state.get("billing_checkout_enabled")),
            "billing_checkout_enabled_plans": list(property_state.get("billing_checkout_enabled_plans") or []),
            "billing_checkout_provider": str(property_state.get("billing_checkout_provider") or ""),
            "billing_checkout_provider_label": str(property_state.get("billing_checkout_provider_label") or ""),
            "billing_order_endpoint": str(property_state.get("billing_order_endpoint") or ""),
            "feedback_person_id": str(property_preferences.get("preference_person_id") or "self"),
            "shortlist_candidates": property_shortlist_cards,
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
                    "title": "Best candidates to review now",
                    "body": "A flagship flow should open with ranked review packets, not just crawl counters. The top row should explain the fit and give the user the next useful action immediately.",
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
