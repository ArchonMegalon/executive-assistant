from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_execution_artifact_adapter import ArtifactRepositoryToolAdapter
from app.services.tool_execution_artifact_registry import register_builtin_artifact_repository
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ArtifactToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        artifacts: ArtifactRepository,
        evidence_runtime: EvidenceRuntimeService | None = None,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = ArtifactRepositoryToolAdapter(
            artifacts=artifacts,
            evidence_runtime=evidence_runtime,
        )

    def register_builtin(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        # Artifact tool outputs preserve evidence_object_id and citation_handle when materialized.
        register_builtin_artifact_repository(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            artifact_adapter=self._adapter,
        )
