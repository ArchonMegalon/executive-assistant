from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def _tts_plugin_options(
    *,
    payload: dict[str, object],
    voice_profile_ready: bool,
    runtime_secret_placeholder: Callable[[object], str],
    text: Callable[[object, str], str],
    browser_speech_tts_plugin_id: str,
    unmixr_tts_plugin_id: str,
    openvoice_tts_plugin_id: str,
    piper_fast_plugin_option: Callable[[], dict[str, object]],
    unmixr_plugin_option: Callable[..., dict[str, object]],
    voicewave_plugin_option: Callable[..., dict[str, object]],
    openvoice_plugin_option: Callable[..., dict[str, object]],
    unmixr_memorial_voice_id: Callable[[], str],
    openvoice_memorial_voice_id: Callable[[], str],
    voicewave_memorial_voice_label: Callable[[], str],
) -> list[dict[str, object]]:
    configured_voice_id = runtime_secret_placeholder(text(payload.get("tts_plugin_voice_id"), ""))
    unmixr_voice_id = configured_voice_id or unmixr_memorial_voice_id()
    voicewave_voice_id = configured_voice_id or voicewave_memorial_voice_label()
    return [
        piper_fast_plugin_option(),
        {
            "tts_plugin": browser_speech_tts_plugin_id,
            "tts_plugin_enabled": True,
            "tts_plugin_needs_clone": False,
            "tts_plugin_clone_capable": False,
            "tts_plugin_voice_id": "",
            "tts_plugin_label": "Browser Speech",
            "tts_plugin_description": "Verwendet die eingebaute SpeechSynthesisUtterance-Stimme des Browsers.",
        },
        unmixr_plugin_option(
            configured_voice_id=unmixr_voice_id,
            voice_profile_ready=bool(voice_profile_ready),
        ),
        voicewave_plugin_option(
            configured_voice_id=voicewave_voice_id,
            voice_profile_ready=bool(voice_profile_ready),
        ),
    ]


def _resolve_tts_plugin(
    *,
    payload: dict[str, object],
    options: list[dict[str, object]],
    safe_tts_plugin_id: Callable[[object], str],
    tts_plugin_default_id: str,
) -> tuple[str, dict[str, object]]:
    requested = safe_tts_plugin_id(payload.get("tts_plugin"))
    if not requested:
        requested = safe_tts_plugin_id(payload.get("tts_mode"))
    if not requested:
        requested = tts_plugin_default_id
    if requested:
        for option in options:
            if option.get("tts_plugin") != requested:
                continue
            return requested, option
    for option in options:
        if option.get("tts_plugin_enabled"):
            return str(option.get("tts_plugin") or tts_plugin_default_id), option
    if options:
        first = options[0]
        return safe_tts_plugin_id(first.get("tts_plugin")) or tts_plugin_default_id, first
    return tts_plugin_default_id, {
        "tts_plugin": tts_plugin_default_id,
        "tts_plugin_enabled": False,
        "tts_plugin_needs_clone": False,
        "tts_plugin_voice_id": "",
        "tts_plugin_label": "Unmixr Voice Clone",
        "tts_plugin_description": "Keine Voice-Konfiguration aktiv.",
    }


def _resolve_server_tts_plugin(
    *,
    payload: dict[str, object],
    options: list[dict[str, object]],
    resolve_tts_plugin: Callable[..., tuple[str, dict[str, object]]],
    safe_tts_plugin_id: Callable[[object], str],
    browser_speech_tts_plugin_id: str,
    tts_plugin_default_id: str,
) -> tuple[str, dict[str, object]]:
    selected_plugin, selected_option = resolve_tts_plugin(payload=payload, options=options)
    if selected_plugin != browser_speech_tts_plugin_id and bool(selected_option.get("tts_plugin_enabled")):
        return selected_plugin, selected_option
    for option in options:
        option_plugin = safe_tts_plugin_id(option.get("tts_plugin"))
        if option_plugin == browser_speech_tts_plugin_id:
            continue
        if bool(option.get("tts_plugin_enabled")):
            return option_plugin or tts_plugin_default_id, option
    return selected_plugin, selected_option


def _display_tts_plugin_label(
    *,
    option: dict[str, object],
    voice_label: str,
    safe_tts_plugin_id: Callable[[object], str],
    unmixr_tts_plugin_id: str,
    openvoice_tts_plugin_id: str,
    piper_fast_tts_plugin_id: str,
    browser_speech_tts_plugin_id: str,
) -> str:
    plugin_id = safe_tts_plugin_id(option.get("tts_plugin"))
    friendly_voice_label = str(voice_label or "").strip() or "Manfred"
    if plugin_id in {unmixr_tts_plugin_id, openvoice_tts_plugin_id}:
        return "Manfreds Stimme" if friendly_voice_label.lower().startswith("manfred") else f"{friendly_voice_label}s Stimme"
    if plugin_id == piper_fast_tts_plugin_id:
        return "Schnelle Gesprächsstimme"
    if plugin_id == browser_speech_tts_plugin_id:
        return "Browser-Stimme"
    return str(option.get("tts_plugin_label") or "Vorlesen").strip() or "Vorlesen"


def _tts_media_type(content_type: str, fallback: str = "audio/mpeg") -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized:
        return normalized
    return fallback


def _effective_tts_base_voice_variant(
    payload: dict[str, object],
    *,
    text: Callable[[object, str], str],
    safe_tts_plugin_id: Callable[[object], str],
    openvoice_tts_plugin_id: str,
) -> str:
    configured = text(payload.get("tts_base_voice_variant"), "").strip().lower()
    if configured:
        return configured
    plugin_id = safe_tts_plugin_id(payload.get("tts_plugin"))
    voice_id = text(payload.get("tts_plugin_voice_id"), "").strip().lower()
    if plugin_id == openvoice_tts_plugin_id and voice_id in {"manfredc", "manfredb24", "manfredsatz"}:
        return "balanced"
    return "default"


def _voice_config_path(
    slug: str,
    *,
    private_profile_dir: Callable[[], Path],
    safe_slug: Callable[[str], str],
) -> Path:
    safe = safe_slug(slug)
    return (private_profile_dir() / safe / "tts_voice.json").resolve()


def _load_voice_config(
    slug: str,
    *,
    tts_plugin_default_id: str,
    text: Callable[[object, str], str],
    private_profile_dir: Callable[[], Path],
    safe_slug: Callable[[str], str],
    safe_tts_plugin_id: Callable[[object], str],
    runtime_secret_placeholder: Callable[[object], str],
    float_between: Callable[..., float],
    unmixr_memorial_voice_id: Callable[[], str],
    openvoice_memorial_voice_id: Callable[[], str],
    public_voice_profile_summary: Callable[[str], dict[str, object]],
    tts_plugin_options: Callable[..., list[dict[str, object]]],
    resolve_tts_plugin: Callable[..., tuple[str, dict[str, object]]],
) -> dict[str, object]:
    default_config = {
        "tts_plugin": tts_plugin_default_id,
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "tts_plugin_voice_id": unmixr_memorial_voice_id(),
        "tts_base_voice_variant": "high",
        "tts_postprocess_profile": "",
        "consent_basis": "generic_or_owner_consented_voice",
        "notes": "Voice-Plugins fuer die Memorial-Interaktion.",
        "synthetic_voice_clone_of_memorial_person": False,
    }
    safe = safe_slug(slug)
    root = private_profile_dir().resolve()
    path = (root / safe / "tts_voice.json").resolve()
    if root in path.parents and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            persisted_tts_plugin = safe_tts_plugin_id(text(payload.get("tts_plugin"), text(payload.get("tts_mode"))))
            if not persisted_tts_plugin:
                persisted_tts_plugin = tts_plugin_default_id
            default_config.update(
                {
                    "tts_plugin": persisted_tts_plugin,
                    "tts_plugin_voice_id": runtime_secret_placeholder(text(payload.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"]))),
                    "voice_profile_id": runtime_secret_placeholder(text(payload.get("voice_profile_id"), str(default_config["voice_profile_id"]))),
                    "voice_label": text(payload.get("voice_label"), str(default_config["voice_label"])),
                    "lang": text(payload.get("lang"), str(default_config["lang"])),
                    "rate": float_between(payload.get("rate"), fallback=0.92, minimum=0.45, maximum=1.5),
                    "pitch": float_between(payload.get("pitch"), fallback=0.92, minimum=0.5, maximum=1.5),
                    "volume": float_between(payload.get("volume"), fallback=1.0, minimum=0.0, maximum=1.0),
                    "voice_name_hints": [
                        str(item).strip()
                        for item in (payload.get("voice_name_hints") or [])
                        if str(item).strip()
                    ][:8],
                    "tts_base_voice_variant": text(payload.get("tts_base_voice_variant"), text(default_config.get("tts_base_voice_variant"), "high")) or "high",
                    "tts_postprocess_profile": text(payload.get("tts_postprocess_profile"), ""),
                    "consent_basis": text(payload.get("consent_basis"), str(default_config["consent_basis"])),
                    "notes": text(payload.get("notes"), str(default_config["notes"])),
                    "voice_consent": dict(payload.get("voice_consent") or {}) if isinstance(payload.get("voice_consent"), dict) else dict(default_config.get("voice_consent") or {}),
                }
            )
    voice_profile_summary = public_voice_profile_summary(slug)
    default_config.update(voice_profile_summary)
    options = tts_plugin_options(
        payload=default_config,
        voice_profile_ready=bool(voice_profile_summary.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = resolve_tts_plugin(payload=default_config, options=options)
    default_config["tts_plugin"] = selected_plugin or tts_plugin_default_id
    default_config["tts_mode"] = default_config["tts_plugin"]
    default_config["tts_plugin_voice_id"] = runtime_secret_placeholder(text(selected_option.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"])))
    if not default_config["tts_plugin_voice_id"]:
        default_config["tts_plugin_voice_id"] = text(unmixr_memorial_voice_id(), "")
    default_config["tts_plugin_options"] = options
    return default_config


def _voice_config_to_public_payload(
    payload: dict[str, object],
    slug: str,
    *,
    text: Callable[[object, str], str],
    safe_tts_plugin_id: Callable[[object], str],
    float_between: Callable[..., float],
    openvoice_memorial_voice_id: Callable[[], str],
    tts_plugin_default_id: str,
) -> dict[str, object]:
    selected_plugin = safe_tts_plugin_id(text(payload.get("tts_plugin"), tts_plugin_default_id))
    if not selected_plugin:
        selected_plugin = tts_plugin_default_id
    safe_config = {
        "tts_plugin": selected_plugin,
        "voice_profile_id": text(payload.get("voice_profile_id"), f"tts-{slug}"),
        "voice_label": text(payload.get("voice_label"), "Austauschbare synthetische Stimme"),
        "lang": text(payload.get("lang"), "de-AT")[:16] or "de-AT",
        "rate": float_between(payload.get("rate"), fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": float_between(payload.get("pitch"), fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": float_between(payload.get("volume"), fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": [str(item).strip() for item in list(payload.get("voice_name_hints") or [])[:8] if str(item or "").strip()],
        "tts_plugin_voice_id": text(payload.get("tts_plugin_voice_id"), ""),
        "tts_base_voice_variant": text(payload.get("tts_base_voice_variant"), "high") or "high",
        "notes": text(payload.get("notes"), ""),
        "synthetic_voice_clone_of_memorial_person": False,
    }
    safe_config["tts_mode"] = selected_plugin
    safe_config["consent_basis"] = text(payload.get("consent_basis"), "generic_or_owner_consented_voice")
    if isinstance(payload.get("voice_consent"), dict):
        safe_config["voice_consent"] = dict(payload.get("voice_consent") or {})
    return safe_config


def _normalize_voice_name_hints_csv(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = [item.strip() for item in value.replace(",", "\n").splitlines()]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item).strip() for item in value]
    else:
        candidates = []
    return [item for item in candidates if item][:8]


def _normalize_voice_config_payload(
    payload: dict[str, object],
    *,
    text: Callable[[object, str], str],
    safe_tts_plugin_id: Callable[[object], str],
    float_between: Callable[..., float],
    tts_plugin_default_id: str,
    unmixr_memorial_voice_id: Callable[[], str],
    openvoice_memorial_voice_id: Callable[[], str],
) -> dict[str, object]:
    requested_plugin = safe_tts_plugin_id(text(payload.get("tts_plugin"), text(payload.get("tts_mode"), tts_plugin_default_id)))
    if not requested_plugin:
        requested_plugin = tts_plugin_default_id
    default_config = {
        "tts_mode": tts_plugin_default_id,
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "tts_plugin": tts_plugin_default_id,
        "tts_plugin_voice_id": unmixr_memorial_voice_id(),
        "tts_base_voice_variant": "high",
        "tts_postprocess_profile": "",
        "consent_basis": "generic_or_owner_consented_voice",
        "notes": "Voice-Plugins fuer die Memorial-Interaktion.",
    }
    default_config["tts_mode"] = requested_plugin
    default_config["tts_plugin"] = requested_plugin
    return {
        "tts_plugin": requested_plugin,
        "tts_plugin_voice_id": text(payload.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"])),
        "voice_profile_id": text(payload.get("voice_profile_id") if isinstance(payload, dict) else None, str(default_config["voice_profile_id"])),
        "voice_label": text(payload.get("voice_label") if isinstance(payload, dict) else None, str(default_config["voice_label"])),
        "lang": text(payload.get("lang") if isinstance(payload, dict) else None, str(default_config["lang"]))[:16] or "de-AT",
        "rate": float_between(payload.get("rate") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": float_between(payload.get("pitch") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": float_between(payload.get("volume") if isinstance(payload, dict) else None, fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": _normalize_voice_name_hints_csv(payload.get("voice_name_hints") if isinstance(payload, dict) else None),
        "tts_base_voice_variant": text(payload.get("tts_base_voice_variant") if isinstance(payload, dict) else None, str(default_config["tts_base_voice_variant"])) or "high",
        "tts_postprocess_profile": text(payload.get("tts_postprocess_profile") if isinstance(payload, dict) else None, ""),
        "consent_basis": text(payload.get("consent_basis") if isinstance(payload, dict) else None, str(default_config["consent_basis"])),
        "notes": text(payload.get("notes") if isinstance(payload, dict) else None, str(default_config["notes"])),
        "voice_consent": dict(payload.get("voice_consent") or {}) if isinstance(payload.get("voice_consent"), dict) else {},
        "tts_mode": requested_plugin,
    }


def _save_voice_config_payload(
    slug: str,
    payload: dict[str, object],
    *,
    text: Callable[[object, str], str],
    load_voice_config: Callable[[str], dict[str, object]],
    normalize_voice_config_payload: Callable[[dict[str, object]], dict[str, object]],
    voice_config_to_public_payload: Callable[[dict[str, object], str], dict[str, object]],
    tts_plugin_options: Callable[..., list[dict[str, object]]],
    public_voice_profile_summary: Callable[[str], dict[str, object]],
    resolve_tts_plugin: Callable[..., tuple[str, dict[str, object]]],
    tts_plugin_default_id: str,
    voice_config_path: Callable[[str], Path],
    write_json_atomic: Callable[[Path, dict[str, object]], None],
) -> None:
    existing_config = load_voice_config(slug)
    merged_payload = {
        "tts_plugin": existing_config.get("tts_plugin"),
        "tts_mode": existing_config.get("tts_mode"),
        "tts_plugin_voice_id": existing_config.get("tts_plugin_voice_id"),
        "voice_profile_id": existing_config.get("voice_profile_id"),
        "voice_label": existing_config.get("voice_label"),
        "lang": existing_config.get("lang"),
        "rate": existing_config.get("rate"),
        "pitch": existing_config.get("pitch"),
        "volume": existing_config.get("volume"),
        "voice_name_hints": list(existing_config.get("voice_name_hints") or []),
        "tts_base_voice_variant": existing_config.get("tts_base_voice_variant"),
        "tts_postprocess_profile": existing_config.get("tts_postprocess_profile"),
        "consent_basis": existing_config.get("consent_basis"),
        "notes": existing_config.get("notes"),
        "voice_consent": dict(existing_config.get("voice_consent") or {}),
    }
    merged_payload.update(dict(payload or {}))
    normalized_config = normalize_voice_config_payload(merged_payload)
    stored = voice_config_to_public_payload(normalized_config, slug)
    if text(normalized_config.get("tts_postprocess_profile"), ""):
        stored["tts_postprocess_profile"] = text(normalized_config.get("tts_postprocess_profile"), "")
    options = tts_plugin_options(payload=stored, voice_profile_ready=bool(public_voice_profile_summary(slug=slug).get("voice_profile_ready")))
    selected_plugin, selected_option = resolve_tts_plugin(payload=stored, options=options)
    selected_plugin = selected_plugin or tts_plugin_default_id
    selected_option = dict(selected_option)
    stored["tts_plugin"] = selected_plugin
    stored["tts_mode"] = selected_plugin
    selected_voice_id = text(selected_option.get("tts_plugin_voice_id"), str(stored.get("tts_plugin_voice_id")))
    if not selected_voice_id:
        selected_voice_id = text(stored.get("tts_plugin_voice_id"), "")
    stored["tts_plugin_voice_id"] = selected_voice_id
    write_json_atomic(voice_config_path(slug), stored)
