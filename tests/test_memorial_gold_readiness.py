from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


TEST_RUNTIME_REVISION = "a" * 40


def test_spatial_package_digest_matches_governed_deploy_contract() -> None:
    from scripts import deploy_ea_memorial as deploy
    from scripts.memorial_spatial_public_origin_contract import (
        canonical_json_sha256,
    )

    snapshot = {
        "tour.json": b'{"slug":"unit-tour"}\n',
        "generated-reconstruction/viewer.html": b"<!doctype html>\n",
    }
    rows = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for path, content in sorted(snapshot.items())
    ]

    assert canonical_json_sha256(rows) == deploy._spatial_package_sha256(snapshot)


@pytest.fixture(autouse=True)
def _clean_source_worktree(monkeypatch):
    import scripts.verify_memorial_gold_readiness as readiness

    monkeypatch.delenv("MEMORIAL_DIAGNOSTIC_SKIP_MEANINGFUL_BROWSER_RECEIPT", raising=False)
    monkeypatch.setattr(readiness, "_source_fingerprint", lambda: "unit-source-state")
    monkeypatch.setattr(
        readiness,
        "source_worktree_metadata",
        lambda root, *, dirty_path_limit=40: {
            "source_worktree_dirty": False,
            "source_dirty_count": 0,
            "source_dirty_files": [],
            "source_dirty_omitted_count": 0,
            "source_dirty_status_sha256": "",
        },
    )


def _voice_receipt(*, base_url: str = "https://8.8.8.8", slow: bool = False) -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "head_semantics": "source_state",
        "source_tree_fingerprint": "unit-source-tree",
        "source_state_fingerprint": "unit-source-state",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "dirty_worktree": False,
        "status": "pass",
        "slug": "manfred",
        "base_url": base_url,
        "runtime_source_revision": TEST_RUNTIME_REVISION,
        "gold_mode": True,
        "require_public_origin": True,
        "gold_claim_allowed": True,
        "failed_codes": [],
        "warned_codes": [],
        "metrics": {
            "direct_tts_f1": 1.0,
            "conversation_turn_audio_f1": 1.0,
            "conversation_turn_total_ms": 7000 if slow else 1200,
            "speech_transcribe_ms": 4000 if slow else 700,
        },
        "checks": [{"status": "pass", "code": "present_world_route_ok"}],
    }


def _browser_receipt(*, base_url: str = "https://8.8.8.8", mode: str = "live") -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_realtime_browser_exit_gate",
        "contract_version": 3,
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "head_semantics": "source_state",
        "source_tree_fingerprint": "unit-source-tree",
        "source_state_fingerprint": "unit-source-state",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "dirty_worktree": False,
        "status": "pass",
        "slug": "manfred",
        "base_url": base_url,
        "runtime_source_revision": TEST_RUNTIME_REVISION,
        "gold_mode": True,
        "require_public_origin": True,
        "gold_claim_allowed": True,
        "speech_transcribe_mode": mode,
        "failed_codes": [],
        "first_answer_ms": 1200,
        "audio_ready_for_ui": True,
        "answer_text_visible": True,
        "ui_audio_play_calls": 1,
        "ui_audio_play_ended": 1,
        "answer_semantic_passed": True,
    }


def test_memorial_gold_readiness_rejects_legacy_browser_contract() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    receipt = _browser_receipt()
    receipt["contract_version"] = 2

    issues = readiness._check_browser_receipt(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
        max_first_answer_ms=4500.0,
    )

    assert "browser_contract_version_invalid" in issues


def _room_receipt(*, base_url: str = "https://8.8.8.8") -> dict[str, object]:
    return {
        "contract_name": "ea.memorial_room_audio_public_origin",
        "git_head": "HEAD",
        "source_git_head": "HEAD",
        "head_semantics": "source_state",
        "source_tree_fingerprint": "unit-source-tree",
        "source_state_fingerprint": "unit-source-state",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "dirty_worktree": False,
        "status": "pass",
        "proof_type": "manual_room_attestation",
        "slug": "manfred",
        "base_url": base_url,
        "runtime_source_revision": TEST_RUNTIME_REVISION,
        "require_public_origin": True,
        "reviewer": "unit reviewer",
        "manual_attestation": {
            "attestation_id": "unit-room-review",
            "signed_at": "2026-06-18T12:00:00Z",
            "source": "unit_test",
            "ci_must_not_auto_assert": True,
        },
        "checks": {
            "actual_device_checked": True,
            "actual_speaker_checked": True,
            "first_syllable_not_clipped": True,
            "intelligibility_confirmed": True,
            "answer_text_fallback_visible": True,
            "no_internet_search_confirmed": True,
            "normal_spoken_turn_confirmed": True,
            "interruption_behavior_confirmed": True,
            "retry_path_confirmed": True,
        },
    }


def _install_passing_spatial_receipt(
    readiness: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_git_head: str = "HEAD",
) -> None:
    spatial_path = tmp_path / "spatial.json"
    spatial_path.write_text(
        json.dumps(
            {
                "status": "pass",
                "slug": "manfred",
                "public_base_url": "https://8.8.8.8",
                "runtime_revision": TEST_RUNTIME_REVISION,
                "source_git_head": source_git_head,
                "source_state_fingerprint": "unit-source-state",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "SPATIAL_RECEIPT", spatial_path)
    monkeypatch.setattr(readiness, "_check_spatial_receipt", lambda *args, **kwargs: [])


def test_memorial_gold_readiness_requires_public_browser_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_passes_with_public_voice_and_browser_receipts(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    meaningful_browser_path = tmp_path / "meaningful-browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    meaningful_browser_path.write_text(json.dumps(_browser_receipt(mode="text_prompt")), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "MEANINGFUL_BROWSER_RECEIPT", meaningful_browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})
    _install_passing_spatial_receipt(readiness, tmp_path, monkeypatch)

    assert readiness.main() == 0


def test_memorial_gold_readiness_requires_meaningful_browser_receipt_by_default(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    meaningful_browser_path = tmp_path / "meaningful-browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "MEANINGFUL_BROWSER_RECEIPT", meaningful_browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})

    assert readiness.main() == 1
    default_payload = json.loads(capsys.readouterr().out)
    assert default_payload["public_meaningful_browser_gold_required"] is True
    assert default_payload["memorial_voice_gold_claim_allowed"] is False

    monkeypatch.setenv("MEMORIAL_DIAGNOSTIC_SKIP_MEANINGFUL_BROWSER_RECEIPT", "1")
    assert readiness.main() == 1
    diagnostic_payload = json.loads(capsys.readouterr().out)
    assert diagnostic_payload["status"] == "blocked"
    assert diagnostic_payload["public_meaningful_browser_diagnostic_override"] is True
    assert diagnostic_payload["public_meaningful_browser_gold_issues"] == [
        "meaningful_browser_receipt_skipped_for_diagnostic_only"
    ]
    assert diagnostic_payload["memorial_voice_gold_claim_allowed"] is False


def test_memorial_gold_readiness_blocks_slow_public_voice_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt(slow=True)), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_blocks_browser_stub_stt_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt(mode="transcript_injected")), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


@pytest.mark.parametrize(
    "origin_url",
    [
        "http://memorial.example.test",
        "https://127.0.0.1:8090",
        "https://192.168.1.20",
        "https://0.0.0.0:8090",
        "https://user:password@memorial.example.test",
        "https://memorial.example.test/path",
    ],
)
def test_memorial_gold_readiness_rejects_non_public_https_voice_origins(
    origin_url: str,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    issues = readiness._check_receipt(
        _voice_receipt(base_url=origin_url),
        current_head="HEAD",
        current_fingerprint="unit-source-state",
        public_required=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
    )

    assert "public_origin_must_be_nonlocal_https" in issues


@pytest.mark.parametrize(
    "origin_url",
    (
        "https://memorial.example.test",
        "https://memorial.internal",
        "https://memorial.local",
        "https://localhost",
    ),
)
def test_memorial_gold_readiness_rejects_reserved_hostnames_without_dns(
    monkeypatch: pytest.MonkeyPatch,
    origin_url: str,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    monkeypatch.setattr(
        readiness.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail(
            "reserved hostnames must be rejected before DNS resolution"
        ),
    )

    assert readiness._is_https_public_origin(origin_url) is False


def test_memorial_gold_readiness_rejects_any_private_dns_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    monkeypatch.setattr(
        readiness.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                readiness.socket.AF_INET,
                readiness.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 0),
            ),
            (
                readiness.socket.AF_INET6,
                readiness.socket.SOCK_STREAM,
                6,
                "",
                ("fd00::23", 0, 0, 0),
            ),
        ],
    )

    assert (
        readiness._is_https_public_origin(
            "https://memorial.public-origin.example.at"
        )
        is False
    )


def test_memorial_gold_readiness_fails_closed_on_dns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    def fail_resolution(*_args, **_kwargs):
        raise readiness.socket.gaierror("unit DNS failure")

    monkeypatch.setattr(readiness.socket, "getaddrinfo", fail_resolution)

    assert (
        readiness._is_https_public_origin(
            "https://memorial.public-origin.example.at"
        )
        is False
    )


def test_memorial_gold_readiness_accepts_global_literal_and_global_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    monkeypatch.setattr(
        readiness.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                readiness.socket.AF_INET,
                readiness.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 0),
            )
        ],
    )

    assert readiness._is_https_public_origin("https://8.8.8.8") is True
    assert (
        readiness._is_https_public_origin(
            "https://memorial.public-origin.example.at"
        )
        is True
    )


def test_memorial_gold_readiness_handles_malformed_room_receipt_fields() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    receipt = _room_receipt()
    receipt["manual_attestation"] = ["not", "an", "object"]
    receipt["checks"] = "not-an-object"

    issues = readiness._check_room_receipt(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
    )

    assert "room_manual_attestation_invalid" in issues
    assert "room_checks_invalid" in issues
    assert "room_manual_attestation_id_missing" in issues
    assert "room_actual_device_checked_missing" in issues


def test_memorial_gold_readiness_handles_malformed_browser_latency() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    receipt = _browser_receipt()
    receipt["first_answer_ms"] = "not-a-number"

    issues = readiness._check_browser_receipt(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
        max_first_answer_ms=4500,
    )

    assert "browser_first_answer_ms_invalid" in issues


def test_memorial_gold_readiness_binds_public_receipts_to_one_runtime() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    receipts = {
        "public_voice": _voice_receipt(),
        "public_browser": _browser_receipt(),
        "meaningful_browser": _browser_receipt(mode="text_prompt"),
        "room_audio": _room_receipt(),
    }

    assert (
        readiness._receipt_set_binding_issues(
            receipts,
            expected_slug="manfred",
            current_head="HEAD",
        )
        == []
    )


def test_memorial_gold_readiness_rejects_mixed_runtime_receipt_set() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    public_browser = _browser_receipt(base_url="https://1.1.1.1")
    public_browser["runtime_source_revision"] = "b" * 40
    meaningful_browser = _browser_receipt(mode="text_prompt")
    meaningful_browser["slug"] = "another-memorial"
    room = _room_receipt()
    room.pop("runtime_source_revision")
    receipts = {
        "public_voice": _voice_receipt(),
        "public_browser": public_browser,
        "meaningful_browser": meaningful_browser,
        "room_audio": room,
    }

    issues = readiness._receipt_set_binding_issues(
        receipts,
        expected_slug="manfred",
        current_head="HEAD",
    )

    assert "receipt_set_meaningful_browser_slug_mismatch" in issues
    assert "receipt_set_room_audio_runtime_revision_missing_or_invalid" in issues
    assert "receipt_set_origin_mismatch" in issues
    assert "receipt_set_runtime_revision_mismatch" in issues


def test_memorial_gold_readiness_requires_room_audio_receipt(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")

    assert readiness.main() == 1


def test_memorial_gold_readiness_uses_source_git_head_before_receipt_commit_head(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    meaningful_browser_path = tmp_path / "meaningful-browser.json"
    room_path = tmp_path / "room.json"
    local = _voice_receipt(base_url="http://127.0.0.1:8090")
    public = _voice_receipt()
    browser = _browser_receipt()
    meaningful_browser = _browser_receipt(mode="text_prompt")
    room = _room_receipt()
    for payload in (local, public, browser, meaningful_browser, room):
        payload["git_head"] = "RECEIPT_COMMIT"
        payload["source_git_head"] = "SOURCE_HEAD"
    local_path.write_text(json.dumps(local), encoding="utf-8")
    public_path.write_text(json.dumps(public), encoding="utf-8")
    browser_path.write_text(json.dumps(browser), encoding="utf-8")
    meaningful_browser_path.write_text(json.dumps(meaningful_browser), encoding="utf-8")
    room_path.write_text(json.dumps(room), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "MEANINGFUL_BROWSER_RECEIPT", meaningful_browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "SOURCE_HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})
    _install_passing_spatial_receipt(
        readiness,
        tmp_path,
        monkeypatch,
        source_git_head="SOURCE_HEAD",
    )

    assert readiness.main() == 0


def test_memorial_gold_readiness_allows_generated_only_receipt_commit_delta(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    meaningful_browser_path = tmp_path / "meaningful-browser.json"
    room_path = tmp_path / "room.json"
    local = _voice_receipt(base_url="http://127.0.0.1:8090")
    public = _voice_receipt()
    browser = _browser_receipt()
    meaningful_browser = _browser_receipt(mode="text_prompt")
    room = _room_receipt()
    for payload in (local, public, browser, meaningful_browser, room):
        payload["git_head"] = "RECEIPT_COMMIT"
        payload["source_git_head"] = "SOURCE_HEAD"
        payload["dirty_worktree"] = True
    local_path.write_text(json.dumps(local), encoding="utf-8")
    public_path.write_text(json.dumps(public), encoding="utf-8")
    browser_path.write_text(json.dumps(browser), encoding="utf-8")
    meaningful_browser_path.write_text(json.dumps(meaningful_browser), encoding="utf-8")
    room_path.write_text(json.dumps(room), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "MEANINGFUL_BROWSER_RECEIPT", meaningful_browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "CURRENT_HEAD")
    monkeypatch.setattr(readiness, "_fresh_enough", lambda recorded_head, current_head: recorded_head == "SOURCE_HEAD" and current_head == "CURRENT_HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})
    _install_passing_spatial_receipt(
        readiness,
        tmp_path,
        monkeypatch,
        source_git_head="CURRENT_HEAD",
    )

    assert readiness.main() == 0


@pytest.mark.parametrize(
    "changed_path",
    [
        "memorial_data/public_memorials/manfred/memorial.json",
        "ea/app/repositories/memorial_memory_repository.py",
        "ea/app/services/memorial_memory_runtime.py",
        "ea/app/templates/admin_memorial_gold.html",
        "ea/scripts/memorial_flagship_preflight.py",
    ],
)
def test_memorial_gold_readiness_rejects_any_source_commit_delta(
    changed_path: str,
    monkeypatch,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{changed_path}\n"),
    )

    assert readiness._fresh_enough("RECORDED_HEAD", current_head="CURRENT_HEAD") is False


def test_memorial_gold_readiness_allows_only_named_generated_receipt_delta(monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    generated_path = ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{generated_path}\n"),
    )

    assert readiness._fresh_enough("RECORDED_HEAD", current_head="CURRENT_HEAD") is True


def test_memorial_gold_readiness_requires_exact_current_source_fingerprint() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    receipt = _voice_receipt()
    assert readiness._receipt_source_state_current(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
    )

    receipt["source_state_fingerprint"] = "stale-source-state"
    assert not readiness._receipt_source_state_current(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
    )

    receipt.pop("source_state_fingerprint")
    assert not readiness._receipt_source_state_current(
        receipt,
        current_head="HEAD",
        current_fingerprint="unit-source-state",
    )


def test_memorial_gold_readiness_requires_memorial_surface_contract(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public_path.write_text(json.dumps(_voice_receipt()), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "blocked", "mode": "memorial"})

    assert readiness.main() == 1


def test_memorial_gold_readiness_treats_operator_status_as_generated_only_artifact() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    assert ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json" in readiness.GENERATED_RECEIPT_PATHS


def test_memorial_gold_readiness_prefers_auto_receipt_refresh_before_room_attestation() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    summary = readiness._blocker_summary(
        local_issues=[],
        public_issues=["receipt_stale_relative_to_current_head"],
        browser_issues=["browser_receipt_stale_relative_to_current_head"],
        meaningful_browser_issues=[],
        memorial_surface_contract_issues=[],
        room_issues=["room_receipt_status_not_pass"],
    )

    assert readiness._next_action_from_summary(summary) == "refresh_memorial_public_auto_receipts_clean"
    blocked_by_key = {item["key"]: item for item in summary["blocked_components"]}
    assert blocked_by_key["public_voice_receipt"]["code"] == "public_voice_receipt"
    assert blocked_by_key["public_voice_receipt"]["component"] == "Public voice receipt"
    assert blocked_by_key["public_voice_receipt"]["next_command"] == "make materialize-memorial-public-auto-receipts-clean"
    assert blocked_by_key["public_browser_receipt"]["next_command"] == "make materialize-memorial-public-auto-receipts-clean"
    assert blocked_by_key["room_audio_receipt"]["next_command"] == "make materialize-memorial-room-audio-gold-clean"
    assert summary["blocked_commands"] == [
        "make materialize-memorial-public-auto-receipts-clean",
        "make materialize-memorial-public-auto-receipts-clean",
        "make materialize-memorial-room-audio-gold-clean",
    ]


def test_memorial_gold_readiness_overrides_auto_refresh_when_source_worktree_dirty(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public = _voice_receipt()
    public["source_git_head"] = "STALE_HEAD"
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    public_path.write_text(json.dumps(public), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})
    monkeypatch.setattr(readiness, "_fresh_enough", lambda recorded_head, current_head: recorded_head == "HEAD")

    source_metadata_calls: list[dict[str, object]] = []

    def _source_metadata(root, *, dirty_path_limit):
        source_metadata_calls.append({"dirty_path_limit": dirty_path_limit})
        return {
            "source_worktree_dirty": True,
            "source_dirty_count": 2,
            "source_dirty_files": ["ea/app/api/routes/public_memorials.py", "scripts/deploy.sh"],
            "source_dirty_omitted_count": 1,
            "source_dirty_status_sha256": "dirty-sha",
        }

    monkeypatch.setattr(
        readiness,
        "source_worktree_metadata",
        _source_metadata,
    )

    assert readiness.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["next_action"] == "commit_or_stash_source_changes_before_clean_receipts"
    assert payload["next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert payload["source_worktree_dirty"] is True
    assert payload["source_dirty_count"] == 2
    assert source_metadata_calls == [{"dirty_path_limit": readiness.SOURCE_DIRTY_FILE_LIMIT}]
    assert payload["source_dirty_summary"]["status"] == "dirty"
    assert payload["source_dirty_summary"]["total_count"] == 2
    assert payload["source_dirty_summary"]["omitted_count"] == 1
    assert payload["source_dirty_verifier"]["contract_name"] == "ea.source_dirty_groups_verifier.v1"
    assert payload["source_dirty_verifier"]["status"] == "pass"
    assert payload["source_dirty_verifier"]["issues"] == []
    assert payload["source_dirty_verifier"]["source_dirty_count"] == 2
    assert payload["source_dirty_verifier"]["priority_group_count"] == 2
    assert payload["source_cleanup"]["status"] == "blocked"
    assert payload["source_cleanup"]["source_dirty_count"] == 2
    assert payload["source_cleanup"]["verifier_status"] == "pass"
    assert payload["source_cleanup"]["next_action"] == "commit_or_stash_source_changes_before_clean_receipts"
    assert payload["source_cleanup"]["next_command"] == "scripts/inspect_source_dirty_groups.py --list-categories"
    assert payload["source_cleanup"]["top_categories"] == [
        {
            "category": "api_routes",
            "visible_count": 1,
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        },
        {
            "category": "scripts",
            "visible_count": 1,
            "drilldown_command": "scripts/inspect_source_dirty_groups.py --category scripts --limit 20",
        },
    ]
    assert payload["source_cleanup"]["category_drilldown_commands"] == [
        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        "scripts/inspect_source_dirty_groups.py --category scripts --limit 20",
    ]
    assert payload["source_cleanup"]["handoff_commands"] == [
        "git status --short",
        "scripts/inspect_source_dirty_groups.py --list-categories",
        "scripts/inspect_source_dirty_groups.py --category api_routes --limit 20",
        "scripts/inspect_source_dirty_groups.py --category scripts --limit 20",
    ]
    categories = {
        item["category"]: item
        for item in payload["source_dirty_summary"]["categories"]
    }
    assert categories["api_routes"]["visible_count"] == 1
    assert categories["scripts"]["visible_count"] == 1
    assert "source_worktree" in payload["blocker_summary"]["blocked_component_keys"]
    source_blocker = {
        item["key"]: item for item in payload["blocker_summary"]["blocked_components"]
    }["source_worktree"]
    assert source_blocker["code"] == "source_worktree"
    assert source_blocker["component"] == "Source worktree"
    assert source_blocker["issues"] == ["source_worktree_dirty"]


def test_memorial_gold_readiness_routes_to_source_dirty_verifier_when_report_is_malformed(tmp_path, monkeypatch, capsys) -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    local_path = tmp_path / "local.json"
    public_path = tmp_path / "public.json"
    browser_path = tmp_path / "browser.json"
    room_path = tmp_path / "room.json"
    local_path.write_text(json.dumps(_voice_receipt(base_url="http://127.0.0.1:8090")), encoding="utf-8")
    public = _voice_receipt()
    public["source_git_head"] = "STALE_HEAD"
    public_path.write_text(json.dumps(public), encoding="utf-8")
    browser_path.write_text(json.dumps(_browser_receipt()), encoding="utf-8")
    room_path.write_text(json.dumps(_room_receipt()), encoding="utf-8")

    monkeypatch.setattr(readiness, "LOCAL_RECEIPT", local_path)
    monkeypatch.setattr(readiness, "PUBLIC_RECEIPT", public_path)
    monkeypatch.setattr(readiness, "BROWSER_RECEIPT", browser_path)
    monkeypatch.setattr(readiness, "ROOM_RECEIPT", room_path)
    monkeypatch.setattr(readiness, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(readiness, "_run_script_json", lambda script_args: {"status": "pass", "mode": "memorial"})
    monkeypatch.setattr(readiness, "_fresh_enough", lambda recorded_head, current_head: recorded_head == "HEAD")
    monkeypatch.setattr(
        readiness,
        "source_worktree_metadata",
        lambda root, *, dirty_path_limit: {
            "source_worktree_dirty": True,
            "source_dirty_count": 2,
            "source_dirty_files": ["ea/app/api/routes/public_memorials.py", "scripts/deploy.sh"],
            "source_dirty_omitted_count": 0,
            "source_dirty_status_sha256": "dirty-sha",
        },
    )
    monkeypatch.setattr(
        readiness,
        "_validate_source_dirty_report",
        lambda report: ["visible_category_total_mismatch"],
    )

    assert readiness.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["next_action"] == "verify_source_dirty_groups_before_source_cleanup"
    assert payload["next_command"] == "make verify-source-dirty-groups"
    assert payload["source_dirty_verifier"]["status"] == "blocked"
    assert payload["source_dirty_verifier"]["issues"] == ["visible_category_total_mismatch"]
    assert payload["source_dirty_verifier"]["priority_group_count"] == 2
    assert payload["source_cleanup"]["status"] == "verifier_blocked"
    assert payload["source_cleanup"]["verifier_status"] == "blocked"
    assert payload["source_cleanup"]["verifier_issues"] == ["visible_category_total_mismatch"]
    assert payload["source_cleanup"]["next_action"] == "verify_source_dirty_groups_before_source_cleanup"
    assert payload["source_cleanup"]["next_command"] == "make verify-source-dirty-groups"
    assert "make verify-source-dirty-groups" in payload["source_cleanup"]["handoff_commands"]
    source_blocker = {
        item["key"]: item for item in payload["blocker_summary"]["blocked_components"]
    }["source_worktree"]
    assert source_blocker["issues"] == [
        "source_worktree_dirty",
        "source_dirty_group_verifier_failed",
    ]


def test_memorial_gold_readiness_prefers_local_refresh_before_room_when_only_local_is_stale() -> None:
    import scripts.verify_memorial_gold_readiness as readiness

    summary = readiness._blocker_summary(
        local_issues=["receipt_stale_relative_to_current_head"],
        public_issues=[],
        browser_issues=[],
        meaningful_browser_issues=[],
        memorial_surface_contract_issues=[],
        room_issues=["room_receipt_status_not_pass"],
    )

    assert readiness._next_action_from_summary(summary) == "refresh_local_memorial_voice_receipt"
    blocked_by_key = {item["key"]: item for item in summary["blocked_components"]}
    assert blocked_by_key["local_release_receipt"]["next_command"] == "make materialize-memorial-public-voice-gold"
    assert blocked_by_key["room_audio_receipt"]["next_command"] == "make materialize-memorial-room-audio-gold-clean"
