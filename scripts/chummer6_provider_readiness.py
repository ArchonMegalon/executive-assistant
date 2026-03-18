#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
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


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


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
    return names


def key_names_present(names: list[str]) -> list[str]:
    return [name for name in names if env_value(name)]


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
            "model": env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-3-flash-preview",
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
            status = "ready"
            detail = "BrowserAct is configured and a Prompting Systems refine workflow is explicitly configured."
        elif available:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, and the Prompting Systems workflow will be resolved live from its configured query."
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
            status = "ready"
            detail = "BrowserAct is configured and an AI Magicx render workflow is explicitly configured."
        elif available:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, and the AI Magicx workflow will be resolved live from its configured query."
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
            status = "experimental_ready"
            detail = "AI Magicx credentials are present and the built-in API lane will be tried."
        else:
            status = "not_configured"
            detail = "No AI Magicx credentials found."
        return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}
    if name == "media_factory":
        script_path = Path("/docker/fleet/repos/chummer-media-factory/scripts/render_guide_asset.py")
        configured_command = env_value("CHUMMER6_MEDIA_FACTORY_RENDER_COMMAND")
        command_name, cli_ready = command_state(configured_command or "python3")
        onemin_keys = key_names_present(raw_key_names("onemin"))
        available = bool((configured_command or script_path.exists()) and cli_ready and onemin_keys)
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
        }
    if name == "onemin":
        available = bool(raw_keys or adapters)
        if raw_keys:
            status = "ready"
            detail = "Built-in 1min.AI image generation is available."
        elif adapters:
            status = "ready"
            detail = "A custom 1min render adapter is configured."
        else:
            status = "not_configured"
            detail = "No 1min.AI credentials or render adapter found."
        return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}
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
        available = bool(gemini.get("available")) and worker_ready and bootstrap_ready
        if available:
            status = "ready"
            detail = "EA planner brain can route Chummer6 prompt generation through the Gemini Vortex structured-generation tool."
        else:
            status = "not_ready"
            detail = "EA text brain is missing either Gemini Vortex, the worker, or the Chummer6 skill bootstrap."
        return {
            "provider": "ea",
            "status": status,
            "available": available,
            "detail": detail,
            "backing_provider": "gemini_vortex",
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
        "recommended_provider": next((row["provider"] for row in states if row["available"]), ""),
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
