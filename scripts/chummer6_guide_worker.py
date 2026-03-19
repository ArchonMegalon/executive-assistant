#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

from chummer6_guide_canon import load_horizon_canon, load_part_canon
from chummer6_runtime_config import load_local_env, load_runtime_overrides

EA_ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_OUT = Path("/docker/fleet/state/chummer6/ea_overrides.json")
STYLE_EPOCH_PATH = Path("/docker/fleet/state/chummer6/ea_style_epoch.json")
SCENE_LEDGER_PATH = Path("/docker/fleet/state/chummer6/ea_scene_ledger.json")
DEFAULT_MODEL = "ea-groundwork"
WORKING_VARIANT: dict[str, object] | None = None
TEXT_PROVIDER_USED: str = ""
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
        "palette": "petrol cyan, rust amber, wet charcoal",
        "lighting": "practical lamps, sodium spill, rain reflections",
        "realism_mode": "documentary cyberpunk realism",
        "lens_grammar": "35mm and 50mm handheld intimacy",
        "texture_treatment": "fine film grain and scratched hardware surfaces",
        "signage_treatment": "icon-first transit grime and cropped labels",
        "troll_material_style": "worn stickers, scratched pins, faded decals",
        "weather_bias": "rain-biased night exterior or damp interior carry-over",
        "humor_ceiling": "dry and restrained",
    },
    {
        "style_family": "neon_docu_realism",
        "palette": "acid teal, sodium peach, bruise violet",
        "lighting": "thin neon spill over believable practical light",
        "realism_mode": "grounded reportage with sharp subject isolation",
        "lens_grammar": "40mm reportage frames and over-shoulder evidence shots",
        "texture_treatment": "cleaner edges, colder glass, subtle electronic bloom",
        "signage_treatment": "pictograms, lane lights, and half-obscured public markers",
        "troll_material_style": "enamel pins, transit stickers, CRT mascots",
        "weather_bias": "humid night air and reflective surfaces",
        "humor_ceiling": "sarcastic but not showy",
    },
    {
        "style_family": "corp_decay_noir",
        "palette": "dull brass, bruise blue, nicotine parchment",
        "lighting": "sickly office fluorescents cut by harder accent light",
        "realism_mode": "grounded noir with expensive surfaces aging badly",
        "lens_grammar": "50mm still-life and long-lens surveillance peeks",
        "texture_treatment": "paper fibers, wax seals, tape residue, smoked glass",
        "signage_treatment": "approval marks, warnings, and symbol clusters only",
        "troll_material_style": "wax seals, warning placards, coffee-stained coasters",
        "weather_bias": "interior-heavy with storm bleed through windows",
        "humor_ceiling": "meaner and drier",
    },
    {
        "style_family": "industrial_shadowplay",
        "palette": "forge orange, machine green, midnight steel",
        "lighting": "task lamps, monitor glow, and hard industrial spill",
        "realism_mode": "tactile shop-floor realism with cinematic contrast",
        "lens_grammar": "28mm environment frames and close prop clusters",
        "texture_treatment": "grease, powder, heat haze, and metal wear",
        "signage_treatment": "warning icons, hazard bands, stamped surfaces",
        "troll_material_style": "patches, tool decals, hazard stickers",
        "weather_bias": "indoor heat with outdoor rain suggested secondarily",
        "humor_ceiling": "deadpan with sharper roast tolerance",
    },
)
PUBLIC_WRITER_RULES = """Public-writer contract:
- write for a curious player, GM, tester, or supporter
- the reader is not a maintainer and is not expected to fix docs or govern repo hierarchy
- explain what the project means for the reader at the table first
- if the reader can act, route them to the Chummer6 issue tracker, releases, or the owning repos as appropriate
- do not send normal users to chummer6-design to propose features or clean up guide drift
- do not open public pages with repo structure, split mechanics, blueprint talk, or architecture lectures
- never invent or restate canonical mechanics, dice math, thresholds, DV/AP, or stat values unless they come from explicit core receipts
- if a section needs rules truth, point to the core-backed receipt or outcome instead of recomputing mechanics in guide/help/media copy
- use long-range plan instead of blueprint, and only mention code repos when the reader explicitly wants source or implementation detail
- translate any internal term into a table-facing benefit the moment it appears
- glossary terms must be things a player or GM can actually feel at the table
- translate internal jargon immediately or avoid it
- humor should be sparse, dry, and useful; if the joke is not better than clear prose, skip it
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
)
COMPOSITION_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{2,80}$")
TABLEAU_COMPOSITIONS = {"safehouse_table", "group_table"}
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
    for candidate in (raw, raw.removeprefix("```json").removesuffix("```").strip(), raw.removeprefix("```").removesuffix("```").strip()):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        loaded = json.loads(raw[start : end + 1])
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
            rules.append("Safehouse-table grammar is already overserved. Use prop-led, solo-operator, dossier, workshop, transit, street, archive, or service-rack grammar instead.")
    if target.endswith("README.md") or target.endswith("chummer6-hero.png"):
        rules.append("The landing hero must feel like product truth under pressure, not just another meeting shot.")
    if target.endswith("what-chummer6-is.png"):
        rules.append("Prefer over-shoulder receipt proof or a solo trust moment, not a group huddle.")
    if target.endswith("core.png"):
        rules.append("Core should be evidence-first: hands, dice, sheets, traces, and proof beat faces.")
    if target.endswith("horizons-index.png"):
        rules.append("Horizons index must be environment-first boulevard grammar, not an icon wall and not a meeting tableau.")
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
    for source, target in PUBLIC_COPY_REPLACEMENTS:
        if source in lowered:
            cleaned = re.sub(re.escape(source), target, cleaned, flags=re.IGNORECASE)
            lowered = cleaned.lower()
    forbidden = _contains_forbidden_public_copy(cleaned)
    if forbidden and fallback:
        return str(fallback or "").strip()
    if context.startswith("page:") or context.startswith("ooda:"):
        if any(term in original_lowered for term in ARCHITECTURE_HEAVY_TERMS) and fallback:
            return str(fallback or "").strip()
    return cleaned


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
    invalid: list[dict[str, str]] = []

    def audit_row(scope: str, *, target: str, row: object) -> None:
        nonlocal checked, tableau
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
        if not composition:
            return
        checked += 1
        normalized = composition.lower().replace("-", "_")
        if normalized in TABLEAU_COMPOSITIONS:
            tableau += 1
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
        "invalid_compositions": invalid,
    }
    if tableau > 2:
        raise RuntimeError(f"scene_plan_audit_failed:tableau_count:{tableau}")
    if invalid:
        raise RuntimeError(f"scene_plan_audit_failed:invalid_compositions:{invalid[:4]}")
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
GUIDE_ROOT = Path("/docker/chummercomplete/Chummer6")


def guide_excerpt_context_enabled() -> bool:
    raw = str(os.environ.get("CHUMMER6_GUIDE_INCLUDE_EXISTING_EXCERPTS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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


def humanize_text(text: str, *, target: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    if sentence_count(cleaned) < humanizer_min_sentences() or word_count(cleaned) < humanizer_min_words():
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
    external_expected = humanizer_available()
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
            if humanized:
                return humanized
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
            if humanized:
                return humanized
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    if humanizer_required():
        detail = " || ".join(attempted) if attempted else "no_external_humanizer_succeeded"
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

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Requirements:
- `table_scene` must read like a real table moment, not a one-line reminder
- `table_scene` should be 5-9 short lines with speaker labels or obviously playable dialogue beats
- `meanwhile` must be 2-4 bullet lines starting with `- `
- `problem`, `why_great`, and `why_waits` should each be one tight paragraph
- `pitch_line` should invite a better future idea without sounding corporate

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
            "source": str(item.get("source", "")).strip(),
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
            }
        else:
            payload[name] = {
                "title": title,
                "hook": item.get("hook", ""),
                "brutal_truth": item.get("brutal_truth", ""),
                "use_case": item.get("use_case", ""),
                "problem": item.get("problem", ""),
                "foundations": item.get("foundations", []),
                "repos": item.get("repos", []),
                "not_now": item.get("not_now", ""),
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
                "one troll easter egg tucked into the scene",
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
        if not isinstance(row, dict):
            raise ValueError(f"missing section OODA bundle row: {section_type}/{name}")
        normalized[name] = normalize_section_ooda(
            row,
            section_type=section_type,
            name=name,
            item=item,
            global_ooda=global_ooda,
        )
    return normalized


def build_page_prompt(page_id: str, item: dict[str, object], *, global_ooda: dict[str, object] | None = None, section_ooda: dict[str, object] | None = None) -> str:
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
- do not tell the reader to fix docs, correct drift, or maintain the guide hierarchy
- if you recommend a public action, use the Chummer6 issue tracker, releases, or owning repos as appropriate
{PUBLIC_WRITER_RULES}

Page id: {page_id}
Current source:
{item.get("source", "")}

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
            "section_ooda": section_oodas.get(page_id, {}),
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
- do not tell the reader to fix docs, correct drift, or maintain the guide hierarchy
- if you recommend a public action, use the Chummer6 issue tracker, releases, or owning repos as appropriate
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
            "section_ooda": section_oodas.get(name, {}),
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
- make the media scene-first, not icon soup
- no literal on-image text or prompt leakage
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
        horizons_payload[name] = {
            "title": item.get("title", ""),
            "hook": item.get("hook", ""),
            "brutal_truth": item.get("brutal_truth", ""),
            "use_case": item.get("use_case", ""),
            "problem": item.get("problem", ""),
            "foundations": item.get("foundations", []),
            "repos": item.get("repos", []),
            "not_now": item.get("not_now", ""),
            "current_page_excerpt": read_markdown_excerpt(f"HORIZONS/{name}.md", limit=260),
            "section_ooda": section_oodas.get(name, {}),
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
- `table_scene` must be a mini scene, not a one-sentence use-case stub
- `table_scene` should feel like table dialogue, with a GM/player/Chummer rhythm when the concept allows it
- `meanwhile` must be 2-4 bullet lines starting with `- `
- prefer pain -> scene -> invisible system action -> payoff -> realism

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
        assert_public_reader_safe(cleaned, context=f"page:{page_id}")
        normalized[page_id] = cleaned
    return normalized


def normalize_parts_bundle(result: dict[str, object], *, items: dict[str, dict[str, object]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    copy_rows: dict[str, dict[str, str]] = {}
    media_rows: dict[str, dict[str, object]] = {}
    for name, item in items.items():
        row = result.get(name)
        if not isinstance(row, dict):
            raise ValueError(f"missing part bundle row: {name}")
        copy = row.get("copy")
        media = row.get("media")
        if not isinstance(copy, dict) or not isinstance(media, dict):
            raise ValueError(f"invalid part bundle row: {name}")
        cleaned_copy = {
            key: editorial_self_audit_text(
                str(copy.get(key, "")).strip(),
                context=f"part:{name}:{key}",
            )
            for key in ("when", "why", "now")
            if str(copy.get(key, "")).strip()
        }
        if len(cleaned_copy) < 3:
            raise ValueError(f"insufficient part copy: {name}")
        assert_public_reader_safe(cleaned_copy, context=f"part:{name}")
        media_cleaned = normalize_media_override("part", dict(media), item)
        copy_rows[name] = cleaned_copy
        media_rows[name] = media_cleaned
    return copy_rows, media_rows


def normalize_horizons_bundle(result: dict[str, object], *, items: dict[str, dict[str, object]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    copy_rows: dict[str, dict[str, str]] = {}
    media_rows: dict[str, dict[str, object]] = {}
    for name, item in items.items():
        row = result.get(name)
        if not isinstance(row, dict):
            raise ValueError(f"missing horizon bundle row: {name}")
        copy = row.get("copy")
        media = row.get("media")
        if not isinstance(copy, dict) or not isinstance(media, dict):
            raise ValueError(f"invalid horizon bundle row: {name}")
        cleaned_copy = {
            key: editorial_self_audit_text(
                str(copy.get(key, "")).strip(),
                context=f"horizon:{name}:{key}",
            )
            for key in ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line")
            if str(copy.get(key, "")).strip()
        }
        if len(cleaned_copy) < 7:
            raise ValueError(f"insufficient horizon copy: {name}")
        assert_public_reader_safe(cleaned_copy, context=f"horizon:{name}")
        media_cleaned = normalize_media_override("horizon", dict(media), item)
        copy_rows[name] = cleaned_copy
        media_rows[name] = media_cleaned
    return copy_rows, media_rows


AUDITOR_OK_STATUSES = {"ok", "pass", "approved", "clean"}


def _trim_audit_text(text: object, *, limit: int = 320) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(32, limit - 1)].rstrip(" ,;:-") + "…"


def _copy_audit_snapshot(overrides: dict[str, object]) -> dict[str, object]:
    return {
        "pages": {
            page_id: {
                key: _trim_audit_text(value, limit=360)
                for key, value in dict(row).items()
                if isinstance(value, str)
            }
            for page_id, row in dict(overrides.get("pages") or {}).items()
            if isinstance(row, dict)
        },
        "parts": {
            part_id: {
                key: _trim_audit_text(value, limit=240)
                for key, value in dict(row).items()
                if isinstance(value, str)
            }
            for part_id, row in dict(overrides.get("parts") or {}).items()
            if isinstance(row, dict)
        },
        "horizons": {
            horizon_id: {
                key: _trim_audit_text(value, limit=260)
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


SOURCE_SIGNAL_FILES = [
    (("/docker/chummercomplete/chummer6-core/instructions.md", "/docker/chummercomplete/chummer-core-engine/instructions.md"), "core_instructions"),
    (("/docker/chummercomplete/chummer6-core/README.md", "/docker/chummercomplete/chummer-core-engine/README.md"), "core_readme"),
    (
        (
            "/docker/chummercomplete/chummer6-core/test-lua-evaluator.sh",
            "/docker/chummercomplete/chummer-core-engine/test-lua-evaluator.sh",
        ),
        "core_lua_rules",
    ),
    (
        (
            "/docker/chummercomplete/chummer6-core/Chummer.Rulesets.Sr4/Sr4RulesetPlugin.cs",
            "/docker/chummercomplete/chummer-core-engine/Chummer.Rulesets.Sr4/Sr4RulesetPlugin.cs",
        ),
        "core_sr4_plugin",
    ),
    (("/docker/chummercomplete/chummer6-ui/README.md", "/docker/chummercomplete/chummer-presentation/README.md"), "ui_readme"),
    (("/docker/chummercomplete/chummer6-mobile/README.md", "/docker/chummercomplete/chummer-play/README.md"), "play_readme"),
    (("/docker/chummercomplete/chummer6-hub/README.md", "/docker/chummercomplete/chummer.run-services/README.md"), "hub_readme"),
    ("/docker/chummercomplete/chummer-design/products/chummer/README.md", "design_front_door"),
    ("/docker/chummercomplete/chummer-design/products/chummer/ARCHITECTURE.md", "design_architecture"),
    ("/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml", "design_milestones"),
]


def collect_interest_signals() -> dict[str, object]:
    snippets: list[str] = []
    tags: list[str] = []
    for raw_path, label in SOURCE_SIGNAL_FILES:
        if isinstance(raw_path, (list, tuple)):
            candidates = [Path(str(item)) for item in raw_path]
            path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        else:
            path = Path(str(raw_path))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        excerpt = short_sentence(text, limit=220)
        if excerpt:
            snippets.append(f"[{label}] {excerpt}")
        for token, tag in (
            ("sr4", "sr4_support"),
            ("sr5", "sr5_support"),
            ("sr6", "sr6_support"),
            ("shadowrun 4", "sr4_support"),
            ("shadowrun 5", "sr5_support"),
            ("shadowrun 6", "sr6_support"),
            ("lua", "lua_rules"),
            ("scripted rules", "lua_rules"),
            ("rulesetplugin", "multi_era_rulesets"),
            ("offline", "offline_play"),
            ("pwa", "installable_pwa"),
            ("explain", "explain_receipts"),
            ("provenance", "provenance_receipts"),
            ("runtime bundle", "runtime_stacks"),
            ("session event", "session_events"),
            ("local-first", "local_first_play"),
        ):
            if token in lowered and tag not in tags:
                tags.append(tag)
    return {"tags": tags, "snippets": snippets[:6]}


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
        "multi_era_rulesets": "multiple Shadowrun rules eras",
        "sr4_support": "SR4 support is visible in the live code",
        "sr5_support": "SR5 support is visible in the live code",
        "sr6_support": "SR6 support is visible in the live code",
        "lua_rules": "scripted rules can cover ugly edge cases",
        "offline_play": "offline-safe play matters",
        "installable_pwa": "installable play surfaces exist",
        "explain_receipts": "the math should explain itself",
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


def _global_ooda_defaults(signals: dict[str, object]) -> dict[str, object]:
    tags = [str(tag).strip() for tag in signals.get("tags", []) if str(tag).strip()]
    highlights = _interest_signals_from_tags(tags)
    return {
        "observe": {
            "source_signal_tags": tags or ["chummer6"],
            "source_excerpt_labels": _excerpt_labels(signals) or ["core_readme", "ui_readme", "play_readme"],
            "audience_needs": [
                "what this does for a real table",
                "why the math is worth trusting",
                "where the project is actually heading",
            ],
            "user_interest_signals": highlights
            or [
                "readable receipts instead of mystery math",
                "offline-safe local-first play",
                "multi-era and scripted-rules flexibility",
            ],
            "risks": [
                "sliding back into repo-topology talk",
                "template-shaped copy",
                "generic cyberpunk wallpaper instead of scenes",
            ],
        },
        "orient": {
            "audience": "players, GMs, and curious tinkerers who want Chummer6 explained from the table inward",
            "promise": "clear Shadowrun rules truth with receipts, local-first play, and fewer arguments about what just happened",
            "tension": "the project is getting larger and more specialized, so the guide has to stay human before it starts sounding architectural",
            "why_care": [
                "faster rulings under pressure",
                "less trust-me math",
                "a clearer path from prep to live play",
            ],
            "current_focus": [
                "trustworthy rules behavior",
                "honest public surfaces",
                "future ideas that feel like table upgrades instead of slideware",
            ],
            "visual_direction": "grounded cyberpunk scenes, readable props, lived table moments, and one sly troll reference per image",
            "humor_line": "If the dev says this is a tiny cleanup pass, hide the accelerants.",
            "signals_to_highlight": highlights
            or [
                "multi-era support",
                "scripted rules for edge cases",
                "receipts and provenance",
                "local-first session resilience",
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
            "information_order": "lead with table value, then product promise, then current truth, then the map of parts and futures",
            "tone_rules": "keep it human, concrete, slightly sarcastic, and allergic to architecture sermons",
            "horizon_policy": "sell each horizon as a table pain and a vivid scene, not a codename first",
            "media_strategy": "use contextual scenes that show the moment the feature matters, not abstract title-card art",
            "overlay_policy": "only use overlays that clarify initiative, receipts, sync state, provenance, or simulation context",
            "cta_strategy": "invite readers to test, watch, or pitch better ideas without sounding like a growth funnel with a knife",
        },
        "act": {
            "landing_tagline": "Shadowrun rules truth, with receipts.",
            "landing_intro": "Chummer6 is trying to make Shadowrun rulings faster, clearer, and easier to trust when the table is loud and the stakes are dumb.",
            "what_it_is": "This guide is the human-facing front door to what Chummer6 is becoming: a more explainable, local-first, multi-era Shadowrun toolkit that does not ask you to trust mystery math.",
            "watch_intro": "If you care about receipts, recoverable sessions, and future tools that feel useful instead of decorative, this is the version worth watching.",
            "horizon_intro": "Horizons are future troublemakers: ideas for where the project could get delightfully more dangerous once the boring foundations stop wobbling.",
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
        observe[key] = cleaned

    orient: dict[str, object] = {}
    for key in ("audience", "promise", "tension", "visual_direction", "humor_line"):
        value = str(raw_orient.get(key, "")).strip() if isinstance(raw_orient, dict) else ""
        if not value:
            value = str(defaults["orient"].get(key, "")).strip()
        orient[key] = editorial_self_audit_text(value, fallback=str(defaults["orient"].get(key, "")).strip(), context=f"ooda:orient:{key}")
    for key in ("why_care", "current_focus", "signals_to_highlight", "banned_terms"):
        raw = raw_orient.get(key) if isinstance(raw_orient, dict) else None
        cleaned = _listish(raw)
        if not cleaned:
            cleaned = _listish(defaults["orient"].get(key))
        orient[key] = [
            editorial_self_audit_text(
                entry,
                fallback=str(fallback).strip(),
                context=f"ooda:orient:{key}",
            )
            for entry, fallback in zip(cleaned, _listish(defaults["orient"].get(key)) + cleaned)
        ]

    decide: dict[str, object] = {}
    for key in ("information_order", "tone_rules", "horizon_policy", "media_strategy", "overlay_policy", "cta_strategy"):
        value = str(raw_decide.get(key, "")).strip() if isinstance(raw_decide, dict) else ""
        if not value:
            value = str(defaults["decide"].get(key, "")).strip()
        decide[key] = editorial_self_audit_text(value, fallback=str(defaults["decide"].get(key, "")).strip(), context=f"ooda:decide:{key}")

    act: dict[str, object] = {}
    for key in ("landing_tagline", "landing_intro", "what_it_is", "watch_intro", "horizon_intro"):
        value = str(raw_act.get(key, "")).strip() if isinstance(raw_act, dict) else ""
        if not value:
            value = str(defaults["act"].get(key, "")).strip()
        act[key] = editorial_self_audit_text(value, fallback=str(defaults["act"].get(key, "")).strip(), context=f"ooda:act:{key}")

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
- dry humor is allowed when it makes the point clearer
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
- visual_prompt must describe an actual cyberpunk scene, not a brochure cover
- visual_prompt must center one memorable focal subject, setup, or action instead of generic poster collage
- if the section implies a person or team, choose a believable protagonist instead of abstract symbols
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, or crash-test simulation, make that metaphor visibly legible in-scene
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible badge/title/subtitle/kicker/note should feel like guide copy, not compliance language
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
- avoid repeating a recently accepted composition family when a different scene family would work
- if the landing truth can be shown with one operator, one prop cluster, one transit lane, or one over-shoulder proof moment, prefer that over a group huddle
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
- scene_contract.subject should name the focal subject in plain language
- scene_contract.metaphor should name the strongest visual metaphor if one exists
- scene_contract.props should be a short list of concrete visible things
- scene_contract.overlays should be a short list of diegetic overlay ideas
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
- dry humor is allowed when it makes the point clearer
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
- visual_prompt must describe an actual cyberpunk scene tied to this part in use
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the part naturally implies a person or team, choose believable cyberpunk people
- if the part naturally implies a machine room, archive, workshop, or table scene, make that spatial metaphor visibly legible
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
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
- dry humor is allowed when it makes the point clearer
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
- visual_prompt must describe an actual cyberpunk scene tied to this horizon
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the section naturally implies a person, make that person specific and believable
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, web, or blackbox, make that metaphor visibly legible in-scene
- if the title reads like a personal codename, make the focal subject feel like that codename embodied; if it reads like a feminine personal name, it is fine to make the focal subject a woman
- if the metaphor is x-ray or simulation, show a real body, runner, or situation with the metaphor happening to it; do not collapse into abstract boxes and HUD wallpaper
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible copy should sell the horizon without pretending it is active build work
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
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
- if the title reads like a codename or person, make scene_contract.subject a believable cyberpunk person, not a generic skyline or dashboard
- if the metaphor is x-ray / dossier / forge / ghost / heat web / mirror / passport / blackbox / simulation, make scene_contract.metaphor explicit

Return valid JSON only.
"""


def normalize_media_override(kind: str, cleaned: dict[str, object], item: dict[str, object]) -> dict[str, object]:
    def infer_scene_contract(*, asset_key: str, visual_prompt: str) -> dict[str, object]:
        lowered = visual_prompt.lower()
        subject = "a cyberpunk protagonist"
        if "team" in lowered or "group" in lowered:
            subject = "a runner team at a live table"
        elif "receipt" in lowered or "dice" in lowered or "sheet" in lowered or "table" in lowered:
            subject = "one operator, one receipt trail, and the props proving the point"
        elif "girl" in lowered or "woman" in lowered or asset_key == "alice":
            subject = "a cyberpunk woman"
        elif "troll" in lowered or "forge" in lowered or asset_key == "karma-forge":
            subject = "a cybernetic troll"
        environment = "a dangerous but inviting cyberpunk scene"
        if "archive" in lowered or "blueprint" in lowered:
            environment = "a blueprint room lit by cold neon"
        elif "workshop" in lowered or "foundation" in lowered:
            environment = "a cyberpunk workshop with exposed internals"
        elif "street" in lowered or "preview" in lowered:
            environment = "a rainy neon street front"
        action = "framing the next move before the chrome starts smoking"
        if "x-ray" in lowered or "xray" in lowered:
            action = "pulling a glowing x-ray of cause and effect through the air"
        elif "simulation" in lowered or "branch" in lowered:
            action = "walking through branching combat outcomes"
        elif "dossier" in lowered or "evidence" in lowered:
            action = "sorting a hot dossier and live evidence threads"
        elif "forge" in lowered:
            action = "hammering volatile rules into controlled shape"
        metaphor = "scene-aware cyberpunk guide art"
        for token, label in (
            ("x-ray", "x-ray causality scan"),
            ("xray", "x-ray causality scan"),
            ("simulation", "branching simulation grid"),
            ("ghost", "forensic replay echoes"),
            ("dossier", "dossier evidence wall"),
            ("forge", "forge sparks and molten rules"),
            ("network", "living consequence web"),
            ("passport", "passport gate"),
            ("mirror", "mirror split"),
            ("blackbox", "blackbox loadout check"),
        ):
            if token in lowered or token in asset_key:
                metaphor = label
                break
        composition = "single_protagonist"
        if "boulevard" in lowered or "district" in lowered or "signpost" in lowered:
            composition = "horizon_boulevard"
        elif "over-shoulder" in lowered or "receipt" in lowered or "modifier" in lowered or "dice" in lowered:
            composition = "over_shoulder_receipt"
        elif "service rack" in lowered or "rack" in lowered or "control surface" in lowered:
            composition = "service_rack"
        elif "transit" in lowered or "checkpoint" in lowered or "route board" in lowered or "station" in lowered:
            composition = "transit_checkpoint"
        elif "workshop bench" in lowered or "forge" in lowered or "anvil" in lowered:
            composition = "workshop_bench"
        elif "operator" in lowered or "solo" in lowered or "kiosk" in lowered:
            composition = "solo_operator"
        elif "team" in lowered or "group" in lowered:
            composition = "group_table"
        elif "dossier" in lowered or "blackbox" in lowered:
            composition = "desk_still_life"
        elif "horizon" in lowered or asset_key in {"horizons-index", "hero"}:
            composition = "city_edge"
        palette = "cyan-magenta neon"
        mood = "dangerous, curious, and slightly amused"
        humor = "dry roast energy without clown mode"
        props = [
            "wet chrome",
            "holographic receipts",
            "rain haze",
        ]
        overlays = [
            "diegetic HUD traces",
            "receipt markers",
            "signal arcs",
        ]
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
        if not isinstance(raw, dict):
            return default
        contract: dict[str, object] = dict(default)
        for key in ("subject", "environment", "action", "metaphor", "palette", "mood", "humor"):
            value = str(raw.get(key, "")).strip()
            if value:
                contract[key] = value
        composition_raw = str(raw.get("composition", "")).strip()
        if composition_raw and COMPOSITION_SLUG_RE.fullmatch(composition_raw):
            contract["composition"] = composition_raw.lower().replace("-", "_")
        for key in ("props", "overlays"):
            value = raw.get(key)
            if isinstance(value, list):
                cleaned_values = [str(entry).strip() for entry in value if str(entry).strip()]
                if cleaned_values:
                    contract[key] = cleaned_values[:6]
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
        motifs: list[str] = []
        for key in ("subject", "environment", "action", "metaphor"):
            value = str(scene_contract.get(key, "")).strip()
            if value:
                motifs.append(value)
        for key in ("props", "overlays"):
            value = scene_contract.get(key)
            if isinstance(value, list):
                motifs.extend(str(entry).strip() for entry in value if str(entry).strip())
        for candidate in (
            overlay_hint,
            f"{item_title} scene",
            "subtle troll easter egg",
            f"{asset_key} context",
        ):
            cleaned_candidate = str(candidate or "").strip()
            if cleaned_candidate:
                motifs.append(cleaned_candidate)
        deduped: list[str] = []
        seen: set[str] = set()
        for motif in motifs:
            key = motif.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(motif)
            if len(deduped) >= 6:
                break
        return deduped or ["contextual scene", "subtle troll easter egg", "diegetic overlays"]

    def infer_overlay_callouts(*, scene_contract: dict[str, object], overlay_hint: str) -> list[str]:
        callouts: list[str] = []
        for entry in scene_contract.get("overlays", []):
            cleaned_entry = str(entry).strip()
            if cleaned_entry:
                callouts.append(cleaned_entry)
        if overlay_hint.strip():
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
        return deduped or ["diegetic HUD traces", "receipt markers"]

    normalized = dict(cleaned)
    if kind == "hero":
        for field in ("badge", "title", "subtitle", "kicker", "note", "overlay_hint", "visual_prompt"):
            value = str(normalized.get(field, "")).strip()
            if not value:
                raise ValueError(f"hero media field is missing: {field}")
            normalized[field] = value
        normalized["meta"] = str(normalized.get("meta", "")).strip()
        normalized["scene_contract"] = normalize_scene_contract(
            normalized.get("scene_contract"),
            asset_key="hero",
            visual_prompt=str(normalized["visual_prompt"]),
        )
        raw_motifs = normalized.get("visual_motifs")
        motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()] if isinstance(raw_motifs, list) else []
        normalized["visual_motifs"] = motifs or infer_visual_motifs(
            asset_key="hero",
            scene_contract=normalized["scene_contract"],
            overlay_hint=str(normalized["overlay_hint"]),
            item_title="hero",
        )
        raw_callouts = normalized.get("overlay_callouts")
        callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()] if isinstance(raw_callouts, list) else []
        normalized["overlay_callouts"] = callouts or infer_overlay_callouts(
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
    normalized["scene_contract"] = normalize_scene_contract(
        normalized.get("scene_contract"),
        asset_key=item.get("slug", item.get("title", "horizon")),
        visual_prompt=str(normalized["visual_prompt"]),
    )
    raw_motifs = normalized.get("visual_motifs")
    motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()] if isinstance(raw_motifs, list) else []
    normalized["visual_motifs"] = motifs or infer_visual_motifs(
        asset_key=str(item.get("slug", item.get("title", "horizon"))),
        scene_contract=normalized["scene_contract"],
        overlay_hint=str(normalized["overlay_hint"]),
        item_title=str(item.get("title", item.get("slug", "horizon"))),
    )
    raw_callouts = normalized.get("overlay_callouts")
    callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()] if isinstance(raw_callouts, list) else []
    normalized["overlay_callouts"] = callouts or infer_overlay_callouts(
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
        "source": "Explain what Chummer6 is becoming for players and GMs, why it matters at the table, and what feels different from older opaque tools. Keep repo and architecture talk below the product story.",
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

def chunk_mapping(mapping: dict[str, object], *, size: int) -> list[dict[str, object]]:
    items = list(mapping.items())
    return [dict(items[index : index + size]) for index in range(0, len(items), size)]


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


def generate_overrides(*, include_parts: bool, include_horizons: bool, model: str) -> dict[str, object]:
    global TEXT_PROVIDER_USED
    TEXT_PROVIDER_USED = ""
    signals = collect_interest_signals()
    style_epoch = resolve_style_epoch(increment=include_parts and include_horizons)
    recent_scenes = scene_ledger_summary(recent_scene_rows())
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
    try:
        ooda_result = chat_json(build_ooda_prompt(signals), model=model, skill_key=PUBLIC_WRITER_SKILL_KEY)
        overrides["ooda"] = normalize_ooda(ooda_result, signals)
    except Exception as exc:
        raise RuntimeError(f"global OODA generation failed: {exc}") from exc
    ooda = dict(overrides.get("ooda") or {})
    if isinstance(ooda.get("act"), dict):
        humanize_mapping_fields(
            ooda["act"],
            ("landing_intro", "what_it_is", "watch_intro", "horizon_intro"),
            target_prefix="guide:ooda:act",
        )
    try:
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
        result = chat_json(
            build_media_prompt(
                "hero",
                "hero",
                {},
                ooda=ooda,
                section_ooda=hero_ooda,
                style_epoch=style_epoch,
                recent_scenes=recent_scenes,
                variation_guardrails=variation_guardrails_for("assets/hero/chummer6-hero.png", recent_scene_rows()),
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
    for batch in chunk_mapping(PAGE_PROMPTS, size=section_batch_size("page", len(PAGE_PROMPTS))):
        try:
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
    for batch in chunk_mapping(PAGE_PROMPTS, size=section_batch_size("page", len(PAGE_PROMPTS))):
        try:
            page_bundle = chat_json(
                build_pages_bundle_prompt(
                    items=batch,
                    global_ooda=ooda,
                    section_oodas={name: page_oodas[name] for name in batch.keys()},
                ),
                model=model,
                skill_key=PUBLIC_WRITER_SKILL_KEY,
            )
            page_rows.update(normalize_pages_bundle(page_bundle, items=batch))
        except Exception as exc:
            raise RuntimeError(f"page copy bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
    for page_id, row in page_rows.items():
        humanize_mapping_fields(row, ("intro", "body", "kicker"), target_prefix=f"guide:page:{page_id}")
    overrides["pages"] = page_rows
    if include_parts:
        part_oodas: dict[str, object] = {}
        for batch in chunk_mapping(PARTS, size=section_batch_size("part", len(PARTS))):
            try:
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
        for name, item in PARTS.items():
            try:
                copy_row = chat_json(
                    build_part_prompt(
                        name,
                        item,
                        ooda=ooda,
                        section_ooda=part_oodas[name],
                    ),
                    model=model,
                    skill_key=PUBLIC_WRITER_SKILL_KEY,
                )
                cleaned_copy = {
                    key: str(copy_row.get(key, "")).strip()
                    for key in ("when", "why", "now")
                    if str(copy_row.get(key, "")).strip()
                }
                if len(cleaned_copy) < 3:
                    raise ValueError(f"insufficient part copy: {name}")
                assert_public_reader_safe(cleaned_copy, context=f"part:{name}")
                media_row = chat_json(
                    build_media_prompt(
                        "part",
                        name,
                        item,
                        ooda=ooda,
                        section_ooda=part_oodas[name],
                        style_epoch=style_epoch,
                        recent_scenes=recent_scenes,
                        variation_guardrails=variation_guardrails_for(f"assets/parts/{name}.png", recent_scene_rows()),
                    ),
                    model=model,
                    skill_key=VISUAL_DIRECTOR_SKILL_KEY,
                )
                part_copy_rows[name] = cleaned_copy
                part_media_rows[name] = normalize_media_override("part", dict(media_row), item)
            except Exception as exc:
                raise RuntimeError(f"part copy/media generation failed ({name}): {exc}") from exc
        for part_id, row in part_copy_rows.items():
            humanize_mapping_fields(row, ("when", "why", "now"), target_prefix=f"guide:part:{part_id}")
        overrides["parts"] = part_copy_rows
        overrides["media"]["parts"] = part_media_rows
    if include_horizons:
        horizon_oodas: dict[str, object] = {}
        for batch in chunk_mapping(HORIZONS, size=section_batch_size("horizon", len(HORIZONS))):
            try:
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
        for name, item in HORIZONS.items():
            try:
                copy_row = chat_json(
                    build_horizon_prompt(
                        name,
                        item,
                        ooda=ooda,
                        section_ooda=horizon_oodas[name],
                    ),
                    model=model,
                    skill_key=PUBLIC_WRITER_SKILL_KEY,
                )
                cleaned_copy = {
                    key: str(copy_row.get(key, "")).strip()
                    for key in ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line")
                    if str(copy_row.get(key, "")).strip()
                }
                if len(cleaned_copy) < 7:
                    raise ValueError(f"insufficient horizon copy: {name}")
                assert_public_reader_safe(cleaned_copy, context=f"horizon:{name}")
                media_row = chat_json(
                    build_media_prompt(
                        "horizon",
                        name,
                        item,
                        ooda=ooda,
                        section_ooda=horizon_oodas[name],
                        style_epoch=style_epoch,
                        recent_scenes=recent_scenes,
                        variation_guardrails=variation_guardrails_for(f"assets/horizons/{name}.png", recent_scene_rows()),
                    ),
                    model=model,
                    skill_key=VISUAL_DIRECTOR_SKILL_KEY,
                )
                horizon_copy_rows[name] = cleaned_copy
                horizon_media_rows[name] = normalize_media_override("horizon", dict(media_row), item)
            except Exception as exc:
                raise RuntimeError(f"horizon copy/media generation failed ({name}): {exc}") from exc
        for horizon_id, row in horizon_copy_rows.items():
            humanize_mapping_fields(
                row,
                ("hook", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line"),
                target_prefix=f"guide:horizon:{horizon_id}",
            )
        overrides["horizons"] = horizon_copy_rows
        overrides["media"]["horizons"] = horizon_media_rows
    overrides["meta"]["public_skill_audit"] = run_skill_audit(
        label="public",
        skill_key=PUBLIC_AUDITOR_SKILL_KEY,
        focus="Check reader usefulness, CTA routing, public-safe language, and whether the copy still sounds like a human guide instead of internal coordination notes.",
        payload=_copy_audit_snapshot(overrides),
        model=model,
    )
    overrides["meta"]["scene_skill_audit"] = run_skill_audit(
        label="scene",
        skill_key=SCENE_AUDITOR_SKILL_KEY,
        focus="Check composition diversity, page-role fit, and whether scene contracts still collapse into repetitive tableaus or generic cyberpunk wallpaper.",
        payload=_scene_audit_snapshot(overrides),
        model=model,
    )
    overrides["meta"]["visual_skill_audit"] = run_skill_audit(
        label="visual",
        skill_key=VISUAL_AUDITOR_SKILL_KEY,
        focus="Check whether the visible media metadata feels specific, premium, and non-repetitive enough for a public guide pack.",
        payload=_visual_audit_snapshot(overrides),
        model=model,
    )
    overrides["meta"]["pack_skill_audit"] = run_skill_audit(
        label="pack",
        skill_key=PACK_AUDITOR_SKILL_KEY,
        focus="Check overall pack coherence: public usefulness, visual consistency, and whether the whole set feels ready to publish for real users.",
        payload=_pack_audit_snapshot(overrides),
        model=model,
    )
    overrides["meta"]["scene_plan_audit"] = scene_plan_pack_audit(overrides)
    overrides["meta"]["editorial_audit"] = editorial_pack_audit(overrides)
    overrides["meta"]["provider"] = TEXT_PROVIDER_USED or "unknown"
    overrides["meta"]["provider_status"] = "ok"
    overrides["meta"]["provider_error"] = provider_error
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chummer6 downstream guide overrides through EA using section-level OODA.")
    parser.add_argument("--output", default=str(OVERRIDE_OUT), help="Where to write the override JSON.")
    parser.add_argument("--model", default=default_text_model(), help="Preferred EA/Gemini text model hint.")
    parser.add_argument("--parts-only", action="store_true", help="Generate part-page overrides only.")
    parser.add_argument("--horizons-only", action="store_true", help="Generate horizon-page overrides only.")
    args = parser.parse_args()

    include_parts = not args.horizons_only
    include_horizons = not args.parts_only
    overrides = generate_overrides(
        include_parts=include_parts,
        include_horizons=include_horizons,
        model=str(args.model or default_text_model()).strip() or default_text_model(),
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
