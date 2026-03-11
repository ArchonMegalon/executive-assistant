#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
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


def build_part_prompt(name: str, item: dict[str, object]) -> str:
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

Return valid JSON only.
"""


def build_horizon_prompt(name: str, item: dict[str, object]) -> str:
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


def generate_overrides(*, include_parts: bool, include_horizons: bool, model: str) -> dict[str, object]:
    overrides: dict[str, object] = {"parts": {}, "horizons": {}, "meta": {"generator": "ea", "provider": "1min.AI", "provider_status": "unknown", "provider_error": ""}}
    provider_available = True
    provider_error = ""
    if include_parts:
        for name, item in PARTS.items():
            if provider_available:
                try:
                    result = chat_json(build_part_prompt(name, item), model=model)
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
                    result = chat_json(build_horizon_prompt(name, item), model=model)
                    cleaned = {key: str(result.get(key, "")).strip() for key in ("hook", "brutal_truth", "use_case") if str(result.get(key, "")).strip()}
                except Exception as exc:
                    provider_available = False
                    provider_error = str(exc)
                    cleaned = fallback_horizon_override(name, item)
            else:
                cleaned = fallback_horizon_override(name, item)
            if cleaned:
                overrides["horizons"][name] = cleaned
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
