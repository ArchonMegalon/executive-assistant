#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "memorial_archive/manfred/public/manfred-how-this-memorial-works/manifest.json"
DEFAULT_OUTPUT = ROOT / "ea/_completion/fliplink/CHUMMER_FLIPLINK_PUBLICATION.generated.json"
DEFAULT_PROBE_CONTACT_URL = "https://example.test"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_contact_url() -> str:
    return (
        os.environ.get("EA_FLIPLINK_PROBE_CONTACT_URL")
        or os.environ.get("EA_PUBLIC_APP_BASE_URL")
        or DEFAULT_PROBE_CONTACT_URL
    ).strip() or DEFAULT_PROBE_CONTACT_URL


def _probe_user_agent() -> str:
    return f"EA-FlipLink-Receipt-Probe/1.0 (+{_probe_contact_url()})"


def _pdf_path(manifest: dict[str, Any], manifest_path: Path) -> Path:
    artifacts = manifest.get("build_artifacts") if isinstance(manifest.get("build_artifacts"), dict) else {}
    raw = str(artifacts.get("pdf_path") or manifest.get("pdf_path") or "build/output.pdf").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _live_get(url: str, *, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/pdf,*/*",
            "User-Agent": _probe_user_agent(),
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(8192)
            return {
                "checked": True,
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": str(response.headers.get("Content-Type") or ""),
                "sample_bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "checked": True,
            "status_code": int(exc.code),
            "content_type": str(exc.headers.get("Content-Type") or ""),
            "sample_bytes": 0,
            "error": "http_error",
        }
    except Exception as exc:
        return {
            "checked": True,
            "status_code": 0,
            "content_type": "",
            "sample_bytes": 0,
            "error": type(exc).__name__,
        }


def build_receipt(
    *,
    manifest_path: Path,
    output_path: Path,
    live_check: bool,
    timeout: int = 20,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    pdf = _pdf_path(manifest, manifest_path)
    url = str(manifest.get("fliplink_url") or "").strip()
    parsed = urlparse(url)
    source_files = [str(item) for item in manifest.get("source_files") or []]
    source_text = ""
    for relpath in source_files:
        source_path = (manifest_path.parent / relpath).resolve()
        if source_path.is_file():
            source_text += "\n" + source_path.read_text(encoding="utf-8", errors="replace")
    forbidden_hits = [
        token
        for token in ("sourcebook", "rulebook", "runner sheet", "gm-only", "entitlement truth", "payment truth")
        if token in source_text.lower()
    ]
    live = _live_get(url, timeout=timeout) if live_check and url else {"checked": False}
    checks = [
        {"code": "manifest_public", "status": "pass" if str(manifest.get("audience") or "").lower() == "public" else "fail"},
        {"code": "manifest_approved", "status": "pass" if bool(manifest.get("approved")) else "fail"},
        {"code": "review_approved_or_published", "status": "pass" if str(manifest.get("review_status") or "").lower() in {"approved", "published"} else "fail"},
        {"code": "pdf_exists", "status": "pass" if pdf.is_file() else "fail"},
        {"code": "https_url", "status": "pass" if parsed.scheme == "https" and bool(parsed.netloc) else "fail"},
        {"code": "forbidden_source_terms_absent", "status": "pass" if not forbidden_hits else "fail", "hits": forbidden_hits},
    ]
    if live_check:
        status_code = int(live.get("status_code") or 0)
        checks.append({"code": "live_url_get_ok", "status": "pass" if 200 <= status_code < 400 else "fail", "status_code": status_code})
    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    payload = {
        "contract_name": "executive_assistant.fliplink_publication_receipt.v1",
        "generated_at": generated_at or _utc_now(),
        "status": status,
        "provider": "FlipLink.me",
        "lane_key": "fliplink_document_portal",
        "document_id": str(manifest.get("document_id") or ""),
        "title": str(manifest.get("title") or ""),
        "audience": str(manifest.get("audience") or ""),
        "review_status": str(manifest.get("review_status") or ""),
        "manifest_path": str(manifest_path),
        "pdf_path": str(pdf),
        "pdf_sha256": _sha256(pdf) if pdf.is_file() else "",
        "fliplink_url": url,
        "live_url": live,
        "source_of_truth_boundary": "EA/Memorial archive owns approved PDF content; FlipLink presents the approved public artifact only.",
        "privacy": {
            "public_document": True,
            "contains_sourcebook_pdf": False,
            "contains_private_runner_sheet": False,
            "contains_gm_only_secret": False,
            "contains_entitlement_or_payment_truth": False,
        },
        "checks": checks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a governed FlipLink first-publication receipt.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    payload = build_receipt(
        manifest_path=Path(args.manifest),
        output_path=Path(args.output),
        live_check=bool(args.live_check),
        timeout=max(5, min(int(args.timeout), 60)),
    )
    print(json.dumps({"status": payload["status"], "output": str(args.output), "fliplink_url": payload["fliplink_url"]}, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
