#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
if str(EA_DIR) not in sys.path:
    sys.path.insert(0, str(EA_DIR))

from fastapi.testclient import TestClient  # noqa: E402


SHOW_SURFACE = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"


def _client(*, operator: bool = False, memorial_mode: bool = False) -> TestClient:
    os.environ["EA_RUNTIME_MODE"] = "test"
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_ENABLE_PUBLIC_MEMORIALS"] = "1" if memorial_mode else "0"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "1" if memorial_mode else "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"
    os.environ["PROPERTYQUARRY_DEFAULT_BRAND"] = "0"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "project-mode-runtime-check"
    if operator:
        os.environ["EA_API_TOKEN"] = "test-token"
    else:
        os.environ["EA_API_TOKEN"] = ""
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "project-mode-runtime-check"})
    if operator:
        client.app.state.container.orchestrator.upsert_operator_profile(
            principal_id="project-mode-runtime-check",
            operator_id="operator-project-mode-runtime",
            display_name="Project Mode Runtime Operator",
            roles=("operator", "reviewer"),
            trust_tier="trusted",
            status="active",
            notes="Seeded by verify_project_mode_runtime.",
        )
        client.headers.update({"Authorization": "Bearer test-token"})
        client.headers.update({"X-EA-Operator-ID": "operator-project-mode-runtime"})
    return client


def _write_public_memorial(root: Path, slug: str, payload: dict[str, object]) -> None:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_private_voice(root: Path, slug: str, payload: dict[str, object]) -> None:
    profile_dir = root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _patch_memorial_runtime_roots(runtime_root: Path) -> None:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    artifacts_root = runtime_root / "artifacts"
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._VIDEO_MEETING_RUNTIME_ROOT = artifacts_root / "memorial_video_meeting"
    public_memorials._MEMORIAL_TTS_RENDER_CACHE_ROOT = artifacts_root / "memorial_tts_render_cache"
    public_memorials._MEMORIAL_PRESENT_WORLD_CACHE_ROOT = artifacts_root / "memorial_present_world_cache"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = runtime_root / "public_registry"
    memorial_archive_registry.ARCHIVE_ROOT = runtime_root / "archive"


def _configure_memorial_runtime_fixture(*, runtime_root: Path, slug: str) -> None:
    public_root = runtime_root / "public"
    private_root = runtime_root / "private"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "subtitle": "Eine ruhige Seite.",
            "audio_clips": [],
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "voice_plugin": "memorial-local",
            "voice_name": "Manfred",
        },
    )
    os.environ["EA_PUBLIC_MEMORIAL_DIR"] = str(public_root)
    os.environ["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(private_root)
    os.environ["EA_HEALTHCHECK_MEMORIAL_SLUG"] = slug
    _patch_memorial_runtime_roots(runtime_root)


def _internal_hrefs(html: str) -> set[str]:
    return {match for match in re.findall(r'href="([^"]+)"', html) if match.startswith("/")}


FORBIDDEN_ROUTE_STATUS_CODES = {401, 403, 404, 405, 409}


def _forbidden_route_paths() -> tuple[str, ...]:
    slug = "manfred"
    return (
        f"/memorials/{slug}",
        f"/memorials/{slug}/archive",
        f"/memorials/{slug}/archive.json",
        f"/memorials/{slug}/warmup",
        f"/memorials/{slug}/warmup-status",
        f"/memorials/{slug}/operator-status",
        f"/memorials/{slug}/video-meeting/status",
        f"/memorials/{slug}/video-meeting/session",
        f"/memorials/{slug}/video-meeting/provider-callback",
        f"/memorials/{slug}/playback-telemetry",
        f"/memorials/{slug}/realtime",
        f"/memorials/{slug}/realtime/webrtc",
        f"/memorials/{slug}/voice-config",
        f"/memorials/{slug}/voice-ab",
        f"/memorials/{slug}/voice-ab/rate",
        f"/memorials/{slug}/voice-ab-admin",
        f"/memorials/{slug}/voice-ab-admin/finalize",
        f"/memorials/{slug}/voice-ab-admin/maintain",
        f"/memorials/{slug}/voice-profile",
        f"/memorials/{slug}/voice-profile/build",
        f"/memorials/{slug}/voice-clone",
        f"/memorials/{slug}/chat",
        f"/memorials/{slug}/speech-transcribe",
        f"/memorials/{slug}/speech-synthesize",
        f"/memorials/{slug}/conversation-turn",
        f"/memorials/{slug}/personal-memory",
        f"/memorials/{slug}/app.webmanifest",
        f"/memorials/{slug}/service-worker.js",
        f"/memorials/{slug}/icon-180.png",
        f"/memorials/{slug}/icon-192.png",
        f"/memorials/{slug}/icon-512.png",
        f"/memorials/{slug}/icon.svg",
        "/memorials/files/manfred/memorial.json",
        "/memorials/files/manfred/tts_voice.json",
        "/properties",
        "/property",
        "/results",
    )


def _verify_ea_core_runtime() -> None:
    manifest = json.loads(SHOW_SURFACE.read_text(encoding="utf-8"))
    forbidden_surfaces = tuple(str(value).replace("*", "") for value in manifest.get("forbidden_surfaces") or [])
    forbidden_provider_names = tuple(str(value) for value in manifest.get("forbidden_provider_names") or [])
    client = _client()
    operator_client = _client(operator=True)

    modes_public = client.get("/modes", follow_redirects=False)
    if modes_public.status_code not in {401, 403}:
        raise SystemExit(f"modes_public_not_operator_gated:{modes_public.status_code}")
    modes_operator = operator_client.get("/modes", follow_redirects=False)
    if modes_operator.status_code != 200 or "data-project-mode-switchboard" not in modes_operator.text:
        raise SystemExit("modes_operator_surface_unavailable")

    for path in ("/", "/product", "/get-started", "/sign-in", "/app/today", "/app/queue", "/app/commitments", "/app/settings"):
        response = client.get(path, follow_redirects=True)
        if response.status_code != 200:
            raise SystemExit(f"allowed_surface_unavailable:{path}:{response.status_code}")
        body = response.text
        for provider in forbidden_provider_names:
            if provider in body:
                raise SystemExit(f"forbidden_provider_visible:{path}:{provider}")
        for href in _internal_hrefs(body):
            if any(href.startswith(prefix) for prefix in forbidden_surfaces):
                raise SystemExit(f"forbidden_surface_linked:{path}:{href}")

    for path in _forbidden_route_paths():
        response = client.get(path, follow_redirects=False)
        if response.status_code not in FORBIDDEN_ROUTE_STATUS_CODES:
            raise SystemExit(
                f"forbidden_route_open_in_ea_core:{path}:{response.status_code}"
            )


def _verify_memorial_runtime() -> None:
    slug = "manfred"
    with tempfile.TemporaryDirectory(prefix="ea-memorial-runtime-") as tmpdir:
        runtime_root = Path(tmpdir)
        _configure_memorial_runtime_fixture(runtime_root=runtime_root, slug=slug)
        client = _client(memorial_mode=True)
        operator_client = _client(operator=True, memorial_mode=True)

        modes_operator = operator_client.get("/modes", follow_redirects=False)
        if modes_operator.status_code != 200 or "Memorial" not in modes_operator.text:
            raise SystemExit("modes_operator_memorial_surface_unavailable")

        live = client.get("/health/live")
        if live.status_code != 200:
            raise SystemExit(f"memorial_health_live_unavailable:{live.status_code}")
        live_payload = live.json()
        runtime = dict(live_payload.get("memorial_runtime") or {})
        if live_payload.get("status") != "live":
            raise SystemExit("memorial_health_live_not_live")
        if runtime.get("state") != "mounted":
            raise SystemExit(f"memorial_runtime_state_not_mounted:{runtime.get('state')}")
        if runtime.get("route_mounted") is not True:
            raise SystemExit("memorial_runtime_route_not_mounted")
        if str(live_payload.get("memorial_slug") or "") != slug:
            raise SystemExit(f"memorial_healthcheck_slug_mismatch:{live_payload.get('memorial_slug')}")

        page = client.get(f"/memorials/{slug}", headers={"host": "myexternalbrain.com"})
        if page.status_code != 200:
            raise SystemExit(f"memorial_surface_unavailable:{page.status_code}")
        if "Manfred Hoza" not in page.text:
            raise SystemExit("memorial_surface_missing_person_name")

        manifest = client.get(f"/memorials/{slug}.json")
        if manifest.status_code != 200:
            raise SystemExit(f"memorial_manifest_unavailable:{manifest.status_code}")
        body = manifest.json()
        if body.get("slug") != slug:
            raise SystemExit(f"memorial_manifest_slug_mismatch:{body.get('slug')}")
        if body.get("person_name") != "Manfred Hoza":
            raise SystemExit("memorial_manifest_missing_person_name")


def main(argv: list[str] | None = None) -> int:
    args = list([] if argv is None else argv)
    if any(arg in {"--help", "-h"} for arg in args):
        print("Usage: python scripts/verify_project_mode_runtime.py")
        print("Verifies the selected project-mode runtime surface contract.")
        print("Options:")
        print("  --mode ea_core|memorial   Default: ea_core")
        return 0
    mode = "ea_core"
    if args:
        if len(args) == 2 and args[0] == "--mode":
            mode = str(args[1] or "").strip().lower()
        else:
            raise SystemExit(f"unsupported_arguments:{' '.join(args)}")
    if mode == "ea_core":
        _verify_ea_core_runtime()
        print(json.dumps({"status": "pass", "mode": "ea_core", "message": "project mode runtime surfaces obey the EA core show manifest."}))
        return 0
    if mode == "memorial":
        _verify_memorial_runtime()
        print(json.dumps({"status": "pass", "mode": "memorial", "message": "memorial runtime is mounted and serves the configured memorial surface."}))
        return 0
    raise SystemExit(f"unsupported_mode:{mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
