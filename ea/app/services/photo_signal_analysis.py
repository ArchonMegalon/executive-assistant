from __future__ import annotations

import base64
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def analyze_photo_url(
    *,
    image_url: str,
    title: str = "",
    summary: str = "",
    mime_type: str = "",
) -> dict[str, object]:
    normalized_image_url = str(image_url or "").strip()
    if not normalized_image_url:
        return _fallback_analysis(title=title, summary=summary, mime_type=mime_type, reason="image_url_missing")
    image_bytes, fetch_error = _download_image_bytes(normalized_image_url)
    if not image_bytes:
        return _fallback_analysis(title=title, summary=summary, mime_type=mime_type, reason=fetch_error or "image_download_failed")
    overlay = _overlay_vision_analysis(
        image_bytes=image_bytes,
        title=title,
        summary=summary,
        mime_type=mime_type,
    )
    if overlay is not None:
        return overlay
    return _fallback_analysis(title=title, summary=summary, mime_type=mime_type, reason="vision_unavailable")


def _fallback_analysis(*, title: str, summary: str, mime_type: str, reason: str) -> dict[str, object]:
    cleaned_title = str(title or "").strip() or "Google Photos item"
    cleaned_summary = str(summary or "").strip()
    tags: list[str] = []
    lowered = f"{cleaned_title} {cleaned_summary}".lower()
    for token in ("family", "holiday", "urlaub", "playground", "bike", "park", "garden", "home", "wohnung", "house"):
        if token in lowered and token not in tags:
            tags.append(token)
    suggestions: list[str] = []
    if any(token in lowered for token in ("playground", "park", "garden", "bike")):
        suggestions.append("This looks lifestyle-relevant. Compare it against green-space and bike-infrastructure preferences.")
    if any(token in lowered for token in ("wohnung", "home", "house", "garden")):
        suggestions.append("If this is home-related, attach it to the current housing review thread or property comparison.")
    return {
        "summary": cleaned_summary or f"Google Photos item captured as a signal: {cleaned_title}.",
        "signal_kind": "photo_signal",
        "tags": tags,
        "suggestions": suggestions,
        "notable_details": [],
        "sensitivity": "medium",
        "confidence": 0.15,
        "provider": "fallback_metadata",
        "status": "fallback",
        "error": str(reason or "").strip(),
    }


def _download_image_bytes(image_url: str) -> tuple[bytes, str]:
    headers = {"User-Agent": "ExecutiveAssistantPhotoSignal/1.0"}
    cf_client_id = (
        str(os.environ.get("OLLAMA_CF_ACCESS_CLIENT_ID") or "").strip()
        or str(os.environ.get("COMFYUI_CF_ACCESS_CLIENT_ID") or "").strip()
        or str(os.environ.get("CF_ACCESS_CLIENT_ID") or "").strip()
    )
    cf_client_secret = (
        str(os.environ.get("OLLAMA_CF_ACCESS_CLIENT_SECRET") or "").strip()
        or str(os.environ.get("COMFYUI_CF_ACCESS_CLIENT_SECRET") or "").strip()
        or str(os.environ.get("CF_ACCESS_CLIENT_SECRET") or "").strip()
    )
    if cf_client_id and cf_client_secret:
        headers["CF-Access-Client-Id"] = cf_client_id
        headers["CF-Access-Client-Secret"] = cf_client_secret
    request = urllib.request.Request(image_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), ""
    except urllib.error.HTTPError as exc:
        return b"", f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        detail = getattr(exc, "reason", exc)
        return b"", f"urlerror:{str(detail)[:200]}"


def _overlay_vision_analysis(
    *,
    image_bytes: bytes,
    title: str,
    summary: str,
    mime_type: str,
) -> dict[str, object] | None:
    base_url = _overlay_vision_base_url()
    model = _overlay_vision_model()
    if not base_url or not model:
        return None
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze personal photo signals for an executive assistant. "
                    "Return JSON only. Be grounded in visible evidence. "
                    "Use concise summaries and 0 to 3 assistant suggestions. "
                    "Do not invent identities, medical claims, or private facts."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    [
                        "Analyze this Google Photos item as an assistant signal.",
                        f"Title: {str(title or '').strip()}",
                        f"Existing summary: {str(summary or '').strip()}",
                        f"MIME type: {str(mime_type or '').strip()}",
                        "Return JSON with keys: summary, signal_kind, tags, suggestions, notable_details, sensitivity, confidence.",
                        "signal_kind should be one of: family, outing, playground, bike, property, document, receipt, food, pet, travel, celebration, screenshot, other.",
                    ]
                ),
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            },
        ],
    }
    parsed = _overlay_vision_json_request(base_url=base_url, path="/api/chat", payload=payload)
    if not isinstance(parsed, dict):
        return None
    message = dict(parsed.get("message") or {}) if isinstance(parsed.get("message"), dict) else {}
    content = str(message.get("content") or parsed.get("response") or "").strip()
    structured = _extract_json_object(content)
    if not isinstance(structured, dict):
        return None
    return {
        "summary": str(structured.get("summary") or "").strip(),
        "signal_kind": str(structured.get("signal_kind") or "other").strip() or "other",
        "tags": [str(value).strip() for value in list(structured.get("tags") or []) if str(value).strip()][:8],
        "suggestions": [str(value).strip() for value in list(structured.get("suggestions") or []) if str(value).strip()][:3],
        "notable_details": [str(value).strip() for value in list(structured.get("notable_details") or []) if str(value).strip()][:6],
        "sensitivity": str(structured.get("sensitivity") or "medium").strip() or "medium",
        "confidence": _safe_float(structured.get("confidence"), default=0.55),
        "provider": "overlay_vision",
        "status": "analyzed",
    }


def _overlay_vision_model() -> str:
    return str(
        os.environ.get("EA_PHOTO_SIGNAL_VISION_MODEL")
        or os.environ.get("CHUMMER6_OVERLAY_VISION_MODEL")
        or "llama3.2-vision:11b"
    ).strip()


def _overlay_vision_base_url() -> str:
    candidates: list[str] = []

    def _add(value: object) -> None:
        normalized = _normalize_http_base_url(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for value in (
        os.environ.get("CHUMMER6_OLLAMA_URL"),
        os.environ.get("OLLAMA_URL"),
        os.environ.get("OLLAMA_HOST"),
    ):
        _add(value)
    for base_url in candidates:
        probe = _overlay_vision_json_request(base_url=base_url, path="/api/tags", payload=None)
        if isinstance(probe, dict):
            return base_url
    return ""


def _overlay_vision_json_request(*, base_url: str, path: str, payload: dict[str, object] | None) -> object | None:
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}/{str(path or '').lstrip('/')}",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "EA-PhotoSignalVision/1.0",
        },
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return None
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def _extract_json_object(text: str) -> object | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    for candidate in (cleaned, cleaned.strip("`"), cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    start = cleaned.find("{")
    if start < 0:
        return None
    for end in range(len(cleaned), start, -1):
        snippet = cleaned[start:end].strip()
        try:
            return json.loads(snippet)
        except Exception:
            continue
    return None


def _normalize_http_base_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def _safe_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
