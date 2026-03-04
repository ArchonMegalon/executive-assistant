from __future__ import annotations
import os
import re, json, asyncio, traceback, time, html
from datetime import datetime, timezone, timedelta
from app.gog import gog_cli, docker_exec
from app.settings import settings
from app.open_loops import OpenLoops
from app.calendar_store import list_events_range
from app.contracts.llm_gateway import ask_text as gateway_ask_text
from app.contracts.repair import open_repair_incident
from app.contracts.telegram import sanitize_incident_copy
from app.intelligence.profile import build_profile_context
from app.intelligence.dossiers import (
    build_finance_commitment_dossier,
    build_health_dossier,
    build_project_dossier,
    build_trip_dossier,
)
from app.intelligence.critical_lane import build_critical_actions
from app.intelligence.epics import (
    build_epics_from_dossiers,
    load_epic_snapshot,
    rank_epics,
    save_epic_snapshot,
    summarize_epic_deltas,
)
from app.intelligence.future_situations import build_future_situations
from app.intelligence.preparation_planner import build_preparation_plan
from app.intelligence.readiness import build_readiness_dossier
from app.intelligence.household_graph import build_household_graph, ensure_profile_isolation
from app.intelligence.modes import mode_label, select_briefing_mode

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


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _briefing_diagnostics_enabled() -> bool:
    return _env_flag("EA_BRIEFING_DIAGNOSTIC_TO_CHAT", False)


def _emit_internal_diagnostics(diag_logs: list[str]) -> None:
    """
    Keep diagnostics in logs only. Do not append internals to Telegram briefing text.
    """
    if not diag_logs:
        return
    if not _briefing_diagnostics_enabled():
        return
    try:
        joined = "\n".join(str(x) for x in diag_logs if str(x).strip())
        if joined:
            print(f"[BRIEFING][DIAGNOSTICS]\n{joined}", flush=True)
    except Exception:
        pass


def _runtime_confidence_note() -> str | None:
    """
    If the sentinel watchdog recovered the runtime recently, avoid strong
    "nothing urgent" claims and show a confidence warning.
    """
    state_path = os.path.join(os.getenv("EA_ATTACHMENTS_DIR", "/attachments"), ".sentinel_last_alert.json")
    window_sec = max(300, int(os.getenv("EA_BRIEFING_CONFIDENCE_DEGRADE_WINDOW_SEC", "21600")))
    now = int(time.time())
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f) if f else {}
        ts = int((state or {}).get("ts") or 0)
    except Exception:
        ts = 0
    if ts <= 0:
        return None
    age = max(0, now - ts)
    if age > window_sec:
        return None
    age_min = max(1, int(round(age / 60)))
    return (
        f"Briefing confidence reduced: runtime auto-recovery was triggered about {age_min}m ago. "
        "Critical scan ran, but you should verify high-impact commitments explicitly."
    )


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
    return await asyncio.to_thread(
        gateway_ask_text,
        str(prompt),
        task_type="briefing_compose",
        purpose="briefing_compose",
        data_class="derived_summary",
    )

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
        if settings.litellm_base_url:
            diag_logs.append('🔑 LLM Gateway: ✅ LiteLLM route configured.')
        elif settings.gemini_api_key:
            diag_logs.append('🔑 LLM Gateway: ✅ direct provider key configured.')
        else:
            diag_logs.append('🔑 LLM Gateway: ⚠️ no provider credentials configured.')
    except Exception as e:
        diag_logs.append(f'🔑 LLM Gateway: ⚠️ status check error ({e})')
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

    confidence_note = _runtime_confidence_note()
    profile_ctx = build_profile_context(
        tenant=str(t_key),
        person_id=str(t_account or t_key),
        timezone_name=str(getattr(settings, "tz", "UTC") or "UTC"),
        runtime_confidence_note=confidence_note,
        mode="standard_morning_briefing",
    )
    household = build_household_graph(
        principals=[
            {
                "person_id": str(t_account or t_key),
                "tenant": str(t_key),
                "role": "principal",
            }
        ]
    )
    if not ensure_profile_isolation(household):
        diag_logs.append("⚠️ Household graph profile-isolation invariant failed; continuing in single-profile mode.")
    trip_dossier = build_trip_dossier(
        mails=list(clean_mails),
        calendar_events=list(clean_cal),
    )
    project_dossier = build_project_dossier(
        mails=list(clean_mails),
        calendar_events=list(clean_cal),
    )
    finance_dossier = build_finance_commitment_dossier(
        mails=list(clean_mails),
        calendar_events=list(clean_cal),
    )
    health_dossier = build_health_dossier(
        mails=list(clean_mails),
        calendar_events=list(clean_cal),
    )
    dossiers = [
        d
        for d in (trip_dossier, project_dossier, finance_dossier, health_dossier)
        if int(getattr(d, "signal_count", 0)) > 0
    ]
    future_situations = build_future_situations(
        profile=profile_ctx,
        dossiers=dossiers,
        calendar_events=list(clean_cal),
        horizon_hours=max(24, int(os.getenv("EA_FUTURE_SITUATION_HORIZON_HOURS", "72"))),
    )
    critical = build_critical_actions(profile_ctx, dossiers, future_situations=future_situations)
    compose_mode = select_briefing_mode(profile_ctx, dossiers, critical)
    epics = build_epics_from_dossiers(profile_ctx, dossiers)
    safe_tenant = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(t_key or "tenant"))
    epic_snapshot_path = os.path.join(
        os.getenv("EA_ATTACHMENTS_DIR", "/attachments"),
        f".briefing_epics_{safe_tenant}.json",
    )
    previous_epics = load_epic_snapshot(epic_snapshot_path)
    epic_deltas = summarize_epic_deltas(previous_epics, epics)
    save_epic_snapshot(epic_snapshot_path, epics)
    readiness = build_readiness_dossier(
        profile=profile_ctx,
        dossiers=dossiers,
        future_situations=future_situations,
    )
    prep_plan = build_preparation_plan(
        profile=profile_ctx,
        readiness=readiness,
        epics=epics,
    )
    compose_mode = select_briefing_mode(profile_ctx, dossiers, critical, epics=epics)

    prompt = (
        "You are a calm, concise executive assistant. "
        "Prioritize what needs action today and suppress low-value noise.\n"
        "Rules:\n"
        "1) Exclude routine delivery/order notifications unless failed delivery or manual pickup is required.\n"
        "2) For each kept email, give one short action-oriented reason.\n"
        "3) Keep language calm and practical; no technical/system wording.\n"
        "4) Format calendars as a clean timeline grouped by date.\n\n"
        f"DATA:\nMails: {json.dumps(clean_mails, ensure_ascii=False)}\nCalendars: {json.dumps(clean_cal, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON with schema:\n"
        "{\n"
        '  "emails": [{"sender":"Sender","subject":"Subject","churchill_action":"1 sentence action reason","action_button":"Short Command"}],\n'
        '  "calendar_summary":"Clean bulleted timeline grouped by date."\n'
        "}"
    )
    out = await call_llm(prompt)
    try:
        obj = _safe_extract_obj(out)
        if 'error' in obj:
            return {
                'text': '⚠️ <b>Briefing degraded.</b>\nI could not assemble a complete briefing right now. Please retry in about a minute.',
                'options': ['🔁 Retry'],
            }
        if not obj:
            raise ValueError('No valid JSON found in LLM response.')
        loops_txt, loop_btns = OpenLoops.get_dashboard(t_key)
        html_out = '🎩 <b>Executive Action Briefing</b>\n\n'
        html_out += f"<i>Mode:</i> { _sanitize_telegram_html(mode_label(compose_mode)) }\n\n"
        immediate_actions = [str(x) for x in critical.actions if str(x).strip()]
        if immediate_actions:
            html_out += '<b>Immediate Action:</b>\n'
            for a in immediate_actions[:4]:
                html_out += f'• {_sanitize_telegram_html(a)}\n'
            if critical.exposure_score or critical.decision_window_score:
                html_out += (
                    f"<i>Exposure/Decision score:</i> "
                    f"{int(critical.exposure_score)}/{int(critical.decision_window_score)}\n"
                )
            ev = [str(x) for x in critical.evidence if str(x).strip()]
            if ev:
                html_out += f"<i>Signal source:</i> {_sanitize_telegram_html(' | '.join(ev[:2]))}\n"
            html_out += '\n'
        if readiness.blockers:
            html_out += "<b>Why It Matters:</b>\n"
            for blocker in list(readiness.blockers)[:2]:
                html_out += f"• {_sanitize_telegram_html(str(blocker))}\n"
            html_out += "\n"
        ranked_epics = rank_epics(epics)
        if ranked_epics:
            html_out += '<b>Active Epics:</b>\n'
            for epic in ranked_epics[:3]:
                title = _sanitize_telegram_html(str(epic.title or "Epic"))
                status = _sanitize_telegram_html(str(epic.status or "watch"))
                summary = _sanitize_telegram_html(str(epic.summary or ""))
                html_out += (
                    f"• <b>{title}</b> ({status})"
                    f" | salience {int(epic.salience)} | open {int(epic.unresolved_count)}\n"
                )
                if summary:
                    html_out += f"  └ <i>{summary}</i>\n"
            html_out += '\n'
        if epic_deltas:
            html_out += '<b>Epic Deltas:</b>\n'
            for line in list(epic_deltas)[:3]:
                html_out += f"• {_sanitize_telegram_html(str(line))}\n"
            html_out += '\n'
        html_out += (
            f"<b>Readiness:</b> {_sanitize_telegram_html(str(readiness.status).title())} "
            f"(score {int(readiness.score)}/100)\n"
        )
        if readiness.watch_items:
            html_out += "<i>Watch:</i> "
            html_out += _sanitize_telegram_html(" | ".join(list(readiness.watch_items)[:2])) + "\n"
        if prep_plan.actions:
            html_out += "<b>Preparation Plan:</b>\n"
            for step in list(prep_plan.actions)[:4]:
                html_out += f"• {_sanitize_telegram_html(str(step))}\n"
        if prep_plan.confidence_note:
            html_out += f"<i>Confidence:</i> {_sanitize_telegram_html(prep_plan.confidence_note)}\n"
        html_out += "\n"
        html_out += loops_txt
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
            if critical.actions:
                html_out += '<i>No additional inbox-critical items after deterministic critical scan.</i>\n\n'
            elif confidence_note:
                html_out += '<i>Runtime confidence is reduced; urgent status may be incomplete. Please verify high-impact commitments.</i>\n\n'
            else:
                html_out += '<i>No immediate action blocks detected right now.</i>\n\n'
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
        _emit_internal_diagnostics(diag_logs)
        clean_opts = [str(o) for o in options][:5]
        return {'text': html_out, 'options': clean_opts, 'dynamic_buttons': loop_btns}
    except Exception as e:
        print(f"Briefing composition error: {e}", flush=True)
        return {
            'text': '⚠️ <b>Briefing degraded.</b>\nI could not complete the briefing safely. Please retry in about a minute.',
            'options': ['🔁 Retry'],
        }
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
        emojis = ['⏳', '⌛', '📝', '📅']
        await asyncio.sleep(1.0)
        while True:
            ticks += 1
            try:
                elapsed = ticks * 2
                if elapsed >= 12:
                    sub = '\n\n<i>Still working. If this takes longer, simplified delivery will be used automatically.</i>'
                elif elapsed >= 6:
                    sub = '\n\n<i>Collecting final details.</i>'
                else:
                    sub = ''
                msg = f'▶️ <b>Preparing your briefing...</b> {emojis[ticks % len(emojis)]} ({elapsed}s){sub}'
                res = status_cb(msg)
                if inspect.isawaitable(res):
                    await res
            except asyncio.CancelledError:
                try:
                    res = status_cb('✅ Briefing prepared.')
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
        return await asyncio.to_thread(
            gateway_ask_text,
            str(prompt),
            task_type="briefing_compose",
            purpose="briefing_compose",
            data_class="derived_summary",
        )
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
            return {
                "text": sanitize_incident_copy(error_payload, correlation_id=cid, mode=mode),
                "options": [],
                "dynamic_buttons": [],
            }
        except Exception as inner_e:
            print(f'L2 Wrapper crashed: {inner_e}')
            return {
                "text": "⏳ <i>Preparing your briefing in safe mode. Formatting repair is running in background.</i>",
                "options": [],
                "dynamic_buttons": [],
            }
    if isinstance(res, dict):
        return res
    return {
        "text": str(res or "⚠️ Briefing response was empty."),
        "options": [],
        "dynamic_buttons": [],
    }
