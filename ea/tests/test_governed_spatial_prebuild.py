from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path
import stat
import threading
from typing import Mapping

import app.services.governed_spatial_prebuild as prebuild_module

import pytest

from app.services.governed_spatial_prebuild import (
    DeterministicPropertyOutputAllocationPlanner,
    PROPERTY_ARTIFACT_AUTHORITY_CONTRACT,
    PROPERTY_EXECUTION_AUTHORITY_CONTRACT,
    PropertyAuthenticatedArtifactVerification,
    PropertyAuthenticatedExecutionEvidence,
    PropertyArtifactCandidate,
    PropertyArtifactVerificationEvidence,
    PropertyEvidenceAuthority,
    PropertyExecutionBoundary,
    PropertyExecutionEvidence,
    PropertyOutputAllocation,
    PropertyPrebuildCoordinator,
    PropertyPrebuildError,
    PropertyPrebuildPlan,
    PropertyPrebuildReconciliationStore,
    PropertyPrebuildSelection,
    PropertyReconciliationRecord,
    build_property_artifact_candidate,
)
from app.services.governed_spatial_crypto import (
    Ed25519EnvelopeSigner,
    Ed25519KeyRegistry,
    sign_envelope,
)
from app.services.governed_spatial_state import (
    DurableSpatialLedger,
    SpatialPrivacyError,
    payload_digest,
    utc_iso,
)
from ea.tests.test_governed_spatial_render import (
    NOW,
    FakePropertyInputAuthorityVerifier,
    FakePropertyPolicyVerifier,
    _assert_property_actions_zero,
    _compose_property,
    _digest,
    _property_context,
    _property_input_authority_verification,
    _property_policy_evidence,
    _property_policy_verification,
    _property_request_payload,
)


class CountingAllocationPlanner:
    def __init__(self) -> None:
        self.planning_calls = 0
        self.output_allocation_actions = 0
        self.filesystem_actions = 0
        self.quota_actions = 0
        self.adapter_actions = 0
        self.provider_actions = 0
        self.render_actions = 0
        self._delegate = DeterministicPropertyOutputAllocationPlanner()

    def __call__(self, plan: PropertyPrebuildPlan) -> PropertyOutputAllocation:
        self.planning_calls += 1
        return self._delegate(plan)


class FakeArtifactVerifier:
    def __init__(self, changes: Mapping[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.changes = dict(changes or {})
        self.artifact_verifier_actions = 0
        self.provider_actions = 0
        self.render_actions = 0

    def __call__(
        self, candidate: PropertyArtifactCandidate, *, observed_at: datetime
    ) -> PropertyArtifactVerificationEvidence:
        self.calls.append(candidate.as_dict())
        self.artifact_verifier_actions += 1
        material = candidate.as_dict()
        payload: dict[str, object] = {
            "contract_name": (
                "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
            ),
            "contract_version": "1.0.0",
            "plan_digest": material["plan_digest"],
            "allocation_digest": material["allocation_digest"],
            "execution_identity_digest": material["execution_identity_digest"],
            "execution_evidence_digest": material["execution_evidence_digest"],
            "artifact_identity_digest": material["artifact_identity_digest"],
            "artifact_digest": material["artifact_digest"],
            "verifier_identity_digest": _digest("independent-artifact-verifier"),
            "verification_profile_digest": material["verification_profile_digest"],
            "outcome_evidence_digest": _digest("artifact-verification-outcome"),
            "state": "verified",
            "verified_at": utc_iso(observed_at),
        }
        payload.update(self.changes)
        return PropertyArtifactVerificationEvidence.parse(payload)


_EXECUTION_IDENTITY = _digest("synthetic-adapter-evidence")
_ARTIFACT_VERIFIER_IDENTITY = _digest("independent-artifact-verifier")


def _authority_signer(kind: str, seed_byte: int) -> Ed25519EnvelopeSigner:
    return Ed25519EnvelopeSigner.from_seed(
        bytes([seed_byte]) * 32,
        issuer=f"propertyquarry-test-{kind}-authority",
        environment="test",
        key_ref=f"propertyquarry-{kind}-authority-v1",
        key_epoch=1,
        not_before="2026-07-01T00:00:00Z",
        not_after="2026-08-01T00:00:00Z",
    )


def _authority_bundle() -> dict[str, object]:
    execution_signer = _authority_signer("execution", 71)
    artifact_signer = _authority_signer("artifact", 73)
    execution_record = execution_signer.key_record
    artifact_record = artifact_signer.key_record
    return {
        "registry": Ed25519KeyRegistry(
            [execution_record, artifact_record]
        ),
        "execution_signer": execution_signer,
        "artifact_signer": artifact_signer,
        "execution": PropertyEvidenceAuthority(
            authority_kind="execution",
            issuer=execution_record.issuer,
            environment=execution_record.environment,
            key_ref=execution_record.key_ref,
            key_epoch=execution_record.key_epoch,
            identity_digest=_EXECUTION_IDENTITY,
            authority_receipt_digest=_digest("trusted-execution-authority-v1"),
        ),
        "artifact": PropertyEvidenceAuthority(
            authority_kind="artifact_verification",
            issuer=artifact_record.issuer,
            environment=artifact_record.environment,
            key_ref=artifact_record.key_ref,
            key_epoch=artifact_record.key_epoch,
            identity_digest=_ARTIFACT_VERIFIER_IDENTITY,
            authority_receipt_digest=_digest("trusted-artifact-authority-v1"),
        ),
    }


def _enable_evidence_authority(
    prepared: dict[str, object],
    *,
    artifact_verifier: object | None = None,
) -> PropertyPrebuildCoordinator:
    base = prepared["coordinator"]
    assert isinstance(base, PropertyPrebuildCoordinator)
    bundle = _authority_bundle()
    coordinator = PropertyPrebuildCoordinator(
        ledger=base._ledger,
        material_store=base._material_store,
        receipt_verifier=base._receipt_verifier,
        policy_verifier=base._policy_verifier,
        input_authority_verifier=base._input_authority_verifier,
        output_allocation_planner=base._allocator,
        artifact_verifier=artifact_verifier,  # type: ignore[arg-type]
        reconciliation_store=base._reconciliation_store,
        telemetry_sink=base._telemetry_sink,
        now=base._now,
        evidence_authority_registry=bundle["registry"],  # type: ignore[arg-type]
        execution_evidence_authority=bundle["execution"],  # type: ignore[arg-type]
        artifact_evidence_authority=bundle["artifact"],  # type: ignore[arg-type]
    )
    prepared["coordinator"] = coordinator
    prepared["authority_bundle"] = bundle
    return coordinator


def _authority_expiry(observed_at: datetime) -> str:
    return utc_iso(observed_at + timedelta(minutes=4))


def _authenticated_execution(
    prepared: Mapping[str, object],
    plan: PropertyPrebuildPlan,
    allocation: PropertyOutputAllocation,
    boundary: PropertyExecutionBoundary,
    *,
    observed_at: datetime = NOW,
    evidence_changes: Mapping[str, object] | None = None,
    authority_changes: Mapping[str, object] | None = None,
) -> PropertyAuthenticatedExecutionEvidence:
    coordinator = prepared["coordinator"]
    bundle = prepared["authority_bundle"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    assert isinstance(bundle, Mapping)
    authority = bundle["execution"]
    signer = bundle["execution_signer"]
    assert isinstance(authority, PropertyEvidenceAuthority)
    assert isinstance(signer, Ed25519EnvelopeSigner)
    evidence_payload = _execution_evidence(plan, allocation, boundary).as_dict()
    evidence_payload.update(dict(evidence_changes or {}))
    evidence = PropertyExecutionEvidence.parse(evidence_payload)
    receipt = prepared["context"]["ledger"].find_composition(  # type: ignore[index,union-attr]
        plan["composition_digest"]
    )
    assert receipt is not None
    evidence_material = evidence.as_dict()
    authority_payload: dict[str, object] = {
        "contract_name": PROPERTY_EXECUTION_AUTHORITY_CONTRACT,
        "contract_version": "1.0.0",
        "issuer": authority.issuer,
        "environment": authority.environment,
        "issued_at": utc_iso(observed_at),
        "expires_at": _authority_expiry(observed_at),
        "authority_identity_digest": authority.identity_digest,
        "authority_receipt_digest": authority.authority_receipt_digest,
        "ledger_scope_digest": coordinator._ledger_scope_digest,
        "composition_digest": plan["composition_digest"],
        "plan_digest": plan.digest,
        "allocation_digest": allocation.digest,
        "execution_boundary_digest": boundary.digest,
        "execution_identity_digest": boundary["execution_identity_digest"],
        "adapter_identity_digest": evidence_material["adapter_identity_digest"],
        "execution_evidence_digest": evidence.digest,
        "output_digest": evidence_material["output_digest"],
        "operation_id": evidence_material["operation_id"],
        "observed_at": utc_iso(observed_at),
    }
    authority_payload.update(dict(authority_changes or {}))
    return PropertyAuthenticatedExecutionEvidence.bind(
        evidence, sign_envelope(authority_payload, signer)
    )


def _authenticated_artifact(
    prepared: Mapping[str, object],
    plan: PropertyPrebuildPlan,
    allocation: PropertyOutputAllocation,
    boundary: PropertyExecutionBoundary,
    execution: PropertyAuthenticatedExecutionEvidence,
    candidate: PropertyArtifactCandidate,
    *,
    observed_at: datetime = NOW,
    evidence_changes: Mapping[str, object] | None = None,
    authority_changes: Mapping[str, object] | None = None,
) -> PropertyAuthenticatedArtifactVerification:
    coordinator = prepared["coordinator"]
    bundle = prepared["authority_bundle"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    assert isinstance(bundle, Mapping)
    authority = bundle["artifact"]
    signer = bundle["artifact_signer"]
    assert isinstance(authority, PropertyEvidenceAuthority)
    assert isinstance(signer, Ed25519EnvelopeSigner)
    execution_material = execution.evidence.as_dict()
    candidate_material = candidate.as_dict()
    evidence_payload: dict[str, object] = {
        "contract_name": (
            "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
        ),
        "contract_version": "1.0.0",
        "plan_digest": plan.digest,
        "allocation_digest": allocation.digest,
        "execution_identity_digest": boundary["execution_identity_digest"],
        "execution_evidence_digest": execution.evidence.digest,
        "artifact_identity_digest": candidate_material["artifact_identity_digest"],
        "artifact_digest": candidate_material["artifact_digest"],
        "verifier_identity_digest": authority.identity_digest,
        "verification_profile_digest": candidate_material[
            "verification_profile_digest"
        ],
        "outcome_evidence_digest": _digest("artifact-verification-outcome"),
        "state": "verified",
        "verified_at": utc_iso(observed_at),
    }
    evidence_payload.update(dict(evidence_changes or {}))
    evidence = PropertyArtifactVerificationEvidence.parse(evidence_payload)
    authority_payload: dict[str, object] = {
        "contract_name": PROPERTY_ARTIFACT_AUTHORITY_CONTRACT,
        "contract_version": "1.0.0",
        "issuer": authority.issuer,
        "environment": authority.environment,
        "issued_at": utc_iso(observed_at),
        "expires_at": _authority_expiry(observed_at),
        "authority_identity_digest": authority.identity_digest,
        "authority_receipt_digest": authority.authority_receipt_digest,
        "ledger_scope_digest": coordinator._ledger_scope_digest,
        "composition_digest": plan["composition_digest"],
        "plan_digest": plan.digest,
        "allocation_digest": allocation.digest,
        "execution_boundary_digest": boundary.digest,
        "execution_identity_digest": boundary["execution_identity_digest"],
        "execution_evidence_digest": execution.evidence.digest,
        "execution_authority_receipt_digest": payload_digest(
            execution.authority_receipt()
        ),
        "execution_output_digest": execution_material["output_digest"],
        "candidate_digest": candidate.digest,
        "allocation_slot_ref": candidate_material["allocation_slot_ref"],
        "artifact_identity_digest": candidate_material["artifact_identity_digest"],
        "artifact_digest": candidate_material["artifact_digest"],
        "verification_profile_digest": candidate_material[
            "verification_profile_digest"
        ],
        "verification_evidence_digest": evidence.digest,
        "decision": (
            "accepted" if evidence["state"] == "verified" else "rejected"
        ),
        "observed_at": utc_iso(observed_at),
    }
    authority_payload.update(dict(authority_changes or {}))
    return PropertyAuthenticatedArtifactVerification.bind(
        evidence, sign_envelope(authority_payload, signer)
    )


class AuthenticatedArtifactVerifier(FakeArtifactVerifier):
    def __init__(self, changes: Mapping[str, object] | None = None) -> None:
        super().__init__(changes)
        self.prepared: Mapping[str, object] | None = None
        self.plan: PropertyPrebuildPlan | None = None
        self.allocation: PropertyOutputAllocation | None = None
        self.boundary: PropertyExecutionBoundary | None = None
        self.execution: PropertyAuthenticatedExecutionEvidence | None = None

    def configure(
        self,
        prepared: Mapping[str, object],
        plan: PropertyPrebuildPlan,
        allocation: PropertyOutputAllocation,
        boundary: PropertyExecutionBoundary,
        execution: PropertyAuthenticatedExecutionEvidence,
    ) -> None:
        self.prepared = prepared
        self.plan = plan
        self.allocation = allocation
        self.boundary = boundary
        self.execution = execution

    def __call__(
        self, candidate: PropertyArtifactCandidate, *, observed_at: datetime
    ) -> PropertyAuthenticatedArtifactVerification:
        self.calls.append(candidate.as_dict())
        self.artifact_verifier_actions += 1
        assert self.prepared is not None
        assert self.plan is not None
        assert self.allocation is not None
        assert self.boundary is not None
        assert self.execution is not None
        return _authenticated_artifact(
            self.prepared,
            self.plan,
            self.allocation,
            self.boundary,
            self.execution,
            candidate,
            observed_at=observed_at,
            evidence_changes=self.changes,
        )


class HookedAuthenticatedArtifactVerifier(AuthenticatedArtifactVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.hook: object | None = None

    def __call__(
        self, candidate: PropertyArtifactCandidate, *, observed_at: datetime
    ) -> PropertyAuthenticatedArtifactVerification:
        result = super().__call__(candidate, observed_at=observed_at)
        if callable(self.hook):
            self.hook()
        return result


class HookedMapping(Mapping[str, object]):
    def __init__(self, material: Mapping[str, object], hook: object) -> None:
        self._material = dict(material)
        self._hook = hook
        self._triggered = False

    def _trigger(self) -> None:
        if not self._triggered and callable(self._hook):
            self._triggered = True
            self._hook()

    def __getitem__(self, key: str) -> object:
        self._trigger()
        return self._material[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        self._trigger()
        return iter(self._material)

    def __len__(self) -> int:
        self._trigger()
        return len(self._material)

    def items(self):  # type: ignore[no-untyped-def]
        self._trigger()
        return self._material.items()


class RaisingMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("/private/provider/credential-do-not-leak")

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("/private/provider/credential-do-not-leak")

    def __len__(self) -> int:
        raise RuntimeError("/private/provider/credential-do-not-leak")

    def items(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("/private/provider/credential-do-not-leak")


class PrivacyInjectingPolicyVerifier(FakePropertyPolicyVerifier):
    def __init__(self, outcomes: list[object]) -> None:
        super().__init__(outcomes)
        self.hook: object | None = None

    def __call__(self, **kwargs: object) -> object:
        result = super().__call__(**kwargs)  # type: ignore[arg-type]
        if len(self.calls) == 3 and callable(self.hook):
            self.hook()
        return result


def _selection(
    context: Mapping[str, object], result: Mapping[str, object]
) -> PropertyPrebuildSelection:
    receipt = context["ledger"].find_composition(result["composition_digest"])  # type: ignore[union-attr]
    assert receipt is not None
    return PropertyPrebuildSelection.parse(
        {
            "contract_name": "propertyquarry.governed_spatial_prebuild_selection.v1",
            "contract_version": "1.0.0",
            "request_id": receipt["request_id"],
            "idempotency_key": receipt["idempotency_key"],
            "composition_digest": receipt["composition_digest"],
            "composition_receipt_digest": payload_digest(receipt),
            "material_identity": receipt["material_identity"],
            "material_digest": receipt["material_digest"],
        }
    )


def _coordinator(
    context: Mapping[str, object],
    tmp_path: Path,
    *,
    allocator: CountingAllocationPlanner | None = None,
    artifact_verifier: FakeArtifactVerifier | None = None,
    reconciliation_root: Path | None = None,
) -> tuple[PropertyPrebuildCoordinator, PropertyPrebuildReconciliationStore]:
    store = PropertyPrebuildReconciliationStore(
        reconciliation_root or tmp_path / "property-prebuild-state",
        lifecycle_authority=context["ledger"].lifecycle_authority,  # type: ignore[union-attr]
    )
    coordinator = context["orchestrator"].property_prebuild_coordinator(  # type: ignore[union-attr]
        output_allocation_planner=allocator,
        artifact_verifier=artifact_verifier,
        reconciliation_store=store,
    )
    return coordinator, store


def _prepared(
    tmp_path: Path,
    *,
    policy_verifier: FakePropertyPolicyVerifier | None = None,
    input_verifier: FakePropertyInputAuthorityVerifier | None = None,
    allocator: CountingAllocationPlanner | None = None,
    artifact_verifier: FakeArtifactVerifier | None = None,
) -> dict[str, object]:
    evidence = _property_policy_evidence()
    context = _property_context(
        tmp_path,
        evidence=evidence,
        verifier=policy_verifier,
        input_verifier=input_verifier
        if input_verifier is not None
        else FakePropertyInputAuthorityVerifier(),
    )
    result = _compose_property(context)
    selection = _selection(context, result)
    coordinator, reconciliation_store = _coordinator(
        context,
        tmp_path,
        allocator=allocator,
        artifact_verifier=artifact_verifier,
    )
    return {
        "context": context,
        "result": result,
        "selection": selection,
        "coordinator": coordinator,
        "reconciliation_store": reconciliation_store,
        "evidence": evidence,
    }


def _resolve(prepared: Mapping[str, object], *, observed_at: datetime = NOW) -> PropertyPrebuildPlan:
    return prepared["coordinator"].resolve_plan(  # type: ignore[union-attr]
        prepared["selection"],
        policy_evidence=prepared["evidence"],
        observed_at=observed_at,
    )


def _allocation_and_boundary(
    prepared: Mapping[str, object], plan: PropertyPrebuildPlan
) -> tuple[PropertyOutputAllocation, PropertyExecutionBoundary]:
    coordinator = prepared["coordinator"]
    allocation = coordinator.plan_output_allocation(  # type: ignore[union-attr]
        prepared["selection"],
        plan=plan,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    boundary = coordinator.prepare_execution_boundary(  # type: ignore[union-attr]
        prepared["selection"],
        plan=plan,
        allocation=allocation,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    return allocation, boundary


def _callback_phase_invocation(
    prepared: dict[str, object],
    phase: str,
    hook: object,
) -> object:
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)

    if phase == "material":
        material_store = prepared["context"]["store"]  # type: ignore[index]
        original_load = material_store.load

        def load(*args: object, **kwargs: object) -> Mapping[str, object]:
            material = original_load(*args, **kwargs)
            return HookedMapping(material.model_dump(mode="json"), hook)

        material_store.load = load

        def invoke_material() -> object:
            return _resolve(prepared)

        return invoke_material

    if phase in {"receipt", "policy", "input"}:
        attribute = {
            "receipt": "_receipt_verifier",
            "policy": "_policy_verifier",
            "input": "_input_authority_verifier",
        }[phase]
        original = getattr(coordinator, attribute)

        def wrapped(*args: object, **kwargs: object) -> object:
            result = original(*args, **kwargs)
            if callable(hook):
                hook()
            return result

        setattr(coordinator, attribute, wrapped)

        def invoke_authority() -> object:
            return _resolve(prepared)

        return invoke_authority

    plan = _resolve(prepared)
    if phase == "planner":
        original_allocator = coordinator._allocator

        def allocator(exact_plan: PropertyPrebuildPlan) -> PropertyOutputAllocation:
            result = original_allocator(exact_plan)
            if callable(hook):
                hook()
            return result

        coordinator._allocator = allocator

        def invoke_planner() -> object:
            return coordinator.plan_output_allocation(
                prepared["selection"],
                plan=plan,
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )

        return invoke_planner

    if phase == "telemetry":
        def telemetry(_: Mapping[str, object]) -> None:
            if callable(hook):
                hook()

        coordinator._telemetry_sink = telemetry

        def invoke_telemetry() -> object:
            return coordinator.plan_output_allocation(
                prepared["selection"],
                plan=plan,
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )

        return invoke_telemetry

    if phase == "mapping":
        supplied = HookedMapping(plan.as_dict(), hook)

        def invoke_mapping() -> object:
            return coordinator.plan_output_allocation(
                prepared["selection"],
                plan=supplied,
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )

        return invoke_mapping

    allocation, boundary = _allocation_and_boundary(prepared, plan)
    if phase == "reconciliation":
        store = prepared["reconciliation_store"]
        assert isinstance(store, PropertyPrebuildReconciliationStore)
        original_prevalidate = store._prevalidate_append

        def prevalidate(**kwargs: object) -> dict[str, object]:
            result = original_prevalidate(**kwargs)  # type: ignore[arg-type]
            if callable(hook):
                hook()
            return result

        store._prevalidate_append = prevalidate  # type: ignore[method-assign]

        def invoke_reconciliation() -> object:
            return coordinator.reconcile(
                prepared["selection"],
                reconciliation_key="reconciliation:callback-mutation:v1",
                plan=plan,
                allocation=allocation,
                boundary=boundary,
                state="planned",
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )

        return invoke_reconciliation

    if phase == "verifier":
        verifier = coordinator._artifact_verifier
        assert isinstance(verifier, HookedAuthenticatedArtifactVerifier)
        execution = _authenticated_execution(prepared, plan, allocation, boundary)
        slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
        candidate = build_property_artifact_candidate(
            boundary=boundary,
            execution_evidence=execution.evidence,
            allocation_slot_ref=slot_ref,
            artifact_ref="artifact:callback-mutation:v1",
            artifact_digest=execution.evidence["output_digest"],  # type: ignore[arg-type]
            verification_profile_digest=_digest("callback-verification-profile"),
        )
        verifier.configure(prepared, plan, allocation, boundary, execution)
        verifier.hook = hook

        def invoke_verifier() -> object:
            return coordinator.verify_artifact_evidence(
                prepared["selection"],
                plan=plan,
                allocation=allocation,
                boundary=boundary,
                execution_evidence=execution,
                candidate=candidate,
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )

        return invoke_verifier

    raise AssertionError(f"unknown callback phase: {phase}")


def _execution_evidence(
    plan: PropertyPrebuildPlan,
    allocation: PropertyOutputAllocation,
    boundary: PropertyExecutionBoundary,
) -> PropertyExecutionEvidence:
    return PropertyExecutionEvidence.parse(
        {
            "contract_name": "propertyquarry.governed_spatial_execution_evidence.v1",
            "contract_version": "1.0.0",
            "execution_identity_digest": boundary["execution_identity_digest"],
            "execution_boundary_digest": boundary.digest,
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "adapter_identity_digest": _digest("synthetic-adapter-evidence"),
            "operation_id": "operation:synthetic-evidence:v1",
            "state": "succeeded",
            "output_digest": _digest("synthetic-output"),
            "output_manifest_ref": "manifest:synthetic-output:v1",
            "private_execution_receipt_digest": _digest("private-execution-receipt"),
            "provider_action_count": 1,
        }
    )


def _assert_external_actions_zero(
    context: Mapping[str, object],
    allocator: CountingAllocationPlanner,
    verifier: FakeArtifactVerifier,
) -> None:
    _assert_property_actions_zero(context)
    assert allocator.output_allocation_actions == 0
    assert allocator.filesystem_actions == 0
    assert allocator.quota_actions == 0
    assert allocator.adapter_actions == 0
    assert allocator.provider_actions == 0
    assert allocator.render_actions == 0
    assert verifier.provider_actions == 0
    assert verifier.render_actions == 0


def test_prebuild_happy_path_is_canonical_immutable_and_zero_live_action(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=verifier
    )
    context = prepared["context"]
    receipt_before = context["ledger"].find_composition(  # type: ignore[union-attr]
        prepared["result"]["composition_digest"]  # type: ignore[index]
    )
    assert receipt_before is not None
    receipt_digest_before = payload_digest(receipt_before)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    material_journal_before = journal.read_bytes()

    plan = _resolve(prepared)
    replay = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)

    assert plan.canonical_bytes() == replay.canonical_bytes()
    assert plan.digest == replay.digest
    assert plan["retention_anchor"] == "2026-07-11T09:30:00Z"
    assert plan["source_packet_created_at"] == "2026-07-11T09:30:00Z"
    assert plan["compose_acceptance_at"] == "2026-07-11T10:00:00Z"
    assert allocation["filesystem_actions"] == 0
    assert allocation["quota_actions"] == 0
    assert allocation["adapter_actions"] == 0
    assert allocation["provider_actions"] == 0
    assert boundary["adapter_invoked"] is False
    assert boundary["provider_actions"] == 0
    assert boundary["render_actions"] == 0
    assert allocator.planning_calls == 1
    assert verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    assert journal.read_bytes() == material_journal_before

    receipt_after = context["ledger"].find_composition(  # type: ignore[union-attr]
        prepared["result"]["composition_digest"]  # type: ignore[index]
    )
    assert receipt_after == receipt_before
    assert payload_digest(receipt_after) == receipt_digest_before
    forbidden_receipt_members = {
        "availability",
        "build_state",
        "output_allocation",
        "readiness",
        "reconciliation",
    }
    assert not forbidden_receipt_members & set(receipt_after)
    lowered = plan.canonical_bytes().lower()
    for fragment in (
        b"provider_url",
        b"signed_url",
        b"credential",
        b"readiness",
        b"availability",
        b"/docker/",
        b"://",
    ):
        assert fragment not in lowered
    _assert_external_actions_zero(context, allocator, verifier)


def test_complete_gate_uses_one_verifier_call_per_required_recheck_boundary(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    counts = {"receipt": 0, "policy": 0, "input": 0}
    observed: dict[str, list[datetime]] = {
        "receipt": [],
        "policy": [],
        "input": [],
    }

    def counted(name: str, callback: object) -> object:
        def invoke(*args: object, **kwargs: object) -> object:
            counts[name] += 1
            observed[name].append(kwargs["observed_at"])  # type: ignore[arg-type]
            return callback(*args, **kwargs)  # type: ignore[operator]

        return invoke

    coordinator._receipt_verifier = counted(  # type: ignore[assignment]
        "receipt", coordinator._receipt_verifier
    )
    coordinator._policy_verifier = counted(  # type: ignore[assignment]
        "policy", coordinator._policy_verifier
    )
    coordinator._input_authority_verifier = counted(  # type: ignore[assignment]
        "input", coordinator._input_authority_verifier
    )
    _resolve(prepared)

    assert counts == {"receipt": 3, "policy": 3, "input": 2}
    assert all(sample == NOW for values in observed.values() for sample in values)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("missing", "property_prebuild_policy_missing"),
        ("stale", "property_prebuild_policy_stale"),
        ("digest_mismatched", "property_prebuild_policy_digest_mismatched"),
        ("mode_mismatched", "property_prebuild_policy_mode_mismatched"),
        ("expired", "property_prebuild_policy_expired"),
        ("revoked", "property_prebuild_policy_revoked"),
        ("unverifiable", "property_prebuild_policy_unverifiable"),
    ],
)
def test_each_policy_evidence_state_blocks_before_every_downstream_action(
    tmp_path: Path, state: str, reason: str,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    policy_verifier = FakePropertyPolicyVerifier([valid])
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path,
        policy_verifier=policy_verifier,
        allocator=allocator,
        artifact_verifier=artifact_verifier,
    )
    plan = _resolve(prepared)
    policy_verifier.outcomes = [replace(valid, state=state)]
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(PropertyPrebuildError, match=reason):
        prepared["coordinator"].plan_output_allocation(  # type: ignore[union-attr]
            prepared["selection"],
            plan=plan,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )

    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert artifact_verifier.artifact_verifier_actions == 0
    assert journal.read_bytes() == before
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(prepared["context"], allocator, artifact_verifier)  # type: ignore[arg-type]


def test_wrong_ledger_same_scope_is_rejected_before_any_boundary_call(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    context = prepared["context"]
    receipt = context["ledger"].find_composition(  # type: ignore[union-attr]
        prepared["result"]["composition_digest"]  # type: ignore[index]
    )
    assert receipt is not None
    wrong_ledger = DurableSpatialLedger(tmp_path / "wrong-ledger")
    wrong_ledger.save_composition(receipt)
    calls = {"receipt": 0, "policy": 0, "input": 0}

    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_lifecycle_authority_mismatch"
    ):
        PropertyPrebuildCoordinator(
            ledger=wrong_ledger,
            material_store=context["store"],  # type: ignore[arg-type]
            receipt_verifier=lambda *args, **kwargs: calls.__setitem__("receipt", 1),
            policy_verifier=lambda *args, **kwargs: calls.__setitem__("policy", 1),
            input_authority_verifier=lambda *args, **kwargs: calls.__setitem__("input", 1),
            output_allocation_planner=allocator,
            artifact_verifier=artifact_verifier,
        )

    assert calls == {"receipt": 0, "policy": 0, "input": 0}
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(context, allocator, artifact_verifier)


def test_privacy_after_compose_preempts_policy_material_and_all_downstream_effects(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    plan = _resolve(prepared)
    context = prepared["context"]
    policy_calls = len(context["verifier"].calls)  # type: ignore[union-attr]
    context["ledger"].record_privacy_action(  # type: ignore[union-attr]
        scope_digest=prepared["result"]["composition_digest"],  # type: ignore[index]
        action="deleted",
        reason_digest=_digest("privacy-after-compose"),
        observed_at=NOW,
    )
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(
        SpatialPrivacyError, match="property_prebuild_privacy_tombstone_active"
    ):
        prepared["coordinator"].plan_output_allocation(  # type: ignore[union-attr]
            prepared["selection"],
            plan=plan,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )

    assert len(context["verifier"].calls) == policy_calls  # type: ignore[union-attr]
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(context, allocator, artifact_verifier)


@pytest.mark.parametrize(
    "condition",
    [
        "stale",
        "source_digest",
        "source_receipt",
        "style_digest",
        "style_receipt",
        "asset_digest",
        "asset_receipt",
    ],
)
def test_current_source_style_and_ordered_asset_authority_failures_are_zero_effect(
    tmp_path: Path, condition: str,
) -> None:
    valid = _property_input_authority_verification()
    changes: dict[str, object]
    if condition == "stale":
        changes = {"state": "stale"}
    elif condition == "source_digest":
        changes = {"source_packet_digest": _digest("changed-source")}
    elif condition == "source_receipt":
        changes = {"source_authority_receipt_digest": _digest("changed-source-receipt")}
    elif condition == "style_digest":
        changes = {"style_snapshot_digest": _digest("changed-style")}
    elif condition == "style_receipt":
        changes = {"style_registry_receipt_digest": _digest("changed-style-receipt")}
    elif condition == "asset_digest":
        changes = {"asset_bindings_digest": _digest("changed-ordered-assets")}
    else:
        changes = {"asset_authority_receipt_digest": _digest("changed-asset-receipt")}
    bad = replace(valid, **changes)
    input_verifier = FakePropertyInputAuthorityVerifier([valid])
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path,
        input_verifier=input_verifier,
        allocator=allocator,
        artifact_verifier=artifact_verifier,
    )
    input_verifier.outcomes = [bad]
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(
        PropertyPrebuildError,
        match="property_prebuild_input_authority_(?:unverifiable|mismatch)",
    ):
        _resolve(prepared)

    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(prepared["context"], allocator, artifact_verifier)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "request_id",
        "idempotency_key",
        "composition_receipt_digest",
        "material_identity",
        "material_digest",
    ],
)
def test_selection_request_receipt_and_material_identity_mismatch_fail_before_policy(
    tmp_path: Path, field: str,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    context = prepared["context"]
    policy_calls = len(context["verifier"].calls)  # type: ignore[union-attr]
    supplied = prepared["selection"].as_dict()  # type: ignore[union-attr]
    replacements = {
        "request_id": "4b5f63bf-d590-456d-b693-226aec5d403f",
        "idempotency_key": "property-tour-conflict-v1",
        "composition_receipt_digest": _digest("wrong-receipt"),
        "material_identity": "material:" + "a" * 64,
        "material_digest": _digest("wrong-material"),
    }
    supplied[field] = replacements[field]
    selection = PropertyPrebuildSelection.parse(supplied)

    with pytest.raises(PropertyPrebuildError):
        prepared["coordinator"].resolve_plan(  # type: ignore[union-attr]
            selection,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )

    assert len(context["verifier"].calls) == policy_calls  # type: ignore[union-attr]
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(context, allocator, artifact_verifier)


class ReceiptOverrideLedger(DurableSpatialLedger):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.override: dict[str, object] | None = None

    def find_composition(self, digest: str) -> dict[str, object] | None:
        if self.override is not None:
            return deepcopy(self.override)
        return super().find_composition(digest)


def test_signed_receipt_tamper_is_rejected_before_policy_or_material_effect(
    tmp_path: Path,
) -> None:
    ledger = ReceiptOverrideLedger(tmp_path / "override-ledger")
    context = _property_context(tmp_path, ledger=ledger)
    result = _compose_property(context)
    receipt = ledger.find_composition(result["composition_digest"])
    assert receipt is not None
    tampered = deepcopy(receipt)
    tampered["style_snapshot_digest"] = _digest("tampered-style")
    ledger.override = tampered
    selection = _selection(context, result).as_dict()
    selection["composition_receipt_digest"] = payload_digest(tampered)
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    coordinator, _ = _coordinator(
        context,
        tmp_path,
        allocator=allocator,
        artifact_verifier=artifact_verifier,
    )
    policy_calls = len(context["verifier"].calls)  # type: ignore[union-attr]
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_receipt_unverifiable"
    ):
        coordinator.resolve_plan(
            selection, policy_evidence=context["evidence"], observed_at=NOW
        )

    assert len(context["verifier"].calls) == policy_calls  # type: ignore[union-attr]
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    _assert_external_actions_zero(context, allocator, artifact_verifier)


def test_material_tamper_is_static_redacted_and_zero_downstream_action(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    store = prepared["context"]["store"]  # type: ignore[index]
    original_load = store.load

    def tampered_load(*args: object, **kwargs: object) -> object:
        material = original_load(*args, **kwargs)
        return material.model_copy(update={"request_digest": _digest("tampered-material")})

    store.load = tampered_load
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_material_invalid"
    ) as caught:
        _resolve(prepared)

    assert "tampered-material" not in str(caught.value)
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    _assert_external_actions_zero(prepared["context"], allocator, artifact_verifier)  # type: ignore[arg-type]


def test_persistent_ledger_integrity_failure_precedes_every_authority_callback(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    context = prepared["context"]
    policy_calls = len(context["verifier"].calls)  # type: ignore[union-attr]
    index_path = tmp_path / "property-ledger" / "index.json"
    index_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_ledger_integrity_invalid"
    ):
        _resolve(prepared)

    assert len(context["verifier"].calls) == policy_calls  # type: ignore[union-attr]
    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(context, allocator, artifact_verifier)


@pytest.mark.parametrize("attack", ["expired", "clock_rollback"])
def test_expiry_and_clock_rollback_fail_before_all_downstream_actions(
    tmp_path: Path, attack: str,
) -> None:
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=artifact_verifier
    )
    observed = NOW + timedelta(hours=13) if attack == "expired" else NOW - timedelta(hours=2)
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(PropertyPrebuildError):
        _resolve(prepared, observed_at=observed)

    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(prepared["context"], allocator, artifact_verifier)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "attack",
    [
        "malformed_digest",
        "unknown_member",
        "url",
        "absolute_path",
        "secret_field",
        "noncanonical_plan",
    ],
)
def test_malformed_noncanonical_unknown_and_injected_values_are_redacted(
    tmp_path: Path, attack: str,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    injected = "https://provider.invalid/private?secret=do-not-leak"
    with pytest.raises(PropertyPrebuildError) as caught:
        if attack == "malformed_digest":
            payload = prepared["selection"].as_dict()  # type: ignore[union-attr]
            payload["material_digest"] = "sha256:not-a-digest"
            PropertyPrebuildSelection.parse(payload)
        elif attack == "unknown_member":
            payload = prepared["selection"].as_dict()  # type: ignore[union-attr]
            payload["unknown"] = injected
            PropertyPrebuildSelection.parse(payload)
        elif attack == "url":
            payload = prepared["selection"].as_dict()  # type: ignore[union-attr]
            payload["idempotency_key"] = injected
            PropertyPrebuildSelection.parse(payload)
        elif attack == "absolute_path":
            payload = prepared["selection"].as_dict()  # type: ignore[union-attr]
            payload["material_identity"] = "/tmp/private-material"
            PropertyPrebuildSelection.parse(payload)
        elif attack == "secret_field":
            payload = plan.as_dict()
            payload["provider_url"] = injected
            PropertyPrebuildPlan.parse(payload)
        else:
            PropertyPrebuildPlan.parse(
                json.dumps(plan.as_dict(), indent=2, sort_keys=False)
            )

    assert injected not in str(caught.value)
    assert "do-not-leak" not in str(caught.value)
    assert not (tmp_path / "property-prebuild-state").exists()


def test_replay_restart_concurrency_and_composition_scope_are_deterministic(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    prepared = _prepared(tmp_path, allocator=allocator)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    coordinator = prepared["coordinator"]
    journal_before = (
        tmp_path / "property-material" / "material.journal.jsonl"
    ).read_bytes()

    def append_once(_: int) -> object:
        return coordinator.reconcile(  # type: ignore[union-attr]
            prepared["selection"],
            reconciliation_key="reconciliation:concurrent:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(append_once, range(8)))

    assert sum(not result.idempotent_replay for result in results) == 1
    assert len({result.record.record_digest for result in results}) == 1
    assert (
        tmp_path / "property-material" / "material.journal.jsonl"
    ).read_bytes() == journal_before

    restarted_store = PropertyPrebuildReconciliationStore(
        tmp_path / "property-prebuild-state",
        lifecycle_authority=prepared["context"]["ledger"].lifecycle_authority,  # type: ignore[index,union-attr]
    )
    restarted = prepared["context"]["orchestrator"].property_prebuild_coordinator(  # type: ignore[index,union-attr]
        reconciliation_store=restarted_store
    )
    history = restarted.reconciliation_history(
        prepared["selection"],
        reconciliation_key="reconciliation:concurrent:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert len(history) == 1
    assert history[0].record_digest == results[0].record.record_digest

    second_result = _compose_property(
        prepared["context"],  # type: ignore[arg-type]
        request=_property_request_payload(
            key="property-tour-r11-conflict",
            request_id="4b5f63bf-d590-456d-b693-226aec5d403f",
        ),
    )
    second_selection = _selection(prepared["context"], second_result)  # type: ignore[arg-type]
    second_plan = restarted.resolve_plan(
        second_selection,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    second_allocation = restarted.plan_output_allocation(
        second_selection,
        plan=second_plan,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    second_boundary = restarted.prepare_execution_boundary(
        second_selection,
        plan=second_plan,
        allocation=second_allocation,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    second_record = restarted.reconcile(
        second_selection,
        reconciliation_key="reconciliation:concurrent:v1",
        plan=second_plan,
        allocation=second_allocation,
        boundary=second_boundary,
        state="planned",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    first_history = restarted.reconciliation_history(
        prepared["selection"],
        reconciliation_key="reconciliation:concurrent:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    second_history = restarted.reconciliation_history(
        second_selection,
        reconciliation_key="reconciliation:concurrent:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert [record.record_digest for record in first_history] == [
        results[0].record.record_digest
    ]
    assert [record.record_digest for record in second_history] == [
        second_record.record.record_digest
    ]
    assert first_history[0]["composition_digest"] != second_history[0][
        "composition_digest"
    ]
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_reconciliation_transitions_are_append_only_and_terminal(
    tmp_path: Path,
) -> None:
    artifact_verifier = AuthenticatedArtifactVerifier()
    prepared = _prepared(tmp_path, artifact_verifier=artifact_verifier)
    _enable_evidence_authority(
        prepared, artifact_verifier=artifact_verifier
    )
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    execution_evidence = _authenticated_execution(
        prepared, plan, allocation, boundary
    )
    slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
    candidate = build_property_artifact_candidate(
        boundary=boundary,
        execution_evidence=execution_evidence.evidence,
        allocation_slot_ref=slot_ref,
        artifact_ref="artifact:terminal-transition:v1",
        artifact_digest=execution_evidence.evidence["output_digest"],  # type: ignore[arg-type]
        verification_profile_digest=_digest("terminal-verification-profile"),
    )
    artifact_verifier.configure(
        prepared, plan, allocation, boundary, execution_evidence
    )
    verification_evidence = prepared["coordinator"].verify_artifact_evidence(  # type: ignore[union-attr]
        prepared["selection"],
        plan=plan,
        allocation=allocation,
        boundary=boundary,
        execution_evidence=execution_evidence,
        candidate=candidate,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    coordinator = prepared["coordinator"]
    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:terminal:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    states = ["planned", "allocation_planned", "execution_pending"]
    records = [coordinator.reconcile(state=state, **common) for state in states]  # type: ignore[union-attr,arg-type]
    records.append(
        coordinator.reconcile(  # type: ignore[union-attr]
            state="execution_succeeded",
            outcome_digest=execution_evidence.evidence.digest,
            execution_evidence=execution_evidence,
            **common,
        )
    )
    artifact_identity = candidate["artifact_identity_digest"]
    verification_digest = verification_evidence.evidence.digest
    records.append(
        coordinator.reconcile(  # type: ignore[union-attr]
            state="artifact_verified",
            outcome_digest=verification_digest,
            artifact_identity_digest=artifact_identity,
            verification_digest=verification_digest,
            execution_evidence=execution_evidence,
            verification_evidence=verification_evidence,
            candidate=candidate,
            **common,
        )
    )
    replay = coordinator.reconcile(  # type: ignore[union-attr]
        state="artifact_verified",
        outcome_digest=verification_digest,
        artifact_identity_digest=artifact_identity,
        verification_digest=verification_digest,
        execution_evidence=execution_evidence,
        verification_evidence=verification_evidence,
        candidate=candidate,
        **common,
    )

    assert [record.record["sequence"] for record in records] == [1, 2, 3, 4, 5]
    assert replay.idempotent_replay is True
    assert replay.record.record_digest == records[-1].record.record_digest
    for previous, current in zip(records, records[1:]):
        assert current.record["prior_record_digest"] == previous.record.record_digest
        assert current.record["retention_anchor"] == plan["retention_anchor"]
        assert current.record["retention_expires_at"] == plan["retention_expires_at"]
    with pytest.raises(
        PropertyPrebuildError, match="property_reconciliation_transition_invalid"
    ):
        coordinator.reconcile(state="failed_final", outcome_digest=_digest("late"), **common)  # type: ignore[union-attr,arg-type]

    history = coordinator.reconciliation_history(  # type: ignore[union-attr]
        prepared["selection"],
        reconciliation_key="reconciliation:terminal:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert len(history) == 5
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_artifact_verification_contract_binds_every_identity_and_rejects_mismatch(
    tmp_path: Path,
) -> None:
    mismatched_verifier = AuthenticatedArtifactVerifier(
        {"allocation_digest": _digest("wrong-allocation")}
    )
    prepared = _prepared(tmp_path, artifact_verifier=mismatched_verifier)
    _enable_evidence_authority(
        prepared, artifact_verifier=mismatched_verifier
    )
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    evidence = _authenticated_execution(prepared, plan, allocation, boundary)
    slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
    candidate = build_property_artifact_candidate(
        boundary=boundary,
        execution_evidence=evidence.evidence,
        allocation_slot_ref=slot_ref,
        artifact_ref="artifact:synthetic-output:v1",
        artifact_digest=evidence.evidence["output_digest"],  # type: ignore[arg-type]
        verification_profile_digest=_digest("verification-profile"),
    )
    mismatched_verifier.configure(
        prepared, plan, allocation, boundary, evidence
    )

    with pytest.raises(
        PropertyPrebuildError, match="property_artifact_verifier_binding_mismatch"
    ):
        prepared["coordinator"].verify_artifact_evidence(  # type: ignore[union-attr]
            prepared["selection"],
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            execution_evidence=evidence,
            candidate=candidate,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )
    assert len(mismatched_verifier.calls) == 1
    assert mismatched_verifier.provider_actions == 0
    assert mismatched_verifier.render_actions == 0
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_source_retention_anchor_never_restarts_on_build_replay_retry_or_reconciliation(
    tmp_path: Path,
) -> None:
    current = [NOW]
    context = _property_context(tmp_path, current=current)
    result = _compose_property(context)
    selection = _selection(context, result)
    coordinator, _ = _coordinator(context, tmp_path)
    first_plan = coordinator.resolve_plan(
        selection, policy_evidence=context["evidence"], observed_at=NOW
    )
    first_allocation = coordinator.plan_output_allocation(
        selection,
        plan=first_plan,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    first_boundary = coordinator.prepare_execution_boundary(
        selection,
        plan=first_plan,
        allocation=first_allocation,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    coordinator.reconcile(
        selection,
        reconciliation_key="reconciliation:anchor:v1",
        plan=first_plan,
        allocation=first_allocation,
        boundary=first_boundary,
        state="planned",
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    current[0] = NOW + timedelta(hours=1)
    replay_plan = coordinator.resolve_plan(
        selection,
        policy_evidence=context["evidence"],
        observed_at=current[0],
    )
    replay_allocation = coordinator.plan_output_allocation(
        selection,
        plan=replay_plan,
        policy_evidence=context["evidence"],
        observed_at=current[0],
    )

    assert replay_plan.canonical_bytes() == first_plan.canonical_bytes()
    assert replay_allocation.canonical_bytes() == first_allocation.canonical_bytes()
    assert replay_plan["retention_anchor"] == "2026-07-11T09:30:00Z"
    assert replay_plan["retention_expires_at"] == result["retention_expires_at"]
    history = coordinator.reconciliation_history(
        selection,
        reconciliation_key="reconciliation:anchor:v1",
        policy_evidence=context["evidence"],
        observed_at=current[0],
    )
    assert history[0]["retention_anchor"] == replay_plan["retention_anchor"]
    assert history[0]["retention_expires_at"] == replay_plan["retention_expires_at"]
    _assert_property_actions_zero(context)


def test_authority_callback_cannot_create_privacy_toctou_before_resolution_effect(
    tmp_path: Path,
) -> None:
    evidence = _property_policy_evidence()
    valid = _property_policy_verification(evidence)
    policy_verifier = PrivacyInjectingPolicyVerifier([valid])
    allocator = CountingAllocationPlanner()
    artifact_verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path,
        policy_verifier=policy_verifier,
        allocator=allocator,
        artifact_verifier=artifact_verifier,
    )
    context = prepared["context"]
    scope = prepared["result"]["composition_digest"]  # type: ignore[index]

    def inject_privacy() -> None:
        context["ledger"].record_privacy_action(  # type: ignore[union-attr]
            scope_digest=scope,
            action="deleted",
            reason_digest=_digest("policy-callback-privacy"),
            observed_at=NOW,
        )

    policy_verifier.hook = inject_privacy
    journal = tmp_path / "property-material" / "material.journal.jsonl"
    before = journal.read_bytes()

    with pytest.raises(
        SpatialPrivacyError, match="property_prebuild_privacy_tombstone_active"
    ):
        _resolve(prepared)

    assert allocator.planning_calls == 0
    assert artifact_verifier.calls == []
    assert journal.read_bytes() == before
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(context, allocator, artifact_verifier)


def test_artifact_candidate_must_name_an_exact_planned_allocation_slot(
    tmp_path: Path,
) -> None:
    artifact_verifier = AuthenticatedArtifactVerifier()
    prepared = _prepared(tmp_path, artifact_verifier=artifact_verifier)
    _enable_evidence_authority(
        prepared, artifact_verifier=artifact_verifier
    )
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    execution_evidence = _authenticated_execution(
        prepared, plan, allocation, boundary
    )
    candidate = build_property_artifact_candidate(
        boundary=boundary,
        execution_evidence=execution_evidence.evidence,
        allocation_slot_ref="allocation-slot:" + "f" * 64,
        artifact_ref="artifact:unallocated:v1",
        artifact_digest=execution_evidence.evidence["output_digest"],  # type: ignore[arg-type]
        verification_profile_digest=_digest("verification-profile"),
    )
    artifact_verifier.configure(
        prepared, plan, allocation, boundary, execution_evidence
    )

    with pytest.raises(
        PropertyPrebuildError,
        match="property_artifact_candidate_allocation_slot_mismatch",
    ):
        prepared["coordinator"].verify_artifact_evidence(  # type: ignore[union-attr]
            prepared["selection"],
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            execution_evidence=execution_evidence,
            candidate=candidate,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )

    assert artifact_verifier.calls == []
    assert artifact_verifier.artifact_verifier_actions == 0
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_reconciliation_requires_exact_evidence_and_rejects_clock_rollback(
    tmp_path: Path,
) -> None:
    current = [NOW]
    context = _property_context(tmp_path, current=current)
    result = _compose_property(context)
    selection = _selection(context, result)
    coordinator, _ = _coordinator(context, tmp_path)
    plan = coordinator.resolve_plan(
        selection,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    allocation = coordinator.plan_output_allocation(
        selection,
        plan=plan,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    boundary = coordinator.prepare_execution_boundary(
        selection,
        plan=plan,
        allocation=allocation,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )
    common = {
        "selection": selection,
        "reconciliation_key": "reconciliation:rollback:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": context["evidence"],
    }
    current[0] = NOW + timedelta(hours=1)
    coordinator.reconcile(  # type: ignore[arg-type]
        state="planned", observed_at=current[0], **common
    )

    current[0] = NOW + timedelta(minutes=30)
    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_trusted_clock_rollback"
    ):
        coordinator.reconcile(
            state="allocation_planned",
            observed_at=current[0],
            **common,  # type: ignore[arg-type]
        )
    current[0] = NOW + timedelta(hours=1)
    with pytest.raises(
        PropertyPrebuildError,
        match="property_execution_evidence_authority_required",
    ):
        coordinator.reconcile(
            state="execution_succeeded",
            outcome_digest=_digest("unbound-execution"),
            execution_evidence=_execution_evidence(plan, allocation, boundary),  # type: ignore[arg-type]
            observed_at=current[0],
            **common,  # type: ignore[arg-type]
        )
    _assert_property_actions_zero(context)


def test_reconciliation_record_parser_and_store_fail_closed_on_tamper_and_symlink(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    result = prepared["coordinator"].reconcile(  # type: ignore[union-attr]
        prepared["selection"],
        reconciliation_key="reconciliation:tamper:v1",
        plan=plan,
        allocation=allocation,
        boundary=boundary,
        state="planned",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    tampered = result.record.as_dict()
    tampered["retention_anchor"] = "2026-07-11T09:31:00Z"
    with pytest.raises(
        PropertyPrebuildError, match="property_reconciliation_record_digest_invalid"
    ):
        PropertyReconciliationRecord.parse(tampered)

    real_root = tmp_path / "real-reconciliation-root"
    real_root.mkdir(mode=0o700)
    symlink_root = tmp_path / "linked-reconciliation-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)
    symlink_store = PropertyPrebuildReconciliationStore(
        symlink_root,
        lifecycle_authority=prepared["context"]["ledger"].lifecycle_authority,  # type: ignore[index,union-attr]
    )
    symlink_coordinator = prepared["context"]["orchestrator"].property_prebuild_coordinator(  # type: ignore[index,union-attr]
        reconciliation_store=symlink_store
    )
    with pytest.raises(
        PropertyPrebuildError,
        match="property_reconciliation_store_(?:unavailable|ancestor_invalid)",
    ):
        symlink_coordinator.reconcile(
            prepared["selection"],
            reconciliation_key="reconciliation:symlink:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )
    assert list(real_root.iterdir()) == []
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_observability_is_digest_only_and_reports_zero_external_actions(
    tmp_path: Path,
) -> None:
    context = _property_context(tmp_path)
    result = _compose_property(context)
    selection = _selection(context, result)
    events: list[dict[str, object]] = []
    allocator = CountingAllocationPlanner()
    reconciliation_store = PropertyPrebuildReconciliationStore(
        tmp_path / "observable-state",
        lifecycle_authority=context["ledger"].lifecycle_authority,  # type: ignore[union-attr]
    )
    coordinator = context["orchestrator"].property_prebuild_coordinator(  # type: ignore[union-attr]
        output_allocation_planner=allocator,
        reconciliation_store=reconciliation_store,
        telemetry_sink=lambda event: events.append(dict(event)),
    )
    plan = coordinator.resolve_plan(
        selection, policy_evidence=context["evidence"], observed_at=NOW
    )
    coordinator.plan_output_allocation(
        selection,
        plan=plan,
        policy_evidence=context["evidence"],
        observed_at=NOW,
    )

    assert [event["event_type"] for event in events] == [
        "plan_resolved",
        "allocation_planned",
    ]
    for event in events:
        assert event["output_allocation_actions"] == 0
        assert event["quota_actions"] == 0
        assert event["adapter_actions"] == 0
        assert event["provider_actions"] == 0
        assert event["render_actions"] == 0
        encoded = json.dumps(event, sort_keys=True).lower()
        assert "://" not in encoded
        assert "credential" not in encoded
        assert "provider_url" not in encoded
    assert not (tmp_path / "observable-state").exists()
    _assert_property_actions_zero(context)


def test_stale_caller_time_cannot_select_an_older_authority_window(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=verifier
    )
    prepared["context"]["current"][0] = NOW + timedelta(minutes=1)  # type: ignore[index]

    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_caller_time_mismatch"
    ):
        _resolve(prepared, observed_at=NOW)

    assert allocator.planning_calls == 0
    assert verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_external_actions_zero(prepared["context"], allocator, verifier)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "phase",
    [
        "receipt",
        "policy",
        "input",
        "material",
        "planner",
        "verifier",
        "telemetry",
        "mapping",
        "reconciliation",
    ],
)
@pytest.mark.parametrize("clock_change", ["expired", "rollback"])
def test_trusted_clock_is_resampled_after_every_callback_boundary(
    tmp_path: Path,
    phase: str,
    clock_change: str,
) -> None:
    allocator = CountingAllocationPlanner()
    verifier = HookedAuthenticatedArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=verifier
    )
    _enable_evidence_authority(prepared, artifact_verifier=verifier)
    current = prepared["context"]["current"]  # type: ignore[index]

    def mutate_clock() -> None:
        current[0] = (
            NOW + timedelta(hours=13)
            if clock_change == "expired"
            else NOW - timedelta(minutes=1)
        )

    invoke = _callback_phase_invocation(prepared, phase, mutate_clock)
    with pytest.raises(
        (PropertyPrebuildError, SpatialPrivacyError)
    ) as caught:
        invoke()  # type: ignore[operator]

    assert "private" not in str(caught.value).lower()
    assert not (tmp_path / "property-prebuild-state").exists()
    assert allocator.output_allocation_actions == 0
    assert allocator.quota_actions == 0
    assert allocator.adapter_actions == 0
    assert allocator.provider_actions == 0
    assert allocator.render_actions == 0
    assert verifier.provider_actions == 0
    assert verifier.render_actions == 0
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "phase",
    ["material", "planner", "verifier", "telemetry", "mapping", "reconciliation"],
)
@pytest.mark.parametrize("mutation", ["privacy", "integrity"])
def test_post_callback_authority_mutation_fails_before_return_or_commit(
    tmp_path: Path,
    phase: str,
    mutation: str,
) -> None:
    allocator = CountingAllocationPlanner()
    verifier = HookedAuthenticatedArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=verifier
    )
    _enable_evidence_authority(prepared, artifact_verifier=verifier)
    context = prepared["context"]

    def mutate_authority() -> None:
        if mutation == "privacy":
            context["ledger"].record_privacy_action(  # type: ignore[union-attr]
                scope_digest=prepared["result"]["composition_digest"],  # type: ignore[index]
                action="deleted",
                reason_digest=_digest(f"{phase}-callback-privacy"),
                observed_at=NOW,
            )
        else:
            index_path = context["ledger"].root / "index.json"  # type: ignore[union-attr]
            index_path.write_text("{}\n", encoding="utf-8")

    invoke = _callback_phase_invocation(prepared, phase, mutate_authority)
    expected = SpatialPrivacyError if mutation == "privacy" else PropertyPrebuildError
    with pytest.raises(expected):
        invoke()  # type: ignore[operator]

    assert not (tmp_path / "property-prebuild-state").exists()
    assert allocator.output_allocation_actions == 0
    assert allocator.quota_actions == 0
    assert allocator.adapter_actions == 0
    assert allocator.provider_actions == 0
    assert allocator.render_actions == 0
    assert verifier.provider_actions == 0
    assert verifier.render_actions == 0
    _assert_property_actions_zero(context)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "callback_kind",
    ["receipt", "policy", "input", "planner", "telemetry", "mapping"],
)
def test_callback_and_mapping_exceptions_are_static_and_redacted(
    tmp_path: Path,
    callback_kind: str,
) -> None:
    allocator = CountingAllocationPlanner()
    verifier = FakeArtifactVerifier()
    prepared = _prepared(
        tmp_path, allocator=allocator, artifact_verifier=verifier
    )
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    private = "/private/provider/credential-do-not-leak"

    def raising(*args: object, **kwargs: object) -> object:
        raise RuntimeError(private)

    if callback_kind in {"receipt", "policy", "input"}:
        setattr(
            coordinator,
            {
                "receipt": "_receipt_verifier",
                "policy": "_policy_verifier",
                "input": "_input_authority_verifier",
            }[callback_kind],
            raising,
        )

        def invoke() -> object:
            return _resolve(prepared)

    else:
        plan = _resolve(prepared)
        if callback_kind == "planner":
            coordinator._allocator = raising  # type: ignore[assignment]

            def invoke() -> object:
                return coordinator.plan_output_allocation(
                    prepared["selection"],
                    plan=plan,
                    policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                    observed_at=NOW,
                )

        elif callback_kind == "telemetry":
            coordinator._telemetry_sink = raising  # type: ignore[assignment]

            def invoke() -> object:
                return coordinator.plan_output_allocation(
                    prepared["selection"],
                    plan=plan,
                    policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                    observed_at=NOW,
                )

        else:
            def invoke() -> object:
                return coordinator.plan_output_allocation(
                    prepared["selection"],
                    plan=RaisingMapping(),
                    policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                    observed_at=NOW,
                )

    with pytest.raises(PropertyPrebuildError) as caught:
        invoke()
    assert private not in str(caught.value)
    assert "credential-do-not-leak" not in str(caught.value)
    assert verifier.calls == []
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


@pytest.mark.parametrize("callback_kind", ["policy", "input", "planner"])
def test_wrong_type_and_raising_mapping_protocol_returns_are_static(
    tmp_path: Path,
    callback_kind: str,
) -> None:
    prepared = _prepared(tmp_path)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    if callback_kind == "policy":
        coordinator._policy_verifier = lambda *args, **kwargs: RaisingMapping()
        invoke = lambda: _resolve(prepared)
    elif callback_kind == "input":
        coordinator._input_authority_verifier = lambda *args, **kwargs: None  # type: ignore[assignment]
        invoke = lambda: _resolve(prepared)
    else:
        plan = _resolve(prepared)
        coordinator._allocator = lambda _: None  # type: ignore[assignment]
        invoke = lambda: coordinator.plan_output_allocation(
            prepared["selection"],
            plan=plan,
            policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
            observed_at=NOW,
        )

    with pytest.raises(PropertyPrebuildError) as caught:
        invoke()
    assert "private" not in str(caught.value).lower()
    assert not (tmp_path / "property-prebuild-state").exists()


def test_artifact_verifier_exception_and_wrong_type_are_static(
    tmp_path: Path,
) -> None:
    class BadVerifier(AuthenticatedArtifactVerifier):
        def __init__(self, wrong_type: bool) -> None:
            super().__init__()
            self.wrong_type = wrong_type

        def __call__(  # type: ignore[override]
            self, candidate: PropertyArtifactCandidate, *, observed_at: datetime
        ) -> object:
            self.calls.append(candidate.as_dict())
            if self.wrong_type:
                return None
            raise RuntimeError("provider-secret:/private/verifier")

    for wrong_type in (False, True):
        verifier = BadVerifier(wrong_type)
        prepared = _prepared(
            tmp_path / ("wrong" if wrong_type else "raise"),
            artifact_verifier=verifier,
        )
        _enable_evidence_authority(prepared, artifact_verifier=verifier)
        plan = _resolve(prepared)
        allocation, boundary = _allocation_and_boundary(prepared, plan)
        execution = _authenticated_execution(
            prepared, plan, allocation, boundary
        )
        slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
        candidate = build_property_artifact_candidate(
            boundary=boundary,
            execution_evidence=execution.evidence,
            allocation_slot_ref=slot_ref,
            artifact_ref="artifact:bad-verifier:v1",
            artifact_digest=execution.evidence["output_digest"],  # type: ignore[arg-type]
            verification_profile_digest=_digest("bad-verifier-profile"),
        )
        with pytest.raises(
            PropertyPrebuildError, match="property_artifact_verifier_failed"
        ) as caught:
            prepared["coordinator"].verify_artifact_evidence(  # type: ignore[union-attr]
                prepared["selection"],
                plan=plan,
                allocation=allocation,
                boundary=boundary,
                execution_evidence=execution,
                candidate=candidate,
                policy_evidence=prepared["evidence"],
                observed_at=NOW,
            )
        assert "provider-secret" not in str(caught.value)
        assert not (
            tmp_path / ("wrong" if wrong_type else "raise") / "property-prebuild-state"
        ).exists()


def test_authenticated_wrapper_direct_construction_cannot_bypass_runtime_types(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    execution = _execution_evidence(plan, allocation, boundary)
    with pytest.raises(
        PropertyPrebuildError,
        match="property_execution_authority_receipt_invalid",
    ):
        PropertyAuthenticatedExecutionEvidence(  # type: ignore[arg-type]
            RaisingMapping(), b"{}"
        )
    verification = PropertyArtifactVerificationEvidence.parse(
        {
            "contract_name": (
                "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
            ),
            "contract_version": "1.0.0",
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "execution_identity_digest": boundary["execution_identity_digest"],
            "execution_evidence_digest": execution.digest,
            "artifact_identity_digest": _digest("wrapper-artifact"),
            "artifact_digest": execution["output_digest"],
            "verifier_identity_digest": _digest("wrapper-verifier"),
            "verification_profile_digest": _digest("wrapper-profile"),
            "outcome_evidence_digest": _digest("wrapper-outcome"),
            "state": "verified",
            "verified_at": utc_iso(NOW),
        }
    )
    with pytest.raises(
        PropertyPrebuildError,
        match="property_artifact_authority_receipt_invalid",
    ):
        PropertyAuthenticatedArtifactVerification(
            verification, b'{"noncanonical": true}'
        )


def test_callback_reentrancy_is_rejected_before_nested_effect(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    prepared = _prepared(tmp_path, allocator=allocator)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    plan = _resolve(prepared)
    nested_calls = 0

    def reenter(_: Mapping[str, object]) -> None:
        nonlocal nested_calls
        nested_calls += 1
        coordinator.resolve_plan(
            prepared["selection"],
            policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
            observed_at=NOW,
        )

    coordinator._telemetry_sink = reenter
    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_telemetry_failed"
    ):
        coordinator.plan_output_allocation(
            prepared["selection"],
            plan=plan,
            policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
            observed_at=NOW,
        )
    assert nested_calls == 1
    assert allocator.planning_calls == 1
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_direct_coordinator_binds_exact_independent_acceptance_identity(
    tmp_path: Path,
) -> None:
    allocator = CountingAllocationPlanner()
    prepared = _prepared(tmp_path, allocator=allocator)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    original = coordinator._policy_verifier

    def mismatched(*args: object, **kwargs: object) -> Mapping[str, object]:
        projection = dict(original(*args, **kwargs))
        projection["independent_acceptance_digest"] = _digest("wrong-acceptance")
        return projection

    coordinator._policy_verifier = mismatched
    with pytest.raises(
        PropertyPrebuildError, match="property_prebuild_policy_authority_mismatch"
    ):
        _resolve(prepared)

    assert allocator.planning_calls == 0
    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_production_factory_is_unconfigured_and_canonical_execution_is_not_authority(
    tmp_path: Path,
) -> None:
    verifier = FakeArtifactVerifier()
    prepared = _prepared(tmp_path, artifact_verifier=verifier)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    assert coordinator._evidence_authority_registry is None
    assert coordinator._execution_evidence_authority is None
    assert coordinator._artifact_evidence_authority is None
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    forged_execution = _execution_evidence(plan, allocation, boundary)
    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:factory-forgery:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    for state in ("planned", "allocation_planned", "execution_pending"):
        coordinator.reconcile(state=state, **common)  # type: ignore[arg-type]

    with pytest.raises(
        PropertyPrebuildError, match="property_execution_evidence_authority_required"
    ):
        coordinator.reconcile(  # type: ignore[arg-type]
            state="execution_succeeded",
            outcome_digest=forged_execution.digest,
            execution_evidence=forged_execution,
            **common,
        )

    history = coordinator.reconciliation_history(
        prepared["selection"],
        reconciliation_key="reconciliation:factory-forgery:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert [record["state"] for record in history] == [
        "planned",
        "allocation_planned",
        "execution_pending",
    ]
    assert verifier.calls == []
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_controller_artifact_forgery_cannot_advance_or_invoke_verifier(
    tmp_path: Path,
) -> None:
    verifier = FakeArtifactVerifier()
    prepared = _prepared(tmp_path, artifact_verifier=verifier)
    _enable_evidence_authority(prepared, artifact_verifier=verifier)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    execution = _authenticated_execution(prepared, plan, allocation, boundary)
    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:controller-forgery:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    for state in ("planned", "allocation_planned", "execution_pending"):
        coordinator.reconcile(state=state, **common)  # type: ignore[arg-type]
    coordinator.reconcile(  # type: ignore[arg-type]
        state="execution_succeeded",
        outcome_digest=execution.evidence.digest,
        execution_evidence=execution,
        **common,
    )

    forged_artifact_digest = _digest("different-from-execution-output")
    assert forged_artifact_digest != execution.evidence["output_digest"]
    slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
    forged_candidate = PropertyArtifactCandidate.parse(
        {
            "contract_name": "propertyquarry.governed_spatial_artifact_candidate.v1",
            "contract_version": "1.0.0",
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "execution_identity_digest": boundary["execution_identity_digest"],
            "execution_evidence_digest": execution.evidence.digest,
            "allocation_slot_ref": slot_ref,
            "artifact_ref": "artifact:controller-forged:v1",
            "artifact_digest": forged_artifact_digest,
            "artifact_identity_digest": _digest("forged-artifact-identity"),
            "verification_profile_digest": _digest("forged-profile"),
        }
    )
    forged_verification = PropertyArtifactVerificationEvidence.parse(
        {
            "contract_name": (
                "propertyquarry.governed_spatial_artifact_verification_evidence.v1"
            ),
            "contract_version": "1.0.0",
            "plan_digest": plan.digest,
            "allocation_digest": allocation.digest,
            "execution_identity_digest": boundary["execution_identity_digest"],
            "execution_evidence_digest": execution.evidence.digest,
            "artifact_identity_digest": forged_candidate[
                "artifact_identity_digest"
            ],
            "artifact_digest": forged_artifact_digest,
            "verifier_identity_digest": _digest("caller-forged-verifier"),
            "verification_profile_digest": forged_candidate[
                "verification_profile_digest"
            ],
            "outcome_evidence_digest": _digest("caller-forged-outcome"),
            "state": "verified",
            "verified_at": utc_iso(NOW),
        }
    )

    with pytest.raises(PropertyPrebuildError) as caught:
        coordinator.reconcile(  # type: ignore[arg-type]
            state="artifact_verified",
            outcome_digest=forged_verification.digest,
            artifact_identity_digest=forged_candidate[
                "artifact_identity_digest"
            ],
            verification_digest=forged_verification.digest,
            execution_evidence=execution,
            verification_evidence=forged_verification,
            candidate=forged_candidate,
            **common,
        )
    assert str(caught.value) in {
        "property_execution_evidence_binding_mismatch",
        "property_reconciliation_artifact_candidate_mismatch",
        "property_artifact_evidence_authority_required",
    }
    assert "controller-forged" not in str(caught.value)
    history = coordinator.reconciliation_history(
        prepared["selection"],
        reconciliation_key="reconciliation:controller-forgery:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert history[-1]["state"] == "execution_succeeded"
    assert len(history) == 4
    assert verifier.calls == []
    assert verifier.artifact_verifier_actions == 0
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def test_rejected_verification_never_emits_verified_or_advances_state(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []
    verifier = AuthenticatedArtifactVerifier({"state": "rejected"})
    prepared = _prepared(tmp_path, artifact_verifier=verifier)
    _enable_evidence_authority(prepared, artifact_verifier=verifier)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    coordinator._telemetry_sink = lambda event: events.append(dict(event))
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    execution = _authenticated_execution(prepared, plan, allocation, boundary)
    slot_ref = allocation.as_dict()["slots"][0]["slot_ref"]  # type: ignore[index]
    candidate = build_property_artifact_candidate(
        boundary=boundary,
        execution_evidence=execution.evidence,
        allocation_slot_ref=slot_ref,
        artifact_ref="artifact:rejected:v1",
        artifact_digest=execution.evidence["output_digest"],  # type: ignore[arg-type]
        verification_profile_digest=_digest("rejected-profile"),
    )
    verifier.configure(prepared, plan, allocation, boundary, execution)
    rejected = coordinator.verify_artifact_evidence(
        prepared["selection"],
        plan=plan,
        allocation=allocation,
        boundary=boundary,
        execution_evidence=execution,
        candidate=candidate,
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert rejected.evidence["state"] == "rejected"
    event_types = [str(event["event_type"]) for event in events]
    assert "artifact_evidence_rejected" in event_types
    assert "artifact_evidence_verified" not in event_types

    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:rejected:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    for state in ("planned", "allocation_planned", "execution_pending"):
        coordinator.reconcile(state=state, **common)  # type: ignore[arg-type]
    coordinator.reconcile(  # type: ignore[arg-type]
        state="execution_succeeded",
        outcome_digest=execution.evidence.digest,
        execution_evidence=execution,
        **common,
    )
    with pytest.raises(
        PropertyPrebuildError,
        match="property_reconciliation_artifact_evidence_mismatch",
    ):
        coordinator.reconcile(  # type: ignore[arg-type]
            state="artifact_verified",
            outcome_digest=rejected.evidence.digest,
            artifact_identity_digest=candidate["artifact_identity_digest"],
            verification_digest=rejected.evidence.digest,
            execution_evidence=execution,
            verification_evidence=rejected,
            candidate=candidate,
            **common,
        )
    history = coordinator.reconciliation_history(
        prepared["selection"],
        reconciliation_key="reconciliation:rejected:v1",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    assert history[-1]["state"] == "execution_succeeded"
    assert len(history) == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "unknown"},
        {"state": "allocation_planned"},
        {"state": "planned", "outcome_digest": _digest("unexpected-outcome")},
        {"state": "planned", "outcome_digest": "sha256:bad"},
        {
            "state": "planned",
            "artifact_identity_digest": _digest("unexpected-artifact"),
        },
        {
            "state": "planned",
            "verification_digest": _digest("unexpected-verification"),
        },
        {"state": "failed_final", "outcome_digest": _digest("first-failure")},
    ],
)
def test_invalid_first_reconciliation_is_prevalidated_before_path_creation(
    tmp_path: Path,
    changes: Mapping[str, object],
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    arguments: dict[str, object] = {
        "state": "planned",
        "outcome_digest": None,
        "artifact_identity_digest": None,
        "verification_digest": None,
    }
    arguments.update(dict(changes))

    with pytest.raises(PropertyPrebuildError):
        prepared["coordinator"].reconcile(  # type: ignore[union-attr,arg-type]
            prepared["selection"],
            reconciliation_key="reconciliation:invalid-first:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
            **arguments,
        )

    assert not (tmp_path / "property-prebuild-state").exists()
    _assert_property_actions_zero(prepared["context"])  # type: ignore[arg-type]


def _two_record_journal(
    tmp_path: Path,
) -> tuple[dict[str, object], Path]:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:restart-frame:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    prepared["coordinator"].reconcile(state="planned", **common)  # type: ignore[union-attr,arg-type]
    prepared["coordinator"].reconcile(  # type: ignore[union-attr,arg-type]
        state="allocation_planned", **common
    )
    return prepared, (
        tmp_path
        / "property-prebuild-state"
        / "property-prebuild-reconciliation.v1.jsonl"
    )


def test_restart_rejects_redigested_recorded_at_rollback(
    tmp_path: Path,
) -> None:
    prepared, journal = _two_record_journal(tmp_path)
    frames = journal.read_bytes().split(b"\n")
    assert frames[-1] == b""
    first = json.loads(frames[0])
    second = json.loads(frames[1])
    first_time = datetime.fromisoformat(
        str(first["recorded_at"]).replace("Z", "+00:00")
    )
    second["recorded_at"] = utc_iso(first_time - timedelta(seconds=1))
    second["record_digest"] = prebuild_module._record_digest(second)
    journal.write_bytes(
        prebuild_module._canonical_bytes(first)
        + b"\n"
        + prebuild_module._canonical_bytes(second)
        + b"\n"
    )
    restarted_store = PropertyPrebuildReconciliationStore(
        journal.parent,
        lifecycle_authority=prepared["context"]["ledger"].lifecycle_authority,  # type: ignore[index,union-attr]
    )
    restarted = prepared["context"]["orchestrator"].property_prebuild_coordinator(  # type: ignore[index,union-attr]
        reconciliation_store=restarted_store
    )

    with pytest.raises(
        PropertyPrebuildError, match="property_reconciliation_clock_rollback"
    ):
        restarted.reconciliation_history(
            prepared["selection"],
            reconciliation_key="reconciliation:restart-frame:v1",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "separator", [b"\r\n", b"\r", b"\xc2\x85", b"\xe2\x80\xa8", b"\xe2\x80\xa9"]
)
def test_restart_rejects_every_non_lf_record_separator(
    tmp_path: Path,
    separator: bytes,
) -> None:
    prepared, journal = _two_record_journal(tmp_path)
    raw = journal.read_bytes()
    journal.write_bytes(raw.replace(b"\n", separator))
    restarted_store = PropertyPrebuildReconciliationStore(
        journal.parent,
        lifecycle_authority=prepared["context"]["ledger"].lifecycle_authority,  # type: ignore[index,union-attr]
    )
    restarted = prepared["context"]["orchestrator"].property_prebuild_coordinator(  # type: ignore[index,union-attr]
        reconciliation_store=restarted_store
    )

    with pytest.raises(
        PropertyPrebuildError,
        match="property_reconciliation_journal_(?:frame_invalid|truncated)",
    ):
        restarted.reconciliation_history(
            prepared["selection"],
            reconciliation_key="reconciliation:restart-frame:v1",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )


def test_symlinked_reconciliation_ancestor_is_never_followed(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked-ancestor"
    linked.symlink_to(outside, target_is_directory=True)
    coordinator, _ = _coordinator(
        prepared["context"],  # type: ignore[arg-type]
        tmp_path,
        reconciliation_root=linked / "state",
    )

    with pytest.raises(PropertyPrebuildError) as caught:
        coordinator.reconcile(
            prepared["selection"],
            reconciliation_key="reconciliation:symlink-ancestor:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
            observed_at=NOW,
        )
    assert str(caught.value).startswith("property_reconciliation_store_")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("substitution", ["root", "lock", "journal", "hardlink"])
def test_reconciliation_root_and_file_substitution_fail_closed(
    tmp_path: Path,
    substitution: str,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    common = {
        "selection": prepared["selection"],
        "reconciliation_key": "reconciliation:substitution:v1",
        "plan": plan,
        "allocation": allocation,
        "boundary": boundary,
        "policy_evidence": prepared["evidence"],
        "observed_at": NOW,
    }
    prepared["coordinator"].reconcile(state="planned", **common)  # type: ignore[union-attr,arg-type]
    store = prepared["reconciliation_store"]
    assert isinstance(store, PropertyPrebuildReconciliationStore)
    root = tmp_path / "property-prebuild-state"
    lock = root / ".property-prebuild-reconciliation.lock"
    journal = root / "property-prebuild-reconciliation.v1.jsonl"
    anchor_by_name = {
        "root": store._root_anchor_fd,
        "lock": store._lock_anchor_fd,
        "journal": store._journal_anchor_fd,
    }
    old_identity = (
        None
        if substitution == "hardlink"
        else os.fstat(anchor_by_name[substitution])  # type: ignore[arg-type]
    )
    if substitution == "root":
        displaced = tmp_path / "displaced-state"
        root.rename(displaced)
        root.mkdir(mode=0o700)
    elif substitution == "lock":
        lock.unlink()
        lock.write_bytes(b"")
        lock.chmod(0o600)
    elif substitution == "journal":
        prior = journal.read_bytes()
        journal.unlink()
        journal.write_bytes(prior)
        journal.chmod(0o600)
    else:
        os.link(journal, tmp_path / "journal-hardlink")

    if old_identity is not None:
        replaced_path = {
            "root": root,
            "lock": lock,
            "journal": journal,
        }[substitution]
        replacement = replaced_path.stat(follow_symlinks=False)
        assert (replacement.st_dev, replacement.st_ino) != (
            old_identity.st_dev,
            old_identity.st_ino,
        )

    with pytest.raises(PropertyPrebuildError) as caught:
        prepared["coordinator"].reconcile(  # type: ignore[union-attr,arg-type]
            state="allocation_planned", **common
        )
    assert str(caught.value).startswith("property_reconciliation_")


@pytest.mark.parametrize("race", ["root", "lock", "journal", "hardlink"])
def test_descriptor_revalidation_catches_post_open_path_races(
    tmp_path: Path,
    race: str,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    store = prepared["reconciliation_store"]
    assert isinstance(store, PropertyPrebuildReconciliationStore)
    root_path = tmp_path / "property-prebuild-state"
    original_open_file = store._open_file
    original_read_locked = store._read_locked
    triggered = False

    def open_file(
        root: PropertyPrebuildReconciliationStore._RootHandle,
        name: str,
        *,
        create: bool,
    ) -> tuple[int, bool]:
        nonlocal triggered
        result = original_open_file(root, name, create=create)
        if not triggered and race in {"root", "lock"} and name.startswith("."):
            triggered = True
            if race == "root":
                root_path.rename(tmp_path / "post-open-displaced")
                root_path.mkdir(mode=0o700)
            else:
                lock_path = root_path / name
                lock_path.unlink()
                lock_path.write_bytes(b"")
                lock_path.chmod(0o600)
        return result

    def read_locked(descriptor: int) -> list[PropertyReconciliationRecord]:
        nonlocal triggered
        if not triggered and race in {"journal", "hardlink"}:
            triggered = True
            journal = root_path / "property-prebuild-reconciliation.v1.jsonl"
            if race == "journal":
                journal.unlink()
                journal.write_bytes(b"")
                journal.chmod(0o600)
            else:
                os.link(journal, tmp_path / "post-open-journal-hardlink")
        return original_read_locked(descriptor)

    store._open_file = open_file  # type: ignore[method-assign]
    store._read_locked = read_locked  # type: ignore[method-assign]
    with pytest.raises(PropertyPrebuildError):
        prepared["coordinator"].reconcile(  # type: ignore[union-attr]
            prepared["selection"],
            reconciliation_key=f"reconciliation:post-open-{race}:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )
    assert triggered is True
    replacement_journal = (
        root_path / "property-prebuild-reconciliation.v1.jsonl"
    )
    if replacement_journal.exists():
        assert replacement_journal.read_bytes() == b""


def test_replaced_lock_is_rejected_after_restart_by_durable_lock_lineage(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    prepared["coordinator"].reconcile(  # type: ignore[union-attr]
        prepared["selection"],
        reconciliation_key="reconciliation:lock-lineage:v1",
        plan=plan,
        allocation=allocation,
        boundary=boundary,
        state="planned",
        policy_evidence=prepared["evidence"],
        observed_at=NOW,
    )
    root = tmp_path / "property-prebuild-state"
    lock = root / ".property-prebuild-reconciliation.lock"
    lock.unlink()
    lock.write_bytes(b"")
    lock.chmod(0o600)
    restarted_store = PropertyPrebuildReconciliationStore(
        root,
        lifecycle_authority=prepared["context"]["ledger"].lifecycle_authority,  # type: ignore[index,union-attr]
    )
    restarted = prepared["context"]["orchestrator"].property_prebuild_coordinator(  # type: ignore[index,union-attr]
        reconciliation_store=restarted_store
    )

    with pytest.raises(
        PropertyPrebuildError, match="property_reconciliation_lock_substituted"
    ):
        restarted.reconciliation_history(
            prepared["selection"],
            reconciliation_key="reconciliation:lock-lineage:v1",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )


def test_two_store_instances_share_atomic_first_creation_and_one_lock(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    root = tmp_path / "two-store-state"
    first, first_store = _coordinator(
        prepared["context"],  # type: ignore[arg-type]
        tmp_path,
        reconciliation_root=root,
    )
    second, second_store = _coordinator(
        prepared["context"],  # type: ignore[arg-type]
        tmp_path,
        reconciliation_root=root,
    )
    barrier = threading.Barrier(2)

    def append(coordinator: PropertyPrebuildCoordinator) -> object:
        barrier.wait(timeout=10)
        return coordinator.reconcile(
            prepared["selection"],
            reconciliation_key="reconciliation:two-store:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
            observed_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, (first, second)))
    assert sum(not result.idempotent_replay for result in results) == 1
    assert len({result.record.record_digest for result in results}) == 1
    assert first_store._lock_anchor_fd is not None
    assert second_store._lock_anchor_fd is not None
    first_lock = os.fstat(first_store._lock_anchor_fd)
    second_lock = os.fstat(second_store._lock_anchor_fd)
    assert (first_lock.st_dev, first_lock.st_ino) == (
        second_lock.st_dev,
        second_lock.st_ino,
    )
    assert (
        first_store._lock_generation_digest
        == second_store._lock_generation_digest
    )
    lock = root / ".property-prebuild-reconciliation.lock"
    journal = root / "property-prebuild-reconciliation.v1.jsonl"
    for path in (lock, journal):
        details = path.stat(follow_symlinks=False)
        assert stat.S_ISREG(details.st_mode)
        assert stat.S_IMODE(details.st_mode) == 0o600
        assert details.st_nlink == 1


def test_multi_process_first_append_is_serialized_and_exactly_replayed(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    coordinator = prepared["coordinator"]
    assert isinstance(coordinator, PropertyPrebuildCoordinator)
    process_context = multiprocessing.get_context("fork")
    results = process_context.Queue()

    def worker() -> None:
        try:
            result = coordinator.reconcile(
                prepared["selection"],
                reconciliation_key="reconciliation:multiprocess:v1",
                plan=plan,
                allocation=allocation,
                boundary=boundary,
                state="planned",
                policy_evidence=prepared["evidence"],  # type: ignore[arg-type]
                observed_at=NOW,
            )
            results.put(
                ("ok", result.record.record_digest, result.idempotent_replay)
            )
        except Exception as exc:
            results.put(("error", type(exc).__name__, str(exc)))

    processes = [process_context.Process(target=worker) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    outcomes = [results.get(timeout=5) for _ in processes]
    assert {outcome[0] for outcome in outcomes} == {"ok"}
    assert len({outcome[1] for outcome in outcomes}) == 1
    assert sum(outcome[2] is False for outcome in outcomes) == 1


def test_filesystem_errors_are_normalized_without_private_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path)
    plan = _resolve(prepared)
    allocation, boundary = _allocation_and_boundary(prepared, plan)
    original_open = os.open
    armed = False

    def failing_open(path: object, *args: object, **kwargs: object) -> int:
        if path == "/":
            raise OSError("/private/provider/credential-do-not-leak")
        return original_open(path, *args, **kwargs)  # type: ignore[arg-type]

    def arm(_: Mapping[str, object]) -> None:
        nonlocal armed
        armed = True
        monkeypatch.setattr(os, "open", failing_open)

    prepared["coordinator"]._telemetry_sink = arm  # type: ignore[union-attr]
    with pytest.raises(
        PropertyPrebuildError, match="property_reconciliation_store_unavailable"
    ) as caught:
        prepared["coordinator"].reconcile(  # type: ignore[union-attr]
            prepared["selection"],
            reconciliation_key="reconciliation:filesystem-error:v1",
            plan=plan,
            allocation=allocation,
            boundary=boundary,
            state="planned",
            policy_evidence=prepared["evidence"],
            observed_at=NOW,
        )
    assert "credential-do-not-leak" not in str(caught.value)
    assert armed is True
    assert not (tmp_path / "property-prebuild-state").exists()
