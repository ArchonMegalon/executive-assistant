from __future__ import annotations

from typing import Callable


def _is_public_item(item: object, *, text: Callable[[object, str], str]) -> bool:
    if not isinstance(item, dict):
        return False
    visibility = text(item.get("visibility"), "").lower()
    public_flag = item.get("public")
    if visibility:
        return visibility == "public" and public_flag is not False
    return public_flag is True


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
    story_text: Callable[..., str],
    censored_memory_preview: Callable[[object], str],
    safe_external_url: Callable[[object], str],
    safe_audio_relpath: Callable[[object], str],
    public_list: Callable[[object, set[str]], list[dict[str, object]]],
    public_memorial_archive_registry: Callable[[str], dict[str, object]],
    memorial_video_call_avatar: Callable[[dict[str, object], str], dict[str, object]],
    public_video_meeting_payload: Callable[..., dict[str, object]],
    approved_memory_excerpt: Callable[[object], str] | None = None,
) -> dict[str, object]:
    public_payload: dict[str, object] = {}
    top_level_text_limits = {
        "slug": 80,
        "person_name": 180,
        "title": 220,
        "subtitle": 420,
        "intro": 1200,
        "disclosure": 1200,
        "voice_label": 180,
        "tts_plugin": 120,
        "tts_base_voice_variant": 120,
        "voice_profile_generated_at": 80,
    }
    for key, max_chars in top_level_text_limits.items():
        if key not in safe_json_keys:
            continue
        value = story_text(payload.get(key), max_chars=max_chars)
        if value:
            public_payload[key] = value
    if "relationship" in safe_json_keys and payload.get("relationship_public") is True:
        relationship = story_text(payload.get("relationship"), max_chars=120)
        if relationship:
            public_payload["relationship"] = relationship
    if "voice_profile_ready" in safe_json_keys and isinstance(payload.get("voice_profile_ready"), bool):
        public_payload["voice_profile_ready"] = payload["voice_profile_ready"]

    public_audio: list[dict[str, object]] = []
    for item in public_list(
        payload.get("audio_clips"),
        {"label", "title", "description", "asset_relpath", "public_transcript"},
    )[:8]:
        relpath = safe_audio_relpath(item.get("asset_relpath"))
        if not relpath:
            continue
        clip = {
            "label": story_text(item.get("label"), max_chars=100),
            "title": story_text(item.get("title"), max_chars=180),
            "description": story_text(item.get("description"), max_chars=600),
            "asset_relpath": relpath,
            "public_transcript": story_text(item.get("public_transcript"), max_chars=3000),
        }
        public_audio.append({key: value for key, value in clip.items() if value})
    public_payload["audio_clips"] = public_audio

    public_memories: list[dict[str, object]] = []
    for item in public_list(
        payload.get("memory_cards"),
        {"source_label", "title", "body", "public_excerpt"},
    )[:12]:
        curated_excerpt = (
            approved_memory_excerpt(item.get("public_excerpt"))
            if approved_memory_excerpt is not None and item.get("public_excerpt")
            else ""
        )
        memory = {
            "source_label": story_text(item.get("source_label"), max_chars=160),
            "title": story_text(item.get("title"), max_chars=180),
            "body": curated_excerpt or censored_memory_preview(item.get("body") or item.get("title")),
            "curation_status": "approved_public_excerpt" if curated_excerpt else "strongly_redacted_preview",
        }
        public_memories.append({key: value for key, value in memory.items() if value})
    public_payload["memory_cards"] = public_memories

    public_candidates: list[dict[str, object]] = []
    for item in public_list(
        payload.get("candidate_recordings"),
        {"title", "recorded_at", "status"},
    )[:8]:
        candidate = {
            "title": story_text(item.get("title"), max_chars=180),
            "recorded_at": story_text(item.get("recorded_at"), max_chars=80),
            "status": story_text(item.get("status"), max_chars=360),
        }
        public_candidates.append({key: value for key, value in candidate.items() if value})
    public_payload["candidate_recordings"] = public_candidates
    raw_prompts = payload.get("suggested_prompts")
    public_payload["suggested_prompts"] = [
        item.strip()[:180]
        for item in (raw_prompts if isinstance(raw_prompts, (list, tuple)) else [])
        if isinstance(item, str) and item.strip()
    ][:8]
    slug = story_text(payload.get("slug"), max_chars=80)
    if slug:
        archive_registry = public_memorial_archive_registry(slug)
        if not isinstance(archive_registry, dict):
            archive_registry = {}
        public_publications: list[dict[str, object]] = []
        public_publication_ids: set[str] = set()
        for raw_item in list(archive_registry.get("fliplink_publications") or [])[:24]:
            if not isinstance(raw_item, dict):
                continue
            audience = story_text(raw_item.get("audience"), max_chars=40).lower()
            review_status = story_text(raw_item.get("review_status"), max_chars=40).lower()
            if audience != "public" or review_status not in {"approved", "published"}:
                continue
            publication_id = story_text(raw_item.get("id"), max_chars=160)
            publication_slug = story_text(raw_item.get("slug"), max_chars=160)
            raw_url = story_text(raw_item.get("url"), max_chars=2048)
            internal_prefix = f"/memorials/{slug}/archive/"
            if raw_url.startswith(internal_prefix):
                url = raw_url if not any(token in raw_url for token in ("\\", "?", "#", "%", "/../", "/./")) else ""
            else:
                url = safe_external_url(raw_url)
            publication = {
                "id": publication_id,
                "title": story_text(raw_item.get("title"), max_chars=220),
                "audience": "public",
                "viewer_type": story_text(raw_item.get("viewer_type"), max_chars=60),
                "type": story_text(raw_item.get("type"), max_chars=60),
                "url": url,
                "thumbnail": safe_external_url(raw_item.get("thumbnail")),
                "description": story_text(raw_item.get("description"), max_chars=600),
                "sensitivity": story_text(raw_item.get("sensitivity"), max_chars=80),
                "review_status": review_status,
                "version": story_text(raw_item.get("version"), max_chars=80),
                "publication_id": story_text(raw_item.get("publication_id"), max_chars=180),
                "slug": publication_slug,
                "noindex": raw_item.get("noindex") is True,
            }
            if not publication_id or not publication["title"] or not url:
                continue
            public_publications.append({key: value for key, value in publication.items() if value != ""})
            public_publication_ids.add(publication_id)
        public_payload["fliplink_publications"] = public_publications

        public_sections: list[dict[str, object]] = []
        for raw_section in list(archive_registry.get("archive_sections") or [])[:12]:
            if not isinstance(raw_section, dict):
                continue
            if story_text(raw_section.get("audience"), max_chars=40).lower() != "public":
                continue
            item_ids = [
                item_id
                for raw_item_id in list(raw_section.get("items") or [])[:24]
                if (item_id := story_text(raw_item_id, max_chars=160)) in public_publication_ids
            ]
            title = story_text(raw_section.get("title"), max_chars=220)
            if title and item_ids:
                public_sections.append({"title": title, "audience": "public", "items": item_ids})
        public_payload["archive_sections"] = public_sections
    else:
        public_payload["archive_sections"] = []
        public_payload["fliplink_publications"] = []

    public_profile: list[dict[str, object]] = []
    for item in public_list(
        payload.get("source_grounded_profile"),
        {"trait", "confidence", "evidence"},
    )[:16]:
        profile_item = {
            "trait": story_text(item.get("trait"), max_chars=240),
            "confidence": story_text(item.get("confidence"), max_chars=120),
            "evidence": story_text(item.get("evidence"), max_chars=1200),
        }
        public_profile.append({key: value for key, value in profile_item.items() if value})
    public_payload["source_grounded_profile"] = public_profile

    public_sources: list[dict[str, object]] = []
    for item in public_list(
        payload.get("external_sources"),
        {"label", "url", "status", "approved"},
    )[:24]:
        if item.get("approved") is not True:
            continue
        url = safe_external_url(item.get("url"))
        if not url:
            continue
        source = {
            "label": story_text(item.get("label"), max_chars=220),
            "url": url,
            "status": story_text(item.get("status"), max_chars=160),
        }
        public_sources.append({key: value for key, value in source.items() if value})
    public_payload["external_sources"] = public_sources

    public_payload["character_notes"] = [
        note
        for item in public_list(payload.get("character_notes"), {"note"})
        if (note := story_text(item.get("note"), max_chars=900))
    ][:12]
    conversation_style = payload.get("conversation_style")
    if isinstance(conversation_style, dict) and _is_public_item(conversation_style, text=text):
        public_style = {
            key: value
            for key in ("reasoning_frame", "conflict_style", "social_tone")
            if (value := story_text(conversation_style.get(key), max_chars=600))
        }
        public_style["should_avoid"] = [
            value
            for raw_value in list(conversation_style.get("should_avoid") or [])[:12]
            if (value := story_text(raw_value, max_chars=300))
        ]
        public_payload["conversation_style"] = public_style
    else:
        public_payload["conversation_style"] = {}
    public_avatar = memorial_video_call_avatar(payload, slug) if slug else memorial_video_call_avatar(payload, "")
    if not isinstance(public_avatar, dict):
        public_avatar = {}
    avatar_enabled = public_avatar.get("enabled") is True
    public_payload["video_call_avatar"] = {
        "enabled": avatar_enabled,
        "kind": story_text(public_avatar.get("kind"), max_chars=80) or "portrait",
        "provider_label": story_text(public_avatar.get("provider_label"), max_chars=180) or "VidBoard noch nicht live",
        "title": story_text(public_avatar.get("title"), max_chars=220)
        or story_text(payload.get("person_name"), max_chars=180)
        or "Manfred",
        "detail": story_text(public_avatar.get("detail"), max_chars=600)
        or "Der Video-Avatar ist noch nicht freigegeben.",
        "asset_url": story_text(public_avatar.get("asset_url"), max_chars=1024) if avatar_enabled else "",
        "poster_url": story_text(public_avatar.get("poster_url"), max_chars=1024) if avatar_enabled else "",
    }
    raw_meeting = public_video_meeting_payload(
        slug=slug,
        person_name=story_text(payload.get("person_name"), max_chars=180) or "Manfred",
    )
    if not isinstance(raw_meeting, dict):
        raw_meeting = {}
    meeting: dict[str, object] = {}
    for key, max_chars in {
        "contract_name": 160,
        "integration_state": 120,
        "provider_key": 80,
        "provider_label": 120,
        "title": 220,
        "detail": 900,
        "fallback_mode": 120,
        "session_endpoint": 320,
        "status_endpoint": 320,
        "recommended_provider": 80,
        "secondary_provider": 80,
        "next_action": 160,
    }.items():
        value = story_text(raw_meeting.get(key), max_chars=max_chars)
        if value:
            meeting[key] = value
    for key in (
        "enabled",
        "provider_truth_allowed",
        "provider_session_creation_allowed",
        "live_provider_runtime_verified",
        "gold_claim_allowed",
        "camera_optional",
        "microphone_required",
    ):
        if isinstance(raw_meeting.get(key), bool):
            meeting[key] = raw_meeting[key]
    public_payload["video_meeting"] = meeting
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
