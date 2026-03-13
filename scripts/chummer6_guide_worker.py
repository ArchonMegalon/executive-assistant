#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
FLEET_GUIDE_SCRIPT = Path("/docker/fleet/scripts/finish_chummer6_guide.py")
OVERRIDE_OUT = Path("/docker/fleet/state/chummer6/ea_overrides.json")
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_CODEX_MODEL = "gpt-5.3-codex"
FALLBACK_MODELS = (
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
)
WORKING_VARIANT: dict[str, object] | None = None
TEXT_PROVIDER_USED: str = ""


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


def load_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = EA_ROOT / ".env"
    if not env_file.exists():
        return values
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


LOCAL_ENV = load_local_env()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or "").strip()


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    return shlex.split(raw) if raw else []


def url_template(env_name: str) -> str:
    return env_value(env_name)


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
    if str(os.environ.get("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS") or LOCAL_ENV.get("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        primary = keys[:1]
        if primary:
            return primary
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


def read_markdown_excerpt(relative_path: str, *, limit: int = 360) -> str:
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


def codex_model_candidate(requested: str) -> str:
    explicit = str(requested or "").strip()
    if explicit and "codex" in explicit.lower():
        return explicit
    env_override = str(os.environ.get("CHUMMER6_CODEX_TEXT_MODEL") or LOCAL_ENV.get("CHUMMER6_CODEX_TEXT_MODEL") or "").strip()
    if env_override:
        return env_override
    return DEFAULT_CODEX_MODEL


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


def onemin_json(prompt: str, *, model: str = DEFAULT_MODEL) -> dict[str, object]:
    last_error = "no_attempts"
    for api_key in resolve_onemin_keys():
        for url, headers, payload in request_variants(prompt, model=model, api_key=api_key):
            body_bytes = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
                return extract_response_json(body)
            except urllib.error.HTTPError as exc:
                response_text = exc.read().decode("utf-8", errors="replace")
                if exc.code == 401:
                    last_error = f"{url}:http_{exc.code}:{response_text[:220]}"
                    break
                if exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in response_text:
                    for _attempt in range(provider_busy_retries()):
                        time.sleep(provider_busy_delay_seconds())
                        retry = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
                        try:
                            with urllib.request.urlopen(retry, timeout=60) as response:
                                body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
                            return extract_response_json(body)
                        except urllib.error.HTTPError as retry_exc:
                            retry_text = retry_exc.read().decode("utf-8", errors="replace")
                            if retry_exc.code == 401:
                                last_error = f"{url}:http_{retry_exc.code}:{retry_text[:220]}"
                                break
                            if retry_exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in retry_text:
                                last_error = f"{url}:openai_busy"
                                continue
                            last_error = f"{url}:http_{retry_exc.code}:{retry_text[:220]}"
                            break
                        except Exception as retry_exc:
                            last_error = f"{url}:{type(retry_exc).__name__}:{str(retry_exc)[:220]}"
                            break
                    continue
                last_error = f"{url}:http_{exc.code}:{response_text[:220]}"
            except Exception as exc:
                last_error = f"{url}:{type(exc).__name__}:{str(exc)[:220]}"
    raise RuntimeError(f"onemin_text_failed:{last_error}")


def codex_json(prompt: str, *, model: str = DEFAULT_MODEL) -> dict[str, object]:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex_cli_unavailable")
    codex_model = codex_model_candidate(model)
    codex_sandbox = str(os.environ.get("CHUMMER6_CODEX_SANDBOX") or LOCAL_ENV.get("CHUMMER6_CODEX_SANDBOX") or "danger-full-access").strip()
    with tempfile.NamedTemporaryFile(prefix="chummer6_codex_", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        command = [
            codex,
            "exec",
            "-C",
            str(EA_ROOT),
            "--skip-git-repo-check",
            "--ephemeral",
        ]
        if codex_sandbox:
            command.extend(["-s", codex_sandbox])
        command.extend(
            [
                "-m",
                codex_model,
                "-c",
                'model_reasoning_effort="low"',
                "-o",
                str(output_path),
                prompt,
            ]
        )
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            timeout=90,
        )
        text = output_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError("codex_empty_output")
        return extract_json(text)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(f"codex_exec_failed:{detail[:400]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("codex_exec_timeout") from exc
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass


def chat_json(prompt: str, *, model: str = DEFAULT_MODEL) -> dict[str, object]:
    global TEXT_PROVIDER_USED
    order_raw = str(os.environ.get("CHUMMER6_TEXT_PROVIDER_ORDER") or LOCAL_ENV.get("CHUMMER6_TEXT_PROVIDER_ORDER") or "codex,onemin").strip()
    order = [entry.strip().lower() for entry in order_raw.split(",") if entry.strip()]
    attempted: list[str] = []
    for provider in order:
        try:
            if provider in {"onemin", "1min", "1min.ai", "oneminai"}:
                payload = onemin_json(prompt, model=model)
                TEXT_PROVIDER_USED = "onemin"
                return payload
            if provider == "codex":
                payload = codex_json(prompt, model=model)
                TEXT_PROVIDER_USED = "codex"
                return payload
            attempted.append(f"{provider}:unknown_provider")
        except Exception as exc:
            attempted.append(f"{provider}:{exc}")
    raise RuntimeError("no text provider succeeded: " + " || ".join(attempted))


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
    return str(raw).strip().lower() in {"1", "true", "yes", "on"} if raw else False


def humanize_text_local(text: str, *, target: str) -> str:
    return " ".join(str(text or "").split()).strip()


def humanize_text(text: str, *, target: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    command_names = [
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND",
        "CHUMMER6_TEXT_HUMANIZER_COMMAND",
    ]
    template_names = [
        "CHUMMER6_BROWSERACT_HUMANIZER_URL_TEMPLATE",
        "CHUMMER6_TEXT_HUMANIZER_URL_TEMPLATE",
    ]
    attempted: list[str] = []
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
    owns = "\n".join(f"- {line}" for line in item.get("owns", []))
    not_owns = "\n".join(f"- {line}" for line in item.get("not_owns", []))
    return f"""You are writing downstream-only copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys intro, why, now.

Voice rules:
- clear, slightly playful, Shadowrun-flavored
- plain language first
- SR jargon is welcome
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
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
    return f"""You are writing downstream-only horizon copy for the human-facing Chummer6 guide.

Task: return a JSON object only with keys hook, brutal_truth, use_case.

Voice rules:
- sell the idea harder
- clear, punchy, Shadowrun-flavored
- SR jargon is welcome
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- keep it exciting without pretending it is active work
- no mention of Fleet or EA
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

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Return valid JSON only.
"""


def build_section_ooda_prompt(
    section_type: str,
    name: str,
    item: dict[str, object],
    *,
    global_ooda: dict[str, object] | None = None,
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
                    f"Intro: {item.get('intro', '')}",
                    f"Why: {item.get('why', '')}",
                    "Owns:\n" + "\n".join(f"- {line}" for line in item.get("owns", [])),
                    "Does not own:\n" + "\n".join(f"- {line}" for line in item.get("not_owns", [])),
                    f"Now: {item.get('now', '')}",
                ]
            ),
        },
        "horizon": {
            "context": f"the HORIZONS/{name}.md page for the human-facing Chummer6 guide",
            "source": "\n\n".join(
                [
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
- the whole guide uses one recurring Chummer troll easter egg; leave room for a small diegetic troll motif, patch, sticker, stamp, charm, ad, or background cameo in the scene
- Shadowrun jargon is welcome
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
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

Return valid JSON only.
"""


def build_section_oodas_bundle_prompt(
    section_type: str,
    section_items: dict[str, dict[str, object]],
    *,
    global_ooda: dict[str, object] | None = None,
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
                "intro": item.get("intro", ""),
                "why": item.get("why", ""),
                "now": item.get("now", ""),
                "owns": item.get("owns", []),
                "not_owns": item.get("not_owns", []),
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
- the whole guide uses one recurring Chummer troll easter egg; leave room for a small diegetic troll motif, patch, sticker, stamp, charm, ad, or background cameo in the scene
- Shadowrun jargon is welcome
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- keep the whole JSON compact

Section type: {section_type}

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Sections:
{json.dumps(payload, ensure_ascii=True)}

Return valid JSON only.
"""


def normalize_section_ooda(
    result: dict[str, object],
    *,
    section_type: str,
    name: str,
    item: dict[str, object],
    global_ooda: dict[str, object] | None = None,
) -> dict[str, object]:
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
            if isinstance(raw, list):
                cleaned = [str(entry).strip() for entry in raw if str(entry).strip()]
                if not cleaned:
                    raise ValueError(f"section OODA field is missing: {section_type}/{name}.{stage}.{field}")
                merged[field] = cleaned
            else:
                value = str(raw or "").strip()
                if not value:
                    raise ValueError(f"section OODA field is missing: {section_type}/{name}.{stage}.{field}")
                merged[field] = value
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

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Pages:
{json.dumps(pages_payload, ensure_ascii=True)}

Return valid JSON only.
"""


def build_parts_bundle_prompt(*, items: dict[str, dict[str, object]], global_ooda: dict[str, object], section_oodas: dict[str, object]) -> str:
    parts_payload: dict[str, object] = {}
    for name, item in items.items():
        parts_payload[name] = {
            "title": item.get("title", ""),
            "tagline": item.get("tagline", ""),
            "intro": item.get("intro", ""),
            "why": item.get("why", ""),
            "now": item.get("now", ""),
            "owns": item.get("owns", []),
            "not_owns": item.get("not_owns", []),
            "section_ooda": section_oodas.get(name, {}),
        }
    return f"""You are writing downstream-only copy and media metadata for multiple Chummer6 part pages.

Task: return one JSON object keyed by part id.
Each part id must map to:
- copy: object with intro, why, now
- media: object with badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract

Rules:
- clear, slightly playful, Shadowrun-flavored
- plain language first
- SR jargon is welcome
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- keep copy grounded and useful
- make each part sound like its own place, not another templated glossary card
- make the media scene-first, not icon soup
- no literal on-image text or prompt leakage

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

Parts:
{json.dumps(parts_payload, ensure_ascii=True)}

Return valid JSON only.
"""


def build_horizons_bundle_prompt(*, items: dict[str, dict[str, object]], global_ooda: dict[str, object], section_oodas: dict[str, object]) -> str:
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
            "section_ooda": section_oodas.get(name, {}),
        }
    return f"""You are writing downstream-only copy and media metadata for multiple Chummer6 horizon pages.

Task: return one JSON object keyed by horizon id.
Each horizon id must map to:
- copy: object with hook, image_idea, problem, table_scene, meanwhile, why_great, why_waits, pitch_line
- media: object with badge, title, subtitle, kicker, note, meta, visual_prompt, overlay_hint, visual_motifs, overlay_callouts, scene_contract

Rules:
- sell the idea harder without pretending it ships tomorrow
- clear, punchy, Shadowrun-flavored
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences
- scenes should feel specific, cool, and dangerous
- if the codename implies a person or metaphor, make that legible
- do not reuse the same sentence stem across multiple horizons
- the copy should feel distinct per horizon, not like one template with swapped nouns
- image_idea is one vivid sentence that would help an illustrator stage the scene
- table_scene should read like a mini play scene with 4-8 short lines of dialogue or narration from GM, player, and Chummer
- meanwhile should be 2-4 markdown bullets explaining what Chummer is doing in the background
- why_great should explain the payoff in plain language, not product jargon
- pitch_line should invite readers back to the Horizons index if they have a better future idea

Global OODA:
{json.dumps(global_ooda or {}, ensure_ascii=True)}

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
        cleaned = {key: str(row.get(key, "")).strip() for key in ("intro", "body", "kicker") if str(row.get(key, "")).strip()}
        if len(cleaned) < 2:
            raise ValueError(f"insufficient page bundle content: {page_id}")
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
        cleaned_copy = {key: str(copy.get(key, "")).strip() for key in ("intro", "why", "now") if str(copy.get(key, "")).strip()}
        if len(cleaned_copy) < 3:
            raise ValueError(f"insufficient part copy: {name}")
        media_cleaned = normalize_media_override("horizon", dict(media), item)
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
            key: str(copy.get(key, "")).strip()
            for key in ("hook", "image_idea", "problem", "table_scene", "meanwhile", "why_great", "why_waits", "pitch_line")
            if str(copy.get(key, "")).strip()
        }
        if len(cleaned_copy) < 8:
            raise ValueError(f"insufficient horizon copy: {name}")
        media_cleaned = normalize_media_override("horizon", dict(media), item)
        copy_rows[name] = cleaned_copy
        media_rows[name] = media_cleaned
    return copy_rows, media_rows


SOURCE_SIGNAL_FILES = [
    ("/docker/chummercomplete/chummer-core-engine/instructions.md", "core_instructions"),
    ("/docker/chummercomplete/chummer-core-engine/README.md", "core_readme"),
    ("/docker/chummercomplete/chummer-core-engine/test-lua-evaluator.sh", "core_lua_rules"),
    ("/docker/chummercomplete/chummer-core-engine/Chummer.Rulesets.Sr4/Sr4RulesetPlugin.cs", "core_sr4_plugin"),
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
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- focus on what a curious human would actually care about first
- if the source suggests strong user-facing selling points like multi-era support, Lua/scripted rules, local-first play, explain receipts, grounded dossiers, or dangerous simulation energy, surface them
- if source signals clearly include multi-era support or scripted rules, make at least one landing-facing sentence say so plainly
- do not invent implementation-specific claims unless the source canon makes them explicit
- the guide art uses a recurring Chummer troll easter egg integrated into scenes as a secondary diegetic detail, never as a giant centered logo
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
- what_it_is should explain the repo in plain language
- watch_intro should tee up why the project is worth following
- horizon_intro should tee up the future ideas in a fun way without pretending they are active work
- keep the whole JSON compact enough to fit on one terminal screen

Observed tags:
{tags}

Observed source excerpts:
{source_excerpt}

Return valid JSON only.
"""


def normalize_ooda(result: dict[str, object], signals: dict[str, object]) -> dict[str, object]:
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
        if not cleaned:
            raise ValueError(f"global OODA list field is missing: observe.{key}")
        observe[key] = cleaned

    orient: dict[str, object] = {}
    for key in ("audience", "promise", "tension", "visual_direction", "humor_line"):
        value = str(raw_orient.get(key, "")).strip() if isinstance(raw_orient, dict) else ""
        if not value:
            raise ValueError(f"global OODA field is missing: orient.{key}")
        orient[key] = value
    for key in ("why_care", "current_focus", "signals_to_highlight", "banned_terms"):
        raw = raw_orient.get(key) if isinstance(raw_orient, dict) else None
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
        else:
            cleaned = []
        if not cleaned:
            raise ValueError(f"global OODA list field is missing: orient.{key}")
        orient[key] = cleaned

    decide: dict[str, object] = {}
    for key in ("information_order", "tone_rules", "horizon_policy", "media_strategy", "overlay_policy", "cta_strategy"):
        value = str(raw_decide.get(key, "")).strip() if isinstance(raw_decide, dict) else ""
        if not value:
            raise ValueError(f"global OODA field is missing: decide.{key}")
        decide[key] = value

    act: dict[str, object] = {}
    for key in ("landing_tagline", "landing_intro", "what_it_is", "watch_intro", "horizon_intro"):
        value = str(raw_act.get(key, "")).strip() if isinstance(raw_act, dict) else ""
        if not value:
            raise ValueError(f"global OODA field is missing: act.{key}")
        act[key] = value

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
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
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

Requirements:
- infer the scene from the source, do not literalize repo-role labels
- do not say or imply "visitor center"
- visual_prompt must describe an actual cyberpunk scene, not a brochure cover
- visual_prompt must center one memorable focal subject, setup, or action instead of generic poster collage
- if the section implies a person or team, choose a believable protagonist instead of abstract symbols
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, or crash-test simulation, make that metaphor visibly legible in-scene
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- every image must include one small recurring Chummer troll easter egg integrated into the scene as a diegetic detail
- that troll motif can be a jacket pin, patch, sticker, stamp, tattoo, charm, transit ad, CRT mascot, or a real troll in the classic Chummer stance
- the troll motif must be clearly visible on a README banner, but secondary and never the main subject
- the visible badge/title/subtitle/kicker/note should feel like guide copy, not compliance language
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
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
  - easter_egg_kind
  - easter_egg_placement
  - easter_egg_detail
  - easter_egg_visibility
- scene_contract.subject should name the focal subject in plain language
- scene_contract.metaphor should name the strongest visual metaphor if one exists
- scene_contract.props should be a short list of concrete visible things
- scene_contract.overlays should be a short list of diegetic overlay ideas
- scene_contract.composition should be a short layout phrase like single_protagonist, group_table, desk_still_life, or city_edge
- scene_contract easter egg fields must describe the troll motif in practical art-direction language

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
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
- never expose secrets, tokens, passwords, or private credentials
- no mention of Fleet or EA
- no mention of chummer5a
- no markdown fences

Source page excerpt:
{part_excerpt}

Part id: {name}
Title: {title}
Tagline: {item.get("tagline", "")}
Intro: {item.get("intro", "")}
Why: {item.get("why", "")}
Now: {item.get("now", "")}
Owns:
{chr(10).join(f"- {line}" for line in item.get("owns", []))}

Does not own:
{chr(10).join(f"- {line}" for line in item.get("not_owns", []))}

Guide OODA:
{json.dumps(ooda or {}, ensure_ascii=True)}

Section OODA:
{json.dumps(section_ooda or {}, ensure_ascii=True)}

Requirements:
- infer the scene from the source, do not repeat repo labels back as literal signage
- visual_prompt must describe an actual cyberpunk scene tied to this part in use
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the part naturally implies a person or team, choose believable cyberpunk people
- if the part naturally implies a machine room, archive, workshop, or table scene, make that spatial metaphor visibly legible
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- every image must include one small recurring Chummer troll easter egg integrated into the scene as a diegetic detail
- that troll motif can be a jacket pin, patch, sticker, stamp, tattoo, charm, transit ad, CRT mascot, or a real troll in the classic Chummer stance
- the troll motif must be clearly visible on a README banner, but secondary and never the main subject
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
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
  - easter_egg_kind
  - easter_egg_placement
  - easter_egg_detail
  - easter_egg_visibility

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
- sharper dev roasting is allowed
- roast code habits first, but if source context makes it land harder, a little real-life spillover is fine
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

Requirements:
- infer the scene from the source, do not just repeat headings back
- visual_prompt must describe an actual cyberpunk scene tied to this horizon
- visual_prompt must center one memorable focal subject, setup, or action instead of icon soup
- if the section naturally implies a person, make that person specific and believable
- if the concept implies a visual metaphor like x-ray, ghost, mirror, passport, dossier, web, or blackbox, make that metaphor visibly legible in-scene
- if the title reads like a personal codename, make the focal subject feel like that codename embodied; if it reads like a feminine personal name, it is fine to make the focal subject a woman
- if the metaphor is x-ray or simulation, show a real body, runner, or situation with the metaphor happening to it; do not collapse into abstract boxes and HUD wallpaper
- visual_prompt must be no-text / no-logo / no-watermark / 16:9
- every image must include one small recurring Chummer troll easter egg integrated into the scene as a diegetic detail
- that troll motif can be a jacket pin, patch, sticker, stamp, tattoo, charm, transit ad, CRT mascot, or a real troll in the classic Chummer stance
- the troll motif must be clearly visible on a README banner, but secondary and never the main subject
- the visible copy should sell the horizon without pretending it is active build work
- overlay_hint should name the kind of diegetic HUD/analysis treatment this image wants, in a few words
- visual_motifs should be 3-6 short noun phrases for what should actually be visible
- overlay_callouts should be 2-4 short overlay ideas, not literal on-image text
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
  - easter_egg_kind
  - easter_egg_placement
  - easter_egg_detail
  - easter_egg_visibility
- if the title reads like a codename or person, make scene_contract.subject a believable cyberpunk person, not a generic skyline or dashboard
- if the metaphor is x-ray / dossier / forge / ghost / heat web / mirror / passport / blackbox / simulation, make scene_contract.metaphor explicit

Return valid JSON only.
"""


def normalize_media_override(kind: str, cleaned: dict[str, object], item: dict[str, object]) -> dict[str, object]:
    def infer_easter_egg(*, asset_key: str, visual_prompt: str, composition: str) -> dict[str, str]:
        lowered = f"{asset_key} {visual_prompt} {composition}".lower()
        kind = "pin"
        placement = "as a small jacket pin or device charm inside the safe crop"
        detail = "a small recurring Chummer troll motif in the classic horned squat stance"
        visibility = "secondary but clearly visible on a README banner"
        if any(token in lowered for token in ("forge", "workshop", "bench")):
            kind = "patch"
            placement = "as a stitched patch on an apron, jacket shoulder, or tool bag"
        elif any(token in lowered for token in ("dossier", "desk", "evidence", "jackpoint", "persona")):
            kind = "stamp"
            placement = "as a wax seal, approval stamp, or sticker on a foreground folder, dossier, or chip case"
        elif any(token in lowered for token in ("passport", "gate", "customs")):
            kind = "stamp"
            placement = "as a customs stamp or inspection mark on a passport card or transit document"
        elif any(token in lowered for token in ("blackbox", "loadout", "gear")):
            kind = "sticker"
            placement = "as a sticker or etched decal on a medkit, ammo case, tool case, or tray edge"
        elif any(token in lowered for token in ("simulation", "alice", "lab")):
            kind = "decal"
            placement = "as a warning decal on the sim bench, restraint frame, or diagnostic housing"
        elif any(token in lowered for token in ("heat", "web", "network", "wall")):
            kind = "screen mascot"
            placement = "on a side monitor, wall display, or pinned note near the conspiracy web"
        elif any(token in lowered for token in ("street", "city", "boulevard", "start-here", "readme", "hero")):
            kind = "sticker"
            placement = "as a sticker, transit ad mascot, or peeling poster on street hardware in the midground"
        elif any(token in lowered for token in ("group_table", "table", "nexus-pan", "tactical")):
            kind = "pin"
            placement = "as a tiny pin, patch, or phone-case sticker near the players and their devices"
        return {
            "easter_egg_kind": kind,
            "easter_egg_placement": placement,
            "easter_egg_detail": detail,
            "easter_egg_visibility": visibility,
        }

    def infer_scene_contract(*, asset_key: str, visual_prompt: str) -> dict[str, object]:
        lowered = visual_prompt.lower()
        subject = "a cyberpunk protagonist"
        if "team" in lowered or "table" in lowered or "gm" in lowered:
            subject = "a runner team at a live table"
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
        if "table" in lowered or "team" in lowered:
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
        contract = {
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
        contract.update(
            infer_easter_egg(
                asset_key=asset_key,
                visual_prompt=visual_prompt,
                composition=composition,
            )
        )
        return contract

    def normalize_scene_contract(raw: object, *, asset_key: str, visual_prompt: str) -> dict[str, object]:
        default = infer_scene_contract(asset_key=asset_key, visual_prompt=visual_prompt)
        if not isinstance(raw, dict):
            return default
        contract: dict[str, object] = dict(default)
        for key in (
            "subject",
            "environment",
            "action",
            "metaphor",
            "composition",
            "palette",
            "mood",
            "humor",
            "easter_egg_kind",
            "easter_egg_placement",
            "easter_egg_detail",
            "easter_egg_visibility",
        ):
            value = str(raw.get(key, "")).strip()
            if value:
                contract[key] = value
        for key in ("props", "overlays"):
            value = raw.get(key)
            if isinstance(value, list):
                cleaned_values = [str(entry).strip() for entry in value if str(entry).strip()]
                if cleaned_values:
                    contract[key] = cleaned_values[:6]
        # Keep the prompt close by so downstream renderers can reason over both.
        contract["visual_prompt"] = visual_prompt
        return contract

    normalized = dict(cleaned)
    if kind == "hero":
        for field in ("badge", "title", "subtitle", "kicker", "note", "overlay_hint", "visual_prompt"):
            value = str(normalized.get(field, "")).strip()
            if not value:
                raise ValueError(f"hero media field is missing: {field}")
            normalized[field] = value
        normalized["meta"] = str(normalized.get("meta", "")).strip()
        raw_motifs = normalized.get("visual_motifs")
        if not isinstance(raw_motifs, list):
            raise ValueError("hero media field is missing: visual_motifs")
        motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()]
        if not motifs:
            raise ValueError("hero media field is missing: visual_motifs")
        if not any("troll" in entry.lower() for entry in motifs):
            motifs.append("small recurring troll motif hidden in-world")
        normalized["visual_motifs"] = motifs
        raw_callouts = normalized.get("overlay_callouts")
        if not isinstance(raw_callouts, list):
            raise ValueError("hero media field is missing: overlay_callouts")
        callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()]
        if not callouts:
            raise ValueError("hero media field is missing: overlay_callouts")
        normalized["overlay_callouts"] = callouts
        normalized["scene_contract"] = normalize_scene_contract(
            normalized.get("scene_contract"),
            asset_key="hero",
            visual_prompt=str(normalized["visual_prompt"]),
        )
        return normalized
    for field in ("badge", "title", "subtitle", "kicker", "note", "overlay_hint", "visual_prompt"):
        value = str(normalized.get(field, "")).strip()
        if not value:
            raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.{field}")
        normalized[field] = value
    normalized["meta"] = str(normalized.get("meta", "")).strip()
    raw_motifs = normalized.get("visual_motifs")
    if not isinstance(raw_motifs, list):
        raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.visual_motifs")
    motifs = [str(entry).strip() for entry in raw_motifs if str(entry).strip()]
    if not motifs:
        raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.visual_motifs")
    if not any("troll" in entry.lower() for entry in motifs):
        motifs.append("small recurring troll motif hidden in-world")
    normalized["visual_motifs"] = motifs
    raw_callouts = normalized.get("overlay_callouts")
    if not isinstance(raw_callouts, list):
        raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.overlay_callouts")
    callouts = [str(entry).strip() for entry in raw_callouts if str(entry).strip()]
    if not callouts:
        raise ValueError(f"horizon media field is missing: {item.get('slug', item.get('title', 'horizon'))}.overlay_callouts")
    normalized["overlay_callouts"] = callouts
    normalized["scene_contract"] = normalize_scene_contract(
        normalized.get("scene_contract"),
        asset_key=item.get("slug", item.get("title", "horizon")),
        visual_prompt=str(normalized["visual_prompt"]),
    )
    return normalized


PAGE_PROMPTS: dict[str, dict[str, str]] = {
    "readme": {
        "source": "The main landing page. Explain why Chummer6 exists, why a human should care, where they should click next, and why the current phase is foundations first.",
    },
    "start_here": {
        "source": "Welcome and first-run orientation for a new human reader. Explain why there are many repos without sounding like internal process sludge.",
    },
    "what_chummer6_is": {
        "source": "Explain what Chummer6 is, why it exists, who it helps, and what it deliberately is not.",
    },
    "where_to_go_deeper": {
        "source": "Explain where deeper blueprint and code truth live without bureaucratic wording.",
    },
    "current_phase": {
        "source": "Explain the current phase in human language: foundations first, not feature fireworks.",
    },
    "current_status": {
        "source": "Explain the current visible state without sounding like raw ops telemetry.",
    },
    "public_surfaces": {
        "source": "Explain what is visible now and why preview does not mean final public shape.",
    },
    "parts_index": {
        "source": "Introduce the main parts in a field-guide voice and help the reader choose where to go next.",
    },
    "horizons_index": {
        "source": "Sell the horizon section as an exciting garage of future ideas without pretending they are active work.",
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
        },
    }
    provider_error = ""
    try:
        ooda_result = chat_json(build_ooda_prompt(signals), model=model)
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
        hero_ooda_result = chat_json(build_section_ooda_prompt("hero", "hero", {}, global_ooda=ooda), model=model)
        hero_ooda = normalize_section_ooda(hero_ooda_result, section_type="hero", name="hero", item={}, global_ooda=ooda)
    except Exception as exc:
        raise RuntimeError(f"hero section OODA generation failed: {exc}") from exc
    overrides["section_ooda"]["hero"]["hero"] = hero_ooda
    try:
        result = chat_json(build_media_prompt("hero", "hero", {}, ooda=ooda, section_ooda=hero_ooda), model=model)
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
                build_section_oodas_bundle_prompt("page", batch, global_ooda=ooda),
                model=model,
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
                    build_section_oodas_bundle_prompt("part", batch, global_ooda=ooda),
                    model=model,
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
        for batch in chunk_mapping(PARTS, size=section_batch_size("part", len(PARTS))):
            try:
                part_bundle = chat_json(
                    build_parts_bundle_prompt(
                        items=batch,
                        global_ooda=ooda,
                        section_oodas={name: part_oodas[name] for name in batch.keys()},
                    ),
                    model=model,
                )
                copy_rows, media_rows = normalize_parts_bundle(part_bundle, items=batch)
                part_copy_rows.update(copy_rows)
                part_media_rows.update(media_rows)
            except Exception as exc:
                raise RuntimeError(f"part bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        for part_id, row in part_copy_rows.items():
            humanize_mapping_fields(row, ("intro", "why", "now"), target_prefix=f"guide:part:{part_id}")
        overrides["parts"] = part_copy_rows
        overrides["media"]["parts"] = part_media_rows
    if include_horizons:
        horizon_oodas: dict[str, object] = {}
        for batch in chunk_mapping(HORIZONS, size=section_batch_size("horizon", len(HORIZONS))):
            try:
                horizon_ooda_result = chat_json(
                    build_section_oodas_bundle_prompt("horizon", batch, global_ooda=ooda),
                    model=model,
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
        for batch in chunk_mapping(HORIZONS, size=section_batch_size("horizon", len(HORIZONS))):
            try:
                horizon_bundle = chat_json(
                    build_horizons_bundle_prompt(
                        items=batch,
                        global_ooda=ooda,
                        section_oodas={name: horizon_oodas[name] for name in batch.keys()},
                    ),
                    model=model,
                )
                copy_rows, media_rows = normalize_horizons_bundle(horizon_bundle, items=batch)
                horizon_copy_rows.update(copy_rows)
                horizon_media_rows.update(media_rows)
            except Exception as exc:
                raise RuntimeError(f"horizon bundle generation failed ({', '.join(batch.keys())}): {exc}") from exc
        for horizon_id, row in horizon_copy_rows.items():
            humanize_mapping_fields(
                row,
                ("hook", "why_wiz", "brutal_truth", "use_case", "idea", "problem", "why_waits"),
                target_prefix=f"guide:horizon:{horizon_id}",
            )
        overrides["horizons"] = horizon_copy_rows
        overrides["media"]["horizons"] = horizon_media_rows
    overrides["meta"]["provider"] = TEXT_PROVIDER_USED or "unknown"
    overrides["meta"]["provider_status"] = "ok"
    overrides["meta"]["provider_error"] = provider_error
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chummer6 downstream guide overrides through EA using section-level OODA.")
    parser.add_argument("--output", default=str(OVERRIDE_OUT), help="Where to write the override JSON.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Preferred non-Codex text model.")
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
