#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chummer6_guide_canon import load_horizon_canon, load_part_canon
from chummer6_runtime_config import load_local_env, load_runtime_overrides


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_media_last.json")
MANIFEST_OUT = Path("/docker/fleet/state/chummer6/ea_media_manifest.json")
SCENE_LEDGER_OUT = Path("/docker/fleet/state/chummer6/ea_scene_ledger.json")
GUIDE_VISUAL_OVERRIDES = EA_ROOT / "chummer6_guide" / "VISUAL_OVERRIDES.json"
MEDIA_FACTORY_ROOT = Path("/docker/fleet/repos/chummer-media-factory")
MEDIA_FACTORY_RENDER_SCRIPT = MEDIA_FACTORY_ROOT / "scripts" / "render_guide_asset.py"
TROLL_MARK_PATH = Path("/docker/chummercomplete/Chummer6/assets/meta/chummer-troll.png")
DEFAULT_PROVIDER_ORDER = [
    "magixai",
    "media_factory",
    "onemin",
    "browseract_magixai",
    "browseract_prompting_systems",
]
PALETTES = [
    ("#0f766e", "#34d399"),
    ("#1d4ed8", "#7dd3fc"),
    ("#7c3aed", "#c084fc"),
    ("#7c2d12", "#fb923c"),
    ("#be123c", "#fb7185"),
    ("#4338ca", "#818cf8"),
]
TABLEAU_COMPOSITIONS = {"safehouse_table", "group_table"}
SPARSE_EASTER_EGG_TARGETS = frozenset(
    {
        "assets/hero/chummer6-hero.png",
        "assets/pages/start-here.png",
        "assets/horizons/karma-forge.png",
    }
)
SPARSE_HUMOR_TARGETS = frozenset(
    {
        "assets/hero/poc-warning.png",
        "assets/horizons/karma-forge.png",
    }
)
EASTER_EGG_FIELDS = (
    "easter_egg_kind",
    "easter_egg_placement",
    "easter_egg_detail",
    "easter_egg_visibility",
    "troll_postpass",
)
EASTER_EGG_OBJECT_HINTS = (
    "sticker",
    "tattoo",
    "patch",
    "decal",
    "doodle",
    "mascot",
    "motif",
    "mark",
    "charm",
    "stamp",
    "seal",
    "pin",
    "pictogram",
    "figurine",
    "patch",
)
META_HUMOR_TOKENS = (
    " dev ",
    " developer",
    " maintainer",
    " sysadmin",
    " admin ",
    " cleanup pass",
    " growth funnel",
    " repo ",
    " repo-",
    " vibe-based",
    " clean code",
    " not my bug",
    " one-liner",
    " roast",
    " roasting",
)
READABLE_JOKE_TOKENS = (
    "reads:",
    "says:",
    "sign reads",
    "sticker reads",
    "placard reads",
    "quote:",
)


LOCAL_ENV = load_local_env()
POLICY_ENV = load_runtime_overrides()
FFMPEG_BIN = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


def easter_egg_allowed_for_target(target: str) -> bool:
    return True


def scene_contract_requests_easter_egg(contract: dict[str, object] | None) -> bool:
    data = contract if isinstance(contract, dict) else {}
    if any(str(data.get(field) or "").strip() for field in EASTER_EGG_FIELDS):
        return True
    policy = str(data.get("easter_egg_policy") or "").strip().lower()
    return policy in {"allow", "allowed", "showcase", "force"}


def media_row_requests_easter_egg(*, target: str, row: dict[str, object] | None) -> bool:
    if not easter_egg_allowed_for_target(target):
        return False
    data = row if isinstance(row, dict) else {}
    contract = data.get("scene_contract") if isinstance(data.get("scene_contract"), dict) else {}
    return scene_contract_requests_easter_egg(contract)


def humor_allowed_for_target(*, target: str, contract: dict[str, object] | None) -> bool:
    data = contract if isinstance(contract, dict) else {}
    policy = str(data.get("humor_policy") or "").strip().lower()
    if policy in {"allow", "allowed", "showcase", "force"}:
        return True
    return str(target or "").replace("\\", "/").strip() in SPARSE_HUMOR_TARGETS


def load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_scene_ledger() -> dict[str, object]:
    loaded = load_json_file(SCENE_LEDGER_OUT)
    assets = loaded.get("assets")
    if not isinstance(assets, list):
        loaded["assets"] = []
    return loaded


def scene_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = ledger.get("assets")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def recent_scene_rows(ledger: dict[str, object], *, limit: int = 8) -> list[dict[str, object]]:
    rows = scene_rows(ledger)
    return rows[-max(1, limit) :]


def scene_rows_for_style_epoch(
    ledger: dict[str, object],
    *,
    style_epoch: dict[str, object] | None,
    allow_fallback: bool = True,
) -> list[dict[str, object]]:
    rows = scene_rows(ledger)
    active = dict(style_epoch or {})
    if not active:
        return rows
    filtered = [
        row
        for row in rows
        if isinstance(row.get("style_epoch"), dict) and dict(row.get("style_epoch") or {}) == active
    ]
    if filtered:
        return filtered
    if allow_fallback:
        return rows
    return []


def infer_cast_signature(contract: dict[str, object]) -> str:
    subject = str(contract.get("subject") or "").lower()
    composition = str(contract.get("composition") or "").lower()
    if any(token in subject for token in ("team", "players", "group", "gm and", "crew", "rest of the table")):
        return "group"
    if any(token in subject for token in ("two", "duo", "operator and", "player and", "gm and")):
        return "duo"
    if composition in {"group_table", "safehouse_table"}:
        return "group"
    return "solo"


def style_epoch_for_overrides(loaded: dict[str, object]) -> dict[str, object]:
    meta = loaded.get("meta")
    if isinstance(meta, dict):
        style = meta.get("style_epoch")
        if isinstance(style, dict):
            return dict(style)
    return {}


def repetition_block_reason(*, target: str, composition: str, ledger: dict[str, object]) -> str:
    recent = recent_scene_rows(ledger)
    lowered = composition.strip().lower()
    if not lowered:
        return ""
    if recent:
        last = str(recent[-1].get("composition") or "").strip().lower()
        if last and last == lowered:
            return f"composition_repeat:last={last}"
    tableish = {"safehouse_table", "group_table"}
    safehouse_like_count = sum(1 for row in recent if str(row.get("composition") or "").strip().lower() in tableish)
    if lowered in tableish and safehouse_like_count >= 2:
        return f"table_monoculture:{safehouse_like_count}"
    if target.endswith("horizons-index.png") and lowered in tableish:
        return "horizons_index_must_be_environment_first"
    if target.endswith("alice.png") and lowered in tableish:
        return "alice_must_not_be_table_scene"
    if target.endswith("jackpoint.png") and lowered in tableish:
        return "jackpoint_should_be_dossier_or_dead_drop"
    return ""


def variation_guardrails_for(*, target: str, rows: list[dict[str, object]]) -> list[str]:
    recent = [
        {
            "target": str(row.get("target") or "").strip(),
            "composition": str(row.get("composition") or "").strip(),
            "subject": str(row.get("subject") or "").strip(),
        }
        for row in rows[-6:]
    ]
    compositions = [entry["composition"] for entry in recent if entry.get("composition")]
    rules = [
        "Do not turn this into a generic meeting tableau or medium-wide leather-jacket huddle.",
        "Prefer a distinct scene family, cast signature, and prop cluster over the most recent accepted banners.",
    ]
    if compositions:
        rules.append(f"Recent composition families already used: {', '.join(compositions)}.")
    if sum(1 for value in compositions if value in {'safehouse_table', 'group_table'}) >= 2:
        rules.append("Table grammar is already overserved; prefer boulevard, solo-operator, over-shoulder proof, dossier, workshop, transit, service-rack, or archive grammar.")
    if target.endswith("horizons-index.png"):
        rules.append("This image must read as a future boulevard or district scene first, not a concept slide.")
    return rules


def ffmpeg_bin() -> str:
    if FFMPEG_BIN and Path(FFMPEG_BIN).exists():
        return FFMPEG_BIN
    raise RuntimeError("ffmpeg_unavailable:ffmpeg executable not found")


def provider_busy_retries() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_RETRIES") or env_value("CHUMMER6_1MIN_BUSY_RETRIES") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


def provider_busy_delay_seconds() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_DELAY_SECONDS") or env_value("CHUMMER6_1MIN_BUSY_DELAY_SECONDS") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


CANON_PARTS = load_part_canon()
CANON_HORIZONS = load_horizon_canon()
LEGACY_PART_SLUGS = {
    "ui": "presentation",
    "mobile": "play",
    "hub": "run-services",
}
HORIZON_MEDIA_FALLBACKS: dict[str, dict[str, object]] = {
    "runsite": {
        "badge": "SITE PACK",
        "kicker": "Spatial truth before the breach starts improvising.",
        "meta": "Status: Horizon Concept // Bounded explorable mission-space artifacts",
        "overlay_hint": "Hotspots, ingress routes, and diegetic location receipts",
        "visual_motifs": [
            "bounded location pack",
            "route overlays",
            "hotspot beacons",
            "museum-grade floor-plan lighting",
            "explorable mission-space context",
        ],
        "overlay_callouts": [
            "Ingress route",
            "Watch angle",
            "Hotspot",
            "Artifact receipt",
        ],
        "scene_contract": {
            "subject": "a runner crew studying an explorable mission-site briefing wall",
            "environment": "a planning room wrapped around a holographic compound map and layered floor plans",
            "action": "tracing ingress paths, chokepoints, and extraction lanes before the breach",
            "metaphor": "mission-space clarity replacing shouted room descriptions",
            "props": ["floor plans", "route overlays", "hotspot markers", "site receipts"],
            "overlays": ["diegetic AR route traces", "hazard markers", "entry labels"],
            "composition": "district_map",
            "palette": "petrol cyan, rust amber, wet concrete neutrals",
            "mood": "focused, spatial, dangerous",
            "humor": "the GM finally gets to stop redrawing the same cursed warehouse on a napkin",
        },
    },
    "runbook-press": {
        "badge": "PRESS ROOM",
        "kicker": "Long-form artifacts without letting vendor dashboards become canon.",
        "meta": "Status: Horizon Concept // Governed long-form publishing lane",
        "overlay_hint": "Editorial receipts, publication manifests, and governed source-pack cues",
        "visual_motifs": [
            "campaign proof sheets",
            "bound source packs",
            "editorial markup",
            "publication manifests",
            "creator desk lighting",
        ],
        "overlay_callouts": [
            "Source pack locked",
            "Editorial approval",
            "Publication manifest",
            "Render-ready proof",
        ],
        "scene_contract": {
            "subject": "a creator-operator assembling a campaign-book proof from governed source packs",
            "environment": "a cramped publishing desk stacked with primers, district drafts, and glowing approval receipts",
            "action": "marking a long-form proof while manifests and citations stay pinned to the spread",
            "metaphor": "creator ambition constrained by governed publication truth",
            "props": ["proof sheets", "bound primers", "approval receipts", "layout boards"],
            "overlays": ["diegetic editorial ticks", "manifest stamps", "citation markers"],
            "composition": "dossier_desk",
            "palette": "rust amber, aged paper cream, petrol cyan monitor spill",
            "mood": "craft-driven, meticulous, slightly sleep-deprived",
            "humor": "the dev discovers publishing is just software scope wearing nicer typography",
        },
    },
}

# Downstream guide visuals must derive from canonical horizon metadata or explicit
# approved overrides. The old bespoke fallback scene map is kept only as dead
# reference during migration and is intentionally disabled at runtime.
HORIZON_MEDIA_FALLBACKS = {}


def provider_order() -> list[str]:
    preferred = ["magixai", "media_factory", "onemin", "browseract_magixai", "browseract_prompting_systems"]
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return list(preferred)
    values = [part.strip().lower().replace("-", "_") for part in raw.split(",") if part.strip()]
    filtered: list[str] = []
    for value in values:
        if value in {"markupgo", "pollinations", "ooda_compositor", "scene_contract_renderer", "local_raster"}:
            continue
        if value not in filtered:
            filtered.append(value)
    return filtered or list(preferred)


def media_factory_render_command() -> list[str]:
    configured = shlex_command("CHUMMER6_MEDIA_FACTORY_RENDER_COMMAND")
    if configured:
        return configured
    if MEDIA_FACTORY_RENDER_SCRIPT.exists():
        return [
            "python3",
            str(MEDIA_FACTORY_RENDER_SCRIPT),
            "--prompt",
            "{prompt}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ]
    return []


def is_credit_exhaustion_message(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        token in lowered
        for token in (
            "insufficient_credits",
            "insufficient credit",
            "insufficient credits",
            "out of credits",
            "not enough credits",
            "credit balance",
            "balance is too low",
            "quota exceeded",
        )
    )


def forbid_legacy_svg_fallback(asset_path: Path) -> None:
    if asset_path.suffix.lower() == ".svg":
        raise RuntimeError(f"legacy_svg_fallback_forbidden:{asset_path}")


def canonical_horizon_visual_contract(slug: str, item: dict[str, object]) -> dict[str, object]:
    title = str(item.get("title") or slug.replace("-", " ").title()).strip()
    hook = " ".join(str(item.get("hook") or "").split()).strip()
    problem = " ".join(str(item.get("problem") or item.get("brutal_truth") or "").split()).strip()
    use_case = " ".join(str(item.get("use_case") or "").split()).strip()
    access_posture = " ".join(str(item.get("access_posture") or "").split()).strip()
    resource_burden = " ".join(str(item.get("resource_burden") or "").split()).strip()
    booster_nudge = " ".join(str(item.get("booster_nudge") or "").split()).strip()
    foundations = [str(entry).strip() for entry in (item.get("foundations") or []) if str(entry).strip()]
    visual_prompt = (
        f"Cinematic cyberpunk concept art for {title}. {use_case or hook or problem} "
        f"Show concrete props tied to {', '.join(foundations[:3]) or 'governed receipts and mission-ready artifacts'}. "
        "No printed text, no logos, no slide-deck framing."
    ).strip()
    subtitle = hook or use_case or problem or title
    visual_motifs = list(dict.fromkeys([*foundations[:4], access_posture, resource_burden]))
    overlay_callouts = list(dict.fromkeys(foundations[:4] or ["Canonical brief", "Bounded move", "Receipt trail"]))
    composition = "single_protagonist"
    if "site" in slug or "runsite" in slug:
        composition = "district_map"
    elif any(token in slug for token in ("press", "jackpoint")):
        composition = "dossier_desk"
    elif any(token in slug for token in ("pulse", "nexus-pan")):
        composition = "solo_operator"
    elif any(token in slug for token in ("forge", "co-processor")):
        composition = "workshop"
    return {
        "badge": f"HORIZON:{slug.upper().replace('-', '_')[:14]}",
        "title": title,
        "subtitle": subtitle,
        "kicker": "Canonical design is ahead of the richer guide packet, so this scene is grounded directly in the current horizon brief.",
        "note": booster_nudge or problem or use_case,
        "meta": "Status: Horizon Concept // Canon-driven visual seed",
        "visual_prompt": visual_prompt,
        "overlay_hint": "Diegetic receipts and bounded operator overlays only.",
        "visual_motifs": visual_motifs,
        "overlay_callouts": overlay_callouts,
        "scene_contract": {
            "subject": f"{title} made concrete in one playable moment",
            "environment": use_case or problem or "bounded table pain becoming visually legible",
            "action": use_case or hook or "show the horizon payoff in one grounded scene",
            "metaphor": hook or problem or "future table relief rendered without fake product certainty",
            "props": foundations[:4],
            "overlays": foundations[:3],
            "composition": composition,
            "palette": "petrol cyan, rust amber, wet charcoal",
            "mood": "grounded, cinematic, specific",
            "humor": "",
        },
    }


def fallback_horizon_media_row(slug: str, item: dict[str, object]) -> dict[str, object]:
    return canonical_horizon_visual_contract(slug, item)


def deep_merge(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return override if override is not None else base


def clause_mentions_easter_egg(text: str) -> bool:
    lowered = " ".join(str(text or "").split()).strip().lower()
    if "troll" not in lowered:
        return False
    return any(token in lowered for token in EASTER_EGG_OBJECT_HINTS)


def strip_easter_egg_clauses(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[,.;])\s+", cleaned)
    kept = [part.strip() for part in parts if part.strip() and not clause_mentions_easter_egg(part)]
    if kept:
        normalized = " ".join(kept)
        normalized = re.sub(r"\s+,", ",", normalized)
        normalized = re.sub(r"\s+\.", ".", normalized)
        normalized = re.sub(r"\s+;", ";", normalized)
        cleaned = normalized.strip(" ,;")
    if clause_mentions_easter_egg(cleaned):
        cleaned = re.sub(
            r",?\s*(?:a|an|the|tiny|small|subtle|hidden|visible|clearly visible)?\s*troll\b[^,.;]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r"\s+\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = cleaned.strip(" ,;")
    return cleaned


def contains_machine_overlay_language(text: str) -> bool:
    lowered = " ".join(str(text or "").split()).strip().lower()
    if not lowered:
        return False
    banned_tokens = (
        "device id",
        "signal strength",
        "ghost-label",
        "ghost label",
        "metadata string",
        "metadata strings",
        "provenance hash",
        "provenance hashes",
        "version receipt",
        "version receipts",
        "verified stamp",
        "verified stamps",
        "compatibility checkmark",
        "compatibility checkmarks",
        "hud style:",
        "id callout",
        "id callouts",
        "link verified",
        "evidence chain",
        "weapon diagnostics",
        "accuracy modifiers",
        "damage modifiers",
        "smartlink electronics",
        "barrel rifling",
        "hardware diagnostics verified",
        "ares predator",
    )
    if any(token in lowered for token in banned_tokens):
        return True
    if re.search(r"\b0x[0-9a-f]+\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+)?%\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+){1,}\b", lowered) and any(ch.isalpha() for ch in lowered):
        return True
    if ("'" in lowered or '"' in lowered) and re.search(r"['\"][A-Z0-9 _-]{3,}['\"]", str(text or "")):
        return True
    return False


def sanitize_visual_prompt_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    kept: list[str] = []
    for part in parts:
        piece = str(part or "").strip()
        if not piece:
            continue
        lowered_piece = piece.lower()
        if any(
            token in lowered_piece
            for token in (
                "no printed text",
                "no readable words",
                "no logo",
                "no logos",
                "no watermark",
            )
        ):
            continue
        if contains_machine_overlay_language(piece):
            continue
        kept.append(piece)
    return " ".join(kept).strip()


def sanitize_overlay_hint_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned or contains_machine_overlay_language(cleaned):
        return ""
    return cleaned


def sanitize_scene_humor(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    lowered = f" {cleaned.lower()} "
    if any(token in lowered for token in META_HUMOR_TOKENS):
        return ""
    if any(token in lowered for token in READABLE_JOKE_TOKENS):
        return ""
    if ("'" in cleaned or '"' in cleaned) and any(
        token in lowered for token in ("sticker", "sign", "placard", "shirt", "patch", "note", "label", "reads", "says")
    ):
        return ""
    if len(cleaned) > 140:
        return ""
    return cleaned


def sanitize_text_list(values: object, *, allow_easter_egg: bool) -> list[str]:
    def looks_like_machine_overlay_phrase(text: str) -> bool:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return False
        if "_" in cleaned:
            return True
        if re.search(r"\b0x[0-9a-f]+\b", cleaned, re.IGNORECASE):
            return True
        if re.search(r"\b\d+(?:\.\d+)?%\b", cleaned):
            return True
        if re.search(r"\b\d+(?:\.\d+){1,}\b", cleaned) and any(ch.isalpha() for ch in cleaned):
            return True
        if (":" in cleaned or "=" in cleaned) and re.search(r"[:=]\s*(?:0x[0-9a-f]+|[A-Z0-9_.%-]{2,}|\d)", cleaned, re.IGNORECASE):
            return True
        words = re.findall(r"[A-Za-z0-9%.-]+", cleaned)
        if words and not any(ch.islower() for ch in cleaned):
            if len(words) >= 2 or any(any(ch.isdigit() for ch in word) for word in words):
                return True
        return False

    if not isinstance(values, list):
        return []
    cleaned_values: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            continue
        if not allow_easter_egg and clause_mentions_easter_egg(text):
            continue
        if looks_like_machine_overlay_phrase(text):
            continue
        cleaned_values.append(text)
    return cleaned_values


def sanitize_scene_contract(*, contract: dict[str, object], target: str) -> dict[str, object]:
    cleaned = copy.deepcopy(contract)
    allow_easter_egg = easter_egg_allowed_for_target(target) and scene_contract_requests_easter_egg(cleaned)
    for key in ("subject", "environment", "action", "metaphor", "palette", "mood"):
        value = " ".join(str(cleaned.get(key) or "").split()).strip()
        if not allow_easter_egg and clause_mentions_easter_egg(value):
            value = strip_easter_egg_clauses(value)
        cleaned[key] = value
    humor = sanitize_scene_humor(cleaned.get("humor"))
    cleaned["humor"] = humor if humor_allowed_for_target(target=target, contract=cleaned) else ""
    cleaned["props"] = sanitize_text_list(cleaned.get("props"), allow_easter_egg=allow_easter_egg)
    cleaned["overlays"] = sanitize_text_list(cleaned.get("overlays"), allow_easter_egg=allow_easter_egg)
    if not allow_easter_egg:
        for field in EASTER_EGG_FIELDS:
            cleaned.pop(field, None)
    return cleaned


def sanitize_media_row(*, target: str, row: dict[str, object]) -> dict[str, object]:
    cleaned = copy.deepcopy(row)
    contract = cleaned.get("scene_contract") if isinstance(cleaned.get("scene_contract"), dict) else {}
    if isinstance(contract, dict):
        cleaned["scene_contract"] = sanitize_scene_contract(contract=contract, target=target)
    allow_easter_egg = media_row_requests_easter_egg(target=target, row=cleaned)
    visual_prompt = " ".join(str(cleaned.get("visual_prompt") or "").split()).strip()
    if visual_prompt and not allow_easter_egg:
        cleaned["visual_prompt"] = strip_easter_egg_clauses(visual_prompt)
    cleaned["visual_prompt"] = sanitize_visual_prompt_text(cleaned.get("visual_prompt")) or str(cleaned.get("visual_prompt") or "").strip()
    cleaned["overlay_hint"] = sanitize_overlay_hint_text(cleaned.get("overlay_hint"))
    cleaned["visual_motifs"] = sanitize_text_list(cleaned.get("visual_motifs"), allow_easter_egg=allow_easter_egg)
    cleaned["overlay_callouts"] = sanitize_text_list(cleaned.get("overlay_callouts"), allow_easter_egg=allow_easter_egg)
    return cleaned


def easter_egg_payload(contract: dict[str, object] | None) -> dict[str, str] | None:
    data = contract if isinstance(contract, dict) else {}
    if not scene_contract_requests_easter_egg(data):
        return None
    return {
        "kind": str(data.get("easter_egg_kind") or "pin").strip(),
        "placement": str(data.get("easter_egg_placement") or "inside the safe crop").strip(),
        "detail": str(
            data.get("easter_egg_detail")
            or "a small recurring Chummer troll motif in the classic horned squat stance"
        ).strip(),
        "visibility": str(
            data.get("easter_egg_visibility")
            or "secondary but clearly visible on a README banner"
        ).strip(),
    }


def load_visual_overrides() -> dict[str, dict[str, object]]:
    if not GUIDE_VISUAL_OVERRIDES.exists():
        return {}
    try:
        loaded = json.loads(GUIDE_VISUAL_OVERRIDES.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for key, value in loaded.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = value
    return normalized


OVERRIDE_PATH = Path("/docker/fleet/state/chummer6/ea_overrides.json")


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    if raw:
        return shlex.split(raw)
    defaults = {
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "prompting_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_humanizer.py"),
            "humanize",
            "--text",
            "{text}",
            "--target",
            "{target}",
        ],
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "magixai_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_PROMPT_REFINER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
    }
    browseract_names = {
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND": (
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND": (
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": (
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND": (
            "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_QUERY",
        ),
    }
    required_workflow_refs = browseract_names.get(env_name)
    if required_workflow_refs and not any(env_value(name) for name in required_workflow_refs):
        return []
    return list(defaults.get(env_name, []))


def url_template(env_name: str) -> str:
    return env_value(env_name)


def load_media_overrides() -> dict[str, object]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        loaded = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def format_command(parts: list[str], *, prompt: str, target: str, output: str, width: int, height: int) -> list[str]:
    return [part.format(prompt=prompt, target=target, output=output, width=width, height=height) for part in parts]


def run_command_provider(name: str, template: list[str], *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            format_command(
                template,
                prompt=prompt,
                target=output_path.stem,
                output=str(output_path),
                width=width,
                height=height,
            ),
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"{name}:command_failed:{detail[:240]}"
    if output_path.exists() and output_path.stat().st_size > 0:
        return True, f"{name}:rendered"
    return False, f"{name}:empty_output"


def run_url_provider(name: str, template: str, *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    url = template.format(
        prompt=urllib.parse.quote(prompt, safe=""),
        width=width,
        height=height,
        output=urllib.parse.quote(str(output_path), safe=""),
    )
    request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-Media/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def run_pollinations_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)
    endpoint = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt, safe="")
    configured = [entry.strip() for entry in env_value("CHUMMER6_POLLINATIONS_MODEL").split(",") if entry.strip()]
    candidates = configured or ["flux", "turbo", "flux-realism"]
    attempts: list[str] = []
    for model in candidates:
        params = {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
            "seed": str(seed),
            "model": model,
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        ok, detail = _download_remote_image(url, output_path=output_path, name=f"pollinations:{model}")
        attempts.append(detail)
        if ok:
            return ok, detail
    return False, " || ".join(attempts)


def _download_remote_image(url: str, *, output_path: Path, name: str) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"EA-Chummer6-{name}/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:image_http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:image_urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:image_empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def run_magixai_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    api_key = env_value("AI_MAGICX_API_KEY")
    if not api_key:
        return False, "magixai:not_configured"
    model_candidates: list[str] = []
    for candidate in (
        env_value("CHUMMER6_MAGIXAI_MODEL"),
        "qwen-image",
        "seedream",
        "nano-banana",
    ):
        normalized_model = str(candidate or "").strip()
        if normalized_model and normalized_model not in model_candidates:
            model_candidates.append(normalized_model)
    size = f"{width}x{height}"
    endpoint_specs = [
        (
            "/api/v1/ai-image/generate",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
        (
            "/ai-image/generate",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
        (
            "/api/v1/images/generations",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "response_format": "url",
                "n": 1,
            },
        ),
        (
            "/images/generations",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "response_format": "url",
                "n": 1,
            },
        ),
        (
            "/v1/images/generations",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "response_format": "url",
                "n": 1,
            },
        ),
        (
            "/v1/ai-image/generate",
            {
                "model": "{model}",
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
        (
            "/api/v1/ai-image/generate",
            {
                "model": "{model}",
                "prompt": prompt,
                "image_size": size,
                "num_images": 1,
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
    ]
    configured_base = env_value("CHUMMER6_MAGIXAI_BASE_URL") or "https://beta.aimagicx.com/api/v1"
    base_urls: list[str] = []
    for candidate in (
        configured_base,
        "https://beta.aimagicx.com/api/v1",
        "https://beta.aimagicx.com/api",
        "https://beta.aimagicx.com/v1",
        "https://beta.aimagicx.com",
        "https://api.aimagicx.com/api/v1",
        "https://api.aimagicx.com/api",
        "https://api.aimagicx.com",
        "https://api.aimagicx.com/v1",
        "https://www.aimagicx.com/api/v1",
        "https://www.aimagicx.com/api",
        "https://www.aimagicx.com/v1",
        "https://www.aimagicx.com",
    ):
        normalized = str(candidate or "").strip().rstrip("/")
        if not normalized or normalized in base_urls:
            continue
        base_urls.append(normalized)
    def build_url(base_url: str, endpoint: str) -> str:
        clean_base = base_url.rstrip("/")
        clean_endpoint = endpoint.lstrip("/")
        if clean_base.endswith("/api/v1") and clean_endpoint.startswith("api/v1/"):
            clean_endpoint = clean_endpoint[len("api/v1/") :]
        elif clean_base.endswith("/api") and clean_endpoint.startswith("api/"):
            clean_endpoint = clean_endpoint[len("api/") :]
        return clean_base + "/" + clean_endpoint
    header_variants = [
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "API-KEY": api_key,
        },
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "X-MGX-API-KEY": api_key,
        },
    ]
    errors: list[str] = []
    seen_requests: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for base_url in base_urls:
        for model in model_candidates:
            for endpoint, payload_template in endpoint_specs:
                payload = json.loads(json.dumps(payload_template).replace('"{model}"', json.dumps(model)))
                url = build_url(base_url, endpoint)
                payload_json = json.dumps(payload, sort_keys=True)
                for headers in header_variants:
                    header_key = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
                    request_key = (url, header_key, payload_json)
                    if request_key in seen_requests:
                        continue
                    seen_requests.add(request_key)
                    request = urllib.request.Request(
                        url,
                        headers=headers,
                        data=payload_json.encode("utf-8"),
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=45) as response:
                            data = response.read()
                            content_type = str(response.headers.get("Content-Type") or "").lower()
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode("utf-8", errors="replace").strip()
                        if is_credit_exhaustion_message(body):
                            return False, f"magixai:insufficient_credits:http_{exc.code}:{body[:180]}"
                        errors.append(f"{url}:{model}:http_{exc.code}:{body[:180]}")
                        continue
                    except urllib.error.URLError as exc:
                        errors.append(f"{url}:{model}:urlerror:{exc.reason}")
                        continue
                    if data:
                        if content_type.startswith("image/"):
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(data)
                            return True, "magixai:rendered"
                        decoded = data.decode("utf-8", errors="replace").strip()
                        if decoded.startswith("http://") or decoded.startswith("https://"):
                            ok, detail = _download_remote_image(decoded, output_path=output_path, name="magixai")
                            if ok:
                                return ok, detail
                            errors.append(detail)
                            continue
                        try:
                            body = json.loads(decoded)
                        except Exception:
                            errors.append(f"{url}:{model}:non_json_response:{decoded[:180]}")
                            continue
                    candidates: list[str] = []
                    if isinstance(body, dict):
                        for field in ("url", "image_url"):
                            value = str(body.get(field) or "").strip()
                            if value:
                                candidates.append(value)
                        data_rows = body.get("data")
                        if isinstance(data_rows, list):
                            for entry in data_rows:
                                if not isinstance(entry, dict):
                                    continue
                                value = str(entry.get("url") or entry.get("image_url") or "").strip()
                                if value:
                                    candidates.append(value)
                        output_rows = body.get("output")
                        if isinstance(output_rows, list):
                            for entry in output_rows:
                                if not isinstance(entry, dict):
                                    continue
                                value = str(entry.get("url") or entry.get("image_url") or "").strip()
                                if value:
                                    candidates.append(value)
                    for candidate in candidates:
                        ok, detail = _download_remote_image(candidate, output_path=output_path, name="magixai")
                        if ok:
                            return ok, detail
                        errors.append(detail)
    return False, "magixai:" + " || ".join(errors[:6])


def resolve_onemin_image_keys() -> list[str]:
    script_path = EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh"
    keys: list[str] = []
    seen: set[str] = set()
    if script_path.exists():
        try:
            output = subprocess.check_output(
                ["bash", str(script_path), "--all"],
                text=True,
            )
        except Exception:
            output = ""
        for raw in output.splitlines():
            key = str(raw or "").strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    fallback_env_names = sorted(
        (
            env_name
            for env_name in os.environ
            if re.fullmatch(r"ONEMIN_AI_API_KEY_FALLBACK_(\d+)", env_name)
        ),
        key=lambda env_name: int(env_name.rsplit("_", 1)[-1]),
    )
    for env_name in ("ONEMIN_AI_API_KEY", *fallback_env_names):
        key = env_value(env_name)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    if str(env_value("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS") or "1").strip().lower() in {"0", "false", "no", "off"}:
        primary = keys[:1]
        if primary:
            return primary
    return keys


def _collect_image_candidates(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        candidate = str(value or "").strip()
        lowered = candidate.lower()
        if (" " in candidate) or ("\n" in candidate) or ("\t" in candidate):
            return found
        if candidate.startswith("http://") or candidate.startswith("https://"):
            found.append(candidate)
        elif candidate.startswith("/") and re.search(r"\.(png|jpg|jpeg|webp|gif)(\?|$)", lowered):
            found.append("https://api.1min.ai" + candidate)
        elif (
            ("/" in candidate or "." in candidate)
            and any(token in lowered for token in ("/asset/", "/image/", "/render/", "/download/", ".png", ".jpg", ".jpeg", ".webp", ".gif"))
            and re.search(r"\.(png|jpg|jpeg|webp|gif)(\?|$)", lowered)
        ):
            found.append("https://api.1min.ai/" + candidate.lstrip("/"))
        return found
    if isinstance(value, dict):
        prioritized_fields = ("url", "image_url", "download_url", "image", "imageUrl", "image_url_path")
        for field in prioritized_fields:
            if field in value:
                found.extend(_collect_image_candidates(value.get(field)))
        for nested in value.values():
            found.extend(_collect_image_candidates(nested))
        return found
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            found.extend(_collect_image_candidates(nested))
    return found


def onemin_model_candidates() -> list[str]:
    candidates: list[str] = []
    for candidate in (
        env_value("CHUMMER6_ONEMIN_MODEL"),
        "gpt-image-1-mini",
        "gpt-image-1",
        "dall-e-3",
    ):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def onemin_size_candidates(model: str, *, width: int, height: int) -> list[str]:
    configured = str(env_value("CHUMMER6_ONEMIN_IMAGE_SIZE") or "").strip()
    if configured:
        return [configured]
    normalized = str(model or "").strip().lower()
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        return ["auto", "1024x1024", "1024x1536", "1536x1024"]
    return [f"{width}x{height}", "1024x1024", "auto"]


def onemin_aspect_ratio(width: int, height: int) -> str:
    try:
        w = max(1, int(width))
        h = max(1, int(height))
    except Exception:
        return "16:9"
    known = [
        (16, 9),
        (4, 3),
        (3, 2),
        (1, 1),
        (9, 16),
        (2, 3),
        (3, 4),
        (21, 9),
    ]
    ratio = w / h
    best = min(known, key=lambda pair: abs((pair[0] / pair[1]) - ratio))
    return f"{best[0]}:{best[1]}"


def onemin_request_timeout_seconds(model: str) -> int:
    raw = env_value("CHUMMER6_ONEMIN_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(30, int(raw))
        except Exception:
            pass
    normalized = str(model or "").strip().lower()
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        return 150
    return 45


def onemin_payloads(model: str, *, prompt: str, width: int, height: int) -> list[dict[str, object]]:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        payloads: list[dict[str, object]] = []
        for size in onemin_size_candidates(model, width=width, height=height):
            prompt_object = {
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": env_value("CHUMMER6_ONEMIN_IMAGE_QUALITY") or "low",
                "style": "natural",
                "output_format": "png",
                "background": "opaque",
            }
            payloads.append(
                {
                    "type": "IMAGE_GENERATOR",
                    "model": model,
                    "promptObject": dict(prompt_object),
                }
            )
        return payloads
    aspect_ratio = env_value("CHUMMER6_ONEMIN_ASPECT_RATIO") or onemin_aspect_ratio(width, height)
    render_mode = env_value("CHUMMER6_ONEMIN_MODE") or "relax"
    base_prompt_object = {
        "prompt": prompt,
        "n": 1,
        "num_outputs": 1,
        "aspect_ratio": aspect_ratio,
        "mode": render_mode,
    }
    payloads = [
        {
            "type": "IMAGE_GENERATOR",
            "model": model,
            "promptObject": dict(base_prompt_object),
        }
    ]
    style = str(env_value("CHUMMER6_ONEMIN_IMAGE_STYLE") or "").strip()
    if style:
        with_style = dict(base_prompt_object)
        with_style["style"] = style
        payloads.append(
            {
                "type": "IMAGE_GENERATOR",
                "model": model,
                "promptObject": with_style,
            }
        )
    return payloads


def run_onemin_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    keys = resolve_onemin_image_keys()
    if not keys:
        return False, "onemin:not_configured"
    model_candidates = onemin_model_candidates()
    endpoints = [
        env_value("CHUMMER6_ONEMIN_ENDPOINT") or "https://api.1min.ai/api/features",
    ]
    errors: list[str] = []
    header_variants = []
    for key in keys:
        header_variants.append(
            {
                "User-Agent": "EA-Chummer6-1min/1.0",
                "Content-Type": "application/json",
                "API-KEY": key,
            }
        )
    seen_requests: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for url in endpoints:
        for model in model_candidates:
            payloads = onemin_payloads(model, prompt=prompt, width=width, height=height)
            timeout_seconds = onemin_request_timeout_seconds(model)
            for payload in payloads:
                prompt_object = payload.get("promptObject") if isinstance(payload, dict) else {}
                size_label = str(
                    (
                        prompt_object.get("size")
                        if isinstance(prompt_object, dict)
                        else ""
                    )
                    or (
                        prompt_object.get("aspect_ratio")
                        if isinstance(prompt_object, dict)
                        else ""
                    )
                    or "auto"
                ).strip()
                payload_json = json.dumps(payload, sort_keys=True)
                for headers in header_variants:
                    header_key = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
                    request_key = (url, header_key, payload_json)
                    if request_key in seen_requests:
                        continue
                    seen_requests.add(request_key)
                    request = urllib.request.Request(
                        url,
                        headers=headers,
                        data=payload_json.encode("utf-8"),
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                            data = response.read()
                            content_type = str(response.headers.get("Content-Type") or "").lower()
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode("utf-8", errors="replace").strip()
                        invalid_size = "Invalid value:" in body and "Supported values are:" in body
                        retryable_busy = exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body and not invalid_size
                        if retryable_busy:
                            busy_recovered = False
                            for _attempt in range(provider_busy_retries()):
                                time.sleep(provider_busy_delay_seconds())
                                try:
                                    request = urllib.request.Request(
                                        url,
                                        headers=headers,
                                        data=payload_json.encode("utf-8"),
                                        method="POST",
                                    )
                                    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                                        data = response.read()
                                        content_type = str(response.headers.get("Content-Type") or "").lower()
                                        busy_recovered = True
                                        break
                                except urllib.error.HTTPError as retry_exc:
                                    body = retry_exc.read().decode("utf-8", errors="replace").strip()
                                    invalid_size = "Invalid value:" in body and "Supported values are:" in body
                                    retryable_busy = retry_exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body and not invalid_size
                                    if not retryable_busy:
                                        errors.append(f"{url}:{model}:{size_label}:http_{retry_exc.code}:{body[:180]}")
                                        break
                                except urllib.error.URLError as retry_url_exc:
                                    errors.append(f"{url}:{model}:{size_label}:urlerror:{retry_url_exc.reason}")
                                    break
                                except TimeoutError:
                                    errors.append(f"{url}:{model}:{size_label}:timeout")
                                    break
                            if not busy_recovered:
                                if retryable_busy:
                                    errors.append(f"{url}:{model}:{size_label}:openai_busy")
                                continue
                        else:
                            errors.append(f"{url}:{model}:{size_label}:http_{exc.code}:{body[:180]}")
                            continue
                    except urllib.error.URLError as exc:
                        errors.append(f"{url}:{model}:{size_label}:urlerror:{exc.reason}")
                        continue
                    except TimeoutError:
                        errors.append(f"{url}:{model}:{size_label}:timeout")
                        continue
                    if data:
                        if content_type.startswith("image/"):
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(data)
                            return True, "onemin:rendered"
                        decoded = data.decode("utf-8", errors="replace").strip()
                        if decoded.startswith("http://") or decoded.startswith("https://"):
                            ok, detail = _download_remote_image(decoded, output_path=output_path, name="onemin")
                            if ok:
                                return ok, detail
                            errors.append(detail)
                            continue
                        try:
                            body = json.loads(decoded)
                        except Exception:
                            errors.append(f"{url}:{model}:{size_label}:non_json_response:{decoded[:180]}")
                            continue
                        for candidate in _collect_image_candidates(body):
                            ok, detail = _download_remote_image(candidate, output_path=output_path, name="onemin")
                            if ok:
                                return ok, detail
                            errors.append(detail)
    return False, "onemin:" + " || ".join(errors[:6])


def palette_for(prompt: str) -> tuple[str, str]:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return PALETTES[int(digest[:2], 16) % len(PALETTES)]


def _font_path(bold: bool = False) -> str:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return path


def _write_text_file(directory: Path, name: str, value: str, *, width: int) -> Path:
    wrapped = textwrap.fill(" ".join(str(value or "").split()).strip(), width=width)
    path = directory / name
    path.write_text(wrapped + "\n", encoding="utf-8")
    return path


def _ffmpeg_path(value: Path) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def refine_prompt_local(prompt: str, *, target: str) -> str:
    return " ".join(prompt.split()).strip()


def prompt_refinement_required() -> bool:
    raw = env_value("CHUMMER6_PROMPT_REFINEMENT_REQUIRED")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def prompt_refinement_attempts_enabled() -> bool:
    explicit_env_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPT_REFINER_COMMAND",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPT_REFINER_URL_TEMPLATE",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID",
    ]
    return any(env_value(name) for name in explicit_env_names)


def prompt_refinement_timeout_seconds() -> int:
    raw = env_value("CHUMMER6_PROMPT_REFINEMENT_TIMEOUT_SECONDS") or "25"
    try:
        return max(5, int(raw))
    except Exception:
        return 25


def troll_postpass_enabled() -> bool:
    raw = env_value("CHUMMER6_TROLL_POSTPASS")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def refine_prompt_with_ooda(*, prompt: str, target: str) -> str:
    # OODA-authored visual_prompt is the required source of truth.
    # External prompt refinement is an optional enhancer by default and should
    # only block publishing when explicitly marked required.
    base_prompt = refine_prompt_local(prompt, target=target)
    command_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPT_REFINER_COMMAND",
    ]
    template_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPT_REFINER_URL_TEMPLATE",
    ]
    attempted: list[str] = []
    external_expected = prompt_refinement_attempts_enabled()
    refinement_required = prompt_refinement_required()
    if not external_expected and not refinement_required:
        return base_prompt
    for env_name in command_names:
        command = shlex_command(env_name)
        if not command:
            continue
        try:
            completed = subprocess.run(
                [part.format(prompt=base_prompt, target=target) for part in command],
                check=True,
                text=True,
                capture_output=True,
                timeout=prompt_refinement_timeout_seconds(),
            )
            refined = (completed.stdout or "").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    for env_name in template_names:
        template = url_template(env_name)
        if not template:
            continue
        url = template.format(
            prompt=urllib.parse.quote(base_prompt, safe=""),
            target=urllib.parse.quote(target, safe=""),
        )
        request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-PromptRefiner/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                refined = response.read().decode("utf-8", errors="replace").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    if external_expected and refinement_required:
        detail = " || ".join(attempted) if attempted else "no_external_refiner_succeeded"
        raise RuntimeError(f"prompt_refinement_failed:{detail}")
    return base_prompt


def sanitize_prompt_for_provider(prompt: str, *, provider: str) -> str:
    cleaned = " ".join(str(prompt or "").split()).strip()
    if not cleaned:
        return cleaned
    provider_name = str(provider or "").strip().lower()
    if provider_name in {"onemin", "1min", "1min.ai", "oneminai"}:
        replacements = {
            "Shadowrun": "cyberpunk tabletop",
            "shadowrun": "cyberpunk tabletop",
            "runner": "operative",
            "runners": "operatives",
            "dangerous": "tense",
            "combat": "tactical simulation",
            "crash-test dummy": "test mannequin",
            "crash test dummy": "test mannequin",
            "weapon": "gear",
            "weapons": "gear",
            "gun": "tool",
            "guns": "tools",
            "blood": "stress",
            "gore": "damage",
        }
        for src, dst in replacements.items():
            cleaned = cleaned.replace(src, dst)
        cleaned += " Safe-for-work, nonviolent, no gore, no weapons, no explicit danger."
    return cleaned


def easter_egg_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "pin").strip()
    placement = str(data.get("easter_egg_placement") or "as a small in-world detail inside the safe crop").strip()
    detail = str(
        data.get("easter_egg_detail")
        or "a small recurring Chummer troll motif in the classic horned squat stance"
    ).strip()
    visibility = str(
        data.get("easter_egg_visibility")
        or "secondary but clearly visible on a README banner"
    ).strip()
    return (
        f"Include one small diegetic Chummer troll motif as a {kind}, placed {placement}. "
        f"Detail: {detail}. Keep it {visibility}. "
        "Do not center it, do not crop it out, and do not turn it into the main subject."
    )


def easter_egg_instruction_set(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "small prop").strip()
    placement = str(data.get("easter_egg_placement") or "inside the safe crop").strip()
    detail = str(
        data.get("easter_egg_detail")
        or "a troll in the classic Chummer horned squat stance"
    ).strip()
    return (
        "Secondary art direction for the same image: integrate one small troll easter egg seamlessly into the scene. "
        f"Make it a real {kind} placed {placement}. "
        f"Use this specific motif: {detail}. "
        "It must share the scene lighting, material, texture, and perspective so it feels native to the world. "
        "Do not render it as a pasted logo, floating UI symbol, watermark, or random face decal."
    )


def composition_visual_guardrails(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition in {"city_edge", "street_front", "horizon_boulevard", "district_map", "transit_checkpoint"}:
        return (
            "Street and transit clues must use pictograms, arrows, mascot art, crossed-out symbols, color lanes, "
            "and physical landmarks instead of readable signs, posters, or neon words."
        )
    if composition in {
        "safehouse_table",
        "group_table",
        "over_shoulder_receipt",
        "solo_operator",
        "service_rack",
        "desk_still_life",
        "dossier_desk",
        "archive_room",
        "workshop",
        "workshop_bench",
        "simulation_lab",
        "rule_xray",
        "passport_gate",
        "mirror_split",
        "loadout_table",
        "forensic_replay",
        "conspiracy_wall",
    }:
        return (
            "Keep papers, dossiers, screens, labels, and forms unreadable, edge-on, cropped, or replaced by chips, "
            "stamps, traces, tokens, light bars, and body language."
        )
    return "Use objects, symbols, and lighting to explain the moment before any readable text would."


def smartlink_overlay_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition in {
        "over_shoulder_receipt",
        "transit_checkpoint",
        "district_map",
        "forensic_replay",
        "passport_gate",
        "rule_xray",
        "conspiracy_wall",
    }:
        return (
            "Diegetic smartlink assessment is welcome: use nonverbal threat posture cues, line-of-fire brackets, "
            "cover confidence arcs, ingress cones, watch-angle silhouettes, or target-priority ghosts as in-world overlays. "
            "Keep them symbolic and cinematic, never readable or numeric."
        )
    if composition in {"solo_operator", "service_rack", "simulation_lab", "mirror_split", "workshop_bench", "dossier_desk"}:
        return (
            "Light tactical AR is welcome: suggest posture checks, signal integrity halos, danger weighting, or consequence ghosts "
            "through pictograms, brackets, and soft traces instead of readable HUD text."
        )
    return ""


def lore_background_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition in {"street_front", "city_edge", "horizon_boulevard", "transit_checkpoint", "district_map"}:
        return (
            "A Shadowrun-lore background nod is welcome if the surface exists for it: dragon-warning graffiti energy, "
            "crossed-out draconic pictograms, extraction arrows, or half-scrubbed alley scrawl in the distance. "
            "Keep it secondary, weathered, and never clean readable typography."
        )
    if composition in {"dossier_desk", "workshop_bench", "simulation_lab", "solo_operator"}:
        return (
            "A scratched anti-dragon sigil, runner superstition sticker, talismonger ward mark, or dog-eared bounty card "
            "can live in the background as secondary lore texture. Keep it subtle and never render it as crisp readable text."
        )
    return ""


def scene_integrity_instruction_set(contract: dict[str, object] | None, *, target: str) -> str:
    _ = target
    return (
        "Secondary art direction for the same image: keep it as a lived moment, not a poster or title card. "
        "Show one focal action, one readable prop cluster, and one secondary story clue. "
        f"{composition_visual_guardrails(contract)} "
        "Avoid centered brochure posing, fake readable typography, and generic wallpaper composition."
    )


def easter_egg_stub(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "pin").strip()
    placement = str(data.get("easter_egg_placement") or "inside the safe crop").strip()
    return f"subtle diegetic troll motif as {kind} {placement}"


def short_easter_egg_stub(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = compact_text(data.get("easter_egg_kind") or "pin", limit=18)
    placement = compact_text(data.get("easter_egg_placement") or "inside the safe crop", limit=64)
    return f"Troll motif: {kind} {placement}."


def compact_easter_egg_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = compact_text(data.get("easter_egg_kind") or "small troll motif", limit=36)
    placement = compact_text(data.get("easter_egg_placement") or "inside the safe crop", limit=90)
    detail = compact_text(
        data.get("easter_egg_detail") or "classic horned Chummer troll silhouette",
        limit=96,
    )
    visibility = compact_text(data.get("easter_egg_visibility") or "clearly visible on the banner", limit=72)
    return (
        f"Troll motif: {kind} at {placement}. "
        f"Detail: {detail}. "
        f"Keep it {visibility}."
    )


def troll_mark_tint(kind: str) -> str:
    lowered = str(kind or "").strip().lower()
    if any(token in lowered for token in ("brass", "gold", "pin")):
        return "#d8ab49"
    if any(token in lowered for token in ("red", "wax", "seal")):
        return "#e76a53"
    if "blue" in lowered:
        return "#4cc0ff"
    if any(token in lowered for token in ("crt", "screen", "green", "ad")):
        return "#61e7a3"
    return "#f2f1e8"


def hex_rgb(value: str) -> tuple[int, int, int]:
    clean = str(value or "").strip().lstrip("#")
    if len(clean) != 6:
        raise ValueError(f"invalid_hex_color:{value}")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def troll_overlay_defaults(*, composition: str, width: int, height: int, kind: str) -> dict[str, object]:
    base_positions = {
        "safehouse_table": (0.46, 0.82),
        "group_table": (0.50, 0.82),
        "desk_still_life": (0.15, 0.80),
        "dossier_desk": (0.20, 0.79),
        "archive_room": (0.14, 0.68),
        "workshop": (0.74, 0.22),
        "district_map": (0.18, 0.78),
        "horizon_boulevard": (0.79, 0.18),
        "city_edge": (0.78, 0.21),
        "street_front": (0.78, 0.21),
        "simulation_lab": (0.14, 0.72),
        "rule_xray": (0.42, 0.82),
        "passport_gate": (0.15, 0.71),
        "mirror_split": (0.48, 0.82),
        "loadout_table": (0.75, 0.74),
        "forensic_replay": (0.78, 0.72),
        "conspiracy_wall": (0.77, 0.33),
    }
    lowered_kind = str(kind or "").strip().lower()
    scale = max(0.75, min(width / 960.0, height / 540.0))
    size = int(34 * scale)
    alpha = 0.86
    rotate = 0.0
    if "sticker" in lowered_kind:
        alpha = 0.78
        rotate = -6.0
    elif any(token in lowered_kind for token in ("stamp", "wax", "seal")):
        alpha = 0.58
        rotate = -4.0
    elif any(token in lowered_kind for token in ("crt", "screen", "ad")):
        alpha = 0.52
    elif "figurine" in lowered_kind:
        alpha = 0.90
        size = int(40 * scale)
    x_ratio, y_ratio = base_positions.get(composition, (0.12, 0.78))
    return {
        "x": int(width * x_ratio),
        "y": int(height * y_ratio),
        "w": size,
        "h": size,
        "alpha": alpha,
        "shadow_alpha": min(0.42, alpha * 0.38),
        "rotate": rotate,
        "tint": troll_mark_tint(kind),
    }


def troll_postpass_settings(*, spec: dict[str, object], width: int, height: int) -> dict[str, object]:
    row = spec.get("media_row") if isinstance(spec, dict) and isinstance(spec.get("media_row"), dict) else {}
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    kind = str(contract.get("easter_egg_kind") or "troll mark").strip()
    composition = str(contract.get("composition") or "").strip()
    settings = troll_overlay_defaults(composition=composition, width=width, height=height, kind=kind)
    override = contract.get("troll_postpass") if isinstance(contract.get("troll_postpass"), dict) else {}
    for key in ("x", "y", "w", "h", "alpha", "shadow_alpha", "rotate", "tint"):
        if key in override and override[key] not in (None, ""):
            settings[key] = override[key]
    return settings


def apply_troll_postpass(*, image_path: Path, spec: dict[str, object], width: int, height: int) -> str:
    if not image_path.exists():
        raise RuntimeError(f"troll_postpass:missing_image:{image_path}")
    if not TROLL_MARK_PATH.exists():
        raise RuntimeError(f"troll_postpass:missing_mark:{TROLL_MARK_PATH}")
    settings = troll_postpass_settings(spec=spec, width=width, height=height)
    tint = str(settings.get("tint") or "#f2f1e8").strip()
    red, green, blue = hex_rgb(tint)
    rg = max(0.0, min(1.0, red / 255.0))
    gg = max(0.0, min(1.0, green / 255.0))
    bg = max(0.0, min(1.0, blue / 255.0))
    alpha = max(0.15, min(1.0, float(settings.get("alpha") or 0.82)))
    shadow_alpha = max(0.08, min(0.6, float(settings.get("shadow_alpha") or 0.28)))
    rotate = float(settings.get("rotate") or 0.0)
    width_px = max(18, int(settings.get("w") or 32))
    height_px = max(18, int(settings.get("h") or 32))
    x = max(0, int(settings.get("x") or 0))
    y = max(0, int(settings.get("y") or 0))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    filter_graph = (
        f"[1:v]scale={width_px}:{height_px},format=rgba,"
        f"colorchannelmixer=rr=0:rg={rg:.3f}:rb=0:gr=0:gg={gg:.3f}:gb=0:br=0:bg={bg:.3f}:bb=0:aa={alpha:.3f},"
        f"rotate={rotate:.3f}*PI/180:ow=rotw(iw):oh=roth(ih):c=none[logo];"
        f"[logo]split[logo_main][logo_shadow];"
        f"[logo_shadow]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_alpha:.3f},boxblur=2:1[shadow];"
        f"[0:v][shadow]overlay={x + 2}:{y + 2}[bg];"
        f"[bg][logo_main]overlay={x}:{y}:format=auto"
    )
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-i",
                str(image_path),
                "-i",
                str(TROLL_MARK_PATH),
                "-filter_complex",
                filter_graph,
                "-frames:v",
                "1",
                str(temp_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_path.replace(image_path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"troll_postpass:ffmpeg_failed:{detail[:240]}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
    return f"troll_postpass:applied:{x}:{y}:{width_px}x{height_px}"


def normalize_banner_size(*, image_path: Path, width: int, height: int) -> str:
    if not image_path.exists():
        raise RuntimeError(f"normalize_banner_size:missing_image:{image_path}")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-i",
                str(image_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                "-frames:v",
                "1",
                str(temp_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_path.replace(image_path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"normalize_banner_size:ffmpeg_failed:{detail[:240]}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
    return f"normalize_banner_size:applied:{width}x{height}"


def ensure_troll_clause(*, prompt: str, spec: dict[str, object]) -> str:
    cleaned = " ".join(str(prompt or "").split()).strip()
    if not cleaned:
        return cleaned
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) and isinstance(row.get("scene_contract"), dict) else {}
    target = str(spec.get("target") or "").strip()
    lowered = cleaned.lower()
    additions: list[str] = []
    if "keep it as a lived moment, not a poster or title card" not in lowered:
        additions.append(scene_integrity_instruction_set(contract, target=target))
    if (
        media_row_requests_easter_egg(target=target, row=row)
        and "chummer troll motif" not in lowered
        and "diegetic troll motif" not in lowered
        and "horned squat stance" not in lowered
    ):
        additions.append(easter_egg_clause(contract))
        additions.append(easter_egg_instruction_set(contract))
    if not additions:
        return cleaned
    return f"{cleaned} {' '.join(additions)}".strip()


def compact_text(value: object, *, limit: int = 120) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return ""
    for splitter in (". ", "! ", "? "):
        head, sep, _tail = cleaned.partition(splitter)
        if sep and head.strip():
            cleaned = head.strip()
            break
    return cleaned[:limit].rstrip(" ,;:-")


def compact_items(values: object, *, limit: int = 3, item_limit: int = 48) -> str:
    if not isinstance(values, (list, tuple)):
        return ""
    cleaned = [compact_text(entry, limit=item_limit) for entry in values]
    items = [entry for entry in cleaned if entry][:limit]
    return ", ".join(items)


def build_safe_pollinations_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    if not isinstance(contract, dict):
        cleaned = " ".join(str(prompt or "").split()).strip()
        return cleaned[:220]
    subject = str(contract.get("subject") or "a cyberpunk protagonist").strip()
    environment = str(contract.get("environment") or "a neon-lit cyberpunk setting").strip()
    action = str(contract.get("action") or "holding the moment together").strip()
    metaphor = str(contract.get("metaphor") or "").strip()
    palette = str(contract.get("palette") or "rainy neon cyan and magenta").strip()
    mood = str(contract.get("mood") or "tense but inviting").strip()
    smartlink = compact_text(smartlink_overlay_clause(contract), limit=88)
    lore = compact_text(lore_background_clause(contract), limit=72)
    parts = [
        "Grounded cinematic cyberpunk scene still",
        subject,
        f"in {environment}",
        action,
        metaphor if metaphor else "",
        mood,
        palette,
        "one focal subject",
        smartlink if smartlink else "",
        lore if lore else "",
        easter_egg_stub(contract) if scene_contract_requests_easter_egg(contract) else "",
        "no readable text no watermark 16:9",
    ]
    return ", ".join(part for part in parts if part)[:240]


def build_safe_onemin_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    if not isinstance(contract, dict):
        return sanitize_prompt_for_provider(prompt, provider="onemin")
    visual_prompt = compact_text(row.get("visual_prompt") or contract.get("visual_prompt") or prompt, limit=220)
    subject = compact_text(contract.get("subject") or "a cyberpunk protagonist", limit=90)
    environment = compact_text(contract.get("environment") or "a neon-lit cyberpunk setting", limit=90)
    action = compact_text(contract.get("action") or "holding the moment together", limit=110)
    metaphor = compact_text(contract.get("metaphor") or "", limit=60)
    composition = compact_text(contract.get("composition") or "single_protagonist", limit=32)
    mood = compact_text(contract.get("mood") or "focused", limit=72)
    props = compact_items(contract.get("props"), limit=4, item_limit=32)
    motifs = compact_items((row.get("visual_motifs") or []), limit=4, item_limit=36)
    guardrail = compact_text(composition_visual_guardrails(contract), limit=156)
    smartlink = compact_text(smartlink_overlay_clause(contract), limit=172)
    lore = compact_text(lore_background_clause(contract), limit=156)
    parts = [
        "Grounded cinematic cyberpunk scene still.",
        visual_prompt,
        compact_easter_egg_clause(contract) if scene_contract_requests_easter_egg(contract) else "",
        f"Focus on {subject}." if subject else "",
        f"Scene: {environment}." if environment else "",
        f"Moment: {action}." if action else "",
        f"Metaphor: {metaphor}." if metaphor else "",
        f"Composition: {composition}." if composition else "",
        f"Mood: {mood}." if mood else "",
        f"Smartlink: {smartlink}." if smartlink else "",
        f"Lore detail: {lore}." if lore else "",
        f"Props: {props}." if props else "",
        f"Motifs: {motifs}." if motifs else "",
        f"Guardrail: {guardrail}." if guardrail else "",
        "Real table, street, lab, archive, desk, or workshop scene. Not abstract infographic. Not product poster.",
        "No readable words or numbers anywhere. Use pictograms, bars, chips, glyphs, traces, stamps, and silhouette icons instead.",
        "No watermark. 16:9.",
    ]
    compact_prompt = " ".join(part for part in parts if part)
    return sanitize_prompt_for_provider(compact_prompt[:680], provider="onemin")


def _overlay_family(row: dict[str, object], spec: dict[str, object]) -> str:
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    tokens = " ".join(
        [
            str(spec.get("target") or ""),
            str(row.get("overlay_hint") or ""),
            " ".join(str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip()),
            str(contract.get("metaphor") or ""),
            str(contract.get("composition") or ""),
        ]
    ).lower()
    if any(token in tokens for token in ("x-ray", "xray", "modifier", "causality", "receipt trace")):
        return "xray"
    if any(token in tokens for token in ("replay", "seed", "timeline", "sim", "simulation")):
        return "replay"
    if any(token in tokens for token in ("dossier", "evidence", "briefing", "jackpoint")):
        return "dossier"
    if any(token in tokens for token in ("heat", "web", "network", "conspiracy")):
        return "network"
    if any(token in tokens for token in ("passport", "border", "compatibility")):
        return "passport"
    if any(token in tokens for token in ("forge", "anvil", "rules shard")):
        return "forge"
    return "hud"


def _ffmpeg_color(value: str, alpha: float) -> str:
    normalized = str(value or "#34d399").strip()
    if normalized.startswith("#"):
        normalized = "0x" + normalized[1:]
    return f"{normalized}@{alpha:.2f}"


def _overlay_filter_for(*, family: str, accent: str, glow: str, width: int, height: int) -> str:
    accent_soft = _ffmpeg_color(accent, 0.12)
    accent_hard = _ffmpeg_color(accent, 0.24)
    glow_soft = _ffmpeg_color(glow, 0.10)
    left_box = f"drawbox=x=24:y=24:w={max(180, width // 5)}:h={max(44, height // 9)}:color={accent_soft}:t=fill"
    bottom_strip = f"drawbox=x=24:y={max(24, height - 92)}:w={max(220, width // 2)}:h=56:color={glow_soft}:t=fill"
    corner_a = f"drawbox=x=18:y=18:w={max(140, width // 6)}:h=3:color={accent_hard}:t=fill"
    corner_b = f"drawbox=x=18:y=18:w=3:h={max(96, height // 6)}:color={accent_hard}:t=fill"
    if family == "xray":
        return ",".join(
            [
                f"drawgrid=w={max(48, width // 16)}:h={max(48, height // 9)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 3}:y=0:w={max(18, width // 7)}:h={height}:color={accent_soft}:t=fill",
                left_box,
                bottom_strip,
                corner_a,
                corner_b,
            ]
        )
    if family == "replay":
        return ",".join(
            [
                f"drawbox=x=24:y={height // 2}:w={max(220, width - 48)}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 2}:y={height // 2 - 20}:w=4:h=40:color={accent_hard}:t=fill",
                left_box,
                bottom_strip,
            ]
        )
    if family == "dossier":
        return ",".join(
            [
                left_box,
                f"drawbox=x={max(40, width - width // 3)}:y=32:w={max(180, width // 4)}:h={max(72, height // 5)}:color={accent_soft}:t=fill",
                f"drawbox=x={max(56, width - width // 3)}:y={height // 2}:w={max(200, width // 4)}:h={max(120, height // 4)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "network":
        return ",".join(
            [
                f"drawgrid=w={max(72, width // 10)}:h={max(72, height // 7)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 5}:y={height // 3}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2}:y={height // 4}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width - width // 4}:y={height // 2}:w=10:h=10:color={accent_hard}:t=fill",
                bottom_strip,
            ]
        )
    if family == "passport":
        return ",".join(
            [
                left_box,
                f"drawbox=x={width // 2 - 1}:y=24:w=2:h={height - 48}:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 + 12}:y=32:w={max(180, width // 4)}:h={max(72, height // 6)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "forge":
        return ",".join(
            [
                f"drawbox=x=24:y={height - 110}:w={width - 48}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 32}:y={height // 3}:w=64:h=64:color={accent_soft}:t=fill",
                left_box,
                corner_a,
                corner_b,
            ]
        )
    return ",".join([left_box, bottom_strip, corner_a, corner_b])


def apply_context_overlay(*, output_path: Path, spec: dict[str, object], width: int, height: int) -> tuple[bool, str]:
    row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
    if not isinstance(row, dict):
        return False, "context_overlay:missing_media_row"
    family = _overlay_family(row, spec)
    accent, glow = palette_for(
        str(spec.get("target") or output_path.name)
        + "::"
        + str(row.get("overlay_hint") or "")
        + "::"
        + family
    )
    filter_chain = _overlay_filter_for(family=family, accent=accent, glow=glow, width=width, height=height)
    with tempfile.NamedTemporaryFile(prefix="ch6_overlay_", suffix=output_path.suffix, delete=False) as handle:
        temp_output = Path(handle.name)
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(output_path),
                "-vf",
                filter_chain,
                "-frames:v",
                "1",
                str(temp_output),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_output.replace(output_path)
        return True, f"context_overlay:{family}"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"context_overlay_failed:{family}:{detail[:220]}"
    finally:
        try:
            temp_output.unlink(missing_ok=True)
        except Exception:
            pass


def render_with_ooda(*, prompt: str, output_path: Path, width: int, height: int, spec: dict[str, object]) -> dict[str, object]:
    forbid_legacy_svg_fallback(output_path)
    attempts: list[str] = []
    requested_order = spec.get("providers")
    if isinstance(requested_order, list):
        requested = [str(entry).strip().lower() for entry in requested_order if str(entry).strip()]
        preferred = provider_order()
        providers = sorted(
            dict.fromkeys(requested),
            key=lambda value: preferred.index(value) if value in preferred else len(preferred),
        ) or preferred
    else:
        providers = provider_order()
    for provider in providers:
        normalized = provider.strip().lower()
        if normalized == "pollinations":
            safe_prompt = build_safe_pollinations_prompt(prompt=prompt, spec=spec)
            ok, detail = run_pollinations_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
        elif normalized in {"media_factory", "media-factory"}:
            ok, detail = run_command_provider(
                "media_factory",
                media_factory_render_command(),
                prompt=prompt,
                output_path=output_path,
                width=width,
                height=height,
            )
        elif normalized == "magixai":
            safe_prompt = sanitize_prompt_for_provider(prompt, provider=normalized)
            ok, detail = run_magixai_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
            if not ok:
                command_ok, command_detail = run_command_provider("magixai", shlex_command("CHUMMER6_MAGIXAI_RENDER_COMMAND"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if command_ok or detail.endswith(":not_configured"):
                    ok, detail = command_ok, command_detail
            if not ok:
                url_ok, url_detail = run_url_provider("magixai", url_template("CHUMMER6_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "markupgo":
            ok, detail = False, "markupgo:disabled_for_primary_art"
        elif normalized == "prompting_systems":
            ok, detail = run_command_provider("prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                url_ok, url_detail = run_url_provider("prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "browseract_magixai":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_magixai", shlex_command("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_magixai", url_template("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_magixai:not_configured"
        elif normalized == "browseract_prompting_systems":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
                if not ok:
                    command_ok, command_detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if command_ok or detail.endswith(":not_configured"):
                        ok, detail = command_ok, command_detail
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_prompting_systems:not_configured"
        elif normalized in {"onemin", "1min", "1min.ai", "oneminai"}:
            safe_prompt = build_safe_onemin_prompt(prompt=prompt, spec=spec)
            ok, detail = run_onemin_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
            if not ok:
                command_ok, command_detail = run_command_provider("onemin", shlex_command("CHUMMER6_1MIN_RENDER_COMMAND"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if command_ok or detail.endswith(":not_configured"):
                    ok, detail = command_ok, command_detail
            if not ok:
                url_ok, url_detail = run_url_provider("onemin", url_template("CHUMMER6_1MIN_RENDER_URL_TEMPLATE"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized in {"scene_contract_renderer", "ooda_compositor", "local_raster"}:
            ok, detail = False, f"{normalized}:forbidden_fallback"
        else:
            ok, detail = False, f"{normalized}:unknown_provider"
        attempts.append(detail)
        if ok:
            return {"provider": normalized, "status": detail, "attempts": attempts}
    raise RuntimeError("no image provider succeeded: " + " || ".join(attempts))


def asset_specs() -> list[dict[str, object]]:
    loaded = load_media_overrides()
    media = loaded.get("media") if isinstance(loaded, dict) else {}
    pages = loaded.get("pages") if isinstance(loaded, dict) else {}
    style_epoch = style_epoch_for_overrides(loaded)
    ledger = load_scene_ledger()
    recent_rows = scene_rows_for_style_epoch(ledger, style_epoch=style_epoch, allow_fallback=False)[-8:]
    section_ooda = loaded.get("section_ooda") if isinstance(loaded, dict) else {}
    page_ooda = section_ooda.get("pages") if isinstance(section_ooda, dict) else {}
    visual_overrides = load_visual_overrides()
    hero_override = media.get("hero") if isinstance(media, dict) else {}
    if not isinstance(hero_override, dict) or not str(hero_override.get("visual_prompt", "")).strip():
        raise RuntimeError("missing hero visual_prompt in EA overrides")
    if not isinstance(pages, dict):
        raise RuntimeError("missing page overrides in EA output")
    if not isinstance(page_ooda, dict):
        raise RuntimeError("missing page section OODA in EA output")

    def apply_visual_override(target: str, row: dict[str, object]) -> dict[str, object]:
        override = visual_overrides.get(target)
        if not isinstance(override, dict):
            return sanitize_media_row(target=target, row=row)
        merged = deep_merge(row, override)
        normalized = merged if isinstance(merged, dict) else row
        return sanitize_media_row(target=target, row=normalized)

    def render_prompt_from_row(row: dict[str, object], *, role: str, target: str) -> str:
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        subject = str(contract.get("subject", "")).strip()
        environment = str(contract.get("environment", "")).strip()
        action = str(contract.get("action", "")).strip()
        metaphor = str(contract.get("metaphor", "")).strip()
        composition = str(contract.get("composition", "")).strip()
        palette = str(contract.get("palette", "")).strip()
        mood = str(contract.get("mood", "")).strip()
        humor = sanitize_scene_humor(contract.get("humor"))
        props = ", ".join(str(entry).strip() for entry in (contract.get("props") or []) if str(entry).strip())
        overlays = ", ".join(str(entry).strip() for entry in (contract.get("overlays") or []) if str(entry).strip())
        motifs = ", ".join(str(entry).strip() for entry in (row.get("visual_motifs") or []) if str(entry).strip())
        callouts = ", ".join(str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip())
        visual_prompt = str(row.get("visual_prompt", "")).strip()
        style_bits = ", ".join(
            str(style_epoch.get(key) or "").strip()
            for key in ("style_family", "palette", "lighting", "lens_grammar", "texture_treatment", "signage_treatment")
            if str(style_epoch.get(key) or "").strip()
        )
        guardrails = variation_guardrails_for(target=target, rows=recent_rows)
        normalized_target = target.replace("\\", "/")
        is_detail_still = "/details/" in normalized_target or normalized_target.endswith("-scene.png")
        intro_line = (
            f"Close, prop-led grounded cyberpunk scene still for the {role}."
            if is_detail_still
            else f"Wide grounded cyberpunk scene still for the {role}."
        )
        smartlink_clause = smartlink_overlay_clause(contract)
        lore_clause = lore_background_clause(contract)
        prompt_parts = [
            intro_line,
            visual_prompt,
            f"One clear focal subject: {subject}." if subject else "",
            f"Set the scene in {environment}." if environment else "",
            f"Show this happening: {action}." if action else "",
            f"Make the core visual metaphor immediately legible: {metaphor}." if metaphor else "",
            f"Use a {composition} composition." if composition else "",
            f"Palette: {palette}." if palette else "",
            f"Mood: {mood}." if mood else "",
            f"Humor note: {humor}." if humor else "",
            f"Concrete visible props: {props}." if props else "",
            f"Useful diegetic overlays in-scene: {overlays}." if overlays else "",
            f"Weave in these recurring visual motifs: {motifs}." if motifs else "",
            f"Imply these idea markers through props and framing, never through readable text: {callouts}." if callouts else "",
            smartlink_clause,
            lore_clause,
            f"Keep the overall look consistent with: {style_bits}." if style_bits else "",
            "Variation rules: " + " ".join(guardrails) if guardrails else "",
            easter_egg_clause(contract) if scene_contract_requests_easter_egg(contract) else "",
            "Make it feel like a lived-in Shadowrun street, lab, archive, forge, or table scene, not a product poster.",
            "Avoid generic skylines, abstract icon soup, flat infographics, or brochure-cover posing.",
            "Do not print text, prompts, OODA labels, metadata, or resolution callouts on the image.",
            "No readable words or numbers on screens, papers, props, or overlays; use abstract bars, chips, glyphs, or traces instead.",
            "No readable titles, no watermark, no giant centered logos, 16:9.",
        ]
        return " ".join(part for part in prompt_parts if part)

    def page_media_row(page_id: str, *, role: str, composition_hint: str) -> dict[str, object]:
        page_row = pages.get(page_id)
        ooda_row = page_ooda.get(page_id)
        if not isinstance(page_row, dict):
            raise RuntimeError(f"missing page override for media asset: {page_id}")
        if not isinstance(ooda_row, dict):
            raise RuntimeError(f"missing section OODA for media asset: {page_id}")
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
        orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
        decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
        visual_seed = str(act.get("visual_prompt_seed", "")).strip()
        intro = str(page_row.get("intro", "")).strip()
        body = str(page_row.get("body", "")).strip()
        focal = str(orient.get("focal_subject", "")).strip()
        scene_logic = str(orient.get("scene_logic", "")).strip()
        overlay = str(decide.get("overlay_priority", "")).strip()
        interests = observe.get("likely_interest") if isinstance(observe.get("likely_interest"), list) else []
        concrete = observe.get("concrete_signals") if isinstance(observe.get("concrete_signals"), list) else []
        if not visual_seed:
            raise RuntimeError(f"missing visual prompt seed for page media asset: {page_id}")
        return {
            "title": role,
            "subtitle": intro,
            "kicker": str(page_row.get("kicker", "")).strip(),
            "note": body,
            "overlay_hint": overlay or str(orient.get("visual_devices", "")).strip(),
            "visual_prompt": visual_seed,
            "visual_motifs": [str(entry).strip() for entry in interests if str(entry).strip()],
            "overlay_callouts": [str(entry).strip() for entry in concrete if str(entry).strip()],
            "scene_contract": {
                "subject": focal or "a cyberpunk protagonist",
                "environment": scene_logic or body,
                "action": str(act.get("paragraph_seed", "")).strip() or str(act.get("one_liner", "")).strip(),
                "metaphor": page_id.replace("_", " "),
                "props": [str(entry).strip() for entry in interests if str(entry).strip()][:5],
                "overlays": [str(entry).strip() for entry in concrete if str(entry).strip()][:4],
                "composition": composition_hint,
                "palette": str(orient.get("visual_devices", "")).strip(),
                "mood": str(orient.get("emotional_goal", "")).strip(),
                "humor": "",
            },
        }

    def page_spec(*, target: str, page_id: str, role: str, composition_hint: str) -> dict[str, object]:
        row = apply_visual_override(target, page_media_row(page_id, role=role, composition_hint=composition_hint))
        return {
            "target": target,
            "role": role,
            "prompt": render_prompt_from_row(row, role=role, target=target),
            "width": 960,
            "height": 540,
            "media_row": row,
            "style_epoch": style_epoch,
            "providers": provider_order(),
        }

    target_scene_policies: dict[str, dict[str, object]] = {
        "assets/hero/chummer6-hero.png": {
            "preferred": "over_shoulder_receipt",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Keep this as one rules-truth moment under pressure, not a committee around a surface.",
        },
        "assets/pages/what-chummer6-is.png": {
            "preferred": "over_shoulder_receipt",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Prefer one trust moment with the proof path doing the heavy lifting over another group confrontation.",
        },
        "assets/pages/where-to-go-deeper.png": {
            "preferred": "archive_room",
            "banned": TABLEAU_COMPOSITIONS | {"desk_still_life"},
            "prompt_nudge": "Treat go-deeper like an archive descent or evidence room, not a desk meeting.",
            "subject": "a reader tracing one question across archive materials",
            "environment": "a dim archive room with binders, drawers, and one glowing review screen",
        },
        "assets/pages/current-status.png": {
            "preferred": "solo_operator",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Show one host or operator keeping the session alive instead of another huddle.",
        },
        "assets/pages/public-surfaces.png": {
            "preferred": "street_front",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Use a real-world surface scene with asymmetrical devices, not another meeting shot.",
        },
        "assets/pages/horizons-index.png": {
            "required": "horizon_boulevard",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Make this a future boulevard of districts and pains, not an icon corridor or meeting tableau.",
            "subject": "a horizon boulevard crossroads where future districts tempt the viewer deeper",
            "environment": "a neon transit district with storefronts, alleys, station mouths, and future neighborhoods receding into rain",
        },
        "assets/parts/core.png": {
            "required": "over_shoulder_receipt",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Core is proof-on-props first: hands, dice, chips, and traces beat faces.",
        },
        "assets/parts/mobile.png": {
            "required": "transit_checkpoint",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Anchor this around one reconnecting device or runner in motion, not a posed group.",
        },
        "assets/parts/hub.png": {
            "required": "service_rack",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Hosted coordination should read as racks, control surfaces, and remote presence seams, not a table in disguise.",
        },
        "assets/horizons/nexus-pan.png": {
            "required": "transit_checkpoint",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Anchor the shot around one reconnecting device or operator; the rest of the table can stay implied off-frame.",
            "subject": "one reconnecting operator bringing a dropped device back into the session",
            "environment": "a transit threshold or rainy cafe edge with one live handheld and one secondary session surface",
        },
        "assets/horizons/alice.png": {
            "required": "simulation_lab",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "ALICE lives in a sim bench or crash lab, never another social huddle.",
        },
        "assets/horizons/jackpoint.png": {
            "required": "dossier_desk",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "JACKPOINT should feel like dossier, dead-drop, or evidence-desk grammar before faces enter frame.",
        },
        "assets/horizons/karma-forge.png": {
            "required": "workshop_bench",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "KARMA FORGE needs a rulesmith bench or forge station, not a committee around glowing furniture.",
        },
    }
    adjacency_fallbacks = {
        "archive_room": "street_front",
        "dossier_desk": "desk_still_life",
        "horizon_boulevard": "city_edge",
        "over_shoulder_receipt": "solo_operator",
        "service_rack": "archive_room",
        "simulation_lab": "solo_operator",
        "solo_operator": "street_front",
        "street_front": "over_shoulder_receipt",
        "transit_checkpoint": "solo_operator",
        "workshop_bench": "service_rack",
    }

    def scene_policy_for_target(target: str) -> dict[str, object]:
        return dict(target_scene_policies.get(target) or {})

    def planned_scene_row(target: str, row: dict[str, object]) -> dict[str, str]:
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        return {
            "target": target,
            "composition": str(contract.get("composition") or "").strip(),
            "subject": str(contract.get("subject") or "").strip(),
        }

    def repair_media_row(target: str, row: dict[str, object], planned_rows: list[dict[str, str]]) -> tuple[dict[str, object], list[str]]:
        cleaned = copy.deepcopy(row)
        policy = scene_policy_for_target(target)
        banned = {str(entry).strip() for entry in policy.get("banned", set()) if str(entry).strip()}
        required = str(policy.get("required") or "").strip()
        preferred = str(policy.get("preferred") or required or "").strip()
        contract = cleaned.get("scene_contract") if isinstance(cleaned.get("scene_contract"), dict) else {}
        contract = dict(contract)
        notes: list[str] = []

        composition = str(contract.get("composition") or "").strip()
        if not composition:
            composition = preferred or "solo_operator"
            notes.append(f"scene_plan_audit:missing_composition->{composition}")
        if composition in banned and preferred and composition != preferred:
            notes.append(f"scene_plan_audit:{composition}->{preferred}")
            composition = preferred
        if required and composition != required:
            notes.append(f"scene_plan_audit:required:{composition}->{required}")
            composition = required

        tableish_count = sum(
            1
            for planned in planned_rows
            if str(planned.get("composition") or "").strip() in TABLEAU_COMPOSITIONS
        )
        if composition in TABLEAU_COMPOSITIONS and tableish_count >= 2:
            fallback = preferred or adjacency_fallbacks.get(composition) or "solo_operator"
            if fallback in TABLEAU_COMPOSITIONS:
                fallback = "solo_operator"
            if fallback != composition:
                notes.append(f"whole_pack_audit:table_monoculture:{composition}->{fallback}")
                composition = fallback

        if planned_rows:
            previous = str(planned_rows[-1].get("composition") or "").strip()
            if previous and composition == previous:
                fallback = preferred or adjacency_fallbacks.get(composition) or ""
                if fallback and fallback != composition:
                    notes.append(f"whole_pack_audit:adjacent_repeat:{composition}->{fallback}")
                    composition = fallback

        contract["composition"] = composition
        for key in ("subject", "environment", "action", "metaphor", "mood"):
            replacement = str(policy.get(key) or "").strip()
            if replacement and (notes or not str(contract.get(key) or "").strip()):
                contract[key] = replacement
        cleaned["scene_contract"] = contract

        prompt_nudge = str(policy.get("prompt_nudge") or "").strip()
        if prompt_nudge:
            visual_prompt = str(cleaned.get("visual_prompt") or "").strip()
            if prompt_nudge.lower() not in visual_prompt.lower():
                cleaned["visual_prompt"] = f"{prompt_nudge} {visual_prompt}".strip()
        if notes:
            cleaned["scene_audit"] = list(notes)
        return cleaned, notes

    def audit_specs(specs_in: list[dict[str, object]]) -> list[dict[str, object]]:
        planned_rows = [dict(row) for row in recent_rows]
        audited_specs: list[dict[str, object]] = []
        for spec in specs_in:
            target = str(spec.get("target") or "").strip()
            role = str(spec.get("role") or "guide asset").strip()
            row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
            repaired_row, notes = repair_media_row(target, row, planned_rows)
            prompt = render_prompt_from_row(repaired_row, role=role, target=target)
            if notes:
                prompt = prompt + " Pack audit enforcement: " + " ".join(notes)
            audited_spec = dict(spec)
            audited_spec["media_row"] = repaired_row
            audited_spec["prompt"] = prompt
            audited_spec["scene_audit"] = notes
            audited_specs.append(audited_spec)
            planned_rows.append(planned_scene_row(target, repaired_row))

        compositions = [
            str(
                (
                    (spec.get("media_row") or {}).get("scene_contract")
                    if isinstance((spec.get("media_row") or {}).get("scene_contract"), dict)
                    else {}
                ).get("composition")
                or ""
            ).strip()
            for spec in audited_specs
        ]
        tableish_count = sum(1 for composition in compositions if composition in TABLEAU_COMPOSITIONS)
        if tableish_count > 2:
            raise RuntimeError(f"whole_pack_audit_failed:table_monoculture:{tableish_count}")
        for expected_target, required in (
            ("assets/pages/horizons-index.png", "horizon_boulevard"),
            ("assets/horizons/alice.png", "simulation_lab"),
            ("assets/horizons/jackpoint.png", "dossier_desk"),
            ("assets/horizons/karma-forge.png", "workshop_bench"),
            ("assets/horizons/nexus-pan.png", "transit_checkpoint"),
        ):
            match = next((spec for spec in audited_specs if str(spec.get("target") or "") == expected_target), None)
            if not isinstance(match, dict):
                continue
            contract = match.get("media_row") if isinstance(match.get("media_row"), dict) else {}
            scene_contract = contract.get("scene_contract") if isinstance(contract.get("scene_contract"), dict) else {}
            composition = str(scene_contract.get("composition") or "").strip()
            if composition != required:
                raise RuntimeError(f"whole_pack_audit_failed:{expected_target}:{composition or 'missing'}!={required}")
        return audited_specs

    hero_row = apply_visual_override("assets/hero/chummer6-hero.png", hero_override)
    specs: list[dict[str, object]] = [
        {
            "target": "assets/hero/chummer6-hero.png",
            "role": "landing hero",
            "prompt": render_prompt_from_row(hero_row, role="landing hero", target="assets/hero/chummer6-hero.png"),
            "width": 960,
            "height": 540,
            "media_row": hero_row,
            "style_epoch": style_epoch,
            "providers": provider_order(),
        },
        page_spec(target="assets/hero/poc-warning.png", page_id="readme", role="POC warning shelf", composition_hint="desk_still_life"),
        page_spec(target="assets/pages/start-here.png", page_id="start_here", role="start-here banner", composition_hint="city_edge"),
        page_spec(target="assets/pages/what-chummer6-is.png", page_id="what_chummer6_is", role="what-is banner", composition_hint="single_protagonist"),
        page_spec(target="assets/pages/where-to-go-deeper.png", page_id="where_to_go_deeper", role="deeper-dive banner", composition_hint="archive_room"),
        page_spec(target="assets/pages/current-phase.png", page_id="current_phase", role="current-phase banner", composition_hint="workshop"),
        page_spec(target="assets/pages/current-status.png", page_id="current_status", role="current-status banner", composition_hint="street_front"),
        page_spec(target="assets/pages/public-surfaces.png", page_id="public_surfaces", role="public-surfaces banner", composition_hint="street_front"),
        page_spec(target="assets/pages/parts-index.png", page_id="parts_index", role="parts-overview banner", composition_hint="district_map"),
        page_spec(target="assets/pages/horizons-index.png", page_id="horizons_index", role="horizons boulevard banner", composition_hint="horizon_boulevard"),
    ]
    part_overrides = media.get("parts") if isinstance(media, dict) else {}
    for slug, item in CANON_PARTS.items():
        override = part_overrides.get(slug) if isinstance(part_overrides, dict) else None
        if not isinstance(override, dict):
            legacy_slug = LEGACY_PART_SLUGS.get(slug)
            override = part_overrides.get(legacy_slug) if isinstance(part_overrides, dict) and legacy_slug else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            raise RuntimeError(f"missing part visual_prompt in EA overrides: {slug}")
        target = f"assets/parts/{slug}.png"
        row = apply_visual_override(target, override)
        specs.append(
            {
                "target": target,
                "role": f"{slug} part page",
                "prompt": render_prompt_from_row(row, role=f"{slug} part page", target=target),
                "width": 960,
                "height": 540,
                "media_row": row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
    horizon_overrides = media.get("horizons") if isinstance(media, dict) else {}
    for slug, item in CANON_HORIZONS.items():
        override = horizon_overrides.get(slug) if isinstance(horizon_overrides, dict) else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            override = fallback_horizon_media_row(slug, item)
        target = f"assets/horizons/{slug}.png"
        row = apply_visual_override(target, override)
        specs.append(
            {
                "target": target,
                "role": f"{slug} horizon page",
                "prompt": render_prompt_from_row(row, role=f"{slug} horizon page", target=target),
                "width": 960,
                "height": 540,
                "media_row": row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
        detail_target = f"assets/horizons/details/{slug}-scene.png"
        detail_row = dict(row)
        detail_contract = dict(row.get("scene_contract") or {}) if isinstance(row.get("scene_contract"), dict) else {}
        detail_contract["composition"] = "prop_detail"
        detail_contract["subject"] = str(
            detail_contract.get("subject") or "hands and props capturing the horizon promise"
        ).strip() or "hands and props capturing the horizon promise"
        detail_contract["action"] = str(
            detail_contract.get("action") or "captured as a tight scene-detail still with hands, props, and implied dialogue beats"
        ).strip() or "captured as a tight scene-detail still with hands, props, and implied dialogue beats"
        detail_row["scene_contract"] = detail_contract
        detail_nudge = (
            "Scene-detail still: tighter framing, prop-led, hands and gear carry the moment; "
            "avoid wide establishing shots or big group huddles."
        )
        detail_visual_prompt = str(detail_row.get("visual_prompt") or "").strip()
        if detail_visual_prompt:
            if detail_nudge.lower() not in detail_visual_prompt.lower():
                detail_row["visual_prompt"] = f"{detail_nudge} {detail_visual_prompt}".strip()
        else:
            detail_row["visual_prompt"] = detail_nudge
        detail_row = apply_visual_override(detail_target, detail_row)
        specs.append(
            {
                "target": detail_target,
                "role": f"{slug} horizon scene detail",
                "prompt": render_prompt_from_row(detail_row, role=f"{slug} horizon scene detail", target=detail_target),
                "width": 640,
                "height": 360,
                "media_row": detail_row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
    return audit_specs(specs)


def render_specs(*, specs: list[dict[str, object]], output_dir: Path) -> dict[str, object]:
    if not specs:
        raise RuntimeError("no asset specs selected for rendering")
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = load_scene_ledger()
    active_style_epoch = {}
    if specs and isinstance(specs[0].get("style_epoch"), dict):
        active_style_epoch = dict(specs[0].get("style_epoch") or {})
    accepted_rows = scene_rows_for_style_epoch(ledger, style_epoch=active_style_epoch, allow_fallback=False)
    audited_compositions = [
        str(
            (
                (spec.get("media_row") or {}).get("scene_contract")
                if isinstance((spec.get("media_row") or {}).get("scene_contract"), dict)
                else {}
            ).get("composition")
            or ""
        ).strip()
        for spec in specs
    ]
    pack_audit = {
        "tableau_count": sum(1 for composition in audited_compositions if composition in TABLEAU_COMPOSITIONS),
        "adjacent_repeat_count": sum(
            1
            for index in range(1, len(audited_compositions))
            if audited_compositions[index] and audited_compositions[index] == audited_compositions[index - 1]
        ),
        "scene_adjustments": [
            {
                "target": str(spec.get("target") or "").strip(),
                "notes": list(spec.get("scene_audit") or []),
            }
            for spec in specs
            if list(spec.get("scene_audit") or [])
        ],
    }

    def _render_spec(spec: dict[str, object]) -> dict[str, object]:
        target = str(spec["target"])
        row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        composition = str(contract.get("composition") or "").strip()
        block_reason = repetition_block_reason(target=target, composition=composition, ledger={"assets": accepted_rows})
        if block_reason:
            egg_payload = easter_egg_payload(contract)
            return {
                "target": target,
                "output": "",
                "provider": "none",
                "status": f"rejected:{block_reason}",
                "attempts": [f"variation_guard:{block_reason}"],
                "prompt": str(spec.get("prompt") or ""),
                "easter_egg": egg_payload,
            }
        prompt = refine_prompt_with_ooda(prompt=str(spec["prompt"]), target=target)
        prompt = ensure_troll_clause(prompt=prompt, spec=spec)
        width = int(spec.get("width", 1280))
        height = int(spec.get("height", 720))
        out_path = output_dir / target
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = render_with_ooda(prompt=prompt, output_path=out_path, width=width, height=height, spec=spec)
        normalize_status = normalize_banner_size(image_path=out_path, width=width, height=height)
        postpass_attempts: list[str] = []
        if troll_postpass_enabled() and scene_contract_requests_easter_egg(contract):
            postpass_attempts.append(
                apply_troll_postpass(image_path=out_path, spec=spec, width=width, height=height)
            )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        accepted_rows.append(
            {
                "target": target,
                "composition": composition,
                "cast_signature": infer_cast_signature(contract),
                "subject": str(contract.get("subject") or "").strip(),
                "mood": str(contract.get("mood") or "").strip(),
                "easter_egg_kind": str(contract.get("easter_egg_kind") or "").strip(),
                "provider": result["provider"],
                "prompt_hash": prompt_hash,
                "style_epoch": dict(spec.get("style_epoch") or {}) if isinstance(spec.get("style_epoch"), dict) else {},
            }
        )
        egg_payload = easter_egg_payload(contract)
        return {
            "target": target,
            "output": str(out_path),
            "provider": result["provider"],
            "status": result["status"],
            "attempts": list(result["attempts"]) + [normalize_status] + postpass_attempts,
            "prompt": prompt,
            "scene_audit": list(spec.get("scene_audit") or []),
            "easter_egg": egg_payload,
        }
    assets = [_render_spec(spec) for spec in specs]
    manifest = {
        "output_dir": str(output_dir),
        "assets": assets,
        "style_epoch": active_style_epoch,
        "pack_audit": pack_audit,
    }
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    write_json_file(
        SCENE_LEDGER_OUT,
        {
            "style_epoch": active_style_epoch,
            "assets": accepted_rows,
        },
    )
    STATE_OUT.write_text(
        json.dumps(
            {
                "output": str(output_dir),
                "provider": assets[0]["provider"] if assets else "none",
                "status": f"pack:rendered:{len(assets)}",
                "attempts": [asset["status"] for asset in assets],
                "pack_audit": pack_audit,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def render_pack(*, output_dir: Path) -> dict[str, object]:
    return render_specs(specs=asset_specs(), output_dir=output_dir)


def render_targets(*, targets: list[str], output_dir: Path) -> dict[str, object]:
    wanted = {str(target).strip() for target in targets if str(target).strip()}
    if not wanted:
        raise RuntimeError("no targets requested")
    available = asset_specs()
    selected = [
        spec
        for spec in available
        if str(spec.get("target")) in wanted or Path(str(spec.get("target"))).name in wanted
    ]
    missing = sorted(
        target
        for target in wanted
        if target not in {str(spec.get("target")) for spec in selected}
        and target not in {Path(str(spec.get("target"))).name for spec in selected}
    )
    if missing:
        raise RuntimeError("unknown render targets: " + ", ".join(missing))
    return render_specs(specs=selected, output_dir=output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Chummer6 guide asset through EA provider selection.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("--prompt", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--width", type=int, default=1280)
    render.add_argument("--height", type=int, default=720)
    render_pack_parser = sub.add_parser("render-pack")
    render_pack_parser.add_argument("--output-dir", default="/docker/fleet/state/chummer6/ea_media_assets")
    render_targets_parser = sub.add_parser("render-targets")
    render_targets_parser.add_argument("--target", action="append", required=True)
    render_targets_parser.add_argument("--output-dir", default="/docker/fleet/state/chummer6/ea_media_assets")
    args = parser.parse_args()

    if args.command == "render-pack":
        manifest = render_pack(output_dir=Path(args.output_dir).expanduser())
        print(json.dumps({"output_dir": manifest["output_dir"], "assets": len(manifest["assets"]), "status": "rendered"}))
        return 0
    if args.command == "render-targets":
        manifest = render_targets(targets=list(args.target), output_dir=Path(args.output_dir).expanduser())
        print(json.dumps({"output_dir": manifest["output_dir"], "assets": len(manifest["assets"]), "status": "rendered"}))
        return 0

    output_path = Path(args.output).expanduser()
    result = render_with_ooda(
        prompt=str(args.prompt),
        output_path=output_path,
        width=int(args.width),
        height=int(args.height),
        spec={"target": str(output_path.name), "media_row": {}},
    )
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps({"output": str(output_path), **result}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "provider": result["provider"], "status": result["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
