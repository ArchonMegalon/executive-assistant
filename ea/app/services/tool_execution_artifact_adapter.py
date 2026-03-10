from __future__ import annotations

import uuid

from app.domain.models import Artifact, ToolDefinition, ToolInvocationRequest, ToolInvocationResult, normalize_artifact
from app.repositories.artifacts import ArtifactRepository
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_execution_common import ToolExecutionError


class ArtifactRepositoryToolAdapter:
    def __init__(
        self,
        *,
        artifacts: ArtifactRepository,
        evidence_runtime: EvidenceRuntimeService | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._evidence_runtime = evidence_runtime

    def execute(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not principal_id:
            raise ToolExecutionError("principal_id_required")
        source_text = str(payload.get("normalized_text") or payload.get("source_text") or "").strip()
        artifact_kind = str(payload.get("expected_artifact") or "rewrite_note")
        plan_id = str(payload.get("plan_id") or "")
        plan_step_key = str(payload.get("plan_step_key") or "")
        artifact = normalize_artifact(Artifact(
            artifact_id=str(uuid.uuid4()),
            kind=artifact_kind,
            content=source_text,
            execution_session_id=request.session_id,
            principal_id=principal_id,
            mime_type=str(payload.get("mime_type") or "text/plain") or "text/plain",
            preview_text=str(payload.get("preview_text") or ""),
            body_ref=str(payload.get("body_ref") or ""),
            structured_output_json=dict(payload.get("structured_output_json") or {}),
            attachments_json=dict(payload.get("attachments_json") or {}),
        ))
        self._artifacts.save(artifact)
        evidence_object = self._evidence_runtime.record_artifact(artifact) if self._evidence_runtime is not None else None
        evidence_object_id = str(evidence_object.evidence_id if evidence_object is not None else "")
        citation_handle = str(evidence_object.citation_handle if evidence_object is not None else "")
        action_kind = str(request.action_kind or "artifact.save") or "artifact.save"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=artifact.artifact_id,
            output_json={
                "artifact_id": artifact.artifact_id,
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "mime_type": artifact.mime_type,
                "preview_text": artifact.preview_text,
                "storage_handle": artifact.storage_handle,
                "body_ref": artifact.body_ref,
                "structured_output_json": dict(artifact.structured_output_json or {}),
                "attachments_json": dict(artifact.attachments_json or {}),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "principal_id": artifact.principal_id,
                "evidence_object_id": evidence_object_id,
                "citation_handle": citation_handle,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "mime_type": artifact.mime_type,
                "body_ref": artifact.body_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "principal_id": artifact.principal_id,
                "evidence_object_id": evidence_object_id,
                "citation_handle": citation_handle,
                "tool_version": definition.version,
            },
            artifacts=(artifact,),
        )
