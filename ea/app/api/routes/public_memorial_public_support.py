from __future__ import annotations

from typing import Callable


def _is_public_item(item: object, *, text: Callable[[object, str], str]) -> bool:
    if not isinstance(item, dict):
        return False
    visibility = text(item.get("visibility"), "").lower()
    if visibility == "public":
        return True
    return bool(item.get("public") is True)


def _public_list(
    items: object,
    *,
    allowed_keys: set[str],
    list_of_dicts: Callable[[object], list[dict[str, object]]],
    text: Callable[[object, str], str],
) -> list[dict[str, object]]:
    public_items: list[dict[str, object]] = []
    for item in list_of_dicts(items):
        if not _is_public_item(item, text=text):
            continue
        public_items.append({key: value for key, value in item.items() if key in allowed_keys})
    return public_items


def _public_memorial_payload(
    payload: dict[str, object],
    *,
    safe_json_keys: set[str],
    text: Callable[[object, str], str],
    public_list: Callable[[object, set[str]], list[dict[str, object]]],
    public_memorial_archive_registry: Callable[[str], dict[str, object]],
    memorial_video_call_avatar: Callable[[dict[str, object], str], dict[str, object]],
    public_video_meeting_payload: Callable[..., dict[str, object]],
) -> dict[str, object]:
    public_payload = {key: value for key, value in payload.items() if key in safe_json_keys}
    slug = text(payload.get("slug"), "")
    if slug:
        archive_registry = public_memorial_archive_registry(slug)
        public_payload["archive_sections"] = list(archive_registry.get("archive_sections") or [])
        public_payload["fliplink_publications"] = list(archive_registry.get("fliplink_publications") or [])
    public_payload["source_grounded_profile"] = public_list(
        payload.get("source_grounded_profile"),
        {"trait", "confidence", "evidence"},
    )
    public_payload["external_sources"] = public_list(
        payload.get("external_sources"),
        {"label", "url", "status"},
    )
    public_payload["character_notes"] = [
        text(item.get("note"), "")
        for item in public_list(payload.get("character_notes"), {"note"})
        if text(item.get("note"), "")
    ]
    conversation_style = payload.get("conversation_style")
    if isinstance(conversation_style, dict) and _is_public_item(conversation_style, text=text):
        public_payload["conversation_style"] = {
            key: conversation_style.get(key)
            for key in ("reasoning_frame", "conflict_style", "social_tone", "should_avoid")
            if key in conversation_style
        }
    else:
        public_payload["conversation_style"] = {}
    public_avatar = memorial_video_call_avatar(payload, slug) if slug else memorial_video_call_avatar(payload, "")
    public_payload["video_call_avatar"] = {
        "enabled": bool(public_avatar.get("enabled")),
        "kind": text(public_avatar.get("kind"), "portrait"),
        "provider_label": text(public_avatar.get("provider_label"), "VidBoard noch nicht live"),
        "title": text(public_avatar.get("title"), text(payload.get("person_name"), "Manfred")),
        "detail": text(public_avatar.get("detail"), "Der Video-Avatar ist noch nicht freigegeben."),
        "asset_url": text(public_avatar.get("asset_url"), "") if bool(public_avatar.get("enabled")) else "",
        "poster_url": text(public_avatar.get("poster_url"), "") if bool(public_avatar.get("enabled")) else "",
    }
    public_payload["video_meeting"] = public_video_meeting_payload(slug=slug, person_name=text(payload.get("person_name"), "Manfred"))
    return public_payload


def _public_voice_config_payload(
    slug: str,
    payload: dict[str, object],
    *,
    text: Callable[[object, str], str],
    public_voice_profile_summary: Callable[[str], dict[str, object]],
    tts_plugin_options: Callable[..., list[dict[str, object]]],
    safe_tts_plugin_id: Callable[[object], str],
    tts_plugin_default_id: str,
) -> dict[str, object]:
    raw_notes = payload.get("notes")
    if isinstance(raw_notes, str):
        notes = [text(raw_notes, "")]
    elif isinstance(raw_notes, (list, tuple, set)):
        notes = [text(item, "") for item in raw_notes]
    else:
        notes = []
    voice_profile_summary = public_voice_profile_summary(slug)
    tts_options = tts_plugin_options(payload=payload, voice_profile_ready=bool(voice_profile_summary.get("voice_profile_ready")))
    selected_plugin_id = safe_tts_plugin_id(payload.get("tts_plugin")) or tts_plugin_default_id
    selected_option = next(
        (option for option in tts_options if safe_tts_plugin_id(option.get("tts_plugin")) == selected_plugin_id),
        {},
    )
    safe_options = [
        {
            "tts_plugin": safe_tts_plugin_id(option.get("tts_plugin")),
            "tts_plugin_label": text(option.get("tts_plugin_label"), ""),
            "tts_plugin_description": text(option.get("tts_plugin_description"), ""),
            "tts_plugin_enabled": bool(option.get("tts_plugin_enabled")),
            "tts_plugin_clone_capable": bool(option.get("tts_plugin_clone_capable")),
            "tts_plugin_needs_clone": bool(option.get("tts_plugin_needs_clone")),
            "tts_plugin_requires_voice_id": bool(option.get("tts_plugin_requires_voice_id")),
        }
        for option in ([selected_option] if selected_option else [])
        if safe_tts_plugin_id(option.get("tts_plugin"))
    ]
    return {
        "slug": slug,
        "tts_plugin": selected_plugin_id,
        "tts_mode": selected_plugin_id,
        "tts_base_voice_variant": text(payload.get("tts_base_voice_variant"), "default"),
        "voice_label": text(payload.get("voice_label"), "Manfreds Stimme"),
        "voice_profile_ready": bool(voice_profile_summary.get("voice_profile_ready")),
        "voice_profile_generated_at": text(voice_profile_summary.get("voice_profile_generated_at"), ""),
        "voice_profile_policy": dict(voice_profile_summary.get("voice_profile_policy") or {}),
        "voice_profile_sources": dict(voice_profile_summary.get("voice_profile_sources") or {}),
        "lang": text(payload.get("lang"), "de-AT"),
        "rate": payload.get("rate"),
        "pitch": payload.get("pitch"),
        "volume": payload.get("volume"),
        "voice_name_hints": [str(item).strip() for item in list(payload.get("voice_name_hints") or [])[:8] if str(item or "").strip()],
        "tts_plugin_options": safe_options,
        "notes": [item for item in notes[:6] if item],
    }


def _public_voice_ab_variant_payload(variant: dict[str, object], *, text: Callable[[object, str], str]) -> dict[str, object]:
    return {
        "id": text(variant.get("id"), ""),
        "label": text(variant.get("label"), "Stimme"),
        "description": text(variant.get("description"), ""),
    }


def _public_voice_profile_payload(summary: dict[str, object], *, text: Callable[[object, str], str]) -> dict[str, object]:
    public_summary = dict(summary)
    assets: list[dict[str, object]] = []
    for raw_item in list(summary.get("voice_profile_sample_assets") or [])[:4]:
        item = dict(raw_item or {})
        kind = text(item.get("kind"), "sample")
        source = text(item.get("source_label"), "").lower()
        coarse_label = "public_clip"
        if "youtube" in source or "youtube" in kind.lower():
            coarse_label = "youtube_audio"
        elif "upload" in source or "upload" in kind.lower():
            coarse_label = "uploaded_sample"
        assets.append(
            {
                "kind": kind,
                "source_label": coarse_label,
                "analysis_status": text(item.get("analysis_status"), ""),
                "duration_seconds": item.get("duration_seconds"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    public_summary["voice_profile_sample_assets"] = assets
    return public_summary


def _resolved_voice_consent(
    payload: dict[str, object],
    *,
    text: Callable[[object, str], str],
    load_voice_config: Callable[[str], dict[str, object]],
) -> dict[str, object]:
    explicit = dict(payload.get("voice_consent") or {}) if isinstance(payload.get("voice_consent"), dict) else {}
    if explicit:
        return explicit
    slug = text(payload.get("slug"), "")
    if slug:
        try:
            voice_payload = load_voice_config(slug)
        except Exception:
            voice_payload = {}
        explicit = dict(voice_payload.get("voice_consent") or {}) if isinstance(voice_payload.get("voice_consent"), dict) else {}
        if explicit:
            return explicit
    return {}


def _require_voice_consent(
    payload: dict[str, object],
    action: str,
    *,
    resolved_voice_consent: Callable[[dict[str, object]], dict[str, object]],
    http_exception_cls: type[Exception],
) -> None:
    consent = resolved_voice_consent(payload)
    if consent.get("status") != "approved" or bool(consent.get("revoked")):
        raise http_exception_cls(status_code=403, detail="voice_consent_required")
    scope = {str(item).strip() for item in list(consent.get("scope") or []) if str(item or "").strip()}
    if action not in scope:
        raise http_exception_cls(status_code=403, detail="voice_consent_scope_missing")


def _payload_with_slug(
    slug: str,
    payload: dict[str, object],
    *,
    safe_slug: Callable[[str], str],
) -> dict[str, object]:
    merged = dict(payload)
    merged["slug"] = safe_slug(slug)
    return merged
