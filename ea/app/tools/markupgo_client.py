import os, json, hashlib, httpx

class MarkupGoClient:
    def __init__(self):
        self.base = os.environ.get("MARKUPGO_BASE_URL", "https://api.markupgo.com/api/v1").rstrip("/")
        self.key = os.environ.get("MARKUPGO_API_KEY", "")

    def _headers(self):
        return {"x-api-key": self.key, "Content-Type": "application/json"}

    async def render_pdf_buffer(self, payload: dict, timeout_s: float = 30.0) -> bytes:
        if not self.key: raise ValueError("OODA: MARKUPGO_API_KEY missing. Act: Add to .env and restart.")
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(f"{self.base}/pdf/buffer", headers=self._headers(), json=payload)
            if r.status_code != 200: raise ValueError(f"OODA: MarkupGo API HTTP {r.status_code}. Act: Verify template ID and payload. {r.text}")
            return r.content

    async def render_image_buffer(self, payload: dict, timeout_s: float = 30.0) -> bytes:
        if not self.key: raise ValueError("OODA: MARKUPGO_API_KEY missing. Act: Add to .env and restart.")
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(f"{self.base}/image/buffer", headers=self._headers(), json=payload)
            if r.status_code not in (200, 201): raise ValueError(f"OODA: MarkupGo API HTTP {r.status_code}. Act: Verify template ID and payload. {r.text}")
            return r.content

def render_request_hash(template_id: str, context: dict, options: dict, fmt: str) -> str:
    norm = json.dumps({"template_id": template_id, "context": context, "options": options, "fmt": fmt},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
