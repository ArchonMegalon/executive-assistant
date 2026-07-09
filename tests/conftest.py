from __future__ import annotations

import os
import subprocess
import sys
import threading
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
    ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
)


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


def _reset_shared_runtime_state() -> None:
    try:
        from app.services import cloudflare_access

        cloudflare_access._jwks_client.cache_clear()
    except Exception:
        pass
    try:
        from app.api.routes import public_memorials

        public_memorials._MEMORIAL_LIVE_WARMUP_STATE.clear()
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
    except Exception:
        pass
    for thread in list(threading.enumerate()):
        if thread is threading.current_thread():
            continue
        if thread.name.startswith("memorial-"):
            thread.join(timeout=0.2)
    try:
        from app.services import responses_upstream

        responses_upstream._test_reset_onemin_states()
        responses_upstream._test_reset_fleet_jury_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_environment_and_shared_runtime_state(tmp_path: Path) -> None:
    snapshot = dict(os.environ)
    _restore_missing_repo_assets()
    _reset_shared_runtime_state()
    os.environ["EA_OUTBOUND_EMAIL_GUARD_STATE_PATH"] = str(tmp_path / "outbound_email_guard.json")
    yield
    current_keys = set(os.environ.keys())
    original_keys = set(snapshot.keys())
    for key in current_keys - original_keys:
        os.environ.pop(key, None)
    for key in original_keys:
        os.environ[key] = snapshot[key]
    _restore_missing_repo_assets()
    _reset_shared_runtime_state()
