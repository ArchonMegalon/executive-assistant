#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
BASE_URL = "https://api.markupgo.com/api/v1/image/buffer"
OVERRIDE_PATH = Path("/docker/fleet/state/chummer6/ea_overrides.json")


def env_value(name: str) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return ""


def compact(value: object, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip(" ,;:-") + "..."


def short_sentence(value: object, *, limit: int = 180) -> str:
    text = compact(value, limit=max(limit * 2, 180))
    for splitter in (". ", "! ", "? ", ": "):
        head, sep, _ = text.partition(splitter)
        if sep and head.strip():
            text = head.strip()
            break
    return compact(text, limit=limit)


def load_media_overrides() -> dict[str, object]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        loaded = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def to_list(value: object, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for entry in value:
        cleaned = compact(entry, limit=72)
        if cleaned:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def keyword_hits(*values: object) -> set[str]:
    lowered = " ".join(str(value or "").lower() for value in values)
    tags: set[str] = set()
    for token, label in (
        ("x-ray", "xray"),
        ("xray", "xray"),
        ("scan", "xray"),
        ("simulation", "simulation"),
        ("sim", "simulation"),
        ("alice", "simulation"),
        ("ghost", "ghost"),
        ("replay", "ghost"),
        ("forensic", "ghost"),
        ("dossier", "dossier"),
        ("evidence", "dossier"),
        ("forge", "forge"),
        ("anvil", "forge"),
        ("heat web", "network"),
        ("network", "network"),
        ("thread", "network"),
        ("conflict", "network"),
        ("mirror", "mirror"),
        ("passport", "passport"),
        ("travel", "passport"),
        ("blackbox", "blackbox"),
        ("loadout", "blackbox"),
        ("map", "map"),
        ("table", "table"),
        ("team", "table"),
        ("runner", "person"),
        ("woman", "woman"),
        ("girl", "woman"),
        ("troll", "troll"),
        ("cyberdeck", "deck"),
        ("commlink", "deck"),
        ("sr4", "sr"),
        ("sr5", "sr"),
        ("sr6", "sr"),
    ):
        if token in lowered:
            tags.add(label)
    return tags


def theme_for(seed: str, palette_hint: str = "") -> tuple[str, str, str]:
    palette_text = str(palette_hint or "").lower()
    if "amber" in palette_text or "orange" in palette_text:
        palettes = [("#120914", "#ffb347", "#ff4f8b"), ("#180b08", "#ffb454", "#ff784f")]
    elif "green" in palette_text:
        palettes = [("#081310", "#4dff8f", "#16f2d1"), ("#10180c", "#8cff4d", "#38f7c8")]
    elif "purple" in palette_text or "violet" in palette_text:
        palettes = [("#120c1e", "#a855f7", "#60a5fa"), ("#14091e", "#c084fc", "#38bdf8")]
    else:
        palettes = [
            ("#0b1020", "#18f0ff", "#ff2f92"),
            ("#0f0d1a", "#7bff5b", "#2ee6ff"),
            ("#120914", "#ffcc33", "#ff4f8b"),
            ("#08141a", "#76ffd1", "#4fb3ff"),
        ]
    digest = hashlib.sha256((seed + "|" + palette_text).encode("utf-8")).hexdigest()
    return palettes[int(digest[:2], 16) % len(palettes)]


def default_scene_contract(prompt: str, *, title: str = "Chummer6") -> dict[str, object]:
    hits = keyword_hits(prompt, title)
    subject = "a cyberpunk runner"
    if "woman" in hits:
        subject = "a sharp-eyed cyberpunk woman"
    elif "troll" in hits:
        subject = "a cybernetic troll"
    elif "table" in hits:
        subject = "a runner team at a table"
    metaphor = "guide chrome"
    for key, value in (
        ("xray", "x-ray causality scan"),
        ("simulation", "branching simulation grid"),
        ("ghost", "forensic replay echoes"),
        ("dossier", "dossier evidence wall"),
        ("forge", "forge sparks and molten rules"),
        ("network", "living consequence web"),
        ("mirror", "mirror split"),
        ("passport", "passport gate"),
        ("blackbox", "blackbox loadout check"),
        ("map", "street map lattice"),
    ):
        if key in hits:
            metaphor = value
            break
    composition = "single_protagonist"
    if "table" in hits:
        composition = "group_table"
    elif "dossier" in hits or "blackbox" in hits:
        composition = "desk_still_life"
    props = ["neon HUD", "rain haze", "glitch reflections"]
    if "deck" in hits:
        props.insert(0, "battered cyberdeck")
    if "sr" in hits:
        props.append("rule stack shards")
    overlays = ["signal traces", "probability arcs", "receipt markers"]
    return {
        "subject": subject,
        "environment": "a dangerous but inviting cyberpunk scene",
        "action": "studying the next move before the chrome starts smoking",
        "metaphor": metaphor,
        "props": props[:6],
        "overlays": overlays[:4],
        "composition": composition,
        "palette": "cyan-magenta neon",
        "mood": "dangerous, curious, and slightly amused",
        "humor": "the dev may still deserve a little heat",
        "visual_prompt": compact(prompt, limit=360),
    }


def detect_metaphor(*values: object) -> str:
    hits = keyword_hits(*values)
    for key, value in (
        ("xray", "x-ray causality scan"),
        ("simulation", "branching simulation grid"),
        ("ghost", "forensic replay echoes"),
        ("dossier", "dossier evidence wall"),
        ("forge", "forge sparks and molten rules"),
        ("network", "living consequence web"),
        ("mirror", "mirror split"),
        ("passport", "passport gate"),
        ("blackbox", "blackbox loadout check"),
        ("map", "street map lattice"),
        ("table", "shared table state"),
    ):
        if key in hits:
            return value
    return "cyberpunk analysis overlay"


def normalize_scene_contract(raw: object, *, prompt: str, title: str) -> dict[str, object]:
    default = default_scene_contract(prompt, title=title)
    if not isinstance(raw, dict):
        return default
    merged = dict(default)
    for key in ("subject", "environment", "action", "metaphor", "composition", "palette", "mood", "humor", "visual_prompt"):
        value = compact(raw.get(key, ""), limit=220 if key != "visual_prompt" else 360)
        if value:
            merged[key] = value
    props = to_list(raw.get("props"), limit=6)
    overlays = to_list(raw.get("overlays"), limit=5)
    if props:
        merged["props"] = props
    if overlays:
        merged["overlays"] = overlays
    if not compact(merged.get("metaphor", "")):
        merged["metaphor"] = detect_metaphor(prompt, title, merged.get("subject", ""), merged.get("environment", ""))
    return merged


def page_scene_contract(page_id: str, page_row: dict[str, object], ooda_row: dict[str, object], *, composition_hint: str) -> dict[str, object]:
    act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
    observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
    orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
    decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
    base = default_scene_contract(
        " ".join(
            part
            for part in [
                page_row.get("intro", ""),
                page_row.get("body", ""),
                act.get("visual_prompt_seed", ""),
                orient.get("focal_subject", ""),
                orient.get("scene_logic", ""),
            ]
            if part
        ),
        title=compact(page_row.get("intro", ""), limit=64) or page_id.replace("_", " ").title(),
    )
    base["subject"] = compact(orient.get("focal_subject", ""), limit=120) or base["subject"]
    base["environment"] = compact(orient.get("scene_logic", ""), limit=160) or compact(page_row.get("body", ""), limit=160) or base["environment"]
    base["action"] = compact(act.get("paragraph_seed", ""), limit=160) or compact(act.get("one_liner", ""), limit=160) or base["action"]
    base["metaphor"] = detect_metaphor(
        act.get("visual_prompt_seed", ""),
        page_row.get("intro", ""),
        page_row.get("body", ""),
        page_id,
    )
    base["props"] = to_list(observe.get("concrete_signals"), limit=5) or to_list(observe.get("likely_interest"), limit=5) or base["props"]
    overlay_values = to_list(decide.get("overlay_priority"), limit=1) + to_list(observe.get("likely_interest"), limit=3)
    base["overlays"] = overlay_values[:4] if overlay_values else base["overlays"]
    base["composition"] = composition_hint
    base["palette"] = compact(orient.get("visual_devices", ""), limit=80) or base["palette"]
    base["mood"] = compact(orient.get("emotional_goal", ""), limit=120) or base["mood"]
    base["humor"] = compact(orient.get("tone_rule", ""), limit=120) or base["humor"]
    return base


def merge_scene_row(base: dict[str, object], row: dict[str, object], *, prompt: str) -> dict[str, object]:
    merged = dict(base)
    for key in ("badge", "title", "subtitle", "kicker", "note", "meta", "overlay_hint"):
        value = compact(row.get(key, ""), limit=120 if key not in {"subtitle", "note"} else 180)
        if value:
            merged[key] = value
    for key in ("visual_motifs", "overlay_callouts"):
        values = to_list(row.get(key), limit=6)
        if values:
            merged[key] = values
    merged["scene_contract"] = normalize_scene_contract(
        row.get("scene_contract"),
        prompt=prompt,
        title=str(merged.get("title", "Chummer6")),
    )
    return merged


def scene_for(output_name: str, prompt: str) -> dict[str, object]:
    name = output_name.lower()
    default = {
        "badge": "Chummer6",
        "title": "Chummer6",
        "subtitle": "Same shadows. Bigger future. Less confusion.",
        "kicker": "Guide art",
        "note": "Fresh chrome for the guide wall.",
        "meta": "",
        "overlay_hint": "diegetic analysis overlay",
        "visual_motifs": [],
        "overlay_callouts": [],
        "scene_contract": default_scene_contract(prompt, title="Chummer6"),
    }
    loaded = load_media_overrides()
    media = loaded.get("media") if isinstance(loaded, dict) else None
    pages = loaded.get("pages") if isinstance(loaded, dict) else None
    section_ooda = loaded.get("section_ooda") if isinstance(loaded, dict) else None
    page_ooda = section_ooda.get("pages") if isinstance(section_ooda, dict) else None

    def page_scene(page_id: str, *, fallback_badge: str, fallback_title: str, fallback_kicker: str, composition_hint: str) -> dict[str, object]:
        if not isinstance(pages, dict) or not isinstance(page_ooda, dict):
            raise RuntimeError(f"missing page media context for {output_name}")
        page_row = pages.get(page_id)
        ooda_row = page_ooda.get(page_id)
        if not isinstance(page_row, dict) or not isinstance(ooda_row, dict):
            raise RuntimeError(f"missing page media context for {output_name}")
        scene = dict(default)
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        scene["badge"] = compact(page_row.get("kicker", ""), limit=72) or fallback_badge
        scene["title"] = compact(act.get("one_liner", ""), limit=72) or compact(page_row.get("intro", ""), limit=72) or fallback_title
        scene["subtitle"] = compact(page_row.get("intro", ""), limit=180) or scene["subtitle"]
        scene["kicker"] = compact(act.get("paragraph_seed", ""), limit=120) or fallback_kicker
        scene["note"] = short_sentence(page_row.get("body", "") or page_row.get("kicker", ""), limit=180) or scene["note"]
        scene["overlay_hint"] = compact((ooda_row.get("decide") or {}).get("overlay_priority", ""), limit=80) or compact((ooda_row.get("orient") or {}).get("visual_devices", ""), limit=80) or scene["overlay_hint"]
        scene["visual_motifs"] = to_list((ooda_row.get("observe") or {}).get("likely_interest"), limit=5) or to_list((ooda_row.get("observe") or {}).get("concrete_signals"), limit=5)
        scene["overlay_callouts"] = to_list((ooda_row.get("observe") or {}).get("concrete_signals"), limit=4) or to_list((ooda_row.get("observe") or {}).get("likely_interest"), limit=4)
        scene["scene_contract"] = page_scene_contract(page_id, page_row, ooda_row, composition_hint=composition_hint)
        return scene

    page_targets = {
        "poc-warning.png": ("readme", "POC", "Test Dummy Drop", "Try the rough build", "desk_still_life"),
        "start-here.png": ("start_here", "Start", "Start Here", "Get your bearings fast", "city_edge"),
        "what-chummer6-is.png": ("what_chummer6_is", "Guide", "What Chummer6 Is", "The lay of the land", "single_protagonist"),
        "where-to-go-deeper.png": ("where_to_go_deeper", "Deeper", "Go Deeper", "Blueprints and code paths", "archive_room"),
        "current-phase.png": ("current_phase", "Now", "Current Phase", "Foundation work first", "workshop"),
        "current-status.png": ("current_status", "Now", "Current Status", "What is visible right now", "street_front"),
        "public-surfaces.png": ("public_surfaces", "Preview", "Public Surfaces", "Visible, but still settling", "street_front"),
        "parts-index.png": ("parts_index", "Parts", "Meet the Parts", "How the machine breaks down", "district_map"),
        "horizons-index.png": ("horizons_index", "Horizons", "Future Rabbit Holes", "The dangerous fun stuff", "city_edge"),
    }
    if name in page_targets:
        page_id, badge, title, kicker, composition = page_targets[name]
        return page_scene(page_id, fallback_badge=badge, fallback_title=title, fallback_kicker=kicker, composition_hint=composition)
    if isinstance(media, dict):
        if name == "chummer6-hero.png":
            hero = media.get("hero")
            if isinstance(hero, dict):
                return merge_scene_row(default, hero, prompt=prompt)
        parts = media.get("parts")
        if isinstance(parts, dict):
            slug = name.removesuffix(".png")
            row = parts.get(slug)
            if isinstance(row, dict):
                return merge_scene_row(default, row, prompt=prompt)
        horizons = media.get("horizons")
        if isinstance(horizons, dict):
            slug = name.removesuffix(".png")
            row = horizons.get(slug)
            if isinstance(row, dict):
                return merge_scene_row(default, row, prompt=prompt)
    raise RuntimeError(f"missing media context for {output_name}")


def css_escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def chips_html(values: list[str], *, kind: str) -> str:
    return "".join(
        f'<span class="chip {kind}">{css_escape(value)}</span>'
        for value in values[:4]
        if str(value).strip()
    )


def motif_classes(contract: dict[str, object]) -> set[str]:
    return keyword_hits(
        contract.get("subject", ""),
        contract.get("environment", ""),
        contract.get("action", ""),
        contract.get("metaphor", ""),
        " ".join(str(entry) for entry in contract.get("props", [])),
        " ".join(str(entry) for entry in contract.get("overlays", [])),
        contract.get("composition", ""),
        contract.get("palette", ""),
    )


def figure_html(kind: set[str]) -> str:
    if "table" in kind:
        return '''
        <div class="table-scene">
          <div class="table-top"></div>
          <div class="figure crew left"><span class="head"></span><span class="body"></span></div>
          <div class="figure crew center"><span class="head"></span><span class="body"></span></div>
          <div class="figure crew right"><span class="head"></span><span class="body"></span></div>
        </div>
        '''
    if "troll" in kind:
        return '''
        <div class="figure troll">
          <span class="head"></span><span class="body"></span><span class="arm left"></span><span class="arm right"></span>
        </div>
        '''
    person_class = "woman" if "woman" in kind else "runner"
    return f'''
    <div class="figure {person_class}">
      <span class="head"></span><span class="body"></span><span class="arm left"></span><span class="arm right"></span>
    </div>
    '''


def metaphor_html(kind: set[str]) -> str:
    blocks: list[str] = []
    if "xray" in kind:
        blocks.append(
            '''
            <div class="metaphor xray">
              <span class="scan ring one"></span><span class="scan ring two"></span>
              <span class="rib a"></span><span class="rib b"></span><span class="rib c"></span>
              <span class="spine"></span>
            </div>
            '''
        )
    if "simulation" in kind:
        blocks.append(
            '''
            <div class="metaphor simulation">
              <span class="grid-ring a"></span><span class="grid-ring b"></span><span class="grid-ring c"></span>
              <span class="branch one"></span><span class="branch two"></span><span class="branch three"></span>
            </div>
            '''
        )
    if "ghost" in kind:
        blocks.append(
            '''
            <div class="metaphor ghost">
              <span class="echo one"></span><span class="echo two"></span><span class="echo three"></span>
            </div>
            '''
        )
    if "dossier" in kind:
        blocks.append(
            '''
            <div class="metaphor dossier">
              <span class="sheet one"></span><span class="sheet two"></span><span class="sheet three"></span>
              <span class="string"></span>
            </div>
            '''
        )
    if "forge" in kind:
        blocks.append(
            '''
            <div class="metaphor forge">
              <span class="anvil"></span>
              <span class="spark a"></span><span class="spark b"></span><span class="spark c"></span><span class="spark d"></span>
            </div>
            '''
        )
    if "network" in kind or "map" in kind:
        blocks.append(
            '''
            <div class="metaphor network">
              <span class="node a"></span><span class="node b"></span><span class="node c"></span><span class="node d"></span>
              <span class="link ab"></span><span class="link bc"></span><span class="link cd"></span><span class="link ad"></span>
            </div>
            '''
        )
    if "mirror" in kind or "passport" in kind:
        blocks.append(
            '''
            <div class="metaphor split">
              <span class="panel left"></span><span class="panel right"></span><span class="divider"></span>
            </div>
            '''
        )
    if "blackbox" in kind:
        blocks.append(
            '''
            <div class="metaphor blackbox">
              <span class="crate"></span><span class="warning one"></span><span class="warning two"></span><span class="warning three"></span>
            </div>
            '''
        )
    return "".join(blocks)


def diagram_html(scene: dict[str, object], *, kind: str) -> str:
    labels = to_list(scene.get("visual_motifs"), limit=6) or to_list(scene.get("overlay_callouts"), limit=6)
    if kind == "status_strip":
        columns = labels[:3] or ["Now", "Preview", "Horizon"]
        tiles = "".join(
            f'<div class="status-tile"><div class="status-title">{css_escape(label)}</div></div>'
            for label in columns
        )
        return f'<div class="status-strip">{tiles}</div>'
    nodes = labels[:6] or ["Core", "UI", "Play", "Hub", "Registry", "Media"]
    cards = "".join(
        f'<div class="map-node">{css_escape(label)}</div>'
        for label in nodes
    )
    return f'<div class="program-map">{cards}</div>'


def composition_html(composition: str, kind: set[str]) -> str:
    if composition == "city_edge":
        return '''
        <div class="setpiece city-edge">
          <span class="skyline one"></span><span class="skyline two"></span><span class="skyline three"></span>
          <span class="street"></span><span class="street-glow"></span>
        </div>
        '''
    if composition == "archive_room":
        return '''
        <div class="setpiece archive-room">
          <span class="shelf left"></span><span class="shelf right"></span><span class="door"></span>
          <span class="aisle-glow"></span>
        </div>
        '''
    if composition == "workshop":
        return '''
        <div class="setpiece workshop">
          <span class="bench"></span><span class="lamp one"></span><span class="lamp two"></span>
          <span class="spark-tray"></span>
        </div>
        '''
    if composition == "street_front":
        return '''
        <div class="setpiece street-front">
          <span class="pane left"></span><span class="pane center"></span><span class="pane right"></span>
          <span class="awning"></span>
        </div>
        '''
    if composition == "district_map":
        return '''
        <div class="setpiece district-map">
          <span class="block a"></span><span class="block b"></span><span class="block c"></span><span class="block d"></span>
          <span class="lane one"></span><span class="lane two"></span>
        </div>
        '''
    if composition == "desk_still_life":
        return '''
        <div class="setpiece desk-still-life">
          <span class="desk"></span><span class="card one"></span><span class="card two"></span><span class="card three"></span>
          <span class="warning"></span>
        </div>
        '''
    if composition == "group_table":
        return '<div class="setpiece group-table"><span class="halo"></span></div>'
    return '''
    <div class="setpiece single-protagonist">
      <span class="frame left"></span><span class="frame right"></span><span class="beam"></span>
    </div>
    '''


def build_html(prompt: str, output_name: str, *, width: int, height: int) -> str:
    scene = scene_for(output_name, prompt)
    contract = scene.get("scene_contract") if isinstance(scene.get("scene_contract"), dict) else default_scene_contract(prompt)
    classes = motif_classes(contract)
    bg, accent_a, accent_b = theme_for(
        prompt + "|" + json.dumps(contract, ensure_ascii=True, sort_keys=True),
        palette_hint=str(contract.get("palette", "")),
    )
    composition = str(contract.get("composition", "single_protagonist")).strip() or "single_protagonist"
    setpiece = composition_html(composition, classes)
    figures = figure_html(classes) if composition not in {"desk_still_life", "archive_room", "district_map"} or {"woman", "runner", "troll", "table"} & classes else ""
    metaphors = metaphor_html(classes)
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      font-family: 'Segoe UI', system-ui, sans-serif;
      background:
        radial-gradient(circle at 20% 20%, {accent_a}22 0, transparent 22%),
        radial-gradient(circle at 82% 18%, {accent_b}20 0, transparent 24%),
        linear-gradient(140deg, {bg} 0%, #060913 58%, #03060d 100%);
      color: #f5f7fb;
    }}
    .stage {{
      position: relative;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }}
    .scan {{
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
      background-size: 48px 48px;
      opacity: 0.55;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,0.85), transparent);
    }}
    .glow {{
      position: absolute;
      inset: auto auto -18% -8%;
      width: 48%;
      height: 60%;
      border-radius: 999px;
      background: radial-gradient(circle, {accent_a}44 0, transparent 68%);
      filter: blur(24px);
      opacity: 0.7;
    }}
    .glow.two {{
      inset: -16% -10% auto auto;
      width: 42%;
      height: 48%;
      background: radial-gradient(circle, {accent_b}3a 0, transparent 70%);
    }}
    .scene {{
      position: absolute;
      inset: 0;
    }}
    .setpiece {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .setpiece.city-edge .skyline,
    .setpiece.archive-room .shelf,
    .setpiece.street-front .pane,
    .setpiece.district-map .block,
    .setpiece.desk-still-life .card,
    .setpiece.single-protagonist .frame {{
      position: absolute;
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.12);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
      box-shadow: 0 18px 28px rgba(0,0,0,0.24);
    }}
    .setpiece.city-edge .skyline.one {{ left: 52%; top: 18%; width: 10%; height: 38%; }}
    .setpiece.city-edge .skyline.two {{ left: 64%; top: 11%; width: 13%; height: 50%; }}
    .setpiece.city-edge .skyline.three {{ left: 79%; top: 22%; width: 9%; height: 34%; }}
    .setpiece.city-edge .street {{
      position: absolute; left: 0; right: 0; bottom: -2%; height: 28%;
      background: linear-gradient(180deg, rgba(6,10,18,0), rgba(2,4,10,0.96));
      clip-path: polygon(22% 0, 78% 0, 100% 100%, 0 100%);
    }}
    .setpiece.city-edge .street-glow {{
      position: absolute; left: 36%; bottom: 10%; width: 28%; height: 3px;
      background: linear-gradient(90deg, transparent, {accent_a}, transparent);
      box-shadow: 0 0 16px {accent_a};
    }}
    .setpiece.archive-room .shelf.left {{ left: 8%; top: 16%; width: 16%; height: 58%; }}
    .setpiece.archive-room .shelf.right {{ right: 8%; top: 16%; width: 16%; height: 58%; }}
    .setpiece.archive-room .door {{
      position: absolute; left: 39%; top: 18%; width: 22%; height: 54%;
      border-radius: 22px; border: 1px solid rgba(255,255,255,0.16);
      background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03));
    }}
    .setpiece.archive-room .aisle-glow {{
      position: absolute; left: 41%; top: 28%; width: 18%; height: 32%;
      background: radial-gradient(circle, {accent_b}44 0, transparent 72%);
      filter: blur(16px);
    }}
    .setpiece.workshop .bench {{
      position: absolute; left: 12%; right: 12%; bottom: 14%; height: 18%;
      border-radius: 28px; border: 1px solid rgba(255,255,255,0.14);
      background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03));
    }}
    .setpiece.workshop .lamp {{
      position: absolute; top: 4%; width: 3px; height: 24%; background: rgba(255,255,255,0.16);
    }}
    .setpiece.workshop .lamp.one {{ left: 34%; }}
    .setpiece.workshop .lamp.two {{ left: 66%; }}
    .setpiece.workshop .spark-tray {{
      position: absolute; left: 44%; bottom: 20%; width: 12%; height: 12%;
      background: radial-gradient(circle, {accent_b}55 0, transparent 70%);
      filter: blur(10px);
    }}
    .setpiece.street-front .pane.left {{ left: 10%; top: 18%; width: 18%; height: 48%; }}
    .setpiece.street-front .pane.center {{ left: 33%; top: 14%; width: 26%; height: 54%; }}
    .setpiece.street-front .pane.right {{ right: 10%; top: 20%; width: 18%; height: 44%; }}
    .setpiece.street-front .awning {{
      position: absolute; left: 30%; top: 10%; width: 32%; height: 8%;
      border-radius: 999px; background: linear-gradient(90deg, {accent_a}, {accent_b});
      opacity: 0.22; filter: blur(6px);
    }}
    .setpiece.district-map .block.a {{ left: 16%; top: 24%; width: 14%; height: 24%; }}
    .setpiece.district-map .block.b {{ left: 34%; top: 18%; width: 18%; height: 34%; }}
    .setpiece.district-map .block.c {{ left: 57%; top: 28%; width: 16%; height: 22%; }}
    .setpiece.district-map .block.d {{ left: 74%; top: 20%; width: 10%; height: 30%; }}
    .setpiece.district-map .lane {{
      position: absolute; height: 3px; background: linear-gradient(90deg, {accent_a}, transparent);
      box-shadow: 0 0 10px {accent_a}; transform-origin: left center;
    }}
    .setpiece.district-map .lane.one {{ left: 28%; top: 42%; width: 28%; transform: rotate(-8deg); }}
    .setpiece.district-map .lane.two {{ left: 49%; top: 38%; width: 24%; transform: rotate(12deg); }}
    .setpiece.desk-still-life .desk {{
      position: absolute; left: 8%; right: 8%; bottom: 8%; height: 24%;
      border-radius: 26px; border: 1px solid rgba(255,255,255,0.14);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
    }}
    .setpiece.desk-still-life .card.one {{ left: 22%; top: 30%; width: 16%; height: 24%; transform: rotate(-10deg); }}
    .setpiece.desk-still-life .card.two {{ left: 42%; top: 22%; width: 18%; height: 26%; transform: rotate(6deg); }}
    .setpiece.desk-still-life .card.three {{ left: 62%; top: 31%; width: 15%; height: 22%; transform: rotate(-4deg); }}
    .setpiece.desk-still-life .warning {{
      position: absolute; left: 48%; top: 38%; width: 12%; height: 12%;
      border-radius: 999px; background: {accent_b}; box-shadow: 0 0 16px {accent_b};
    }}
    .setpiece.group-table .halo {{
      position: absolute; left: 20%; top: 30%; width: 46%; height: 24%;
      border-radius: 999px; border: 1px solid {accent_a}66;
      box-shadow: 0 0 18px {accent_a};
    }}
    .setpiece.single-protagonist .frame.left {{ left: 10%; top: 20%; width: 8%; height: 50%; }}
    .setpiece.single-protagonist .frame.right {{ right: 10%; top: 18%; width: 10%; height: 54%; }}
    .setpiece.single-protagonist .beam {{
      position: absolute; left: 48%; top: 0; width: 4px; height: 72%;
      background: linear-gradient(180deg, {accent_b}, transparent);
      opacity: 0.26;
    }}
    .figure {{
      position: absolute;
      left: 18%;
      bottom: 16%;
      width: 18%;
      height: 54%;
      filter: drop-shadow(0 18px 28px rgba(0,0,0,0.45));
    }}
    .figure .head {{
      position: absolute;
      left: 31%;
      top: 4%;
      width: 38%;
      height: 18%;
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(255,255,255,0.42), rgba(255,255,255,0.08));
      border: 1px solid rgba(255,255,255,0.22);
    }}
    .figure .body {{
      position: absolute;
      left: 24%;
      top: 19%;
      width: 52%;
      height: 46%;
      border-radius: 28px 28px 20px 20px;
      background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.03));
      border: 1px solid rgba(255,255,255,0.18);
    }}
    .figure .arm {{
      position: absolute;
      top: 28%;
      width: 16%;
      height: 28%;
      border-radius: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.02));
      border: 1px solid rgba(255,255,255,0.12);
    }}
    .figure .arm.left {{ left: 10%; transform: rotate(16deg); }}
    .figure .arm.right {{ right: 10%; transform: rotate(-16deg); }}
    .figure.runner::after {{
      content: "";
      position: absolute;
      left: 18%;
      top: 14%;
      width: 64%;
      height: 18%;
      border-radius: 999px;
      background: linear-gradient(90deg, transparent 0, {accent_a}88 32%, transparent 100%);
      filter: blur(10px);
      opacity: 0.85;
    }}
    .figure.woman::before {{
      content: "";
      position: absolute;
      left: 16%;
      top: 2%;
      width: 68%;
      height: 24%;
      border-radius: 48% 48% 56% 56%;
      background: linear-gradient(180deg, {accent_b}88, rgba(255,255,255,0.08));
      filter: blur(2px);
      opacity: 0.72;
    }}
    .figure.troll {{
      left: 14%;
      width: 24%;
      height: 58%;
    }}
    .table-scene {{
      position: absolute;
      left: 10%;
      bottom: 14%;
      width: 40%;
      height: 42%;
    }}
    .table-top {{
      position: absolute;
      left: 2%;
      right: 2%;
      bottom: 8%;
      height: 16%;
      border-radius: 32px;
      background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.04));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .figure.crew {{
      width: 18%;
      height: 62%;
      bottom: 18%;
    }}
    .figure.crew.left {{ left: 0; }}
    .figure.crew.center {{ left: 38%; }}
    .figure.crew.right {{ left: 76%; }}
    .metaphor {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .metaphor.xray .scan.ring,
    .metaphor.simulation .grid-ring {{
      position: absolute;
      border-radius: 999px;
      border: 1px solid {accent_a}88;
      opacity: 0.72;
    }}
    .metaphor.xray .scan.ring.one {{ left: 20%; top: 18%; width: 26%; height: 36%; }}
    .metaphor.xray .scan.ring.two {{ left: 16%; top: 14%; width: 34%; height: 44%; border-color: {accent_b}66; }}
    .metaphor.xray .spine {{
      position: absolute;
      left: 31%;
      top: 28%;
      width: 4px;
      height: 30%;
      background: linear-gradient(180deg, rgba(255,255,255,0.1), {accent_a});
      box-shadow: 0 0 12px {accent_a};
    }}
    .metaphor.xray .rib {{
      position: absolute;
      width: 14%;
      height: 2px;
      left: 24%;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.85), transparent);
    }}
    .metaphor.xray .rib.a {{ top: 34%; }}
    .metaphor.xray .rib.b {{ top: 39%; }}
    .metaphor.xray .rib.c {{ top: 44%; }}
    .metaphor.simulation .grid-ring.a {{ left: 18%; top: 18%; width: 30%; height: 40%; }}
    .metaphor.simulation .grid-ring.b {{ left: 15%; top: 14%; width: 36%; height: 48%; border-color: {accent_b}7a; }}
    .metaphor.simulation .grid-ring.c {{ left: 12%; top: 10%; width: 42%; height: 56%; border-color: rgba(255,255,255,0.28); }}
    .metaphor.simulation .branch {{
      position: absolute;
      width: 22%;
      height: 2px;
      background: linear-gradient(90deg, {accent_a}, transparent);
      transform-origin: left center;
    }}
    .metaphor.simulation .branch.one {{ left: 48%; top: 28%; transform: rotate(-18deg); }}
    .metaphor.simulation .branch.two {{ left: 48%; top: 38%; transform: rotate(4deg); }}
    .metaphor.simulation .branch.three {{ left: 48%; top: 48%; transform: rotate(20deg); }}
    .metaphor.ghost .echo {{
      position: absolute;
      left: 18%;
      top: 16%;
      width: 20%;
      height: 54%;
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.16);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), transparent);
    }}
    .metaphor.ghost .echo.one {{ opacity: 0.18; transform: translateX(0); }}
    .metaphor.ghost .echo.two {{ opacity: 0.12; transform: translateX(48px); }}
    .metaphor.ghost .echo.three {{ opacity: 0.08; transform: translateX(92px); }}
    .metaphor.dossier .sheet {{
      position: absolute;
      width: 18%;
      height: 26%;
      top: 20%;
      left: 58%;
      border-radius: 20px;
      border: 1px solid rgba(255,255,255,0.14);
      background: linear-gradient(180deg, rgba(255,255,255,0.11), rgba(255,255,255,0.03));
      box-shadow: 0 16px 24px rgba(0,0,0,0.28);
    }}
    .metaphor.dossier .sheet.one {{ transform: rotate(-8deg); }}
    .metaphor.dossier .sheet.two {{ transform: rotate(4deg) translateX(44px); }}
    .metaphor.dossier .sheet.three {{ transform: rotate(-2deg) translateX(88px); }}
    .metaphor.dossier .string {{
      position: absolute;
      left: 60%;
      top: 24%;
      width: 22%;
      height: 24%;
      border-left: 2px solid {accent_b};
      border-top: 2px solid {accent_b};
      transform: rotate(12deg);
    }}
    .metaphor.forge .anvil {{
      position: absolute;
      left: 22%;
      bottom: 18%;
      width: 24%;
      height: 12%;
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.04));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .metaphor.forge .spark {{
      position: absolute;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: {accent_b};
      box-shadow: 0 0 18px {accent_b};
    }}
    .metaphor.forge .spark.a {{ left: 42%; top: 28%; }}
    .metaphor.forge .spark.b {{ left: 46%; top: 24%; }}
    .metaphor.forge .spark.c {{ left: 50%; top: 30%; }}
    .metaphor.forge .spark.d {{ left: 48%; top: 18%; }}
    .metaphor.network .node {{
      position: absolute;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      background: {accent_a};
      box-shadow: 0 0 16px {accent_a};
    }}
    .metaphor.network .node.a {{ left: 58%; top: 22%; }}
    .metaphor.network .node.b {{ left: 72%; top: 34%; }}
    .metaphor.network .node.c {{ left: 64%; top: 52%; }}
    .metaphor.network .node.d {{ left: 80%; top: 46%; }}
    .metaphor.network .link {{
      position: absolute;
      height: 2px;
      background: linear-gradient(90deg, {accent_a}, {accent_b});
      transform-origin: left center;
      opacity: 0.7;
    }}
    .metaphor.network .link.ab {{ left: 59%; top: 24%; width: 14%; transform: rotate(20deg); }}
    .metaphor.network .link.bc {{ left: 65%; top: 40%; width: 12%; transform: rotate(96deg); }}
    .metaphor.network .link.cd {{ left: 66%; top: 54%; width: 18%; transform: rotate(-16deg); }}
    .metaphor.network .link.ad {{ left: 60%; top: 28%; width: 24%; transform: rotate(34deg); }}
    .metaphor.split .panel {{
      position: absolute;
      top: 18%;
      width: 18%;
      height: 46%;
      border-radius: 24px;
      border: 1px solid rgba(255,255,255,0.14);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
    }}
    .metaphor.split .panel.left {{ left: 18%; }}
    .metaphor.split .panel.right {{ left: 52%; }}
    .metaphor.split .divider {{
      position: absolute;
      left: 48%;
      top: 14%;
      width: 2px;
      height: 56%;
      background: linear-gradient(180deg, transparent, {accent_b}, transparent);
    }}
    .metaphor.blackbox .crate {{
      position: absolute;
      left: 22%;
      bottom: 20%;
      width: 22%;
      height: 16%;
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.16);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
      box-shadow: 0 14px 28px rgba(0,0,0,0.35);
    }}
    .metaphor.blackbox .warning {{
      position: absolute;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: {accent_b};
      box-shadow: 0 0 12px {accent_b};
    }}
    .metaphor.blackbox .warning.one {{ left: 48%; top: 26%; }}
    .metaphor.blackbox .warning.two {{ left: 54%; top: 22%; }}
    .metaphor.blackbox .warning.three {{ left: 60%; top: 28%; }}
    .program-map {{
      position: absolute;
      inset: 18% 14% 18% 14%;
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px;
      align-content: center;
    }}
    .program-map .map-node,
    .status-strip .status-tile {{
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.14);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
      backdrop-filter: blur(8px);
      padding: 20px 18px;
      box-shadow: 0 18px 30px rgba(0,0,0,0.24);
      font-size: 20px;
      line-height: 1.2;
      color: rgba(248,250,252,0.92);
      text-align: center;
    }}
    .status-strip {{
      position: absolute;
      inset: 30% 10% 24% 10%;
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 22px;
      align-items: stretch;
    }}
    .status-strip .status-title {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
  </style>
</head>
<body>
  <div class="stage">
    <div class="scan"></div>
    <div class="glow"></div>
    <div class="glow two"></div>
    <div class="scene">
      {setpiece}
      {figures}
      {metaphors}
    </div>
  </div>
</body>
</html>
'''


def render(prompt: str, output: Path, *, width: int, height: int) -> None:
    api_key = env_value("MARKUPGO_API_KEY")
    if not api_key:
        raise SystemExit("MARKUPGO_API_KEY is not configured")
    body = {
        "source": {
            "type": "html",
            "data": build_html(prompt, output.name, width=width, height=height),
        },
        "options": {
            "properties": {
                "format": "png",
                "width": width,
                "height": height,
                "clip": True,
            },
            "optimizeForSpeed": True,
        },
    }
    request = urllib.request.Request(
        BASE_URL,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "EA-Chummer6-MarkupGo/1.0",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise SystemExit(f"MarkupGo HTTP {exc.code}: {body[:300]}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"MarkupGo transport error: {exc.reason}")
    if not data:
        raise SystemExit("MarkupGo returned empty output")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Chummer6 art through MarkupGo.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()
    render(str(args.prompt), Path(args.output).expanduser(), width=int(args.width), height=int(args.height))
    print(json.dumps({"output": str(Path(args.output).expanduser()), "status": "rendered"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
