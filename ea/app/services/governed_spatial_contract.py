from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


SAFE_INTEGER_MIN = -9_007_199_254_740_991
SAFE_INTEGER_MAX = 9_007_199_254_740_991
MIN_SAFE_INTEGER = SAFE_INTEGER_MIN
MAX_SAFE_INTEGER = SAFE_INTEGER_MAX
DEFAULT_MAX_RAW_JSON_BYTES = 2 * 1024 * 1024

REQUEST_CONTRACT_NAME = "ea.governed_spatial_render_request.v1"
SOURCE_PACKET_CONTRACT_NAME = "ea.governed_spatial_source_packet.v1"
BUILD_AUTHORIZATION_SCHEMA = "ea.governed_spatial_render_build_authorization.v1"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SENSITIVE_KEY_PARTS = {
    "access_token",
    "account_id",
    "admin_url",
    "api_key",
    "authorization_header",
    "credential",
    "dispatch_detail",
    "password",
    "private_key",
    "private_url",
    "provider_account",
    "provider_task",
    "provider_url",
    "raw_trace",
    "refresh_token",
    "secret",
    "session_cookie",
}
FORBIDDEN_RULE_RESULT_FIELDS = frozenset(
    {
        "action_pool",
        "armor",
        "damage",
        "damage_track",
        "dice",
        "effect",
        "initiative",
        "initiative_order",
        "rules_result",
        "successes",
    }
)


class SpatialContractError(ValueError):
    """A local governed-spatial contract failure with a safe reason code."""


class RawJsonContractError(SpatialContractError):
    pass


class CanonicalizationError(SpatialContractError):
    pass


GovernedSpatialContractError = SpatialContractError


def _valid_unicode(value: str) -> bool:
    return not any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def bounded_domain_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if value is None or isinstance(value, bool):
        return errors
    if isinstance(value, int):
        if value < SAFE_INTEGER_MIN or value > SAFE_INTEGER_MAX:
            errors.append(f"{path}:unsafe_integer")
        return errors
    if isinstance(value, float):
        errors.append(f"{path}:float_forbidden")
        return errors
    if isinstance(value, str):
        if not _valid_unicode(value):
            errors.append(f"{path}:invalid_unicode")
        return errors
    if isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(bounded_domain_errors(item, f"{path}[{index}]"))
        return errors
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                errors.append(f"{path}:non_string_key")
                continue
            if not _valid_unicode(key):
                errors.append(f"{path}:invalid_key_unicode")
            errors.extend(bounded_domain_errors(item, f"{path}.{key}"))
        return errors
    errors.append(f"{path}:unsupported_type")
    return errors


def parse_raw_json(
    raw: bytes | bytearray | memoryview | str,
    *,
    max_bytes: int = DEFAULT_MAX_RAW_JSON_BYTES,
) -> dict[str, Any]:
    """Parse raw JSON without ever collapsing duplicate object members."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise RawJsonContractError("raw_json_limit_invalid")
    if isinstance(raw, str):
        if not _valid_unicode(raw):
            raise RawJsonContractError("invalid_unicode")
        encoded = raw.encode("utf-8")
    elif isinstance(raw, (bytes, bytearray, memoryview)):
        encoded = bytes(raw)
    else:
        raise RawJsonContractError("raw_json_bytes_required")
    if not encoded:
        raise RawJsonContractError("raw_json_empty")
    if len(encoded) > max_bytes:
        raise RawJsonContractError("raw_json_too_large")
    if encoded.startswith(b"\xef\xbb\xbf"):
        raise RawJsonContractError("bom_forbidden")
    try:
        text = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RawJsonContractError("invalid_utf8") from exc
    if text.startswith("\ufeff"):
        raise RawJsonContractError("bom_forbidden")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RawJsonContractError(f"duplicate_member:{key}")
            result[key] = value
        return result

    def parse_integer(token: str) -> int:
        if token == "-0":
            raise RawJsonContractError("negative_zero_forbidden")
        value = int(token)
        if value < SAFE_INTEGER_MIN or value > SAFE_INTEGER_MAX:
            raise RawJsonContractError("unsafe_integer")
        return value

    def reject_float(token: str) -> Any:
        raise RawJsonContractError(f"float_forbidden:{token}")

    def reject_constant(token: str) -> Any:
        raise RawJsonContractError(f"non_finite_forbidden:{token}")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_pairs,
            parse_int=parse_integer,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except RawJsonContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise RawJsonContractError("malformed_json") from exc
    if not isinstance(parsed, dict):
        raise RawJsonContractError("root_object_required")
    errors = bounded_domain_errors(parsed)
    if errors:
        raise RawJsonContractError(";".join(errors))
    return parsed


def parse_raw_transport_json(
    raw: bytes | bytearray | memoryview | str,
    *,
    max_bytes: int = DEFAULT_MAX_RAW_JSON_BYTES,
) -> dict[str, Any]:
    if isinstance(raw, str):
        if not _valid_unicode(raw):
            raise RawJsonContractError("invalid_unicode")
        encoded = raw.encode("utf-8")
    elif isinstance(raw, (bytes, bytearray, memoryview)):
        encoded = bytes(raw)
    else:
        raise RawJsonContractError("raw_json_bytes_required")
    if not encoded or len(encoded) > max_bytes:
        raise RawJsonContractError("raw_json_empty" if not encoded else "raw_json_too_large")
    if encoded.startswith(b"\xef\xbb\xbf"):
        raise RawJsonContractError("bom_forbidden")
    try:
        text = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RawJsonContractError("invalid_utf8") from exc

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RawJsonContractError(f"duplicate_member:{key}")
            result[key] = value
        return result

    def parse_integer(token: str) -> int:
        value = int(token)
        if value < SAFE_INTEGER_MIN or value > SAFE_INTEGER_MAX:
            raise RawJsonContractError("unsafe_integer")
        return value

    def parse_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise RawJsonContractError("non_finite_forbidden")
        return value

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_pairs,
            parse_int=parse_integer,
            parse_float=parse_float,
            parse_constant=lambda token: (_ for _ in ()).throw(RawJsonContractError(f"non_finite_forbidden:{token}")),
        )
    except RawJsonContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise RawJsonContractError("malformed_json") from exc
    if not isinstance(parsed, dict):
        raise RawJsonContractError("root_object_required")

    def validate(value: object, path: str = "$") -> None:
        if value is None or isinstance(value, (bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise RawJsonContractError(f"{path}:non_finite")
            return
        if isinstance(value, str):
            if not _valid_unicode(value):
                raise RawJsonContractError(f"{path}:invalid_unicode")
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                validate(nested, f"{path}[{index}]")
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                if not _valid_unicode(key):
                    raise RawJsonContractError(f"{path}:invalid_key_unicode")
                validate(nested, f"{path}.{key}")
            return
        raise RawJsonContractError(f"{path}:unsupported_type")

    validate(parsed)
    return parsed


def _scalar_json(value: object) -> str:
    if value is None or isinstance(value, (bool, int, str)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raise CanonicalizationError("unsupported_scalar")


def bounded_jcs(value: object) -> bytes:
    """Canonicalize the accepted no-float JCS subset to UTF-8 bytes."""

    errors = bounded_domain_errors(value)
    if errors:
        raise CanonicalizationError(";".join(errors))

    def render(item: object) -> str:
        if item is None or isinstance(item, (bool, int, str)):
            return _scalar_json(item)
        if isinstance(item, list):
            return "[" + ",".join(render(part) for part in item) + "]"
        if isinstance(item, dict):
            keys = sorted(item, key=lambda key: key.encode("utf-16-be"))
            return "{" + ",".join(_scalar_json(key) + ":" + render(item[key]) for key in keys) + "}"
        raise CanonicalizationError("unsupported_runtime_type")

    return render(value).encode("utf-8")


def bounded_sha256(value: object, *, prefixed: bool = False) -> str:
    digest = hashlib.sha256(bounded_jcs(value)).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def signed_payload_bytes(envelope: Mapping[str, object]) -> bytes:
    copied = deepcopy(dict(envelope))
    signature = copied.get("signature")
    if not isinstance(signature, dict):
        raise CanonicalizationError("signature_object_required")
    if "signature_value" not in signature or "signed_payload_digest" not in signature:
        raise CanonicalizationError("signature_excluded_members_missing")
    del signature["signature_value"]
    del signature["signed_payload_digest"]
    return bounded_jcs(copied)


def signed_payload(envelope: Mapping[str, object]) -> dict[str, object]:
    copied = deepcopy(dict(envelope))
    signature = copied.get("signature")
    if not isinstance(signature, dict):
        raise CanonicalizationError("signature_object_required")
    if "signature_value" not in signature or "signed_payload_digest" not in signature:
        raise CanonicalizationError("signature_excluded_members_missing")
    del signature["signature_value"]
    del signature["signed_payload_digest"]
    return copied


def public_key_fingerprint(public_key: object) -> str:
    # Compatibility for the existing render facade; crypto owns the implementation.
    from app.services.governed_spatial_crypto import public_key_fingerprint as calculate

    return calculate(public_key)


def encode_ed25519_signature(signature: bytes) -> str:
    from app.services.governed_spatial_crypto import encode_ed25519_signature as encode

    return encode(signature)


def decode_ed25519_signature(value: object) -> bytes:
    from app.services.governed_spatial_crypto import decode_ed25519_signature as decode

    return decode(value)


parse_raw_bounded_json = parse_raw_json


def _path(path: str, key: object) -> str:
    normalized = str(key)
    return f"{path}.{normalized}" if path else normalized


def sensitive_material_paths(value: object, *, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            nested_path = _path(path, key)
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                issues.append(f"sensitive_field:{nested_path}")
            issues.extend(sensitive_material_paths(nested, path=nested_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            issues.extend(sensitive_material_paths(nested, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if "://" in lowered:
            issues.append(f"external_url_forbidden:{path or 'value'}")
        if lowered.startswith("bearer ") or "bearer-" in lowered:
            issues.append(f"authorization_material_forbidden:{path or 'value'}")
        if "provider_account_id" in lowered or "provider_task_id" in lowered:
            issues.append(f"provider_private_identifier_forbidden:{path or 'value'}")
    return issues


def forbidden_rule_field_paths(value: object, *, path: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            nested_path = _path(path, key)
            if normalized in FORBIDDEN_RULE_RESULT_FIELDS:
                paths.append(nested_path)
            paths.extend(forbidden_rule_field_paths(nested, path=nested_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            paths.extend(forbidden_rule_field_paths(nested, path=f"{path}[{index}]"))
    return paths


def _safe_token(value: str) -> str:
    if not _TOKEN_RE.fullmatch(value):
        raise ValueError("stable_token_required")
    return value


def _safe_ref(value: str) -> str:
    if not value or any(character.isspace() for character in value) or "://" in value:
        raise ValueError("provider_safe_ref_required")
    if len(value) > 512:
        raise ValueError("provider_safe_ref_too_long")
    return value


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConsumerContract(ContractModel):
    product: str
    tenant_ref: str
    subject_ref: str

    _product_token = field_validator("product")(_safe_token)
    _consumer_refs = field_validator("tenant_ref", "subject_ref")(_safe_ref)


class ArtifactContract(ContractModel):
    kind: str
    purpose: str
    locale: str

    _artifact_tokens = field_validator("kind", "purpose")(_safe_token)

    @field_validator("locale")
    @classmethod
    def locale_is_bounded(cls, value: str) -> str:
        if not _LOCALE_RE.fullmatch(value):
            raise ValueError("bounded_locale_required")
        return value


class PortalEdgeContract(ContractModel):
    from_room_id: str
    to_room_id: str

    _portal_tokens = field_validator("from_room_id", "to_room_id")(_safe_token)


class SpatialPlanContract(ContractModel):
    room_graph_ref: str
    walkable_mesh_ref: str
    portal_graph_ref: str
    required_room_ids: list[str] = Field(min_length=1)
    route_room_ids: list[str] = Field(min_length=1)
    portal_edges: list[PortalEdgeContract] = Field(default_factory=list)
    route_policy: str = "continuous_all_walkable_rooms"
    start_anchor: str | None = None
    end_anchor: str | None = None
    allow_revisit: StrictBool = False

    _graph_refs = field_validator("room_graph_ref", "walkable_mesh_ref", "portal_graph_ref")(_safe_ref)

    @field_validator("required_room_ids")
    @classmethod
    def required_room_ids_are_unique_tokens(cls, values: list[str]) -> list[str]:
        if any(not _TOKEN_RE.fullmatch(value) for value in values):
            raise ValueError("room_id_token_required")
        if len(values) != len(set(values)):
            raise ValueError("required_room_ids_must_be_unique")
        return values

    @field_validator("route_room_ids")
    @classmethod
    def route_room_ids_are_tokens(cls, values: list[str]) -> list[str]:
        if any(not _TOKEN_RE.fullmatch(value) for value in values):
            raise ValueError("room_id_token_required")
        return values

    @model_validator(mode="after")
    def route_is_continuous(self) -> SpatialPlanContract:
        if self.route_policy != "continuous_all_walkable_rooms":
            raise ValueError("continuous_all_walkable_rooms_required")
        required = set(self.required_room_ids)
        route = self.route_room_ids
        if set(route) != required:
            raise ValueError("route_room_ids_must_equal_required_room_ids")
        if len(route) > 2 * len(self.required_room_ids) - 1:
            raise ValueError("route_visit_count_exceeds_2n_minus_1")
        if any(left == right for left, right in zip(route, route[1:])):
            raise ValueError("consecutive_route_room_ids_forbidden")
        has_revisit = len(route) != len(set(route))
        if self.allow_revisit is not has_revisit:
            raise ValueError("allow_revisit_must_equal_actual_route_revisit")

        declared: set[tuple[str, str]] = set()
        for edge in self.portal_edges:
            left, right = edge.from_room_id, edge.to_room_id
            if left == right:
                raise ValueError("self_portal_edge_forbidden")
            if left not in required or right not in required:
                raise ValueError("portal_edge_room_not_required")
            identity = tuple(sorted((left, right)))
            if identity in declared:
                raise ValueError("duplicate_undirected_portal_edge")
            declared.add(identity)
        for left, right in zip(route, route[1:]):
            if tuple(sorted((left, right))) not in declared:
                raise ValueError(f"route transition has no declared portal:{left}:{right}")
        return self


class StyleContract(ContractModel):
    style_pack_id: str
    room_overrides: dict[str, object] = Field(default_factory=dict)
    asset_license_policy: str = "verified_reuse_only"
    brand_claim_policy: str = "truthful_no_affiliation_claim"
    real_product_claim: bool = False
    asset_reuse_proof_refs: list[str] = Field(default_factory=list)

    _style_token = field_validator("style_pack_id")(_safe_token)

    @field_validator("asset_reuse_proof_refs")
    @classmethod
    def proof_refs_are_safe(cls, values: list[str]) -> list[str]:
        return [_safe_ref(value) for value in values]


class ParticipantContract(ContractModel):
    actor_ref: str
    role: str
    minor: Literal[False] = False
    real_person: Literal[False] = False
    identity_ref: str | None = None
    wardrobe_ref: str | None = None
    equipment_ref: str | None = None
    transform_track_ref: str | None = None
    handedness: str | None = None

    _actor_ref = field_validator("actor_ref")(_safe_ref)
    _role_token = field_validator("role")(_safe_token)

    @field_validator("identity_ref", "wardrobe_ref", "equipment_ref", "transform_track_ref")
    @classmethod
    def optional_refs_are_safe(cls, value: str | None) -> str | None:
        return _safe_ref(value) if value is not None else None


class BeatContract(ContractModel):
    at_s: int | float
    action: str
    actor_ref: str
    target_ref: str | None = None
    location_anchor: str | None = None
    transform_ref: str | None = None

    _action_token = field_validator("action")(_safe_token)
    _beat_actor_ref = field_validator("actor_ref")(_safe_ref)

    @field_validator("at_s")
    @classmethod
    def time_is_finite(cls, value: int | float) -> int | float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
            raise ValueError("finite_nonnegative_time_required")
        return value


class SceneOverlayContract(ContractModel):
    overlay_id: str
    kind: Literal["fictional_combat_choreography"]
    gameplay_truth_ref: str
    location_anchor: str
    start_time_s: int | float
    end_time_s: int | float
    participants: list[ParticipantContract] = Field(min_length=1)
    beats: list[BeatContract] = Field(min_length=1)
    provided_outcome: str | None = None
    provided_outcome_ref: str | None = None
    camera_policy: Literal["continuous_witness_path"]
    graphic_injury: Literal[False]

    _overlay_token = field_validator("overlay_id")(_safe_token)
    _overlay_refs = field_validator("gameplay_truth_ref", "location_anchor")(_safe_ref)

    @model_validator(mode="after")
    def choreography_is_reference_only(self) -> SceneOverlayContract:
        outcomes = [value for value in (self.provided_outcome, self.provided_outcome_ref) if value]
        if len(outcomes) != 1:
            raise ValueError("exactly_one_provided_outcome_ref_required")
        _safe_ref(outcomes[0])
        if any(isinstance(value, bool) for value in (self.start_time_s, self.end_time_s)):
            raise ValueError("finite_overlay_window_required")
        if not all(math.isfinite(float(value)) for value in (self.start_time_s, self.end_time_s)):
            raise ValueError("finite_overlay_window_required")
        if self.start_time_s < 0 or self.end_time_s <= self.start_time_s:
            raise ValueError("ordered_overlay_window_required")
        participants = {participant.actor_ref for participant in self.participants}
        if any(beat.actor_ref not in participants for beat in self.beats):
            raise ValueError("beat_actor_must_be_participant")
        if any(not self.start_time_s <= beat.at_s <= self.end_time_s for beat in self.beats):
            raise ValueError("beat_outside_overlay_window")
        if any(left.at_s > right.at_s for left, right in zip(self.beats, self.beats[1:])):
            raise ValueError("beats_must_be_ordered")
        return self


class CameraContract(ContractModel):
    height_m: int | float
    target_delivery_fps: int = Field(ge=60)
    minimum_effective_motion_fps: int = Field(ge=30)
    motion_profile: str
    cuts_allowed: Literal[False]
    teleports_allowed: Literal[False]
    collision_avoidance: Literal[True]
    rotation_smoothing: Literal[True]

    _motion_token = field_validator("motion_profile")(_safe_token)

    @field_validator("height_m")
    @classmethod
    def height_is_plausible(cls, value: int | float) -> int | float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or not 0.8 <= value <= 2.2:
            raise ValueError("plausible_camera_height_required")
        return value

    @field_validator("target_delivery_fps", "minimum_effective_motion_fps", mode="before")
    @classmethod
    def frame_rate_is_exact_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("exact_integer_frame_rate_required")
        return value


class OutputContract(ContractModel):
    desktop: Literal[True]
    mobile: Literal[True]
    video_codec: str
    interactive_package: bool
    poster_frame: Literal[True]
    contact_sheet: Literal[True]

    _codec_token = field_validator("video_codec")(_safe_token)


class ContentPolicyContract(ContractModel):
    rating: str
    graphic_injury: Literal[False]
    real_person_likeness: Literal[False]
    minor_combatants: Literal[False]

    _rating_token = field_validator("rating")(_safe_token)


class ComposeQuotaContract(ContractModel):
    consume_quota: Literal[False]
    maximum_provider_attempts: Literal[0]


class CallbackContract(ContractModel):
    product_event_ref: str

    _event_ref = field_validator("product_event_ref")(_safe_ref)


class GovernedSpatialRenderRequestV1(ContractModel):
    contract_name: Literal[REQUEST_CONTRACT_NAME] = REQUEST_CONTRACT_NAME
    request_id: UUID
    idempotency_key: str
    consumer: ConsumerContract
    artifact: ArtifactContract
    source_packet_ref: str
    truth_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    spatial_plan: SpatialPlanContract
    style: StyleContract
    scene_overlays: list[SceneOverlayContract] = Field(default_factory=list)
    camera: CameraContract
    output: OutputContract
    content_policy: ContentPolicyContract
    quota: ComposeQuotaContract
    callback: CallbackContract

    _idempotency_token = field_validator("idempotency_key")(_safe_token)
    _source_ref = field_validator("source_packet_ref")(_safe_ref)

    @field_validator("truth_refs", "evidence_refs")
    @classmethod
    def refs_are_nonempty_unique_and_safe(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("refs_must_be_unique")
        return [_safe_ref(value) for value in values]

    @model_validator(mode="after")
    def enforce_cross_field_policy(self) -> GovernedSpatialRenderRequestV1:
        payload = self.model_dump(mode="json")
        sensitive = sensitive_material_paths(payload)
        if sensitive:
            raise ValueError(sensitive[0])
        forbidden = forbidden_rule_field_paths(payload.get("scene_overlays", []), path="scene_overlays")
        if forbidden:
            raise ValueError(f"rules_result_field_forbidden:{forbidden[0]}")
        if self.scene_overlays and self.content_policy.rating != "teen_fictional_combat":
            raise ValueError("combat overlays require bounded fictional-combat rating")
        return self


class SourceRoomContract(ContractModel):
    room_id: str
    room_type: str
    walkable: bool
    boundary_ref: str
    ceiling_height_m: int | float
    geometry_anchor_ref: str
    texture_anchor_refs: list[str] = Field(min_length=1)
    exterior_classification: str | None = None
    accessible: bool | None = None

    _room_tokens = field_validator("room_id", "room_type")(_safe_token)
    _room_refs = field_validator("boundary_ref", "geometry_anchor_ref")(_safe_ref)


class SourcePortalContract(ContractModel):
    portal_id: str
    from_room_id: str
    to_room_id: str
    walkable: Literal[True]

    _portal_tokens = field_validator("portal_id", "from_room_id", "to_room_id")(_safe_token)


class GovernedSpatialSourcePacketV1(ContractModel):
    contract_name: Literal[SOURCE_PACKET_CONTRACT_NAME] = SOURCE_PACKET_CONTRACT_NAME
    source_packet_ref: str
    source_digest: str
    source_retrieved_at: str
    source_packet_created_at: str | None = None
    normalized_floorplan_ref: str
    room_graph_ref: str
    walkable_mesh_ref: str
    portal_graph_ref: str
    scale_m_per_unit: int | float
    orientation_degrees: int | float
    license_provenance_refs: list[str] = Field(min_length=1)
    source_media_assignments: list[dict[str, object]] = Field(default_factory=list)
    inaccessible_rooms: list[dict[str, object]] = Field(default_factory=list)
    route_exclusions: list[dict[str, object]] = Field(default_factory=list)
    rooms: list[SourceRoomContract] = Field(min_length=1)
    portals: list[SourcePortalContract] = Field(default_factory=list)
    route_room_ids: list[str] = Field(min_length=1)
    existing_artifacts: dict[str, dict[str, object]] = Field(default_factory=dict)

    _packet_refs = field_validator(
        "source_packet_ref",
        "normalized_floorplan_ref",
        "room_graph_ref",
        "walkable_mesh_ref",
        "portal_graph_ref",
    )(_safe_ref)

    @field_validator("source_digest")
    @classmethod
    def source_digest_is_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_digest_sha256_required")
        return value.removeprefix("sha256:")

    @field_validator("source_packet_created_at")
    @classmethod
    def source_timestamps_are_offset_aware(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 40:
            raise ValueError("source_timestamp_offset_required")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("source_timestamp_offset_required") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("source_timestamp_offset_required")
        return value

    @model_validator(mode="after")
    def source_inventory_is_coherent(self) -> GovernedSpatialSourcePacketV1:
        payload = self.model_dump(mode="json")
        sensitive = sensitive_material_paths(payload)
        if sensitive:
            raise ValueError(sensitive[0])
        if self.source_packet_created_at is not None:
            retrieved = datetime.fromisoformat(self.source_retrieved_at.replace("Z", "+00:00"))
            created = datetime.fromisoformat(self.source_packet_created_at.replace("Z", "+00:00"))
            if retrieved.tzinfo is None or retrieved.utcoffset() is None:
                raise ValueError("source_timestamp_offset_required")
            if created < retrieved:
                raise ValueError("source_packet_created_before_source_retrieved")
        room_ids = [room.room_id for room in self.rooms]
        if len(room_ids) != len(set(room_ids)):
            raise ValueError("source_room_ids_must_be_unique")
        known = set(room_ids)
        walkable = {room.room_id for room in self.rooms if room.walkable}
        if any(room_id not in known for room_id in self.route_room_ids):
            raise ValueError("route_room_not_in_source_inventory")
        if any(room_id not in walkable for room_id in self.route_room_ids):
            raise ValueError("route_room_not_walkable")
        if set(self.route_room_ids) != walkable:
            raise ValueError("source_route_must_equal_walkable_room_set")
        if len(self.route_room_ids) > 2 * len(walkable) - 1:
            raise ValueError("source_route_visit_count_exceeds_2n_minus_1")
        if any(left == right for left, right in zip(self.route_room_ids, self.route_room_ids[1:])):
            raise ValueError("source_consecutive_route_room_ids_forbidden")

        portal_ids: set[str] = set()
        portal_edges: set[tuple[str, str]] = set()
        for portal in self.portals:
            if portal.portal_id in portal_ids:
                raise ValueError("source_portal_ids_must_be_unique")
            portal_ids.add(portal.portal_id)
            if portal.from_room_id == portal.to_room_id:
                raise ValueError("source_self_portal_forbidden")
            if portal.from_room_id not in known or portal.to_room_id not in known:
                raise ValueError("source_portal_room_not_in_inventory")
            if portal.from_room_id in walkable and portal.to_room_id in walkable:
                portal_edges.add(tuple(sorted((portal.from_room_id, portal.to_room_id))))
        for left, right in zip(self.route_room_ids, self.route_room_ids[1:]):
            if tuple(sorted((left, right))) not in portal_edges:
                raise ValueError("source_route_transition_has_no_portal")
        return self


class GovernedSpatialBuildAuthorization(ContractModel):
    schema_name: Literal[BUILD_AUTHORIZATION_SCHEMA] = BUILD_AUTHORIZATION_SCHEMA
    accepted_composition_digest: str
    idempotency_key: str
    requested_by_ref: str
    authorization_ref: str
    audit_event_ref: str
    consume_quota: Literal[True]
    maximum_provider_attempts: int = Field(ge=1, le=2)
    issued_at: str | None = None
    expires_at: str | None = None
    quota_limit_digest: str | None = None

    _build_token = field_validator("idempotency_key")(_safe_token)
    _build_refs = field_validator("requested_by_ref", "authorization_ref", "audit_event_ref")(_safe_ref)

    @field_validator("accepted_composition_digest", "quota_limit_digest")
    @classmethod
    def build_digests_are_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256_digest_required")
        return value.removeprefix("sha256:") if value is not None else None

    @field_validator("maximum_provider_attempts", mode="before")
    @classmethod
    def attempts_are_exact_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("exact_integer_attempt_count_required")
        return value


def normalize_compatibility_numbers(value: object) -> object:
    """Map finite legacy object floats to explicit decimal strings before hashing."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        if not SAFE_INTEGER_MIN <= value <= SAFE_INTEGER_MAX:
            raise CanonicalizationError("unsafe_integer")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("non_finite_number")
        try:
            decimal = Decimal(str(value))
        except InvalidOperation as exc:
            raise CanonicalizationError("invalid_decimal") from exc
        if decimal == 0:
            return "0"
        rendered = format(decimal.normalize(), "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, Mapping):
        return {str(key): normalize_compatibility_numbers(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_compatibility_numbers(nested) for nested in value]
    raise CanonicalizationError("unsupported_compatibility_type")


def normalized_request_material(request: GovernedSpatialRenderRequestV1 | Mapping[str, object]) -> dict[str, object]:
    supplied = request.model_dump(mode="json") if isinstance(request, GovernedSpatialRenderRequestV1) else dict(request)
    parsed = GovernedSpatialRenderRequestV1.model_validate(supplied)
    payload = parsed.model_dump(mode="json")
    payload.pop("request_id", None)
    normalized = normalize_compatibility_numbers(payload)
    if not isinstance(normalized, dict):
        raise CanonicalizationError("normalized_request_object_required")
    return normalized


def parse_normalized_request_material(value: object) -> dict[str, object]:
    """Accept only the exact request material form, never a compatibility form."""

    if not isinstance(value, Mapping):
        raise ValueError("normalized_request_object_required")
    supplied = dict(value)
    if "request_id" in supplied:
        raise ValueError("normalized_request_request_id_forbidden")
    candidate = dict(supplied)
    candidate["request_id"] = "00000000-0000-0000-0000-000000000000"
    parsed = GovernedSpatialRenderRequestV1.model_validate(candidate)
    normalized = normalized_request_material(parsed)
    try:
        supplied_bytes = bounded_jcs(supplied)
        normalized_bytes = bounded_jcs(normalized)
    except CanonicalizationError as exc:
        raise ValueError("normalized_request_canonical_form_required") from exc
    if supplied_bytes != normalized_bytes:
        raise ValueError("normalized_request_canonical_form_required")
    return normalized


def validate_capability_quota_evidence_semantics(receipt: Mapping[str, object]) -> None:
    errors: list[str] = []
    authorization = receipt.get("authorization")
    quota = receipt.get("quota")
    idempotency = receipt.get("idempotency")
    if not isinstance(authorization, Mapping):
        raise SpatialContractError("authorization_object_required")
    if not isinstance(quota, Mapping):
        raise SpatialContractError("quota_object_required")
    if not isinstance(idempotency, Mapping):
        raise SpatialContractError("idempotency_object_required")

    auth_state = str(authorization.get("state") or "")
    auth_ref = authorization.get("authorization_ref")
    auth_issued = authorization.get("issued_at")
    auth_expires = authorization.get("expires_at")
    auth_quota_digest = authorization.get("quota_limit_digest")
    maximum_attempts = authorization.get("maximum_provider_attempts")
    if isinstance(maximum_attempts, bool) or not isinstance(maximum_attempts, int):
        errors.append("authorization.maximum_provider_attempts:exact_nonnegative_integer_required")
        maximum_attempts = -1
    if auth_state == "not_present_audit_only":
        if any(value is not None for value in (auth_ref, auth_issued, auth_expires, auth_quota_digest)) or maximum_attempts != 0:
            errors.append("authorization:not_present_audit_only_shape_invalid")
    elif auth_state == "valid":
        if any(value is None for value in (auth_ref, auth_issued, auth_expires, auth_quota_digest)):
            errors.append("authorization:valid_evidence_required")
        if maximum_attempts not in {1, 2}:
            errors.append("authorization:valid_attempt_ceiling_invalid")

    state = str(quota.get("state") or "")
    reservation = quota.get("reservation_ref_digest")
    reservation_expires = quota.get("reservation_expires_at")
    attempt = quota.get("attempt_number")
    mutation = quota.get("mutation_token_digest")
    consumption = quota.get("consumption_receipt_digest")
    compensation = quota.get("compensation_receipt_digest")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        errors.append("quota.attempt_number:exact_nonnegative_integer_required")
        attempt = -1
    if maximum_attempts >= 0 and attempt > maximum_attempts:
        errors.append("quota.attempt_number:exceeds_authorization")

    no_execution = (reservation, reservation_expires, mutation, consumption, compensation)
    if state in {"audit_only", "authorization_verified", "blocked"}:
        if attempt != 0 or any(value is not None for value in no_execution):
            errors.append(f"quota.{state}:execution_lineage_must_be_null")
    elif state in {"reservation_held", "released"}:
        if reservation is None or reservation_expires is None or attempt != 0:
            errors.append(f"quota.{state}:reservation_lineage_required")
        if any(value is not None for value in (mutation, consumption, compensation)):
            errors.append(f"quota.{state}:later_lineage_must_be_null")
    elif state in {"attempt_committed", "charge_pending", "cancelled_reconciliation_pending"}:
        if reservation is None or reservation_expires is None or attempt < 1 or mutation is None:
            errors.append(f"quota.{state}:attempt_lineage_required")
        if consumption is not None or compensation is not None:
            errors.append(f"quota.{state}:later_receipts_must_be_null")
    elif state in {"consumed", "closed_consumed", "compensation_pending"}:
        if reservation is None or attempt < 1 or mutation is None or consumption is None:
            errors.append(f"quota.{state}:consumption_lineage_required")
        if compensation is not None:
            errors.append(f"quota.{state}:compensation_must_be_null")
    elif state in {"compensated", "compensation_failed_blocked"}:
        if reservation is None or attempt < 1 or mutation is None or consumption is None or compensation is None:
            errors.append(f"quota.{state}:complete_immutable_lineage_required")
        if state == "compensation_failed_blocked":
            if receipt.get("quota_posture") != "blocked":
                errors.append("quota.compensation_failed_blocked:blocked_posture_required")
            for field in ("key_digest", "normalized_request_digest", "composition_digest", "authorization_binding_digest"):
                if idempotency.get(field) is None:
                    errors.append(f"idempotency.{field}:immutable_build_lineage_required")
    else:
        errors.append("quota.state:unsupported")

    quota_posture = str(receipt.get("quota_posture") or "")
    if quota_posture == "build_allowed":
        if auth_state != "valid":
            errors.append("build_allowed:valid_authorization_required")
        for field in ("key_digest", "normalized_request_digest", "composition_digest", "authorization_binding_digest"):
            if idempotency.get(field) is None:
                errors.append(f"build_allowed:idempotency.{field}_required")

    evidence_refs = receipt.get("evidence_refs")
    families = {
        str(row.get("evidence_family") or "")
        for row in evidence_refs
        if isinstance(row, Mapping)
    } if isinstance(evidence_refs, list) else set()
    capability_state = str(receipt.get("capability_state") or "")
    if capability_state == "verified":
        for family in ("provider_capability", "canonical_compose_validator_exact_version"):
            if family not in families:
                errors.append(f"evidence_family:{family}_required_for_verified")
    if quota_posture == "build_allowed":
        for family in ("quota_snapshot", "kill_switch"):
            if family not in families:
                errors.append(f"evidence_family:{family}_required_for_build_allowed")

    if errors:
        raise SpatialContractError(";".join(errors))


__all__ = [
    "BUILD_AUTHORIZATION_SCHEMA",
    "CanonicalizationError",
    "FORBIDDEN_RULE_RESULT_FIELDS",
    "GovernedSpatialBuildAuthorization",
    "GovernedSpatialRenderRequestV1",
    "GovernedSpatialSourcePacketV1",
    "REQUEST_CONTRACT_NAME",
    "RawJsonContractError",
    "SAFE_INTEGER_MAX",
    "SAFE_INTEGER_MIN",
    "SOURCE_PACKET_CONTRACT_NAME",
    "SpatialContractError",
    "GovernedSpatialContractError",
    "MAX_SAFE_INTEGER",
    "MIN_SAFE_INTEGER",
    "bounded_domain_errors",
    "bounded_jcs",
    "bounded_sha256",
    "forbidden_rule_field_paths",
    "normalized_request_material",
    "parse_normalized_request_material",
    "parse_raw_json",
    "parse_raw_bounded_json",
    "parse_raw_transport_json",
    "signed_payload",
    "sensitive_material_paths",
    "signed_payload_bytes",
    "validate_capability_quota_evidence_semantics",
]
