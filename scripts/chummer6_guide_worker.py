#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
FLEET_GUIDE_SCRIPT = Path("/docker/fleet/scripts/finish_chummer6_guide.py")
OVERRIDE_OUT = Path("/docker/fleet/state/chummer6/ea_overrides.json")
DEFAULT_MODEL = "gpt-4o-mini"


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


def resolve_onemin_key() -> str:
    output = subprocess.check_output(
        ["bash", str(EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh")],
        text=True,
    ).strip()
    if not output:
        raise RuntimeError("no 1min.AI key configured")
    return output


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


def chat_json(api_key: str, prompt: str, *, model: str = DEFAULT_MODEL) -> dict[str, object]:
    payload = {
        "type": "UNIFY_CHAT_WITH_AI",
        "model": model,
        "promptObject": {
            "prompt": prompt,
        },
    }
    request = urllib.request.Request(
        "https://api.1min.ai/api/chat-with-ai",
        headers={
            "Content-Type": "application/json",
            "API-KEY": api_key,
        },
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    result_rows = (((body.get("aiRecord") or {}).get("aiRecordDetail") or {}).get("resultObject") or [])
    if not result_rows:
        raise RuntimeError("1min.AI returned no resultObject rows")
    return extract_json(str(result_rows[0]))


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


def generate_overrides(*, include_parts: bool, include_horizons: bool, model: str) -> dict[str, object]:
    api_key = resolve_onemin_key()
    overrides: dict[str, object] = {"parts": {}, "horizons": {}}
    if include_parts:
        for name, item in PARTS.items():
            result = chat_json(api_key, build_part_prompt(name, item), model=model)
            cleaned = {key: str(result.get(key, "")).strip() for key in ("intro", "why", "now") if str(result.get(key, "")).strip()}
            if cleaned:
                overrides["parts"][name] = cleaned
    if include_horizons:
        for name, item in HORIZONS.items():
            result = chat_json(api_key, build_horizon_prompt(name, item), model=model)
            cleaned = {key: str(result.get(key, "")).strip() for key in ("hook", "brutal_truth", "use_case") if str(result.get(key, "")).strip()}
            if cleaned:
                overrides["horizons"][name] = cleaned
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
    print(json.dumps({"output": str(output_path), "parts": len(overrides.get("parts", {})), "horizons": len(overrides.get("horizons", {}))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
