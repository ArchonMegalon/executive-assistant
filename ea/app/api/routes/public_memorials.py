from __future__ import annotations

import html
import json
import hmac
import mimetypes
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

import requests

from app.services.brain_catalog import DEFAULT_PUBLIC_MODEL
from app.services.memorial_openvoice import (
    OPENVOICE_TTS_PLUGIN_ID,
    openvoice_clone_request,
    openvoice_memorial_voice_id,
    openvoice_plugin_option,
    openvoice_synthesize_request_with_variant,
)
from app.services.public_clickrank import clickrank_head_snippet, request_hostname
from app.services.responses_upstream import ResponsesUpstreamError, generate_text
from app.services.memorial_voice_profile import build_memorial_voice_profile, load_memorial_voice_profile

router = APIRouter(tags=["public-memorials"])

_MAX_SPEECH_UPLOAD_BYTES = 12 * 1024 * 1024
_ONEMIN_SPEECH_AUDIO_TYPES = {
    "audio/x-m4a",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/flac",
}
_BROWSER_SPEECH_TTS_PLUGIN_ID = "browser_speech_synthesis"
_TTS_PLUGIN_DEFAULT_ID = _BROWSER_SPEECH_TTS_PLUGIN_ID
_LEGACY_ELEVENLABS_TTS_PLUGIN_ID = "elevenlabs_memorial_voice_clone"
_TTS_MAX_CLONE_FILES = 3
_TTS_MAX_TEXT_LEN = 3000


def _memorial_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_MEMORIAL_DIR") or "/mnt/pcloud/EA/public_memorials")).expanduser()


def _resolved_memorial_root() -> Path:
    return _memorial_dir().resolve()


def _private_profile_dir() -> Path:
    return Path(str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or "/mnt/pcloud/EA/private_memorial_profiles")).expanduser()


def _safe_slug(slug: str) -> str:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return safe


def _memorial_bundle(slug: str) -> Path:
    root = _resolved_memorial_root()
    bundle_dir = (root / _safe_slug(slug)).resolve()
    if bundle_dir != root and root not in bundle_dir.parents:
        raise HTTPException(status_code=404, detail="memorial_not_found")
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return bundle_dir


def _manifest_path(slug: str) -> Path:
    path = _memorial_bundle(slug) / "memorial.json"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return path


def _load_memorial(slug: str) -> dict[str, object]:
    try:
        payload = json.loads(_manifest_path(slug).read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="memorial_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="memorial_payload_invalid")
    return payload


def _collect_memorial_write_tokens(payload: dict[str, object]) -> list[str]:
    tokens: list[str] = []
    raw_values: list[object] = []
    raw_values.extend(
        [
            payload.get("write_token"),
            payload.get("write_tokens"),
            payload.get("admin_token"),
            payload.get("management_token"),
            payload.get("owner_token"),
        ]
    )
    env_token = str(os.getenv("EA_PUBLIC_MEMORIAL_WRITE_TOKEN") or "").strip()
    if env_token:
        raw_values.append(env_token)
    for raw_value in raw_values:
        if raw_value is None:
            continue
        if isinstance(raw_value, (list, tuple, set)):
            values = [str(item).strip() for item in raw_value]
        else:
            values = [str(raw_value).strip()]
        for value in values:
            if value and value not in tokens:
                tokens.append(value)
    return tokens


def _require_public_memorial_write_access(*, slug: str, request: Request, memorial: dict[str, object] | None = None) -> None:
    payload = memorial or _load_memorial(slug)
    allowed_tokens = _collect_memorial_write_tokens(payload)
    if not allowed_tokens:
        return
    provided = str(
        request.headers.get("x-memorial-write-token")
        or request.headers.get("x-memorial-admin-token")
        or request.query_params.get("memorial_write_token")
        or request.query_params.get("token")
        or ""
    ).strip()
    if not provided:
        raise HTTPException(status_code=403, detail="memorial_write_unauthorized")
    for candidate in allowed_tokens:
        if len(provided) == len(candidate) and hmac.compare_digest(provided, candidate):
            return
    raise HTTPException(status_code=403, detail="memorial_write_unauthorized")


def _asset_file(slug: str, asset_path: str) -> Path:
    bundle_dir = _memorial_bundle(slug)
    candidate = (bundle_dir / str(asset_path or "")).resolve()
    if candidate != bundle_dir.resolve() and bundle_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    return candidate


def _text(value: object, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in (value or []) if isinstance(item, dict)]


def _normalize_memorial_text_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_values = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []
    values: list[str] = []
    for raw_value in raw_values:
        normalized = str(raw_value or "").strip()
        if not normalized:
            continue
        if normalized not in values:
            values.append(normalized)
    return values


def _normalize_memorial_chat_model_plugin_values(value: object) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    raw_items: list[object] = []
    if isinstance(value, (str, dict)):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return entries
    for raw_item in raw_items:
        if isinstance(raw_item, (list, tuple, set)):
            entries.extend(_normalize_memorial_chat_model_plugin_values(list(raw_item)))
            continue
        if isinstance(raw_item, dict):
            model = _text(
                raw_item.get("model"),
                _text(
                    raw_item.get("id"),
                    _text(raw_item.get("name"), _text(raw_item.get("value"), "")),
                ),
            )
            if not model:
                model = _text(raw_item.get("llm_model"), "")
            if not model:
                continue
            label = _text(raw_item.get("label"), _text(raw_item.get("name"), model))
            normalized_model = model.strip()
            if normalized_model and (normalized_model, label) not in entries:
                entries.append((normalized_model, label))
            continue
        if isinstance(raw_item, str):
            for model in _normalize_memorial_text_list(raw_item):
                normalized_model = str(model or "").strip()
                if normalized_model and (normalized_model, normalized_model) not in entries:
                    entries.append((normalized_model, normalized_model))
            continue
        normalized_model = str(raw_item or "").strip()
        if normalized_model and (normalized_model, normalized_model) not in entries:
            entries.append((normalized_model, normalized_model))
    return entries


def _normalize_memorial_chat_model_values(value: object) -> list[str]:
    plugin_values = [item[0] for item in _normalize_memorial_chat_model_plugin_values(value)]
    if plugin_values:
        return plugin_values
    return _normalize_memorial_text_list(value)


def _memorial_chat_model_sources(payload: dict[str, object], private_profile: dict[str, object]) -> list[dict[str, object]]:
    sources = [payload, private_profile]
    profile_section = private_profile.get("memorial_chat")
    if isinstance(profile_section, dict):
        sources.append(profile_section)
    return [dict(item) for item in sources if isinstance(item, dict)]


def _collect_memorial_chat_models(payload: dict[str, object], private_profile: dict[str, object]) -> list[str]:
    raw_candidates: list[object] = []
    for source in _memorial_chat_model_sources(payload, private_profile):
        raw_candidates.extend(
            [
                source.get("chat_model_plugins"),
                source.get("chat_models"),
                source.get("chat_model_catalog"),
                source.get("llm_chat_models"),
            ]
        )
    raw_candidates.append(os.getenv("EA_PUBLIC_MEMORIAL_CHAT_MODELS", ""))
    models: list[str] = []
    for raw_candidate in raw_candidates:
        for candidate in _normalize_memorial_chat_model_values(raw_candidate):
            if candidate not in models:
                models.append(candidate)
    if not models:
        fallback = _text(os.getenv("EA_PUBLIC_MEMORIAL_CHAT_MODEL"), "")
        if fallback:
            models.append(fallback)
    if not models:
        models.append(DEFAULT_PUBLIC_MODEL)
    return models


def _collect_memorial_chat_model_options(
    payload: dict[str, object],
    private_profile: dict[str, object],
    models: list[str],
) -> list[dict[str, str]]:
    model_labels: dict[str, str] = {}
    for source in _memorial_chat_model_sources(payload, private_profile):
        for key in ("chat_model_plugins", "chat_models", "chat_model_catalog", "llm_chat_models"):
            for model, label in _normalize_memorial_chat_model_plugin_values(source.get(key)):
                if model in models and model not in model_labels:
                    model_labels[model] = label or model
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for model in models:
        if model in seen:
            continue
        seen.add(model)
        options.append({"value": model, "label": model_labels.get(model, model)})
    return options


def _resolve_memorial_chat_default_model(payload: dict[str, object], private_profile: dict[str, object], models: list[str]) -> str:
    for source in _memorial_chat_model_sources(payload, private_profile):
        for key in ("chat_model_default", "default_chat_model", "memorial_chat_default_model", "llm_default_model"):
            value = _text(source.get(key), "")
            if not value:
                continue
            if value in models:
                return value
    fallback = _text(os.getenv("EA_PUBLIC_MEMORIAL_CHAT_MODEL"), "")
    if fallback and (not models or fallback in models):
        return fallback
    return models[0] if models else DEFAULT_PUBLIC_MODEL


def _resolve_memorial_chat_model(
    payload: dict[str, object],
    private_profile: dict[str, object],
    requested_model: str | None,
) -> tuple[str, list[str], str]:
    models = _collect_memorial_chat_models(payload, private_profile)
    default_model = _resolve_memorial_chat_default_model(payload, private_profile, models)
    requested = _text(requested_model, "")
    selected = requested or default_model
    if requested and requested not in models:
        raise HTTPException(status_code=400, detail="invalid_llm_model")
    return selected, models, default_model


def _load_private_profile(slug: str) -> dict[str, object]:
    safe = _safe_slug(slug)
    root = _private_profile_dir().resolve()
    path = (root / safe / "llm_profile_notes.json").resolve()
    if root not in path.parents or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _public_voice_profile_summary(slug: str) -> dict[str, object]:
    profile = load_memorial_voice_profile(slug=slug)
    if not profile:
        return {
            "voice_profile_ready": False,
            "voice_profile_policy": {
                "voice_cloning_supported": False,
                "voice_cloning_policy": "safe_profile_only",
            },
            "voice_profile_sources": {"ready": 0},
        }
    source_counts = dict(profile.get("source_counts") or {})
    policy = dict(profile.get("policy") or {})
    audio_assets = [dict(item) for item in (profile.get("audio_assets") or []) if isinstance(item, dict)]
    ready_sources = int(source_counts.get("processed", 0) or 0)
    return {
        "voice_profile_ready": ready_sources > 0,
        "voice_profile_manifest_version": str(profile.get("manifest_version") or "1"),
        "voice_profile_slug": str(profile.get("slug") or ""),
        "voice_profile_generated_at": str(profile.get("generated_at") or ""),
        "voice_profile_policy": {
            "voice_cloning_supported": bool(policy.get("voice_cloning_supported") is True),
            "voice_cloning_policy": str(policy.get("voice_cloning_policy") or ""),
            "notes": str(policy.get("notes") or ""),
        },
        "voice_profile_sources": {
            "ready": int(source_counts.get("processed", 0) or 0),
            "failed": int(source_counts.get("failed", 0) or 0),
            "total": len(audio_assets),
            "public_clips": int(source_counts.get("public_clips", 0) or 0),
            "youtube_urls": int(source_counts.get("youtube_urls", 0) or 0),
            "youtube_downloads": int(source_counts.get("youtube_downloads", 0) or 0),
        },
        "voice_profile_sample_assets": [
            {k: item.get(k) for k in ("kind", "source_label", "analysis_status", "filename", "duration_seconds", "size_bytes") if k in item}
            for item in audio_assets[:4]
        ],
    }


def _normalize_tts_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()[:_TTS_MAX_TEXT_LEN]


def _safe_tts_plugin_id(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized == _LEGACY_ELEVENLABS_TTS_PLUGIN_ID:
        return _TTS_PLUGIN_DEFAULT_ID
    return normalized


def _tts_plugin_options(*, payload: dict[str, object], voice_profile_ready: bool) -> list[dict[str, object]]:
    configured_voice_id = _text(payload.get("tts_plugin_voice_id"), openvoice_memorial_voice_id())
    return [
        {
            "tts_plugin": _BROWSER_SPEECH_TTS_PLUGIN_ID,
            "tts_plugin_enabled": True,
            "tts_plugin_needs_clone": False,
            "tts_plugin_clone_capable": False,
            "tts_plugin_voice_id": "",
            "tts_plugin_label": "Browser Speech",
            "tts_plugin_description": "Verwendet die eingebaute SpeechSynthesisUtterance-Stimme des Browsers.",
        },
        openvoice_plugin_option(
            configured_voice_id=configured_voice_id,
            voice_profile_ready=bool(voice_profile_ready),
        )
    ]


def _resolve_tts_plugin(*, payload: dict[str, object], options: list[dict[str, object]]) -> tuple[str, dict[str, object]]:
    requested = _safe_tts_plugin_id(payload.get("tts_plugin"))
    if not requested:
        requested = _safe_tts_plugin_id(payload.get("tts_mode"))
    if not requested:
        requested = _TTS_PLUGIN_DEFAULT_ID
    if requested:
        for option in options:
            if option.get("tts_plugin") != requested:
                continue
            return requested, option
    for option in options:
        if option.get("tts_plugin_enabled"):
            return str(option.get("tts_plugin") or _TTS_PLUGIN_DEFAULT_ID), option
    if options:
        first = options[0]
        return _safe_tts_plugin_id(first.get("tts_plugin")) or _TTS_PLUGIN_DEFAULT_ID, first
    return _TTS_PLUGIN_DEFAULT_ID, {
        "tts_plugin": _TTS_PLUGIN_DEFAULT_ID,
        "tts_plugin_enabled": False,
        "tts_plugin_needs_clone": False,
        "tts_plugin_voice_id": "",
        "tts_plugin_label": "OpenVoice Local Clone",
        "tts_plugin_description": "Keine Voice-Konfiguration aktiv.",
    }


def _tts_media_type(content_type: str, fallback: str = "audio/mpeg") -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized:
        return normalized
    return fallback


def _profile_clip_assets_for_memorial(*, slug: str) -> list[Path]:
    summary = load_memorial_voice_profile(slug=slug)
    profile_root = (_private_profile_dir() / _safe_slug(slug)).resolve()
    assets: list[Path] = []
    if not isinstance(summary, dict):
        return assets
    for item in _list_of_dicts(summary.get("audio_assets")):
        if _text(item.get("analysis_status"), "failed").lower() != "ok":
            continue
        relpath = _text(item.get("asset_relpath"), "")
        if not relpath:
            continue
        candidate = (profile_root / relpath).resolve()
        if profile_root not in candidate.parents and candidate != profile_root:
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        if not candidate.name.lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm")):
            continue
        assets.append(candidate)
    return assets


def _openvoice_clone_from_memorial(*, slug: str, voice_label: str) -> str:
    sample_paths = _profile_clip_assets_for_memorial(slug=slug)
    if not sample_paths:
        raise HTTPException(status_code=400, detail="voice_profile_no_samples")
    usable_sample_paths = sample_paths[:_TTS_MAX_CLONE_FILES]
    return openvoice_clone_request(slug=slug, voice_label=voice_label, sample_paths=usable_sample_paths)


def _float_between(value: object, *, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def _load_voice_config(slug: str) -> dict[str, object]:
    default_config = {
        "tts_plugin": _TTS_PLUGIN_DEFAULT_ID,
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "tts_plugin_voice_id": openvoice_memorial_voice_id(),
        "consent_basis": "generic_or_owner_consented_voice",
        "notes": "Voice-Plugins fuer die Memorial-Interaktion.",
        "synthetic_voice_clone_of_memorial_person": False,
    }
    safe = _safe_slug(slug)
    root = _private_profile_dir().resolve()
    path = (root / safe / "tts_voice.json").resolve()
    if root in path.parents and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            persisted_tts_plugin = _safe_tts_plugin_id(_text(payload.get("tts_plugin"), _text(payload.get("tts_mode"))))
            if not persisted_tts_plugin:
                persisted_tts_plugin = _TTS_PLUGIN_DEFAULT_ID
            default_config.update(
                {
                    "tts_plugin": persisted_tts_plugin,
                    "tts_plugin_voice_id": _text(payload.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"])),
                    "voice_profile_id": _text(payload.get("voice_profile_id"), str(default_config["voice_profile_id"])),
                    "voice_label": _text(payload.get("voice_label"), str(default_config["voice_label"])),
                    "lang": _text(payload.get("lang"), str(default_config["lang"])),
                    "rate": _float_between(payload.get("rate"), fallback=0.92, minimum=0.45, maximum=1.5),
                    "pitch": _float_between(payload.get("pitch"), fallback=0.92, minimum=0.5, maximum=1.5),
                    "volume": _float_between(payload.get("volume"), fallback=1.0, minimum=0.0, maximum=1.0),
                    "voice_name_hints": [
                        str(item).strip()
                        for item in (payload.get("voice_name_hints") or [])
                        if str(item).strip()
                    ][:8],
                    "consent_basis": _text(payload.get("consent_basis"), str(default_config["consent_basis"])),
                    "notes": _text(payload.get("notes"), str(default_config["notes"])),
                }
            )
    voice_profile_summary = _public_voice_profile_summary(slug)
    default_config.update(voice_profile_summary)
    tts_options = _tts_plugin_options(
        payload=default_config,
        voice_profile_ready=bool(voice_profile_summary.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = _resolve_tts_plugin(payload=default_config, options=tts_options)
    default_config["tts_plugin"] = selected_plugin or _TTS_PLUGIN_DEFAULT_ID
    default_config["tts_mode"] = default_config["tts_plugin"]
    default_config["tts_plugin_voice_id"] = _text(selected_option.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"]))
    if not default_config["tts_plugin_voice_id"]:
        default_config["tts_plugin_voice_id"] = _text(openvoice_memorial_voice_id(), "")
    default_config["tts_plugin_options"] = tts_options
    return default_config


def _voice_config_path(slug: str) -> Path:
    safe = _safe_slug(slug)
    return (_private_profile_dir() / safe / "tts_voice.json").resolve()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _safe_voice_name_hints(value: object) -> list[str]:
    hints: list[str] = []
    for item in (value if isinstance(value, list) else []):
        normalized = str(item or "").strip()
        if normalized:
            hints.append(normalized)
    return hints[:8]


def _voice_config_to_public_payload(payload: dict[str, object], slug: str) -> dict[str, object]:
    selected_plugin = _safe_tts_plugin_id(_text(payload.get("tts_plugin"), _TTS_PLUGIN_DEFAULT_ID))
    if not selected_plugin:
        selected_plugin = _TTS_PLUGIN_DEFAULT_ID
    safe_config = {
        "tts_plugin": selected_plugin,
        "voice_profile_id": _text(payload.get("voice_profile_id"), f"tts-{slug}"),
        "voice_label": _text(payload.get("voice_label"), "Austauschbare synthetische Stimme"),
        "lang": _text(payload.get("lang"), "de-AT")[:16] or "de-AT",
        "rate": _float_between(payload.get("rate"), fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": _float_between(payload.get("pitch"), fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": _float_between(payload.get("volume"), fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": _safe_voice_name_hints(payload.get("voice_name_hints")),
        "tts_plugin_voice_id": _text(payload.get("tts_plugin_voice_id"), openvoice_memorial_voice_id()),
        "notes": _text(payload.get("notes"), ""),
        "synthetic_voice_clone_of_memorial_person": False,
    }
    safe_config["tts_mode"] = selected_plugin
    safe_config["consent_basis"] = _text(payload.get("consent_basis"), "generic_or_owner_consented_voice")
    return safe_config


def _normalize_voice_name_hints_csv(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = [item.strip() for item in value.replace(",", "\n").splitlines()]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item).strip() for item in value]
    else:
        candidates = []
    return [item for item in candidates if item][:8]


def _normalize_voice_config_payload(payload: dict[str, object]) -> dict[str, object]:
    requested_plugin = _safe_tts_plugin_id(_text(payload.get("tts_plugin"), _text(payload.get("tts_mode"), _TTS_PLUGIN_DEFAULT_ID)))
    if not requested_plugin:
        requested_plugin = _TTS_PLUGIN_DEFAULT_ID
    default_config = {
        "tts_mode": _TTS_PLUGIN_DEFAULT_ID,
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "tts_plugin": _TTS_PLUGIN_DEFAULT_ID,
        "tts_plugin_voice_id": openvoice_memorial_voice_id(),
        "consent_basis": "generic_or_owner_consented_voice",
        "notes": "Voice-Plugins fuer die Memorial-Interaktion.",
    }
    default_config["tts_mode"] = requested_plugin
    default_config["tts_plugin"] = requested_plugin
    return {
        "tts_plugin": requested_plugin,
        "tts_plugin_voice_id": _text(payload.get("tts_plugin_voice_id"), str(default_config["tts_plugin_voice_id"])),
        "voice_profile_id": _text(payload.get("voice_profile_id") if isinstance(payload, dict) else None, str(default_config["voice_profile_id"])),
        "voice_label": _text(payload.get("voice_label") if isinstance(payload, dict) else None, str(default_config["voice_label"])),
        "lang": _text(payload.get("lang") if isinstance(payload, dict) else None, str(default_config["lang"]))[:16] or "de-AT",
        "rate": _float_between(payload.get("rate") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": _float_between(payload.get("pitch") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": _float_between(payload.get("volume") if isinstance(payload, dict) else None, fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": _normalize_voice_name_hints_csv(payload.get("voice_name_hints") if isinstance(payload, dict) else None),
        "consent_basis": _text(payload.get("consent_basis") if isinstance(payload, dict) else None, str(default_config["consent_basis"])),
        "notes": _text(payload.get("notes") if isinstance(payload, dict) else None, str(default_config["notes"])),
        "tts_mode": requested_plugin,
    }


def _normalize_voice_build_payload(payload: dict[str, object]) -> tuple[list[str], str, int]:
    raw_urls = payload.get("youtube_urls") or payload.get("youtube_links") or payload.get("youtube")
    url_candidates: list[str] = []
    if isinstance(raw_urls, str):
        url_candidates.extend([item.strip() for item in raw_urls.replace(",", "\n").splitlines() if item.strip()])
    elif isinstance(raw_urls, (list, tuple, set)):
        for raw in raw_urls:
            normalized = str(raw or "").strip()
            if normalized:
                url_candidates.append(normalized)
    raw_limit = payload.get("youtube_limit")
    try:
        youtube_limit = int(raw_limit) if raw_limit is not None else 5
    except (TypeError, ValueError):
        youtube_limit = 5
    youtube_limit = max(1, min(youtube_limit, 12))
    query = _text(payload.get("youtube_query"), _text(payload.get("query"), _text(payload.get("search", ""))))
    return list(dict.fromkeys(url_candidates)), query, youtube_limit


def _compact_public_facts(payload: dict[str, object]) -> list[str]:
    facts: list[str] = []
    for card in _list_of_dicts(payload.get("memory_cards")):
        title = _text(card.get("title"))
        body = _text(card.get("body"))
        if title and body:
            facts.append(f"{title}: {body}")
    for note in _list_of_dicts(payload.get("source_grounded_profile")):
        trait = _text(note.get("trait"))
        evidence = _text(note.get("evidence"))
        if trait and evidence:
            facts.append(f"{trait}: {evidence}")
    return facts[:8]


def _save_voice_config_payload(slug: str, payload: dict[str, object]) -> None:
    stored = _voice_config_to_public_payload(_normalize_voice_config_payload(payload), slug=slug)
    tts_options = _tts_plugin_options(payload=stored, voice_profile_ready=bool(_public_voice_profile_summary(slug=slug).get("voice_profile_ready")))
    selected_plugin, selected_option = _resolve_tts_plugin(payload=stored, options=tts_options)
    selected_plugin = selected_plugin or _TTS_PLUGIN_DEFAULT_ID
    selected_option = dict(selected_option)
    stored["tts_plugin"] = selected_plugin
    stored["tts_mode"] = selected_plugin
    selected_voice_id = _text(selected_option.get("tts_plugin_voice_id"), str(stored.get("tts_plugin_voice_id")))
    if not selected_voice_id:
        selected_voice_id = _text(stored.get("tts_plugin_voice_id"), "")
    stored["tts_plugin_voice_id"] = selected_voice_id
    _write_json_atomic(_voice_config_path(slug=slug), stored)


def _collect_memorial_public_audio_paths(payload: dict[str, object], slug: str) -> list[Path]:
    seen: set[str] = set()
    paths: list[Path] = []
    for clip in _list_of_dicts(payload.get("audio_clips")):
        relpath = _text(clip.get("asset_relpath"))
        if not relpath:
            continue
        try:
            path = _asset_file(slug=slug, asset_path=relpath)
        except HTTPException:
            continue
        normalized = str(path.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(path)
    return paths


def _memorial_chat_source_labels(payload: dict[str, object]) -> list[str]:
    return [
        label
        for label in (
            "Originalaufnahme: Hanusch Krankenhaus",
            *[_text(source.get("label")) for source in _list_of_dicts(payload.get("external_sources"))],
        )
        if label
    ][:4]


def _memorial_chat_fallback_answer(
    payload: dict[str, object],
    question: str,
    private_profile: dict[str, object],
    *,
    llm_model: str = "",
    fallback_reason: str = "",
) -> dict[str, object]:
    person_name = _text(payload.get("person_name"), "Manfred")
    normalized_question = " ".join(str(question or "").strip().split())
    if not normalized_question:
        raise HTTPException(status_code=400, detail="question_missing")
    if len(normalized_question) > 1200:
        raise HTTPException(status_code=400, detail="question_too_long")
    lowered = normalized_question.lower()
    facts = _compact_public_facts(payload)
    private_notes = _list_of_dicts(private_profile.get("family_context_notes"))
    source_labels = _memorial_chat_source_labels(payload)
    if any(token in lowered for token in ("bist du", "sprichst du", "lebst du", "wirklich")):
        body = (
            "Ich bin hier als Erinnerung ansprechbar, nicht als Beweis, dass ich wirklich da bin. "
            "Wenn du meine Stimme hoerst oder meine Worte liest, dann soll es dir nahe sein, aber du darfst dabei klar bleiben: "
            "Das hier ist aus Aufnahmen, Quellen und euren Erinnerungen zusammengesetzt."
        )
    elif any(token in lowered for token in ("mutter", "mama", "allein", "einsam")):
        body = (
            "Deine Mutter hat gewusst, was in einem Haushalt zu tun ist. Ich war der, der draussen Verantwortung getragen hat, "
            "und daheim musste eben auch Ordnung sein. Hemden buegeln, Fenster putzen, Kinder, das faellt nicht von allein. "
            "Heute wird so getan, als waere das alles gleich verteilt gewesen. So habe ich das nicht gesehen."
        )
    elif any(token in lowered for token in ("schach", "familie")):
        body = (
            "Das Schach soll in der Familie bleiben. Nicht weil es irgendein grosses Symbol sein muss, "
            "sondern weil daran etwas von mir haengt. Behalt es. Gib darauf acht. "
            "Familie war nie einfach, aber manche Dinge sollen nicht verlorengehen."
        )
    elif any(token in lowered for token in ("haushalt", "hemden", "buegel", "bügel", "fenster", "putz", "putzen", "frau", "ehefrau", "ernaehrer", "ernährer", "kindererziehung")) and private_notes:
        body = (
            "Ich habe meinen Teil getan, indem ich fuer die Familie gesorgt habe. "
            "Im Haus muss jemand schauen, dass die Dinge ordentlich sind, und das war fuer mich die Aufgabe der Frau. "
            "Kindererziehung, Hemden, Fenster, der ganze Haushalt: Das war nicht der Bereich, in dem ich mich dauernd erklaeren wollte. "
            "Wenn man versorgt wird, kann man auch erwarten, dass daheim etwas funktioniert."
        )
    elif any(token in lowered for token in ("mfg", "partei", "politik", "corona", "impf", "auslaender", "ausländer", "migration", "fremde", "institution")) and private_notes:
        if any(token in lowered for token in ("corona", "covid", "impf", "arzt", "aerzte", "ärzte", "pharma")):
            body = (
                "Bei Corona habe ich mir nicht von Aerzten und Pharmafirmen vorschreiben lassen wollen, was richtig ist. "
                "Die haben ihre Interessen, und ich war nicht bereit, einfach brav zu nicken, nur weil ein Arzt es sagt. "
                "Ich habe mir eingebildet, ich sehe da klarer als viele andere. Wenn mir jemand damit kam, dass die Experten es besser wissen, "
                "dann war fuer mich das Gespraech meistens schon erledigt."
            )
        else:
            body = (
                "Ich habe mir nicht gern von oben erklaeren lassen, was ich zu denken habe. "
                "Diese ganzen Institutionen, Parteien und Experten, da war viel dabei, dem ich nicht getraut habe. "
                "Bei Zuwanderung war ich hart, ja. Ich habe oft zuerst gesehen, was mich stoert und was sich fuer mich falsch entwickelt. "
                "Und wenn mir jemand deswegen Vorhaltungen gemacht hat, dann habe ich erst recht zugemacht."
            )
    elif any(token in lowered for token in ("kind", "kinder", "geschlagen", "schlagen", "erwachsener", "erwachsene", "strafe", "disziplin")) and private_notes:
        body = (
            "Ein Kind muss lernen, wo die Grenze ist. So haette ich das gesehen. "
            "Wenn es so weit kommt, dann ist vorher schon genug passiert, und dann soll man nicht so tun, "
            "als waere der Erwachsene aus heiterem Himmel der Schuldige. Heute reden alle schnell von Gewalt, "
            "aber keiner fragt, was das Kind vorher aufgefuehrt hat. Das war meine Haltung, und davon waere ich nicht leicht abgerueckt."
        )
    elif any(token in lowered for token in ("kritik", "schuld", "vater", "mutter", "kind", "adhs", "narz")) and private_notes:
        body = (
            "Jetzt fang nicht wieder damit an, mir alles umzudrehen. Ich habe getan, was notwendig war, "
            "und wenn jemand ein Problem damit hatte, dann haette er vielleicht einmal genauer hinschauen sollen, "
            "was die anderen beigetragen haben. Kritik ist leicht, wenn man selber nicht in meiner Haut gesteckt ist. "
            "Ich lasse mir nicht einreden, dass immer ich schuld gewesen sein soll."
        )
    elif any(token in lowered for token in ("quelle", "belegt", "wahr", "echt")):
        body = (
            "Echt sind die Aufnahmen, die Quellen und das, was ihr wirklich erlebt habt. "
            "Alles andere hier ist eine vorsichtige Formulierung daraus. Nimm es als Naehe, nicht als Urkunde. "
            "Wenn du wissen willst, was belegt ist, schau auf die Quellen und die Originalstimme."
        )
    else:
        fact_line = facts[0] if facts else "Die Seite enthaelt Originalstimme, Quellen und vorsichtig markierte Erinnerungen."
        body = (
            f"Ich weiss nicht mehr, als hier von mir aufgehoben ist. Aber daran kannst du dich halten: {fact_line} "
            "Frag mich ruhig konkreter. Dann antworte ich naeher an dem, was wirklich von mir geblieben ist."
        )
    response = {
        "person_name": person_name,
        "mode": "memorial_first_person_memory_chat",
        "question": normalized_question,
        "answer": body,
        "sources": [item for item in source_labels if item],
        "private_context_used": bool(private_notes),
        "safety_note": "Erinnerungsmodus in Ich-Form: keine Behauptung, dass die verstorbene Person real antwortet; keine synthetische Stimmnachbildung der verstorbenen Person.",
        "llm_model": llm_model or "",
        "llm_fallback_used": True,
    }
    if fallback_reason:
        response["fallback_reason"] = fallback_reason
    return response


def _build_memorial_chat_messages(
    payload: dict[str, object],
    private_profile: dict[str, object],
    question: str,
) -> list[dict[str, str]]:
    normalized_question = " ".join(str(question or "").strip().split())
    if not normalized_question:
        raise HTTPException(status_code=400, detail="question_missing")
    if len(normalized_question) > 1200:
        raise HTTPException(status_code=400, detail="question_too_long")
    person_name = _text(payload.get("person_name"), "Manfred")
    relationship = _text(payload.get("relationship"), "Vater")
    facts = _compact_public_facts(payload)
    private_notes = _list_of_dicts(private_profile.get("family_context_notes"))
    context_bits = [
        f"Person: {person_name}",
        f"Beziehung: {relationship}",
    ]
    if facts:
        context_bits.append("Quellen aus Archiv: " + " | ".join(facts))
    if private_notes:
        private_lines: list[str] = []
        for note in private_notes[:4]:
            trait = _text(note.get("trait"))
            evidence = _text(note.get("evidence"))
            if trait and evidence:
                private_lines.append(f"{trait}: {evidence}")
        if private_lines:
            context_bits.append("Privatkontext (kurz): " + " | ".join(private_lines))
    source_labels = _memorial_chat_source_labels(payload)
    if source_labels:
        context_bits.append("Externe Quellen: " + "; ".join(source_labels))
    return [
        {
            "role": "system",
            "content": (
                "Du bist ein vorsichtiger Erinnerungs-Assistent fuer eine Gedenkseite. "
                "Antworte in ruhiger Ich-Perspektive und vermeide dramatische Uebertreibungen. "
                "Du simulierst eine rekonstruktive Erinnerung auf Grundlage archivierter Aufnahmen, Belege und Familienkontext. "
                "Du behauptest NIE, dass du die verstorbene Person wirklich bist oder real antwortest. "
                "Wenn etwas ungeklärt ist, sage offen, dass es nicht belegt ist und bitte um eine präzisere Frage. "
                "Antworte emotional einfühlsam, aber factentreu innerhalb der bereitgestellten Fakten."
            ),
        },
        {"role": "system", "content": " | ".join(context_bits)},
        {"role": "user", "content": normalized_question},
    ]


def _memorial_chat_answer(
    payload: dict[str, object],
    question: str,
    private_profile: dict[str, object],
    requested_model: str,
) -> dict[str, object]:
    person_name = _text(payload.get("person_name"), "Manfred")
    normalized_question = " ".join(str(question or "").strip().split())
    if not normalized_question:
        raise HTTPException(status_code=400, detail="question_missing")
    if len(normalized_question) > 1200:
        raise HTTPException(status_code=400, detail="question_too_long")
    source_labels = _memorial_chat_source_labels(payload)
    messages = _build_memorial_chat_messages(payload, private_profile, normalized_question)
    try:
        result = generate_text(
            messages=messages,
            requested_model=requested_model,
            max_output_tokens=360,
        )
        generated = _text(result.text, "")
        if not generated:
            raise RuntimeError("empty_upstream_answer")
        return {
            "person_name": person_name,
            "mode": "memorial_first_person_memory_chat",
            "question": normalized_question,
            "answer": generated,
            "sources": [item for item in source_labels if item],
            "private_context_used": bool(_list_of_dicts(private_profile.get("family_context_notes"))),
            "safety_note": "Erinnerungsmodus in Ich-Form: keine Behauptung, dass die verstorbene Person real antwortet; keine synthetische Stimmnachbildung der verstorbenen Person.",
            "llm_model": _text(result.model, requested_model),
            "llm_provider": _text(result.provider_key, ""),
            "llm_request_model": requested_model,
            "llm_fallback_used": False,
        }
    except ResponsesUpstreamError as exc:
        return _memorial_chat_fallback_answer(
            payload,
            normalized_question,
            private_profile,
            llm_model=requested_model,
            fallback_reason=f"upstream_unavailable:{exc}",
        )


def _normalize_memorial_transcript_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _memorial_transcribe_audio_blob(*, payload: bytes, content_type: str) -> dict[str, object]:
    if not payload:
        raise HTTPException(status_code=400, detail="audio_missing")
    if len(payload) > _MAX_SPEECH_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")
    normalized_content_type = str(content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(normalized_content_type) or ".webm"
    try:
        from app.product import service as product_service

        keys = product_service._pocket_onemin_api_keys()
        if not keys:
            raise HTTPException(status_code=503, detail="speech_transcriber_unavailable")
        upload_payload = payload
        upload_content_type = normalized_content_type
        upload_extension = extension
        if normalized_content_type not in _ONEMIN_SPEECH_AUDIO_TYPES:
            try:
                upload_payload = _convert_audio_to_wav(payload=payload, extension=extension)
            except Exception as exc:
                return {
                    "transcription_status": "no_speech",
                    "transcript_text": "",
                    "transcriber": "ffmpeg",
                    "retryable": True,
                    "detail": str(exc)[:180],
                }
            upload_content_type = "audio/wav"
            upload_extension = ".wav"
        last_error: Exception | None = None
        for api_key in keys:
            try:
                uploaded = product_service._onemin_asset_upload(
                    api_key=api_key,
                    filename=f"memorial-speech{upload_extension}",
                    content_type=upload_content_type,
                    payload=upload_payload,
                )
                asset = dict(uploaded.get("asset") or {}) if isinstance(uploaded.get("asset"), dict) else {}
                file_content = dict(uploaded.get("fileContent") or {}) if isinstance(uploaded.get("fileContent"), dict) else {}
                audio_path = str(file_content.get("path") or asset.get("key") or "").strip()
                if not audio_path:
                    raise RuntimeError("speech_asset_missing_path")
                transcribed = product_service._onemin_speech_to_text(
                    api_key=api_key,
                    audio_path=audio_path,
                    language="de",
                )
                ai_record = dict(transcribed.get("aiRecord") or {}) if isinstance(transcribed.get("aiRecord"), dict) else {}
                ai_detail = dict(ai_record.get("aiRecordDetail") or {}) if isinstance(ai_record.get("aiRecordDetail"), dict) else {}
                text = _normalize_memorial_transcript_text(
                    product_service._extract_transcript_text(ai_detail.get("responseObject"))
                    or product_service._extract_transcript_text(ai_detail.get("resultObject"))
                )
                if text.startswith("{") and text.endswith("}"):
                    try:
                        parsed_text = json.loads(text)
                    except json.JSONDecodeError:
                        parsed_text = {}
                    if isinstance(parsed_text, dict):
                        text = _normalize_memorial_transcript_text(
                            product_service._extract_transcript_text(parsed_text.get("text")) or text
                        )
                if not text:
                    raise RuntimeError("speech_transcript_empty")
                return {
                    "transcription_status": "transcribed",
                    "transcript_text": text,
                    "transcriber": "1min.ai/whisper-1",
                }
            except Exception as exc:
                last_error = exc
                continue
        detail = str(last_error or "speech_transcription_failed")[:180]
        return {
            "transcription_status": "no_speech",
            "transcript_text": "",
            "transcriber": "1min.ai/whisper-1",
            "retryable": True,
            "detail": detail,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"speech_transcription_failed:{str(exc)[:120]}") from exc


def _convert_audio_to_wav(*, payload: bytes, extension: str) -> bytes:
    suffix = extension if str(extension or "").startswith(".") else ".webm"
    with tempfile.TemporaryDirectory(prefix="ea-memorial-stt-") as tmp_dir:
        input_path = Path(tmp_dir) / f"input{suffix}"
        output_path = Path(tmp_dir) / "output.wav"
        input_path.write_bytes(payload)
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(output_path),
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not output_path.exists():
            stderr = proc.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"speech_audio_convert_failed:{stderr[:160]}")
        return output_path.read_bytes()


def _memorial_html(
    payload: dict[str, object],
    *,
    hostname: str = "",
    private_profile: dict[str, object] | None = None,
) -> str:
    slug = _text(payload.get("slug"))
    if not slug:
        raise HTTPException(status_code=500, detail="memorial_slug_missing")
    person_name = _text(payload.get("person_name"), "Manfred")
    title = _text(payload.get("title"), f"Erinnerungen an {person_name}")
    subtitle = _text(
        payload.get("subtitle"),
        "Eine ruhige Seite fuer Erinnerungen, Originalstimme und dokumentierte Gedanken.",
    )
    relationship = _text(payload.get("relationship"), "Vater")
    intro = _text(
        payload.get("intro"),
        "Diese Seite sammelt echte Aufnahmen und belegte Erinnerungen. Neue Texte sind keine direkte Rede.",
    )
    disclosure = _text(
        payload.get("disclosure"),
        "Originalaufnahmen sind als Original gekennzeichnet. Antworttexte werden aus gespeicherten Quellen formuliert und sprechen nicht an seiner Stelle.",
    )
    audio_clips = _list_of_dicts(payload.get("audio_clips"))
    memory_cards = _list_of_dicts(payload.get("memory_cards"))
    candidate_recordings = _list_of_dicts(payload.get("candidate_recordings"))
    profile_notes = _list_of_dicts(payload.get("source_grounded_profile"))
    external_sources = _list_of_dicts(payload.get("external_sources"))
    suggested_prompts = [str(item).strip() for item in (payload.get("suggested_prompts") or []) if str(item).strip()]
    resolved_private_profile = private_profile or _load_private_profile(slug)
    chat_models = _collect_memorial_chat_models(payload, resolved_private_profile)
    chat_model_default = _resolve_memorial_chat_default_model(payload, resolved_private_profile, chat_models)
    chat_model_options = _collect_memorial_chat_model_options(payload, resolved_private_profile, chat_models)
    if chat_model_options:
        if chat_model_default not in {item["value"] for item in chat_model_options}:
            chat_model_default = chat_model_options[0]["value"]
    else:
        chat_model_options = [{"value": model, "label": model} for model in chat_models]
    chat_model_option_lines: list[str] = []
    for option in chat_model_options:
        option_value = html.escape(option["value"])
        option_label = html.escape(option["label"] or option["value"])
        selected = " selected" if option["value"] == chat_model_default else ""
        chat_model_option_lines.append(f'<option value="{option_value}"{selected}>{option_label}</option>')
    chat_models_html = "\n          ".join(chat_model_option_lines)
    page_title = html.escape(title)
    voice_config = _load_voice_config(slug)
    voice_label = html.escape(_text(voice_config.get("voice_label"), "Austauschbare synthetische Stimme"))
    voice_profile_ready = bool(voice_config.get("voice_profile_ready"))
    voice_profile_ready_text = "Aktiv" if voice_profile_ready else "Nicht vorbereitet"
    voice_profile_sources = dict(voice_config.get("voice_profile_sources") or {})
    voice_profile_generated_at = html.escape(_text(voice_config.get("voice_profile_generated_at"), ""))
    voice_profile_policy = dict(voice_config.get("voice_profile_policy") or {})
    voice_name_hints = ", ".join(
        str(item)
        for item in list(dict.fromkeys(voice_config.get("voice_name_hints") or []))[:8]
        if str(item or "").strip()
    )
    tts_plugin_options = list(_tts_plugin_options(payload=voice_config, voice_profile_ready=bool(voice_profile_ready))
    )
    tts_plugin_options_html_lines: list[str] = []
    for option in tts_plugin_options:
        option_value = html.escape(str(option.get("tts_plugin") or ""))
        option_label = html.escape(str(option.get("tts_plugin_label") or option_value))
        selected = " selected" if option.get("tts_plugin") == _safe_tts_plugin_id(voice_config.get("tts_plugin")) else ""
        disabled = " disabled" if not bool(option.get("tts_plugin_enabled")) else ""
        clone_required = "1" if bool(option.get("tts_plugin_needs_clone")) else "0"
        requires_voice_id = "1" if bool(option.get("tts_plugin_requires_voice_id")) else "0"
        plugin_enabled = "1" if bool(option.get("tts_plugin_enabled")) else "0"
        data_voice_id = html.escape(_text(option.get("tts_plugin_voice_id"), ""))
        tts_plugin_options_html_lines.append(
            f'<option value="{option_value}"{selected}{disabled} '
            f'data-clone-required="{clone_required}" data-requires-voice-id="{requires_voice_id}" '
            f'data-enabled="{plugin_enabled}" data-voice-id="{data_voice_id}" '
            f'data-description="{html.escape(_text(option.get("tts_plugin_description"), ""))}">{option_label}</option>'
        )
    tts_plugin_options_html = "\n            ".join(tts_plugin_options_html_lines)
    if not tts_plugin_options_html:
        tts_plugin_options_html = '<option value="" disabled selected>Keine TTS-Plug-ins verfügbar</option>'
    voice_build_default_query = html.escape(f"{person_name} interview")
    clickrank_html = clickrank_head_snippet(hostname)
    clips_html = "\n".join(
        f"""
        <article class="clip">
          <div>
            <p class="eyebrow">{html.escape(_text(clip.get("label"), "Originalaufnahme"))}</p>
            <h3>{html.escape(_text(clip.get("title"), "Audio"))}</h3>
            <p>{html.escape(_text(clip.get("description"), "Echte Aufnahme aus dem Archiv."))}</p>
          </div>
          <audio controls preload="metadata" src="/memorials/files/{html.escape(slug)}/{html.escape(_text(clip.get("asset_relpath")))}"></audio>
        </article>"""
        for clip in audio_clips
        if _text(clip.get("asset_relpath"))
    )
    if not clips_html:
        clips_html = '<p class="empty">Noch keine freigegebenen Originalaufnahmen.</p>'
    cards_html = "\n".join(
        f"""
        <article class="memory">
          <p class="eyebrow">{html.escape(_text(card.get("source_label"), "Quelle"))}</p>
          <h3>{html.escape(_text(card.get("title"), "Erinnerung"))}</h3>
          <p>{html.escape(_text(card.get("body"), ""))}</p>
        </article>"""
        for card in memory_cards
    )
    candidates_html = "\n".join(
        f"""
        <article class="candidate">
          <strong>{html.escape(_text(candidate.get("title"), "Aufnahme"))}</strong>
          <span>{html.escape(_text(candidate.get("recorded_at"), "Datum offen"))}</span>
          <p>{html.escape(_text(candidate.get("status"), "Noch nicht als Stimme freigegeben."))}</p>
        </article>"""
        for candidate in candidate_recordings
    )
    if candidates_html:
        candidates_html = f"""
      <section>
        <h2>Weitere gefundene Kandidaten</h2>
        <div class="candidates">{candidates_html}</div>
      </section>"""
    profile_html = "\n".join(
        f"""
        <article class="profile-note">
          <p class="eyebrow">{html.escape(_text(note.get("confidence"), "quellenbasiert"))}</p>
          <h3>{html.escape(_text(note.get("trait"), "Profilnotiz"))}</h3>
          <p>{html.escape(_text(note.get("evidence"), ""))}</p>
        </article>"""
        for note in profile_notes
    )
    if profile_html:
        profile_html = f"""
      <section>
        <h2>Quellenbasiertes Profil</h2>
        <p class="lead">Keine Diagnose und kein Anspruch auf innere Wahrheit. Das sind belegbare Muster aus Texten, oeffentlichen Quellen und Erinnerungen.</p>
        <div class="grid">{profile_html}</div>
      </section>"""
    sources_html = "\n".join(
        f"""
        <li>
          <a href="{html.escape(_text(source.get("url")))}" target="_blank" rel="noreferrer">{html.escape(_text(source.get("label"), "Quelle"))}</a>
          <span>{html.escape(_text(source.get("status"), "Quelle"))}</span>
        </li>"""
        for source in external_sources
        if _text(source.get("url"))
    )
    if sources_html:
        sources_html = f"""
      <section>
        <h2>Oeffentliche Quellen</h2>
        <ul class="sources">{sources_html}</ul>
      </section>"""
    prompts_html = "\n".join(f"<button type=\"button\" data-prompt=\"{html.escape(prompt)}\">{html.escape(prompt)}</button>" for prompt in suggested_prompts)
    if not prompts_html:
        prompts_html = "<button type=\"button\">Was ist wirklich belegt?</button>"
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{page_title}</title>
    {clickrank_html}
    <style>
      :root {{
        --sky-top: #a9bdd0;
        --sky-mid: #d7e0e5;
        --paper: #f4ecdf;
        --paper-deep: #e5d7c0;
        --panel: rgba(252, 247, 239, 0.88);
        --panel-strong: rgba(255, 250, 242, 0.97);
        --ink: #2b211c;
        --muted: #6f6255;
        --line: rgba(65, 53, 43, 0.14);
        --line-strong: rgba(65, 53, 43, 0.24);
        --sage: #65745f;
        --wine: #87535d;
        --blue: #48677e;
        --gold: #b48d51;
        --shadow: 0 20px 48px rgba(56, 45, 36, 0.11);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background:
          radial-gradient(circle at 22% 14%, rgba(255,255,255,.86) 0, rgba(255,255,255,0) 16%),
          radial-gradient(circle at 78% 10%, rgba(255,250,244,.82) 0, rgba(255,250,244,0) 15%),
          linear-gradient(180deg, #9bb0c2 0%, #c6d2da 12%, #e9e1d5 32%, var(--paper) 100%);
        color: var(--ink);
        font: 16px/1.7 Georgia, "Times New Roman", serif;
        position: relative;
      }}
      body::before {{
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        opacity: .24;
        background:
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'%3E%3Cg fill='none'%3E%3Cpath d='M128 188c26-46 95-58 139-20 31-21 79-19 110 10 36-11 80 6 95 37 49-8 84 29 77 74H30c-8-48 24-85 74-87 4-6 10-11 24-14Z' fill='%23fffaf4' fill-opacity='.62'/%3E%3Cpath d='M1058 122c20-35 74-45 112-16 24-16 62-14 86 8 31-10 65 4 78 31 41-7 71 24 66 62H986c-5-41 21-72 60-74 3-4 7-8 12-11Z' fill='%23fff8ee' fill-opacity='.56'/%3E%3Cpath d='M1180 294c18-30 64-38 98-14 23-14 53-11 72 8 28-8 56 4 67 27 35-5 62 19 57 52h-382c-4-33 18-58 51-60 4-6 9-10 17-13Z' fill='%23fff6ea' fill-opacity='.42'/%3E%3C/g%3E%3C/svg%3E") center top / 100% auto no-repeat;
      }}
      a {{ color: inherit; }}
      .wrap {{ width: min(1120px, calc(100vw - 36px)); margin: 0 auto; }}
      header {{
        min-height: 86vh;
        display: grid;
        align-items: end;
        border-bottom: 1px solid rgba(64,98,123,.16);
        background:
          linear-gradient(180deg, rgba(128,153,172,0.18), rgba(244,236,223,0.44) 55%, rgba(244,236,223,0.98)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1400' height='820' viewBox='0 0 1400 820'%3E%3Cdefs%3E%3ClinearGradient id='sky' x1='0' y1='0' x2='0' y2='1'%3E%3Cstop offset='0%25' stop-color='%2394aabd'/%3E%3Cstop offset='38%25' stop-color='%23c5d0d7'/%3E%3Cstop offset='72%25' stop-color='%23e6ddd0'/%3E%3Cstop offset='100%25' stop-color='%23f1e7d8'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='1400' height='820' fill='url(%23sky)'/%3E%3Cg fill='%23fff9f0' fill-opacity='.62'%3E%3Cpath d='M164 168c28-52 109-67 157-23 37-25 86-21 118 12 39-14 86 6 103 42 55-8 96 33 88 84H58c-7-53 26-95 82-98 5-7 12-13 24-17Z'/%3E%3Cpath d='M890 118c21-39 84-50 123-18 26-18 68-15 94 9 33-12 70 4 84 34 43-6 74 25 68 66H810c-5-44 22-77 68-79 4-5 8-9 12-12Z'/%3E%3C/g%3E%3Cpath d='M0 548c158-40 259-10 382-44 112-31 200-96 334-108 151-14 232 45 372 27 125-16 211-58 312-92V820H0Z' fill='%23ccb08a' fill-opacity='.34'/%3E%3Cpath d='M0 614c138-53 262-16 412-57 150-41 223-140 415-145 149-4 245 78 388 73 71-2 124-20 185-44V820H0Z' fill='%2365745f' fill-opacity='.20'/%3E%3Cpath d='M0 688c183-43 309-5 465-44 169-42 255-114 445-97 166 14 256 80 490 48V820H0Z' fill='%2348677e' fill-opacity='.19'/%3E%3Cg stroke='%236b5a4c' stroke-opacity='.20' fill='none'%3E%3Cpath d='M944 520c36-34 77-48 113-45 34 2 62 20 90 44 18 16 48 23 80 20'/%3E%3Cpath d='M986 570c44-31 95-37 134-20 31 13 56 38 84 59 16 12 35 18 56 18'/%3E%3C/g%3E%3Cg fill='%237d4851' fill-opacity='.44' font-family='Georgia' font-size='18'%3E%3Ctext x='962' y='504'%3ED%C3%B6bling%3C/text%3E%3Ctext x='1016' y='560'%3EGrinzing%3C/text%3E%3Ctext x='1098' y='620'%3EHeiligenstadt%3C/text%3E%3C/g%3E%3Ccircle cx='1152' cy='150' r='58' fill='%23f9e6b8' fill-opacity='.60'/%3E%3C/svg%3E");
        background-size: cover;
        background-position: center;
        position: relative;
        overflow: hidden;
      }}
      header::after {{
        content: "";
        position: absolute;
        inset: auto 0 0 0;
        height: 180px;
        background: linear-gradient(180deg, rgba(247,243,234,0), rgba(247,243,234,0.88) 45%, var(--paper) 100%);
        pointer-events: none;
      }}
      .hero {{
        padding: 64px 0 54px;
        max-width: 860px;
        position: relative;
        z-index: 1;
      }}
      .eyebrow {{
        margin: 0 0 10px;
        color: var(--wine);
        font: 700 12px/1.2 "Trebuchet MS", ui-sans-serif, system-ui, sans-serif;
        letter-spacing: .14em;
        text-transform: uppercase;
      }}
      h1 {{
        margin: 0;
        font-size: clamp(2.6rem, 7vw, 5.9rem);
        line-height: .94;
        font-weight: 560;
        letter-spacing: -.03em;
        text-wrap: balance;
      }}
      h2 {{
        margin: 0 0 12px;
        font-size: clamp(1.7rem, 3vw, 2.5rem);
        line-height: 1.06;
        font-weight: 560;
        letter-spacing: -.02em;
      }}
      h3 {{ margin: 0 0 6px; font-size: 1.06rem; line-height: 1.25; }}
      p {{ margin: 0; }}
      .lead {{ margin-top: 20px; max-width: 64ch; color: var(--muted); font-size: 1.12rem; text-wrap: pretty; }}
      .chat-model-row {{
        display: grid;
        gap: 6px;
        margin-top: 14px;
        width: min(340px, 100%);
      }}
      .chat-model-select {{
        max-width: 340px;
      }}
      .notice {{
        margin-top: 28px;
        max-width: 760px;
        padding: 16px 18px;
        border: 1px solid rgba(95,116,100,.16);
        border-left: 4px solid var(--gold);
        border-radius: 14px;
        backdrop-filter: blur(10px);
        background: rgba(254,249,241,.62);
        color: var(--muted);
        box-shadow: var(--shadow);
      }}
      main {{ padding: 54px 0 88px; position: relative; z-index: 1; }}
      section {{ margin-top: 52px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
      .clip, .memory, .chat, .candidate, .profile-note, .voice-tools {{
        border: 1px solid var(--line);
        background: var(--panel);
        backdrop-filter: blur(8px);
        border-radius: 22px;
        padding: 22px;
        box-shadow: var(--shadow);
      }}
      .memory, .candidate, .profile-note {{
        background:
          linear-gradient(180deg, rgba(255,255,255,.52), rgba(255,255,255,.12)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='620' viewBox='0 0 900 620'%3E%3Crect width='900' height='620' fill='%23f7efdf'/%3E%3Cg opacity='.18' stroke='%2382684d' fill='none'%3E%3Cpath d='M64 118c108-24 182 14 252-12 48-18 87-61 151-68 72-8 118 24 184 14 61-9 101-36 154-62'/%3E%3Cpath d='M48 236c102-34 176-12 248-35 63-21 101-72 180-82 79-9 129 30 204 18 50-8 84-22 126-44'/%3E%3Cpath d='M72 370c84-24 134 12 204-6 67-18 110-75 190-84 78-9 126 36 194 27 46-7 90-28 146-48'/%3E%3C/g%3E%3Cg opacity='.16' stroke='%239f835c' stroke-width='1.2'%3E%3Cpath d='M170 70v470'/%3E%3Cpath d='M330 54v496'/%3E%3Cpath d='M514 66v470'/%3E%3Cpath d='M686 78v450'/%3E%3Cpath d='M90 146h694'/%3E%3Cpath d='M64 278h724'/%3E%3Cpath d='M88 402h692'/%3E%3C/g%3E%3Cg fill='%237d4851' fill-opacity='.62' font-family='Georgia' font-size='24'%3E%3Ctext x='94' y='104'%3ED%C3%B6bling 1954%3C/text%3E%3Ctext x='560' y='140'%3EGrinzing%3C/text%3E%3Ctext x='114' y='438'%3EHeiligenstadt%3C/text%3E%3Ctext x='590' y='410'%3ENussdorf%3C/text%3E%3C/g%3E%3Cg fill='%23b89559' fill-opacity='.24'%3E%3Ccircle cx='220' cy='188' r='48'/%3E%3Ccircle cx='624' cy='214' r='38'/%3E%3Ccircle cx='294' cy='472' r='34'/%3E%3Ccircle cx='684' cy='358' r='44'/%3E%3C/g%3E%3C/svg%3E") center/cover,
          var(--panel);
        border-color: var(--line-strong);
      }}
      .memory:nth-of-type(4n+1), .candidate:nth-of-type(4n+1), .profile-note:nth-of-type(4n+1) {{
        background-position: center, left top, center;
      }}
      .memory:nth-of-type(4n+2), .candidate:nth-of-type(4n+2), .profile-note:nth-of-type(4n+2) {{
        background-image:
          linear-gradient(180deg, rgba(255,255,255,.56), rgba(255,255,255,.14)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='620' viewBox='0 0 900 620'%3E%3Crect width='900' height='620' fill='%23f6eedc'/%3E%3Cg opacity='.17' stroke='%23836b55' fill='none'%3E%3Cpath d='M92 86c78 36 150 35 225 8 62-22 124-12 196 22 74 34 145 37 232 14'/%3E%3Cpath d='M86 206c76 28 145 24 220-10 61-28 122-17 197 14 78 33 149 38 243 16'/%3E%3Cpath d='M70 332c96 35 166 18 236-11 58-24 122-18 196 11 72 30 147 39 244 14'/%3E%3Cpath d='M116 468c72 27 132 24 198 5 61-18 124-7 188 16 79 29 152 32 226 11'/%3E%3C/g%3E%3Cg opacity='.18' stroke='%23987852'%3E%3Cpath d='M154 56v506'/%3E%3Cpath d='M286 56v506'/%3E%3Cpath d='M450 56v506'/%3E%3Cpath d='M618 56v506'/%3E%3Cpath d='M756 56v506'/%3E%3Cpath d='M62 148h774'/%3E%3Cpath d='M62 268h774'/%3E%3Cpath d='M62 392h774'/%3E%3Cpath d='M62 500h774'/%3E%3C/g%3E%3Cg fill='%2340627b' fill-opacity='.60' font-family='Georgia' font-size='23'%3E%3Ctext x='122' y='132'%3ED%C3%B6blinger Hauptstra%C3%9Fe%3C/text%3E%3Ctext x='520' y='184'%3EWien 1950er%3C/text%3E%3Ctext x='114' y='430'%3EGrinzing / Sievering%3C/text%3E%3C/g%3E%3C/svg%3E"),
          var(--panel);
      }}
      .memory:nth-of-type(4n+3), .candidate:nth-of-type(4n+3), .profile-note:nth-of-type(4n+3) {{
        background-image:
          linear-gradient(180deg, rgba(255,255,255,.56), rgba(255,255,255,.12)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='620' viewBox='0 0 900 620'%3E%3Crect width='900' height='620' fill='%23f8f0e2'/%3E%3Cg fill='none' stroke='%23856f58' opacity='.18'%3E%3Cpath d='M88 106c42 0 80 31 130 31 73 0 99-59 175-59 67 0 104 43 167 43 53 0 96-22 152-22 53 0 93 18 112 34'/%3E%3Cpath d='M86 252c35 0 73 27 132 27 76 0 115-70 198-70 61 0 103 39 162 39 64 0 118-30 176-30 42 0 67 10 88 22'/%3E%3Cpath d='M90 410c58 0 92 31 155 31 78 0 111-55 190-55 68 0 103 36 163 36 48 0 95-17 161-17 47 0 82 10 118 28'/%3E%3C/g%3E%3Cg stroke='%23b89559' opacity='.14'%3E%3Cpath d='M210 52v510'/%3E%3Cpath d='M390 52v510'/%3E%3Cpath d='M560 52v510'/%3E%3Cpath d='M716 52v510'/%3E%3Cpath d='M58 164h790'/%3E%3Cpath d='M58 308h790'/%3E%3Cpath d='M58 470h790'/%3E%3C/g%3E%3Cg fill='%237d4851' fill-opacity='.58' font-family='Georgia' font-size='26'%3E%3Ctext x='94' y='154'%3EAlt-D%C3%B6bling%3C/text%3E%3Ctext x='528' y='332'%3EHeiligenst%C3%A4dter Stra%C3%9Fe%3C/text%3E%3Ctext x='118' y='456'%3EKahlenbergerdorf%3C/text%3E%3C/g%3E%3C/svg%3E"),
          var(--panel);
      }}
      .memory:nth-of-type(4n), .candidate:nth-of-type(4n), .profile-note:nth-of-type(4n) {{
        background-image:
          linear-gradient(180deg, rgba(255,255,255,.54), rgba(255,255,255,.10)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='620' viewBox='0 0 900 620'%3E%3Crect width='900' height='620' fill='%23f3ead8'/%3E%3Cg opacity='.16' fill='none' stroke='%238d6f51'%3E%3Cpath d='M70 130c79-21 144 20 219 2 62-15 105-68 184-74 82-6 140 42 216 34 48-5 95-27 141-45'/%3E%3Cpath d='M70 274c69-19 148 17 219 3 59-12 96-58 177-68 81-9 145 35 225 25 51-6 92-24 139-39'/%3E%3Cpath d='M70 430c72-24 144 16 215 0 69-16 108-58 191-66 80-8 141 31 217 20 43-7 88-23 137-46'/%3E%3C/g%3E%3Cg stroke='%23b89559' opacity='.16'%3E%3Cpath d='M130 72v484'/%3E%3Cpath d='M302 72v484'/%3E%3Cpath d='M472 72v484'/%3E%3Cpath d='M644 72v484'/%3E%3Cpath d='M772 72v484'/%3E%3Cpath d='M56 176h792'/%3E%3Cpath d='M56 322h792'/%3E%3Cpath d='M56 470h792'/%3E%3C/g%3E%3Cg fill='%2340627b' fill-opacity='.58' font-family='Georgia' font-size='25'%3E%3Ctext x='94' y='118'%3EWien-D%C3%B6bling 1956%3C/text%3E%3Ctext x='134' y='354'%3ENussdorfer Platz%3C/text%3E%3Ctext x='534' y='470'%3EObkirchergasse%3C/text%3E%3C/g%3E%3C/svg%3E"),
          var(--panel);
      }}
      .voice-tools {{
        background:
          linear-gradient(180deg, rgba(180,141,81,.08), rgba(255,255,255,0)),
          rgba(246,249,247,.9);
        border-color: rgba(83,104,91,.24);
      }}
      .voice-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
      .voice-field {{ display: grid; gap: 6px; }}
      .voice-actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
      .voice-variant-group {{ display: grid; gap: 8px; }}
      .voice-variant-toggle {{
        display: inline-flex;
        flex-wrap: wrap;
        gap: 8px;
        padding: 6px;
        border: 1px solid rgba(46,82,102,.18);
        border-radius: 999px;
        background: rgba(255,250,242,.92);
      }}
      .voice-variant-button {{
        border: 0;
        background: transparent;
        color: var(--muted);
        border-radius: 999px;
        padding: 10px 14px;
        min-width: 110px;
      }}
      .voice-variant-button.active {{
        background: var(--blue);
        color: #fffaf2;
      }}
      .voice-variant-button:disabled {{ opacity: .48; }}
      .voice-variant-chip {{
        display: inline-flex;
        align-items: center;
        border: 1px solid rgba(46,82,102,.22);
        border-radius: 999px;
        padding: 5px 10px;
        background: rgba(255,250,242,.88);
        color: var(--blue);
        font: 700 12px/1 ui-sans-serif, system-ui, sans-serif;
        letter-spacing: .03em;
        text-transform: uppercase;
      }}
      .voice-input {{
        width: 100%;
        border: 1px solid rgba(46,82,102,.28);
        border-radius: 14px;
        padding: 11px 12px;
        background: var(--panel-strong);
        color: var(--ink);
        font: 14px/1.4 ui-sans-serif, system-ui, sans-serif;
      }}
      .voice-input[type="range"] {{ max-width: 100%; }}
      .voice-status {{ color: var(--muted); font-size: .93rem; min-height: 1.4em; }}
      .status-note {{ margin-top: 12px; color: var(--muted); }}
      label {{ font: 600 12px/1.2 ui-sans-serif, system-ui, sans-serif; letter-spacing: 0.01em; }}
      .clip {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .65fr); gap: 18px; align-items: center; }}
      .clip audio {{
        padding: 10px;
        border-radius: 18px;
        background: rgba(255,255,255,.72);
        border: 1px solid rgba(64,98,123,.14);
      }}
      audio {{ width: 100%; }}
      .memory p:last-child, .clip p:last-child, .chat p {{ color: var(--muted); }}
      .candidates {{ display: grid; gap: 10px; }}
      .candidate {{ display: grid; grid-template-columns: minmax(0, 1fr) 170px; gap: 12px; align-items: start; }}
      .candidate span, .candidate p {{ color: var(--muted); }}
      .candidate p {{ grid-column: 1 / -1; }}
      .sources {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
      .sources li {{ border-bottom: 1px solid var(--line); padding: 10px 0; display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 12px; }}
      .sources span {{ color: var(--muted); }}
      .chat {{
        background:
          radial-gradient(circle at top right, rgba(255,255,255,.38), rgba(255,255,255,0) 32%),
          #eef0ea;
        border-color: rgba(83,104,91,.24);
      }}
      .prompt-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
      .chat-form {{ display: grid; gap: 12px; margin-top: 18px; }}
      .voice-build {{ display: grid; gap: 10px; margin-top: 12px; }}
      .speech-row {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
      textarea {{
        width: 100%;
        min-height: 112px;
        resize: vertical;
        border: 1px solid rgba(46,82,102,.28);
        border-radius: 16px;
        padding: 12px;
        background: var(--panel-strong);
        color: var(--ink);
        font: 16px/1.5 ui-sans-serif, system-ui, sans-serif;
      }}
      .chat-actions {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
      .speech-note {{ color: var(--muted); font-size: .94rem; }}
      .chat-answer {{
        margin-top: 16px;
        padding: 18px;
        border: 1px solid rgba(83,104,91,.24);
        border-radius: 18px;
        background: rgba(255,250,242,.78);
        white-space: pre-wrap;
        color: var(--ink);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.5);
      }}
      .chat-answer:empty {{ display: none; }}
      button {{
        border: 1px solid rgba(46,82,102,.28);
        background: linear-gradient(180deg, rgba(255,255,255,.94), rgba(248,241,231,.96));
        color: var(--blue);
        border-radius: 999px;
        padding: 10px 14px;
        font: 650 14px/1 ui-sans-serif, system-ui, sans-serif;
        box-shadow: 0 8px 16px rgba(64,98,123,.08);
        transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease;
      }}
      button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 12px 22px rgba(64,98,123,.12);
        border-color: rgba(64,98,123,.34);
      }}
      button:active {{
        transform: translateY(0);
      }}
      footer {{
        border-top: 1px solid var(--line);
        padding: 30px 0;
        color: var(--muted);
        background: linear-gradient(180deg, rgba(247,243,234,0), rgba(237,228,212,.56));
      }}
      @media (max-width: 760px) {{
        header {{ min-height: 78vh; }}
        .grid, .clip, .voice-grid {{ grid-template-columns: 1fr; }}
        .wrap {{ width: min(100vw - 28px, 1120px); }}
        .clip, .memory, .chat, .candidate, .profile-note, .voice-tools {{ border-radius: 18px; padding: 18px; }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div class="wrap hero">
        <p class="eyebrow">Gedenkseite · {html.escape(relationship)}</p>
        <h1>{html.escape(person_name)}</h1>
        <p class="lead">{html.escape(subtitle)}</p>
        <p class="notice">{html.escape(disclosure)}</p>
      </div>
    </header>
    <main class="wrap">
      <section>
        <h2>Worum es hier geht</h2>
        <p class="lead">{html.escape(intro)}</p>
      </section>
      <section>
        <h2>Seine Stimme hoeren</h2>
        {clips_html}
      </section>
      <section>
        <h2>Erinnerungen und Quellen</h2>
        <div class="grid">{cards_html}</div>
      </section>
      {profile_html}
      {sources_html}
      {candidates_html}
      <section class="voice-tools">
        <p class="eyebrow">Stimme und Sprachmodell</p>
        <h2>Stimmenprofil verwalten</h2>
        <p class="lead">Wähle ein TTS-Plugin und nutze die echte Stimme, nachdem ein Voice-Clone aktiv gesetzt ist.</p>
        <form class="voice-grid" id="memorial-voice-config-form">
          <div class="voice-field">
            <label for="memorial-tts-plugin">TTS-Plugin</label>
            <select id="memorial-tts-plugin" class="voice-input">
              {tts_plugin_options_html}
            </select>
            <span class="status-note" id="memorial-tts-plugin-note">Plugin wird geladen...</span>
            <button type="button" id="memorial-voice-clone">Voice klonen</button>
            <span class="status-note" id="memorial-tts-clone-status"></span>
          </div>
          <div class="voice-field">
            <label for="memorial-voice-label">Stimmenlabel</label>
            <input id="memorial-voice-label" class="voice-input" type="text" value="{voice_label}" autocomplete="off">
          </div>
          <div class="voice-field">
            <label for="memorial-voice-lang">Sprache</label>
            <input id="memorial-voice-lang" class="voice-input" type="text" value="{html.escape(_text(voice_config.get('lang'), 'de-AT'))[:16]}">
          </div>
          <div class="voice-field voice-variant-group">
            <label>Basisstimme fuer Clone</label>
            <div class="voice-variant-toggle" id="memorial-tts-base-voice-toggle">
              <button type="button" class="voice-variant-button{' active' if _text(voice_config.get('tts_base_voice_variant'), 'high') == 'high' else ''}" data-variant="high">High</button>
              <button type="button" class="voice-variant-button{' active' if _text(voice_config.get('tts_base_voice_variant'), 'high') == 'balanced' else ''}" data-variant="balanced">Balanced</button>
            </div>
            <input id="memorial-tts-base-voice-variant" type="hidden" value="{html.escape(_text(voice_config.get('tts_base_voice_variant'), 'high'))}">
            <span class="status-note">Waehlt die lokale Piper-Basis unter dem Manfred-Clone.</span>
          </div>
          <div class="voice-field">
            <label for="memorial-voice-rate">Sprechtempo ({voice_config.get("rate", 0.92)})</label>
            <input id="memorial-voice-rate" class="voice-input" type="range" min="0.45" max="1.5" step="0.05" value="{voice_config.get("rate", 0.92)}">
          </div>
          <div class="voice-field">
            <label for="memorial-voice-pitch">Stimmtonhöhe ({voice_config.get("pitch", 0.92)})</label>
            <input id="memorial-voice-pitch" class="voice-input" type="range" min="0.5" max="1.5" step="0.05" value="{voice_config.get("pitch", 0.92)}">
          </div>
          <div class="voice-field">
            <label for="memorial-voice-volume">Lautstaerke ({voice_config.get("volume", 1.0)})</label>
            <input id="memorial-voice-volume" class="voice-input" type="range" min="0" max="1" step="0.05" value="{voice_config.get("volume", 1.0)}">
          </div>
          <div class="voice-field">
            <label for="memorial-voice-hints">Stimmen-Hints (Komma oder Zeilenumbruch)</label>
            <textarea id="memorial-voice-hints" class="voice-input" rows="3">{voice_name_hints}</textarea>
          </div>
          <div class="voice-actions">
            <button type="button" id="memorial-voice-config-save">Einstellungen speichern</button>
            <span class="voice-status" id="memorial-voice-status">Profil aus Cache geladen.</span>
          </div>
        </form>
        <div class="voice-build">
          <h3>Stimmprofil erweitern (Audio + YouTube)</h3>
          <p class="lead">Aus den freigegebenen Clips + YouTube-Liste wird ein wiederverwendbarer Sprecher-Fingerprint aufgebaut (ohne Echtzeit-Klon).</p>
          <div class="voice-grid">
            <div class="voice-field">
              <label for="memorial-voice-youtube-query">YouTube-Suchbegriff</label>
              <input id="memorial-voice-youtube-query" class="voice-input" type="text" value="{voice_build_default_query}">
            </div>
            <div class="voice-field">
              <label for="memorial-voice-youtube-limit">YouTube-Item-Limit</label>
              <input id="memorial-voice-youtube-limit" class="voice-input" type="number" min="1" max="12" value="5">
            </div>
            <div class="voice-field" style="grid-column:1 / -1;">
              <label for="memorial-voice-youtube-urls">YouTube-URLs (optional, pro Zeile/Komma)</label>
              <textarea id="memorial-voice-youtube-urls" class="voice-input" rows="3" placeholder="https://www.youtube.com/watch?v=..."></textarea>
            </div>
          </div>
          <div class="voice-actions">
            <button type="button" id="memorial-voice-profile-build">Stimmprofil neu bauen</button>
            <span class="voice-status" id="memorial-voice-profile-status">{html.escape(f"Status: {voice_profile_ready_text}")}</span>
          </div>
          <div class="status-note" id="memorial-voice-profile-summary">{html.escape(f"Samples: {int(voice_profile_sources.get('total',0))}, Verarbeitet: {int(voice_profile_sources.get('ready',0))}, Fehler: {int(voice_profile_sources.get('failed',0))}{', erstellt ' + voice_profile_generated_at if voice_profile_generated_at else ''}.")}</div>
          </div>
        </div>
      </section>
      <section class="chat">
        <p class="eyebrow">Erinnerungs-Chat</p>
        <h2>Sprich mit der Erinnerung.</h2>
        <p>Die Antworten bleiben aus Archiv, Originalstimme und Familienkontext zusammengesetzt, aber sie duerfen nah und persoenlich klingen.</p>
        <div class="prompt-row">{prompts_html}</div>
        <div class="chat-model-row">
          <label for="memorial-chat-model">Sprachmodell (Plugin-Auswahl)</label>
          <select id="memorial-chat-model" class="voice-input chat-model-select">
            {chat_models_html}
          </select>
        </div>
      <div class="speech-row">
          <button type="button" id="memorial-conversation">Gespräch starten</button>
          <button type="button" id="memorial-speech-listen">Mikrofon starten</button>
          <button type="button" id="memorial-server-stt">Server-STT starten</button>
          <button type="button" id="memorial-speech-speak">Antwort vorlesen</button>
          <button type="button" id="memorial-speech-stop">Stopp</button>
          <span class="voice-variant-chip" id="memorial-speech-voice-chip">Basis: {html.escape(_text(voice_config.get('tts_base_voice_variant'), 'high'))}</span>
          <span class="speech-note" id="memorial-speech-note">Antwort wird mit Server-Voice-Clone vorgelesen, {voice_label}.</span>
        </div>
        <form class="chat-form" id="memorial-chat-form">
          <textarea id="memorial-chat-question" name="question" placeholder="Frag nach einer Erinnerung, Quelle oder vorsichtigen Einordnung."></textarea>
        <div class="chat-actions">
            <button type="submit">Antwort formulieren</button>
            <span id="memorial-chat-status"></span>
          </div>
        </form>
        <audio id="memorial-speech-audio" preload="none"></audio>
        <div class="chat-answer" id="memorial-chat-answer"></div>
      </section>
    </main>
    <footer>
      <div class="wrap">Hosted on myexternalbrain.com · Originalstimme nur aus freigegebenen Aufnahmen.</div>
    </footer>
    <script>
      const form = document.getElementById("memorial-chat-form");
      const question = document.getElementById("memorial-chat-question");
      const chatModelSelect = document.getElementById("memorial-chat-model");
      const answer = document.getElementById("memorial-chat-answer");
      const statusNode = document.getElementById("memorial-chat-status");
      const voiceConfigForm = document.getElementById("memorial-voice-config-form");
      const voiceProfileSaveButton = document.getElementById("memorial-voice-config-save");
      const voiceProfileStatus = document.getElementById("memorial-voice-status");
      const voiceProfileSummary = document.getElementById("memorial-voice-profile-summary");
      const voiceBuildButton = document.getElementById("memorial-voice-profile-build");
      const voiceBuildStatus = document.getElementById("memorial-voice-profile-status");
      const voiceLabelInput = document.getElementById("memorial-voice-label");
      const voiceLangInput = document.getElementById("memorial-voice-lang");
      const voiceRateInput = document.getElementById("memorial-voice-rate");
      const voicePitchInput = document.getElementById("memorial-voice-pitch");
      const voiceVolumeInput = document.getElementById("memorial-voice-volume");
      const voiceHintsInput = document.getElementById("memorial-voice-hints");
      const ttsBaseVoiceVariantInput = document.getElementById("memorial-tts-base-voice-variant");
      const ttsBaseVoiceToggle = document.getElementById("memorial-tts-base-voice-toggle");
      const ttsBaseVoiceButtons = Array.from(document.querySelectorAll("[data-variant]"));
      const voiceYoutubeQueryInput = document.getElementById("memorial-voice-youtube-query");
      const voiceYoutubeLimitInput = document.getElementById("memorial-voice-youtube-limit");
      const voiceYoutubeUrlsInput = document.getElementById("memorial-voice-youtube-urls");
      const ttsPluginSelect = document.getElementById("memorial-tts-plugin");
      const ttsPluginNote = document.getElementById("memorial-tts-plugin-note");
      const ttsCloneButton = document.getElementById("memorial-voice-clone");
      const ttsCloneStatus = document.getElementById("memorial-tts-clone-status");
      const speechAudio = document.getElementById("memorial-speech-audio");
      const listenButton = document.getElementById("memorial-speech-listen");
      const serverSttButton = document.getElementById("memorial-server-stt");
      const conversationButton = document.getElementById("memorial-conversation");
      const speakButton = document.getElementById("memorial-speech-speak");
      const stopButton = document.getElementById("memorial-speech-stop");
      const speechVoiceChip = document.getElementById("memorial-speech-voice-chip");
      const speechNote = document.getElementById("memorial-speech-note");
      let lastAnswerText = "";
      let activeRecognition = null;
      let activeRecorder = null;
      let recorderChunks = [];
      let conversationActive = false;
      let activeStream = null;
      let activeAudioContext = null;
      let activeSilenceTimer = null;
      let activeMaxTimer = null;
      let speechHadError = false;
      let speechObjectUrl = null;
      let memorialVoiceConfig = {{
        tts_plugin: "browser_speech_synthesis",
        tts_plugin_voice_id: "",
        tts_plugin_options: [],
        voice_label: "Austauschbare synthetische Stimme",
        lang: "de-AT",
        tts_base_voice_variant: "high",
        rate: 0.92,
        pitch: 0.92,
        volume: 1,
        voice_name_hints: ["de-AT", "de-DE", "German"],
        synthetic_voice_clone_of_memorial_person: false
      }};
      function currentBaseVoiceVariant() {{
        return String(ttsBaseVoiceVariantInput ? (ttsBaseVoiceVariantInput.value || "high") : memorialVoiceConfig.tts_base_voice_variant || "high");
      }}
      function updateBaseVoiceVariantUi() {{
        const selected = currentBaseVoiceVariant();
        for (const button of ttsBaseVoiceButtons) {{
          const isActive = String(button.getAttribute("data-variant") || "") === selected;
          button.classList.toggle("active", isActive);
          button.setAttribute("aria-pressed", isActive ? "true" : "false");
        }}
        if (speechVoiceChip) {{
          speechVoiceChip.textContent = "Basis: " + selected;
        }}
      }}
      async function loadVoiceConfig() {{
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-config");
          if (!response.ok) return;
          const payload = await response.json();
          memorialVoiceConfig = Object.assign(memorialVoiceConfig, payload || {{}});
          if (ttsPluginSelect && payload.tts_plugin_options && Array.isArray(payload.tts_plugin_options)) {{
            memorialVoiceConfig.tts_plugin_options = payload.tts_plugin_options;
          }}
          if (voiceLabelInput) voiceLabelInput.value = memorialVoiceConfig.voice_label || "";
          if (voiceLangInput) voiceLangInput.value = memorialVoiceConfig.lang || "de-AT";
          if (ttsBaseVoiceVariantInput) ttsBaseVoiceVariantInput.value = String(memorialVoiceConfig.tts_base_voice_variant || "high");
          updateBaseVoiceVariantUi();
          if (voiceRateInput) voiceRateInput.value = String(memorialVoiceConfig.rate || 0.92);
          if (voicePitchInput) voicePitchInput.value = String(memorialVoiceConfig.pitch || 0.92);
          if (voiceVolumeInput) voiceVolumeInput.value = String(memorialVoiceConfig.volume || 1);
          if (voiceHintsInput) voiceHintsInput.value = (Array.isArray(memorialVoiceConfig.voice_name_hints) ? memorialVoiceConfig.voice_name_hints : []).join(", ");
          if (ttsPluginSelect && memorialVoiceConfig.tts_plugin) {{
            ttsPluginSelect.value = String(memorialVoiceConfig.tts_plugin || "");
          }}
          applyTtsPluginState();
          if (payload.voice_profile_sources) {{
            const source = payload.voice_profile_sources;
            const status = "Stimmenprofil: " + (payload.voice_profile_ready ? "aktiv" : "nicht aktiv") + " (Samples " + (source.total || 0) + ", verarbeitet " + (source.ready || 0) + ", Fehler " + (source.failed || 0) + ")";
            if (voiceProfileStatus) voiceProfileStatus.textContent = status;
            const generatedAt = payload.voice_profile_generated_at || "";
            const summaryParts = [];
            if (generatedAt) summaryParts.push("erstellt: " + generatedAt);
            if ((source.public_clips || 0) > 0) summaryParts.push("Öffentliche Clips: " + (source.public_clips || 0));
            if ((source.youtube_urls || 0) > 0) summaryParts.push("YouTube-Suche/Links: " + (source.youtube_urls || 0));
            if ((source.youtube_downloads || 0) > 0) summaryParts.push("Downloads: " + (source.youtube_downloads || 0));
            if (voiceProfileSummary) voiceProfileSummary.textContent = status + (summaryParts.length ? " · " + summaryParts.join(" · ") : "");
          }}
        }} catch (error) {{}}
      }}
      function getActiveTtsPluginOption() {{
        const selected = String(ttsPluginSelect ? ttsPluginSelect.value : memorialVoiceConfig.tts_plugin || "");
        const candidates = Array.isArray(memorialVoiceConfig.tts_plugin_options) ? memorialVoiceConfig.tts_plugin_options : [];
        for (const option of candidates) {{
          if (String(option.tts_plugin || "") === selected) {{
            return option;
          }}
        }}
        for (const option of candidates) {{
          if (option.tts_plugin_enabled) {{
            return option;
          }}
        }}
        return candidates[0] || {{}};
      }}
      function applyTtsPluginState() {{
        if (ttsPluginSelect) {{
          const selected = String(memorialVoiceConfig.tts_plugin || ttsPluginSelect.value || "");
          if (selected) ttsPluginSelect.value = selected;
        }}
        const option = getActiveTtsPluginOption();
        const optionEnabled = Boolean(option.tts_plugin_enabled);
        const optionNeedsClone = Boolean(option.tts_plugin_needs_clone);
        const optionLabel = String(option.tts_plugin_label || "TTS Plugin").trim() || "TTS Plugin";
        const optionDescription = String(option.tts_plugin_description || "").trim() || "";
        const voiceReady = Boolean(option.tts_plugin_voice_id || optionNeedsClone === false || option.tts_plugin_requires_voice_id === false);
        const variantEnabled = String(option.tts_plugin || "") === "{OPENVOICE_TTS_PLUGIN_ID}";
        for (const button of ttsBaseVoiceButtons) {{
          button.disabled = !variantEnabled;
        }}
        updateBaseVoiceVariantUi();
        if (ttsPluginNote) {{
          if (optionEnabled) {{
            ttsPluginNote.textContent = optionDescription || (optionLabel + (voiceReady ? " aktiv." : " aktiv, aber ID fehlt."));
          }} else {{
            ttsPluginNote.textContent = optionDescription || "Plugin nicht verfügbar.";
          }}
        }}
        if (speechNote) {{
          speechNote.textContent = (optionEnabled ? "Antwort aus " : "Plugin aktivieren: ") + optionLabel + (voiceReady ? "" : " (Voice-ID fehlt)");
        }}
        if (ttsCloneButton) {{
          ttsCloneButton.disabled = !Boolean(option.tts_plugin_clone_capable && optionEnabled);
          ttsCloneButton.style.display = option.tts_plugin_clone_capable ? "inline-block" : "none";
        }}
        if (ttsCloneStatus && !ttsCloneStatus.textContent) {{
          ttsCloneStatus.textContent = optionNeedsClone ? "Klon noch nicht vorhanden." : "";
        }}
      }}
      function buildProfileSummaryText(payload) {{
        const source = payload.voice_profile_sources || {{}};
        const total = Number(source.total || 0);
        const ready = Number(source.ready || 0);
        const failed = Number(source.failed || 0);
        const policy = payload.voice_profile_policy || {{}};
        const policyText = policy.voice_cloning_supported ? "klonfähig" : "nur stimmliches Fingerprint";
        const lines = [
          "Status: " + (payload.voice_profile_ready ? "aktiv" : "nicht aktiv"),
          "Samples: " + total + " (verarbeitet " + ready + ", Fehler " + failed + ")",
          "Profil-Policy: " + policyText,
        ];
        if (source.public_clips) lines.push("Öffentliche Clips: " + source.public_clips);
        if (source.youtube_urls) lines.push("YouTube-Quellen: " + source.youtube_urls);
        if (payload.voice_profile_generated_at) lines.push("Zuletzt: " + String(payload.voice_profile_generated_at || ""));
        return lines.join(" · ");
      }}
      async function refreshVoiceProfileSummary() {{
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-profile");
          if (!response.ok) return;
          const payload = await readJsonResponse(response);
          const summary = buildProfileSummaryText(payload);
          if (voiceProfileSummary) voiceProfileSummary.textContent = summary;
          if (voiceProfileStatus) {{
            voiceProfileStatus.textContent = "Status: " + (payload.voice_profile_ready ? "aktiv" : "nicht aktiv");
          }}
        }} catch (error) {{}}
      }}
      async function saveVoiceConfig() {{
        if (!voiceConfigForm) return;
        if (voiceProfileStatus) voiceProfileStatus.textContent = "Speichere Stimmenprofil...";
        const selectedTtsPlugin = getActiveTtsPluginOption();
        const selectedPluginId = String(ttsPluginSelect ? (ttsPluginSelect.value || "") : String(memorialVoiceConfig.tts_plugin || ""));
        const selectedVoiceId = String(
          (selectedTtsPlugin && selectedTtsPlugin.tts_plugin_voice_id ? selectedTtsPlugin.tts_plugin_voice_id : memorialVoiceConfig.tts_plugin_voice_id) || ""
        );
        const payload = {{
          tts_plugin: selectedPluginId,
          tts_plugin_voice_id: selectedVoiceId,
          voice_label: String(voiceLabelInput ? (voiceLabelInput.value || "") : memorialVoiceConfig.voice_label || ""),
          lang: String(voiceLangInput ? (voiceLangInput.value || "") : memorialVoiceConfig.lang || "de-AT").slice(0, 16),
          tts_base_voice_variant: currentBaseVoiceVariant(),
          rate: Number(voiceRateInput ? voiceRateInput.value || 0.92 : memorialVoiceConfig.rate || 0.92),
          pitch: Number(voicePitchInput ? voicePitchInput.value || 0.92 : memorialVoiceConfig.pitch || 0.92),
          volume: Number(voiceVolumeInput ? voiceVolumeInput.value || 1 : memorialVoiceConfig.volume || 1),
          voice_name_hints: String(voiceHintsInput ? (voiceHintsInput.value || "") : "").split(/[\n,]/).map((item) => String(item || "").trim()).filter(Boolean).slice(0, 8),
        }};
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-config", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const updated = await readJsonResponse(response);
          memorialVoiceConfig = Object.assign(memorialVoiceConfig, updated || {{}});
          if (updated && Array.isArray(updated.tts_plugin_options)) {{
            memorialVoiceConfig.tts_plugin_options = updated.tts_plugin_options;
          }}
          if (ttsPluginSelect && updated && updated.tts_plugin) {{
            ttsPluginSelect.value = String(updated.tts_plugin);
          }}
          if (memorialVoiceConfig.tts_plugin_voice_id && ttsPluginSelect) {{
            const active = getActiveTtsPluginOption();
            if (active && active.tts_plugin_requires_voice_id && !active.tts_plugin_voice_id) {{
              active.tts_plugin_voice_id = memorialVoiceConfig.tts_plugin_voice_id;
            }}
          }}
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Einstellungen gespeichert.";
          applyTtsPluginState();
        }} catch (error) {{
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Speichern fehlgeschlagen: " + String(error.message || error);
        }}
      }}
      async function buildVoiceProfile() {{
        if (voiceBuildStatus) voiceBuildStatus.textContent = "Starte Profilaufbau...";
        const payload = {{
          youtube_query: String(voiceYoutubeQueryInput ? (voiceYoutubeQueryInput.value || "") : ""),
          youtube_urls: String(voiceYoutubeUrlsInput ? (voiceYoutubeUrlsInput.value || "") : ""),
          youtube_limit: Number(voiceYoutubeLimitInput ? (voiceYoutubeLimitInput.value || 5) : 5),
        }};
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-profile/build", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const result = await readJsonResponse(response);
          if (voiceProfileStatus) voiceProfileStatus.textContent = result.voice_profile_ready ? "Profil aufgebaut." : "Profil teilweise aufgebaut.";
          if (voiceProfileSummary) voiceProfileSummary.textContent = buildProfileSummaryText(result);
        }} catch (error) {{
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Profil konnte nicht aufgebaut werden: " + String(error.message || error);
        }}
        await refreshVoiceProfileSummary();
      }}
      async function cloneVoiceProfile() {{
        if (!ttsCloneButton) return;
        if (ttsCloneStatus) ttsCloneStatus.textContent = "Starte Stimmklon...";
        ttsCloneButton.disabled = true;
        const profileLabel = String(
          voiceLabelInput ? (voiceLabelInput.value || memorialVoiceConfig.voice_label || "Memorial") : (memorialVoiceConfig.voice_label || "Memorial")
        ).trim();
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-clone", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ voice_label: profileLabel }}),
          }});
          const updated = await readJsonResponse(response);
          memorialVoiceConfig = Object.assign(memorialVoiceConfig, updated || {{}});
          if (updated && Array.isArray(updated.tts_plugin_options)) {{
            memorialVoiceConfig.tts_plugin_options = updated.tts_plugin_options;
          }}
          if (memorialVoiceConfig.tts_plugin && ttsPluginSelect) {{
            ttsPluginSelect.value = String(memorialVoiceConfig.tts_plugin);
          }}
          if (memorialVoiceConfig.tts_plugin_voice_id && ttsPluginSelect) {{
            const active = getActiveTtsPluginOption();
            if (active && active.tts_plugin_requires_voice_id && !active.tts_plugin_voice_id) {{
              active.tts_plugin_voice_id = memorialVoiceConfig.tts_plugin_voice_id;
            }}
          }}
          applyTtsPluginState();
          if (ttsCloneStatus) ttsCloneStatus.textContent = "Klon-ID gespeichert.";
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Klon erstellt.";
        }} catch (error) {{
          if (ttsCloneStatus) ttsCloneStatus.textContent = "Klon fehlgeschlagen: " + String(error.message || error);
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Klon fehlgeschlagen.";
        }} finally {{
          await refreshVoiceProfileSummary();
          const activeOption = getActiveTtsPluginOption();
          const activeEnabled = Boolean(activeOption && activeOption.tts_plugin_enabled);
          ttsCloneButton.disabled = !Boolean(activeOption && activeOption.tts_plugin_clone_capable && activeEnabled);
        }}
      }}
      function normalizeTranscriptText(value) {{
        return String(value || "").replace(/\\s+/g, " ").trim();
      }}
      function stopSpeechPlayback() {{
        if (speechAudio) {{
          try {{
            speechAudio.pause();
          }} catch (error) {{}}
          speechAudio.onended = null;
          speechAudio.onerror = null;
        }}
        if (speechObjectUrl) {{
          try {{
            URL.revokeObjectURL(speechObjectUrl);
          }} catch (error) {{}}
          speechObjectUrl = null;
        }}
        if (speechAudio) {{
          try {{
            speechAudio.src = "";
          }} catch (error) {{}}
        }}
      }}
      function currentTtsOptionOrDefault() {{
        const option = getActiveTtsPluginOption();
        const plugin = String(ttsPluginSelect ? (ttsPluginSelect.value || memorialVoiceConfig.tts_plugin || "") : String(memorialVoiceConfig.tts_plugin || ""));
        const voiceId = String(option.tts_plugin_voice_id || memorialVoiceConfig.tts_plugin_voice_id || "");
        return {{
          tts_plugin: plugin,
          tts_plugin_voice_id: voiceId,
          tts_plugin_label: String(option.tts_plugin_label || "TTS Plugin"),
          tts_plugin_enabled: Boolean(option.tts_plugin_enabled),
        }};
      }}
      async function parseSpeakError(response) {{
        const raw = await response.text();
        try {{
          const payload = JSON.parse(raw);
          return String(payload.detail || payload.message || payload.error || raw || "request_failed");
        }} catch (error) {{
          return String(raw || "request_failed");
        }}
      }}
      async function readJsonResponse(response) {{
        const raw = await response.text();
        try {{
          const payload = JSON.parse(raw);
          if (!response.ok) throw new Error(payload.detail || payload.error?.message || "request_failed");
          return payload;
        }} catch (error) {{
          if (error instanceof SyntaxError) {{
            const preview = raw.trim().slice(0, 120);
            throw new Error(preview.startsWith("<") ? "Server lieferte HTML statt JSON. Bitte kurz warten und erneut versuchen." : preview || "ungueltige Serverantwort");
          }}
          throw error;
        }}
      }}
      async function askMemorialChat(value, options = {{}}) {{
        const text = normalizeTranscriptText(value || "");
        if (!text) return;
        statusNode.textContent = "Formuliere...";
        answer.textContent = "";
        const selectedModel = chatModelSelect ? String(chatModelSelect.value || "").trim() : "";
        const requestPayload = {{ question: text }};
        if (selectedModel) requestPayload.llm_model = selectedModel;
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/chat", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(requestPayload)
          }});
          const payload = await readJsonResponse(response);
          lastAnswerText = String(payload.answer || "");
          answer.textContent = lastAnswerText + "\\n\\nQuellen: " + (payload.sources || []).join(", ");
          statusNode.textContent = "";
          void speakText(lastAnswerText, options.continueConversation ? () => {{
            if (conversationActive) setTimeout(recordConversationTurn, 450);
          }} : null);
        }} catch (error) {{
          statusNode.textContent = "Antwort konnte nicht erstellt werden: " + String(error.message || error);
          if (options.continueConversation && conversationActive) setTimeout(recordConversationTurn, 900);
        }}
      }}
      async function speakText(value, onDone = null) {{
        const text = normalizeTranscriptText(value || lastAnswerText || "");
        if (!text) {{
          if (onDone) onDone();
          return;
        }}
        stopSpeechPlayback();
        const pluginConfig = currentTtsOptionOrDefault();
        if (!pluginConfig.tts_plugin_enabled) {{
          speechNote.textContent = "Ausgewähltes TTS-Plugin ist nicht aktiviert.";
          if (onDone) onDone();
          return;
        }}
        if (pluginConfig.tts_plugin === "browser_speech_synthesis") {{
          const synth = window.speechSynthesis;
          if (!synth || typeof SpeechSynthesisUtterance === "undefined") {{
            speechNote.textContent = "Browser-Sprachausgabe ist nicht verfügbar.";
            if (onDone) onDone();
            return;
          }}
          try {{
            synth.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = String(memorialVoiceConfig.lang || "de-AT");
            utterance.rate = Number(memorialVoiceConfig.rate || 0.92);
            utterance.pitch = Number(memorialVoiceConfig.pitch || 0.92);
            utterance.volume = Number(memorialVoiceConfig.volume || 1);
            const hints = Array.isArray(memorialVoiceConfig.voice_name_hints) ? memorialVoiceConfig.voice_name_hints.map((item) => String(item || "").toLowerCase()) : [];
            const voices = typeof synth.getVoices === "function" ? synth.getVoices() : [];
            const matchedVoice = voices.find((voice) => {{
              const name = String(voice && voice.name || "").toLowerCase();
              const lang = String(voice && voice.lang || "").toLowerCase();
              return hints.some((hint) => hint && (name.includes(hint) || lang.includes(hint)));
            }});
            if (matchedVoice) utterance.voice = matchedVoice;
            utterance.onend = () => {{
              speechNote.textContent = "Sprachausgabe bereit.";
              if (onDone) onDone();
            }};
            utterance.onerror = (event) => {{
              speechNote.textContent = "Browser-Sprachausgabe fehlgeschlagen.";
              if (onDone) onDone();
            }};
            speechNote.textContent = "Sprachausgabe mit Browser Speech.";
            synth.speak(utterance);
          }} catch (error) {{
            speechNote.textContent = "Browser-Sprachausgabe fehlgeschlagen: " + String(error.message || error);
            if (onDone) onDone();
          }}
          return;
        }}
        if (!speechAudio) {{
          if (onDone) onDone();
          return;
        }}
        speechNote.textContent = "Erzeuge Sprachausgabe mit " + String(pluginConfig.tts_plugin_label || pluginConfig.tts_plugin || "TTS Plugin") + ".";
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/speech-synthesize", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              text: text,
              tts_plugin: pluginConfig.tts_plugin,
              tts_plugin_voice_id: pluginConfig.tts_plugin_voice_id,
              tts_base_voice_variant: currentBaseVoiceVariant(),
            }}),
          }});
          if (!response.ok) {{
            const message = await parseSpeakError(response);
            throw new Error(message || "speech_synthesis_failed");
          }}
          const blob = await response.blob();
          if (!blob || !blob.size) {{
            throw new Error("speech_synthesis_empty_audio");
          }}
          speechObjectUrl = URL.createObjectURL(blob);
          speechAudio.src = speechObjectUrl;
          speechAudio.onended = () => {{
            stopSpeechPlayback();
            if (onDone) onDone();
          }};
          speechAudio.onerror = () => {{
            speechNote.textContent = "Wiedergabe fehlgeschlagen.";
            stopSpeechPlayback();
            if (onDone) onDone();
          }};
          await speechAudio.play();
        }} catch (error) {{
          if (speechAudio) speechAudio.src = "";
          if (speechObjectUrl) {{
            try {{
              URL.revokeObjectURL(speechObjectUrl);
            }} catch (error) {{}}
            speechObjectUrl = null;
          }}
          speechNote.textContent = "Sprachausgabe fehlgeschlagen: " + String(error.message || error);
          if (onDone) onDone();
        }}
      }}
      function releaseConversationAudio() {{
        if (activeSilenceTimer) clearTimeout(activeSilenceTimer);
        if (activeMaxTimer) clearTimeout(activeMaxTimer);
        activeSilenceTimer = null;
        activeMaxTimer = null;
        if (activeAudioContext) {{
          try {{ activeAudioContext.close(); }} catch (error) {{}}
          activeAudioContext = null;
        }}
        if (activeStream) {{
          activeStream.getTracks().forEach((track) => track.stop());
          activeStream = null;
        }}
      }}
      function setConversationUi(active) {{
        conversationButton.textContent = active ? "Gespräch beenden" : "Gespräch starten";
        listenButton.disabled = active;
        serverSttButton.disabled = active;
      }}
      async function transcribeAudioBlob(blob) {{
        const response = await fetch("/memorials/{html.escape(slug)}/speech-transcribe", {{
          method: "POST",
          headers: {{ "Content-Type": blob.type || "application/octet-stream" }},
          body: blob
        }});
        return readJsonResponse(response);
      }}
      function startSpeechInput() {{
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Recognition) {{
          speechNote.textContent = "Speech-to-Text wird von diesem Browser nicht unterstuetzt. Bitte Chrome/Edge verwenden oder die Frage tippen.";
          if (window.location.protocol === "https:" || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {{
            void startServerSpeechInput();
          }}
          return;
        }}
        if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {{
          speechNote.textContent = "Mikrofonzugriff braucht HTTPS. Bitte die https:// Adresse verwenden.";
          return;
        }}
        if (activeRecognition) {{
          try {{ activeRecognition.stop(); }} catch (error) {{}}
          activeRecognition = null;
        }}
        const recognition = new Recognition();
        activeRecognition = recognition;
        speechHadError = false;
        recognition.lang = "de-AT";
        recognition.interimResults = true;
        recognition.continuous = true;
        let finalText = "";
        recognition.onstart = () => {{
          speechNote.textContent = "Hoere zu...";
          listenButton.disabled = true;
          stopButton.disabled = false;
        }};
        recognition.onresult = (event) => {{
          let interim = "";
          for (let index = event.resultIndex; index < event.results.length; index += 1) {{
            const transcript = event.results[index][0].transcript;
            if (event.results[index].isFinal) finalText += transcript;
            else interim += transcript;
          }}
          question.value = (finalText || interim || "").trim();
        }};
        recognition.onerror = (event) => {{
          speechHadError = true;
          const errorCode = String(event.error || "unknown");
          const messages = {{
            "not-allowed": "Mikrofon nicht erlaubt. Bitte Browser-Berechtigung fuer myexternalbrain.com aktivieren.",
            "service-not-allowed": "Spracherkennungsdienst vom Browser blockiert. Bitte Chrome/Edge oder Texteingabe verwenden.",
            "no-speech": "Keine Sprache erkannt. Bitte naeher ans Mikrofon sprechen und erneut starten.",
            "audio-capture": "Kein Mikrofon gefunden oder vom System blockiert.",
            "network": "Browser-Spracherkennung hat ein Netzwerkproblem. Bitte Server-STT starten.",
            "aborted": "Spracherkennung gestoppt."
          }};
          speechNote.textContent = messages[errorCode] || ("Spracherkennung fehlgeschlagen: " + errorCode);
        }};
        recognition.onend = () => {{
          listenButton.disabled = false;
          stopButton.disabled = false;
          if (activeRecognition === recognition) activeRecognition = null;
          if (speechHadError) return;
          const text = normalizeTranscriptText(question.value || finalText || "");
          speechNote.textContent = text ? "Frage erkannt." : "Keine Frage erkannt. Bitte lauter sprechen, Mikrofon pruefen oder die Frage tippen.";
          if (text) askMemorialChat(text);
        }};
        try {{
          recognition.start();
        }} catch (error) {{
          activeRecognition = null;
          listenButton.disabled = false;
          speechNote.textContent = "Mikrofon konnte nicht gestartet werden. Bitte Seite neu laden oder Frage tippen.";
        }}
      }}
      async function startServerSpeechInput() {{
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {{
          speechNote.textContent = "Server-STT braucht MediaRecorder und Mikrofonzugriff. Bitte Chrome/Edge verwenden oder tippen.";
          return;
        }}
        if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {{
          speechNote.textContent = "Mikrofonzugriff braucht HTTPS. Bitte die https:// Adresse verwenden.";
          return;
        }}
        if (activeRecorder && activeRecorder.state === "recording") {{
          activeRecorder.stop();
          return;
        }}
        try {{
          const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
          const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
          const recorder = new MediaRecorder(stream, {{ mimeType }});
          activeRecorder = recorder;
          recorderChunks = [];
          recorder.ondataavailable = (event) => {{
            if (event.data && event.data.size > 0) recorderChunks.push(event.data);
          }};
          recorder.onstart = () => {{
            serverSttButton.textContent = "Server-STT stoppen";
            listenButton.disabled = true;
            speechNote.textContent = "Server-STT hoert zu. Zum Senden erneut klicken oder Stopp.";
          }};
          recorder.onerror = () => {{
            speechNote.textContent = "Audioaufnahme fehlgeschlagen. Bitte Berechtigung pruefen oder tippen.";
          }};
          recorder.onstop = async () => {{
            stream.getTracks().forEach((track) => track.stop());
            serverSttButton.textContent = "Server-STT starten";
            listenButton.disabled = false;
            activeRecorder = null;
            const blob = new Blob(recorderChunks, {{ type: mimeType }});
            recorderChunks = [];
            if (!blob.size) {{
              speechNote.textContent = "Keine Audioaufnahme erhalten. Bitte erneut versuchen.";
              return;
            }}
            speechNote.textContent = "Transkribiere Audio...";
            try {{
              const payload = await transcribeAudioBlob(blob);
              question.value = normalizeTranscriptText(payload.transcript_text || "");
              speechNote.textContent = question.value ? "Audio transkribiert." : "Keine Sprache im Audio erkannt.";
              if (question.value) askMemorialChat(question.value);
            }} catch (error) {{
              speechNote.textContent = "Server-STT fehlgeschlagen: " + String(error.message || error);
            }}
          }};
          recorder.start();
        }} catch (error) {{
          speechNote.textContent = "Mikrofon nicht verfuegbar oder nicht erlaubt.";
        }}
      }}
      async function recordConversationTurn() {{
        if (!conversationActive) return;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {{
          speechNote.textContent = "Gesprächsmodus braucht MediaRecorder. Bitte Chrome/Edge verwenden.";
          conversationActive = false;
          setConversationUi(false);
          return;
        }}
        try {{
          releaseConversationAudio();
          activeStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
          const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
          const recorder = new MediaRecorder(activeStream, {{ mimeType }});
          activeRecorder = recorder;
          recorderChunks = [];
          let chunkInterval = null;
          let stopped = false;
          const stopRecorder = (restart = false) => {{
            if (stopped) return;
            stopped = true;
            recorder._restartAfterStop = Boolean(restart);
            try {{
              if (recorder.state === "recording") recorder.stop();
            }} catch (error) {{}}
          }};
          recorder.ondataavailable = (event) => {{
            if (event.data && event.data.size > 0) recorderChunks.push(event.data);
          }};
          recorder.onstop = async () => {{
            releaseConversationAudio();
            activeRecorder = null;
            if (chunkInterval) clearInterval(chunkInterval);
            if (!conversationActive) return;
            const shouldRestart = Boolean(recorder._restartAfterStop);
            const blob = new Blob(recorderChunks, {{ type: mimeType }});
            recorderChunks = [];
            if (!blob.size) {{
              speechNote.textContent = "Ich höre weiter...";
              setTimeout(recordConversationTurn, 120);
              return;
            }}
            speechNote.textContent = "Transkribiere laufend...";
            try {{
              const payload = await transcribeAudioBlob(blob);
              const text = normalizeTranscriptText(payload.transcript_text || "");
              question.value = text;
              if (!text) {{
                speechNote.textContent = "Ich höre weiter...";
                setTimeout(recordConversationTurn, 120);
                return;
              }}
              speechNote.textContent = "Frage erkannt.";
              await askMemorialChat(text, {{ continueConversation: true }});
            }} catch (error) {{
              const message = String(error.message || error);
              if (message.includes("speech_transcription_failed") || message.includes("AUDIO_FORMAT") || message.includes("ungueltige Serverantwort")) {{
                speechNote.textContent = "Ich höre weiter...";
              }} else {{
                speechNote.textContent = "Server-STT fehlgeschlagen: " + message;
              }}
              if (conversationActive) setTimeout(recordConversationTurn, shouldRestart ? 120 : 650);
            }}
          }};
          recorder.start(900);
          speechNote.textContent = "Gespräch läuft. Ich transkribiere fortlaufend.";
          chunkInterval = setInterval(() => stopRecorder(true), 2400);
          activeMaxTimer = setTimeout(() => stopRecorder(true), 2600);
          try {{
            activeAudioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = activeAudioContext.createMediaStreamSource(activeStream);
            const analyser = activeAudioContext.createAnalyser();
            analyser.fftSize = 1024;
            source.connect(analyser);
            const data = new Uint8Array(analyser.fftSize);
            const checkLevel = () => {{
              if (!conversationActive || stopped) return;
              analyser.getByteTimeDomainData(data);
              let sum = 0;
              for (let index = 0; index < data.length; index += 1) {{
                const value = (data[index] - 128) / 128;
                sum += value * value;
              }}
              const rms = Math.sqrt(sum / data.length);
              if (rms > 0.025) {{
                speechNote.textContent = "Ich höre...";
              }}
              requestAnimationFrame(checkLevel);
            }};
            checkLevel();
          }} catch (error) {{
            speechNote.textContent = "Gespräch läuft. Ich transkribiere fortlaufend.";
          }}
        }} catch (error) {{
          speechNote.textContent = "Mikrofon nicht verfuegbar oder nicht erlaubt.";
          conversationActive = false;
          setConversationUi(false);
          releaseConversationAudio();
        }}
      }}
      function toggleConversation() {{
        conversationActive = !conversationActive;
        setConversationUi(conversationActive);
        if (conversationActive) {{
          recordConversationTurn();
        }} else {{
        if (activeRecorder && activeRecorder.state === "recording") {{
          try {{ activeRecorder.stop(); }} catch (error) {{}}
        }}
        releaseConversationAudio();
        speechNote.textContent = "Gespräch beendet.";
      }}
      }}
      form.addEventListener("submit", (event) => {{
        event.preventDefault();
        askMemorialChat(question.value);
      }});
      listenButton.addEventListener("click", startSpeechInput);
      serverSttButton.addEventListener("click", startServerSpeechInput);
      conversationButton.addEventListener("click", toggleConversation);
      speakButton.addEventListener("click", () => void speakText(lastAnswerText || answer.textContent));
      stopButton.addEventListener("click", () => {{
        conversationActive = false;
        setConversationUi(false);
        if (activeRecognition) {{
          speechHadError = true;
          try {{ activeRecognition.stop(); }} catch (error) {{}}
          activeRecognition = null;
        }}
        if (activeRecorder && activeRecorder.state === "recording") {{
          try {{ activeRecorder.stop(); }} catch (error) {{}}
        }}
        releaseConversationAudio();
        stopSpeechPlayback();
        speechNote.textContent = "Gestoppt.";
        listenButton.disabled = false;
        serverSttButton.disabled = false;
        serverSttButton.textContent = "Server-STT starten";
        stopButton.disabled = false;
      }});
      if (voiceConfigForm && voiceProfileSaveButton) {{
        voiceProfileSaveButton.addEventListener("click", saveVoiceConfig);
      }}
      if (ttsBaseVoiceToggle && ttsBaseVoiceVariantInput) {{
        ttsBaseVoiceToggle.addEventListener("click", (event) => {{
          const target = event.target instanceof HTMLElement ? event.target.closest("[data-variant]") : null;
          if (!target) return;
          const selected = String(target.getAttribute("data-variant") || "").trim();
          if (!selected) return;
          ttsBaseVoiceVariantInput.value = selected;
          memorialVoiceConfig.tts_base_voice_variant = selected;
          updateBaseVoiceVariantUi();
        }});
      }}
      if (voiceBuildButton) {{
        voiceBuildButton.addEventListener("click", buildVoiceProfile);
      }}
      if (ttsCloneButton) {{
        ttsCloneButton.addEventListener("click", cloneVoiceProfile);
      }}
      if (ttsPluginSelect) {{
        ttsPluginSelect.addEventListener("change", applyTtsPluginState);
      }}
      document.querySelectorAll("[data-prompt]").forEach((button) => {{
        button.addEventListener("click", () => {{
          question.value = button.getAttribute("data-prompt") || "";
          askMemorialChat(question.value);
        }});
      }});
      loadVoiceConfig();
      void refreshVoiceProfileSummary();
    </script>
  </body>
</html>"""


@router.get("/memorials/{slug}.json")
def public_memorial_manifest(slug: str) -> JSONResponse:
    return JSONResponse(_load_memorial(slug))


@router.get("/memorials/{slug}/voice-config")
def public_memorial_voice_config(slug: str) -> JSONResponse:
    return JSONResponse(_load_voice_config(slug))


@router.post("/memorials/{slug}/voice-config")
async def public_memorial_voice_config_update(slug: str, request: Request) -> JSONResponse:
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    _save_voice_config_payload(slug=slug, payload=payload)
    return JSONResponse(_load_voice_config(slug))


@router.get("/memorials/{slug}/voice-profile")
def public_memorial_voice_profile(slug: str) -> JSONResponse:
    _load_memorial(slug)
    return JSONResponse(_public_voice_profile_summary(slug))


@router.post("/memorials/{slug}/voice-profile/build")
async def public_memorial_voice_profile_build(slug: str, request: Request) -> JSONResponse:
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        payload = {}
    youtube_urls, youtube_query, youtube_limit = _normalize_voice_build_payload(payload)
    public_paths = _collect_memorial_public_audio_paths(memorial, slug)
    if not public_paths and not youtube_urls and not youtube_query:
        raise HTTPException(status_code=400, detail="voice_profile_no_source")
    try:
        build_memorial_voice_profile(
            slug=slug,
            public_audio_paths=public_paths,
            youtube_query=youtube_query,
            youtube_urls=youtube_urls,
            youtube_limit=youtube_limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc
    return JSONResponse(_public_voice_profile_summary(slug))


@router.get("/memorials/files/{slug}/{asset_path:path}")
def public_memorial_file(slug: str, asset_path: str) -> FileResponse:
    path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/memorials/{slug}/chat")
async def public_memorial_chat(slug: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    selected_model, _, _ = _resolve_memorial_chat_model(payload, private_profile, _text(body.get("llm_model")))
    answer = _memorial_chat_answer(payload, _text(body.get("question")), private_profile, requested_model=selected_model)
    return JSONResponse(answer)


@router.post("/memorials/{slug}/speech-transcribe")
async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    _load_memorial(slug)
    payload = await request.body()
    content_type = str(request.headers.get("content-type") or "application/octet-stream")
    return JSONResponse(_memorial_transcribe_audio_blob(payload=payload, content_type=content_type))


@router.post("/memorials/{slug}/speech-synthesize")
async def public_memorial_speech_synthesize(slug: str, request: Request) -> Response:
    _load_memorial(slug)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    base_config = _load_voice_config(slug)
    merged_config = dict(base_config)
    merged_config.update(body)
    tts_options = _tts_plugin_options(
        payload=merged_config,
        voice_profile_ready=bool(base_config.get("voice_profile_ready")),
    )
    selected_plugin, selected_option = _resolve_tts_plugin(payload=merged_config, options=tts_options)
    if selected_plugin != OPENVOICE_TTS_PLUGIN_ID:
        raise HTTPException(status_code=400, detail="unsupported_tts_plugin")
    if not bool(selected_option.get("tts_plugin_enabled")):
        raise HTTPException(status_code=409, detail="tts_plugin_not_ready")
    text = _normalize_tts_text(body.get("text"))
    if not text:
        raise HTTPException(status_code=400, detail="tts_text_missing")
    voice_id = _text(
        merged_config.get("tts_plugin_voice_id"),
        _text(selected_option.get("tts_plugin_voice_id"), str(base_config.get("tts_plugin_voice_id"))),
    )
    if not voice_id:
        raise HTTPException(status_code=409, detail="tts_voice_id_missing")
    audio, content_type = openvoice_synthesize_request_with_variant(
        text=text,
        voice_id=voice_id,
        lang=_text(merged_config.get("lang"), "de-AT"),
        base_voice_variant=_text(merged_config.get("tts_base_voice_variant"), "default"),
    )
    return Response(content=audio, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.post("/memorials/{slug}/voice-clone")
async def public_memorial_voice_clone(slug: str, request: Request) -> JSONResponse:
    memorial = _load_memorial(slug)
    _require_public_memorial_write_access(slug=slug, request=request, memorial=memorial)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        body = {}
    memory_person_name = _text(memorial.get("person_name"), "Memorial")
    voice_label = _text(body.get("voice_label"), _text(body.get("label"), f"{memory_person_name} OpenVoice"))
    cloned_voice_id = _openvoice_clone_from_memorial(slug=slug, voice_label=voice_label)
    _save_voice_config_payload(
        slug=slug,
        payload={
            "tts_plugin": OPENVOICE_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": cloned_voice_id,
        },
    )
    return JSONResponse(_load_voice_config(slug))


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> HTMLResponse:
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    return HTMLResponse(
        _memorial_html(
            payload,
            private_profile=private_profile,
            hostname=request_hostname(request),
        )
    )


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> HTMLResponse:
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    return HTMLResponse(
        _memorial_html(
            payload,
            private_profile=private_profile,
            hostname=request_hostname(request),
        )
    )
