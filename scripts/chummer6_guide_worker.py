#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
FLEET_GUIDE_SCRIPT = Path("/docker/fleet/scripts/finish_chummer6_guide.py")
OVERRIDE_OUT = Path("/docker/fleet/state/chummer6/ea_overrides.json")
DEFAULT_MODEL = "gpt-4o-mini"
FALLBACK_MODELS = (
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
)
WORKING_VARIANT: dict[str, object] | None = None


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


def resolve_onemin_keys() -> list[str]:
    output = subprocess.check_output(
        ["bash", str(EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh"), "--all"],
        text=True,
    )
    keys: list[str] = []
    seen: set[str] = set()
    for raw in output.splitlines():
        key = raw.strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    if not keys:
        raise RuntimeError("no 1min.AI key configured")
    return keys


def load_literal(name: str) -> dict[str, object]:
    module = ast.parse(FLEET_GUIDE_SCRIPT.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = ast.literal_eval(node.value)
                if isinstance(value, dict):
                    return value
    raise RuntimeError(f"missing literal {name} in {FLEET_GUIDE_SCRIPT}")


PARTS = load_literal("PARTS")
HORIZONS = load_literal("HORIZONS")
GUIDE_ROOT = Path("/docker/chummercomplete/Chummer6")


def read_markdown_excerpt(relative_path: str, *, limit: int = 900) -> str:
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


def model_candidates(requested: str) -> list[str]:
    preferred = str(requested or "").strip() or DEFAULT_MODEL
    ordered = [preferred, *FALLBACK_MODELS]
    seen: set[str] = set()
    models: list[str] = []
    for model in ordered:
        candidate = str(model or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            models.append(candidate)
    return models


def request_variants(prompt: str, *, model: str, api_key: str) -> list[tuple[str, dict[str, str], dict[str, object]]]:
    prompt_object_variants = [
        {"prompt": prompt},
        {"messages": [{"role": "user", "content": prompt}]},
        {"prompt": prompt, "messages": [{"role": "user", "content": prompt}]},
    ]
    type_variants = [
        ("https://api.1min.ai/api/chat-with-ai", "UNIFY_CHAT_WITH_AI"),
        ("https://api.1min.ai/api/features", "UNIFY_CHAT_WITH_AI"),
        ("https://api.1min.ai/api/chat-with-ai", "CHAT_WITH_AI"),
        ("https://api.1min.ai/api/features", "CHAT_WITH_AI"),
    ]
    header_variants = [
        {"Content-Type": "application/json", "API-KEY": api_key},
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        {"Content-Type": "application/json", "X-API-KEY": api_key},
    ]
    variants: list[tuple[str, dict[str, str], dict[str, object]]] = []
    for url, request_type in type_variants:
        for prompt_object in prompt_object_variants:
            payload = {
                "type": request_type,
                "model": model,
                "promptObject": prompt_object,
            }
            for headers in header_variants:
                variants.append((url, headers, payload))
    return variants


def extract_response_json(body: dict[str, object]) -> dict[str, object]:
    candidates: list[object] = []
    ai_record = body.get("aiRecord") if isinstance(body, dict) else None
    if isinstance(ai_record, dict):
        details = ai_record.get("aiRecordDetail")
        if isinstance(details, dict):
            candidates.extend((details.get("resultObject") or []))
        candidates.append(ai_record.get("result"))
    candidates.extend(
        [
            body.get("resultObject") if isinstance(body, dict) else None,
            body.get("result") if isinstance(body, dict) else None,
            body.get("message") if isinstance(body, dict) else None,
            ((body.get("choices") or [{}])[0] if isinstance(body, dict) else {}).get("message", {}).get("content"),
            ((body.get("data") or [{}])[0] if isinstance(body, dict) else {}).get("content"),
        ]
    )
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, list):
            for row in candidate:
                if row is None:
                    continue
                try:
                    return extract_json(str(row))
                except Exception:
                    continue
            continue
        try:
            return extract_json(str(candidate))
        except Exception:
            continue
    raise RuntimeError("1min.AI returned no parseable JSON payload")


def chat_json(prompt: str, *, model: str = DEFAULT_MODEL) -> dict[str, object]:
    global WORKING_VARIANT
    errors: list[str] = []
    keys = resolve_onemin_keys()
    models = model_candidates(model)
    for api_key in keys:
        key_mask = f"{api_key[:6]}…{api_key[-4:]}" if len(api_key) > 10 else "***"
        for candidate_model in models:
            variants = request_variants(prompt, model=candidate_model, api_key=api_key)
            if WORKING_VARIANT:
                variants = [tuple(WORKING_VARIANT.values())] + variants
            seen: set[str] = set()
            deduped: list[tuple[str, dict[str, str], dict[str, object]]] = []
            for url, headers, payload in variants:
                identity = json.dumps([url, headers, payload], sort_keys=True)
                if identity in seen:
                    continue
                seen.add(identity)
                deduped.append((url, headers, payload))
            for url, headers, payload in deduped:
                request = urllib.request.Request(
                    url,
                    headers=headers,
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=180) as response:
                        body = json.loads(response.read().decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace").strip()
                    errors.append(
                        f"{exc.code} model={candidate_model} key={key_mask} url={url} auth={','.join(headers.keys())} body={body[:240]}"
                    )
                    continue
                except urllib.error.URLError as exc:
                    errors.append(f"urlerror model={candidate_model} key={key_mask} url={url} reason={exc.reason}")
                    continue
                WORKING_VARIANT = {
                    "url": url,
                    "headers": headers,
                    "payload": payload,
                }
                return extract_response_json(body)
    raise RuntimeError("1min.AI request failed; " + " || ".join(errors[:8]))


def build_part_prompt(name: str, item: dict[str, object], ooda: dict[str, object] | None = None) -> str:
    owns = "\n".join(f"- {line}" for line in item.get("owns", []))
    not_owns = "\n".join(f"- {line}" for line in item.get("not_owns", []))
    return f"""You are writing downstream-only copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys intro, why, now.

Voice rules:
- clear, slightly playful, Shadowrun-flavored
- plain language first
- SR jargon is welcome
- mild dev roasting is allowed
- no mention of Fleet
- no mention of chummer5a
- no control-plane jargon
- no markdown fences

Part id: {name}
Title: {item.get("title", "")}
Tagline: {item.get("tagline", "")}
Current intro:
{item.get("intro", "")}

Why it matters:
{item.get("why", "")}

What it owns:
{owns}

What it does not own:
{not_owns}

Current now-text:
{item.get("now", "")}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def build_horizon_prompt(name: str, item: dict[str, object], ooda: dict[str, object] | None = None) -> str:
    foundations = "\n".join(f"- {line}" for line in item.get("foundations", []))
    repos = ", ".join(str(repo) for repo in item.get("repos", []))
    return f"""You are writing downstream-only horizon copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys hook, brutal_truth, use_case.

Voice rules:
- sell the idea harder
- clear, punchy, Shadowrun-flavored
- SR jargon is welcome
- mild dev roasting is allowed
- keep it exciting without pretending it is active work
- no mention of Fleet
- no mention of chummer5a
- no markdown fences

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

Foundations:
{foundations}

Touched repos later:
{repos}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


SOURCE_SIGNAL_FILES = [
    ("/docker/chummercomplete/chummer-core-engine/instructions.md", "core_instructions"),
    ("/docker/chummercomplete/chummer-core-engine/README.md", "core_readme"),
    ("/docker/chummercomplete/chummer-presentation/README.md", "ui_readme"),
    ("/docker/chummercomplete/chummer-play/README.md", "play_readme"),
    ("/docker/chummercomplete/chummer.run-services/README.md", "hub_readme"),
    ("/docker/chummercomplete/chummer-design/products/chummer/README.md", "design_front_door"),
    ("/docker/chummercomplete/chummer-design/products/chummer/ARCHITECTURE.md", "design_architecture"),
    ("/docker/chummercomplete/chummer-design/products/chummer/PROGRAM_MILESTONES.yaml", "design_milestones"),
]


def collect_interest_signals() -> dict[str, object]:
    snippets: list[str] = []
    tags: list[str] = []
    for path_text, label in SOURCE_SIGNAL_FILES:
        path = Path(path_text)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        excerpt = " ".join(text.split())[:900]
        if excerpt:
            snippets.append(f"[{label}] {excerpt}")
        for token, tag in (
            ("lua", "lua_scripted_rules"),
            ("script pack", "lua_scripted_rules"),
            ("sr4", "sr4_support"),
            ("sr5", "sr5_support"),
            ("sr6", "sr6_support"),
            ("shadowrun 4", "sr4_support"),
            ("shadowrun 5", "sr5_support"),
            ("shadowrun 6", "sr6_support"),
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
    return {"tags": tags, "snippets": snippets[:10]}


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
- light dev roasting is allowed
- focus on what a curious human would actually care about first
- if the source suggests strong user-facing selling points like Lua-scripted rules or SR4/SR5/SR6 support, surface them
- no mention of Fleet
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
- what_it_is should explain the repo in plain language
- watch_intro should tee up why the project is worth following
- horizon_intro should tee up the future ideas in a fun way without pretending they are active work

Observed tags:
{tags}

Observed source excerpts:
{source_excerpt}

Return valid JSON only.
"""


def fallback_ooda(signals: dict[str, object]) -> dict[str, object]:
    tags = [str(tag) for tag in signals.get("tags", []) if str(tag).strip()]
    highlights: list[str] = []
    if "lua_scripted_rules" in tags:
        highlights.append("Lua-scripted rules make Chummer more moddable without turning every table into a code fork.")
    sr_tags = [tag for tag in tags if tag in {"sr4_support", "sr5_support", "sr6_support"}]
    if sr_tags:
        highlights.append("The project is aiming to support Shadowrun 4, 5, and 6 instead of pretending the Sixth World started yesterday.")
    if "local_first_play" in tags or "offline_play" in tags:
        highlights.append("Play is being built local-first, so the table does not fall apart the moment the network gets cute.")
    if "explain_receipts" in tags or "provenance_receipts" in tags:
        highlights.append("Explain and provenance work means the machine should eventually be able to show its receipts instead of shrugging at your dice pool.")
    if "runtime_stacks" in tags:
        highlights.append("Runtime stacks and overlays are the future power-up path, but only after the foundations stop wobbling.")
    if not highlights:
        highlights.append("Chummer is growing into a sharper multi-repo ecosystem instead of staying one haunted toolbox.")
    return {
        "observe": {
            "source_signal_tags": tags,
            "source_excerpt_labels": [f"signal:{tag}" for tag in tags[:6]],
            "audience_needs": [
                "understand the project fast",
                "spot what is actually cool",
                "avoid internal control-plane jargon",
            ],
            "user_interest_signals": highlights,
            "risks": [
                "the guide can slide into compliance-speak",
                "future ideas can sound dispatchable if not framed carefully",
            ],
        },
        "orient": {
            "audience": "curious chummers, skeptical testers, and people trying to figure out why this split matters",
            "promise": "Chummer6 should make the project feel exciting, legible, and worth following without making readers wade through internal machinery.",
            "tension": "The future is exciting, but the current job is still foundations, cleanup, and making the split real.",
            "why_care": highlights[:4],
            "current_focus": [
                "clean up the shared rules and interfaces",
                "finish the play/session boundary",
                "make the UI kit, registry, and media seams real",
            ],
            "visual_direction": "street-level cyberpunk, dangerous but inviting, analytical overlays, dark humor, no brochure energy",
            "humor_line": "Give the dev a little heat when deserved, but keep the guide readable for actual humans.",
            "signals_to_highlight": highlights,
            "banned_terms": ["Fleet", "mission control", "contract plane", "preview debt"],
        },
        "decide": {
            "information_order": "lead with hook, usefulness, and current shape before disclaimers or governance caveats",
            "tone_rules": "plain language first, a little SR swagger, mild dev roasting, zero corp-compliance voice",
            "horizon_policy": "sell the horizon as a cool future lane, but keep it clearly non-dispatchable",
            "media_strategy": "show scene-first cyberpunk art with meaningful HUD overlays driven by user-interest signals, not literal repo-role labels",
            "overlay_policy": "use overlay callouts for selling points like Lua rules, SR4-SR6 support, explain receipts, and local-first play",
            "cta_strategy": "invite curious test dummies, bug reports, stars, and laughter without sounding needy or sketchy",
        },
        "act": {
            "landing_tagline": "Same shadows. Bigger future. Less confusion.",
            "landing_intro": "Chummer6 is the readable guide to the next Chummer: what it is becoming, how the parts fit together, what is happening right now, and which future ideas are still parked in the garage.",
            "what_it_is": "Chummer6 is the friendly guide to the next Chummer, built for curious chummers who want the lay of the land without spelunking through every repo.",
            "watch_intro": "People who care about Shadowrun tools should probably care because:",
            "horizon_intro": "Some ideas are too fun not to document. They are real possibilities, but they are not active build commitments.",
        },
    }


def normalize_ooda(result: dict[str, object], signals: dict[str, object]) -> dict[str, object]:
    fallback = fallback_ooda(signals)
    normalized: dict[str, object] = {}
    raw_observe = result.get("observe") if isinstance(result.get("observe"), dict) else {}
    raw_orient = result.get("orient") if isinstance(result.get("orient"), dict) else result
    raw_decide = result.get("decide") if isinstance(result.get("decide"), dict) else {}
    raw_act = result.get("act") if isinstance(result.get("act"), dict) else result

    observe: dict[str, object] = {}
    for key in ("source_signal_tags", "source_excerpt_labels", "audience_needs", "user_interest_signals", "risks"):
        raw = raw_observe.get(key) if isinstance(raw_observe, dict) else None
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
        else:
            cleaned = []
        observe[key] = cleaned or list((fallback.get("observe") or {}).get(key, []))

    orient: dict[str, object] = {}
    for key in ("audience", "promise", "tension", "visual_direction", "humor_line"):
        value = str(raw_orient.get(key, "")).strip() if isinstance(raw_orient, dict) else ""
        orient[key] = value or str((fallback.get("orient") or {}).get(key, ""))
    for key in ("why_care", "current_focus", "signals_to_highlight", "banned_terms"):
        raw = raw_orient.get(key) if isinstance(raw_orient, dict) else None
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
        else:
            cleaned = []
        orient[key] = cleaned or list((fallback.get("orient") or {}).get(key, []))

    decide: dict[str, object] = {}
    for key in ("information_order", "tone_rules", "horizon_policy", "media_strategy", "overlay_policy", "cta_strategy"):
        value = str(raw_decide.get(key, "")).strip() if isinstance(raw_decide, dict) else ""
        decide[key] = value or str((fallback.get("decide") or {}).get(key, ""))

    act: dict[str, object] = {}
    for key in ("landing_tagline", "landing_intro", "what_it_is", "watch_intro", "horizon_intro"):
        value = str(raw_act.get(key, "")).strip() if isinstance(raw_act, dict) else ""
        act[key] = value or str((fallback.get("act") or {}).get(key, ""))

    normalized["observe"] = observe
    normalized["orient"] = orient
    normalized["decide"] = decide
    normalized["act"] = act
    return normalized


def build_media_prompt(kind: str, name: str, item: dict[str, object], ooda: dict[str, object] | None = None) -> str:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    foundations = "\n".join(f"- {line}" for line in item.get("foundations", []))
    repos = ", ".join(str(repo) for repo in item.get("repos", []))
    if kind == "hero":
        readme_excerpt = read_markdown_excerpt("README.md", limit=900)
        current_excerpt = read_markdown_excerpt("NOW/current-phase.md", limit=700)
        return f"""You are writing image-card copy for the human-facing Chummer6 guide landing hero.

Task: return a JSON object only with keys badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts.

Voice rules:
- clear, inviting, slightly playful, Shadowrun-flavored
- this is a human-facing guide, not a spec
- SR jargon is welcome
- mild dev roasting is allowed
- no mention of Fleet
- no mention of chummer5a
- no markdown fences

Source excerpts:
README:
{readme_excerpt}

Current phase:
{current_excerpt}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Requirements:
- infer the scene from the source, do not literalize repo-role labels
- do not say or imply "visitor center"
- visual_prompt must describe an actual cyberpunk scene, not a brochure cover
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible badge/title/subtitle/kicker/note should feel like guide copy, not compliance language
- overlay_hint should name the kind of HUD/analysis overlay this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short HUD labels or overlay phrases worth surfacing to the reader

Return valid JSON only.
"""
    horizon_excerpt = read_markdown_excerpt(f"HORIZONS/{name}.md", limit=900)
    return f"""You are writing image-card copy for a human-facing Chummer6 horizon banner.

Task: return a JSON object only with keys badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts.

Voice rules:
- clear, punchy, slightly funny, Shadowrun-flavored
- sell the horizon harder
- the image should feel cool, dangerous, specific, and scene-first
- SR jargon is welcome
- mild dev roasting is allowed
- no mention of Fleet
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

Requirements:
- infer the scene from the source, do not just repeat headings back
- visual_prompt must describe an actual cyberpunk scene tied to this horizon
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- the visible copy should sell the horizon without pretending it is active build work
- overlay_hint should name the kind of HUD/analysis overlay this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short HUD labels or overlay phrases worth surfacing to the reader

Return valid JSON only.
"""


def fallback_part_override(name: str, item: dict[str, object]) -> dict[str, str]:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    tagline = str(item.get("tagline", "")).strip().rstrip(".")
    intro = str(item.get("intro", "")).strip()
    why = str(item.get("why", "")).strip()
    now = str(item.get("now", "")).strip()
    return {
        "intro": (
            f"{title} is {tagline.lower()} when the chrome is working and the excuses are not. "
            f"{intro}"
        ).strip(),
        "why": (
            f"{why} If this part goes sideways, the whole run gets janky fast and somebody starts blaming the dev."
            if why
            else f"If {title} goes sideways, the whole run gets janky fast and somebody starts blaming the dev."
        ),
        "now": (
            f"{now} The short version: make it real, keep it sharp, and stop letting legacy duct tape cosplay as architecture."
            if now
            else f"Right now the job is to make {title} real, sharp, and impossible to mistake for another half-finished split."
        ),
    }


def fallback_horizon_override(name: str, item: dict[str, object]) -> dict[str, str]:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    hook = str(item.get("hook", "")).strip()
    brutal_truth = str(item.get("brutal_truth", "")).strip()
    use_case = str(item.get("use_case", "")).strip()
    return {
        "hook": (
            f"{hook} This is the kind of horizon that makes a runner grin, a GM squint, and the dev pretend this was definitely the plan all along."
            if hook
            else f"{title} is the kind of horizon that makes a runner grin, a GM squint, and the dev pretend this was definitely the plan all along."
        ),
        "brutal_truth": (
            f"{brutal_truth} If this ever lands cleanly, Chummer gets smarter, meaner, and much harder to bullshit."
            if brutal_truth
            else f"The brutal truth: if {title} ever lands cleanly, Chummer gets smarter, meaner, and much harder to bullshit."
        ),
        "use_case": (
            f"{use_case} That is the moment where the future version of Chummer stops sounding like chrome daydreams and starts feeling dangerously real."
            if use_case
            else f"The use case: you hit the button, the chrome lights up, and the future version of Chummer suddenly feels dangerously real."
        ),
    }


def fallback_media_override(kind: str, name: str, item: dict[str, object]) -> dict[str, str]:
    title = str(item.get("title", name.replace("-", " ").title())).strip()
    hook = " ".join(str(item.get("hook", "")).split()).strip()
    brutal_truth = " ".join(str(item.get("brutal_truth", "")).split()).strip()
    use_case = " ".join(str(item.get("use_case", "")).split()).strip()
    foundations = [str(line).strip() for line in item.get("foundations", []) if str(line).strip()]
    repos = [str(repo).replace("chummer6-", "") for repo in item.get("repos", []) if str(repo).strip()]
    short_foundations = [line.replace("DTOs", "DTO").replace(" and ", " / ") for line in foundations[:3]]
    if kind == "hero":
        guide_summary = read_markdown_excerpt("README.md", limit=320) or "The human guide to the next Chummer."
        phase_summary = read_markdown_excerpt("NOW/current-phase.md", limit=220)
        short_guide = short_sentence(guide_summary) or "The human guide to the next Chummer"
        short_phase = short_sentence(phase_summary) or "Foundation work first, fireworks later"
        return {
            "badge": "Chummer6",
            "title": "Chummer6",
            "subtitle": hook or short_guide,
            "kicker": foundations[0] if foundations else "Guide",
            "note": brutal_truth or short_phase or "A readable guide wall for curious chummers, nervous test dummies, and the occasional roasted dev.",
            "meta": "",
            "overlay_hint": "street map overlay",
            "visual_prompt": (
                f"Wide cinematic cyberpunk concept art for Chummer6, inspired by this guide summary: {guide_summary}. "
                f"Current phase mood: {phase_summary or 'foundations first, chrome later'}. "
                "Use a dangerous but inviting street-level scene with commlink, cyberdeck, holographic artifacts, rain, neon, and map-on-the-wall energy. "
                "No text, no logo, no watermark, 16:9."
            ),
            "visual_motifs": [
                "battered cyberdeck on a wet crate",
                "floating holographic repo cards",
                "city map overlays",
                "rainy neon alley",
            ],
            "overlay_callouts": [
                "Lua rules",
                "SR4-SR6",
                "Local-first play",
                "Explain receipts",
            ],
        }
    return {
        "badge": "Horizon",
        "title": title,
        "subtitle": hook or use_case or brutal_truth or f"{title} is a horizon lane with too much chrome to ignore and too much blast radius to rush.",
        "kicker": repos[0] if repos else (foundations[0] if foundations else "Horizon lane"),
        "note": brutal_truth or use_case or "Horizon only. Slick enough to sell, dangerous enough to keep parked for now.",
        "meta": "",
        "overlay_hint": foundations[0] if foundations else "analysis overlay",
        "visual_prompt": f"Wide cinematic cyberpunk concept art for {title}, {hook or use_case or brutal_truth or 'future-shadowrun capability'}, scene-first composition, dark humor, no text, no logo, no watermark, 16:9",
        "visual_motifs": [hook or title, *(foundations[:3] if foundations else ["cyberpunk horizon"])],
        "overlay_callouts": [title, *(short_foundations[:2] if short_foundations else repos[:2] or ["Horizon"])],
    }


def normalize_media_override(kind: str, cleaned: dict[str, object], item: dict[str, object]) -> dict[str, object]:
    normalized = dict(cleaned)
    if kind == "hero":
        title = str(normalized.get("title", "")).strip().lower()
        if title in {"", "hero", "guide", "guide hero", "landing hero"}:
            normalized["title"] = "Chummer6"
        badge = str(normalized.get("badge", "")).strip()
        if not badge:
            normalized["badge"] = "Chummer6"
        kicker = str(normalized.get("kicker", "")).strip()
        if not kicker or kicker.lower() in {"visitor center", "front door"}:
            normalized["kicker"] = "Guide"
        subtitle = str(normalized.get("subtitle", "")).strip()
        if subtitle:
            normalized["subtitle"] = subtitle.replace("visitor center", "guide").replace("Visitor Center", "Guide")
            if normalized["subtitle"].lower().startswith("chummer6 "):
                normalized["subtitle"] = normalized["subtitle"][len("Chummer6 ") :].strip()
        note = str(normalized.get("note", "")).strip()
        if note:
            normalized["note"] = note.replace("visitor center", "guide").replace("Visitor center", "Guide")
            if normalized["note"].lower().startswith("current phase "):
                normalized["note"] = normalized["note"][len("Current Phase ") :].strip()
            normalized["note"] = short_sentence(normalized["note"], limit=180) or normalized["note"]
        normalized["meta"] = ""
        if not str(normalized.get("overlay_hint", "")).strip():
            normalized["overlay_hint"] = "street map overlay"
        if not str(normalized.get("visual_prompt", "")).strip():
            normalized["visual_prompt"] = fallback_media_override("hero", "hero", {})["visual_prompt"]
        raw_motifs = normalized.get("visual_motifs")
        if isinstance(raw_motifs, list):
            normalized["visual_motifs"] = [str(item).strip() for item in raw_motifs if str(item).strip()]
        else:
            normalized["visual_motifs"] = list(fallback_media_override("hero", "hero", {})["visual_motifs"])
        raw_callouts = normalized.get("overlay_callouts")
        if isinstance(raw_callouts, list):
            normalized["overlay_callouts"] = [str(item).strip() for item in raw_callouts if str(item).strip()]
        else:
            normalized["overlay_callouts"] = list(fallback_media_override("hero", "hero", {})["overlay_callouts"])
        return normalized
    if not str(normalized.get("title", "")).strip():
        normalized["title"] = str(item.get("title", "")).strip()
    if not str(normalized.get("badge", "")).strip():
        normalized["badge"] = "Horizon"
    normalized["meta"] = ""
    if not str(normalized.get("overlay_hint", "")).strip():
        normalized["overlay_hint"] = "analysis overlay"
    if not str(normalized.get("visual_prompt", "")).strip():
        normalized["visual_prompt"] = fallback_media_override("horizon", str(item.get("slug", "") or item.get("title", "horizon")), item)["visual_prompt"]
    raw_motifs = normalized.get("visual_motifs")
    if isinstance(raw_motifs, list):
        normalized["visual_motifs"] = [str(entry).strip() for entry in raw_motifs if str(entry).strip()]
    else:
        normalized["visual_motifs"] = list(fallback_media_override("horizon", str(item.get("slug", "") or item.get("title", "horizon")), item)["visual_motifs"])
    raw_callouts = normalized.get("overlay_callouts")
    if isinstance(raw_callouts, list):
        normalized["overlay_callouts"] = [str(entry).strip() for entry in raw_callouts if str(entry).strip()]
    else:
        normalized["overlay_callouts"] = list(fallback_media_override("horizon", str(item.get("slug", "") or item.get("title", "horizon")), item)["overlay_callouts"])
    return normalized


def generate_overrides(*, include_parts: bool, include_horizons: bool, model: str) -> dict[str, object]:
    signals = collect_interest_signals()
    overrides: dict[str, object] = {
        "parts": {},
        "horizons": {},
        "media": {"hero": {}, "horizons": {}},
        "ooda": {},
        "meta": {
            "generator": "ea",
            "provider": "1min.AI",
            "provider_status": "unknown",
            "provider_error": "",
            "ooda_version": "v2",
        },
    }
    provider_available = True
    provider_error = ""
    if provider_available:
        try:
            ooda_result = chat_json(build_ooda_prompt(signals), model=model)
            overrides["ooda"] = normalize_ooda(ooda_result, signals)
        except Exception as exc:
            provider_available = False
            provider_error = str(exc)
            overrides["ooda"] = fallback_ooda(signals)
    else:
        overrides["ooda"] = fallback_ooda(signals)
    ooda = dict(overrides.get("ooda") or {})
    if provider_available:
        try:
            result = chat_json(build_media_prompt("hero", "hero", {}, ooda=ooda), model=model)
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
            provider_available = False
            provider_error = str(exc)
            cleaned = fallback_media_override("hero", "hero", {})
    else:
        cleaned = fallback_media_override("hero", "hero", {})
    cleaned = normalize_media_override("hero", cleaned, {})
    overrides["media"]["hero"] = cleaned
    if include_parts:
        for name, item in PARTS.items():
            if provider_available:
                try:
                    result = chat_json(build_part_prompt(name, item, ooda=ooda), model=model)
                    cleaned = {key: str(result.get(key, "")).strip() for key in ("intro", "why", "now") if str(result.get(key, "")).strip()}
                except Exception as exc:
                    provider_available = False
                    provider_error = str(exc)
                    cleaned = fallback_part_override(name, item)
            else:
                cleaned = fallback_part_override(name, item)
            if cleaned:
                overrides["parts"][name] = cleaned
    if include_horizons:
        for name, item in HORIZONS.items():
            if provider_available:
                try:
                    result = chat_json(build_horizon_prompt(name, item, ooda=ooda), model=model)
                    cleaned = {key: str(result.get(key, "")).strip() for key in ("hook", "brutal_truth", "use_case") if str(result.get(key, "")).strip()}
                except Exception as exc:
                    provider_available = False
                    provider_error = str(exc)
                    cleaned = fallback_horizon_override(name, item)
            else:
                cleaned = fallback_horizon_override(name, item)
            if cleaned:
                overrides["horizons"][name] = cleaned
            if provider_available:
                try:
                    media_result = chat_json(build_media_prompt("horizon", name, item, ooda=ooda), model=model)
                    media_cleaned = {}
                    for key in ("badge", "title", "subtitle", "kicker", "note", "meta", "visual_prompt", "overlay_hint"):
                        value = str(media_result.get(key, "")).strip()
                        if value:
                            media_cleaned[key] = value
                    for key in ("visual_motifs", "overlay_callouts"):
                        raw = media_result.get(key)
                        if isinstance(raw, list):
                            media_cleaned[key] = [str(entry).strip() for entry in raw if str(entry).strip()]
                    media_cleaned = normalize_media_override("horizon", media_cleaned, item)
                except Exception as exc:
                    provider_available = False
                    provider_error = str(exc)
                    media_cleaned = fallback_media_override("horizon", name, item)
            else:
                media_cleaned = fallback_media_override("horizon", name, item)
            media_cleaned = normalize_media_override("horizon", media_cleaned, item)
            overrides["media"]["horizons"][name] = media_cleaned
    overrides["meta"]["provider_status"] = "ok" if provider_available else "fallback_local_templates"
    overrides["meta"]["provider_error"] = provider_error
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chummer6 downstream guide overrides through EA using 1min.AI.")
    parser.add_argument("--output", default=str(OVERRIDE_OUT), help="Where to write the override JSON.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="1min.AI chat model.")
    parser.add_argument("--parts-only", action="store_true", help="Generate part-page overrides only.")
    parser.add_argument("--horizons-only", action="store_true", help="Generate horizon-page overrides only.")
    args = parser.parse_args()

    include_parts = not args.horizons_only
    include_horizons = not args.parts_only
    overrides = generate_overrides(
        include_parts=include_parts,
        include_horizons=include_horizons,
        model=str(args.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
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
