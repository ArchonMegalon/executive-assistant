from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from app.db import get_db
from app.gog import gog_cli
from app.tools.markupgo_client import MarkupGoClient


_PUBLISHERS: dict[str, tuple[str, ...]] = {
    "The Economist": ("economist.com",),
    "The Atlantic": ("theatlantic.com", "atlantic.com"),
    "The New York Times": ("nytimes.com",),
}

_INTERESTING_RE = re.compile(
    r"(?i)\b(ai|artificial intelligence|policy|economy|market|geopolit|war|energy|europe|china|usa|tech|automation|productivity|science|strategy|risk)\b"
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\\-]{3,}")
_STOP = {
    "with", "from", "that", "this", "have", "your", "their", "will", "about", "into", "over", "after",
    "would", "could", "should", "today", "tomorrow", "meeting", "review", "update", "thread", "email",
    "calendar", "event", "task", "notes", "briefing", "assistant", "executive",
}


@dataclass
class Article:
    publisher: str
    domain: str
    title: str
    url: str
    summary: str
    published_at: str
    score: float


def _publisher_for_domain(domain: str) -> str | None:
    d = (domain or "").lower().strip()
    for name, needles in _PUBLISHERS.items():
        if any(n in d for n in needles):
            return name
    return None


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _extract_json_list(text: str) -> list[Any]:
    try:
        clean = (text or "").strip()
        m = re.search(r"\[[\s\S]*\]", clean)
        if not m:
            return []
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


def _tokenize(text: str) -> list[str]:
    vals: list[str] = []
    for m in _WORD_RE.finditer((text or "").lower()):
        w = m.group(0)
        if w in _STOP:
            continue
        vals.append(w)
    return vals


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for val in node.values():
            yield from _walk(val)
    elif isinstance(node, list):
        for val in node:
            yield from _walk(val)


def _extract_articles_from_payload(payload: dict[str, Any], default_ts: str) -> list[Article]:
    out: list[Article] = []
    seen: set[str] = set()
    for obj in _walk(payload):
        if not isinstance(obj, dict):
            continue
        url = _as_text(obj.get("url") or obj.get("link") or obj.get("article_url"))
        if not url.startswith("http"):
            continue
        domain = (urlparse(url).netloc or "").lower()
        publisher = _publisher_for_domain(domain) or _as_text(obj.get("publisher") or obj.get("source") or obj.get("site"))
        publisher = _publisher_for_domain(publisher) or _publisher_for_domain(domain)
        if not publisher:
            continue
        title = _as_text(
            obj.get("title")
            or obj.get("headline")
            or obj.get("name")
            or obj.get("article_title")
        )
        if not title:
            continue
        summary = _as_text(
            obj.get("summary")
            or obj.get("excerpt")
            or obj.get("description")
            or obj.get("content")
        )
        published_at = _as_text(
            obj.get("published_at")
            or obj.get("published")
            or obj.get("date")
            or obj.get("timestamp")
            or default_ts
        )
        key = f"{url}|{title.lower()[:120]}"
        if key in seen:
            continue
        seen.add(key)
        score = 1.0
        if _INTERESTING_RE.search(f"{title} {summary}"):
            score += 1.0
        score += min(1.0, len(summary) / 500.0)
        out.append(
            Article(
                publisher=publisher,
                domain=domain,
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                score=score,
            )
        )
    return out


def fetch_browseract_articles(
    *,
    tenant_candidates: list[str],
    lookback_days: int = 7,
    max_events: int = 120,
) -> list[Article]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
    db = get_db()
    rows = db.fetchall(
        """
        SELECT tenant, event_type, payload_json, created_at
        FROM external_events
        WHERE source='browseract'
          AND created_at >= %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (since, max_events),
    )
    if not rows:
        return []
    allowed = {x.strip() for x in tenant_candidates if x and x.strip()}
    articles: list[Article] = []
    for row in rows:
        tenant = _as_text(row.get("tenant"))
        if allowed and tenant not in allowed:
            continue
        payload = row.get("payload_json") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            continue
        created = _as_text(row.get("created_at"))
        articles.extend(_extract_articles_from_payload(payload, created))
    dedup: dict[str, Article] = {}
    for a in sorted(articles, key=lambda x: x.score, reverse=True):
        if a.url not in dedup:
            dedup[a.url] = a
    return list(dedup.values())


def select_interesting(articles: list[Article], *, max_items: int = 12, signal_terms: set[str] | None = None) -> list[Article]:
    if not articles:
        return []
    sig = {s.lower().strip() for s in (signal_terms or set()) if s}
    rescored: list[Article] = []
    for a in articles:
        sc = a.score
        if sig:
            blob = f"{a.title} {a.summary}".lower()
            hits = 0
            for t in sig:
                if len(t) < 4:
                    continue
                if t in blob:
                    hits += 1
            if hits:
                sc += min(1.5, 0.35 * hits)
        rescored.append(
            Article(
                publisher=a.publisher,
                domain=a.domain,
                title=a.title,
                url=a.url,
                summary=a.summary,
                published_at=a.published_at,
                score=sc,
            )
        )
    buckets: dict[str, list[Article]] = {}
    for a in rescored:
        buckets.setdefault(a.publisher, []).append(a)
    for arr in buckets.values():
        arr.sort(key=lambda x: x.score, reverse=True)
    selected: list[Article] = []
    for pub in ("The Economist", "The Atlantic", "The New York Times"):
        if pub in buckets and buckets[pub]:
            selected.append(buckets[pub].pop(0))
    rest: list[Article] = []
    for arr in buckets.values():
        rest.extend(arr)
    rest.sort(key=lambda x: x.score, reverse=True)
    selected.extend(rest[: max(0, max_items - len(selected))])
    return selected[:max_items]


def _pdf_html(articles: list[Article], title: str) -> str:
    cards = []
    for idx, a in enumerate(articles, start=1):
        summary = a.summary[:460] + ("..." if len(a.summary) > 460 else "")
        cards.append(
            f"""
            <section class="card">
              <div class="meta">{idx}. {a.publisher} | {a.domain}</div>
              <h2>{a.title}</h2>
              <p>{summary or "No summary provided by BrowserAct."}</p>
              <p><a href="{a.url}">{a.url}</a></p>
            </section>
            """
        )
    cards_html = "\n".join(cards)
    return f"""
    <html>
      <body>
        <div class="wrap">
          <header>
            <h1>{title}</h1>
            <div class="sub">Curated from BrowserAct | Economist / Atlantic / NYT</div>
          </header>
          {cards_html}
        </div>
      </body>
      <style>
        body {{
          font-family: Arial, Helvetica, sans-serif;
          background: linear-gradient(180deg, #f5f7fa 0%, #ffffff 30%);
          color: #101418;
          margin: 0;
          padding: 30px;
        }}
        .wrap {{ max-width: 1050px; margin: 0 auto; }}
        header {{
          padding: 20px 24px;
          border: 1px solid #d8dee8;
          border-radius: 14px;
          background: #f8fbff;
          margin-bottom: 18px;
        }}
        h1 {{ margin: 0; font-size: 34px; }}
        .sub {{ margin-top: 6px; color: #3f4c5a; font-size: 14px; }}
        .card {{
          border: 1px solid #dce3ec;
          border-radius: 14px;
          padding: 16px 18px;
          margin: 12px 0;
          background: white;
        }}
        .meta {{ color: #48607a; font-size: 12px; letter-spacing: 0.02em; }}
        h2 {{ margin: 8px 0 10px 0; font-size: 22px; line-height: 1.25; }}
        p {{ margin: 8px 0; line-height: 1.45; font-size: 14px; }}
        a {{ color: #0b5ea8; text-decoration: none; word-break: break-all; }}
      </style>
    </html>
    """


async def render_articles_pdf(articles: list[Article], *, title: str) -> bytes:
    html_doc = _pdf_html(articles, title)
    mg = MarkupGoClient()
    payload = {
        "source": {"type": "html", "data": html_doc},
        "options": {},
    }
    return await asyncio.wait_for(mg.render_pdf_buffer(payload, timeout_s=45.0), timeout=60.0)


async def collect_user_signal_terms(*, openclaw_container: str, google_account: str) -> set[str]:
    if not openclaw_container:
        return set()
    texts: list[str] = []

    async def _run(cmd: list[str], timeout: float = 8.0) -> None:
        try:
            out = await asyncio.wait_for(gog_cli(openclaw_container, cmd, google_account or ""), timeout=timeout)
            rows = _extract_json_list(out)
            for row in rows[:20]:
                if not isinstance(row, dict):
                    continue
                texts.append(
                    " ".join(
                        [
                            _as_text(row.get("summary")),
                            _as_text(row.get("title")),
                            _as_text(row.get("subject")),
                            _as_text(row.get("snippet")),
                        ]
                    )
                )
        except Exception:
            return

    await _run(["calendar", "events", "list", "primary", "--limit", "25", "--json"], timeout=9.0)
    await _run(["tasks", "list", "--limit", "25", "--json"], timeout=9.0)
    await _run(["gmail", "messages", "search", "newer_than:3d", "--limit", "30", "--json"], timeout=10.0)

    words: dict[str, int] = {}
    for txt in texts:
        for w in _tokenize(txt):
            words[w] = words.get(w, 0) + 1
    top = sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:30]
    return {k for k, _ in top}
