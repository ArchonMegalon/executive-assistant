from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/audiobook_mount_guard.sh"


def _source() -> str:
    return GUARD.read_text(encoding="utf-8")


def test_mount_guard_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(GUARD)], check=True)


def test_mount_guard_reuses_observed_compose_topology() -> None:
    source = _source()

    for label in (
        "com.docker.compose.project.working_dir",
        "com.docker.compose.project.config_files",
        "com.docker.compose.project.environment_file",
    ):
        assert label in source
    assert 'command+=(--env-file "${path}")' in source
    assert 'command+=(-f "${path}")' in source
    assert "-f /docker/EA/docker-compose.yml" not in source
    assert "-f /docker/EA/docker-compose.whatsapp-web-session.yml" not in source
    assert "-f /docker/audiobookshelf/docker-compose.yml" not in source


def test_mount_guard_preflights_every_topology_before_recreation() -> None:
    source = _source()

    preflight = source.index(
        'run_compose_for_container preflight "${container}"'
    )
    lease = source.index('write_result "action_started"')
    recreate = source.index(
        'run_compose_for_container recreate "${container}"'
    )

    assert preflight < lease < recreate
    assert 'write_result "preaction_refused"' in source
    assert 'result_reason="compose_topology_render_failed:${container}"' in source


def test_mount_guard_rejects_mutable_or_missing_compose_inputs() -> None:
    source = _source()

    assert '[[ ! -L "${path}" ]] || return 1' in source
    assert '"${owner}" == "0" || "${owner}" == "${effective_uid}"' in source
    assert '"${permissions:5:1}" != "w"' in source
    assert '"${permissions:8:1}" != "w"' in source
    assert (
        'result_reason="compose_topology_untrusted_or_unavailable:${container}"'
        in source
    )


def test_mount_guard_skips_memorial_only_runtime_without_audiobook_mount() -> None:
    source = _source()

    assert "EA_DEPLOY_PRIMARY_MODE=" in source
    assert "EA_DEPLOY_ENABLED_MODES=" in source
    assert (
        '"${primary_mode_entry#EA_DEPLOY_PRIMARY_MODE=}" == "MEMORIAL"'
        in source
    )
    assert (
        '"${enabled_modes_entry#EA_DEPLOY_ENABLED_MODES=}" == "MEMORIAL"'
        in source
    )
    assert "skipped|memorial_mode_without_audiobook_mount" in source
