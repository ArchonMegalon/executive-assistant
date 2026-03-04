from __future__ import annotations
import os
import re, json, asyncio, traceback, time, html
from datetime import datetime, timezone, timedelta
from app.settings import settings
from app.open_loops import OpenLoops
from app.contracts.llm_gateway import ask_text as gateway_ask_text
from app.contracts.repair import open_repair_incident
from app.contracts.telegram import sanitize_incident_copy
from app.intelligence.profile import build_profile_context
from app.intelligence.dossiers import (
    build_finance_commitment_dossier,
    build_health_dossier,
    build_household_ops_dossier,
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
from app.intelligence.modes import select_briefing_mode
from app.intelligence.human_compose import compose_briefing_html
from app.intelligence.source_acquisition import collect_briefing_sources

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
    # v1.19.3 hard boundary: diagnostics are never user-surface content.
    # Keep this helper for backwards-compatibility with old call sites/tests.
    return False


def _emit_internal_diagnostics(diag_logs: list[str]) -> None:
    """
    Keep diagnostics in logs only. Do not append internals to Telegram briefing text.
    """
    if not diag_logs:
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


async def call_powerful_llm(prompt: str, temp=0.1, tenant: str = "", person_id: str = "") -> str:
    return await asyncio.to_thread(
        gateway_ask_text,
        str(prompt),
        task_type="briefing_compose",
        purpose="briefing_compose",
        data_class="derived_summary",
        tenant=str(tenant or ""),
        person_id=str(person_id or ""),
    )

async def call_llm(prompt: str, temp=0.1, tenant: str = "", person_id: str = "") -> str:
    return await call_powerful_llm(prompt, temp=temp, tenant=tenant, person_id=person_id)

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
    try:
        if settings.litellm_base_url:
            diag_logs.append('🔑 LLM Gateway: ✅ LiteLLM route configured.')
        elif settings.gemini_api_key:
            diag_logs.append('🔑 LLM Gateway: ✅ direct provider key configured.')
        else:
            diag_logs.append('🔑 LLM Gateway: ⚠️ no provider credentials configured.')
    except Exception as e:
        diag_logs.append(f'🔑 LLM Gateway: ⚠️ status check error ({e})')
    source_bundle = await collect_briefing_sources(
        openclaw_container=str(t_openclaw or ""),
        primary_account=str(t_account or ""),
        tenant_key=str(t_key or ""),
        status_cb=_log,
    )
    clean_mails = list(source_bundle.mails or [])
    clean_cal = list(source_bundle.calendar_events or [])
    diag_logs.extend(list(source_bundle.diagnostics or []))
    await _log('Synthesizing Executive Action Report...')

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
    household_ops_dossier = build_household_ops_dossier(
        mails=list(clean_mails),
        calendar_events=list(clean_cal),
    )
    dossiers = [
        d
        for d in (
            trip_dossier,
            project_dossier,
            finance_dossier,
            health_dossier,
            household_ops_dossier,
        )
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
    try:
        from app.intelligence.snapshots import save_intelligence_snapshot

        await asyncio.to_thread(
            save_intelligence_snapshot,
            tenant=str(t_key),
            person_id=str(t_account or t_key),
            compose_mode=str(compose_mode),
            profile=profile_ctx,
            dossiers=dossiers,
            future_situations=future_situations,
            readiness=readiness,
            critical=critical,
            preparation=prep_plan,
            epics=epics,
            source="briefing_compose",
        )
    except Exception:
        pass

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
    out = await call_llm(prompt, tenant=str(t_key), person_id=str(t_account or t_key))
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
        html_out, clean_opts = compose_briefing_html(
            compose_mode=str(compose_mode),
            critical=critical,
            readiness=readiness,
            prep_plan=prep_plan,
            ranked_epics=rank_epics(epics),
            epic_deltas=list(epic_deltas or []),
            llm_obj=obj,
            loops_txt=loops_txt,
            confidence_note=confidence_note,
        )
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
        clean_opts = [str(o) for o in clean_opts][:5]
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
    tenant = str(kwargs.get("tenant") or "")
    person_id = str(kwargs.get("person_id") or "")

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
            tenant=tenant,
            person_id=person_id,
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
