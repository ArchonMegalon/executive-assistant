#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chummer6_runtime_config import load_local_env, load_runtime_overrides

EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_provider_readiness.json")

RAW_KEY_NAMES = {
    "pollinations": [],
    "browseract": ["BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1", "BROWSERACT_API_KEY_FALLBACK_2", "BROWSERACT_API_KEY_FALLBACK_3"],
    "unmixr": ["UNMIXR_API_KEY"],
    "onemin": [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_2",
        "ONEMIN_AI_API_KEY_FALLBACK_3",
        "ONEMIN_AI_API_KEY_FALLBACK_4",
        "ONEMIN_AI_API_KEY_FALLBACK_5",
        "ONEMIN_AI_API_KEY_FALLBACK_6",
        "ONEMIN_AI_API_KEY_FALLBACK_7",
        "ONEMIN_AI_API_KEY_FALLBACK_8",
        "ONEMIN_AI_API_KEY_FALLBACK_9",
        "ONEMIN_AI_API_KEY_FALLBACK_10",
    ],
    "magixai": ["MAGIXAI_API_KEY", "AI_MAGICX_API_KEY", "AIMAGICX_API_KEY"],
    "markupgo": ["MARKUPGO_API_KEY"],
    "prompting_systems": ["PROMPTING_SYSTEMS_API_KEY"],
}

ADAPTER_ENV_NAMES = {
    "media_factory": ["CHUMMER6_MEDIA_FACTORY_RENDER_COMMAND"],
    "gemini_vortex": ["EA_GEMINI_VORTEX_COMMAND", "EA_GEMINI_VORTEX_MODEL", "EA_GEMINI_VORTEX_TIMEOUT_SECONDS"],
    "magixai": ["CHUMMER6_MAGIXAI_RENDER_COMMAND", "CHUMMER6_MAGIXAI_RENDER_URL_TEMPLATE"],
    "markupgo": ["CHUMMER6_MARKUPGO_RENDER_COMMAND", "CHUMMER6_MARKUPGO_RENDER_URL_TEMPLATE"],
    "prompting_systems": ["CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND", "CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"],
    "browseract_magixai": [
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_ID",
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_QUERY",
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND",
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_URL_TEMPLATE",
    ],
    "browseract_prompting_systems": [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_ID",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_QUERY",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE",
    ],
    "onemin": ["CHUMMER6_1MIN_RENDER_COMMAND", "CHUMMER6_1MIN_RENDER_URL_TEMPLATE"],
}

LOCAL_ENV = load_local_env()
POLICY_ENV = load_runtime_overrides()
_ONEMIN_FALLBACK_ENV_RE = re.compile(r"^ONEMIN_AI_API_KEY_FALLBACK_(\d+)$")
PREFERRED_PROVIDER_STATUSES = {"ready"}


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


def _onemin_manifest_payload() -> object:
    inline = env_value("ONEMIN_DIRECT_API_KEYS_JSON")
    if inline:
        try:
            return json.loads(inline)
        except Exception:
            return None
    raw_path = env_value("ONEMIN_DIRECT_API_KEYS_JSON_FILE")
    if not raw_path:
        return None
    try:
        configured_path = Path(raw_path)
    except Exception:
        return None
    candidates: list[Path] = []
    if configured_path.is_absolute():
        candidates.append(configured_path)
        if str(configured_path).startswith("/config/"):
            candidates.append(EA_ROOT / "config" / configured_path.name)
    else:
        candidates.extend([EA_ROOT / configured_path, configured_path])
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized.exists():
            try:
                return json.loads(normalized.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _onemin_manifest_account_names() -> list[str]:
    payload = _onemin_manifest_payload()
    if isinstance(payload, dict):
        if isinstance(payload.get("slots"), list):
            items = payload.get("slots") or []
        elif isinstance(payload.get("keys"), list):
            items = payload.get("keys") or []
        elif isinstance(payload.get("accounts"), list):
            items = payload.get("accounts") or []
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    fallback_numbers: set[int] = set()
    for mapping in (os.environ, LOCAL_ENV, POLICY_ENV):
        for env_name in mapping:
            match = _ONEMIN_FALLBACK_ENV_RE.match(str(env_name or "").strip())
            if match is None:
                continue
            try:
                fallback_numbers.add(int(match.group(1)))
            except Exception:
                continue
    next_fallback = max(fallback_numbers, default=0) + 1
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        slot = ""
        account_name = ""
        key = ""
        if isinstance(item, str):
            key = str(item or "").strip()
        elif isinstance(item, dict):
            key = str(
                item.get("key")
                or item.get("secret")
                or item.get("api_key")
                or item.get("value")
                or item.get("token")
                or ""
            ).strip()
            slot = str(item.get("slot") or item.get("slot_name") or "").strip()
            account_name = str(item.get("account_name") or item.get("name") or "").strip()
        if not key:
            continue
        if not account_name:
            lowered = str(slot or "").strip().lower()
            if lowered == "primary":
                account_name = "ONEMIN_AI_API_KEY"
            else:
                match = re.fullmatch(r"fallback_?(\d+)", lowered.replace("-", "_").replace(" ", "_"))
                if match is not None:
                    account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{int(match.group(1))}"
                else:
                    account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{next_fallback}"
                    next_fallback += 1
        if account_name in seen:
            continue
        seen.add(account_name)
        names.append(account_name)
    return names


def raw_key_names(provider_name: str) -> list[str]:
    if provider_name != "onemin":
        return RAW_KEY_NAMES.get(provider_name, [])
    fallback_numbers: set[int] = set()
    for mapping in (os.environ, LOCAL_ENV, POLICY_ENV):
        for env_name in mapping:
            match = _ONEMIN_FALLBACK_ENV_RE.match(str(env_name or "").strip())
            if match is None:
                continue
            try:
                fallback_numbers.add(int(match.group(1)))
            except Exception:
                continue
    names = ["ONEMIN_AI_API_KEY"]
    names.extend(f"ONEMIN_AI_API_KEY_FALLBACK_{index}" for index in sorted(fallback_numbers))
    for account_name in _onemin_manifest_account_names():
        if account_name not in names:
            names.append(account_name)
    return names


def key_names_present(names: list[str]) -> list[str]:
    return [name for name in names if env_value(name)]


def resolved_onemin_slots() -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_env_names: set[str] = set()
    for env_name in raw_key_names("onemin"):
        key = env_value(env_name)
        if not key or env_name in seen_env_names or key in seen_keys:
            continue
        seen_env_names.add(env_name)
        seen_keys.add(key)
        slots.append({"env_name": env_name, "key": key})
    script_path = EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh"
    if script_path.exists():
        try:
            output = subprocess.check_output(
                ["bash", str(script_path), "--all"],
                text=True,
            )
        except Exception:
            output = ""
        synthetic_index = 0
        for raw in output.splitlines():
            key = str(raw or "").strip()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            synthetic_index += 1
            slots.append({"env_name": f"ONEMIN_RESOLVED_SLOT_{synthetic_index}", "key": key})
    return slots


def command_state(command_name: str) -> tuple[str, bool]:
    parts = shlex.split(str(command_name or "").strip() or "gemini")
    if not parts:
        return ("", False)
    resolved = shutil.which(parts[0]) or ""
    return (parts[0], bool(resolved))


def provider_order() -> list[str]:
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return ["magixai", "media_factory", "onemin"]
    values = [part.strip().lower().replace("-", "_") for part in raw.split(",") if part.strip()]
    filtered = [value for value in values if value not in {"local_raster", "markupgo", "ooda_compositor", "scene_contract_renderer", "pollinations"}]
    return filtered or ["magixai", "media_factory", "onemin"]


def text_provider_order() -> list[str]:
    raw = env_value("CHUMMER6_TEXT_PROVIDER_ORDER")
    if not raw:
        return ["ea"]
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return values or ["ea"]


def chummer6_skill_catalog_state() -> dict[str, object]:
    scripts_root = str(EA_ROOT / "scripts")
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    from bootstrap_chummer6_guide_skill import ensure_local_skill_payloads, required_skill_keys

    return ensure_local_skill_payloads(required_keys=required_skill_keys())


def provider_state(name: str) -> dict[str, object]:
    if name == "pollinations":
        return {
            "provider": name,
            "status": "disabled",
            "available": False,
            "raw_keys": [],
            "adapters": [],
            "detail": "Disabled. Chummer6 media must use real external render lanes.",
        }
    if name == "local_raster":
        return {
            "provider": name,
            "status": "disabled",
            "available": False,
            "raw_keys": [],
            "adapters": [],
            "detail": "Disabled. Chummer6 media must use a real provider.",
        }
    raw_keys = key_names_present(raw_key_names(name))
    adapters = key_names_present(ADAPTER_ENV_NAMES.get(name, []))
    if name == "gemini_vortex":
        command_name, cli_ready = command_state(env_value("EA_GEMINI_VORTEX_COMMAND") or "gemini")
        available = cli_ready
        status = "ready" if available else "cli_missing"
        detail = (
            f"Gemini Vortex structured generation is available through `{command_name}`."
            if available
            else f"Gemini Vortex CLI `{command_name}` was not found on PATH."
        )
        return {
            "provider": name,
            "status": status,
            "available": available,
            "raw_keys": raw_keys,
            "adapters": adapters,
            "detail": detail,
            "command": command_name,
            "model": env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-2.5-flash",
        }
    if name == "browseract":
        available = bool(raw_keys)
        status = "ready" if available else "missing_credentials"
        detail = "BrowserAct live automation is available." if available else "No BrowserAct key found in local env."
        return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}
    if name == "browseract_prompting_systems":
        browseract_ready = bool(key_names_present(RAW_KEY_NAMES.get("browseract", [])))
        helper_ready = (EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py").exists()
        effective_adapters = list(adapters)
        if helper_ready and "built_in_browseract_helper" not in effective_adapters:
            effective_adapters.append("built_in_browseract_helper")
        explicit_workflow = bool(env_value("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID"))
        query_workflow = bool(env_value("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY"))
        available = browseract_ready and helper_ready and (explicit_workflow or query_workflow)
        if explicit_workflow:
            status = "workflow_configured"
            detail = "BrowserAct is configured and a Prompting Systems refine workflow is pinned, but the workflow itself is not health-verified."
        elif available:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, but the Prompting Systems workflow still has to be resolved live from its query before it should be trusted."
        elif browseract_ready and helper_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no Prompting Systems workflow id/query or adapter is configured yet."
        elif browseract_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no Prompting Systems workflow/adapter is configured yet."
        else:
            status = "missing_browseract"
            detail = "No BrowserAct key found in local env."
        return {"provider": name, "status": status, "available": available, "raw_keys": key_names_present(RAW_KEY_NAMES.get('browseract', [])), "adapters": effective_adapters, "detail": detail}
    if name == "browseract_magixai":
        browseract_ready = bool(key_names_present(RAW_KEY_NAMES.get("browseract", [])))
        helper_ready = (EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py").exists()
        effective_adapters = list(adapters)
        if helper_ready and "built_in_browseract_helper" not in effective_adapters:
            effective_adapters.append("built_in_browseract_helper")
        explicit_workflow = bool(env_value("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_ID"))
        query_workflow = bool(env_value("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_QUERY"))
        available = browseract_ready and helper_ready and (explicit_workflow or query_workflow)
        if explicit_workflow:
            status = "workflow_configured"
            detail = "BrowserAct is configured and an AI Magicx render workflow is pinned, but the workflow itself is not health-verified."
        elif available:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, but the AI Magicx workflow still has to be resolved live from its query before it should be trusted."
        elif browseract_ready and helper_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no AI Magicx workflow id/query or adapter is configured yet."
        elif browseract_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no AI Magicx render workflow/adapter is configured yet."
        else:
            status = "missing_browseract"
            detail = "No BrowserAct key found in local env."
        return {"provider": name, "status": status, "available": available, "raw_keys": key_names_present(RAW_KEY_NAMES.get('browseract', [])), "adapters": effective_adapters, "detail": detail}
    if name == "magixai":
        available = bool(raw_keys or adapters)
        if available and raw_keys:
            status = "credential_only"
            detail = "AI Magicx credentials are present, but the raw image API lane still needs live route verification before it should be preferred."
        else:
            status = "not_configured"
            detail = "No AI Magicx credentials found."
        return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}
    if name == "media_factory":
        script_path = Path("/docker/fleet/repos/chummer-media-factory/scripts/render_guide_asset.py")
        configured_command = env_value("CHUMMER6_MEDIA_FACTORY_RENDER_COMMAND")
        command_name, cli_ready = command_state(configured_command or "python3")
        onemin_keys = key_names_present(raw_key_names("onemin"))
        resolved_slots = resolved_onemin_slots()
        available = bool((configured_command or script_path.exists()) and cli_ready and (onemin_keys or resolved_slots))
        if available:
            status = "ready"
            detail = "Media Factory render bridge is available and can hand guide renders to the 1min-backed media seam."
        elif configured_command or script_path.exists():
            status = "missing_onemin_keys"
            detail = "Media Factory render bridge exists, but no 1min keys are available for its current onemin-backed adapter."
        else:
            status = "not_configured"
            detail = "No Media Factory render bridge command is configured yet."
        effective_adapters = list(adapters)
        if script_path.exists() and "built_in_media_factory_bridge" not in effective_adapters:
            effective_adapters.append("built_in_media_factory_bridge")
        return {
            "provider": name,
            "status": status,
            "available": available,
            "raw_keys": onemin_keys,
            "adapters": effective_adapters,
            "detail": detail,
            "command": configured_command or str(script_path),
            "backing_provider": "onemin",
            "resolved_slot_count": len(resolved_slots),
        }
    if name == "onemin":
        resolved_slots = resolved_onemin_slots()
        available = bool(raw_keys or resolved_slots or adapters)
        if raw_keys or resolved_slots:
            status = "ready"
            detail = "Built-in 1min.AI image generation is available."
        elif adapters:
            status = "ready"
            detail = "A custom 1min render adapter is configured."
        else:
            status = "not_configured"
            detail = "No 1min.AI credentials or render adapter found."
        return {
            "provider": name,
            "status": status,
            "available": available,
            "raw_keys": raw_keys,
            "adapters": adapters,
            "detail": detail,
            "resolved_slot_count": len(resolved_slots),
        }
    available = bool(adapters)
    if available:
        status = "ready"
        detail = "A render adapter is configured."
    elif raw_keys:
        status = "credential_only"
        detail = "Credentials appear present, but no render command/URL template is configured yet."
    else:
        status = "not_configured"
        detail = "No credentials or render adapter found."
    return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}


def text_provider_state(name: str) -> dict[str, object]:
    normalized = str(name or "").strip().lower()
    if normalized in {"ea", "planner", "skill", "gemini", "gemini_vortex"}:
        gemini = provider_state("gemini_vortex")
        worker_ready = (EA_ROOT / "scripts" / "chummer6_guide_worker.py").exists()
        bootstrap_ready = (EA_ROOT / "scripts" / "bootstrap_chummer6_guide_skill.py").exists()
        try:
            skill_state = chummer6_skill_catalog_state()
        except Exception as exc:
            skill_state = {
                "status": "missing",
                "required_skill_keys": [],
                "registered_skill_keys": [],
                "missing_skill_keys": ["chummer6_skill_catalog"],
                "upserted_skill_keys": [],
                "error": f"{exc.__class__.__name__}:{exc}",
            }
        missing_skill_keys = [
            str(value).strip()
            for value in (skill_state.get("missing_skill_keys") or [])
            if str(value).strip()
        ]
        available = bool(gemini.get("available")) and worker_ready and bootstrap_ready and not missing_skill_keys
        if available:
            status = "ready"
            upserted = [
                str(value).strip()
                for value in (skill_state.get("upserted_skill_keys") or [])
                if str(value).strip()
            ]
            if upserted:
                detail = "EA planner brain can route Chummer6 prompt generation through the Gemini Vortex structured-generation tool, and missing Chummer6 skills were auto-registered locally."
            else:
                detail = "EA planner brain can route Chummer6 prompt generation through the Gemini Vortex structured-generation tool."
        else:
            status = "not_ready"
            if missing_skill_keys:
                detail = "EA text brain is missing required Chummer6 skill registrations."
            else:
                detail = "EA text brain is missing either Gemini Vortex, the worker, or the Chummer6 skill bootstrap."
        return {
            "provider": "ea",
            "status": status,
            "available": available,
            "detail": detail,
            "backing_provider": "gemini_vortex",
            "skill_catalog": skill_state,
        }
    return {
        "provider": normalized or "unknown",
        "status": "unknown",
        "available": False,
        "detail": "No readiness rule exists for this text provider alias. Chummer6 text generation is expected to run through EA only.",
    }


def main() -> int:
    providers = provider_order()
    states = [provider_state(name) for name in providers]
    text_providers = text_provider_order()
    text_states = [text_provider_state(name) for name in text_providers]
    result = {
        "provider_order": providers,
        "providers": states,
        "recommended_provider": next(
            (row["provider"] for row in states if row["status"] in PREFERRED_PROVIDER_STATUSES),
            next((row["provider"] for row in states if row["available"]), ""),
        ),
        "text_provider_order": text_providers,
        "text_providers": text_states,
        "recommended_text_provider": next((row["provider"] for row in text_states if row["available"]), ""),
    }
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
