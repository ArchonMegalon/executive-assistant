from __future__ import annotations

import html
import json
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.services.public_clickrank import clickrank_head_snippet, request_hostname

router = APIRouter(tags=["public-memorials"])


def _memorial_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_MEMORIAL_DIR") or "/mnt/pcloud/EA/public_memorials")).expanduser()


def _resolved_memorial_root() -> Path:
    return _memorial_dir().resolve()


def _safe_slug(slug: str) -> str:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return safe


def _memorial_bundle(slug: str) -> Path:
    root = _resolved_memorial_root()
    bundle_dir = (root / _safe_slug(slug)).resolve()
    if bundle_dir != root and root not in bundle_dir.parents:
        raise HTTPException(status_code=404, detail="memorial_not_found")
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return bundle_dir


def _manifest_path(slug: str) -> Path:
    path = _memorial_bundle(slug) / "memorial.json"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return path


def _load_memorial(slug: str) -> dict[str, object]:
    try:
        payload = json.loads(_manifest_path(slug).read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="memorial_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="memorial_payload_invalid")
    return payload


def _asset_file(slug: str, asset_path: str) -> Path:
    bundle_dir = _memorial_bundle(slug)
    candidate = (bundle_dir / str(asset_path or "")).resolve()
    if candidate != bundle_dir.resolve() and bundle_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    return candidate


def _text(value: object, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in (value or []) if isinstance(item, dict)]


def _memorial_html(payload: dict[str, object], *, hostname: str = "") -> str:
    slug = _text(payload.get("slug"))
    if not slug:
        raise HTTPException(status_code=500, detail="memorial_slug_missing")
    person_name = _text(payload.get("person_name"), "Manfred")
    title = _text(payload.get("title"), f"Erinnerungen an {person_name}")
    subtitle = _text(
        payload.get("subtitle"),
        "Eine ruhige Seite fuer Erinnerungen, Originalstimme und dokumentierte Gedanken.",
    )
    relationship = _text(payload.get("relationship"), "Vater")
    intro = _text(
        payload.get("intro"),
        "Diese Seite sammelt echte Aufnahmen und belegte Erinnerungen. Neue Texte sind keine direkte Rede.",
    )
    disclosure = _text(
        payload.get("disclosure"),
        "Originalaufnahmen sind als Original gekennzeichnet. Antworttexte werden aus gespeicherten Quellen formuliert und sprechen nicht an seiner Stelle.",
    )
    audio_clips = _list_of_dicts(payload.get("audio_clips"))
    memory_cards = _list_of_dicts(payload.get("memory_cards"))
    candidate_recordings = _list_of_dicts(payload.get("candidate_recordings"))
    suggested_prompts = [str(item).strip() for item in (payload.get("suggested_prompts") or []) if str(item).strip()]
    page_title = html.escape(title)
    clickrank_html = clickrank_head_snippet(hostname)
    clips_html = "\n".join(
        f"""
        <article class="clip">
          <div>
            <p class="eyebrow">{html.escape(_text(clip.get("label"), "Originalaufnahme"))}</p>
            <h3>{html.escape(_text(clip.get("title"), "Audio"))}</h3>
            <p>{html.escape(_text(clip.get("description"), "Echte Aufnahme aus dem Archiv."))}</p>
          </div>
          <audio controls preload="metadata" src="/memorials/files/{html.escape(slug)}/{html.escape(_text(clip.get("asset_relpath")))}"></audio>
        </article>"""
        for clip in audio_clips
        if _text(clip.get("asset_relpath"))
    )
    if not clips_html:
        clips_html = '<p class="empty">Noch keine freigegebenen Originalaufnahmen.</p>'
    cards_html = "\n".join(
        f"""
        <article class="memory">
          <p class="eyebrow">{html.escape(_text(card.get("source_label"), "Quelle"))}</p>
          <h3>{html.escape(_text(card.get("title"), "Erinnerung"))}</h3>
          <p>{html.escape(_text(card.get("body"), ""))}</p>
        </article>"""
        for card in memory_cards
    )
    candidates_html = "\n".join(
        f"""
        <article class="candidate">
          <strong>{html.escape(_text(candidate.get("title"), "Aufnahme"))}</strong>
          <span>{html.escape(_text(candidate.get("recorded_at"), "Datum offen"))}</span>
          <p>{html.escape(_text(candidate.get("status"), "Noch nicht als Stimme freigegeben."))}</p>
        </article>"""
        for candidate in candidate_recordings
    )
    if candidates_html:
        candidates_html = f"""
      <section>
        <h2>Weitere gefundene Kandidaten</h2>
        <div class="candidates">{candidates_html}</div>
      </section>"""
    prompts_html = "\n".join(f"<button type=\"button\">{html.escape(prompt)}</button>" for prompt in suggested_prompts)
    if not prompts_html:
        prompts_html = "<button type=\"button\">Was ist wirklich belegt?</button>"
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{page_title}</title>
    {clickrank_html}
    <style>
      :root {{
        --paper: #f7f1e8;
        --ink: #211f1b;
        --muted: #665f55;
        --line: rgba(33, 31, 27, 0.16);
        --panel: #fffaf2;
        --sage: #53685b;
        --wine: #7d3236;
        --blue: #2e5266;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--paper);
        color: var(--ink);
        font: 16px/1.6 ui-serif, Georgia, "Times New Roman", serif;
      }}
      a {{ color: inherit; }}
      .wrap {{ width: min(1120px, calc(100vw - 36px)); margin: 0 auto; }}
      header {{
        min-height: 86vh;
        display: grid;
        align-items: end;
        border-bottom: 1px solid var(--line);
        background:
          linear-gradient(180deg, rgba(247,241,232,0.58), rgba(247,241,232,0.98)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='720' viewBox='0 0 1200 720'%3E%3Crect width='1200' height='720' fill='%23efe2d0'/%3E%3Cpath d='M0 520 C220 420 340 590 560 500 C780 410 880 260 1200 320 L1200 720 L0 720 Z' fill='%2353685b' opacity='.28'/%3E%3Cpath d='M0 420 C230 330 390 430 620 360 C850 290 970 160 1200 210 L1200 720 L0 720 Z' fill='%232e5266' opacity='.20'/%3E%3Ccircle cx='940' cy='170' r='80' fill='%23fff7dc' opacity='.72'/%3E%3C/svg%3E");
        background-size: cover;
        background-position: center;
      }}
      .hero {{ padding: 42px 0 34px; max-width: 820px; }}
      .eyebrow {{
        margin: 0 0 10px;
        color: var(--wine);
        font: 700 12px/1.2 ui-sans-serif, system-ui, sans-serif;
        letter-spacing: .08em;
        text-transform: uppercase;
      }}
      h1 {{ margin: 0; font-size: clamp(2.3rem, 7vw, 5.6rem); line-height: .96; font-weight: 560; }}
      h2 {{ margin: 0 0 12px; font-size: clamp(1.55rem, 3vw, 2.4rem); line-height: 1.1; font-weight: 560; }}
      h3 {{ margin: 0 0 6px; font-size: 1.06rem; line-height: 1.25; }}
      p {{ margin: 0; }}
      .lead {{ margin-top: 20px; max-width: 64ch; color: var(--muted); font-size: 1.12rem; }}
      .notice {{
        margin-top: 22px;
        max-width: 760px;
        padding: 14px 16px;
        border-left: 4px solid var(--sage);
        background: rgba(255,250,242,.82);
        color: var(--muted);
      }}
      main {{ padding: 44px 0 72px; }}
      section {{ margin-top: 44px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
      .clip, .memory, .chat, .candidate {{
        border: 1px solid var(--line);
        background: var(--panel);
        border-radius: 8px;
        padding: 18px;
      }}
      .clip {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .65fr); gap: 18px; align-items: center; }}
      audio {{ width: 100%; }}
      .memory p:last-child, .clip p:last-child, .chat p {{ color: var(--muted); }}
      .candidates {{ display: grid; gap: 10px; }}
      .candidate {{ display: grid; grid-template-columns: minmax(0, 1fr) 170px; gap: 12px; align-items: start; }}
      .candidate span, .candidate p {{ color: var(--muted); }}
      .candidate p {{ grid-column: 1 / -1; }}
      .chat {{ background: #eef3ef; border-color: rgba(83,104,91,.24); }}
      .prompt-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
      button {{
        border: 1px solid rgba(46,82,102,.28);
        background: #fffaf2;
        color: var(--blue);
        border-radius: 999px;
        padding: 9px 12px;
        font: 650 14px/1 ui-sans-serif, system-ui, sans-serif;
      }}
      footer {{ border-top: 1px solid var(--line); padding: 24px 0; color: var(--muted); }}
      @media (max-width: 760px) {{
        header {{ min-height: 78vh; }}
        .grid, .clip {{ grid-template-columns: 1fr; }}
        .wrap {{ width: min(100vw - 28px, 1120px); }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div class="wrap hero">
        <p class="eyebrow">Gedenkseite · {html.escape(relationship)}</p>
        <h1>{html.escape(person_name)}</h1>
        <p class="lead">{html.escape(subtitle)}</p>
        <p class="notice">{html.escape(disclosure)}</p>
      </div>
    </header>
    <main class="wrap">
      <section>
        <h2>Worum es hier geht</h2>
        <p class="lead">{html.escape(intro)}</p>
      </section>
      <section>
        <h2>Seine Stimme hoeren</h2>
        {clips_html}
      </section>
      <section>
        <h2>Erinnerungen und Quellen</h2>
        <div class="grid">{cards_html}</div>
      </section>
      {candidates_html}
      <section class="chat">
        <p class="eyebrow">Erinnerungs-Chat</p>
        <h2>Nicht er selbst. Nur sorgfaeltig aus dem Archiv formuliert.</h2>
        <p>Antworten sollten immer zeigen, welche Aufnahme, Notiz oder Erinnerung zugrunde liegt. Wenn etwas nicht belegt ist, bleibt die Antwort ehrlich unsicher.</p>
        <div class="prompt-row">{prompts_html}</div>
      </section>
    </main>
    <footer>
      <div class="wrap">Hosted on myexternalbrain.com · Originalstimme nur aus freigegebenen Aufnahmen.</div>
    </footer>
  </body>
</html>"""


@router.get("/memorials/{slug}.json")
def public_memorial_manifest(slug: str) -> JSONResponse:
    return JSONResponse(_load_memorial(slug))


@router.get("/memorials/files/{slug}/{asset_path:path}")
def public_memorial_file(slug: str, asset_path: str) -> FileResponse:
    path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> HTMLResponse:
    return HTMLResponse(_memorial_html(_load_memorial(slug), hostname=request_hostname(request)))


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> HTMLResponse:
    return HTMLResponse(_memorial_html(_load_memorial(slug), hostname=request_hostname(request)))
