from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.settings import get_settings, resolve_signing_secret


router = APIRouter(tags=["public-documents"])


def _attachment_root() -> Path:
    return Path(str(os.getenv("EA_ONEDRIVE_ATTACHMENT_ROOT") or "/data/onedrive_attachments").strip()).expanduser()


def _document_secret() -> str:
    return resolve_signing_secret(get_settings(), purpose="onedrive-documents")


def _decode_token(token: str) -> dict[str, object]:
    normalized = str(token or "").strip()
    if not normalized or "." not in normalized:
        raise HTTPException(status_code=404, detail="document_not_found")
    payload_b64, signature = normalized.rsplit(".", 1)
    expected = hmac.new(_document_secret().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=404, detail="document_not_found")
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(f"{payload_b64}{padding}".encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    if not isinstance(payload, dict) or str(payload.get("kind") or "").strip() != "onedrive_document":
        raise HTTPException(status_code=404, detail="document_not_found")
    return payload


def _document_file(token: str) -> tuple[Path, str]:
    payload = _decode_token(token)
    relpath = str(payload.get("relpath") or "").strip()
    if not relpath:
        raise HTTPException(status_code=404, detail="document_not_found")
    root = _attachment_root().resolve()
    candidate = (root / relpath).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=404, detail="document_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="document_not_found")
    return candidate, str(payload.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream"


@router.get("/documents/onedrive-mail/{token}")
def public_onedrive_mail_document(token: str) -> FileResponse:
    path, media_type = _document_file(token)
    return FileResponse(path, media_type=media_type, filename=path.name)
