from __future__ import annotations

import html
import json
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


router = APIRouter(tags=["public-tours"])


def _tour_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/fleet/state/public_property_tours")).expanduser()


def _tour_path(slug: str) -> Path:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="tour_not_found")
    bundle_dir = _tour_dir() / safe
    if bundle_dir.is_dir():
        bundle_manifest = bundle_dir / "tour.json"
        if bundle_manifest.exists():
            return bundle_manifest
    return _tour_dir() / f"{safe}.json"


def _tour_bundle_dir(slug: str) -> Path | None:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="tour_not_found")
    bundle_dir = _tour_dir() / safe
    if bundle_dir.is_dir():
        return bundle_dir
    return None


def _load_tour(slug: str) -> dict[str, object]:
    path = _tour_path(slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail="tour_not_found")
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="tour_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="tour_payload_invalid")
    return payload


def _asset_file(slug: str, asset_path: str) -> Path:
    bundle_dir = _tour_bundle_dir(slug)
    if bundle_dir is None:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    candidate = (bundle_dir / str(asset_path or "")).resolve()
    if bundle_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    return candidate


def _money(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"EUR {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "EUR ?"


def _tour_html(payload: dict[str, object]) -> str:
    scenes = [dict(row) for row in (payload.get("scenes") or []) if isinstance(row, dict)]
    if not scenes:
        raise HTTPException(status_code=500, detail="tour_scenes_missing")
    facts = dict(payload.get("facts") or {})
    brief = dict(payload.get("brief") or {})
    title = str(payload.get("title") or payload.get("tour_title") or payload.get("slug") or "Property Tour").strip()
    display_title = str(payload.get("display_title") or title).strip() or title
    listing_url = str(payload.get("listing_url") or "").strip()
    hosted_url = str(payload.get("hosted_url") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    video_relpath = str(payload.get("video_relpath") or "").strip()
    video_fallback_relpath = str(payload.get("video_fallback_relpath") or "").strip()
    video_url = f"/tours/files/{slug}/{video_relpath}" if slug and video_relpath else ""
    video_fallback_url = f"/tours/files/{slug}/{video_fallback_relpath}" if slug and video_fallback_relpath else ""
    scene_data = [
        {
            "name": str(scene.get("name") or "").strip(),
            "image_url": (
                f"/tours/files/{slug}/{str(scene.get('asset_relpath') or '').strip()}"
                if slug and str(scene.get("asset_relpath") or "").strip()
                else str(scene.get("image_url") or "").strip()
            ),
            "role": str(scene.get("role") or "photo").strip(),
            "source_url": str(scene.get("source_url") or "").strip(),
        }
        for scene in scenes
    ]
    data_json = json.dumps(scene_data, ensure_ascii=False).replace("</", "<\\/")
    title_html = html.escape(title)
    display_html = html.escape(display_title)
    variant_label = html.escape(str(payload.get("variant_label") or payload.get("variant_key") or "").strip())
    rooms = html.escape(str(facts.get("rooms") or "?"))
    area = html.escape(str(facts.get("area_sqm") or "?"))
    rent = html.escape(_money(facts.get("total_rent_eur")))
    availability = html.escape(str(facts.get("availability") or "?"))
    address = "<br>".join(html.escape(str(value)) for value in (facts.get("address_lines") or []))
    teaser = " · ".join(html.escape(str(value)) for value in (facts.get("teaser_attributes") or []))
    creative_brief = html.escape(str(brief.get("creative_brief") or "").strip())
    theme_name = html.escape(str(brief.get("theme_name") or "").strip())
    tour_style = html.escape(str(brief.get("tour_style") or "").strip())
    audience = html.escape(str(brief.get("audience") or "").strip())
    cta = html.escape(str(brief.get("call_to_action") or "").strip())
    listing_link = f'<a class="ghost" href="{html.escape(listing_url)}" target="_blank" rel="noreferrer">Open Listing</a>' if listing_url else ""
    hosted_link = f'<a class="ghost" href="{html.escape(hosted_url)}">Permalink</a>' if hosted_url else ""
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    <style>
      :root {{
        --bg: #f3eee3;
        --panel: rgba(255,255,255,0.76);
        --ink: #1d1c1a;
        --muted: #6e6658;
        --accent: #9f2f22;
        --edge: rgba(29,28,26,0.12);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        background:
          radial-gradient(circle at top left, rgba(159,47,34,0.18), transparent 34%),
          radial-gradient(circle at bottom right, rgba(29,28,26,0.10), transparent 30%),
          linear-gradient(160deg, #f8f4eb 0%, #ece5d8 100%);
      }}
      .shell {{
        max-width: 1220px;
        margin: 0 auto;
        padding: 24px;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        gap: 22px;
        align-items: start;
      }}
      .mast, .panel {{
        background: var(--panel);
        backdrop-filter: blur(14px);
        border: 1px solid var(--edge);
        border-radius: 28px;
        box-shadow: 0 18px 50px rgba(29,28,26,0.08);
      }}
      .mast {{
        padding: 28px;
      }}
      .eyebrow {{
        display: inline-flex;
        gap: 10px;
        align-items: center;
        font-size: 12px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      h1 {{
        margin: 16px 0 10px;
        font-size: clamp(2rem, 4vw, 4.2rem);
        line-height: 0.95;
      }}
      .sub {{
        margin: 0;
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.55;
        max-width: 65ch;
      }}
      .facts {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 20px 0 22px;
      }}
      .chip {{
        padding: 10px 14px;
        border-radius: 999px;
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(29,28,26,0.09);
        font-size: 14px;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 18px;
      }}
      a {{
        color: inherit;
        text-decoration: none;
      }}
      .ghost, .cta {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 44px;
        padding: 0 18px;
        border-radius: 999px;
        border: 1px solid var(--edge);
      }}
      .cta {{
        background: var(--ink);
        color: #fff9f1;
        border-color: transparent;
      }}
      .panel {{
        padding: 22px;
      }}
      .panel h2 {{
        margin: 0 0 10px;
        font-size: 1.1rem;
      }}
      .stack {{
        display: grid;
        gap: 12px;
      }}
      .kv {{
        padding: 12px 14px;
        border-radius: 18px;
        background: rgba(255,255,255,0.7);
        border: 1px solid rgba(29,28,26,0.07);
      }}
      .kv b {{
        display: block;
        margin-bottom: 4px;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--muted);
      }}
      .stage {{
        margin-top: 22px;
        display: grid;
        gap: 18px;
      }}
      .hero-video {{
        overflow: hidden;
        border-radius: 30px;
        background: rgba(18,17,16,0.94);
        border: 1px solid rgba(29,28,26,0.15);
        box-shadow: 0 18px 50px rgba(29,28,26,0.08);
      }}
      .hero-video video {{
        display: block;
        width: 100%;
        min-height: 360px;
        max-height: 78vh;
        background: #111;
      }}
      .tour-toolbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .toggle {{
        display: inline-flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .toggle button {{
        min-height: 42px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid rgba(29,28,26,0.10);
        background: rgba(255,255,255,0.72);
        color: var(--ink);
        cursor: pointer;
      }}
      .toggle button.active {{
        background: var(--ink);
        color: #fff8ef;
        border-color: var(--ink);
      }}
      .viewer {{
        position: relative;
        overflow: hidden;
        border-radius: 30px;
        background: rgba(18,17,16,0.94);
        min-height: 420px;
        border: 1px solid rgba(29,28,26,0.15);
      }}
      .viewer img {{
        width: 100%;
        height: 72vh;
        max-height: 760px;
        min-height: 420px;
        object-fit: contain;
        display: block;
      }}
      .caption {{
        position: absolute;
        left: 18px;
        bottom: 18px;
        padding: 12px 16px;
        max-width: min(90%, 520px);
        border-radius: 18px;
        background: rgba(11,11,10,0.64);
        color: #fffaf2;
      }}
      .caption small {{
        display: block;
        opacity: 0.72;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .nav {{
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 14px;
        pointer-events: none;
      }}
      .nav button {{
        pointer-events: auto;
        width: 52px;
        height: 52px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.08);
        color: #fffaf2;
        font-size: 20px;
        cursor: pointer;
      }}
      .thumbs {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 10px;
      }}
      .thumb {{
        position: relative;
        overflow: hidden;
        border-radius: 18px;
        border: 2px solid transparent;
        background: rgba(255,255,255,0.6);
        cursor: pointer;
      }}
      .thumb.active {{
        border-color: var(--accent);
      }}
      .thumb.hidden {{
        display: none;
      }}
      .thumb img {{
        width: 100%;
        height: 104px;
        object-fit: cover;
        display: block;
      }}
      .badge {{
        position: absolute;
        left: 8px;
        top: 8px;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(11,11,10,0.72);
        color: #fffaf2;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      @media (max-width: 900px) {{
        .hero {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 640px) {{
        .shell {{ padding: 14px; }}
        .mast, .panel {{ border-radius: 22px; }}
        .viewer img {{ min-height: 320px; height: 52vh; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <div class="mast">
          <div class="eyebrow">EA Property Tour <span>•</span> {variant_label}</div>
          <h1>{title_html}</h1>
          <p class="sub">{display_html}</p>
          <div class="facts">
            <div class="chip">{rooms} Zimmer</div>
            <div class="chip">{area} m²</div>
            <div class="chip">{rent}</div>
            <div class="chip">Verfügbar: {availability}</div>
            <div class="chip">{html.escape(str(payload.get("scene_count") or len(scenes)))} Szenen</div>
          </div>
          <p class="sub">{teaser}</p>
          <div class="actions">
            <a class="cta" href="#viewer">Open Tour</a>
            {listing_link}
            {hosted_link}
          </div>
        </div>
        <aside class="panel">
          <h2>Tour Brief</h2>
          <div class="stack">
            <div class="kv"><b>Theme</b>{theme_name}</div>
            <div class="kv"><b>Style</b>{tour_style}</div>
            <div class="kv"><b>Audience</b>{audience}</div>
            <div class="kv"><b>Creative Brief</b>{creative_brief}</div>
            <div class="kv"><b>CTA</b>{cta}</div>
            <div class="kv"><b>Adresse</b>{address}</div>
          </div>
        </aside>
      </section>
      <section class="stage">
        {(
            f'''<div class="hero-video">
              <video id="tour-video" controls playsinline preload="metadata" poster="{html.escape(scene_data[0]["image_url"])}">
                <source src="{html.escape(video_url)}" type="video/webm">
                {f'<source src="{html.escape(video_fallback_url)}" type="video/mp4">' if video_fallback_url else ''}
              </video>
            </div>'''
        ) if video_url else ''}
        <div class="tour-toolbar">
          <div class="toggle" id="role-filter">
            <button type="button" class="active" data-role="all">All Scenes</button>
            <button type="button" data-role="photo">Photos</button>
            <button type="button" data-role="floorplan">Floorplans</button>
          </div>
          <div class="toggle">
            <button type="button" id="autoplay-btn">Autoplay Scenes</button>
          </div>
        </div>
        <div id="viewer" class="viewer">
          <img id="stage-image" src="{html.escape(scene_data[0]['image_url'])}" alt="{html.escape(scene_data[0]['name'])}">
          <div class="caption">
            <small id="stage-role">{html.escape(scene_data[0]['role'])}</small>
            <div id="stage-name">{html.escape(scene_data[0]['name'])}</div>
          </div>
          <div class="nav">
            <button id="prev-btn" aria-label="Previous scene">‹</button>
            <button id="next-btn" aria-label="Next scene">›</button>
          </div>
        </div>
        <div id="thumbs" class="thumbs"></div>
      </section>
    </div>
    <script id="scene-data" type="application/json">{data_json}</script>
    <script>
      const scenes = JSON.parse(document.getElementById("scene-data").textContent);
      let activeIndex = 0;
      const stageImage = document.getElementById("stage-image");
      const stageName = document.getElementById("stage-name");
      const stageRole = document.getElementById("stage-role");
      const thumbs = document.getElementById("thumbs");
      const autoplayButton = document.getElementById("autoplay-btn");
      let autoplayHandle = null;
      let activeRoleFilter = "all";
      function visibleSceneIndexes() {{
        return scenes
          .map((scene, index) => (activeRoleFilter === "all" || scene.role === activeRoleFilter ? index : -1))
          .filter((index) => index >= 0);
      }}
      function renderThumbs() {{
        thumbs.innerHTML = "";
        scenes.forEach((scene, index) => {{
          const button = document.createElement("button");
          button.className = "thumb" + (index === activeIndex ? " active" : "");
          button.type = "button";
          if (activeRoleFilter !== "all" && scene.role !== activeRoleFilter) button.classList.add("hidden");
          button.innerHTML = `<span class="badge">${{scene.role}}</span><img src="${{scene.image_url}}" alt="${{scene.name}}">`;
          button.addEventListener("click", () => setActive(index));
          thumbs.appendChild(button);
        }});
      }}
      function setActive(index) {{
        activeIndex = (index + scenes.length) % scenes.length;
        const scene = scenes[activeIndex];
        stageImage.src = scene.image_url;
        stageImage.alt = scene.name;
        stageName.textContent = scene.name;
        stageRole.textContent = scene.role;
        renderThumbs();
      }}
      function shiftVisible(delta) {{
        const visible = visibleSceneIndexes();
        if (!visible.length) return;
        const currentSlot = Math.max(0, visible.indexOf(activeIndex));
        const nextSlot = (currentSlot + delta + visible.length) % visible.length;
        setActive(visible[nextSlot]);
      }}
      document.getElementById("prev-btn").addEventListener("click", () => shiftVisible(-1));
      document.getElementById("next-btn").addEventListener("click", () => shiftVisible(1));
      window.addEventListener("keydown", (event) => {{
        if (event.key === "ArrowLeft") shiftVisible(-1);
        if (event.key === "ArrowRight") shiftVisible(1);
      }});
      document.querySelectorAll("#role-filter button").forEach((button) => {{
        button.addEventListener("click", () => {{
          activeRoleFilter = button.dataset.role || "all";
          document.querySelectorAll("#role-filter button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
          const visible = visibleSceneIndexes();
          if (visible.length && !visible.includes(activeIndex)) activeIndex = visible[0];
          renderThumbs();
          setActive(activeIndex);
        }});
      }});
      autoplayButton.addEventListener("click", () => {{
        if (autoplayHandle) {{
          clearInterval(autoplayHandle);
          autoplayHandle = null;
          autoplayButton.textContent = "Autoplay Scenes";
          return;
        }}
        autoplayButton.textContent = "Stop Autoplay";
        autoplayHandle = setInterval(() => shiftVisible(1), 2600);
      }});
      renderThumbs();
    </script>
  </body>
</html>"""


@router.get("/tours/{slug}.json", response_class=JSONResponse)
def public_tour_payload(slug: str) -> JSONResponse:
    return JSONResponse(_load_tour(slug))


@router.get("/tours/files/{slug}/{asset_path:path}")
def public_tour_file(slug: str, asset_path: str) -> FileResponse:
    file_path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@router.get("/tours/{slug}", response_class=HTMLResponse)
def public_tour_page(slug: str) -> HTMLResponse:
    payload = _load_tour(slug)
    return HTMLResponse(_tour_html(payload))
