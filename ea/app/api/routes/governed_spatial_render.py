from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from app.services.governed_spatial_contract import (
    GovernedSpatialBuildAuthorization,
    GovernedSpatialContractError,
    parse_raw_transport_json,
)
from app.services.governed_spatial_crypto import Ed25519EnvelopeSigner, Ed25519KeyRegistry
from app.services.governed_spatial_render import (
    GovernedExecutionAdapter,
    GovernedQualityGate,
    GovernedQuotaAdapter,
    GovernedSpatialOrchestrator,
)
from app.services.governed_spatial_state import (
    BUILD_STATES,
    DurableSpatialLedger,
    SpatialIdempotencyConflict,
    SpatialStateError,
    payload_digest,
)


router = APIRouter(prefix="/v1/internal/governed-spatial-render", tags=["governed-spatial-render"])

_COMPOSE_FIELDS = frozenset({"request", "source_packet"})
_BUILD_FIELDS = frozenset({"authorization", "evidence_envelope"})
_SAFE_REASON = re.compile(r"^[a-z0-9_]+$")
_SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_INGRESS_REASONS = frozenset(
    {
        "bom_forbidden",
        "duplicate_member",
        "float_out_of_range",
        "invalid_unicode",
        "invalid_utf8",
        "malformed_json",
        "non_finite_forbidden",
        "raw_json_empty",
        "raw_json_too_large",
        "unsafe_integer",
    }
)


@dataclass(frozen=True, slots=True)
class GovernedSpatialApiRuntime:
    orchestrator: GovernedSpatialOrchestrator
    evidence_registry: Ed25519KeyRegistry | None = None


def build_governed_spatial_api_runtime(
    *,
    ledger_root: Path,
    signer: Ed25519EnvelopeSigner,
    evidence_registry: Ed25519KeyRegistry | None = None,
    quota_adapter: GovernedQuotaAdapter | None = None,
    execution_adapter: GovernedExecutionAdapter | None = None,
    execution_target: Mapping[str, object] | None = None,
    quality_gate: GovernedQualityGate | None = None,
    telemetry_sink: Callable[[dict[str, object]], None] | None = None,
    now: Callable[[], datetime] | None = None,
) -> GovernedSpatialApiRuntime:
    """Build the API runtime only from controller-supplied durable dependencies."""

    options: dict[str, object] = {
        "ledger": DurableSpatialLedger(ledger_root),
        "signer": signer,
        "quota_adapter": quota_adapter,
        "execution_adapter": execution_adapter,
        "execution_target": execution_target,
        "quality_gate": quality_gate,
        "telemetry_sink": telemetry_sink,
    }
    if now is not None:
        options["now"] = now
    return GovernedSpatialApiRuntime(
        orchestrator=GovernedSpatialOrchestrator(**options),
        evidence_registry=evidence_registry,
    )


def get_governed_spatial_runtime(request: Request) -> GovernedSpatialApiRuntime:
    factory = getattr(request.app.state, "governed_spatial_runtime_factory", None)
    if not callable(factory):
        raise HTTPException(status_code=503, detail="governed_spatial_runtime_unconfigured")
    runtime = factory()
    if not isinstance(runtime, GovernedSpatialApiRuntime):
        raise HTTPException(status_code=503, detail="governed_spatial_runtime_invalid")
    return runtime


def _safe_error_code(error: Exception) -> str:
    raw = str(error).strip().lower()
    for reason in _SAFE_INGRESS_REASONS:
        if reason in raw:
            return reason
    leading = raw.split(":", 1)[0].split(";", 1)[0]
    return leading if _SAFE_REASON.fullmatch(leading) else "governed_spatial_request_rejected"


def _safe_digest(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_DIGEST.fullmatch(value) else ""


async def _raw_object(request: Request, *, allowed_fields: frozenset[str]) -> dict[str, object]:
    try:
        payload = parse_raw_transport_json(await request.body())
    except GovernedSpatialContractError as exc:
        raise HTTPException(status_code=422, detail=_safe_error_code(exc)) from exc
    unexpected = set(payload).difference(allowed_fields)
    if unexpected:
        raise HTTPException(status_code=422, detail="unexpected_fields")
    return payload


def _compose_projection(receipt: Mapping[str, object]) -> dict[str, object]:
    target = receipt.get("execution_target")
    target_binding = target.get("binding_state") if isinstance(target, Mapping) else "unbound"
    status = receipt.get("status")
    state = receipt.get("state")
    return {
        "contract_name": "ea.governed_spatial_render_compose_api_projection.v1",
        "status": status if status in {"accepted", "blocked"} else "blocked",
        "state": state if state in {"audit_only", "blocked"} else "blocked",
        "composition_digest": _safe_digest(receipt.get("composition_digest")),
        "composition_receipt_digest": payload_digest(receipt),
        "request_digest": _safe_digest(receipt.get("request_digest")),
        "source_digest": _safe_digest(receipt.get("source_digest")),
        "source_packet_digest": _safe_digest(receipt.get("source_packet_digest")),
        "style_digest": _safe_digest(receipt.get("style_digest")),
        "output_contract_digest": _safe_digest(receipt.get("output_contract_digest")),
        "execution_target_binding": target_binding if target_binding in {"bound", "unbound"} else "unbound",
        "executable": False,
        "audit_only": receipt.get("audit_only") is True,
        "idempotent_replay": receipt.get("idempotent_replay") is True,
        "quota_mutated": False,
        "provider_job_enqueued": False,
        "provider_details_exposed": False,
    }


def _build_projection(receipt: Mapping[str, object]) -> dict[str, object]:
    projection = receipt.get("product_projection")
    supplied = projection if isinstance(projection, Mapping) else {}
    raw_state = supplied.get("state")
    projection_state = (
        raw_state
        if isinstance(raw_state, str)
        and raw_state in {"blocked", "complete_internal", "processing", "unavailable"}
        else "blocked"
    )
    raw_reason = supplied.get("reason")
    projection_reason = (
        raw_reason
        if isinstance(raw_reason, str) and len(raw_reason) <= 128 and _SAFE_REASON.fullmatch(raw_reason)
        else ""
    )
    raw_progress = supplied.get("progress_percent")
    progress = raw_progress if type(raw_progress) is int and 0 <= raw_progress <= 100 else 0
    safe_projection = {
        "contract_name": "ea.governed_spatial_render_product_projection.v1",
        "state": projection_state,
        "reason": projection_reason,
        "progress_percent": progress,
        "publication_allowed": False,
        "serving_allowed": False,
        "privacy_tombstone_active": supplied.get("privacy_tombstone_active") is True,
        "provider_details_exposed": False,
        "quota_details_exposed": False,
    }
    raw_receipt_state = receipt.get("state")
    receipt_state = raw_receipt_state if raw_receipt_state in BUILD_STATES else "blocked"
    return {
        "contract_name": "ea.governed_spatial_render_build_api_projection.v1",
        "status": receipt_state,
        "state": receipt_state,
        "composition_digest": _safe_digest(receipt.get("composition_digest")),
        "build_receipt_digest": payload_digest(receipt),
        "idempotent_replay": receipt.get("idempotent_replay") is True,
        "reconciliation_required": receipt.get("reconciliation_required") is True,
        "product_projection": safe_projection,
        "publication_allowed": False,
        "serving_allowed": False,
        "provider_details_exposed": False,
        "quota_details_exposed": False,
    }


@router.post("/compose")
async def compose_governed_spatial_render(
    request: Request,
    runtime: GovernedSpatialApiRuntime = Depends(get_governed_spatial_runtime),
) -> dict[str, object]:
    payload = await _raw_object(request, allowed_fields=_COMPOSE_FIELDS)
    render_request = payload.get("request")
    source_packet = payload.get("source_packet")
    if not isinstance(render_request, Mapping) or not isinstance(source_packet, Mapping):
        raise HTTPException(status_code=422, detail="request_and_source_packet_objects_required")
    try:
        receipt = runtime.orchestrator.compose_audit(
            dict(render_request),
            source_packet=dict(source_packet),
        )
    except SpatialIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency_conflict") from exc
    except (GovernedSpatialContractError, SpatialStateError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=_safe_error_code(exc)) from exc
    return _compose_projection(receipt)


@router.post("/build")
async def build_governed_spatial_render(
    request: Request,
    runtime: GovernedSpatialApiRuntime = Depends(get_governed_spatial_runtime),
) -> dict[str, object]:
    payload = await _raw_object(request, allowed_fields=_BUILD_FIELDS)
    authorization = payload.get("authorization")
    evidence_envelope = payload.get("evidence_envelope")
    if not isinstance(authorization, Mapping) or not isinstance(evidence_envelope, Mapping):
        raise HTTPException(status_code=422, detail="authorization_and_evidence_objects_required")
    try:
        parsed = GovernedSpatialBuildAuthorization.model_validate(dict(authorization))
        receipt = runtime.orchestrator.build(
            parsed,
            evidence_envelope=dict(evidence_envelope),
            evidence_registry=runtime.evidence_registry,
        )
    except SpatialIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency_conflict") from exc
    except (GovernedSpatialContractError, SpatialStateError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=_safe_error_code(exc)) from exc
    return _build_projection(receipt)
