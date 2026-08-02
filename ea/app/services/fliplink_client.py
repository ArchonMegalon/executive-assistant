from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FlipLinkError(RuntimeError):
    """Raised when the FlipLink API adapter cannot complete a publication request."""


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class FlipLinkSettings:
    api_key: str
    base_url: str = "https://fliplink.me"
    create_path: str = "/publications"
    update_path_template: str = "/publications/{publication_id}"
    timeout_seconds: int = 60
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    metadata_field: str = "metadata"
    file_field: str = "file"
    max_pdf_bytes: int = 250 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "FlipLinkSettings":
        api_key = (os.getenv("FLIPLINK_API_KEY") or "").strip()
        if not api_key:
            raise FlipLinkError("FLIPLINK_API_KEY is required")
        return cls(
            api_key=api_key,
            base_url=(os.getenv("FLIPLINK_API_BASE_URL") or "https://fliplink.me").strip().rstrip("/"),
            create_path=(os.getenv("FLIPLINK_CREATE_PATH") or "/publications").strip() or "/publications",
            update_path_template=(os.getenv("FLIPLINK_UPDATE_PATH_TEMPLATE") or "/publications/{publication_id}").strip(),
            timeout_seconds=max(10, min(_env_int("FLIPLINK_TIMEOUT_SECONDS", 60), 300)),
            auth_header=(
                os.getenv("FLIPLINK_API_AUTH_HEADER")
                or os.getenv("FLIPLINK_AUTH_HEADER")
                or "Authorization"
            ).strip()
            or "Authorization",
            auth_prefix=(
                os.getenv("FLIPLINK_API_AUTH_PREFIX")
                if os.getenv("FLIPLINK_API_AUTH_PREFIX") is not None
                else os.getenv("FLIPLINK_AUTH_PREFIX", "Bearer ")
            ),
            metadata_field=(os.getenv("FLIPLINK_METADATA_FIELD") or "metadata").strip() or "metadata",
            file_field=(os.getenv("FLIPLINK_FILE_FIELD") or "file").strip() or "file",
            max_pdf_bytes=max(1024 * 1024, _env_int("FLIPLINK_MAX_PDF_BYTES", 250 * 1024 * 1024)),
        )


class FlipLinkClient:
    """
    Endpoint-configurable FlipLink upload adapter for archive PDFs.

    FlipLink endpoint names vary by account/API version. Keep the paths and
    form-field names configurable so publisher scripts can change endpoints
    without code edits.
    """

    def __init__(self, settings: FlipLinkSettings | None = None) -> None:
        self.settings = settings or FlipLinkSettings.from_env()

    def _headers(self, *, content_type: str) -> dict[str, str]:
        return {
            self.settings.auth_header: f"{self.settings.auth_prefix}{self.settings.api_key}".strip(),
            "Accept": "application/json",
            "Content-Type": content_type,
        }

    def _url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.settings.base_url}{normalized}"

    def _multipart_body(self, *, metadata: dict[str, Any], pdf_path: Path) -> tuple[bytes, str]:
        boundary = "----ea-archive-fliplink-boundary"
        pdf_bytes = pdf_path.read_bytes()
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{self.settings.metadata_field}\"\r\n\r\n".encode(),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            b"\r\n",
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{self.settings.file_field}\"; filename=\"{pdf_path.name}\"\r\n"
                "Content-Type: application/pdf\r\n\r\n"
            ).encode(),
            pdf_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return b"".join(parts), boundary

    def _request_pdf(self, *, method: str, path: str, metadata: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
        body, boundary = self._multipart_body(metadata=metadata, pdf_path=pdf_path)
        request = urllib.request.Request(
            self._url(path),
            data=body,
            method=method.upper(),
            headers=self._headers(content_type=f"multipart/form-data; boundary={boundary}"),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise FlipLinkError(f"fliplink_api_error:{exc.code}:{raw_error[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise FlipLinkError(f"fliplink_unreachable:{type(exc).__name__}") from exc

        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise FlipLinkError("fliplink_invalid_json_response") from exc
        if not isinstance(payload, dict):
            raise FlipLinkError("fliplink_invalid_response")
        return payload

    @staticmethod
    def _publication_payload(payload: dict[str, Any]) -> dict[str, str]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return {
            "publication_id": str(
                data.get("publication_id")
                or data.get("id")
                or data.get("uuid")
                or data.get("document_id")
                or ""
            ).strip(),
            "url": str(data.get("url") or data.get("public_url") or data.get("share_url") or data.get("link") or "").strip(),
            "embed_code": str(data.get("embed_code") or data.get("embed") or "").strip(),
            "qr_url": str(data.get("qr_url") or data.get("qr") or "").strip(),
            "slug": str(data.get("slug") or data.get("alias") or "").strip(),
            "published_at": str(data.get("published_at") or "").strip(),
        }

    def publish_pdf(self, *, pdf_path: Path, metadata: dict[str, Any], publication_id: str = "") -> dict[str, str]:
        pdf = Path(pdf_path)
        if not pdf.is_file():
            raise FlipLinkError(f"pdf_missing:{pdf}")
        if pdf.suffix.lower() != ".pdf":
            raise FlipLinkError("fliplink_requires_pdf")
        size = pdf.stat().st_size
        if size <= 0:
            raise FlipLinkError("pdf_empty")
        if size > self.settings.max_pdf_bytes:
            raise FlipLinkError("pdf_too_large")

        path = self.settings.create_path
        method = "POST"
        if publication_id:
            path = self.settings.update_path_template.format(publication_id=publication_id)
            method = "PUT"

        payload = self._request_pdf(method=method, path=path, metadata=metadata, pdf_path=pdf)
        normalized = self._publication_payload(payload)
        if publication_id and not normalized["publication_id"]:
            normalized["publication_id"] = publication_id
        return normalized
