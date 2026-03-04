from __future__ import annotations
import asyncio
import base64
import contextlib
import html
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from app.config import get_tenant, get_admin_chat_id, load_tenants, tenant_by_chat_id
from app.gog import gog_scout, gog_cli, docker_exec
from app.settings import settings
from app.telegram import TelegramClient
from app.vision import extract_calendar_from_image
from app.sepa_qr import generate_epc_qr
from app.sepa_xml import generate_pain001_xml
from app.open_loops import OpenLoops
from app.briefings import build_briefing_for_tenant, get_val
from app.articles_digest import fetch_browseract_articles, select_interesting, render_articles_pdf, collect_user_signal_terms, enrich_full_articles
from app.memory import get_button_context, save_button_context
from app.render_guard import classify_markupgo_error, log_render_guard, markupgo_breaker_open, open_markupgo_breaker, promote_known_good_template_if_needed
from app.repair.healer import system_health_snapshot
from app.policy.household import gate_household_document_action
from app.intake.survey_planner import plan_article_preference_survey, plan_briefing_feedback_survey
from app.intake.calendar_import_result import build_calendar_import_response
from app.intake.calendar_events import normalize_extracted_calendar_events
from app.contracts.repair import open_repair_incident
from app.chat_assist import ask_llm_text as _ask_llm_text, humanize_agent_report as _humanize_agent_report
from app.telegram_menu import bot_commands as _bot_commands, menu_text as _menu_text, mumbrain_user_visible as _mumbrain_user_visible
from app.auth_sessions import AuthSessionStore
from app.brief_commands import brief_command_throttled as _brief_command_throttled, brief_enter as _brief_enter, brief_exit as _brief_exit
from app.briefing_delivery_sessions import create_briefing_delivery_session, activate_briefing_delivery_session
from app.offset_store import atomic_write_offset, read_offset
from app.watchdog import heartbeat_pinger, mark_heartbeat, start_watchdog_thread
from app.update_router import route_update


start_watchdog_thread(
    get_admin_chat_id=get_admin_chat_id,
    telegram_bot_token=getattr(settings, "telegram_bot_token", None),
)
tg = TelegramClient(settings.telegram_bot_token)
MENU_REGISTERED = False

async def _ensure_bot_command_menu():
    global MENU_REGISTERED
    if MENU_REGISTERED or not settings.telegram_bot_token:
        return
    try:
        await tg.set_my_commands(_bot_commands())
        MENU_REGISTERED = True
    except Exception:
        pass

AUTH_SESSIONS = AuthSessionStore(path='/attachments/auth_sessions.json', ttl_sec=900)

def clean_html_for_telegram(text: str) -> str:
    if not text:
        return ''
    t = text.replace('<br>', '\n').replace('<br/>', '\n').replace('</p>', '\n\n').replace('<p>', '')
    t = t.replace('<ul>', '').replace('</ul>', '').replace('<ol>', '').replace('</ol>', '')
    t = t.replace('<li>', '• ').replace('</li>', '\n').replace('<h1>', '\n\n<b>').replace('</h1>', '</b>\n').replace('<h2>', '\n\n<b>').replace('</h2>', '</b>\n')
    t = t.replace('<strong>', '<b>').replace('</strong>', '</b>').replace('<em>', '<i>').replace('</em>', '</i>')
    t = t.replace('<html>', '').replace('</html>', '').replace('<body>', '').replace('</body>', '').replace('<div>', '').replace('</div>', '')
    t = re.sub('&(?![A-Za-z0-9#]+;)', '&amp;', t)

    def repl(m):
        tag = m.group(1).lower()
        if tag in ['b', 'i', 'a', 'code', 'pre', 's', 'u']:
            return m.group(0)
        return ''
    t = re.sub('</?([a-zA-Z0-9]+)[^>]*>', repl, t)
    return re.sub('\\n{3,}', '\n\n', t).strip()


def _safe_err(e) -> str:
    return html.escape(str(e), quote=False)

def _incident_ref(prefix: str = "EA") -> str:
    return f"{prefix}-{int(time.time())}"


def _count_pdf_images(pdf_reader) -> int:
    total = 0
    for page in getattr(pdf_reader, "pages", []):
        try:
            res = page.get("/Resources") or {}
            xobj = res.get("/XObject") if hasattr(res, "get") else None
            if xobj is None:
                continue
            try:
                xobj = xobj.get_object()
            except Exception:
                pass
            if not hasattr(xobj, "items"):
                continue
            for _, obj in xobj.items():
                try:
                    target = obj.get_object()
                except Exception:
                    target = obj
                subtype = ""
                try:
                    subtype = str(target.get("/Subtype") or "")
                except Exception:
                    subtype = ""
                if subtype == "/Image":
                    total += 1
        except Exception:
            continue
    return total


def _validate_newspaper_pdf_bytes(pdf_bytes: bytes, *, min_pages: int = 4, min_images: int = 3) -> tuple[bool, str]:
    try:
        import io
        from pypdf import PdfReader
    except Exception as e:
        return False, f"pdf_validation_dependency_missing:{e}"
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        if page_count < min_pages:
            return False, f"page_count:{page_count}<min:{min_pages}"
        first_text = ""
        try:
            first_text = str(reader.pages[0].extract_text() or "")
        except Exception:
            first_text = ""
        if "Tibor Daily" not in first_text:
            return False, "missing_masthead:Tibor Daily"
        image_count = _count_pdf_images(reader)
        if image_count < min_images:
            return False, f"image_count:{image_count}<min:{min_images}"
        blob = first_text[:8000]
        for banned in ("OODA Diagnostic", "statusCode", "FST_ERR_VALIDATION", "Traceback"):
            if banned in blob:
                return False, f"banned_token:{banned}"
        return True, f"ok:pages={page_count},images={image_count}"
    except Exception as e:
        return False, f"pdf_validation_error:{e}"


def _household_confidence_for_message(chat_id: int, msg: dict) -> float:
    try:
        override = (os.getenv('EA_HOUSEHOLD_CONFIDENCE_OVERRIDE', '') or '').strip()
        if override:
            return max(0.0, min(1.0, float(override)))
    except Exception:
        pass
    confidence = 0.99
    chat_type = str((msg.get('chat') or {}).get('type') or '').lower()
    if chat_type in ('group', 'supergroup', 'channel'):
        confidence = min(confidence, 0.70)
    if msg.get('forward_origin') or msg.get('forward_from') or msg.get('forward_from_chat'):
        confidence = min(confidence, 0.70)
    sender_id = str((msg.get('from') or {}).get('id') or '')
    if sender_id and sender_id != str(chat_id):
        confidence = min(confidence, 0.75)
    return confidence


def _message_document_ref(chat_id: int, msg: dict, doc: dict | None, photo: list | None) -> tuple[str, str]:
    file_id = ''
    if doc and doc.get('file_id'):
        file_id = str(doc.get('file_unique_id') or doc.get('file_id') or '')
    elif photo and isinstance(photo, list):
        last = photo[-1] if photo else {}
        file_id = str(last.get('file_unique_id') or last.get('file_id') or '')
    message_id = str(msg.get('message_id') or '0')
    document_id = file_id or f'chat{chat_id}_msg{message_id}'
    raw_ref = f'telegram:chat:{chat_id}:message:{message_id}:file:{file_id or "none"}'
    return document_id, raw_ref

async def check_security(chat_id: int) -> tuple[str, dict]:
    t = get_tenant(chat_id)
    if t:
        return (str(get_val(t, 'key', f'chat_{chat_id}')), t)
    try:
        if __import__('os').path.exists('/attachments/dynamic_users.json'):
            with open('/attachments/dynamic_users.json', 'r') as f:
                dt = json.load(f)
            if str(chat_id) in dt:
                u_info = dt[str(chat_id)]
                default_openclaw = os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway")
                return (
                    f'guest_{chat_id}',
                    {
                        'key': f'guest_{chat_id}',
                        'label': u_info.get('name', 'Guest'),
                        'google_account': u_info.get('email', ''),
                        'openclaw_container': default_openclaw,
                        'is_admin': u_info.get('is_admin', False),
                    },
                )
    except:
        pass
    return (None, None)


async def _send_browseract_articles_pdf(chat_id: int, tenant_name: str, tenant_cfg: dict, *, force: bool = False) -> bool:
    try:
        signal_terms = await collect_user_signal_terms(
            openclaw_container=get_val(tenant_cfg, 'openclaw_container', ''),
            google_account=get_val(tenant_cfg, 'google_account', ''),
        )
        tenant_candidates = [
            tenant_name,
            get_val(tenant_cfg, 'key', ''),
            get_val(tenant_cfg, 'google_account', ''),
            'ea_bot',
        ]
        tenant_hint = os.environ.get("EA_ARTICLE_TENANT_HINT", "").strip()
        if tenant_hint:
            tenant_candidates.append(tenant_hint)
        articles = await asyncio.to_thread(
            fetch_browseract_articles,
            tenant_candidates=[x for x in tenant_candidates if x],
            lookback_days=7,
            max_events=180,
        )
        picked = select_interesting(articles, max_items=12, signal_terms=signal_terms)
        if not picked:
            if force:
                await tg.send_message(chat_id, '🗞️ No recent BrowserAct articles found yet for Economist/Atlantic/NYT.')
            return False
        picked = await enrich_full_articles(picked, max_fetch=6)
        title = f"Executive Reading Brief | {datetime.now().strftime('%Y-%m-%d')}"
        pdf_bytes = await render_articles_pdf(picked, title=title)
        filename = f"EA_Reading_Brief_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        caption = f"🗞️ <b>{len(picked)} interesting articles</b> from Economist / Atlantic / NYT."
        await tg.send_document(chat_id, pdf_bytes, filename, caption=caption, parse_mode='HTML')
        refs = [{"title": a.title[:160], "url": a.url[:360], "publisher": a.publisher} for a in picked[:8]]
        principal = get_val(tenant_cfg, 'google_account', '') or str(chat_id)
        tenant_for_survey = get_val(tenant_cfg, 'google_account', '') or tenant_name
        asyncio.create_task(plan_article_preference_survey(tenant=tenant_for_survey, principal=principal, article_refs=refs))
        return True
    except Exception as e:
        log_render_guard('articles_pdf_failed', str(e)[:140], location='poll_listener')
        if force:
            await tg.send_message(chat_id, f'⚠️ Articles PDF failed: {_safe_err(e)}')
        return False

async def _collect_briefing_articles(tenant_name: str, tenant_cfg: dict) -> list:
    try:
        signal_terms = await collect_user_signal_terms(
            openclaw_container=get_val(tenant_cfg, 'openclaw_container', ''),
            google_account=get_val(tenant_cfg, 'google_account', ''),
        )
        tenant_candidates = [
            tenant_name,
            get_val(tenant_cfg, 'key', ''),
            get_val(tenant_cfg, 'google_account', ''),
            'ea_bot',
        ]
        tenant_hint = os.environ.get("EA_ARTICLE_TENANT_HINT", "").strip()
        if tenant_hint:
            tenant_candidates.append(tenant_hint)
        articles = await asyncio.to_thread(
            fetch_browseract_articles,
            tenant_candidates=[x for x in tenant_candidates if x],
            lookback_days=7,
            max_events=180,
        )
        picked = select_interesting(articles, max_items=8, signal_terms=signal_terms)
        if not picked:
            return []
        return await enrich_full_articles(picked, max_fetch=4)
    except Exception:
        return []

def _briefing_newspaper_html(briefing_text: str, tenant_name: str, pref_snapshot: dict | None = None, articles: list | None = None) -> str:
    raw = re.sub('<[^>]+>', '', briefing_text or '')
    raw = raw.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    sections: dict[str, list[str]] = {"Lead": [], "Must know": [], "Calendar": [], "Signals": []}
    current = "Lead"
    for ln in lines:
        low = ln.lower()
        if low.startswith('requires attention'):
            current = "Must know"
            continue
        if low.startswith('calendars'):
            current = "Calendar"
            continue
        if low.startswith('⚙️ diagnostics') or low.startswith('diagnostics'):
            current = "Signals"
            continue
        sections.setdefault(current, []).append(ln)

    def _items_html(items: list[str], limit: int = 10) -> str:
        out = []
        for i, item in enumerate(items[:limit], start=1):
            clean = html.escape(item)
            out.append(f"<li><span class='idx'>{i:02d}</span><span>{clean}</span></li>")
        return "\n".join(out) if out else "<li><span>No items.</span></li>"

    today = datetime.now().strftime("%A, %d %B %Y")
    title = f"{tenant_name.title()} Personal Newspaper"
    pref_snapshot = pref_snapshot or {}
    pref_positive = pref_snapshot.get("prioritize") or []
    pref_avoid = pref_snapshot.get("avoid") or []
    pref_html = (
        f"<div><b>Prioritize:</b> {html.escape(', '.join(pref_positive[:8]) or 'none')}</div>"
        f"<div><b>Avoid:</b> {html.escape(', '.join(pref_avoid[:8]) or 'none')}</div>"
    )
    story_rows = []
    for i, a in enumerate((articles or [])[:8], start=1):
        title = html.escape(str(getattr(a, "title", "") or "Untitled"))
        publisher = html.escape(str(getattr(a, "publisher", "") or "Unknown"))
        url = html.escape(str(getattr(a, "url", "") or ""))
        summary = str(getattr(a, "summary", "") or "").strip()
        if len(summary) > 260:
            summary = summary[:260] + "..."
        summary = html.escape(summary or "No summary available.")
        story_rows.append(
            f"""
            <article class="story">
              <div class="story-meta">{i:02d} | {publisher}</div>
              <h4>{title}</h4>
              <p>{summary}</p>
              <p><a href="{url}">{url}</a></p>
            </article>
            """
        )
    stories_html = "\n".join(story_rows) if story_rows else "<p class='empty'>No recent qualifying articles.</p>"
    return f"""
    <html>
      <body>
        <div class="page">
          <header class="masthead">
            <div class="kicker">Executive Morning Edition</div>
            <h1>{html.escape(title)}</h1>
            <div class="meta">{html.escape(today)} | EA Concierge Desk</div>
          </header>
          <section class="lead">
            <h2>Lead</h2>
            <div class="lead-copy">{html.escape(' '.join(sections.get('Lead', [])[:8])) or 'No lead available.'}</div>
          </section>
          <section class="grid">
            <article class="card">
              <h3>Must know</h3>
              <ul>{_items_html(sections.get("Must know", []), limit=12)}</ul>
            </article>
            <article class="card">
              <h3>Calendar</h3>
              <ul>{_items_html(sections.get("Calendar", []), limit=14)}</ul>
            </article>
          </section>
          <section class="signals">
            <h3>Signals</h3>
            <ul>{_items_html(sections.get("Signals", []), limit=10)}</ul>
          </section>
          <section class="prefs">
            <h3>Preference Lens</h3>
            {pref_html}
          </section>
          <section class="stories">
            <h3>Interesting Articles</h3>
            {stories_html}
          </section>
        </div>
      </body>
      <style>
        @page {{ size: A4; margin: 14mm; }}
        body {{
          margin: 0;
          color: #102030;
          font-family: "Georgia", "Times New Roman", serif;
          background:
            radial-gradient(1200px 300px at 10% -15%, #dbeeff 0, transparent 55%),
            linear-gradient(180deg, #f8fbff 0, #ffffff 45%);
        }}
        .page {{ max-width: 980px; margin: 0 auto; }}
        .masthead {{
          border-bottom: 4px solid #0d3b66;
          padding-bottom: 8px;
          margin-bottom: 14px;
        }}
        .kicker {{
          font: 700 12px/1.2 "Arial", sans-serif;
          letter-spacing: .12em;
          text-transform: uppercase;
          color: #0d3b66;
        }}
        h1 {{
          margin: 4px 0 4px 0;
          font-size: 42px;
          line-height: 1.05;
          letter-spacing: .01em;
        }}
        .meta {{
          font: 500 12px/1.2 "Arial", sans-serif;
          color: #334e68;
        }}
        .lead {{
          background: #ffffff;
          border: 1px solid #d8e2ef;
          border-left: 7px solid #0d3b66;
          border-radius: 8px;
          padding: 10px 12px;
          margin-bottom: 12px;
        }}
        h2 {{ margin: 0 0 8px 0; font-size: 24px; }}
        .lead-copy {{ font-size: 16px; line-height: 1.4; white-space: pre-wrap; }}
        .grid {{
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-bottom: 12px;
        }}
        .card {{
          background: #fff;
          border: 1px solid #d8e2ef;
          border-radius: 8px;
          padding: 10px 12px;
        }}
        h3 {{
          margin: 0 0 8px 0;
          font-size: 22px;
          border-bottom: 1px solid #dbe4ef;
          padding-bottom: 4px;
        }}
        ul {{ list-style: none; margin: 0; padding: 0; }}
        li {{
          display: grid;
          grid-template-columns: 34px 1fr;
          gap: 6px;
          margin: 0 0 6px 0;
          font-size: 14px;
          line-height: 1.3;
          break-inside: avoid;
        }}
        .idx {{
          font: 700 11px/1.7 "Arial", sans-serif;
          color: #486581;
        }}
        .signals {{
          background: #fff;
          border: 1px solid #d8e2ef;
          border-radius: 8px;
          padding: 10px 12px;
          margin-bottom: 12px;
        }}
        .prefs {{
          background: #fff;
          border: 1px solid #d8e2ef;
          border-radius: 8px;
          padding: 10px 12px;
          font: 13px/1.45 "Arial", sans-serif;
          color: #213547;
        }}
        .stories {{
          background: #fff;
          border: 1px solid #d8e2ef;
          border-radius: 8px;
          padding: 10px 12px;
          margin-top: 12px;
        }}
        .story {{
          border-top: 1px solid #e5edf6;
          padding-top: 8px;
          margin-top: 8px;
        }}
        .story:first-of-type {{ border-top: 0; padding-top: 0; margin-top: 0; }}
        .story-meta {{
          font: 700 11px/1.3 "Arial", sans-serif;
          letter-spacing: .06em;
          color: #486581;
          text-transform: uppercase;
        }}
        h4 {{
          margin: 4px 0;
          font-size: 18px;
          line-height: 1.25;
        }}
        .story p {{
          margin: 4px 0;
          font: 13px/1.45 "Arial", sans-serif;
          color: #1f2f3f;
        }}
        .empty {{
          margin: 4px 0;
          font: 13px/1.45 "Arial", sans-serif;
          color: #52667a;
        }}
        a {{ color: #0b5ea8; text-decoration: none; word-break: break-all; }}
      </style>
    </html>
    """

async def _preference_snapshot(tenant_name: str, tenant_cfg: dict, chat_id: int) -> dict:
    prioritize: list[str] = []
    avoid: list[str] = []
    try:
        terms = await collect_user_signal_terms(
            openclaw_container=get_val(tenant_cfg, 'openclaw_container', ''),
            google_account=get_val(tenant_cfg, 'google_account', ''),
        )
        prioritize = sorted([t for t in terms if t and len(t) > 3])[:12]
    except Exception:
        pass
    try:
        from app.db import get_db
        db = get_db()
        tenant_keys = []
        for key in (tenant_name, get_val(tenant_cfg, 'google_account', '')):
            k = str(key or '').strip()
            if k and k not in tenant_keys:
                tenant_keys.append(k)
        rows = []
        for tk in tenant_keys:
            part = await asyncio.to_thread(
                db.fetchall,
                """
                SELECT concept_key, weight, hard_dislike
                FROM user_interest_profiles
                WHERE tenant_key=%s AND principal_id=%s
                ORDER BY hard_dislike DESC, weight ASC
                LIMIT 20
                """,
                (tk, str(chat_id)),
            ) or []
            rows.extend(part)
        for r in rows:
            c = str(r.get("concept_key") or "").strip()
            if not c:
                continue
            if bool(r.get("hard_dislike")) or float(r.get("weight") or 0.0) < -0.35:
                avoid.append(c)
            elif float(r.get("weight") or 0.0) > 0.25:
                prioritize.append(c)
    except Exception:
        pass
    # Keep list deterministic and compact.
    prioritize = list(dict.fromkeys(prioritize))[:12]
    avoid = list(dict.fromkeys(avoid))[:12]
    return {"prioritize": prioritize, "avoid": avoid}

async def _send_briefing_newspaper_pdf(chat_id: int, tenant_name: str, tenant_cfg: dict, briefing_text: str) -> bool:
    try:
        from app.tools.markupgo_client import MarkupGoClient
        from app.newspaper import build_issue_for_brief, render_issue_html, validate_issue
        pref = await _preference_snapshot(tenant_name, tenant_cfg, chat_id)
        issue = await build_issue_for_brief(
            tenant_name=tenant_name,
            tenant_cfg=tenant_cfg,
            chat_id=chat_id,
            briefing_text=briefing_text,
            preference_snapshot=pref,
        )
        errs = validate_issue(issue)
        if errs:
            log_render_guard("brief_newspaper_invalid_issue", "; ".join(errs)[:200], location="poll_listener")
            return False
        html_doc = render_issue_html(issue)
        mg = MarkupGoClient()
        payload = {"source": {"type": "html", "data": html_doc}, "options": {}}
        pdf_bytes = await mg.render_pdf_buffer(payload, timeout_s=60.0)
        if not pdf_bytes:
            return False
        ok, detail = _validate_newspaper_pdf_bytes(pdf_bytes, min_pages=4, min_images=3)
        if not ok:
            log_render_guard("brief_newspaper_pdf_quality_gate_failed", detail[:180], location="poll_listener")
            return False
        log_render_guard("brief_newspaper_pdf_quality_gate_passed", detail[:180], location="poll_listener")
        filename = f"{tenant_name}_Personal_Newspaper_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        await tg.send_document(chat_id, pdf_bytes, filename, caption="📰 <b>Your personal newspaper</b>", parse_mode='HTML')
        return True
    except Exception as e:
        log_render_guard('brief_newspaper_pdf_failed', str(e)[:140], location='poll_listener')
        return False

def build_dynamic_ui(report_text: str, context_prompt: str, fwd_name: str=None) -> dict:
    kb = []
    if fwd_name:
        if 'liz' in fwd_name.lower() or 'elisabeth' in fwd_name.lower():
            kb.append([{'text': f'🤖 Ask to reply to {fwd_name}', 'callback_data': f'fwd_liz:{save_button_context(report_text)}'}])
        else:
            kb.append([{'text': f'📤 Forward to {fwd_name}', 'url': f'https://t.me/share/url?url={urllib.parse.quote('Antwort:\n' + report_text)}'}])
    opt_match = re.search('\\[OPTIONS:\\s*(.+?)\\]', report_text)
    if opt_match:
        for opt in [o.strip() for o in opt_match.group(1).split('|') if o.strip()][:5]:
            is_rej = any((w in opt.lower() for w in ['do not', 'no', 'cancel', 'stop', 'abort', 'skip']))
            if is_rej:
                kb.append([{'text': f'🎯 {opt}', 'callback_data': f'act:{save_button_context(f'CONTINUING TASK:\n{context_prompt[:1500]}\n\nUser selected: {opt}. REJECTED. Propose alternatives.')}'}])
            else:
                kb.append([{'text': f'🎯 {opt}', 'callback_data': f'act:{save_button_context(f'CONTINUING TASK:\n{context_prompt[:1500]}\n\nUser selected: {opt}. Proceed.')}'}])
    return {'inline_keyboard': kb} if kb else None

async def handle_photo(chat_id: int, msg: dict):
    await handle_intent(chat_id, msg)


def _openclaw_candidates(t: dict) -> list[str]:
    configured = str(get_val(t, "openclaw_container", "") or "").strip()
    env_default = str(os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "") or "").strip()
    csv_fallback = str(os.environ.get("EA_OPENCLAW_FALLBACK_CONTAINERS", "") or "").strip()
    candidates: list[str] = []
    for raw in [configured, env_default]:
        c = str(raw or "").strip()
        if c and c not in candidates:
            candidates.append(c)
    if csv_fallback:
        for item in csv_fallback.split(","):
            c = str(item or "").strip()
            if c and c not in candidates:
                candidates.append(c)
    # Last-resort defaults for common gateway naming.
    for c in ("openclaw-gateway-tibor", "openclaw-gateway-family-girschele", "openclaw-gateway-liz", "openclaw-gateway"):
        if c not in candidates:
            candidates.append(c)
    return candidates


async def trigger_auth_flow(chat_id: int, email: str, t: dict, scopes: str=''):
    res = await tg.send_message(chat_id, f'🔄 Generating secure OAuth link for <b>{email}</b>...', parse_mode='HTML')
    candidates = _openclaw_candidates(t or {})
    is_admin = bool(get_val(t, 'is_admin', False)) or str(chat_id) == str(get_admin_chat_id() or "")
    try:
        scopes_arg = 'calendar' if 'cal' in scopes else 'gmail' if 'mail' in scopes else 'gmail,calendar,tasks'
        keyring_password = (
            getattr(settings, 'gog_keyring_password', None)
            or os.environ.get('GOG_KEYRING_PASSWORD')
            or os.environ.get('EA_GOG_KEYRING_PASSWORD')
        )
        if not keyring_password:
            raise RuntimeError('Missing GOG_KEYRING_PASSWORD')
        last_output = ""
        for t_openclaw in candidates:
            try:
                await docker_exec(t_openclaw, ['pkill', '-f', 'gog'], user='root', timeout_s=8.0)
                await asyncio.sleep(0.25)
                await docker_exec(t_openclaw, ['gog', 'auth', 'remove', email], user='root', timeout_s=10.0)
                await asyncio.sleep(0.25)
                out_str = await docker_exec(
                    t_openclaw,
                    ['gog', 'auth', 'add', email, '--services', scopes_arg, '--remote', '--step', '1'],
                    user='root',
                    extra_env={'GOG_KEYRING_PASSWORD': keyring_password},
                    timeout_s=18.0,
                )
                m_url = re.search('(https://accounts\\.google\\.com/[^\\s"\\\'><]+)', out_str)
                if m_url:
                    AUTH_SESSIONS.set(chat_id, {'email': email, 'openclaw': t_openclaw, 'services': scopes_arg, 'ts': time.time()})
                    admin_note = f'\n\n💡 <b>Admin Troubleshooting:</b>\nEnsure <code>{email}</code> is a Test User in Google Cloud.' if is_admin else ''
                    auth_msg = f"🔗 <b>Authorization Required</b>\n\n1. 👉 <b><a href='{m_url.group(1).replace('&amp;', '&').strip()}'>Click here to open Google Login</a></b> 👈\n2. Select <code>{email}</code>.\n3. Copy the broken '127.0.0.1' URL from your browser and paste it here.{admin_note}"
                    await tg.edit_message_text(chat_id, res['message_id'], auth_msg, parse_mode='HTML', disable_web_page_preview=True)
                    return
                last_output = out_str[-1200:]
            except Exception as loop_err:
                last_output = str(loop_err)[-1200:]

        ref = _incident_ref("AUTH")
        print(f'AUTH ERROR [{ref}] step1_no_url containers={candidates} output={last_output}', flush=True)
        await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Auth Error.</b>\nReference: <code>{ref}</code>', parse_mode='HTML')
    except Exception as e:
        ref = _incident_ref("AUTH")
        print(f'AUTH ERROR [{ref}] exception={traceback.format_exc()}', flush=True)
        await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Auth Error.</b>\nReference: <code>{ref}</code>', parse_mode='HTML')

async def handle_callback(cb):
    chat_id = cb.get('message', {}).get('chat', {}).get('id')
    tenant_name, t = await check_security(chat_id)
    if not t:
        return await tg.answer_callback_query(cb['id'], text='Unauthorized.', show_alert=True)
    if cb['data'] == 'cmd_auth_custom':
        await tg.answer_callback_query(cb['id'])
        return await tg.send_message(chat_id, 'Type: <code>/auth your.email@gmail.com</code>', parse_mode='HTML')
    if cb['data'].startswith('auth_cb:'):
        ctx_id = cb['data'].split(':')[1]
        payload = get_button_context(ctx_id)
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        if not payload:
            return await tg.send_message(chat_id, '⚠️ Auth session expired. Please type /auth again.')
        try:
            scope_type, email = payload.split('|', 1)
        except ValueError:
            return await tg.send_message(chat_id, '⚠️ Invalid auth payload.')
        if scope_type == 'cancel':
            AUTH_SESSIONS.clear(chat_id)
            return await tg.send_message(chat_id, '🛑 Auth cancelled.')
        await trigger_auth_flow(chat_id, email, t, scopes=scope_type)
        return
    if cb['data'] == 'clear_shopping':
        OpenLoops.clear_shopping(tenant_name)
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        return await tg.send_message(chat_id, '✅ <b>Shopping List marked as Done.</b>', parse_mode='HTML')
    if cb['data'].startswith('mark_paid:'):
        OpenLoops.remove_payment(tenant_name, cb['data'].split(':')[1])
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        return await tg.send_message(chat_id, '✅ <b>Rechnung als bezahlt markiert.</b>', parse_mode='HTML')
    if cb['data'].startswith('drop_pay:'):
        OpenLoops.remove_payment(tenant_name, cb['data'].split(':')[1])
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        return await tg.send_message(chat_id, '🗑️ <b>Zahlungs-Loop gelöscht.</b>', parse_mode='HTML')
    if cb['data'].startswith('exec_cal:'):
        cid = cb['data'].split(':')[1]
        cal_data = OpenLoops.get_calendar(tenant_name, cid)
        if cal_data:
            OpenLoops.remove_calendar(tenant_name, cid)
            try:
                await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
            except:
                pass
            from app.briefings import safe_gog
            from app.calendar_store import create_import, commit_import
            t_openclaw = get_val(t, 'openclaw_container', '')
            t_account = get_val(t, 'google_account', '')
            imported = 0
            failed = 0
            normalized_events = []
            persisted = 0
            persist_status = "not_attempted"
            persist_err = ""
            events_for_import = normalize_extracted_calendar_events(cal_data.get('events') or [])
            if not events_for_import:
                await tg.send_message(
                    chat_id,
                    '⚠️ <b>Calendar Import Failed.</b>\nNo valid event timestamps were found in this request.',
                    parse_mode='HTML',
                )
                return
            for ev in events_for_import:
                try:
                    await safe_gog(t_openclaw, ['calendar', 'events', 'add', str(ev.get('title', '')), '--start', str(ev.get('start', '')), '--end', str(ev.get('end', '')), '--location', str(ev.get('location', '')), '--calendar', 'Executive Assistant'], t_account, timeout=10.0)
                    imported += 1
                    normalized_events.append({
                        "title": str(ev.get("title", "")),
                        "start_ts": str(ev.get("start", "")),
                        "end_ts": str(ev.get("end", "")),
                        "location": str(ev.get("location", "")),
                        "notes": "",
                    })
                except Exception:
                    failed += 1
            # Persist successful imports into local calendar store as a reliable fallback for briefing.
            if normalized_events:
                try:
                    imp_id = create_import(
                        tenant=tenant_name,
                        source_type="telegram_image_import",
                        source_id=f"exec_cal:{cid}",
                        filename="open_loop_import",
                        extracted={"normalized_events": normalized_events},
                        preview="Imported via Open Loops execute",
                    )
                    persisted, persist_status = commit_import(tenant_name, imp_id)
                except Exception as e:
                    persist_status = "failed"
                    persist_err = str(e)[:120]
            total = len(events_for_import)
            response = build_calendar_import_response(
                imported=imported,
                total=total,
                persisted=persisted,
                persist_status=persist_status,
                failed=failed,
                persist_err=persist_err,
            )
            await tg.send_message(chat_id, response.text, parse_mode=response.parse_mode)
        return
    if cb['data'].startswith('drop_cal:'):
        cid = cb['data'].split(':')[1]
        OpenLoops.remove_calendar(tenant_name, cid)
        await tg.answer_callback_query(cb['id'], text='Import Dropped!')
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        return await tg.send_message(chat_id, '🛑 <b>Calendar Import Discarded.</b>', parse_mode='HTML')
    if cb['data'].startswith('act:'):
        action_id = cb['data'][4:]
        rich_prompt = get_button_context(action_id)
        if not rich_prompt:
            return await tg.answer_callback_query(cb['id'], text='⚠️ Action expired.', show_alert=True)
        btn_txt = 'Task'
        for row in cb.get('message', {}).get('reply_markup', {}).get('inline_keyboard', []):
            for btn in row:
                if btn.get('callback_data') == cb.get('data'):
                    btn_txt = btn.get('text', 'Task')
        try:
            await tg.edit_message_reply_markup(chat_id, cb['message']['message_id'], reply_markup={'inline_keyboard': []})
        except:
            pass
        await tg.answer_callback_query(cb['id'], text='Executing...')
        clean_btn = btn_txt.replace('✅', '').replace('⚙️', '').replace('🎯', '').strip()
        is_rejection = any((w in clean_btn.lower() for w in ['do not', 'no', 'cancel', 'stop', 'reject', 'abort', 'skip']))
        if is_rejection:
            enhanced_prompt = f'EXECUTE: {rich_prompt}\nCRITICAL UPDATE: The user REJECTED the previous proposal.'
        else:
            enhanced_prompt = f"EXECUTE: {rich_prompt}\nCRITICAL INSTRUCTIONS:\n1. Use google account '{get_val(t, 'google_account', '')}'."
        res = await tg.send_message(chat_id, f'🚀 <b>Executing:</b> {clean_btn}...\n\n▶️ <b>Analyzing task requirements...</b>', parse_mode='HTML')

        async def _ui_updater(msg):
            try:
                await tg.edit_message_text(chat_id, res['message_id'], f'🚀 <b>Executing:</b> {clean_btn}...\n\n▶️ <b>{msg[:80]}...</b>', parse_mode='HTML', disable_web_page_preview=True)
            except:
                pass
        try:
            report = await asyncio.wait_for(gog_scout(get_val(t, 'openclaw_container', ''), enhanced_prompt, get_val(t, 'google_account', ''), _ui_updater, task_name=f'Button: {clean_btn}'), timeout=240.0)
            kb_dict = build_dynamic_ui(report, enhanced_prompt)
            clean_rep = clean_html_for_telegram(re.sub('\\[OPTIONS:.*?\\]', '', _humanize_agent_report(report)).replace('[YES/NO]', ''))
            if not clean_rep.strip() or clean_rep.strip() == '[]':
                clean_rep = '✅ Task executed successfully!'
            try:
                await tg.edit_message_text(chat_id, res['message_id'], f'🎯 <b>Result:</b>\n\n{clean_rep[:3500]}', parse_mode='HTML', reply_markup=kb_dict)
            except:
                await tg.edit_message_text(chat_id, res['message_id'], f'🎯 <b>Result:</b>\n\n{_safe_err(clean_rep).strip()[:3500]}', reply_markup=kb_dict)
        except Exception as task_err:
            await tg.send_message(chat_id, f'❌ Task Failed: {_safe_err(task_err)}')

async def handle_intent(chat_id: int, msg: dict):
    try:
        tenant_name, t = await check_security(chat_id)
        if not t:
            return
        text = str(msg.get('text') or msg.get('caption') or '').strip()
        text_lower = text.lower()
        doc = msg.get('document')
        photo = msg.get('photo')
        low_stock_words = ['katzenfutter', 'cat food', 'futter', 'brot', 'milch', 'kaffee', 'coffee', 'einkaufsliste']
        if any((w in text_lower for w in low_stock_words)) and any((w in text_lower for w in ['kaufen', 'leer', 'aus', 'fast kein', 'brauchen', 'setz'])):
            OpenLoops.add_shopping(tenant_name, text)
            return await tg.send_message(chat_id, f'🛒 <b>Added to Shopping List Open Loop:</b>\n{text}', parse_mode='HTML')
        if any((kw in text_lower for kw in ['zahl', 'rechnung', 'pay', 'sepa', 'iban'])) and 'kannst du' in text_lower:
            pid = OpenLoops.add_payment(tenant_name, 'Zahlung gewünscht (Missing PDF)', '?', '?', status='needs_doc')
            kb = [[{'text': '🛑 Drop Payment', 'callback_data': f'drop_pay:{pid}'}]]
            return await tg.send_message(chat_id, '📌 <b>Zahlung notiert (Open Loop).</b>\n\nBitte sende die Rechnung als PDF hier in den Chat, damit ich IBAN/Betrag extrahieren kann.', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
        is_pdf = bool(doc and ('pdf' in str(doc.get('mime_type', '')).lower() or str(doc.get('file_name', '')).lower().endswith('.pdf')))
        is_invoice = any((kw in text_lower for kw in ['zahl', 'rechnung', 'pay', 'sepa', 'iban'])) or (is_pdf and (not text_lower or 'rechnung' in str(doc.get('file_name', '')).lower()))
        is_image_calendar = bool(photo or (doc and str(doc.get('mime_type', '')).startswith('image/'))) and (not is_invoice)
        sess = AUTH_SESSIONS.get_and_clear(chat_id)
        if sess and ('localhost' in text_lower or '127.0.0.1' in text_lower or 'code=' in text_lower or ('state=' in text_lower)):
            if text_lower.startswith('/'):
                return await tg.send_message(chat_id, '🛑 Auth session aborted.')
            email = sess['email']
            t_openclaw = sess['openclaw']
            services = sess['services']
            res = await tg.send_message(chat_id, '🔄 <i>⚙️ Verifying OAuth token...</i>', parse_mode='HTML')
            try:
                pasted_url = re.search('(http[^\\s]+)', text)
                url_to_pass = pasted_url.group(1) if pasted_url else text.strip()
                keyring_password = (
                    getattr(settings, 'gog_keyring_password', None)
                    or os.environ.get('GOG_KEYRING_PASSWORD')
                    or os.environ.get('EA_GOG_KEYRING_PASSWORD')
                )
                if not keyring_password:
                    raise RuntimeError('Missing GOG_KEYRING_PASSWORD')
                out_str = await docker_exec(
                    t_openclaw,
                    ['gog', 'auth', 'add', email, '--services', services, '--remote', '--step', '2', '--auth-url', url_to_pass],
                    user='root',
                    extra_env={'GOG_KEYRING_PASSWORD': keyring_password},
                    timeout_s=24.0,
                )
                if 'error' in out_str.lower() or 'failed' in out_str.lower() or 'invalid' in out_str.lower():
                    ref = _incident_ref("AUTH")
                    print(f'TOKEN EXCHANGE ERROR [{ref}] output={out_str[-1600:]}', flush=True)
                    await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Token Exchange Failed.</b>\nReference: <code>{ref}</code>', parse_mode='HTML')
                else:
                    try:
                        with open('/attachments/dynamic_users.json', 'r') as f:
                            dt = json.load(f)
                    except:
                        dt = {}
                    if str(chat_id) not in dt:
                        dt[str(chat_id)] = {}
                    dt[str(chat_id)]['email'] = email
                    _atomic_write_json('/attachments/dynamic_users.json', dt)
                    await tg.edit_message_text(chat_id, res['message_id'], f'✅ <b>Authentication Successful for {email}!</b>\n\nRun /brief to pull your calendars.', parse_mode='HTML')
            except Exception as e:
                await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Error exchanging token:</b> {_safe_err(e)}', parse_mode='HTML')
            return
        if sess and text:
            AUTH_SESSIONS.set(chat_id, sess)
        if is_image_calendar:
            res = await tg.send_message(chat_id, '🖼️ <b>Extracting schedule from image...</b>', parse_mode='HTML')
            progress_task = None
            stop_progress = asyncio.Event()

            async def _calendar_progress_ticker() -> None:
                elapsed = 0
                progress_sec = max(10, int(float(os.getenv("EA_CALENDAR_VISION_PROGRESS_SEC", "15") or 15)))
                while not stop_progress.is_set():
                    await asyncio.sleep(progress_sec)
                    elapsed += progress_sec
                    if stop_progress.is_set():
                        break
                    try:
                        await tg.edit_message_text(
                            chat_id,
                            res['message_id'],
                            f'🖼️ <b>Extracting schedule from image...</b>\n<i>Still processing ({elapsed}s elapsed)...</i>',
                            parse_mode='HTML',
                        )
                    except Exception:
                        pass
            try:
                progress_task = asyncio.create_task(_calendar_progress_ticker())
                document_id, raw_ref = _message_document_ref(chat_id, msg, doc, photo)
                gate = gate_household_document_action(
                    document_id=document_id,
                    user_id=str(chat_id),
                    confidence_score=_household_confidence_for_message(chat_id, msg),
                    raw_document_ref=raw_ref,
                    pipeline_stage='intent.image_calendar',
                    correlation_id=f'hh-{chat_id}-{int(time.time() * 1000)}',
                )
                if not gate.get('action_allowed'):
                    return await tg.edit_message_text(
                        chat_id,
                        res['message_id'],
                        '🔒 <b>Household Safety Hold</b>\n\nA new family document needs review before action.',
                        parse_mode='HTML',
                    )
                file_id = photo[-1]['file_id'] if photo else doc['file_id']
                meta = await tg.get_file(file_id)
                img_bytes = await tg.download_file_bytes(meta['file_path'])
                vision_timeout_sec = float(os.getenv("EA_CALENDAR_VISION_TIMEOUT_SEC", "90") or 90)
                extracted = await asyncio.wait_for(
                    extract_calendar_from_image(img_bytes, 'image/jpeg'),
                    timeout=max(10.0, vision_timeout_sec),
                )
                events = normalize_extracted_calendar_events(extracted.get('events') or [])
                if not events:
                    return await tg.edit_message_text(chat_id, res['message_id'], '⚠️ No calendar events detected.')
                lines = []
                for e in events:
                    start_txt = html.escape(str((e or {}).get('start') or ''), quote=False)
                    title_txt = html.escape(str((e or {}).get('title') or ''), quote=False)
                    lines.append(f'• {start_txt} - {title_txt}\n')
                preview = '📅 <b>Found Events:</b>\n' + ''.join(lines)
                cid = OpenLoops.add_calendar(tenant_name, preview, events)
                kb = [[{'text': f'✅ Execute Import to EA', 'callback_data': f'exec_cal:{cid}'}], [{'text': f'🛑 Discard', 'callback_data': f'drop_cal:{cid}'}]]
                await tg.edit_message_text(chat_id, res['message_id'], preview + '\n\n<i>This import request has been added to your Open Loops.</i>', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
            except asyncio.TimeoutError:
                await tg.edit_message_text(
                    chat_id,
                    res['message_id'],
                    '⚠️ Calendar extraction timed out. Please retry with a clearer image.',
                    parse_mode='HTML',
                )
            except Exception as e:
                await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ Vision Error: {_safe_err(e)}', parse_mode='HTML')
            finally:
                stop_progress.set()
                if progress_task is not None:
                    progress_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await progress_task
            return
        if is_invoice:
            res = await tg.send_message(chat_id, '💸 <b>Rechnung erkannt. Lese Daten (1min.ai gpt-4o)...</b>', parse_mode='HTML')
            try:
                document_id, raw_ref = _message_document_ref(chat_id, msg, doc, photo)
                gate = gate_household_document_action(
                    document_id=document_id,
                    user_id=str(chat_id),
                    confidence_score=_household_confidence_for_message(chat_id, msg),
                    raw_document_ref=raw_ref,
                    pipeline_stage='intent.invoice',
                    correlation_id=f'hh-{chat_id}-{int(time.time() * 1000)}',
                )
                if not gate.get('action_allowed'):
                    return await tg.edit_message_text(
                        chat_id,
                        res['message_id'],
                        '🔒 <b>Household Safety Hold</b>\n\nA new family document needs review before payment extraction.',
                        parse_mode='HTML',
                    )
                file_id = doc['file_id'] if doc else photo[-1]['file_id']
                meta = await tg.get_file(file_id)
                file_bytes = await tg.download_file_bytes(meta['file_path'])
                prompt_str = 'Extract invoice details. Return ONLY JSON matching {"iban": "AT...", "amount": 12.34, "creditor": "Name", "reference": "Ref"}'
                if is_pdf:
                    import pypdf
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    pdf_text = '\n'.join([page.extract_text() for page in reader.pages[:3] if page.extract_text()])
                    sepa_json = await _ask_llm_text(
                        f'{prompt_str}\n\nText:\n{pdf_text[:4000]}',
                        tenant=str(tenant_name or ""),
                        person_id=str(chat_id),
                    )
                else:
                    one_min_key = getattr(settings, 'one_min_ai_api_key', None) or os.environ.get('ONE_MIN_AI_API_KEY')
                    if not one_min_key:
                        raise RuntimeError('Missing ONE_MIN_AI_API_KEY')
                    b64_img = base64.b64encode(file_bytes).decode('utf-8')
                    payload = {'model': 'gpt-4o', 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt_str}, {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64_img}'}}]}]}
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post('https://api.1min.ai/v1/chat/completions', json=payload, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {one_min_key}'})
                        sepa_json = resp.json()['choices'][0]['message']['content']
                m = re.search('\\{[\\s\\S]*\\}', sepa_json)
                if m:
                    sepa_data = json.loads(m.group(0))
                    if sepa_data.get('iban') and sepa_data.get('amount'):
                        amt = f'{float(sepa_data['amount']):.2f}'
                        pid = OpenLoops.add_payment(tenant_name, sepa_data.get('creditor', 'Unknown'), amt, sepa_data.get('iban'))
                        qr_bytes, _ = generate_epc_qr(sepa_data.get('creditor', ''), sepa_data.get('iban', ''), float(sepa_data.get('amount', 0)), sepa_data.get('reference', ''))
                        xml_bytes = generate_pain001_xml(sepa_data.get('creditor', ''), sepa_data.get('iban', ''), float(sepa_data.get('amount', 0)), sepa_data.get('reference', ''))
                        if qr_bytes and xml_bytes:
                            kb = [[{'text': '✅ Als bezahlt markieren', 'callback_data': f'mark_paid:{pid}'}]]
                            await tg.edit_message_text(chat_id, res['message_id'], '✅ <b>Daten extrahiert!</b>', parse_mode='HTML')
                            await tg.send_document(chat_id, xml_bytes.encode('utf-8'), 'SEPA_Transfer.xml')
                            await tg.send_photo(chat_id, qr_bytes, caption=f'📋 <b>Copy-Block</b>\nEmpfänger: <code>{sepa_data.get('creditor')}</code>\nIBAN: <code>{sepa_data['iban']}</code>\nBetrag: <code>{amt}</code>\nZweck: <code>{sepa_data.get('reference')}</code>', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
                            return
            except Exception as e:
                pass
            try:
                await tg.edit_message_text(chat_id, res['message_id'], '⚠️ Konnte IBAN oder Betrag nicht eindeutig lesen.', parse_mode='HTML')
            except:
                pass
            return
        if text and (not is_invoice) and (not is_image_calendar) and (not text.startswith('/')) and (not ('localhost' in text_lower or '127.0.0.1' in text_lower or 'code=' in text_lower or ('state=' in text_lower))):
            t_openclaw = get_val(t, 'openclaw_container', os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway"))
            active_res = await tg.send_message(chat_id, '▶️ <b>Analyzing request...</b>', parse_mode='HTML')
            urls = re.findall('(https?://[^\\s]+)', text)
            if urls and any((w in text_lower for w in ['read', 'scrape', 'summarize', 'check', 'extract', 'what'])):
                from app.tools.browseract import scrape_url
                try:
                    await tg.edit_message_text(chat_id, active_res['message_id'], '🌐 <b>Scraping website with BrowserAct...</b>', parse_mode='HTML')
                except:
                    pass
                scraped_data = await scrape_url(urls[0])
                prompt = f"EXECUTE: The user sent a link. I scraped it for you using BrowserAct. Here is the website content:\n\n{str(scraped_data)[:3000]}\n\nUser request: '{text}'. Be concise."
            else:
                prompt = f"EXECUTE: Answer or execute the user request: '{text}'. Be concise."

            async def _ui_updater(m):
                try:
                    await tg.edit_message_text(chat_id, active_res['message_id'], f'▶️ <b>{m[:80]}...</b>', parse_mode='HTML')
                except:
                    pass
            try:
                report = await asyncio.wait_for(gog_scout(t_openclaw, prompt, get_val(t, 'google_account', ''), _ui_updater, task_name='Intent: Free Text'), timeout=240.0)
                kb_dict = build_dynamic_ui(report, prompt)
                clean_rep = clean_html_for_telegram(re.sub('\\[OPTIONS:.*?\\]', '', _humanize_agent_report(report)).replace('[YES/NO]', ''))
                if not clean_rep.strip() or clean_rep.strip() == '[]':
                    clean_rep = '✅ Task executed successfully!'
                try:
                    await tg.edit_message_text(chat_id, active_res['message_id'], f'🎯 <b>Result:</b>\n\n{clean_rep[:3500]}', parse_mode='HTML', reply_markup=kb_dict)
                except Exception as tg_err:
                    import html as pyhtml
                    plain_txt = re.sub('<[^>]+>', '', clean_rep).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    if len(plain_txt) > 4000:
                        plain_txt = plain_txt[:4000] + '\n...[truncated]'
                    try:
                        await tg.edit_message_text(chat_id, active_res['message_id'], f'🎯 <b>Result:</b>\n\n{plain_txt}', parse_mode=None, reply_markup=kb_dict)
                    except:
                        pass
            except Exception as task_err:
                await tg.edit_message_text(chat_id, active_res['message_id'], f'❌ Agent Failed: {_safe_err(task_err)}', parse_mode='HTML')
            return
    except Exception as e:
        print(f'INTENT CRASH: {traceback.format_exc()}', flush=True)

async def handle_command(chat_id: int, text: str, msg: dict):
    try:
        tenant_name, t = await check_security(chat_id)
        if not t:
            return
        parts = text.strip().split(' ', 1)
        cmd = parts[0].lower().split('@')[0].rstrip(':')
        cmd_aliases = {
            '/vrief': '/brief',
        }
        cmd = cmd_aliases.get(cmd, cmd)
        if cmd in ('/start', '/menu', '/help'):
            return await tg.send_message(chat_id, _menu_text(), parse_mode='HTML')
        if cmd == '/auth':
            target_email = parts[1].strip() if len(parts) > 1 else ''
            t_acc = get_val(t, 'google_account', '')
            if not target_email:
                kb = []
                if t_acc:
                    kb.extend([
                        [{'text': f'🔑 All Features ({t_acc})', 'callback_data': f'auth_cb:{save_button_context(f'all|{t_acc}')}'}],
                        [{'text': f'📅 Cal Only ({t_acc})', 'callback_data': f'auth_cb:{save_button_context(f'cal|{t_acc}')}'}],
                    ])
                kb.append([{'text': '✏️ Type a different email...', 'callback_data': 'cmd_auth_custom'}])
                return await tg.send_message(chat_id, 'ℹ️ <b>Authentication</b>\nWhich Google Account do you want to authorize?', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
            else:
                kb = [[{'text': '🔑 All Features', 'callback_data': f'auth_cb:{save_button_context(f'all|{target_email}')}'}], [{'text': '📅 Calendar Only', 'callback_data': f'auth_cb:{save_button_context(f'cal|{target_email}')}'}], [{'text': '✉️ Gmail Only', 'callback_data': f'auth_cb:{save_button_context(f'mail|{target_email}')}'}], [{'text': '✏️ Type a different email...', 'callback_data': 'cmd_auth_custom'}], [{'text': '❌ Cancel', 'callback_data': f'auth_cb:{save_button_context('cancel|none')}'}]]
                return await tg.send_message(chat_id, f'ℹ️ <b>Features for {target_email}</b>\nWhich features do you want to enable?', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
        if cmd == '/brain':
            try:
                import json
                if not __import__('os').path.exists('/attachments/brain.json'):
                    return await tg.send_message(chat_id, '🧠 Brain is empty. Use /remember <text>.')
                with open('/attachments/brain.json', 'r', encoding='utf-8') as f:
                    brain = json.load(f)
                if not brain:
                    return await tg.send_message(chat_id, '🧠 Brain is empty.')
                lines = ['🧠 <b>Active Memories:</b>']
                for k, v in brain.items():
                    lines.append(f'• <b>{k}</b>: {v}')
                return await tg.send_message(chat_id, '\n'.join(lines), parse_mode='HTML')
            except Exception as e:
                return await tg.send_message(chat_id, f'⚠️ Brain error: {_safe_err(e)}')
        if cmd == '/mumbrain':
            is_admin = bool(get_val(t, 'is_admin', False)) or str(chat_id) == str(get_admin_chat_id() or "")
            if not is_admin:
                return await tg.send_message(
                    chat_id,
                    "ℹ️ This command is operator-only.",
                    parse_mode='HTML',
                )
            try:
                from app.db import get_db

                db = get_db()
                active = db.fetchone("SELECT count(*) AS c FROM delivery_sessions WHERE status = 'active'")
                h = system_health_snapshot(db)
                last = db.fetchone("SELECT recipe_key, status FROM repair_jobs ORDER BY job_id DESC LIMIT 1")
                msg = (
                    "🧠 <b>Mum Brain Status</b>\n\n"
                    f"• Phase A active deliveries: <b>{int((active or {}).get('c') or 0)}</b>\n"
                    f"• Phase B pending/running: <b>{h['pending']}</b>/<b>{h['running']}</b>\n"
                    f"• Repairs 24h (ok/failed): <b>{h['completed_24h']}</b>/<b>{h['failed_24h']}</b>\n"
                    f"• Replay queue/dead letters: <b>{h['replay_q']}</b>/<b>{h['dead_q']}</b>\n"
                    f"• Render breaker open: <b>{'yes' if h['breaker_open'] else 'no'}</b>\n"
                    f"• Last repair: <b>{(last or {}).get('recipe_key') or 'none'}</b> → <b>{(last or {}).get('status') or 'none'}</b>"
                )
                return await tg.send_message(chat_id, msg, parse_mode='HTML')
            except Exception as e:
                return await tg.send_message(chat_id, f'⚠️ Mum Brain status error: {_safe_err(e)}')
        if cmd in ('/briefpdf', '/articlespdf'):
            wait_msg = await tg.send_message(chat_id, '🗞️ <i>Building reading PDF from BrowserAct...</i>', parse_mode='HTML')
            sent = await _send_browseract_articles_pdf(chat_id, tenant_name, t, force=True)
            if sent:
                try:
                    await tg.delete_message(chat_id, wait_msg.get('message_id'))
                except Exception:
                    pass
            else:
                await tg.edit_message_text(chat_id, wait_msg['message_id'], '🗞️ No qualifying Economist/Atlantic/NYT BrowserAct articles in the last 7 days.', parse_mode='HTML')
            return
        if cmd == '/remember':
            rem_text = text[len('/remember'):].strip()
            if not rem_text:
                return await tg.send_message(chat_id, 'Usage: /remember <fact to remember>')
            res = await tg.send_message(chat_id, '🧠 <i>Normalizing memory...</i>', parse_mode='HTML')
            try:
                import json
                prompt = f'Extract a short 3-5 word title and the core fact from this text. Return STRICT JSON: {{"title": "...", "fact": "..."}}. Text: {rem_text}'
                out = await _ask_llm_text(
                    prompt,
                    tenant=str(tenant_name or ""),
                    person_id=str(chat_id),
                )
                match = re.search('\\{[\\s\\S]*\\}', out)
                if match:
                    data = json.loads(match.group(0))
                    brain_file = '/attachments/brain.json'
                    brain = {}
                    if __import__('os').path.exists(brain_file):
                        with open(brain_file, 'r', encoding='utf-8') as f:
                            brain = json.load(f)
                    brain[data['title']] = data['fact']
                    with open(brain_file, 'w', encoding='utf-8') as f:
                        json.dump(brain, f)
                    return await tg.edit_message_text(chat_id, res['message_id'], f'✅ <b>Remembered:</b> {data['title']}', parse_mode='HTML')
                else:
                    return await tg.edit_message_text(chat_id, res['message_id'], '⚠️ Failed to parse memory via AI.')
            except Exception as e:
                return await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ Error saving memory: {_safe_err(e)}')
        if cmd == '/brief':
            if _brief_command_throttled(chat_id):
                return await tg.send_message(
                    chat_id,
                    "⏳ A briefing was already requested recently. Please wait a moment and try again.",
                    parse_mode='HTML',
                )
            if not _brief_enter(chat_id):
                return await tg.send_message(
                    chat_id,
                    "⏳ A briefing is already in progress. Please wait for it to finish.",
                    parse_mode='HTML',
                )
            res = await tg.send_message(chat_id, '<i>Initializing...</i>', parse_mode='HTML')

            async def _update_status(msg_text):
                try:
                    await tg.edit_message_text(chat_id, res['message_id'], msg_text, parse_mode='HTML', disable_web_page_preview=True)
                except:
                    pass
            try:
                b = await asyncio.wait_for(build_briefing_for_tenant(t, status_cb=_update_status), timeout=240.0)
                txt = b.get('text', '⚠️ Error')
                inline_kb = []
                for row in b.get('dynamic_buttons', []):
                    inline_kb.append(row)
                for opt in b.get('options', []):
                    if opt and 'Option' not in opt:
                        inline_kb.append([{'text': str(opt)[:40], 'callback_data': f'act:{save_button_context(f'Deep dive: {opt}')}'}])
                markup = {'inline_keyboard': inline_kb} if inline_kb else None
                safe_txt = clean_html_for_telegram(txt)
                try:
                    if markupgo_breaker_open():
                        raise RuntimeError('EA render guard: markupgo breaker open')
                    from app.tools.markupgo_client import MarkupGoClient, render_request_hash
                    import uuid
                    from app.db import get_db
                    await _update_status('🎨 <i>Rendering visual briefing via MarkupGo...</i>')
                    db = get_db()
                    row = await asyncio.to_thread(db.fetchone, "SELECT template_id FROM template_registry WHERE key = 'briefing.image' AND is_active = TRUE ORDER BY version DESC LIMIT 1")
                    template_id = row['template_id'] if row else ''
                    if not template_id:
                        raise ValueError("OODA: No active template found for 'briefing.image'. Act: Run SQL: INSERT INTO template_registry (tenant, key, provider, template_id) VALUES ('ea_bot', 'briefing.image', 'markupgo', 'YOUR_ID');")
                    template_id = promote_known_good_template_if_needed(str(template_id), tenant='ea_bot')
                    if str(template_id).strip().lower().startswith('ooda_auto_tpl_') or str(template_id).strip().upper() == 'YOUR_ID':
                        raise RuntimeError("EA render guard: markupgo template not configured")
                    context = {'briefing_text': txt}
                    options = {'format': 'png'}
                    req_hash = render_request_hash(template_id, context, options, 'png')
                    cached = await asyncio.to_thread(db.fetchone, "SELECT artifact_id FROM render_cache WHERE tenant = 'ea_bot' AND render_request_hash = %s", (req_hash,))
                    __import__('os').makedirs(__import__('os').path.join(__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments'), 'artifacts'), exist_ok=True)
                    img_bytes = None
                    art_id = None
                    if cached and __import__('os').path.exists(f'{__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments')}/artifacts/{cached['artifact_id']}.png'):
                        art_id = cached['artifact_id']
                        with open(f'{__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments')}/artifacts/{cached['artifact_id']}.png', 'rb') as f:
                            img_bytes = f.read()
                    else:
                        mg = MarkupGoClient()
                        payload = {'source': {'type': 'template', 'data': {'id': template_id, 'context': context}}, 'options': options}
                        img_bytes = await mg.render_image_buffer(payload)
                        art_id = str(uuid.uuid4())
                        with open(f'{__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments')}/artifacts/{art_id}.png', 'wb') as f:
                            f.write(img_bytes)
                        await asyncio.to_thread(db.execute, 'INSERT INTO render_cache (tenant, render_request_hash, provider, format, artifact_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING', ('ea_bot', req_hash, 'markupgo', 'png', art_id))
                    if img_bytes:
                        from app.outbox import enqueue_outbox
                        delivery_session_id = await asyncio.to_thread(
                            create_briefing_delivery_session,
                            chat_id,
                            status="pending",
                        )
                        payload = {
                            'type': 'photo',
                            'artifact_id': art_id,
                            'caption': safe_txt[:1000] + ('...' if len(safe_txt) > 1000 else ''),
                            'parse_mode': 'HTML',
                        }
                        if delivery_session_id:
                            payload['delivery_session_id'] = int(delivery_session_id)
                        await asyncio.to_thread(enqueue_outbox, tenant_name, chat_id, payload)
                        await safe_task('Briefing PDF', _send_briefing_newspaper_pdf(chat_id, tenant_name, t, txt))
                        asyncio.create_task(safe_task('Briefing Survey', plan_briefing_feedback_survey(
                            tenant=(get_val(t, 'google_account', '') or tenant_name),
                            principal=str(chat_id),
                            briefing_excerpt=safe_txt,
                        )))
                        try:
                            await tg.delete_message(chat_id, res['message_id'])
                        except:
                            pass
                        return
                except Exception as mg_err:
                    _ea_fault = classify_markupgo_error(mg_err)
                    if _ea_fault in ('invalid_template_id', 'renderer_unavailable'):
                        open_markupgo_breaker(_ea_fault, skill='markupgo', location='poll_listener')
                    # OODA self-heal: keep visual briefing available via direct HTML rendering when template path is unstable.
                    try:
                        from app.tools.markupgo_client import MarkupGoClient
                        import uuid
                        from app.outbox import enqueue_outbox
                        plain = re.sub('<[^>]+>', '', txt)
                        plain = plain[:3500]
                        html_doc = (
                            "<html><body style='margin:24px;font-family:Arial,sans-serif;'>"
                            f"<div style='white-space:pre-wrap;font-size:22px;line-height:1.35;'>{html.escape(plain)}</div>"
                            "</body></html>"
                        )
                        mg = MarkupGoClient()
                        payload = {'source': {'type': 'html', 'data': html_doc}, 'options': {'format': 'png'}}
                        img_bytes = await mg.render_image_buffer(payload)
                        if img_bytes and img_bytes.startswith(b'\x89PNG'):
                            art_id = str(uuid.uuid4())
                            pdir = f"{__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments')}/artifacts"
                            __import__('os').makedirs(pdir, exist_ok=True)
                            with open(f'{pdir}/{art_id}.png', 'wb') as f:
                                f.write(img_bytes)
                            delivery_session_id = await asyncio.to_thread(
                                create_briefing_delivery_session,
                                chat_id,
                                status="pending",
                            )
                            payload = {
                                'type': 'photo',
                                'artifact_id': art_id,
                                'caption': safe_txt[:1000] + ('...' if len(safe_txt) > 1000 else ''),
                                'parse_mode': 'HTML',
                            }
                            if delivery_session_id:
                                payload['delivery_session_id'] = int(delivery_session_id)
                            await asyncio.to_thread(enqueue_outbox, tenant_name, chat_id, payload)
                            await safe_task('Briefing PDF', _send_briefing_newspaper_pdf(chat_id, tenant_name, t, txt))
                            asyncio.create_task(safe_task('Briefing Survey', plan_briefing_feedback_survey(
                                tenant=(get_val(t, 'google_account', '') or tenant_name),
                                principal=str(chat_id),
                                briefing_excerpt=safe_txt,
                            )))
                            try:
                                await tg.delete_message(chat_id, res['message_id'])
                            except:
                                pass
                            log_render_guard('renderer_html_fallback', _ea_fault, skill='markupgo', location='poll_listener')
                            return
                    except Exception as html_fb_err:
                        log_render_guard('renderer_html_fallback_failed', str(html_fb_err)[:120], skill='markupgo', location='poll_listener')
                    try:
                        open_repair_incident(
                            db_conn=None,
                            error_message=str(mg_err),
                            fallback_mode='simplified-first',
                            failure_class='renderer_fault',
                            intent='brief_render',
                            chat_id=str(chat_id),
                        )
                    except Exception:
                        pass
                    log_render_guard('renderer_text_only', _ea_fault, skill='markupgo', location='poll_listener')
                    # Hard boundary: never append renderer diagnostics to user chat.
                    safe_txt += '\n\n📝 <i>Visual template unavailable, switched to safe text mode.</i>'
                try:
                    delivery_session_id = await asyncio.to_thread(
                        create_briefing_delivery_session,
                        chat_id,
                        status="active",
                    )
                    await tg.edit_message_text(chat_id, res['message_id'], safe_txt, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)
                    if delivery_session_id:
                        await asyncio.to_thread(activate_briefing_delivery_session, int(delivery_session_id))
                    await safe_task('Briefing PDF', _send_briefing_newspaper_pdf(chat_id, tenant_name, t, txt))
                    asyncio.create_task(safe_task('Briefing Survey', plan_briefing_feedback_survey(
                        tenant=(get_val(t, 'google_account', '') or tenant_name),
                        principal=str(chat_id),
                        briefing_excerpt=safe_txt,
                    )))
                except Exception as tg_err:
                    print(f'Telegram HTML Parse Error: {tg_err}', flush=True)
                    import html as pyhtml
                    plain_txt = re.sub('<[^>]+>', '', txt).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    if len(plain_txt) > 4000:
                        plain_txt = plain_txt[:4000] + '...[truncated]'
                    try:
                        delivery_session_id = await asyncio.to_thread(
                            create_briefing_delivery_session,
                            chat_id,
                            status="active",
                        )
                        await tg.edit_message_text(chat_id, res['message_id'], plain_txt, parse_mode=None, reply_markup=markup, disable_web_page_preview=True)
                        if delivery_session_id:
                            await asyncio.to_thread(activate_briefing_delivery_session, int(delivery_session_id))
                    except Exception:
                        await tg.edit_message_text(chat_id, res['message_id'], '⚠️ Fatal error rendering briefing.', parse_mode=None)
            except Exception as e:
                ref = _incident_ref("BRIEF")
                print(f'BRIEFING FAILED [{ref}] {traceback.format_exc()}', flush=True)
                await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Briefing Failed.</b>\nReference: <code>{ref}</code>', parse_mode='HTML')
            finally:
                _brief_exit(chat_id)
            return
    except Exception as e:
        print(f'COMMAND CRASH: {traceback.format_exc()}', flush=True)

async def safe_task(tag, coro):
    try:
        await coro
    except Exception as e:
        print(f'Task Crash [{tag}]: {traceback.format_exc()}', flush=True)

async def poll_loop():
    print('🤖 Telegram Bot Poller: ACTIVE (V170 God-Mode Omni-Brain)', flush=True)
    if not settings.telegram_bot_token:
        return
    await _ensure_bot_command_menu()
    asyncio.create_task(heartbeat_pinger())
    offset = read_offset()
    sem = asyncio.Semaphore(15)
    while True:
        try:
            updates = await tg.get_updates(offset, timeout_s=30)
            mark_heartbeat()
            for u in updates:
                offset = u['update_id'] + 1
                await asyncio.to_thread(atomic_write_offset, offset)

                async def _run_with_guard(u_data):
                    async with sem:
                        try:
                            await asyncio.wait_for(
                                route_update(
                                    u_data,
                                    on_callback=handle_callback,
                                    on_command=handle_command,
                                    on_intent=handle_intent,
                                ),
                                timeout=240.0,
                            )
                        except asyncio.TimeoutError:
                            print('🚨 SENTINEL: Task timed out!', flush=True)
                asyncio.create_task(safe_task('Route Update', _run_with_guard(u)))
        except Exception as e:
            print(f'POLL LOOP CRASH: {traceback.format_exc()}', flush=True)
            await asyncio.sleep(5)
