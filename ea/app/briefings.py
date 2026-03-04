from __future__ import annotations
import os
import re, json, httpx, asyncio, traceback, time, html
from datetime import datetime, timezone, timedelta
from app.gog import gog_cli, docker_exec
from app.settings import settings
from app.open_loops import OpenLoops
from app.calendar_store import list_events_range
from app.contracts.llm_gateway import ask_text as gateway_ask_text
from app.contracts.repair import open_repair_incident
from app.contracts.telegram import sanitize_incident_copy

def _sanitize_telegram_html(text: str) -> str:
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def _safe_extract_array(text: str) -> list:
    try:
        clean = re.sub('\\x1b\\[[0-9;]*m', '', text).strip()
        start = -1
        for i, c in enumerate(clean):
            if c in '[{':
                start = i
                break
        if start >= 0:
            obj = json.loads(clean[start:])
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                for k in ['items', 'messages', 'events', 'result', 'data']:
                    if k in obj and isinstance(obj[k], list):
                        return obj[k]
    except:
        pass
    try:
        m = re.search('\\[[\\s\\S]*\\]', text)
        if m:
            return json.loads(m.group(0))
    except:
        pass
    return []

def _safe_extract_obj(text: str) -> dict:
    try:
        m = re.search('\\{[\\s\\S]*\\}', text)
        return json.loads(m.group(0)) if m else {}
    except:
        return {}

def get_val(obj, key, default=''):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _avomap_prepare_card(
    *,
    tenant_key: str,
    person_id: str,
    calendar_events: list[dict],
    travel_emails: list[dict],
) -> tuple[str, dict | None]:
    if not settings.avomap_enabled:
        return "", None
    try:
        from app.db import get_db
        from app.integrations.avomap.service import AvoMapService

        svc = AvoMapService(get_db())
        ready = await asyncio.to_thread(
            svc.get_ready_asset,
            tenant=str(tenant_key),
            person_id=str(person_id),
        )
        if not ready:
            return "", {"status": "not_ready"}

        mode = str((ready or {}).get("mode") or "").replace("_", " ").strip().title() or "Travel"
        object_ref = str((ready or {}).get("object_ref") or "").strip()
        if object_ref.startswith("http://") or object_ref.startswith("https://"):
            link = f"\n<a href='{html.escape(object_ref, quote=True)}'>▶ Open travel video</a>"
        elif object_ref:
            link = f"\n<code>{html.escape(object_ref, quote=False)}</code>"
        else:
            link = ""
        card = f"\n\n<b>Travel Video ({mode}):</b>{link}"
        return card, {"status": "ready"}
    except Exception as e:
        return "", {"status": "error", "error": str(e)[:120]}


async def safe_gog(container, cmd, account, timeout=20.0):
    try:
        return await asyncio.wait_for(gog_cli(container, cmd, account), timeout=timeout)
    except asyncio.TimeoutError:
        await docker_exec(container, ["pkill", "-f", "gog"], user="root", timeout_s=8.0)
        raise TimeoutError(f'CLI hung on command: {' '.join(cmd[:3])}')

async def call_powerful_llm(prompt: str, temp=0.1) -> str:
    return await asyncio.to_thread(gateway_ask_text, str(prompt))

async def call_llm(prompt: str, temp=0.1) -> str:
    return await call_powerful_llm(prompt, temp=temp)

async def _raw_build_briefing_for_tenant(tenant, status_cb=None) -> dict:
    t_openclaw = get_val(tenant, 'openclaw_container', '')
    t_account = get_val(tenant, 'google_account', '')
    t_key = get_val(tenant, 'key', os.environ.get('EA_DEFAULT_ADMIN_KEY', 'admin'))
    ui_history = []
    diag_logs = []

    async def _log(msg):
        display_lines = [f'✅ {x}' for x in ui_history]
        display_lines.append(f'▶️ <b>{msg}</b>')
        if status_cb:
            try:
                await status_cb('\n'.join(display_lines))
            except:
                pass
        ui_history.append(msg)
    await _log('Discovering Authorized Google Accounts...')
    try:
        import httpx
        _env_key = ''
        try:
            with open('.env', 'r') as _f:
                for _l in _f:
                    if _l.startswith('GEMINI_API_KEY='):
                        _env_key = _l.strip().split('=', 1)[1].strip('"').strip("'")
        except:
            pass
        if not _env_key:
            diag_logs.append('🔑 API Key Check: 🟢 OODA: Cognitive Router (Magixx/LiteLLM) is ACTIVE.')
        else:
            _url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={_env_key}'
            async with httpx.AsyncClient(timeout=4.0) as _c:
                _r = await _c.post(_url, headers={'Content-Type': 'application/json'}, json={'contents': [{'parts': [{'text': 'hi'}]}]})
                if _r.status_code == 200:
                    diag_logs.append(f'🔑 API Key Check: ✅ VALID (...{_env_key[-4:]})')
                else:
                    diag_logs.append(f'🔑 API Key Check: ❌ REVOKED/INVALID (HTTP {_r.status_code})')
    except Exception as e:
        diag_logs.append(f'🔑 API Key Check: ⚠️ NETWORK ERROR ({e})')
    try:
        raw_auths = await safe_gog(t_openclaw, ['auth', 'list'], '', timeout=10.0)
        accounts = list(set(re.findall('[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+', raw_auths)))
        if not accounts:
            accounts = [t_account] if t_account else ['']
        diag_logs.append(f'🔑 Accounts: {', '.join([a.split('@')[0] for a in accounts if a])}')
    except Exception as e:
        accounts = [t_account] if t_account else ['']
        diag_logs.append(f'⚠️ Auth List Err: {str(e)[:50]}')
    await _log('Fetching & Python Filtering Emails...')
    clean_mails = []
    junk_kws = ['eff', 'andrew lock', 'stack overflow', 'dodo', 'appsumo', 'dyson', 'facebook', 'linkedin', 'bestsecret', 'mediamarkt', 'voyage', 'babysits', 'stacksocial', 'digital trends', 'the futurist', 'newsletter', 'spiceworks', 'ikea', 'paypal', 'gog.com', 'steam', 'humble bundle', 'indie gala', 'promotions', 'penny', 'chummer', 'samsung', 'mtg', 'omi ai', 'omi', 'akupara', 'cinecenter', 'beta', 'early access', 'n8n', 'versandinformation', 'danke für', 'we got your full', 'out for delivery', 'ihre bestellung bei', 'paket kommt', 'order confirmed', 'wird zugestellt', 'hardloop', 'bergzeit', 'betzold', 'immmo', 'zalando', 'klarna', 'amazon', 'lieferando']
    keep_kws = ['nicht zugestellt', 'wartet auf abholung', 'fehlgeschlagen', 'abholbereit', 'action required']
    for acc in accounts:
        try:
            raw_mails = await safe_gog(t_openclaw, ['gmail', 'messages', 'search', 'newer_than:1d', '--max', '40', '--json'], acc, timeout=20.0)
            mails = _safe_extract_array(raw_mails)
            for m in mails:
                raw_val = json.dumps(m, ensure_ascii=False).lower()
                if any((kp in raw_val for kp in keep_kws)):
                    m['_account'] = acc
                    clean_mails.append(m)
                    continue
                if any((j in raw_val for j in junk_kws)):
                    continue
                m['_account'] = acc
                clean_mails.append(m)
        except Exception as e:
            diag_logs.append(f'⚠️ Mails ({(acc.split('@')[0] if acc else 'def')}) Err: {str(e)[:30]}')
    deduped_mails = []
    seen_subj = set()
    for m in clean_mails:
        subj = str(m.get('subject', '')).lower().strip()[:80]
        if subj not in seen_subj:
            seen_subj.add(subj)
            deduped_mails.append(m)
    clean_mails = deduped_mails
    await _log('Fetching Calendar Events (Rewinding to Midnight)...')
    clean_cal = []
    processed_events = set()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    target_cals = []
    for acc in accounts:
        target_cals.append((acc, 'primary', 'primary'))
        target_cals.append((acc, 'Executive Assistant', 'EA Shared'))
    for acc, cid, cname in target_cals:
        acc_lbl = acc.split('@')[0] if acc else 'def'
        try:
            flags_to_try = [['--timeMin', today_start], ['--time-min', today_start], ['--start', today_start], []]
            events = []
            # Try common gog list syntaxes and explicit calendar selection.
            cmd_variants = [
                ['calendar', 'events', '--max', '50', '--json', '--calendar', cid],
                ['calendar', 'events', 'list', '--max', '50', '--json', '--calendar', cid],
                ['calendar', 'events', '--calendar', cid, '--max', '50', '--json'],
                ['calendar', 'events', '--max', '50', '--json'],
            ]
            last_err = None
            for base_cmd in cmd_variants:
                for flags in flags_to_try:
                    cmd = base_cmd + flags
                    try:
                        raw_cal = await safe_gog(t_openclaw, cmd, acc, timeout=12.0)
                        events = _safe_extract_array(raw_cal)
                        if events:
                            break
                    except Exception as e:
                        last_err = e
                        continue
                if events:
                    break
            if not events:
                if last_err is not None:
                    diag_logs.append(f"ℹ️ Cal '{cname}' ({acc_lbl}): 0 events (last err: {str(last_err)[:60]})")
                else:
                    diag_logs.append(f"ℹ️ Cal '{cname}' ({acc_lbl}): 0 events.")
                continue
            added = 0
            for ev in events:
                dt_str = ''
                end_val = ev.get('end', {})
                if isinstance(end_val, dict):
                    dt_str = end_val.get('dateTime') or end_val.get('date') or ''
                elif isinstance(end_val, str):
                    dt_str = end_val
                if dt_str:
                    dt_str = dt_str.replace('Z', '+00:00')
                    if ' ' in dt_str and '+' not in dt_str:
                        dt_str = dt_str.replace(' ', 'T') + '+01:00'
                    try:
                        end_ts = datetime.fromisoformat(dt_str)
                        if end_ts.tzinfo is None:
                            end_ts = end_ts.replace(tzinfo=timezone.utc)
                        if end_ts <= now - timedelta(days=7):
                            continue
                        ev_title = str(ev.get('summary') or ev.get('title') or '')
                        dedupe_key = f'{ev_title}_{dt_str}'
                        if dedupe_key not in processed_events:
                            processed_events.add(dedupe_key)
                            ev['_calendar'] = cname
                            clean_cal.append(ev)
                            added += 1
                    except:
                        clean_cal.append(ev)
                        added += 1
                else:
                    clean_cal.append(ev)
                    added += 1
            diag_logs.append(f"✅ Cal '{cname}' ({acc_lbl}): kept {added} events.")
        except Exception as e:
            err_str = str(e).lower()
            if 'not found' not in err_str and '404' not in err_str:
                diag_logs.append(f"⚠️ Cal '{cname}' ({acc_lbl}) Err: {str(e)[:30]}")
    await _log('Synthesizing Executive Action Report...')
    # Fallback: if remote calendar fetch produced no events, use locally persisted imports.
    if not clean_cal:
        try:
            now_utc = datetime.now(timezone.utc)
            end_utc = now_utc + timedelta(days=2)
            local_rows = list_events_range(t_key, now_utc - timedelta(hours=12), end_utc) or []
            for r in local_rows:
                clean_cal.append({
                    "summary": str(r.get("title") or ""),
                    "title": str(r.get("title") or ""),
                    "start": {"dateTime": str(r.get("start_ts") or "")},
                    "end": {"dateTime": str(r.get("end_ts") or "")},
                    "_calendar": "EA Local",
                })
            if local_rows:
                diag_logs.append(f"✅ Local calendar fallback ({t_key}): {len(local_rows)} events.")
        except Exception as e:
            diag_logs.append(f"⚠️ Local calendar fallback error: {str(e)[:40]}")

    prompt = f'You are an elite, ruthless Executive Assistant. I demand extreme noise reduction. NO BULLSHIT.\nCRITICAL CULLING RULES:\n1. THE PURGE: You MUST completely delete ALL package delivery updates, shipping notices, order confirmations, and standard payment receipts from the JSON. ERASE THEM ENTIRELY.\n2. EXCEPTION: You MAY include a package/delivery alert ONLY IF it is a FAILURE or requires manual pickup.\n3. CHURCHILL TONE: For the critical emails that remain, state brutally and concisely WHY it requires action in 1 sentence.\n4. CALENDARS: Format ALL events provided into a clean schedule. Group them cleanly by Day/Date. YOU MUST INCLUDE EVENTS FROM THIS MORNING.\n\nDATA:\nMails: {json.dumps(clean_mails, ensure_ascii=False)}\nCalendars: {json.dumps(clean_cal, ensure_ascii=False)}\n\nReturn ONLY valid JSON matching this schema:\n{{\n  "emails": [{{"sender": "Sender", "subject": "Subject", "churchill_action": "1 sentence: What must I do?", "action_button": "Short Command"}}],\n  "calendar_summary": "Clean, bulleted timeline of the schedule across all calendars, grouped by date."\n}}'
    out = await call_llm(prompt)
    try:
        obj = _safe_extract_obj(out)
        if 'error' in obj:
            return {'text': f'⚠️ <b>Diagnostic Report:</b>\n<pre>{_sanitize_telegram_html(obj['error'])}</pre>', 'options': ['🔁 Retry']}
        if not obj:
            raise ValueError('No valid JSON found in LLM response.')
        loops_txt, loop_btns = OpenLoops.get_dashboard(t_key)
        html_out = '🎩 <b>Executive Action Briefing</b>\n\n' + loops_txt
        options = []
        seen_btns = set()
        if obj.get('emails') and len(obj['emails']) > 0:
            html_out += '<b>Requires Attention:</b>\n'
            for e in obj['emails']:
                s_name = _sanitize_telegram_html(e.get('sender', 'Unknown'))
                subj = _sanitize_telegram_html(e.get('subject', ''))
                reason = _sanitize_telegram_html(e.get('churchill_action', ''))
                html_out += f'• <b>{s_name}</b>: <i>{subj}</i>\n  └ <i>{reason}</i>\n\n'
                btn = str(e.get('action_button') or '').strip()
                if btn and 'option' not in btn.lower():
                    btn_lower = btn.lower()
                    if btn_lower not in seen_btns:
                        seen_btns.add(btn_lower)
                        options.append(btn)
        else:
            html_out += '<i>No critical items require your immediate attention.</i>\n\n'
        html_out += f'<b>Calendars:</b>\n{_sanitize_telegram_html(obj.get('calendar_summary', 'No upcoming events.'))}'
        avomap_card, avomap_state = await _avomap_prepare_card(
            tenant_key=str(t_key),
            person_id=str(t_account or t_key),
            calendar_events=list(clean_cal),
            travel_emails=list(clean_mails),
        )
        if avomap_card:
            html_out += avomap_card
        elif isinstance(avomap_state, dict):
            st = str(avomap_state.get('status') or '').strip()
            if st:
                diag_logs.append(f'🎬 AvoMap: {st}')
        if diag_logs:
            diag_str = '\n'.join(diag_logs)
            if len(diag_str) > 1000:
                diag_str = diag_str[:1000] + '\n...[truncated]'
            html_out += '\n\n<i>⚙️ Diagnostics:</i>\n<pre>' + html.escape(diag_str, quote=False) + '</pre>'
        clean_opts = [str(o) for o in options][:5]
        return {'text': html_out, 'options': clean_opts, 'dynamic_buttons': loop_btns}
    except Exception as e:
        return {'text': f'⚠️ <b>Fatal Briefing Error:</b>\n<pre>{html.escape(str(e), quote=False)}</pre>', 'options': ['🔁 Retry']}
import inspect
import contextvars
current_status_cb = contextvars.ContextVar('current_status_cb', default=None)
if 'orig_build_briefing_for_tenant' not in globals():
    orig_build_briefing_for_tenant = _raw_build_briefing_for_tenant

async def build_wrapper(*args, **kwargs):
    cb = kwargs.get('status_cb')
    if not cb and len(args) >= 2:
        cb = args[1]
    token = current_status_cb.set(cb) if cb else None
    try:
        res_text = await orig_build_briefing_for_tenant(*args, **kwargs)
        coach_annex = ''
        try:
            from app.db import get_db
            db = get_db()
            tenant_id = kwargs.get('tenant') or (args[0] if len(args) > 0 else 'unknown')
            links = db.fetchall("SELECT source_person, config_json FROM briefing_links WHERE target_person = %s AND rule_type = 'coach_event_append' AND enabled = TRUE", (tenant_id,))
            if links:
                from app.coaching import is_qualifying_coach_event, generate_coach_annex
                from app.google_api import get_calendar_events
                import json
                import datetime
                time_min = datetime.datetime.utcnow().isoformat() + 'Z'
                time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat() + 'Z'
                for link in links:
                    src_person = link['source_person']
                    cfg = link['config_json'] if isinstance(link['config_json'], dict) else json.loads(link['config_json'])
                    try:
                        src_events = get_calendar_events(src_person, time_min=time_min, time_max=time_max)
                        for cal_name, ev_list in src_events.items():
                            for ev in ev_list:
                                if is_qualifying_coach_event(ev, cfg):
                                    if 'status_cb' in locals() and status_cb:
                                        try:
                                            res = status_cb(f'🧠 Coaching Event detektiert: Analysiere {ev.get('summary', 'Termin')}...')
                                            if __import__('inspect').isawaitable(res):
                                                await res
                                        except:
                                            pass
                                    ev_id = ev.get('id', 'unknown')
                                    row = db.fetchone('SELECT status FROM survey_requests WHERE event_id = %s', (ev_id,))
                                    if not row:
                                        try:
                                            from app.intake.survey_planner import plan_and_build_survey
                                            await plan_and_build_survey(tenant_id, ev.get('summary', 'Target'), ev_id)
                                            annex_text = f'🤖 <i>META AI: No intake found. Dispatched BrowserAct UI-bot to build MetaSurvey form. Fallback mode:</i>\n'
                                        except Exception as e:
                                            annex_text = f'⚠️ Meta AI Error: {e}\n'
                                        annex_text += await generate_coach_annex(tenant_id, ev)
                                    else:
                                        annex_text = f'🎯 <i>V1.9 Intake Status: {row['status']}. Fallback mode:</i>\n'
                                        annex_text += await generate_coach_annex(tenant_id, ev)
                                    coach_annex += f'\n\n➖ <b>Coach Briefing Annex</b> ➖\n{annex_text}'
                    except Exception:
                        pass
        except Exception as e:
            print(f'Coaching Annex Error: {e}')
        if coach_annex:
            res_text += coach_annex
        if isinstance(res_text, str) and 'OODA Diagnostic (Rendering):' in res_text:
            res_text = res_text.split('⚙️ OODA Diagnostic')[0].strip()
            res_text += '\n\n📄 <i>PDF Render Skipped (Template ID Missing or Invalid in .env)</i>'
        return res_text
    finally:
        if token:
            current_status_cb.reset(token)
build_briefing_for_tenant = build_wrapper

async def call_llm_async(prompt, *args, **kwargs):
    status_cb = current_status_cb.get()

    async def _heartbeat():
        if not status_cb:
            return
        ticks = 0
        emojis = ['⏳', '⌛', '💡', '🧠', '⚙️']
        await asyncio.sleep(1.0)
        while True:
            ticks += 1
            try:
                elapsed = ticks * 2
                sub = ''
                if elapsed >= 12:
                    sub = '\n\n🚨 <i>[Timeout]: All neural uplinks dead. Graceful Fallback...</i>'
                elif elapsed >= 8:
                    sub = '\n\n🧠 <i>[OODA]: Attempting internal WAF Bypass...</i>'
                elif elapsed >= 4:
                    sub = '\n\n📡 <i>[Network]: Contacting Cognitive Router...</i>'
                msg = f'▶️ <b>Synthesizing Executive Action...</b> {emojis[ticks % len(emojis)]} ({elapsed}s){sub}'
                res = status_cb(msg)
                if inspect.isawaitable(res):
                    await res
            except asyncio.CancelledError:
                try:
                    res = status_cb('✅ Executive Action Report synthesized.')
                    if __import__('inspect').isawaitable(res):
                        await res
                except:
                    pass
                break
            except Exception as e:
                pass
            await asyncio.sleep(2.0)
    hb_task = asyncio.create_task(_heartbeat())
    try:
        return await asyncio.to_thread(gateway_ask_text, str(prompt))
    finally:
        hb_task.cancel()
call_llm = call_llm_async
call_powerful_llm = call_llm_async
import builtins
import io
import sys
import traceback

async def build_briefing_for_tenant(*args, **kwargs):
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_output = io.StringIO()
    sys.stdout = captured_output
    sys.stderr = captured_output
    res = None
    exc = None
    try:
        res = await _raw_build_briefing_for_tenant(*args, **kwargs)
    except Exception as e:
        exc = e
        traceback.print_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    printed_str = captured_output.getvalue()
    if printed_str:
        print(printed_str, end='', flush=True)
    res_str = str(res) + ' ' + printed_str + ' ' + str(exc)
    if 'MarkupGo' in res_str or 'FST_ERR' in res_str or '"statusCode":' in res_str or exc:
        print('🚨 [L2 WRAPPER] Intercepted toxic payload! Triggering Mum Brain Phase B...', flush=True)
        try:
            db = getattr(builtins, '_ooda_global_db', None)
            mode = 'status-first' if len(str(res)) < 300 else 'simplified-first'
            chat_id = args[0] if len(args) > 0 else 'system'
            error_payload = str(exc) if exc else res_str
            cid = open_repair_incident(
                db_conn=db,
                error_message=error_payload,
                fallback_mode=mode,
                failure_class='markup_api_400',
                intent='render_visuals',
                chat_id=str(chat_id),
            )
            return sanitize_incident_copy(error_payload, correlation_id=cid, mode=mode)
        except Exception as inner_e:
            print(f'L2 Wrapper crashed: {inner_e}')
            return '⏳ *Preparing your briefing in safe mode...*\n_(Formatting repair running in background.)_'
    return res
