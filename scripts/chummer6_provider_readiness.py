#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_provider_readiness.json")

RAW_KEY_NAMES = {
    "pollinations": [],
    "browseract": ["BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1", "BROWSERACT_API_KEY_FALLBACK_2", "BROWSERACT_API_KEY_FALLBACK_3"],
    "unmixr": ["UNMIXR_API_KEY"],
    "onemin": ["ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1", "ONEMIN_AI_API_KEY_FALLBACK_2", "ONEMIN_AI_API_KEY_FALLBACK_3"],
    "magixai": ["MAGIXAI_API_KEY", "AI_MAGICX_API_KEY", "AIMAGICX_API_KEY"],
    "markupgo": ["MARKUPGO_API_KEY"],
    "prompting_systems": ["PROMPTING_SYSTEMS_API_KEY"],
}

ADAPTER_ENV_NAMES = {
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


def key_names_present(names: list[str]) -> list[str]:
    return [name for name in names if env_value(name)]


def provider_order() -> list[str]:
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return ["browseract_magixai", "magixai", "onemin"]
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    filtered = [value for value in values if value not in {"local_raster", "markupgo", "ooda_compositor", "scene_contract_renderer", "pollinations"}]
    return filtered or ["browseract_magixai", "magixai", "onemin"]


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
    raw_keys = key_names_present(RAW_KEY_NAMES.get(name, []))
    adapters = key_names_present(ADAPTER_ENV_NAMES.get(name, []))
    if name == "browseract":
        available = bool(raw_keys)
        status = "ready" if available else "missing_credentials"
        detail = "BrowserAct live automation is available." if available else "No BrowserAct key found in EA env."
        return {"provider": name, "status": status, "available": available, "raw_keys": raw_keys, "adapters": adapters, "detail": detail}
    if name == "browseract_prompting_systems":
        browseract_ready = bool(key_names_present(RAW_KEY_NAMES.get("browseract", [])))
        helper_ready = (EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py").exists()
        effective_adapters = list(adapters)
        if helper_ready and "built_in_browseract_helper" not in effective_adapters:
            effective_adapters.append("built_in_browseract_helper")
        explicit_workflow = bool(env_value("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID"))
        available = browseract_ready and helper_ready and explicit_workflow
        if available:
            status = "ready"
            detail = "BrowserAct is configured and a Prompting Systems refine workflow is explicitly configured."
        elif browseract_ready and helper_ready:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, but no explicit Prompting Systems workflow ID is set yet."
        elif browseract_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no Prompting Systems workflow/adapter is configured yet."
        else:
            status = "missing_browseract"
            detail = "No BrowserAct key found in EA env."
        return {"provider": name, "status": status, "available": available, "raw_keys": key_names_present(RAW_KEY_NAMES.get('browseract', [])), "adapters": effective_adapters, "detail": detail}
    if name == "browseract_magixai":
        browseract_ready = bool(key_names_present(RAW_KEY_NAMES.get("browseract", [])))
        helper_ready = (EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py").exists()
        effective_adapters = list(adapters)
        if helper_ready and "built_in_browseract_helper" not in effective_adapters:
            effective_adapters.append("built_in_browseract_helper")
        explicit_workflow = bool(env_value("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_ID"))
        available = browseract_ready and helper_ready and explicit_workflow
        if available:
            status = "ready"
            detail = "BrowserAct is configured and an AI Magicx render workflow is explicitly configured."
        elif browseract_ready and helper_ready:
            status = "workflow_query_only"
            detail = "BrowserAct and the helper are configured, but no explicit AI Magicx render workflow ID is set yet."
        elif browseract_ready:
            status = "browseract_ready_missing_render_adapter"
            detail = "BrowserAct is configured, but no AI Magicx render workflow/adapter is configured yet."
        else:
            status = "missing_browseract"
            detail = "No BrowserAct key found in EA env."
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


def main() -> int:
    providers = provider_order()
    states = [provider_state(name) for name in providers]
    result = {
        "provider_order": providers,
        "providers": states,
        "recommended_provider": next((row["provider"] for row in states if row["available"]), ""),
    }
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
