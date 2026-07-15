from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_EA_ROOT = _ROOT / "ea"
for _candidate in (str(_EA_ROOT), str(_ROOT)):
    while _candidate in sys.path:
        sys.path.remove(_candidate)
    sys.path.insert(0, _candidate)

os.environ.setdefault("EA_INLINE_SYNC_HANDLERS", "1")

_REPO_ASSET_RESTORE_PATHS = (
    ".codex-design/product/COMPANION_TRIGGER_REGISTRY.yaml",
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/PUBLIC_GUIDE_IMAGE_CURATION.yaml",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/TELEGRAM_FLAGSHIP_RUNTIME_DESIGN.md",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
    ".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json",
    ".codex-studio/published/ea_operator_action_required_digest.generated.json",
    ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
    ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
    ".codex-studio/published/release_authority_status.generated.json",
    ".codex-studio/published/runtime_dependency_audit.generated.json",
    ".codex-studio/published/runtime_dependency_sbom.cdx.json",
    ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
    ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
    ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
    "LTDs.md",
    "telegram_video_delivery_live.generated.json",
)
_MUTABLE_REPO_ARTIFACT_PATHS = (
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-studio/published/chummer6_media/ea_provider_health_registry.json",
    ".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json",
    ".codex-studio/published/ea_operator_action_required_digest.generated.json",
    ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
    ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
    ".codex-studio/published/release_authority_status.generated.json",
    ".codex-studio/published/runtime_dependency_audit.generated.json",
    ".codex-studio/published/runtime_dependency_sbom.cdx.json",
    ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
    ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json",
    ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json",
    ".codex-studio/published/avatar_presenter_provider/manfred_video_call_avatar_publish.generated.json",
    "LTDs.md",
    "telegram_video_delivery_live.generated.json",
)
_MUTABLE_REPO_ARTIFACT_BASELINE: dict[str, tuple[bytes, int] | None] | None = None


def _restore_missing_repo_assets() -> None:
    missing = [path for path in _REPO_ASSET_RESTORE_PATHS if not (_ROOT / path).exists()]
    if not missing:
        return
    try:
        subprocess.run(
            ["git", "-C", str(_ROOT), "restore", "--", *missing],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _capture_mutable_repo_artifact_baseline() -> dict[str, tuple[bytes, int] | None]:
    baseline: dict[str, tuple[bytes, int] | None] = {}
    for relpath in _MUTABLE_REPO_ARTIFACT_PATHS:
        path = _ROOT / relpath
        if not path.exists():
            baseline[relpath] = None
            continue
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"pytest mutable repository artifact is not a regular file: {relpath}")
        baseline[relpath] = (path.read_bytes(), path.stat().st_mode & 0o777)
    return baseline


def _restore_mutable_repo_artifacts(
    baseline: dict[str, tuple[bytes, int] | None],
) -> None:
    for relpath, snapshot in baseline.items():
        path = _ROOT / relpath
        if snapshot is None:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            continue
        content, mode = snapshot
        if (
            path.is_file()
            and not path.is_symlink()
            and path.read_bytes() == content
            and (path.stat().st_mode & 0o777) == mode
        ):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.pytest-", dir=path.parent)
        tmp_path = Path(raw_tmp)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, mode)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() and not (path.is_file() or path.is_symlink()):
                path.unlink()
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)


_THREAD_JOIN_BEFORE_START_ERROR = "cannot join thread before it is started"


def _join_memorial_thread(
    thread: threading.Thread,
    *,
    timeout_seconds: float = 0.2,
) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            thread.join(timeout=remaining)
            return
        except RuntimeError as exc:
            if exc.args != (_THREAD_JOIN_BEFORE_START_ERROR,):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            threading.Event().wait(min(0.001, remaining))


def _reset_shared_runtime_state() -> None:
    try:
        from app.services import cloudflare_access

        cloudflare_access._jwks_client.cache_clear()
    except Exception:
        pass
    try:
        from app.api.routes import public_memorials

        with public_memorials._MEMORIAL_LIVE_WARMUP_LOCK:
            public_memorials._MEMORIAL_LIVE_WARMUP_STATE.clear()
            public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS.clear()
        public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()
        public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
        with public_memorials._MEMORIAL_KNOWN_AUDIO_LOCK:
            public_memorials._MEMORIAL_KNOWN_AUDIO_TRANSCRIPTS.clear()
        public_memorials._memorial_known_prompt_transcript_cache.cache_clear()
        public_memorials._memorial_guest_cookie_secret.cache_clear()
        public_memorials._public_memorial_redis_client.cache_clear()
        public_memorials._memorial_property_search_rows.cache_clear()
        public_memorials._memorial_property_live_research.cache_clear()
        public_memorials._memorial_fetch_page_title.cache_clear()
        public_memorials._PUBLIC_MEMORIAL_RATE_BACKEND_CACHE = None
        with public_memorials._PUBLIC_MEMORIAL_RATE_MEMORY_LOCK:
            public_memorials._PUBLIC_MEMORIAL_RATE_MEMORY_EVENTS.clear()
    except Exception:
        pass
    for thread in list(threading.enumerate()):
        if thread is threading.current_thread():
            continue
        if thread.name.startswith("memorial-"):
            _join_memorial_thread(thread)
    try:
        from app.services import responses_upstream

        responses_upstream._test_reset_onemin_states()
        responses_upstream._test_reset_fleet_jury_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_environment_and_shared_runtime_state(tmp_path: Path) -> None:
    global _MUTABLE_REPO_ARTIFACT_BASELINE
    snapshot = dict(os.environ)
    _restore_missing_repo_assets()
    if _MUTABLE_REPO_ARTIFACT_BASELINE is None:
        _MUTABLE_REPO_ARTIFACT_BASELINE = _capture_mutable_repo_artifact_baseline()
    _restore_mutable_repo_artifacts(_MUTABLE_REPO_ARTIFACT_BASELINE)
    _reset_shared_runtime_state()
    os.environ["EA_OUTBOUND_EMAIL_GUARD_STATE_PATH"] = str(tmp_path / "outbound_email_guard.json")
    try:
        yield
    finally:
        current_keys = set(os.environ.keys())
        original_keys = set(snapshot.keys())
        for key in current_keys - original_keys:
            os.environ.pop(key, None)
        for key in original_keys:
            os.environ[key] = snapshot[key]
        _restore_mutable_repo_artifacts(_MUTABLE_REPO_ARTIFACT_BASELINE)
        _restore_missing_repo_assets()
        _reset_shared_runtime_state()
