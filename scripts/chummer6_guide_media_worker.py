#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import mean

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageDraw = None
    ImageFont = None

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chummer6_guide_canon import load_horizon_canon, load_media_briefs, load_page_registry, load_part_canon
from chummer6_magixai_api import (
    MAGIXAI_IMAGE_ENDPOINT,
    magixai_api_base_urls,
    magixai_build_url,
    magixai_image_model_candidates,
    magixai_looks_like_html,
    magixai_size_variants,
)
from chummer6_runtime_config import load_local_env, load_runtime_overrides


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_media_last.json")
MANIFEST_OUT = Path("/docker/fleet/state/chummer6/ea_media_manifest.json")
SCENE_LEDGER_OUT = Path("/docker/fleet/state/chummer6/ea_scene_ledger.json")
GUIDE_VISUAL_OVERRIDES = EA_ROOT / "chummer6_guide" / "VISUAL_OVERRIDES.json"
MEDIA_FACTORY_ROOT = Path("/docker/fleet/repos/chummer-media-factory")
MEDIA_FACTORY_RENDER_SCRIPT = MEDIA_FACTORY_ROOT / "scripts" / "render_guide_asset.py"
RELEASE_CONTROL_SCRIPT = Path("/docker/fleet/scripts/materialize_chummer_release_registry_projection.py")
RELEASE_BUILDER_SCRIPT = EA_ROOT / "scripts" / "chummer6_release_builder.py"
RELEASE_MATRIX_OUT = Path("/docker/fleet/state/chummer6/chummer6_release_matrix.json")
TROLL_MARK_PATH = Path("/docker/chummercomplete/Chummer6/assets/meta/chummer-troll.png")
DEFAULT_PROVIDER_ORDER = [
    "media_factory",
    "browseract_prompting_systems",
    "browseract_magixai",
    "magixai",
    "onemin",
]
PALETTES = [
    ("#0f766e", "#34d399"),
    ("#1d4ed8", "#7dd3fc"),
    ("#7c3aed", "#c084fc"),
    ("#7c2d12", "#fb923c"),
    ("#be123c", "#fb7185"),
    ("#4338ca", "#818cf8"),
]
TABLEAU_COMPOSITIONS = {"safehouse_table", "group_table"}
STATIC_DESK_COMPOSITIONS = {"desk_still_life", "dossier_desk"}
SURFACE_HEAVY_COMPOSITIONS = TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS | {"loadout_table"}
SPARSE_EASTER_EGG_TARGETS = frozenset(
    {
        "assets/pages/start-here.png",
    }
)
FIRST_CONTACT_TARGETS = frozenset(
    {
        "assets/hero/chummer6-hero.png",
        "assets/pages/horizons-index.png",
        "assets/horizons/karma-forge.png",
    }
)
CRITICAL_VISUAL_TARGETS = FIRST_CONTACT_TARGETS
SPARSE_HUMOR_TARGETS = frozenset(
    {
        "assets/hero/poc-warning.png",
    }
)
CANON_LOCKED_TARGETS = frozenset(
    {
        "assets/hero/chummer6-hero.png",
        "assets/pages/public-surfaces.png",
        "assets/pages/parts-index.png",
        "assets/pages/horizons-index.png",
        "assets/horizons/karma-forge.png",
    }
)
EASTER_EGG_FIELDS = (
    "easter_egg_kind",
    "easter_egg_placement",
    "easter_egg_detail",
    "easter_egg_visibility",
    "troll_postpass",
)
EASTER_EGG_OBJECT_HINTS = (
    "sticker",
    "tattoo",
    "patch",
    "decal",
    "doodle",
    "mascot",
    "motif",
    "mark",
    "charm",
    "stamp",
    "seal",
    "pin",
    "pictogram",
    "figurine",
    "patch",
)
META_HUMOR_TOKENS = (
    " dev ",
    " developer",
    " maintainer",
    " sysadmin",
    " admin ",
    " cleanup pass",
    " growth funnel",
    " repo ",
    " repo-",
    " vibe-based",
    " clean code",
    " not my bug",
    " one-liner",
    " roast",
    " roasting",
)
READABLE_JOKE_TOKENS = (
    "reads:",
    "says:",
    "sign reads",
    "sticker reads",
    "placard reads",
    "quote:",
)


LOCAL_ENV = load_local_env()
POLICY_ENV = load_runtime_overrides()
FFMPEG_BIN = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
_ONEMIN_MANAGER_SELECTION_CACHE: dict[str, object] = {
    "expires_at": 0.0,
    "available": False,
    "occupied_account_ids": set(),
    "occupied_secret_env_names": set(),
}
_MEDIA_BRIEFS_CACHE: dict[str, object] | None = None
_PAGE_REGISTRY_CACHE: dict[str, object] | None = None


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or POLICY_ENV.get(name) or "").strip()


def _ea_local_base_url() -> str:
    return (
        env_value("CHUMMER6_EA_BASE_URL")
        or env_value("EA_BASE_URL")
        or "http://127.0.0.1:8090"
    ).rstrip("/")


def _ea_local_timeout_seconds() -> float:
    raw = env_value("CHUMMER6_EA_TIMEOUT_SECONDS") or "3"
    try:
        return max(0.25, min(10.0, float(raw)))
    except Exception:
        return 3.0


def _ea_local_cache_ttl_seconds() -> float:
    raw = env_value("CHUMMER6_ONEMIN_MANAGER_CACHE_TTL_SECONDS") or "15"
    try:
        return max(1.0, min(300.0, float(raw)))
    except Exception:
        return 15.0


def _onemin_allow_reserve() -> bool:
    return _boolish(env_value("CHUMMER6_ONEMIN_ALLOW_RESERVE"), default=True)


def _onemin_principal_id() -> str:
    return env_value("CHUMMER6_EA_PRINCIPAL_ID") or env_value("EA_PRINCIPAL_ID") or "ea-chummer6"


def _ea_local_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "EA-Chummer6-1min/1.0",
    }
    token = env_value("EA_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    principal_id = env_value("CHUMMER6_EA_PRINCIPAL_ID") or env_value("EA_PRINCIPAL_ID")
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    return headers


def _ea_local_json_get(path: str) -> object | None:
    return _ea_local_json_request("GET", path)


def _ea_local_json_post(path: str, payload: dict[str, object]) -> object | None:
    return _ea_local_json_request("POST", path, payload)


def _ea_local_json_request(method: str, path: str, payload: dict[str, object] | None = None) -> object | None:
    data = None
    headers = _ea_local_headers()
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{_ea_local_base_url()}{path}",
        headers=headers,
        data=data,
        method=str(method or "GET").upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=_ea_local_timeout_seconds()) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def _normalize_onemin_accounts_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        rows = payload.get("accounts")
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


def _normalize_onemin_leases_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        rows = payload.get("leases")
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


def _refresh_onemin_manager_selection_snapshot() -> tuple[bool, set[str], set[str]]:
    cached_expires_at = float(_ONEMIN_MANAGER_SELECTION_CACHE.get("expires_at") or 0.0)
    now = time.time()
    if cached_expires_at > now:
        return (
            bool(_ONEMIN_MANAGER_SELECTION_CACHE.get("available")),
            set(_ONEMIN_MANAGER_SELECTION_CACHE.get("occupied_account_ids") or set()),
            set(_ONEMIN_MANAGER_SELECTION_CACHE.get("occupied_secret_env_names") or set()),
        )

    occupancy_payload = _ea_local_json_get("/v1/providers/onemin/occupancy")
    if not isinstance(occupancy_payload, dict):
        _ONEMIN_MANAGER_SELECTION_CACHE["available"] = False
        _ONEMIN_MANAGER_SELECTION_CACHE["occupied_account_ids"] = set()
        _ONEMIN_MANAGER_SELECTION_CACHE["occupied_secret_env_names"] = set()
        _ONEMIN_MANAGER_SELECTION_CACHE["expires_at"] = now + _ea_local_cache_ttl_seconds()
        return False, set(), set()

    occupied_account_ids = {
        str(value or "").strip()
        for value in (occupancy_payload.get("occupied_account_ids") or [])
        if str(value or "").strip()
    }
    occupied_secret_env_names = {
        str(value or "").strip()
        for value in (occupancy_payload.get("occupied_secret_env_names") or [])
        if str(value or "").strip()
    }

    _ONEMIN_MANAGER_SELECTION_CACHE["available"] = True
    _ONEMIN_MANAGER_SELECTION_CACHE["occupied_account_ids"] = set(occupied_account_ids)
    _ONEMIN_MANAGER_SELECTION_CACHE["occupied_secret_env_names"] = set(occupied_secret_env_names)
    _ONEMIN_MANAGER_SELECTION_CACHE["expires_at"] = now + _ea_local_cache_ttl_seconds()
    return True, occupied_account_ids, occupied_secret_env_names


def _estimate_onemin_image_credits(*, width: int, height: int) -> int:
    raw = env_value("CHUMMER6_ONEMIN_ESTIMATED_IMAGE_CREDITS")
    if raw:
        try:
            return max(0, int(float(raw)))
        except Exception:
            pass
    primary_model = str(env_value("CHUMMER6_ONEMIN_MODEL") or "").strip().lower()
    if primary_model == "black-forest-labs/flux-schnell":
        return 9000
    megapixels = max(1.0, (max(1, int(width)) * max(1, int(height))) / 1000000.0)
    return int(round(1200.0 * megapixels))


def _reserve_onemin_image_slot(*, width: int, height: int, allow_reserve: bool | None = None) -> dict[str, object] | None:
    payload = _ea_local_json_post(
        "/v1/providers/onemin/reserve-image",
        {
            "request_id": f"chummer-image-{int(time.time() * 1000)}-{width}x{height}",
            "estimated_credits": _estimate_onemin_image_credits(width=width, height=height),
            "allow_reserve": _onemin_allow_reserve() if allow_reserve is None else bool(allow_reserve),
        },
    )
    if not isinstance(payload, dict):
        return None
    if not str(payload.get("lease_id") or "").strip():
        return None
    return dict(payload)


def _reserve_onemin_image_slot_locally(
    *,
    width: int,
    height: int,
    principal_id: str,
    allow_reserve: bool,
    request_id: str,
) -> tuple[dict[str, object], object] | tuple[None, None]:
    def _synthesized_onemin_candidates(*, upstream_module: object | None = None) -> list[dict[str, object]]:
        slots = resolve_onemin_image_slots()
        if not slots:
            return []
        active_env_names: set[str] = set()
        reserve_env_names: set[str] = set()
        if upstream_module is not None:
            try:
                active_env_names = {
                    str(name or "").strip()
                    for name in getattr(upstream_module, "_csv_values")(getattr(upstream_module, "_env")("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS"))
                    if str(name or "").strip()
                }
            except Exception:
                active_env_names = set()
            try:
                reserve_env_names = {
                    str(name or "").strip()
                    for name in getattr(upstream_module, "_csv_values")(getattr(upstream_module, "_env")("EA_RESPONSES_ONEMIN_RESERVE_SLOTS"))
                    if str(name or "").strip()
                }
            except Exception:
                reserve_env_names = set()
        candidates: list[dict[str, object]] = []
        for index, slot in enumerate(slots):
            env_name = str(slot.get("env_name") or "").strip()
            key = str(slot.get("key") or "").strip()
            if not env_name or not key:
                continue
            role = "mixed"
            if env_name in reserve_env_names:
                role = "reserve"
            elif env_name in active_env_names:
                role = "image"
            elif index > 0:
                role = "reserve"
            candidates.append(
                {
                    "account_name": env_name,
                    "account_id": env_name,
                    "slot_name": env_name,
                    "credential_id": env_name,
                    "secret_env_name": env_name,
                    "slot_role": role,
                    "state": "ready",
                    "failure_count": 0,
                    "last_success_at": 0.0,
                    "last_used_at": 0.0,
                    "estimated_remaining_credits": None,
                    "billing_remaining_credits": None,
                    "remaining_credits": None,
                }
            )
        return candidates

    def _candidate_has_known_budget(candidate: dict[str, object]) -> bool:
        for key in ("billing_remaining_credits", "estimated_remaining_credits", "remaining_credits"):
            value = candidate.get(key)
            if value not in (None, ""):
                return True
        return False

    ea_app_root = EA_ROOT / "ea"
    if str(ea_app_root) not in sys.path:
        sys.path.insert(0, str(ea_app_root))
    try:
        from app.repositories.onemin_manager import build_onemin_manager_service_repo
        from app.services import responses_upstream as upstream
        from app.services.onemin_manager import OneminManagerService
        from app.settings import get_settings, settings_with_storage_backend
    except Exception:
        return None, None
    try:
        settings = settings_with_storage_backend(get_settings(), "memory")
        manager = OneminManagerService(repo=build_onemin_manager_service_repo(settings))
        provider_health = upstream._provider_health_report()
        estimated_credits = _estimate_onemin_image_credits(width=width, height=height)
        candidates = manager._candidates_from_provider_health(provider_health=provider_health)  # type: ignore[attr-defined]
        if not candidates:
            candidates = _synthesized_onemin_candidates(upstream_module=upstream)
        reserve_candidates = [
            candidate
            for candidate in candidates
            if str(candidate.get("slot_role") or "").strip().lower() == "reserve"
        ]
        candidate_pools = [reserve_candidates, candidates] if allow_reserve and reserve_candidates else [candidates]
        lease = None
        for candidate_pool in candidate_pools:
            if not candidate_pool:
                continue
            lease = manager.reserve_for_candidates(
                candidates=candidate_pool,
                lane="image",
                capability="image_generate",
                principal_id=principal_id,
                request_id=request_id,
                estimated_credits=estimated_credits,
                allow_reserve=allow_reserve,
            )
            if lease is None and not any(_candidate_has_known_budget(candidate) for candidate in candidate_pool):
                lease = manager.reserve_for_candidates(
                    candidates=candidate_pool,
                    lane="image",
                    capability="image_generate",
                    principal_id=principal_id,
                    request_id=request_id,
                    estimated_credits=0,
                    allow_reserve=allow_reserve,
                )
            if lease is not None:
                break
    except Exception:
        return None, None
    if not isinstance(lease, dict) or not str(lease.get("lease_id") or "").strip():
        return None, None
    return dict(lease), manager


def _release_onemin_image_slot(*, lease_id: str, status: str, actual_credits_delta: int | None = None, error: str = "") -> None:
    normalized = str(lease_id or "").strip()
    if not normalized:
        return
    _ = _ea_local_json_post(
        f"/v1/providers/onemin/leases/{urllib.parse.quote(normalized, safe='')}/release",
        {
            "status": str(status or "released").strip() or "released",
            "actual_credits_delta": actual_credits_delta,
            "error": str(error or "").strip(),
        },
    )


def _release_onemin_image_slot_locally(
    *,
    manager: object | None,
    lease_id: str,
    status: str,
    actual_credits_delta: int | None = None,
    error: str = "",
) -> None:
    normalized = str(lease_id or "").strip()
    if not normalized or manager is None:
        return
    try:
        if actual_credits_delta is not None:
            manager.record_usage(
                lease_id=normalized,
                actual_credits_delta=actual_credits_delta,
                status=str(status or "released").strip() or "released",
            )
        manager.release_lease(
            lease_id=normalized,
            status=str(status or "released").strip() or "released",
            error=str(error or "").strip(),
        )
    except Exception:
        return


def _onemin_manager_selection_available() -> bool:
    return bool(_ONEMIN_MANAGER_SELECTION_CACHE.get("available"))


def easter_egg_allowed_for_target(target: str) -> bool:
    return str(target or "").replace("\\", "/").strip() in SPARSE_EASTER_EGG_TARGETS


def scene_contract_requests_easter_egg(contract: dict[str, object] | None) -> bool:
    data = contract if isinstance(contract, dict) else {}
    policy = str(data.get("easter_egg_policy") or "").strip().lower()
    if policy in {"force", "showcase"}:
        return True
    if any(str(data.get(field) or "").strip() for field in EASTER_EGG_FIELDS):
        return policy in {"allow", "allowed", ""}
    return policy in {"allow", "allowed"}


def media_row_requests_easter_egg(*, target: str, row: dict[str, object] | None) -> bool:
    data = row if isinstance(row, dict) else {}
    contract = data.get("scene_contract") if isinstance(data.get("scene_contract"), dict) else {}
    policy = str(contract.get("easter_egg_policy") or "").strip().lower()
    if policy in {"force", "showcase"}:
        return True
    if not easter_egg_allowed_for_target(target):
        return False
    return scene_contract_requests_easter_egg(contract)


def first_contact_target(target: str) -> bool:
    return str(target or "").replace("\\", "/").strip() in FIRST_CONTACT_TARGETS


def _media_briefs() -> dict[str, object]:
    global _MEDIA_BRIEFS_CACHE
    if _MEDIA_BRIEFS_CACHE is None:
        _MEDIA_BRIEFS_CACHE = load_media_briefs()
    return _MEDIA_BRIEFS_CACHE


def _page_registry() -> dict[str, object]:
    global _PAGE_REGISTRY_CACHE
    if _PAGE_REGISTRY_CACHE is None:
        _PAGE_REGISTRY_CACHE = load_page_registry()
    return _PAGE_REGISTRY_CACHE


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        if "," in cleaned:
            return [part.strip() for part in cleaned.split(",") if part.strip()]
        return [cleaned]
    return []


def _boolish(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    cleaned = str(value or "").strip().lower()
    if cleaned in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if cleaned in {"0", "false", "no", "off", "deny", "denied", "forbid", "forbidden"}:
        return False
    return default


def visual_density_profile_name_for_target(target: str) -> str:
    normalized = str(target or "").replace("\\", "/").strip()
    page_types = _page_registry().get("page_types") if isinstance(_page_registry().get("page_types"), dict) else {}
    if normalized == "assets/hero/chummer6-hero.png":
        return str((page_types.get("root_story") or {}).get("visual_density_profile") or "first_contact_hero").strip()
    if normalized == "assets/pages/horizons-index.png":
        return str((page_types.get("horizon_index") or {}).get("visual_density_profile") or "page_index").strip()
    if normalized == "assets/pages/parts-index.png":
        return "page_index"
    if normalized == "assets/horizons/karma-forge.png":
        return "flagship_horizon"
    return ""


def target_visual_contract(target: str) -> dict[str, object]:
    normalized = str(target or "").replace("\\", "/").strip()
    briefs = _media_briefs()
    contracts = briefs.get("visual_contract") if isinstance(briefs.get("visual_contract"), dict) else {}
    asset_overlay_contracts = (
        briefs.get("asset_overlay_contracts") if isinstance(briefs.get("asset_overlay_contracts"), dict) else {}
    )
    profile_name = visual_density_profile_name_for_target(normalized)
    contract = dict(contracts.get(profile_name) or {}) if profile_name else {}
    asset_contract = dict(asset_overlay_contracts.get(normalized) or {}) if isinstance(asset_overlay_contracts, dict) else {}
    if not asset_contract and normalized == "README.md":
        asset_contract = dict(asset_overlay_contracts.get("assets/hero/chummer6-hero.png") or {})
    contract.update(asset_contract)
    world_marker_bucket = briefs.get("world_marker_bucket")
    if isinstance(world_marker_bucket, list):
        contract.setdefault(
            "world_marker_bucket",
            [str(entry).strip() for entry in world_marker_bucket if str(entry).strip()],
        )
    if briefs.get("world_marker_minimum") not in (None, ""):
        contract.setdefault("world_marker_minimum", briefs.get("world_marker_minimum"))
    if normalized in FIRST_CONTACT_TARGETS:
        critical_style = briefs.get("critical_asset_style_epoch")
        if isinstance(critical_style, dict):
            if isinstance(critical_style.get("overrides_shared_prompt_scaffold"), bool):
                contract.setdefault(
                    "critical_style_overrides_shared_prompt_scaffold",
                    bool(critical_style.get("overrides_shared_prompt_scaffold")),
                )
            contract.setdefault("critical_style_mode", str(critical_style.get("mode") or "").strip())
            contract.setdefault("critical_style_anchor", str(critical_style.get("style_anchor") or "").strip())
            contract.setdefault("critical_negative_prompt", str(critical_style.get("negative_prompt") or "").strip())
    page_types = _page_registry().get("page_types") if isinstance(_page_registry().get("page_types"), dict) else {}
    if normalized == "assets/pages/horizons-index.png":
        horizon_index = page_types.get("horizon_index") if isinstance(page_types.get("horizon_index"), dict) else {}
        anchors = _string_list(contract.get("must_show_semantic_anchors"))
        anchors.extend(_string_list(horizon_index.get("must_show_semantic_anchors")))
        if anchors:
            deduped: list[str] = []
            seen: set[str] = set()
            for entry in anchors:
                key = entry.casefold()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(entry)
            contract["must_show_semantic_anchors"] = deduped
    return contract


def humor_allowed_for_target(*, target: str, contract: dict[str, object] | None) -> bool:
    data = contract if isinstance(contract, dict) else {}
    policy = str(data.get("humor_policy") or "").strip().lower()
    if policy in {"deny", "denied", "forbid", "forbidden", "none", "off"}:
        return False
    if policy in {"allow", "allowed", "showcase", "force"}:
        return True
    visual_contract = target_visual_contract(target)
    if visual_contract and not _boolish(visual_contract.get("humor_allowed"), default=True):
        return False
    return str(target or "").replace("\\", "/").strip() in SPARSE_HUMOR_TARGETS


def person_count_target_for_target(target: str) -> str:
    contract = target_visual_contract(target)
    return str(contract.get("person_count_target") or "").strip().lower()


def cast_prompt_clause_for_target(target: str) -> str:
    profile = person_count_target_for_target(target)
    if profile == "duo_or_team":
        return "Prefer two to four people with one focal operator relationship instead of a lone isolated figure."
    if profile == "plurality_optional":
        return "Keep the environment plural; if people appear, use multiple partial figures or crews instead of a lone centered silhouette."
    if profile == "duo_preferred":
        return "Prefer one active operator plus a visible reviewer, witness, or second pair of hands instead of one isolated person in a glow void."
    return ""


def overlay_mode_for_target(target: str) -> str:
    contract = target_visual_contract(target)
    normalized_mode = (
        str(contract.get("required_overlay_mode") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if normalized_mode:
        return normalized_mode
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized == "assets/hero/chummer6-hero.png":
        return "medscan_diagnostic"
    if normalized == "assets/pages/horizons-index.png":
        return "ambient_diegetic"
    if normalized == "assets/horizons/karma-forge.png":
        return "forge_review_ar"
    return ""


def overlay_mode_prompt_clause(*, target: str, compact: bool = False) -> str:
    mode = overlay_mode_for_target(target)
    if mode == "medscan_diagnostic":
        return (
            "overlay mode medscan diagnostic: slim stat rail, anchored calibration callouts, one or two status capsules, no face-covering panels"
            if compact
            else "Use medscan diagnostic overlays only: a slim stat rail, anchored calibration callouts, and one or two status capsules. No face-covering panels or floating generic rectangles."
        )
    if mode == "ambient_diegetic":
        return (
            "overlay mode ambient diegetic: subtle lane arcs, district markers, no big UI slabs"
            if compact
            else "Use ambient diegetic overlays only: subtle lane arcs, district markers, and path traces. No big UI slabs or city-wide diagnostic rectangles."
        )
    if mode == "forge_review_ar":
        return (
            "overlay mode forge review AR: edge-following rails, provenance seals, rollback vectors, no torso-covering boxes"
            if compact
            else "Use forge-review AR overlays only: edge-following rails, provenance seals, rollback vectors, and compact approval chips. No torso-covering boxes or generic floating HUD slabs."
        )
    return ""


def flagship_prompt_intro(target: str, *, compact: bool = False, fallback: str) -> str:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized == "assets/hero/chummer6-hero.png":
        return (
            "illustrated cover-grade Shadowrun streetdoc poster scene"
            if compact
            else "Illustrated cover-grade Shadowrun streetdoc poster scene. Poster energy is welcome when it stays tied to a lived scene."
        )
    if normalized == "assets/pages/horizons-index.png":
        return (
            "illustrated cover-grade cyberpunk futures crossroads poster scene"
            if compact
            else "Illustrated cover-grade cyberpunk futures crossroads poster scene. Poster energy is welcome when it stays tied to a lived scene."
        )
    if normalized == "assets/horizons/karma-forge.png":
        return (
            "illustrated cover-grade Shadowrun rules-forge poster scene"
            if compact
            else "Illustrated cover-grade Shadowrun rules-forge poster scene. Poster energy is welcome when it stays tied to a lived scene."
        )
    return fallback


def load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _release_build_default_for_pack() -> bool:
    return _boolish(env_value("CHUMMER6_RELEASE_BUILD_ON_PACK"), default=True)


def _release_build_default_for_targets() -> bool:
    return _boolish(env_value("CHUMMER6_RELEASE_BUILD_ON_TARGETS"), default=False)


def _run_release_build_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True)


def run_release_build_pipeline() -> dict[str, object]:
    commands: list[list[str]] = []
    registry_projection = "skipped"
    if RELEASE_CONTROL_SCRIPT.exists():
        registry_cmd = ["python3", str(RELEASE_CONTROL_SCRIPT)]
        commands.append(list(registry_cmd))
        registry_completed = _run_release_build_command(registry_cmd)
        if registry_completed.returncode != 0:
            detail = (registry_completed.stderr or registry_completed.stdout or "").strip()
            raise RuntimeError(f"release_registry_projection_failed:{detail[:240]}")
        registry_projection = "refreshed"
    if not RELEASE_BUILDER_SCRIPT.exists():
        raise RuntimeError(f"release_builder_missing:{RELEASE_BUILDER_SCRIPT}")
    release_cmd = ["python3", str(RELEASE_BUILDER_SCRIPT), "--output", str(RELEASE_MATRIX_OUT)]
    commands.append(list(release_cmd))
    release_completed = _run_release_build_command(release_cmd)
    if release_completed.returncode != 0:
        detail = (release_completed.stderr or release_completed.stdout or "").strip()
        raise RuntimeError(f"release_builder_failed:{detail[:240]}")
    payload: dict[str, object] = {}
    stdout = str(release_completed.stdout or "").strip()
    if stdout:
        try:
            loaded = json.loads(stdout)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {"stdout": stdout}
    return {
        "status": "built",
        "registry_projection": registry_projection,
        "output": str(payload.get("output") or RELEASE_MATRIX_OUT).strip() or str(RELEASE_MATRIX_OUT),
        "commands": commands,
        "artifacts": int(payload.get("artifacts") or 0),
    }


def load_scene_ledger() -> dict[str, object]:
    loaded = load_json_file(SCENE_LEDGER_OUT)
    assets = loaded.get("assets")
    if not isinstance(assets, list):
        loaded["assets"] = []
    return loaded


def scene_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    rows = ledger.get("assets")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def recent_scene_rows(ledger: dict[str, object], *, limit: int = 8) -> list[dict[str, object]]:
    rows = scene_rows(ledger)
    return rows[-max(1, limit) :]


def scene_rows_for_style_epoch(
    ledger: dict[str, object],
    *,
    style_epoch: dict[str, object] | None,
    allow_fallback: bool = True,
) -> list[dict[str, object]]:
    rows = scene_rows(ledger)
    active = dict(style_epoch or {})
    if not active:
        return rows
    filtered = [
        row
        for row in rows
        if isinstance(row.get("style_epoch"), dict) and dict(row.get("style_epoch") or {}) == active
    ]
    if filtered:
        return filtered
    if allow_fallback:
        return rows
    return []


def infer_cast_signature(contract: dict[str, object]) -> str:
    subject = str(contract.get("subject") or "").lower()
    composition = str(contract.get("composition") or "").lower()
    if any(token in subject for token in ("team", "players", "group", "crew", "rest of the table", "trio", "several", "multiple")):
        return "group"
    if subject.count(" and ") >= 2 or ("," in subject and " and " in subject):
        return "group"
    if any(
        token in subject
        for token in (
            "two",
            "duo",
            "pair",
            "operator and",
            "player and",
            "gm and",
            "streetdoc and",
            "runner and",
            "rulesmith and",
            "reviewer and",
            "spotter and",
            "assistant and",
            "teammate and",
            "medic and",
        )
    ):
        return "duo"
    if subject.count(" and ") == 1:
        return "duo"
    if composition in {"group_table", "safehouse_table"}:
        return "group"
    return "solo"


def style_epoch_for_overrides(loaded: dict[str, object]) -> dict[str, object]:
    meta = loaded.get("meta")
    if isinstance(meta, dict):
        style = meta.get("style_epoch")
        if isinstance(style, dict):
            return dict(style)
    return {}


def repetition_block_reason(*, target: str, composition: str, ledger: dict[str, object], allow_repeat: bool = False) -> str:
    recent = recent_scene_rows(ledger)
    lowered = composition.strip().lower()
    normalized_target = str(target or "").replace("\\", "/").strip().lower()
    if not lowered:
        return ""
    if recent:
        last = str(recent[-1].get("composition") or "").strip().lower()
        allow_same_family_rerender = (
            normalized_target.endswith("assets/pages/horizons-index.png")
            and lowered == "horizon_boulevard"
        )
        if last and last == lowered and not allow_same_family_rerender and not allow_repeat:
            return f"composition_repeat:last={last}"
    tableish = SURFACE_HEAVY_COMPOSITIONS
    safehouse_like_count = sum(1 for row in recent if str(row.get("composition") or "").strip().lower() in tableish)
    if lowered in tableish and safehouse_like_count >= 3:
        return f"surface_scene_monoculture:{safehouse_like_count}"
    if target.endswith("horizons-index.png") and lowered in tableish:
        return "horizons_index_must_be_environment_first"
    if target.endswith("alice.png") and lowered in tableish:
        return "alice_must_not_be_table_scene"
    if target.endswith("jackpoint.png") and lowered in tableish:
        return "jackpoint_should_be_dossier_or_dead_drop"
    return ""


def variation_guardrails_for(*, target: str, rows: list[dict[str, object]]) -> list[str]:
    recent = [
        {
            "target": str(row.get("target") or "").strip(),
            "composition": str(row.get("composition") or "").strip(),
            "subject": str(row.get("subject") or "").strip(),
        }
        for row in rows[-6:]
    ]
    compositions = [entry["composition"] for entry in recent if entry.get("composition")]
    rules = [
        "Do not turn this into a generic meeting tableau or medium-wide leather-jacket huddle.",
        "Prefer a distinct scene family, cast signature, and prop cluster over the most recent accepted banners.",
    ]
    if compositions:
        rules.append(f"Recent composition families already used: {', '.join(compositions)}.")
    if sum(1 for value in compositions if value in SURFACE_HEAVY_COMPOSITIONS) >= 3:
        rules.append("Desk, crate, and table-surface grammar are already overserved; prefer clinic, boulevard, station-edge, van, render-lane, service-rack, archive, or proof-room grammar.")
    if target.endswith("horizons-index.png"):
        rules.append("This image must read as a future boulevard or district scene first, not a concept slide.")
    return rules


def ffmpeg_bin() -> str:
    if FFMPEG_BIN and Path(FFMPEG_BIN).exists():
        return FFMPEG_BIN
    raise RuntimeError("ffmpeg_unavailable:ffmpeg executable not found")


def provider_busy_retries() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_RETRIES") or env_value("CHUMMER6_1MIN_BUSY_RETRIES") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


def provider_busy_delay_seconds() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_DELAY_SECONDS") or env_value("CHUMMER6_1MIN_BUSY_DELAY_SECONDS") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


CANON_PARTS = load_part_canon()
CANON_HORIZONS = load_horizon_canon()
LEGACY_PART_SLUGS = {
    "ui": "presentation",
    "mobile": "play",
    "hub": "run-services",
}
HORIZON_MEDIA_FALLBACKS: dict[str, dict[str, object]] = {
    "runsite": {
        "badge": "SITE PACK",
        "kicker": "Spatial truth before the breach starts improvising.",
        "meta": "Status: Horizon Concept // Bounded explorable mission-space artifacts",
        "overlay_hint": "Hotspots, ingress routes, and diegetic location receipts",
        "visual_motifs": [
            "bounded location pack",
            "route overlays",
            "hotspot beacons",
            "museum-grade floor-plan lighting",
            "explorable mission-space context",
        ],
        "overlay_callouts": [
            "Ingress route",
            "Watch angle",
            "Hotspot",
            "Artifact receipt",
        ],
        "scene_contract": {
            "subject": "a runner crew studying an explorable mission-site briefing wall",
            "environment": "a planning room wrapped around a holographic compound map and layered floor plans",
            "action": "tracing ingress paths, chokepoints, and extraction lanes before the breach",
            "metaphor": "mission-space clarity replacing shouted room descriptions",
            "props": ["floor plans", "route overlays", "hotspot markers", "site receipts"],
            "overlays": ["diegetic AR route traces", "hazard markers", "entry labels"],
            "composition": "district_map",
            "palette": "petrol cyan, rust amber, wet concrete neutrals",
            "mood": "focused, spatial, dangerous",
            "humor": "the GM finally gets to stop redrawing the same cursed warehouse on a napkin",
        },
    },
    "runbook-press": {
        "badge": "PRESS ROOM",
        "kicker": "Long-form artifacts without letting vendor dashboards become canon.",
        "meta": "Status: Horizon Concept // Governed long-form publishing lane",
        "overlay_hint": "Editorial receipts, publication manifests, and governed source-pack cues",
        "visual_motifs": [
            "campaign proof sheets",
            "bound source packs",
            "editorial markup",
            "publication manifests",
            "creator desk lighting",
        ],
        "overlay_callouts": [
            "Source pack locked",
            "Editorial approval",
            "Publication manifest",
            "Render-ready proof",
        ],
        "scene_contract": {
            "subject": "a creator-operator assembling a campaign-book proof from governed source packs",
            "environment": "a cramped publishing desk stacked with primers, district drafts, and glowing approval receipts",
            "action": "marking a long-form proof while manifests and citations stay pinned to the spread",
            "metaphor": "creator ambition constrained by governed publication truth",
            "props": ["proof sheets", "bound primers", "approval receipts", "layout boards"],
            "overlays": ["diegetic editorial ticks", "manifest stamps", "citation markers"],
            "composition": "dossier_desk",
            "palette": "rust amber, aged paper cream, petrol cyan monitor spill",
            "mood": "craft-driven, meticulous, slightly sleep-deprived",
            "humor": "the dev discovers publishing is just software scope wearing nicer typography",
        },
    },
}

# Downstream guide visuals must derive from canonical horizon metadata or explicit
# approved overrides. The old bespoke fallback scene map is kept only as dead
# reference during migration and is intentionally disabled at runtime.
HORIZON_MEDIA_FALLBACKS = {}


def provider_order() -> list[str]:
    preferred = list(DEFAULT_PROVIDER_ORDER)
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return _normalized_provider_order(preferred)
    values = [part.strip().lower().replace("-", "_") for part in raw.split(",") if part.strip()]
    filtered: list[str] = []
    for value in values:
        if value in {"markupgo", "pollinations", "ooda_compositor", "scene_contract_renderer", "local_raster"}:
            continue
        if value not in filtered:
            filtered.append(value)
    return filtered or list(preferred)


def _normalized_provider_order(values: list[str]) -> list[str]:
    normalized: list[str] = []
    deferred_onemin: list[str] = []
    for raw in values:
        value = str(raw or "").strip().lower().replace("-", "_")
        if not value:
            continue
        target = deferred_onemin if value in {"onemin", "1min", "1min_ai", "oneminai"} else normalized
        if value not in normalized and value not in deferred_onemin:
            target.append(value)
    return normalized + deferred_onemin


def media_factory_render_command() -> list[str]:
    configured = shlex_command("CHUMMER6_MEDIA_FACTORY_RENDER_COMMAND")
    if configured:
        return configured
    if MEDIA_FACTORY_RENDER_SCRIPT.exists():
        return [
            "python3",
            str(MEDIA_FACTORY_RENDER_SCRIPT),
            "--prompt",
            "{prompt}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ]
    return []


def is_credit_exhaustion_message(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        token in lowered
        for token in (
            "insufficient_credits",
            "insufficient credit",
            "insufficient credits",
            "out of credits",
            "not enough credits",
            "credit balance",
            "balance is too low",
            "quota exceeded",
        )
    )


def forbid_legacy_svg_fallback(asset_path: Path) -> None:
    if asset_path.suffix.lower() == ".svg":
        raise RuntimeError(f"legacy_svg_fallback_forbidden:{asset_path}")


def canonical_horizon_visual_contract(slug: str, item: dict[str, object]) -> dict[str, object]:
    title = str(item.get("title") or slug.replace("-", " ").title()).strip()
    hook = " ".join(str(item.get("hook") or "").split()).strip()
    problem = " ".join(str(item.get("problem") or item.get("brutal_truth") or "").split()).strip()
    use_case = " ".join(str(item.get("use_case") or "").split()).strip()
    access_posture = " ".join(str(item.get("access_posture") or "").split()).strip()
    resource_burden = " ".join(str(item.get("resource_burden") or "").split()).strip()
    booster_nudge = " ".join(str(item.get("booster_nudge") or "").split()).strip()
    foundations = [str(entry).strip() for entry in (item.get("foundations") or []) if str(entry).strip()]
    visual_prompt = (
        f"Cinematic cyberpunk concept art for {title}. {use_case or hook or problem} "
        f"Show concrete props tied to {', '.join(foundations[:3]) or 'governed receipts and mission-ready artifacts'}. "
        "No printed text, no logos, no slide-deck framing."
    ).strip()
    subtitle = hook or use_case or problem or title
    visual_motifs = list(dict.fromkeys([*foundations[:4], access_posture, resource_burden]))
    overlay_callouts = list(dict.fromkeys(foundations[:4] or ["Canonical brief", "Bounded move", "Receipt trail"]))
    composition = "single_protagonist"
    if "site" in slug or "runsite" in slug:
        composition = "district_map"
    elif "runbook-press" in slug or "press" in slug:
        composition = "proof_room"
    elif "jackpoint" in slug:
        composition = "dossier_desk"
    elif "nexus-pan" in slug:
        composition = "van_interior"
    elif "pulse" in slug:
        composition = "forensic_replay"
    elif any(token in slug for token in ("forge", "co-processor")):
        composition = "workshop_bench"
    return {
        "badge": f"HORIZON:{slug.upper().replace('-', '_')[:14]}",
        "title": title,
        "subtitle": subtitle,
        "kicker": "Canonical design is ahead of the richer guide packet, so this scene is grounded directly in the current horizon brief.",
        "note": booster_nudge or problem or use_case,
        "meta": "Status: Horizon Concept // Canon-driven visual seed",
        "visual_prompt": visual_prompt,
        "overlay_hint": "Diegetic receipts and bounded operator overlays only.",
        "visual_motifs": visual_motifs,
        "overlay_callouts": overlay_callouts,
        "scene_contract": {
            "subject": f"{title} made concrete in one playable moment",
            "environment": use_case or problem or "bounded table pain becoming visually legible",
            "action": use_case or hook or "show the horizon payoff in one grounded scene",
            "metaphor": hook or problem or "future table relief rendered without fake product certainty",
            "props": foundations[:4],
            "overlays": foundations[:3],
            "composition": composition,
            "palette": "petrol cyan, rust amber, wet charcoal",
            "mood": "grounded, cinematic, specific",
            "humor": "",
        },
    }


def fallback_horizon_media_row(slug: str, item: dict[str, object]) -> dict[str, object]:
    return canonical_horizon_visual_contract(slug, item)


def deep_merge(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return override if override is not None else base


def clause_mentions_easter_egg(text: str) -> bool:
    lowered = " ".join(str(text or "").split()).strip().lower()
    if "troll" not in lowered:
        return False
    return any(token in lowered for token in EASTER_EGG_OBJECT_HINTS)


def strip_easter_egg_clauses(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[,.;])\s+", cleaned)
    kept = [part.strip() for part in parts if part.strip() and not clause_mentions_easter_egg(part)]
    if kept:
        normalized = " ".join(kept)
        normalized = re.sub(r"\s+,", ",", normalized)
        normalized = re.sub(r"\s+\.", ".", normalized)
        normalized = re.sub(r"\s+;", ";", normalized)
        cleaned = normalized.strip(" ,;")
    if clause_mentions_easter_egg(cleaned):
        cleaned = re.sub(
            r",?\s*(?:a|an|the|tiny|small|subtle|hidden|visible|clearly visible)?\s*troll\b[^,.;]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r"\s+\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = cleaned.strip(" ,;")
    return cleaned


def contains_machine_overlay_language(text: str) -> bool:
    lowered = " ".join(str(text or "").split()).strip().lower()
    if not lowered:
        return False
    banned_tokens = (
        "device id",
        "signal strength",
        "ghost-label",
        "ghost label",
        "metadata string",
        "metadata strings",
        "provenance hash",
        "provenance hashes",
        "version receipt",
        "version receipts",
        "verified stamp",
        "verified stamps",
        "compatibility checkmark",
        "compatibility checkmarks",
        "hud style:",
        "id callout",
        "id callouts",
        "link verified",
        "evidence chain",
        "weapon diagnostics",
        "accuracy modifiers",
        "damage modifiers",
        "smartlink electronics",
        "barrel rifling",
        "hardware diagnostics verified",
        "ares predator",
        "sync complete",
        "grid offline",
        "lua code",
        "lua-backed",
        "combat modifiers",
        "declassified",
    )
    if any(token in lowered for token in banned_tokens):
        return True
    if re.search(r"\b0x[0-9a-f]+\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+)?%\b", lowered):
        return True
    if re.search(r"\b\d+(?:\.\d+){1,}\b", lowered) and any(ch.isalpha() for ch in lowered):
        return True
    if ("'" in lowered or '"' in lowered) and re.search(r"['\"][A-Z0-9 _-]{3,}['\"]", str(text or "")):
        return True
    return False


def sanitize_visual_prompt_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    kept: list[str] = []
    for part in parts:
        piece = str(part or "").strip()
        if not piece:
            continue
        lowered_piece = piece.lower()
        if any(
            token in lowered_piece
            for token in (
                "no printed text",
                "no readable words",
                "no logo",
                "no logos",
                "no watermark",
                "prerelease",
                "pre-release",
                "usable tonight",
                "available today",
                "public guide is active today",
                "integrity clues",
            )
        ):
            continue
        if contains_machine_overlay_language(piece):
            continue
        kept.append(piece)
    return " ".join(kept).strip()


def sanitize_overlay_hint_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    lowered = cleaned.lower()
    if (
        not cleaned
        or contains_machine_overlay_language(cleaned)
        or any(
            token in lowered
            for token in (
                "math should explain itself",
                "public guide is active today",
                "integrity clues",
                "available today",
                "release shelf",
            )
        )
    ):
        return ""
    return cleaned


def sanitize_scene_humor(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    lowered = f" {cleaned.lower()} "
    if any(token in lowered for token in META_HUMOR_TOKENS):
        return ""
    if any(token in lowered for token in READABLE_JOKE_TOKENS):
        return ""
    if ("'" in cleaned or '"' in cleaned) and any(
        token in lowered for token in ("sticker", "sign", "placard", "shirt", "patch", "note", "label", "reads", "says")
    ):
        return ""
    if len(cleaned) > 140:
        return ""
    return cleaned


def sanitize_text_list(values: object, *, allow_easter_egg: bool) -> list[str]:
    def looks_like_machine_overlay_phrase(text: str) -> bool:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return False
        if "_" in cleaned:
            return True
        if re.search(r"\b0x[0-9a-f]+\b", cleaned, re.IGNORECASE):
            return True
        if re.search(r"\b\d+(?:\.\d+)?%\b", cleaned):
            return True
        if re.search(r"\b\d+(?:\.\d+){1,}\b", cleaned) and any(ch.isalpha() for ch in cleaned):
            return True
        if (":" in cleaned or "=" in cleaned) and re.search(r"[:=]\s*(?:0x[0-9a-f]+|[A-Z0-9_.%-]{2,}|\d)", cleaned, re.IGNORECASE):
            return True
        words = re.findall(r"[A-Za-z0-9%.-]+", cleaned)
        if words and not any(ch.islower() for ch in cleaned):
            if len(words) >= 2 or any(any(ch.isdigit() for ch in word) for word in words):
                return True
        return False

    if not isinstance(values, list):
        return []
    cleaned_values: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        lowered = text.lower()
        if not text:
            continue
        if not allow_easter_egg and clause_mentions_easter_egg(text):
            continue
        if looks_like_machine_overlay_phrase(text):
            continue
        if any(
            token in lowered
            for token in (
                "math should explain itself",
                "public guide is active today",
                "integrity clues",
                "available today",
                "release shelf",
                "latest drop",
                "proof trace",
                "usable tonight",
                "prerelease",
                "pre-release",
            )
        ):
            continue
        cleaned_values.append(text)
    return cleaned_values


def sanitize_scene_contract(*, contract: dict[str, object], target: str) -> dict[str, object]:
    cleaned = copy.deepcopy(contract)
    allow_easter_egg = easter_egg_allowed_for_target(target) and scene_contract_requests_easter_egg(cleaned)
    for key in ("subject", "environment", "action", "metaphor", "palette", "mood"):
        value = " ".join(str(cleaned.get(key) or "").split()).strip()
        if not allow_easter_egg and clause_mentions_easter_egg(value):
            value = strip_easter_egg_clauses(value)
        cleaned[key] = value
    humor = sanitize_scene_humor(cleaned.get("humor"))
    cleaned["humor"] = humor if humor_allowed_for_target(target=target, contract=cleaned) else ""
    cleaned["props"] = sanitize_text_list(cleaned.get("props"), allow_easter_egg=allow_easter_egg)
    cleaned["overlays"] = sanitize_text_list(cleaned.get("overlays"), allow_easter_egg=allow_easter_egg)
    if not allow_easter_egg:
        for field in EASTER_EGG_FIELDS:
            cleaned.pop(field, None)
    return cleaned


def sanitize_media_row(*, target: str, row: dict[str, object]) -> dict[str, object]:
    cleaned = copy.deepcopy(row)
    contract = cleaned.get("scene_contract") if isinstance(cleaned.get("scene_contract"), dict) else {}
    if isinstance(contract, dict):
        cleaned["scene_contract"] = sanitize_scene_contract(contract=contract, target=target)
    allow_easter_egg = media_row_requests_easter_egg(target=target, row=cleaned)
    visual_prompt = " ".join(str(cleaned.get("visual_prompt") or "").split()).strip()
    if visual_prompt and not allow_easter_egg:
        cleaned["visual_prompt"] = strip_easter_egg_clauses(visual_prompt)
    cleaned["visual_prompt"] = sanitize_visual_prompt_text(cleaned.get("visual_prompt")) or str(cleaned.get("visual_prompt") or "").strip()
    cleaned["overlay_hint"] = sanitize_overlay_hint_text(cleaned.get("overlay_hint"))
    cleaned["visual_motifs"] = sanitize_text_list(cleaned.get("visual_motifs"), allow_easter_egg=allow_easter_egg)
    cleaned["overlay_callouts"] = sanitize_text_list(cleaned.get("overlay_callouts"), allow_easter_egg=allow_easter_egg)
    return cleaned


def row_has_stale_override_drift(*, target: str, row: dict[str, object]) -> bool:
    texts: list[str] = []
    for key in ("visual_prompt", "overlay_hint", "title", "subtitle", "kicker", "note", "meta"):
        value = str(row.get(key) or "").strip()
        if value:
            texts.append(value)
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    for key in ("subject", "environment", "action", "metaphor", "palette", "mood"):
        value = str(contract.get(key) or "").strip()
        if value:
            texts.append(value)
    for key in ("props", "overlays"):
        values = contract.get(key)
        if isinstance(values, list):
            texts.extend(str(entry).strip() for entry in values if str(entry).strip())
    lowered = "\n".join(texts).lower()
    if any(
        token in lowered
        for token in (
            "rules truth",
            "rules-truth",
            "prerelease",
            "pre-release",
            "usable tonight",
            "available today",
            "public guide is active today",
            "integrity clues",
            "latest drop",
            "release shelf",
        )
    ):
        return True
    if target == "assets/hero/chummer6-hero.png" and any(
        token in lowered
        for token in (
            "task lamp",
            "battered table corner",
            "dice tray",
            "modifier chips",
            "crate",
            "table corner",
            "tabletop",
            "crate desk",
            "waist-height counter",
            "card close-up",
            "alley-brooding",
            "lonely person nursing a gadget",
            "single person in a dim bay",
            "single-person dim bay",
            "one standing runner",
            "one runner deciding",
            "solo trust moment",
            "solo operator",
            "quiet gear bay",
            "vague board",
            "vague prop wall",
            "one man in profile",
            "brooding profile",
            "seated alley brood",
            "brooding alley",
            "moody alley",
            "dominant face crop",
            "quietly satisfying",
            "cyberdeck case",
            "dice tray",
            "modifier chips",
            "over-the-shoulder rules-truth",
            "safehouse edge",
        )
    ):
        return True
    if target == "assets/hero/chummer6-hero.png" and infer_cast_signature(contract) == "solo":
        return True
    if target == "assets/hero/poc-warning.png" and any(
        token in lowered for token in ("desk still life", "scarred desk", "workbench", "coffee ring")
    ):
        return True
    if target == "assets/pages/current-status.png" and any(
        token in lowered
        for token in (
            "real session",
            "wi-fi dies",
            "shared state",
            "tablet screen",
            "phone close-up",
            "heroic screen",
            "wall panel",
            "public monitor",
        )
    ):
        return True
    if target == "assets/pages/public-surfaces.png" and any(
        token in lowered
        for token in (
            "battered tablet in hand",
            "pocket device",
            "screen layouts",
            "monitor triptychs",
            "wall-mounted service slabs",
            "handheld",
            "tablet",
            "phone",
        )
    ):
        return True
    if target == "assets/pages/horizons-index.png" and any(
        token in lowered
        for token in (
            "menu sign",
            "placard wall",
            "directory",
            "storefront",
            "billboard",
            "signboard centerpiece",
            "central sign panel",
            "text-heavy centerpiece",
            "glowing panel",
            "empty road",
            "empty roadway",
            "single roadway",
            "mostly empty roadway",
            "empty interchange",
            "one symbol",
            "one marker",
            "lone centered silhouette",
            "single corridor vanishing point",
            "future table pains",
            "storefronts",
        )
    ):
        return True
    if target == "assets/pages/parts-index.png" and any(
        token in lowered
        for token in (
            "expo hall",
            "kiosk",
            "terminal bank",
            "monitor cluster",
            "screen island",
            "lightbox",
        )
    ):
        return True
    if target == "assets/parts/core.png" and any(
        token in lowered
        for token in (
            "macro dice",
            "dice tray",
            "receipt slip",
            "table surface",
            "isolated prop glamour",
        )
    ):
        return True
    if target == "assets/parts/ui.png" and any(
        token in lowered
        for token in ("laptop", "wall display", "terminal wallpaper", "monitor", "screen", "x-ray")
    ):
        return True
    if target == "assets/parts/mobile.png" and any(
        token in lowered for token in ("handheld", "phone", "tablet", "device glamour", "screen")
    ):
        return True
    if target == "assets/parts/hub.png" and any(
        token in lowered
        for token in ("seated terminal", "operator at keyboard", "monitor", "screen", "dashboard", "wall display")
    ):
        return True
    if target == "assets/horizons/karma-forge.png" and any(
        token in lowered
        for token in (
            "literal blacksmith",
            "anvil",
            "forge fire",
            "medieval",
            "smithy",
            "hammering metal",
            "generic card tinkering",
            "glowing cards",
            "generic console tinkering",
            "single operator at a console",
            "single operator in a glow void",
            "one operator at a console",
            "quiet desk still life",
            "semantically empty glow props",
        )
    ):
        return True
    if target == "assets/horizons/karma-forge.png" and any(
        token in lowered
        for token in (
            "rule shards",
            "hammered into shape",
            "funny and tactile",
            "glowing cards",
            "generic card tinkering",
            "quiet bench",
            "sparse bench",
            "forge scene",
        )
    ):
        return True
    return False


def easter_egg_payload(contract: dict[str, object] | None) -> dict[str, str] | None:
    data = contract if isinstance(contract, dict) else {}
    if not scene_contract_requests_easter_egg(data):
        return None
    return {
        "kind": str(data.get("easter_egg_kind") or "pin").strip(),
        "placement": str(data.get("easter_egg_placement") or "inside the safe crop").strip(),
        "detail": str(
            data.get("easter_egg_detail")
            or "a small recurring Chummer troll motif in the classic horned squat stance"
        ).strip(),
        "visibility": str(
            data.get("easter_egg_visibility")
            or "secondary but clearly visible on a README banner"
        ).strip(),
    }


def load_visual_overrides() -> dict[str, dict[str, object]]:
    if not GUIDE_VISUAL_OVERRIDES.exists():
        return {}
    try:
        loaded = json.loads(GUIDE_VISUAL_OVERRIDES.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for key, value in loaded.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = value
    return normalized


OVERRIDE_PATH = Path("/docker/fleet/state/chummer6/ea_overrides.json")


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    if raw:
        return shlex.split(raw)
    defaults = {
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "prompting_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_humanizer.py"),
            "humanize",
            "--text",
            "{text}",
            "--target",
            "{target}",
        ],
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "magixai_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_PROMPT_REFINER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
    }
    browseract_names = {
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND": (
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND": (
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_HUMANIZER_COMMAND": (
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_HUMANIZER_WORKFLOW_QUERY",
        ),
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND": (
            "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_ID",
            "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_WORKFLOW_QUERY",
        ),
    }
    required_workflow_refs = browseract_names.get(env_name)
    if required_workflow_refs and not any(env_value(name) for name in required_workflow_refs):
        return []
    return list(defaults.get(env_name, []))


def url_template(env_name: str) -> str:
    return env_value(env_name)


def load_media_overrides() -> dict[str, object]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        loaded = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def format_command(parts: list[str], *, prompt: str, target: str, output: str, width: int, height: int) -> list[str]:
    return [part.format(prompt=prompt, target=target, output=output, width=width, height=height) for part in parts]


def run_command_provider(name: str, template: list[str], *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            format_command(
                template,
                prompt=prompt,
                target=output_path.stem,
                output=str(output_path),
                width=width,
                height=height,
            ),
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"{name}:command_failed:{detail[:240]}"
    if output_path.exists() and output_path.stat().st_size > 0:
        return True, f"{name}:rendered"
    return False, f"{name}:empty_output"


def run_url_provider(name: str, template: str, *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    url = template.format(
        prompt=urllib.parse.quote(prompt, safe=""),
        width=width,
        height=height,
        output=urllib.parse.quote(str(output_path), safe=""),
    )
    request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-Media/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def run_pollinations_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)
    endpoint = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt, safe="")
    configured = [entry.strip() for entry in env_value("CHUMMER6_POLLINATIONS_MODEL").split(",") if entry.strip()]
    candidates = configured or ["flux", "turbo", "flux-realism"]
    attempts: list[str] = []
    for model in candidates:
        params = {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
            "seed": str(seed),
            "model": model,
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        ok, detail = _download_remote_image(url, output_path=output_path, name=f"pollinations:{model}")
        attempts.append(detail)
        if ok:
            return ok, detail
    return False, " || ".join(attempts)


def _download_remote_image(url: str, *, output_path: Path, name: str) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"EA-Chummer6-{name}/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:image_http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:image_urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:image_empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def run_magixai_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    api_key = env_value("AI_MAGICX_API_KEY")
    if not api_key:
        return False, "magixai:not_configured"
    model_candidates = magixai_image_model_candidates(env_value("CHUMMER6_MAGIXAI_MODEL"))
    size_candidates = magixai_size_variants(width=width, height=height)
    base_urls = magixai_api_base_urls(env_value("CHUMMER6_MAGIXAI_BASE_URL"))
    headers = {
        "User-Agent": "EA-Chummer6-Magicx/1.0",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    errors: list[str] = []
    for base_url in base_urls:
        for model in model_candidates:
            for size in size_candidates:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "response_format": "url",
                    "n": 1,
                }
                url = magixai_build_url(base_url, MAGIXAI_IMAGE_ENDPOINT)
                request = urllib.request.Request(
                    url,
                    headers=headers,
                    data=json.dumps(payload, sort_keys=True).encode("utf-8"),
                    method="POST",
                )
                body: dict[str, object] | list[object] | str = {}
                try:
                    with urllib.request.urlopen(request, timeout=45) as response:
                        data = response.read()
                        content_type = str(response.headers.get("Content-Type") or "").lower()
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace").strip()
                    if is_credit_exhaustion_message(body):
                        return False, f"magixai:insufficient_credits:http_{exc.code}:{body[:180]}"
                    if '"error":"Forbidden"' in body or '"error": "Forbidden"' in body:
                        return False, f"magixai:forbidden:http_{exc.code}:{body[:180]}"
                    if magixai_looks_like_html(content_type=exc.headers.get("Content-Type"), body=body):
                        errors.append(f"{url}:{model}:{size}:html_response:http_{exc.code}")
                        continue
                    errors.append(f"{url}:{model}:{size}:http_{exc.code}:{body[:180]}")
                    continue
                except urllib.error.URLError as exc:
                    errors.append(f"{url}:{model}:{size}:urlerror:{exc.reason}")
                    continue
                if data:
                    if content_type.startswith("image/"):
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(data)
                        return True, "magixai:rendered"
                    decoded = data.decode("utf-8", errors="replace").strip()
                    if magixai_looks_like_html(content_type=content_type, body=decoded):
                        errors.append(f"{url}:{model}:{size}:html_response")
                        continue
                    if decoded.startswith("http://") or decoded.startswith("https://"):
                        ok, detail = _download_remote_image(decoded, output_path=output_path, name="magixai")
                        if ok:
                            return ok, detail
                        errors.append(detail)
                        continue
                    try:
                        body = json.loads(decoded)
                    except Exception:
                        errors.append(f"{url}:{model}:{size}:non_json_response:{decoded[:180]}")
                        continue
                candidates: list[str] = []
                if isinstance(body, dict):
                    for field in ("url", "image_url"):
                        value = str(body.get(field) or "").strip()
                        if value:
                            candidates.append(value)
                    data_rows = body.get("data")
                    if isinstance(data_rows, list):
                        for entry in data_rows:
                            if not isinstance(entry, dict):
                                continue
                            value = str(entry.get("url") or entry.get("image_url") or "").strip()
                            if value:
                                candidates.append(value)
                    output_rows = body.get("output")
                    if isinstance(output_rows, list):
                        for entry in output_rows:
                            if not isinstance(entry, dict):
                                continue
                            value = str(entry.get("url") or entry.get("image_url") or "").strip()
                            if value:
                                candidates.append(value)
                for candidate in candidates:
                    ok, detail = _download_remote_image(candidate, output_path=output_path, name="magixai")
                    if ok:
                        return ok, detail
                    errors.append(detail)
    return False, "magixai:" + " || ".join(errors[:6])


def resolve_onemin_image_slots() -> list[dict[str, str]]:
    script_path = EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh"
    slots: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_env_names: set[str] = set()
    fallback_env_names = sorted(
        (
            env_name
            for env_name in os.environ
            if re.fullmatch(r"ONEMIN_AI_API_KEY_FALLBACK_(\d+)", env_name)
        ),
        key=lambda env_name: int(env_name.rsplit("_", 1)[-1]),
    )
    for env_name in ("ONEMIN_AI_API_KEY", *fallback_env_names):
        key = env_value(env_name)
        if key and env_name not in seen_env_names:
            seen_env_names.add(env_name)
            seen_keys.add(key)
            slots.append({"env_name": env_name, "key": key})
    if script_path.exists():
        try:
            output = subprocess.check_output(
                ["bash", str(script_path), "--all"],
                text=True,
            )
        except Exception:
            output = ""
        synthetic_index = 0
        for raw in output.splitlines():
            key = str(raw or "").strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                synthetic_index += 1
                slots.append({"env_name": f"ONEMIN_RESOLVED_SLOT_{synthetic_index}", "key": key})
    if str(env_value("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS") or "1").strip().lower() in {"0", "false", "no", "off"}:
        primary = slots[:1]
        if primary:
            return primary
    return slots


def resolve_onemin_image_keys() -> list[str]:
    return [str(slot.get("key") or "").strip() for slot in resolve_onemin_image_slots() if str(slot.get("key") or "").strip()]


def filter_onemin_image_slots(slots: list[dict[str, str]]) -> list[dict[str, str]]:
    available, occupied_account_ids, occupied_secret_env_names = _refresh_onemin_manager_selection_snapshot()
    if not available:
        return []
    if not occupied_account_ids and not occupied_secret_env_names:
        return slots
    filtered: list[dict[str, str]] = []
    for slot in slots:
        env_name = str(slot.get("env_name") or "").strip()
        account_id = env_name
        if env_name and env_name in occupied_secret_env_names:
            continue
        if account_id and account_id in occupied_account_ids:
            continue
        filtered.append(slot)
    return filtered


def _collect_image_candidates(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        candidate = str(value or "").strip()
        lowered = candidate.lower()
        if (" " in candidate) or ("\n" in candidate) or ("\t" in candidate):
            return found
        if candidate.startswith("http://") or candidate.startswith("https://"):
            found.append(candidate)
        elif candidate.startswith("/") and re.search(r"\.(png|jpg|jpeg|webp|gif)(\?|$)", lowered):
            found.append("https://api.1min.ai" + candidate)
        elif (
            ("/" in candidate or "." in candidate)
            and any(token in lowered for token in ("/asset/", "/image/", "/render/", "/download/", ".png", ".jpg", ".jpeg", ".webp", ".gif"))
            and re.search(r"\.(png|jpg|jpeg|webp|gif)(\?|$)", lowered)
        ):
            found.append("https://api.1min.ai/" + candidate.lstrip("/"))
        return found
    if isinstance(value, dict):
        prioritized_fields = ("url", "image_url", "download_url", "image", "imageUrl", "image_url_path")
        for field in prioritized_fields:
            if field in value:
                found.extend(_collect_image_candidates(value.get(field)))
        for nested in value.values():
            found.extend(_collect_image_candidates(nested))
        return found
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            found.extend(_collect_image_candidates(nested))
    return found


def onemin_model_candidates() -> list[str]:
    candidates: list[str] = []
    for candidate in (
        env_value("CHUMMER6_ONEMIN_MODEL"),
        "black-forest-labs/flux-schnell",
        "gpt-image-1-mini",
        "gpt-image-1",
        "dall-e-3",
    ):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def onemin_size_candidates(model: str, *, width: int, height: int) -> list[str]:
    configured = str(env_value("CHUMMER6_ONEMIN_IMAGE_SIZE") or "").strip()
    if configured:
        return [configured]
    normalized = str(model or "").strip().lower()
    if normalized == "black-forest-labs/flux-schnell":
        return [onemin_aspect_ratio(width, height)]
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        return ["auto", "1024x1024", "1024x1536", "1536x1024"]
    return [f"{width}x{height}", "1024x1024", "auto"]


def onemin_aspect_ratio(width: int, height: int) -> str:
    try:
        w = max(1, int(width))
        h = max(1, int(height))
    except Exception:
        return "16:9"
    known = [
        (16, 9),
        (4, 3),
        (3, 2),
        (1, 1),
        (9, 16),
        (2, 3),
        (3, 4),
        (21, 9),
    ]
    ratio = w / h
    best = min(known, key=lambda pair: abs((pair[0] / pair[1]) - ratio))
    return f"{best[0]}:{best[1]}"


def onemin_request_timeout_seconds(model: str) -> int:
    raw = env_value("CHUMMER6_ONEMIN_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(30, int(raw))
        except Exception:
            pass
    normalized = str(model or "").strip().lower()
    if normalized == "black-forest-labs/flux-schnell":
        return 90
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        return 150
    return 45


def onemin_payloads(model: str, *, prompt: str, width: int, height: int) -> list[dict[str, object]]:
    normalized = str(model or "").strip().lower()
    if normalized == "black-forest-labs/flux-schnell":
        prompt_object = {
            "prompt": prompt,
            "aspect_ratio": env_value("CHUMMER6_ONEMIN_ASPECT_RATIO") or onemin_aspect_ratio(width, height),
            "num_inference_steps": int(env_value("CHUMMER6_ONEMIN_FLUX_SCHNELL_STEPS") or 4),
            "go_fast": str(env_value("CHUMMER6_ONEMIN_FLUX_SCHNELL_GO_FAST") or "1").strip().lower() not in {"0", "false", "no", "off"},
            "megapixels": str(env_value("CHUMMER6_ONEMIN_FLUX_SCHNELL_MEGAPIXELS") or "1").strip() or "1",
            "output_quality": int(env_value("CHUMMER6_ONEMIN_FLUX_SCHNELL_OUTPUT_QUALITY") or 80),
        }
        return [
            {
                "type": "IMAGE_GENERATOR",
                "model": model,
                "promptObject": prompt_object,
            }
        ]
    if normalized.startswith("gpt-image-") or normalized.startswith("dall-e-"):
        payloads: list[dict[str, object]] = []
        for size in onemin_size_candidates(model, width=width, height=height):
            prompt_object = {
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": env_value("CHUMMER6_ONEMIN_IMAGE_QUALITY") or "low",
                "style": "natural",
                "output_format": "png",
                "background": "opaque",
            }
            payloads.append(
                {
                    "type": "IMAGE_GENERATOR",
                    "model": model,
                    "promptObject": dict(prompt_object),
                }
            )
        return payloads
    aspect_ratio = env_value("CHUMMER6_ONEMIN_ASPECT_RATIO") or onemin_aspect_ratio(width, height)
    render_mode = env_value("CHUMMER6_ONEMIN_MODE") or "relax"
    base_prompt_object = {
        "prompt": prompt,
        "n": 1,
        "num_outputs": 1,
        "aspect_ratio": aspect_ratio,
        "mode": render_mode,
    }
    payloads = [
        {
            "type": "IMAGE_GENERATOR",
            "model": model,
            "promptObject": dict(base_prompt_object),
        }
    ]
    style = str(env_value("CHUMMER6_ONEMIN_IMAGE_STYLE") or "").strip()
    if style:
        with_style = dict(base_prompt_object)
        with_style["style"] = style
        payloads.append(
            {
                "type": "IMAGE_GENERATOR",
                "model": model,
                "promptObject": with_style,
            }
        )
    return payloads


def run_onemin_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    configured_slots = resolve_onemin_image_slots()
    if not configured_slots:
        return False, "onemin:not_configured"
    principal_id = _onemin_principal_id()
    request_id = f"chummer-image-{int(time.time() * 1000)}-{width}x{height}"
    local_manager = None
    reservation = _reserve_onemin_image_slot(width=width, height=height, allow_reserve=_onemin_allow_reserve())
    if reservation is None:
        reservation, local_manager = _reserve_onemin_image_slot_locally(
            width=width,
            height=height,
            principal_id=principal_id,
            allow_reserve=_onemin_allow_reserve(),
            request_id=request_id,
        )
    if reservation is None:
        if not _onemin_manager_selection_available():
            return False, "onemin:manager_unavailable"
        return False, "onemin:image_capacity_unavailable"
    lease_id = str(reservation.get("lease_id") or "").strip()
    reserved_env_name = str(reservation.get("secret_env_name") or "").strip()
    reserved_account_id = str(reservation.get("account_id") or "").strip()
    slots = [
        slot
        for slot in configured_slots
        if (
            reserved_env_name
            and str(slot.get("env_name") or "").strip() == reserved_env_name
        )
        or (
            reserved_account_id
            and not reserved_env_name
            and str(slot.get("env_name") or "").strip() == reserved_account_id
        )
    ]
    synthetic_reservation = reserved_env_name.startswith("ONEMIN_RESOLVED_SLOT_") or reserved_account_id.startswith("ONEMIN_RESOLVED_SLOT_")
    if synthetic_reservation:
        selected_keys = {
            str(slot.get("key") or "").strip()
            for slot in slots
            if str(slot.get("key") or "").strip()
        }
        fallback_slots = [
            slot
            for slot in configured_slots
            if str(slot.get("key") or "").strip() and str(slot.get("key") or "").strip() not in selected_keys
        ]
        slots = [*slots, *fallback_slots]
    if not slots:
        _release_onemin_image_slot(lease_id=lease_id, status="failed", error="reserved_slot_not_available_locally")
        _release_onemin_image_slot_locally(
            manager=local_manager,
            lease_id=lease_id,
            status="failed",
            error="reserved_slot_not_available_locally",
        )
        return False, "onemin:reserved_slot_not_available_locally"
    model_candidates = onemin_model_candidates()
    endpoints = [
        env_value("CHUMMER6_ONEMIN_ENDPOINT") or "https://api.1min.ai/api/features",
    ]
    errors: list[str] = []
    header_variants = []
    for slot in slots:
        key = str(slot.get("key") or "").strip()
        if not key:
            continue
        header_variants.append(
            {
                "User-Agent": "EA-Chummer6-1min/1.0",
                "Content-Type": "application/json",
                "API-KEY": key,
            }
        )
    seen_requests: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    try:
        for url in endpoints:
            for model in model_candidates:
                payloads = onemin_payloads(model, prompt=prompt, width=width, height=height)
                timeout_seconds = onemin_request_timeout_seconds(model)
                for payload in payloads:
                    prompt_object = payload.get("promptObject") if isinstance(payload, dict) else {}
                    size_label = str(
                        (
                            prompt_object.get("size")
                            if isinstance(prompt_object, dict)
                            else ""
                        )
                        or (
                            prompt_object.get("aspect_ratio")
                            if isinstance(prompt_object, dict)
                            else ""
                        )
                        or "auto"
                    ).strip()
                    payload_json = json.dumps(payload, sort_keys=True)
                    for headers in header_variants:
                        header_key = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
                        request_key = (url, header_key, payload_json)
                        if request_key in seen_requests:
                            continue
                        seen_requests.add(request_key)
                        request = urllib.request.Request(
                            url,
                            headers=headers,
                            data=payload_json.encode("utf-8"),
                            method="POST",
                        )
                        try:
                            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                                data = response.read()
                                content_type = str(response.headers.get("Content-Type") or "").lower()
                        except urllib.error.HTTPError as exc:
                            body = exc.read().decode("utf-8", errors="replace").strip()
                            invalid_size = "Invalid value:" in body and "Supported values are:" in body
                            retryable_busy = exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body and not invalid_size
                            if retryable_busy:
                                busy_recovered = False
                                for _attempt in range(provider_busy_retries()):
                                    time.sleep(provider_busy_delay_seconds())
                                    try:
                                        request = urllib.request.Request(
                                            url,
                                            headers=headers,
                                            data=payload_json.encode("utf-8"),
                                            method="POST",
                                        )
                                        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                                            data = response.read()
                                            content_type = str(response.headers.get("Content-Type") or "").lower()
                                            busy_recovered = True
                                            break
                                    except urllib.error.HTTPError as retry_exc:
                                        body = retry_exc.read().decode("utf-8", errors="replace").strip()
                                        invalid_size = "Invalid value:" in body and "Supported values are:" in body
                                        retryable_busy = retry_exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body and not invalid_size
                                        if not retryable_busy:
                                            errors.append(f"{url}:{model}:{size_label}:http_{retry_exc.code}:{body[:180]}")
                                            break
                                    except urllib.error.URLError as retry_url_exc:
                                        errors.append(f"{url}:{model}:{size_label}:urlerror:{retry_url_exc.reason}")
                                        break
                                    except TimeoutError:
                                        errors.append(f"{url}:{model}:{size_label}:timeout")
                                        break
                                if not busy_recovered:
                                    if retryable_busy:
                                        errors.append(f"{url}:{model}:{size_label}:openai_busy")
                                    continue
                            else:
                                errors.append(f"{url}:{model}:{size_label}:http_{exc.code}:{body[:180]}")
                                continue
                        except urllib.error.URLError as exc:
                            errors.append(f"{url}:{model}:{size_label}:urlerror:{exc.reason}")
                            continue
                        except TimeoutError:
                            errors.append(f"{url}:{model}:{size_label}:timeout")
                            continue
                        if data:
                            if content_type.startswith("image/"):
                                output_path.parent.mkdir(parents=True, exist_ok=True)
                                output_path.write_bytes(data)
                                _release_onemin_image_slot(
                                    lease_id=lease_id,
                                    status="released",
                                    actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                )
                                _release_onemin_image_slot_locally(
                                    manager=local_manager,
                                    lease_id=lease_id,
                                    status="released",
                                    actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                )
                                lease_id = ""
                                return True, "onemin:rendered"
                            decoded = data.decode("utf-8", errors="replace").strip()
                            if decoded.startswith("http://") or decoded.startswith("https://"):
                                ok, detail = _download_remote_image(decoded, output_path=output_path, name="onemin")
                                if ok:
                                    _release_onemin_image_slot(
                                        lease_id=lease_id,
                                        status="released",
                                        actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                    )
                                    _release_onemin_image_slot_locally(
                                        manager=local_manager,
                                        lease_id=lease_id,
                                        status="released",
                                        actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                    )
                                    lease_id = ""
                                    return ok, detail
                                errors.append(detail)
                                continue
                            try:
                                body = json.loads(decoded)
                            except Exception:
                                errors.append(f"{url}:{model}:{size_label}:non_json_response:{decoded[:180]}")
                                continue
                            for candidate in _collect_image_candidates(body):
                                ok, detail = _download_remote_image(candidate, output_path=output_path, name="onemin")
                                if ok:
                                    _release_onemin_image_slot(
                                        lease_id=lease_id,
                                        status="released",
                                        actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                    )
                                    _release_onemin_image_slot_locally(
                                        manager=local_manager,
                                        lease_id=lease_id,
                                        status="released",
                                        actual_credits_delta=_estimate_onemin_image_credits(width=width, height=height),
                                    )
                                    lease_id = ""
                                    return ok, detail
                                errors.append(detail)
    finally:
        if lease_id:
            _release_onemin_image_slot(
                lease_id=lease_id,
                status="failed",
                error=" || ".join(errors[:3]) if errors else "render_failed",
            )
            _release_onemin_image_slot_locally(
                manager=local_manager,
                lease_id=lease_id,
                status="failed",
                error=" || ".join(errors[:3]) if errors else "render_failed",
            )
    return False, "onemin:" + " || ".join(errors[:6])


def palette_for(prompt: str) -> tuple[str, str]:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return PALETTES[int(digest[:2], 16) % len(PALETTES)]


def _font_path(bold: bool = False) -> str:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return path


def _write_text_file(directory: Path, name: str, value: str, *, width: int) -> Path:
    wrapped = textwrap.fill(" ".join(str(value or "").split()).strip(), width=width)
    path = directory / name
    path.write_text(wrapped + "\n", encoding="utf-8")
    return path


def _ffmpeg_path(value: Path) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def refine_prompt_local(prompt: str, *, target: str) -> str:
    return " ".join(prompt.split()).strip()


def prompt_refinement_required() -> bool:
    raw = env_value("CHUMMER6_PROMPT_REFINEMENT_REQUIRED")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def prompt_refinement_disabled() -> bool:
    raw = env_value("CHUMMER6_DISABLE_PROMPT_REFINEMENT")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def prompt_refinement_attempts_enabled() -> bool:
    if prompt_refinement_disabled():
        return False
    explicit_env_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPT_REFINER_COMMAND",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPT_REFINER_URL_TEMPLATE",
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_WORKFLOW_ID",
    ]
    return any(env_value(name) for name in explicit_env_names)


def prompt_refinement_timeout_seconds() -> int:
    raw = env_value("CHUMMER6_PROMPT_REFINEMENT_TIMEOUT_SECONDS") or "25"
    try:
        return max(5, int(raw))
    except Exception:
        return 25


def troll_postpass_enabled() -> bool:
    raw = env_value("CHUMMER6_TROLL_POSTPASS")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def refine_prompt_with_ooda(*, prompt: str, target: str) -> str:
    # OODA-authored visual_prompt is the required source of truth.
    # External prompt refinement is an optional enhancer by default and should
    # only block publishing when explicitly marked required.
    base_prompt = refine_prompt_local(prompt, target=target)
    command_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPT_REFINER_COMMAND",
    ]
    template_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPT_REFINER_URL_TEMPLATE",
    ]
    attempted: list[str] = []
    external_expected = prompt_refinement_attempts_enabled()
    refinement_required = prompt_refinement_required()
    if prompt_refinement_disabled():
        return base_prompt
    if not external_expected and not refinement_required:
        return base_prompt
    for env_name in command_names:
        command = shlex_command(env_name)
        if not command:
            continue
        try:
            completed = subprocess.run(
                [part.format(prompt=base_prompt, target=target) for part in command],
                check=True,
                text=True,
                capture_output=True,
                timeout=prompt_refinement_timeout_seconds(),
            )
            refined = (completed.stdout or "").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    for env_name in template_names:
        template = url_template(env_name)
        if not template:
            continue
        url = template.format(
            prompt=urllib.parse.quote(base_prompt, safe=""),
            target=urllib.parse.quote(target, safe=""),
        )
        request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-PromptRefiner/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                refined = response.read().decode("utf-8", errors="replace").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    if external_expected and refinement_required:
        detail = " || ".join(attempted) if attempted else "no_external_refiner_succeeded"
        raise RuntimeError(f"prompt_refinement_failed:{detail}")
    return base_prompt


def sanitize_prompt_for_provider(prompt: str, *, provider: str) -> str:
    cleaned = " ".join(str(prompt or "").split()).strip()
    if not cleaned:
        return cleaned
    provider_name = str(provider or "").strip().lower()
    if provider_name in {"onemin", "1min", "1min.ai", "oneminai"}:
        replacements = {
            "dangerous": "tense",
            "crash-test dummy": "test mannequin",
            "crash test dummy": "test mannequin",
            "rules truth": "receipt trail",
            "rules-truth": "receipt trail",
            "preview software that is usable tonight": "a rough trace that happens to be visible by accident tonight",
            "proof of concept": "rough concept",
            "pre-release": "concept-stage",
            "prerelease": "concept-stage",
            "blood": "stress",
            "gore": "damage",
            "wounded": "post-run",
            "injury": "strain",
            "injured": "stressed",
            "trauma": "strain",
            "patching up": "stabilizing",
            "patching": "stabilizing",
            "surgery": "calibration",
            "surgical": "repair",
            "exposed cyberware": "open cyberware housing",
            "human runner": "runner",
        }
        for src, dst in replacements.items():
            cleaned = cleaned.replace(src, dst)
        cleaned += " Adult Shadowrun tone is fine; keep violence non-gory."
    return cleaned


def easter_egg_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "pin").strip()
    placement = str(data.get("easter_egg_placement") or "as a small in-world detail inside the safe crop").strip()
    detail = str(
        data.get("easter_egg_detail")
        or "a small recurring Chummer troll motif in the classic horned squat stance"
    ).strip()
    visibility = str(
        data.get("easter_egg_visibility")
        or "secondary but clearly visible on a README banner"
    ).strip()
    return (
        f"Include one small diegetic Chummer troll motif as a {kind}, placed {placement}. "
        f"Detail: {detail}. Keep it {visibility}. "
        "Do not center it, do not crop it out, and do not turn it into the main subject."
    )


def easter_egg_instruction_set(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "small prop").strip()
    placement = str(data.get("easter_egg_placement") or "inside the safe crop").strip()
    detail = str(
        data.get("easter_egg_detail")
        or "a troll in the classic Chummer horned squat stance"
    ).strip()
    return (
        "Secondary art direction for the same image: integrate one small troll easter egg seamlessly into the scene. "
        f"Make it a real {kind} placed {placement}. "
        f"Use this specific motif: {detail}. "
        "It must share the scene lighting, material, texture, and perspective so it feels native to the world. "
        "Do not render it as a pasted logo, floating UI symbol, watermark, or random face decal."
    )


def composition_visual_guardrails(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition == "archive_room":
        return (
            "Use drawers, canisters, locker slots, hanging translucent sleeves, shelf rails, sealed packets, and hard archive hardware. "
            "Do not show binder spines, shelf tabs, envelope fronts, note cards, pinned wall memos, bulletin boards, or readable labels."
        )
    if composition == "review_bay":
        return (
            "Keep the logic on a vertical rail or standing trace surface with chips, bands, clips, suspended markers, and hard physical anchors. "
            "Do not fall back to papers, desk spreads, trays, cards, credit-card plaques, or monitor walls."
        )
    if composition == "workshop_bench":
        return (
            "Use diff strips, approval tabs, rollback cassettes, rails, chips, and housings. "
            "Do not use pages, printouts, loose sheets, forge-fire cosplay, or readable labels."
        )
    if composition == "proof_room":
        return (
            "Use rollers, hanging proof strips, drawers, rails, clamps, and print hardware. "
            "Do not show front-facing pages, headlines, mastheads, readable sheet fronts, or someone presenting a page toward camera."
        )
    if composition == "van_interior":
        return (
            "The van or rig interior must dominate. Any handheld stays buried and secondary. "
            "Do not raise a phone or tablet toward camera, and do not let a screen become the focal object."
        )
    if composition in {"city_edge", "street_front", "horizon_boulevard", "district_map", "transit_checkpoint", "platform_edge", "van_interior"}:
        return (
            "Street and transit clues must use pictograms, arrows, mascot art, crossed-out symbols, color lanes, "
            "and physical landmarks instead of readable signs, posters, neon words, or a central square signboard."
        )
    if composition in {
        "safehouse_table",
        "group_table",
        "over_shoulder_receipt",
        "solo_operator",
        "service_rack",
        "review_bay",
        "clinic_intake",
        "render_lane",
        "desk_still_life",
        "dossier_desk",
        "archive_room",
        "workshop",
        "workshop_bench",
        "proof_room",
        "simulation_lab",
        "rule_xray",
        "passport_gate",
        "mirror_split",
        "loadout_table",
        "forensic_replay",
        "conspiracy_wall",
    }:
        return (
            "Keep papers, dossiers, screens, labels, and forms unreadable, edge-on, cropped, or replaced by chips, "
            "stamps, traces, tokens, light bars, and body language."
        )
    return "Use objects, symbols, and lighting to explain the moment before any readable text would."


def smartlink_overlay_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition == "horizon_boulevard":
        return "Keep any base-scene AR abstract and environmental: lane halos, route arcs, and contingent branch markers only; readable lane labels arrive in verified post-composite overlays."
    if composition == "approval_rail":
        return "Keep any base-scene review instrumentation abstract: edge-following rails, seal glows, and rollback traces only; readable approval language arrives in verified post-composite overlays."
    if composition in {
        "over_shoulder_receipt",
        "transit_checkpoint",
        "platform_edge",
        "van_interior",
        "district_map",
        "forensic_replay",
        "passport_gate",
        "rule_xray",
        "conspiracy_wall",
    }:
        return "Use symbolic smartlink brackets, threat posture cues, ingress cones, or ghost silhouettes; never readable HUD text."
    if composition in {"solo_operator", "service_rack", "review_bay", "clinic_intake", "render_lane", "simulation_lab", "mirror_split", "workshop_bench", "proof_room", "dossier_desk"}:
        return "Keep any base-scene diagnostics abstract: fit-check glows, calibration halos, seam traces, or consequence ghosts only; readable HUD language arrives in verified post-composite overlays."
    return ""


def lore_background_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    composition = str(data.get("composition") or "").strip().lower()
    if composition == "horizon_boulevard":
        return "Secondary lore texture can appear as crossed-out draconic pictograms, extraction arrows, hazard icon stencils, or ward marks, but never as readable signage."
    if composition in {"street_front", "city_edge", "transit_checkpoint", "platform_edge", "van_interior", "district_map"}:
        return "Secondary lore texture is welcome: dragon-warning pictograms, crossed-out draconic pictograms, extraction arrows, or ward marks."
    if composition in {"dossier_desk", "workshop_bench", "proof_room", "simulation_lab", "solo_operator", "review_bay", "clinic_intake", "render_lane"}:
        return "Secondary lore texture can include an anti-dragon sigil, runner superstition sticker, ward mark, or dog-eared bounty card."
    return ""


def scene_integrity_instruction_set(contract: dict[str, object] | None, *, target: str) -> str:
    _ = target
    return (
        "Secondary art direction for the same image: keep it as a lived moment with cover-grade framing, not a static title card. "
        "Show one focal action, one clear prop cluster, and one secondary story clue. "
        f"{composition_visual_guardrails(contract)} "
        "Avoid centered brochure posing, fake readable typography, and generic wallpaper composition."
    )


def easter_egg_stub(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = str(data.get("easter_egg_kind") or "pin").strip()
    placement = str(data.get("easter_egg_placement") or "inside the safe crop").strip()
    return f"subtle diegetic troll motif as {kind} {placement}"


def short_easter_egg_stub(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = compact_text(data.get("easter_egg_kind") or "pin", limit=18)
    placement = compact_text(data.get("easter_egg_placement") or "inside the safe crop", limit=64)
    return f"Troll motif: {kind} {placement}."


def compact_easter_egg_clause(contract: dict[str, object] | None) -> str:
    data = contract if isinstance(contract, dict) else {}
    kind = compact_text(data.get("easter_egg_kind") or "small troll motif", limit=36)
    placement = compact_text(data.get("easter_egg_placement") or "inside the safe crop", limit=90)
    visibility = compact_text(data.get("easter_egg_visibility") or "clearly visible on the banner", limit=72)
    return f"Troll motif: {kind} at {placement}; keep it {visibility}."


def troll_mark_tint(kind: str) -> str:
    lowered = str(kind or "").strip().lower()
    if any(token in lowered for token in ("brass", "gold", "pin")):
        return "#d8ab49"
    if any(token in lowered for token in ("red", "wax", "seal")):
        return "#e76a53"
    if "blue" in lowered:
        return "#4cc0ff"
    if any(token in lowered for token in ("crt", "screen", "green", "ad")):
        return "#61e7a3"
    return "#f2f1e8"


def hex_rgb(value: str) -> tuple[int, int, int]:
    clean = str(value or "").strip().lstrip("#")
    if len(clean) != 6:
        raise ValueError(f"invalid_hex_color:{value}")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def troll_overlay_defaults(*, composition: str, width: int, height: int, kind: str) -> dict[str, object]:
    base_positions = {
        "safehouse_table": (0.46, 0.82),
        "group_table": (0.50, 0.82),
        "desk_still_life": (0.15, 0.80),
        "dossier_desk": (0.20, 0.79),
        "archive_room": (0.14, 0.68),
        "workshop": (0.74, 0.22),
        "district_map": (0.18, 0.78),
        "horizon_boulevard": (0.79, 0.18),
        "city_edge": (0.78, 0.21),
        "street_front": (0.78, 0.21),
        "simulation_lab": (0.14, 0.72),
        "rule_xray": (0.42, 0.82),
        "passport_gate": (0.15, 0.71),
        "mirror_split": (0.48, 0.82),
        "loadout_table": (0.75, 0.74),
        "forensic_replay": (0.78, 0.72),
        "conspiracy_wall": (0.77, 0.33),
    }
    lowered_kind = str(kind or "").strip().lower()
    scale = max(0.75, min(width / 960.0, height / 540.0))
    size = int(34 * scale)
    alpha = 0.86
    rotate = 0.0
    if "sticker" in lowered_kind:
        alpha = 0.78
        rotate = -6.0
    elif any(token in lowered_kind for token in ("stamp", "wax", "seal")):
        alpha = 0.58
        rotate = -4.0
    elif any(token in lowered_kind for token in ("crt", "screen", "ad")):
        alpha = 0.52
    elif "figurine" in lowered_kind:
        alpha = 0.90
        size = int(40 * scale)
    x_ratio, y_ratio = base_positions.get(composition, (0.12, 0.78))
    return {
        "x": int(width * x_ratio),
        "y": int(height * y_ratio),
        "w": size,
        "h": size,
        "alpha": alpha,
        "shadow_alpha": min(0.42, alpha * 0.38),
        "rotate": rotate,
        "tint": troll_mark_tint(kind),
    }


def troll_postpass_settings(*, spec: dict[str, object], width: int, height: int) -> dict[str, object]:
    row = spec.get("media_row") if isinstance(spec, dict) and isinstance(spec.get("media_row"), dict) else {}
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    kind = str(contract.get("easter_egg_kind") or "troll mark").strip()
    composition = str(contract.get("composition") or "").strip()
    settings = troll_overlay_defaults(composition=composition, width=width, height=height, kind=kind)
    override = contract.get("troll_postpass") if isinstance(contract.get("troll_postpass"), dict) else {}
    for key in ("x", "y", "w", "h", "alpha", "shadow_alpha", "rotate", "tint"):
        if key in override and override[key] not in (None, ""):
            settings[key] = override[key]
    return settings


def apply_troll_postpass(*, image_path: Path, spec: dict[str, object], width: int, height: int) -> str:
    if not image_path.exists():
        raise RuntimeError(f"troll_postpass:missing_image:{image_path}")
    if not TROLL_MARK_PATH.exists():
        raise RuntimeError(f"troll_postpass:missing_mark:{TROLL_MARK_PATH}")
    settings = troll_postpass_settings(spec=spec, width=width, height=height)
    tint = str(settings.get("tint") or "#f2f1e8").strip()
    red, green, blue = hex_rgb(tint)
    rg = max(0.0, min(1.0, red / 255.0))
    gg = max(0.0, min(1.0, green / 255.0))
    bg = max(0.0, min(1.0, blue / 255.0))
    alpha = max(0.15, min(1.0, float(settings.get("alpha") or 0.82)))
    shadow_alpha = max(0.08, min(0.6, float(settings.get("shadow_alpha") or 0.28)))
    rotate = float(settings.get("rotate") or 0.0)
    width_px = max(18, int(settings.get("w") or 32))
    height_px = max(18, int(settings.get("h") or 32))
    x = max(0, int(settings.get("x") or 0))
    y = max(0, int(settings.get("y") or 0))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    filter_graph = (
        f"[1:v]scale={width_px}:{height_px},format=rgba,"
        f"colorchannelmixer=rr=0:rg={rg:.3f}:rb=0:gr=0:gg={gg:.3f}:gb=0:br=0:bg={bg:.3f}:bb=0:aa={alpha:.3f},"
        f"rotate={rotate:.3f}*PI/180:ow=rotw(iw):oh=roth(ih):c=none[logo];"
        f"[logo]split[logo_main][logo_shadow];"
        f"[logo_shadow]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_alpha:.3f},boxblur=2:1[shadow];"
        f"[0:v][shadow]overlay={x + 2}:{y + 2}[bg];"
        f"[bg][logo_main]overlay={x}:{y}:format=auto"
    )
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-i",
                str(image_path),
                "-i",
                str(TROLL_MARK_PATH),
                "-filter_complex",
                filter_graph,
                "-frames:v",
                "1",
                str(temp_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_path.replace(image_path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"troll_postpass:ffmpeg_failed:{detail[:240]}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
    return f"troll_postpass:applied:{x}:{y}:{width_px}x{height_px}"


def normalize_banner_size(*, image_path: Path, width: int, height: int) -> str:
    if not image_path.exists():
        raise RuntimeError(f"normalize_banner_size:missing_image:{image_path}")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-i",
                str(image_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                "-frames:v",
                "1",
                str(temp_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_path.replace(image_path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"normalize_banner_size:ffmpeg_failed:{detail[:240]}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
    return f"normalize_banner_size:applied:{width}x{height}"


def first_contact_variant_count(*, target: str) -> int:
    if not first_contact_target(target):
        return 1
    raw = env_value("CHUMMER6_FIRST_CONTACT_VARIANTS")
    try:
        value = int(raw) if raw else 5
    except Exception:
        value = 5
    return max(1, min(12, value))


def visual_audit_enabled(*, target: str) -> bool:
    if not first_contact_target(target):
        return False
    if Image is not None:
        return True
    try:
        return bool(ffmpeg_bin())
    except Exception:
        return False


def critical_visual_gate_failures(
    *,
    target: str,
    base_score: float,
    base_notes: list[str],
    final_score: float,
    final_notes: list[str],
) -> list[str]:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized not in CRITICAL_VISUAL_TARGETS:
        return []
    gate = {
        "assets/hero/chummer6-hero.png": {
            "min_base_score": 85.0,
            "reject_notes": {
                "visual_audit:dead_negative_space",
                "visual_audit:low_semantic_density",
                "visual_audit:insufficient_flash",
                "visual_audit:narrow_subject_cluster",
                "visual_audit:shallow_layering",
                "visual_audit:soft_finish",
            },
        },
        "assets/pages/horizons-index.png": {
            "min_base_score": 78.0,
            "reject_notes": {
                "visual_audit:dead_negative_space",
                "visual_audit:low_semantic_density",
                "visual_audit:narrow_subject_cluster",
                "visual_audit:missing_lane_plurality",
            },
        },
        "assets/horizons/karma-forge.png": {
            "min_base_score": 90.0,
            "reject_notes": {
                "visual_audit:dead_negative_space",
                "visual_audit:low_semantic_density",
                "visual_audit:insufficient_flash",
                "visual_audit:narrow_subject_cluster",
                "visual_audit:shallow_layering",
                "visual_audit:soft_finish",
            },
        },
    }.get(normalized, {})
    failures: list[str] = []
    min_base_score = float(gate.get("min_base_score") or 0.0)
    if min_base_score and base_score < min_base_score:
        failures.append(f"critical_visual_gate:base_score<{min_base_score:.0f}")
    reject_notes = {str(entry).strip() for entry in gate.get("reject_notes") or set() if str(entry).strip()}
    seen_notes = set(base_notes) | set(final_notes)
    for note in sorted(reject_notes):
        if note in seen_notes:
            failures.append(f"critical_visual_gate:{note.split(':', 1)[-1]}")
    if final_score < max(40.0, min_base_score * 0.65):
        failures.append("critical_visual_gate:final_score_too_low")
    return failures


def _overlay_font():
    if ImageFont is None:
        return None
    try:
        return ImageFont.load_default()
    except Exception:  # pragma: no cover - defensive only
        return None


def _text_box(draw, text: str, *, font) -> tuple[int, int]:
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return max(1, right - left), max(1, bottom - top)
    except Exception:  # pragma: no cover - compatibility path
        width, height = draw.textsize(text, font=font)
        return max(1, int(width)), max(1, int(height))


def _ffmpeg_overlay_fontfile() -> str:
    candidates = [
        env_value("CHUMMER6_OVERLAY_FONT"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for candidate in candidates:
        path = Path(str(candidate or "").strip())
        if path.exists():
            return str(path)
    return ""


def _ffmpeg_escape_drawtext(text: str) -> str:
    cleaned = str(text or "")
    return (
        cleaned.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("%", "\\%")
    )


def _ffmpeg_rgba_color(color: tuple[int, int, int, int]) -> str:
    red, green, blue, alpha = color
    return f"0x{red:02x}{green:02x}{blue:02x}@{max(0.0, min(1.0, alpha / 255.0)):.3f}"


def _first_contact_overlay_layout(*, target: str, width: int, height: int) -> dict[str, list[dict[str, object]]]:
    cyan = (39, 212, 255, 110)
    amber = (255, 166, 87, 95)
    red = (255, 78, 78, 110)
    if target == "assets/hero/chummer6-hero.png":
        return {
            "fills": [
                {"x": int(width * 0.04), "y": int(height * 0.16), "w": int(width * 0.008), "h": int(height * 0.48), "color": (39, 212, 255, 78)},
                {"x": int(width * 0.052), "y": int(height * 0.16), "w": int(width * 0.065), "h": int(height * 0.48), "color": (39, 212, 255, 18)},
                {"x": int(width * 0.62), "y": int(height * 0.44), "w": int(width * 0.058), "h": int(height * 0.01), "color": (255, 166, 87, 86)},
                {"x": int(width * 0.34), "y": int(height * 0.615), "w": int(width * 0.1), "h": int(height * 0.01), "color": (39, 212, 255, 72)},
                {"x": int(width * 0.69), "y": int(height * 0.4), "w": int(width * 0.034), "h": int(height * 0.12), "color": (255, 166, 87, 36)},
            ],
            "boxes": [
                {"x": int(width * 0.04), "y": int(height * 0.14), "w": int(width * 0.105), "h": int(height * 0.54), "color": cyan},
            ],
            "lines": [
                {"points": (int(width * 0.145), int(height * 0.28), int(width * 0.31), int(height * 0.35)), "color": cyan, "width": 3},
                {"points": (int(width * 0.145), int(height * 0.58), int(width * 0.29), int(height * 0.62)), "color": cyan, "width": 3},
                {"points": (int(width * 0.44), int(height * 0.62), int(width * 0.58), int(height * 0.585)), "color": cyan, "width": 3},
                {"points": (int(width * 0.72), int(height * 0.455), int(width * 0.675), int(height * 0.452)), "color": amber, "width": 3},
                {"points": (int(width * 0.645), int(height * 0.465), int(width * 0.68), int(height * 0.57)), "color": amber, "width": 2},
                {"points": (int(width * 0.665), int(height * 0.465), int(width * 0.705), int(height * 0.585)), "color": amber, "width": 2},
            ],
            "arcs": [
                {"box": (int(width * 0.39), int(height * 0.22), int(width * 0.62), int(height * 0.47)), "start": 210, "end": 326, "color": cyan, "width": 3},
                {"box": (int(width * 0.49), int(height * 0.36), int(width * 0.76), int(height * 0.7)), "start": 198, "end": 274, "color": amber, "width": 3},
                {"box": (int(width * 0.57), int(height * 0.43), int(width * 0.71), int(height * 0.65)), "start": 214, "end": 336, "color": amber, "width": 2},
            ],
            "chips": [
                {"x": int(width * 0.05), "y": int(height * 0.13), "text": "BOD 5", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.18), "text": "AGI 4 ↑ UPGRADING", "color": amber},
                {"x": int(width * 0.05), "y": int(height * 0.23), "text": "REA 3", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.28), "text": "STR 6", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.33), "text": "CHA 2", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.38), "text": "INT 4", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.43), "text": "LOG 3", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.48), "text": "WIL 5", "color": cyan},
                {"x": int(width * 0.05), "y": int(height * 0.53), "text": "ESS 2.8 ↑ UPGRADING", "color": amber},
                {"x": int(width * 0.05), "y": int(height * 0.58), "text": "EDGE 3", "color": cyan},
                {"x": int(width * 0.58), "y": int(height * 0.39), "text": "CYBERLIMB CALIBRATION", "color": amber},
                {"x": int(width * 0.32), "y": int(height * 0.53), "text": "WOUND STABILIZED", "color": amber},
                {"x": int(width * 0.34), "y": int(height * 0.61), "text": "NEURAL LINK RESYNC", "color": cyan},
            ],
        }
    if target == "assets/pages/horizons-index.png":
        return {
            "fills": [
                {"x": int(width * 0.1), "y": int(height * 0.2), "w": int(width * 0.1), "h": int(height * 0.014), "color": (255, 166, 87, 72)},
                {"x": int(width * 0.28), "y": int(height * 0.63), "w": int(width * 0.12), "h": int(height * 0.014), "color": (255, 166, 87, 58)},
                {"x": int(width * 0.43), "y": int(height * 0.56), "w": int(width * 0.12), "h": int(height * 0.014), "color": (39, 212, 255, 62)},
                {"x": int(width * 0.66), "y": int(height * 0.2), "w": int(width * 0.12), "h": int(height * 0.014), "color": (39, 212, 255, 66)},
                {"x": int(width * 0.71), "y": int(height * 0.61), "w": int(width * 0.12), "h": int(height * 0.014), "color": (255, 166, 87, 58)},
            ],
            "boxes": [
                {"x": int(width * 0.18), "y": int(height * 0.61), "w": int(width * 0.16), "h": int(height * 0.03), "color": amber},
                {"x": int(width * 0.41), "y": int(height * 0.55), "w": int(width * 0.18), "h": int(height * 0.03), "color": cyan},
                {"x": int(width * 0.68), "y": int(height * 0.6), "w": int(width * 0.16), "h": int(height * 0.03), "color": amber},
            ],
            "lines": [
                {"points": (int(width * 0.18), int(height * 0.72), int(width * 0.38), int(height * 0.63)), "color": cyan, "width": 3},
                {"points": (int(width * 0.38), int(height * 0.68), int(width * 0.52), int(height * 0.58)), "color": amber, "width": 3},
                {"points": (int(width * 0.52), int(height * 0.66), int(width * 0.72), int(height * 0.56)), "color": cyan, "width": 3},
                {"points": (int(width * 0.68), int(height * 0.68), int(width * 0.82), int(height * 0.6)), "color": amber, "width": 3},
            ],
            "arcs": [
                {"box": (int(width * 0.12), int(height * 0.5), int(width * 0.34), int(height * 1.06)), "start": 248, "end": 322, "color": amber, "width": 3},
                {"box": (int(width * 0.3), int(height * 0.5), int(width * 0.52), int(height * 1.06)), "start": 248, "end": 322, "color": cyan, "width": 3},
                {"box": (int(width * 0.48), int(height * 0.5), int(width * 0.7), int(height * 1.06)), "start": 248, "end": 322, "color": amber, "width": 3},
                {"box": (int(width * 0.66), int(height * 0.5), int(width * 0.88), int(height * 1.06)), "start": 248, "end": 322, "color": cyan, "width": 3},
            ],
            "chips": [
                {"x": int(width * 0.11), "y": int(height * 0.13), "text": "CLINIC ARC", "color": amber},
                {"x": int(width * 0.44), "y": int(height * 0.51), "text": "ARCHIVE STAIR", "color": cyan},
                {"x": int(width * 0.68), "y": int(height * 0.13), "text": "ROOF ROUTE", "color": cyan},
                {"x": int(width * 0.72), "y": int(height * 0.55), "text": "RAIL YARD", "color": amber},
            ],
        }
    if target == "assets/horizons/karma-forge.png":
        return {
            "fills": [
                {"x": int(width * 0.05), "y": int(height * 0.15), "w": int(width * 0.13), "h": int(height * 0.012), "color": (255, 166, 87, 88)},
                {"x": int(width * 0.65), "y": int(height * 0.13), "w": int(width * 0.15), "h": int(height * 0.012), "color": (255, 78, 78, 92)},
                {"x": int(width * 0.08), "y": int(height * 0.74), "w": int(width * 0.14), "h": int(height * 0.012), "color": (39, 212, 255, 84)},
                {"x": int(width * 0.43), "y": int(height * 0.74), "w": int(width * 0.19), "h": int(height * 0.012), "color": (255, 166, 87, 84)},
                {"x": int(width * 0.55), "y": int(height * 0.47), "w": int(width * 0.14), "h": int(height * 0.012), "color": (39, 212, 255, 78)},
            ],
            "boxes": [
                {"x": int(width * 0.05), "y": int(height * 0.13), "w": int(width * 0.11), "h": int(height * 0.036), "color": amber},
                {"x": int(width * 0.63), "y": int(height * 0.1), "w": int(width * 0.16), "h": int(height * 0.05), "color": red},
            ],
            "lines": [
                {"points": (int(width * 0.22), int(height * 0.16), int(width * 0.35), int(height * 0.29)), "color": amber, "width": 3},
                {"points": (int(width * 0.24), int(height * 0.74), int(width * 0.35), int(height * 0.68)), "color": cyan, "width": 3},
                {"points": (int(width * 0.53), int(height * 0.6), int(width * 0.66), int(height * 0.53)), "color": cyan, "width": 3},
                {"points": (int(width * 0.55), int(height * 0.75), int(width * 0.72), int(height * 0.74)), "color": amber, "width": 3},
                {"points": (int(width * 0.49), int(height * 0.43), int(width * 0.58), int(height * 0.43)), "color": cyan, "width": 2},
                {"points": (int(width * 0.57), int(height * 0.34), int(width * 0.62), int(height * 0.43)), "color": amber, "width": 2},
            ],
            "arcs": [
                {"box": (int(width * 0.49), int(height * 0.12), int(width * 0.93), int(height * 0.56)), "start": 182, "end": 278, "color": red, "width": 4},
                {"box": (int(width * 0.4), int(height * 0.36), int(width * 0.88), int(height * 0.9)), "start": 214, "end": 302, "color": amber, "width": 3},
                {"box": (int(width * 0.18), int(height * 0.46), int(width * 0.72), int(height * 1.02)), "start": 232, "end": 310, "color": cyan, "width": 3},
            ],
            "chips": [
                {"x": int(width * 0.08), "y": int(height * 0.12), "text": "DIFF", "color": amber},
                {"x": int(width * 0.09), "y": int(height * 0.69), "text": "APPROVAL", "color": cyan},
                {"x": int(width * 0.64), "y": int(height * 0.1), "text": "ROLLBACK", "color": red},
                {"x": int(width * 0.58), "y": int(height * 0.41), "text": "PROVENANCE", "color": cyan},
                {"x": int(width * 0.55), "y": int(height * 0.49), "text": "WITNESS LOCK", "color": amber},
                {"x": int(width * 0.6), "y": int(height * 0.57), "text": "COMPATIBILITY ARC", "color": cyan},
                {"x": int(width * 0.45), "y": int(height * 0.69), "text": "REVERT COST", "color": amber},
            ],
        }
    return {"boxes": [], "chips": []}


def _apply_first_contact_overlay_postpass_ffmpeg(*, image_path: Path, target: str, width: int, height: int) -> str:
    layout = _first_contact_overlay_layout(target=target, width=width, height=height)
    filters: list[str] = []
    for fill in layout.get("fills", []):
        filters.append(
            "drawbox="
            f"x={int(fill['x'])}:y={int(fill['y'])}:w={int(fill['w'])}:h={int(fill['h'])}:"
            f"color={_ffmpeg_rgba_color(fill['color'])}:t=fill"
        )
    for box in layout["boxes"]:
        filters.append(
            "drawbox="
            f"x={int(box['x'])}:y={int(box['y'])}:w={int(box['w'])}:h={int(box['h'])}:"
            f"color={_ffmpeg_rgba_color(box['color'])}:t=2"
        )
    fontfile = _ffmpeg_overlay_fontfile()
    escaped_fontfile = fontfile.replace("\\", "\\\\").replace(":", "\\:")
    for chip in layout["chips"]:
        if not fontfile:
            continue
        filters.append(
            "drawtext="
            f"fontfile='{escaped_fontfile}':"
            f"text='{_ffmpeg_escape_drawtext(str(chip['text']))}':"
            f"x={int(chip['x'])}:y={int(chip['y'])}:"
            "fontsize=18:"
            "fontcolor=white@0.92:"
            "box=1:"
            f"boxcolor={_ffmpeg_rgba_color(chip['color'])}:"
            "boxborderw=6"
        )
    if not filters:
        return "first_contact_overlay:unavailable"
    temp_path = image_path.with_name(f"{image_path.stem}.overlaytmp{image_path.suffix}")
    command = [
        ffmpeg_bin(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(image_path),
        "-vf",
        ",".join(filters),
        str(temp_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"first_contact_overlay:ffmpeg_failed:{detail[:240]}") from exc
    if not temp_path.exists():
        raise RuntimeError("first_contact_overlay:ffmpeg_missing_output")
    temp_path.replace(image_path)
    return "first_contact_overlay:applied_ffmpeg"


def _draw_overlay_chip(draw, *, x: int, y: int, text: str, color: tuple[int, int, int, int]) -> None:
    if not text:
        return
    font = _overlay_font()
    text_w, text_h = _text_box(draw, text, font=font)
    pad_x = 6
    pad_y = 4
    fill = (color[0], color[1], color[2], max(42, min(color[3] // 2, 88)))
    draw.rounded_rectangle(
        (x, y, x + text_w + pad_x * 2, y + text_h + pad_y * 2),
        outline=color,
        fill=fill,
        width=2,
        radius=6,
    )
    draw.text((x + pad_x, y + pad_y - 1), text, fill=(241, 246, 250, 220), font=font)


def apply_first_contact_overlay_postpass(*, image_path: Path, spec: dict[str, object], width: int, height: int) -> str:
    if not first_contact_target(str(spec.get("target") or "")):
        return "first_contact_overlay:skipped"
    if Image is None or ImageDraw is None:
        return _apply_first_contact_overlay_postpass_ffmpeg(
            image_path=image_path,
            target=str(spec.get("target") or "").strip(),
            width=width,
            height=height,
        )
    if not image_path.exists():
        raise RuntimeError(f"first_contact_overlay:missing_image:{image_path}")

    target = str(spec.get("target") or "").strip()
    with Image.open(image_path).convert("RGBA") as base:
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        layout = _first_contact_overlay_layout(target=target, width=base.size[0], height=base.size[1])
        if not any(layout.get(key) for key in ("fills", "boxes", "lines", "arcs", "chips")):
            return "first_contact_overlay:skipped"
        for fill in layout.get("fills", []):
            x = int(fill["x"])
            y = int(fill["y"])
            w = int(fill["w"])
            h = int(fill["h"])
            color = tuple(fill["color"])
            draw.rounded_rectangle(
                (x, y, x + w, y + h),
                outline=None,
                fill=color,
                radius=int(fill.get("radius", 6)),
            )
        for box in layout.get("boxes", []):
            x = int(box["x"])
            y = int(box["y"])
            w = int(box["w"])
            h = int(box["h"])
            color = tuple(box["color"])
            draw.rounded_rectangle(
                (x, y, x + w, y + h),
                outline=color,
                fill=(color[0], color[1], color[2], max(18, min(color[3] // 4, 52))),
                width=int(box.get("width", 2)),
                radius=int(box.get("radius", 8)),
            )
        for line in layout.get("lines", []):
            draw.line(tuple(int(value) for value in line["points"]), fill=tuple(line["color"]), width=int(line.get("width", 2)))
        for arc in layout.get("arcs", []):
            draw.arc(tuple(int(value) for value in arc["box"]), start=int(arc["start"]), end=int(arc["end"]), fill=tuple(arc["color"]), width=int(arc.get("width", 2)))
        for chip in layout.get("chips", []):
            _draw_overlay_chip(draw, x=int(chip["x"]), y=int(chip["y"]), text=str(chip["text"]), color=tuple(chip["color"]))

        combined = Image.alpha_composite(base, overlay).convert("RGB")
        combined.save(image_path)
    return "first_contact_overlay:applied"


def _visual_audit_grayscale_grid(*, image_path: Path, width: int = 48, height: int = 36) -> tuple[int, int, list[int]]:
    if not image_path.exists():
        return 0, 0, []
    if Image is not None:
        with Image.open(image_path).convert("L") as image:
            resized = image.resize((width, height))
            return width, height, list(resized.getdata())
    command = [
        ffmpeg_bin(),
        "-v",
        "error",
        "-i",
        str(image_path),
        "-vf",
        f"scale={width}:{height},format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True)
    except Exception:
        return 0, 0, []
    raw = list(completed.stdout or b"")
    if len(raw) != width * height:
        return 0, 0, []
    return width, height, raw


def visual_audit_score(*, image_path: Path, target: str) -> tuple[float, list[str]]:
    width, height, raw = _visual_audit_grayscale_grid(image_path=image_path)
    if not raw:
        return 0.0, ["visual_audit:unavailable"]
    visual_contract = target_visual_contract(target)
    density = str(visual_contract.get("density_target") or "").strip().lower()
    overlay_density = str(visual_contract.get("overlay_density") or "").strip().lower()
    negative_space_cap = str(visual_contract.get("negative_space_cap") or "").strip().lower()
    flash_level = str(visual_contract.get("flash_level") or "").strip().lower()
    tiles_x = 4
    tiles_y = 3
    tile_w = max(1, width // tiles_x)
    tile_h = max(1, height // tiles_y)
    active_tiles = 0
    dark_flat_tiles = 0
    bright_tiles = 0
    bright_tile_floor = 92.0
    if target == "assets/hero/chummer6-hero.png":
        bright_tile_floor = 70.0
    elif target == "assets/horizons/karma-forge.png":
        bright_tile_floor = 34.0
    spreads: list[float] = []
    edge_diffs: list[int] = []
    active_cols: set[int] = set()
    active_rows: set[int] = set()
    for y in range(height):
        row_offset = y * width
        for x in range(1, width):
            edge_diffs.append(abs(raw[row_offset + x] - raw[row_offset + x - 1]))
    for y in range(1, height):
        row_offset = y * width
        prev_offset = (y - 1) * width
        for x in range(width):
            edge_diffs.append(abs(raw[row_offset + x] - raw[prev_offset + x]))
    for y in range(tiles_y):
        for x in range(tiles_x):
            pixels: list[int] = []
            start_x = x * tile_w
            end_x = width if x == tiles_x - 1 else min(width, (x + 1) * tile_w)
            start_y = y * tile_h
            end_y = height if y == tiles_y - 1 else min(height, (y + 1) * tile_h)
            for row in range(start_y, end_y):
                base = row * width
                pixels.extend(raw[base + start_x : base + end_x])
            low = min(pixels) if pixels else 0
            high = max(pixels) if pixels else 0
            avg = mean(pixels) if pixels else 0.0
            spread = float((high or 0) - (low or 0))
            spreads.append(spread)
            if avg < 70 and spread < 28:
                dark_flat_tiles += 1
            if spread >= 42:
                active_tiles += 1
                active_cols.add(x)
                active_rows.add(y)
            if avg >= bright_tile_floor and spread >= 48:
                bright_tiles += 1
    notes: list[str] = []
    score = float(active_tiles * 12 - dark_flat_tiles * 9 + mean(spreads))
    required_active_tiles = 5
    max_dark_flat_tiles = 5
    required_bright_tiles = 0
    required_active_cols = 0
    required_active_rows = 0
    min_edge_energy = 0.0
    if density == "high":
        required_active_tiles = max(required_active_tiles, 6)
        required_active_cols = 3
        required_active_rows = 2
    if overlay_density == "medium":
        required_active_tiles = max(required_active_tiles, 6)
        required_bright_tiles = max(required_bright_tiles, 1)
    elif overlay_density == "high":
        required_active_tiles = max(required_active_tiles, 7)
        required_bright_tiles = max(required_bright_tiles, 2)
    if negative_space_cap == "low":
        max_dark_flat_tiles = min(max_dark_flat_tiles, 4)
    if flash_level == "bold":
        required_bright_tiles = max(required_bright_tiles, 2)
    if target == "assets/hero/chummer6-hero.png":
        required_active_tiles = max(required_active_tiles, 7)
        required_bright_tiles = 1
        required_active_cols = max(required_active_cols, 4)
        required_active_rows = max(required_active_rows, 3)
        min_edge_energy = 28.0
    elif target == "assets/pages/horizons-index.png":
        required_active_tiles = max(required_active_tiles, 7)
        required_active_cols = max(required_active_cols, 4)
    elif target == "assets/horizons/karma-forge.png":
        required_active_tiles = max(required_active_tiles, 8)
        required_bright_tiles = max(required_bright_tiles, 2)
        required_active_cols = max(required_active_cols, 4)
        required_active_rows = max(required_active_rows, 3)
        min_edge_energy = 24.0
    if dark_flat_tiles > max_dark_flat_tiles:
        notes.append("visual_audit:dead_negative_space")
        score -= 25
    if active_tiles < required_active_tiles:
        notes.append("visual_audit:low_semantic_density")
        score -= 25
    if required_bright_tiles and bright_tiles < required_bright_tiles:
        notes.append("visual_audit:insufficient_flash")
        score -= 18
    edge_energy = mean(edge_diffs) if edge_diffs else 0.0
    if min_edge_energy and edge_energy < min_edge_energy:
        notes.append("visual_audit:soft_finish")
        score -= 16
    if required_active_cols and len(active_cols) < required_active_cols:
        notes.append("visual_audit:narrow_subject_cluster")
        score -= 18
    if required_active_rows and len(active_rows) < required_active_rows:
        notes.append("visual_audit:shallow_layering")
        score -= 16
    if target == "assets/pages/horizons-index.png" and len(spreads) >= 12:
        left = mean([spreads[0], spreads[4], spreads[8]])
        center = mean([spreads[1], spreads[5], spreads[9]])
        right = mean([spreads[2], spreads[6], spreads[10]])
        if min(left, center, right) < 24:
            notes.append("visual_audit:missing_lane_plurality")
            score -= 20
    return score, notes


def ensure_troll_clause(*, prompt: str, spec: dict[str, object]) -> str:
    cleaned = " ".join(str(prompt or "").split()).strip()
    if not cleaned:
        return cleaned
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) and isinstance(row.get("scene_contract"), dict) else {}
    target = str(spec.get("target") or "").strip()
    lowered = cleaned.lower()
    additions: list[str] = []
    if "not a static title card" not in lowered and "cover-grade framing" not in lowered:
        additions.append(scene_integrity_instruction_set(contract, target=target))
    if target == "assets/hero/chummer6-hero.png" and not any(
        token in lowered for token in ("troll patient", "troll runner", "hairy troll", "troll on a hacked surgical recliner")
    ):
        additions.append(
            "The patient must read clearly as an ugly hairy troll runner with tusks, heavy body mass, rough scarred skin, dermal texture, and individually visible wet or matted hair strands."
        )
    if (
        media_row_requests_easter_egg(target=target, row=row)
        and "chummer troll motif" not in lowered
        and "diegetic troll motif" not in lowered
        and "horned squat stance" not in lowered
    ):
        additions.append(easter_egg_clause(contract))
        additions.append(easter_egg_instruction_set(contract))
    if not additions:
        return cleaned
    return f"{cleaned} {' '.join(additions)}".strip()


def compact_text(value: object, *, limit: int = 120) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return ""
    for splitter in (". ", "! ", "? "):
        head, sep, _tail = cleaned.partition(splitter)
        if sep and head.strip():
            cleaned = head.strip()
            break
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[: limit + 1]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped.rstrip(" ,;:-")
    while clipped.lower().endswith((" a", " an", " the", " and", " of", " with", " to", " on", " in", " near")):
        shorter = clipped.rsplit(" ", 1)[0].rstrip(" ,;:-")
        if not shorter or shorter == clipped:
            break
        clipped = shorter
    return clipped


def compact_items(values: object, *, limit: int = 3, item_limit: int = 48) -> str:
    if not isinstance(values, (list, tuple)):
        return ""
    cleaned = [compact_text(entry, limit=item_limit) for entry in values]
    items = [entry for entry in cleaned if entry][:limit]
    return ", ".join(items)


def compact_descriptor(value: object, *, limit: int = 96, item_limit: int = 32, item_count: int = 3) -> str:
    if isinstance(value, (list, tuple)):
        return compact_items(value, limit=item_count, item_limit=item_limit)
    return compact_text(value, limit=limit)


def visual_contract_prompt_parts(*, target: str, compact: bool = False) -> list[str]:
    contract = target_visual_contract(target)
    if not contract:
        return []
    density = str(contract.get("density_target") or "").strip().lower()
    overlay_density = str(contract.get("overlay_density") or "").strip().lower()
    negative_space_cap = str(contract.get("negative_space_cap") or "").strip().lower()
    flash_level = str(contract.get("flash_level") or "").strip().lower()
    person_count_target = str(contract.get("person_count_target") or "").strip().lower()
    anchors = [compact_text(entry, limit=72 if compact else 120) for entry in _string_list(contract.get("must_show_semantic_anchors"))]
    blockers = [compact_text(entry, limit=64 if compact else 110) for entry in _string_list(contract.get("must_not_show"))]
    setting_markers = [compact_text(entry, limit=56 if compact else 96) for entry in _string_list(contract.get("required_setting_markers"))]
    cast_markers = [compact_text(entry, limit=52 if compact else 88) for entry in _string_list(contract.get("required_cast_markers"))]
    overlay_schema = [compact_text(entry, limit=24 if compact else 40) for entry in _string_list(contract.get("required_overlay_schema"))]
    status_labels = [compact_text(entry, limit=24 if compact else 36) for entry in _string_list(contract.get("required_status_labels"))]
    forbidden_environment = [
        compact_text(entry, limit=56 if compact else 88) for entry in _string_list(contract.get("forbidden_environment_markers"))
    ]
    forbidden_cast_defaults = [
        compact_text(entry, limit=48 if compact else 84) for entry in _string_list(contract.get("forbidden_cast_defaults"))
    ]
    required_action_posture = [
        compact_text(entry, limit=40 if compact else 72) for entry in _string_list(contract.get("required_action_posture"))
    ]
    troll_markers = [compact_text(entry, limit=42 if compact else 84) for entry in _string_list(contract.get("required_troll_markers"))]
    render_detail = [compact_text(entry, limit=44 if compact else 96) for entry in _string_list(contract.get("required_render_detail"))]
    world_markers = [compact_text(entry, limit=60 if compact else 110) for entry in _string_list(contract.get("world_marker_bucket"))]
    world_marker_minimum = int(contract.get("world_marker_minimum") or 0) if str(contract.get("world_marker_minimum") or "").strip() else 0
    cyberpunk_intensity = str(contract.get("cyberpunk_intensity") or "").strip().lower().replace("_", " ")
    lore_weight = str(contract.get("shadowrun_lore_weight") or "").strip().lower().replace("_", " ")
    critical_style_mode = str(contract.get("critical_style_mode") or "").strip().lower().replace("_", " ")
    critical_style_anchor = compact_text(contract.get("critical_style_anchor") or "", limit=180 if compact else 420)
    critical_negative_prompt = compact_text(contract.get("critical_negative_prompt") or "", limit=160 if compact else 320)
    required_overlay_mode = str(contract.get("required_overlay_mode") or "").strip().lower().replace("_", " ")
    overlay_geometry = [compact_text(entry, limit=40 if compact else 76) for entry in _string_list(contract.get("overlay_geometry"))]
    overlay_priority_order = [compact_text(entry, limit=28 if compact else 52) for entry in _string_list(contract.get("overlay_priority_order"))]
    overlay_actionability_rule = compact_text(contract.get("overlay_actionability_rule") or "", limit=120 if compact else 220)
    overlay_render_strategy = compact_text(
        str(contract.get("overlay_render_strategy") or "").replace("_", " "),
        limit=72 if compact else 132,
    )
    render_layers = [
        compact_text(str(entry).replace("_", " "), limit=24 if compact else 44)
        for entry in _string_list(contract.get("render_layers"))
    ]
    overlay_attachment_rule = compact_text(contract.get("overlay_attachment_rule") or "", limit=100 if compact else 220)
    status_binding_rule = compact_text(contract.get("status_binding_rule") or "", limit=100 if compact else 220)
    style_epoch_force_only = _boolish(contract.get("style_epoch_force_only"), default=False)
    parts: list[str] = []
    if _boolish(contract.get("critical_style_overrides_shared_prompt_scaffold"), default=False):
        parts.append(
            "Let the flagship poster epoch override the softer shared guide-still scaffold."
            if not compact
            else "override shared still scaffold"
        )
    if style_epoch_force_only:
        parts.append(
            "Do not fall back to the softer secondary guide-still epoch for this asset."
            if not compact
            else "no fallback to secondary still epoch"
        )
    if critical_style_mode:
        parts.append(
            f"For this flagship asset, favor {critical_style_mode} energy over restrained editorial still-photography."
            if not compact
            else f"{critical_style_mode} energy"
        )
    if critical_style_anchor:
        parts.append(
            f"Target this render finish: {critical_style_anchor}."
            if not compact
            else f"render finish {critical_style_anchor}"
        )
    if critical_negative_prompt:
        parts.append(
            f"Avoid this finish drift: {critical_negative_prompt}."
            if not compact
            else f"avoid finish drift {critical_negative_prompt}"
        )
    if density == "high":
        parts.append(
            "Keep the frame packed and layered with grounded clues across foreground, midground, and background."
            if not compact
            else "packed layered frame"
        )
    if overlay_density == "high":
        parts.append(
            "Diegetic overlays must do real semantic work and stay visibly present through the frame."
            if not compact
            else "heavy semantic overlays"
        )
    elif overlay_density == "medium":
        parts.append(
            "Include visible diegetic overlay traces that clarify the scene instead of decorative glow."
            if not compact
            else "visible semantic overlays"
        )
    if required_overlay_mode:
        parts.append(
            f"Lock the overlay posture to {required_overlay_mode}."
            if not compact
            else f"overlay posture {required_overlay_mode}"
        )
        parts.append(
            "Render a clean scene plate first; verified readable overlay text and chips will be composited after the art render."
            if not compact
            else "clean scene plate then verified overlay composite"
        )
    if overlay_geometry:
        joined = ", ".join(entry for entry in overlay_geometry if entry)
        if joined:
            parts.append(
                f"Overlay geometry should prefer {joined}."
                if not compact
                else f"geometry {joined}"
            )
    if overlay_priority_order:
        joined = ", ".join(entry for entry in overlay_priority_order if entry)
        if joined:
            parts.append(
                f"Overlay priority order: {joined}."
                if not compact
                else f"overlay priority {joined}"
            )
    if overlay_actionability_rule:
        parts.append(
            overlay_actionability_rule.rstrip(".") + "."
            if not compact
            else overlay_actionability_rule
        )
    if overlay_render_strategy:
        parts.append(
            f"Overlay render strategy: {overlay_render_strategy}."
            if not compact
            else f"overlay strategy {overlay_render_strategy}"
        )
    if render_layers:
        joined = ", ".join(entry for entry in render_layers if entry)
        if joined:
            parts.append(
                f"Pipeline layers: {joined}."
                if not compact
                else f"layers {joined}"
            )
    if overlay_attachment_rule:
        parts.append(
            overlay_attachment_rule.rstrip(".") + "."
            if not compact
            else overlay_attachment_rule
        )
    if status_binding_rule:
        parts.append(
            status_binding_rule.rstrip(".") + "."
            if not compact
            else status_binding_rule
        )
    if troll_markers:
        joined = "; ".join(entry for entry in troll_markers if entry)
        if joined:
            parts.append(
                f"The troll patient must read clearly through: {joined}."
                if not compact
                else f"troll markers {joined}"
            )
    if render_detail:
        joined = "; ".join(entry for entry in render_detail if entry)
        if joined:
            parts.append(
                f"Render detail must hold on: {joined}."
                if not compact
                else f"detail {joined}"
            )
    if world_markers:
        joined = "; ".join(entry for entry in world_markers[:4] if entry)
        if joined:
            minimum = max(1, world_marker_minimum or 0)
            parts.append(
                f"Keep at least {minimum} Shadowrun world markers visible, such as: {joined}."
                if not compact
                else f"world markers {joined}"
            )
    if negative_space_cap == "low":
        parts.append(
            "Avoid dead empty darkness, sparse corners, and quiet negative-space voids."
            if not compact
            else "low negative space"
        )
    if flash_level == "bold":
        parts.append(
            "Push stronger contrast, sharper focal separation, bolder silhouettes, and more cover-like energy."
            if not compact
            else "bold high-contrast energy"
        )
    if person_count_target == "duo_or_team":
        parts.append(
            "Prefer two to four people with one focal operator relationship instead of a lone isolated figure."
            if not compact
            else "two to four people, not one isolated figure"
        )
    elif person_count_target == "plurality_optional":
        parts.append(
            "Keep the scene plural; if people appear, they should imply multiple lanes or crews rather than a lone centered silhouette."
            if not compact
            else "plural scene, no lone centered silhouette"
        )
    elif person_count_target == "duo_preferred":
        parts.append(
            "Prefer one active operator plus a visible reviewer, witness, or second pair of hands instead of one isolated person in a glow void."
            if not compact
            else "visible second actor or witness"
        )
    if anchors:
        joined = "; ".join(entry for entry in anchors if entry)
        if joined:
            parts.append(
                f"Make these semantic anchors legible at a glance: {joined}."
                if not compact
                else f"show {joined}"
            )
    if blockers:
        joined = "; ".join(entry for entry in blockers if entry)
        if joined:
            parts.append(
                f"Do not drift into these failure modes: {joined}."
                if not compact
                else f"avoid {joined}"
            )
    if setting_markers:
        joined = "; ".join(entry for entry in setting_markers if entry)
        if joined:
            parts.append(
                f"Make these setting markers unmistakable in the frame: {joined}."
                if not compact
                else f"show setting markers {joined}"
            )
    if cast_markers:
        joined = "; ".join(entry for entry in cast_markers if entry)
        if joined:
            parts.append(
                f"Make the cast read through these markers: {joined}."
                if not compact
                else f"show cast markers {joined}"
            )
    if overlay_schema:
        joined = ", ".join(entry for entry in overlay_schema if entry)
        if joined:
            parts.append(
                f"Verified overlay language should explicitly use this schema: {joined}."
                if not compact
                else f"overlay schema {joined}"
            )
    if status_labels:
        joined = ", ".join(entry for entry in status_labels if entry)
        if joined:
            parts.append(
                f"When status chips appear, keep these labels available for verified post-composite overlays: {joined}."
                if not compact
                else f"status labels {joined}"
            )
    if forbidden_environment:
        joined = "; ".join(entry for entry in forbidden_environment if entry)
        if joined:
            parts.append(
                f"Do not let the environment drift into: {joined}."
                if not compact
                else f"avoid environments {joined}"
            )
    if forbidden_cast_defaults:
        joined = "; ".join(entry for entry in forbidden_cast_defaults if entry)
        if joined:
            parts.append(
                f"Do not default the cast toward: {joined}."
                if not compact
                else f"avoid cast defaults {joined}"
            )
    if required_action_posture:
        joined = "; ".join(entry for entry in required_action_posture if entry)
        if joined:
            parts.append(
                f"Keep the action posture aligned with: {joined}."
                if not compact
                else f"action posture {joined}"
            )
    if cyberpunk_intensity:
        parts.append(
            f"Cyberpunk-fantasy world intensity should read as {cyberpunk_intensity}, not generic near-future cleanliness."
            if not compact
            else f"{cyberpunk_intensity} cyberpunk intensity"
        )
    if lore_weight:
        parts.append(
            f"Shadowrun-lore specificity should read as {lore_weight}; make the scene feel like runner life rather than generic sci-fi staging."
            if not compact
            else f"{lore_weight} shadowrun lore weight"
        )
    if not _boolish(contract.get("pseudo_text_allowed"), default=True):
        parts.append(
            "Do not invent pseudo-text, fake glyph strings, or readable signboard-like lettering."
            if not compact
            else "no pseudo-text or readable signs"
        )
    if not _boolish(contract.get("humor_allowed"), default=True):
        parts.append(
            "No playful visual joke, cute gag, or sparse humor beat on this asset."
            if not compact
            else "no humor beat"
        )
    return parts


def clip_prompt_text(value: object, *, limit: int) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[: limit + 1]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" ,;:-")


def build_safe_pollinations_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    target = str(spec.get("target") or "").strip()
    if not isinstance(contract, dict):
        cleaned = " ".join(str(prompt or "").split()).strip()
        return cleaned[:220]
    subject = str(contract.get("subject") or "a cyberpunk protagonist").strip()
    environment = str(contract.get("environment") or "a neon-lit cyberpunk setting").strip()
    action = str(contract.get("action") or "holding the moment together").strip()
    metaphor = str(contract.get("metaphor") or "").strip()
    palette = str(contract.get("palette") or "rainy neon cyan and magenta").strip()
    mood = str(contract.get("mood") or "tense but inviting").strip()
    smartlink = compact_text(smartlink_overlay_clause(contract), limit=88)
    lore = compact_text(lore_background_clause(contract), limit=72)
    cast_clause = compact_text(cast_prompt_clause_for_target(target), limit=80)
    overlay_clause = compact_text(overlay_mode_prompt_clause(target=target, compact=True), limit=110)
    contract_clause = ""
    if target and not first_contact_target(target):
        contract_clause = ", ".join(visual_contract_prompt_parts(target=target, compact=True))
    hard_block = ""
    if target == "assets/hero/chummer6-hero.png":
        hard_block = (
            "standing prep wall or clinic intake rail, no crate desk, no tabletop, no seated alley brood, "
            "no dominant face crop, no readable signs"
        )
    elif target in {"assets/pages/horizons-index.png", "assets/pages/parts-index.png"}:
        hard_block = (
            "environment map first, no central signboard, no menu slab, no billboard centerpiece, "
            "humans minimal, no readable text"
        )
    elif target == "assets/horizons/karma-forge.png":
        hard_block = (
            "governed rules evolution, approval rails, rollback cassettes, diff pressure, "
            "no blacksmith forge, no anvil, no tabletop card spread, no readable text"
        )
    elif target in {"assets/pages/current-status.png", "assets/pages/public-surfaces.png"}:
        hard_block = (
            "public wall or threshold scene first, no tablet glamour, no phone close-up, "
            "no glowing panel centerpiece, no readable text"
        )
    parts = [
        flagship_prompt_intro(target, compact=True, fallback="Grounded cinematic cyberpunk scene still"),
        hard_block,
        overlay_clause if overlay_clause else "",
        subject,
        f"in {environment}",
        action,
        metaphor if metaphor else "",
        contract_clause,
        mood,
        palette,
        cast_clause if cast_clause else "one focal subject",
        smartlink if smartlink else "",
        lore if lore else "",
        easter_egg_stub(contract) if media_row_requests_easter_egg(target=target, row=row) else "",
        "no readable text no watermark 16:9",
    ]
    return clip_prompt_text(", ".join(part for part in parts if part), limit=240)


def build_safe_onemin_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    if not isinstance(row, dict):
        row = {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    target = str(spec.get("target") or "").strip()
    if not isinstance(contract, dict):
        return sanitize_prompt_for_provider(prompt, provider="onemin")
    subject = compact_text(contract.get("subject") or "a cyberpunk protagonist", limit=88)
    environment = compact_text(contract.get("environment") or "a neon-lit cyberpunk setting", limit=92)
    action = compact_text(contract.get("action") or "holding the moment together", limit=104)
    metaphor = compact_text(contract.get("metaphor") or "", limit=56)
    composition = compact_text(contract.get("composition") or "single_protagonist", limit=28)
    props = compact_items(contract.get("props"), limit=4, item_limit=24)
    overlays = compact_items(contract.get("overlays"), limit=4, item_limit=24)
    guardrail = compact_text(composition_visual_guardrails(contract), limit=132)
    smartlink = compact_text(smartlink_overlay_clause(contract), limit=64)
    lore = compact_text(lore_background_clause(contract), limit=64)
    framing = compact_text(row.get("framing") or contract.get("framing") or "", limit=92)
    avoid = compact_text(row.get("avoid") or contract.get("avoid") or "", limit=150)
    overlay_clause = overlay_mode_prompt_clause(target=target)
    hard_block = ""
    if target in {
        "assets/hero/chummer6-hero.png",
        "assets/hero/poc-warning.png",
        "assets/pages/start-here.png",
        "assets/pages/current-status.png",
        "assets/pages/public-surfaces.png",
        "assets/pages/parts-index.png",
        "assets/pages/horizons-index.png",
    }:
        hard_block = "If a signboard, poster, label plate, crate stencil, jacket patch, or glowing panel starts to become readable, remove it entirely and keep the composition environmental."
    elif target in {
        "assets/pages/what-chummer6-is.png",
        "assets/pages/where-to-go-deeper.png",
        "assets/parts/core.png",
        "assets/parts/ui-kit.png",
        "assets/horizons/alice.png",
        "assets/horizons/jackpoint.png",
        "assets/horizons/details/jackpoint-scene.png",
        "assets/horizons/karma-forge.png",
        "assets/horizons/nexus-pan.png",
        "assets/horizons/runbook-press.png",
    }:
        hard_block = "If a paper, binder tab, monitor, sheet front, or handheld screen starts to face camera, remove it and replace it with chips, sleeves, rails, clamps, bands, or abstract light traces."
    if target == "assets/hero/chummer6-hero.png":
        hard_block += " The hero must show at least two people: a metahuman streetdoc or support figure beside a wounded runner in a prep chair or intake rail. The environment must read as an improvised garage clinic, patch-up bay, or getaway-van triage space with hacked med gear, tool-chest grime, work lamps, and runner clutter. No crate desk, bench, tabletop, seated brood, dominant face crop, hallway symmetry, or pristine hospital energy."
    elif target == "assets/pages/what-chummer6-is.png":
        hard_block += " Show enough of the room and proof anchors to explain the tool; no face-only portrait, no whiteboard glamour, and no giant blank panel."
    elif target in {"assets/pages/current-status.png", "assets/pages/public-surfaces.png"}:
        hard_block += " Keep any device fully secondary or absent; the wall, shelf, glass, and weathered public surface must carry the frame."
    elif target in {"assets/pages/parts-index.png", "assets/pages/horizons-index.png"}:
        hard_block += " Treat this as an environment map first; human figures should stay minimal, partial, or plural, and no title-card centerpiece is allowed. No lone centered silhouette, no central sign panel, no menu slab, no glowing billboard, no single corridor vanishing point, and no directory board may take over the frame."
    elif target == "assets/horizons/karma-forge.png":
        hard_block += " Prefer a visible reviewer, witness, or second active figure at the approval rail. Do not show fire worship, an anvil, magic runes, glowing letterforms, a fantasy forge pose, paper sheets in hand, loose card inspection, two people sitting at a table, a paperwork workshop, or a tabletop spread of cards as the whole scene; publication-control hardware, rollback machinery, and diff pressure must carry the image."
    elif target == "assets/horizons/runsite.png":
        hard_block += " Planning cues must cling to walls, floors, rails, and crate edges in the real space; never a bright freestanding hologram slab."
    elif target == "assets/horizons/runbook-press.png":
        hard_block += " Keep sheets edge-on, clipped, or half-obscured inside the mechanism; never presented frontally like a readable page."
    parts = [
        flagship_prompt_intro(target, fallback="Grounded cinematic Shadowrun scene still."),
        f"Composition: {composition}." if composition else "",
        hard_block,
        compact_easter_egg_clause(contract) if media_row_requests_easter_egg(target=target, row=row) else "",
        " ".join(visual_contract_prompt_parts(target=target)) if target else "",
        overlay_clause if overlay_clause else "",
        f"Subject: {subject}." if subject else "",
        f"Setting: {environment}." if environment else "",
        f"Moment: {action}." if action else "",
        f"Meaning: {metaphor}." if metaphor else "",
        f"Key props: {props}." if props else "",
        f"Overlay cues: {overlays}." if overlays else "",
        f"Smartlink cues: {smartlink}." if smartlink else "",
        f"Lore cues: {lore}." if lore else "",
        f"Framing: {framing}." if framing else "",
        f"Avoid: {avoid}." if avoid else "",
        f"Guardrail: {guardrail}." if guardrail else "",
        "Human presence must be obvious; not props alone."
        if composition not in {"prop_detail", "desk_still_life", "dossier_desk", "district_map", "horizon_boulevard"}
        else "",
        (
            "Ground the image in one believable Shadowrun place that matches the composition. Poster energy is welcome when it stays tied to a lived scene; never drift into an abstract infographic or empty title card."
            if first_contact_target(target)
            else "Ground the image in one believable Shadowrun place that matches the composition. Not abstract infographic. Not product poster."
        ),
        "Avoid desk-only still lifes unless this target explicitly calls for dossier or prop-detail framing.",
        "No readable words or numbers anywhere.",
        "Do not center signboards, menu boards, glowing panels, bright screens, or text rectangles.",
        "Use pictograms, arrows, chips, glyphs, traces, stamps, and silhouette icons instead of readable lettering.",
        "No watermark. 16:9.",
    ]
    compact_prompt = " ".join(part for part in parts if part)
    return sanitize_prompt_for_provider(clip_prompt_text(compact_prompt, limit=680), provider="onemin")


def _overlay_family(row: dict[str, object], spec: dict[str, object]) -> str:
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    tokens = " ".join(
        [
            str(spec.get("target") or ""),
            str(row.get("overlay_hint") or ""),
            " ".join(str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip()),
            str(contract.get("metaphor") or ""),
            str(contract.get("composition") or ""),
        ]
    ).lower()
    if any(token in tokens for token in ("x-ray", "xray", "modifier", "causality", "receipt trace")):
        return "xray"
    if any(token in tokens for token in ("replay", "seed", "timeline", "sim", "simulation")):
        return "replay"
    if any(token in tokens for token in ("dossier", "evidence", "briefing", "jackpoint")):
        return "dossier"
    if any(token in tokens for token in ("heat", "web", "network", "conspiracy")):
        return "network"
    if any(token in tokens for token in ("passport", "border", "compatibility")):
        return "passport"
    if any(token in tokens for token in ("forge", "anvil", "rules shard")):
        return "forge"
    return "hud"


def _ffmpeg_color(value: str, alpha: float) -> str:
    normalized = str(value or "#34d399").strip()
    if normalized.startswith("#"):
        normalized = "0x" + normalized[1:]
    return f"{normalized}@{alpha:.2f}"


def _overlay_filter_for(*, family: str, accent: str, glow: str, width: int, height: int) -> str:
    accent_soft = _ffmpeg_color(accent, 0.12)
    accent_hard = _ffmpeg_color(accent, 0.24)
    glow_soft = _ffmpeg_color(glow, 0.10)
    left_box = f"drawbox=x=24:y=24:w={max(180, width // 5)}:h={max(44, height // 9)}:color={accent_soft}:t=fill"
    bottom_strip = f"drawbox=x=24:y={max(24, height - 92)}:w={max(220, width // 2)}:h=56:color={glow_soft}:t=fill"
    corner_a = f"drawbox=x=18:y=18:w={max(140, width // 6)}:h=3:color={accent_hard}:t=fill"
    corner_b = f"drawbox=x=18:y=18:w=3:h={max(96, height // 6)}:color={accent_hard}:t=fill"
    if family == "xray":
        return ",".join(
            [
                f"drawgrid=w={max(48, width // 16)}:h={max(48, height // 9)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 3}:y=0:w={max(18, width // 7)}:h={height}:color={accent_soft}:t=fill",
                left_box,
                bottom_strip,
                corner_a,
                corner_b,
            ]
        )
    if family == "replay":
        return ",".join(
            [
                f"drawbox=x=24:y={height // 2}:w={max(220, width - 48)}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 2}:y={height // 2 - 20}:w=4:h=40:color={accent_hard}:t=fill",
                left_box,
                bottom_strip,
            ]
        )
    if family == "dossier":
        return ",".join(
            [
                left_box,
                f"drawbox=x={max(40, width - width // 3)}:y=32:w={max(180, width // 4)}:h={max(72, height // 5)}:color={accent_soft}:t=fill",
                f"drawbox=x={max(56, width - width // 3)}:y={height // 2}:w={max(200, width // 4)}:h={max(120, height // 4)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "network":
        return ",".join(
            [
                f"drawgrid=w={max(72, width // 10)}:h={max(72, height // 7)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 5}:y={height // 3}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2}:y={height // 4}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width - width // 4}:y={height // 2}:w=10:h=10:color={accent_hard}:t=fill",
                bottom_strip,
            ]
        )
    if family == "passport":
        return ",".join(
            [
                left_box,
                f"drawbox=x={width // 2 - 1}:y=24:w=2:h={height - 48}:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 + 12}:y=32:w={max(180, width // 4)}:h={max(72, height // 6)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "forge":
        return ",".join(
            [
                f"drawbox=x=24:y={height - 110}:w={width - 48}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 32}:y={height // 3}:w=64:h=64:color={accent_soft}:t=fill",
                left_box,
                corner_a,
                corner_b,
            ]
        )
    return ",".join([left_box, bottom_strip, corner_a, corner_b])


def apply_context_overlay(*, output_path: Path, spec: dict[str, object], width: int, height: int) -> tuple[bool, str]:
    row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
    if not isinstance(row, dict):
        return False, "context_overlay:missing_media_row"
    family = _overlay_family(row, spec)
    accent, glow = palette_for(
        str(spec.get("target") or output_path.name)
        + "::"
        + str(row.get("overlay_hint") or "")
        + "::"
        + family
    )
    filter_chain = _overlay_filter_for(family=family, accent=accent, glow=glow, width=width, height=height)
    with tempfile.NamedTemporaryFile(prefix="ch6_overlay_", suffix=output_path.suffix, delete=False) as handle:
        temp_output = Path(handle.name)
    try:
        subprocess.run(
            [
                ffmpeg_bin(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(output_path),
                "-vf",
                filter_chain,
                "-frames:v",
                "1",
                str(temp_output),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_output.replace(output_path)
        return True, f"context_overlay:{family}"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"context_overlay_failed:{family}:{detail[:220]}"
    finally:
        try:
            temp_output.unlink(missing_ok=True)
        except Exception:
            pass


def render_with_ooda(*, prompt: str, output_path: Path, width: int, height: int, spec: dict[str, object]) -> dict[str, object]:
    forbid_legacy_svg_fallback(output_path)
    attempts: list[str] = []
    requested_order = spec.get("providers")
    explicit_provider_filter = bool(env_value("CHUMMER6_IMAGE_PROVIDER_ORDER"))
    if isinstance(requested_order, list):
        requested = [str(entry).strip().lower() for entry in requested_order if str(entry).strip()]
        preferred = provider_order()
        if explicit_provider_filter:
            requested = [value for value in requested if value in preferred]
        providers = list(dict.fromkeys(requested)) or preferred
    else:
        providers = provider_order()
    for provider in providers:
        normalized = provider.strip().lower()
        if normalized == "pollinations":
            safe_prompt = build_safe_pollinations_prompt(prompt=prompt, spec=spec)
            ok, detail = run_pollinations_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
        elif normalized in {"media_factory", "media-factory"}:
            ok, detail = run_command_provider(
                "media_factory",
                media_factory_render_command(),
                prompt=prompt,
                output_path=output_path,
                width=width,
                height=height,
            )
        elif normalized == "magixai":
            safe_prompt = sanitize_prompt_for_provider(prompt, provider=normalized)
            ok, detail = run_magixai_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
            if not ok:
                command_ok, command_detail = run_command_provider("magixai", shlex_command("CHUMMER6_MAGIXAI_RENDER_COMMAND"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if command_ok or detail.endswith(":not_configured"):
                    ok, detail = command_ok, command_detail
            if not ok:
                url_ok, url_detail = run_url_provider("magixai", url_template("CHUMMER6_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "markupgo":
            ok, detail = False, "markupgo:disabled_for_primary_art"
        elif normalized == "prompting_systems":
            ok, detail = run_command_provider("prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                url_ok, url_detail = run_url_provider("prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "browseract_magixai":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_magixai", shlex_command("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_magixai", url_template("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_magixai:not_configured"
        elif normalized == "browseract_prompting_systems":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
                if not ok:
                    command_ok, command_detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if command_ok or detail.endswith(":not_configured"):
                        ok, detail = command_ok, command_detail
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_prompting_systems:not_configured"
        elif normalized in {"onemin", "1min", "1min.ai", "oneminai"}:
            safe_prompt = build_safe_onemin_prompt(prompt=prompt, spec=spec)
            ok, detail = run_onemin_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
        elif normalized in {"scene_contract_renderer", "ooda_compositor", "local_raster"}:
            ok, detail = False, f"{normalized}:forbidden_fallback"
        else:
            ok, detail = False, f"{normalized}:unknown_provider"
        attempts.append(detail)
        if ok:
            return {"provider": normalized, "status": detail, "attempts": attempts}
    raise RuntimeError("no image provider succeeded: " + " || ".join(attempts))


def asset_specs() -> list[dict[str, object]]:
    loaded = load_media_overrides()
    media = loaded.get("media") if isinstance(loaded, dict) else {}
    pages = loaded.get("pages") if isinstance(loaded, dict) else {}
    style_epoch = style_epoch_for_overrides(loaded)
    ledger = load_scene_ledger()
    recent_rows = scene_rows_for_style_epoch(ledger, style_epoch=style_epoch, allow_fallback=False)[-8:]
    section_ooda = loaded.get("section_ooda") if isinstance(loaded, dict) else {}
    page_ooda = section_ooda.get("pages") if isinstance(section_ooda, dict) else {}
    visual_overrides = load_visual_overrides()
    hero_override = media.get("hero") if isinstance(media, dict) else {}
    if not isinstance(hero_override, dict) or not str(hero_override.get("visual_prompt", "")).strip():
        raise RuntimeError("missing hero visual_prompt in EA overrides")
    if not isinstance(pages, dict):
        raise RuntimeError("missing page overrides in EA output")
    if not isinstance(page_ooda, dict):
        raise RuntimeError("missing page section OODA in EA output")

    def apply_visual_override(target: str, row: dict[str, object]) -> dict[str, object]:
        if str(target or "").replace("\\", "/").strip() in CANON_LOCKED_TARGETS:
            return sanitize_media_row(target=target, row=row)
        override = visual_overrides.get(target)
        if not isinstance(override, dict):
            return sanitize_media_row(target=target, row=row)
        merged = deep_merge(row, override)
        normalized = merged if isinstance(merged, dict) else row
        sanitized = sanitize_media_row(target=target, row=normalized)
        if row_has_stale_override_drift(target=target, row=sanitized):
            return sanitize_media_row(target=target, row=row)
        return sanitized

    def render_prompt_from_row(row: dict[str, object], *, role: str, target: str) -> str:
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        subject = compact_descriptor(contract.get("subject"), limit=120)
        environment = compact_descriptor(contract.get("environment"), limit=130)
        action = compact_descriptor(contract.get("action"), limit=140)
        metaphor = compact_descriptor(contract.get("metaphor"), limit=80)
        composition = compact_descriptor(contract.get("composition"), limit=32)
        palette = compact_descriptor(contract.get("palette"), limit=72, item_limit=28)
        mood = compact_descriptor(contract.get("mood"), limit=72, item_limit=28)
        humor = sanitize_scene_humor(contract.get("humor"))
        props = compact_items(contract.get("props"), limit=4, item_limit=32)
        overlays = compact_items(contract.get("overlays"), limit=4, item_limit=32)
        motifs = compact_items((row.get("visual_motifs") or []), limit=3, item_limit=28)
        callouts = compact_items((row.get("overlay_callouts") or []), limit=3, item_limit=28)
        visual_prompt = compact_text(row.get("visual_prompt", ""), limit=460)
        style_bits = ", ".join(
            str(style_epoch.get(key) or "").strip()
            for key in ("style_family", "lighting", "lens_grammar", "texture_treatment", "signage_treatment")
            if str(style_epoch.get(key) or "").strip()
        )
        normalized_target = target.replace("\\", "/")
        is_detail_still = "/details/" in normalized_target or normalized_target.endswith("-scene.png")
        is_flagship_asset = first_contact_target(normalized_target)
        visual_contract = target_visual_contract(normalized_target)
        poster_override = _boolish(visual_contract.get("critical_style_overrides_shared_prompt_scaffold"), default=False)
        intro_line = (
            "Close, prop-led illustrated Shadowrun scene poster for a guide detail."
            if is_detail_still
            else (
                "Wide illustrated Shadowrun cover-poster scene for a flagship public guide banner."
                if is_flagship_asset
                else "Wide grounded Shadowrun scene still for a public guide banner."
            )
        )
        smartlink_clause = smartlink_overlay_clause(contract)
        overlay_plate_clause = (
            "Treat this as a clean base-scene plate first. Do not bake final stat rails, approval tags, readable badges, or boxed HUD slabs into the painting; leave those for the deterministic post-composite overlay layer."
            if is_flagship_asset
            else ""
        )
        lore_clause = lore_background_clause(contract)
        prompt_parts = [
            intro_line,
            visual_prompt,
            *visual_contract_prompt_parts(target=target),
            f"One clear focal subject: {subject}." if subject else "",
            f"Set the scene in {environment}." if environment else "",
            f"Show this happening: {action}." if action else "",
            f"Make the core visual metaphor immediately legible: {metaphor}." if metaphor else "",
            f"Use a {composition} composition." if composition else "",
            f"Palette: {palette}." if palette else "",
            f"Mood: {mood}." if mood else "",
            f"Humor note: {humor}." if humor else "",
            f"Concrete visible props: {props}." if props else "",
            (
                f"Reserve these overlay semantics for the verified composite layer rather than baking readable UI into the artwork: {overlays}."
                if overlays and is_flagship_asset
                else (f"Useful diegetic overlays in-scene: {overlays}." if overlays else "")
            ),
            f"Secondary motif cues: {motifs}." if motifs else "",
            (
                f"Reserve these short labels for the verified composite layer only: {callouts}."
                if callouts and is_flagship_asset
                else (f"Nonverbal idea cues only: {callouts}." if callouts else "")
            ),
            overlay_plate_clause,
            smartlink_clause,
            lore_clause,
            (
                "Keep the shared guide continuity in palette, texture, and world feel without softening the flagship poster finish."
                if style_bits and is_flagship_asset and poster_override
                else (f"Keep the overall look consistent with: {style_bits}." if style_bits else "")
            ),
            easter_egg_clause(contract) if media_row_requests_easter_egg(target=target, row=row) else "",
            (
                "Make it feel like a lived-in Shadowrun world scene with illustrated cover-grade energy, not a tasteful editorial still, glossy brochure cover, or tabletop glamour shot."
                if is_flagship_asset
                else "Make it feel like a lived-in Shadowrun world scene with cover-grade energy, not a glossy brochure cover or tabletop glamour shot."
            ),
            "Avoid generic skylines, abstract icon soup, flat infographics, or brochure-cover posing.",
            "Do not print text, prompts, OODA labels, metadata, or resolution callouts on the image.",
            "No readable words or numbers on screens, papers, props, or overlays; use abstract bars, chips, glyphs, or traces instead.",
            "No readable letters on clothing patches, warning placards, crate plates, stickers, wall marks, or chest labels.",
            "Do not center any signboard, menu board, placard, monitor, or glowing panel as the main subject.",
            "If signage appears at all, keep it peripheral, abstract, and unreadable.",
            "Avoid bright framed screens, glowing wall panels, or illuminated rectangles becoming the composition anchor.",
            "Never render the words WARNING, MENU, OPEN, EXIT, ALPHA, BETA, or any other legible label.",
            "No readable titles, no watermark, no giant centered logos, 16:9.",
        ]
        return " ".join(part for part in prompt_parts if part)

    def page_media_row(page_id: str, *, role: str, composition_hint: str) -> dict[str, object]:
        page_row = pages.get(page_id)
        ooda_row = page_ooda.get(page_id)
        if not isinstance(page_row, dict):
            raise RuntimeError(f"missing page override for media asset: {page_id}")
        if not isinstance(ooda_row, dict):
            raise RuntimeError(f"missing section OODA for media asset: {page_id}")
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
        orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
        decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
        visual_seed = str(act.get("visual_prompt_seed", "")).strip()
        intro = str(page_row.get("intro", "")).strip()
        body = str(page_row.get("body", "")).strip()
        focal = str(orient.get("focal_subject", "")).strip()
        scene_logic = str(orient.get("scene_logic", "")).strip()
        overlay = str(decide.get("overlay_priority", "")).strip()
        interests = observe.get("likely_interest") if isinstance(observe.get("likely_interest"), list) else []
        concrete = observe.get("concrete_signals") if isinstance(observe.get("concrete_signals"), list) else []
        if not visual_seed:
            raise RuntimeError(f"missing visual prompt seed for page media asset: {page_id}")
        return {
            "title": role,
            "subtitle": intro,
            "kicker": str(page_row.get("kicker", "")).strip(),
            "note": body,
            "overlay_hint": overlay or str(orient.get("visual_devices", "")).strip(),
            "visual_prompt": visual_seed,
            "visual_motifs": [str(entry).strip() for entry in interests if str(entry).strip()],
            "overlay_callouts": [str(entry).strip() for entry in concrete if str(entry).strip()],
            "scene_contract": {
                "subject": focal or "a cyberpunk protagonist",
                "environment": scene_logic or body,
                "action": str(act.get("paragraph_seed", "")).strip() or str(act.get("one_liner", "")).strip(),
                "metaphor": "",
                "props": [str(entry).strip() for entry in interests if str(entry).strip()][:5],
                "overlays": [str(entry).strip() for entry in concrete if str(entry).strip()][:4],
                "composition": composition_hint,
                "palette": str(orient.get("visual_devices", "")).strip(),
                "mood": str(orient.get("emotional_goal", "")).strip(),
                "humor": "",
            },
        }

    def page_spec(*, target: str, page_id: str, role: str, composition_hint: str) -> dict[str, object]:
        row = apply_visual_override(target, page_media_row(page_id, role=role, composition_hint=composition_hint))
        return {
            "target": target,
            "role": role,
            "prompt": render_prompt_from_row(row, role=role, target=target),
            "width": 960,
            "height": 540,
            "media_row": row,
            "style_epoch": style_epoch,
            "providers": provider_order(),
        }

    target_scene_policies: dict[str, dict[str, object]] = {
        "assets/hero/chummer6-hero.png": {
            "required": "clinic_intake",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "person_count_target": "duo_or_team",
            "prompt_nudge": "Treat the hero like a first-contact Shadowrun runner-life poster, not a quiet mood still: obvious ork or other metahuman streetdoc anatomy, an ugly hairy troll patient with readable tusks and dermal texture, wounded-runner trust pressure, hacked med gear, magic-tech coexistence, visible attribute rails, and strong foreground-midground-background layering. Push harder on poster energy with stronger orange-cyan contrast, harsher rim light, wetter reflections, sharper prop detail, and a real barrens patch-up feel. This is an improvised streetdoc garage clinic or getaway-van triage lane with at least two active people in frame, not alley-brooding at a crate, not desk glamour, not a clean hospital exam room, and not a lonely human doctor in a tidy white coat.",
            "environment": "an improvised streetdoc garage clinic carved into a rain-soaked barrens auto bay, with a hacked surgical recliner made from a mechanic chair, tool chests, lift-bay residue, hanging cables, med-gel, injector trays, cyberlimb parts, ammo trays, six-sided dice, a magical focus, tarp dividers, extension cords, rust, oil stains, wet concrete, and hard fluorescent strips fighting with amber work lamps across the room",
            "subject": "an obvious ork or other metahuman streetdoc actively stabilizing an ugly hairy troll runner on a hacked surgical recliner while a teammate crowds the opposite side with tools, telemetry, or light",
            "action": "the streetdoc is physically calibrating cyberware fit, checking recovery traces, or stabilizing post-run strain while the troll runner braces in the chair with visible tusks, rough scarred skin, and matted hair, and the support figure reaches into frame with tool handoff, trust traces, attribute checks, and proof anchors spread through the improvised garage clinic",
            "metaphor": "trust becoming visible through physical prep traces",
            "replace_visual_prompt": "16:9 illustrated promo-poster key art for a cyberpunk-fantasy runner-life scene in an improvised streetdoc garage clinic inside a rain-soaked barrens auto bay. An ork streetdoc with visible tusks is actively stabilizing and calibrating an ugly hairy troll runner on a hacked surgical recliner built from an old mechanic chair while one assistant or teammate crowds the opposite edge with tools or telemetry. The troll patient must read clearly through heavy body mass, coarse visible hair, wet or matted hair clumping, rough scarred skin, dermal texture, and readable tusks. Layer physical props everywhere: tool chest, hacked med gear, med-gel, cyberarm parts, ammo tray, six-sided dice, commlink, route scribbles, magical focus, cable bundles, cheap fluorescent strips, work lamps, hanging cables, tarp divider, rust, oil stains, wet concrete, and electric-blue diagnostics against warm amber work light. The frame must feel grimy, mythic, and specific enough that a new viewer immediately reads Shadowrun streetdoc culture, runner-life recovery pressure, character-build trust, and cyberware calibration instead of generic sci-fi medicine. Push harder toward packed flashy cover-art energy with stronger orange-cyan contrast, sharper rim light, bolder silhouettes, more diagonal force, crisp material detail, and obvious left-side attribute-rail support. Show at least two active people clearly in frame with visible hands doing work. No human patient, no clean-shaved patient, no back-facing idle pair, no hallway symmetry, no clean van interior with no garage cues, no clean hospital room, no pristine dental-clinic lighting, no lonely human doctor in a white coat, no desk, no bench, no crate, and no lone gadget hero prop.",
            "framing": "wide cover-energy garage-clinic triage shot with strong diagonal composition, the reclined runner crossing the lower-middle frame, the ork streetdoc leaning in from one side, a second support figure on the opposite edge, dense foreground clutter in both lower corners, overhead work lights, and deep background tool storage visible together; no portrait crop, no hallway symmetry, and no empty negative-space void",
            "avoid": "extreme face crop, alley crate posing, alley corridor, desk glamour, storefront windows, neon words, menu boards, seated table pose, close portrait framing, side-profile portrait, phone glamour close-up, handheld slate, card close-up, paper in hand, bright screens, glowing panels, framed boards, front-facing paper strips, long receipt paper, waist-height counters, benches, tabletops, pristine hospital tiles, clean white medical showroom, a lone clean human doctor in a white coat, a human patient, a clean-shaved patient, soft watercolor blur, broad painterly smearing, chest labels, sleeve patches, badge plates, a lone gadget becoming the hero prop, a single-person dim bay still, a back-facing idle pair, hallway symmetry, a quiet low-density mood still, or a clean suburban clinic",
            "overlay_hint": "medscan attribute rail anchors, cyberlimb calibration cues, wound stabilization, neural-link resync, and subsystem fit brackets",
            "props": ["tool chest", "med-gel", "injector tray", "cyberware part", "ammo tray", "prep chair", "magical focus", "six-sided dice"],
            "overlays": ["BOD rail", "AGI rail", "REA rail", "STR rail", "ESS state", "EDGE readout", "cyberlimb calibration", "wound stabilized"],
            "visual_motifs": ["garage clinic grime", "streetdoc assist", "attribute rail", "triage action", "runner life", "cyberware surgery", "medscan posture"],
            "overlay_callouts": ["BOD", "AGI", "REA", "STR", "ESS", "EDGE", "UPGRADING", "CYBERLIMB CALIBRATION", "WOUND STABILIZED", "NEURAL LINK RESYNC"],
            "providers": ["browseract_prompting_systems", "media_factory", "onemin", "browseract_magixai", "magixai"],
        },
        "assets/hero/poc-warning.png": {
            "preferred": "street_front",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Treat this as a dangerous concept warning in the world: a sealed crate, shuttered kiosk, or alley-side warning surface, not a desk still life with readable labels.",
            "subject": "a suspicious concept crate or warning package left where a curious runner could still find it",
            "environment": "a rain-slick alley threshold or shuttered street-front kiosk with hazard tape and hard practical light",
            "action": "warning the viewer that almost nothing here should be mistaken for dependable software",
            "mood": "tense, cautionary, and dry",
            "replace_visual_prompt": "A sealed concept warning case or barricade block abandoned at a shuttered street-front kiosk in the rain, hazard tape and hard practical light, tactile and believable. The object may carry one torn triangle glyph, stripe bands, or abstract hazard pictograms, but never a label plate, poster, engraved plate, stencil word, or readable warning text. Do not print the word warning anywhere. Keep the object scarred and lived-in, not a clean product-shot cube. No desk still life.",
            "avoid": "readable warning labels, the word warning, crate nameplates, poster text, pseudo-branding, stencil words, engraved plates, desk still life, or a clean product-shot cube",
            "overlay_hint": "subtle hazard glyphs and provenance traces",
            "providers": ["browseract_prompting_systems", "media_factory", "onemin", "browseract_magixai", "magixai"],
        },
        "assets/pages/what-chummer6-is.png": {
            "required": "review_bay",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Make this feel like trust being assembled from physical traces, not another person staring at a device.",
            "subject": "one runner deciding whether a ruling becomes trustworthy because the trace survives inspection in the open",
            "environment": "a cramped standing review bay with a vertical trace rail, clipped translucent markers, stamped chips, and one glowing evidence seam",
            "metaphor": "trust assembled from visible traces instead of trust-me math",
            "replace_visual_prompt": "One runner at a cramped standing review bay, upper torso and both hands visible while translucent markers, stamped chips, gear tokens, and cause bands are pegged onto a vertical trace rail under hard practical light. Trust is assembled from physical traces in the open, not from paper receipts or a glowing device. Use translucent plastic markers, chips, bands, and rail clips instead of notes, paper, or monitor screens. No readable text, no handwritten cards, and no loose printed sheets.",
            "avoid": "paper receipts with printed lines, handheld paper cards, loose slips, readable forms, pinned handwritten notes, glowing room numbers, glowing handhelds, wall monitors, or a desk spread",
            "overlay_hint": "rule-source provenance tags, trust arrows, and receipt traces",
            "providers": ["browseract_prompting_systems", "media_factory", "onemin", "browseract_magixai", "magixai"],
        },
        "assets/pages/where-to-go-deeper.png": {
            "required": "archive_room",
            "banned": TABLEAU_COMPOSITIONS | {"desk_still_life"},
            "prompt_nudge": "Treat go-deeper like an archive descent or evidence room, not a desk meeting and not a green-screen nostalgia shot.",
            "subject": "a reader tracing one question deeper through archive shelves and hanging tags",
            "environment": "a dim archive aisle with binders, drawers, hanging evidence tags, and shelf rails",
            "metaphor": "follow the source trail deeper into the stacks",
            "replace_visual_prompt": "A narrow archive aisle with drawer towers, sealed canisters, hanging translucent sleeves, shelf rails, and one reader tracing a source deeper into the stacks while standing; shelves and drawer fronts dominate. Use unlabeled containers, plastic sleeves, and hardware pulls instead of binders, paper fronts, or note cards. No desk spread, no CRT hero prop, no paper layout, and no front-facing monitor.",
            "avoid": "desk spreads, seated desk posture, front-facing monitor text, loose paper map spreads, binder spines, label tabs, shelf cards, or a lone CRT taking over the scene",
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/pages/start-here.png": {
            "required": "transit_checkpoint",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Start-here should feel like choosing a route through the mess, not staring at a kiosk or billboard.",
            "subject": "one runner choosing the next useful lane through a rough public threshold",
            "environment": "a rain-dark checkpoint split with route arrows, lane marks, barrier posts, and grounded wayfinding cues",
            "metaphor": "choose one useful lane through the mess",
            "replace_visual_prompt": "A rain-dark checkpoint split where one runner chooses between rough but useful lanes marked by floor arrows, barrier posts, lane paint, hazard pylons, and grounded route cues. The scene should read as navigation through a concept-stage mess, not a kiosk interaction or wall-reading moment. No public terminal, no menu board, no poster wall, no giant route sign, and no readable text.",
            "avoid": "kiosk, ATM, public terminal, menu board, billboard, poster wall, giant route sign, wall-sized text mark, or readable text",
            "overlay_hint": "lane brackets and route markers",
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/pages/current-status.png": {
            "preferred": "street_front",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Show one fragile public trace surviving in the wild, not another heroic phone close-up and not a triumphant usable-build shot.",
            "subject": "one host or operator checking whether a fragile public trace still clings to a physical public shelf",
            "environment": "a rain-streaked public notice niche or shuttered parcel shelf with taped artifacts, scratched glass, and too much uncertainty",
            "action": "checking whether the visible trace is still there by luck rather than by support, without any device becoming the hero",
            "metaphor": "a fragile public trace surviving mostly by luck",
            "mood": "fragile, honest, and uncertain",
            "replace_visual_prompt": "At a rain-streaked public notice niche or shuttered parcel shelf, one operator stands half in frame while weak public traces cling to taped artifact strips, scratched glass, and small abstract status glows buried inside the physical shelf. The environment must dominate over any electronics. Use abstract marks and residue instead of posters or printed portraits. No handheld device, no giant panel, no heroic screen, no dashboard wall, and no readable text. Wet reflections everywhere.",
            "framing": "medium-wide standing street shot with the physical public shelf or notice niche clearly visible and no dominant overhead sign, wall display, or handheld",
            "overlay_hint": "faint provenance traces, weak receipt halos, and fragile target brackets",
            "avoid": "phone glamour close-up, tablet in hand, giant overhead sign, billboard, glowing wall panel, dashboard wallpaper, public monitor, printed portrait poster, flyer wall, or triumphant product hero shot",
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/pages/public-surfaces.png": {
            "required": "city_edge",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Use a real-world public-surface scene in a bare utility threshold, but keep it physical and environmental. This is not another person holding a tablet and not another storefront sign.",
            "subject": "one runner passing a cluster of rough public traces that survive across physical surfaces",
            "environment": "a concrete underpass threshold with exposed conduit, scratched utility windows, taped notice pockets, route tiles, and wet floor reflections",
            "metaphor": "rough traces surviving across walls, shelves, and thresholds",
            "replace_visual_prompt": "A concrete underpass threshold where several rough public traces survive across physical surfaces: scratched utility windows, taped notice pockets, seal strips, route tiles, and small abstract glows embedded in the wall. One runner passes through the scene standing up, but no device is in their hands and no single panel becomes the composition anchor. No storefront sign, no desk, no readable UI text, no wall placards, and no monitor bank.",
            "avoid": "desk surfaces, seated desk posture, handheld tablet, pocket device glamour, readable storefront signs, OPEN signs, shop windows, wall placards, neat monitor triptychs on a counter, or screen layouts dominated by text lines",
            "overlay_hint": "cross-surface state echoes and route markers",
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/pages/horizons-index.png": {
            "required": "horizon_boulevard",
            "banned": TABLEAU_COMPOSITIONS,
            "person_count_target": "plurality_optional",
            "prompt_nudge": "Make this a dense market of futures and districts, not an icon corridor, menu sign, kiosk, or text-heavy centerpiece. The image should feel like several Shadowrun lanes worth clicking right now, with multiple differentiated branches, crowds or vehicle traces, street-level cyberpunk clues, and visible pressure, not a fake UI billboard or a quiet empty road.",
            "subject": "a branching Shadowrun future where several practical lanes peel outward into distinct possible directions",
            "environment": "a rain-dark district splice where wet streets, elevated ramps, tunnel mouths, market edges, maintenance gantries, branching corridors, route pylons, cable halos, and differentiated lane clutter collide instead of clean storefront facades",
            "action": "asking which future lane could carry the work next without pretending any of them are already finished",
            "metaphor": "future lanes branching without promise",
            "replace_visual_prompt": "16:9 cover-energy futures crossroads for a grounded cyberpunk-fantasy guide page. Show a rain-dark district splice where several practical Shadowrun lanes peel outward into distinct domains: a streetdoc alley washed in work-lamp amber, a dossier stair with clipped packets, a cobalt relay street with hanging cables, a tactical route with ghosted threat markers, and an industrial approval lane with diff-strip glow. The frame must feel packed, branching, and graphic rather than empty. Lane identity must come from prop silhouettes, color bands, wet street texture, tram wires, barrier clutter, partial crowds, vehicle traces, puddle reflections, and diegetic overlays instead of storefront signs, kiosks, glowing rectangles, or readable boards. No centered figure, no single corridor vanishing point, no overhead sign, no billboard centerpiece, and no one road carrying the whole idea.",
            "framing": "wide environment-first district splice with at least four distinct branch directions visible, multiple differentiated clue clusters, partial crowd or vehicle presence, strong diagonal lane flow, and no dominant central sign, glowing rectangle, kiosk, storefront, solitary figure, or single corridor vanishing point",
            "avoid": "central menu sign, kiosk, placard wall, readable signboard, storefront directory, neon words, overhead billboards, lone centered silhouette, text rectangles, glowing panels, shopfront facades, a single text-heavy centerpiece, a single corridor vanishing point, sparse interchange, or an empty road ambience with one symbol",
            "overlay_hint": "future-lane markers, district callout arcs, contingent route brackets, threat-posture overlays, and faction/domain clue bands",
            "props": ["branching ramps", "tram wires", "floor arrows", "hazard pylons", "cable halos", "district clutter"],
            "overlays": ["future-lane brackets", "route halos", "threat ghosts", "branch markers", "district arcs", "domain clue bands"],
            "visual_motifs": ["branching ramps", "future lanes", "district pressure", "stacked route choices", "street-level cyberpunk clues"],
            "overlay_callouts": ["route branch", "future lane", "threat drift", "district split"],
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/parts/core.png": {
            "required": "review_bay",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Core should feel like a standing proof rail where modifiers and consequences get cross-checked in the open. No macro dice glamour, no tray close-up, and no tabletop ritual shot.",
            "metaphor": "visible cause and effect at the rules rail",
            "replace_visual_prompt": "One rules referee at a standing proof rail in a cramped review bay, upper torso and both hands visible while wound chips, recoil bands, clipped tags, and cause-and-effect markers are pegged onto a vertical trace surface under hard practical light. The ruling trace must live on the rail and in the posture, not in a tray, receipt slip, tabletop, or macro prop still. Use clipped markers, bands, and rail slots instead of paper or cards. No readable text.",
            "framing": "medium shot with upper torso, both hands, and the standing proof rail visible together",
            "avoid": "macro dice close-up, isolated chip glamour, receipt slip hero prop, tabletop tray, abstract x-ray overlay with no operator, face-only portrait, paper card, or a horizontal desk surface dominating the frame",
            "overlay_hint": "cause-and-effect traces, receipt markers, and posture brackets",
        },
        "assets/parts/ui.png": {
            "preferred": "mirror_split",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "UI should feel like a runner building and inspecting across real surfaces in motion, not another glowing screen composition.",
            "replace_visual_prompt": "A runner stands inside a compact mirror-split review nook, moving build cards and component tags between a vertical inspection mirror, a clipped hanging slate frame, and a rugged side rail so the shared logic is visible through posture and props rather than screens. No laptop, no desk spread, no giant monitor, and no readable text.",
            "framing": "show the vertical inspection mirror, the clipped side rail, and the operator body language clearly in one frame",
            "avoid": "laptop-on-desk framing, framed wall posters with readable text, generic terminal wallpaper, x-ray body screen, or any dominant glowing monitor",
            "overlay_hint": "build-state deltas and inspection brackets",
        },
        "assets/parts/mobile.png": {
            "required": "platform_edge",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Anchor this around one runner catching the live trace in motion at a platform edge or station choke point, not a posed group and not a handheld glamour shot.",
            "replace_visual_prompt": "A runner threads through a crowded station edge while recovering the live session trace mid-stride; platform markers, crowd rail, route arrows, and motion pressure are obvious; any commlink stays secondary and partially obscured while the human movement and station geometry carry the frame. No readable text and no device close-up.",
            "overlay_hint": "signal halos, reconnect markers, and route-weighting brackets",
        },
        "assets/parts/hub.png": {
            "required": "service_rack",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Hosted coordination should read as racks, relay seams, and remote presence traces, not a seated operator at a big screen.",
            "subject": "one remote operator moving through a rack corridor while hosted state keeps several rough lanes aligned",
            "environment": "a narrow service-rack corridor with relay lights, hanging tags, cable gutters, and mirrored access seams",
            "replace_visual_prompt": "A narrow service-rack corridor with relay lights, hanging tags, cable gutters, mirrored access seams, and one remote operator moving through the aisle while hosted state stays aligned across the hardware. The racks and seams must dominate over any screen. No seated keyboard posture, no giant monitor, no dashboard wall, no readable jacket logo, and no handheld slate as the hero prop.",
            "framing": "medium-wide aisle shot with racks on both sides and the operator moving through the corridor",
            "avoid": "seated terminal posture, giant monitor, keyboard hero shot, dashboard wall, generic SOC screen room, readable jacket logo, or handheld slate glamour",
            "overlay_hint": "relay seams, hosted-state brackets, and remote presence pings",
        },
        "assets/parts/ui-kit.png": {
            "required": "mirror_split",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Shared chrome should show up across real surfaces in motion, not just swatches on a desk or macro UI texture shots.",
            "metaphor": "one language stretched across several real surfaces",
            "replace_visual_prompt": "A compact interface workshop where one designer is clearly present, adjusting component tokens, material chips, and badge plates across a vertical review board, a clipped component rail, and a hanging sample frame so all three surfaces visibly share the same language. No monitors, no desk glamour, no abstract x-ray UI shot, and no readable design docs.",
            "avoid": "monitor-on-desk trope, paired monitors, readable design docs, or a single framed UI mockup taking over the whole image",
            "overlay_hint": "component echoes and shared-state alignment markers",
        },
        "assets/parts/hub-registry.png": {
            "required": "archive_room",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Registry should feel like intake and judgment in a real archive lane, not a stack of props on a desk.",
            "replace_visual_prompt": "An archive-style intake lane with bins, scanners, hanging tags, and one registrar visibly standing in frame while deciding where a rough artifact belongs; shelves and intake rails beat desk glamour, no readable forms, no close-up of a hand touching one device.",
            "overlay_hint": "intake stamps and compatibility bands",
        },
        "assets/parts/media-factory.png": {
            "required": "render_lane",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Media Factory should read as one operator pushing a rough packet through a vertical render lane with provenance still attached, not an abstract printer close-up or empty hardware still life.",
            "replace_visual_prompt": "One operator inside a vertical render lane, surrounded by output racks, hanging proofs, approval rails, and monitor spill while a rough packet moves toward publishable shape; the operator is clearly visible, the lane feels mechanical and real, and the scene is not just a macro machine detail or a print bench duplicate.",
            "framing": "vertical-lane medium shot with the operator, racks, proofs, and approval rails all visible together",
            "avoid": "empty printer glamour, abstract machine macro, isolated hands on buttons, or readable page fronts",
            "overlay_hint": "publication-path arrows, provenance seals, and approval bands",
        },
        "assets/horizons/nexus-pan.png": {
            "required": "van_interior",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Anchor the shot around one reconnecting operator inside a van or rig interior; the rest of the table can stay implied off-frame, but this is not a phone close-up or cafe drift shot.",
            "subject": "one reconnecting operator bringing a dropped device back into the session",
            "environment": "a rain-streaked van interior with a live relay deck, cable bundle, and one battered secondary session surface",
            "metaphor": "reconnection under noise inside a rig",
            "replace_visual_prompt": "A reconnecting rigger inside a rain-streaked van interior, upper body clearly visible while both hands patch a commlink mesh back into a relay deck, cable bundle, and battered secondary session surface fixed into the van wall. Any handheld must stay buried and secondary, not raised toward camera. Center the operator and the van environment, not a gadget. No readable screens.",
            "avoid": "close-up of fingers on a phone, neutral tablet portrait, cropped gadget glamour, or a handheld lifted into the foreground",
            "overlay_hint": "signal halos, route weighting arcs, and posture brackets",
        },
        "assets/horizons/alice.png": {
            "required": "simulation_lab",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "This horizon belongs in a sim bench or crash lab, never another social huddle and never a giant failure screen with a readable verdict word.",
            "replace_visual_prompt": "A deterministic crash lab or sim bench where one operator studies a projected mannequin silhouette, branching hazard arcs, and outcome ghosts around a test lane. The risk should be obvious through branching light, posture, and silhouettes, not through a giant result word, lab screen, or report panel. No readable text, no FAIL sign, and no glass-wall status board.",
            "avoid": "giant result word, FAIL sign, wall display, lab report panel, glass booth signage, or a neutral human bust behind glass",
        },
        "assets/horizons/jackpoint.png": {
            "required": "archive_room",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "Make this feel like a dead-drop dossier lane or evidence archive, not another desk scene.",
            "metaphor": "dead-drop provenance assembled from shelves and sleeves",
            "replace_visual_prompt": "A fixer in a narrow archive drop lane, torso and one arm visible while dead-drop packets, translucent sleeves, evidence chips, coded tabs, and sealed dossier canisters are pulled from shelves and hanging slots into a usable packet. Shelves, bins, lockers, and drop hardware must dominate over any desk surface. No readable forms, no front-facing papers, and no centered data-slab glamour.",
            "overlay_hint": "provenance stamps and dossier anchors",
        },
        "assets/horizons/details/jackpoint-scene.png": {
            "required": "prop_detail",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "This detail should show dead-drop hardware and dossier props, not a readable envelope or desk memo.",
            "replace_visual_prompt": "Tight prop-led dead-drop detail: gloved hands, sealed sleeves, evidence chips, locking tabs, and a half-open archive slot under rain-streaked light. No front-facing paper, no envelope text, and no desk memo.",
            "avoid": "readable envelope text, front-facing notes, typed paper, or a clean office desk",
            "overlay_hint": "dossier anchors and provenance marks",
        },
        "assets/horizons/karma-forge.png": {
            "required": "approval_rail",
            "banned": TABLEAU_COMPOSITIONS,
            "person_count_target": "duo_preferred",
            "prompt_nudge": "Make governed rules evolution legible at a glance, not literal blacksmith cosplay, not forge-hands wallpaper, and not two people doing paperwork at a table. This should feel dense, graphic, dangerous, and high-pressure, with obvious approval, rollback, provenance, consequence, and compatibility logic in the frame. Prefer a standing rulesmith plus reviewer or witness in motion over one isolated operator or any seated tableau.",
            "subject": "a standing rulesmith and skeptical reviewer reconciling a volatile house-rule pack through review, diff, rollback, and consequence pressure",
            "environment": "an improvised industrial rules lab built around an approval rail, rollback rig, provenance seals, rule cassettes, consequence chutes, diff strips, compatibility halos, and heat-scored control hardware under hard sodium spill",
            "action": "the rulesmith drives diff controls and cassette clamps while a reviewer leans into the approval rail and rollback rig under visible pressure, witness locks, consequence markers, and compatibility arcs",
            "metaphor": "governed rules evolution under approval and rollback pressure",
            "replace_visual_prompt": "16:9 illustrated flagship horizon cover poster inside an improvised industrial rules lab. A standing rulesmith and skeptical reviewer work at an approval rail, rollback rig, and consequence chamber while they reconcile a volatile house-rule pack through color-banded diff strips, stamped approval cards, rule cassettes, provenance seals, consequence markers, compatibility arcs, witness locks, and visible control hardware under hard sodium spill and cyan overlay rails. The frame must immediately sell governed rules evolution for a Shadowrun table: approval, rollback, provenance, consequence, danger, and bounded experimentation all need to be legible before anyone reads a caption. Keep both people standing and engaged with rails, clamps, cassette housings, and diff controls rather than holding papers or cards toward camera. Show both torsos and the control hardware together with stronger mythic poster energy, not anonymous forge hands over flame, not one isolated operator in a glow void, and not two people sitting at a workbench doing paperwork. Use abstract diff bars, chips, seal bands, cassette housings, clipped approval tabs, and smartlink-like overlay traces instead of pages, printouts, or glowing text sheets. This is not a literal blacksmith shop, not a seated bench-table moment, not a calm workshop, and not generic glowing-card tinkering. No readable labels.",
            "framing": "medium-wide two-person standing shot with both torsos, active hands on hardware, approval rails, diff strips, rollback rig hardware, witness locks, and several layered control cues visible together; not a face crop, not anonymous hand macro, and not a quiet sparse bench still",
            "avoid": "literal medieval forge cliché, anonymous blacksmith close-up, generic fire-and-anvil shot, forge hands over flame, handheld slate glamour, tablet close-up, page-with-text hero prop, glowing text sheet, loose paper stack, paper held in hand, generic card tinkering, sparse desk still life, one operator at a console, two people sitting at a table, generic paperwork workshop, or any scene without publication-control cues",
            "overlay_hint": "approval rails, provenance seals, rollback vectors, witness locks, compatibility arcs, and consequence-path anchors",
            "props": ["diff strips", "approval cards", "rollback cassettes", "provenance rails", "seal bands", "control markers", "witness locks", "consequence nodes"],
            "overlays": ["compatibility arcs", "diff markers", "approval seals", "rollback arcs", "control brackets", "consequence nodes", "witness locks"],
            "visual_motifs": ["rules lab", "rollback rig", "approval pressure", "controlled experimentation", "review witness", "consequence chamber"],
            "overlay_callouts": ["DIFF", "APPROVAL", "PROVENANCE", "ROLLBACK", "COMPATIBILITY ARC", "WITNESS LOCK", "REVERT COST"],
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/horizons/runsite.png": {
            "required": "district_map",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Make this feel like ingress planning over real space, not another person staring at a tablet.",
            "subject": "a rigger plotting ingress lanes across a projected floor plan in the field",
            "environment": "a rain-slick loading dock and alley staging point with stacked crates, chalk marks, and one ghosted building outline",
            "metaphor": "ingress planning across real space instead of a slab",
            "replace_visual_prompt": "A rigger in a rain-slick loading dock and alley staging point traces ingress cones, threat silhouettes, and a ghosted building layout across wet concrete, wall seams, and stacked crate edges. The planning surface lives in the world around the operator, not on a readable tablet screen or tabletop hologram slab.",
            "avoid": "tabletop hologram slab, readable tablet screen, kneeling over a crate as if it were a desk, or any single flat planning surface taking over the frame",
            "overlay_hint": "ingress cones, threat-posture marks, and ghost-lane overlays",
        },
        "assets/horizons/runbook-press.png": {
            "required": "proof_room",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Make this feel like a proof room and print rail under revision pressure, not a stack of dossiers or a readable front page.",
            "subject": "a campaign writer pushing rough district material through a cramped proof room",
            "environment": "a narrow proof room with rollers, map drawers, clipped proof strips, and a lit print rail",
            "metaphor": "rough source material pushed through a cramped proof lane",
            "replace_visual_prompt": "A narrow proof room with ink rollers, map drawers, clipped proof strips, a lit print rail, and one campaign writer moving fresh district material through the mechanism; tactile and alive, no front-facing page, no loose sheet held toward camera, no readable headline, and no newspaper-like masthead.",
            "framing": "oblique angle across the print rail, rollers, map drawers, and the writer moving through the room; the proof hardware dominates, not a held-up sheet",
            "avoid": "newspaper mastheads, readable page headlines, front-facing sheets, centered poster samples, or someone presenting a printed page to camera",
            "overlay_hint": "layout marks and route-callout arrows",
        },
        "assets/pages/parts-index.png": {
            "required": "district_map",
            "banned": TABLEAU_COMPOSITIONS | STATIC_DESK_COMPOSITIONS,
            "prompt_nudge": "Parts index should read like a walkable map of work zones, not an expo floor of kiosks and not a central planning table.",
            "subject": "the Chummer parts expressed as distinct work zones across one walkable room",
            "environment": "an open backroom warehouse floor with hanging cables, grounded prop islands, rail clusters, bins, and color-lit lanes crossing the concrete",
            "metaphor": "a walkable map of work zones instead of a menu",
            "replace_visual_prompt": "An open backroom warehouse floor where each Chummer part appears as its own grounded work zone: a standing proof rail cluster, a mirror-split inspection nook, a mobile route checkpoint, a registry intake rail, a service-rack corridor slice, and a media render lane, all connected by floor-route lines, cable paths, and subtle color bands across concrete. Treat it as an environment map first. Keep human figures minimal or absent. There are no kiosks, no terminal banks, no giant screens, no wall signs, no floating labels, no lightboxes, no title banner, and no central table. This must read like a walkable room map, not a fake expo hall or poster diagram.",
            "framing": "wide room view with multiple distinct physical work zones visible at once and route lines connecting them across the concrete",
            "avoid": "top-down tabletop composition, central command table, boardgame layout, kiosks, terminal banks, labeled doorways, wall signage, framed station headers, floating labels, title banners, specialist desks, seated operators, neat laptops arranged around one surface, or large human figures posed in the room",
            "overlay_hint": "route lines and district callout pings",
            "providers": ["media_factory", "onemin", "browseract_prompting_systems", "browseract_magixai", "magixai"],
        },
        "assets/horizons/table-pulse.png": {
            "required": "forensic_replay",
            "banned": TABLEAU_COMPOSITIONS,
            "prompt_nudge": "TABLE PULSE should feel like replaying the run after hours, not another neutral person-with-tablet portrait.",
            "replace_visual_prompt": "After the run, a tired orc GM sits alone in a booth with cooling soykaf while translucent heat paths, threat pulses, and session echoes bloom above physical tokens, cups, and a pushed-aside device; intimate, exhausted, and lived-in, with the replay living in the room instead of as a device close-up; no readable screens.",
            "avoid": "neutral tablet portrait, phone glamour, or clean desk scene",
            "overlay_hint": "replay heat paths and consequence echoes",
        },
    }
    adjacency_fallbacks = {
        "archive_room": "street_front",
        "clinic_intake": "street_front",
        "dossier_desk": "desk_still_life",
        "horizon_boulevard": "city_edge",
        "over_shoulder_receipt": "solo_operator",
        "platform_edge": "solo_operator",
        "proof_room": "archive_room",
        "render_lane": "archive_room",
        "review_bay": "mirror_split",
        "service_rack": "archive_room",
        "simulation_lab": "solo_operator",
        "solo_operator": "street_front",
        "street_front": "over_shoulder_receipt",
        "transit_checkpoint": "solo_operator",
        "van_interior": "solo_operator",
        "workshop_bench": "service_rack",
    }

    def scene_policy_for_target(target: str) -> dict[str, object]:
        return dict(target_scene_policies.get(target) or {})

    def planned_scene_row(target: str, row: dict[str, object]) -> dict[str, str]:
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        return {
            "target": target,
            "composition": str(contract.get("composition") or "").strip(),
            "subject": str(contract.get("subject") or "").strip(),
        }

    def repair_media_row(target: str, row: dict[str, object], planned_rows: list[dict[str, str]]) -> tuple[dict[str, object], list[str]]:
        cleaned = copy.deepcopy(row)
        policy = scene_policy_for_target(target)
        visual_contract = target_visual_contract(target)
        banned = {str(entry).strip() for entry in policy.get("banned", set()) if str(entry).strip()}
        required = str(policy.get("required") or "").strip()
        preferred = str(policy.get("preferred") or required or "").strip()
        contract = cleaned.get("scene_contract") if isinstance(cleaned.get("scene_contract"), dict) else {}
        contract = dict(contract)
        notes: list[str] = []

        composition = str(contract.get("composition") or "").strip()
        if not composition:
            composition = preferred or "solo_operator"
            notes.append(f"scene_plan_audit:missing_composition->{composition}")
        if composition in banned and preferred and composition != preferred:
            notes.append(f"scene_plan_audit:{composition}->{preferred}")
            composition = preferred
        if required and composition != required:
            notes.append(f"scene_plan_audit:required:{composition}->{required}")
            composition = required

        tableish_count = sum(
            1
            for planned in planned_rows
            if str(planned.get("composition") or "").strip() in TABLEAU_COMPOSITIONS
        )
        if composition in TABLEAU_COMPOSITIONS and tableish_count >= 1:
            fallback = preferred or adjacency_fallbacks.get(composition) or "solo_operator"
            if fallback in TABLEAU_COMPOSITIONS:
                fallback = "solo_operator"
            if fallback != composition:
                notes.append(f"whole_pack_audit:table_monoculture:{composition}->{fallback}")
                composition = fallback

        if planned_rows:
            previous = str(planned_rows[-1].get("composition") or "").strip()
            if previous and composition == previous:
                fallback = preferred or adjacency_fallbacks.get(composition) or ""
                if fallback and fallback != composition:
                    notes.append(f"whole_pack_audit:adjacent_repeat:{composition}->{fallback}")
                    composition = fallback

        contract["composition"] = composition
        if visual_contract:
            cleaned["visual_contract"] = dict(visual_contract)
            for field in ("density_target", "overlay_density", "negative_space_cap", "flash_level"):
                value = str(visual_contract.get(field) or "").strip()
                if value:
                    contract[field] = value
            person_count_target = str(visual_contract.get("person_count_target") or policy.get("person_count_target") or "").strip()
            if person_count_target:
                contract["person_count_target"] = person_count_target
            anchors = _string_list(visual_contract.get("must_show_semantic_anchors"))
            if anchors:
                contract["must_show_semantic_anchors"] = anchors
            blockers = _string_list(visual_contract.get("must_not_show"))
            if blockers:
                contract["must_not_show"] = blockers
            if not _boolish(visual_contract.get("humor_allowed"), default=True):
                contract["humor_policy"] = "forbid"
            if not _boolish(visual_contract.get("pseudo_text_allowed"), default=True):
                contract["pseudo_text_allowed"] = False
        for key in ("subject", "environment", "action", "metaphor", "mood"):
            replacement = str(policy.get(key) or "").strip()
            if replacement:
                contract[key] = replacement
        for key in ("props", "overlays"):
            value = policy.get(key)
            if isinstance(value, (list, tuple)):
                contract[key] = [str(entry).strip() for entry in value if str(entry).strip()]
        palette_override = policy.get("palette")
        if palette_override not in (None, ""):
            contract["palette"] = palette_override
        cast_target = str(contract.get("person_count_target") or policy.get("person_count_target") or "").strip().lower()
        cast_signature = infer_cast_signature(contract)
        if cast_target in {"duo_or_team", "duo_preferred"} and cast_signature == "solo":
            replacement_subject = str(policy.get("subject") or "").strip()
            if replacement_subject:
                contract["subject"] = replacement_subject
            replacement_action = str(policy.get("action") or "").strip()
            if replacement_action:
                contract["action"] = replacement_action
            notes.append(f"scene_plan_audit:cast_density:solo->{cast_target}")
        cleaned["scene_contract"] = contract

        prompt_nudge = str(policy.get("prompt_nudge") or "").strip()
        replace_visual_prompt = str(policy.get("replace_visual_prompt") or "").strip()
        replace_overlay_hint = str(policy.get("overlay_hint") or "").strip()
        replace_visual_motifs = policy.get("visual_motifs")
        replace_overlay_callouts = policy.get("overlay_callouts")
        if prompt_nudge:
            visual_prompt = str(cleaned.get("visual_prompt") or "").strip()
            if prompt_nudge.lower() not in visual_prompt.lower():
                cleaned["visual_prompt"] = f"{prompt_nudge} {visual_prompt}".strip()
        if replace_visual_prompt:
            cleaned["visual_prompt"] = replace_visual_prompt
        if replace_overlay_hint:
            cleaned["overlay_hint"] = replace_overlay_hint
        if isinstance(replace_visual_motifs, (list, tuple)):
            cleaned["visual_motifs"] = [str(entry).strip() for entry in replace_visual_motifs if str(entry).strip()]
        if isinstance(replace_overlay_callouts, (list, tuple)):
            cleaned["overlay_callouts"] = [str(entry).strip() for entry in replace_overlay_callouts if str(entry).strip()]
        if notes:
            cleaned["scene_audit"] = list(notes)
        return cleaned, notes

    def audit_specs(specs_in: list[dict[str, object]]) -> list[dict[str, object]]:
        planned_rows = [dict(row) for row in recent_rows]
        audited_specs: list[dict[str, object]] = []
        for spec in specs_in:
            target = str(spec.get("target") or "").strip()
            role = str(spec.get("role") or "guide asset").strip()
            row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
            repaired_row, notes = repair_media_row(target, row, planned_rows)
            prompt = render_prompt_from_row(repaired_row, role=role, target=target)
            if notes:
                prompt = prompt + " Pack audit enforcement: " + " ".join(notes)
            audited_spec = dict(spec)
            audited_spec["media_row"] = repaired_row
            audited_spec["prompt"] = prompt
            audited_spec["scene_audit"] = notes
            providers_override = scene_policy_for_target(target).get("providers")
            if isinstance(providers_override, list):
                audited_spec["providers"] = [str(entry).strip().lower() for entry in providers_override if str(entry).strip()]
            audited_specs.append(audited_spec)
            planned_rows.append(planned_scene_row(target, repaired_row))

        compositions = [
            str(
                (
                    (spec.get("media_row") or {}).get("scene_contract")
                    if isinstance((spec.get("media_row") or {}).get("scene_contract"), dict)
                    else {}
                ).get("composition")
                or ""
            ).strip()
            for spec in audited_specs
        ]
        tableish_count = sum(1 for composition in compositions if composition in TABLEAU_COMPOSITIONS)
        surface_heavy_count = sum(1 for composition in compositions if composition in SURFACE_HEAVY_COMPOSITIONS)
        if tableish_count > 1:
            raise RuntimeError(f"whole_pack_audit_failed:table_monoculture:{tableish_count}")
        if surface_heavy_count > 4:
            raise RuntimeError(f"whole_pack_audit_failed:surface_scene_monoculture:{surface_heavy_count}")
        for expected_target, required in (
            ("assets/hero/chummer6-hero.png", "clinic_intake"),
            ("assets/pages/horizons-index.png", "horizon_boulevard"),
            ("assets/parts/ui.png", "mirror_split"),
            ("assets/parts/mobile.png", "platform_edge"),
            ("assets/parts/media-factory.png", "render_lane"),
            ("assets/horizons/alice.png", "simulation_lab"),
            ("assets/horizons/jackpoint.png", "archive_room"),
            ("assets/horizons/karma-forge.png", "approval_rail"),
            ("assets/horizons/nexus-pan.png", "van_interior"),
            ("assets/horizons/runbook-press.png", "proof_room"),
        ):
            match = next((spec for spec in audited_specs if str(spec.get("target") or "") == expected_target), None)
            if not isinstance(match, dict):
                continue
            contract = match.get("media_row") if isinstance(match.get("media_row"), dict) else {}
            scene_contract = contract.get("scene_contract") if isinstance(contract.get("scene_contract"), dict) else {}
            composition = str(scene_contract.get("composition") or "").strip()
            if composition != required:
                raise RuntimeError(f"whole_pack_audit_failed:{expected_target}:{composition or 'missing'}!={required}")
        return audited_specs

    hero_row = apply_visual_override("assets/hero/chummer6-hero.png", hero_override)
    specs: list[dict[str, object]] = [
        {
            "target": "assets/hero/chummer6-hero.png",
            "role": "landing hero",
            "prompt": render_prompt_from_row(hero_row, role="landing hero", target="assets/hero/chummer6-hero.png"),
            "width": 960,
            "height": 540,
            "media_row": hero_row,
            "style_epoch": style_epoch,
            "providers": provider_order(),
        },
        page_spec(target="assets/hero/poc-warning.png", page_id="readme", role="POC warning shelf", composition_hint="street_front"),
        page_spec(target="assets/pages/start-here.png", page_id="start_here", role="start-here banner", composition_hint="transit_checkpoint"),
        page_spec(target="assets/pages/what-chummer6-is.png", page_id="what_chummer6_is", role="what-is banner", composition_hint="review_bay"),
        page_spec(target="assets/pages/where-to-go-deeper.png", page_id="where_to_go_deeper", role="deeper-dive banner", composition_hint="archive_room"),
        page_spec(target="assets/pages/current-phase.png", page_id="current_phase", role="current-phase banner", composition_hint="workshop"),
        page_spec(target="assets/pages/current-status.png", page_id="current_status", role="current-status banner", composition_hint="street_front"),
        page_spec(target="assets/pages/public-surfaces.png", page_id="public_surfaces", role="public-surfaces banner", composition_hint="city_edge"),
        page_spec(target="assets/pages/parts-index.png", page_id="parts_index", role="parts-overview banner", composition_hint="district_map"),
        page_spec(target="assets/pages/horizons-index.png", page_id="horizons_index", role="horizons boulevard banner", composition_hint="horizon_boulevard"),
    ]
    part_overrides = media.get("parts") if isinstance(media, dict) else {}
    for slug, item in CANON_PARTS.items():
        override = part_overrides.get(slug) if isinstance(part_overrides, dict) else None
        if not isinstance(override, dict):
            legacy_slug = LEGACY_PART_SLUGS.get(slug)
            override = part_overrides.get(legacy_slug) if isinstance(part_overrides, dict) and legacy_slug else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            raise RuntimeError(f"missing part visual_prompt in EA overrides: {slug}")
        target = f"assets/parts/{slug}.png"
        row = apply_visual_override(target, override)
        specs.append(
            {
                "target": target,
                "role": f"{slug} part page",
                "prompt": render_prompt_from_row(row, role=f"{slug} part page", target=target),
                "width": 960,
                "height": 540,
                "media_row": row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
    horizon_overrides = media.get("horizons") if isinstance(media, dict) else {}
    for slug, item in CANON_HORIZONS.items():
        override = horizon_overrides.get(slug) if isinstance(horizon_overrides, dict) else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            override = fallback_horizon_media_row(slug, item)
        target = f"assets/horizons/{slug}.png"
        row = apply_visual_override(target, override)
        specs.append(
            {
                "target": target,
                "role": f"{slug} horizon page",
                "prompt": render_prompt_from_row(row, role=f"{slug} horizon page", target=target),
                "width": 960,
                "height": 540,
                "media_row": row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
        detail_target = f"assets/horizons/details/{slug}-scene.png"
        detail_row = dict(row)
        detail_contract = dict(row.get("scene_contract") or {}) if isinstance(row.get("scene_contract"), dict) else {}
        detail_contract["composition"] = "prop_detail"
        detail_contract["subject"] = str(
            detail_contract.get("subject") or "hands and props capturing the horizon promise"
        ).strip() or "hands and props capturing the horizon promise"
        detail_contract["action"] = str(
            detail_contract.get("action") or "captured as a tight scene-detail still with hands, props, and implied dialogue beats"
        ).strip() or "captured as a tight scene-detail still with hands, props, and implied dialogue beats"
        detail_row["scene_contract"] = detail_contract
        detail_nudge = (
            "Scene-detail still: tighter framing, prop-led, hands and gear carry the moment; "
            "avoid wide establishing shots or big group huddles."
        )
        detail_visual_prompt = str(detail_row.get("visual_prompt") or "").strip()
        if detail_visual_prompt:
            if detail_nudge.lower() not in detail_visual_prompt.lower():
                detail_row["visual_prompt"] = f"{detail_nudge} {detail_visual_prompt}".strip()
        else:
            detail_row["visual_prompt"] = detail_nudge
        detail_row = apply_visual_override(detail_target, detail_row)
        specs.append(
            {
                "target": detail_target,
                "role": f"{slug} horizon scene detail",
                "prompt": render_prompt_from_row(detail_row, role=f"{slug} horizon scene detail", target=detail_target),
                "width": 640,
                "height": 360,
                "media_row": detail_row,
                "style_epoch": style_epoch,
                "providers": provider_order(),
            }
        )
    return audit_specs(specs)


def render_specs(*, specs: list[dict[str, object]], output_dir: Path, build_release: bool = False) -> dict[str, object]:
    if not specs:
        raise RuntimeError("no asset specs selected for rendering")
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = load_scene_ledger()
    active_style_epoch = {}
    if specs and isinstance(specs[0].get("style_epoch"), dict):
        active_style_epoch = dict(specs[0].get("style_epoch") or {})
    accepted_rows = scene_rows_for_style_epoch(ledger, style_epoch=active_style_epoch, allow_fallback=False)
    audited_compositions = [
        str(
            (
                (spec.get("media_row") or {}).get("scene_contract")
                if isinstance((spec.get("media_row") or {}).get("scene_contract"), dict)
                else {}
            ).get("composition")
            or ""
        ).strip()
        for spec in specs
    ]
    pack_audit = {
        "tableau_count": sum(1 for composition in audited_compositions if composition in TABLEAU_COMPOSITIONS),
        "surface_heavy_count": sum(1 for composition in audited_compositions if composition in SURFACE_HEAVY_COMPOSITIONS),
        "adjacent_repeat_count": sum(
            1
            for index in range(1, len(audited_compositions))
            if audited_compositions[index] and audited_compositions[index] == audited_compositions[index - 1]
        ),
        "scene_adjustments": [
            {
                "target": str(spec.get("target") or "").strip(),
                "notes": list(spec.get("scene_audit") or []),
            }
            for spec in specs
            if list(spec.get("scene_audit") or [])
        ],
    }

    def _render_spec(spec: dict[str, object]) -> dict[str, object]:
        target = str(spec["target"])
        row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        composition = str(contract.get("composition") or "").strip()
        block_reason = repetition_block_reason(
            target=target,
            composition=composition,
            ledger={"assets": accepted_rows},
            allow_repeat=bool(spec.get("allow_repeat")),
        )
        if block_reason:
            egg_payload = easter_egg_payload(contract)
            return {
                "target": target,
                "output": "",
                "provider": "none",
                "status": f"rejected:{block_reason}",
                "attempts": [f"variation_guard:{block_reason}"],
                "prompt": str(spec.get("prompt") or ""),
                "easter_egg": egg_payload,
            }
        prompt = refine_prompt_with_ooda(prompt=str(spec["prompt"]), target=target)
        prompt = ensure_troll_clause(prompt=prompt, spec=spec)
        width = int(spec.get("width", 1280))
        height = int(spec.get("height", 720))
        out_path = output_dir / target
        out_path.parent.mkdir(parents=True, exist_ok=True)
        variant_attempts = first_contact_variant_count(target=target)
        best_result: dict[str, object] | None = None
        best_statuses: list[str] = []
        best_score = float("-inf")
        best_notes: list[str] = []
        best_gate_failures: list[str] = []
        for variant in range(variant_attempts):
            candidate_path = out_path if variant_attempts == 1 else out_path.with_name(f"{out_path.stem}.__candidate{variant}{out_path.suffix}")
            result = render_with_ooda(prompt=prompt, output_path=candidate_path, width=width, height=height, spec=spec)
            statuses: list[str] = list(result["attempts"])
            statuses.append(normalize_banner_size(image_path=candidate_path, width=width, height=height))
            base_score = 0.0
            base_notes: list[str] = []
            if visual_audit_enabled(target=target):
                base_score, base_notes = visual_audit_score(image_path=candidate_path, target=target)
                statuses.extend(note.replace("visual_audit:", "base_visual_audit:", 1) for note in base_notes)
                statuses.append(f"base_visual_audit:score:{base_score:.2f}")
            if first_contact_target(target):
                statuses.append(apply_first_contact_overlay_postpass(image_path=candidate_path, spec=spec, width=width, height=height))
            if troll_postpass_enabled() and scene_contract_requests_easter_egg(contract):
                statuses.append(apply_troll_postpass(image_path=candidate_path, spec=spec, width=width, height=height))
            score, notes = visual_audit_score(image_path=candidate_path, target=target) if visual_audit_enabled(target=target) else (0.0, [])
            statuses.extend(notes)
            statuses.append(f"visual_audit:score:{score:.2f}")
            gate_failures = critical_visual_gate_failures(
                target=target,
                base_score=base_score,
                base_notes=base_notes,
                final_score=score,
                final_notes=notes,
            )
            statuses.extend(gate_failures)
            candidate_score = score + (base_score * 0.6) - (35.0 * len(gate_failures))
            if candidate_score > best_score:
                best_score = candidate_score
                best_result = {"provider": result["provider"], "status": result["status"], "candidate_path": str(candidate_path)}
                best_statuses = statuses
                best_notes = [*base_notes, *notes]
                best_gate_failures = gate_failures
            if variant_attempts > 1 and candidate_path != out_path and candidate_score < best_score:
                try:
                    candidate_path.unlink()
                except Exception:
                    pass
        if best_result is None:
            raise RuntimeError(f"render_failed_without_candidate:{target}")
        if best_gate_failures:
            raise RuntimeError(f"critical_visual_audit_failed:{target}:{','.join(best_gate_failures[:4])}")
        chosen_path = Path(str(best_result["candidate_path"]))
        if chosen_path != out_path:
            chosen_path.replace(out_path)
        postpass_attempts = best_statuses
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        accepted_rows.append(
            {
                "target": target,
                "composition": composition,
                "cast_signature": infer_cast_signature(contract),
                "subject": str(contract.get("subject") or "").strip(),
                "mood": str(contract.get("mood") or "").strip(),
                "easter_egg_kind": str(contract.get("easter_egg_kind") or "").strip(),
                "provider": str(best_result["provider"]),
                "prompt_hash": prompt_hash,
                "style_epoch": dict(spec.get("style_epoch") or {}) if isinstance(spec.get("style_epoch"), dict) else {},
            }
        )
        egg_payload = easter_egg_payload(contract)
        return {
            "target": target,
            "output": str(out_path),
            "provider": str(best_result["provider"]),
            "status": str(best_result["status"]),
            "attempts": postpass_attempts,
            "prompt": prompt,
            "scene_audit": list(spec.get("scene_audit") or []) + best_notes,
            "easter_egg": egg_payload,
        }
    assets = [_render_spec(spec) for spec in specs]
    render_accounting = build_render_accounting(assets)
    release_build: dict[str, object] = {"status": "skipped", "reason": "not_requested"}
    if build_release:
        release_build = run_release_build_pipeline()
    manifest = {
        "output_dir": str(output_dir),
        "assets": assets,
        "style_epoch": active_style_epoch,
        "pack_audit": pack_audit,
        "render_accounting": render_accounting,
        "release_build": release_build,
    }
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    write_json_file(
        SCENE_LEDGER_OUT,
        {
            "style_epoch": active_style_epoch,
            "assets": accepted_rows,
        },
    )
    STATE_OUT.write_text(
        json.dumps(
            {
                "output": str(output_dir),
                "provider": assets[0]["provider"] if assets else "none",
                "status": f"pack:rendered:{len(assets)}",
                "attempts": [asset["status"] for asset in assets],
                "pack_audit": pack_audit,
                "render_accounting": render_accounting,
                "release_build": release_build,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _attempt_provider(detail: object) -> str:
    cleaned = str(detail or "").strip()
    if ":" not in cleaned:
        return ""
    provider = cleaned.split(":", 1)[0].strip().lower()
    if provider in {
        "normalize_banner_size",
        "troll_postpass",
        "variation_guard",
        "rejected",
        "pack",
        "none",
    }:
        return ""
    return provider


def _attempt_is_billable(detail: object) -> bool:
    cleaned = str(detail or "").strip().lower()
    provider = _attempt_provider(cleaned)
    if not provider:
        return False
    if any(
        token in cleaned
        for token in (
            ":not_configured",
            ":unknown_provider",
            ":forbidden_fallback",
            ":disabled_for_primary_art",
            "legacy_svg_fallback_forbidden",
        )
    ):
        return False
    return True


def build_render_accounting(assets: list[dict[str, object]]) -> dict[str, object]:
    by_provider: dict[str, dict[str, int]] = {}
    per_asset: list[dict[str, object]] = []
    total_attempts = 0
    total_billable_attempts = 0
    for asset in assets:
        target = str(asset.get("target") or "").strip()
        final_status = str(asset.get("status") or "").strip().lower()
        final_provider = str(asset.get("provider") or "").strip().lower()
        attempts = list(asset.get("attempts") or [])
        asset_attempts = 0
        asset_billable = 0
        provider_order: list[str] = []
        for detail in attempts:
            provider = _attempt_provider(detail)
            if not provider:
                continue
            provider_row = by_provider.setdefault(
                provider,
                {
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "estimated_billable_attempts": 0,
                },
            )
            provider_row["attempts"] += 1
            asset_attempts += 1
            total_attempts += 1
            if provider == final_provider and str(detail or "").strip().lower() == final_status:
                provider_row["successes"] += 1
            else:
                provider_row["failures"] += 1
            if _attempt_is_billable(detail):
                provider_row["estimated_billable_attempts"] += 1
                asset_billable += 1
                total_billable_attempts += 1
            provider_order.append(provider)
        per_asset.append(
            {
                "target": target,
                "final_provider": final_provider,
                "render_attempts": asset_attempts,
                "estimated_billable_attempts": asset_billable,
                "attempt_provider_order": provider_order,
            }
        )
    return {
        "asset_count": len(assets),
        "total_render_attempts": total_attempts,
        "estimated_billable_attempts": total_billable_attempts,
        "providers": by_provider,
        "per_asset": per_asset,
        "note": "Estimated billable attempts count provider calls that were actually attempted; it is a burn proxy, not a provider invoice.",
    }


def render_pack(*, output_dir: Path, build_release: bool | None = None) -> dict[str, object]:
    enabled = _release_build_default_for_pack() if build_release is None else bool(build_release)
    return render_specs(specs=asset_specs(), output_dir=output_dir, build_release=enabled)


def render_targets(*, targets: list[str], output_dir: Path, build_release: bool | None = None) -> dict[str, object]:
    wanted = {str(target).strip() for target in targets if str(target).strip()}
    if not wanted:
        raise RuntimeError("no targets requested")
    available = asset_specs()
    selected = [
        spec
        for spec in available
        if str(spec.get("target")) in wanted or Path(str(spec.get("target"))).name in wanted
    ]
    selected = [{**spec, "allow_repeat": True} for spec in selected]
    missing = sorted(
        target
        for target in wanted
        if target not in {str(spec.get("target")) for spec in selected}
        and target not in {Path(str(spec.get("target"))).name for spec in selected}
    )
    if missing:
        raise RuntimeError("unknown render targets: " + ", ".join(missing))
    enabled = _release_build_default_for_targets() if build_release is None else bool(build_release)
    return render_specs(specs=selected, output_dir=output_dir, build_release=enabled)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Chummer6 guide asset through EA provider selection.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("--prompt", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--width", type=int, default=1280)
    render.add_argument("--height", type=int, default=720)
    render_pack_parser = sub.add_parser("render-pack")
    render_pack_parser.add_argument("--output-dir", default="/docker/fleet/state/chummer6/ea_media_assets")
    render_pack_parser.add_argument("--skip-release-build", action="store_true")
    render_targets_parser = sub.add_parser("render-targets")
    render_targets_parser.add_argument("--target", action="append", required=True)
    render_targets_parser.add_argument("--output-dir", default="/docker/fleet/state/chummer6/ea_media_assets")
    render_targets_parser.add_argument("--build-release", action="store_true")
    args = parser.parse_args()

    if args.command == "render-pack":
        manifest = render_pack(
            output_dir=Path(args.output_dir).expanduser(),
            build_release=not bool(args.skip_release_build),
        )
        print(
            json.dumps(
                {
                    "output_dir": manifest["output_dir"],
                    "assets": len(manifest["assets"]),
                    "status": "rendered",
                    "release_build": str((manifest.get("release_build") or {}).get("status") or ""),
                }
            )
        )
        return 0
    if args.command == "render-targets":
        manifest = render_targets(
            targets=list(args.target),
            output_dir=Path(args.output_dir).expanduser(),
            build_release=bool(args.build_release),
        )
        print(
            json.dumps(
                {
                    "output_dir": manifest["output_dir"],
                    "assets": len(manifest["assets"]),
                    "status": "rendered",
                    "release_build": str((manifest.get("release_build") or {}).get("status") or ""),
                }
            )
        )
        return 0

    output_path = Path(args.output).expanduser()
    result = render_with_ooda(
        prompt=str(args.prompt),
        output_path=output_path,
        width=int(args.width),
        height=int(args.height),
        spec={"target": str(output_path.name), "media_row": {}},
    )
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps({"output": str(output_path), **result}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "provider": result["provider"], "status": result["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
