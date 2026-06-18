from __future__ import annotations

import os
from typing import Any


def build_workflow_receipt_metadata() -> dict[str, Any]:
    run_id = str(
        os.getenv("EA_WORKFLOW_RUN_ID")
        or os.getenv("GITHUB_RUN_ID")
        or ""
    ).strip()
    artifact_id = str(
        os.getenv("EA_WORKFLOW_ARTIFACT_ID")
        or os.getenv("GITHUB_ARTIFACT_ID")
        or ""
    ).strip()
    payload = {
        "workflow_run_id": run_id,
        "workflow_artifact_id": artifact_id,
        "workflow_name": str(
            os.getenv("EA_WORKFLOW_NAME")
            or os.getenv("GITHUB_WORKFLOW")
            or ""
        ).strip(),
        "workflow_job": str(
            os.getenv("EA_WORKFLOW_JOB")
            or os.getenv("GITHUB_JOB")
            or ""
        ).strip(),
        "workflow_run_attempt": str(
            os.getenv("EA_WORKFLOW_RUN_ATTEMPT")
            or os.getenv("GITHUB_RUN_ATTEMPT")
            or ""
        ).strip(),
        "workflow_repository": str(
            os.getenv("EA_WORKFLOW_REPOSITORY")
            or os.getenv("GITHUB_REPOSITORY")
            or ""
        ).strip(),
        "workflow_ref": str(
            os.getenv("EA_WORKFLOW_REF")
            or os.getenv("GITHUB_REF")
            or ""
        ).strip(),
    }
    if not run_id and not artifact_id:
        return {}
    return payload
