from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "telegram_audiobook_live_readiness.generated.json"
DEFAULT_RUNTIME_CONTAINER = "ea-api"
CONTRACT_NAME = "ea.telegram_audiobook_live_readiness_checklist.v1"
RUNTIME_PREFLIGHT_CONTRACT_NAME = "ea.telegram_epub_audiobook_runtime_preflight.v1"


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


Runner = Callable[..., object]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _telegram_audiobook_enabled() -> bool:
    if str(os.environ.get("EA_TELEGRAM_AUDIOBOOK_ENABLED") or "").strip():
        return _env_bool("EA_TELEGRAM_AUDIOBOOK_ENABLED", True)
    return _env_bool("EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED", True)


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(float(raw or str(default)))
    except Exception:
        value = default
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _env_path(name: str, default: str) -> Path:
    raw = str(os.environ.get(name) or "").strip()
    return Path(raw or default).expanduser()


def _path_storage_kind(path: Path) -> str:
    text = path.as_posix()
    durable_root = _env_path(
        "EA_AUDIOBOOK_DURABLE_STORAGE_ROOT",
        str(Path(__file__).resolve().parents[2] / "data" / "audiobooks"),
    )
    try:
        path.expanduser().resolve().relative_to(durable_root.expanduser().resolve())
        return "durable"
    except Exception:
        pass
    legacy_pcloud_root = "/mnt/" + "pcloud"
    if text.startswith(legacy_pcloud_root) or "/pcloud/" in text:
        return "pcloud"
    if text.startswith("/tmp") or text.startswith("/var/tmp"):
        return "local_tmp"
    return "local"


def _writable_or_creatable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ea-audiobook-readiness-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _configured_voice_catalog_count() -> int:
    raw_json = str(os.environ.get("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except Exception:
            parsed = []
        if isinstance(parsed, dict):
            rows = parsed.get("voices") or parsed.get("presets") or parsed.get("items") or []
        else:
            rows = parsed
        if isinstance(rows, list):
            count = 0
            for row in rows:
                if isinstance(row, dict) and (row.get("voice_id") or row.get("uuid") or row.get("id")):
                    count += 1
            return count
    raw_path = str(os.environ.get("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH") or "").strip()
    if raw_path and Path(raw_path).expanduser().is_file():
        try:
            parsed = json.loads(Path(raw_path).expanduser().read_text(encoding="utf-8"))
        except Exception:
            parsed = []
        rows = parsed.get("voices") if isinstance(parsed, dict) else parsed
        if isinstance(rows, list):
            return sum(1 for row in rows if isinstance(row, dict) and (row.get("voice_id") or row.get("uuid") or row.get("id")))
    return 1 if str(os.environ.get("UNMIXR_VOICE_ID") or "").strip() else 0


def _unmixr_api_key_slot_count() -> int:
    seen: set[str] = set()

    def add(value: object) -> None:
        key = str(value or "").strip()
        if key:
            seen.add(key)

    add(os.environ.get("UNMIXR_API_KEY"))
    fallback_names = sorted(
        (
            name
            for name in os.environ
            if name.startswith("UNMIXR_API_KEY_FALLBACK_")
            and name[len("UNMIXR_API_KEY_FALLBACK_"):].isdigit()
        ),
        key=lambda name: int(name[len("UNMIXR_API_KEY_FALLBACK_"):]),
    )
    for name in fallback_names:
        add(os.environ.get(name))
    for key in re.split(r"[\s,;]+", str(os.environ.get("UNMIXR_API_KEYS") or "")):
        add(key)
    return len(seen)


def _build_env_preflight() -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[2]
    durable_root = _env_path("EA_AUDIOBOOK_DURABLE_STORAGE_ROOT", str(repo_root / "data" / "audiobooks"))
    jobs_root = _env_path("EA_AUDIOBOOK_JOBS_ROOT", str(durable_root / "jobs"))
    import_root = _env_path("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(durable_root / "audiobookshelf"))
    allow_non_durable = _env_bool("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", False)
    external_tts = _env_bool("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", False)
    unmixr_auto = external_tts and _env_bool("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", False)
    voice_count = _configured_voice_catalog_count()
    audition_min = _env_int("EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES", 3, minimum=1, maximum=30)
    public_share_enabled = _env_bool("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", False)
    api_base = bool(str(os.environ.get("EA_AUDIOBOOKSHELF_API_BASE_URL") or "").strip())
    public_base = bool(str(os.environ.get("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL") or "").strip())
    api_token = bool(str(os.environ.get("EA_AUDIOBOOKSHELF_API_TOKEN") or "").strip())
    library_id = bool(str(os.environ.get("EA_AUDIOBOOKSHELF_LIBRARY_ID") or "").strip())
    auto_import = _env_bool("EA_AUDIOBOOKSHELF_AUTO_IMPORT", True)
    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffprobe_available = shutil.which("ffprobe") is not None
    m4b_tool_available = shutil.which(str(os.environ.get("EA_M4B_TOOL_BIN") or "m4b-tool").strip() or "m4b-tool") is not None
    ffmpeg_fallback_enabled = _env_bool("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", True)
    m4b_available = m4b_tool_available or (ffmpeg_fallback_enabled and ffmpeg_available and ffprobe_available)

    checks: list[dict[str, object]] = []

    def add(key: str, passed: bool, *, severity: str = "fail") -> None:
        checks.append({"key": key, "status": "pass" if passed else severity})

    telegram_audiobook_enabled = _telegram_audiobook_enabled()
    add("telegram_audiobook_enabled", telegram_audiobook_enabled)
    add("telegram_epub_enabled", telegram_audiobook_enabled)
    add("unmixr_cinematic_narration_enabled", _env_bool("EA_AUDIOBOOK_CINEMATIC_NARRATION", True))
    add("jobs_root_durable", allow_non_durable or _path_storage_kind(jobs_root) in {"durable", "pcloud"})
    add("jobs_root_writable", _writable_or_creatable(jobs_root))
    add("external_tts_enabled", external_tts)
    add("unmixr_auto_render_enabled", unmixr_auto)
    add("voice_catalog_configured", voice_count > 0)
    add("voice_catalog_audition_ready", voice_count >= audition_min, severity="warn")
    add("m4b_assembly_available", m4b_available)
    add("audiobookshelf_import_root_durable", allow_non_durable or _path_storage_kind(import_root) in {"durable", "pcloud"})
    add("audiobookshelf_import_root_writable", _writable_or_creatable(import_root))
    add("audiobookshelf_public_share_configured", api_base and public_base and api_token and library_id, severity="warn")
    add("player_access_signing_secret_present", bool(str(os.environ.get("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET") or "").strip()))
    add(
        "player_access_base_url_present",
        bool(str(os.environ.get("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL") or "").strip()),
        severity="warn",
    )
    add("scheduler_resume_enabled", _env_bool("EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", True))

    failed = [str(row["key"]) for row in checks if row["status"] == "fail"]
    warned = [str(row["key"]) for row in checks if row["status"] == "warn"]
    return {
        "contract_name": RUNTIME_PREFLIGHT_CONTRACT_NAME,
        "status": "fail" if failed else "warn" if warned else "pass",
        "observed_at": _now_iso(),
        "checks": checks,
        "failed_checks": failed,
        "warned_checks": warned,
        "provider": {
            "api_key_slot_count": _unmixr_api_key_slot_count(),
            "voice_catalog_count": voice_count,
            "unmixr_cinematic_narration_enabled": _env_bool("EA_AUDIOBOOK_CINEMATIC_NARRATION", True),
            "voice_discovery_enabled": _env_bool("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", True),
            "voice_discovery_target_count": _env_int("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", 30, minimum=3, maximum=100),
            "voice_audition_min_candidates": audition_min,
            "raw_voice_ids_exposed": False,
            "provider_secrets_exposed": False,
        },
        "assembly": {
            "m4b_tool_available": m4b_tool_available,
            "ffmpeg_available": ffmpeg_available,
            "ffprobe_available": ffprobe_available,
            "ffmpeg_m4b_fallback_enabled": ffmpeg_fallback_enabled,
            "m4b_assembly_available": m4b_available,
        },
        "access": {
            "audiobookshelf_auto_import_enabled": auto_import,
            "audiobookshelf_public_share_enabled": public_share_enabled,
            "audiobookshelf_public_share_configured": api_base and public_base and api_token and library_id,
            "audiobookshelf_api_base_url_present": api_base,
            "audiobookshelf_public_base_url_present": public_base,
            "audiobookshelf_api_token_present": api_token,
            "audiobookshelf_library_id_present": library_id,
            "player_access_signing_secret_present": bool(str(os.environ.get("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET") or "").strip()),
            "player_access_base_url_present": bool(str(os.environ.get("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL") or "").strip()),
            "tokens_exposed": False,
        },
        "storage": {"raw_paths_exposed": False},
        "scheduler": {"resume_enabled": _env_bool("EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", True)},
    }


def _run_command(command: Sequence[str], runner: Runner | None = None) -> tuple[int, str, str]:
    if runner is None:
        proc = subprocess.run(list(command), text=True, capture_output=True, check=False)
    else:
        proc = runner(list(command), text=True, capture_output=True, check=False)
    return (
        int(getattr(proc, "returncode", 1)),
        str(getattr(proc, "stdout", "") or ""),
        str(getattr(proc, "stderr", "") or ""),
    )


def _load_runtime_preflight_from_container(*, runtime_container: str, runner: Runner | None = None) -> dict[str, object]:
    code, stdout, stderr = _run_command(
        [
            "docker",
            "exec",
            runtime_container,
            "python",
            "-c",
            (
                "import json\n"
                "from app.services import audiobook_epub_pipeline as p\n"
                "print(json.dumps(p.audiobook_runtime_preflight(), sort_keys=True))\n"
            ),
        ],
        runner=runner,
    )
    if code != 0:
        return {
            "contract_name": RUNTIME_PREFLIGHT_CONTRACT_NAME,
            "status": "fail",
            "failed_checks": ["runtime_container_preflight_failed"],
            "warned_checks": [],
            "checks": [{"key": "runtime_container_preflight_failed", "status": "fail"}],
            "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0, "voice_audition_min_candidates": 3},
            "access": {},
            "assembly": {},
            "scheduler": {},
            "runtime_container": runtime_container,
            "runtime_error_sha256": hashlib.sha256((stderr or stdout).encode("utf-8", errors="replace")).hexdigest(),
        }
    try:
        parsed = json.loads(stdout)
    except Exception as exc:
        return {
            "contract_name": RUNTIME_PREFLIGHT_CONTRACT_NAME,
            "status": "fail",
            "failed_checks": ["runtime_container_preflight_json_invalid"],
            "warned_checks": [],
            "checks": [{"key": "runtime_container_preflight_json_invalid", "status": "fail"}],
            "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0, "voice_audition_min_candidates": 3},
            "access": {},
            "assembly": {},
            "scheduler": {},
            "runtime_container": runtime_container,
            "runtime_error_sha256": hashlib.sha256(str(exc).encode("utf-8")).hexdigest(),
        }
    if not isinstance(parsed, dict):
        return {
            "contract_name": RUNTIME_PREFLIGHT_CONTRACT_NAME,
            "status": "fail",
            "failed_checks": ["runtime_container_preflight_not_object"],
            "warned_checks": [],
            "checks": [{"key": "runtime_container_preflight_not_object", "status": "fail"}],
            "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0, "voice_audition_min_candidates": 3},
            "access": {},
            "assembly": {},
            "scheduler": {},
            "runtime_container": runtime_container,
        }
    return parsed


def _check_lookup(preflight: dict[str, object]) -> dict[str, str]:
    rows = {}
    for row in list(preflight.get("checks") or []):
        if isinstance(row, dict):
            rows[str(row.get("key") or "")] = str(row.get("status") or "")
    return rows


def _status_from_check(checks: dict[str, str], key: str, fallback: bool = False, *, warn_is_ready: bool = False) -> str:
    status = checks.get(key)
    if status == "pass":
        return "ready"
    if status == "warn":
        return "ready" if warn_is_ready else "blocked"
    if status == "fail":
        return "blocked"
    return "ready" if fallback else "blocked"


def _status_from_any_check(checks: dict[str, str], keys: Sequence[str], fallback: bool = False) -> str:
    for key in keys:
        if key in checks:
            return _status_from_check(checks, key, fallback)
    return "ready" if fallback else "blocked"


def _item(
    *,
    key: str,
    status: str,
    env_var_names: list[str],
    operator_action: str,
) -> dict[str, object]:
    return {
        "key": key,
        "status": status,
        "env_var_names": env_var_names,
        "env_values_exposed": False,
        "operator_action": operator_action,
        "verification_command": "make verify-telegram-audiobook-live-readiness",
    }


def materialize_telegram_audiobook_live_readiness(
    *,
    receipt_path: Path = DEFAULT_RECEIPT,
    generated_at: str | None = None,
    preflight: dict[str, object] | None = None,
    runtime_container: str | None = None,
    runner: Runner | None = None,
) -> dict[str, object]:
    observation_source = "provided_preflight" if preflight is not None else "host_env"
    if preflight is None and runtime_container:
        preflight = _load_runtime_preflight_from_container(runtime_container=runtime_container, runner=runner)
        observation_source = "runtime_container"
    preflight = preflight or _build_env_preflight()
    checks = _check_lookup(preflight)
    provider = dict(preflight.get("provider") or {})
    access = dict(preflight.get("access") or {})
    assembly = dict(preflight.get("assembly") or {})
    scheduler = dict(preflight.get("scheduler") or {})

    api_key_slot_count = int(provider.get("api_key_slot_count") or 0)
    voice_catalog_count = int(provider.get("voice_catalog_count") or 0)
    audition_min = int(provider.get("voice_audition_min_candidates") or 3)
    m4b_available = bool(assembly.get("m4b_assembly_available"))
    auto_import = bool(access.get("audiobookshelf_auto_import_enabled"))
    public_share_enabled = bool(access.get("audiobookshelf_public_share_enabled"))
    public_share_configured = bool(access.get("audiobookshelf_public_share_configured"))
    scheduler_enabled = bool(scheduler.get("resume_enabled", True))

    voice_items = [
        _item(
            key="telegram_audiobook_enabled",
            status=_status_from_any_check(checks, ["telegram_audiobook_enabled", "telegram_epub_enabled"], True),
            env_var_names=["EA_TELEGRAM_AUDIOBOOK_ENABLED", "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED"],
            operator_action="Enable Telegram audiobook intake.",
        ),
        _item(
            key="jobs_root_durable",
            status=_status_from_check(checks, "jobs_root_durable"),
            env_var_names=["EA_AUDIOBOOK_DURABLE_STORAGE_ROOT", "EA_AUDIOBOOK_JOBS_ROOT", "EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE"],
            operator_action="Point the audiobook job root at configured durable audiobook storage.",
        ),
        _item(
            key="jobs_root_writable",
            status=_status_from_check(checks, "jobs_root_writable"),
            env_var_names=["EA_AUDIOBOOK_JOBS_ROOT"],
            operator_action="Create the audiobook job root and make it writable by the EA runtime user.",
        ),
        _item(
            key="external_tts_enabled",
            status=_status_from_check(checks, "external_tts_enabled"),
            env_var_names=["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"],
            operator_action="Approve raw owned audiobook source text leaving EA for governed external audiobook TTS.",
        ),
        _item(
            key="unmixr_cinematic_narration_enabled",
            status=_status_from_check(checks, "unmixr_cinematic_narration_enabled", True),
            env_var_names=["EA_AUDIOBOOK_CINEMATIC_NARRATION"],
            operator_action="Keep cinematic narration enabled for premium audiobook output.",
        ),
        _item(
            key="unmixr_auto_render_enabled",
            status=_status_from_check(checks, "unmixr_auto_render_enabled"),
            env_var_names=["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"],
            operator_action="Enable automatic Unmixr rendering after the user chooses a voice.",
        ),
        _item(
            key="voice_catalog_configured",
            status="ready" if voice_catalog_count > 0 else "blocked",
            env_var_names=[
                "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
                "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH",
                "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED",
                "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES",
                "UNMIXR_VOICE_ID",
                "UNMIXR_API_KEY",
            ],
            operator_action="Configure or discover the Unmixr audiobook voice catalog.",
        ),
        _item(
            key="voice_catalog_audition_ready",
            status="ready" if voice_catalog_count >= audition_min else "blocked",
            env_var_names=[
                "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
                "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH",
                "EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED",
                "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_TARGET_COUNT",
                "EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES",
            ],
            operator_action="Provide or discover at least three audiobook voices so Telegram can send comparison samples.",
        ),
        _item(
            key="unmixr_api_key_slot_present",
            status="ready" if api_key_slot_count > 0 else "blocked",
            env_var_names=["UNMIXR_API_KEY", "UNMIXR_API_KEY_FALLBACK_1", "UNMIXR_API_KEYS"],
            operator_action="Configure at least one owned Unmixr API-key slot for sample and chapter rendering.",
        ),
    ]
    delivery_items = [
        _item(
            key="m4b_assembly_available",
            status="ready" if m4b_available else "blocked",
            env_var_names=["EA_M4B_TOOL_BIN", "EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK"],
            operator_action="Install m4b-tool or keep the ffmpeg M4B fallback enabled and available.",
        ),
        _item(
            key="audiobookshelf_auto_import_enabled",
            status="ready" if auto_import else "blocked",
            env_var_names=["EA_AUDIOBOOKSHELF_AUTO_IMPORT"],
            operator_action="Enable automatic import into the Audiobookshelf library folder.",
        ),
        _item(
            key="audiobookshelf_import_root_durable",
            status=_status_from_check(checks, "audiobookshelf_import_root_durable", True),
            env_var_names=["EA_AUDIOBOOK_DURABLE_STORAGE_ROOT", "EA_AUDIOBOOKSHELF_IMPORT_ROOT", "EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE"],
            operator_action="Point the Audiobookshelf import root at configured durable audiobook storage.",
        ),
        _item(
            key="audiobookshelf_import_root_writable",
            status=_status_from_check(checks, "audiobookshelf_import_root_writable", True),
            env_var_names=["EA_AUDIOBOOKSHELF_IMPORT_ROOT"],
            operator_action="Create the Audiobookshelf import root and make it writable by EA.",
        ),
        _item(
            key="audiobookshelf_public_share_enabled",
            status="ready" if public_share_enabled else "blocked",
            env_var_names=["EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED"],
            operator_action="Enable Audiobookshelf public-share creation after scan/import.",
        ),
        _item(
            key="audiobookshelf_public_share_configured",
            status="ready" if public_share_configured else "blocked",
            env_var_names=[
                "EA_AUDIOBOOKSHELF_API_BASE_URL",
                "EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL",
                "EA_AUDIOBOOKSHELF_API_TOKEN",
                "EA_AUDIOBOOKSHELF_LIBRARY_ID",
            ],
            operator_action="Configure the Audiobookshelf API/public base URL, library id, and admin token.",
        ),
        _item(
            key="player_access_signing_secret_present",
            status="ready" if bool(access.get("player_access_signing_secret_present")) else "blocked",
            env_var_names=["EA_AUDIOBOOK_ACCESS_SIGNING_SECRET"],
            operator_action="Configure the EA signing secret for player-scoped audiobook links.",
        ),
        _item(
            key="player_access_base_url_present",
            status=_status_from_check(checks, "player_access_base_url_present", warn_is_ready=True),
            env_var_names=["EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL"],
            operator_action="Configure the public EA base URL for player-scoped audiobook links.",
        ),
        _item(
            key="scheduler_resume_enabled",
            status="ready" if scheduler_enabled else "blocked",
            env_var_names=["EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", "EA_SCHEDULER_AUDIOBOOK_RESUME_INTERVAL_SECONDS"],
            operator_action="Enable the audiobook scheduler so provider waits and Audiobookshelf scans resume automatically.",
        ),
    ]
    sample_blockers = [str(row["key"]) for row in voice_items if row["status"] != "ready"]
    delivery_blockers = [str(row["key"]) for row in delivery_items if row["status"] != "ready"]
    voice_ready = not sample_blockers
    delivery_ready = not delivery_blockers
    status = "ready_for_live_epub_delivery_test" if voice_ready and delivery_ready else "blocked_live_prerequisites"
    next_action = "run_real_telegram_epub_audiobook_delivery_test" if status.startswith("ready") else _next_action(sample_blockers, delivery_blockers)

    receipt = {
        "contract_name": CONTRACT_NAME,
        **_source_state_fields(),
        "generated_at": generated_at or _now_iso(),
        "observation_source": observation_source,
        "runtime_container": runtime_container or "",
        "status": status,
        "preflight_status": str(preflight.get("status") or ""),
        "preflight_failed_checks": list(preflight.get("failed_checks") or []),
        "preflight_warned_checks": list(preflight.get("warned_checks") or []),
        "voice_sample_prereqs_ready": voice_ready,
        "public_share_delivery_prereqs_ready": delivery_ready,
        "can_run_live_epub_delivery_test": voice_ready and delivery_ready,
        "live_delivery_claim_allowed": False,
        "real_user_playback_acceptance_verified": False,
        "goal_completion_claim_allowed": False,
        "sample_blockers": sample_blockers,
        "delivery_blockers": delivery_blockers,
        "next_action": next_action,
        "voice_samples": {
            "status": "ready" if voice_ready else "blocked",
            "api_key_slot_count": api_key_slot_count,
            "voice_catalog_count": voice_catalog_count,
            "voice_audition_min_candidates": audition_min,
            "voice_discovery_enabled": bool(provider.get("voice_discovery_enabled", True)),
            "voice_discovery_target_count": int(provider.get("voice_discovery_target_count") or 30),
            "items": voice_items,
        },
        "delivery": {
            "status": "ready" if delivery_ready else "blocked",
            "m4b_assembly_available": m4b_available,
            "audiobookshelf_auto_import_enabled": auto_import,
            "audiobookshelf_public_share_enabled": public_share_enabled,
            "audiobookshelf_public_share_configured": public_share_configured,
            "scheduler_resume_enabled": scheduler_enabled,
            "items": delivery_items,
        },
        "required_live_proof_after_readiness": [
            "real Telegram audiobook source upload",
            "three Telegram voice samples delivered with Use this/Dismiss controls",
            "operator-selected voice callback applied",
            "M4B rendered and imported into Audiobookshelf",
            "Audiobookshelf scan completed",
            "public share link sent back to Telegram",
            "sanitized live delivery receipt materialized",
            "separate human playback acceptance captured",
        ],
        "operator_commands": [
            "make verify-telegram-audiobook-live-readiness",
            "make verify-telegram-audiobook-live-delivery-receipt",
            "make verify-active-media-ltd-goal-bundle",
        ],
        "privacy": {
            "env_values_exposed": False,
            "raw_provider_voice_ids_exposed": False,
            "raw_public_share_url_included": False,
            "raw_storage_paths_included": False,
            "raw_telegram_chat_id_included": False,
            "preflight_contract_sha256": _sha256_json(preflight),
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _next_action(sample_blockers: list[str], delivery_blockers: list[str]) -> str:
    if "external_tts_enabled" in sample_blockers:
        return "Approve raw owned audiobook source text leaving EA for governed external audiobook TTS."
    if "unmixr_api_key_slot_present" in sample_blockers:
        return "Configure at least one owned Unmixr API-key slot."
    if "voice_catalog_configured" in sample_blockers or "voice_catalog_audition_ready" in sample_blockers:
        return "Configure or discover at least three audiobook voices."
    if "audiobookshelf_public_share_enabled" in delivery_blockers or "audiobookshelf_public_share_configured" in delivery_blockers:
        return "Configure Audiobookshelf public-share creation and rerun readiness."
    if delivery_blockers:
        return "Fix Audiobookshelf import/player-link prerequisites and rerun readiness."
    return "run_real_telegram_epub_audiobook_delivery_test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", "--out", dest="receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument(
        "--runtime-container",
        default=DEFAULT_RUNTIME_CONTAINER,
        help=(
            "Runtime container used for authoritative preflight evidence "
            f"(default: {DEFAULT_RUNTIME_CONTAINER}). Pass an empty value only for an explicit host-env diagnostic."
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    receipt = materialize_telegram_audiobook_live_readiness(
        receipt_path=args.receipt,
        generated_at=args.generated_at or None,
        runtime_container=args.runtime_container or None,
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
