from __future__ import annotations

import html
import json
import hmac
import mimetypes
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.services.public_clickrank import clickrank_head_snippet, request_hostname
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


def _float_between(value: object, *, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def _load_voice_config(slug: str) -> dict[str, object]:
    default_config = {
        "tts_mode": "browser_speech_synthesis",
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "synthetic_voice_clone_of_memorial_person": False,
        "consent_basis": "generic_or_owner_consented_voice",
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
            default_config.update(
                {
                    "tts_mode": _text(payload.get("tts_mode"), str(default_config["tts_mode"])),
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
                }
            )
    # Safety invariant: production never reports full speech cloning support to memorial users.
    # Keep provider-compatible fields but clearly expose safe-profile policy only.
    default_config["tts_mode"] = "browser_speech_synthesis"
    default_config["synthetic_voice_clone_of_memorial_person"] = False
    default_config.update(_public_voice_profile_summary(slug))
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
    safe_config = {
        "voice_profile_id": _text(payload.get("voice_profile_id"), f"tts-{slug}"),
        "voice_label": _text(payload.get("voice_label"), "Austauschbare synthetische Stimme"),
        "lang": _text(payload.get("lang"), "de-AT")[:16] or "de-AT",
        "rate": _float_between(payload.get("rate"), fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": _float_between(payload.get("pitch"), fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": _float_between(payload.get("volume"), fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": _safe_voice_name_hints(payload.get("voice_name_hints")),
    }
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
    default_config = {
        "tts_mode": "browser_speech_synthesis",
        "voice_profile_id": "default-browser-synthetic",
        "voice_label": "Austauschbare synthetische Stimme",
        "lang": "de-AT",
        "rate": 0.92,
        "pitch": 0.92,
        "volume": 1.0,
        "voice_name_hints": ["de-AT", "de-DE", "German"],
        "consent_basis": "generic_or_owner_consented_voice",
    }
    return {
        "tts_mode": "browser_speech_synthesis",
        "voice_profile_id": _text(payload.get("voice_profile_id") if isinstance(payload, dict) else None, str(default_config["voice_profile_id"])),
        "voice_label": _text(payload.get("voice_label") if isinstance(payload, dict) else None, str(default_config["voice_label"])),
        "lang": _text(payload.get("lang") if isinstance(payload, dict) else None, str(default_config["lang"]))[:16] or "de-AT",
        "rate": _float_between(payload.get("rate") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.45, maximum=1.5),
        "pitch": _float_between(payload.get("pitch") if isinstance(payload, dict) else None, fallback=0.92, minimum=0.5, maximum=1.5),
        "volume": _float_between(payload.get("volume") if isinstance(payload, dict) else None, fallback=1.0, minimum=0.0, maximum=1.0),
        "voice_name_hints": _normalize_voice_name_hints_csv(payload.get("voice_name_hints") if isinstance(payload, dict) else None),
        "consent_basis": _text(payload.get("consent_basis") if isinstance(payload, dict) else None, str(default_config["consent_basis"])),
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
    normalized = _voice_config_to_public_payload(_normalize_voice_config_payload(payload), slug=slug)
    normalized.update({
        "tts_mode": "browser_speech_synthesis",
        "synthetic_voice_clone_of_memorial_person": False,
    })
    _write_json_atomic(_voice_config_path(slug=slug), normalized)


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


def _memorial_chat_answer(payload: dict[str, object], question: str, private_profile: dict[str, object]) -> dict[str, object]:
    person_name = _text(payload.get("person_name"), "Manfred")
    normalized_question = " ".join(str(question or "").strip().split())
    if not normalized_question:
        raise HTTPException(status_code=400, detail="question_missing")
    if len(normalized_question) > 1200:
        raise HTTPException(status_code=400, detail="question_too_long")
    lowered = normalized_question.lower()
    facts = _compact_public_facts(payload)
    private_notes = _list_of_dicts(private_profile.get("family_context_notes"))
    source_labels = ["Originalaufnahme: Hanusch Krankenhaus"] + [
        _text(source.get("label"))
        for source in _list_of_dicts(payload.get("external_sources"))
        if _text(source.get("label"))
    ][:4]
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
    return {
        "person_name": person_name,
        "mode": "memorial_first_person_memory_chat",
        "question": normalized_question,
        "answer": body,
        "sources": [item for item in source_labels if item],
        "private_context_used": bool(private_notes),
        "safety_note": "Erinnerungsmodus in Ich-Form: keine Behauptung, dass die verstorbene Person real antwortet; keine synthetische Stimmnachbildung der verstorbenen Person.",
    }


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


def _memorial_html(payload: dict[str, object], *, hostname: str = "") -> str:
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
        --paper: #f7f1e8;
        --ink: #211f1b;
        --muted: #665f55;
        --line: rgba(33, 31, 27, 0.16);
        --panel: #fffaf2;
        --sage: #53685b;
        --wine: #7d3236;
        --blue: #2e5266;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--paper);
        color: var(--ink);
        font: 16px/1.6 ui-serif, Georgia, "Times New Roman", serif;
      }}
      a {{ color: inherit; }}
      .wrap {{ width: min(1120px, calc(100vw - 36px)); margin: 0 auto; }}
      header {{
        min-height: 86vh;
        display: grid;
        align-items: end;
        border-bottom: 1px solid var(--line);
        background:
          linear-gradient(180deg, rgba(247,241,232,0.58), rgba(247,241,232,0.98)),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='720' viewBox='0 0 1200 720'%3E%3Crect width='1200' height='720' fill='%23efe2d0'/%3E%3Cpath d='M0 520 C220 420 340 590 560 500 C780 410 880 260 1200 320 L1200 720 L0 720 Z' fill='%2353685b' opacity='.28'/%3E%3Cpath d='M0 420 C230 330 390 430 620 360 C850 290 970 160 1200 210 L1200 720 L0 720 Z' fill='%232e5266' opacity='.20'/%3E%3Ccircle cx='940' cy='170' r='80' fill='%23fff7dc' opacity='.72'/%3E%3C/svg%3E");
        background-size: cover;
        background-position: center;
      }}
      .hero {{ padding: 42px 0 34px; max-width: 820px; }}
      .eyebrow {{
        margin: 0 0 10px;
        color: var(--wine);
        font: 700 12px/1.2 ui-sans-serif, system-ui, sans-serif;
        letter-spacing: .08em;
        text-transform: uppercase;
      }}
      h1 {{ margin: 0; font-size: clamp(2.3rem, 7vw, 5.6rem); line-height: .96; font-weight: 560; }}
      h2 {{ margin: 0 0 12px; font-size: clamp(1.55rem, 3vw, 2.4rem); line-height: 1.1; font-weight: 560; }}
      h3 {{ margin: 0 0 6px; font-size: 1.06rem; line-height: 1.25; }}
      p {{ margin: 0; }}
      .lead {{ margin-top: 20px; max-width: 64ch; color: var(--muted); font-size: 1.12rem; }}
      .notice {{
        margin-top: 22px;
        max-width: 760px;
        padding: 14px 16px;
        border-left: 4px solid var(--sage);
        background: rgba(255,250,242,.82);
        color: var(--muted);
      }}
      main {{ padding: 44px 0 72px; }}
      section {{ margin-top: 44px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
      .clip, .memory, .chat, .candidate, .profile-note, .voice-tools {{
        border: 1px solid var(--line);
        background: var(--panel);
        border-radius: 8px;
        padding: 18px;
      }}
      .voice-tools {{ background: #f7f9f8; border-color: rgba(83,104,91,.24); }}
      .voice-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
      .voice-field {{ display: grid; gap: 6px; }}
      .voice-actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
      .voice-input {{
        width: 100%;
        border: 1px solid rgba(46,82,102,.28);
        border-radius: 8px;
        padding: 10px;
        background: #fffaf2;
        color: var(--ink);
        font: 14px/1.4 ui-sans-serif, system-ui, sans-serif;
      }}
      .voice-input[type="range"] {{ max-width: 100%; }}
      .voice-status {{ color: var(--muted); font-size: .93rem; min-height: 1.4em; }}
      .status-note {{ margin-top: 12px; color: var(--muted); }}
      label {{ font: 600 12px/1.2 ui-sans-serif, system-ui, sans-serif; letter-spacing: 0.01em; }}
      .clip {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .65fr); gap: 18px; align-items: center; }}
      audio {{ width: 100%; }}
      .memory p:last-child, .clip p:last-child, .chat p {{ color: var(--muted); }}
      .candidates {{ display: grid; gap: 10px; }}
      .candidate {{ display: grid; grid-template-columns: minmax(0, 1fr) 170px; gap: 12px; align-items: start; }}
      .candidate span, .candidate p {{ color: var(--muted); }}
      .candidate p {{ grid-column: 1 / -1; }}
      .sources {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
      .sources li {{ border-bottom: 1px solid var(--line); padding: 10px 0; display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 12px; }}
      .sources span {{ color: var(--muted); }}
      .chat {{ background: #eef3ef; border-color: rgba(83,104,91,.24); }}
      .prompt-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
      .chat-form {{ display: grid; gap: 12px; margin-top: 18px; }}
      .voice-build {{ display: grid; gap: 10px; margin-top: 12px; }}
      .speech-row {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
      textarea {{
        width: 100%;
        min-height: 112px;
        resize: vertical;
        border: 1px solid rgba(46,82,102,.28);
        border-radius: 8px;
        padding: 12px;
        background: #fffaf2;
        color: var(--ink);
        font: 16px/1.5 ui-sans-serif, system-ui, sans-serif;
      }}
      .chat-actions {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
      .speech-note {{ color: var(--muted); font-size: .94rem; }}
      .chat-answer {{
        margin-top: 16px;
        padding: 16px;
        border: 1px solid rgba(83,104,91,.24);
        border-radius: 8px;
        background: rgba(255,250,242,.72);
        white-space: pre-wrap;
        color: var(--ink);
      }}
      .chat-answer:empty {{ display: none; }}
      button {{
        border: 1px solid rgba(46,82,102,.28);
        background: #fffaf2;
        color: var(--blue);
        border-radius: 999px;
        padding: 9px 12px;
        font: 650 14px/1 ui-sans-serif, system-ui, sans-serif;
      }}
      footer {{ border-top: 1px solid var(--line); padding: 24px 0; color: var(--muted); }}
      @media (max-width: 760px) {{
        header {{ min-height: 78vh; }}
        .grid, .clip {{ grid-template-columns: 1fr; }}
        .wrap {{ width: min(100vw - 28px, 1120px); }}
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
        <p class="lead">Die Seite nutzt Browser-STT/TTS. Du kannst eine bevorzugte Stimme wählen und einen Fingerprint auf Basis echter Audioquellen aufbauen.</p>
        <form class="voice-grid" id="memorial-voice-config-form">
          <div class="voice-field">
            <label for="memorial-voice-label">Stimmenlabel</label>
            <input id="memorial-voice-label" class="voice-input" type="text" value="{voice_label}" autocomplete="off">
          </div>
          <div class="voice-field">
            <label for="memorial-voice-lang">Sprache</label>
            <input id="memorial-voice-lang" class="voice-input" type="text" value="{html.escape(_text(voice_config.get('lang'), 'de-AT'))[:16]}">
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
        <div class="speech-row">
          <button type="button" id="memorial-conversation">Gespräch starten</button>
          <button type="button" id="memorial-speech-listen" hidden>Mikrofon starten</button>
          <button type="button" id="memorial-server-stt" hidden>Server-STT starten</button>
          <button type="button" id="memorial-speech-speak" hidden>Antwort vorlesen</button>
          <button type="button" id="memorial-speech-stop" hidden>Stopp</button>
          <span class="speech-note" id="memorial-speech-note">Browser-STT/TTS, {voice_label}.</span>
        </div>
        <form class="chat-form" id="memorial-chat-form">
          <textarea id="memorial-chat-question" name="question" placeholder="Frag nach einer Erinnerung, Quelle oder vorsichtigen Einordnung."></textarea>
          <div class="chat-actions">
            <button type="submit">Antwort formulieren</button>
            <span id="memorial-chat-status"></span>
          </div>
        </form>
        <div class="chat-answer" id="memorial-chat-answer"></div>
      </section>
    </main>
    <footer>
      <div class="wrap">Hosted on myexternalbrain.com · Originalstimme nur aus freigegebenen Aufnahmen.</div>
    </footer>
    <script>
      const form = document.getElementById("memorial-chat-form");
      const question = document.getElementById("memorial-chat-question");
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
      const voiceYoutubeQueryInput = document.getElementById("memorial-voice-youtube-query");
      const voiceYoutubeLimitInput = document.getElementById("memorial-voice-youtube-limit");
      const voiceYoutubeUrlsInput = document.getElementById("memorial-voice-youtube-urls");
      const listenButton = document.getElementById("memorial-speech-listen");
      const serverSttButton = document.getElementById("memorial-server-stt");
      const conversationButton = document.getElementById("memorial-conversation");
      const speakButton = document.getElementById("memorial-speech-speak");
      const stopButton = document.getElementById("memorial-speech-stop");
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
      let speechSynthesisDoneTimer = null;
      let memorialVoiceConfig = {{
        tts_mode: "browser_speech_synthesis",
        voice_label: "Austauschbare synthetische Stimme",
        lang: "de-AT",
        rate: 0.92,
        pitch: 0.92,
        volume: 1,
        voice_name_hints: ["de-AT", "de-DE", "German"],
        synthetic_voice_clone_of_memorial_person: false
      }};
      async function loadVoiceConfig() {{
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/voice-config");
          if (!response.ok) return;
          const payload = await response.json();
          memorialVoiceConfig = Object.assign(memorialVoiceConfig, payload || {{}});
          if (voiceLabelInput) voiceLabelInput.value = memorialVoiceConfig.voice_label || "";
          if (voiceLangInput) voiceLangInput.value = memorialVoiceConfig.lang || "de-AT";
          if (voiceRateInput) voiceRateInput.value = String(memorialVoiceConfig.rate || 0.92);
          if (voicePitchInput) voicePitchInput.value = String(memorialVoiceConfig.pitch || 0.92);
          if (voiceVolumeInput) voiceVolumeInput.value = String(memorialVoiceConfig.volume || 1);
          if (voiceHintsInput) voiceHintsInput.value = (Array.isArray(memorialVoiceConfig.voice_name_hints) ? memorialVoiceConfig.voice_name_hints : []).join(", ");
          speechNote.textContent = "Browser-STT/TTS, " + (memorialVoiceConfig.voice_label || "synthetische Stimme") + ".";
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
        const payload = {{
          voice_label: String(voiceLabelInput ? (voiceLabelInput.value || "") : memorialVoiceConfig.voice_label || ""),
          lang: String(voiceLangInput ? (voiceLangInput.value || "") : memorialVoiceConfig.lang || "de-AT").slice(0, 16),
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
          if (voiceProfileStatus) voiceProfileStatus.textContent = "Einstellungen gespeichert.";
          speechNote.textContent = "Browser-STT/TTS, " + (memorialVoiceConfig.voice_label || "synthetische Stimme") + ".";
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
      function normalizeTranscriptText(value) {{
        return String(value || "").replace(/\\s+/g, " ").trim();
      }}
      async function resolveSpeechVoices() {{
        const current = window.speechSynthesis.getVoices();
        if (Array.isArray(current) && current.length > 0) return current;
        return await new Promise((resolve) => {{
          const timeout = setTimeout(() => {{
            window.speechSynthesis.onvoiceschanged = null;
            resolve(window.speechSynthesis.getVoices() || []);
          }}, 1500);
          window.speechSynthesis.onvoiceschanged = () => {{
            clearTimeout(timeout);
            window.speechSynthesis.onvoiceschanged = null;
            resolve(window.speechSynthesis.getVoices() || []);
          }};
        }});
      }}
      function pickSpeechVoice(voices) {{
        const hints = Array.isArray(memorialVoiceConfig.voice_name_hints) ? memorialVoiceConfig.voice_name_hints : [];
        return (
          voices.find((voice) => hints.some((hint) => String(voice.name + " " + voice.lang).toLowerCase().includes(String(hint).toLowerCase()))) ||
          voices.find((voice) => /de[-_](AT|DE)/i.test(voice.lang || "")) ||
          voices.find((voice) => /^de/i.test(voice.lang || ""))
        );
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
        try {{
          const response = await fetch("/memorials/{html.escape(slug)}/chat", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ question: text }})
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
        if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {{
          speechNote.textContent = "Text-to-Speech wird von diesem Browser nicht unterstuetzt.";
          if (onDone) onDone();
          return;
        }}
        const text = normalizeTranscriptText(value || lastAnswerText || "");
        if (!text) return;
        window.speechSynthesis.cancel();
        if (speechSynthesisDoneTimer) {{
          clearTimeout(speechSynthesisDoneTimer);
          speechSynthesisDoneTimer = null;
        }}
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = memorialVoiceConfig.lang || "de-AT";
        utterance.rate = Number(memorialVoiceConfig.rate || 0.92);
        utterance.pitch = Number(memorialVoiceConfig.pitch || 0.92);
        utterance.volume = Number(memorialVoiceConfig.volume ?? 1);
        const voices = await resolveSpeechVoices();
        const preferred = pickSpeechVoice(voices);
        if (preferred) utterance.voice = preferred;
        const finishSpeech = () => {{
          if (speechSynthesisDoneTimer) {{
            clearTimeout(speechSynthesisDoneTimer);
            speechSynthesisDoneTimer = null;
          }}
          if (onDone) onDone();
        }};
        utterance.onend = () => {{
          finishSpeech();
        }};
        utterance.onerror = () => {{
          finishSpeech();
        }};
        utterance.oncancel = () => {{
          finishSpeech();
        }};
        window.speechSynthesis.speak(utterance);
        const estimatedMs = Math.min(20000, Math.max(900, Math.ceil(text.length * 45)));
        speechSynthesisDoneTimer = setTimeout(() => {{
          speechSynthesisDoneTimer = null;
          finishSpeech();
        }}, estimatedMs);
        speechNote.textContent = "Antwort wird mit " + (memorialVoiceConfig.voice_label || "synthetischer Stimme") + " vorgelesen.";
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
        window.speechSynthesis && window.speechSynthesis.cancel();
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
          if ("speechSynthesis" in window) window.speechSynthesis.cancel();
          recordConversationTurn();
        }} else {{
        if (activeRecorder && activeRecorder.state === "recording") {{
          try {{ activeRecorder.stop(); }} catch (error) {{}}
        }}
        releaseConversationAudio();
        if (speechSynthesisDoneTimer) {{
          clearTimeout(speechSynthesisDoneTimer);
          speechSynthesisDoneTimer = null;
        }}
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
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        if (speechSynthesisDoneTimer) {{
          clearTimeout(speechSynthesisDoneTimer);
          speechSynthesisDoneTimer = null;
        }}
        speechNote.textContent = "Gestoppt.";
        listenButton.disabled = false;
        serverSttButton.disabled = false;
        serverSttButton.textContent = "Server-STT starten";
        stopButton.disabled = false;
      }});
      if (voiceConfigForm && voiceProfileSaveButton) {{
        voiceProfileSaveButton.addEventListener("click", saveVoiceConfig);
      }}
      if (voiceBuildButton) {{
        voiceBuildButton.addEventListener("click", buildVoiceProfile);
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
    answer = _memorial_chat_answer(payload, _text(body.get("question")), _load_private_profile(slug))
    return JSONResponse(answer)


@router.post("/memorials/{slug}/speech-transcribe")
async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    _load_memorial(slug)
    payload = await request.body()
    content_type = str(request.headers.get("content-type") or "application/octet-stream")
    return JSONResponse(_memorial_transcribe_audio_blob(payload=payload, content_type=content_type))


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> HTMLResponse:
    return HTMLResponse(_memorial_html(_load_memorial(slug), hostname=request_hostname(request)))


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> HTMLResponse:
    return HTMLResponse(_memorial_html(_load_memorial(slug), hostname=request_hostname(request)))
