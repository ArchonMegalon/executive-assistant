import json, urllib.request
from app.settings import settings

def get_health() -> str:
    """OBSERVE: Live-Zustand der kognitiven Gateways erfassen"""
    h = []
    if getattr(settings, 'magixx_api_key', None): h.append("🟢 Magixx")
    else: h.append("🔴 Magixx")
    
    if getattr(settings, 'litellm_api_key', None): h.append("🟢 LiteLLM")
    else: h.append("🔴 LiteLLM")
    
    if getattr(settings, 'gemini_api_key', None): h.append("🟢 Gemini")
    else: h.append("🔴 Gemini")
    
    return f"🧠 Cognitive Core: {' | '.join(h)}"

def ask_llm(prompt: str, system_prompt: str = "Du bist ein präziser Executive Assistant.") -> str:
    """ORIENT, DECIDE, ACT: Kaskadierendes Routing der Intelligenz"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    errors = []
    
    # PRIO 1: Magixx Enterprise Gateway (z.B. o1-mini)
    if getattr(settings, 'magixx_api_key', None):
        try:
            print("🔄 OODA Orient: Routing to Magixx...", flush=True)
            url = f"{(settings.magixx_base_url or 'https://api.magixx.com').rstrip('/')}/chat/completions"
            model = settings.llm_chain.replace('magixx:', '') if getattr(settings, 'llm_chain', None) else 'o1-mini'
            data = json.dumps({"model": model, "messages": messages}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {settings.magixx_api_key}'})
            res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            return res['choices'][0]['message']['content']
        except Exception as e:
            errors.append(f"Magixx Failed: {e}")

    # PRIO 2: LiteLLM Fallback Gateway
    if getattr(settings, 'litellm_api_key', None):
        try:
            print("🔄 OODA Orient: Routing to LiteLLM...", flush=True)
            url = f"{(settings.litellm_base_url or 'http://litellm:4000').rstrip('/')}/chat/completions"
            data = json.dumps({"model": "gpt-4o-mini", "messages": messages}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {settings.litellm_api_key}'})
            res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            return res['choices'][0]['message']['content']
        except Exception as e:
            errors.append(f"LiteLLM Failed: {e}")

    # PRIO 3: Gemini Native Failsafe
    if getattr(settings, 'gemini_api_key', None):
        try:
            print("🔄 OODA Orient: Routing to Gemini...", flush=True)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}"
            data = json.dumps({"contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}]}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            return res['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            if hasattr(e, 'read'): errors.append(f"Gemini Failed: {e.read().decode()}")
            else: errors.append(f"Gemini Failed: {e}")

    return f"❌ OODA FATAL: Alle LLM Gateways offline.\nDetails: {' | '.join(errors)}"
