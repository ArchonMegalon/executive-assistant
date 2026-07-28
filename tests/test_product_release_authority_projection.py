from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.product import service


COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
REMOTE_BINDING = {
    "source_remote_ref": "refs/remotes/origin/main",
    "source_remote_ref_commit_sha": COMMIT_SHA,
    "source_remote_ref_evidence": "local_remote_tracking_ref",
    "source_commit_reachable_from_remote_ref": True,
}


def _status_payload() -> dict[str, object]:
    return {
        "contract_name": "ea.release_authority_status.v1",
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": COMMIT_SHA,
        **REMOTE_BINDING,
        "gate": {
            "contract_name": "ea.release_authority_gate.v1",
            "status": "pass",
            "issues": [],
        },
    }


@pytest.mark.parametrize("published_status", [True, False])
def test_release_authority_summary_projects_remote_source_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    published_status: bool,
) -> None:
    payload = _status_payload()
    status_path = tmp_path / "release_authority_status.generated.json"
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(service, "_release_authority_status_path", lambda: status_path)
    monkeypatch.setattr(
        service,
        "_published_release_authority_status_is_authoritative",
        lambda: published_status,
    )
    if not published_status:
        monkeypatch.setattr(
            service,
            "_load_release_authority_status_materializer",
            lambda: SimpleNamespace(build_status=lambda **_kwargs: dict(payload)),
        )
        monkeypatch.setattr(
            service,
            "_release_manifest_path",
            lambda: tmp_path / "release_manifest.generated.json",
        )
        monkeypatch.setattr(
            service,
            "_project_modes_manifest_path",
            lambda: tmp_path / "PROJECT_MODES.generated.json",
        )

    product = object.__new__(service.ProductService)
    summary = product.release_authority_summary()

    assert {key: summary.get(key) for key in REMOTE_BINDING} == REMOTE_BINDING
