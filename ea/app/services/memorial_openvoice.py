from __future__ import annotations

import os
import json
import math
import re
import shutil
import subprocess
import tempfile
import hashlib
import time
from pathlib import Path

import requests
from fastapi import HTTPException


OPENVOICE_TTS_PLUGIN_ID = "openvoice_local"
OPENVOICE_TTS_PLUGIN_LABEL = "OpenVoice Local Clone"
PIPER_FAST_TTS_PLUGIN_ID = "piper_local_fast"
PIPER_FAST_TTS_PLUGIN_LABEL = "Piper Local Fast"
OPENVOICE_TTS_DISABLED_REASON = "openvoice_tts_pipeline_removed"
UNMIXR_TTS_PLUGIN_ID = "unmixr_clone"
UNMIXR_TTS_PLUGIN_LABEL = "Unmixr AI Clone"
VOICEWAVE_TTS_PLUGIN_ID = "voicewave_clone"
VOICEWAVE_TTS_PLUGIN_LABEL = "VoiceWave Clone"
_OPENVOICE_TIMEOUT_ENV = "OPENVOICE_TIMEOUT_SECONDS"
_OPENVOICE_DEFAULT_TIMEOUT_SECONDS = 180
_OPENVOICE_CLONE_CLIP_SECONDS = 180
_OPENVOICE_CLONE_SAMPLE_RATE = 16000
_OPENVOICE_MAX_CURATED_CLIPS = 3
_UNMIXR_CLONE_CLIP_SECONDS = 75
_UNMIXR_CLONE_SAMPLE_RATE = 16000
_UNMIXR_API_KEY_ENV = "UNMIXR_API_KEY"
_UNMIXR_API_KEY_FALLBACK_PREFIX = "UNMIXR_API_KEY_FALLBACK_"
_UNMIXR_API_KEYS_ENV = "UNMIXR_API_KEYS"
_UNMIXR_SLOT_SELECTOR_ENABLED_ENV = "EA_UNMIXR_SLOT_SELECTOR_ENABLED"
_UNMIXR_SLOT_SELECTOR_STATE_FILE_ENV = "EA_UNMIXR_SLOT_SELECTOR_STATE_FILE"
_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV = "EA_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS"
_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS_ENV = "EA_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS"
_UNMIXR_VOICE_ID_ENV = "UNMIXR_VOICE_ID"
_UNMIXR_LANGUAGE_ENV = "UNMIXR_LANGUAGE"
_UNMIXR_SPEAKING_RATE_ENV = "UNMIXR_SPEAKING_RATE"
_UNMIXR_SPEAKING_PITCH_ENV = "UNMIXR_SPEAKING_PITCH"
_UNMIXR_SPEAKING_VOLUME_ENV = "UNMIXR_SPEAKING_VOLUME"
_UNMIXR_BASE_URL = "https://unmixr.com/api/v1"
_VOICEWAVE_LOGIN_EMAIL_ENV = "VOICEWAVE_LOGIN_EMAIL"
_VOICEWAVE_LOGIN_PASSWORD_ENV = "VOICEWAVE_LOGIN_PASSWORD"
_VOICEWAVE_MEMORIAL_VOICE_LABEL_ENV = "VOICEWAVE_MEMORIAL_VOICE_LABEL"
_VOICEWAVE_SCRIPT_PATH_ENV = "VOICEWAVE_SCRIPT_PATH"
_VOICEWAVE_RUNTIME_TMP_ROOT_ENV = "VOICEWAVE_RUNTIME_TMP_ROOT"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOICEWAVE_SCRIPT_RELATIVE_PATH = Path("scripts") / "voicewave_memorial_voice.py"
_VOICEWAVE_SCRIPT_CANDIDATES = (
    _REPO_ROOT / _VOICEWAVE_SCRIPT_RELATIVE_PATH,
    Path("/app") / _VOICEWAVE_SCRIPT_RELATIVE_PATH,
)
_VOICEWAVE_RUNTIME_TMP_ROOT_CANDIDATES = (
    _REPO_ROOT / ".runtime" / "voicewave_runtime_tmp",
    Path("/tmp/voicewave_runtime_tmp"),
)
_VOICEWAVE_CACHE_ROOT_CANDIDATES = (
    Path("/data/artifacts/voicewave_tts_cache"),
    _REPO_ROOT / ".runtime" / "voicewave_tts_cache",
    Path("/tmp/voicewave_tts_cache"),
)
_VOICEWAVE_TIMEOUT_SECONDS = 420
_UNMIXR_RETRY_AFTER_RE = re.compile(
    r"(?:available|retry|try again)[^0-9]{0,40}(\d{1,6})\s*seconds?",
    re.IGNORECASE,
)


def openvoice_base_url() -> str:
    return ""


def openvoice_timeout_seconds() -> int:
    raw = str(os.environ.get(_OPENVOICE_TIMEOUT_ENV) or "").strip()
    try:
        value = int(raw) if raw else _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    return max(15, min(value, 900))


def openvoice_memorial_voice_id() -> str:
    return ""


def unmixr_api_key() -> str:
    return str(os.environ.get(_UNMIXR_API_KEY_ENV) or "").strip()


def _split_unmixr_api_keys(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[\s,;]+", str(value or "")) if item.strip())


def _unmixr_api_key_slots() -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_slot(name: str, value: object) -> None:
        key = str(value or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append((name, key))

    primary = unmixr_api_key()
    add_slot(_UNMIXR_API_KEY_ENV, primary)

    fallback_names = sorted(
        (
            name
            for name in os.environ
            if name.startswith(_UNMIXR_API_KEY_FALLBACK_PREFIX)
            and name[len(_UNMIXR_API_KEY_FALLBACK_PREFIX):].isdigit()
        ),
        key=lambda name: int(name[len(_UNMIXR_API_KEY_FALLBACK_PREFIX):]),
    )
    for env_name in fallback_names:
        add_slot(env_name, os.environ.get(env_name))

    for index, key in enumerate(_split_unmixr_api_keys(os.environ.get(_UNMIXR_API_KEYS_ENV)), start=1):
        add_slot(f"{_UNMIXR_API_KEYS_ENV}_{index}", key)
    return tuple(rows)


def unmixr_api_key_slot_count() -> int:
    return len(_unmixr_api_key_slots())


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 86_400) -> int:
    try:
        parsed = int(str(os.environ.get(name) or "").strip() or default)
    except ValueError:
        parsed = default
    return max(minimum, min(int(parsed), maximum))


def _unmixr_slot_selector_enabled() -> bool:
    return _env_bool(_UNMIXR_SLOT_SELECTOR_ENABLED_ENV, True)


def _unmixr_slot_state_file() -> Path:
    configured = str(os.environ.get(_UNMIXR_SLOT_SELECTOR_STATE_FILE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    ledger_dir = str(os.environ.get("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "").strip()
    if ledger_dir:
        return Path(ledger_dir).expanduser() / "unmixr_slot_selector.json"
    return Path(tempfile.gettempdir()) / "ea_unmixr_slot_selector.json"


def _load_unmixr_slot_state() -> dict[str, object]:
    if not _unmixr_slot_selector_enabled():
        return {}
    path = _unmixr_slot_state_file()
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_unmixr_slot_state(state: dict[str, object]) -> None:
    if not _unmixr_slot_selector_enabled():
        return
    path = _unmixr_slot_state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        return


def _unmixr_slot_cooldown_max_seconds() -> int:
    return _env_int(_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS_ENV, 3600, minimum=0, maximum=86_400)


def _unmixr_retry_after_seconds_from_response(response: requests.Response) -> int:
    retry_after = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
    if retry_after.isdigit():
        return int(retry_after)
    detail = _unmixr_response_error_detail(response)
    match = _UNMIXR_RETRY_AFTER_RE.search(detail)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def _unmixr_slot_cooldown_seconds(response: requests.Response | None = None, *, exception: BaseException | None = None) -> int:
    max_seconds = _unmixr_slot_cooldown_max_seconds()
    if max_seconds <= 0:
        return 0
    if response is not None:
        retry_after = _unmixr_retry_after_seconds_from_response(response)
        if retry_after > 0:
            return max(1, min(retry_after, max_seconds))
        status_code = int(getattr(response, "status_code", 0) or 0)
        detail = _unmixr_response_error_detail(response).lower()
        if status_code == 429 or "throttle" in detail or "rate" in detail:
            return min(_env_int(_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV, 900, minimum=1, maximum=max_seconds), max_seconds)
        if status_code in {401, 402, 403} or any(
            marker in detail
            for marker in ("insufficient", "balance", "quota", "credit", "billing", "payment")
        ):
            return min(_env_int(_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV, 900, minimum=1, maximum=max_seconds), max_seconds)
        if status_code in {500, 502, 503, 504}:
            return min(60, max_seconds)
    if exception is not None:
        return min(60, max_seconds)
    return 0


def _rotate_unmixr_slots(slots: list[tuple[str, str]], last_slot_name: str) -> list[tuple[str, str]]:
    if not slots or not last_slot_name:
        return slots
    names = [name for name, _key in slots]
    if last_slot_name not in names:
        return slots
    index = names.index(last_slot_name) + 1
    return slots[index:] + slots[:index]


def _selected_unmixr_slots(slots: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    if not _unmixr_slot_selector_enabled():
        return list(slots)
    state = _load_unmixr_slot_state()
    slot_state = dict(state.get("slots") or {})
    now = time.time()
    available: list[tuple[str, str]] = []
    cooling: list[tuple[float, tuple[str, str]]] = []
    for slot in slots:
        name = slot[0]
        item = dict(slot_state.get(name) or {})
        cooldown_until = float(item.get("cooldown_until_epoch") or 0)
        if cooldown_until > now:
            cooling.append((cooldown_until, slot))
        else:
            available.append(slot)
    if available:
        return _rotate_unmixr_slots(available, str(state.get("last_slot_name") or ""))
    if cooling:
        wait_seconds = max(1, int(min(item[0] for item in cooling) - now))
        raise HTTPException(status_code=429, detail=f"unmixr_slots_cooling_down:{wait_seconds}")
    return list(slots)


def _record_unmixr_slot_result(
    slot_name: str,
    *,
    ok: bool,
    response: requests.Response | None = None,
    exception: BaseException | None = None,
) -> None:
    if not _unmixr_slot_selector_enabled() or not slot_name:
        return
    state = _load_unmixr_slot_state()
    slots = dict(state.get("slots") or {})
    item = dict(slots.get(slot_name) or {})
    now = time.time()
    item["updated_at_epoch"] = now
    item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    if ok:
        item.pop("cooldown_until_epoch", None)
        item.pop("cooldown_until", None)
        item["last_status"] = "ok"
        state["last_slot_name"] = slot_name
    else:
        cooldown_seconds = _unmixr_slot_cooldown_seconds(response, exception=exception)
        if cooldown_seconds > 0:
            cooldown_until = now + cooldown_seconds
            item["cooldown_until_epoch"] = cooldown_until
            item["cooldown_until"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cooldown_until))
        item["last_status"] = "error"
        if response is not None:
            item["last_status_code"] = int(getattr(response, "status_code", 0) or 0)
            detail = _unmixr_response_error_detail(response)
            if detail:
                item["last_error"] = detail[:180]
        elif exception is not None:
            item["last_error"] = type(exception).__name__
    slots[slot_name] = item
    state["slots"] = slots
    state["updated_at"] = item["updated_at"]
    _write_unmixr_slot_state(state)


def unmixr_memorial_voice_id() -> str:
    return str(os.environ.get(_UNMIXR_VOICE_ID_ENV) or "").strip()


def unmixr_language(default: str = "de") -> str:
    preferred = str(default or "").strip()
    if preferred.lower().startswith("de"):
        return "de"
    configured = str(os.environ.get(_UNMIXR_LANGUAGE_ENV) or "").strip()
    return preferred or configured or "de"


def unmixr_speaking_rate() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_RATE_ENV) or "medium").strip() or "medium"


def unmixr_speaking_pitch() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_PITCH_ENV) or "low").strip() or "low"


def unmixr_speaking_volume() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_VOLUME_ENV) or "medium").strip() or "medium"


def voicewave_login_email() -> str:
    return str(os.environ.get(_VOICEWAVE_LOGIN_EMAIL_ENV) or "").strip()


def voicewave_login_password() -> str:
    return str(os.environ.get(_VOICEWAVE_LOGIN_PASSWORD_ENV) or "").strip()


def voicewave_memorial_voice_label() -> str:
    return str(os.environ.get(_VOICEWAVE_MEMORIAL_VOICE_LABEL_ENV) or "Manfred Hoza Memorial").strip() or "Manfred Hoza Memorial"


def voicewave_runtime_script_path() -> Path:
    configured = str(os.environ.get(_VOICEWAVE_SCRIPT_PATH_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    for candidate in _VOICEWAVE_SCRIPT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return _VOICEWAVE_SCRIPT_CANDIDATES[0]


def voicewave_runtime_tmp_root() -> Path:
    configured = str(os.environ.get(_VOICEWAVE_RUNTIME_TMP_ROOT_ENV) or "").strip()
    candidates = ((Path(configured).expanduser(),) if configured else ()) + _VOICEWAVE_RUNTIME_TMP_ROOT_CANDIDATES
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return _VOICEWAVE_RUNTIME_TMP_ROOT_CANDIDATES[-1]


def voicewave_cache_root() -> Path:
    for candidate in _VOICEWAVE_CACHE_ROOT_CANDIDATES:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return _VOICEWAVE_CACHE_ROOT_CANDIDATES[-1]


def _voicewave_cache_key(*, text: str, voice_label: str) -> str:
    normalized = f"{voice_label.strip().lower()}::{text.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _voicewave_cache_paths(*, text: str, voice_label: str) -> tuple[Path, Path]:
    key = _voicewave_cache_key(text=text, voice_label=voice_label)
    root = voicewave_cache_root()
    return root / f"{key}.wav", root / f"{key}.json"


def openvoice_plugin_option(*, configured_voice_id: str, voice_profile_ready: bool) -> dict[str, object]:
    return {
        "tts_plugin": OPENVOICE_TTS_PLUGIN_ID,
        "tts_plugin_label": OPENVOICE_TTS_PLUGIN_LABEL,
        "tts_plugin_description": "OpenVoice ist fuer Memorial-TTS deaktiviert; OpenVoice darf nur als STT/Analysepfad verwendet werden.",
        "tts_plugin_enabled": False,
        "tts_plugin_needs_clone": False,
        "tts_plugin_clone_capable": False,
        "tts_plugin_requires_voice_id": True,
        "tts_plugin_voice_id": configured_voice_id,
        "tts_plugin_voice_profile_ready": bool(voice_profile_ready),
        "tts_plugin_disabled_reason": OPENVOICE_TTS_DISABLED_REASON,
    }


def piper_fast_plugin_option() -> dict[str, object]:
    return {
        "tts_plugin": PIPER_FAST_TTS_PLUGIN_ID,
        "tts_plugin_label": PIPER_FAST_TTS_PLUGIN_LABEL,
        "tts_plugin_description": "Lokaler Piper/OpenVoice-TTS ist fuer Memorial-Stimmen deaktiviert.",
        "tts_plugin_enabled": False,
        "tts_plugin_needs_clone": False,
        "tts_plugin_clone_capable": False,
        "tts_plugin_requires_voice_id": False,
        "tts_plugin_voice_id": "",
        "tts_plugin_voice_profile_ready": True,
        "tts_plugin_disabled_reason": OPENVOICE_TTS_DISABLED_REASON,
    }


def unmixr_plugin_option(*, configured_voice_id: str, voice_profile_ready: bool) -> dict[str, object]:
    api_key = unmixr_api_key()
    plugin_enabled = bool(api_key)
    needs_clone = bool(plugin_enabled and voice_profile_ready and not configured_voice_id)
    if not api_key:
        description = "Bitte UNMIXR_API_KEY setzen."
    elif needs_clone:
        description = "Stimmprofil ist bereit. Bitte jetzt den Unmixr-Klon erzeugen."
    elif not configured_voice_id:
        description = "Unmixr ist verbunden. Es fehlt noch eine aktive Voice-ID."
    else:
        description = "Unmixr-Klon fuer hochwertige Sprachausgabe ist aktiviert."
    return {
        "tts_plugin": UNMIXR_TTS_PLUGIN_ID,
        "tts_plugin_label": UNMIXR_TTS_PLUGIN_LABEL,
        "tts_plugin_description": description,
        "tts_plugin_enabled": plugin_enabled,
        "tts_plugin_needs_clone": needs_clone,
        "tts_plugin_clone_capable": True,
        "tts_plugin_requires_voice_id": True,
        "tts_plugin_voice_id": configured_voice_id,
        "tts_plugin_voice_profile_ready": bool(voice_profile_ready),
    }


def voicewave_plugin_option(*, configured_voice_id: str, voice_profile_ready: bool) -> dict[str, object]:
    login_ready = bool(voicewave_login_email() and voicewave_login_password())
    voice_label = configured_voice_id or voicewave_memorial_voice_label()
    if not login_ready:
        description = "Bitte VOICEWAVE_LOGIN_EMAIL und VOICEWAVE_LOGIN_PASSWORD setzen."
    elif not voice_label:
        description = "VoiceWave ist verbunden. Es fehlt noch das aktive Clone-Label."
    else:
        description = "VoiceWave-Studio-Clone fuer memoriale Sprachausgabe ist verbunden."
    return {
        "tts_plugin": VOICEWAVE_TTS_PLUGIN_ID,
        "tts_plugin_label": VOICEWAVE_TTS_PLUGIN_LABEL,
        "tts_plugin_description": description,
        "tts_plugin_enabled": login_ready and bool(voice_label),
        "tts_plugin_needs_clone": False,
        "tts_plugin_clone_capable": True,
        "tts_plugin_requires_voice_id": True,
        "tts_plugin_voice_id": voice_label,
        "tts_plugin_voice_profile_ready": bool(voice_profile_ready),
    }


def _unmixr_headers(api_key: str | None = None) -> dict[str, str]:
    api_key = str(api_key or unmixr_api_key()).strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="unmixr_api_key_missing")
    return {"Authorization": f"Bearer {api_key}"}


def _unmixr_response_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        if response.ok and str(payload.get("audio_url") or "").strip():
            return ""
        detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or "").strip()
        if detail:
            return detail
    return str(getattr(response, "text", "") or "").strip()


def _unmixr_should_try_next_slot(response: requests.Response) -> bool:
    status_code = int(response.status_code or 0)
    if status_code in {401, 402, 403, 429, 500, 502, 503, 504}:
        return True
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.ok and isinstance(payload, dict) and str(payload.get("audio_url") or "").strip():
        return False
    detail = _unmixr_response_error_detail(response).lower()
    return any(
        marker in detail
        for marker in (
            "insufficient api balance",
            "insufficient balance",
            "prebuilt character",
            "quota",
            "credit",
            "billing",
            "payment",
        )
    )


def _unmixr_response_public_error(response: requests.Response) -> str:
    return _unmixr_response_error_detail(response) or "unmixr_tts_failed"


def _unmixr_request(
    *,
    method: str,
    path: str,
    json_payload: dict[str, object] | None = None,
    files: list[tuple[str, object]] | None = None,
    data: dict[str, str] | None = None,
) -> requests.Response:
    slots = _unmixr_api_key_slots()
    if not slots:
        raise HTTPException(status_code=503, detail="unmixr_api_key_missing")
    last_response: requests.Response | None = None
    last_exception: requests.RequestException | None = None
    selected_slots = _selected_unmixr_slots(slots)
    for index, (slot_name, api_key) in enumerate(selected_slots, start=1):
        try:
            response = requests.request(
                method=method,
                url=f"{_UNMIXR_BASE_URL}{path}",
                headers=_unmixr_headers(api_key),
                json=json_payload,
                files=files,
                data=data,
                timeout=openvoice_timeout_seconds(),
            )
        except requests.RequestException as exc:
            last_exception = exc
            _record_unmixr_slot_result(slot_name, ok=False, exception=exc)
            if index < len(selected_slots):
                continue
            break
        last_response = response
        if _unmixr_should_try_next_slot(response):
            _record_unmixr_slot_result(slot_name, ok=False, response=response)
            if index < len(selected_slots):
                continue
            return response
        if response.ok:
            _record_unmixr_slot_result(slot_name, ok=True, response=response)
            return response
        if index < len(selected_slots) and _unmixr_should_try_next_slot(response):
            continue
        return response
    if last_response is not None:
        return last_response
    detail = type(last_exception).__name__ if last_exception else "unknown"
    raise HTTPException(status_code=502, detail=f"unmixr_upstream_unreachable:{detail}")


def voicewave_synthesize_request(*, text: str, voice_label: str) -> tuple[bytes, str]:
    normalized_text = " ".join(str(text or "").split()).strip()
    if not normalized_text:
        raise HTTPException(status_code=400, detail="voicewave_tts_text_missing")
    normalized_label = str(voice_label or "").strip() or voicewave_memorial_voice_label()
    if not normalized_label:
        raise HTTPException(status_code=409, detail="voicewave_voice_label_missing")
    cache_audio_path, cache_meta_path = _voicewave_cache_paths(text=normalized_text, voice_label=normalized_label)
    if cache_audio_path.is_file() and cache_audio_path.stat().st_size > 0:
        return cache_audio_path.read_bytes(), "audio/wav"
    script_path = voicewave_runtime_script_path()
    if not script_path.is_file():
        raise HTTPException(status_code=503, detail="voicewave_runtime_script_missing")
    if not voicewave_login_email() or not voicewave_login_password():
        raise HTTPException(status_code=503, detail="voicewave_login_missing")
    with tempfile.TemporaryDirectory(
        prefix="ea-voicewave-render-",
        dir=str(voicewave_runtime_tmp_root()),
    ) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        output_path = temp_dir / "voicewave_render.generated.json"
        screenshot_path = temp_dir / "voicewave_render.png"
        audio_path = temp_dir / "voicewave_render.wav"
        command = [
            shutil.which("python3") or "python3",
            str(script_path),
            "render",
            "--voice-label",
            normalized_label,
            "--text",
            normalized_text,
            "--output",
            str(output_path),
            "--screenshot-output",
            str(screenshot_path),
            "--audio-output",
            str(audio_path),
        ]
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=_VOICEWAVE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="voicewave_tts_timeout") from exc
        if completed.returncode != 0:
            detail = str(completed.stdout or completed.stderr or "").strip()[:500]
            if output_path.is_file():
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                    detail = str((payload.get("errors") or [detail])[0] or detail)[:500]
                except Exception:
                    pass
            raise HTTPException(status_code=502, detail=f"voicewave_tts_failed:{detail or 'render_failed'}")
        if not audio_path.is_file() or audio_path.stat().st_size <= 0:
            raise HTTPException(status_code=502, detail="voicewave_tts_no_audio")
        audio_bytes = audio_path.read_bytes()
        try:
            cache_audio_path.write_bytes(audio_bytes)
            cache_meta_path.write_text(
                json.dumps(
                    {
                        "voice_label": normalized_label,
                        "text": normalized_text,
                        "content_type": "audio/wav",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return audio_bytes, "audio/wav"


def _prepare_clone_upload_path(path: Path) -> tuple[Path, bool]:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="voice_profile_sample_missing")
    if path.stat().st_size <= 18 * 1024 * 1024:
        return path, False
    suffix = path.suffix or ".wav"
    handle = tempfile.NamedTemporaryFile(prefix="ea-unmixr-clone-", suffix=suffix, delete=False)
    temp_path = Path(handle.name)
    handle.close()
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(_OPENVOICE_CLONE_SAMPLE_RATE),
        "-t",
        str(_OPENVOICE_CLONE_CLIP_SECONDS),
        str(temp_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"voice_profile_sample_prepare_failed:{type(exc).__name__}") from exc
    if proc.returncode != 0 or not temp_path.is_file():
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="voice_profile_sample_prepare_failed")
    return temp_path, True


def _prepare_unmixr_clone_upload_path(path: Path) -> Path:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="voice_profile_sample_missing")
    handle = tempfile.NamedTemporaryFile(prefix="ea-unmixr-clone-", suffix=".wav", delete=False)
    temp_path = Path(handle.name)
    handle.close()
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(_UNMIXR_CLONE_SAMPLE_RATE),
        "-t",
        str(_UNMIXR_CLONE_CLIP_SECONDS),
        str(temp_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"voice_profile_sample_prepare_failed:{type(exc).__name__}") from exc
    if proc.returncode != 0 or not temp_path.is_file():
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="voice_profile_sample_prepare_failed")
    return temp_path


def _ffprobe_duration_seconds(path: Path) -> float:
    cmd = [
        shutil.which("ffprobe") or "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    except Exception:
        return 0.0
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((proc.stdout or "").strip() or "0"))
    except ValueError:
        return 0.0


def _curate_clone_paths(sample_paths: list[Path]) -> list[Path]:
    if len(sample_paths) <= _OPENVOICE_MAX_CURATED_CLIPS:
        return sample_paths
    scored: list[tuple[float, Path]] = []
    for path in sample_paths:
        duration = _ffprobe_duration_seconds(path)
        size_bytes = path.stat().st_size if path.is_file() else 0
        basename = path.name.lower()
        score = 0.0
        if "hanusch" in basename or "enhanced" in basename:
            score += 2.5
        if basename.endswith(".wav"):
            score += 0.5
        target = min(duration, float(_OPENVOICE_CLONE_CLIP_SECONDS))
        if target > 0:
            score += min(target / 45.0, 3.0)
            score -= abs(target - 90.0) / 240.0
        if size_bytes > 0:
            score += min(math.log10(size_bytes), 8.0) / 8.0
        scored.append((score, path))
    scored.sort(key=lambda item: item[0], reverse=True)
    curated = [path for _, path in scored[:_OPENVOICE_MAX_CURATED_CLIPS]]
    return curated


def openvoice_clone_request(
    *,
    slug: str,
    voice_label: str,
    sample_paths: list[Path],
    voice_id: str | None = None,
) -> str:
    raise HTTPException(status_code=410, detail=OPENVOICE_TTS_DISABLED_REASON)


def unmixr_clone_request(*, slug: str, voice_label: str, sample_paths: list[Path]) -> str:
    if not sample_paths:
        raise HTTPException(status_code=400, detail="voice_profile_no_samples")
    sample_paths = _curate_clone_paths(sample_paths)
    source_path = sample_paths[0]
    upload_path = _prepare_unmixr_clone_upload_path(source_path)
    temp_paths: list[Path] = [upload_path]
    try:
        response = _unmixr_request(
            method="POST",
            path="/clone-voice/",
            data={
                "name": voice_label,
                "description": f"{slug} memorial clone",
            },
            files=[
                (
                    "audio",
                    (
                        f"memorial-{slug}{upload_path.suffix or '.wav'}",
                        upload_path.read_bytes(),
                        "application/octet-stream",
                    ),
                )
            ],
        )
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
    try:
        payload = response.json()
    except Exception:
        payload = {}
    status_text = str(payload.get("status") or "").strip().upper() if isinstance(payload, dict) else ""
    if response.status_code >= 400 or not response.ok or status_text == "FAILED":
        detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or "unmixr_clone_failed").strip()
        status_code = int(payload.get("code") or response.status_code or 502) if isinstance(payload, dict) else int(response.status_code or 502)
        raise HTTPException(status_code=502, detail=f"{detail}:{status_code}")
    voice_id = str(payload.get("voice_id") or payload.get("uuid") or "").strip()
    if not voice_id:
        raise HTTPException(status_code=502, detail="unmixr_clone_invalid_response")
    return voice_id


def unmixr_voice_metadata_request(*, voice_id: str) -> dict[str, object]:
    normalized_voice_id = str(voice_id or "").strip()
    if not normalized_voice_id:
        raise HTTPException(status_code=400, detail="unmixr_voice_id_missing")
    response = _unmixr_request(
        method="GET",
        path=f"/voice/{normalized_voice_id}/",
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or not response.ok:
        detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or "unmixr_voice_lookup_failed").strip()
        raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="unmixr_voice_lookup_invalid_response")
    return payload


def unmixr_voice_profile_id(*, voice_id: str) -> str:
    payload = unmixr_voice_metadata_request(voice_id=voice_id)
    sample_url = str(payload.get("sample_voice_url") or "").strip()
    if not sample_url:
        return ""
    match = re.search(r"/voiceprofile/([0-9a-f-]+)-", sample_url, flags=re.IGNORECASE)
    return str(match.group(1) if match else "").strip()


def unmixr_delete_clone_profile_request(*, profile_id: str) -> dict[str, object]:
    normalized_profile_id = str(profile_id or "").strip()
    if not normalized_profile_id:
        raise HTTPException(status_code=400, detail="unmixr_profile_id_missing")
    response = _unmixr_request(
        method="DELETE",
        path=f"/voice-cloning-profile/{normalized_profile_id}/",
    )
    if response.status_code in {200, 202, 204}:
        return {"status": "deleted", "profile_id": normalized_profile_id}
    try:
        payload = response.json()
    except Exception:
        payload = {}
    detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or "unmixr_clone_delete_failed").strip()
    raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")


def openvoice_synthesize_request(*, text: str, voice_id: str, lang: str) -> tuple[bytes, str]:
    raise HTTPException(status_code=410, detail=OPENVOICE_TTS_DISABLED_REASON)


def openvoice_synthesize_request_with_variant(*, text: str, voice_id: str, lang: str, base_voice_variant: str) -> tuple[bytes, str]:
    raise HTTPException(status_code=410, detail=OPENVOICE_TTS_DISABLED_REASON)


def piper_fast_synthesize_request(*, text: str, lang: str, base_voice_variant: str) -> tuple[bytes, str]:
    raise HTTPException(status_code=410, detail=OPENVOICE_TTS_DISABLED_REASON)


def unmixr_synthesize_request(
    *,
    text: str,
    voice_id: str,
    lang: str,
    speaking_rate: str | None = None,
    speaking_pitch: str | None = None,
    speaking_volume: str | None = None,
) -> tuple[bytes, str]:
    normalized_voice_id = str(voice_id or "").strip()
    if not normalized_voice_id:
        raise HTTPException(status_code=409, detail="tts_voice_id_missing")
    response = _unmixr_request(
        method="POST",
        path="/short-tts/",
        json_payload={
            "text": text,
            "voice_id": normalized_voice_id,
            "language": unmixr_language(lang),
            "response_type": "url",
            "speaking_rate": str(speaking_rate or unmixr_speaking_rate()).strip() or unmixr_speaking_rate(),
            "speaking_pitch": str(speaking_pitch or unmixr_speaking_pitch()).strip() or unmixr_speaking_pitch(),
            "speaking_volume": str(speaking_volume or unmixr_speaking_volume()).strip() or unmixr_speaking_volume(),
        },
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or not response.ok:
        detail = _unmixr_response_public_error(response)
        raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
    audio_url = str(payload.get("audio_url") or "").strip()
    if not audio_url:
        message = str(payload.get("message") or payload.get("detail") or payload.get("error") or "").strip()
        detail = "unmixr_tts_no_audio_url"
        if message:
            detail = f"{detail}:{message[:240]}"
        raise HTTPException(status_code=502, detail=detail)
    try:
        audio_response = requests.get(audio_url, timeout=openvoice_timeout_seconds())
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"unmixr_audio_fetch_failed:{type(exc).__name__}") from exc
    if audio_response.status_code >= 400 or not audio_response.ok or not audio_response.content:
        raise HTTPException(status_code=502, detail=f"unmixr_audio_fetch_failed:{audio_response.status_code}")
    content_type = str(audio_response.headers.get("Content-Type") or "audio/mpeg").split(";", 1)[0].strip().lower() or "audio/mpeg"
    return audio_response.content, content_type
