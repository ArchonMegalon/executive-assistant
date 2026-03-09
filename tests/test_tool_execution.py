from __future__ import annotations

import pytest

from app.domain.models import Artifact, ToolInvocationRequest
from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.evidence_objects import InMemoryEvidenceObjectRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_execution import (
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
    ToolExecutionError,
    ToolExecutionService,
)
from app.services.tool_runtime import ToolRuntimeService


def test_tool_execution_service_executes_builtin_artifact_repository_handler() -> None:
    artifacts = InMemoryArtifactRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(tool_runtime=tool_runtime, artifacts=artifacts)

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-1",
            step_id="step-1",
            tool_name="artifact_repository",
            action_kind="artifact.save",
            payload_json={
                "source_text": "draft note",
                "expected_artifact": "rewrite_note",
                "plan_id": "plan-1",
                "plan_step_key": "step_artifact_save",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "artifact_repository"
    assert result.action_kind == "artifact.save"
    assert result.receipt_json["handler_key"] == "artifact_repository"
    assert result.receipt_json["invocation_contract"] == "tool.v1"
    assert result.output_json["artifact_kind"] == "rewrite_note"
    assert len(result.artifacts) == 1
    saved = artifacts.get(result.target_ref)
    assert saved is not None
    assert saved.content == "draft note"
    assert saved.principal_id == "exec-1"


def test_tool_execution_service_materializes_evidence_objects_for_evidence_pack_artifacts() -> None:
    artifacts = InMemoryArtifactRepository()
    evidence_runtime = EvidenceRuntimeService(InMemoryEvidenceObjectRepository())
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=artifacts,
        evidence_runtime=evidence_runtime,
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-evidence-1",
            step_id="step-evidence-1",
            tool_name="artifact_repository",
            action_kind="artifact.save",
            payload_json={
                "source_text": "Market conditions suggest two viable options.",
                "expected_artifact": "decision_summary",
                "structured_output_json": {
                    "format": "evidence_pack",
                    "claims": ["Option A preserves margin", "Option B accelerates launch"],
                    "evidence_refs": ["browseract://run/123", "paper://abc"],
                    "open_questions": ["Need final vendor pricing"],
                    "confidence": 0.72,
                },
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.output_json["evidence_object_id"] == f"evidence-{result.target_ref}"
    assert result.output_json["citation_handle"] == f"evidence://evidence-{result.target_ref}"
    listed = evidence_runtime.list_objects(limit=10, principal_id="exec-1")
    assert len(listed) == 1
    assert listed[0].artifact_id == result.target_ref
    assert listed[0].claims == ("Option A preserves margin", "Option B accelerates launch")
    assert listed[0].evidence_refs == ("browseract://run/123", "paper://abc")


def test_evidence_runtime_merges_materialized_evidence_objects_without_reparsing_artifact_body() -> None:
    evidence_runtime = EvidenceRuntimeService(InMemoryEvidenceObjectRepository())
    first = evidence_runtime.record_artifact(
        Artifact(
            artifact_id="artifact-evidence-1",
            kind="decision_summary",
            content="Market conditions suggest two viable options.",
            execution_session_id="session-evidence-1",
            principal_id="exec-1",
            structured_output_json={
                "format": "evidence_pack",
                "claims": ["Option A preserves margin", "Option B accelerates launch"],
                "evidence_refs": ["browseract://run/123", "paper://abc"],
                "open_questions": ["Need final vendor pricing"],
                "confidence": 0.72,
            },
        )
    )
    second = evidence_runtime.record_artifact(
        Artifact(
            artifact_id="artifact-evidence-2",
            kind="decision_summary",
            content="Support load may fall if the simpler option ships first.",
            execution_session_id="session-evidence-2",
            principal_id="exec-1",
            structured_output_json={
                "format": "evidence_pack",
                "claims": ["Option C reduces support load"],
                "evidence_refs": ["paper://abc", "call://ops-review"],
                "open_questions": ["Need service staffing forecast"],
                "confidence": 0.58,
            },
        )
    )

    assert first is not None
    assert second is not None
    merged = evidence_runtime.merge_objects([first.evidence_id, second.evidence_id], principal_id="exec-1")

    assert merged.claims == (
        "Option A preserves margin",
        "Option B accelerates launch",
        "Option C reduces support load",
    )
    assert merged.evidence_refs == ("browseract://run/123", "paper://abc", "call://ops-review")
    assert merged.open_questions == ("Need final vendor pricing", "Need service staffing forecast")
    assert merged.source_artifact_ids == ("artifact-evidence-1", "artifact-evidence-2")
    assert merged.citation_handles == (
        "evidence://evidence-artifact-evidence-1",
        "evidence://evidence-artifact-evidence-2",
    )


def test_tool_execution_service_rejects_disabled_tools() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    tool_runtime.upsert_tool(
        tool_name="artifact_repository",
        version="v2",
        enabled=False,
    )

    with pytest.raises(ToolExecutionError, match="tool_disabled:artifact_repository"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-1",
                step_id="step-1",
                tool_name="artifact_repository",
                action_kind="artifact.save",
                payload_json={"source_text": "draft note"},
                context_json={"principal_id": "exec-1"},
            )
        )


def test_tool_execution_service_requires_principal_for_artifact_repository_handler() -> None:
    service = ToolExecutionService(
        tool_runtime=ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        ),
        artifacts=InMemoryArtifactRepository(),
    )

    with pytest.raises(ToolExecutionError, match="principal_id_required"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-1",
                step_id="step-1",
                tool_name="artifact_repository",
                action_kind="artifact.save",
                payload_json={"source_text": "draft note"},
                context_json={},
            )
        )


def test_tool_execution_service_executes_builtin_connector_dispatch_handler() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-1",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-2",
            step_id="step-2",
            tool_name="connector.dispatch",
            action_kind="delivery.send",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "queued dispatch",
                "metadata": {"source": "tool"},
                "idempotency_key": "tool-dispatch-test",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "connector.dispatch"
    assert result.action_kind == "delivery.send"
    assert result.output_json["status"] == "queued"
    assert result.output_json["binding_id"] == binding.binding_id
    assert result.receipt_json["handler_key"] == "connector.dispatch"
    assert result.receipt_json["invocation_contract"] == "tool.v1"
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert any(row.delivery_id == result.target_ref for row in pending)


def test_connector_dispatch_builtin_schema_matches_executor_contract() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=ChannelRuntimeService(
            observations=InMemoryObservationEventRepository(),
            outbox=InMemoryDeliveryOutboxRepository(),
        ),
    )

    tool = tool_runtime.get_tool("connector.dispatch")

    assert service is not None
    assert tool is not None
    assert tuple(tool.input_schema_json.get("required") or ()) == CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS
    assert set(CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS).issubset(tool.input_schema_json["properties"])
    assert set(CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS).issubset(tool.input_schema_json["properties"])
    assert tool.policy_json["idempotency_key_policy"] == CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY


@pytest.mark.parametrize(
    ("missing_field", "expected_error"),
    [
        ("binding_id", "connector_binding_required:connector.dispatch"),
    ],
)
def test_connector_dispatch_executor_required_fields_match_declared_schema(
    missing_field: str,
    expected_error: str,
) -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-required-contract",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    payload = {
        "binding_id": binding.binding_id,
        "principal_id": "exec-1",
        "channel": "email",
        "recipient": "ops@example.com",
        "content": "queued dispatch",
    }
    payload.pop(missing_field)

    tool = tool_runtime.get_tool("connector.dispatch")

    assert tool is not None
    assert missing_field in tuple(tool.input_schema_json.get("required") or ())
    with pytest.raises(ToolExecutionError, match=expected_error):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-contract-1",
                step_id="step-contract-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json=payload,
                context_json={"principal_id": "exec-1"},
            )
        )


def test_connector_dispatch_executor_allows_missing_optional_idempotency_key() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-optional-idem",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    tool = tool_runtime.get_tool("connector.dispatch")
    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-optional-idem-1",
            step_id="step-optional-idem-1",
            tool_name="connector.dispatch",
            action_kind="delivery.send",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "queued dispatch",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert tool is not None
    assert "idempotency_key" not in tuple(tool.input_schema_json.get("required") or ())
    assert tool.policy_json["idempotency_key_policy"] == CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY
    assert result.output_json["idempotency_key"] == ""
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert any(row.delivery_id == result.target_ref and row.idempotency_key == "" for row in pending)


def test_connector_dispatch_executor_accepts_missing_payload_principal_when_request_principal_present() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-optional-principal",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-optional-principal-1",
            step_id="step-optional-principal-1",
            tool_name="connector.dispatch",
            action_kind="delivery.send",
            payload_json={
                "binding_id": binding.binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "queued dispatch",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.output_json["status"] == "queued"
    assert result.receipt_json["principal_id"] == "exec-1"


def test_connector_dispatch_executor_falls_back_to_builtin_allowed_channels_if_tool_definition_is_missing_it() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-fallback-channels",
        scope_json={"scopes": ["mail.send", "sms.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    tool_runtime.upsert_tool(
        tool_name="connector.dispatch",
        version="v1",
        input_schema_json={
            "type": "object",
            "required": ["binding_id", "channel", "recipient", "content"],
            "properties": {
                "binding_id": {"type": "string"},
                "channel": {"type": "string"},
                "recipient": {"type": "string"},
                "content": {"type": "string"},
            },
        },
        output_schema_json={
            "type": "object",
            "required": ["delivery_id", "status", "tool_name", "action_kind"],
        },
        policy_json={
            "builtin": True,
            "action_kind": "delivery.send",
            "idempotency_key_policy": CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
        },
        allowed_channels=(),
        approval_default="manager",
        enabled=True,
    )

    with pytest.raises(
        ToolExecutionError,
        match="connector_dispatch_channel_not_allowed:sms:email,slack,telegram",
    ):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-channel-fallback-1",
                step_id="step-channel-fallback-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "sms",
                    "recipient": "ops@example.com",
                    "content": "blocked by fallback channels",
                },
                context_json={"principal_id": "exec-1"},
            )
        )


def test_connector_dispatch_executor_rejects_missing_principal_id() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-missing-principal",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_id_required"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-missing-principal-1",
                step_id="step-missing-principal-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={},
            )
        )


def test_connector_dispatch_executor_rejects_context_principal_id_missing_even_if_payload_principal_present() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-missing-context-principal",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_id_required"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-missing-context-principal-1",
                step_id="step-missing-context-principal-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={},
            )
        )


def test_connector_dispatch_executor_rejects_disallowed_channel() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-disallowed-channel",
        scope_json={"scopes": ["mail.send", "sms.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(
        ToolExecutionError,
        match="connector_dispatch_channel_not_allowed:sms:email,slack,telegram",
    ):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-disallowed-channel-1",
                step_id="step-disallowed-channel-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "sms",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-1"},
            )
        )


def test_connector_dispatch_executor_prefers_scope_validation_before_channel_validation() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-disallowed-channel-no-scope",
        scope_json={"scopes": ["mail.readonly"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(
        ToolExecutionError,
        match="principal_scope_mismatch",
    ):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-disallowed-channel-before-scope-1",
                step_id="step-disallowed-channel-before-scope-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "push",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-1"},
            )
        )


def test_connector_dispatch_executor_rejects_principal_scope_mismatch() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-mismatch",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_scope_mismatch"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-dispatched-mismatch-1",
                step_id="step-dispatched-mismatch-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-2"},
            )
        )


def test_connector_dispatch_executor_normalizes_channel_for_allowed_channels() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-case",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-dispatched-case-1",
            step_id="step-dispatched-case-1",
            tool_name="connector.dispatch",
            action_kind="delivery.send",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "channel": "EMAIL",
                "recipient": "ops@example.com",
                "content": "queued dispatch",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.output_json["channel"] == "email"
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert any(row.delivery_id == result.target_ref and row.channel == "email" for row in pending)


def test_connector_dispatch_executor_enforces_sorted_allowed_channels_deterministically() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-disallowed-channel-order",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    tool_runtime.upsert_tool(
        tool_name="connector.dispatch",
        version="v1",
        input_schema_json={
            "type": "object",
            "required": ["binding_id", "channel", "recipient", "content"],
            "properties": {
                "binding_id": {"type": "string"},
                "channel": {"type": "string"},
                "recipient": {"type": "string"},
                "content": {"type": "string"},
                "metadata": {"type": "object"},
            },
        },
        output_schema_json={
            "type": "object",
            "required": ["delivery_id", "status", "tool_name", "action_kind"],
        },
        policy_json={
            "builtin": True,
            "action_kind": "delivery.send",
            "idempotency_key_policy": CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
        },
        allowed_channels=("telegram", "email", "slack"),
        approval_default="manager",
        enabled=True,
    )

    with pytest.raises(
        ToolExecutionError,
        match="connector_dispatch_channel_not_allowed:push:email,slack,telegram",
    ):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-disallowed-channel-order-1",
                step_id="step-disallowed-channel-order-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "push",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-1"},
            )
        )


def test_connector_dispatch_executor_rejects_request_principal_mismatch_even_when_payload_principal_present() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-dispatch-request-principal-mismatch",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_scope_mismatch"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-dispatch-request-principal-mismatch-1",
                step_id="step-dispatch-request-principal-mismatch-1",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "principal_id": "exec-1",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-2"},
            )
        )


def test_browseract_tool_dispatch_requires_request_principal_id_even_if_payload_supplies_mismatch() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_id_required"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-browseract-principal-missing-1",
                step_id="step-browseract-principal-missing-1",
                tool_name="browseract.extract_account_facts",
                action_kind="account.extract",
                payload_json={
                    "binding_id": binding.binding_id,
                    "service_name": "BrowserAct",
                    "principal_id": "exec-1",
                },
                context_json={},
            )
        )


def test_browseract_tool_dispatch_accepts_missing_payload_principal_when_request_principal_present() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-browseract-principal-optional-1",
            step_id="step-browseract-principal-optional-1",
            tool_name="browseract.extract_account_facts",
            action_kind="account.extract",
            payload_json={
                "binding_id": binding.binding_id,
                "service_name": "BrowserAct",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.receipt_json["principal_id"] == "exec-1"
    assert result.output_json["service_name"] == "BrowserAct"


def test_browseract_tool_dispatch_rejects_request_principal_scope_mismatch() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="^principal_scope_mismatch$"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-browseract-principal-mismatch-1",
                step_id="step-browseract-principal-mismatch-1",
                tool_name="browseract.extract_account_facts",
                action_kind="account.extract",
                payload_json={
                    "binding_id": binding.binding_id,
                    "service_name": "BrowserAct",
                    "principal_id": "exec-1",
                },
                context_json={"principal_id": "exec-2"},
            )
        )


def test_browseract_tool_dispatch_rejects_service_scope_mismatch() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError) as exc:
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-browseract-scope-mismatch-1",
                step_id="step-browseract-scope-mismatch-1",
                tool_name="browseract.extract_account_facts",
                action_kind="account.extract",
                payload_json={
                    "binding_id": binding.binding_id,
                    "service_name": "Teable",
                },
                context_json={"principal_id": "exec-1"},
            )
        )
    assert str(exc.value) == f"connector_binding_scope_mismatch:{binding.binding_id}:teable"


def test_tool_execution_service_executes_builtin_browseract_extract_handler() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct", "Teable"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                }
            }
        },
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-browseract-1",
            step_id="step-browseract-1",
            tool_name="browseract.extract_account_facts",
            action_kind="account.extract",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
                "instructions": "Use stored BrowserAct credentials",
                "account_hints_json": {"BrowserAct": {"workspace": "primary"}},
                "run_url": "https://browseract.example/run",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "browseract.extract_account_facts"
    assert result.action_kind == "account.extract"
    assert result.output_json["service_name"] == "BrowserAct"
    assert result.output_json["facts_json"]["tier"] == "Tier 3"
    assert result.output_json["account_email"] == "ops@example.com"
    assert result.output_json["missing_fields"] == []
    assert result.output_json["structured_output_json"]["verification_source"] == "connector_metadata"
    assert result.output_json["instructions"] == "Use stored BrowserAct credentials"
    assert result.output_json["account_hints_json"] == {"BrowserAct": {"workspace": "primary"}}
    assert result.output_json["requested_run_url"] == "https://browseract.example/run"
    assert result.output_json["structured_output_json"]["requested_run_url"] == "https://browseract.example/run"
    assert result.receipt_json["handler_key"] == "browseract.extract_account_facts"
    assert result.receipt_json["invocation_contract"] == "tool.v1"
    assert result.receipt_json["requested_run_url"] == "https://browseract.example/run"


def test_tool_execution_service_executes_builtin_browseract_inventory_handler() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct", "Teable", "UnknownService"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                },
                "Teable": {
                    "tier": "License Tier 4",
                    "account_email": "ops@teable.example",
                    "status": "activated",
                },
            }
        },
        status="enabled",
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-browseract-inventory-1",
            step_id="step-browseract-inventory-1",
            tool_name="browseract.extract_account_inventory",
            action_kind="account.extract_inventory",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
                "instructions": "Use stored BrowserAct credentials",
                "account_hints_json": {"Teable": {"workspace": "ops"}},
                "run_url": "https://browseract.example/run",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "browseract.extract_account_inventory"
    assert result.action_kind == "account.extract_inventory"
    assert result.output_json["service_names"] == ["BrowserAct", "Teable", "UnknownService"]
    assert result.output_json["missing_services"] == ["UnknownService"]
    assert result.output_json["instructions"] == "Use stored BrowserAct credentials"
    assert result.output_json["account_hints_json"] == {"Teable": {"workspace": "ops"}}
    assert result.output_json["requested_run_url"] == "https://browseract.example/run"
    assert len(result.output_json["services_json"]) == 3
    assert result.output_json["services_json"][0]["plan_tier"] == "Tier 3"
    assert result.output_json["services_json"][1]["account_email"] == "ops@teable.example"
    assert result.output_json["services_json"][1]["structured_output_json"]["account_hints_json"] == {
        "Teable": {"workspace": "ops"}
    }
    assert result.output_json["services_json"][2]["discovery_status"] == "missing"
    assert "Service: BrowserAct" in result.output_json["normalized_text"]
    assert "Service: UnknownService" in result.output_json["normalized_text"]
    assert result.receipt_json["handler_key"] == "browseract.extract_account_inventory"
    assert result.receipt_json["invocation_contract"] == "tool.v1"
    assert result.receipt_json["requested_run_url"] == "https://browseract.example/run"


def test_tool_execution_service_tolerates_live_browseract_inventory_fallback_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct", "UnknownService"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                }
            }
        },
        status="enabled",
    )

    def _boom(**_: object) -> dict[str, object] | None:
        raise ToolExecutionError("browseract_live_transport_error:offline")

    monkeypatch.setattr(service, "_browseract_live_extract", _boom)

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-browseract-inventory-2",
            step_id="step-browseract-inventory-2",
            tool_name="browseract.extract_account_inventory",
            action_kind="account.extract_inventory",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "service_names": ["BrowserAct", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
                "run_url": "https://browseract.example/run",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.output_json["missing_services"] == ["UnknownService"]
    assert result.output_json["services_json"][0]["plan_tier"] == "Tier 3"
    assert result.output_json["services_json"][1]["discovery_status"] == "missing"
    assert result.output_json["services_json"][1]["live_discovery_error"] == "browseract_live_transport_error:offline"
    assert result.output_json["services_json"][1]["structured_output_json"]["live_discovery_error"] == (
        "browseract_live_transport_error:offline"
    )


def test_tool_execution_service_rejects_foreign_connector_binding_scope() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-1",
        scope_json={"scopes": ["mail.readonly"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError) as exc:
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-3",
                step_id="step-3",
                tool_name="connector.dispatch",
                action_kind="delivery.send",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "content": "blocked dispatch",
                },
                context_json={"principal_id": "exec-1"},
            )
        )
    assert str(exc.value) == (
        f"connector_binding_scope_mismatch:{binding.binding_id}:email,email.send,mail,mail.send,send.mail"
    )


def test_tool_execution_service_rejects_connector_scope_mismatch() -> None:
    test_tool_execution_service_rejects_foreign_connector_binding_scope()


def test_tool_execution_service_rejects_foreign_browseract_binding_scope() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    with pytest.raises(ToolExecutionError, match="principal_scope_mismatch"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-browseract-2",
                step_id="step-browseract-2",
                tool_name="browseract.extract_account_facts",
                action_kind="account.extract",
                payload_json={
                    "binding_id": binding.binding_id,
                    "principal_id": "exec-1",
                    "service_name": "BrowserAct",
                },
                context_json={"principal_id": "exec-2"},
            )
        )


def test_tool_execution_service_self_heals_missing_builtin_artifact_definition() -> None:
    artifacts = InMemoryArtifactRepository()
    registry = InMemoryToolRegistryRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=registry,
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(tool_runtime=tool_runtime, artifacts=artifacts)

    registry._rows.clear()  # type: ignore[attr-defined]
    registry._order.clear()  # type: ignore[attr-defined]

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-4",
            step_id="step-4",
            tool_name="artifact_repository",
            action_kind="artifact.save",
            payload_json={"source_text": "self-healed artifact"},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "artifact_repository"
    assert tool_runtime.get_tool("artifact_repository") is not None
    saved = artifacts.get(result.target_ref)
    assert saved is not None
    assert saved.content == "self-healed artifact"


def test_tool_execution_service_self_heals_missing_builtin_connector_dispatch_definition() -> None:
    registry = InMemoryToolRegistryRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=registry,
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
        channel_runtime=channel_runtime,
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-self-heal",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    registry._rows.pop("connector.dispatch", None)  # type: ignore[attr-defined]
    registry._order = [key for key in registry._order if key != "connector.dispatch"]  # type: ignore[attr-defined]

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-5",
            step_id="step-5",
            tool_name="connector.dispatch",
            action_kind="delivery.send",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "self-healed dispatch",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "connector.dispatch"
    assert tool_runtime.get_tool("connector.dispatch") is not None


def test_tool_execution_service_self_heals_missing_builtin_browseract_definition() -> None:
    registry = InMemoryToolRegistryRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=registry,
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        auth_metadata_json={"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
        status="enabled",
    )

    registry._rows.pop("browseract.extract_account_facts", None)  # type: ignore[attr-defined]
    registry._order = [key for key in registry._order if key != "browseract.extract_account_facts"]  # type: ignore[attr-defined]

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-browseract-3",
            step_id="step-browseract-3",
            tool_name="browseract.extract_account_facts",
            action_kind="account.extract",
            payload_json={
                "binding_id": binding.binding_id,
                "principal_id": "exec-1",
                "service_name": "BrowserAct",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "browseract.extract_account_facts"
    assert tool_runtime.get_tool("browseract.extract_account_facts") is not None
