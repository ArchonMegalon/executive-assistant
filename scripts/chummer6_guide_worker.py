#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chummer6_guide_canon import (
    asset_visual_profile,
    load_faq_canon,
    load_help_canon,
    load_horizon_canon,
    load_media_briefs,
    load_part_canon,
    load_page_registry,
    load_public_feature_registry,
    load_release_experience_canon,
    load_trust_content_canon,
)
from chummer6_runtime_config import load_local_env, load_runtime_overrides

EA_ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_OUT = Path("/docker/fleet/state/chummer6/ea_overrides.json")
STYLE_EPOCH_PATH = Path("/docker/fleet/state/chummer6/ea_style_epoch.json")
SCENE_LEDGER_PATH = Path("/docker/fleet/state/chummer6/ea_scene_ledger.json")
DEFAULT_MODEL = "ea-groundwork"
WORKING_VARIANT: dict[str, object] | None = None
TEXT_PROVIDER_USED: str = ""
HUMANIZER_EXTERNAL_LOCKED_OUT: bool = False
HUMANIZER_EXTERNAL_LOCKOUT_REASON: str = ""
HUMANIZER_EXTERNAL_READY: bool | None = None
HUMANIZER_BRAIN_ONLY: bool = False
TRACE_ENABLED: bool = False
EA_ORCHESTRATOR = None
EA_CONTAINER = None
PUBLIC_WRITER_SKILL_KEY = "chummer6_public_writer"
VISUAL_DIRECTOR_SKILL_KEY = "chummer6_visual_director"
PUBLIC_AUDITOR_SKILL_KEY = "chummer6_public_auditor"
SCENE_AUDITOR_SKILL_KEY = "chummer6_scene_auditor"
VISUAL_AUDITOR_SKILL_KEY = "chummer6_visual_auditor"
PACK_AUDITOR_SKILL_KEY = "chummer6_pack_auditor"
REQUIRED_CHUMMER6_SKILL_KEYS: tuple[str, ...] = (
    PUBLIC_WRITER_SKILL_KEY,
    PUBLIC_AUDITOR_SKILL_KEY,
    VISUAL_DIRECTOR_SKILL_KEY,
    SCENE_AUDITOR_SKILL_KEY,
    VISUAL_AUDITOR_SKILL_KEY,
    PACK_AUDITOR_SKILL_KEY,
)
SKILL_BOOTSTRAP_STATUS: dict[str, object] | None = None
STYLE_PACKS: tuple[dict[str, str], ...] = (
    {
        "style_family": "grimy_cinematic_realism",
        "palette": "saturated sodium orange, acid cyan, nicotine yellow, wet asphalt blue",
        "lighting": "practical lamps, sodium spill, rain reflections",
        "realism_mode": "documentary cyberpunk realism",
        "lens_grammar": "28mm and 40mm layered frames with strong foreground obstruction and visible room depth",
        "texture_treatment": "fine film grain, scratched hardware surfaces, denser prop layering, and harder focal separation",
        "signage_treatment": "icon-first transit grime and cropped labels",
        "troll_material_style": "worn stickers, scratched pins, faded decals",
        "weather_bias": "rain-biased exterior with day-edge spill and damp interior carry-over",
        "humor_ceiling": "wry and restrained",
    },
    {
        "style_family": "shadowrun_cover_realism",
        "palette": "warning red, market neon cyan, bruised blue, warm white glare",
        "lighting": "hard practical key light with shaped neon accents and dense shadow",
        "realism_mode": "grounded cover-art realism with obvious focal storytelling and stronger graphic punch",
        "lens_grammar": "28mm and 40mm graphic frames with strong foreground shapes, diagonal energy, and layered depth",
        "texture_treatment": "sharper silhouettes, tactile props, wet surfaces, restrained bloom, and higher semantic prop density",
        "signage_treatment": "pictograms, hazard stripes, cropped glyphs, never readable words",
        "troll_material_style": "enamel pins, transit stickers, scratched charm decals",
        "weather_bias": "humid exteriors and heat-loaded interiors with reflective grime and sodium carry-over",
        "humor_ceiling": "dry, sparse, and scene-native",
    },
    {
        "style_family": "corp_decay_noir",
        "palette": "acrid green, bruised brass, warning amber, nicotine ivory",
        "lighting": "sickly office fluorescents cut by harder accent light",
        "realism_mode": "grounded noir with expensive surfaces aging badly",
        "lens_grammar": "50mm still-life and long-lens surveillance peeks",
        "texture_treatment": "paper fibers, wax seals, tape residue, smoked glass",
        "signage_treatment": "approval marks, warnings, and symbol clusters only",
        "troll_material_style": "wax seals, warning placards, coffee-stained coasters",
        "weather_bias": "storm bleed through windows onto tired interiors",
        "humor_ceiling": "dry, spare, and adult",
    },
    {
        "style_family": "industrial_shadowplay",
        "palette": "forge orange, neon magenta accents, smoked steel, wet concrete blue",
        "lighting": "task lamps, monitor glow, and hard industrial spill",
        "realism_mode": "tactile shop-floor realism with cinematic contrast",
        "lens_grammar": "28mm environment frames and dense close prop clusters with layered control hardware",
        "texture_treatment": "grease, powder, heat haze, metal wear, and visibly packed work surfaces",
        "signage_treatment": "warning icons, hazard bands, stamped surfaces",
        "troll_material_style": "patches, tool decals, hazard stickers",
        "weather_bias": "indoor heat with outdoor rain, soot, and grit suggested secondarily",
        "humor_ceiling": "deadpan and tightly controlled",
    },
)
PUBLIC_WRITER_RULES = """Public-writer contract:
- write for a curious player, GM, tester, or supporter
- the reader is not a maintainer and is not expected to fix docs or govern repo hierarchy
- explain what the project means for the reader at the table first
- if the reader can act, route them to the Chummer6 issue tracker, the public guide, the horizon shelf, or the owning repos as appropriate
- do not send normal users to chummer6-design to propose features or clean up guide drift
- do not open public pages with repo structure, split mechanics, blueprint talk, or architecture lectures
- on first-contact pages, prioritize: what the idea is trying to solve, why someone should care if it ever lands, how little currently exists, and what the reader can inspect or watch next
- give the reader at least one concrete table pain or future table win instead of only product framing
- never invent or restate canonical mechanics, dice math, thresholds, DV/AP, or stat values unless they come from explicit core receipts
- if a section needs rules truth, point to the core-backed receipt or outcome instead of recomputing mechanics in guide/help/media copy
- use long-range plan instead of blueprint, and only mention code repos when the reader explicitly wants source or implementation detail
- translate any internal term into a table-facing benefit the moment it appears
- glossary terms must be things a player or GM can actually feel at the table
- translate internal jargon immediately or avoid it
- this is still closer to concept work than software: any visible proof surface, build, or artifact should be treated as provisional spillover or luck, not as a supported product
- when describing the future, write like there is a nonzero chance some of it never fully lands
- until the Lua-backed rules coverage is genuinely complete, do not write as if the math is already settled, fully clear, or trustworthy end to end
- on first-contact pages, say the project is trying to earn trust through the idea and whatever limited traces escape into public view; do not claim that dependable software already exists
- humor should be sparse, dry, and useful; if the joke is not better than clear prose, skip it
- a rare Shadowrun-lore jab at cursed code, corp-grade UX, busted patch rituals, or an overpriced cerebral-booster tier mindset is fine if it sharpens the point
- sparse lore-bound vice metaphors like cram, jazz, novacoke, or stim-burnout are fine when they read like world flavor rather than real-world shock bait
- keep that sharper lore-roast energy mostly to core, UI, or KARMA FORGE style material; keep FAQ, help, account, and participation copy cleaner
- never make the reader, their body, or private real-life circumstances the target of the joke
"""
FORBIDDEN_PUBLIC_COPY_PHRASES: tuple[str, ...] = (
    "fix chummer6 first",
    "correct the blueprint",
    "visitor center",
    "blueprint room",
    "blueprint truth",
    "control plane",
    "repo topology",
    "split story",
    "architectural rules",
    "repo taxonomy",
    "three main nodes",
    "signoff only",
    "shared interface",
    "where do i propose design changes?\n\nin `chummer6-design`",
)
PUBLIC_COPY_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("blueprint", "long-range plan"),
    ("repo taxonomy", "internal map"),
    ("repo topology", "internal map"),
    ("architectural rules", "deeper design notes"),
    ("split story", "part map"),
    ("three main nodes", "main paths"),
    ("the split is real", "the parts are real"),
    ("workbench", "prep surface"),
    ("play shell", "live-play surface"),
    ("device churn", "reconnect chaos"),
    ("rules-truth", "receipt trail"),
    ("rules truth", "receipt trail"),
    ("trust the math", "follow the receipts"),
    ("stop guessing", "start with the idea"),
    ("proof of concept", "rough concept"),
    ("proof-of-concept", "rough concept"),
    ("pre-release", "concept spillover"),
    ("prerelease", "concept spillover"),
    ("usable tonight", "visible by accident tonight"),
    ("available today", "visible right now by accident"),
    ("release shelf", "artifact shelf"),
    ("prototype logic", "unstable experiment"),
    ("governed ruleset evolution", "rule experiment lane"),
    ("tactical dossier", "idea trace"),
    ("dossier metadata hud", "provenance traces"),
)
OVERPLAYED_SNARK_PHRASES: tuple[str, ...] = (
    "hide the accelerants",
    "growth funnel with a knife",
    "future troublemakers",
    "tiny cleanup pass",
)
SOFT_OODA_PHRASES: tuple[str, ...] = (
    "future tech we are tracking",
    "tech we are tracking",
    "long-range scans",
    "version worth watching",
    "worth watching once",
)
OODA_RESTRICTED_TERMS: tuple[str, ...] = (
    "booster",
    "participate",
    "booster_first",
    "deterministic_truth",
    "multi-era",
    "multi era",
    "multi_era",
    "multi_era_rulesets",
    "lua",
    "lua_rules",
    "scriptable",
    "scripted rules",
    "session shell",
)
OODA_OVERCLAIM_PHRASES: tuple[str, ...] = (
    "rules assistant",
    "character assistant",
    "deterministic character",
    "verifiable core",
    "device churn",
    "offline sessions",
    "offline-safe play",
    "offline safe play",
    "shared table state",
    "grounded ai analysis",
    "mobile-first",
    "local-first stability",
    "audit every dv",
    "audit every threshold",
    "usable tonight",
    "available today",
    "latest drop",
    "release shelf",
    "public guide is active today",
    "integrity clues are on the shelf",
)
SECTION_OODA_DRIFT_PHRASES: tuple[str, ...] = (
    "corp-subsidized calculator",
    "professional-grade",
    "proof of concept",
    "proof-of-concept",
    "save-file",
    "long-range plan",
    "automated mission briefings",
    "validation passed",
    "compatibility verified",
    "built-in sanity checks",
    "lua-chip",
    "lua chip",
    "node-graphs",
    "node graphs",
    "stop guessing",
    "start auditing",
    "the math is the law",
    "trust the vibe",
    "trust the math",
    "rules-truth",
    "rules truth",
    "prototype logic",
    "tactical dossier",
    "governed ruleset evolution",
    "dossier metadata hud",
    "current drop",
    "device churn",
    "typography guides",
    "prerelease",
    "pre-release",
    "usable tonight",
    "available today",
    "latest drop",
    "release shelf",
    "public guide is active today",
    "integrity clues are on the shelf",
    "the math should explain itself",
)
SPARSE_EASTER_EGG_ASSET_TARGETS: frozenset[str] = frozenset(
    set()
)
SPARSE_HUMOR_ASSET_TARGETS: frozenset[str] = frozenset(
    {
        "assets/hero/poc-warning.png",
    }
)
BOOSTER_REFERENCE_HORIZON = "karma-forge"
LEGACY_PART_SLUGS: dict[str, str] = {
    "ui-kit": "ui_kit",
    "hub-registry": "hub_registry",
    "media-factory": "media_factory",
}
MEDIA_META_HUMOR_TOKENS: tuple[str, ...] = (
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
MEDIA_READABLE_JOKE_TOKENS: tuple[str, ...] = (
    "reads:",
    "says:",
    "sign reads",
    "sticker reads",
    "placard reads",
    "quote:",
)
CRITICAL_VISUAL_TARGETS: frozenset[str] = frozenset(
    {
        "assets/hero/chummer6-hero.png",
        "assets/pages/horizons-index.png",
        "assets/horizons/karma-forge.png",
    }
)
COMPOSITION_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{2,80}$")
TABLEAU_COMPOSITIONS = {"safehouse_table", "group_table"}
SURFACE_HEAVY_COMPOSITIONS = TABLEAU_COMPOSITIONS | {"desk_still_life", "dossier_desk", "loadout_table"}
ARCHITECTURE_HEAVY_TERMS: tuple[str, ...] = (
    "architecture",
    "architectural",
    "dependency injection",
    "repo",
    "topology",
    "control plane",
    "worker",
    "orchestration",
    "node",
)
MECHANICS_RECEIPT_KEYS: tuple[str, ...] = (
    "core_receipt_refs",
    "mechanics_receipt_refs",
    "receipt_refs",
    "source_receipt_refs",
)
MECHANICS_CLAIM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d+\s*d6(?:\s*(?:[+-]|plus|minus)\s*\d+)?\b", re.IGNORECASE), "dice_notation"),
    (re.compile(r"\broll\s+\d+\s*d6\b", re.IGNORECASE), "roll_dice_notation"),
    (re.compile(r"\b(?:\+\d+|-\d+)\s+dice\b", re.IGNORECASE), "dice_modifier"),
    (
        re.compile(
            r"\b(?:threshold|initiative|dice pool|damage value|armor penetration|soak|drain|edge|essence)\b[^.!?\n]{0,32}\b(?:\+?\-?\d+(?:[ps])?)\b",
            re.IGNORECASE,
        ),
        "named_mechanics_value",
    ),
    (re.compile(r"\b(?:dv|ap)\s*[:=]?\s*-?\d+(?:[ps])?\b", re.IGNORECASE), "dv_ap_value"),
)


def extract_json(text: str) -> dict[str, object]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty model response")
    decoder = json.JSONDecoder()
    for candidate in (raw, raw.removeprefix("```json").removesuffix("```").strip(), raw.removeprefix("```").removesuffix("```").strip()):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            loaded, _end = decoder.raw_decode(raw[index:])
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("response did not contain a JSON object")

LOCAL_ENV = load_local_env()
POLICY_ENV = load_runtime_overrides()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


def load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def trace(message: str) -> None:
    if not TRACE_ENABLED:
        return
    print(f"[chummer6-guide] {message}", file=sys.stderr, flush=True)


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def resolve_style_epoch(*, increment: bool) -> dict[str, object]:
    existing = load_json_file(STYLE_EPOCH_PATH)
    try:
        epoch = int(existing.get("epoch") or -1)
    except Exception:
        epoch = -1
    if increment or epoch < 0:
        epoch += 1
    pack = dict(STYLE_PACKS[epoch % len(STYLE_PACKS)])
    record: dict[str, object] = {
        "epoch": epoch,
        "run_id": f"style-{epoch:03d}",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        **pack,
    }
    write_json_file(STYLE_EPOCH_PATH, record)
    return record


def recent_scene_rows(*, limit: int = 10) -> list[dict[str, object]]:
    ledger = load_json_file(SCENE_LEDGER_PATH)
    rows = ledger.get("assets")
    if not isinstance(rows, list):
        return []
    cleaned = [dict(row) for row in rows if isinstance(row, dict)]
    return cleaned[-max(1, limit) :]


def recent_scene_rows_for_style_epoch(
    *,
    style_epoch: dict[str, object] | None,
    limit: int = 10,
    allow_fallback: bool = True,
) -> list[dict[str, object]]:
    ledger = load_json_file(SCENE_LEDGER_PATH)
    rows = ledger.get("assets")
    if not isinstance(rows, list):
        return []
    cleaned = [dict(row) for row in rows if isinstance(row, dict)]
    active = dict(style_epoch or {})
    if active:
        filtered = [
            row
            for row in cleaned
            if isinstance(row.get("style_epoch"), dict) and dict(row.get("style_epoch") or {}) == active
        ]
        if filtered:
            cleaned = filtered
        elif not allow_fallback:
            cleaned = []
    return cleaned[-max(1, limit) :]


def scene_ledger_summary(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for row in rows[-8:]:
        summary.append(
            {
                "target": str(row.get("target") or "").strip(),
                "composition": str(row.get("composition") or "").strip(),
                "cast_signature": str(row.get("cast_signature") or "").strip(),
                "subject": str(row.get("subject") or "").strip(),
            }
        )
    return summary


def variation_guardrails_for(target: str, rows: list[dict[str, object]]) -> list[str]:
    recent = scene_ledger_summary(rows)
    compositions = [entry.get("composition", "") for entry in recent if entry.get("composition")]
    rules: list[str] = [
        "Do not default to a medium-wide safehouse table unless the page absolutely depends on shared social geometry.",
        "Prefer a distinct scene family, cast count, and camera grammar over the nearest previous accepted banner.",
    ]
    if compositions:
        last = compositions[-1]
        rules.append(f"Do not reuse the most recent accepted composition family `{last}` for `{target}`.")
        safehouse_count = sum(1 for value in compositions if value == "safehouse_table")
        if safehouse_count >= 2:
            rules.append("Safehouse-table grammar is already overserved. Use prop-led, dossier, approval-rail, transit, street, archive, clinic, or service-rack grammar instead.")
    if target.endswith("README.md") or target.endswith("chummer6-hero.png"):
        rules.append("The landing hero must show visible trust pressure in Shadowrun life through a metahuman streetdoc / wounded runner / support-figure scene inside an improvised garage clinic, triage bay, getaway van, or patch-up space; not a quiet lone-operator still, clean hospital room, or generic meeting tableau.")
    if target.endswith("what-chummer6-is.png"):
        rules.append("Prefer an inspectable trust moment or operator relationship, not a generic group huddle.")
    if target.endswith("core.png"):
        rules.append("Core should be evidence-first: hands, dice, sheets, traces, and proof beat faces.")
    if target.endswith("horizons-index.png"):
        rules.append("Horizons index must show multiple future lanes, grounded street-level cyberpunk clue clusters, and branching plurality; do not solve it with atmosphere alone, a single corridor, a sparse road, or a central sign.")
    rules.extend(visual_contract_guardrails_for_target(target))
    return rules


def _contains_forbidden_public_copy(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return ""
    for phrase in FORBIDDEN_PUBLIC_COPY_PHRASES:
        if phrase in lowered:
            return phrase
    if "propose design changes" in lowered and "chummer6-design" in lowered:
        return "design_repo_redirect"
    if "fix" in lowered and "guide" in lowered and "first" in lowered:
        return "maintainer_imperative"
    return ""


def _mechanics_receipt_refs(value: object) -> tuple[str, ...]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key in MECHANICS_RECEIPT_KEYS:
            raw = value.get(key)
            if isinstance(raw, str):
                cleaned = raw.strip()
                if cleaned:
                    refs.append(cleaned)
            elif isinstance(raw, list):
                refs.extend(str(entry).strip() for entry in raw if str(entry).strip())
    elif isinstance(value, list):
        refs.extend(str(entry).strip() for entry in value if str(entry).strip())
    elif isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            refs.append(cleaned)
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        key = ref.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return tuple(deduped)


def _mechanics_claim_reason(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for pattern, label in MECHANICS_CLAIM_PATTERNS:
        if pattern.search(cleaned):
            return label
    return ""


def _mechanics_boundary_issues(
    value: object,
    *,
    scope: str,
    receipt_refs: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if isinstance(value, dict):
        local_receipts = receipt_refs + _mechanics_receipt_refs(value)
        for key, entry in value.items():
            lowered_key = str(key or "").strip().lower()
            if lowered_key in MECHANICS_RECEIPT_KEYS:
                continue
            child_scope = f"{scope}.{key}" if scope else str(key)
            issues.extend(_mechanics_boundary_issues(entry, scope=child_scope, receipt_refs=local_receipts))
        return issues
    if isinstance(value, list):
        for index, entry in enumerate(value):
            issues.extend(_mechanics_boundary_issues(entry, scope=f"{scope}[{index}]", receipt_refs=receipt_refs))
        return issues
    if isinstance(value, str) and not receipt_refs:
        reason = _mechanics_claim_reason(value)
        if reason:
            issues.append({"scope": scope, "reason": reason})
    return issues


def editorial_self_audit_text(
    text: str,
    *,
    fallback: str = "",
    context: str = "",
) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return str(fallback or "").strip()
    original_lowered = cleaned.lower()
    lowered = original_lowered
    audit_lowered = original_lowered
    for source, target in PUBLIC_COPY_REPLACEMENTS:
        if source in lowered:
            cleaned = re.sub(re.escape(source), target, cleaned, flags=re.IGNORECASE)
            lowered = cleaned.lower()
    audit_lowered = f"{original_lowered}\n{lowered}"
    forbidden = _contains_forbidden_public_copy(cleaned)
    if forbidden and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(phrase in audit_lowered for phrase in OVERPLAYED_SNARK_PHRASES) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(phrase in audit_lowered for phrase in WEAK_COPY_PHRASES + SOFT_OODA_PHRASES + PAGE_SOFT_FILLER_PHRASES) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(phrase in audit_lowered for phrase in PAGE_MATH_CERTAINTY_PHRASES) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(pattern.search(cleaned) for pattern in TOTALIZING_PUBLIC_MATH_PATTERNS) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(phrase in audit_lowered for phrase in PAGE_RISKY_SPECIFIC_CLAIMS + PAGE_RISKY_GAME_DETAIL_TOKENS) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(phrase in audit_lowered for phrase in OODA_OVERCLAIM_PHRASES) and fallback:
        return str(fallback or "").strip()
    if context.startswith("ooda:") and any(term in audit_lowered for term in OODA_RESTRICTED_TERMS) and fallback:
        return str(fallback or "").strip()
    if any(context.startswith(prefix) for prefix in ("hero:", "part:", "horizon:", "ooda:", "page:")) and any(
        phrase in audit_lowered for phrase in SECTION_OODA_DRIFT_PHRASES
    ) and fallback:
        return str(fallback or "").strip()
    if any(context.startswith(prefix) for prefix in ("hero:", "part:", "horizon:", "ooda:", "page:")) and re.search(
        r"\b20\d{2}\s*(?:[-/]|to)\s*20\d{2}\b|\b20\d{2}\b",
        cleaned,
        re.IGNORECASE,
    ) and fallback:
        return str(fallback or "").strip()
    if any(context.startswith(prefix) for prefix in ("hero:", "part:", "horizon:", "ooda:", "page:")) and re.search(
        r"\b(?:status|mode|lane|rule|dependency|compatibility)\b[^.!?\n]{0,24}\b(?:verified|passed|compatible)\b",
        lowered,
        re.IGNORECASE,
    ) and fallback:
        return str(fallback or "").strip()
    if context == "ooda:act:landing_tagline" and re.match(r"^(stop|start|grab|download|use)\b", lowered) and fallback:
        return str(fallback or "").strip()
    if context.startswith("page:") and any(phrase in audit_lowered for phrase in PAGE_RISKY_SPECIFIC_CLAIMS + PAGE_RISKY_GAME_DETAIL_TOKENS + PAGE_MATH_CERTAINTY_PHRASES + OODA_OVERCLAIM_PHRASES) and fallback:
        return str(fallback or "").strip()
    if context.startswith("page:") and any(pattern.search(cleaned) for pattern in TOTALIZING_PUBLIC_MATH_PATTERNS) and fallback:
        return str(fallback or "").strip()
    if any(context.startswith(prefix) for prefix in ("hero:", "part:", "horizon:", "page:", "ooda:")) and _mechanics_claim_reason(cleaned) and fallback:
        return str(fallback or "").strip()
    if context.startswith("page:") or context.startswith("ooda:"):
        if any(term in original_lowered for term in ARCHITECTURE_HEAVY_TERMS) and fallback:
            return str(fallback or "").strip()
    return cleaned


def strip_unbacked_mechanics_entries(
    entries: list[str],
    *,
    scope: str,
    receipt_refs: tuple[str, ...] = (),
) -> list[str]:
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

    cleaned: list[str] = []
    for index, entry in enumerate(entries):
        text = str(entry or "").strip()
        if not text:
            continue
        if (
            re.match(r"^[A-Z][A-Z0-9_]{2,}\s*[:=]\s*[A-Z0-9_-]{2,}$", text)
            or re.match(r"^[A-Z0-9_]{4,}$", text)
            or looks_like_machine_overlay_phrase(text)
        ):
            continue
        issues = _mechanics_boundary_issues(text, scope=f"{scope}[{index}]", receipt_refs=receipt_refs)
        if issues:
            continue
        cleaned.append(text)
    return cleaned


def media_asset_target(*, kind: str, item: dict[str, object]) -> str:
    if kind == "hero":
        return "assets/hero/chummer6-hero.png"
    slug = str(item.get("slug") or item.get("id") or item.get("title") or "").strip().lower().replace(" ", "-")
    if kind == "part":
        return f"assets/parts/{slug}.png"
    return f"assets/horizons/{slug}.png"


def media_easter_egg_allowed(*, kind: str, item: dict[str, object], contract: dict[str, object]) -> bool:
    target = media_asset_target(kind=kind, item=item)
    policy = str(contract.get("easter_egg_policy") or "").strip().lower()
    if policy in {"deny", "denied", "forbid", "forbidden", "none", "off"}:
        return False
    if policy in {"force", "showcase"}:
        return True
    return target in SPARSE_EASTER_EGG_ASSET_TARGETS


def media_humor_allowed(*, kind: str, item: dict[str, object], contract: dict[str, object]) -> bool:
    target = media_asset_target(kind=kind, item=item)
    policy = str(contract.get("humor_policy") or "").strip().lower()
    if policy in {"deny", "denied", "forbid", "forbidden", "none", "off"}:
        return False
    if policy in {"allow", "allowed", "showcase", "force"}:
        return True
    visual_contract = visual_contract_for_target(target)
    if visual_contract and not _boolish(visual_contract.get("humor_allowed"), default=True):
        return False
    return target in SPARSE_HUMOR_ASSET_TARGETS


def sanitize_media_humor(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    lowered = f" {cleaned.lower()} "
    if any(token in lowered for token in MEDIA_META_HUMOR_TOKENS):
        return ""
    if any(token in lowered for token in MEDIA_READABLE_JOKE_TOKENS):
        return ""
    if ("'" in cleaned or '"' in cleaned) and any(
        token in lowered for token in ("sticker", "sign", "placard", "shirt", "patch", "note", "label", "reads", "says")
    ):
        return ""
    if len(cleaned) > 140:
        return ""
    return cleaned


def contains_meta_humor_language(text: str) -> bool:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return False
    lowered = f" {cleaned.lower()} "
    return any(token in lowered for token in MEDIA_META_HUMOR_TOKENS) or any(
        token in lowered for token in MEDIA_READABLE_JOKE_TOKENS
    )


def _mentions_troll_motif(text: str) -> bool:
    lowered = " ".join(str(text or "").split()).strip().lower()
    if "troll" not in lowered:
        return False
    return any(
        token in lowered
        for token in ("sticker", "tattoo", "patch", "decal", "doodle", "mascot", "motif", "mark", "charm", "stamp", "seal", "pin", "pictogram", "figurine")
    )


def strip_media_easter_egg_clauses(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[,.;])\s+", cleaned)
    kept = [part.strip() for part in parts if part.strip() and not _mentions_troll_motif(part)]
    if kept:
        normalized = " ".join(kept)
        normalized = re.sub(r"\s+,", ",", normalized)
        normalized = re.sub(r"\s+\.", ".", normalized)
        normalized = re.sub(r"\s+;", ";", normalized)
        cleaned = normalized.strip(" ,;")
    if _mentions_troll_motif(cleaned):
        cleaned = re.sub(
            r"\bwith\s+(?:a|an|one)\s+[^,.!?;]*troll[^,.!?;]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b[a-z-]*troll[a-z-]*(?:\s+[a-z-]+){0,5}",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r"\s+\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,;")


def editorial_pack_audit(overrides: dict[str, object]) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    checked = 0

    def audit_mapping(scope: str, mapping: object, *, inherited_receipts: tuple[str, ...] = ()) -> None:
        nonlocal checked
        if not isinstance(mapping, dict):
            return
        local_receipts = inherited_receipts + _mechanics_receipt_refs(mapping)
        for key, value in mapping.items():
            lowered_key = str(key or "").strip().lower()
            if lowered_key.startswith("banned_") or lowered_key == "banned_terms":
                continue
            if isinstance(value, dict):
                audit_mapping(f"{scope}.{key}", value, inherited_receipts=local_receipts)
                continue
            if isinstance(value, list):
                for index, entry in enumerate(value):
                    entry_scope = f"{scope}.{key}[{index}]"
                    if isinstance(entry, dict):
                        audit_mapping(entry_scope, entry, inherited_receipts=local_receipts)
                        continue
                    if isinstance(entry, str):
                        checked += 1
                        forbidden = _contains_forbidden_public_copy(entry)
                        if forbidden:
                            issues.append({"scope": entry_scope, "reason": forbidden})
                        for mechanics_issue in _mechanics_boundary_issues(entry, scope=entry_scope, receipt_refs=local_receipts):
                            issues.append(mechanics_issue)
                continue
            if isinstance(value, str):
                checked += 1
                forbidden = _contains_forbidden_public_copy(value)
                if forbidden:
                    issues.append({"scope": f"{scope}.{key}", "reason": forbidden})
                for mechanics_issue in _mechanics_boundary_issues(value, scope=f"{scope}.{key}", receipt_refs=local_receipts):
                    issues.append(mechanics_issue)

    for section in ("pages", "parts", "horizons", "ooda", "section_ooda"):
        audit_mapping(section, overrides.get(section))

    summary = {
        "checked_fields": checked,
        "issues": issues,
        "status": "ok" if not issues else "failed",
    }
    if issues:
        scope_list = ", ".join(f"{row['scope']}:{row['reason']}" for row in issues[:8])
        raise RuntimeError(f"editorial_pack_audit_failed:{scope_list}")
    return summary


def scene_plan_pack_audit(overrides: dict[str, object]) -> dict[str, object]:
    media = overrides.get("media")
    if not isinstance(media, dict):
        return {"status": "skipped", "reason": "missing_media", "checked": 0}

    visual_overrides: dict[str, object] = {}
    overrides_path = EA_ROOT / "chummer6_guide" / "VISUAL_OVERRIDES.json"
    if overrides_path.exists():
        try:
            loaded = json.loads(overrides_path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        if isinstance(loaded, dict):
            visual_overrides = loaded

    checked = 0
    tableau = 0
    surface_heavy = 0
    invalid: list[dict[str, str]] = []
    critical_findings: list[dict[str, str]] = []

    def audit_row(scope: str, *, target: str, row: object) -> None:
        nonlocal checked, tableau, surface_heavy
        if not isinstance(row, dict):
            return
        contract = row.get("scene_contract")
        if not isinstance(contract, dict):
            return
        composition = str(contract.get("composition") or "").strip()
        if target:
            override = visual_overrides.get(target)
            if isinstance(override, dict):
                override_contract = override.get("scene_contract")
                override_comp = ""
                if isinstance(override_contract, dict):
                    override_comp = str(override_contract.get("composition") or "").strip()
                if override_comp:
                    composition = override_comp
        for reason in critical_visual_findings_for_target(target, row):
            critical_findings.append({"scope": scope, "reason": reason})
        if not composition:
            return
        checked += 1
        normalized = composition.lower().replace("-", "_")
        if normalized in TABLEAU_COMPOSITIONS:
            tableau += 1
        if normalized in SURFACE_HEAVY_COMPOSITIONS:
            surface_heavy += 1
        if not re.fullmatch(r"[a-z0-9_]{2,80}", normalized):
            invalid.append({"scope": scope, "composition": composition})

    audit_row("media.hero", target="assets/hero/chummer6-hero.png", row=media.get("hero"))
    for group in ("parts", "horizons"):
        mapping = media.get(group)
        if not isinstance(mapping, dict):
            continue
        for key, row in mapping.items():
            target = f"assets/{group}/{key}.png"
            audit_row(f"media.{group}.{key}", target=target, row=row)

    summary: dict[str, object] = {
        "status": "ok",
        "checked": checked,
        "tableau_count": tableau,
        "surface_heavy_count": surface_heavy,
        "invalid_compositions": invalid,
        "critical_target_findings": critical_findings,
    }
    if tableau > 2:
        raise RuntimeError(f"scene_plan_audit_failed:tableau_count:{tableau}")
    if surface_heavy > 5:
        raise RuntimeError(f"scene_plan_audit_failed:surface_heavy_count:{surface_heavy}")
    if invalid:
        raise RuntimeError(f"scene_plan_audit_failed:invalid_compositions:{invalid[:4]}")
    if critical_findings:
        scope_list = ", ".join(f"{row['scope']}:{row['reason']}" for row in critical_findings[:8])
        raise RuntimeError(f"scene_plan_audit_failed:critical_targets:{scope_list}")
    return summary


def assert_public_reader_safe(mapping: dict[str, object], *, context: str) -> None:
    for key, value in mapping.items():
        if not isinstance(value, str):
            continue
        forbidden = _contains_forbidden_public_copy(value)
        if forbidden:
            raise ValueError(f"forbidden public-copy phrase in {context}:{key}:{forbidden}")
    issues = _mechanics_boundary_issues(mapping, scope=context, receipt_refs=_mechanics_receipt_refs(mapping))
    if issues:
        first = issues[0]
        raise ValueError(f"unbacked mechanics claim in {first['scope']}:{first['reason']}")


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    if raw:
        return shlex.split(raw)
    defaults = {
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_humanizer.py"),
            "humanize",
            "--text",
            "{text}",
            "--target",
            "{target}",
        ],
    }
    browseract_names = {
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": (
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY",
        ),
    }
    required_workflow_refs = browseract_names.get(env_name)
    if required_workflow_refs and not any(env_value(name) for name in required_workflow_refs):
        return []
    return list(defaults.get(env_name, []))


def url_template(env_name: str) -> str:
    return env_value(env_name)


PARTS = load_part_canon()
HORIZONS = load_horizon_canon()
FAQ = load_faq_canon()
HELP = load_help_canon()
RELEASE = load_release_experience_canon()
TRUST = load_trust_content_canon()
PAGE_REGISTRY = load_page_registry()
MEDIA_BRIEFS = load_media_briefs()
PUBLIC_FEATURE_REGISTRY = load_public_feature_registry()
GUIDE_ROOT = Path("/docker/chummercomplete/Chummer6")
PUBLIC_SIGNAL_TAG_HINTS: tuple[tuple[str, str], ...] = (
    ("deterministic rules truth", "deterministic_truth"),
    ("receipts", "explain_receipts"),
    ("provenance", "provenance_receipts"),
    ("local-first", "local_first_play"),
    ("offline", "offline_play"),
    ("multiple rules eras", "multi_era_rulesets"),
    ("sr4", "sr4_support"),
    ("sr5", "sr5_support"),
    ("sr6", "sr6_support"),
    ("booster", "booster_participation"),
    ("participate", "booster_participation"),
    ("download", "download_now"),
    ("issue tracker", "public_feedback"),
    ("public guide", "public_guide"),
    ("horizon", "future_horizons"),
    ("dossier", "dossier_artifacts"),
    ("runsite", "runsite_artifacts"),
)


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    if value in (None, ""):
        return []
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []


def _boolish(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    cleaned = str(value or "").strip().lower()
    if cleaned in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if cleaned in {"0", "false", "no", "off", "deny", "denied", "forbid", "forbidden"}:
        return False
    return default


def visual_density_profile_name_for_target(target: str) -> str:
    normalized = str(target or "").replace("\\", "/").strip()
    page_types = PAGE_REGISTRY.get("page_types") if isinstance(PAGE_REGISTRY.get("page_types"), dict) else {}
    if normalized.endswith("assets/hero/chummer6-hero.png"):
        return str((page_types.get("root_story") or {}).get("visual_density_profile") or "first_contact_hero").strip()
    if normalized.endswith("README.md"):
        return str((page_types.get("root_story_github_readme") or {}).get("visual_density_profile") or "first_contact_hero").strip()
    if normalized.endswith("assets/pages/horizons-index.png"):
        return str((page_types.get("horizon_index") or {}).get("visual_density_profile") or "page_index").strip()
    if normalized.endswith("assets/horizons/karma-forge.png"):
        return "flagship_horizon"
    return ""


def visual_contract_for_target(target: str) -> dict[str, object]:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized in CRITICAL_VISUAL_TARGETS or normalized.endswith("README.md"):
        profile = asset_visual_profile(normalized)
        if profile:
            return profile
    contracts = MEDIA_BRIEFS.get("visual_contract") if isinstance(MEDIA_BRIEFS.get("visual_contract"), dict) else {}
    profile = visual_density_profile_name_for_target(normalized)
    return dict(contracts.get(profile) or {}) if profile else {}


def overlay_mode_for_target(target: str) -> str:
    contract = visual_contract_for_target(target)
    normalized_mode = (
        str(contract.get("required_overlay_mode") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if normalized_mode:
        return normalized_mode
    normalized_target = str(target or "").replace("\\", "/").strip()
    if normalized_target in {"assets/hero/chummer6-hero.png", "README.md"}:
        return "medscan_diagnostic"
    if normalized_target == "assets/pages/horizons-index.png":
        return "ambient_diegetic"
    if normalized_target == "assets/horizons/karma-forge.png":
        return "forge_review_ar"
    return ""


def fallback_finish_clause_for_target(target: str) -> str:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized in {"assets/hero/chummer6-hero.png", "README.md"}:
        return "illustrated cover-grade Shadowrun streetdoc poster, gritty garage-clinic props, metahuman runner-life pressure, dense practical clutter"
    if normalized == "assets/pages/horizons-index.png":
        return "illustrated cover-grade cyberpunk futures crossroads poster, branching districts, dense clue clusters, readable plurality"
    if normalized == "assets/horizons/karma-forge.png":
        return "illustrated cover-grade Shadowrun rules-forge poster, industrial approval machinery, dangerous motion, provenance pressure"
    return "cinematic 35mm, grounded prop-led still"


def visual_contract_guardrails_for_target(target: str) -> list[str]:
    contract = visual_contract_for_target(target)
    if not contract:
        return []
    rules: list[str] = []
    density = str(contract.get("density_target") or "").strip().lower()
    flash = str(contract.get("flash_level") or "").strip().lower()
    negative_space = str(contract.get("negative_space_cap") or "").strip().lower()
    person_count = str(contract.get("person_count_target") or "").strip().lower()
    overlay_mode = overlay_mode_for_target(target)
    if _boolish(contract.get("critical_style_overrides_shared_prompt_scaffold"), default=False):
        rules.append("For this flagship asset, let the poster epoch override the softer shared guide-still scaffold.")
    if _boolish(contract.get("style_epoch_force_only"), default=False):
        rules.append("Do not let this asset fall back to the softer secondary guide-still epoch.")
    if str(contract.get("critical_style_anchor") or "").strip():
        rules.append("Use the flagship poster style epoch here: illustrated cover-grade promo energy, Shadowrun street-life specificity, and lived-in grime instead of a tasteful editorial still.")
    if density == "high":
        rules.append("Keep this frame packed and layered with grounded clues in foreground, midground, and background.")
    if flash == "bold":
        rules.append("Push harder poster energy with stronger contrast, bolder silhouettes, and less tasteful restraint.")
    if negative_space == "low":
        rules.append("Avoid dead darkness, sparse corners, and calm negative-space voids.")
    if person_count == "duo_or_team":
        rules.append("Prefer two to four people with a visible operator relationship instead of one isolated figure.")
    elif person_count == "duo_preferred":
        rules.append("Prefer a visible reviewer, witness, or second active figure instead of one isolated operator.")
    if overlay_mode == "medscan_diagnostic":
        rules.append("Overlay OODA mode: medscan_diagnostic. Use a slim attribute rail, subsystem-bound status chips, and cyberware calibration/stability callouts instead of vague trust labels or torso-covering boxes.")
    elif overlay_mode == "ambient_diegetic":
        rules.append("Overlay OODA mode: ambient_diegetic. Use lane arcs, district markers, and path traces only; avoid city-wide diagnostic slabs or big floating boxes.")
    elif overlay_mode == "forge_review_ar":
        rules.append("Overlay OODA mode: forge_review_ar. Use edge-following approval rails, provenance seals, rollback vectors, and compact witness chips instead of generic workshop HUD rectangles.")
    overlay_priority = _string_list(contract.get("overlay_priority_order"))
    if overlay_priority:
        rules.append("Overlay priority order: " + "; ".join(overlay_priority) + ".")
    overlay_geometry = _string_list(contract.get("overlay_geometry"))
    if overlay_geometry:
        rules.append("Overlay geometry should prefer " + "; ".join(overlay_geometry) + ".")
    overlay_actionability_rule = str(contract.get("overlay_actionability_rule") or "").strip()
    if overlay_actionability_rule:
        rules.append(overlay_actionability_rule.rstrip(".") + ".")
    overlay_render_strategy = str(contract.get("overlay_render_strategy") or "").strip().replace("_", " ")
    if overlay_render_strategy:
        rules.append("Overlay render strategy: " + overlay_render_strategy.rstrip(".") + ".")
    render_layers = [str(entry).replace("_", " ") for entry in _string_list(contract.get("render_layers"))]
    if render_layers:
        rules.append("Overlay pipeline layers: " + "; ".join(render_layers) + ".")
    overlay_attachment_rule = str(contract.get("overlay_attachment_rule") or "").strip()
    if overlay_attachment_rule:
        rules.append(overlay_attachment_rule.rstrip(".") + ".")
    status_binding_rule = str(contract.get("status_binding_rule") or "").strip()
    if status_binding_rule:
        rules.append(status_binding_rule.rstrip(".") + ".")
    troll_markers = _string_list(contract.get("required_troll_markers"))
    if troll_markers:
        rules.append("The troll patient must read clearly through: " + "; ".join(troll_markers) + ".")
    render_detail = _string_list(contract.get("required_render_detail"))
    if render_detail:
        rules.append("Render detail must hold on: " + "; ".join(render_detail) + ".")
    world_markers = _string_list(contract.get("world_marker_bucket"))
    world_marker_minimum = str(contract.get("world_marker_minimum") or "").strip()
    if world_markers:
        prefix = f"Keep at least {world_marker_minimum} Shadowrun world markers visible" if world_marker_minimum else "Keep Shadowrun world markers visible"
        rules.append(prefix + ": " + "; ".join(world_markers[:4]) + ".")
        rules.append("At least one of those world markers should land as a lore crumb on a prop or wall: megacorp gear, critter ephemera, parabotany plate, corp scrip, or astral totem cue.")
    anchors = _string_list(contract.get("must_show_semantic_anchors"))
    if anchors:
        rules.append("Make these semantic anchors legible: " + "; ".join(anchors) + ".")
    blockers = _string_list(contract.get("must_not_show"))
    if blockers:
        rules.append("Do not drift into these failures: " + "; ".join(blockers) + ".")
    if not _boolish(contract.get("humor_allowed"), default=True):
        rules.append("Do not solve this asset with a sparse humor beat or cute visual joke.")
    if not _boolish(contract.get("pseudo_text_allowed"), default=True):
        rules.append("Do not invent pseudo-text, readable signboards, or fake lettering.")
    if overlay_mode:
        rules.append("Overlay geometry should prefer rails, brackets, spline traces, halos, seam-following markers, and capsule chips over large translucent rectangles.")
    return rules


def visual_contract_prompt_clause(target: str) -> str:
    rules = visual_contract_guardrails_for_target(target)
    if not rules:
        return ""
    return " ".join(rules[:4]).strip()


def _dedupe_casefolded(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _row_text_bundle(row: dict[str, object]) -> str:
    scene = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    values: list[str] = []
    for key in ("badge", "title", "subtitle", "kicker", "note", "visual_prompt", "overlay_hint"):
        cleaned = str(row.get(key) or "").strip()
        if cleaned:
            values.append(cleaned)
    for key in ("subject", "environment", "action", "metaphor", "composition", "humor"):
        cleaned = str(scene.get(key) or "").strip()
        if cleaned:
            values.append(cleaned)
    for key in ("props", "overlays"):
        values.extend(_string_list(scene.get(key)))
    for key in ("visual_motifs", "overlay_callouts"):
        values.extend(_string_list(row.get(key)))
    return " ".join(values).strip().lower()


def _is_sparse_shadowrun_scene_text(text: str, *, minimum_tokens: int = 65) -> bool:
    return len(str(text or "").split()) < minimum_tokens


def _has_visible_relationship_signal(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    phrases = (
        " and ",
        " with ",
        " alongside ",
        " reviewer",
        " witness",
        " teammate",
        " support figure",
        " assistant",
        " streetdoc",
        " runner",
        " duo",
        " team",
        " operator relationship",
    )
    hits = sum(1 for phrase in phrases if phrase in lowered)
    return hits >= 2 or ("streetdoc" in lowered and "runner" in lowered)


def _looks_like_statusish_overlay_signal(text: str) -> bool:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if "|" in cleaned or "_" in cleaned:
        return True
    if re.search(r"\b0x[0-9a-f]+\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+)?%\b", cleaned):
        return True
    if re.search(r"\bv\d+(?:\.\d+)*\b", lowered):
        return True
    if re.match(r"^[A-Z]{2,}(?:-[A-Z0-9]{1,})+$", cleaned):
        return True
    status_tokens = (
        "verified",
        "validated",
        "status:",
        "hash verified",
        "source truth",
        "artifact ready",
        "prototype logic",
        "governed ruleset evolution",
        "metadata hud",
    )
    if any(token in lowered for token in status_tokens):
        return True
    letters = [char for char in cleaned if char.isalpha()]
    if letters and sum(1 for char in letters if char.isupper()) >= max(6, int(len(letters) * 0.75)):
        return True
    return False


def _critical_target_phrase_groups(target: str) -> tuple[tuple[str, ...], ...]:
    if target == "assets/hero/chummer6-hero.png":
        return (
            ("streetdoc", "garage clinic", "patch-up bay", "triage bench", "getaway van triage"),
            ("troll", "troll patient", "hairy troll", "tusks", "dermal texture"),
            ("runner", "wounded runner", "support figure", "assistant", "teammate"),
            ("cyberware", "med-gel", "tool chest", "jury-rigged med rig", "work lamp"),
            ("BOD", "AGI", "REA", "ESS", "EDGE", "UPGRADING", "CYBERLIMB CALIBRATION"),
        )
    if target == "assets/pages/horizons-index.png":
        return (
            ("multiple lanes", "branching futures", "district split", "market of futures", "interchange"),
            ("street-level cyberpunk", "wet street", "wires", "crowd clue", "district"),
            ("multiple clues", "plurality", "different paths", "differentiated domains", "branching"),
            ("Bug City", "Arcology", "Barrens", "Underground", "Chicago", "Puyallup"),
        )
    if target == "assets/horizons/karma-forge.png":
        return (
            ("rules lab", "approval rail", "consequence bench", "rollback rig", "rulesmith"),
            ("reviewer", "witness", "approval", "provenance"),
            ("DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK"),
            ("cassette", "seal", "compatibility arc", "forged rules packet"),
        )
    return ()


def _critical_target_banned_compositions(target: str) -> set[str]:
    base = {
        "single_protagonist",
        "solo_operator",
        "single_person_dim_bay",
        "brooding_profile",
        "generic_console_tinkering",
        "empty_road_ambience",
        "sparse_corridor_single_marker",
        "quiet_desk_still_life",
        "glow_void_operator",
        "paperwork_tableau",
    }
    if target == "assets/hero/chummer6-hero.png":
        return base | {"city_edge", "service_rack", "desk_still_life", "dossier_desk", "clean_exam_room"}
    if target == "assets/pages/horizons-index.png":
        return base | {"city_edge", "transit_checkpoint", "service_rack"}
    if target == "assets/horizons/karma-forge.png":
        return base | {"desk_still_life", "dossier_desk", "service_rack", "city_edge", "workshop", "workshop_bench", "group_table", "safehouse_table"}
    return base


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
        "source truth verified",
        "artifact ready for print",
        "entry point validated",
        "zero_drift",
        "hash_verified",
        "lua_driven",
        "mesh_stability",
        "debug text",
        "layout text",
        "status stamp",
        "readable text",
        "typography",
        "metadata hud",
        "dossier metadata hud",
        "prototype logic",
        "rules-truth",
        "hud-style",
        "data-source labels",
        "biometric lock icons",
        "integrity signatures",
        "build timestamps",
    )
    if any(token in lowered for token in banned_tokens):
        return True
    if re.search(r"\b0x[0-9a-f]+\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+)?%\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+){1,}\b", lowered) and any(ch.isalpha() for ch in lowered):
        return True
    if ("'" in lowered or '"' in lowered) and (
        re.search(r"['\"][A-Z0-9 _-]{3,}['\"]", str(text or ""))
        or re.search(r"['\"][A-Za-z][^'\"]{2,}['\"]", str(text or ""))
    ):
        return True
    return False


def looks_like_status_label(text: str) -> bool:
    cleaned_text = " ".join(str(text or "").split()).strip()
    if not cleaned_text:
        return False
    lowered = cleaned_text.lower()
    if contains_machine_overlay_language(cleaned_text):
        return True
    if "|" in cleaned_text or "_" in cleaned_text:
        return True
    if re.search(r"\bv\d+(?:\.\d+)*\b", lowered):
        return True
    if re.match(r"^[A-Z]{2,}(?:-[A-Z0-9]{1,})+$", cleaned_text):
        return True
    return False


def critical_visual_findings_for_target(target: str, row: object) -> list[str]:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized not in CRITICAL_VISUAL_TARGETS or not isinstance(row, dict):
        return []
    contract = visual_contract_for_target(normalized)
    overlay_mode = overlay_mode_for_target(normalized)
    scene = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    composition = str(scene.get("composition") or "").strip().lower().replace("-", "_")
    props = _dedupe_casefolded(_string_list(scene.get("props")))
    overlays = _dedupe_casefolded(_string_list(scene.get("overlays")))
    motifs = _dedupe_casefolded(_string_list(row.get("visual_motifs")))
    callouts = _dedupe_casefolded(_string_list(row.get("overlay_callouts")))
    overlay_signals = _dedupe_casefolded(overlays + callouts)
    combined = _row_text_bundle(row)
    is_sparse_scene_text = _is_sparse_shadowrun_scene_text(combined, minimum_tokens=65)
    allowed_overlay_tokens = {
        str(entry).strip().casefold()
        for entry in (
            _string_list(contract.get("required_overlay_schema"))
            + _string_list(contract.get("required_status_labels"))
            + (
                [
                    "Wound stabilized",
                    "Cyberlimb calibration",
                    "Neural link resync",
                ]
                if normalized == "assets/hero/chummer6-hero.png"
                else []
            )
            + (
                [
                    "Approval rail",
                    "Provenance seal",
                    "Rollback vector",
                    "Witness lock",
                    "Revert cost",
                    "Compatibility arc",
                ]
                if normalized == "assets/horizons/karma-forge.png"
                else []
            )
        )
        if str(entry).strip()
    }
    findings: list[str] = []

    if not composition:
        findings.append("critical_composition:missing")
    if composition in _critical_target_banned_compositions(normalized):
        findings.append(f"critical_composition:{composition}")
    if str(contract.get("density_target") or "").strip().lower() == "high" and len(props) < 4 and len(motifs) < 4:
        findings.append("critical_density:too_sparse")
    overlay_density = str(contract.get("required_overlay_density") or contract.get("overlay_density") or "").strip().lower()
    overlay_min = 4 if overlay_density == "high" else 3 if overlay_density == "medium" else 2
    if len(overlay_signals) < overlay_min:
        findings.append(f"critical_overlays:below_{overlay_min}")
    person_target = str(contract.get("required_person_count") or contract.get("person_count_target") or "").strip().lower()
    if person_target in {"duo_or_team", "duo_preferred"} and not _has_visible_relationship_signal(combined):
        findings.append("critical_cast:missing_visible_relationship")
    for token_group in _critical_target_phrase_groups(normalized):
        if not any(str(token).casefold() in combined for token in token_group):
            findings.append(f"critical_anchor_missing:{token_group[0]}")
    if normalized == "assets/hero/chummer6-hero.png":
        if not any(token in combined for token in ("troll", "troll patient", "hairy troll", "tusks", "dermal", "scarred skin")):
            findings.append("critical_cast:missing_troll_patient")
        if not any(token in combined for token in ("orc", "ork", "troll", "elf", "dwarf", "metahuman")):
            findings.append("critical_lore:missing_metahuman_cue")
        if not any(token in combined for token in ("garage", "tool chest", "lift bay", "tarp", "extension cord", "work lamp", "van")):
            findings.append("critical_lore:missing_streetdoc_garage_clinic")
        if not any(token in combined for token in ("streetdoc", "clinician", "stabilizing", "triage", "patch-up", "calibrating cyberware")):
            findings.append("critical_scene:missing_clinical_action")
        if not any(token in combined for token in ("cyberware", "cyberlimb", "implant", "augment", "calibration", "surgery", "med-gel")):
            findings.append("critical_scene:missing_cyberware_surgery")
        if not any(token in combined for token in ("hair strands", "matted hair", "coarse hair", "scarred skin", "dermal texture")):
            findings.append("critical_detail:missing_troll_microtexture")
        if not any(token in combined for token in ("bod", "agi", "rea", "str", "ess", "edge", "upgrading")):
            findings.append("critical_overlay:missing_attribute_rail")
        if is_sparse_scene_text:
            if not any(
                token in combined
                for token in (
                    "ares",
                    "renraku",
                    "horizon",
                    "aztechnology",
                    "shiawase",
                    "saeder-krupp",
                    "saeder krupp",
                    "evo",
                    "wuxing",
                )
            ):
                findings.append("critical_lore:missing_megacorp_footprint")
            if not any(
                token in combined
                for token in (
                    "devil rat",
                    "barghest",
                    "hell hound",
                    "hellhound",
                    "blood orchid",
                    "paper lotus",
                    "ward scar",
                    "ward",
                    "totem",
                    "astral",
                )
            ):
                findings.append("critical_lore:missing_shamanic_or_critter_crumb")
            if not any(
                token in combined
                for token in (
                    "rat",
                    "rat trap",
                    "rat tracks",
                    "vermin",
                    "stain",
                    "crash",
                    "infection",
                    "dry blood",
                    "cough",
                    "cough syrup",
                    "stim",
                    "med waste",
                    "spit",
                    "scarred",
                    "mold",
                )
            ):
                findings.append("critical_scene:missing_hardship_beat")
        if overlay_mode == "medscan_diagnostic" and not any(
            token in combined
            for token in ("medscan", "diagnostic rail", "wound stabilized", "cyberlimb calibration", "neural link resync", "stability indicator")
        ):
            findings.append("critical_overlay:missing_medscan_posture")
    if normalized == "assets/horizons/karma-forge.png":
        if "table" in combined and any(token in combined for token in ("sitting", "seated", "paperwork")):
            findings.append("critical_scene:tableau_not_forge")
        if not any(token in combined for token in ("approval rail", "rollback rig", "provenance seal", "rules lab", "consequence bench")):
            findings.append("critical_lore:missing_forge_semantics")
        if not any(token in combined for token in ("pressure", "danger", "volatile", "consequence", "rollback", "witness lock")):
            findings.append("critical_scene:missing_pressure")
        if any(token in combined for token in ("quiet workshop", "workshop bench", "workbench", "paperwork workshop", "generic workshop")):
            findings.append("critical_scene:generic_workshop_drift")
        if not any(token in combined for token in ("standing", "in motion", "forcing", "feeding", "locking", "active motion", "reconciling")):
            findings.append("critical_scene:missing_action_posture")
        if overlay_mode == "forge_review_ar" and not any(
            token in combined
            for token in ("approval rail", "provenance seal", "rollback vector", "witness lock", "revert cost", "compatibility arc")
        ):
            findings.append("critical_overlay:missing_forge_review_ar")
    if not _boolish(contract.get("humor_allowed"), default=True) and str(scene.get("humor") or "").strip():
        findings.append("critical_humor:forbidden")
    if not _boolish(contract.get("pseudo_text_allowed"), default=True):
        offending = next((entry for entry in overlay_signals if _looks_like_statusish_overlay_signal(entry)), "")
        if offending and offending.casefold() not in allowed_overlay_tokens:
            findings.append(f"critical_pseudo_text:{offending}")
    return findings
WEAK_COPY_PHRASES: tuple[str, ...] = (
    "toolkit",
    "management suite",
    "industrial-grade",
    "foundation",
    "foundations first",
    "digital handshake",
    "background systems",
    "keeping the lights on",
    "designed to make",
    "we are building",
    "we're building",
    "long-range plans ready",
    "works perfectly",
    "absolute rules-certainty",
    "absolute rules certainty",
    "guaranteed",
    "zero-hallucination",
    "hallucinates the math",
    "hallucinating the math",
)


def guide_excerpt_context_enabled() -> bool:
    raw = str(os.environ.get("CHUMMER6_GUIDE_INCLUDE_EXISTING_EXCERPTS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _public_card_rows() -> list[dict[str, object]]:
    cards = PUBLIC_FEATURE_REGISTRY.get("cards") or []
    return [dict(row) for row in cards if isinstance(row, dict)]


def _public_card_buckets(*bucket_names: str, audience: str = "public", limit: int = 6) -> list[str]:
    wanted = {str(name).strip() for name in bucket_names if str(name).strip()}
    snippets: list[str] = []
    for row in _public_card_rows():
        if wanted and str(row.get("bucket") or "").strip() not in wanted:
            continue
        if audience and str(row.get("audience") or "").strip() not in {audience, ""}:
            continue
        parts = [
            str(row.get("title") or "").strip(),
            str(row.get("summary") or "").strip(),
            str(row.get("pain") or "").strip(),
            str(row.get("payoff") or "").strip(),
            str(row.get("badge") or "").strip(),
        ]
        compact = " ".join(part for part in parts if part).strip()
        if compact:
            snippets.append(compact)
        if len(snippets) >= max(1, limit):
            break
    return snippets


def page_supporting_context(page_id: str) -> list[str]:
    page = str(page_id or "").strip()
    faq_questions = []
    for section in FAQ.values():
        if not isinstance(section, dict):
            continue
        for entry in section.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            question = str(entry.get("question") or "").strip()
            if question:
                faq_questions.append(question)
    buckets_map = {
        "readme": ("what_you_can_do_today", "why_this_feels_different", "whats_real_now"),
        "start_here": ("what_you_can_do_today", "why_this_feels_different", "whats_real_now"),
        "what_chummer6_is": ("what_you_can_do_today", "why_this_feels_different"),
        "faq": ("what_you_can_do_today", "whats_real_now"),
        "how_can_i_help": ("what_you_can_do_today", "release_shelf"),
        "current_phase": ("whats_real_now", "coming_next"),
        "current_status": ("whats_real_now", "release_shelf"),
        "public_surfaces": ("what_you_can_do_today", "release_shelf"),
        "parts_index": ("choose_your_lane",),
        "horizons_index": ("coming_next",),
        "where_to_go_deeper": ("release_shelf",),
    }
    snippets = _public_card_buckets(*buckets_map.get(page, ()), limit=6)
    if page in {"readme", "start_here", "what_chummer6_is", "current_phase", "current_status", "public_surfaces"}:
        snippets = [
            snippet
            for snippet in snippets
            if not any(
                token in snippet.lower()
                for token in (
                    "get the poc",
                    "current drop",
                    "registered soon",
                    "sign in to follow",
                    "deterministic rules truth",
                )
            )
        ]
    if page in {"public_surfaces", "where_to_go_deeper"}:
        snippets.extend(f"FAQ: {question}" for question in faq_questions[:3])
    if page == "faq":
        snippets.extend(f"FAQ: {question}" for question in faq_questions[:6])
    if page == "how_can_i_help":
        ctas = HELP.get("primary_ctas") if isinstance(HELP, dict) else []
        snippets.extend(str(entry).strip() for entry in ctas if str(entry).strip())
    if not snippets and page in {"readme", "start_here", "what_chummer6_is", "current_phase", "current_status", "public_surfaces"}:
        curated_fallbacks = {
            "readme": [
                "Start with the guide, not with assumptions about a working product.",
                "If you find a proof shelf or rough artifact, treat it as a trace of the idea rather than support.",
            ],
            "start_here": [
                "See what is real now before you trust any lucky trace.",
                "Start with the guide and horizon shelf, not with a fantasy about a finished tool.",
            ],
            "what_chummer6_is": [
                "This is an idea about inspectable Shadowrun math, not a dependable app surface.",
                "Any visible artifact matters less than the direction and the receipts it tries to earn.",
            ],
            "current_phase": [
                "Trust work and visible reasoning still come before polish.",
                "The work is still about making the idea inspectable before pretending the product is ready.",
            ],
            "current_status": [
                "The reliable public story is still the guide, the horizon shelf, and a few rough traces.",
                "Any concrete artifact may still break, move, or vanish without ceremony.",
            ],
            "public_surfaces": [
                "The guide, horizon shelf, and issue tracker are the deliberate public surfaces.",
                "Anything else should be read as a rough trace, not as a dependable product path.",
            ],
        }
        snippets = list(curated_fallbacks.get(page, []))
    return snippets[:8]


def faq_page_source() -> str:
    faq_questions: list[str] = []
    for section in FAQ.values():
        if not isinstance(section, dict):
            continue
        for entry in section.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            question = " ".join(str(entry.get("question") or "").split()).strip()
            if question:
                faq_questions.append(question)
    trust_data = TRUST if isinstance(TRUST, dict) else {}
    trust_questions: list[str] = []
    for page in trust_data.get("faq_pages") or []:
        if not isinstance(page, dict):
            continue
        for section in page.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for entry in section.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                question = " ".join(str(entry.get("question") or "").split()).strip()
                if question:
                    trust_questions.append(question)
    deduped_questions = list(dict.fromkeys(trust_questions + faq_questions))
    joined = "; ".join(deduped_questions[:6]).strip()
    if joined:
        joined = f" Common questions include: {joined}."
    return (
        "Answer the obvious public-reader questions in plain language: can I use this now, why trust it, what is rough, "
        "and what should I click next." + joined
    )


def help_page_source() -> str:
    help_data = HELP if isinstance(HELP, dict) else {}
    release_data = RELEASE if isinstance(RELEASE, dict) else {}
    trust_data = TRUST if isinstance(TRUST, dict) else {}
    feedback_lane = " ".join(str(help_data.get("public_feedback_lane") or "").split()).strip()
    ctas = [str(entry).strip() for entry in help_data.get("primary_ctas") or [] if str(entry).strip()]
    release_summary = " ".join(str(release_data.get("release_notes_summary") or "").split()).strip()
    update_summary = " ".join(str(release_data.get("update_posture_summary") or "").split()).strip()
    help_intro = ""
    help_actions: list[str] = []
    for page in trust_data.get("trust_pages") or []:
        if not isinstance(page, dict) or str(page.get("id") or "").strip() != "help":
            continue
        help_intro = " ".join(str(page.get("intro") or "").split()).strip()
        help_actions = [
            str(entry.get("label") or "").strip()
            for entry in page.get("actions") or []
            if isinstance(entry, dict) and str(entry.get("label") or "").strip()
        ]
        break
    cta_text = "; ".join(ctas[:3]).strip()
    trust_action_text = "; ".join(help_actions[:3]).strip()
    joined_bits = [bit for bit in (feedback_lane, cta_text, release_summary, update_summary, help_intro, trust_action_text) if bit]
    tail = f" Current public actions: {'; '.join(joined_bits)}." if joined_bits else ""
    return (
        "Explain how a normal human can help right now without sounding like operator onboarding. "
        "Keep it on public feedback, current visible actions, and honest expectations." + tail
    )


def part_supporting_context(part_id: str) -> list[str]:
    part = str(part_id or "").strip()
    buckets_map = {
        "core": ("why_this_feels_different", "whats_real_now"),
        "ui": ("what_you_can_do_today", "release_shelf"),
        "mobile": ("what_you_can_do_today", "whats_real_now"),
        "hub": ("what_you_can_do_today", "release_shelf"),
        "design": ("coming_next",),
        "ui-kit": ("what_you_can_do_today",),
        "hub-registry": ("featured_artifacts", "release_shelf"),
        "media-factory": ("featured_artifacts",),
    }
    snippets = _public_card_buckets(*buckets_map.get(part, ()), limit=6)
    return snippets[:8]


def read_markdown_excerpt(relative_path: str, *, limit: int = 360) -> str:
    if not guide_excerpt_context_enabled():
        return ""
    path = GUIDE_ROOT / relative_path
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    def scrub(line: str) -> str:
        cleaned = line.strip()
        cleaned = re.sub(r"^#+\s*", "", cleaned)
        cleaned = re.sub(r"^>\s*", "", cleaned)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        cleaned = re.sub(r"`([^`]+)`", lambda m: m.group(1), cleaned)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", lambda m: m.group(1), cleaned)
        cleaned = re.sub(r"\*([^*]+)\*", lambda m: m.group(1), cleaned)
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", lambda m: m.group(1), cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" -")
    lines: list[str] = []
    for raw in text.splitlines():
        line = scrub(raw)
        if not line:
            continue
        if line.startswith("_Last synced:") or line.startswith("_Derived from:"):
            continue
        lines.append(line)
        if sum(len(row) for row in lines) >= limit:
            break
    return " ".join(lines)[:limit].strip()


def horizon_rollout_context(name: str, item: dict[str, object]) -> dict[str, str]:
    if name != BOOSTER_REFERENCE_HORIZON:
        return {
            "access_posture": "",
            "resource_burden": "",
            "booster_nudge": "",
            "free_later_intent": "",
            "booster_api_scope_note": "",
            "booster_outcome_note": "",
        }
    return {
        "access_posture": str(item.get("access_posture", "")).strip(),
        "resource_burden": str(item.get("resource_burden", "")).strip(),
        "booster_nudge": str(item.get("booster_nudge", "")).strip(),
        "free_later_intent": str(item.get("free_later_intent", "")).strip(),
        "booster_api_scope_note": "Booster here means we may consume your API-backed capacity for development work. Normal product/UI use on your account stays unaffected unless you built your own API-side tooling around that same capacity.",
        "booster_outcome_note": "The promise is that we may spend the API capacity on this expensive lane, not that it will reliably produce something useful or shippable.",
    }


def short_sentence(text: str, *, limit: int = 160) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    for splitter in (". ", "! ", "? ", ": "):
        head, sep, _tail = cleaned.partition(splitter)
        if sep and head.strip():
            cleaned = head.strip()
            break
    if cleaned.lower().startswith("chummer6 "):
        cleaned = cleaned[len("chummer6 ") :].strip()
    return cleaned[:limit].rstrip(" ,;:-")


def ensure_required_chummer6_skills(*, force: bool = False) -> dict[str, object]:
    global SKILL_BOOTSTRAP_STATUS
    if SKILL_BOOTSTRAP_STATUS is not None and not force:
        return SKILL_BOOTSTRAP_STATUS
    scripts_root = str(EA_ROOT / "scripts")
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    from bootstrap_chummer6_guide_skill import ensure_local_skill_payloads

    skills_service = getattr(EA_CONTAINER, "skills", None) if EA_CONTAINER is not None else None
    state = ensure_local_skill_payloads(
        required_keys=REQUIRED_CHUMMER6_SKILL_KEYS,
        skills=skills_service,
    )
    missing = [str(value).strip() for value in (state.get("missing_skill_keys") or []) if str(value).strip()]
    if missing:
        raise RuntimeError("missing_chummer6_skills:" + ",".join(missing))
    SKILL_BOOTSTRAP_STATUS = state
    return state


def _ea_orchestrator():
    global EA_CONTAINER, EA_ORCHESTRATOR
    if EA_ORCHESTRATOR is not None:
        return EA_ORCHESTRATOR
    app_root = str(EA_ROOT / "ea")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    scripts_root = str(EA_ROOT / "scripts")
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    from app.container import build_container

    EA_CONTAINER = build_container()
    ensure_required_chummer6_skills(force=True)
    EA_ORCHESTRATOR = EA_CONTAINER.orchestrator
    return EA_ORCHESTRATOR


def ea_json(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    skill_key: str = PUBLIC_WRITER_SKILL_KEY,
) -> dict[str, object]:
    app_root = str(EA_ROOT / "ea")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    from app.domain.models import TaskExecutionRequest
    from app.services.orchestrator import AsyncExecutionQueuedError

    def execute_request():
        return _ea_orchestrator().execute_task_artifact(
            TaskExecutionRequest(
                skill_key=skill_key,
                text=prompt,
                principal_id=f"ea-{skill_key}-worker",
                goal=f"Generate a structured JSON packet for the {skill_key} worker.",
                input_json={
                    "model": model,
                    "generation_instruction": "Return JSON only. No markdown fences or commentary.",
                    "mime_type": "application/json",
                },
            )
        )

    def drain_queued_session(session_id: str) -> dict[str, object]:
        orchestrator = _ea_orchestrator()
        deadline = time.time() + 300.0
        last_artifact = None
        while time.time() < deadline:
            snapshot = orchestrator.fetch_session(session_id)
            if snapshot is not None:
                session_row = getattr(snapshot, "session", None)
                session_status = str(getattr(session_row, "status", "") or "").strip().lower()
                snapshot_artifacts = list(getattr(snapshot, "artifacts", []) or [])
                if session_status == "completed":
                    artifact = snapshot_artifacts[-1] if snapshot_artifacts else last_artifact
                    if artifact is None:
                        raise RuntimeError(f"queued_task_completed_without_artifact:{session_id}")
                    structured = dict(getattr(artifact, "structured_output_json", {}) or {})
                    if structured:
                        if set(structured.keys()) == {"result"} and isinstance(structured.get("result"), dict):
                            return dict(structured.get("result") or {})
                        return structured
                    return extract_json(artifact.content)
                if session_status in {"failed", "denied", "awaiting_human", "waiting_human", "awaiting_approval", "waiting_approval"}:
                    raise RuntimeError(f"queued_task_stopped:{session_status}:{session_id}")
                queue_rows = [
                    row
                    for row in list(getattr(snapshot, "queue_items", []) or [])
                    if str(getattr(row, "state", "") or "").strip().lower() == "queued"
                ]
                for row in queue_rows:
                    artifact = orchestrator.run_queue_item(str(getattr(row, "queue_id", "") or ""), lease_owner="inline")
                    if artifact is not None:
                        last_artifact = artifact
            time.sleep(0.25)
        raise RuntimeError(f"queued_task_timeout:{session_id}")

    try:
        artifact = execute_request()
        structured = dict(getattr(artifact, "structured_output_json", {}) or {})
        if structured:
            if set(structured.keys()) == {"result"} and isinstance(structured.get("result"), dict):
                return dict(structured.get("result") or {})
            return structured
        return extract_json(artifact.content)
    except AsyncExecutionQueuedError as exc:
        return drain_queued_session(exc.session_id)
    except ValueError as exc:
        if str(exc).startswith("skill_not_found:"):
            ensure_required_chummer6_skills(force=True)
            try:
                artifact = execute_request()
            except AsyncExecutionQueuedError as queued_exc:
                return drain_queued_session(queued_exc.session_id)
            structured = dict(getattr(artifact, "structured_output_json", {}) or {})
            if structured:
                if set(structured.keys()) == {"result"} and isinstance(structured.get("result"), dict):
                    return dict(structured.get("result") or {})
                return structured
            return extract_json(artifact.content)
        raise


def default_text_model() -> str:
    return (
        env_value("CHUMMER6_TEXT_MODEL")
        or env_value("CHUMMER6_TEXT_LANE")
        or DEFAULT_MODEL
    )


def execution_text_model(model: str) -> str:
    selected = str(model or "").strip() or DEFAULT_MODEL
    if selected in {"ea-groundwork", "groundwork"}:
        return env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-2.5-flash"
    return selected


def chat_json(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    skill_key: str = PUBLIC_WRITER_SKILL_KEY,
) -> dict[str, object]:
    global TEXT_PROVIDER_USED
    order_raw = str(os.environ.get("CHUMMER6_TEXT_PROVIDER_ORDER") or LOCAL_ENV.get("CHUMMER6_TEXT_PROVIDER_ORDER") or "ea").strip()
    order = [entry.strip().lower() for entry in order_raw.split(",") if entry.strip()]
    unsupported = [
        provider
        for provider in order
        if provider not in {"ea", "planner", "skill", "gemini", "gemini_vortex"}
    ]
    if unsupported:
        raise RuntimeError(
            "unsupported_chummer6_text_provider:" + ",".join(unsupported)
        )
    selected_model = str(model or "").strip() or default_text_model()
    payload = ea_json(prompt, model=execution_text_model(selected_model), skill_key=skill_key)
    TEXT_PROVIDER_USED = "ea-groundwork" if selected_model == "ea-groundwork" else "ea"
    return payload


def humanizer_available() -> bool:
    explicit_env_names = [
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND",
        "CHUMMER6_TEXT_HUMANIZER_COMMAND",
        "CHUMMER6_BROWSERACT_HUMANIZER_URL_TEMPLATE",
        "CHUMMER6_TEXT_HUMANIZER_URL_TEMPLATE",
        "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID",
        "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY",
    ]
    return any(env_value(name) for name in explicit_env_names)


def humanizer_required() -> bool:
    raw = env_value("CHUMMER6_TEXT_HUMANIZER_REQUIRED")
    if raw:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return False


def _browseract_humanizer_script_path() -> str:
    return str(EA_ROOT / "scripts" / "chummer6_browseract_humanizer.py")


def external_humanizer_ready() -> bool:
    global HUMANIZER_EXTERNAL_READY
    if HUMANIZER_EXTERNAL_LOCKED_OUT:
        return False
    if HUMANIZER_EXTERNAL_READY is not None:
        return HUMANIZER_EXTERNAL_READY
    if not humanizer_available():
        HUMANIZER_EXTERNAL_READY = False
        return False
    command = shlex_command("CHUMMER6_BROWSERACT_HUMANIZER_COMMAND")
    script_path = _browseract_humanizer_script_path()
    if command[:2] == ["python3", script_path]:
        try:
            completed = subprocess.run(
                ["python3", script_path, "check"],
                check=False,
                text=True,
                capture_output=True,
                timeout=min(60, humanizer_timeout_seconds()),
            )
            if completed.returncode == 0:
                HUMANIZER_EXTERNAL_READY = True
                return True
            detail = (completed.stdout or completed.stderr or "browseract_humanizer_unhealthy").strip()
            lock_out_external_humanizer(detail[:400])
            return False
        except Exception as exc:
            lock_out_external_humanizer(str(exc))
            return False
    HUMANIZER_EXTERNAL_READY = True
    return True


def humanizer_lockout_reason() -> str:
    return HUMANIZER_EXTERNAL_LOCKOUT_REASON


def lock_out_external_humanizer(reason: str) -> None:
    global HUMANIZER_EXTERNAL_LOCKED_OUT, HUMANIZER_EXTERNAL_LOCKOUT_REASON, HUMANIZER_EXTERNAL_READY
    HUMANIZER_EXTERNAL_LOCKED_OUT = True
    HUMANIZER_EXTERNAL_READY = False
    HUMANIZER_EXTERNAL_LOCKOUT_REASON = str(reason or "external_humanizer_failed").strip() or "external_humanizer_failed"


def humanize_text_local(text: str, *, target: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        # Preserve simple HTML blocks as single lines.
        if stripped.startswith("<") and stripped.endswith(">"):
            cleaned_lines.append(stripped)
            continue
        cleaned_lines.append(" ".join(stripped.split()))
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    return "\n".join(cleaned_lines).strip()


def humanizer_min_sentences() -> int:
    raw = env_value("CHUMMER6_TEXT_HUMANIZER_MIN_SENTENCES") or "2"
    try:
        return max(1, int(raw))
    except Exception:
        return 2


def humanizer_timeout_seconds() -> int:
    raw = env_value("CHUMMER6_TEXT_HUMANIZER_TIMEOUT_SECONDS") or "120"
    try:
        return max(30, int(raw))
    except Exception:
        return 120


def humanizer_min_words() -> int:
    raw = env_value("CHUMMER6_TEXT_HUMANIZER_MIN_WORDS") or "50"
    try:
        return max(1, int(raw))
    except Exception:
        return 50


def sentence_count(text: str) -> int:
    pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if part.strip()]
    return len(pieces)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\\-]*", str(text or "")))


def _humanizer_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", str(text or "").lower())
        if len(token) >= 4
        and token
        not in {
            "about",
            "after",
            "again",
            "being",
            "could",
            "first",
            "from",
            "into",
            "just",
            "more",
            "over",
            "their",
            "there",
            "these",
            "this",
            "those",
            "very",
            "while",
            "with",
            "your",
        }
    }


def humanizer_overlap_score(source: str, candidate: str) -> tuple[int, float]:
    source_tokens = _humanizer_tokens(source)
    candidate_tokens = _humanizer_tokens(candidate)
    if not source_tokens or not candidate_tokens:
        return 0, 0.0
    overlap = len(source_tokens & candidate_tokens)
    ratio = overlap / max(1, len(source_tokens))
    return overlap, ratio


def humanizer_ai_tells(text: str) -> list[str]:
    lowered = str(text or "").lower()
    phrases = (
        "seamless",
        "unlock",
        "ever-evolving",
        "in today's",
        "dynamic landscape",
        "not just ",
        "more than just",
        "journey",
        "delve into",
        "toolkit",
        "foundation",
        "elevate",
        "next-level",
        "game-changer",
        "transformative",
        "empowering",
        "streamlined",
    )
    return [phrase for phrase in phrases if phrase in lowered]


def humanized_candidate_findings(source: str, candidate: str) -> list[str]:
    findings: list[str] = []
    cleaned_source = str(source or "").strip()
    cleaned_candidate = str(candidate or "").strip()
    if not cleaned_candidate:
        return ["empty_output"]
    source_lowered = cleaned_source.lower()
    candidate_lowered = cleaned_candidate.lower()
    overlap, ratio = humanizer_overlap_score(cleaned_source, cleaned_candidate)
    if overlap < 2 or ratio < 0.12:
        findings.append("low_source_overlap")
    if word_count(cleaned_candidate) < max(12, int(word_count(cleaned_source) * 0.35)):
        findings.append("collapsed_too_far")
    ai_tells = humanizer_ai_tells(cleaned_candidate)
    if len(ai_tells) >= 2:
        findings.append("ai_tells:" + ",".join(ai_tells[:4]))
    concept_markers = ("concept", "idea", "direction", "experiment")
    source_has_concept_posture = ("pre-alpha" in source_lowered) or any(marker in source_lowered for marker in concept_markers)
    candidate_has_concept_posture = ("pre-alpha" in candidate_lowered) or any(marker in candidate_lowered for marker in concept_markers)
    if source_has_concept_posture and not candidate_has_concept_posture:
        findings.append("dropped_concept_posture")
    if any(
        phrase in candidate_lowered and phrase not in source_lowered
        for phrase in PAGE_MATH_CERTAINTY_PHRASES
    ):
        findings.append("introduced_math_certainty")
    if any(
        pattern.search(cleaned_candidate) and not pattern.search(cleaned_source)
        for pattern in TOTALIZING_PUBLIC_MATH_PATTERNS
    ):
        findings.append("introduced_totalizing_claim")
    if any(
        phrase in candidate_lowered and phrase not in source_lowered
        for phrase in PAGE_RISKY_SPECIFIC_CLAIMS
    ):
        findings.append("introduced_specific_claim")
    return findings


def humanized_candidate_ok(source: str, candidate: str) -> bool:
    return not humanized_candidate_findings(source, candidate)


def _humanizer_prompt(text: str, *, target: str, retry_reason: str = "") -> str:
    retry_block = f"\nPrevious rewrite failed because: {retry_reason}\nTighten it.\n" if retry_reason else ""
    return f"""You are the final human editorial pass for public-facing Chummer6 copy.

Task: rewrite the source text so it reads like a sharp human editor wrote it.

Return JSON only with one key: `humanized`.

Rules:
- preserve factual meaning, caveats, limits, route names, product names, and uncertainty
- do not add new claims, features, promises, or mechanics
- keep the same overall point and roughly similar density
- prefer concrete language over abstract product mush
- keep the existing tone grounded, adult, and dry; do not add jokes unless the source already has one
- if the source sounds concept-stage, keep it concept-stage or even more defensive; do not promote it into dependable software
- if the source warns that something may fail or never fully land, keep that warning explicit
- avoid synthetic phrases like seamless, unlock, journey, toolkit, foundation, or more-than-just framing
- do not sound like marketing copy, investor copy, or AI filler
- profanity is allowed only when it already fits the source naturally

Target: {target}
{retry_block}
Source text:
\"\"\"{text}\"\"\"
"""


def humanize_text_brain(text: str, *, target: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    retry_reason = ""
    for _attempt in range(2):
        payload = chat_json(
            _humanizer_prompt(cleaned, target=target, retry_reason=retry_reason),
            model=default_text_model(),
            skill_key=PUBLIC_WRITER_SKILL_KEY,
        )
        humanized = str(payload.get("humanized") or payload.get("result") or "").strip()
        if humanized_candidate_ok(cleaned, humanized):
            return humanized
        retry_reason = " | ".join(humanized_candidate_findings(cleaned, humanized)) or "invalid_rewrite"
    raise RuntimeError(f"brain_humanizer_failed:{retry_reason or 'invalid_rewrite'}")


def humanize_text(text: str, *, target: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    if sentence_count(cleaned) < humanizer_min_sentences() or word_count(cleaned) < humanizer_min_words():
        return humanize_text_local(cleaned, target=target)
    if HUMANIZER_BRAIN_ONLY:
        brain_humanized = humanize_text_brain(cleaned, target=target)
        if humanized_candidate_ok(cleaned, brain_humanized):
            return brain_humanized
        if humanizer_required():
            raise RuntimeError("text_humanizer_failed:brain_only_invalid")
        return humanize_text_local(cleaned, target=target)
    command_names = [
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND",
        "CHUMMER6_TEXT_HUMANIZER_COMMAND",
    ]
    template_names = [
        "CHUMMER6_BROWSERACT_HUMANIZER_URL_TEMPLATE",
        "CHUMMER6_TEXT_HUMANIZER_URL_TEMPLATE",
    ]
    attempted: list[str] = []
    external_expected = external_humanizer_ready()
    if external_expected:
        for env_name in command_names:
            command = shlex_command(env_name)
            if not command:
                continue
            try:
                completed = subprocess.run(
                    [part.format(text=cleaned, prompt=cleaned, target=target) for part in command],
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=humanizer_timeout_seconds(),
                )
                humanized = (completed.stdout or "").strip()
                if humanized and humanized_candidate_ok(cleaned, humanized):
                    return humanized
                if humanized:
                    attempted.append(
                        f"{env_name}:invalid_output:{'|'.join(humanized_candidate_findings(cleaned, humanized))}"
                    )
                else:
                    attempted.append(f"{env_name}:empty_output")
            except Exception as exc:
                attempted.append(f"{env_name}:{exc}")
        for env_name in template_names:
            template = url_template(env_name)
            if not template:
                continue
            url = template.format(
                text=urllib.parse.quote(cleaned, safe=""),
                prompt=urllib.parse.quote(cleaned, safe=""),
                target=urllib.parse.quote(target, safe=""),
            )
            request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-Humanizer/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    humanized = response.read().decode("utf-8", errors="replace").strip()
                if humanized and humanized_candidate_ok(cleaned, humanized):
                    return humanized
                if humanized:
                    attempted.append(
                        f"{env_name}:invalid_output:{'|'.join(humanized_candidate_findings(cleaned, humanized))}"
                    )
                else:
                    attempted.append(f"{env_name}:empty_output")
            except Exception as exc:
                attempted.append(f"{env_name}:{exc}")
    if attempted:
        lock_out_external_humanizer(" || ".join(attempted))
    try:
        brain_humanized = humanize_text_brain(cleaned, target=target)
        if humanized_candidate_ok(cleaned, brain_humanized):
            return brain_humanized
        attempted.append("brain_humanizer_invalid")
    except Exception as exc:
        attempted.append(str(exc))
    if humanizer_required():
        detail = " || ".join(attempted) if attempted else humanizer_lockout_reason() or "no_humanizer_succeeded"
        raise RuntimeError(f"text_humanizer_failed:{detail}")
    return humanize_text_local(cleaned, target=target)


def humanize_mapping_fields(mapping: dict[str, object], keys: tuple[str, ...], *, target_prefix: str) -> dict[str, object]:
    for key in keys:
        if key not in mapping:
            continue
        value = str(mapping.get(key, "")).strip()
        if not value:
            continue
        mapping[key] = humanize_text(value, target=f"{target_prefix}:{key}")
    return mapping


def humanize_mapping_fields_with_mode(
    mapping: dict[str, object],
    keys: tuple[str, ...],
    *,
    target_prefix: str,
    brain_only: bool,
) -> dict[str, object]:
    if brain_only:
        for key in keys:
            if key not in mapping:
                continue
            value = str(mapping.get(key, "")).strip()
            if not value:
                continue
            mapping[key] = humanize_text_local(value, target=f"{target_prefix}:{key}")
        return mapping
    global HUMANIZER_BRAIN_ONLY
    previous = HUMANIZER_BRAIN_ONLY
    HUMANIZER_BRAIN_ONLY = bool(brain_only)
    try:
        return humanize_mapping_fields(mapping, keys, target_prefix=target_prefix)
    finally:
        HUMANIZER_BRAIN_ONLY = previous


def build_part_prompt(
    name: str,
    item: dict[str, object],
    ooda: dict[str, object] | None = None,
    *,
    section_ooda: dict[str, object] | None = None,
) -> str:
    notice = "\n".join(f"- {line}" for line in item.get("notice", item.get("owns", [])))
    limits = "\n".join(f"- {line}" for line in item.get("limits", item.get("not_owns", [])))
    return f"""You are writing downstream-only copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys when, why, now.

Voice rules:
- clear, slightly playful, Shadowrun-flavored
- plain language first
- SR jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no control-plane jargon
- no markdown fences
- `when` should name concrete user situations, not vague platform posture
- `why` should cash out a visible reader benefit instead of abstract coordination language
- `now` should say what is true today plus one honest limit if the canon implies it
- if the part label sounds internal, translate it into the human-facing job a reader would actually care about
- avoid generic filler like toolkit, platform glue, digital handshake, or background systems
{PUBLIC_WRITER_RULES}

Part id: {name}
Title: {item.get("title", "")}
Tagline: {item.get("tagline", "")}
When you touch this:
{item.get("when", "")}

Why it matters:
{item.get("why", "")}

What you notice first:
{notice}

What you do not need to care about yet:
{limits}

Current now-text:
{item.get("now", "")}

Go deeper links:
{json.dumps(item.get("go_deeper_links", []), ensure_ascii=True)}

Supporting public context:
{json.dumps(part_supporting_context(name), ensure_ascii=True)}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def build_horizon_prompt(
    name: str,
    item: dict[str, object],
    ooda: dict[str, object] | None = None,
    *,
    section_ooda: dict[str, object] | None = None,
) -> str:
    foundations = "\n".join(f"- {line}" for line in item.get("foundations", []))
    repos = ", ".join(str(repo) for repo in item.get("repos", []))
    current_page = read_markdown_excerpt(f"HORIZONS/{name}.md", limit=360)
    rollout = horizon_rollout_context(name, item)
    return f"""You are writing downstream-only horizon copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys hook, problem, table_scene, meanwhile, why_great, why_waits, pitch_line.

Voice rules:
- sell the idea harder without pretending it ships tomorrow
- clear, punchy, Shadowrun-flavored
- SR jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- keep it exciting without pretending it is active work
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
{PUBLIC_WRITER_RULES}

Horizon id: {name}
Title: {item.get("title", "")}
Current hook:
{item.get("hook", "")}

Current brutal truth:
{item.get("brutal_truth", "")}

Current use case:
{item.get("use_case", "")}

Problem:
{item.get("problem", "")}

Current page excerpt:
{current_page}

Foundations:
{foundations}

Touched repos later:
{repos}

Access posture:
{rollout["access_posture"]}

Resource burden:
{rollout["resource_burden"]}

Booster nudge:
{rollout["booster_nudge"]}

Free-later intent:
{rollout["free_later_intent"]}

Booster API scope note:
{rollout["booster_api_scope_note"]}

Booster outcome note:
{rollout["booster_outcome_note"]}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Requirements:
- `table_scene` must read like a real table moment, not a one-line reminder
- `table_scene` should be 5-9 short lines with speaker labels or obviously playable dialogue beats
- avoid the default symmetrical five-line GM/player exchange; let the scene breathe, interrupt itself, or switch speaker mix when that fits the horizon better
- `meanwhile` must be 2-4 bullet lines starting with `- `
- `problem`, `why_great`, and `why_waits` should each be one tight paragraph
- `pitch_line` should invite a better future idea without sounding corporate
- if access posture or booster guidance exists in canon, `why_waits` and `pitch_line` should reflect it plainly instead of improvising a vague delay
- if free-later intent exists in canon, explain broad-access intent without sounding like a paywall apology
- avoid vague filler like future platform, foundation work, or shaky anvil when the canon gives a sharper reason

Return valid JSON only.
"""


def build_section_ooda_prompt(
    section_type: str,
    name: str,
    item: dict[str, object],
    *,
    global_ooda: dict[str, object] | None = None,
    style_epoch: dict[str, object] | None = None,
    recent_scenes: list[dict[str, str]] | None = None,
) -> str:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    prompt_bits = {
        "hero": {
            "context": "the landing hero for the human-facing Chummer6 guide",
            "source": "\n\n".join(
                [
                    "README:\n" + read_markdown_excerpt("README.md", limit=320),
                    "Current phase:\n" + read_markdown_excerpt("NOW/current-phase.md", limit=220),
                ]
            ),
        },
        "part": {
            "context": f"the PARTS/{name}.md page for the human-facing Chummer6 guide",
            "source": "\n\n".join(
                [
                    f"Tagline: {item.get('tagline', '')}",
                    f"When you touch this: {item.get('when', item.get('intro', ''))}",
                    f"Why: {item.get('why', '')}",
                    "What you notice:\n" + "\n".join(f"- {line}" for line in item.get("notice", item.get("owns", []))),
                    "What you do not need to care about yet:\n" + "\n".join(f"- {line}" for line in item.get("limits", item.get("not_owns", []))),
                    f"Now: {item.get('now', '')}",
                ]
            ),
        },
        "horizon": {
            "context": f"the HORIZONS/{name}.md page for the human-facing Chummer6 guide",
            "source": "\n\n".join(
                [
                    "Current page excerpt:\n" + read_markdown_excerpt(f"HORIZONS/{name}.md", limit=280),
                    f"Hook: {item.get('hook', '')}",
                    f"Brutal truth: {item.get('brutal_truth', '')}",
                    f"Use case: {item.get('use_case', '')}",
                    f"Problem: {item.get('problem', '')}",
                    "Foundations:\n" + "\n".join(f"- {line}" for line in item.get("foundations", [])),
                    "Touched repos later:\n" + "\n".join(f"- {line}" for line in item.get("repos", [])),
                ]
            ),
        },
        "page": {
            "context": f"the {name} guide page for the human-facing Chummer6 repo",
            "source": "\n\n".join(
                [
                    "Page brief:\n" + str(item.get("source", "")).strip(),
                    "Supporting public context:\n" + "\n".join(f"- {line}" for line in page_supporting_context(name)),
                ]
            ).strip(),
        },
    }[section_type]
    return f"""You are doing section-level OODA for {prompt_bits['context']}.

Task: return a JSON object only with keys observe, orient, decide, act.

Required shape:
- observe: reader_question, likely_interest, concrete_signals, risks
- orient: emotional_goal, sales_angle, focal_subject, scene_logic, visual_devices, tone_rule, banned_literalizations
- decide: copy_priority, image_priority, overlay_priority, subject_rule, hype_limit
- act: one_liner, paragraph_seed, visual_prompt_seed

Rules:
- this OODA is for this section only, not the whole repo
- think about what a curious human reader would actually notice or care about here
- if the source suggests strong selling points like multi-era support, Lua/scripted rules, local-first play, explain receipts, or dangerous simulation energy, surface them
- keep the concept-stage posture obvious; do not let section OODA drift into stable-product certainty
- do not literalize repo governance labels into the scene
- avoid generic poster language
- for image thinking, prefer one memorable focal subject or action over abstract icon soup
- if the section naturally implies a person, choose a believable cyberpunk protagonist instead of a faceless symbol
- if the concept itself implies a visual metaphor like x-ray, ghost, mirror, passport, web, blackbox, dossier, or crash-test simulation, make that metaphor visually legible in-scene
- if the title reads like a codename or person, let the scene revolve around a specific cyberpunk character instead of a generic skyline or dashboard
- if the title reads like a personal codename, make the character feel like that codename embodied; if it reads like a feminine personal name, it is fine to make the focal subject a woman
- if the metaphor is x-ray or simulation, show a real body, runner, or situation with the metaphor happening to it; do not collapse into abstract boxes and HUD wallpaper
- overlay hints are design guidance for the renderer, not excuses to print UI labels or prompt text on the image
- Shadowrun jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences

Section type: {section_type}
Section id: {name}
Section title: {title}

Section source:
{prompt_bits['source']}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Return valid JSON only.
"""


def build_section_oodas_bundle_prompt(
    section_type: str,
    section_items: dict[str, dict[str, object]],
    *,
    global_ooda: dict[str, object] | None = None,
    style_epoch: dict[str, object] | None = None,
    recent_scenes: list[dict[str, str]] | None = None,
) -> str:
    payload: dict[str, object] = {}
    for name, item in section_items.items():
        title = str(item.get("title", name.replace("-", " ").title())).strip()
        if section_type == "page":
            payload[name] = {
                "title": title,
                "source": str(item.get("source", "")).strip(),
                "supporting_public_context": page_supporting_context(name),
            }
        elif section_type == "part":
            payload[name] = {
                "title": title,
                "tagline": item.get("tagline", ""),
                "when": item.get("when", item.get("intro", "")),
                "why": item.get("why", ""),
                "now": item.get("now", ""),
                "notice": item.get("notice", item.get("owns", [])),
                "limits": item.get("limits", item.get("not_owns", [])),
                "go_deeper_links": item.get("go_deeper_links", []),
            }
        else:
            rollout = horizon_rollout_context(name, item)
            payload[name] = {
                "title": title,
                "hook": item.get("hook", ""),
                "brutal_truth": item.get("brutal_truth", ""),
                "use_case": item.get("use_case", ""),
                "problem": item.get("problem", ""),
                "foundations": item.get("foundations", []),
                "repos": item.get("repos", []),
                "not_now": item.get("not_now", ""),
                "access_posture": rollout["access_posture"],
                "resource_burden": rollout["resource_burden"],
                "booster_nudge": rollout["booster_nudge"],
                "free_later_intent": rollout["free_later_intent"],
                "booster_api_scope_note": rollout["booster_api_scope_note"],
                "booster_outcome_note": rollout["booster_outcome_note"],
                "current_page_excerpt": read_markdown_excerpt(f"HORIZONS/{name}.md", limit=220),
            }
    return f"""You are doing section-level OODA for multiple human-facing Chummer6 guide sections.

Task: return one JSON object keyed by section id.
Each section id must map to an object with keys observe, orient, decide, act.

Required shape per section:
- observe: reader_question, likely_interest, concrete_signals, risks
- orient: emotional_goal, sales_angle, focal_subject, scene_logic, visual_devices, tone_rule, banned_literalizations
- decide: copy_priority, image_priority, overlay_priority, subject_rule, hype_limit
- act: one_liner, paragraph_seed, visual_prompt_seed

Rules:
- think like a sharp human guide writer, not a compliance bot
- this OODA is for each section only, not the whole repo
- focus on what a curious human reader would actually care about here
- if the source suggests strong selling points like multi-era support, Lua/scripted rules, local-first play, explain receipts, grounded dossier flows, or dangerous simulation energy, surface them
- keep the concept-stage posture obvious; do not let section OODA drift into stable-product certainty
- if source signals clearly include multi-era support or scripted rules, make at least one section hook say so in plain language instead of burying it
- do not literalize repo governance labels into the scene
- avoid generic poster language and repeated sentence frames
- prefer one memorable focal subject or action over abstract icon soup
- if the section naturally implies a person, choose a believable cyberpunk protagonist instead of a faceless symbol
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, web, blackbox, forge, or crash-test simulation, make that metaphor visibly legible in-scene
- if the title reads like a codename or person, let the scene revolve around a specific cyberpunk character instead of a generic skyline or dashboard
- if the title reads like a personal codename, make the character feel like that codename embodied; if it reads like a feminine personal name, it is fine to make the focal subject a woman
- if the metaphor is x-ray or simulation, show a real body, runner, or situation with the metaphor happening to it; do not collapse into abstract boxes and HUD wallpaper
- overlay hints are design guidance for the renderer, not excuses to print labels, prompts, OODA, or resolution junk on the image
- Shadowrun jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- keep the whole JSON compact

Section type: {section_type}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Sections:
{json.dumps(payload, ensure_ascii=True)}

Return valid JSON only.
"""


def _section_ooda_defaults(
    *,
    section_type: str,
    name: str,
    item: dict[str, object],
    global_ooda: dict[str, object] | None = None,
) -> dict[str, object]:
    title = str(item.get("title") or name.replace("-", " ").title()).strip()
    tagline = str(item.get("tagline") or item.get("hook") or "").strip()
    intro = str(
        item.get("intro")
        or item.get("why")
        or item.get("problem")
        or item.get("why_great")
        or item.get("idea")
        or ""
    ).strip()
    foundations = _listish(item.get("foundations"))
    repos = _listish(item.get("repos"))
    signals: list[str] = []
    if isinstance(global_ooda, dict):
        orient = global_ooda.get("orient")
        if isinstance(orient, dict):
            signals = _listish(orient.get("signals_to_highlight"))
    concrete_signals = foundations or repos or signals or [title]
    question = {
        "hero": "Why should I trust this thing with a live Shadowrun table?",
        "page": f"Why should I read the {title} page?",
        "part": f"When would I actually care about {title}?",
        "horizon": f"What table pain is {title} trying to fix later?",
    }.get(section_type, f"Why does {title} matter?")
    likely_interest = tagline or intro or f"{title} should matter because it changes how the table feels, not just how the repo is sorted."
    scene_logic = intro or likely_interest
    one_liner = tagline or intro or f"{title} should feel like a table upgrade, not another internal nickname."
    paragraph_seed = intro or f"{title} matters when the table needs something clearer, faster, or less fragile."
    visual_seed = f"Contextual cyberpunk scene for {title}; show the real moment this page would matter."
    if section_type == "page" and name == "readme":
        likely_interest = "How honest is this about being mostly an idea with stray spillover?"
        scene_logic = "A risky concept warning, not a release announcement."
        one_liner = "README should warn people that they are looking at an idea with accidental spillover, not a product front door."
        paragraph_seed = "README matters when a curious runner needs the honest warning before mistaking stray traces for dependable software."
        visual_seed = "A dangerous concept warning scene in a rain-slick alley threshold or shuttered kiosk: sealed crate, hazard tape, hard practical light, no readable labels."
        concrete_signals = [
            "concept honesty before product posture",
            "stray traces instead of dependable surfaces",
            "follow the guide before trusting the spillover",
        ]
    elif section_type == "page" and name == "current_status":
        likely_interest = "What is actually visible right now, and how accidental is it?"
        scene_logic = "A fragile public trace still hanging on, not a supported live feature."
        one_liner = "Current status should read like an idea leaving faint traces behind, not a latest-drop victory lap."
        paragraph_seed = "Current status matters when a player or GM wants the honest state of the idea and whatever accidental public traces it left behind."
        visual_seed = "One operator or host checking a fragile public trace at a rain-streaked kiosk edge or transit bench; obvious uncertainty, no triumphant product posture."
        concrete_signals = [
            "public explanation before product claims",
            "horizon map and artifact shelf as traces, not guarantees",
            "almost everything still provisional or accidental",
        ]
    elif section_type == "page" and name == "what_chummer6_is":
        likely_interest = "What kind of trust problem is this idea trying to solve at the table?"
        scene_logic = "One inspectable trust moment beats an abstract feature poster."
        one_liner = "What Chummer6 is should feel like a trust problem caught in the act, not a finished system pitch."
        paragraph_seed = "This page matters when someone wants to know what kind of Shadowrun pain this idea is trying to relieve, without pretending the tool already exists."
        visual_seed = "A visible trust relationship under pressure: runner, reviewer, or spotter inspecting a suspect receipt trail in a rain-cut threshold, with visible stakes and no generic group huddle."
    elif section_type == "page" and name == "parts_index":
        likely_interest = "Which practical lane should I click first if I want the useful slice instead of the whole repo sermon?"
        scene_logic = "A lane-selection environment should read through differentiated work zones, not a row of screens or a centered mascot."
        one_liner = "Parts index should feel like several real work lanes opening off the same rough Shadowrun surface."
        paragraph_seed = "This page matters when a curious reader wants to choose the right lane quickly by reading the work zones, props, and stakes instead of parsing repo taxonomy."
        visual_seed = "A grounded Shadowrun lane-selection environment with clearly differentiated work zones for rules, UI, mobile continuity, hosted coordination, registry shelves, and media output; environment first, no centered signboard, no desk-monitor wall."
        concrete_signals = [
            "choose a lane by practical table pain",
            "different work zones should read at a glance",
            "environment-first guide art beats another device glamour shot",
        ]
    elif section_type == "page" and name == "horizons_index":
        likely_interest = "Which future lane looks dangerous enough to matter without pretending any of them are already finished?"
        scene_logic = "A branching district of futures should read through lane plurality, route pressure, and differentiated domains instead of one corridor and one hero silhouette."
        one_liner = "Horizons index should feel like a market of branching futures, not a title card for one corridor."
        paragraph_seed = "This page matters when a reader wants to browse several possible futures at once and feel the pressure, plurality, and risk without mistaking it for a shipped roadmap."
        visual_seed = "A branching Shadowrun district splice with at least four differentiated future lanes, partial crowds or vehicle traces, route clutter, wet reflections, and environment-first plurality; no lone centered silhouette, no central sign panel, no single corridor vanishing point."
        concrete_signals = [
            "future lanes branching without promise",
            "district plurality beats one corridor",
            "street-level clues should sell each horizon lane",
        ]
    return {
        "observe": {
            "reader_question": question,
            "likely_interest": likely_interest,
            "concrete_signals": concrete_signals,
            "risks": [
                "generic cyberpunk filler",
                "explaining architecture before user value",
                "template-shaped copy",
            ],
        },
        "orient": {
            "emotional_goal": "make the reader feel oriented, intrigued, and slightly smug for finally getting the point",
            "sales_angle": f"show {title} as a practical table benefit first",
            "focal_subject": title,
            "scene_logic": scene_logic,
            "visual_devices": [
                "lived props",
                "grounded lighting",
                "one obvious point of action",
            ],
            "tone_rule": "be clear first, stylish second, and never drift into dead template language",
            "banned_literalizations": [
                "floating infographic panels",
                "generic skyline wallpaper",
                "big centered logo art",
            ],
        },
        "decide": {
            "copy_priority": "lead with the pain or payoff a human reader would care about",
            "image_priority": "show the moment of use, not a codename poster",
            "overlay_priority": "only add overlays that clarify the action",
            "subject_rule": "anchor the scene in one concrete subject and one readable prop cluster",
            "hype_limit": "keep the promise sharp but believable",
        },
        "act": {
            "one_liner": one_liner,
            "paragraph_seed": paragraph_seed,
            "visual_prompt_seed": visual_seed,
        },
    }


def normalize_section_ooda(
    result: dict[str, object],
    *,
    section_type: str,
    name: str,
    item: dict[str, object],
    global_ooda: dict[str, object] | None = None,
) -> dict[str, object]:
    defaults = _section_ooda_defaults(
        section_type=section_type,
        name=name,
        item=item,
        global_ooda=global_ooda,
    )
    normalized: dict[str, object] = {}
    for stage, fields in {
        "observe": ["reader_question", "likely_interest", "concrete_signals", "risks"],
        "orient": ["emotional_goal", "sales_angle", "focal_subject", "scene_logic", "visual_devices", "tone_rule", "banned_literalizations"],
        "decide": ["copy_priority", "image_priority", "overlay_priority", "subject_rule", "hype_limit"],
        "act": ["one_liner", "paragraph_seed", "visual_prompt_seed"],
    }.items():
        raw_stage = result.get(stage) if isinstance(result.get(stage), dict) else {}
        merged: dict[str, object] = {}
        for field in fields:
            raw = raw_stage.get(field) if isinstance(raw_stage, dict) else None
            default_value = defaults[stage].get(field)
            if isinstance(raw, (list, tuple)) or isinstance(default_value, (list, tuple)):
                cleaned = _listish(raw)
                if not cleaned:
                    cleaned = _listish(default_value)
                fallback_values = _listish(default_value)
                merged[field] = [
                    editorial_self_audit_text(
                        entry,
                        fallback=(fallback_values[index] if index < len(fallback_values) else entry),
                        context=f"{section_type}:{name}:{stage}:{field}",
                    )
                    for index, entry in enumerate(cleaned)
                ]
            else:
                value = str(raw or "").strip()
                if not value:
                    if isinstance(default_value, (list, tuple)):
                        merged[field] = _listish(default_value)
                        continue
                    value = str(default_value or "").strip()
                merged[field] = editorial_self_audit_text(
                    value,
                    fallback=str(default_value or "").strip(),
                    context=f"{section_type}:{name}:{stage}:{field}",
                )
        normalized[stage] = merged
    return normalized


def normalize_section_oodas_bundle(
    result: dict[str, object],
    *,
    section_type: str,
    section_items: dict[str, dict[str, object]],
    global_ooda: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    normalized: dict[str, dict[str, object]] = {}
    for name, item in section_items.items():
        row = result.get(name)
        if not isinstance(row, dict) and section_type == "part":
            legacy_name = LEGACY_PART_SLUGS.get(name)
            if legacy_name:
                row = result.get(legacy_name)
        if not isinstance(row, dict):
            row = {}
        normalized[name] = normalize_section_ooda(
            row,
            section_type=section_type,
            name=name,
            item=item,
            global_ooda=global_ooda,
        )
    return normalized


def build_page_prompt(page_id: str, item: dict[str, object], *, global_ooda: dict[str, object] | None = None, section_ooda: dict[str, object] | None = None) -> str:
    supporting_context = page_supporting_context(page_id)
    role_hint = {
        "readme": "README is the front-door pitch and map. It should explain what the idea is trying to fix and which shelves are worth checking, not read like a checklist.",
        "start_here": "START_HERE is the orientation page. It should route the reader toward the next useful shelf or action.",
        "current_status": "CURRENT_STATUS is the honest present-tense readout. It should sound like status, not another concept pitch.",
    }.get(page_id, "Keep the page role clear and distinct.")
    return f"""You are writing downstream-only copy for the human-facing Chummer6 guide page `{page_id}`.

Task: return a JSON object only with keys intro, body, kicker.

Rules:
- plain language first
- human-facing, slightly playful, Shadowrun-flavored
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- explain why this page matters to a normal reader
- avoid internal jargon unless it is immediately translated
- make the page sound distinct instead of reusing one canned sentence pattern
- lead with one concrete table pain, payoff, or proof signal instead of abstract platform framing
- body should name at least two specific present-tense truths, proofs, or user actions when the canon supports them
- avoid generic filler like toolkit, foundation, platform glue, digital handshake, or background systems unless the sentence becomes sharper by keeping them
- do not tell the reader to fix docs, correct drift, or maintain the guide hierarchy
- if you recommend a public action, use the Chummer6 issue tracker, releases, or owning repos as appropriate
- treat `supporting_public_context` as the safe boundary for exact present-tense feature claims
- use `global_ooda` only for tone, emphasis, and information order; do not treat it as permission to add narrower product facts
- if a capability is not explicit in the page source or supporting_public_context, stay at the level of proof shelf, release shelf, current drop, public guide, horizon shelf, issue tracker, or local-first posture
- do not improvise exact current capabilities like gear availability checks, session continuity, device swaps, character integrity checks, multi-era support, scripted-rule internals, mobile-ready behavior, or similar feature details unless the page payload explicitly says them
- do not improvise specific rules-subsystem examples like stats, initiative, health, cyberware, qualities, or edition labels unless the page payload explicitly says them
- avoid niche gear, augment, or modifier anecdotes on root pages unless the page context explicitly names them
- avoid certainty words like deterministic truth, settled math, or solved rules coverage on root pages unless the page context explicitly says that level of completion
- keep the concept / idea posture defensive and honest on first-contact pages
- vary the defensive honesty language; do not repeat the same rough-trace or accidental-evidence disclaimer on every page
- do not mention booster / participate caveats on general pages; reserve that expensive-lane explanation for the KARMA FORGE horizon unless a page payload explicitly requires it
{PUBLIC_WRITER_RULES}

Page id: {page_id}
Page role:
{role_hint}

Current source:
{item.get("source", "")}

Supporting public context:
{json.dumps(supporting_context, ensure_ascii=True)}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def build_pages_bundle_prompt(*, items: dict[str, dict[str, object]], global_ooda: dict[str, object], section_oodas: dict[str, object]) -> str:
    pages_payload: dict[str, object] = {}
    for page_id, item in items.items():
        pages_payload[page_id] = {
            "source": str(item.get("source", "")).strip(),
            "supporting_public_context": page_supporting_context(page_id),
            "section_ooda": section_oodas.get(page_id, {}),
            "page_role": {
                "readme": "front-door pitch and map",
                "start_here": "orientation and next-step routing",
                "current_status": "present-tense status readout",
            }.get(page_id, "distinct public guide page"),
        }
    return f"""You are writing downstream-only copy for multiple human-facing Chummer6 guide pages.

Task: return one JSON object keyed by page id. Each page id must map to an object with keys intro, body, kicker.

Rules:
- plain language first
- human-facing, slightly playful, Shadowrun-flavored
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- explain why each page matters to a normal reader
- avoid internal jargon unless it is immediately translated
- keep each page compact and useful
- make each page feel distinct instead of reusing one sentence frame
- make README, START_HERE, and CURRENT_STATUS feel like different jobs, not three defensive rewrites of the same disclaimer
- lead with one concrete table pain, payoff, or proof signal instead of abstract platform framing
- each page body should name at least two specific present-tense truths, proofs, or user actions when the canon supports them
- avoid generic filler like toolkit, foundation, platform glue, digital handshake, or background systems unless the sentence becomes sharper by keeping them
- do not tell the reader to fix docs, correct drift, or maintain the guide hierarchy
- if you recommend a public action, use the Chummer6 issue tracker, releases, or owning repos as appropriate
- treat each page's `supporting_public_context` as the safe boundary for exact present-tense feature claims
- use `global_ooda` only for tone, emphasis, and information order; do not treat it as permission to add narrower product facts
- if a capability is not explicit in the page source or supporting_public_context, stay at the level of proof shelf, release shelf, current drop, public guide, horizon shelf, issue tracker, or local-first posture
- do not improvise exact current capabilities like gear availability checks, session continuity, device swaps, character integrity checks, multi-era support, scripted-rule internals, mobile-ready behavior, or similar feature details unless the page payload explicitly says them
- do not improvise specific rules-subsystem examples like stats, initiative, health, cyberware, qualities, or edition labels unless the page payload explicitly says them
- avoid niche gear, augment, or modifier anecdotes on root pages unless the page context explicitly names them
- avoid certainty words like deterministic truth, settled math, or solved rules coverage on root pages unless the page context explicitly says that level of completion
- vary the defensive honesty language across the set; do not keep repeating rough traces, accidental evidence, or identical spillover warnings page after page
{PUBLIC_WRITER_RULES}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Pages:
{json.dumps(pages_payload, ensure_ascii=True)}

Return valid JSON only.
"""


def build_parts_bundle_prompt(
    *,
    items: dict[str, dict[str, object]],
    global_ooda: dict[str, object],
    section_oodas: dict[str, object],
    style_epoch: dict[str, object] | None = None,
    recent_scenes: list[dict[str, str]] | None = None,
) -> str:
    parts_payload: dict[str, object] = {}
    for name, item in items.items():
        parts_payload[name] = {
            "title": item.get("title", ""),
            "tagline": item.get("tagline", ""),
            "when": item.get("when", item.get("intro", "")),
            "why": item.get("why", ""),
            "now": item.get("now", ""),
            "notice": item.get("notice", item.get("owns", [])),
            "limits": item.get("limits", item.get("not_owns", [])),
            "go_deeper_links": item.get("go_deeper_links", []),
            "supporting_public_context": part_supporting_context(name),
            "section_ooda": section_oodas.get(name, {}),
            "asset_target": f"assets/parts/{name}.png",
            "variation_guardrails": variation_guardrails_for(
                f"assets/parts/{name}.png",
                recent_scene_rows_for_style_epoch(style_epoch=style_epoch, allow_fallback=False),
            ),
        }
    return f"""You are writing downstream-only copy and media metadata for multiple Chummer6 part pages.

Task: return one JSON object keyed by part id.
Each part id must map to:
- copy: object with when, why, now
- media: object with badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract

Rules:
- clear, slightly playful, Shadowrun-flavored
- plain language first
- SR jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- keep copy grounded and useful
- make each part sound like its own place, not another templated glossary card
- if a part label sounds internal, translate it into a human-facing concept instead of repeating the module name back at the reader
- make the media scene-first, not icon soup
- humor is optional; if the scene does not earn it, skip it
- easter eggs are optional; any asset may carry one if the scene earns it, but no asset is required to have one
- no literal on-image text or prompt leakage
- do not make gloved hands, scarred hands, or anonymous hand close-ups the primary focal subject
- `when` should sound like real user situations, not platform posture
- `why` should cash out a visible benefit instead of abstract glue language
- `now` should say what is true today plus one honest limit when the canon implies it
{PUBLIC_WRITER_RULES}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Parts:
{json.dumps(parts_payload, ensure_ascii=True)}

Return valid JSON only.
"""


def build_horizons_bundle_prompt(
    *,
    items: dict[str, dict[str, object]],
    global_ooda: dict[str, object],
    section_oodas: dict[str, object],
    style_epoch: dict[str, object] | None = None,
    recent_scenes: list[dict[str, str]] | None = None,
) -> str:
    horizons_payload: dict[str, object] = {}
    for name, item in items.items():
        rollout = horizon_rollout_context(name, item)
        horizons_payload[name] = {
            "title": item.get("title", ""),
            "hook": item.get("hook", ""),
            "brutal_truth": item.get("brutal_truth", ""),
            "use_case": item.get("use_case", ""),
            "problem": item.get("problem", ""),
            "foundations": item.get("foundations", []),
            "repos": item.get("repos", []),
            "not_now": item.get("not_now", ""),
            "access_posture": rollout["access_posture"],
            "resource_burden": rollout["resource_burden"],
            "booster_nudge": rollout["booster_nudge"],
            "free_later_intent": rollout["free_later_intent"],
            "booster_api_scope_note": rollout["booster_api_scope_note"],
            "booster_outcome_note": rollout["booster_outcome_note"],
            "current_page_excerpt": read_markdown_excerpt(f"HORIZONS/{name}.md", limit=260),
            "section_ooda": section_oodas.get(name, {}),
            "asset_target": f"assets/horizons/{name}.png",
            "variation_guardrails": variation_guardrails_for(
                f"assets/horizons/{name}.png",
                recent_scene_rows_for_style_epoch(style_epoch=style_epoch, allow_fallback=False),
            ),
        }
    return f"""You are writing downstream-only copy and media metadata for multiple Chummer6 horizon pages.

Task: return one JSON object keyed by horizon id.
Each horizon id must map to:
- copy: object with hook, problem, table_scene, meanwhile, why_great, why_waits, pitch_line
- media: object with badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract

Rules:
- sell the idea harder without pretending it ships tomorrow
- clear, punchy, Shadowrun-flavored
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- scenes should feel specific, cool, dangerous, and actually playable
- if the codename implies a person or metaphor, make that legible
- do not reuse the same sentence stem across multiple horizons
- the copy should feel distinct per horizon, not like one template with swapped nouns
- humor is optional; if it does not sharpen the horizon, leave it out
- easter eggs are optional; any horizon asset may carry one if the scene earns it, but no asset is required to have one
- `table_scene` must be a mini scene, not a one-sentence use-case stub
- `table_scene` should feel like table dialogue, with a GM/player/Chummer rhythm when the concept allows it
- vary `table_scene` cadence across the set; do not give every horizon the same tidy five-line exchange
- across the bundle, mix beat counts, speaker mixes, and the occasional unlabeled action beat when the scene earns it
- do not let every horizon end on the same neat mic-drop line or identical GM/player rhythm
- `meanwhile` must be 2-4 bullet lines starting with `- `
- do not make gloved hands, scarred hands, or anonymous hand close-ups the primary focal subject of the media scene
- prefer pain -> scene -> invisible system action -> payoff -> realism
- if access posture, booster guidance, or free-later intent exists in canon, carry that into `why_waits` and `pitch_line` instead of improvising a vague delay story

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Horizons:
{json.dumps(horizons_payload, ensure_ascii=True)}

Return valid JSON only.
"""


def normalize_pages_bundle(result: dict[str, object], *, items: dict[str, dict[str, object]]) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for page_id in items:
        row = result.get(page_id)
        if not isinstance(row, dict):
            raise ValueError(f"missing page bundle row: {page_id}")
        cleaned = {
            key: editorial_self_audit_text(
                str(row.get(key, "")).strip(),
                context=f"page:{page_id}:{key}",
            )
            for key in ("intro", "body", "kicker")
            if str(row.get(key, "")).strip()
        }
        if len(cleaned) < 2:
            raise ValueError(f"insufficient page bundle content: {page_id}")
        normalized[page_id] = cleaned
    return normalized


def normalize_single_page_bundle_candidate(result: dict[str, object], *, page_id: str) -> dict[str, str]:
    candidate: dict[str, object] | None = None
    if all(str(result.get(key, "")).strip() for key in ("intro", "body", "kicker")):
        candidate = result
    else:
        nested_candidates = [
            value
            for value in result.values()
            if isinstance(value, dict) and any(str(value.get(key, "")).strip() for key in ("intro", "body", "kicker"))
        ]
        if len(nested_candidates) == 1:
            candidate = dict(nested_candidates[0])
    if not isinstance(candidate, dict):
        raise ValueError(f"missing page bundle row: {page_id}")
    cleaned = {
        key: editorial_self_audit_text(
            str(candidate.get(key, "")).strip(),
            context=f"page:{page_id}:{key}",
        )
        for key in ("intro", "body", "kicker")
        if str(candidate.get(key, "")).strip()
    }
    if len(cleaned) < 2:
        raise ValueError(f"insufficient page bundle content: {page_id}")
    return cleaned


def fallback_media_seed(kind: str, *, name: str, item: dict[str, object]) -> dict[str, str]:
    title = str(item.get("title") or item.get("slug") or name).strip() or name
    if kind == "part":
        subtitle = str(item.get("tagline") or item.get("why") or item.get("when") or title).strip() or title
        return {
            "badge": "Concept // part",
            "title": title,
            "subtitle": subtitle,
            "kicker": "public job, not finished software",
            "note": "Treat this as a concept lane with a few rough traces, not a dependable surface.",
            "overlay_hint": "subtle diegetic context markers",
            "visual_prompt": f"{title}; grounded Shadowrun part scene; tactile props; no readable text",
        }
    subtitle = str(item.get("hook") or item.get("problem") or item.get("use_case") or title).strip() or title
    return {
        "badge": "Concept // horizon",
        "title": title,
        "subtitle": subtitle,
        "kicker": "future lane, not a promise",
        "note": "Treat this as a concept lane with rough public traces, not a finished feature.",
        "overlay_hint": "subtle diegetic context markers",
        "visual_prompt": f"{title}; grounded Shadowrun horizon scene; tactile props; no readable text",
    }


def normalize_parts_bundle(result: dict[str, object], *, items: dict[str, dict[str, object]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    copy_rows: dict[str, dict[str, str]] = {}
    media_rows: dict[str, dict[str, object]] = {}
    for name, item in items.items():
        row = result.get(name)
        if not isinstance(row, dict):
            legacy_name = LEGACY_PART_SLUGS.get(name)
            if legacy_name:
                row = result.get(legacy_name)
        if not isinstance(row, dict):
            copy_rows[name] = fallback_part_copy(name, item)
            media_rows[name] = normalize_media_override("part", fallback_media_seed("part", name=name, item=item), item)
            continue
        copy = row.get("copy")
        media = row.get("media")
        if not isinstance(copy, dict) or not isinstance(media, dict):
            copy_rows[name] = fallback_part_copy(name, item)
            media_rows[name] = normalize_media_override("part", fallback_media_seed("part", name=name, item=item), item)
            continue
        cleaned_copy = {
            key: editorial_self_audit_text(
                str(copy.get(key, "")).strip(),
                context=f"part:{name}:{key}",
            )
            for key in ("when", "why", "now")
            if str(copy.get(key, "")).strip()
        }
        if len(cleaned_copy) < 3:
            cleaned_copy = fallback_part_copy(name, item)
        try:
            media_cleaned = normalize_media_override("part", dict(media), item)
        except Exception:
            media_cleaned = normalize_media_override("part", fallback_media_seed("part", name=name, item=item), item)
        copy_rows[name] = cleaned_copy
        media_rows[name] = media_cleaned
    return copy_rows, media_rows


def normalize_horizons_bundle(result: dict[str, object], *, items: dict[str, dict[str, object]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    copy_rows: dict[str, dict[str, str]] = {}
    media_rows: dict[str, dict[str, object]] = {}
    for name, item in items.items():
        row = result.get(name)
        if not isinstance(row, dict):
            copy_rows[name] = fallback_horizon_copy(name, item)
            media_rows[name] = normalize_media_override("horizon", fallback_media_seed("horizon", name=name, item=item), item)
            continue
        copy = row.get("copy")
        media = row.get("media")
        if not isinstance(copy, dict) or not isinstance(media, dict):
            copy_rows[name] = fallback_horizon_copy(name, item)
            media_rows[name] = normalize_media_override("horizon", fallback_media_seed("horizon", name=name, item=item), item)
            continue
        cleaned_copy = {
            key: editorial_self_audit_text(
                str(copy.get(key, "")).strip(),
                context=f"horizon:{name}:{key}",
            )
            for key in ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line")
            if str(copy.get(key, "")).strip()
        }
        if len(cleaned_copy) < 7:
            cleaned_copy = fallback_horizon_copy(name, item)
        try:
            media_cleaned = normalize_media_override("horizon", dict(media), item)
        except Exception:
            media_cleaned = normalize_media_override("horizon", fallback_media_seed("horizon", name=name, item=item), item)
        copy_rows[name] = cleaned_copy
        media_rows[name] = media_cleaned
    return copy_rows, media_rows


AUDITOR_OK_STATUSES = {"ok", "pass", "approved", "clean"}


def _trim_audit_text(text: object, *, limit: int = 320) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(32, limit - 1)].rstrip(" ,;:-") + "…"


def _trim_structured_audit_text(text: object, *, limit: int = 1200) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()).strip() for line in normalized.split("\n")]
    preserved = "\n".join(line for line in lines if line)
    if len(preserved) <= limit:
        return preserved
    return preserved[: max(64, limit - 1)].rstrip(" ,;:-") + "…"


def _copy_audit_snapshot(overrides: dict[str, object]) -> dict[str, object]:
    return {
        "pages": {
            page_id: {
                key: _trim_structured_audit_text(value, limit=1600)
                for key, value in dict(row).items()
                if isinstance(value, str)
            }
            for page_id, row in dict(overrides.get("pages") or {}).items()
            if isinstance(row, dict)
        },
        "parts": {
            part_id: {
                key: _trim_structured_audit_text(value, limit=480)
                for key, value in dict(row).items()
                if isinstance(value, str)
            }
            for part_id, row in dict(overrides.get("parts") or {}).items()
            if isinstance(row, dict)
        },
        "horizons": {
            horizon_id: {
                key: (
                    _trim_structured_audit_text(value, limit=1600)
                    if key in {"table_scene", "meanwhile"}
                    else _trim_structured_audit_text(value, limit=520)
                )
                for key, value in dict(row).items()
                if isinstance(value, str)
            }
            for horizon_id, row in dict(overrides.get("horizons") or {}).items()
            if isinstance(row, dict)
        },
    }


def _scene_audit_snapshot(overrides: dict[str, object]) -> dict[str, object]:
    media = dict(overrides.get("media") or {})
    summary: dict[str, object] = {
        "hero": {},
        "parts": {},
        "horizons": {},
    }
    hero = media.get("hero")
    if isinstance(hero, dict):
        contract = hero.get("scene_contract") if isinstance(hero.get("scene_contract"), dict) else {}
        summary["hero"] = {
            "visual_prompt": _trim_audit_text(hero.get("visual_prompt"), limit=260),
            "overlay_hint": _trim_audit_text(hero.get("overlay_hint"), limit=120),
            "scene_contract": {
                key: contract.get(key)
                for key in ("subject", "environment", "action", "metaphor", "composition")
                if str(contract.get(key) or "").strip()
            },
        }
    for group in ("parts", "horizons"):
        rows: dict[str, object] = {}
        for item_id, row in dict(media.get(group) or {}).items():
            if not isinstance(row, dict):
                continue
            contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
            rows[item_id] = {
                "title": _trim_audit_text(row.get("title"), limit=100),
                "visual_prompt": _trim_audit_text(row.get("visual_prompt"), limit=220),
                "overlay_hint": _trim_audit_text(row.get("overlay_hint"), limit=120),
                "scene_contract": {
                    key: contract.get(key)
                    for key in ("subject", "environment", "action", "metaphor", "composition")
                    if str(contract.get(key) or "").strip()
                },
            }
        summary[group] = rows
    return summary


def _visual_audit_snapshot(overrides: dict[str, object]) -> dict[str, object]:
    media = dict(overrides.get("media") or {})
    snapshot: dict[str, object] = {}
    for group in ("hero", "parts", "horizons"):
        rows = media.get(group)
        if isinstance(rows, dict):
            if group == "hero":
                rows = {"hero": rows}
            snapshot[group] = {
                item_id: {
                    "title": _trim_audit_text(row.get("title"), limit=90),
                    "badge": _trim_audit_text(row.get("badge"), limit=60),
                    "subtitle": _trim_audit_text(row.get("subtitle"), limit=120),
                    "kicker": _trim_audit_text(row.get("kicker"), limit=120),
                    "visual_motifs": list(row.get("visual_motifs") or [])[:6],
                    "overlay_callouts": list(row.get("overlay_callouts") or [])[:4],
                    "composition": str(((row.get("scene_contract") or {}) if isinstance(row, dict) else {}).get("composition") or "").strip(),
                }
                for item_id, row in rows.items()
                if isinstance(row, dict)
            }
    return snapshot


def _pack_audit_snapshot(overrides: dict[str, object]) -> dict[str, object]:
    meta = dict(overrides.get("meta") or {})
    style_epoch = dict(meta.get("style_epoch") or {})
    return {
        "copy": _copy_audit_snapshot(overrides),
        "visuals": _visual_audit_snapshot(overrides),
        "style_epoch": {
            key: style_epoch.get(key)
            for key in ("epoch", "run_id", "style_family", "palette", "lighting", "humor_ceiling")
            if key in style_epoch
        },
    }


def build_auditor_prompt(*, label: str, focus: str, payload: dict[str, object]) -> str:
    return f"""You are auditing a generated Chummer6 public-guide pack before publish.

Task: return JSON only with keys status, summary, findings, risky_scopes.

Rules:
- `status` must be either `ok` or `revise`
- mark `revise` if the pack still sounds like maintainers explaining structure to themselves, if the calls to action are misrouted, if the copy is not useful to a curious player/GM/tester, or if the visuals feel repetitive, generic, or mismatched to the page role
- keep `summary` to one short paragraph
- `findings` should be a short list of concrete issues, or an empty list when the pack is clean
- `risky_scopes` should name the page ids, part ids, horizon ids, or media groups that need attention
- do not rewrite the pack; audit it
- no markdown fences

Audit label: {label}
Audit focus:
{focus}

Pack snapshot:
{json.dumps(payload, ensure_ascii=True)}

Return valid JSON only.
"""


def normalize_audit_result(result: dict[str, object], *, label: str) -> dict[str, object]:
    raw_status = str(result.get("status") or "").strip().lower()
    summary = editorial_self_audit_text(
        str(result.get("summary") or "").strip(),
        fallback=f"{label} audit returned no summary.",
        context=f"audit:{label}:summary",
    )
    findings = [
        editorial_self_audit_text(
            entry,
            fallback=entry,
            context=f"audit:{label}:finding",
        )
        for entry in _listish(result.get("findings"))
    ]
    risky_scopes = [entry for entry in _listish(result.get("risky_scopes")) if entry]
    if raw_status not in AUDITOR_OK_STATUSES | {"revise", "fail", "failed", "reject"}:
        raw_status = "ok" if not findings and not risky_scopes else "revise"
    status = "ok" if raw_status in AUDITOR_OK_STATUSES else "revise"
    return {
        "status": status,
        "summary": summary,
        "findings": findings,
        "risky_scopes": risky_scopes,
    }


def run_skill_audit(
    *,
    label: str,
    skill_key: str,
    focus: str,
    payload: dict[str, object],
    model: str,
) -> dict[str, object]:
    result = chat_json(
        build_auditor_prompt(label=label, focus=focus, payload=payload),
        model=model,
        skill_key=skill_key,
    )
    normalized = normalize_audit_result(result, label=label)
    if normalized["status"] != "ok":
        scopes = ",".join(normalized["risky_scopes"][:8]) if normalized["risky_scopes"] else "unspecified"
        findings = " | ".join(normalized["findings"][:4]) if normalized["findings"] else normalized["summary"]
        raise RuntimeError(f"{label}_audit_failed:{scopes}:{findings}")
    return normalized


COPY_KEYS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "page": ("intro", "body", "kicker"),
    "part": ("when", "why", "now"),
    "horizon": ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line"),
}


def normalize_horizon_meanwhile(text: str) -> str:
    def _normalize_raw(value: object) -> str:
        raw_text = str(value or "").strip()
        if not raw_text:
            return ""
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\\r\\n", "\n").replace("\\r", "\n").replace("\\n", "\n")
        while len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
            candidate = normalized[1:-1].strip()
            if not candidate:
                break
            normalized = candidate
        return normalized.strip()

    def _flatten_entries(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            normalized = _normalize_raw(value)
            return [line.strip() for line in normalized.split("\n") if line.strip()]
        if isinstance(value, list):
            flattened: list[str] = []
            for entry in value:
                flattened.extend(_flatten_entries(entry))
            return flattened
        if isinstance(value, dict):
            for key in ("meanwhile", "items", "bullets", "lines", "entries"):
                if key in value:
                    return _flatten_entries(value.get(key))
            flattened: list[str] = []
            for entry in value.values():
                flattened.extend(_flatten_entries(entry))
            return flattened
        return [str(value).strip()]

    def _clean_entry(value: str) -> str:
        candidate = _normalize_raw(value)
        candidate = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", candidate).strip(" \t\"'")
        candidate = " ".join(candidate.split()).strip(" ,.;:-")
        if candidate and candidate[0].islower():
            candidate = candidate[0].upper() + candidate[1:]
        return candidate

    raw = _normalize_raw(text)
    if not raw:
        return ""
    parsed_entries: list[str] = []
    parse_candidate = raw
    for _ in range(2):
        if not parse_candidate or parse_candidate[0] not in "[{\"":
            break
        try:
            loaded = json.loads(parse_candidate)
        except Exception:
            break
        flattened = _flatten_entries(loaded)
        if flattened:
            parsed_entries = flattened
            break
        if isinstance(loaded, str):
            parse_candidate = _normalize_raw(loaded)
            continue
        break
    if not parsed_entries and "[" in raw and "]" in raw:
        bracketed = raw[raw.find("[") : raw.rfind("]") + 1].strip()
        try:
            literal_loaded = ast.literal_eval(bracketed)
        except Exception:
            literal_loaded = None
        flattened_literal = _flatten_entries(literal_loaded)
        if flattened_literal:
            parsed_entries = flattened_literal
    lines = parsed_entries or [line.strip() for line in raw.split("\n") if line.strip()]
    cleaned_parts: list[str] = []
    seen_lowered: set[str] = set()
    for line in lines:
        candidate = _clean_entry(line)
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen_lowered:
            continue
        seen_lowered.add(lowered)
        cleaned_parts.append(candidate)
    if not cleaned_parts:
        compact = " ".join(raw.split()).strip(" .")
        if not compact:
            return ""
        seeded = re.sub(r"\s+and\s+", "; ", compact, flags=re.IGNORECASE)
        parts = [
            _clean_entry(part)
            for part in re.split(r";\s+|,\s+|\.\s+", seeded)
            if part.strip(" ,.;:-")
        ]
        cleaned_parts = [part for part in parts if part]
    if len(cleaned_parts) <= 1:
        compact = " ".join(raw.split()).strip(" .")
        seeded = re.sub(r"\s+and\s+", "; ", compact, flags=re.IGNORECASE)
        split_parts = [
            _clean_entry(part)
            for part in re.split(r";\s+|,\s+|\.\s+", seeded)
            if part.strip(" ,.;:-")
        ]
        deduped_split: list[str] = []
        seen_split: set[str] = set()
        for part in split_parts:
            lowered = part.lower()
            if not part or lowered in seen_split:
                continue
            seen_split.add(lowered)
            deduped_split.append(part)
        if len(deduped_split) >= 2:
            cleaned_parts = deduped_split
    if not cleaned_parts:
        return ""
    if len(cleaned_parts) == 1:
        return f"- {cleaned_parts[0]}"
    return "\n".join(f"- {entry}" for entry in cleaned_parts[:4])


def copy_quality_findings(section_type: str, name: str, row: dict[str, object], item: dict[str, object]) -> list[str]:
    combined = " ".join(
        str(row.get(key, "")).strip()
        for key in COPY_KEYS_BY_SECTION.get(section_type, ())
        if str(row.get(key, "")).strip()
    ).strip()
    lowered = combined.lower()
    findings: list[str] = []
    truncated_fields = [
        key
        for key in COPY_KEYS_BY_SECTION.get(section_type, ())
        if str(row.get(key, "")).strip().endswith(("…", "..."))
    ]
    if truncated_fields:
        findings.append(
            "Replace truncated public copy. Do not leave clipped words or trailing ellipses in fields like "
            + ", ".join(truncated_fields[:4])
            + "."
        )
    if section_type == "page":
        source_context = " ".join(
            [
                str(item.get("source", "")).strip(),
                *page_supporting_context(name),
            ]
        ).lower()
        risky_claims = [
            phrase
            for phrase in PAGE_RISKY_SPECIFIC_CLAIMS
            if phrase in lowered and phrase not in source_context
        ]
        if risky_claims:
            findings.append(
                "Do not invent exact present-tense feature claims beyond the provided page context. Stay on guide, horizon shelf, issue tracker, concept posture, or explicitly marked accidental artifacts unless the source explicitly goes narrower."
            )
        risky_game_details = [
            phrase
            for phrase in PAGE_RISKY_GAME_DETAIL_TOKENS
            if phrase in lowered and phrase not in source_context
        ]
        if risky_game_details:
            findings.append(
                "Avoid specific subsystem, edition, or character-sheet examples unless the page context explicitly names them. Keep these root pages at the level of concept, public explanation, future lanes, and accidental spillover."
            )
        math_certainty_phrases = [
            phrase
            for phrase in PAGE_MATH_CERTAINTY_PHRASES
            if phrase in lowered and phrase not in source_context
        ]
        if math_certainty_phrases:
            findings.append(
                "Do not claim the rules math is already settled or end-to-end trustworthy on root pages. Keep the copy at concept-stage honesty, limited traces, and trust not yet earned."
            )
        if any(pattern.search(combined) for pattern in TOTALIZING_PUBLIC_MATH_PATTERNS):
            findings.append(
                "Avoid universal math claims on root pages. Do not say every calculation, every bonus, or every threshold is already covered; this project has not earned that posture."
            )
        soft_filler_phrases = [
            phrase
            for phrase in PAGE_SOFT_FILLER_PHRASES
            if phrase in lowered
        ]
        if soft_filler_phrases:
            findings.append(
                "Replace synthetic product phrasing with plain user language. Say what the reader can watch, inspect cautiously, or argue with instead of calling it a session shell, character engine, or similar invented label."
            )
        if name in {"readme", "start_here", "what_chummer6_is", "current_phase", "current_status", "public_surfaces"} and any(
            phrase in lowered
            for phrase in (
                "proof of concept",
                "proof-of-concept",
                "run the current",
                "download the build",
                "current drop",
                "current release",
                "latest drop",
            )
        ):
            findings.append(
                "Do not pitch a runnable proof-of-concept or dependable build on root pages. If you mention artifacts at all, frame them as rough, provisional traces instead of a product path."
            )
        if page_supporting_context(name) and not any(
            token in lowered
            for token in (
                "guide",
                "horizon",
                "issue",
                "watch",
                "concept",
                "idea",
                "artifact",
                "spillover",
            )
        ):
            findings.append("Name at least one visible public surface, future lane, or cautious public action instead of describing the project only in abstract terms.")
        if name in {"readme", "start_here", "current_phase", "current_status"} and not any(
            token in lowered
            for token in (
                "concept",
                "idea",
                "experiment",
                "accident",
                "accidental",
                "spillover",
                "trace",
                "rough",
                "not dependable",
                "not stable",
                "provisional",
                "not a product",
                "not a promise",
            )
        ):
            findings.append("Make the concept-stage and accidental-artifact posture explicit so the guide does not sound like a rough product pitch.")
        if name == "readme" and not any(token in lowered for token in ("guide", "horizon", "issue tracker", "artifact", "trace", "rough")):
            findings.append("README should point the reader toward the public guide, future lanes, issue tracker, or clearly provisional artifacts instead of staying at product-story altitude.")
        intro_lowered = str(row.get("intro", "")).strip().lower()
        if name == "readme" and re.match(r"^(stop|start|grab|download|use)\b", intro_lowered):
            findings.append("README should open with concept-stage honesty before any command-style invitation. Do not make the first line sound like the tool is ready for immediate use.")
        if name == "readme" and any(
            phrase in lowered
            for phrase in (
                "stop guessing",
                "start auditing",
                "download now",
                "try it now",
            )
        ):
            findings.append(
                "README should not lean on command-slogan copy that makes the project sound ready to use. Keep the tone closer to concept, inspection, and rough traces."
            )
        intro_niche_tokens = [
            phrase
            for phrase in PAGE_RISKY_GAME_DETAIL_TOKENS
            if phrase in intro_lowered and phrase not in source_context
        ]
        if intro_niche_tokens:
            findings.append("Keep the opening line at table friction, visible proof, or current-state level. Do not open root pages with niche gear, modifier, or combat anecdotes.")
        bad_intro_labels = [
            label
            for pattern, label in BAD_PAGE_OPENING_PATTERNS
            if pattern.search(str(row.get("intro", "")).strip()) and not pattern.search(source_context)
        ]
        if bad_intro_labels:
            findings.append("Rewrite the opening line. Frozen bad-opening patterns from earlier runs should not come back on root pages.")
        if name == "start_here" and not any(
            token in lowered for token in ("next", "start", "read", "watch", "guide", "horizon", "issue tracker", "if you find")
        ):
            findings.append("START_HERE should tell the reader what to inspect or watch next, not just why the project matters in the abstract.")
        if name == "start_here" and not any(
            token in lowered for token in ("what_chummer6_is", "current status", "current_status", "horizon", "issue tracker", "read", "start here")
        ):
            findings.append("START_HERE should route the reader toward the next useful shelf or action instead of repeating README posture.")
        if name == "what_chummer6_is":
            if not any(token in lowered for token in ("concept", "idea", "experiment", "direction")):
                findings.append("Explain WHAT_CHUMMER6_IS as a concept or direction first, not as a product already standing on its own feet.")
            if not any(token in lowered for token in ("receipt", "proof", "show the math", "visible math", "earn trust", "trust", "artifact", "spillover", "trace", "rough")):
                findings.append("Tie WHAT_CHUMMER6_IS back to trust, receipts, or rough traces instead of leaving the trust story abstract.")
        if name == "current_phase" and not any(
            token in lowered for token in ("trust", "receipt", "math", "before polish", "before the paint", "concept", "idea")
        ):
            findings.append("CURRENT_PHASE should explain that concept work and trust work still come before anything product-shaped.")
        if name == "current_status" and not any(token in lowered for token in ("guide", "horizon", "issue tracker", "artifact", "trace", "rough", "concept")):
            findings.append("CURRENT_STATUS should point to visible explanation surfaces or clearly provisional artifacts, not drift back into generic product status talk.")
        if name == "current_status" and not any(token in intro_lowered for token in ("current", "today", "right now", "status")):
            findings.append("CURRENT_STATUS should sound like an honest status readout in the opening line, not a generic product pitch.")
        if any(
            phrase in intro_lowered
            for phrase in (
                "the honest thing on offer right now",
                "there is no dependable software surface",
                "right now the dependable public surface",
                "still closer to an idea than to a dependable tool",
            )
        ):
            findings.append("Keep root-page openings distinct. Do not recycle the same defensive disclaimer frame across the public guide.")
        if name == "public_surfaces":
            if not any(token in lowered for token in ("guide", "issue tracker", "horizon", "artifact", "trace", "public surface")):
                findings.append("PUBLIC_SURFACES should name the visible public surfaces directly instead of speaking in generalities.")
            if not any(token in intro_lowered for token in ("public surface", "guide", "issue tracker", "horizon", "artifact", "trace")):
                findings.append("PUBLIC_SURFACES should open by naming the visible surfaces, not with a generic product hook.")
            if any(token in lowered for token in ("booster", "participate")):
                findings.append("Keep booster or participation framing out of general public-surface copy unless the page source explicitly requires it.")
        if name == "faq" and not any(
            token in intro_lowered
            for token in ("question", "questions", "answer", "answers", "can i use", "use it now", "what works", "what is rough", "what's rough")
        ):
            findings.append("FAQ should open like practical user questions are being answered, not like another landing-page pitch.")
        if name == "how_can_i_help" and not any(
            token in intro_lowered for token in ("help", "report", "issue", "watch", "react", "try")
        ):
            findings.append("HOW_CAN_I_HELP should open with a concrete help action, not with another product summary.")
    if section_type == "part":
        if any(token in lowered for token in ("digital handshake", "background systems", "platform posture")):
            findings.append("Keep the part grounded in visible user behavior instead of background-system metaphors.")
        if any(phrase in lowered for phrase in ("coordination story", "public posture", "hosted posture", "coordination lane")):
            findings.append("Translate hosted coordination into visible public jobs like sign-in, participation, shared status, or hosted traces instead of abstract posture language.")
        if any(phrase in lowered for phrase in ("one-off visual reinvention", "one-off visual reinventions", "visual reinvention", "design-system maintenance")):
            findings.append("Keep part copy reader-facing. Do not complain about internal reinvention or maintenance churn.")
        if re.search(r"\b(?:you|your)\b", lowered):
            findings.append("Keep part copy in a detached public voice. Avoid abrupt second-person phrasing like 'you' or 'your'.")
        now_lowered = str(row.get("now", "")).strip().lower()
        if any(token in now_lowered for token in ("migrating", "migration", "forensic auditing", "forensic audit")):
            findings.append("Keep the part `now` field reader-facing. Do not describe internal migration or audit chores when the reader needs the visible public consequence.")
        if any(
            phrase in now_lowered
            for phrase in (
                "today it is mostly",
                "right now it is mostly",
                "for now it is mostly",
                "today it is more",
                "today it is closer to",
            )
        ):
            findings.append("Make each part `now` field name a distinct present-tense trace or missing seam instead of repeating the same generic disclaimer.")
        if name == "hub-registry" and any(
            token in lowered for token in ("replaces", "ensures", "guarantees", "keeps everything labeled", "stops drift")
        ):
            findings.append("Keep Hub Registry in concept or future-tense posture. Do not describe it as a live public service that already replaces chaos today.")
        if name == "hub-registry" and not any(token in lowered for token in ("artifact", "shelf", "catalog", "intake", "label", "archive")):
            findings.append("Translate Hub Registry into the public job it would do: labeling, shelving, or cataloging rough artifacts so they do not turn into rumor.")
        if name == "media-factory" and not any(token in lowered for token in ("packet", "image", "render", "publish", "artifact", "media")):
            findings.append("Translate Media Factory into the public job it would do: turning rough packets or images into cleaner artifacts without cutting the source loose.")
        if name == "ui" and not any(token in lowered for token in ("inspect", "sheet", "build", "cross-check", "compare", "proof")):
            findings.append("Keep UI tied to inspectable builds and visible cross-checking instead of abstract technical chores.")
        if name == "ui-kit" and not any(token in lowered for token in ("shared visual", "shared cues", "same language", "surface", "chrome")):
            findings.append("Keep UI Kit tied to the shared visual language a reader would actually notice instead of internal design-system maintenance talk.")
    if section_type == "horizon":
        rollout = horizon_rollout_context(name, item)
        access_posture = rollout["access_posture"].lower()
        free_later_intent = rollout["free_later_intent"]
        meanwhile_lowered = str(row.get("meanwhile", "")).replace("\r\n", "\n").replace("\r", "\n").lower()
        why_waits_lowered = str(row.get("why_waits", "")).strip().lower()
        table_scene_lines = [
            line.strip()
            for line in str(row.get("table_scene", "")).replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        ]
        meanwhile_lines = [
            line.strip()
            for line in str(row.get("meanwhile", "")).replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        ]
        if table_scene_lines and not (5 <= len(table_scene_lines) <= 9):
            findings.append("Make `table_scene` a fuller mini-scene with 5-9 short playable beats.")
        if meanwhile_lines and (len(meanwhile_lines) < 2 or len(meanwhile_lines) > 4 or any(not line.startswith("- ") for line in meanwhile_lines)):
            findings.append("Format `meanwhile` as 2-4 short bullet lines starting with `- `.")
        if name == "table-pulse" and any(line.count(",") >= 2 for line in meanwhile_lines):
            findings.append("Keep TABLE PULSE `meanwhile` in short cautionary sentences, not comma-heavy feature-list bullets.")
        if any(
            token in meanwhile_lowered
            for token in ("provenance", "cache recovery", "manifests", "vendor dashboards", "local-first ingestion", "ingestion")
        ):
            findings.append("Translate `meanwhile` into plain public language. Do not rely on internal shorthand like provenance, cache recovery, manifests, or vendor dashboards without explaining the user-facing consequence.")
        if name == "table-pulse" and any(
            token in lowered for token in ("spotlight ghost", "local-first ingestion", "ingestion pipeline", "operator replay")
        ):
            findings.append("Keep TABLE PULSE in post-session coaching language. Do not drift into internal replay or ingestion implementation terms.")
        if any(
            phrase in meanwhile_lowered or phrase in why_waits_lowered
            for phrase in (
                "this lane",
                "future-facing",
                "only matters if",
                "publication prep",
                "behind the scenes",
                "one-way export",
            )
        ):
            findings.append("Keep `meanwhile` and `why_waits` reader-facing. Avoid internal status-board language like lane management, publication prep, or behind-the-scenes process talk.")
        if "booster-first" in meanwhile_lowered or "booster-first" in why_waits_lowered or "booster first" in meanwhile_lowered or "booster first" in why_waits_lowered:
            findings.append("Translate booster-first into plain public language like optional paid preview or booster preview. Do not rely on internal shorthand.")
        if access_posture == "booster_first" and not any(token in lowered for token in ("booster", "preview", "participate")):
            findings.append("Explain the booster-first preview posture plainly instead of implying a vague wait.")
        if free_later_intent and not any(
            token in lowered
            for token in ("wider access", "broader access", "not a permanent paywall", "free later", "free baseline")
        ):
            findings.append("State the broad-access or free-later intent when canon provides it.")
        if name == BOOSTER_REFERENCE_HORIZON:
            if "booster lane" in lowered or "booster lanes" in lowered:
                findings.append("Translate booster lane into plain public language like optional paid preview. Do not rely on internal shorthand.")
            if "paid booster preview" in lowered or "paid booster previews" in lowered:
                findings.append("Translate booster disclosure into plain public language like optional paid preview. Do not lean on booster-internal phrasing.")
            if not any(token in lowered for token in ("expensive", "review-heavy", "careful review", "booster-first", "preview")):
                findings.append("Explain that this lane stays expensive and review-heavy even in preview.")
            if not any(token in lowered for token in ("no promise", "not promise", "might get nothing", "may get nothing", "nothing useful", "not guaranteed")):
                findings.append("Say plainly that this lane may still produce nothing useful or shippable.")
    for phrase in WEAK_COPY_PHRASES:
        if phrase in lowered:
            findings.append(f"Replace generic filler like '{phrase}' with a sharper table-facing, proof-facing, or user-action detail.")
    deduped: list[str] = []
    for finding in findings:
        normalized = str(finding or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:8]


def build_copy_polish_prompt(
    *,
    section_type: str,
    name: str,
    item: dict[str, object],
    draft: dict[str, object],
    findings: list[str],
    global_ooda: dict[str, object],
    section_ooda: dict[str, object],
) -> str:
    keys = COPY_KEYS_BY_SECTION.get(section_type, ())
    context_payload: dict[str, object] = {"draft": draft, "findings": findings}
    if section_type == "page":
        context_payload["source"] = str(item.get("source", "")).strip()
        context_payload["supporting_public_context"] = page_supporting_context(name)
    elif section_type == "part":
        context_payload["title"] = str(item.get("title", "")).strip()
        context_payload["tagline"] = str(item.get("tagline", "")).strip()
        context_payload["when"] = str(item.get("when", "")).strip()
        context_payload["why"] = str(item.get("why", "")).strip()
        context_payload["now"] = str(item.get("now", "")).strip()
        context_payload["notice"] = list(item.get("notice") or [])
        context_payload["limits"] = list(item.get("limits") or [])
        context_payload["go_deeper_links"] = list(item.get("go_deeper_links") or [])
        context_payload["supporting_public_context"] = part_supporting_context(name)
    else:
        rollout = horizon_rollout_context(name, item)
        context_payload["title"] = str(item.get("title", "")).strip()
        context_payload["hook"] = str(item.get("hook", "")).strip()
        context_payload["problem"] = str(item.get("problem", "")).strip()
        context_payload["use_case"] = str(item.get("use_case", "")).strip()
        context_payload["access_posture"] = rollout["access_posture"]
        context_payload["resource_burden"] = rollout["resource_burden"]
        context_payload["booster_nudge"] = rollout["booster_nudge"]
        context_payload["free_later_intent"] = rollout["free_later_intent"]
        context_payload["booster_api_scope_note"] = rollout["booster_api_scope_note"]
        context_payload["booster_outcome_note"] = rollout["booster_outcome_note"]
        context_payload["foundations"] = list(item.get("foundations") or [])
    return f"""You are revising downstream-only {section_type} copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys {", ".join(keys)}.

Revision rules:
- keep what is already sharp, but rewrite the weak or generic parts
- prioritize concrete user value, proof, and current public actions over abstract platform framing
- avoid generic filler like toolkit, foundation, digital handshake, background systems, or vague future posture
- keep the output public-safe, reader-first, and distinct
- do not add exact current capabilities that are not explicit in the section context
- for root/page copy, treat global OODA as tone guidance only; exact facts must come from the page source or supporting public context
- if the section context is vague, stay grounded in proof shelf, current drop, guide, release shelf, horizon shelf, issue tracker, or local-first posture instead of inventing narrower feature claims
- do not improvise subsystem, edition, or character-sheet specifics unless the section context explicitly names them
- for root/page copy, replace unsupported subsystem specifics with reader-visible proof surfaces, current drop, route names, or local-first posture
- for root/page copy, replace unsupported repo-wide hints like multi-era support, scripted-rule internals, or mobile-ready claims with proof surfaces, local-first posture, or the current drop unless the page context explicitly names them
- for root/page copy, replace niche gear, augment, or modifier anecdotes with general table-friction language unless the page context explicitly names them
- for root/page copy, replace certainty words like deterministic truth or solved math with rougher language about proofs, receipts, inspection, and trust still being earned
- for root/page copy, do not claim the build already works offline, works without the grid, or keeps every surface on-device unless the page context explicitly says so; local-first is enough
- for root/page copy, do not claim that every result, every outcome, or every calculation already carries a receipt
- for root/page copy, do not say the public surfaces already verify rules math broadly; keep the claim scoped to the specific proofs visible on the proof shelf
- keep booster / participate caveats scoped to KARMA FORGE-style expensive-horizon copy unless the section context explicitly requires them
- no markdown fences
{PUBLIC_WRITER_RULES}

Section id: {name}
Section context:
{json.dumps(context_payload, ensure_ascii=True)}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def build_page_grounding_rescue_prompt(
    *,
    name: str,
    item: dict[str, object],
    draft: dict[str, object],
    findings: list[str],
    global_ooda: dict[str, object],
    section_ooda: dict[str, object],
) -> str:
    return f"""You are repairing an overclaimed root-page draft for the human-facing Chummer6 guide.

Task: return a JSON object only with keys intro, body, kicker.

Hard rules:
- use only facts that are explicit in the page source or supporting public context; use global OODA only for tone and ordering
- do not mention specific rules subsystems, stats, cyberware, qualities, initiative, health, edition labels, scripted internals, device swaps, session continuity, multi-era support, mobile-ready behavior, or other narrow feature claims unless the provided context explicitly names them
- replace niche gear, augment, or modifier anecdotes with general table-friction language unless the page context explicitly names them
- stay grounded in proof shelf, current drop, release shelf, public guide, horizon shelf, issue tracker, receipts, and local-first posture
- keep the page defensive and honest about concept-stage reality
- if the page is about what Chummer6 is, explicitly tie it back to trust, receipts, or accidental spillover instead of abstract product-story language
- avoid generic filler like designed to make, providing, ensuring that, built to, or similar soft product mush
- intro should say what this page means to a normal reader
- body should name visible proof or action surfaces without improvising deeper capability claims
- kicker should end on one concrete next action, proof surface, or honest caution
- no markdown fences
{PUBLIC_WRITER_RULES}

Page id: {name}
Page source:
{str(item.get("source", "")).strip()}

Supporting public context:
{json.dumps(page_supporting_context(name), ensure_ascii=True)}

Failed draft:
{json.dumps(draft, ensure_ascii=True)}

Why the draft failed:
{json.dumps(findings, ensure_ascii=True)}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def fallback_page_copy(name: str, item: dict[str, object], global_ooda: dict[str, object]) -> dict[str, str]:
    page_id = str(name or "").strip()
    act = dict(global_ooda.get("act") or {}) if isinstance(global_ooda, dict) else {}
    tagline = str(act.get("landing_tagline") or "An idea for less mystical Shadowrun math.").strip()
    if page_id == "readme":
        return {
            "intro": "Chummer6 is still concept-stage: an idea for table rulings that are easier to inspect before anyone is asked to trust them.",
            "body": "The project is chasing visible reasoning instead of trust-me table lore. What exists in public is still mostly guide work, future lanes, issue threads, and the occasional rough artifact that escaped into view by accident.",
            "kicker": "If the idea sounds useful, read the guide and judge the rough traces cautiously.",
        }
    if page_id == "start_here":
        return {
            "intro": "If you only look once, use this page to choose the next shelf.",
            "body": "Start with the short explanation if you want the pitch, Current Status if you want the honest public state, the future lanes if you want the ambition, and the issue tracker if you want to watch reality push back on the idea.",
            "kicker": "Pick the shelf that matches your curiosity and move.",
        }
    if page_id == "what_chummer6_is":
        return {
            "intro": "Chummer6 is an idea about letting Shadowrun math show its work.",
            "body": "The ambition is visible reasoning instead of trust-me answers, but the honest present tense is still concept work with only a few inspectable traces. If something concrete exists, good; if it does not, the direction still matters more than the lucky artifact.",
            "kicker": "Judge the direction first and the stray evidence second.",
        }
    if page_id == "faq":
        return {
            "intro": "Practical question first: does anything usable actually exist yet?",
            "body": "Not in a dependable product sense. There may be guide pages, issue threads, or stray artifacts worth inspecting, but they should be read as experiments or lucky public traces, not as promised software.",
            "kicker": "If something works today, treat it as lucky evidence, not stable support.",
        }
    if page_id == "how_can_i_help":
        return {
            "intro": "Help starts with reacting to the idea honestly, not pretending there is a stable build to adopt.",
            "body": "If you find a rough artifact, break it and report what that teaches. If you do not, point at the table pain, the bad assumption, or the future lane that seems worth pursuing.",
            "kicker": "Useful help is still mostly critique, direction, and reality checks.",
        }
    if page_id == "where_to_go_deeper":
        return {
            "intro": "Go deeper only after you decide whether the idea itself sounds worth following.",
            "body": "Stay with the guide and horizons if you want the public story. Drop into repos or issues only when you want to inspect stray implementation evidence or argue about a specific choice.",
            "kicker": "Start with the concept; only chase artifacts when the concept earns it.",
        }
    if page_id == "current_phase":
        return {
            "intro": "The current phase is trust work before product posture.",
            "body": "The project is still trying to make rulings inspectable, bounded, and worth trusting before it earns the right to call itself software. In public that mostly shows up as a clearer guide, a sharper horizon shelf, an issue tracker, and the occasional rough artifact that still needs to be treated as accidental evidence instead of support.",
            "kicker": "Read the guide, watch the horizons, and assume the artifacts are still rough.",
        }
    if page_id == "current_status":
        return {
            "intro": "Status first: the guide is solid, and everything else is still provisional.",
            "body": "What is consistently visible today is the guide, the horizon shelf, and a few rough artifacts. Anything more concrete than that may still break, move, or vanish without ceremony.",
            "kicker": "Treat the explanations as current and the software traces as provisional.",
        }
    if page_id == "public_surfaces":
        return {
            "intro": "The deliberate public surfaces are the guide, the horizon shelf, and the issue tracker.",
            "body": "If there is a proof artifact, rough build, or screenshot, treat it as a rough trace instead of a dependable product surface.",
            "kicker": "The safe assumption is still that almost nothing exists on purpose.",
        }
    if page_id == "parts_index":
        return {
            "intro": "The parts mostly describe how the idea would eventually split if it ever hardens into software.",
            "body": "Use the part map as a conceptual diagram, not as evidence that all of those layers already exist in a usable form. If a part seems to have a visible artifact, treat that as an exception.",
            "kicker": "Read the parts as responsibilities the idea would need, not as finished modules.",
        }
    if page_id == "horizons_index":
        return {
            "intro": "Horizons are idea lanes, not current promises.",
            "body": "They exist to show what kinds of table pain this concept might tackle if it survives long enough to earn that scope. Read them as contingent thoughts with vivid use cases, not as a release schedule disguised as lore.",
            "kicker": "If a horizon sounds useful, watch it; if it sounds done, distrust the sentence.",
        }
    return {}


def fallback_part_copy(name: str, item: dict[str, object]) -> dict[str, str]:
    curated = {
        "core": {
            "when": "If this idea ever becomes trustworthy, core is where the math accountability would have to live.",
            "why": "Right now it mostly marks the responsibility that would need to exist before anyone should trust a rules engine.",
            "now": "Today it mostly shows up as trust language, rough receipts, and arguments about what the math would need to explain before anyone should lean on it.",
        },
        "ui": {
            "when": "If something user-facing ever becomes real, UI is where people would feel the idea instead of just reading about it.",
            "why": "It would eventually turn abstract rules intent into something a person could inspect.",
            "now": "Right now this mostly means rough workbench traces that show how a build might become inspectable. It is still not a user surface that has earned trust.",
        },
        "mobile": {
            "when": "If this concept ever survives real table chaos, mobile is where that claim would get tested hardest.",
            "why": "It is the imagined jump from prep talk to software that could survive actual play.",
            "now": "Today mobile is still mostly pressure from the real table: reconnects, bad signal, and movement are the test, not a solved lane.",
        },
        "hub": {
            "when": "If there is ever a hosted front door, hub is the layer that would have to keep it coherent.",
            "why": "It would keep sign-in, public participation, and hosted status from turning into scavenger hunts or backroom admin work.",
            "now": "Today the visible bits are the front door, the participation route, and a few hosted traces you can inspect, but they are still too provisional to treat like a finished service.",
        },
        "ui-kit": {
            "when": "If the project ever stops looking accidental, UI Kit is part of how that would happen.",
            "why": "A shared visual language would make future surfaces easier to read instead of forcing every reader to relearn the interface from scratch.",
            "now": "Publicly, you can already spot repeated badges, chrome, and dense-data cues across the rough guide and proof surfaces, but it is still more of a shared visual direction than a polished kit to rely on.",
        },
        "hub-registry": {
            "when": "Registry is where public artifacts would stay findable instead of turning into rumor.",
            "why": "It helps a reader tell which artifact is current, which one is rough, and where each one came from.",
            "now": "Publicly, the job is simple: keep artifacts findable and comparable instead of making people guess which file matters.",
        },
        "media-factory": {
            "when": "If the concept ever produces polished packets or imagery, media-factory is the lane that would have to do it without lying.",
            "why": "It is the imagined render plant for outputs that still need provenance and restraint.",
            "now": "Today it mostly means rough packet and image work that still has to prove it can clean things up without cutting the source trail loose.",
        },
        "design": {
            "when": "Somebody wants to understand what the idea is trying to become before caring whether any artifact exists today.",
            "why": "It gives a reader one place to see what the project is aiming for before stray artifacts start sending mixed signals.",
            "now": "Publicly, the design shelf is still the clearest explanation of what the project wants to become, which is why it often makes more sense than the software traces around it.",
        },
    }.get(str(name or "").strip())
    if isinstance(curated, dict):
        return {key: str(curated.get(key, "")).strip() for key in ("when", "why", "now")}
    return {
        "when": str(item.get("when", "")).strip(),
        "why": str(item.get("why", "")).strip(),
        "now": str(item.get("now", "")).strip(),
    }


def fallback_horizon_copy(name: str, item: dict[str, object]) -> dict[str, str]:
    curated: dict[str, dict[str, str]] = {
        "nexus-pan": {
            "hook": "Shared state survives dirty reconnects without turning the table into a trust exercise.",
            "problem": "A reconnect should be annoying, not campaign-threatening.",
            "table_scene": "\n".join(
                [
                    "The dead zone lifts just as the van starts rolling again.",
                    "GM: Your phone died; the run did not.",
                    "Player: Good. I only want to lose battery, not state.",
                    "Rigger: The loadout came back where I left it.",
                    "Chummer6: Missed actions replayed. Current penalties still attached.",
                    "Face: So we keep moving instead of rebuilding the scene from memory.",
                    "GM: That is the whole fantasy.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- Shared-state continuity only counts if reconnects are boring and honest.",
                    "- Reconnect chaos and drift cleanup still have to stop lying before this becomes real.",
                ]
            ),
            "why_great": "It could let the session survive dirty reconnects without making the table re-litigate what was true five minutes ago.",
            "why_waits": "Shared state is only useful if reconnects preserve trust instead of inventing a cleaner history than the session actually had.",
            "pitch_line": "Let the session survive the reconnect without pretending the drift never happened.",
        },
        "alice": {
            "hook": "Grounded what-if analysis before the bad build hits public view.",
            "problem": "It is cheaper to catch a weak build early than to apologize for it later.",
            "table_scene": "\n".join(
                [
                    "Player: I thought this build was clean.",
                    "GM: ALICE says the weak point shows up on turn two, not after the campaign starts.",
                    "Decker: Good. I would rather get roasted by a preflight than by the whole table.",
                    "Chummer6: The hallway goes loud, your soak folds, and the plan stops being clever.",
                    "Player: Show me the evidence, not the vibes.",
                    "GM: Exactly. Humiliation is cheaper in preview.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- Comparative analysis has to stay tied to visible proof instead of fuzzy assistant theater.",
                    "- Preflight checks only matter if they are explainable enough for a skeptical table.",
                ]
            ),
            "why_great": "It could catch weak assumptions before they become public embarrassment or campaign drag.",
            "why_waits": "Advice that sounds clever but cannot show its work is worse than silence, so this stays hypothetical until the evidence holds.",
            "pitch_line": "Catch the weak build before the table has to.",
        },
        "karma-forge": {
            "hook": "House rules with governance instead of fork chaos.",
            "problem": "Tables want variation without turning every campaign into unreadable folklore.",
            "table_scene": "\n".join(
                [
                    "GM: I want the house rule, not the forked-code religion that comes with it.",
                    "Chummer6: Diff strip loaded. Two collisions, one rollback path, one approval still pending.",
                    "Player: Fine, but I want to know whether it still plays nice with the rest of the sheet.",
                    "Rigger: And I want rollback before somebody ships a clever disaster.",
                    "A stamped approval card lands on the bench and nobody trusts it yet.",
                    "GM: That is why this is a forge and not a pastebin.",
                    "Player: Good. Keep the receipts hotter than the hype.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- Approval, compatibility, and rollback still eat real effort before any ruleset preview is safe.",
                    "- It is still expensive, review-heavy, and easy to overpromise if the receipts are weak.",
                    "- Broader access later is still the hope, but nobody should read that as a promise that the work lands cleanly or soon.",
                ]
            ),
            "why_great": "It could let tables evolve rules without splintering into silent canon, unreadable forks, or post-hoc apology culture.",
            "why_waits": "At most this starts as an optional paid preview because safe review still costs real effort, and even then the pass may still produce nothing useful or shippable.",
            "pitch_line": "Evolve the rules without pretending every clever hack deserves to become canon.",
        },
        "jackpoint": {
            "hook": "Finished-feeling packets that still show where the facts came from.",
            "problem": "Dossiers and recaps get much less useful the moment polish starts making facts up.",
            "table_scene": "\n".join(
                [
                    "Face: The packet finally tells me which guard swaps at 02:10 and which door was chained shut last night.",
                    "GM: Good. Brief the team from that instead of from my raw notes.",
                    "Decker: Every claim still points back to the witness note, camera grab, or receipt it came from.",
                    "Rigger: So if one timing is wrong, we can see which source lied instead of arguing with the whole dossier.",
                    "GM: Exactly. Clean enough to brief from, honest enough to cross-check.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- The packet still has to stay readable without hiding where each claim came from.",
                    "- If polish makes the facts feel cleaner than they were, the whole thing gets less trustworthy, not more.",
                ]
            ),
            "why_great": "It could turn grim notes into packets people actually want to open, use, and share at the table.",
            "why_waits": "A dossier that reads beautifully but blurs the evidence is still a bad brief, so this stays hypothetical until the proof survives the polish.",
            "pitch_line": "Make the packet feel finished without making the facts up.",
        },
        "runsite": {
            "hook": "Mission spaces that become legible before the bullets do.",
            "problem": "A briefing is still doing half the work if the table cannot read the space.",
            "table_scene": "\n".join(
                [
                    "A ghosted floor plan climbs the wet concrete between the crates.",
                    "GM: Here is the site before anyone has to improvise the floor plan from memory.",
                    "Player: Good. I would like to know where the exits are before I need one.",
                    "Rigger: Route overlay makes sense for once.",
                    "Chummer6: West stair choke point marked. Two cleaner ingress lanes still open.",
                    "Face: So the room stops being a surprise punishment box.",
                    "GM: Exactly.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- Briefing-space artifacts have to stay bounded and useful instead of drifting into fake live-session truth.",
                    "- The lane only works if mission-space clarity gets better without pretending to be a VTT replacement.",
                ]
            ),
            "why_great": "It could make mission spaces easier to read before the action starts, which is usually when that clarity matters most.",
            "why_waits": "Spatial help is only worth shipping if it stays bounded to briefing and planning instead of promising a whole combat shell by accident.",
            "pitch_line": "Make the site legible before the run makes it urgent.",
        },
        "runbook-press": {
            "hook": "Long-form books that stay coherent after the second panic revision.",
            "problem": "A real primer should not need ten tools, three dashboards, and a superstition to stay coherent.",
            "table_scene": "\n".join(
                [
                    "Writer: I want the handbook, not a graveyard of near-final exports.",
                    "GM: And I want the book to stay reusable after the first panic revision.",
                    "Fresh proof tabs hang off the layout rail while the old version sulks in a tray.",
                    "Player: If it looks finished, it should still point back to real source truth.",
                    "Writer: Exactly. Long form without folklore.",
                    "Chummer6: Source anchors intact. Reuse survives this revision.",
                    "GM: That would be a first.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- A long guide is only worth it if later revisions still point back to the source instead of turning into copy-paste folklore.",
                    "- If every update turns the book into salvage work, nobody should pretend the work is ready.",
                ]
            ),
            "why_great": "It could make primers, handbooks, and campaign books feel like real products instead of heroic document salvage.",
            "why_waits": "A handbook only earns trust once revisions stop making the source harder to trace and the next edition less reusable.",
            "pitch_line": "Publish the book without turning it into an archaeological site.",
        },
        "table-pulse": {
            "hook": "Post-session coaching without pretending the software was secretly the GM all along.",
            "problem": "Tables drift, pacing breaks, and spotlight balance goes weird long before anyone can explain why.",
            "table_scene": "\n".join(
                [
                    "GM: I know the energy broke somewhere, I just cannot point to the exact moment.",
                    "Player: Show me the drift after the session, not while I am still in the scene.",
                    "Chummer6: Spotlight weight spiked after the third interruption, then one player vanished for twenty minutes of airtime.",
                    "Face: Spotlight balance would be nice without live surveillance vibes.",
                    "GM: Good. Post-session coaching, not a hall monitor.",
                    "Player: That line matters.",
                ]
            ),
            "meanwhile": "\n".join(
                [
                    "- This lane only works if the consent boundary stays obvious and the replay stays easy to ignore.",
                    "- The feedback has to stay post-session coaching instead of drifting into a live authority voice over the table.",
                ]
            ),
            "why_great": "It could help a GM see where pacing, interruptions, or spotlight balance broke without pretending the software ran the table.",
            "why_waits": "Anything this sensitive has to stay opt-in, bounded, and post-session or it turns from coaching into surveillance theater.",
            "pitch_line": "Find the drift after the session without letting the software become the table cop.",
        },
    }
    fallback = curated.get(str(name or "").strip())
    if isinstance(fallback, dict):
        return {key: str(fallback.get(key, "")).strip() for key in ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line")}
    rollout = horizon_rollout_context(name, item)
    return {
        "hook": str(item.get("hook", "")).strip(),
        "problem": str(item.get("problem", "")).strip(),
        "table_scene": "",
        "meanwhile": "",
        "why_great": str(item.get("use_case", "")).strip(),
        "why_waits": str(rollout.get("booster_nudge") or "").strip(),
        "pitch_line": str(item.get("hook", "")).strip(),
    }


def polish_copy_row(
    *,
    section_type: str,
    name: str,
    row: dict[str, object],
    item: dict[str, object],
    global_ooda: dict[str, object],
    section_ooda: dict[str, object],
    model: str,
) -> dict[str, object]:
    keys = COPY_KEYS_BY_SECTION.get(section_type, ())
    current = dict(row)
    findings = copy_quality_findings(section_type, name, current, item)
    try:
        assert_public_reader_safe(current, context=f"{section_type}:{name}:draft")
    except Exception as exc:
        findings = [*findings, str(exc)]
    deduped_findings: list[str] = []
    for finding in findings:
        normalized = str(finding or "").strip()
        if normalized and normalized not in deduped_findings:
            deduped_findings.append(normalized)
    if not deduped_findings:
        return current
    for _attempt in range(2):
        result = chat_json(
            build_copy_polish_prompt(
                section_type=section_type,
                name=name,
                item=item,
                draft=current,
                findings=deduped_findings,
                global_ooda=global_ooda,
                section_ooda=section_ooda,
            ),
            model=model,
            skill_key=PUBLIC_WRITER_SKILL_KEY,
        )
        polished = {
            key: str(result.get(key, "")).strip()
            for key in keys
            if str(result.get(key, "")).strip()
        }
        if len(polished) < len(keys):
            break
        if section_type == "horizon" and "meanwhile" in polished:
            polished["meanwhile"] = normalize_horizon_meanwhile(str(polished.get("meanwhile") or ""))
        next_findings = copy_quality_findings(section_type, name, polished, item)
        try:
            assert_public_reader_safe(polished, context=f"{section_type}:{name}:polished")
        except Exception as exc:
            next_findings.append(str(exc))
        deduped_findings = []
        for finding in next_findings:
            normalized = str(finding or "").strip()
            if normalized and normalized not in deduped_findings:
                deduped_findings.append(normalized)
        current = polished
        if not deduped_findings:
            return current
    if section_type == "page":
        result = chat_json(
            build_page_grounding_rescue_prompt(
                name=name,
                item=item,
                draft=current,
                findings=deduped_findings,
                global_ooda=global_ooda,
                section_ooda=section_ooda,
            ),
            model=model,
            skill_key=PUBLIC_WRITER_SKILL_KEY,
        )
        rescued = {
            key: str(result.get(key, "")).strip()
            for key in keys
            if str(result.get(key, "")).strip()
        }
        if len(rescued) == len(keys):
            rescue_findings = copy_quality_findings(section_type, name, rescued, item)
            try:
                assert_public_reader_safe(rescued, context=f"{section_type}:{name}:rescued")
            except Exception as exc:
                rescue_findings.append(str(exc))
            deduped_findings = []
            for finding in rescue_findings:
                normalized = str(finding or "").strip()
                if normalized and normalized not in deduped_findings:
                    deduped_findings.append(normalized)
            if not deduped_findings:
                return rescued
        fallback = fallback_page_copy(name, item, global_ooda)
        if fallback:
            fallback_findings = copy_quality_findings(section_type, name, fallback, item)
            try:
                assert_public_reader_safe(fallback, context=f"{section_type}:{name}:fallback")
            except Exception as exc:
                fallback_findings.append(str(exc))
            deduped_findings = []
            for finding in fallback_findings:
                normalized = str(finding or "").strip()
                if normalized and normalized not in deduped_findings:
                    deduped_findings.append(normalized)
            if not deduped_findings:
                return fallback
    raise RuntimeError(f"copy_polish_failed:{section_type}:{name}:{' | '.join(deduped_findings[:6])}")


def finalize_copy_row(
    *,
    section_type: str,
    name: str,
    row: dict[str, object],
    item: dict[str, object],
    global_ooda: dict[str, object],
    section_ooda: dict[str, object],
    model: str,
    humanize_keys: tuple[str, ...],
    target_prefix: str,
    prefer_brain_humanizer: bool,
) -> dict[str, object]:
    if section_type == "page":
        fallback = fallback_page_copy(name, item, global_ooda)
        if fallback:
            humanize_mapping_fields_with_mode(
                fallback,
                humanize_keys,
                target_prefix=target_prefix,
                brain_only=True,
            )
            fallback_findings = copy_quality_findings(section_type, name, fallback, item)
            try:
                assert_public_reader_safe(fallback, context=f"{section_type}:{name}:curated")
            except Exception as exc:
                fallback_findings.append(str(exc))
            fallback_findings = [str(entry or "").strip() for entry in fallback_findings if str(entry or "").strip()]
            if not fallback_findings:
                return fallback
    if section_type == "part":
        fallback = fallback_part_copy(name, item)
        if fallback:
            humanize_mapping_fields_with_mode(
                fallback,
                humanize_keys,
                target_prefix=target_prefix,
                brain_only=True,
            )
            fallback_findings = copy_quality_findings(section_type, name, fallback, item)
            try:
                assert_public_reader_safe(fallback, context=f"{section_type}:{name}:curated")
            except Exception as exc:
                fallback_findings.append(str(exc))
            fallback_findings = [str(entry or "").strip() for entry in fallback_findings if str(entry or "").strip()]
            if not fallback_findings:
                return fallback
    if section_type == "horizon":
        fallback = fallback_horizon_copy(name, item)
        if fallback:
            if "meanwhile" in fallback:
                fallback["meanwhile"] = normalize_horizon_meanwhile(str(fallback.get("meanwhile") or ""))
            humanize_mapping_fields_with_mode(
                fallback,
                humanize_keys,
                target_prefix=target_prefix,
                brain_only=True,
            )
            fallback_findings = copy_quality_findings(section_type, name, fallback, item)
            try:
                assert_public_reader_safe(fallback, context=f"{section_type}:{name}:curated")
            except Exception as exc:
                fallback_findings.append(str(exc))
            fallback_findings = [str(entry or "").strip() for entry in fallback_findings if str(entry or "").strip()]
            if not fallback_findings:
                return fallback
    current = dict(row)
    humanize_mapping_fields_with_mode(
        current,
        humanize_keys,
        target_prefix=target_prefix,
        brain_only=prefer_brain_humanizer,
    )
    if section_type == "horizon" and "meanwhile" in current:
        current["meanwhile"] = normalize_horizon_meanwhile(str(current.get("meanwhile") or ""))
    findings = copy_quality_findings(section_type, name, current, item)
    try:
        assert_public_reader_safe(current, context=f"{section_type}:{name}:final")
    except Exception as exc:
        findings.append(str(exc))
    findings = [str(entry or "").strip() for entry in findings if str(entry or "").strip()]
    if not findings:
        return current

    repaired = polish_copy_row(
        section_type=section_type,
        name=name,
        row=current,
        item=item,
        global_ooda=global_ooda,
        section_ooda=section_ooda,
        model=model,
    )
    humanize_mapping_fields_with_mode(
        repaired,
        humanize_keys,
        target_prefix=target_prefix,
        brain_only=True,
    )
    if section_type == "horizon" and "meanwhile" in repaired:
        repaired["meanwhile"] = normalize_horizon_meanwhile(str(repaired.get("meanwhile") or ""))
    repaired_findings = copy_quality_findings(section_type, name, repaired, item)
    try:
        assert_public_reader_safe(repaired, context=f"{section_type}:{name}:final_repaired")
    except Exception as exc:
        repaired_findings.append(str(exc))
    repaired_findings = [str(entry or "").strip() for entry in repaired_findings if str(entry or "").strip()]
    if not repaired_findings:
        return repaired

    if section_type == "page":
        fallback = fallback_page_copy(name, item, global_ooda)
        if fallback:
            humanize_mapping_fields_with_mode(
                fallback,
                humanize_keys,
                target_prefix=target_prefix,
                brain_only=True,
            )
            fallback_findings = copy_quality_findings(section_type, name, fallback, item)
            try:
                assert_public_reader_safe(fallback, context=f"{section_type}:{name}:final_fallback")
            except Exception as exc:
                fallback_findings.append(str(exc))
            fallback_findings = [str(entry or "").strip() for entry in fallback_findings if str(entry or "").strip()]
            if not fallback_findings:
                return fallback
            repaired_findings = fallback_findings

    raise RuntimeError(f"final_copy_validation_failed:{section_type}:{name}:{' | '.join(repaired_findings[:6])}")


def collect_interest_signals() -> dict[str, object]:
    def add_tags(text: str, *, extra: list[str] | None = None) -> None:
        lowered = str(text or "").lower()
        for token, tag in PUBLIC_SIGNAL_TAG_HINTS:
            if token in lowered and tag not in tags:
                tags.append(tag)
        for tag in extra or []:
            normalized = str(tag or "").strip()
            if normalized and normalized not in tags:
                tags.append(normalized)

    def add_snippet(label: str, text: str, *, extra_tags: list[str] | None = None, limit: int = 220) -> None:
        compact = short_sentence(text, limit=limit)
        if not compact:
            return
        snippets.append(f"[{label}] {compact}")
        add_tags(compact, extra=extra_tags)

    snippets: list[str] = []
    tags: list[str] = []
    for row in _public_card_rows()[:6]:
        label = f"feature:{str(row.get('id') or '').strip() or 'card'}"
        text = " ".join(
            part
            for part in (
                str(row.get("title") or "").strip(),
                str(row.get("summary") or "").strip(),
                str(row.get("pain") or "").strip(),
                str(row.get("payoff") or "").strip(),
            )
            if part
        )
        lowered = f"{label} {text}".lower()
        if any(
            token in lowered
            for token in (
                "feature:get_the_poc",
                "feature:sign_in_follow",
                "deterministic rules truth",
                "current drop",
            )
        ):
            continue
        add_snippet(label, text)
    part_signal_order = ["core", "ui", "mobile", "hub", "design"]
    for slug in part_signal_order:
        row = PARTS.get(slug)
        if not isinstance(row, dict):
            continue
        text = " ".join(
            part
            for part in (
                str(row.get("title") or "").strip(),
                str(row.get("tagline") or "").strip(),
                str(row.get("why") or "").strip(),
                str(row.get("now") or "").strip(),
            )
            if part
        )
        add_snippet(f"part:{slug}", text)
    horizon_signal_order = ["nexus-pan", "alice", "karma-forge", "jackpoint", "runsite", "runbook-press", "table-pulse"]
    for slug in horizon_signal_order:
        row = HORIZONS.get(slug)
        if not isinstance(row, dict):
            continue
        rollout = horizon_rollout_context(slug, row)
        text = " ".join(
            part
            for part in (
                str(row.get("title") or "").strip(),
                str(row.get("hook") or "").strip(),
                str(row.get("problem") or "").strip(),
                rollout["booster_nudge"],
                rollout["free_later_intent"],
            )
            if part
        )
        add_snippet(
            f"horizon:{slug}",
            text,
            extra_tags=[
                rollout["access_posture"],
                "future_horizons",
            ],
        )
    for section_id, section in FAQ.items():
        if not isinstance(section, dict):
            continue
        for entry in section.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            question = str(entry.get("question") or "").strip()
            answer = str(entry.get("answer") or "").strip()
            if question:
                add_snippet(f"faq:{section_id}", f"{question} {answer}", extra_tags=["faq"])
    return {"tags": tags, "snippets": snippets[:16]}


def build_ooda_prompt(signals: dict[str, object]) -> str:
    tags = ", ".join(str(tag) for tag in signals.get("tags", []))
    source_excerpt = "\n\n".join(str(line) for line in signals.get("snippets", []))
    return f"""You are the OODA brain for Chummer6, the human-facing guide repo for the Chummer ecosystem.

Task: return a JSON object only with top-level keys observe, orient, decide, act.

Required shape:
- observe: source_signal_tags, source_excerpt_labels, audience_needs, user_interest_signals, risks
- orient: audience, promise, tension, why_care, current_focus, visual_direction, humor_line, signals_to_highlight, banned_terms
- decide: information_order, tone_rules, horizon_policy, media_strategy, overlay_policy, cta_strategy
- act: landing_tagline, landing_intro, what_it_is, watch_intro, horizon_intro

Rules:
- think like a sharp human guide writer, not a compliance bot
- Shadowrun jargon is welcome
- dry humor is allowed when it makes the point clearer
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- focus on what a curious human would actually care about first
- if the source suggests strong user-facing selling points like multi-era support, Lua/scripted rules, local-first play, explain receipts, grounded dossiers, or dangerous simulation energy, surface them
- if source signals clearly include multi-era support or scripted rules, make at least one landing-facing sentence say so plainly
- do not invent implementation-specific claims unless the source canon makes them explicit
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- keep every field compact and useful
- why_care and current_focus should be short arrays of punchy strings
- signals_to_highlight should be an array of concrete selling points worth surfacing in the docs
- banned_terms should be an array of internal phrases to avoid in the human guide
- information_order should explain what the guide should lead with before disclaimers
- media_strategy should explain how art should amplify the guide instead of literalizing repo-role labels
- overlay_policy should explain what HUD-style overlays are useful to readers
- cta_strategy should explain how to invite readers to engage without sounding sketchy
- landing_tagline should be short, punchy, and human-facing
- landing_intro should be one short paragraph
- what_it_is should explain the product in plain language before it mentions the guide or repo
- watch_intro should tee up why the project is worth following
- horizon_intro should tee up the future ideas in a fun way without pretending they are active work
- keep the whole JSON compact enough to fit on one terminal screen
- do not tell the reader to fix docs, correct drift, or maintain hierarchy
- do not route normal users to chummer6-design for feature requests
{PUBLIC_WRITER_RULES}

Observed tags:
{tags}

Observed source excerpts:
{source_excerpt}

Return valid JSON only.
"""


def _listish(raw: object) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if any(token in text for token in ("\n", ";", "|")):
        parts = re.split(r"(?:\r?\n|;|\|)+", text)
        cleaned = [part.strip(" ,;-") for part in parts if part.strip(" ,;-")]
        if cleaned:
            return cleaned
    return [text]


def _excerpt_labels(signals: dict[str, object]) -> list[str]:
    labels: list[str] = []
    for snippet in signals.get("snippets", []):
        text = str(snippet or "").strip()
        match = re.match(r"^\[([^\]]+)\]", text)
        if match:
            labels.append(match.group(1).strip())
    return labels


def _interest_signals_from_tags(tags: list[str]) -> list[str]:
    mapping = {
        "multi_era_rulesets": "future rules coverage should be shown honestly",
        "sr4_support": "proof surfaces should show what rule coverage exists today",
        "sr5_support": "proof surfaces should show what rule coverage exists today",
        "sr6_support": "proof surfaces should show what rule coverage exists today",
        "lua_rules": "edge-case handling should come with receipts instead of trust-me copy",
        "offline_play": "offline-safe play matters",
        "installable_pwa": "downloadable proof builds matter",
        "explain_receipts": "receipt trails should stay inspectable",
        "provenance_receipts": "modifiers should show where they came from",
        "runtime_stacks": "runtime bundles should stay legible",
        "session_events": "session state and replay matter at the table",
        "local_first_play": "local-first behavior is part of the promise",
    }
    seen: list[str] = []
    for tag in tags:
        value = mapping.get(str(tag))
        if value and value not in seen:
            seen.append(value)
    return seen


def _public_signal_tags_from_tags(tags: list[str]) -> list[str]:
    mapping = {
        "deterministic_truth": "proof_receipts",
        "explain_receipts": "proof_receipts",
        "provenance_receipts": "provenance_receipts",
        "future_horizons": "future_lanes",
        "runsite_artifacts": "public_downloads",
        "offline_play": "offline_play",
        "public_guide": "public_guide",
        "multi_era_rulesets": "future_rules_coverage",
        "lua_rules": "receipt_driven_edge_cases",
        "local_first_play": "local_first_play",
        "session_events": "session_continuity",
        "runtime_stacks": "readable_surfaces",
    }
    seen: list[str] = []
    for tag in tags:
        value = mapping.get(str(tag))
        if value and value not in seen:
            seen.append(value)
    return seen


def _global_ooda_defaults(signals: dict[str, object]) -> dict[str, object]:
    tags = [str(tag).strip() for tag in signals.get("tags", []) if str(tag).strip()]
    highlights = _interest_signals_from_tags(tags)
    public_tags = _public_signal_tags_from_tags(tags)
    return {
        "observe": {
            "source_signal_tags": public_tags or ["proof_receipts", "offline_play", "public_guide"],
            "source_excerpt_labels": _excerpt_labels(signals) or ["core_readme", "ui_readme", "play_readme"],
            "audience_needs": [
                "what this does for a real table",
                "why the math is worth trusting",
                "where the project is actually heading",
            ],
            "user_interest_signals": highlights
            or [
                "an idea for readable receipts instead of mystery math",
                "less folklore if the concept ever lands",
                "future lanes that feel table-driven instead of repo-driven",
            ],
            "risks": [
                "sliding back into repo-topology talk",
                "template-shaped copy",
                "generic cyberpunk wallpaper instead of scenes",
            ],
        },
        "orient": {
            "audience": "players, GMs, and curious tinkerers who want Chummer6 explained from the table inward",
            "promise": "an idea for inspectable Shadowrun math with fewer trust-me rulings if it ever hardens into real software",
            "tension": "the guide has to stay honest that the idea is stronger than the current software traces",
            "why_care": [
                "a clearer direction for future rulings tools",
                "less trust-me math if the concept survives",
                "a saner long-range path from prep to live play",
            ],
            "current_focus": [
                "honest concept-stage public surfaces",
                "future ideas that feel like table upgrades instead of slideware",
                "not pretending lucky artifacts are dependable product",
            ],
            "visual_direction": "grounded cyberpunk scenes, readable props, lived table moments, and only occasional recurring motifs when they genuinely improve the image",
            "humor_line": "Keep the wit dry, adult, and secondary to the actual point.",
            "signals_to_highlight": highlights
            or [
                "receipts and provenance as goals",
                "concept honesty over fake product posture",
                "future table relief instead of fake current completeness",
                "public explanation before product claims",
            ],
            "banned_terms": [
                "visitor center",
                "repo topology",
                "internal control plane",
                "template placeholder future",
                "fix Chummer6 first",
                "correct the blueprint",
                "blueprint room",
                "shared interface",
                "signoff only",
            ],
        },
        "decide": {
            "information_order": "lead with table pain, then the idea, then the almost-nothing current truth, then the map of parts and futures",
            "tone_rules": "keep it human, concrete, lightly wry, and allergic to architecture sermons",
            "horizon_policy": "sell each horizon as a table pain and a vivid scene, not a codename first",
            "media_strategy": "use contextual scenes that show the moment the feature matters, not abstract title-card art",
            "overlay_policy": "only use overlays that clarify initiative, receipts, sync state, provenance, or simulation context",
            "cta_strategy": "invite readers to watch, react, report spillover, or pitch better ideas without sounding pushy or synthetic",
        },
        "act": {
            "landing_tagline": "An idea for less mystical Shadowrun rulings.",
            "landing_intro": "Chummer6 is mostly an idea about making Shadowrun rulings easier to inspect while the table is loud and the stakes are dumb.",
            "what_it_is": "Chummer6 is an idea about inspecting Shadowrun rulings instead of trusting folklore math or lucky table memory.",
            "watch_intro": "If you care about receipts, future session resilience, and tools that might become useful instead of decorative, this is the concept worth watching.",
            "horizon_intro": "Horizons are contingent idea lanes worth watching only if the concept survives long enough to carry them.",
        },
    }


def normalize_ooda(result: dict[str, object], signals: dict[str, object]) -> dict[str, object]:
    defaults = _global_ooda_defaults(signals)
    normalized: dict[str, object] = {}
    raw_observe = result.get("observe") if isinstance(result.get("observe"), dict) else {}
    raw_orient = result.get("orient") if isinstance(result.get("orient"), dict) else result
    raw_decide = result.get("decide") if isinstance(result.get("decide"), dict) else {}
    raw_act = result.get("act") if isinstance(result.get("act"), dict) else result

    observe: dict[str, object] = {}
    for key in ("source_signal_tags", "source_excerpt_labels", "audience_needs", "user_interest_signals", "risks"):
        raw = raw_observe.get(key) if isinstance(raw_observe, dict) else None
        cleaned = _listish(raw)
        if not cleaned:
            cleaned = _listish(defaults["observe"].get(key))
        observe[key] = [
            editorial_self_audit_text(
                entry,
                fallback=str(fallback).strip(),
                context=f"ooda:observe:{key}",
            )
            for entry, fallback in zip(cleaned, _listish(defaults["observe"].get(key)) + cleaned)
        ]

    orient: dict[str, object] = {}
    for key in ("audience", "promise", "tension", "visual_direction", "humor_line"):
        value = str(defaults["orient"].get(key, "")).strip()
        orient[key] = editorial_self_audit_text(value, fallback=value, context=f"ooda:orient:{key}")
    for key in ("why_care", "current_focus", "signals_to_highlight", "banned_terms"):
        orient[key] = [
            editorial_self_audit_text(
                str(entry).strip(),
                fallback=str(entry).strip(),
                context=f"ooda:orient:{key}",
            )
            for entry in _listish(defaults["orient"].get(key))
        ]

    decide: dict[str, object] = {}
    for key in ("information_order", "tone_rules", "horizon_policy", "media_strategy", "overlay_policy", "cta_strategy"):
        raw_value = raw_decide.get(key) if isinstance(raw_decide, dict) else ""
        if isinstance(raw_value, (list, tuple)):
            separator = " -> " if key == "information_order" else "; "
            value = separator.join(str(entry).strip() for entry in raw_value if str(entry).strip()).strip()
        else:
            value = str(raw_value or "").strip()
        if not value:
            value = str(defaults["decide"].get(key, "")).strip()
        decide[key] = editorial_self_audit_text(value, fallback=str(defaults["decide"].get(key, "")).strip(), context=f"ooda:decide:{key}")

    act: dict[str, object] = {}
    for key in ("landing_tagline", "landing_intro", "what_it_is", "watch_intro", "horizon_intro"):
        value = str(defaults["act"].get(key, "")).strip()
        act[key] = editorial_self_audit_text(value, fallback=value, context=f"ooda:act:{key}")

    normalized["observe"] = observe
    normalized["orient"] = orient
    normalized["decide"] = decide
    normalized["act"] = act
    return normalized


def build_media_prompt(
    kind: str,
    name: str,
    item: dict[str, object],
    ooda: dict[str, object] | None = None,
    *,
    section_ooda: dict[str, object] | None = None,
    style_epoch: dict[str, object] | None = None,
    recent_scenes: list[dict[str, str]] | None = None,
    variation_guardrails: list[str] | None = None,
) -> str:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    foundations = "\n".join(f"- {line}" for line in item.get("foundations", []))
    repos = ", ".join(str(repo) for repo in item.get("repos", []))
    if kind == "hero":
        readme_excerpt = read_markdown_excerpt("README.md", limit=320)
        current_excerpt = read_markdown_excerpt("NOW/current-phase.md", limit=220)
        return f"""You are writing image-card copy for the human-facing Chummer6 guide landing hero.

Task: return a JSON object only with keys badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract.

Voice rules:
- clear, inviting, slightly playful, Shadowrun-flavored
- this is a human-facing guide, not a spec
- SR jargon is welcome
- dry humor is optional and should stay secondary to the actual scene
- adult language is fine when it fits the setting, but never make profanity the whole gag
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences

Source excerpts:
README:
{readme_excerpt}

Current phase:
{current_excerpt}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Variation guardrails:
{json.dumps(variation_guardrails or [], ensure_ascii=True)}

Requirements:
- infer the scene from the source, do not literalize repo-role labels
- do not say or imply "visitor center"
- treat the whole thing as concept-stage and accidental-spillover-adjacent, not as stable current software
- visible copy should feel like a dangerous idea or concept lane, not a ready-to-use feature banner
- avoid command-slogan lines like stop/start/use/download now
- never use phrases like deterministic truth, proof of concept, hardware diagnostics verified, or rules-engine certainty
- avoid branded weapon models, exact diagnostics, exact modifier labels, or named telemetry unless the source explicitly demands them
- visual_prompt must describe an actual cyberpunk scene, not a brochure cover
- visual_prompt must center one memorable focal subject, setup, or action instead of generic poster collage
- do not make gloved hands, scarred hands, or anonymous hand close-ups the main subject unless the asset is specifically about proof-on-props
- if the section implies a person or team, choose a believable protagonist instead of abstract symbols
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, or crash-test simulation, make that metaphor visibly legible in-scene
- hero art must read as a lived Shadowrun triage scene: metahuman clinician, ugly troll patient, and one assistant or teammate in an improvised garage clinic or getaway-bay, not a lone operator in a mood void
- the room must do at least half the storytelling for the hero: visible floor, doorway, bay hardware, shelves, tool wall, side bench, hanging lights, and improvised med clutter belong in frame
- the troll patient must stay visibly troll-sized with readable tusks, rough skin, hair texture, and treated chrome, not a generic shaved human or a clean sci-fi mannequin
- seed the hero with small Sixth World lore crumbs such as cropped Ares or Renraku med gear, critter photo strips, Blood Orchid or Paper Lotus ephemera, corp scrip, or a faint astral totem residue, but never a readable ad or product board
- if a recognizable lore location helps the hero, use it through background residue like Bug City towers, Arcology shadows, Barrens infrastructure, Underground tilework, or ashfall rather than tourist-postcard framing
- show the human cost of the setting in the hero: dirt, stained gauze, old blood, rat traps, mold, crash fatigue, or cheap-med residue should be visible without turning the scene into splatter theatre
- if drug or vice cues appear in the hero, keep them scene-bound and ugly through spent inhalers, stim patches, crash kits, or shaky hands, not glamor shots
- if magic appears in the hero, make it warded or totemic: astral residue, fetish bundles, or a totem portrait glow, not generic fantasy light spam
- medscan or upgrade overlays must feel anchored to anatomy, tools, rails, or work surfaces; never solve the hero with floating UI wallpaper or a clean monitor wall
- avoid clean clinics, white-coat doctor staging, hallway symmetry, quiet back-view pairs, or any bedside crop that turns the hero into generic sci-fi medicine
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible badge/title/subtitle/kicker/note should feel like guide copy, not compliance language
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
- overlay_callouts must stay in plain language; never use uppercase status labels, IDs, percentages, version strings, or exact telemetry
- avoid repeating a recently accepted composition family when a different scene family would work
- if the landing truth can be shown with one vivid operator relationship, one prop cluster, one transit lane, or one over-shoulder proof moment, prefer that over a generic group huddle
- scene_contract must be an object with keys:
  - subject
  - environment
  - action
  - metaphor
  - props
  - overlays
  - composition
  - palette
  - mood
  - humor
- scene_contract.humor is optional; if present, make it a brief tonal nudge, not a personal roast, quoted joke, or readable sign
- a sparse Shadowrun-lore jab at cursed code, corp UX, wage-mage patch rituals, or cerebral-booster bravado is fine when the scene earns it
- sparse Shadowrun vice cues like cram haze, jazz crash, or novacoke bravado are fine when they stay clearly fictional and scene-bound
- scene_contract.subject should name the focal subject in plain language
- scene_contract.metaphor should name the strongest visual metaphor if one exists
- scene_contract.props should be a short list of concrete visible things
- scene_contract.overlays should be a short list of diegetic overlay ideas, not machine labels or exact readouts
- scene_contract.composition should be a short layout phrase like single_protagonist, group_table, desk_still_life, or city_edge

Return valid JSON only.
"""
    if kind == "part":
        part_excerpt = read_markdown_excerpt(f"PARTS/{name}.md", limit=320)
        return f"""You are writing image-card copy for a human-facing Chummer6 part banner.

Task: return a JSON object only with keys badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract.

Voice rules:
- clear, punchy, slightly funny, Shadowrun-flavored
- sell the part as something a reader should care about right now
- the image should feel grounded, useful, and scene-first
- SR jargon is welcome
- dry humor is optional and should stay secondary to the actual scene
- adult language is fine when it fits the setting, but never make profanity the whole gag
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
{PUBLIC_WRITER_RULES}

Source page excerpt:
{part_excerpt}

Part id: {name}
Title: {title}
Tagline: {item.get("tagline", "")}
When you touch this: {item.get("when", item.get("intro", ""))}
Why: {item.get("why", "")}
Now: {item.get("now", "")}
What you notice:
{chr(10).join(f"- {line}" for line in item.get("notice", item.get("owns", [])))}

What you do not need to care about yet:
{chr(10).join(f"- {line}" for line in item.get("limits", item.get("not_owns", [])))}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Variation guardrails:
{json.dumps(variation_guardrails or [], ensure_ascii=True)}

Requirements:
- infer the scene from the source, do not repeat repo labels back as literal signage
- keep the concept-stage posture obvious; the image copy should feel like a vivid idea trace, not a polished shipping feature
- visible copy and meta should read like concept-stage guide material, not a shipping subsystem or verified status board
- avoid branded weapon models, exact diagnostics, exact modifier labels, or named telemetry unless the source explicitly demands them
- visual_prompt must describe an actual cyberpunk scene tied to this part in use
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the part naturally implies a person or team, choose believable cyberpunk people
- if the part naturally implies a machine room, archive, workshop, or table scene, make that spatial metaphor visibly legible
- use at least one concrete Sixth World lore crumb when it fits: cropped megacorp consumer shells, corp scrip, critter photos, Blood Orchid or Paper Lotus ephemera, talismonger leftovers, or astral-totem residue
- when a part image needs stronger setting identity, a recognizable lore location cue is welcome: Chicago containment skyline, Redmond Barrens geometry, Renraku Arcology shadow, Ork Underground structure, Puyallup ash, or Glow City hazard detail
- when the scene can carry it, show at least one hardship cue from the Sixth World: grime, vermin pressure, stained wraps, old blood, crash posture, dirty cups, mold, cough medicine, or spent stimulants
- if magic shows up in a part image, keep it to wards, fetishes, or a totem portrait ghost, not generic fantasy casting glamour
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- visible copy and meta should read like concept-stage guide material, not a verified ops label
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
- overlay_callouts must stay in plain language; never use uppercase status labels, IDs, percentages, version strings, or exact telemetry
- if proof, prep, compatibility, or hosted coordination can be shown without a social huddle, prefer the non-table scene family
- do not solve every part page as people debating around a surface
- scene_contract must be an object with keys:
  - subject
  - environment
  - action
  - metaphor
  - props
  - overlays
  - composition
  - palette
  - mood
  - humor
- scene_contract.humor is optional; if present, make it a brief tonal nudge, not a personal roast, quoted joke, or readable sign
- a sparse Shadowrun-lore jab at cursed code, corp UX, wage-mage patch rituals, or cerebral-booster bravado is fine when the scene earns it
- sparse Shadowrun vice cues like cram haze, jazz crash, or novacoke bravado are fine when they stay clearly fictional and scene-bound
- scene_contract.overlays should be short plain-language visual cues, not machine labels or exact readouts

Return valid JSON only.
"""
    horizon_excerpt = read_markdown_excerpt(f"HORIZONS/{name}.md", limit=320)
    return f"""You are writing image-card copy for a human-facing Chummer6 horizon banner.

Task: return a JSON object only with keys badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract.

Voice rules:
- clear, punchy, slightly funny, Shadowrun-flavored
- sell the horizon harder
- the image should feel cool, dangerous, specific, and scene-first
- SR jargon is welcome
- dry humor is optional and should stay secondary to the actual scene
- adult language is fine when it fits the setting, but never make profanity the whole gag
- never drift into personal sniping, daredevil edginess, or maintainer in-jokes
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences

Source page excerpt:
{horizon_excerpt}

Horizon id: {name}
Title: {title}
Current hook:
{item.get("hook", "")}

Current brutal truth:
{item.get("brutal_truth", "")}

Current use case:
{item.get("use_case", "")}

Problem:
{item.get("problem", "")}

Foundations:
{foundations}

Touched repos later:
{repos}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Active style epoch:
{json.dumps(style_epoch or {}, ensure_ascii=True)}

Recent accepted scene ledger rows:
{json.dumps(recent_scenes or [], ensure_ascii=True)}

Variation guardrails:
{json.dumps(variation_guardrails or [], ensure_ascii=True)}

Requirements:
- infer the scene from the source, do not just repeat headings back
- keep the concept-stage posture obvious; this is a future lane with maybe-traces, not a product panel for an already working feature
- visible copy and meta should read like a speculative lane, not an already deployed module with verified status strings
- avoid branded weapon models, exact diagnostics, exact modifier labels, or named telemetry unless the source explicitly demands them
- visual_prompt must describe an actual cyberpunk scene tied to this horizon
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the section naturally implies a person, make that person specific and believable
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, web, or blackbox, make that metaphor visibly legible in-scene
- if the title reads like a personal codename, make the focal subject feel like that codename embodied; if it reads like a feminine personal name, it is fine to make the focal subject a woman
- if the metaphor is x-ray or simulation, show a real body, runner, or situation with the metaphor happening to it; do not collapse into abstract boxes and HUD wallpaper
- if the horizon is a forge / approval / rollback / consequence lane, make the scene a standing rulesmith plus reviewer or witness inside an industrial approval rail with visibly more apparatus than faces; never a quiet workbench or paperwork table
- seed the horizon with small Sixth World lore crumbs such as cropped megacorp product cues, critter field photos, Paper Lotus or Blood Orchid ephemera, talismonger leftovers, or a totem portrait hanging in astral glow
- horizons may use recognizable lore locations aggressively when they clarify the fantasy: Bug City, Arcology edges, Barrens cuts, Underground passages, ash zones, or Touristville should read as lived places, not generic cyberpunk backdrop
- horizons should not feel clean or aspirational by default; when it fits, show the social damage they are meant to solve through grime, sickness, blood, vermin, withdrawal, urban decay, or busted clinic residue
- if magic appears, make it read as astral Shadowrun magic with wards, fetishes, or a mentor-animal silhouette rather than generic fantasy spellfire
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible copy should sell the horizon without pretending it is active build work
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
- overlay_callouts must stay in plain language; never use uppercase status labels, IDs, percentages, version strings, or exact telemetry
- do not reuse a recent table-huddle family when dossier, boulevard, workshop, sim-bench, archive, transit, service-rack, or solo-operator grammar would fit
- if the horizon already has a table-scene dialogue block, the banner may represent the in-world scene or the surrounding context instead of restaging the same table
- scene_contract must be an object with keys:
  - subject
  - environment
  - action
  - metaphor
  - props
  - overlays
  - composition
  - palette
  - mood
  - humor
- scene_contract.humor is optional; if present, make it a brief tonal nudge, not a personal roast, quoted joke, or readable sign
- a sparse Shadowrun-lore jab at cursed code, corp UX, wage-mage patch rituals, or cerebral-booster bravado is fine when the scene earns it
- sparse Shadowrun vice cues like cram haze, jazz crash, or novacoke bravado are fine when they stay clearly fictional and scene-bound
- if the title reads like a codename or person, make scene_contract.subject a believable cyberpunk person, not a generic skyline or dashboard
- if the metaphor is x-ray / dossier / forge / ghost / heat web / mirror / passport / blackbox / simulation, make scene_contract.metaphor explicit
- scene_contract.overlays should be short plain-language visual cues, not machine labels or exact readouts

Return valid JSON only.
"""


def normalize_media_override(kind: str, cleaned: dict[str, object], item: dict[str, object]) -> dict[str, object]:
    def asset_slug(raw_item: dict[str, object]) -> str:
        return str(raw_item.get("slug") or raw_item.get("id") or raw_item.get("title") or kind).strip().lower().replace(" ", "-")

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
            "source truth verified",
            "artifact ready for print",
            "entry point validated",
            "zero_drift",
            "hash_verified",
            "lua_driven",
            "mesh_stability",
            "debug text",
            "layout text",
            "status stamp",
            "readable text",
            "typography",
            "metadata hud",
            "dossier metadata hud",
            "prototype logic",
            "rules-truth",
            "hud-style",
            "data-source labels",
            "biometric lock icons",
            "integrity signatures",
            "build timestamps",
        )
        if any(token in lowered for token in banned_tokens):
            return True
        if re.search(r"\b0x[0-9a-f]+\b", lowered):
            return True
        if re.search(r"\b\d+(?:\.\d+)?%\b", lowered):
            return True
        if re.search(r"\b\d+(?:\.\d+){1,}\b", lowered) and any(ch.isalpha() for ch in lowered):
            return True
        if ("'" in lowered or '"' in lowered) and (
            re.search(r"['\"][A-Z0-9 _-]{3,}['\"]", str(text or ""))
            or re.search(r"['\"][A-Za-z][^'\"]{2,}['\"]", str(text or ""))
        ):
            return True
        return False

    def looks_like_status_label(text: str) -> bool:
        cleaned_text = " ".join(str(text or "").split()).strip()
        if not cleaned_text:
            return False
        lowered = cleaned_text.lower()
        if contains_machine_overlay_language(cleaned_text):
            return True
        if "|" in cleaned_text or "_" in cleaned_text:
            return True
        if re.search(r"\bv\d+(?:\.\d+)*\b", lowered):
            return True
        if re.match(r"^[A-Z]{2,}(?:-[A-Z0-9]{1,})+$", cleaned_text):
            return True
        if any(
            token in lowered
            for token in (
                "verified",
                "validated",
                "ready for",
                "status:",
                "initial spillover",
                "mesh stability",
                "zero drift",
                "hash verified",
                "lua driven",
                "artifact ready",
                "source truth",
                "tactical dossier",
                "governed ruleset evolution",
            "prototype logic",
            "dossier metadata hud",
            "artifact-driven",
            "spatial awareness",
            "sync complete",
            "grid offline",
            "lua code",
            "lua-backed",
            "combat modifiers",
            "declassified",
        )
        ):
            return True
        letters = [char for char in cleaned_text if char.isalpha()]
        if letters and sum(1 for char in letters if char.isupper()) >= max(6, int(len(letters) * 0.75)):
            return True
        return False

    def infer_overlay_hint(*, target: str, asset_key: str, scene_contract: dict[str, object], item_title: str) -> str:
        overlay_mode = overlay_mode_for_target(target)
        if overlay_mode == "medscan_diagnostic":
            return "medscan diagnostic rail with AGI/ESS upgrade markers, cyberlimb calibration, wound stabilization, and neural link resync"
        if overlay_mode == "ambient_diegetic":
            return "ambient lane arcs with district markers and branching path traces"
        if overlay_mode == "forge_review_ar":
            return "forge review rails with provenance seals, rollback vectors, approval chips, and witness lock"
        lowered_asset_key = str(asset_key or "").strip().lower()
        if lowered_asset_key == "hero":
            return "medscan diagnostic rail with cyberware calibration, wound stabilization, and upgrade-state chips"
        if lowered_asset_key == "design":
            return "route strings and scope brackets"
        if lowered_asset_key == "core":
            return "cross-check ticks and receipt markers"
        if lowered_asset_key == "hub":
            return "state alignment bands and relay seam markers"
        if lowered_asset_key == "ui":
            return "source-rule markers and modifier origin tags"
        if lowered_asset_key == "ui-kit":
            return "alignment bands and surface fit checks"
        if lowered_asset_key == "mobile":
            return "gesture taps and reconnect markers"
        if lowered_asset_key == "runbook-press":
            return "publication markers and manifest traces"
        if lowered_asset_key == "media-factory":
            return "trim guides and publication arrows"
        if lowered_asset_key == "hub-registry":
            return "catalog tags and provenance anchors"
        if lowered_asset_key == "jackpoint":
            return "source anchors and redaction bars"
        if lowered_asset_key == "karma-forge":
            return "compatibility seals and rollback markers"
        if lowered_asset_key == "nexus-pan":
            return "signal halos and continuity arcs"
        if lowered_asset_key == "runsite":
            return "route markers and hotspot cones"
        if lowered_asset_key == "table-pulse":
            return "spotlight drift arcs and pacing gaps"
        if lowered_asset_key == "alice":
            return "branch traces and risk silhouettes"
        tokens = " ".join(
            [
                asset_key,
                item_title,
                str(scene_contract.get("subject") or ""),
                str(scene_contract.get("environment") or ""),
                str(scene_contract.get("action") or ""),
                str(scene_contract.get("metaphor") or ""),
                " ".join(str(entry).strip() for entry in (scene_contract.get("props") or []) if str(entry).strip()),
                " ".join(str(entry).strip() for entry in (scene_contract.get("overlays") or []) if str(entry).strip()),
            ]
        ).lower()
        if any(token in tokens for token in ("hero", "intake tray", "build-state", "clinic intake", "streetdoc", "medscan", "cyberware calibration")):
            return "medscan diagnostic rail with cyberware calibration, wound stabilization, and upgrade-state chips"
        if any(token in tokens for token in ("design", "route string", "scope bracket", "planning corner", "surface callout")):
            return "route strings and scope brackets"
        if any(token in tokens for token in ("core", "review bench", "cross-examining", "dice tray", "rule chip")):
            return "cross-check ticks and receipt markers"
        if any(token in tokens for token in ("hub", "relay spine", "state alignment", "remote-presence", "service rack")):
            return "state alignment bands and relay seam markers"
        if any(token in tokens for token in ("mobile", "platform marker", "crowd rail", "gesture", "reconnect")):
            return "gesture taps and reconnect markers"
        if any(token in tokens for token in ("ui-kit", "component rail", "alignment band", "surface fit")):
            return "alignment bands and surface fit checks"
        if any(token in tokens for token in ("ui", "review bench", "rule chip", "modifier", "source-rule")):
            return "source-rule markers and modifier origin tags"
        if any(token in tokens for token in ("media-factory", "render", "publish", "proof", "output rack", "approval rail")):
            return "trim guides and publication arrows"
        if any(token in tokens for token in ("hub-registry", "intake", "archive", "provenance anchor", "compatibility shelf")):
            return "catalog tags and provenance anchors"
        if any(token in tokens for token in ("jackpoint", "dossier", "provenance", "evidence")):
            return "source anchors and redaction bars"
        if any(token in tokens for token in ("karma-forge", "forge", "rulesmith", "compatibility", "rollback", "rule", "lattice")):
            return "compatibility seals and rollback markers"
        if any(token in tokens for token in ("nexus-pan", "signal", "cable", "handshake", "link", "reconnect", "data-jack")):
            return "signal halos and continuity arcs"
        if any(token in tokens for token in ("runsite", "route", "district", "ingress", "hotspot")):
            return "route markers and hotspot cones"
        if any(token in tokens for token in ("runbook", "press", "publication", "manifest")):
            return "publication markers and manifest traces"
        if any(token in tokens for token in ("table-pulse", "pulse", "spotlight", "pacing", "table")):
            return "spotlight drift arcs and pacing gaps"
        if any(token in tokens for token in ("alice", "simulation", "x-ray", "branch", "preflight")):
            return "branch traces and risk silhouettes"
        return "receipt markers and bounded HUD traces"

    def sanitize_visual_prompt_text(
        text: str,
        *,
        fallback: str,
    ) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return fallback
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
                    "readable text",
                    "layout text",
                    "status stamp",
                    "typography",
                    "rules-truth",
                    "prototype logic",
                    "tactical dossier",
                    "governed ruleset evolution",
                    "dossier metadata hud",
                    "no logo",
                    "no logos",
                    "no watermark",
                )
            ):
                continue
            if contains_machine_overlay_language(piece):
                continue
            kept.append(piece)
        repaired = " ".join(kept).strip()
        return repaired or fallback

    def is_generic_motif(text: str) -> bool:
        lowered = " ".join(str(text or "").split()).strip().lower()
        return lowered in {
            "a cyberpunk protagonist",
            "a cyberpunk woman",
            "a cyberpunk troll",
            "a dangerous but inviting cyberpunk scene",
            "a rainy neon street front",
            "a cyberpunk workshop with exposed internals",
            "scene-aware cyberpunk guide art",
            "framing the next move before the chrome starts smoking",
            "wet chrome",
            "holographic receipts",
            "rain haze",
            "diegetic hud traces",
            "signal arcs",
        }

    def fallback_media_fields(*, asset_key: str, kind: str) -> dict[str, str]:
        lowered_key = str(asset_key or "").strip().lower()
        curated: dict[str, dict[str, str]] = {
            "hero": {
                "badge": "Streetdoc Scan",
                "kicker": "concept, not contract",
                "note": "Concept-stage only. If anything looks usable, treat it as accidental spillover rather than support.",
            },
            "core": {
                "badge": "Rule Receipt",
                "kicker": "show the ruling, not the folklore",
                "note": "A rules-trace idea, not a finished authority surface.",
            },
            "ui": {
                "badge": "Build Check",
                "kicker": "cross-check the sheet before it bites",
                "note": "A build-inspection idea, not a finished user surface.",
            },
            "mobile": {
                "badge": "Handoff Trace",
                "kicker": "catch the session state mid-stride",
                "note": "A continuity idea for motion and reconnects, not a dependable mobile app.",
            },
            "hub": {
                "badge": "Hosted Lane",
                "kicker": "your footprint, held together under pressure",
                "note": "A hosted-coordination idea, not a stable service promise.",
            },
            "ui-kit": {
                "badge": "Shared Chrome",
                "kicker": "one visual language across rough surfaces",
                "note": "A shared-surface idea, not a finished design system.",
            },
            "hub-registry": {
                "badge": "Artifact Customs",
                "kicker": "label the rough packet before rumor wins",
                "note": "A provenance-shelf idea, not a finished registry product.",
            },
            "media-factory": {
                "badge": "Packet Refinery",
                "kicker": "make the packet readable without scrubbing the trail",
                "note": "A packet-cleanup idea, not a live media studio.",
            },
            "design": {
                "badge": "Route Map",
                "kicker": "choose the next honest surface",
                "note": "A planning lane, not a promise that the next surface already exists.",
            },
            "nexus-pan": {
                "badge": "Reconnect Idea",
                "kicker": "continuity without fake certainty",
                "note": "A reconnect idea, not a dependable continuity feature.",
            },
            "alice": {
                "badge": "Preflight Idea",
                "kicker": "show the weak point before it hurts",
                "note": "A preflight thought experiment, not an oracle.",
            },
            "karma-forge": {
                "badge": "Expensive Lane",
                "kicker": "house rules with rollback dreams",
                "note": "An expensive experiment lane. Even a careful run here can still end in a dead lane rather than a durable feature.",
            },
            "jackpoint": {
                "badge": "Dossier Lane",
                "kicker": "packets that still point back to source",
                "note": "The idea is provenance that survives polish, not instant finished output.",
            },
            "runsite": {
                "badge": "Briefing Space",
                "kicker": "make the room legible before it shoots back",
                "note": "A planning aid idea, not a live tactical shell.",
            },
            "runbook-press": {
                "badge": "Handbook Lane",
                "kicker": "books that still remember the source",
                "note": "Long-form publishing is still an idea lane here, not a finished press.",
            },
            "table-pulse": {
                "badge": "Post-Session",
                "kicker": "spotlight drift after the dust settles",
                "note": "Post-session coaching only, if it ever becomes more than an idea.",
            },
        }
        if lowered_key in curated:
            return curated[lowered_key]
        return {
            "badge": "Idea Trace" if kind == "hero" else "Idea Lane",
            "kicker": "idea first, survival uncertain",
            "note": "Treat any visible trace as provisional spillover, not a promise.",
        }

    def asset_scene_defaults(asset_key: str) -> dict[str, object]:
        lowered_key = str(asset_key or "").strip().lower()
        curated: dict[str, dict[str, object]] = {
            "hero": {
                "subject": "an ork streetdoc stabilizing an ugly hairy troll runner on a hacked surgical recliner while a teammate crowds the far edge with tools or hard light",
                "environment": "an improvised garage clinic carved into a rain-soaked barrens auto bay with tool chest grime, tarp dividers, hanging work lamps, extension cords, hacked med gear, a side bench, an open bay door, shelves of old chrome, and wet concrete",
                "action": "stabilizing the troll runner under pressure while calibrating a treated cyberlimb, checking upgrade posture, and keeping the bay clutter, floor, doorway, and surrounding hardware visibly part of the story",
                "metaphor": "streetdoc medscan under pressure",
                "props": ["tool chest", "med-gel", "cyberware part", "injector tray", "work lamp", "extension cord", "old chrome limb", "magical focus"],
                "overlays": ["BOD rail", "AGI upgrading rail", "ESS upgrading rail", "cyberlimb calibration", "wound stabilized", "neural link resync"],
                "composition": "clinic_intake",
                "palette": "wet concrete graphite, surgical cyan, sodium amber",
                "mood": "wary, improvised, and first-contact honest",
                "humor_policy": "forbid",
            },
            "core": {
                "subject": "one rules referee cross-checking dice, chips, and a fragile rules trace",
                "environment": "a battered review bench with dice trays, clipped tags, and one sheet surface under hard work light",
                "action": "cross-examining the ruling before it turns into folklore",
                "metaphor": "receipt-first cross examination",
                "props": ["dice tray", "clipped tags", "rule chips"],
                "overlays": ["cause-and-effect traces", "receipt markers", "target posture brackets"],
                "composition": "over_shoulder_receipt",
                "palette": "tungsten gold, ledger cream, oxidized blue",
                "mood": "forensic, skeptical, and grounded",
            },
            "ui": {
                "subject": "one player comparing a live build across a wall slate and a clipped hanging sheet",
                "environment": "a locker-shelf review bay with one vertical display, one hanging slate, and gear cards in motion",
                "action": "cross-checking a build before the session punishes the wrong assumption",
                "metaphor": "mirror split build review",
                "props": ["vertical wall slate", "hanging sheet", "gear cards"],
                "overlays": ["build-state deltas", "inspection brackets", "shared component echoes"],
                "composition": "review_bay",
                "palette": "locker oxblood, smoked glass, worklight ivory",
                "mood": "practical, inspectable, and slightly tense",
            },
            "mobile": {
                "subject": "one runner catching the live-play trace while threading through a crowded station edge",
                "environment": "a packed station mezzanine with a handheld, platform markers, and moving bodies at the edge",
                "action": "recovering the session state mid-stride before the next connection closes",
                "metaphor": "platform-edge recovery",
                "props": ["rugged handheld", "platform marker", "crowd rail"],
                "overlays": ["signal halos", "reconnect markers", "route-weighting brackets"],
                "composition": "platform_edge",
                "palette": "station graphite, route red, station white",
                "mood": "hurried, resilient, and compressed",
            },
            "hub": {
                "subject": "one operator checking whether the hosted lane is still coherent under pressure",
                "environment": "a service rack corridor with cable runs, control slabs, and remote presence seams",
                "action": "keeping the hosted coordination lane coherent without pretending the chaos went away",
                "metaphor": "relay spine under pressure",
                "props": ["service rack", "control slab", "cable bundle"],
                "overlays": ["remote-presence seams", "state alignment bands", "warning glyphs"],
                "composition": "service_rack",
                "palette": "rack graphite, relay green, cold porcelain",
                "mood": "contained, pressurized, and watchful",
            },
            "ui-kit": {
                "subject": "one designer tuning shared interface parts across real surfaces instead of mockup wallpaper",
                "environment": "an improvised surface lab with component rails, acetate overlays, and a lit demo plinth",
                "action": "aligning live chrome across surfaces before the style fragments into folklore",
                "metaphor": "shared chrome across rough surfaces",
                "props": ["component rail", "acetate overlay", "demo plinth"],
                "overlays": ["component echoes", "alignment bands", "surface fit checks"],
                "composition": "mirror_split",
                "palette": "powder ivory, lacquer red, smoked cyan",
                "mood": "precise, tactile, and intentionally built",
            },
            "hub-registry": {
                "subject": "one registrar deciding where a rough artifact belongs before it becomes rumor",
                "environment": "an archive shelf lane with bins, hanging tags, scanner rails, and compatibility shelves",
                "action": "sorting an artifact into shelf, label, and provenance lanes",
                "metaphor": "artifact customs desk",
                "props": ["archive bins", "hanging tags", "compatibility shelves"],
                "overlays": ["catalog tags", "compatibility bands", "provenance anchors"],
                "composition": "archive_room",
                "palette": "archive umber, intake orange, oxidized green",
                "mood": "methodical, dusty, and quietly suspicious",
            },
            "media-factory": {
                "subject": "one operator turning a rough packet into something readable without losing the receipts",
                "environment": "a vertical render bay with output racks, trim bins, hanging frames, and approval rails",
                "action": "washing rough source material into a publishable packet while the receipts stay visible",
                "metaphor": "packet wash line under publication pressure",
                "props": ["output rack", "trim bin", "approval rail"],
                "overlays": ["publication-path arrows", "trim guides", "approval bands"],
                "composition": "render_lane",
                "palette": "ink black, print magenta, cooled steel",
                "mood": "busy, mechanical, and evidence-bound",
            },
            "design": {
                "subject": "one planner mapping the future shape of the tool across a wall of rough public surfaces",
                "environment": "a quiet planning corner with pinned cards, route strings, and clipped shelf mockups",
                "action": "deciding which visible surface earns the next bit of honesty",
                "metaphor": "concept map with public consequences",
                "props": ["pinned cards", "route strings", "shelf mockups"],
                "overlays": ["direction arrows", "surface callouts", "scope brackets"],
                "composition": "conspiracy_wall",
                "palette": "paper gray, dried teal, worklight amber",
                "mood": "deliberate, strategic, and still provisional",
            },
            "nexus-pan": {
                "subject": "a rigger nursing a patched commlink mesh back to life",
                "environment": "a hot van interior parked beneath a loading-dock awning",
                "action": "checking whether a dirty reconnect preserved the run state or lied about it",
                "metaphor": "hardware handshake under pressure",
                "props": ["patched commlink rig", "heat-blown cable bundle", "portable relay deck"],
                "overlays": ["signal halos", "route weighting arcs", "posture brackets"],
                "composition": "van_interior",
                "palette": "storm cobalt, relay green, moonlit gray",
                "mood": "frazzled, technical, and still moving",
            },
            "alice": {
                "subject": "a wary analyst walking through a volatile preflight sim",
                "environment": "a wet-glass simulation bay with practical lamps and fogged partitions",
                "action": "pulling a branching x-ray of the weak build through the air",
                "metaphor": "branching simulation grid",
                "props": ["branching sim panes", "diagnostic chips", "fogged lab glass"],
                "overlays": ["branch traces", "preflight markers", "risk silhouettes"],
                "composition": "simulation_lab",
                "palette": "bruise violet, lab mint, dull brass",
                "mood": "clinical, tense, and predictive",
            },
            "karma-forge": {
                "subject": "a standing rulesmith and skeptical reviewer forcing unstable house-rule packs through an industrial approval rail while the apparatus looms larger than they do",
                "environment": "an improvised industrial rules lab with approval rails, rollback rig hardware, provenance seals, consequence chambers, assay racks, cassette bins, gantry hooks, sample lockers, and hard sodium spill",
                "action": "driving diff controls, rollback clamps, and witness locks under visible pressure so governed rules evolution reads through apparatus, rails, and consequence hardware instead of paperwork",
                "metaphor": "governed rules evolution under pressure",
                "props": ["rule lattice", "approval rail", "rollback cassette", "provenance seals", "cassette bin", "assay rack", "witness lock"],
                "overlays": ["compatibility markers", "rollback seals", "receipt traces", "approval state brackets", "witness locks"],
                "composition": "approval_rail",
                "palette": "forge orange, audit green, midnight iron",
                "mood": "volatile, expensive, and tightly governed",
                "humor_policy": "forbid",
                "easter_egg_policy": "deny",
            },
            "jackpoint": {
                "subject": "a fixer assembling a hot dossier from real evidence and dirty notes",
                "environment": "a backroom evidence loft with coffee rings and rain on the window",
                "action": "sorting volatile evidence into a packet that still points back to source",
                "metaphor": "dossier evidence wall",
                "props": ["dossier folders", "evidence chips", "binder clips"],
                "overlays": ["source anchors", "redaction bars", "evidence pins"],
                "composition": "dossier_desk",
                "palette": "coffee umber, evidence red, archive gray",
                "mood": "nervy, editorial, and streetwise",
            },
            "runsite": {
                "subject": "a rigger plotting ingress lanes across a projected floor plan",
                "environment": "a rain-slick loading dock and alley staging point",
                "action": "checking routes and threat posture before the team steps inside",
                "metaphor": "district map",
                "props": ["wireframe floor plan", "shipping crate", "route pins"],
                "overlays": ["route markers", "threat posture cones", "ingress arcs"],
                "composition": "district_map",
                "palette": "concrete blue, hazard chalk, wet amber",
                "mood": "alert, spatial, and field-bound",
            },
            "runbook-press": {
                "subject": "a campaign writer pushing raw district material through a rail-side proof room",
                "environment": "a rail-side proof room with rollers, map drawers, clipped proof strips, and a lit print rail",
                "action": "turning loose district notes into a governed handbook artifact without losing the source trail",
                "metaphor": "revision rail with source memory",
                "props": ["ink rollers", "map drawer", "proof rail"],
                "overlays": ["layout guides", "source anchors", "publication-path arrows"],
                "composition": "proof_room",
                "palette": "ink blue, plate silver, warm paper",
                "mood": "craft-heavy, editorial, and careful",
            },
            "table-pulse": {
                "subject": "a tired orc GM replaying the session after everyone else has gone home",
                "environment": "a late-night booth after the run, lit by rain and soycaf steam",
                "action": "reviewing where pacing and spotlight drifted after the table cooled off",
                "metaphor": "post-session heat web",
                "props": ["cooling soycaf mug", "dice tray", "glowing tablet"],
                "overlays": ["spotlight drift arcs", "pacing gaps", "conversation heat traces"],
                "composition": "forensic_replay",
                "palette": "booth maroon, nicotine amber, cold cyan echo",
                "mood": "spent, reflective, and a little haunted",
            },
        }
        return dict(curated.get(lowered_key, {}))

    def fallback_media_meta(*, asset_key: str, kind: str) -> str:
        lowered_key = str(asset_key or "").strip().lower()
        curated = {
            "hero": "Idea stage | accidental public traces only",
            "core": "Concept lane | rule receipts before folklore",
            "ui": "Concept lane | build inspection, not finished UX",
            "mobile": "Concept lane | continuity under motion, not deployment",
            "hub": "Concept lane | hosted coordination, still provisional",
            "ui-kit": "Concept lane | shared chrome across rough surfaces",
            "hub-registry": "Concept lane | provenance shelves before polish",
            "media-factory": "Concept lane | packet cleanup, not a live studio",
            "design": "Concept lane | route map, not roadmap theater",
            "nexus-pan": "Concept lane | reconnect fantasy, not deployment",
            "alice": "Concept lane | preflight, not oracle",
            "karma-forge": "Concept lane | expensive experiments, no promises",
            "jackpoint": "Concept lane | provenance before polish",
            "runsite": "Concept lane | planning only, not live ops",
            "runbook-press": "Concept lane | books that still point back to source",
            "table-pulse": "Concept lane | post-session only, never table cop",
        }
        if lowered_key in curated:
            return curated[lowered_key]
        return "Concept lane | accidental traces, not stable software" if kind == "hero" else "Concept lane | still provisional and unpromised"

    def needs_concept_meta_refresh(text: str) -> bool:
        cleaned_text = " ".join(str(text or "").split()).strip()
        lowered = cleaned_text.lower()
        if not cleaned_text:
            return True
        if looks_like_status_label(cleaned_text):
            return True
        if any(
            token in lowered
            for token in (
                "planning phase",
                "artifact stage",
                "artifact-stage",
                "lore governance",
                "build integrity",
                "peer-to-peer",
                "state synchronization",
                "spatial intelligence",
                "tactical artifact",
                "dossier packs",
                "recap artifacts",
                "analytical what-if",
                "ruleset governance",
                "tactical dossier",
                "governed ruleset evolution",
                "prototype logic",
                "dossier metadata hud",
                "phase:",
                "source:",
                "epoch:",
            )
        ):
            return True
        return False

    def infer_scene_contract(*, asset_key: str, visual_prompt: str) -> dict[str, object]:
        lowered = visual_prompt.lower()
        defaults = asset_scene_defaults(asset_key)
        locked_defaults = bool(defaults)
        subject = str(defaults.get("subject") or "a cyberpunk protagonist")
        if not locked_defaults and ("team" in lowered or "group" in lowered):
            subject = "a runner team at a live table"
        elif not locked_defaults and "decker" in lowered:
            subject = "a tired decker keeping a fragile link alive"
        elif not locked_defaults and "rigger" in lowered:
            subject = "a rigger keeping a fragile link alive"
        elif not locked_defaults and "archivist" in lowered:
            subject = "an archivist sorting volatile evidence into usable shape"
        elif not locked_defaults and "fixer" in lowered and "dossier" in lowered:
            subject = "a fixer turning raw evidence into a readable dossier"
        elif not locked_defaults and ("tech-adept" in lowered or ("terminal" in lowered and "lattice" in lowered)):
            subject = "a rulesmith staring down a live rule lattice"
        elif not locked_defaults and ("rulesmith" in lowered or "rule-chip" in lowered or "rule thread" in lowered):
            subject = "a rulesmith at a dangerous workbench"
        elif not locked_defaults and ("receipt" in lowered or "dice" in lowered or "sheet" in lowered or "table" in lowered):
            subject = "one operator, one receipt trail, and the props proving the point"
        elif not locked_defaults and ("girl" in lowered or "woman" in lowered):
            subject = "a cyberpunk woman"
        elif not locked_defaults and "troll" in lowered:
            subject = "a cyberpunk troll"
        elif not locked_defaults and "forge" in lowered:
            subject = "a rulesmith at a dangerous workbench"
        environment = str(defaults.get("environment") or "a dangerous but inviting cyberpunk scene")
        if not locked_defaults and ("bunker" in lowered or "archive" in lowered or "dossier" in lowered):
            environment = "an archive or bunker office lit by sodium spill"
        elif not locked_defaults and "office" in lowered:
            environment = "a rain-streaked office lit by sodium spill"
        elif not locked_defaults and "blueprint" in lowered:
            environment = "a blueprint room lit by cold neon"
        elif not locked_defaults and ("workshop" in lowered or "foundation" in lowered or "bench" in lowered):
            environment = "a cyberpunk workshop with exposed internals"
        elif not locked_defaults and ("street" in lowered or "preview" in lowered):
            environment = "a rainy neon street front"
        action = str(defaults.get("action") or "framing the next move before the chrome starts smoking")
        if not locked_defaults and ("plugging" in lowered or "cable" in lowered or "port" in lowered):
            action = "patching a fragile link back into the stack"
        if not locked_defaults and ("x-ray" in lowered or "xray" in lowered):
            action = "pulling a glowing x-ray of cause and effect through the air"
        elif not locked_defaults and ("simulation" in lowered or "branch" in lowered):
            action = "walking through branching combat outcomes"
        elif not locked_defaults and ("dossier" in lowered or "evidence" in lowered):
            action = "sorting a hot dossier and live evidence threads"
        elif not locked_defaults and ("lattice" in lowered and "terminal" in lowered):
            action = "forcing unstable rule logic into governed shape"
        elif not locked_defaults and "forge" in lowered:
            action = "hammering volatile rules into controlled shape"
        metaphor = str(defaults.get("metaphor") or "scene-aware cyberpunk guide art")
        if not locked_defaults:
            for token, label in (
                ("nexus-pan", "hardware handshake under pressure"),
                ("data-jack", "hardware handshake under pressure"),
                ("fiber-optic", "hardware handshake under pressure"),
                ("x-ray", "x-ray causality scan"),
                ("xray", "x-ray causality scan"),
                ("simulation", "branching simulation grid"),
                ("ghost", "forensic replay echoes"),
                ("dossier", "dossier evidence wall"),
                ("forge", "forge sparks and molten rules"),
                ("rule-chip", "governed rules forge"),
                ("lattice", "governed rules forge"),
                ("network", "living consequence web"),
                ("passport", "passport gate"),
                ("mirror", "mirror split"),
                ("blackbox", "blackbox loadout check"),
            ):
                if token in lowered or token in asset_key:
                    metaphor = label
                    break
        composition = str(defaults.get("composition") or "single_protagonist")
        if not locked_defaults and ("boulevard" in lowered or "district" in lowered or "signpost" in lowered):
            composition = "horizon_boulevard"
        elif not locked_defaults and ("over-shoulder" in lowered or "receipt" in lowered or "modifier" in lowered or "dice" in lowered):
            composition = "over_shoulder_receipt"
        elif not locked_defaults and ("service rack" in lowered or "rack" in lowered or "control surface" in lowered):
            composition = "service_rack"
        elif not locked_defaults and ("transit" in lowered or "checkpoint" in lowered or "route board" in lowered or "station" in lowered):
            composition = "transit_checkpoint"
        elif not locked_defaults and ("workshop bench" in lowered or "forge" in lowered or "anvil" in lowered or "approval rail" in lowered or "rollback cassette" in lowered):
            composition = "approval_rail"
        elif not locked_defaults and ("operator" in lowered or "solo" in lowered or "kiosk" in lowered):
            composition = "solo_operator"
        elif not locked_defaults and ("team" in lowered or "group" in lowered):
            composition = "group_table"
        elif not locked_defaults and ("dossier" in lowered or "blackbox" in lowered):
            composition = "desk_still_life"
        elif not locked_defaults and ("horizon" in lowered or asset_key in {"horizons-index", "hero"}):
            composition = "city_edge"
        preferred_compositions = {
            "hero": "clinic_intake",
            "core": "over_shoulder_receipt",
            "ui": "review_bay",
            "mobile": "platform_edge",
            "hub": "service_rack",
            "ui-kit": "mirror_split",
            "hub-registry": "archive_room",
            "media-factory": "render_lane",
            "design": "conspiracy_wall",
            "nexus-pan": "van_interior",
            "alice": "simulation_lab",
            "karma-forge": "approval_rail",
            "jackpoint": "dossier_desk",
            "runsite": "district_map",
            "runbook-press": "proof_room",
            "table-pulse": "forensic_replay",
        }
        preferred = preferred_compositions.get(asset_key)
        if preferred and composition in {"single_protagonist", "service_rack", "desk_still_life", "city_edge", "solo_operator", "transit_checkpoint", "workshop"}:
            composition = preferred
        palette = str(defaults.get("palette") or "cyan-magenta neon")
        mood = str(defaults.get("mood") or "dangerous, curious, and slightly amused")
        humor = ""
        if locked_defaults:
            props = list(defaults.get("props") or ["wet chrome", "holographic receipts", "rain haze"])
            overlays = list(defaults.get("overlays") or ["diegetic HUD traces", "receipt markers", "signal arcs"])
        elif any(token in lowered for token in ("nexus-pan", "data-jack", "fiber-optic", "signal", "connector", "lead")):
            props = ["fiber-optic lead", "rugged data-jack", "petrol cyan signal traces"]
            overlays = ["signal bars", "receipt traces", "hardware handshake glyphs"]
        elif any(token in lowered for token in ("karma-forge", "rule-chip", "lattice", "rulesmith", "forge", "terminal", "approval rail", "rollback cassette")):
            props = ["rule lattice", "industrial terminal", "receipt traces"]
            overlays = ["compatibility markers", "receipt traces", "rollback seals"]
        elif any(token in lowered for token in ("jackpoint", "dossier", "archive", "evidence", "data-slab")):
            props = ["dossier folders", "floating data-slabs", "rain-streaked window"]
            overlays = ["provenance stamps", "dossier markers", "receipt traces"]
        else:
            props = list(defaults.get("props") or ["wet chrome", "holographic receipts", "rain haze"])
            overlays = list(defaults.get("overlays") or ["diegetic HUD traces", "receipt markers", "signal arcs"])
        if asset_key == "hero":
            props = list(defaults.get("props") or ["worn sidearm or commlink", "receipt traces", "rain haze"])
            overlays = list(defaults.get("overlays") or ["receipt markers", "x-ray cause-and-effect traces", "target posture brackets"])
        elif asset_key == "nexus-pan":
            props = list(defaults.get("props") or ["patched commlink rig", "wet cable bundle", "receipt traces"])
            overlays = list(defaults.get("overlays") or ["signal halos", "receipt traces", "posture brackets"])
        elif asset_key == "jackpoint":
            props = list(defaults.get("props") or ["dossier folders", "evidence chips", "rain-streaked window"])
            overlays = list(defaults.get("overlays") or ["provenance stamps", "dossier markers", "receipt traces"])
        elif asset_key == "karma-forge":
            props = list(defaults.get("props") or ["rule lattice", "approval rail", "rollback cassette"])
            overlays = list(defaults.get("overlays") or ["compatibility markers", "rollback seals", "receipt traces"])
        return {
            "subject": subject,
            "environment": environment,
            "action": action,
            "metaphor": metaphor,
            "props": props,
            "overlays": overlays,
            "composition": composition,
            "palette": palette,
            "mood": mood,
            "humor": humor,
            "visual_prompt": visual_prompt,
        }

    def normalize_scene_contract(raw: object, *, asset_key: str, visual_prompt: str) -> dict[str, object]:
        default = infer_scene_contract(asset_key=asset_key, visual_prompt=visual_prompt)
        locked_defaults = bool(asset_scene_defaults(asset_key))
        if not isinstance(raw, dict):
            return default
        if locked_defaults:
            contract: dict[str, object] = dict(default)
            for key in ("easter_egg_kind", "easter_egg_placement", "easter_egg_detail", "easter_egg_visibility", "easter_egg_policy", "humor_policy"):
                value = str(raw.get(key, "")).strip()
                if value:
                    contract[key] = value
            humor = str(raw.get("humor", "")).strip()
            if humor:
                contract["humor"] = humor
            contract["visual_prompt"] = visual_prompt
            return contract
        contract: dict[str, object] = dict(default)
        for key in ("subject", "environment", "action", "metaphor", "palette", "mood", "humor"):
            value = str(raw.get(key, "")).strip()
            if locked_defaults and key in {"subject", "environment", "action", "metaphor"}:
                continue
            if value and not is_generic_motif(value) and not looks_like_status_label(value):
                contract[key] = value
        composition_raw = str(raw.get("composition", "")).strip()
        if not locked_defaults and composition_raw and COMPOSITION_SLUG_RE.fullmatch(composition_raw):
            contract["composition"] = composition_raw.lower().replace("-", "_")
        for key in ("props", "overlays"):
            value = raw.get(key)
            if isinstance(value, list):
                cleaned_values = [
                    str(entry).strip()
                    for entry in value
                    if str(entry).strip()
                    and not is_generic_motif(str(entry))
                    and not looks_like_status_label(str(entry))
                ]
                if cleaned_values:
                    contract[key] = cleaned_values[:6]
        for key in ("easter_egg_kind", "easter_egg_placement", "easter_egg_detail", "easter_egg_visibility", "easter_egg_policy", "humor_policy"):
            value = str(raw.get(key, "")).strip()
            if value:
                contract[key] = value
        preferred_compositions = {
            "hero": "clinic_intake",
            "core": "over_shoulder_receipt",
            "ui": "review_bay",
            "mobile": "platform_edge",
            "hub": "service_rack",
            "ui-kit": "mirror_split",
            "hub-registry": "archive_room",
            "media-factory": "render_lane",
            "design": "conspiracy_wall",
            "nexus-pan": "van_interior",
            "alice": "simulation_lab",
            "karma-forge": "approval_rail",
            "jackpoint": "dossier_desk",
            "runsite": "district_map",
            "runbook-press": "proof_room",
            "table-pulse": "forensic_replay",
        }
        preferred = preferred_compositions.get(asset_key)
        if preferred and str(contract.get("composition") or "").strip().lower() in {
            "single_protagonist",
            "service_rack",
            "desk_still_life",
            "city_edge",
            "horizon_boulevard",
            "solo_operator",
            "transit_checkpoint",
            "workshop",
        }:
            contract["composition"] = preferred
        # Keep the prompt close by so downstream renderers can reason over both.
        contract["visual_prompt"] = visual_prompt
        return contract

    def infer_visual_motifs(
        *,
        asset_key: str,
        scene_contract: dict[str, object],
        overlay_hint: str,
        item_title: str,
    ) -> list[str]:
        scene_label_map = {
            "hero": "intake truth check",
            "hub": "relay spine",
            "ui-kit": "shared chrome",
            "hub-registry": "artifact customs",
            "media-factory": "packet refinery",
            "nexus-pan": "hardware handshake",
            "alice": "preflight branch scan",
            "karma-forge": "governed rules forge",
            "jackpoint": "dossier provenance",
            "runsite": "threat map",
            "runbook-press": "proof rail",
            "table-pulse": "post-session heat web",
        }
        scene_label = scene_label_map.get(asset_key, str(item_title or "").strip() or str(asset_key or "").strip())
        motifs: list[str] = []
        for key in ("subject", "environment", "action", "metaphor"):
            value = str(scene_contract.get(key, "")).strip()
            if value:
                motifs.append(value)
        for key in ("props", "overlays"):
            value = scene_contract.get(key)
            if isinstance(value, list):
                motifs.extend(str(entry).strip() for entry in value if str(entry).strip())
        for candidate in (overlay_hint, scene_label):
            cleaned_candidate = str(candidate or "").strip()
            if cleaned_candidate:
                motifs.append(cleaned_candidate)
        deduped: list[str] = []
        seen: set[str] = set()
        for motif in motifs:
            if is_generic_motif(motif):
                continue
            key = motif.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(motif)
            if len(deduped) >= 6:
                break
        return deduped or ["contextual scene", "diegetic overlays", "grounded prop cluster"]

    def infer_overlay_callouts(*, target: str, scene_contract: dict[str, object], overlay_hint: str) -> list[str]:
        callouts: list[str] = []
        for entry in scene_contract.get("overlays", []):
            cleaned_entry = str(entry).strip()
            if cleaned_entry and not looks_like_status_label(cleaned_entry):
                callouts.append(cleaned_entry)
        if len(callouts) < 3 and overlay_hint.strip() and not looks_like_status_label(overlay_hint):
            callouts.append(overlay_hint.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for callout in callouts:
            key = callout.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(callout)
            if len(deduped) >= 4:
                break
        overlay_mode = overlay_mode_for_target(target)
        if overlay_mode == "medscan_diagnostic":
            curated = [
                entry
                for entry in deduped
                if any(
                    token in entry.casefold()
                    for token in ("wound", "cyberlimb", "neural", "calibration", "stabil", "implant", "augment")
                )
            ]
            for fallback in ("Wound stabilized", "Cyberlimb calibration", "Neural link resync"):
                if fallback.casefold() not in {entry.casefold() for entry in curated}:
                    curated.append(fallback)
                if len(curated) >= 4:
                    break
            return curated[:4]
        if overlay_mode == "ambient_diegetic":
            curated = [
                entry
                for entry in deduped
                if any(token in entry.casefold() for token in ("lane", "district", "path", "route", "arc"))
            ]
            for fallback in ("Lane arc", "District marker", "Path trace"):
                if fallback.casefold() not in {entry.casefold() for entry in curated}:
                    curated.append(fallback)
                if len(curated) >= 4:
                    break
            return curated[:4]
        if overlay_mode == "forge_review_ar":
            curated = [
                entry
                for entry in deduped
                if any(
                    token in entry.casefold()
                    for token in ("approval", "provenance", "rollback", "witness", "revert", "compatibility")
                )
            ]
            for fallback in ("Approval rail", "Provenance seal", "Rollback vector", "Witness lock"):
                if fallback.casefold() not in {entry.casefold() for entry in curated}:
                    curated.append(fallback)
                if len(curated) >= 4:
                    break
            return curated[:4]
        if deduped:
            return deduped
        return ["diegetic HUD traces", "receipt markers"]

    normalized = dict(cleaned)
    if kind == "hero":
        for field in ("badge", "title", "subtitle", "kicker", "note", "overlay_hint", "visual_prompt"):
            value = str(normalized.get(field, "")).strip()
            if not value:
                raise ValueError(f"hero media field is missing: {field}")
            normalized[field] = value
        fallback_fields = fallback_media_fields(asset_key="hero", kind="hero")
        if looks_like_status_label(str(normalized["badge"])):
            normalized["badge"] = fallback_fields["badge"]
        if contains_meta_humor_language(str(normalized["title"])):
            normalized["title"] = "Chummer6"
        if contains_meta_humor_language(str(normalized["subtitle"])):
            normalized["subtitle"] = "An idea about letting the math show its work before the table has to improvise trust."
        if looks_like_status_label(str(normalized["kicker"])) or re.match(r"^(stop|start|grab|download|use|trust)\b", str(normalized["kicker"]).strip().lower()):
            normalized["kicker"] = fallback_fields["kicker"]
        if contains_meta_humor_language(str(normalized["kicker"])):
            normalized["kicker"] = fallback_fields["kicker"]
        if re.match(r"^(stop|start|grab|download|use|trust)\b", str(normalized["subtitle"]).strip().lower()):
            normalized["subtitle"] = "An idea about letting the math show its work before the table has to improvise trust."
        normalized["meta"] = str(normalized.get("meta", "")).strip()
        if contains_meta_humor_language(str(normalized["note"])):
            normalized["note"] = fallback_fields["note"]
        if needs_concept_meta_refresh(str(normalized["meta"])) or contains_meta_humor_language(str(normalized["meta"])) or "proof of intent" in str(normalized["meta"]).lower():
            normalized["meta"] = fallback_media_meta(asset_key="hero", kind="hero")
        normalized["scene_contract"] = normalize_scene_contract(
            normalized.get("scene_contract"),
            asset_key="hero",
            visual_prompt=str(normalized["visual_prompt"]),
        )
        hero_target = media_asset_target(kind=kind, item=item)
        hero_visual_contract = visual_contract_for_target(hero_target)
        if hero_visual_contract:
            normalized["scene_contract"]["visual_contract"] = hero_visual_contract
        hero_contract_clause = visual_contract_prompt_clause(hero_target)
        fallback_visual_prompt = (
            f"{normalized['scene_contract'].get('subject')}, "
            f"{normalized['scene_contract'].get('action')}, "
            f"{normalized['scene_contract'].get('environment')}, "
            f"{normalized['scene_contract'].get('palette')}, {fallback_finish_clause_for_target(hero_target)}. "
            f"{hero_contract_clause}"
        ).strip()
        normalized["visual_prompt"] = sanitize_visual_prompt_text(
            str(normalized["visual_prompt"]),
            fallback=fallback_visual_prompt,
        )
        if asset_scene_defaults("hero"):
            normalized["visual_prompt"] = fallback_visual_prompt
        if asset_scene_defaults("hero") or contains_machine_overlay_language(str(normalized["overlay_hint"])) or looks_like_status_label(str(normalized["overlay_hint"])):
            normalized["overlay_hint"] = infer_overlay_hint(
                target=hero_target,
                asset_key="hero",
                scene_contract=normalized["scene_contract"],
                item_title="hero",
            )
        title_lowered = str(normalized.get("title", "")).strip().lower()
        if re.match(r"^(stop|start|grab|download|use)\b", title_lowered):
            normalized["title"] = "An Idea With Receipts"
        note_lowered = str(normalized.get("note", "")).strip().lower()
        if any(
            token in note_lowered
            for token in (
                "proof of concept",
                "proof of intent",
                "prototype logic",
                "rely on it",
                "finished tool",
                "the math is the law",
                "authority",
            )
        ):
            normalized["note"] = fallback_fields["note"]
        allow_easter_egg = media_easter_egg_allowed(kind=kind, item=item, contract=normalized["scene_contract"])
        allow_humor = media_humor_allowed(kind=kind, item=item, contract=normalized["scene_contract"])
        normalized["scene_contract"]["humor"] = sanitize_media_humor(str(normalized["scene_contract"].get("humor") or ""))
        if not allow_humor:
            normalized["scene_contract"]["humor"] = ""
        if not allow_easter_egg:
            normalized["visual_prompt"] = strip_media_easter_egg_clauses(str(normalized["visual_prompt"]))
            for field in ("subject", "environment", "action", "metaphor", "palette", "mood"):
                normalized["scene_contract"][field] = strip_media_easter_egg_clauses(str(normalized["scene_contract"].get(field) or ""))
            normalized["scene_contract"]["props"] = [
                str(entry).strip()
                for entry in normalized["scene_contract"].get("props", [])
                if str(entry).strip() and not _mentions_troll_motif(str(entry))
            ]
            normalized["scene_contract"]["overlays"] = [
                str(entry).strip()
                for entry in normalized["scene_contract"].get("overlays", [])
                if str(entry).strip() and not _mentions_troll_motif(str(entry))
            ]
            for field in ("easter_egg_kind", "easter_egg_placement", "easter_egg_detail", "easter_egg_visibility", "easter_egg_policy"):
                normalized["scene_contract"].pop(field, None)
        normalized["scene_contract"]["overlays"] = strip_unbacked_mechanics_entries(
            [str(entry).strip() for entry in normalized["scene_contract"].get("overlays", []) if str(entry).strip()],
            scope="hero_media:hero.scene_contract.overlays",
            receipt_refs=_mechanics_receipt_refs(item),
        )
        raw_motifs = normalized.get("visual_motifs")
        motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()] if isinstance(raw_motifs, list) else []
        if not allow_easter_egg:
            motifs = [entry for entry in motifs if not _mentions_troll_motif(entry)]
        motifs = strip_unbacked_mechanics_entries(
            motifs,
            scope="hero_media:hero.visual_motifs",
            receipt_refs=_mechanics_receipt_refs(item),
        )
        if asset_scene_defaults("hero"):
            motifs = []
        normalized["visual_motifs"] = motifs or infer_visual_motifs(
            asset_key="hero",
            scene_contract=normalized["scene_contract"],
            overlay_hint=str(normalized["overlay_hint"]),
            item_title="hero",
        )
        raw_callouts = normalized.get("overlay_callouts")
        callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()] if isinstance(raw_callouts, list) else []
        if not allow_easter_egg:
            callouts = [entry for entry in callouts if not _mentions_troll_motif(entry)]
        callouts = [entry for entry in callouts if not looks_like_status_label(entry)]
        callouts = strip_unbacked_mechanics_entries(
            callouts,
            scope="hero_media:hero.overlay_callouts",
            receipt_refs=_mechanics_receipt_refs(item),
        )
        if asset_scene_defaults("hero"):
            callouts = []
        normalized["overlay_callouts"] = callouts or infer_overlay_callouts(
            target=hero_target,
            scene_contract=normalized["scene_contract"],
            overlay_hint=str(normalized["overlay_hint"]),
        )
        issues = _mechanics_boundary_issues(
            normalized,
            scope="hero_media:hero",
            receipt_refs=_mechanics_receipt_refs(item),
        )
        if issues:
            first = issues[0]
            raise ValueError(f"unbacked mechanics claim in {first['scope']}:{first['reason']}")
        return normalized
    for field in ("badge", "title", "subtitle", "kicker", "note", "overlay_hint", "visual_prompt"):
        value = str(normalized.get(field, "")).strip()
        if not value:
            raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.{field}")
        normalized[field] = value
    normalized["meta"] = str(normalized.get("meta", "")).strip()
    asset_key = asset_slug(item)
    fallback_fields = fallback_media_fields(asset_key=asset_key, kind=kind)
    curated_titles = {
        "hub": ("Relay Spine", "Hosted coordination under pressure."),
        "ui-kit": ("Shared Chrome", "One visual language surviving across rough surfaces."),
        "hub-registry": ("Artifact Customs", "Intake, labels, and provenance before rumor."),
        "media-factory": ("Packet Refinery", "Rough packets cleaned up without washing out the trail."),
    }
    if looks_like_status_label(str(normalized["badge"])):
        normalized["badge"] = fallback_fields["badge"]
    if contains_meta_humor_language(str(normalized["title"])):
        normalized["title"] = str(item.get("title") or item.get("slug") or kind).strip() or "Concept lane"
    title_lowered = str(normalized["title"]).strip().lower()
    if asset_key in curated_titles and title_lowered in {
        str(item.get("title") or "").strip().lower(),
        asset_key,
        asset_key.replace("-", " "),
    }:
        normalized["title"] = curated_titles[asset_key][0]
        normalized["subtitle"] = curated_titles[asset_key][1]
    if looks_like_status_label(str(normalized["subtitle"])) or contains_machine_overlay_language(str(normalized["subtitle"])):
        normalized["subtitle"] = (
            str(item.get("hook") or item.get("why") or item.get("problem") or item.get("title") or "").strip()
            or fallback_fields["note"]
        )
    if contains_meta_humor_language(str(normalized["subtitle"])):
        normalized["subtitle"] = (
            str(item.get("hook") or item.get("why") or item.get("problem") or item.get("title") or "").strip()
            or fallback_fields["note"]
        )
    if looks_like_status_label(str(normalized["kicker"])) or re.match(r"^(stop|start|grab|download|use|trust)\b", str(normalized["kicker"]).strip().lower()):
        normalized["kicker"] = fallback_fields["kicker"]
    if contains_meta_humor_language(str(normalized["kicker"])):
        normalized["kicker"] = fallback_fields["kicker"]
    note_lowered = str(normalized["note"]).strip().lower()
    if any(
        token in note_lowered
        for token in (
            "finished tool",
            "finished press",
            "prototype logic",
            "lua-scripted",
            "integrity signature",
            "artifact-driven",
            "spatial awareness",
            "professional weight",
            "authority",
            "the math is the law",
        )
    ):
        normalized["note"] = fallback_fields["note"]
    if contains_meta_humor_language(str(normalized["note"])):
        normalized["note"] = fallback_fields["note"]
    if needs_concept_meta_refresh(str(normalized["meta"])) or contains_meta_humor_language(str(normalized["meta"])):
        normalized["meta"] = fallback_media_meta(asset_key=asset_key, kind=kind)
    normalized["scene_contract"] = normalize_scene_contract(
        normalized.get("scene_contract"),
        asset_key=asset_key,
        visual_prompt=str(normalized["visual_prompt"]),
    )
    media_target = media_asset_target(kind=kind, item=item)
    visual_contract = visual_contract_for_target(media_target)
    if visual_contract:
        normalized["scene_contract"]["visual_contract"] = visual_contract
    contract_clause = visual_contract_prompt_clause(media_target)
    fallback_visual_prompt = (
        f"{normalized['scene_contract'].get('subject')}, "
        f"{normalized['scene_contract'].get('action')}, "
        f"{normalized['scene_contract'].get('environment')}, "
        f"{normalized['scene_contract'].get('palette')}, {fallback_finish_clause_for_target(media_target)}. "
        f"{contract_clause}"
    ).strip()
    normalized["visual_prompt"] = sanitize_visual_prompt_text(
        str(normalized["visual_prompt"]),
        fallback=fallback_visual_prompt,
    )
    if asset_scene_defaults(asset_key):
        normalized["visual_prompt"] = fallback_visual_prompt
    locked_scene_defaults = bool(asset_scene_defaults(asset_key))
    if locked_scene_defaults or contains_machine_overlay_language(str(normalized["overlay_hint"])) or looks_like_status_label(str(normalized["overlay_hint"])):
        normalized["overlay_hint"] = infer_overlay_hint(
            target=media_target,
            asset_key=asset_key,
            scene_contract=normalized["scene_contract"],
            item_title=str(item.get("title", item.get("slug", kind))),
        )
    allow_easter_egg = media_easter_egg_allowed(kind=kind, item=item, contract=normalized["scene_contract"])
    allow_humor = media_humor_allowed(kind=kind, item=item, contract=normalized["scene_contract"])
    normalized["scene_contract"]["humor"] = sanitize_media_humor(str(normalized["scene_contract"].get("humor") or ""))
    if not allow_humor:
        normalized["scene_contract"]["humor"] = ""
    if not allow_easter_egg:
        normalized["visual_prompt"] = strip_media_easter_egg_clauses(str(normalized["visual_prompt"]))
        for field in ("subject", "environment", "action", "metaphor", "palette", "mood"):
            normalized["scene_contract"][field] = strip_media_easter_egg_clauses(str(normalized["scene_contract"].get(field) or ""))
        normalized["scene_contract"]["props"] = [
            str(entry).strip()
            for entry in normalized["scene_contract"].get("props", [])
            if str(entry).strip() and not _mentions_troll_motif(str(entry))
        ]
        normalized["scene_contract"]["overlays"] = [
            str(entry).strip()
            for entry in normalized["scene_contract"].get("overlays", [])
            if str(entry).strip() and not _mentions_troll_motif(str(entry))
        ]
        for field in ("easter_egg_kind", "easter_egg_placement", "easter_egg_detail", "easter_egg_visibility", "easter_egg_policy"):
            normalized["scene_contract"].pop(field, None)
    normalized["scene_contract"]["overlays"] = strip_unbacked_mechanics_entries(
        [str(entry).strip() for entry in normalized["scene_contract"].get("overlays", []) if str(entry).strip()],
        scope=f"{kind}_media:{item.get('slug', item.get('title', kind))}.scene_contract.overlays",
        receipt_refs=_mechanics_receipt_refs(item),
    )
    raw_motifs = normalized.get("visual_motifs")
    motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()] if isinstance(raw_motifs, list) else []
    if not allow_easter_egg:
        motifs = [entry for entry in motifs if not _mentions_troll_motif(entry)]
    motifs = [entry for entry in motifs if not is_generic_motif(entry) and not looks_like_status_label(entry)]
    motifs = strip_unbacked_mechanics_entries(
        motifs,
        scope=f"{kind}_media:{item.get('slug', item.get('title', kind))}.visual_motifs",
        receipt_refs=_mechanics_receipt_refs(item),
    )
    if locked_scene_defaults:
        motifs = []
    normalized["visual_motifs"] = motifs or infer_visual_motifs(
        asset_key=str(item.get("slug", item.get("title", "horizon"))),
        scene_contract=normalized["scene_contract"],
        overlay_hint=str(normalized["overlay_hint"]),
        item_title=str(item.get("title", item.get("slug", "horizon"))),
    )
    raw_callouts = normalized.get("overlay_callouts")
    callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()] if isinstance(raw_callouts, list) else []
    if not allow_easter_egg:
        callouts = [entry for entry in callouts if not _mentions_troll_motif(entry)]
    callouts = [entry for entry in callouts if not looks_like_status_label(entry)]
    callouts = strip_unbacked_mechanics_entries(
        callouts,
        scope=f"{kind}_media:{item.get('slug', item.get('title', kind))}.overlay_callouts",
        receipt_refs=_mechanics_receipt_refs(item),
    )
    if locked_scene_defaults:
        callouts = []
    normalized["overlay_callouts"] = callouts or infer_overlay_callouts(
        target=media_target,
        scene_contract=normalized["scene_contract"],
        overlay_hint=str(normalized["overlay_hint"]),
    )
    issues = _mechanics_boundary_issues(
        normalized,
        scope=f"{kind}_media:{item.get('slug', item.get('title', kind))}",
        receipt_refs=_mechanics_receipt_refs(item),
    )
    if issues:
        first = issues[0]
        raise ValueError(f"unbacked mechanics claim in {first['scope']}:{first['reason']}")
    return normalized


PAGE_PROMPTS: dict[str, dict[str, str]] = {
    "readme": {
        "source": "The main landing page. Explain why Chummer6 exists, why a human should care, where they should click next, and why the current phase is foundations first.",
    },
    "start_here": {
        "source": "Welcome and first-run orientation for a new human reader. Lead with tonight's problems and the shortest path to answers. Do not open with repo splits, architecture, nodes, or internal organization.",
    },
    "what_chummer6_is": {
        "source": "Explain what Chummer6 is becoming for players and GMs, why it matters at the table, and what feels different from older opaque tools. Keep repo and architecture talk below the product story. Keep it concept-stage, tie it back to trust or receipts, and treat anything visible today as accidental spillover rather than a product promise.",
    },
    "faq": {
        "source": faq_page_source(),
    },
    "how_can_i_help": {
        "source": help_page_source(),
    },
    "where_to_go_deeper": {
        "source": "Explain where to read next, what to trust, and where to report confusion. Do not use blueprint, drift, hierarchy, governance, or repo-maintainer language.",
    },
    "current_phase": {
        "source": "Explain the current phase in human language: trust work first, not feature fireworks. Translate any internal boundary cleanup into what it means for a real session tonight.",
    },
    "current_status": {
        "source": "Explain the current visible state without sounding like raw ops telemetry or architecture notes. Lead with what a player or GM would notice today.",
    },
    "public_surfaces": {
        "source": "Explain what is visible now, what someone can try, and why preview does not mean fake. Avoid ownership and architecture wording unless immediately translated.",
    },
    "parts_index": {
        "source": "Introduce the main parts in a field-guide voice and help the reader choose where to go next based on symptoms and use cases, not repo taxonomy.",
    },
    "horizons_index": {
        "source": "Sell the horizon section as future table pain relief and vivid scene ideas without pretending they are active work. Avoid blueprint, garage, or architecture metaphors.",
    },
}

PAGE_RISKY_SPECIFIC_CLAIMS: tuple[str, ...] = (
    "gear availability",
    "gear costs",
    "gear limits",
    "character integrity",
    "session continuity",
    "device swap",
    "commlink reboot",
    "corporate uplink",
    "on your phone",
    "your phone",
    "total precision",
    "multi-era",
    "scripted rules",
    "lua-scripted",
    "mobile-ready",
    "live data",
    "works without a grid connection",
    "without a grid connection",
    "works offline",
    "fully offline",
    "offline-ready",
    "offline ready",
    "keeps your data on your device",
    "keeps the data on your device",
    "data stays on your device",
    "data stays on your deck",
    "on your own gear",
    "local grid",
    "core-backed receipts",
    "poc build",
    "release notes",
    "downloadable",
    "what's functional",
    "system integrity",
    "integrity signatures",
    "build timestamps",
    "live-fire test",
    "live fire test",
    "core logic",
    "release shelf",
    "latest drop",
    "available today",
    "usable tonight",
    "public guide is active today",
    "integrity clues",
)
PAGE_RISKY_GAME_DETAIL_TOKENS: tuple[str, ...] = (
    "stat change",
    "stat adjustment",
    "qualities",
    "cyberware",
    "initiative",
    "health",
    "sr4",
    "sr5",
    "vision modifiers",
    "combat turns",
    "augmentations",
    "karma spend",
    "street sam",
    "smartlink",
    "optics",
    "dice-pool math",
    "dice pool math",
)
PAGE_SOFT_FILLER_PHRASES: tuple[str, ...] = (
    "session shell",
    "character engine",
    "local-first system",
    "rules prep surface",
    "local-first rules prep surface",
    "rules workbench",
    "proof of concept",
    "proof-of-concept",
    "poc drop",
    "pre-release",
    "prerelease",
    "designed to give",
    "delivers a",
)
PAGE_MATH_CERTAINTY_PHRASES: tuple[str, ...] = (
    "the math is clear",
    "math is clear",
    "trust the math",
    "rules truth",
    "deterministic truth",
    "deterministic answers",
    "deterministic core",
    "deterministic rules engine",
    "deterministic rules truth",
    "deterministic math",
    "deterministic logic",
    "core logic today",
    "every stat and threshold",
    "every dice pool",
    "fully scripted",
    "fully functional",
    "trustworthy math",
    "trustworthy math receipts",
    "receipts for every calculation",
    "verify rules math",
    "rules are functioning today",
    "functioning today before you buy in",
    "the math should explain itself",
)
BAD_PAGE_OPENING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsmartlink\b|\boptics\b", re.IGNORECASE), "niche_gear_hook"),
    (re.compile(r"\bvision modifiers?\b|\bcombat turns?\b", re.IGNORECASE), "mechanics_hook"),
    (re.compile(r"\bkarma spend\b|\bstreet sam\b|\baugmentations?\b", re.IGNORECASE), "character_build_hook"),
    (re.compile(r"\bdice pools?\b[^.!?\n]{0,24}\bmodifier", re.IGNORECASE), "modifier_hook"),
)
TOTALIZING_PUBLIC_MATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bevery\s+(?:calculation|bonus|penalty|modifier|threshold|value|stat|rule)\b", re.IGNORECASE),
    re.compile(r"\ball\s+(?:calculations|bonuses|penalties|modifiers|thresholds|values|stats|rules)\b", re.IGNORECASE),
    re.compile(r"\bevery\s+(?:result|outcome)\b", re.IGNORECASE),
    re.compile(r"\ball\s+(?:results|outcomes)\b", re.IGNORECASE),
    re.compile(r"\bevery\s+(?:functioning\s+)?(?:mechanic|feature)\b", re.IGNORECASE),
)

def chunk_mapping(mapping: dict[str, object], *, size: int) -> list[dict[str, object]]:
    items = list(mapping.items())
    return [dict(items[index : index + size]) for index in range(0, len(items), size)]


def selected_mapping(mapping: dict[str, object], selected_ids: Sequence[str] | None) -> dict[str, object]:
    if not selected_ids:
        return dict(mapping)
    wanted = [str(item or "").strip() for item in selected_ids if str(item or "").strip()]
    filtered = {key: value for key, value in mapping.items() if key in wanted}
    missing = [item for item in wanted if item not in filtered]
    if missing:
        raise ValueError(f"unknown_chummer6_section_ids:{','.join(missing)}")
    return filtered


def parse_selected_ids(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def load_reusable_ooda(path: Path) -> dict[str, object]:
    payload = load_json_file(path)
    ooda = payload.get("ooda")
    return dict(ooda) if isinstance(ooda, dict) else {}


def section_batch_size(section_type: str, total: int) -> int:
    defaults = {
        "page": 2,
        "part": 2,
        "horizon": 2,
    }
    env_key = f"CHUMMER6_{section_type.upper()}_BATCH_SIZE"
    raw = str(os.environ.get(env_key) or LOCAL_ENV.get(env_key) or "").strip()
    try:
        value = int(raw or defaults.get(section_type, 1))
    except Exception:
        value = defaults.get(section_type, 1)
    return max(1, min(total, value))


def effective_section_batch_size(
    section_type: str,
    total: int,
    *,
    prefer_quality: bool = False,
) -> int:
    if prefer_quality and section_type == "page":
        return 1
    return section_batch_size(section_type, total)


def generate_overrides(
    *,
    include_parts: bool,
    include_horizons: bool,
    model: str,
    include_pages: bool = True,
    include_hero_media: bool = True,
    reused_ooda: dict[str, object] | None = None,
    page_ids: Sequence[str] | None = None,
    part_ids: Sequence[str] | None = None,
    horizon_ids: Sequence[str] | None = None,
    run_skill_audits: bool = True,
    prefer_brain_humanizer: bool = False,
    prefer_page_quality: bool = False,
) -> dict[str, object]:
    global TEXT_PROVIDER_USED
    TEXT_PROVIDER_USED = ""
    signals = collect_interest_signals()
    style_epoch = resolve_style_epoch(increment=include_parts and include_horizons)
    recent_scene_source_rows = recent_scene_rows_for_style_epoch(style_epoch=style_epoch, allow_fallback=False)
    recent_scenes = scene_ledger_summary(recent_scene_source_rows)
    overrides: dict[str, object] = {
        "parts": {},
        "horizons": {},
        "pages": {},
        "media": {"hero": {}, "horizons": {}},
        "ooda": {},
        "section_ooda": {"hero": {}, "parts": {}, "horizons": {}, "pages": {}},
        "meta": {
            "generator": "ea",
            "provider": "unknown",
            "provider_status": "unknown",
            "provider_error": "",
            "ooda_version": "v3",
            "style_epoch": style_epoch,
            "recent_scene_ledger": recent_scenes,
        },
    }
    provider_error = ""
    selected_pages = selected_mapping(PAGE_PROMPTS, page_ids) if include_pages else {}
    selected_parts = selected_mapping(PARTS, part_ids) if include_parts else {}
    selected_horizons = selected_mapping(HORIZONS, horizon_ids) if include_horizons else {}
    focused_page_quality_run = (
        prefer_page_quality
        and bool(selected_pages)
        and not include_parts
        and not include_horizons
    )
    trace(
        "regen start"
        + f" pages={','.join(selected_pages.keys()) or '-'}"
        + f" parts={','.join(selected_parts.keys()) or '-'}"
        + f" horizons={','.join(selected_horizons.keys()) or '-'}"
        + f" hero_media={'yes' if include_hero_media else 'no'}"
    )
    reusable = dict(reused_ooda or {})
    if reusable:
        trace("global OODA reused")
        overrides["ooda"] = normalize_ooda(reusable, signals)
    else:
        try:
            trace("global OODA")
            ooda_result = chat_json(build_ooda_prompt(signals), model=model, skill_key=PUBLIC_WRITER_SKILL_KEY)
            overrides["ooda"] = normalize_ooda(ooda_result, signals)
        except Exception as exc:
            trace(f"global OODA fallback: {exc}")
            overrides["ooda"] = normalize_ooda({}, signals)
    ooda = dict(overrides.get("ooda") or {})
    if isinstance(ooda.get("act"), dict):
        humanize_mapping_fields_with_mode(
            ooda["act"],
            ("landing_intro", "what_it_is", "watch_intro", "horizon_intro"),
            target_prefix="guide:ooda:act",
            brain_only=prefer_brain_humanizer,
        )
    if include_hero_media:
        try:
            trace("hero OODA")
            hero_ooda_result = chat_json(
                build_section_ooda_prompt(
                    "hero",
                    "hero",
                    {},
                    global_ooda=ooda,
                    style_epoch=style_epoch,
                    recent_scenes=recent_scenes,
                ),
                model=model,
                skill_key=VISUAL_DIRECTOR_SKILL_KEY,
            )
            hero_ooda = normalize_section_ooda(hero_ooda_result, section_type="hero", name="hero", item={}, global_ooda=ooda)
        except Exception as exc:
            raise RuntimeError(f"hero section OODA generation failed: {exc}") from exc
        overrides["section_ooda"]["hero"]["hero"] = hero_ooda
        try:
            trace("hero media")
            result = chat_json(
                build_media_prompt(
                    "hero",
                    "hero",
                    {},
                    ooda=ooda,
                    section_ooda=hero_ooda,
                    style_epoch=style_epoch,
                    recent_scenes=recent_scenes,
                    variation_guardrails=variation_guardrails_for("assets/hero/chummer6-hero.png", recent_scene_source_rows),
                ),
                model=model,
                skill_key=VISUAL_DIRECTOR_SKILL_KEY,
            )
            cleaned = {}
            for key in ("badge", "title", "subtitle", "kicker", "note", "meta", "visual_prompt", "overlay_hint"):
                value = str(result.get(key, "")).strip()
                if value:
                    cleaned[key] = value
            for key in ("visual_motifs", "overlay_callouts"):
                raw = result.get(key)
                if isinstance(raw, list):
                    cleaned[key] = [str(entry).strip() for entry in raw if str(entry).strip()]
            cleaned = normalize_media_override("hero", cleaned, {})
        except Exception as exc:
            raise RuntimeError(f"hero media generation failed: {exc}") from exc
        cleaned = normalize_media_override("hero", cleaned, {})
        overrides["media"]["hero"] = cleaned
    page_oodas: dict[str, object] = {}
    if focused_page_quality_run:
        trace("page OODA skipped for focused quality run")
        page_oodas = {page_id: {} for page_id in selected_pages.keys()}
    else:
        for batch in chunk_mapping(
            selected_pages,
            size=effective_section_batch_size(
                "page",
                len(selected_pages),
                prefer_quality=prefer_page_quality,
            ),
        ):
            try:
                trace(f"page OODA bundle: {','.join(batch.keys())}")
                page_ooda_result = chat_json(
                    build_section_oodas_bundle_prompt(
                        "page",
                        batch,
                        global_ooda=ooda,
                        style_epoch=style_epoch,
                        recent_scenes=recent_scenes,
                    ),
                    model=model,
                    skill_key=PUBLIC_WRITER_SKILL_KEY,
                )
                page_oodas.update(
                    normalize_section_oodas_bundle(
                        page_ooda_result,
                        section_type="page",
                        section_items=batch,
                        global_ooda=ooda,
                    )
                )
            except Exception as exc:
                raise RuntimeError(f"page section OODA bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
    overrides["section_ooda"]["pages"] = page_oodas
    page_rows: dict[str, object] = {}
    for batch in chunk_mapping(
        selected_pages,
        size=effective_section_batch_size(
            "page",
            len(selected_pages),
            prefer_quality=prefer_page_quality,
        ),
    ):
        try:
            trace(f"page copy bundle: {','.join(batch.keys())}")
            page_bundle = chat_json(
                build_pages_bundle_prompt(
                    items=batch,
                    global_ooda=ooda,
                    section_oodas={name: page_oodas[name] for name in batch.keys()},
                ),
                model=model,
                skill_key=PUBLIC_WRITER_SKILL_KEY,
            )
            try:
                page_rows.update(normalize_pages_bundle(page_bundle, items=batch))
            except Exception:
                if len(batch) != 1:
                    raise
                page_id, item = next(iter(batch.items()))
                try:
                    trace(f"page bundle repair: {page_id}")
                    page_rows[page_id] = normalize_single_page_bundle_candidate(page_bundle, page_id=page_id)
                except Exception:
                    try:
                        trace(f"page single retry: {page_id}")
                        page_rows[page_id] = normalize_single_page_bundle_candidate(
                            chat_json(
                                build_page_prompt(
                                    page_id,
                                    dict(item),
                                    global_ooda=ooda,
                                    section_ooda=dict(page_oodas.get(page_id) or {}),
                                ),
                                model=model,
                                skill_key=PUBLIC_WRITER_SKILL_KEY,
                            ),
                            page_id=page_id,
                        )
                    except Exception:
                        trace(f"page bundle fallback: {page_id}")
                        page_rows[page_id] = fallback_page_copy(page_id, dict(item), ooda)
        except Exception as exc:
            raise RuntimeError(f"page copy bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
    for page_id, row in list(page_rows.items()):
        trace(f"page polish: {page_id}")
        page_rows[page_id] = polish_copy_row(
            section_type="page",
            name=page_id,
            row=dict(row),
            item=dict(selected_pages.get(page_id) or {}),
            global_ooda=ooda,
            section_ooda=dict(page_oodas.get(page_id) or {}),
            model=model,
        )
    for page_id, row in page_rows.items():
        trace(f"page humanize: {page_id}")
        page_rows[page_id] = finalize_copy_row(
            section_type="page",
            name=page_id,
            row=row,
            item=dict(selected_pages.get(page_id) or {}),
            global_ooda=ooda,
            section_ooda=dict(page_oodas.get(page_id) or {}),
            model=model,
            humanize_keys=("intro", "body", "kicker"),
            target_prefix=f"guide:page:{page_id}",
            prefer_brain_humanizer=prefer_brain_humanizer,
        )
    overrides["pages"] = page_rows
    if include_parts:
        part_oodas: dict[str, object] = {}
        for batch in chunk_mapping(selected_parts, size=section_batch_size("part", len(selected_parts))):
            try:
                trace(f"part OODA bundle: {','.join(batch.keys())}")
                part_ooda_result = chat_json(
                    build_section_oodas_bundle_prompt("part", batch, global_ooda=ooda, style_epoch=style_epoch, recent_scenes=recent_scenes),
                    model=model,
                    skill_key=VISUAL_DIRECTOR_SKILL_KEY,
                )
                part_oodas.update(
                    normalize_section_oodas_bundle(
                        part_ooda_result,
                        section_type="part",
                        section_items=batch,
                        global_ooda=ooda,
                    )
                )
            except Exception as exc:
                raise RuntimeError(f"part section OODA bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        overrides["section_ooda"]["parts"] = part_oodas
        part_copy_rows: dict[str, object] = {}
        part_media_rows: dict[str, object] = {}
        for batch in chunk_mapping(selected_parts, size=section_batch_size("part", len(selected_parts))):
            try:
                trace(f"part copy/media bundle: {','.join(batch.keys())}")
                part_bundle = chat_json(
                    build_parts_bundle_prompt(
                        items=batch,
                        global_ooda=ooda,
                        section_oodas={name: part_oodas[name] for name in batch.keys()},
                        style_epoch=style_epoch,
                        recent_scenes=recent_scenes,
                    ),
                    model=model,
                    skill_key=PUBLIC_WRITER_SKILL_KEY,
                )
                batch_copy_rows, batch_media_rows = normalize_parts_bundle(part_bundle, items=batch)
                part_copy_rows.update(batch_copy_rows)
                part_media_rows.update(batch_media_rows)
            except Exception as exc:
                raise RuntimeError(f"part copy/media bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        for name, item in selected_parts.items():
            cleaned_copy = dict(part_copy_rows[name])
            try:
                cleaned_copy = polish_copy_row(
                    section_type="part",
                    name=name,
                    row=cleaned_copy,
                    item=item,
                    global_ooda=ooda,
                    section_ooda=part_oodas[name],
                    model=model,
                )
            except Exception:
                fallback = fallback_part_copy(name, item)
                if fallback:
                    cleaned_copy = fallback
                else:
                    raise
            part_copy_rows[name] = cleaned_copy
        for part_id, row in part_copy_rows.items():
            part_copy_rows[part_id] = finalize_copy_row(
                section_type="part",
                name=part_id,
                row=row,
                item=dict(selected_parts.get(part_id) or {}),
                global_ooda=ooda,
                section_ooda=dict(part_oodas.get(part_id) or {}),
                model=model,
                humanize_keys=("when", "why", "now"),
                target_prefix=f"guide:part:{part_id}",
                prefer_brain_humanizer=prefer_brain_humanizer,
            )
        overrides["parts"] = part_copy_rows
        overrides["media"]["parts"] = part_media_rows
    if include_horizons:
        horizon_oodas: dict[str, object] = {}
        for batch in chunk_mapping(selected_horizons, size=section_batch_size("horizon", len(selected_horizons))):
            try:
                trace(f"horizon OODA bundle: {','.join(batch.keys())}")
                horizon_ooda_result = chat_json(
                    build_section_oodas_bundle_prompt("horizon", batch, global_ooda=ooda, style_epoch=style_epoch, recent_scenes=recent_scenes),
                    model=model,
                    skill_key=VISUAL_DIRECTOR_SKILL_KEY,
                )
                horizon_oodas.update(
                    normalize_section_oodas_bundle(
                        horizon_ooda_result,
                        section_type="horizon",
                        section_items=batch,
                        global_ooda=ooda,
                    )
                )
            except Exception as exc:
                raise RuntimeError(f"horizon section OODA bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        overrides["section_ooda"]["horizons"] = horizon_oodas
        horizon_copy_rows: dict[str, object] = {}
        horizon_media_rows: dict[str, object] = {}
        for batch in chunk_mapping(selected_horizons, size=section_batch_size("horizon", len(selected_horizons))):
            try:
                trace(f"horizon copy/media bundle: {','.join(batch.keys())}")
                horizon_bundle = chat_json(
                    build_horizons_bundle_prompt(
                        items=batch,
                        global_ooda=ooda,
                        section_oodas={name: horizon_oodas[name] for name in batch.keys()},
                        style_epoch=style_epoch,
                        recent_scenes=recent_scenes,
                    ),
                    model=model,
                    skill_key=PUBLIC_WRITER_SKILL_KEY,
                )
                batch_copy_rows, batch_media_rows = normalize_horizons_bundle(horizon_bundle, items=batch)
                horizon_copy_rows.update(batch_copy_rows)
                horizon_media_rows.update(batch_media_rows)
            except Exception as exc:
                raise RuntimeError(f"horizon copy/media bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        for name, item in selected_horizons.items():
            cleaned_copy = dict(horizon_copy_rows[name])
            fallback = fallback_horizon_copy(name, item)
            if fallback:
                try:
                    assert_public_reader_safe(fallback, context=f"horizon:{name}:curated_prepolish")
                    fallback_findings = copy_quality_findings("horizon", name, fallback, item)
                except Exception:
                    fallback_findings = ["fallback_invalid"]
                fallback_findings = [str(entry or "").strip() for entry in fallback_findings if str(entry or "").strip()]
                if not fallback_findings:
                    horizon_copy_rows[name] = fallback
                    continue
            try:
                cleaned_copy = polish_copy_row(
                    section_type="horizon",
                    name=name,
                    row=cleaned_copy,
                    item=item,
                    global_ooda=ooda,
                    section_ooda=horizon_oodas[name],
                    model=model,
                )
            except Exception:
                if fallback:
                    cleaned_copy = fallback
                else:
                    raise
            horizon_copy_rows[name] = cleaned_copy
        for horizon_id, row in horizon_copy_rows.items():
            horizon_copy_rows[horizon_id] = finalize_copy_row(
                section_type="horizon",
                name=horizon_id,
                row=row,
                item=dict(selected_horizons.get(horizon_id) or {}),
                global_ooda=ooda,
                section_ooda=dict(horizon_oodas.get(horizon_id) or {}),
                model=model,
                humanize_keys=("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line"),
                target_prefix=f"guide:horizon:{horizon_id}",
                prefer_brain_humanizer=prefer_brain_humanizer,
            )
        overrides["horizons"] = horizon_copy_rows
        overrides["media"]["horizons"] = horizon_media_rows
    if run_skill_audits:
        trace("public audit")
        overrides["meta"]["public_skill_audit"] = run_skill_audit(
            label="public",
            skill_key=PUBLIC_AUDITOR_SKILL_KEY,
            focus="Check reader usefulness, CTA routing, public-safe language, and whether the copy still sounds like a human guide instead of internal coordination notes.",
            payload=_copy_audit_snapshot(overrides),
            model=model,
        )
    else:
        overrides["meta"]["public_skill_audit"] = {"status": "skipped", "reason": "partial_regen"}
    run_media_audits = include_hero_media or include_parts or include_horizons
    if run_media_audits and run_skill_audits:
        trace("scene audit")
        overrides["meta"]["scene_skill_audit"] = run_skill_audit(
            label="scene",
            skill_key=SCENE_AUDITOR_SKILL_KEY,
            focus="Check composition diversity, page-role fit, and whether scene contracts still collapse into repetitive tableaus or generic cyberpunk wallpaper.",
            payload=_scene_audit_snapshot(overrides),
            model=model,
        )
        trace("visual audit")
        overrides["meta"]["visual_skill_audit"] = run_skill_audit(
            label="visual",
            skill_key=VISUAL_AUDITOR_SKILL_KEY,
            focus="Check whether the visible media metadata feels specific, premium, and non-repetitive enough for a public guide pack.",
            payload=_visual_audit_snapshot(overrides),
            model=model,
        )
    else:
        skip_reason = "partial_regen" if not run_skill_audits else "text_only_pages_regen"
        overrides["meta"]["scene_skill_audit"] = {"status": "skipped", "reason": skip_reason}
        overrides["meta"]["visual_skill_audit"] = {"status": "skipped", "reason": skip_reason}
    if run_skill_audits:
        trace("pack audit")
        overrides["meta"]["pack_skill_audit"] = run_skill_audit(
            label="pack",
            skill_key=PACK_AUDITOR_SKILL_KEY,
            focus="Check overall pack coherence: public usefulness, visual consistency, and whether the whole set feels ready to publish for real users.",
            payload=_pack_audit_snapshot(overrides),
            model=model,
        )
    else:
        overrides["meta"]["pack_skill_audit"] = {"status": "skipped", "reason": "partial_regen"}
    overrides["meta"]["scene_plan_audit"] = scene_plan_pack_audit(overrides)
    overrides["meta"]["editorial_audit"] = editorial_pack_audit(overrides)
    overrides["meta"]["provider"] = TEXT_PROVIDER_USED or "unknown"
    overrides["meta"]["provider_status"] = "ok"
    overrides["meta"]["provider_error"] = provider_error
    trace("regen complete")
    return overrides


def main() -> int:
    global TRACE_ENABLED
    parser = argparse.ArgumentParser(description="Generate Chummer6 downstream guide overrides through EA using section-level OODA.")
    parser.add_argument("--output", default=str(OVERRIDE_OUT), help="Where to write the override JSON.")
    parser.add_argument("--model", default=default_text_model(), help="Preferred EA/Gemini text model hint.")
    parser.add_argument("--trace", action="store_true", help="Emit phase trace lines to stderr during generation.")
    parser.add_argument("--pages-only", action="store_true", help="Generate root/page overrides only.")
    parser.add_argument("--parts-only", action="store_true", help="Generate part-page overrides only.")
    parser.add_argument("--horizons-only", action="store_true", help="Generate horizon-page overrides only.")
    parser.add_argument("--pages", default="", help="Comma-separated page ids to regenerate.")
    parser.add_argument("--parts", default="", help="Comma-separated part ids to regenerate.")
    parser.add_argument("--horizons", default="", help="Comma-separated horizon ids to regenerate.")
    parser.add_argument("--full-skill-audits", action="store_true", help="Run external skill audits even for partial targeted regenerations.")
    parser.add_argument("--skip-skill-audits", action="store_true", help="Skip external skill-audit passes even for a full regeneration run.")
    parser.add_argument(
        "--reuse-global-ooda-from",
        default="",
        help="Optional override JSON path to reuse the existing global OODA packet during targeted iterations.",
    )
    args = parser.parse_args()
    TRACE_ENABLED = bool(args.trace) or str(os.environ.get("CHUMMER6_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}

    if sum(1 for enabled in (args.pages_only, args.parts_only, args.horizons_only) if enabled) > 1:
        raise SystemExit("Choose at most one of --pages-only, --parts-only, or --horizons-only.")

    include_parts = not args.horizons_only and not args.pages_only
    include_horizons = not args.parts_only and not args.pages_only
    include_pages = not args.parts_only and not args.horizons_only
    partial_regen = bool(args.pages_only or args.parts_only or args.horizons_only or args.pages or args.parts or args.horizons)
    reuse_ooda_path = str(args.reuse_global_ooda_from or "").strip()
    reusable_ooda = load_reusable_ooda(Path(reuse_ooda_path).expanduser()) if reuse_ooda_path else {}
    overrides = generate_overrides(
        include_pages=include_pages,
        include_parts=include_parts,
        include_horizons=include_horizons,
        model=str(args.model or default_text_model()).strip() or default_text_model(),
        include_hero_media=not args.pages_only,
        reused_ooda=reusable_ooda,
        page_ids=parse_selected_ids(args.pages),
        part_ids=parse_selected_ids(args.parts),
        horizon_ids=parse_selected_ids(args.horizons),
        run_skill_audits=(((not partial_regen) or bool(args.full_skill_audits)) and not bool(args.skip_skill_audits)),
        prefer_brain_humanizer=partial_regen,
        prefer_page_quality=partial_regen,
    )
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(overrides, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "parts": len(overrides.get("parts", {})),
                "horizons": len(overrides.get("horizons", {})),
                "provider_status": ((overrides.get("meta") or {}).get("provider_status", "")),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
