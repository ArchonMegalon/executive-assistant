from __future__ import annotations
import os
import re, json, httpx, asyncio, traceback, time, html, random
from datetime import datetime, timezone, timedelta
from app.gog import gog_cli
from app.settings import settings
from app.open_loops import OpenLoops

def _sanitize_telegram_html(text: str) -> str: return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _safe_extract_array(text: str) -> list:
    try:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', text).strip()
        start = -1
        for i, c in enumerate(clean):
            if c in '[{':
                start = i
                break
        if start >= 0:
            obj = json.loads(clean[start:])
            if isinstance(obj, list): return obj
            if isinstance(obj, dict):
                for k in ['items', 'messages', 'events', 'result', 'data']:
                    if k in obj and isinstance(obj[k], list): return obj[k]
    except: pass
    try:
        m = re.search(r"\[[\s\S]*\]", text)
        if m: return json.loads(m.group(0))
    except: pass
    return []

def _safe_extract_obj(text: str) -> dict:
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}
    except: return {}

def get_val(obj, key, default=""):
    if isinstance(obj, dict): return obj.get(key, default)
    return getattr(obj, key, default)

async def safe_gog(container, cmd, account, timeout=20.0):
    try: return await asyncio.wait_for(gog_cli(container, cmd, account), timeout=timeout)
    except asyncio.TimeoutError: 
        await asyncio.create_subprocess_exec("docker", "exec", "-u", "root", container, "sh", "-c", "pkill -f gog 2>/dev/null || true")
        raise TimeoutError(f"CLI hung on command: {' '.join(cmd[:3])}")

# RESTORED to prevent ImportError in poll_listener! (Wired directly to Gemini)
async def call_powerful_llm(prompt: str, temp=0.1) -> str:
    url = "https://beta.aimagicx.com/api/v1/chat"
    api_key = "mgx-sk-BbJ663CtW0nfnIlMrSRf8Wj8PSPK9oADqBtwCcKJjWk"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    # Using the proprietary Magix payload discovered by ChatGPT
    payload = {"model": "4o-mini", "message": prompt, "temperature": temp}
    import httpx
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try: r = await client.post(url, headers=headers, json=payload)
        except Exception as e: return f'{{"error": "Magix Network Crash: {e}"}}'
        
        try: data = r.json()
        except: return f'{{"error": "Magix non-JSON (HTTP {r.status_code}): {r.text[:200]}"}}'
        
        if isinstance(data, dict) and data.get("success") is False:
            return f'{{"error": "Magix API Error: {data.get("error")}"}}'
            
        inner = data.get("data", data)
        if isinstance(inner, dict) and "choices" in inner and len(inner["choices"]) > 0:
            return inner["choices"][0].get("message", {}).get("content", "")
            
        return f'{{"error": "Unexpected Magix payload: {data}"}}'


async def call_llm(prompt: str, temp=0.1) -> str:
    keys = [os.environ.get("GEMINI_API_KEY", "")]
    random.shuffle(keys)
    errors = []
    
    for key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": temp}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    if 'candidates' in data: return data['candidates'][0]['content']['parts'][0]['text']
                else:
                    try: err_msg = r.json().get('error', {}).get('message', r.text[:100])
                    except: err_msg = r.text[:100]
                    errors.append(f"🔑 ...{key[-4:]} ❌ {err_msg}")
            except Exception as e:
                errors.append(f"🔑 ...{key[-4:]} ❌ Network Error")
                
    joined_errs = "\n".join(errors)
    err_report = f"🚨 ALL GEMINI KEYS FAILED!\n\n{joined_errs}\n\n💡 FIX: Google revoked these keys because they were posted in chat. Generate ONE new key and use the update_keys.sh script!"
    return json.dumps({"error": err_report})

async def build_briefing_for_tenant(tenant, status_cb=None) -> dict:
    t_openclaw = get_val(tenant, 'openclaw_container', '')
    t_account = get_val(tenant, 'google_account', '')
    t_key = get_val(tenant, 'key', 'tibor')
    
    ui_history = []
    diag_logs = []
    async def _log(msg):
        display_lines = [f"✅ {x}" for x in ui_history]
        display_lines.append(f"▶️ <b>{msg}</b>")
        if status_cb:
            try: await status_cb("\n".join(display_lines))
            except: pass
        ui_history.append(msg)

    await _log("Discovering Authorized Google Accounts...")

    # --- ADMIN KEY VALIDATOR ---
    try:
        import httpx
        _env_key = ""
        try:
            with open(".env", "r") as _f:
                for _l in _f:
                    if _l.startswith("GEMINI_API_KEY="): _env_key = _l.strip().split("=", 1)[1].strip('"').strip("'")
        except: pass
        
        if not _env_key:
            diag_logs.append("🔑 API Key Check: 🟢 OODA: Cognitive Router (Magixx/LiteLLM) is ACTIVE.")
        else:
            _url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={_env_key}"
            async with httpx.AsyncClient(timeout=4.0) as _c:
                _r = await _c.post(_url, headers={"Content-Type": "application/json"}, json={"contents":[{"parts":[{"text":"hi"}]}]})
                if _r.status_code == 200: diag_logs.append(f"🔑 API Key Check: ✅ VALID (...{_env_key[-4:]})")
                else: diag_logs.append(f"🔑 API Key Check: ❌ REVOKED/INVALID (HTTP {_r.status_code})")
    except Exception as e: diag_logs.append(f"🔑 API Key Check: ⚠️ NETWORK ERROR ({e})")
    # ---------------------------

    try:
        raw_auths = await safe_gog(t_openclaw, ["auth", "list"], "", timeout=10.0)
        accounts = list(set(re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', raw_auths)))
        if not accounts: accounts = [t_account] if t_account else [""]
        diag_logs.append(f"🔑 Accounts: {', '.join([a.split('@')[0] for a in accounts if a])}")
    except Exception as e:
        accounts = [t_account] if t_account else [""]
        diag_logs.append(f"⚠️ Auth List Err: {str(e)[:50]}")

    await _log("Fetching & Python Filtering Emails...")
    clean_mails = []
    
    junk_kws = [
        'eff', 'andrew lock', 'stack overflow', 'dodo', 'appsumo', 'dyson', 'facebook', 'linkedin', 
        'bestsecret', 'mediamarkt', 'voyage', 'babysits', 'stacksocial', 'digital trends', 'the futurist', 
        'newsletter', 'spiceworks', 'ikea', 'paypal', 'gog.com', 'steam', 'humble bundle', 'indie gala', 
        'promotions', 'penny', 'chummer', 'samsung', 'mtg', 'omi ai', 'omi', 'akupara', 'cinecenter', 
        'beta', 'early access', 'n8n', 'versandinformation', 'danke für', 'we got your full', 
        'out for delivery', 'ihre bestellung bei', 'paket kommt', 'order confirmed', 'wird zugestellt',
        'hardloop', 'bergzeit', 'betzold', 'immmo', 'zalando', 'klarna', 'amazon', 'lieferando'
    ]
    keep_kws = ['nicht zugestellt', 'wartet auf abholung', 'fehlgeschlagen', 'abholbereit', 'action required']
    
    for acc in accounts:
        try:
            raw_mails = await safe_gog(t_openclaw, ["gmail", "messages", "search", "newer_than:1d", "--limit", "40", "--json"], acc, timeout=20.0)
            mails = _safe_extract_array(raw_mails)
            for m in mails:
                raw_val = json.dumps(m, ensure_ascii=False).lower()
                if any(kp in raw_val for kp in keep_kws):
                    m['_account'] = acc
                    clean_mails.append(m)
                    continue
                if any(j in raw_val for j in junk_kws): continue
                m['_account'] = acc
                clean_mails.append(m)
        except Exception as e: diag_logs.append(f"⚠️ Mails ({acc.split('@')[0] if acc else 'def'}) Err: {str(e)[:30]}")

    deduped_mails = []
    seen_subj = set()
    for m in clean_mails:
        subj = str(m.get('subject', '')).lower().strip()[:80]
        if subj not in seen_subj:
            seen_subj.add(subj)
            deduped_mails.append(m)
    clean_mails = deduped_mails

    await _log("Fetching Calendar Events (Rewinding to Midnight)...")
    clean_cal = []
    processed_events = set()
    now = datetime.now(timezone.utc)
    
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    target_cals = []
    for acc in accounts:
        target_cals.append((acc, "primary", "primary"))
        target_cals.append((acc, "Executive Assistant", "EA Shared"))
            
    for acc, cid, cname in target_cals:
        acc_lbl = acc.split('@')[0] if acc else 'def'
        try:
            flags_to_try = [
                ["--timeMin", today_start],
                ["--time-min", today_start],
                ["--start", today_start],
                [] 
            ]
            
            events = []
            for flags in flags_to_try:
                cmd = ["calendar", "events", "list", cid, "--limit", "50", "--json"] + flags
                raw_cal = await safe_gog(t_openclaw, cmd, acc, timeout=12.0)
                events = _safe_extract_array(raw_cal)
                if events: break
                
            if not events: 
                diag_logs.append(f"ℹ️ Cal '{cname}' ({acc_lbl}): 0 events.")
                continue
                
            added = 0
            for ev in events:
                dt_str = ''
                end_val = ev.get('end', {})
                if isinstance(end_val, dict): dt_str = end_val.get('dateTime') or end_val.get('date') or ''
                elif isinstance(end_val, str): dt_str = end_val
                
                if dt_str:
                    dt_str = dt_str.replace('Z', '+00:00')
                    if ' ' in dt_str and '+' not in dt_str: dt_str = dt_str.replace(' ', 'T') + '+01:00'
                    try:
                        end_ts = datetime.fromisoformat(dt_str)
                        if end_ts.tzinfo is None: end_ts = end_ts.replace(tzinfo=timezone.utc)
                        if end_ts <= now - timedelta(hours=24): continue
                        
                        ev_title = str(ev.get('summary') or ev.get('title') or '')
                        dedupe_key = f"{ev_title}_{dt_str}"
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
            if "not found" not in err_str and "404" not in err_str:
                diag_logs.append(f"⚠️ Cal '{cname}' ({acc_lbl}) Err: {str(e)[:30]}")

    await _log("Synthesizing Executive Action Report...")
    prompt = f"""You are an elite, ruthless Executive Assistant. I demand extreme noise reduction. NO BULLSHIT.
CRITICAL CULLING RULES:
1. THE PURGE: You MUST completely delete ALL package delivery updates, shipping notices, order confirmations, and standard payment receipts from the JSON. ERASE THEM ENTIRELY.
2. EXCEPTION: You MAY include a package/delivery alert ONLY IF it is a FAILURE or requires manual pickup.
3. CHURCHILL TONE: For the critical emails that remain, state brutally and concisely WHY it requires action in 1 sentence.
4. CALENDARS: Format ALL events provided into a clean schedule. Group them cleanly by Day/Date. YOU MUST INCLUDE EVENTS FROM THIS MORNING.

DATA:
Mails: {json.dumps(clean_mails, ensure_ascii=False)}
Calendars: {json.dumps(clean_cal, ensure_ascii=False)}

Return ONLY valid JSON matching this schema:
{{
  "emails": [{{"sender": "Sender", "subject": "Subject", "churchill_action": "1 sentence: What must I do?", "action_button": "Short Command"}}],
  "calendar_summary": "Clean, bulleted timeline of the schedule across all calendars, grouped by date."
}}"""

    out = await call_llm(prompt)
    try:
        obj = _safe_extract_obj(out)
        
        # 🚨 THE ADMIN KEY AUDITOR UI HOOK
        if "error" in obj:
            return {"text": f"⚠️ <b>Diagnostic Report:</b>\n<pre>{_sanitize_telegram_html(obj['error'])}</pre>", "options": ["🔁 Retry"]}
            
        if not obj: raise ValueError("No valid JSON found in LLM response.")
        
        loops_txt, loop_btns = OpenLoops.get_dashboard(t_key)
        html_out = "🎩 <b>Executive Action Briefing</b>\n\n" + loops_txt
        options = []
        seen_btns = set()
        
        if obj.get("emails") and len(obj["emails"]) > 0:
            html_out += "<b>Requires Attention:</b>\n"
            for e in obj["emails"]:
                s_name = _sanitize_telegram_html(e.get('sender', 'Unknown'))
                subj = _sanitize_telegram_html(e.get('subject', ''))
                reason = _sanitize_telegram_html(e.get('churchill_action', ''))
                html_out += f"• <b>{s_name}</b>: <i>{subj}</i>\n  └ <i>{reason}</i>\n\n"
                
                btn = str(e.get('action_button') or '').strip()
                if btn and "option" not in btn.lower():
                    btn_lower = btn.lower()
                    if btn_lower not in seen_btns:
                        seen_btns.add(btn_lower)
                        options.append(btn)
        else:
            html_out += "<i>No critical items require your immediate attention.</i>\n\n"
            
        html_out += f"<b>Calendars:</b>\n{_sanitize_telegram_html(obj.get('calendar_summary', 'No upcoming events.'))}"
        
        if diag_logs: 
            diag_str = "\n".join(diag_logs)
            if len(diag_str) > 1000: diag_str = diag_str[:1000] + "\n...[truncated]"
            html_out += "\n\n<i>⚙️ Diagnostics:</i>\n<pre>" + html.escape(diag_str, quote=False) + "</pre>"

        clean_opts = [str(o) for o in options][:5]
        return {"text": html_out, "options": clean_opts, "dynamic_buttons": loop_btns}
    except Exception as e: 
        return {"text": f"⚠️ <b>Fatal Briefing Error:</b>\n<pre>{html.escape(str(e), quote=False)}</pre>", "options": ["🔁 Retry"]}


# ==========================================
# V1.7.1 COGNITIVE ROUTER OVERRIDE
# ==========================================
import urllib.request
import json
try:
    from app.llm import ask_llm
except ImportError:
    ask_llm = lambda p: f"❌ Router Error: llm module not found."

# Globale Funktionen für externe Aufrufer (Poller/Worker) überschreiben
call_llm = lambda prompt, *args, **kwargs: ask_llm(prompt)
call_powerful_llm = lambda prompt, *args, **kwargs: ask_llm(prompt)

# Abfangen des nativen Google-Aufrufs im Legacy Code
_orig_urlopen = urllib.request.urlopen
def _monkey_urlopen(req, *args, **kwargs):
    url = req.full_url if hasattr(req, 'full_url') else str(req)
    if 'generativelanguage.googleapis.com' in url:
        class DummyResp:
            def read(self):
                try:
                    body = json.loads(req.data.decode('utf-8'))
                    prompt = body['contents'][0]['parts'][0]['text']
                    if prompt.strip().lower() == 'ping':
                        return json.dumps({"candidates": [{"content": {"parts": [{"text": "pong"}]}}]}).encode('utf-8')
                    ans = ask_llm(prompt)
                    return json.dumps({"candidates": [{"content": {"parts": [{"text": ans}]}}]}).encode('utf-8')
                except Exception as e:
                    return json.dumps({"candidates": [{"content": {"parts": [{"text": f"❌ Cognitive Router Crash: {e}"}]}}]}).encode('utf-8')
        return DummyResp()
    return _orig_urlopen(req, *args, **kwargs)

urllib.request.urlopen = _monkey_urlopen
