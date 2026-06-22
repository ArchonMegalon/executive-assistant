from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCRIPT_PATHS = [
    ROOT / "scripts" / "chummer6_runtime_config.py",
    ROOT / "scripts" / "chummer6_browseract_humanizer.py",
    ROOT / "scripts" / "chummer6_release_builder.py",
    ROOT / "scripts" / "chummer6_markupgo_render.py",
    ROOT / "scripts" / "chummer6_provider_readiness.py",
    ROOT / "scripts" / "prepare_memorial_vidboard_avatar_packet.py",
    ROOT / "scripts" / "compare_memorial_video_meeting_providers.py",
    ROOT / "scripts" / "publish_memorial_video_call_avatar.py",
    ROOT / "scripts" / "plan_memorial_live_avatar_integration.py",
]


def test_chummer6_runtime_provider_helpers_do_not_default_to_fleet_host_paths() -> None:
    for path in SCRIPT_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "/docker/fleet" not in source, path
        assert ".codex-studio" in source, path


def test_chummer6_runtime_provider_helpers_keep_explicit_env_overrides() -> None:
    expected_env_names = {
        "chummer6_runtime_config.py": "CHUMMER6_POLICY_PATH",
        "chummer6_browseract_humanizer.py": "CHUMMER6_BROWSERACT_BOOTSTRAP_RUNTIME_ROOT",
        "chummer6_release_builder.py": "CHUMMER6_RELEASE_MATRIX_PATH",
        "chummer6_markupgo_render.py": "CHUMMER6_EA_OVERRIDES_PATH",
        "chummer6_provider_readiness.py": "CHUMMER6_MEDIA_FACTORY_RENDER_SCRIPT",
        "prepare_memorial_vidboard_avatar_packet.py": "CHUMMER6_AVATAR_PROVIDER_ROOT",
        "compare_memorial_video_meeting_providers.py": "CHUMMER6_VIDEO_MEETING_PROVIDER_MATRIX_PATH",
        "publish_memorial_video_call_avatar.py": "CHUMMER6_AVATAR_PROVIDER_ROOT",
        "plan_memorial_live_avatar_integration.py": "CHUMMER6_LIVE_AVATAR_INTEGRATION_PLAN_PATH",
    }
    for filename, env_name in expected_env_names.items():
        source = (ROOT / "scripts" / filename).read_text(encoding="utf-8")
        assert env_name in source
