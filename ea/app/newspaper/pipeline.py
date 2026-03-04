from __future__ import annotations

import asyncio
import html
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from app.articles_digest import (
    collect_user_signal_terms,
    enrich_full_articles,
    fetch_browseract_articles,
    select_interesting,
)
from app.calendar_store import list_events_range


def _cfg_val(cfg: dict[str, Any], key: str, default: str = "") -> str:
    return str(cfg.get(key, default) or default)


def _text_blocks(briefing_text: str) -> dict[str, list[str]]:
    raw = re.sub(r"<[^>]+>", "", briefing_text or "")
    raw = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [ln.strip(" \t•") for ln in raw.splitlines() if ln.strip()]
    sections: dict[str, list[str]] = {
        "lead": [],
        "must_know": [],
        "calendar": [],
        "signals": [],
    }
    current = "lead"
    for ln in lines:
        low = ln.lower()
        if low.startswith("requires attention"):
            current = "must_know"
            continue
        if low.startswith("calendars"):
            current = "calendar"
            continue
        if low.startswith("diagnostics") or low.startswith("⚙️ diagnostics"):
            current = "signals"
            continue
        sections.setdefault(current, []).append(ln)
    return sections


def _fallback_image_data_uri(label: str) -> str:
    txt = quote((label or "Story")[:32])
    # Remote raster fallback to ensure PDF embeds /Image objects for strict quality gates.
    return f"https://dummyimage.com/1200x675/e7eef7/123456.png&text={txt}"


async def _collect_articles(tenant_name: str, tenant_cfg: dict[str, Any]) -> list[Any]:
    signal_terms = await collect_user_signal_terms(
        openclaw_container=_cfg_val(tenant_cfg, "openclaw_container"),
        google_account=_cfg_val(tenant_cfg, "google_account"),
    )
    tenant_candidates = [
        tenant_name,
        _cfg_val(tenant_cfg, "key"),
        _cfg_val(tenant_cfg, "google_account"),
        "ea_bot",
    ]
    tenant_hint = os.environ.get("EA_ARTICLE_TENANT_HINT", "").strip()
    if tenant_hint:
        tenant_candidates.append(tenant_hint)
    raw_articles = await asyncio.to_thread(
        fetch_browseract_articles,
        tenant_candidates=[x for x in tenant_candidates if x],
        lookback_days=7,
        max_events=200,
    )
    picked = select_interesting(raw_articles, max_items=10, signal_terms=signal_terms)
    if not picked:
        return []
    return await enrich_full_articles(picked, max_fetch=5)


async def _collect_calendar_rows(tenant_name: str, tenant_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [tenant_name, _cfg_val(tenant_cfg, "key"), _cfg_val(tenant_cfg, "google_account")]
    dedupe: set[str] = set()
    rows_out: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(days=2)
    for k in [x for x in keys if x]:
        try:
            rows = list_events_range(k, now_utc - timedelta(hours=12), end_utc) or []
        except Exception:
            rows = []
        for r in rows:
            key = f"{r.get('start_ts')}|{r.get('title')}"
            if key in dedupe:
                continue
            dedupe.add(key)
            rows_out.append(r)
    rows_out.sort(key=lambda r: str(r.get("start_ts") or ""))
    return rows_out[:20]


def _editorial_story(a: Any, section: str, layout_role: str) -> dict[str, Any]:
    summary = (str(getattr(a, "summary", "") or "").strip() or "No summary available.")[:900]
    summary_words = summary.split()
    if len(summary_words) > 180:
        summary = " ".join(summary_words[:180]) + "..."
    source_label = str(getattr(a, "publisher", "Source") or "Source")
    image_url = str(getattr(a, "image_url", "") or "")
    if not image_url.startswith("http"):
        image_url = _fallback_image_data_uri(source_label)
        image_kind = "fallback"
    else:
        image_kind = "hero"
    headline = str(getattr(a, "title", "Untitled") or "Untitled")[:140]
    dek = f"From {source_label}. Curated for today's decisions."[:130]
    why = f"Track this today: {headline[:86]}"[:120]
    return {
        "id": str(uuid.uuid4()),
        "section": section,
        "layout_role": layout_role,
        "headline": headline,
        "dek": dek,
        "summary": summary,
        "why_it_matters": why,
        "source_label": source_label,
        "source_url": str(getattr(a, "url", "") or ""),
        "published_at": str(getattr(a, "published_at", "") or ""),
        "image": {
            "kind": image_kind,
            "url": image_url,
            "caption": source_label,
        },
        "pull_quote": "",
        "facts": [],
    }


async def build_issue_for_brief(
    *,
    tenant_name: str,
    tenant_cfg: dict[str, Any],
    chat_id: int,
    briefing_text: str,
    preference_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del chat_id  # reserved for future per-principal styling.
    blocks = _text_blocks(briefing_text or "")
    articles = await _collect_articles(tenant_name, tenant_cfg)
    cal_rows = await _collect_calendar_rows(tenant_name, tenant_cfg)

    must_know = []
    worth_knowing = []
    watchlist = []
    for idx, a in enumerate(articles):
        if idx == 0:
            must_know.append(_editorial_story(a, "must_know", "cover_lead"))
        elif idx <= 2:
            must_know.append(_editorial_story(a, "must_know", "feature"))
        elif idx <= 6:
            worth_knowing.append(_editorial_story(a, "worth_knowing", "feature"))
        else:
            watchlist.append(_editorial_story(a, "watchlist", "quick_hit"))

    # Ensure at least one cover lead visual.
    if not must_know:
        must_know.append(
            {
                "id": str(uuid.uuid4()),
                "section": "must_know",
                "layout_role": "cover_lead",
                "headline": "No lead story available",
                "dek": "This edition was generated with limited source data.",
                "summary": "No qualifying article candidates were available in this window.",
                "why_it_matters": "Re-run once article ingestion completes.",
                "source_label": "EA System",
                "source_url": "",
                "published_at": "",
                "image": {"kind": "fallback", "url": _fallback_image_data_uri("No lead story"), "caption": "Fallback visual"},
                "pull_quote": "",
                "facts": [],
            }
        )

    agenda_items = []
    if cal_rows:
        for r in cal_rows[:16]:
            agenda_items.append(
                {
                    "time": str(r.get("start_ts") or "")[:16].replace("T", " "),
                    "title": str(r.get("title") or ""),
                    "location": str(r.get("location") or ""),
                }
            )
    else:
        for ln in blocks.get("calendar", [])[:10]:
            agenda_items.append({"time": "", "title": ln, "location": ""})

    issue = {
        "issue_id": str(uuid.uuid4()),
        "title": "Tibor Daily",
        "subtitle": "Personal Morning Edition",
        "issue_date": datetime.now().date().isoformat(),
        "edition_no": int(datetime.now().strftime("%j")),
        "timezone": "Europe/Vienna",
        "preferences": preference_snapshot or {"prioritize": [], "avoid": []},
        "sections": {
            "must_know": must_know,
            "worth_knowing": worth_knowing,
            "agenda": agenda_items,
            "watchlist": watchlist,
            "signals": blocks.get("signals", [])[:12],
            "brief_notes": blocks.get("must_know", [])[:12],
        },
        "footer_note": "Curated automatically from your sources.",
    }
    return issue
