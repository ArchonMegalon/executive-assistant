from __future__ import annotations

import json

from tests.product_test_helpers import build_product_client, seed_product_state, start_workspace


def _seed(principal_id: str = "exec-support-contracts"):
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")
    seeded = seed_product_state(client, principal_id=principal_id)
    return client, seeded


def test_surface_open_events_flow_into_workspace_diagnostics() -> None:
    client, _seeded = _seed("exec-diagnostics-events")

    assert client.get("/register", follow_redirects=False).status_code == 307
    assert client.get("/app/today").status_code == 200
    assert client.get("/app/settings").status_code == 200
    assert client.get("/app/api/plan").status_code == 200
    assert client.get("/app/api/usage").status_code == 200
    assert client.get("/app/api/support").status_code == 200
    assert client.get("/app/channel-loop/memo").status_code == 200
    assert client.get("/app/channel-loop/operator").status_code == 200
    assert client.get("/app/channel-loop/memo/plain").status_code == 200

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    counts = dict(payload["analytics"]["counts"])
    assert counts.get("memo_opened", 0) >= 1
    assert counts.get("rules_opened", 0) >= 1
    assert counts.get("plan_opened", 0) >= 1
    assert counts.get("usage_opened", 0) >= 1
    assert counts.get("support_opened", 0) >= 1
    assert counts.get("channel_digest_opened", 0) >= 2
    assert counts.get("channel_digest_plain_opened", 0) >= 1
    assert payload["billing"]["invoice_status"] in {"trial_active", "current", "upgrade_required"}
    assert "risk_state" in payload["providers"]
    assert "blocked_actions" in payload["commercial"]
    assert "blocked_action_message" in payload["commercial"]
    assert "load_score" in payload["queue_health"]
    assert "retrying_delivery" in payload["queue_health"]
    assert payload["product_control"]["summary"]
    assert payload["product_control"]["journey_gate_health"]["state"]
    assert "support_fallout" in payload["product_control"]
    assert "public_guide_freshness" in payload["product_control"]
    assert "state" in payload["support_verification"]
    assert "churn_risk" in payload["analytics"]
    assert "success_summary" in payload["analytics"]


def test_support_bundle_export_includes_commercial_state_and_records_event() -> None:
    client, _seeded = _seed("exec-support-bundle")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "calendar_note",
            "channel": "calendar",
            "title": "Board prep",
            "summary": "Confirm the board memo owner before the afternoon meeting.",
            "source_ref": "calendar-event-1",
            "external_id": "calendar-note-1",
        },
    )
    assert signal.status_code == 200

    export = client.get("/app/api/diagnostics/export")
    assert export.status_code == 200
    body = export.json()
    assert body["plan"]["display_name"] == "Executive Ops"
    assert body["billing"]["support_tier"] == "priority"
    assert body["billing"]["billing_portal_state"] in {"guided", "self_serve", "account_managed"}
    assert body["entitlements"]["operator_seats"] >= 1
    assert body["analytics"]["counts"].get("support_bundle_opened", 0) >= 1
    assert "queue_health" in body
    assert "assignment_suggestions" in body
    assert "sla_breaches" in body["queue_health"]
    assert "unclaimed_handoffs" in body["queue_health"]
    assert "load_score" in body["queue_health"]
    assert "retrying_delivery" in body["queue_health"]
    assert "risk_state" in body["providers"]
    assert "blocked_action_message" in body["commercial"]
    assert "pending" in body["approvals"]
    assert isinstance(body["human_tasks"], list)
    assert body["product_control"]["summary"]
    assert "journey_gate_freshness" in body["product_control"]
    assert "support_fallout" in body["product_control"]
    assert "public_guide_freshness" in body["product_control"]
    assert "state" in body["support_verification"]
    assert "success_summary" in body["analytics"]
    assert isinstance(body["recent_events"], list)
    assert "release_authority" in body
    assert body["release_authority"]["manifest_path"].endswith("release_manifest.generated.json")
    assert body["release_authority"]["project_modes_path"].endswith("PROJECT_MODES.generated.json")
    assert body["release_authority"]["state"] in {"clear", "watch", "missing"}
    assert "artifact_count" in body["release_authority"]
    assert isinstance(body["release_authority"]["enabled_project_modes"], list)
    assert isinstance(body["release_authority"]["compose_files"], list)
    assert "tracking_branch" in body["release_authority"]
    assert "public_origin_source" in body["release_authority"]
    assert any(item["event_type"] == "office_signal_calendar_note" for item in body["recent_events"])

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = diagnostics.json()["analytics"]["counts"]
    assert counts.get("support_bundle_opened", 0) >= 1


def test_support_bundle_download_sets_attachment_headers_and_records_event() -> None:
    client, _seeded = _seed("exec-support-bundle-download")

    export = client.get("/app/api/diagnostics/export", params={"download": "1"})
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/json")
    content_disposition = str(export.headers.get("content-disposition") or "")
    assert "attachment;" in content_disposition
    assert "support-bundle" in content_disposition
    body = export.json()
    assert body["workspace"]["name"] == "Executive Office"

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = diagnostics.json()["analytics"]["counts"]
    assert counts.get("support_bundle_downloaded", 0) >= 1


def test_trust_release_authority_flags_missing_public_origin(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "release_manifest.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "dirty_worktree": False,
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "",
                "public_origin_source": "missing",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "deploy-123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")
    monkeypatch.setenv("EA_RELEASE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("EA_PROJECT_MODES_MANIFEST_PATH", str(project_modes_path))

    client = build_product_client(principal_id="release-authority-missing-origin")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")

    trust = client.get("/app/api/trust")
    assert trust.status_code == 200
    authority = trust.json()["release_authority"]
    assert authority["state"] == "watch"
    assert authority["authority_posture"] == "missing_public_origin"
    assert authority["next_action"] == "Set the deployed public base URL and rematerialize the release manifest so release authority points at a runtime origin."


def test_trust_release_authority_flags_local_only_deploy_id(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "release_manifest.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
                "dirty_worktree": False,
                "deployment_id": "local-20260622T000000Z-89abcdef0123",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "89abcdef0123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")
    monkeypatch.setenv("EA_RELEASE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("EA_PROJECT_MODES_MANIFEST_PATH", str(project_modes_path))

    client = build_product_client(principal_id="release-authority-local-deploy")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")

    trust = client.get("/app/api/trust")
    assert trust.status_code == 200
    authority = trust.json()["release_authority"]
    assert authority["state"] == "watch"
    assert authority["authority_posture"] == "local_only_deploy_id"
    assert authority["next_action"] == "Set an explicit deployment ID from the real deploy system and rematerialize the release manifest."


def test_trust_release_authority_flags_dirty_worktree(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "release_manifest.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "fedcba9876543210fedcba9876543210fedcba98",
                "dirty_worktree": True,
                "deployment_id": "deploy-456",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "deploy-456",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")
    monkeypatch.setenv("EA_RELEASE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("EA_PROJECT_MODES_MANIFEST_PATH", str(project_modes_path))

    client = build_product_client(principal_id="release-authority-dirty-worktree")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")

    trust = client.get("/app/api/trust")
    assert trust.status_code == 200
    authority = trust.json()["release_authority"]
    assert authority["state"] == "watch"
    assert authority["authority_posture"] == "dirty_worktree"
    assert authority["next_action"] == "Build from a clean committed tree before treating this runtime as release authority."


def test_trust_release_authority_reports_authoritative_runtime(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "release_manifest.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "dirty_worktree": False,
                "deployment_id": "deploy-789",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "deploy-789",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")
    monkeypatch.setenv("EA_RELEASE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("EA_PROJECT_MODES_MANIFEST_PATH", str(project_modes_path))

    client = build_product_client(principal_id="release-authority-authoritative")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")

    trust = client.get("/app/api/trust")
    assert trust.status_code == 200
    authority = trust.json()["release_authority"]
    assert authority["state"] == "clear"
    assert authority["authority_posture"] == "authoritative_runtime"
    assert authority["next_action"] == "No action required."
    assert authority["authority_basis"] == "main@origin/main · aaaaaaaaaaaa · EA_CORE · EA_CORE · docker-compose.yml, docker-compose.prod.yml"


def test_people_history_endpoint_reflects_memory_corrections() -> None:
    client, seeded = _seed("exec-people-history")
    person_id = seeded["stakeholder_id"]

    correction = client.post(
        f"/app/actions/people/{person_id}/correct",
        data={
            "preferred_tone": "warmer",
            "add_theme": "board packet",
            "add_risk": "travel coordination",
            "return_to": f"/app/people/{person_id}",
        },
        follow_redirects=False,
    )
    assert correction.status_code == 303

    detail = client.get(f"/app/api/people/{person_id}")
    assert detail.status_code == 200
    profile = detail.json()
    assert profile["preferred_tone"] == "warmer"
    assert "board packet" in profile["themes"]
    assert "travel coordination" in profile["risks"]

    history = client.get(f"/app/api/people/{person_id}/detail/history")
    assert history.status_code == 200
    entries = history.json()
    assert any(entry["event_type"] == "memory_corrected" for entry in entries)
