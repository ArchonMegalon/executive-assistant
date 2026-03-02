from __future__ import annotations
import os
import asyncio
import os
import httpx, asyncio, os, sys, traceback, re, json, io, base64, urllib.parse, time, threading, html
from datetime import datetime, timezone
import urllib.request
from app.config import get_tenant, get_admin_chat_id, load_tenants, tenant_by_chat_id
from app.gog import gog_scout, gog_cli
from app.settings import settings
from app.telegram import TelegramClient
from app.vision import extract_calendar_from_image
from app.sepa_qr import generate_epc_qr
from app.sepa_xml import generate_pain001_xml
from app.open_loops import OpenLoops
from app.briefings import build_briefing_for_tenant, get_val, call_llm, call_powerful_llm
from app.memory import get_button_context, save_button_context
from app.render_guard import classify_markupgo_error, log_render_guard, markupgo_breaker_open, open_markupgo_breaker, promote_known_good_template_if_needed
from app.policy.household import gate_household_document_action
LAST_HEARTBEAT = time.time()

def _watchdog_loop():
    while True:
        time.sleep(15)
        if time.time() - LAST_HEARTBEAT > 300:
            print('🚨 SENTINEL: System Deadlock Detected! Restarting...', flush=True)
            try:
                tok = getattr(settings, 'telegram_bot_token', None)
                admin = get_admin_chat_id()
                if tok and admin:
                    msg = '🚨 <b>Sentinel Alert:</b> Assistant AI suffered a fatal event loop deadlock. Executing emergency container restart to self-heal...'
                    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=json.dumps({'chat_id': admin, 'text': msg, 'parse_mode': 'HTML'}).encode('utf-8'), headers={'Content-Type': 'application/json'})
                    urllib.request.urlopen(req, timeout=5)
            except:
                pass
            os._exit(1)
threading.Thread(target=_watchdog_loop, daemon=True).start()

async def heartbeat_pinger():
    global LAST_HEARTBEAT
    while True:
        LAST_HEARTBEAT = time.time()
        await asyncio.sleep(10)
tg = TelegramClient(settings.telegram_bot_token)

class AuthSessionStore:

    def __init__(self):
        self._lock = threading.Lock()
        self._path = '/attachments/auth_sessions.json'

    def _read(self):
        if not __import__('os').path.exists(self._path):
            return {}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _write(self, data):
        tmp = self._path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, self._path)

    def set(self, chat_id: int, session: dict):
        with self._lock:
            data = self._read()
            data[str(chat_id)] = session
            self._write(data)

    def get_and_clear(self, chat_id: int) -> dict | None:
        with self._lock:
            data = self._read()
            if str(chat_id) in data:
                sess = data.pop(str(chat_id))
                self._write(data)
                if time.time() - sess.get('ts', 0) < 900:
                    return sess
            return None

    def clear(self, chat_id: int):
        with self._lock:
            data = self._read()
            if str(chat_id) in data:
                del data[str(chat_id)]
                self._write(data)
AUTH_SESSIONS = AuthSessionStore()

def _atomic_write_json(path: str, data: dict):
    tmp = path + '.tmp'
    try:
        __import__('os').makedirs(__import__('os').path.dirname(path) or '.', exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        print(f'Atomic Write Error: {e}', flush=True)

def _atomic_write_offset(offset: int):
    _atomic_write_json('/attachments/tg_offset.json', {'offset': offset})

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
        return (get_val(t, 'key', 'tibor'), t)
    try:
        if __import__('os').path.exists('/attachments/dynamic_users.json'):
            with open('/attachments/dynamic_users.json', 'r') as f:
                dt = json.load(f)
            if str(chat_id) in dt:
                u_info = dt[str(chat_id)]
                return (f'guest_{chat_id}', {'key': f'guest_{chat_id}', 'label': u_info.get('name', 'Guest'), 'google_account': u_info.get('email', ''), 'openclaw_container': 'openclaw-gateway-tibor', 'is_admin': u_info.get('is_admin', False)})
    except:
        pass
    return (None, None)

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

async def trigger_auth_flow(chat_id: int, email: str, t: dict, scopes: str=''):
    res = await tg.send_message(chat_id, f'🔄 Generating secure OAuth link for <b>{email}</b>...', parse_mode='HTML')
    t_openclaw = get_val(t, 'openclaw_container', 'openclaw-gateway-tibor')
    is_admin = get_val(t, 'is_admin', False) or get_val(t, 'key', '') == 'tibor'
    await asyncio.create_subprocess_exec('docker', 'exec', '-u', 'root', t_openclaw, 'sh', '-c', 'pkill -f gog 2>/dev/null || true')
    await asyncio.sleep(0.5)
    try:
        await asyncio.create_subprocess_exec('docker', 'exec', '-u', 'root', t_openclaw, 'sh', '-c', f'gog auth remove {email} 2>/dev/null || true')
        await asyncio.sleep(0.5)
        scopes_arg = 'calendar' if 'cal' in scopes else 'gmail' if 'mail' in scopes else 'gmail,calendar,tasks'
        cmd = ['docker', 'exec', '-u', 'root', '-e', f'GOG_KEYRING_PASSWORD={getattr(settings, 'gog_keyring_password', 'rangersofB5')}', t_openclaw, 'gog', 'auth', 'add', email, '--services', scopes_arg, '--remote', '--step', '1']
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        out_str = stdout.decode('utf-8', errors='ignore')
        m_url = re.search('(https://accounts\\.google\\.com/[^\\s"\\\'><]+)', out_str)
        if m_url:
            AUTH_SESSIONS.set(chat_id, {'email': email, 'openclaw': t_openclaw, 'services': scopes_arg, 'ts': time.time()})
            admin_note = f'\n\n💡 <b>Admin Troubleshooting:</b>\nEnsure <code>{email}</code> is a Test User in Google Cloud.' if is_admin else ''
            auth_msg = f"🔗 <b>Authorization Required</b>\n\n1. 👉 <b><a href='{m_url.group(1).replace('&amp;', '&').strip()}'>Click here to open Google Login</a></b> 👈\n2. Select <code>{email}</code>.\n3. Copy the broken '127.0.0.1' URL from your browser and paste it here.{admin_note}"
            await tg.edit_message_text(chat_id, res['message_id'], auth_msg, parse_mode='HTML', disable_web_page_preview=True)
        else:
            await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Auth Error:</b>\n<pre>{_safe_err(out_str[-1000:])}</pre>', parse_mode='HTML')
    except Exception as e:
        await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Auth Error:</b> {_safe_err(e)}', parse_mode='HTML')

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
            t_openclaw = get_val(t, 'openclaw_container', '')
            t_account = get_val(t, 'google_account', '')
            for ev in cal_data['events']:
                try:
                    await safe_gog(t_openclaw, ['calendar', 'events', 'add', str(ev.get('title', '')), '--start', str(ev.get('start', '')), '--end', str(ev.get('end', '')), '--location', str(ev.get('location', '')), '--calendar', 'Executive Assistant'], t_account, timeout=10.0)
                except:
                    pass
            await tg.send_message(chat_id, '✅ <b>Calendar Events Imported.</b>', parse_mode='HTML')
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
            clean_rep = clean_html_for_telegram(re.sub('\\[OPTIONS:.*?\\]', '', report).replace('[YES/NO]', ''))
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
                cmd = ['docker', 'exec', '-u', 'root', '-e', f'GOG_KEYRING_PASSWORD={getattr(settings, 'gog_keyring_password', 'rangersofB5')}', t_openclaw, 'gog', 'auth', 'add', email, '--services', services, '--remote', '--step', '2', '--auth-url', url_to_pass]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20.0)
                out_str = ''
                if stdout:
                    out_str += stdout.decode('utf-8', errors='ignore')
                if stderr:
                    out_str += '\n' + stderr.decode('utf-8', errors='ignore')
                if 'error' in out_str.lower() or 'failed' in out_str.lower() or 'invalid' in out_str.lower():
                    await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Token Exchange Failed!</b>\n<pre>{_safe_err(out_str)}</pre>', parse_mode='HTML')
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
            res = await tg.send_message(chat_id, '🖼️ <b>Extracting schedule via 1min.ai gpt-4o...</b>', parse_mode='HTML')
            try:
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
                extracted = await extract_calendar_from_image(img_bytes, 'image/jpeg')
                events = extracted.get('events', [])
                if not events:
                    return await tg.edit_message_text(chat_id, res['message_id'], '⚠️ No calendar events detected.')
                preview = '📅 <b>Found Events:</b>\n' + ''.join([f'• {e.get('start')} - {e.get('title')}\n' for e in events])
                cid = OpenLoops.add_calendar(tenant_name, preview, events)
                kb = [[{'text': f'✅ Execute Import to EA', 'callback_data': f'exec_cal:{cid}'}], [{'text': f'🛑 Discard', 'callback_data': f'drop_cal:{cid}'}]]
                await tg.edit_message_text(chat_id, res['message_id'], preview + '\n\n<i>This import request has been added to your Open Loops.</i>', parse_mode='HTML', reply_markup={'inline_keyboard': kb})
            except Exception as e:
                await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ Vision Error: {_safe_err(e)}', parse_mode='HTML')
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
                    sepa_json = await call_powerful_llm(f'{prompt_str}\n\nText:\n{pdf_text[:4000]}')
                else:
                    b64_img = base64.b64encode(file_bytes).decode('utf-8')
                    payload = {'model': 'gpt-4o', 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt_str}, {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64_img}'}}]}]}
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post('https://api.1min.ai/v1/chat/completions', json=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer 3456b8bc60e3d10b45232b034b822a275b5b5e616eea93e3a3852e6283ac30b0*'})
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
            t_openclaw = get_val(t, 'openclaw_container', 'openclaw-gateway-tibor')
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
                clean_rep = clean_html_for_telegram(re.sub('\\[OPTIONS:.*?\\]', '', report).replace('[YES/NO]', ''))
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
        cmd = parts[0].lower().split('@')[0]
        if cmd == '/auth':
            target_email = parts[1].strip() if len(parts) > 1 else ''
            t_acc = get_val(t, 'google_account', 'tibor.girschele@gmail.com')
            if not target_email:
                kb = [[{'text': f'🔑 All Features ({t_acc})', 'callback_data': f'auth_cb:{save_button_context(f'all|{t_acc}')}'}], [{'text': f'📅 Cal Only ({t_acc})', 'callback_data': f'auth_cb:{save_button_context(f'cal|{t_acc}')}'}], [{'text': '🔑 archon.megalon@gmail.com (All)', 'callback_data': f'auth_cb:{save_button_context('all|archon.megalon@gmail.com')}'}], [{'text': '✏️ Type a different email...', 'callback_data': 'cmd_auth_custom'}]]
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
            try:
                from app.db import get_db

                db = get_db()
                pending = db.fetchone("SELECT count(*) AS c FROM repair_jobs WHERE status = 'pending'")
                active = db.fetchone("SELECT count(*) AS c FROM delivery_sessions WHERE status = 'active'")
                replay_q = db.fetchone("SELECT count(*) AS c FROM replay_events WHERE status IN ('queued', 'retry')")
                dead = db.fetchone("SELECT count(*) AS c FROM replay_events WHERE status = 'deadletter'")
                msg = (
                    "🧠 <b>Mum Brain Status</b>\n\n"
                    f"• Phase A active deliveries: <b>{int((active or {}).get('c') or 0)}</b>\n"
                    f"• Phase B pending repairs: <b>{int((pending or {}).get('c') or 0)}</b>\n"
                    f"• Replay queue: <b>{int((replay_q or {}).get('c') or 0)}</b>\n"
                    f"• Dead letters: <b>{int((dead or {}).get('c') or 0)}</b>"
                )
                return await tg.send_message(chat_id, msg, parse_mode='HTML')
            except Exception as e:
                return await tg.send_message(chat_id, f'⚠️ Mum Brain status error: {_safe_err(e)}')
        if cmd == '/remember':
            rem_text = text[len('/remember'):].strip()
            if not rem_text:
                return await tg.send_message(chat_id, 'Usage: /remember <fact to remember>')
            res = await tg.send_message(chat_id, '🧠 <i>Normalizing memory...</i>', parse_mode='HTML')
            try:
                from app.briefings import call_llm
                import json
                prompt = f'Extract a short 3-5 word title and the core fact from this text. Return STRICT JSON: {{"title": "...", "fact": "..."}}. Text: {rem_text}'
                out = await call_llm(prompt)
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
                    if cached and __import__('os').path.exists(f'{__import__('os').environ.get('EA_ATTACHMENTS_DIR', '/attachments')}/artifacts/{cached['artifact_id']}.png'):
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
                        payload = {'type': 'photo', 'artifact_id': art_id, 'caption': safe_txt[:1000] + ('...' if len(safe_txt) > 1000 else ''), 'parse_mode': 'HTML'}
                        await asyncio.to_thread(enqueue_outbox, tenant, chat_id, payload)
                        try:
                            await tg.delete_message(chat_id, res['message_id'])
                        except:
                            pass
                        return
                except Exception as mg_err:
                    _ea_fault = classify_markupgo_error(mg_err)
                    if _ea_fault in ('invalid_template_id', 'renderer_unavailable'):
                        open_markupgo_breaker(_ea_fault, skill='markupgo', location='poll_listener')
                    try:
                        from app.supervisor import trigger_mum_brain
                        trigger_mum_brain(None, str(mg_err), fallback_mode='simplified-first', failure_class='renderer_fault', intent='brief_render', chat_id=str(chat_id))
                    except Exception:
                        pass
                    log_render_guard('renderer_text_only', _ea_fault, skill='markupgo', location='poll_listener')
                    # Keep raw renderer diagnostics in logs, not in normal user-visible briefings.
                    if str((os.getenv('EA_RENDER_DIAGNOSTIC_TO_CHAT', '') or '')).strip().lower() in ('1', 'true', 'yes', 'on'):
                        safe_txt += f'\n\n⚙️ <b>OODA Diagnostic (Rendering):</b>\n<code>{str(mg_err)}</code>'
                    else:
                        safe_txt += '\n\n📝 <i>Visual template unavailable, switched to safe text mode.</i>'
                try:
                    await tg.edit_message_text(chat_id, res['message_id'], safe_txt, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)
                except Exception as tg_err:
                    print(f'Telegram HTML Parse Error: {tg_err}', flush=True)
                    import html as pyhtml
                    plain_txt = re.sub('<[^>]+>', '', txt).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    if len(plain_txt) > 4000:
                        plain_txt = plain_txt[:4000] + '...[truncated]'
                    try:
                        await tg.edit_message_text(chat_id, res['message_id'], plain_txt, parse_mode=None, reply_markup=markup, disable_web_page_preview=True)
                    except Exception:
                        await tg.edit_message_text(chat_id, res['message_id'], '⚠️ Fatal error rendering briefing.', parse_mode=None)
            except Exception as e:
                err_str = traceback.format_exc()
                await tg.edit_message_text(chat_id, res['message_id'], f'⚠️ <b>Briefing Failed:</b>\n<pre>{_safe_err(err_str)[:1500]}</pre>', parse_mode='HTML')
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
    asyncio.create_task(heartbeat_pinger())
    offset = 0
    try:
        with open('/attachments/tg_offset.json', 'r') as f:
            offset = json.load(f).get('offset', 0)
    except:
        pass
    sem = asyncio.Semaphore(15)
    while True:
        try:
            updates = await tg.get_updates(offset, timeout_s=30)
            global LAST_HEARTBEAT
            LAST_HEARTBEAT = time.time()
            for u in updates:
                offset = u['update_id'] + 1
                await asyncio.to_thread(_atomic_write_offset, offset)

                async def _route_update(u_data):
                    if 'callback_query' in u_data:
                        await handle_callback(u_data['callback_query'])
                    elif 'message' in u_data:
                        msg = u_data['message']
                        chat_id = msg.get('chat', {}).get('id')
                        if not chat_id:
                            return
                        cmd_text = str(msg.get('text') or msg.get('caption') or '').strip()
                        if cmd_text.startswith('/'):
                            await handle_command(chat_id, cmd_text, msg)
                        elif msg.get('text') or msg.get('photo') or msg.get('document') or msg.get('voice') or msg.get('audio'):
                            await handle_intent(chat_id, msg)

                async def _run_with_guard(u_data):
                    async with sem:
                        try:
                            await asyncio.wait_for(_route_update(u_data), timeout=240.0)
                        except asyncio.TimeoutError:
                            print('🚨 SENTINEL: Task timed out!', flush=True)
                asyncio.create_task(safe_task('Route Update', _run_with_guard(u)))
        except Exception as e:
            print(f'POLL LOOP CRASH: {traceback.format_exc()}', flush=True)
            await asyncio.sleep(5)
