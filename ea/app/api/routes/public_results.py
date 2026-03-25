from __future__ import annotations

import html
import json
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


router = APIRouter(tags=["public-results"])


def _result_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_RESULT_DIR") or "/docker/fleet/state/public_browseract_results")).expanduser()


def _result_base_dir(slug: str) -> Path:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="result_not_found")
    root = _result_dir().resolve()
    candidate = (root / safe).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=404, detail="result_not_found")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="result_not_found")
    return candidate


def _manifest_path(slug: str) -> Path:
    base = _result_base_dir(slug)
    candidate = (base / "result.json").resolve()
    if base not in candidate.parents:
        raise HTTPException(status_code=404, detail="result_not_found")
    return candidate


def _load_manifest(slug: str) -> dict[str, object]:
    path = _manifest_path(slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail="result_not_found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="result_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="result_payload_invalid")
    return payload


def _asset_file(slug: str, asset_path: str) -> Path:
    base = _result_base_dir(slug)
    candidate = (base / str(asset_path or "")).resolve()
    if base not in candidate.parents and candidate != base:
        raise HTTPException(status_code=404, detail="result_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="result_file_not_found")
    return candidate


def _maybe_text(value: object) -> str:
    return str(value or "").strip()


def _viewer_kind(payload: dict[str, object]) -> str:
    explicit = _maybe_text(payload.get("viewer_kind")).lower()
    if explicit:
        return explicit
    mime_type = _maybe_text(payload.get("mime_type")).lower()
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    return "text"


def _result_html(payload: dict[str, object]) -> str:
    title = html.escape(_maybe_text(payload.get("title")) or _maybe_text(payload.get("result_title")) or "EA Result")
    service = html.escape(_maybe_text(payload.get("service_key")) or _maybe_text(payload.get("service_name")) or "browseract")
    summary = html.escape(_maybe_text(payload.get("summary")) or _maybe_text(payload.get("normalized_text")))
    notes = html.escape(_maybe_text(payload.get("notes")))
    viewer_kind = _viewer_kind(payload)
    body_text = html.escape(_maybe_text(payload.get("body_text")) or _maybe_text(payload.get("raw_text")))
    slug = _maybe_text(payload.get("slug"))
    asset_relpath = _maybe_text(payload.get("asset_relpath"))
    asset_href = f"/results/files/{html.escape(slug)}/{html.escape(asset_relpath)}" if slug and asset_relpath else ""
    hosted_url = _maybe_text(payload.get("hosted_url")) or _maybe_text(payload.get("public_url"))
    vendor_public_url = _maybe_text(payload.get("crezlo_public_url"))
    source_links = [
        ("Hosted URL", hosted_url),
        ("Original asset", _maybe_text(payload.get("asset_url"))),
        ("Download URL", _maybe_text(payload.get("download_url"))),
        ("Vendor URL", vendor_public_url),
        ("Editor URL", _maybe_text(payload.get("editor_url"))),
    ]
    link_html = "".join(
        f'<a class="chip" href="{html.escape(url)}" target="_blank" rel="noreferrer">{html.escape(label)}</a>'
        for label, url in source_links
        if url
    )
    viewer_html = "<p class='empty'>No proxied asset was published for this result yet.</p>"
    if asset_href and viewer_kind == "video":
        viewer_html = f'<video controls playsinline preload="metadata" src="{asset_href}"></video>'
    elif asset_href and viewer_kind == "image":
        viewer_html = f'<img src="{asset_href}" alt="{title}">'
    elif asset_href and viewer_kind == "pdf":
        viewer_html = f'<iframe src="{asset_href}" title="{title}"></iframe>'
    elif asset_href and viewer_kind == "html":
        viewer_html = f'<iframe src="{asset_href}" title="{title}"></iframe>'
    elif body_text:
        viewer_html = f"<pre>{body_text}</pre>"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      :root {{
        --bg: #f2efe7;
        --ink: #1f1d1a;
        --muted: #645d55;
        --panel: rgba(255,255,255,0.84);
        --edge: rgba(31,29,26,0.10);
        --accent: #1652a1;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(22,82,161,0.15), transparent 28%),
          linear-gradient(160deg, #f7f3eb 0%, #ece6db 100%);
        font-family: "Iowan Old Style", Georgia, serif;
      }}
      .shell {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
      .hero, .viewer {{
        background: var(--panel);
        border: 1px solid var(--edge);
        border-radius: 28px;
        box-shadow: 0 18px 54px rgba(31,29,26,0.08);
      }}
      .hero {{ padding: 24px; margin-bottom: 20px; }}
      .eyebrow {{
        color: var(--muted);
        font-size: 12px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }}
      h1 {{ margin: 12px 0 8px; font-size: clamp(2rem, 4vw, 3.6rem); line-height: 0.94; }}
      p {{ margin: 0; line-height: 1.6; }}
      .summary {{ color: var(--muted); max-width: 72ch; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
      .chip {{
        display: inline-flex;
        align-items: center;
        min-height: 42px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid var(--edge);
        background: rgba(255,255,255,0.72);
        text-decoration: none;
        color: inherit;
      }}
      .viewer {{ padding: 18px; min-height: 320px; }}
      .viewer video, .viewer img, .viewer iframe {{
        width: 100%;
        min-height: 68vh;
        border: 0;
        border-radius: 20px;
        background: #111;
      }}
      .viewer img {{ object-fit: contain; background: #f8f8f8; }}
      pre {{
        white-space: pre-wrap;
        background: rgba(250,248,243,0.92);
        border: 1px solid var(--edge);
        border-radius: 20px;
        padding: 18px;
        font-family: "SFMono-Regular", Consolas, monospace;
        font-size: 13px;
        line-height: 1.55;
      }}
      .empty {{ color: var(--muted); padding: 16px; }}
      .notes {{ margin-top: 14px; color: var(--muted); }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div class="eyebrow">{service}</div>
        <h1>{title}</h1>
        <p class="summary">{summary or "EA public result viewer"}</p>
        <div class="actions">
          {f'<a class="chip" href="{asset_href}" target="_blank" rel="noreferrer">Open Proxied Asset</a>' if asset_href else ''}
          {link_html}
        </div>
        {f'<p class="notes">{notes}</p>' if notes else ''}
      </section>
      <section class="viewer">
        {viewer_html}
      </section>
    </main>
  </body>
</html>"""


@router.get("/results/{slug}.json", response_class=JSONResponse)
def public_result_json(slug: str) -> JSONResponse:
    return JSONResponse(_load_manifest(slug))


@router.get("/results/files/{slug}/{asset_path:path}")
def public_result_file(slug: str, asset_path: str) -> FileResponse:
    payload = _load_manifest(slug)
    file_path = _asset_file(slug, asset_path)
    guessed_media_type = mimetypes.guess_type(str(file_path))[0]
    media_type = guessed_media_type or _maybe_text(payload.get("mime_type")) or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@router.get("/results/{slug}", response_class=HTMLResponse)
def public_result_page(slug: str) -> HTMLResponse:
    return HTMLResponse(_result_html(_load_manifest(slug)))
