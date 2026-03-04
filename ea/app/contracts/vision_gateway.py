from __future__ import annotations

import base64
import json
import os
import random
import re

import httpx


async def extract_calendar_events_from_image(img_bytes: bytes, mime_type: str) -> dict:
    """Contract adapter for vision/calendar extraction requests."""
    b64_img = base64.b64encode(img_bytes).decode("utf-8")
    keys = [os.environ.get("GEMINI_API_KEY", "")]
    random.shuffle(keys)
    prompt = (
        "Extract all calendar events from this Therapy Plan (Therapieplan). "
        "The patient is Tibor. Look closely for the date on the document "
        "(e.g., Freitag, der 27.02.2026). Return ONLY a JSON object exactly "
        "matching this schema: {\"events\": [{\"title\": \"Therapy Name "
        "(e.g. Physiotherapie)\", \"start\": \"YYYY-MM-DDTHH:MM:SS+01:00\", "
        "\"end\": \"YYYY-MM-DDTHH:MM:SS+01:00\", \"location\": \"Room "
        "(e.g. G207)\"}]}. Timezone is Europe/Vienna (+01:00). Assume therapies "
        "last 30 minutes if no end time is given."
    )
    payload = {
        "contents": [
            {"parts": [{"text": prompt}, {"inlineData": {"mimeType": mime_type, "data": b64_img}}]}
        ],
        "generationConfig": {"temperature": 0.1},
    }

    last_err = ""
    for key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    if "candidates" in data:
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        text = text.replace("```json", "").replace("```", "").strip()
                        m = re.search(r"\{[\s\S]*\}", text)
                        if m:
                            return json.loads(m.group(0))
                else:
                    last_err = f"HTTP {r.status_code} {r.text[:100]}"
            except Exception as e:
                last_err = str(e)
    print(f"⚠️ Gemini Vision Error: {last_err}", flush=True)
    return {"events": []}
