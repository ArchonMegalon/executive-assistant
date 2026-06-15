from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import Request

from app.api.routes.landing_shared_support import _repo_root
from app.services.memorial_archive_registry import load_json as _load_archive_json
from app.services.memorial_archive_registry import public_registry_path as _public_registry_path
from app.services.memorial_archive_registry import public_registry_payload as _public_registry_payload
from app.services.public_clickrank import request_hostname as _request_hostname


_ARCHIVE_HOSTNAME = "archive.myexternalbrain.com"
_ARCHIVE_MEMORIAL_SLUG = "manfred"


def _memorial_archive_dir() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_ARCHIVE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return _repo_root() / "memorial_archive"


def _is_archive_host(request: Request) -> bool:
    return _request_hostname(request) == _ARCHIVE_HOSTNAME


def _archive_public_registry() -> dict[str, object]:
    path = _public_registry_path(_ARCHIVE_MEMORIAL_SLUG, generated=False)
    if not path.is_file():
        return {"slug": _ARCHIVE_MEMORIAL_SLUG, "archive_sections": [], "fliplink_publications": []}
    payload = _load_archive_json(path)
    if not isinstance(payload, dict):
        return {"slug": _ARCHIVE_MEMORIAL_SLUG, "archive_sections": [], "fliplink_publications": []}
    return _public_registry_payload(payload)


def _archive_publication_html_path(publication_slug: str) -> Path:
    base = _memorial_archive_dir() / _ARCHIVE_MEMORIAL_SLUG / "public" / publication_slug / "build" / "index.html"
    return base.resolve()


def _archive_home_html() -> str:
    registry = _archive_public_registry()
    items = list(registry.get("fliplink_publications") or [])
    cards: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = html.escape(str(item.get("slug") or item.get("id") or "").strip())
        title = html.escape(str(item.get("title") or slug).strip())
        desc = html.escape(str(item.get("description") or "").strip())
        cards.append(
            "<article style='border:1px solid rgba(43,39,35,.14);background:rgba(255,255,255,.52);padding:18px 20px;border-radius:18px;'>"
            f"<h2 style='margin:0 0 8px;font-size:1.35rem;'><a href='/{slug}' style='color:#2B2723;text-decoration:none;'>{title}</a></h2>"
            f"<p style='margin:0;color:#665E55;'>{desc}</p>"
            "</article>"
        )
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Manfred Memorial Archive</title>"
        "<style>:root{--paper:#F7EFE0;--ink:#2B2723;--muted:#665E55;--line:rgba(43,39,35,.14);}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 Georgia,\"Libre Baskerville\",serif;}main{max-width:920px;margin:0 auto;padding:48px 28px 72px;}header{margin-bottom:28px;padding-bottom:18px;border-bottom:1px solid var(--line);}h1{margin:0 0 10px;font-size:2.6rem;line-height:1.05}.kicker{color:#7D4851;font:700 12px/1.2 \"Trebuchet MS\",system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase}.grid{display:grid;gap:18px}.lead{color:var(--muted)}</style>"
        "</head><body><main><header><div class='kicker'>Manfred Memorial Archive</div><h1>Archiv</h1><p class='lead'>Geprüfte Dokumente, Erinnerungen und Quellen als lesbare Archivseiten.</p></header>"
        f"<section class='grid'>{''.join(cards)}</section></main></body></html>"
    )
