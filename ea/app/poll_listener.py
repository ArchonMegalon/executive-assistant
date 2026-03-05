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
from datetime import datetime, timedelta, timezone

import httpx
from app.config import get_admin_chat_id, load_tenants, tenant_by_chat_id
from app.gog import gog_scout, gog_cli, docker_exec
from app.settings import settings
from app.telegram import TelegramClient
from app.vision import extract_calendar_from_image
from app.sepa_qr import generate_epc_qr
from app.sepa_xml import generate_pain001_xml
from app.open_loops import OpenLoops
from app.briefings import get_val
from app.articles_digest import fetch_browseract_articles, select_interesting, render_articles_pdf, collect_user_signal_terms, enrich_full_articles
from app.memory import get_button_context, save_button_context
from app.newspaper.pdf_quality_gate import validate_newspaper_pdf_bytes
from app.render_guard import log_render_guard
from app.operator_commands import handle_mumbrain_command as _handle_mumbrain_command
from app.policy.household import gate_household_document_action
from app.intake.survey_planner import plan_article_preference_survey
from app.intake.calendar_import_result import build_calendar_import_response
from app.intake.calendar_events import normalize_extracted_calendar_events
from app.chat_assist import ask_llm_text as _ask_llm_text, humanize_agent_report as _humanize_agent_report
from app.brain_commands import remember_fact as _remember_fact, show_brain as _show_brain
from app.auth_commands import handle_auth_command as _handle_auth_command
from app.reading_commands import handle_articles_pdf_command as _handle_articles_pdf_command
from app.newspaper.preferences import build_preference_snapshot
from app.poll_ui import build_dynamic_ui, clean_html_for_telegram
from app.telegram_menu import bot_commands as _bot_commands, menu_text as _menu_text, mumbrain_user_visible as _mumbrain_user_visible
from app.auth_sessions import AuthSessionStore
from app.message_security import check_security, household_confidence_for_message as _household_confidence_for_message, message_document_ref as _message_document_ref
from app.brief_commands import brief_command_throttled as _brief_command_throttled, brief_enter as _brief_enter, brief_exit as _brief_exit
from app.brief_runtime import run_brief_command as _run_brief_command
from app.offset_store import atomic_write_offset, read_offset
from app.watchdog import heartbeat_pinger, mark_heartbeat, start_watchdog_thread
from app.update_router import route_update
from app.callback_commands import handle_callback_command as _handle_callback_command
from app.intent_runtime import handle_free_text_intent as _handle_free_text_intent
from app.skill_commands import handle_skill_command as _handle_skill_command


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


def _safe_err(e) -> str:
    return html.escape(str(e), quote=False)

def _incident_ref(prefix: str = "EA") -> str:
    return f"{prefix}-{int(time.time())}"


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

async def _send_briefing_newspaper_pdf(chat_id: int, tenant_name: str, tenant_cfg: dict, briefing_text: str) -> bool:
    try:
        from app.tools.markupgo_client import MarkupGoClient
        from app.newspaper import build_issue_for_brief, render_issue_html, validate_issue
        pref = await build_preference_snapshot(tenant_name, tenant_cfg, chat_id)
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
        ok, detail = validate_newspaper_pdf_bytes(pdf_bytes, min_pages=4, min_images=3)
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
    await _handle_callback_command(
        tg=tg,
        cb=cb,
        check_security=check_security,
        auth_sessions=AUTH_SESSIONS,
        trigger_auth_flow=trigger_auth_flow,
    )

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
                        creditor = str(sepa_data.get("creditor") or "")
                        iban = str(sepa_data.get("iban") or "")
                        reference = str(sepa_data.get("reference") or "")
                        amount_value = float(sepa_data.get("amount") or 0)
                        amt = f"{amount_value:.2f}"
                        pid = OpenLoops.add_payment(tenant_name, creditor or "Unknown", amt, iban)
                        qr_bytes, _ = generate_epc_qr(creditor, iban, amount_value, reference)
                        xml_bytes = generate_pain001_xml(creditor, iban, amount_value, reference)
                        if qr_bytes and xml_bytes:
                            kb = [[{'text': '✅ Als bezahlt markieren', 'callback_data': f'mark_paid:{pid}'}]]
                            caption = (
                                "📋 <b>Copy-Block</b>\n"
                                f"Empfänger: <code>{creditor}</code>\n"
                                f"IBAN: <code>{iban}</code>\n"
                                f"Betrag: <code>{amt}</code>\n"
                                f"Zweck: <code>{reference}</code>"
                            )
                            await tg.edit_message_text(chat_id, res['message_id'], '✅ <b>Daten extrahiert!</b>', parse_mode='HTML')
                            await tg.send_document(chat_id, xml_bytes.encode('utf-8'), 'SEPA_Transfer.xml')
                            await tg.send_photo(chat_id, qr_bytes, caption=caption, parse_mode='HTML', reply_markup={'inline_keyboard': kb})
                            return
            except Exception as e:
                pass
            try:
                await tg.edit_message_text(chat_id, res['message_id'], '⚠️ Konnte IBAN oder Betrag nicht eindeutig lesen.', parse_mode='HTML')
            except:
                pass
            return
        if text and (not is_invoice) and (not is_image_calendar) and (not text.startswith('/')) and (not ('localhost' in text_lower or '127.0.0.1' in text_lower or 'code=' in text_lower or ('state=' in text_lower))):
            return await _handle_free_text_intent(
                tg=tg,
                chat_id=chat_id,
                tenant_name=tenant_name,
                text=text,
                tenant_cfg=t,
                safe_err=_safe_err,
            )
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
            return await _handle_auth_command(
                tg=tg,
                chat_id=chat_id,
                command_text=text,
                primary_account=str(get_val(t, 'google_account', '') or ''),
                save_ctx=save_button_context,
            )
        if cmd == '/brain':
            return await _show_brain(tg=tg, chat_id=chat_id)
        if cmd == '/mumbrain':
            return await _handle_mumbrain_command(
                tg=tg,
                chat_id=chat_id,
                tenant_cfg=t,
                admin_chat_id=str(get_admin_chat_id() or ""),
            )
        if cmd in ('/briefpdf', '/articlespdf'):
            return await _handle_articles_pdf_command(
                tg=tg,
                chat_id=chat_id,
                tenant_name=tenant_name,
                tenant_cfg=t,
                send_pdf_func=_send_browseract_articles_pdf,
            )
        if cmd == '/remember':
            return await _remember_fact(
                tg=tg,
                chat_id=chat_id,
                tenant_name=str(tenant_name or ""),
                command_text=text,
                ask_llm_text=_ask_llm_text,
            )
        if cmd == '/skill':
            return await _handle_skill_command(
                tg=tg,
                chat_id=chat_id,
                command_text=text,
                tenant_name=str(tenant_name or ""),
            )
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
            try:
                await _run_brief_command(
                    tg=tg,
                    chat_id=chat_id,
                    tenant_name=tenant_name,
                    tenant_cfg=t,
                    init_message_id=res['message_id'],
                    save_ctx=save_button_context,
                    clean_html=clean_html_for_telegram,
                    send_newspaper_pdf=_send_briefing_newspaper_pdf,
                    safe_task=safe_task,
                    incident_ref=_incident_ref,
                )
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
