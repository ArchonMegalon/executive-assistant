from __future__ import annotations

import base64
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Iterator, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator, model_validator

from app.services.governed_spatial_contract import (
    GovernedSpatialRenderRequestV1,
    GovernedSpatialSourcePacketV1,
    RawJsonContractError,
    bounded_domain_errors,
    bounded_jcs,
    normalize_compatibility_numbers,
    normalized_request_material,
    parse_normalized_request_material,
    parse_raw_json,
)
from app.services.governed_spatial_state import (
    SpatialCompositionLifecycleGuard,
    SpatialLifecycleAuthority,
    SpatialStateError,
)


SAFE_INTEGER_MAX = 9_007_199_254_740_991
MAX_CANONICAL_MATERIAL_BYTES = 2 * 1024 * 1024
CANONICALIZATION = "rfc8785_jcs_bounded_no_float_v1"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_EXECUTION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SIGNED_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{85}[AQgw]$")
_URI_SCHEME_RE = re.compile(r"^(?:https?|file|ftp|s3|gs|ssh|data|javascript):", re.IGNORECASE)
_SHELL_OR_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f$;&|`<>()[\]{}*?!~'\"]")
_PROVIDER_PRIVATE_RE = re.compile(
    r"(?:^|[._:-])(?:provider|account|task|job|session|credential|secret|api[-_]?key|access[-_]?token)(?:$|[._:-])",
    re.IGNORECASE,
)
_INERT_IMAGES = frozenset({"image/avif", "image/jpeg", "image/png", "image/webp"})
_SAFE_MODELS = frozenset({"model/gltf+json", "model/gltf-binary", "model/obj"})
_PASSIVE_STRUCTURED = frozenset({"application/json"})
_PURPOSE_MEDIA_TYPES = {
    "source_geometry": _SAFE_MODELS | _PASSIVE_STRUCTURED,
    "source_texture": _INERT_IMAGES,
    "style_asset": _SAFE_MODELS | _INERT_IMAGES,
    "brand_reuse_proof": _PASSIVE_STRUCTURED | _INERT_IMAGES,
    "visual_direction": _PASSIVE_STRUCTURED | _INERT_IMAGES,
    "verification_reference": _PASSIVE_STRUCTURED | _INERT_IMAGES | {"video/mp4"},
}
# Authority metadata identities are not adapter-consumed byte assets in this slice.
_OPAQUE_SOURCE_METADATA_FIELDS = frozenset(
    {"license_provenance_refs", "inaccessible_rooms", "route_exclusions", "existing_artifacts"}
)
_SOURCE_ASSIGNMENT_BYTE_REF_FIELDS = {
    "geometry_ref": ("source_geometry", False),
    "geometry_refs": ("source_geometry", True),
    "texture_ref": ("source_texture", False),
    "texture_refs": ("source_texture", True),
    "media_ref": ("source_texture", False),
    "media_refs": ("source_texture", True),
}
_SOURCE_ASSIGNMENT_METADATA_FIELDS = frozenset({"room_id"})
_MAX_DECIMAL_PRECISION = 24
_MAX_DECIMAL_SCALE = 18


class SpatialExecutionContractError(ValueError):
    """Provider-redacted execution contract failure with a stable reason code."""


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


def validate_execution_ref(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("execution_ref_shape_invalid")
    if any(character.isspace() for character in value):
        raise ValueError("execution_ref_whitespace_forbidden")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError("execution_ref_path_syntax_forbidden")
    if "://" in value or _URI_SCHEME_RE.match(value):
        raise ValueError("execution_ref_uri_forbidden")
    if _SHELL_OR_CONTROL_RE.search(value):
        raise ValueError("execution_ref_shell_syntax_forbidden")
    if _PROVIDER_PRIVATE_RE.search(value):
        raise ValueError("execution_ref_provider_private_forbidden")
    if not _EXECUTION_REF_RE.fullmatch(value):
        raise ValueError("execution_ref_opaque_token_required")
    return value


def validate_digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError("sha256_digest_required")
    return value


def _validate_token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ValueError("stable_token_required")
    return value


def _validate_timestamp(value: str) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("offset_aware_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("offset_aware_timestamp_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("offset_aware_timestamp_required")
    return value


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _unique(values: list[str], reason: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(reason)
    return values


def _token_list(values: list[str]) -> list[str]:
    _unique(values, "token_list_must_be_unique")
    for value in values:
        _validate_token(value)
    return values


def _ref_list(values: list[str]) -> list[str]:
    _unique(values, "ref_list_must_be_unique")
    for value in values:
        validate_execution_ref(value)
    return values


def _decimal_string(value: str) -> str:
    if not isinstance(value, str) or len(value) > 43 or not _DECIMAL_RE.fullmatch(value):
        raise ValueError("canonical_nonnegative_decimal_string_required")
    if "." in value and value.endswith("0"):
        raise ValueError("canonical_nonnegative_decimal_string_required")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("canonical_nonnegative_decimal_string_required") from exc
    _, digits, exponent = decimal.as_tuple()
    scale = max(0, -exponent)
    if len(digits) > _MAX_DECIMAL_PRECISION or scale > _MAX_DECIMAL_SCALE:
        raise ValueError("canonical_decimal_precision_exceeded")
    return value


def _signed_decimal_string(value: str) -> str:
    reason = "canonical_signed_decimal_string_required"
    if not isinstance(value, str) or len(value) > 44 or not _SIGNED_DECIMAL_RE.fullmatch(value):
        raise ValueError(reason)
    if value.startswith("-0") and (value == "-0" or value.startswith("-0.")):
        raise ValueError(reason)
    if "." in value and value.endswith("0"):
        raise ValueError(reason)
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(reason) from exc
    _, digits, exponent = decimal.as_tuple()
    if len(digits) > _MAX_DECIMAL_PRECISION or max(0, -exponent) > _MAX_DECIMAL_SCALE:
        raise ValueError("canonical_decimal_precision_exceeded")
    return value


def _bounded_canonical_bytes(value: object, *, maximum: int = MAX_CANONICAL_MATERIAL_BYTES) -> bytes:
    errors = bounded_domain_errors(value)
    if errors:
        raise SpatialExecutionContractError(errors[0].split(":", 1)[-1])
    encoded = bounded_jcs(value)
    if len(encoded) > maximum:
        raise SpatialExecutionContractError("canonical_material_too_large")
    return encoded


def _canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_bounded_canonical_bytes(value)).hexdigest()


def _canonical_equal(left: object, right: object) -> bool:
    return _bounded_canonical_bytes(left) == _bounded_canonical_bytes(right)


class RenderRoom(StrictContractModel):
    room_id: str
    room_type: str
    walkable: StrictBool
    boundary_ref: str
    ceiling_height_m: str
    geometry_anchor_ref: str
    texture_anchor_refs: list[str] = Field(min_length=1, max_length=1000)
    exterior_classification: str | None = None
    accessible: StrictBool | None = None

    _tokens = field_validator("room_id", "room_type")(_validate_token)
    _refs = field_validator("boundary_ref", "geometry_anchor_ref")(validate_execution_ref)
    _decimal = field_validator("ceiling_height_m")(_decimal_string)
    _texture_refs = field_validator("texture_anchor_refs")(_ref_list)
    _optional_token = field_validator("exterior_classification")(
        lambda value: _validate_token(value) if value is not None else None
    )


class RenderArtifact(StrictContractModel):
    kind: Literal["continuous_walkthrough"]
    purpose: Literal["walkthrough", "encounter_preview"]
    locale: str

    @field_validator("locale")
    @classmethod
    def locale_is_bounded(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", value):
            raise ValueError("bounded_locale_required")
        return value


class RenderPortal(StrictContractModel):
    portal_id: str
    from_room_id: str
    to_room_id: str
    walkable: Literal[True]

    _tokens = field_validator("portal_id", "from_room_id", "to_room_id")(_validate_token)


class RenderParticipant(StrictContractModel):
    actor_ref: str
    role: str
    minor: Literal[False]
    real_person: Literal[False]
    identity_ref: str | None = None
    wardrobe_ref: str | None = None
    equipment_ref: str | None = None
    transform_track_ref: str | None = None
    handedness: str | None = None

    _actor = field_validator("actor_ref")(validate_execution_ref)
    _role = field_validator("role")(_validate_token)
    _refs = field_validator("identity_ref", "wardrobe_ref", "equipment_ref", "transform_track_ref")(
        lambda value: validate_execution_ref(value) if value is not None else None
    )
    _handedness = field_validator("handedness")(
        lambda value: _validate_token(value) if value is not None else None
    )


class RenderBeat(StrictContractModel):
    at_s: str
    action: str
    actor_ref: str
    target_ref: str | None = None
    location_anchor: str | None = None
    transform_ref: str | None = None

    _at = field_validator("at_s")(_decimal_string)
    _action = field_validator("action")(_validate_token)
    _refs = field_validator("actor_ref", "target_ref", "location_anchor", "transform_ref")(
        lambda value: validate_execution_ref(value) if value is not None else None
    )


class RenderSceneOverlay(StrictContractModel):
    overlay_id: str
    kind: Literal["fictional_combat_choreography"]
    gameplay_truth_ref: str
    location_anchor: str
    start_time_s: str
    end_time_s: str
    participants: list[RenderParticipant] = Field(min_length=1, max_length=1000)
    beats: list[RenderBeat] = Field(min_length=1, max_length=10000)
    provided_outcome: str | None = None
    provided_outcome_ref: str | None = None
    camera_policy: Literal["continuous_witness_path"]
    graphic_injury: Literal[False]

    _overlay = field_validator("overlay_id")(_validate_token)
    _refs = field_validator("gameplay_truth_ref", "location_anchor")(validate_execution_ref)
    _times = field_validator("start_time_s", "end_time_s")(_decimal_string)

    @model_validator(mode="after")
    def validate_overlay(self) -> RenderSceneOverlay:
        outcomes = [value for value in (self.provided_outcome, self.provided_outcome_ref) if value is not None]
        if len(outcomes) != 1:
            raise ValueError("exactly_one_provided_outcome_required")
        validate_execution_ref(outcomes[0])
        start = Decimal(self.start_time_s)
        end = Decimal(self.end_time_s)
        if end <= start:
            raise ValueError("ordered_overlay_window_required")
        participants = {participant.actor_ref for participant in self.participants}
        previous: Decimal | None = None
        for beat in self.beats:
            current = Decimal(beat.at_s)
            if beat.actor_ref not in participants:
                raise ValueError("beat_actor_must_be_participant")
            if not start <= current <= end:
                raise ValueError("beat_outside_overlay_window")
            if previous is not None and current < previous:
                raise ValueError("beats_must_be_ordered")
            previous = current
        return self


class RenderCamera(StrictContractModel):
    height_m: str
    target_delivery_fps: StrictInt = Field(ge=60, le=240)
    minimum_effective_motion_fps: StrictInt = Field(ge=30, le=240)
    motion_profile: str
    cuts_allowed: Literal[False]
    teleports_allowed: Literal[False]
    collision_avoidance: Literal[True]
    rotation_smoothing: Literal[True]

    _height = field_validator("height_m")(_decimal_string)
    _motion = field_validator("motion_profile")(_validate_token)

    @model_validator(mode="after")
    def validate_camera(self) -> RenderCamera:
        if not Decimal("0.8") <= Decimal(self.height_m) <= Decimal("2.2"):
            raise ValueError("plausible_camera_height_required")
        if self.minimum_effective_motion_fps > self.target_delivery_fps:
            raise ValueError("effective_fps_exceeds_delivery_fps")
        return self


class RenderOutput(StrictContractModel):
    desktop: Literal[True]
    mobile: Literal[True]
    video_codec: str
    interactive_package: StrictBool
    poster_frame: Literal[True]
    contact_sheet: Literal[True]

    _codec = field_validator("video_codec")(_validate_token)


class RenderContentPolicy(StrictContractModel):
    rating: str
    graphic_injury: Literal[False]
    real_person_likeness: Literal[False]
    minor_combatants: Literal[False]

    _rating = field_validator("rating")(_validate_token)


class GovernedSpatialRenderSpecV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_render_spec.v1"]
    contract_version: Literal["1.0.0"]
    product: Literal["propertyquarry", "chummer"]
    artifact: RenderArtifact
    normalized_floorplan_ref: str
    room_graph_ref: str
    walkable_mesh_ref: str
    portal_graph_ref: str
    scale_m_per_unit: str
    orientation_degrees: str
    rooms: list[RenderRoom] = Field(min_length=1, max_length=10000)
    portals: list[RenderPortal] = Field(max_length=20000)
    required_room_ids: list[str] = Field(min_length=1, max_length=10000)
    route_room_ids: list[str] = Field(min_length=1, max_length=19999)
    allow_revisit: StrictBool
    camera: RenderCamera
    output: RenderOutput
    content_policy: RenderContentPolicy
    scene_overlays: list[RenderSceneOverlay] = Field(max_length=1000)

    _refs = field_validator(
        "normalized_floorplan_ref", "room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"
    )(validate_execution_ref)
    _scale = field_validator("scale_m_per_unit")(_decimal_string)
    _orientation = field_validator("orientation_degrees")(_signed_decimal_string)
    _required_room_ids = field_validator("required_room_ids")(_token_list)

    @field_validator("route_room_ids")
    @classmethod
    def route_room_ids_are_tokens(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_token(value)
        return values

    @model_validator(mode="after")
    def validate_route(self) -> GovernedSpatialRenderSpecV1:
        room_ids = [room.room_id for room in self.rooms]
        if len(room_ids) != len(set(room_ids)):
            raise ValueError("render_room_ids_must_be_unique")
        known = set(room_ids)
        walkable = {room.room_id for room in self.rooms if room.walkable}
        if set(self.required_room_ids) != walkable:
            raise ValueError("required_rooms_must_equal_walkable_inventory")
        if set(self.route_room_ids) != walkable:
            raise ValueError("route_rooms_must_equal_walkable_inventory")
        if len(self.route_room_ids) > 2 * len(self.required_room_ids) - 1:
            raise ValueError("route_visit_count_exceeds_2n_minus_1")
        if any(left == right for left, right in zip(self.route_room_ids, self.route_room_ids[1:])):
            raise ValueError("consecutive_route_room_ids_forbidden")
        actual_revisit = len(self.route_room_ids) != len(set(self.route_room_ids))
        if self.allow_revisit is not actual_revisit:
            raise ValueError("allow_revisit_must_equal_actual_route_revisit")
        portal_ids: set[str] = set()
        edges: set[tuple[str, str]] = set()
        for portal in self.portals:
            if portal.portal_id in portal_ids:
                raise ValueError("render_portal_ids_must_be_unique")
            portal_ids.add(portal.portal_id)
            if portal.from_room_id == portal.to_room_id:
                raise ValueError("self_portal_forbidden")
            if portal.from_room_id not in known or portal.to_room_id not in known:
                raise ValueError("portal_room_not_in_inventory")
            edges.add(tuple(sorted((portal.from_room_id, portal.to_room_id))))
        for left, right in zip(self.route_room_ids, self.route_room_ids[1:]):
            if tuple(sorted((left, right))) not in edges:
                raise ValueError("route_transition_has_no_portal")
        if self.product == "propertyquarry" and self.scene_overlays:
            raise ValueError("propertyquarry_scene_overlays_forbidden")
        return self


class GovernedSpatialStyleSnapshotV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_style_snapshot.v1"]
    contract_version: Literal["1.0.0"]
    style_pack_id: str
    registry_contract: str
    registry_version: str
    registry_digest: str
    consumer_products: list[Literal["propertyquarry", "chummer"]] = Field(min_length=1, max_length=2)
    status: Literal["accepted"]
    room_types: list[str] = Field(min_length=1, max_length=1000)
    room_rules: dict[str, list[str]]
    composition_rules: list[str] = Field(max_length=1000)
    palette: list[str] = Field(max_length=1000)
    materials: list[str] = Field(max_length=1000)
    catalog_families: list[str] = Field(max_length=1000)
    furniture_catalog_refs: list[str] = Field(max_length=1000)
    negative_constraints: list[str] = Field(max_length=1000)
    asset_license_policy: Literal["verified_reuse_only"]
    brand_claim_policy: Literal["truthful_no_affiliation_claim"]
    adapter_profile_ref: str
    external_asset_refs: list[str] = Field(max_length=1000)
    provenance_status: Literal["verified"]
    provenance_refs: list[str] = Field(min_length=1, max_length=1000)
    source_retrieved_at: str
    visual_direction_refs: list[str] = Field(max_length=1000)
    visual_regression_refs: list[str] = Field(max_length=1000)
    acceptance_contact_sheet_refs: list[str] = Field(max_length=1000)

    _tokens = field_validator(
        "style_pack_id", "registry_contract", "registry_version"
    )(_validate_token)
    _digest = field_validator("registry_digest")(validate_digest)
    _token_arrays = field_validator(
        "room_types", "composition_rules", "palette", "materials", "catalog_families", "negative_constraints"
    )(_token_list)
    _refs = field_validator("adapter_profile_ref")(validate_execution_ref)
    _ref_arrays = field_validator(
        "furniture_catalog_refs", "external_asset_refs", "provenance_refs", "visual_direction_refs",
        "visual_regression_refs", "acceptance_contact_sheet_refs"
    )(_ref_list)
    _timestamp = field_validator("source_retrieved_at")(_validate_timestamp)

    @field_validator("consumer_products")
    @classmethod
    def products_are_unique(cls, values: list[str]) -> list[str]:
        return _unique(values, "consumer_products_must_be_unique")

    @field_validator("room_rules")
    @classmethod
    def room_rules_are_typed(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if not 1 <= len(value) <= 1000:
            raise ValueError("room_rules_cardinality_invalid")
        for room_type, rules in value.items():
            _validate_token(room_type)
            if not 1 <= len(rules) <= 1000:
                raise ValueError("room_rule_list_cardinality_invalid")
            _token_list(rules)
        return value

    @model_validator(mode="after")
    def style_is_coherent(self) -> GovernedSpatialStyleSnapshotV1:
        if set(self.room_rules) != set(self.room_types):
            raise ValueError("room_rules_must_match_room_types")
        if bool(self.catalog_families) is not bool(self.furniture_catalog_refs):
            raise ValueError("catalog_families_and_product_refs_must_be_jointly_present")
        return self


class GovernedSpatialAssetBindingV1(StrictContractModel):
    asset_ref: str
    sha256: str
    size_bytes: StrictInt = Field(ge=1, le=SAFE_INTEGER_MAX)
    media_type: str
    purpose: Literal[
        "source_geometry", "source_texture", "style_asset", "brand_reuse_proof",
        "visual_direction", "verification_reference"
    ]
    license_provenance_ref: str
    source_owner_ref: str

    _refs = field_validator("asset_ref", "license_provenance_ref", "source_owner_ref")(validate_execution_ref)
    _digest = field_validator("sha256")(validate_digest)

    @model_validator(mode="after")
    def media_type_matches_purpose(self) -> GovernedSpatialAssetBindingV1:
        if self.media_type not in _PURPOSE_MEDIA_TYPES[self.purpose]:
            raise ValueError("media_type_not_allowlisted_for_purpose")
        return self


def _source_asset_inventory(source: Mapping[str, object]) -> dict[str, str]:
    inventory: dict[str, str] = {}

    def add(ref: object, purpose: str) -> None:
        if not isinstance(ref, str):
            raise ValueError("source_asset_ref_invalid")
        if ref in inventory and inventory[ref] != purpose:
            raise ValueError("source_asset_purpose_ambiguous")
        inventory[ref] = purpose

    for field in ("normalized_floorplan_ref", "room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"):
        add(source.get(field), "source_geometry")
    rooms = source.get("rooms")
    if not isinstance(rooms, list):
        raise ValueError("source_rooms_invalid")
    source_room_ids: set[str] = set()
    for room in rooms:
        if not isinstance(room, Mapping):
            raise ValueError("source_room_invalid")
        room_id = room.get("room_id")
        if not isinstance(room_id, str):
            raise ValueError("source_room_id_invalid")
        source_room_ids.add(room_id)
        add(room.get("boundary_ref"), "source_geometry")
        add(room.get("geometry_anchor_ref"), "source_geometry")
        texture_refs = room.get("texture_anchor_refs")
        if not isinstance(texture_refs, list):
            raise ValueError("source_texture_refs_invalid")
        for ref in texture_refs:
            add(ref, "source_texture")

    assignments = source.get("source_media_assignments")
    if not isinstance(assignments, list):
        raise ValueError("source_media_assignments_invalid")
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            raise ValueError("source_media_assignment_invalid")
        unsupported = set(assignment) - set(_SOURCE_ASSIGNMENT_BYTE_REF_FIELDS) - _SOURCE_ASSIGNMENT_METADATA_FIELDS
        if unsupported:
            raise ValueError("source_media_assignment_member_unsupported")
        if "room_id" in assignment:
            room_id = assignment["room_id"]
            _validate_token(room_id)
            if room_id not in source_room_ids:
                raise ValueError("source_media_assignment_room_not_in_inventory")
        recognized = False
        for key, (purpose, plural) in _SOURCE_ASSIGNMENT_BYTE_REF_FIELDS.items():
            if key not in assignment:
                continue
            value = assignment[key]
            recognized = True
            if plural:
                if not isinstance(value, list) or not 1 <= len(value) <= 1000:
                    raise ValueError("source_asset_ref_list_invalid")
                refs = value
            else:
                if not isinstance(value, str):
                    raise ValueError("source_asset_ref_invalid")
                refs = [value]
            for ref in refs:
                validate_execution_ref(ref)
                add(ref, purpose)
            if plural:
                _unique(refs, "source_asset_ref_list_must_be_unique")
        if not recognized:
            raise ValueError("source_media_assignment_byte_ref_required")
    for field in _OPAQUE_SOURCE_METADATA_FIELDS:
        if field not in source:
            raise ValueError("source_metadata_field_missing")
    return inventory


def _style_asset_inventory(style: GovernedSpatialStyleSnapshotV1) -> dict[str, str]:
    inventory: dict[str, str] = {}
    groups = (
        (style.furniture_catalog_refs, "style_asset"),
        (style.external_asset_refs, "style_asset"),
        (style.visual_direction_refs, "visual_direction"),
        (style.visual_regression_refs, "verification_reference"),
        (style.acceptance_contact_sheet_refs, "verification_reference"),
    )
    for refs, purpose in groups:
        for ref in refs:
            if ref in inventory and inventory[ref] != purpose:
                raise ValueError("style_asset_purpose_ambiguous")
            inventory[ref] = purpose
    return inventory


def _validate_asset_bindings(
    bindings: list[GovernedSpatialAssetBindingV1],
    style: GovernedSpatialStyleSnapshotV1,
    source: Mapping[str, object] | None = None,
) -> None:
    refs = [binding.asset_ref for binding in bindings]
    if len(refs) != len(set(refs)):
        raise ValueError("asset_refs_must_be_unique")
    pairs = [(binding.purpose, binding.asset_ref) for binding in bindings]
    if len(pairs) != len(set(pairs)):
        raise ValueError("asset_purpose_ref_pairs_must_be_unique")
    by_ref = {binding.asset_ref: binding for binding in bindings}
    required = _style_asset_inventory(style)
    if source is not None:
        for ref, purpose in _source_asset_inventory(source).items():
            if ref in required and required[ref] != purpose:
                raise ValueError("asset_ref_cross_inventory_purpose_ambiguous")
            required[ref] = purpose
    catalog_proof_refs: list[str] = []
    for catalog_ref in style.furniture_catalog_refs:
        catalog_asset = by_ref.get(catalog_ref)
        if catalog_asset is None or catalog_asset.purpose != "style_asset":
            raise ValueError("catalog_style_asset_binding_required")
        if catalog_asset.license_provenance_ref == catalog_asset.asset_ref:
            raise ValueError("catalog_asset_self_proof_forbidden")
        proof = by_ref.get(catalog_asset.license_provenance_ref)
        if proof is None or proof.purpose != "brand_reuse_proof":
            raise ValueError("catalog_brand_reuse_proof_binding_required")
        catalog_proof_refs.append(proof.asset_ref)
        required[proof.asset_ref] = "brand_reuse_proof"
    if len(catalog_proof_refs) != len(set(catalog_proof_refs)):
        raise ValueError("catalog_brand_reuse_proofs_must_be_distinct")
    if source is not None:
        if set(by_ref) != set(required):
            raise ValueError("asset_binding_inventory_mismatch")
        if any(by_ref[ref].purpose != purpose for ref, purpose in required.items()):
            raise ValueError("asset_binding_purpose_mismatch")


def _validate_material_semantics(
    request: Mapping[str, object], source: Mapping[str, object], style: GovernedSpatialStyleSnapshotV1,
    bindings: list[GovernedSpatialAssetBindingV1],
) -> None:
    spatial_plan = request.get("spatial_plan")
    request_style = request.get("style")
    if not isinstance(spatial_plan, Mapping) or not isinstance(request_style, Mapping):
        raise ValueError("material_nested_contract_invalid")
    if request.get("source_packet_ref") != source.get("source_packet_ref"):
        raise ValueError("request_source_packet_ref_mismatch")
    for field in ("room_graph_ref", "walkable_mesh_ref", "portal_graph_ref"):
        if spatial_plan.get(field) != source.get(field):
            raise ValueError(f"request_source_{field}_mismatch")
    rooms = source.get("rooms")
    portals = source.get("portals")
    if not isinstance(rooms, list) or not isinstance(portals, list):
        raise ValueError("source_graph_inventory_invalid")
    walkable = [room.get("room_id") for room in rooms if isinstance(room, Mapping) and room.get("walkable") is True]
    if set(spatial_plan.get("required_room_ids", [])) != set(walkable):
        raise ValueError("request_required_rooms_source_mismatch")
    source_route = source.get("route_room_ids")
    if spatial_plan.get("route_room_ids") != source_route:
        raise ValueError("request_route_source_mismatch")
    if not isinstance(source_route, list):
        raise ValueError("source_route_invalid")
    if spatial_plan.get("allow_revisit") is not (len(source_route) != len(set(source_route))):
        raise ValueError("request_allow_revisit_source_mismatch")
    walkable_set = set(walkable)
    source_edges = {
        tuple(sorted((portal.get("from_room_id"), portal.get("to_room_id"))))
        for portal in portals
        if isinstance(portal, Mapping)
        and portal.get("from_room_id") in walkable_set
        and portal.get("to_room_id") in walkable_set
    }
    request_edges_raw = spatial_plan.get("portal_edges")
    if not isinstance(request_edges_raw, list):
        raise ValueError("request_portal_edges_invalid")
    request_edges = {
        tuple(sorted((edge.get("from_room_id"), edge.get("to_room_id"))))
        for edge in request_edges_raw if isinstance(edge, Mapping)
    }
    if request_edges != source_edges or len(request_edges) != len(request_edges_raw):
        raise ValueError("request_portal_edges_source_mismatch")
    for field in ("style_pack_id", "asset_license_policy", "brand_claim_policy"):
        if request_style.get(field) != getattr(style, field):
            raise ValueError(f"request_style_{field}_mismatch")
    claims_real_products = bool(style.furniture_catalog_refs)
    if request_style.get("real_product_claim") is not claims_real_products:
        raise ValueError("request_real_product_claim_mismatch")
    by_ref = {binding.asset_ref: binding for binding in bindings}
    expected_proofs = [
        by_ref[ref].license_provenance_ref for ref in style.furniture_catalog_refs if ref in by_ref
    ]
    supplied_proofs = request_style.get("asset_reuse_proof_refs")
    if not isinstance(supplied_proofs, list) or supplied_proofs != expected_proofs:
        raise ValueError("request_asset_reuse_proof_refs_mismatch")
    if len(expected_proofs) != len(set(expected_proofs)):
        raise ValueError("request_asset_reuse_proof_refs_must_be_distinct")


class GovernedSpatialExecutionMaterialV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_execution_material.v1"]
    contract_version: Literal["1.0.0"]
    composition_digest: str
    request_digest: str
    source_packet_digest: str
    style_snapshot_digest: str
    output_contract_digest: str
    execution_target_digest: str
    normalized_request: dict[str, Any]
    normalized_source_packet: dict[str, Any]
    style_snapshot: GovernedSpatialStyleSnapshotV1
    asset_bindings: list[GovernedSpatialAssetBindingV1] = Field(min_length=1, max_length=10000)
    source_packet_created_at: str
    compose_created_at: str
    retention_expires_at: str

    _digests = field_validator(
        "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
        "output_contract_digest", "execution_target_digest"
    )(validate_digest)
    _timestamps = field_validator(
        "source_packet_created_at", "compose_created_at", "retention_expires_at"
    )(_validate_timestamp)

    @field_validator("normalized_request", mode="before")
    @classmethod
    def normalized_request_is_strict_typed_payload(cls, value: object) -> dict[str, object]:
        return parse_normalized_request_material(value)

    @field_validator("normalized_source_packet", mode="before")
    @classmethod
    def normalized_source_packet_is_strict_typed_payload(cls, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError("normalized_source_packet_object_required")
        supplied = dict(value)
        parsed = GovernedSpatialSourcePacketV1.model_validate(value)
        normalized = normalize_compatibility_numbers(parsed.model_dump(mode="json"))
        if not isinstance(normalized, dict):
            raise ValueError("normalized_source_packet_object_required")
        if not _canonical_equal(supplied, normalized):
            raise ValueError("normalized_source_packet_canonical_form_required")
        return normalized

    @model_validator(mode="after")
    def material_is_coherent(self) -> GovernedSpatialExecutionMaterialV1:
        for payload in (self.normalized_request, self.normalized_source_packet):
            errors = bounded_domain_errors(payload)
            if errors:
                raise ValueError(errors[0].split(":", 1)[-1])
        packet_created = self.normalized_source_packet.get("source_packet_created_at")
        if packet_created is None:
            raise ValueError("source_packet_created_at_required_for_execution_material")
        if packet_created != self.source_packet_created_at:
            raise ValueError("source_packet_created_at_binding_mismatch")
        if self.request_digest != _canonical_digest(self.normalized_request):
            raise ValueError("request_digest_mismatch")
        if self.source_packet_digest != _canonical_digest(self.normalized_source_packet):
            raise ValueError("source_packet_digest_mismatch")
        if self.style_snapshot_digest != _canonical_digest(self.style_snapshot.model_dump(mode="json")):
            raise ValueError("style_snapshot_digest_mismatch")
        if self.output_contract_digest != _canonical_digest(self.normalized_request["output"]):
            raise ValueError("output_contract_digest_mismatch")
        _validate_material_semantics(
            self.normalized_request, self.normalized_source_packet, self.style_snapshot, self.asset_bindings
        )
        _validate_asset_bindings(self.asset_bindings, self.style_snapshot, self.normalized_source_packet)
        if _as_datetime(self.style_snapshot.source_retrieved_at) > _as_datetime(self.compose_created_at):
            raise ValueError("style_source_timestamp_after_compose")
        source_retrieved = self.normalized_source_packet.get("source_retrieved_at")
        if not isinstance(source_retrieved, str):
            raise ValueError("source_retrieved_at_required")
        if not (
            _as_datetime(source_retrieved)
            <= _as_datetime(self.source_packet_created_at)
            <= _as_datetime(self.compose_created_at)
        ):
            raise ValueError("material_timestamp_chronology_invalid")
        if not _as_datetime(self.compose_created_at) < _as_datetime(self.retention_expires_at):
            raise ValueError("material_retention_expiry_invalid")
        return self


class GovernedSpatialExecutionMaterialEnvelopeV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_execution_material_envelope.v1"]
    contract_version: Literal["1.0.0"]
    environment: Literal["development", "test", "candidate", "production"]
    material_identity: str
    material_digest: str
    composition_digest: str
    request_digest: str
    source_packet_digest: str
    style_snapshot_digest: str
    output_contract_digest: str
    execution_target_digest: str
    created_at: str
    retention_expires_at: str
    key_ref: str
    key_epoch: StrictInt = Field(ge=0, le=SAFE_INTEGER_MAX)
    key_fingerprint: str
    algorithm: Literal["aes-256-gcm"]
    nonce_encoding: Literal["base64url_no_padding"]
    nonce: str
    ciphertext_encoding: Literal["base64url_no_padding"]
    ciphertext: str
    canonicalization: Literal[CANONICALIZATION]
    aad_digest: str

    _refs = field_validator("material_identity", "key_ref")(validate_execution_ref)
    _digests = field_validator(
        "material_digest", "composition_digest", "request_digest", "source_packet_digest",
        "style_snapshot_digest", "output_contract_digest", "execution_target_digest",
        "key_fingerprint", "aad_digest"
    )(validate_digest)
    _timestamps = field_validator("created_at", "retention_expires_at")(_validate_timestamp)

    @staticmethod
    def _decode(value: str, reason: str) -> bytes:
        if not value or "=" in value or not _BASE64URL_RE.fullmatch(value):
            raise ValueError(reason)
        try:
            decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except ValueError as exc:
            raise ValueError(reason) from exc
        if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
            raise ValueError(reason)
        return decoded

    @model_validator(mode="after")
    def envelope_shape_is_exact(self) -> GovernedSpatialExecutionMaterialEnvelopeV1:
        if len(self._decode(self.nonce, "nonce_shape_invalid")) != 12 or len(self.nonce) != 16:
            raise ValueError("nonce_shape_invalid")
        if len(self._decode(self.ciphertext, "ciphertext_shape_invalid")) < 16:
            raise ValueError("ciphertext_tag_missing")
        if _as_datetime(self.created_at) >= _as_datetime(self.retention_expires_at):
            raise ValueError("envelope_retention_expiry_invalid")
        expected = "sha256:" + hashlib.sha256(_unchecked_envelope_aad_bytes(self.model_dump(mode="json"))).hexdigest()
        if self.aad_digest != expected:
            raise ValueError("aad_digest_mismatch")
        return self


class GovernedSpatialExecutionRequestV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_execution_request.v1"]
    contract_version: Literal["1.0.0"]
    build_request_digest: str
    composition_digest: str
    request_digest: str
    source_packet_digest: str
    style_snapshot_digest: str
    output_contract_digest: str
    material_digest: str
    execution_target_digest: str
    attempt_number: StrictInt = Field(ge=1, le=2)
    mutation_token_digest: str
    operation_intent_digest: str
    artifact_family: Literal[
        "propertyquarry_continuous_walkthrough", "runsite_continuous_walkthrough",
        "runsite_private_encounter_preview"
    ]
    content_profile: Literal[
        "spatial_orientation_no_encounter_fields", "private_fictional_non_graphic_encounter"
    ]
    environment: Literal["development", "test", "candidate", "production"]
    provider_route_digest: str
    gate_versions: dict[str, str] = Field(min_length=1, max_length=32)
    render_spec: GovernedSpatialRenderSpecV1
    style_snapshot: GovernedSpatialStyleSnapshotV1
    asset_bindings: list[GovernedSpatialAssetBindingV1] = Field(min_length=1, max_length=10000)
    output_allocation_ref: str

    _digests = field_validator(
        "build_request_digest", "composition_digest", "request_digest", "source_packet_digest",
        "style_snapshot_digest", "output_contract_digest", "material_digest", "execution_target_digest",
        "mutation_token_digest", "operation_intent_digest", "provider_route_digest"
    )(validate_digest)
    _output = field_validator("output_allocation_ref")(validate_execution_ref)

    @field_validator("gate_versions")
    @classmethod
    def gate_versions_are_typed(cls, value: dict[str, str]) -> dict[str, str]:
        for version in value.values():
            if not isinstance(version, str) or not 1 <= len(version) <= 128:
                raise ValueError("gate_version_length_invalid")
        return value

    @model_validator(mode="after")
    def execution_binding_is_exact(self) -> GovernedSpatialExecutionRequestV1:
        product = self.render_spec.product
        purpose = self.render_spec.artifact.purpose
        overlays = self.render_spec.scene_overlays
        expected = {
            ("propertyquarry", "walkthrough"): (
                "propertyquarry_continuous_walkthrough", "spatial_orientation_no_encounter_fields", False
            ),
            ("chummer", "walkthrough"): (
                "runsite_continuous_walkthrough", "spatial_orientation_no_encounter_fields", False
            ),
            ("chummer", "encounter_preview"): (
                "runsite_private_encounter_preview", "private_fictional_non_graphic_encounter", True
            ),
        }.get((product, purpose))
        if expected is None or (self.artifact_family, self.content_profile) != expected[:2]:
            raise ValueError("product_family_profile_purpose_mismatch")
        if bool(overlays) is not expected[2]:
            raise ValueError("product_family_overlay_mismatch")
        if product not in self.style_snapshot.consumer_products:
            raise ValueError("style_consumer_product_mismatch")
        if ("property_policy" in self.gate_versions) is not (product == "propertyquarry"):
            raise ValueError("property_policy_gate_family_presence_invalid")
        if expected[2] and self.render_spec.content_policy.rating != "teen_fictional_combat":
            raise ValueError("private_encounter_content_policy_mismatch")
        if not expected[2] and self.render_spec.content_policy.rating == "teen_fictional_combat":
            raise ValueError("non_encounter_content_policy_mismatch")
        room_types = {room.room_type for room in self.render_spec.rooms}
        if "any" not in self.style_snapshot.room_types and not room_types.issubset(set(self.style_snapshot.room_types)):
            raise ValueError("style_room_type_coverage_missing")
        _validate_asset_bindings(self.asset_bindings, self.style_snapshot)
        return self


class GovernedSpatialExecutionResultV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_execution_result.v1"]
    contract_version: Literal["1.0.0"]
    operation_id: str
    state: Literal["succeeded", "failed_final", "unknown"]
    output_digest: str | None
    output_manifest_ref: str | None
    private_execution_receipt_digest: str | None
    provider_action_count: StrictInt = Field(ge=0, le=1)

    _operation = field_validator("operation_id")(validate_execution_ref)
    _optional_digests = field_validator("output_digest", "private_execution_receipt_digest")(
        lambda value: validate_digest(value) if value is not None else None
    )
    _manifest = field_validator("output_manifest_ref")(
        lambda value: validate_execution_ref(value) if value is not None else None
    )

    @model_validator(mode="after")
    def result_shape_is_exact(self) -> GovernedSpatialExecutionResultV1:
        outputs = (self.output_digest, self.output_manifest_ref, self.private_execution_receipt_digest)
        if self.state == "succeeded":
            if any(value is None for value in outputs) or self.provider_action_count != 1:
                raise ValueError("successful_adapter_result_shape_invalid")
        elif any(value is not None for value in outputs):
            raise ValueError("non_success_adapter_output_fields_must_be_null")
        return self


class Ed25519Signature(StrictContractModel):
    algorithm: Literal["ed25519"]
    encoding: Literal["base64url_no_padding"]
    signature_value: str
    key_ref: str
    key_fingerprint: str
    key_epoch: StrictInt = Field(ge=0, le=SAFE_INTEGER_MAX)
    canonicalization: Literal["rfc8785_jcs"]
    signed_payload_scope: Literal["entire_receipt_excluding_signature_value_and_signed_payload_digest"]
    signed_payload_digest: str

    _key_ref = field_validator("key_ref")(validate_execution_ref)
    _digests = field_validator("key_fingerprint", "signed_payload_digest")(validate_digest)

    @field_validator("signature_value")
    @classmethod
    def signature_shape(cls, value: str) -> str:
        if not _SIGNATURE_RE.fullmatch(value):
            raise ValueError("signature_value_shape_invalid")
        return value


class GovernedSpatialOperationReconciliationV1(StrictContractModel):
    contract_name: Literal["ea.governed_spatial_operation_reconciliation.v1"]
    contract_version: Literal["1.0.0"]
    adapter_identity_digest: str
    environment: Literal["development", "test", "candidate", "production"]
    operation_id: str
    operation: Literal["reserve", "commit_attempt", "execute", "consume", "release", "compensate"]
    build_request_digest: str
    attempt_number: StrictInt = Field(ge=0, le=2)
    observed_at: str
    issued_at: str
    expires_at: str
    adapter_sequence: StrictInt = Field(ge=1, le=SAFE_INTEGER_MAX)
    state: Literal["not_started", "in_progress", "succeeded", "failed_final", "unknown"]
    outcome_digest: str | None
    prior_reconciliation_digest: str | None
    signature: Ed25519Signature

    _digests = field_validator("adapter_identity_digest", "build_request_digest")(validate_digest)
    _optional_digests = field_validator("outcome_digest", "prior_reconciliation_digest")(
        lambda value: validate_digest(value) if value is not None else None
    )
    _operation_id = field_validator("operation_id")(validate_execution_ref)
    _timestamps = field_validator("observed_at", "issued_at", "expires_at")(_validate_timestamp)

    @model_validator(mode="after")
    def reconciliation_shape_is_exact(self) -> GovernedSpatialOperationReconciliationV1:
        observed = _as_datetime(self.observed_at)
        issued = _as_datetime(self.issued_at)
        expires = _as_datetime(self.expires_at)
        if not observed <= issued < expires:
            raise ValueError("reconciliation_timestamp_chronology_invalid")
        if issued - observed > timedelta(minutes=5) or expires - issued > timedelta(minutes=5):
            raise ValueError("reconciliation_timestamp_window_invalid")
        if self.state == "not_started":
            if self.adapter_sequence != 1 or self.outcome_digest is not None or self.prior_reconciliation_digest is not None:
                raise ValueError("not_started_shape_invalid")
        elif self.adapter_sequence == 1 and self.prior_reconciliation_digest is not None:
            raise ValueError("initial_reconciliation_prior_must_be_null")
        elif self.adapter_sequence > 1 and self.prior_reconciliation_digest is None:
            raise ValueError("later_reconciliation_prior_required")
        if self.state in {"succeeded", "failed_final"}:
            if self.outcome_digest is None:
                raise ValueError("terminal_reconciliation_outcome_required")
        elif self.outcome_digest is not None:
            raise ValueError("nonterminal_reconciliation_outcome_must_be_null")
        return self


def reconciliation_digest(receipt: GovernedSpatialOperationReconciliationV1) -> str:
    receipt = _fresh_model(receipt, GovernedSpatialOperationReconciliationV1, "reconciliation")
    payload = _safe_model_dump(receipt, "reconciliation")
    return "sha256:" + hashlib.sha256(_bounded_canonical_bytes(payload)).hexdigest()


def validate_reconciliation_freshness(
    receipt: GovernedSpatialOperationReconciliationV1, *, now: datetime
) -> None:
    receipt = _fresh_model(receipt, GovernedSpatialOperationReconciliationV1, "reconciliation")
    if now.tzinfo is None or now.utcoffset() is None:
        raise SpatialExecutionContractError("offset_aware_now_required")
    observed = _as_datetime(receipt.observed_at)
    issued = _as_datetime(receipt.issued_at)
    current = now.astimezone(UTC)
    if observed > current:
        raise SpatialExecutionContractError("reconciliation_observed_in_future")
    if issued > current:
        raise SpatialExecutionContractError("reconciliation_issued_in_future")
    if (
        current - observed > timedelta(minutes=5)
        or current - issued > timedelta(minutes=5)
        or current >= _as_datetime(receipt.expires_at)
    ):
        raise SpatialExecutionContractError("reconciliation_stale")


def validate_style_snapshot_time(
    snapshot: GovernedSpatialStyleSnapshotV1, *, now: datetime
) -> None:
    snapshot = _fresh_model(snapshot, GovernedSpatialStyleSnapshotV1, "style_snapshot")
    if now.tzinfo is None or now.utcoffset() is None:
        raise SpatialExecutionContractError("offset_aware_now_required")
    if _as_datetime(snapshot.source_retrieved_at) > now.astimezone(UTC) + timedelta(minutes=5):
        raise SpatialExecutionContractError("style_source_timestamp_in_future")


def validate_reconciliation_transition(
    previous: GovernedSpatialOperationReconciliationV1 | None,
    current: GovernedSpatialOperationReconciliationV1,
) -> None:
    if previous is not None:
        previous = _fresh_model(previous, GovernedSpatialOperationReconciliationV1, "previous_reconciliation")
    current = _fresh_model(current, GovernedSpatialOperationReconciliationV1, "current_reconciliation")
    if previous is None:
        if current.adapter_sequence != 1 or current.prior_reconciliation_digest is not None:
            raise SpatialExecutionContractError("reconciliation_initial_sequence_invalid")
        return
    bindings = (
        "adapter_identity_digest", "environment", "operation_id", "operation",
        "build_request_digest", "attempt_number"
    )
    if any(getattr(previous, field) != getattr(current, field) for field in bindings):
        raise SpatialExecutionContractError("reconciliation_binding_changed")
    if current.adapter_sequence <= previous.adapter_sequence:
        raise SpatialExecutionContractError("reconciliation_sequence_not_increasing")
    if current.prior_reconciliation_digest != reconciliation_digest(previous):
        raise SpatialExecutionContractError("reconciliation_prior_digest_mismatch")
    if _as_datetime(current.observed_at) < _as_datetime(previous.observed_at):
        raise SpatialExecutionContractError("reconciliation_observed_at_regression")
    if _as_datetime(current.issued_at) < _as_datetime(previous.issued_at):
        raise SpatialExecutionContractError("reconciliation_issued_at_regression")
    if current.state == "not_started":
        raise SpatialExecutionContractError("reconciliation_not_started_regression")
    if previous.state in {"succeeded", "failed_final"}:
        if current.state != previous.state or current.outcome_digest != previous.outcome_digest:
            raise SpatialExecutionContractError("reconciliation_terminal_restatement_mismatch")


class PropertyExecutionProjectionV1(StrictContractModel):
    contract_name: Literal["propertyquarry.governed_spatial_execution_projection.v1"]
    contract_version: Literal["1.0.0"]
    state: Literal["blocked", "pending", "succeeded", "failed_final", "unknown"]
    reason_code: Literal[
        "none",
        "authorization_unavailable",
        "capability_unavailable",
        "contract_invalid",
        "execution_blocked",
        "execution_failed",
        "internal_error",
        "material_unavailable",
        "policy_unavailable",
        "privacy_blocked",
        "reconciliation_pending",
        "verification_failed",
    ]
    composition_digest: str
    output_digest: str | None
    verification_digest: str | None
    artifact_ref: str | None
    privacy_deletion_status: Literal["not_requested", "pending", "complete", "blocked"]
    idempotent_replay_state: Literal["new", "replayed", "reconciled", "blocked"]

    _composition = field_validator("composition_digest")(validate_digest)
    _optional_digests = field_validator("output_digest", "verification_digest")(
        lambda value: validate_digest(value) if value is not None else None
    )
    _artifact = field_validator("artifact_ref")(
        lambda value: validate_execution_ref(value) if value is not None else None
    )

    @model_validator(mode="after")
    def state_output_shape_is_exact(self) -> PropertyExecutionProjectionV1:
        outputs = (self.output_digest, self.verification_digest, self.artifact_ref)
        if self.state == "succeeded":
            if self.reason_code != "none" or any(value is None for value in outputs):
                raise ValueError("successful_property_projection_shape_invalid")
            return self
        if self.reason_code == "none" or any(value is not None for value in outputs):
            raise ValueError("non_success_property_projection_shape_invalid")
        appropriate = {
            "blocked": {
                "authorization_unavailable", "capability_unavailable", "contract_invalid",
                "execution_blocked", "material_unavailable", "policy_unavailable", "privacy_blocked",
            },
            "pending": {"reconciliation_pending"},
            "failed_final": {"execution_failed", "verification_failed", "internal_error"},
            "unknown": {"internal_error", "reconciliation_pending"},
        }
        if self.reason_code not in appropriate[self.state]:
            raise ValueError("property_projection_reason_state_mismatch")
        return self


class PropertyDeletionEvidenceProjectionV1(StrictContractModel):
    contract_name: Literal["propertyquarry.governed_spatial_deletion_evidence_projection.v1"]
    contract_version: Literal["1.0.0"]
    scope_digest: str
    tombstone_digest: str
    deletion_evidence_digest: str
    requested_at: str
    tombstoned_at: str
    ciphertext_deleted_at: str | None
    derivative_coverage: Literal["complete", "partial_blocked"]
    provider_deletion_state: Literal["not_applicable", "requested", "confirmed", "blocked_failure"]
    retry_state: Literal["not_required", "pending_authorized", "blocked_manual_reconciliation"]
    next_retry_at: str | None

    _digests = field_validator("scope_digest", "tombstone_digest", "deletion_evidence_digest")(validate_digest)
    _timestamps = field_validator("requested_at", "tombstoned_at", "ciphertext_deleted_at", "next_retry_at")(
        lambda value: _validate_timestamp(value) if value is not None else None
    )

    @model_validator(mode="after")
    def deletion_chronology_is_exact(self) -> PropertyDeletionEvidenceProjectionV1:
        if _as_datetime(self.tombstoned_at) < _as_datetime(self.requested_at):
            raise ValueError("deletion_timestamp_chronology_invalid")
        if self.ciphertext_deleted_at is not None and _as_datetime(self.ciphertext_deleted_at) < _as_datetime(self.tombstoned_at):
            raise ValueError("ciphertext_deletion_precedes_tombstone")
        if self.retry_state == "pending_authorized" and self.next_retry_at is None:
            raise ValueError("pending_retry_timestamp_required")
        if self.retry_state != "pending_authorized" and self.next_retry_at is not None:
            raise ValueError("next_retry_timestamp_forbidden")
        return self


PropertyResponse = PropertyExecutionProjectionV1 | PropertyDeletionEvidenceProjectionV1


def _parse_public_model(
    value: Mapping[str, object] | bytes | bytearray | memoryview | str,
    model: type[StrictContractModel],
    *,
    prefix: str,
) -> StrictContractModel:
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        try:
            payload = parse_raw_json(value)
        except RawJsonContractError as exc:
            reason = "duplicate_member" if str(exc).startswith("duplicate_member") else "json_invalid"
            raise SpatialExecutionContractError(f"{prefix}_{reason}") from None
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise SpatialExecutionContractError(f"{prefix}_object_required")
    try:
        return model.model_validate(payload)
    except (ValidationError, ValueError, SpatialExecutionContractError):
        raise SpatialExecutionContractError(f"{prefix}_validation_failed") from None


def _safe_model_dump(value: BaseModel, prefix: str) -> dict[str, Any]:
    try:
        payload = value.model_dump(mode="json")
    except Exception:
        raise SpatialExecutionContractError(f"{prefix}_validation_failed") from None
    if not isinstance(payload, dict):
        raise SpatialExecutionContractError(f"{prefix}_validation_failed")
    return payload


def _fresh_model(value: StrictContractModel, model: type[StrictContractModel], prefix: str) -> Any:
    payload = _safe_model_dump(value, prefix)
    try:
        return model.model_validate(payload)
    except (ValidationError, ValueError, SpatialExecutionContractError):
        raise SpatialExecutionContractError(f"{prefix}_validation_failed") from None


def parse_execution_material(
    value: Mapping[str, object] | bytes | bytearray | memoryview | str,
) -> GovernedSpatialExecutionMaterialV1:
    return _parse_public_model(
        value, GovernedSpatialExecutionMaterialV1, prefix="execution_material"
    )  # type: ignore[return-value]


def parse_execution_request(
    value: Mapping[str, object] | bytes | bytearray | memoryview | str,
) -> GovernedSpatialExecutionRequestV1:
    return _parse_public_model(
        value, GovernedSpatialExecutionRequestV1, prefix="execution_request"
    )  # type: ignore[return-value]


def parse_property_response(value: Mapping[str, object] | bytes | bytearray | memoryview | str) -> PropertyResponse:
    payload: Mapping[str, object]
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        try:
            payload = parse_raw_json(value)
        except RawJsonContractError as exc:
            reason = str(exc)
            static_reason = (
                "property_response_duplicate_member"
                if reason.startswith("duplicate_member")
                else "property_response_json_invalid"
            )
            raise SpatialExecutionContractError(static_reason) from None
    elif isinstance(value, Mapping):
        payload = value
    else:
        raise SpatialExecutionContractError("property_response_object_required")
    contract_name = payload.get("contract_name")
    models: dict[str, type[PropertyExecutionProjectionV1] | type[PropertyDeletionEvidenceProjectionV1]] = {
        "propertyquarry.governed_spatial_execution_projection.v1": PropertyExecutionProjectionV1,
        "propertyquarry.governed_spatial_deletion_evidence_projection.v1": PropertyDeletionEvidenceProjectionV1,
    }
    model = models.get(contract_name) if isinstance(contract_name, str) else None
    if model is None:
        raise SpatialExecutionContractError("property_response_contract_unknown")
    try:
        return model.model_validate(dict(payload))
    except ValidationError:
        raise SpatialExecutionContractError("property_response_validation_failed") from None


def canonical_material_bytes(material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object]) -> bytes:
    supplied = _safe_model_dump(material, "execution_material") if isinstance(
        material, GovernedSpatialExecutionMaterialV1
    ) else material
    parsed = parse_execution_material(supplied)
    return _bounded_canonical_bytes(_safe_model_dump(parsed, "execution_material"))


def material_digest(material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_material_bytes(material)).hexdigest()


def _render_spec_from_material(material: GovernedSpatialExecutionMaterialV1) -> GovernedSpatialRenderSpecV1:
    material = _fresh_model(material, GovernedSpatialExecutionMaterialV1, "execution_material")
    request = material.normalized_request
    source = material.normalized_source_packet
    spatial_plan = request["spatial_plan"]
    payload = {
        "contract_name": "ea.governed_spatial_render_spec.v1",
        "contract_version": "1.0.0",
        "product": request["consumer"]["product"],
        "artifact": request["artifact"],
        "normalized_floorplan_ref": source["normalized_floorplan_ref"],
        "room_graph_ref": source["room_graph_ref"],
        "walkable_mesh_ref": source["walkable_mesh_ref"],
        "portal_graph_ref": source["portal_graph_ref"],
        "scale_m_per_unit": str(source["scale_m_per_unit"]),
        "orientation_degrees": str(source["orientation_degrees"]),
        "rooms": source["rooms"],
        "portals": source["portals"],
        "required_room_ids": spatial_plan["required_room_ids"],
        "route_room_ids": spatial_plan["route_room_ids"],
        "allow_revisit": spatial_plan["allow_revisit"],
        "camera": request["camera"],
        "output": request["output"],
        "content_policy": request["content_policy"],
        "scene_overlays": request["scene_overlays"],
    }
    return GovernedSpatialRenderSpecV1.model_validate(payload)


def validate_execution_request_material_binding(
    request: GovernedSpatialExecutionRequestV1,
    material: GovernedSpatialExecutionMaterialV1,
) -> None:
    request = parse_execution_request(_safe_model_dump(request, "execution_request"))
    material = parse_execution_material(_safe_model_dump(material, "execution_material"))
    for field in (
        "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
        "output_contract_digest", "execution_target_digest",
    ):
        if getattr(request, field) != getattr(material, field):
            raise SpatialExecutionContractError(f"execution_material_{field}_mismatch")
    if request.material_digest != material_digest(material):
        raise SpatialExecutionContractError("execution_material_digest_mismatch")
    if not _canonical_equal(
        _safe_model_dump(request.style_snapshot, "execution_request"),
        _safe_model_dump(material.style_snapshot, "execution_material"),
    ):
        raise SpatialExecutionContractError("execution_material_style_snapshot_mismatch")
    if not _canonical_equal(
        [_safe_model_dump(binding, "execution_request") for binding in request.asset_bindings],
        [_safe_model_dump(binding, "execution_material") for binding in material.asset_bindings],
    ):
        raise SpatialExecutionContractError("execution_material_asset_bindings_mismatch")
    expected_render_spec = _render_spec_from_material(material)
    if not _canonical_equal(
        _safe_model_dump(request.render_spec, "execution_request"),
        _safe_model_dump(expected_render_spec, "execution_material"),
    ):
        raise SpatialExecutionContractError("execution_material_render_spec_mismatch")


def validate_execution_gate_versions(
    request: GovernedSpatialExecutionRequestV1,
    verified_capability_projection: Mapping[str, object],
) -> None:
    request = parse_execution_request(_safe_model_dump(request, "execution_request"))
    verified_family = verified_capability_projection.get("artifact_family")
    verified_gates = verified_capability_projection.get("gate_versions")
    if verified_family != request.artifact_family or not isinstance(verified_gates, Mapping):
        raise SpatialExecutionContractError("verified_gate_projection_invalid")
    gates = dict(verified_gates)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in gates.items()):
        raise SpatialExecutionContractError("verified_gate_projection_invalid")
    if request.gate_versions != gates:
        raise SpatialExecutionContractError("gate_versions_verified_projection_mismatch")


def _unchecked_envelope_aad_bytes(payload: Mapping[str, object]) -> bytes:
    payload = dict(payload)
    payload.pop("ciphertext", None)
    payload.pop("aad_digest", None)
    return _bounded_canonical_bytes(payload)


def envelope_aad_bytes(
    envelope: GovernedSpatialExecutionMaterialEnvelopeV1 | Mapping[str, object],
) -> bytes:
    if isinstance(envelope, GovernedSpatialExecutionMaterialEnvelopeV1):
        parsed = _fresh_model(envelope, GovernedSpatialExecutionMaterialEnvelopeV1, "execution_envelope")
    else:
        try:
            parsed = GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(dict(envelope))
        except (ValidationError, ValueError, SpatialExecutionContractError):
            raise SpatialExecutionContractError("execution_envelope_validation_failed") from None
    return _unchecked_envelope_aad_bytes(_safe_model_dump(parsed, "execution_envelope"))


def _seal_envelope_payload(
    payload: Mapping[str, object], *, plaintext: bytes, key_bytes: bytes,
) -> tuple[GovernedSpatialExecutionMaterialEnvelopeV1, bytes]:
    sealed = dict(payload)
    aad = _unchecked_envelope_aad_bytes(sealed)
    sealed["aad_digest"] = "sha256:" + hashlib.sha256(aad).hexdigest()
    try:
        nonce = GovernedSpatialExecutionMaterialEnvelopeV1._decode(
            sealed["nonce"], "nonce_shape_invalid"  # type: ignore[arg-type]
        )
        sealed["ciphertext"] = _b64url(AESGCM(key_bytes).encrypt(nonce, plaintext, aad))
        envelope = GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(sealed)
    except (KeyError, TypeError, ValueError, ValidationError, SpatialExecutionContractError):
        raise SpatialMaterialStoreError("material_envelope_seal_failed") from None
    return envelope, _bounded_canonical_bytes(sealed)


class SpatialMaterialStoreError(SpatialExecutionContractError):
    """Static, redacted local material-store failure."""


class SpatialMaterialStoreSecurityError(SpatialMaterialStoreError):
    """A private-store filesystem invariant was violated."""


KEY_STATES = frozenset({"active_encrypt_decrypt", "decrypt_only", "revoked"})
JOURNAL_STATES = frozenset(
    {"seal_intent", "sealed", "seal_aborted_missing_ciphertext", "delete_tombstone", "deleted"}
)
_JOURNAL_MEMBERS = frozenset(
    {
        "sequence", "prior_record_digest", "record_digest", "operation_id", "state",
        "material_identity", "composition_digest", "material_digest", "envelope_digest",
        "requested_at", "observed_at",
    }
)
_MAX_ENVELOPE_BYTES = MAX_CANONICAL_MATERIAL_BYTES + 64 * 1024
_MAX_JOURNAL_BYTES = 32 * 1024 * 1024
# Conservative maximum for one canonical JSON record including its newline frame.
_MAX_JOURNAL_RECORD_BYTES = 4096
_JOURNAL_PENDING_NAME = "material.journal.pending.json"
_JOURNAL_PENDING_MEMBERS = frozenset(
    {
        "contract_name", "contract_version", "journal_pre_size", "prior_record_digest",
        "record_digest", "record_encoding", "record_bytes",
    }
)


def _aware_utc(value: datetime, reason: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SpatialMaterialStoreError(reason)
    return value.astimezone(UTC)


def _journal_reserved_bytes(records: list[dict[str, object]]) -> int:
    latest: dict[str, str] = {}
    for record in records:
        identity = record.get("material_identity")
        state = record.get("state")
        if not isinstance(identity, str) or not isinstance(state, str):
            raise SpatialMaterialStoreError("material_journal_record_invalid")
        latest[identity] = state
    future_records = {
        "seal_intent": 3,
        "sealed": 2,
        "seal_aborted_missing_ciphertext": 2,
        "delete_tombstone": 1,
        "deleted": 0,
    }
    try:
        return sum(future_records[state] * _MAX_JOURNAL_RECORD_BYTES for state in latest.values())
    except KeyError:
        raise SpatialMaterialStoreError("material_journal_state_invalid") from None


def _preflight_journal_capacity(
    *, current_size: int, encoded_record: bytes, records_after: list[dict[str, object]],
) -> None:
    if len(encoded_record) > _MAX_JOURNAL_RECORD_BYTES:
        raise SpatialMaterialStoreError("material_journal_record_too_large")
    if current_size + len(encoded_record) + _journal_reserved_bytes(records_after) > _MAX_JOURNAL_BYTES:
        raise SpatialMaterialStoreError("material_journal_capacity_exceeded")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def key_fingerprint(key_bytes: bytes) -> str:
    if not isinstance(key_bytes, bytes) or len(key_bytes) != 32:
        raise SpatialMaterialStoreError("material_key_length_invalid")
    return "sha256:" + hashlib.sha256(key_bytes).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class SpatialMaterialKeyRecord:
    environment: str
    key_ref: str
    key_epoch: int
    key_fingerprint: str
    key_bytes: bytes
    state: Literal["active_encrypt_decrypt", "decrypt_only", "revoked"]
    not_before: datetime
    decrypt_until: datetime

    def __post_init__(self) -> None:
        try:
            validate_execution_ref(self.key_ref)
            validate_digest(self.key_fingerprint)
        except (ValueError, SpatialExecutionContractError):
            raise SpatialMaterialStoreError("material_key_record_invalid") from None
        if self.environment not in {"development", "test", "candidate", "production"}:
            raise SpatialMaterialStoreError("material_key_record_invalid")
        if isinstance(self.key_epoch, bool) or not isinstance(self.key_epoch, int) or not 0 <= self.key_epoch <= SAFE_INTEGER_MAX:
            raise SpatialMaterialStoreError("material_key_record_invalid")
        if self.state not in KEY_STATES:
            raise SpatialMaterialStoreError("material_key_record_invalid")
        if not isinstance(self.key_bytes, bytes) or len(self.key_bytes) != 32:
            raise SpatialMaterialStoreError("material_key_length_invalid")
        if not hashlib.sha256(self.key_bytes).digest() == bytes.fromhex(self.key_fingerprint[7:]):
            raise SpatialMaterialStoreError("material_key_fingerprint_mismatch")
        not_before = _aware_utc(self.not_before, "material_key_time_invalid")
        decrypt_until = _aware_utc(self.decrypt_until, "material_key_time_invalid")
        if decrypt_until <= not_before:
            raise SpatialMaterialStoreError("material_key_time_invalid")
        object.__setattr__(self, "not_before", not_before)
        object.__setattr__(self, "decrypt_until", decrypt_until)

    def __repr__(self) -> str:
        return "SpatialMaterialKeyRecord(<redacted>)"


class SpatialMaterialKeyRegistry:
    def __init__(self, records: list[SpatialMaterialKeyRecord] | tuple[SpatialMaterialKeyRecord, ...]):
        self._records: dict[tuple[str, str, int, str], SpatialMaterialKeyRecord] = {}
        active: set[str] = set()
        for record in records:
            if not isinstance(record, SpatialMaterialKeyRecord):
                raise SpatialMaterialStoreError("material_key_record_invalid")
            identity = (record.environment, record.key_ref, record.key_epoch, record.key_fingerprint)
            if identity in self._records:
                raise SpatialMaterialStoreError("material_key_tuple_duplicate")
            if record.state == "active_encrypt_decrypt" and record.environment in active:
                raise SpatialMaterialStoreError("material_encrypt_key_not_unique")
            self._records[identity] = record
            if record.state == "active_encrypt_decrypt":
                active.add(record.environment)

    def encryption_key(
        self, *, environment: str, compose_at: datetime, retention_expires_at: datetime
    ) -> SpatialMaterialKeyRecord:
        candidates = [
            record for record in self._records.values()
            if record.environment == environment and record.state == "active_encrypt_decrypt"
        ]
        if len(candidates) != 1:
            raise SpatialMaterialStoreError("material_encrypt_key_unavailable")
        record = candidates[0]
        compose = _aware_utc(compose_at, "material_key_time_invalid")
        retention = _aware_utc(retention_expires_at, "material_key_time_invalid")
        if compose < record.not_before:
            raise SpatialMaterialStoreError("material_key_not_yet_valid")
        if compose > record.not_before + timedelta(days=90):
            raise SpatialMaterialStoreError("material_encrypt_key_rotation_overdue")
        if retention > record.decrypt_until:
            raise SpatialMaterialStoreError("material_key_decrypt_horizon_insufficient")
        return record

    def decryption_key(
        self, *, environment: str, key_ref: str, key_epoch: int, key_fingerprint: str,
        created_at: datetime, now: datetime,
    ) -> SpatialMaterialKeyRecord:
        record = self._records.get((environment, key_ref, key_epoch, key_fingerprint))
        if record is None:
            raise SpatialMaterialStoreError("material_decrypt_key_unknown")
        if record.state == "revoked":
            raise SpatialMaterialStoreError("material_decrypt_key_revoked")
        if _aware_utc(created_at, "material_key_time_invalid") < record.not_before:
            raise SpatialMaterialStoreError("material_key_not_yet_valid")
        if _aware_utc(now, "material_key_time_invalid") > record.decrypt_until:
            raise SpatialMaterialStoreError("material_key_decrypt_horizon_elapsed")
        return record


def fixed_material_retention_expiry(
    *, source_packet_created_at: datetime, compose_acceptance_at: datetime,
    source_retention_days: int = 30, policy_expires_at: datetime,
    shorter_deadlines: tuple[datetime, ...] = (),
) -> datetime:
    source = _aware_utc(source_packet_created_at, "material_retention_time_invalid")
    compose = _aware_utc(compose_acceptance_at, "material_retention_time_invalid")
    policy = _aware_utc(policy_expires_at, "material_retention_time_invalid")
    if isinstance(source_retention_days, bool) or not isinstance(source_retention_days, int) or not 1 <= source_retention_days <= 30:
        raise SpatialMaterialStoreError("material_retention_days_invalid")
    candidates = [min(source, compose) + timedelta(days=source_retention_days), policy]
    candidates.extend(_aware_utc(value, "material_retention_time_invalid") for value in shorter_deadlines)
    expiry = min(candidates)
    if expiry <= min(source, compose):
        raise SpatialMaterialStoreError("material_retention_deadline_invalid")
    return expiry


class SpatialExecutionMaterialStore:
    """Private, write-once AES-GCM execution-material store."""

    def __init__(
        self, root: Path, *, environment: str, keys: SpatialMaterialKeyRegistry,
        clock: Callable[[], datetime] | None = None,
        randomness: Callable[[int], bytes] | None = None,
        crash_hook: Callable[[str], None] | None = None,
        journal_write: Callable[[int, bytes], int] | None = None,
        retention_resolver: Callable[[GovernedSpatialExecutionMaterialV1], datetime] | None = None,
        authority_guarded_recovery: bool = False,
        lifecycle_authority: SpatialLifecycleAuthority | None = None,
    ) -> None:
        if not isinstance(root, Path) or ".." in root.parts:
            raise SpatialMaterialStoreSecurityError("material_store_root_invalid")
        if environment not in {"development", "test", "candidate", "production"}:
            raise SpatialMaterialStoreError("material_store_environment_invalid")
        if not isinstance(authority_guarded_recovery, bool):
            raise SpatialMaterialStoreError("material_store_recovery_mode_invalid")
        if authority_guarded_recovery and not isinstance(
            lifecycle_authority, SpatialLifecycleAuthority
        ):
            raise SpatialMaterialStoreError("material_lifecycle_authority_required")
        if lifecycle_authority is not None and not isinstance(
            lifecycle_authority, SpatialLifecycleAuthority
        ):
            raise SpatialMaterialStoreError("material_lifecycle_authority_invalid")
        self.root = root
        self.environment = environment
        self.authority_guarded_recovery = authority_guarded_recovery
        self._lifecycle_authority = lifecycle_authority
        self.keys = keys
        self._clock = clock or (lambda: datetime.now(UTC))
        self._randomness = randomness or os.urandom
        self._crash_hook = crash_hook or (lambda point: None)
        self._journal_write = journal_write or os.write
        self._retention_resolver = retention_resolver
        self._owner = os.geteuid()
        self._root_identity = self._establish_root()
        if not self.authority_guarded_recovery:
            with self._journal() as (directory_fd, journal_fd, records):
                self._recover(directory_fd, journal_fd, records, restart=True)

    @property
    def lifecycle_authority(self) -> SpatialLifecycleAuthority | None:
        return self._lifecycle_authority

    @staticmethod
    def material_identity(composition_digest: str) -> str:
        validate_digest(composition_digest)
        return "material:" + composition_digest[7:]

    @staticmethod
    def _filename(identity: str) -> str:
        if not re.fullmatch(r"material:[0-9a-f]{64}", identity):
            raise SpatialMaterialStoreError("material_identity_invalid")
        return identity[9:] + ".envelope.json"

    def _require_lifecycle_guard(
        self,
        composition_digest: str,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None,
        *,
        allow_privacy: bool = False,
        require_privacy: bool = False,
    ) -> None:
        if not self.authority_guarded_recovery:
            return
        if not isinstance(lifecycle_guard, SpatialCompositionLifecycleGuard):
            raise SpatialMaterialStoreError("material_lifecycle_guard_required")
        if self._lifecycle_authority is None:
            raise SpatialMaterialStoreError("material_lifecycle_authority_required")
        try:
            lifecycle_guard.assert_active(
                composition_digest,
                authority=self._lifecycle_authority,
                allow_privacy=True,
            )
        except SpatialStateError:
            raise SpatialMaterialStoreError("material_lifecycle_guard_invalid") from None
        privacy_status = lifecycle_guard.privacy_status
        if privacy_status is not None and not allow_privacy:
            raise SpatialMaterialStoreError(
                "material_lifecycle_privacy_tombstone_active"
            )
        if require_privacy and privacy_status is None:
            raise SpatialMaterialStoreError(
                "material_lifecycle_privacy_tombstone_required"
            )

    @staticmethod
    def _directory_flags() -> int:
        return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def _validate_directory_descriptor(self, fd: int, *, final: bool) -> os.stat_result:
        try:
            info = os.fstat(fd)
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_store_root_unavailable") from None
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, self._owner}:
            raise SpatialMaterialStoreSecurityError("material_store_root_ancestor_insecure")
        if final and (info.st_uid != self._owner or stat.S_IMODE(info.st_mode) != 0o700):
            raise SpatialMaterialStoreSecurityError("material_store_root_insecure")
        return info

    def _walk_root(self, *, create_final: bool) -> tuple[int, bool]:
        rendered = os.fspath(self.root)
        if (
            not self.root.is_absolute() or self.root == Path("/")
            or rendered.startswith("//") or rendered != os.path.normpath(rendered)
            or any(part in {"", ".", ".."} for part in self.root.parts[1:])
        ):
            raise SpatialMaterialStoreSecurityError("material_store_root_invalid")
        components = self.root.parts[1:]
        descriptors: list[int] = []
        created = False
        try:
            current = os.open("/", self._directory_flags())
            descriptors.append(current)
            self._validate_directory_descriptor(current, final=False)
            for index, component in enumerate(components):
                final = index == len(components) - 1
                if final and create_final:
                    try:
                        os.mkdir(component, 0o700, dir_fd=current)
                        created = True
                    except FileExistsError:
                        created = False
                    except OSError:
                        raise SpatialMaterialStoreSecurityError("material_store_root_unavailable") from None
                try:
                    child = os.open(component, self._directory_flags(), dir_fd=current)
                except OSError:
                    reason = "material_store_root_unavailable" if final else "material_store_root_ancestor_invalid"
                    raise SpatialMaterialStoreSecurityError(reason) from None
                descriptors.append(child)
                self._validate_directory_descriptor(child, final=final)
                current = child
            root_fd = descriptors.pop()
            if created:
                try:
                    os.fsync(root_fd)
                    os.fsync(descriptors[-1])
                except OSError:
                    os.close(root_fd)
                    raise SpatialMaterialStoreSecurityError("material_store_root_sync_failed") from None
            return root_fd, created
        except SpatialMaterialStoreError:
            raise
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_store_root_unavailable") from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _establish_root(self) -> tuple[int, int]:
        fd, _ = self._walk_root(create_final=True)
        try:
            info = self._validate_directory_descriptor(fd, final=True)
            return info.st_dev, info.st_ino
        finally:
            os.close(fd)

    def _open_root(self) -> int:
        fd, _ = self._walk_root(create_final=False)
        try:
            info = self._validate_directory_descriptor(fd, final=True)
            if (info.st_dev, info.st_ino) != self._root_identity:
                raise SpatialMaterialStoreSecurityError("material_store_root_substituted")
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def _journal(
        self,
        *,
        pending_mode: Literal["recover", "defer", "tombstone"] = "recover",
        pending_identity: str | None = None,
    ) -> Iterator[tuple[int, int, list[dict[str, object]]]]:
        directory_fd = self._open_root()
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            created = False
            try:
                journal_fd = os.open(
                    "material.journal.jsonl", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd
                )
                created = True
            except FileExistsError:
                journal_fd = os.open("material.journal.jsonl", flags, dir_fd=directory_fd)
            if created:
                os.fchmod(journal_fd, 0o600)
                os.fsync(directory_fd)
            fcntl.flock(journal_fd, fcntl.LOCK_EX)
            self._verify_open_file(directory_fd, "material.journal.jsonl", journal_fd)
            if pending_mode == "recover":
                self._recover_pending_record(directory_fd, journal_fd)
            elif pending_mode == "defer":
                try:
                    self._read_pending_record(directory_fd)
                except SpatialMaterialStoreError as exc:
                    if str(exc) != "material_journal_pending_absent":
                        raise
                else:
                    raise SpatialMaterialStoreError(
                        "material_journal_pending_authority_required"
                    )
            elif pending_mode == "tombstone" and pending_identity is not None:
                self._recover_pending_record(
                    directory_fd,
                    journal_fd,
                    tombstone_identity=pending_identity,
                )
            else:
                raise SpatialMaterialStoreError("material_journal_pending_mode_invalid")
            records = self._read_journal(journal_fd)
            self._verify_open_file(directory_fd, "material.journal.jsonl", journal_fd)
            yield directory_fd, journal_fd, records
            self._verify_open_file(directory_fd, "material.journal.jsonl", journal_fd)
            opened_root = os.fstat(directory_fd)
            current_fd, _ = self._walk_root(create_final=False)
            try:
                current_root = os.fstat(current_fd)
            finally:
                os.close(current_fd)
            if (
                (opened_root.st_dev, opened_root.st_ino) != (current_root.st_dev, current_root.st_ino)
                or (opened_root.st_dev, opened_root.st_ino) != self._root_identity
            ):
                raise SpatialMaterialStoreSecurityError("material_store_root_substituted")
        except SpatialMaterialStoreError:
            raise
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_journal_unavailable") from None
        finally:
            if "journal_fd" in locals():
                try:
                    fcntl.flock(journal_fd, fcntl.LOCK_UN)
                    os.close(journal_fd)
                except OSError:
                    pass
            os.close(directory_fd)

    def _verify_open_file(self, directory_fd: int, name: str, fd: int) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_store_file_substituted") from None
        if (
            not stat.S_ISREG(opened.st_mode) or opened.st_uid != self._owner
            or stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise SpatialMaterialStoreSecurityError("material_store_file_insecure")

    def _read_journal(self, fd: int) -> list[dict[str, object]]:
        size = os.fstat(fd).st_size
        if size > _MAX_JOURNAL_BYTES:
            raise SpatialMaterialStoreError("material_journal_too_large")
        os.lseek(fd, 0, os.SEEK_SET)
        raw = b""
        while len(raw) < size:
            chunk = os.read(fd, min(65536, size - len(raw)))
            if not chunk:
                break
            raw += chunk
        return self._parse_journal_bytes(raw, expected_size=size)

    def _parse_journal_bytes(
        self, raw: bytes, *, expected_size: int | None = None,
    ) -> list[dict[str, object]]:
        if expected_size is not None and len(raw) != expected_size:
            raise SpatialMaterialStoreError("material_journal_truncated")
        if len(raw) > _MAX_JOURNAL_BYTES:
            raise SpatialMaterialStoreError("material_journal_too_large")
        if raw and not raw.endswith(b"\n"):
            raise SpatialMaterialStoreError("material_journal_truncated")
        records: list[dict[str, object]] = []
        prior: str | None = None
        framed_lines = raw.split(b"\n")[:-1] if raw else []
        for sequence, line in enumerate(framed_lines, start=1):
            if len(line) + 1 > _MAX_JOURNAL_RECORD_BYTES:
                raise SpatialMaterialStoreError("material_journal_record_too_large")
            try:
                pairs = json.loads(line, object_pairs_hook=lambda value: value)
                if not isinstance(pairs, list) or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                    raise ValueError
                keys = [pair[0] for pair in pairs]
                if len(keys) != len(set(keys)):
                    raise ValueError
                record = dict(pairs)
                if bounded_jcs(record) != line:
                    raise ValueError
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                raise SpatialMaterialStoreError("material_journal_record_invalid") from None
            if set(record) != _JOURNAL_MEMBERS:
                raise SpatialMaterialStoreError("material_journal_record_invalid")
            if isinstance(record["sequence"], bool) or record["sequence"] != sequence:
                raise SpatialMaterialStoreError("material_journal_sequence_invalid")
            if record["prior_record_digest"] != prior:
                raise SpatialMaterialStoreError("material_journal_prior_mismatch")
            expected = self._journal_digest(record)
            if record["record_digest"] != expected:
                raise SpatialMaterialStoreError("material_journal_digest_mismatch")
            try:
                validate_execution_ref(record["operation_id"])
                validate_execution_ref(record["material_identity"])
                validate_digest(record["composition_digest"])
                validate_digest(record["material_digest"])
                if record["envelope_digest"] is not None:
                    validate_digest(record["envelope_digest"])
                if record["requested_at"] is not None:
                    _validate_timestamp(record["requested_at"])
                _validate_timestamp(record["observed_at"])
            except (ValueError, TypeError, SpatialExecutionContractError):
                raise SpatialMaterialStoreError("material_journal_record_invalid") from None
            if not isinstance(record["state"], str) or record["state"] not in JOURNAL_STATES:
                raise SpatialMaterialStoreError("material_journal_state_invalid")
            records.append(record)
            prior = expected
        self._validate_journal_transitions(records)
        return records

    def _read_pending_record(self, directory_fd: int) -> tuple[dict[str, object], bytes]:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(_JOURNAL_PENDING_NAME, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            raise SpatialMaterialStoreError("material_journal_pending_absent") from None
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_journal_pending_unavailable") from None
        try:
            self._verify_open_file(directory_fd, _JOURNAL_PENDING_NAME, fd)
            size = os.fstat(fd).st_size
            if not 1 <= size <= 64 * 1024:
                raise SpatialMaterialStoreError("material_journal_pending_invalid")
            raw = b""
            while len(raw) < size:
                chunk = os.read(fd, min(65536, size - len(raw)))
                if not chunk:
                    break
                raw += chunk
            self._verify_open_file(directory_fd, _JOURNAL_PENDING_NAME, fd)
        finally:
            os.close(fd)
        try:
            payload = parse_raw_json(raw)
            if set(payload) != _JOURNAL_PENDING_MEMBERS:
                raise ValueError
            if payload.get("contract_name") != "ea.governed_spatial_material_journal_pending.v1":
                raise ValueError
            if payload.get("contract_version") != "1.0.0":
                raise ValueError
            pre_size = payload.get("journal_pre_size")
            if isinstance(pre_size, bool) or not isinstance(pre_size, int) or pre_size < 0:
                raise ValueError
            prior = payload.get("prior_record_digest")
            if prior is not None:
                validate_digest(prior)
            validate_digest(payload.get("record_digest"))
            if payload.get("record_encoding") != "base64url_no_padding":
                raise ValueError
            encoded_value = payload.get("record_bytes")
            if not isinstance(encoded_value, str):
                raise ValueError
            encoded = GovernedSpatialExecutionMaterialEnvelopeV1._decode(
                encoded_value, "journal_pending_record_encoding_invalid"
            )
            if len(encoded) > _MAX_JOURNAL_RECORD_BYTES:
                raise SpatialMaterialStoreError("material_journal_record_too_large")
            if not encoded.endswith(b"\n") or encoded.count(b"\n") != 1:
                raise ValueError
            record_payload = parse_raw_json(encoded[:-1])
            if bounded_jcs(record_payload) + b"\n" != encoded:
                raise ValueError
            if record_payload.get("record_digest") != payload.get("record_digest"):
                raise ValueError
            if record_payload.get("prior_record_digest") != prior:
                raise ValueError
            if raw != bounded_jcs(payload):
                raise ValueError
            return dict(payload), encoded
        except SpatialMaterialStoreError:
            raise
        except (RawJsonContractError, ValueError, TypeError, SpatialExecutionContractError):
            raise SpatialMaterialStoreError("material_journal_pending_invalid") from None

    def _recover_pending_record(
        self,
        directory_fd: int,
        journal_fd: int,
        *,
        tombstone_identity: str | None = None,
    ) -> None:
        try:
            pending, encoded = self._read_pending_record(directory_fd)
        except SpatialMaterialStoreError as exc:
            if str(exc) == "material_journal_pending_absent":
                return
            raise
        pre_size = pending["journal_pre_size"]
        if not isinstance(pre_size, int):
            raise SpatialMaterialStoreError("material_journal_pending_invalid")
        size = os.fstat(journal_fd).st_size
        if size < pre_size or size > pre_size + len(encoded):
            raise SpatialMaterialStoreError("material_journal_pending_mismatch")
        os.lseek(journal_fd, 0, os.SEEK_SET)
        raw = b""
        while len(raw) < size:
            chunk = os.read(journal_fd, min(65536, size - len(raw)))
            if not chunk:
                break
            raw += chunk
        if len(raw) != size:
            raise SpatialMaterialStoreError("material_journal_pending_mismatch")
        prefix = raw[:pre_size]
        prefix_records = self._parse_journal_bytes(prefix, expected_size=pre_size)
        expected_prior = prefix_records[-1]["record_digest"] if prefix_records else None
        if expected_prior != pending["prior_record_digest"]:
            raise SpatialMaterialStoreError("material_journal_pending_mismatch")
        tail = raw[pre_size:]
        if not encoded.startswith(tail):
            raise SpatialMaterialStoreError("material_journal_pending_mismatch")
        try:
            pending_record = dict(parse_raw_json(encoded[:-1]))
        except (RawJsonContractError, TypeError, ValueError):
            raise SpatialMaterialStoreError("material_journal_pending_invalid") from None
        records_after = [*prefix_records, pending_record]
        self._validate_journal_transitions(records_after)
        if tombstone_identity is not None:
            if pending_record.get("material_identity") != tombstone_identity:
                raise SpatialMaterialStoreError(
                    "material_journal_pending_authority_required"
                )
            if pending_record.get("state") in {
                "seal_intent",
                "sealed",
                "seal_aborted_missing_ciphertext",
            }:
                try:
                    os.ftruncate(journal_fd, pre_size)
                    os.fsync(journal_fd)
                    os.unlink(_JOURNAL_PENDING_NAME, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except OSError:
                    raise SpatialMaterialStoreSecurityError(
                        "material_journal_pending_tombstone_failed"
                    ) from None
                return
        _preflight_journal_capacity(
            current_size=pre_size,
            encoded_record=encoded,
            records_after=records_after,
        )
        try:
            if tail != encoded:
                os.ftruncate(journal_fd, pre_size)
                os.fsync(journal_fd)
                written = 0
                while written < len(encoded):
                    count = os.write(journal_fd, encoded[written:])
                    if count <= 0:
                        raise OSError
                    written += count
            os.fsync(journal_fd)
            repaired = self._read_journal(journal_fd)
            if not repaired or repaired[-1]["record_digest"] != pending["record_digest"]:
                raise SpatialMaterialStoreError("material_journal_pending_mismatch")
            os.unlink(_JOURNAL_PENDING_NAME, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except SpatialMaterialStoreError:
            raise
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_journal_pending_recovery_failed") from None

    def _write_pending_record(
        self, directory_fd: int, *, journal_pre_size: int,
        prior_record_digest: object, record_digest: object, encoded: bytes,
    ) -> None:
        if len(encoded) > _MAX_JOURNAL_RECORD_BYTES:
            raise SpatialMaterialStoreError("material_journal_record_too_large")
        payload = {
            "contract_name": "ea.governed_spatial_material_journal_pending.v1",
            "contract_version": "1.0.0",
            "journal_pre_size": journal_pre_size,
            "prior_record_digest": prior_record_digest,
            "record_digest": record_digest,
            "record_encoding": "base64url_no_padding",
            "record_bytes": _b64url(encoded),
        }
        raw = bounded_jcs(payload)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(_JOURNAL_PENDING_NAME, flags, 0o600, dir_fd=directory_fd)
            os.fchmod(fd, 0o600)
            written = 0
            while written < len(raw):
                count = os.write(fd, raw[written:])
                if count <= 0:
                    raise OSError
                written += count
            os.fsync(fd)
            self._verify_open_file(directory_fd, _JOURNAL_PENDING_NAME, fd)
            os.fsync(directory_fd)
        except OSError:
            try:
                os.unlink(_JOURNAL_PENDING_NAME, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except OSError:
                pass
            raise SpatialMaterialStoreSecurityError("material_journal_pending_write_failed") from None
        finally:
            if "fd" in locals():
                try:
                    os.close(fd)
                except OSError:
                    pass

    @staticmethod
    def _journal_digest(record: Mapping[str, object]) -> str:
        payload = dict(record)
        payload.pop("record_digest", None)
        return "sha256:" + hashlib.sha256(_bounded_canonical_bytes(payload)).hexdigest()

    @staticmethod
    def _validate_journal_transitions(records: list[dict[str, object]]) -> None:
        latest: dict[str, str] = {}
        bindings: dict[str, tuple[object, object]] = {}
        envelopes: dict[str, object] = {}
        requests: dict[str, object] = {}
        prior_observed: datetime | None = None
        allowed = {
            None: {"seal_intent", "delete_tombstone"},
            "seal_intent": {"sealed", "seal_aborted_missing_ciphertext", "delete_tombstone"},
            "seal_aborted_missing_ciphertext": {"seal_intent", "delete_tombstone"},
            "sealed": {"delete_tombstone"},
            "delete_tombstone": {"deleted"},
            "deleted": set(),
        }
        for record in records:
            identity = record["material_identity"]
            if not isinstance(identity, str):
                raise SpatialMaterialStoreError("material_journal_record_invalid")
            binding = (record["composition_digest"], record["material_digest"])
            if identity in bindings and bindings[identity] != binding:
                raise SpatialMaterialStoreError("material_journal_binding_changed")
            state = record["state"]
            if not isinstance(state, str):
                raise SpatialMaterialStoreError("material_journal_state_invalid")
            if state not in allowed.get(latest.get(identity), set()):
                raise SpatialMaterialStoreError("material_journal_transition_invalid")
            observed = _as_datetime(record["observed_at"])
            if prior_observed is not None and observed < prior_observed:
                raise SpatialMaterialStoreError("material_journal_observed_at_regression")
            prior_observed = observed
            envelope_digest = record["envelope_digest"]
            requested_at = record["requested_at"]
            if state == "sealed":
                if envelope_digest is None or requested_at is not None:
                    raise SpatialMaterialStoreError("material_journal_record_invalid")
                envelopes[identity] = envelope_digest
            elif state in {"seal_intent", "seal_aborted_missing_ciphertext"}:
                if envelope_digest is not None or requested_at is not None:
                    raise SpatialMaterialStoreError("material_journal_record_invalid")
            else:
                if requested_at is None or envelope_digest != envelopes.get(identity):
                    raise SpatialMaterialStoreError("material_journal_record_invalid")
                if _as_datetime(requested_at) > observed:
                    raise SpatialMaterialStoreError("material_journal_requested_at_after_observed")
                if identity in requests and requests[identity] != requested_at:
                    raise SpatialMaterialStoreError("material_journal_record_invalid")
                requests[identity] = requested_at
            bindings[identity] = binding
            latest[identity] = state  # type: ignore[assignment]

    def _build_journal_record(
        self, records: list[dict[str, object]], *, identity: str,
        composition_digest: str, digest: str, state: str,
        envelope_digest: str | None = None, requested_at: str | None = None,
        observed_at: str | None = None,
    ) -> tuple[dict[str, object], bytes]:
        sequence = len(records) + 1
        observed = (
            _as_datetime(observed_at)
            if observed_at is not None
            else _aware_utc(self._clock(), "material_store_clock_invalid")
        )
        if records:
            observed = max(observed, _as_datetime(records[-1]["observed_at"]))
        if requested_at is not None:
            observed = max(observed, _as_datetime(requested_at))
        record: dict[str, object] = {
            "sequence": sequence,
            "prior_record_digest": records[-1]["record_digest"] if records else None,
            "record_digest": "",
            "operation_id": f"material-operation:{sequence}",
            "state": state,
            "material_identity": identity,
            "composition_digest": composition_digest,
            "material_digest": digest,
            "envelope_digest": envelope_digest,
            "requested_at": requested_at,
            "observed_at": _timestamp(observed),
        }
        record["record_digest"] = self._journal_digest(record)
        encoded = _bounded_canonical_bytes(record) + b"\n"
        if len(encoded) > _MAX_JOURNAL_RECORD_BYTES:
            raise SpatialMaterialStoreError("material_journal_record_too_large")
        self._validate_journal_transitions([*records, record])
        return record, encoded

    def _append_record(
        self, directory_fd: int, fd: int, records: list[dict[str, object]], *, identity: str,
        composition_digest: str, digest: str, state: str,
        envelope_digest: str | None = None, requested_at: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, object]:
        record, encoded = self._build_journal_record(
            records,
            identity=identity,
            composition_digest=composition_digest,
            digest=digest,
            state=state,
            envelope_digest=envelope_digest,
            requested_at=requested_at,
            observed_at=observed_at,
        )
        pre_size = os.fstat(fd).st_size
        _preflight_journal_capacity(
            current_size=pre_size,
            encoded_record=encoded,
            records_after=[*records, record],
        )
        self._write_pending_record(
            directory_fd,
            journal_pre_size=pre_size,
            prior_record_digest=record["prior_record_digest"],
            record_digest=record["record_digest"],
            encoded=encoded,
        )
        self._crash_hook(f"before_journal_record_write:{state}")
        try:
            written = 0
            while written < len(encoded):
                count = self._journal_write(fd, encoded[written:])
                if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= len(encoded) - written:
                    raise OSError
                written += count
            self._crash_hook(f"before_journal_record_fsync:{state}")
            os.fsync(fd)
            self._crash_hook(f"after_journal_record_fsync:{state}")
            os.unlink(_JOURNAL_PENDING_NAME, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except SpatialMaterialStoreError:
            raise
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_journal_write_failed") from None
        records.append(record)
        return record

    @staticmethod
    def _latest(records: list[dict[str, object]], identity: str) -> dict[str, object] | None:
        return next((record for record in reversed(records) if record["material_identity"] == identity), None)

    @staticmethod
    def _temporary_filename(name: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}\.envelope\.json", name):
            raise SpatialMaterialStoreError("material_identity_invalid")
        return "." + name + ".tmp"

    def _verify_linked_publication(
        self, directory_fd: int, temporary: str, name: str, fd: int,
    ) -> None:
        opened = os.fstat(fd)
        try:
            temp_info = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
            final_info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_ciphertext_publication_substituted") from None
        identities = {
            (opened.st_dev, opened.st_ino),
            (temp_info.st_dev, temp_info.st_ino),
            (final_info.st_dev, final_info.st_ino),
        }
        if (
            len(identities) != 1 or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != self._owner or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 2 or temp_info.st_nlink != 2 or final_info.st_nlink != 2
        ):
            raise SpatialMaterialStoreSecurityError("material_ciphertext_publication_insecure")

    def _atomic_publish(self, directory_fd: int, name: str, payload: bytes) -> None:
        temporary = self._temporary_filename(name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
            os.fchmod(fd, 0o600)
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
            os.fsync(fd)
            self._verify_open_file(directory_fd, temporary, fd)
            os.fsync(directory_fd)
            self._crash_hook("after_ciphertext_temp_fsync")
            os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.fsync(directory_fd)
            self._verify_linked_publication(directory_fd, temporary, name, fd)
            self._crash_hook("after_ciphertext_link_fsync")
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
            self._verify_open_file(directory_fd, name, fd)
            self._crash_hook("after_ciphertext_temp_unlink_fsync")
        except FileExistsError:
            raise SpatialMaterialStoreError("material_identity_write_conflict") from None
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_ciphertext_write_failed") from None
        finally:
            if "fd" in locals():
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _read_envelope(self, directory_fd: int, identity: str) -> GovernedSpatialExecutionMaterialEnvelopeV1:
        name = self._filename(identity)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            raise SpatialMaterialStoreError("material_ciphertext_absent") from None
        except OSError:
            raise SpatialMaterialStoreSecurityError("material_ciphertext_unreadable") from None
        try:
            self._verify_open_file(directory_fd, name, fd)
            size = os.fstat(fd).st_size
            if not 1 <= size <= _MAX_ENVELOPE_BYTES:
                raise SpatialMaterialStoreError("material_ciphertext_size_invalid")
            raw = b""
            while len(raw) < size:
                chunk = os.read(fd, min(65536, size - len(raw)))
                if not chunk:
                    break
                raw += chunk
            if len(raw) != size:
                raise SpatialMaterialStoreError("material_ciphertext_truncated")
            self._verify_open_file(directory_fd, name, fd)
        finally:
            os.close(fd)
        try:
            payload = parse_raw_json(raw)
            envelope = GovernedSpatialExecutionMaterialEnvelopeV1.model_validate(payload)
            if raw != _bounded_canonical_bytes(_safe_model_dump(envelope, "execution_envelope")):
                raise ValueError
            return envelope
        except (RawJsonContractError, ValidationError, ValueError, SpatialExecutionContractError):
            raise SpatialMaterialStoreError("material_envelope_invalid") from None

    def _decrypt_envelope(
        self, envelope: GovernedSpatialExecutionMaterialEnvelopeV1, *, now: datetime,
    ) -> GovernedSpatialExecutionMaterialV1:
        if envelope.environment != self.environment:
            raise SpatialMaterialStoreError("material_envelope_environment_mismatch")
        aad = envelope_aad_bytes(envelope)
        record = self.keys.decryption_key(
            environment=envelope.environment, key_ref=envelope.key_ref, key_epoch=envelope.key_epoch,
            key_fingerprint=envelope.key_fingerprint, created_at=_as_datetime(envelope.created_at), now=now,
        )
        try:
            plaintext = AESGCM(record.key_bytes).decrypt(
                GovernedSpatialExecutionMaterialEnvelopeV1._decode(envelope.nonce, "nonce_shape_invalid"),
                GovernedSpatialExecutionMaterialEnvelopeV1._decode(envelope.ciphertext, "ciphertext_shape_invalid"),
                aad,
            )
        except (InvalidTag, ValueError):
            raise SpatialMaterialStoreError("material_authentication_failed") from None
        if len(plaintext) > MAX_CANONICAL_MATERIAL_BYTES:
            raise SpatialMaterialStoreError("material_plaintext_invalid")
        try:
            material = parse_execution_material(plaintext)
        except SpatialExecutionContractError:
            raise SpatialMaterialStoreError("material_plaintext_invalid") from None
        if canonical_material_bytes(material) != plaintext or material_digest(material) != envelope.material_digest:
            raise SpatialMaterialStoreError("material_digest_mismatch")
        for field in (
            "composition_digest", "request_digest", "source_packet_digest", "style_snapshot_digest",
            "output_contract_digest", "execution_target_digest", "retention_expires_at",
        ):
            if getattr(material, field) != getattr(envelope, field):
                raise SpatialMaterialStoreError("material_lineage_mismatch")
        if self.material_identity(material.composition_digest) != envelope.material_identity:
            raise SpatialMaterialStoreError("material_identity_mismatch")
        return material

    @staticmethod
    def _envelope_digest(envelope: GovernedSpatialExecutionMaterialEnvelopeV1) -> str:
        encoded = _bounded_canonical_bytes(_safe_model_dump(envelope, "execution_envelope"))
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _verify_sealed_envelope_binding(
        self, envelope: GovernedSpatialExecutionMaterialEnvelopeV1,
        journal_record: Mapping[str, object], *, composition_digest: str,
    ) -> None:
        if journal_record.get("envelope_digest") != self._envelope_digest(envelope):
            raise SpatialMaterialStoreError("material_envelope_substituted")
        if (
            envelope.composition_digest != composition_digest
            or journal_record.get("composition_digest") != composition_digest
            or journal_record.get("material_digest") != envelope.material_digest
            or envelope.material_identity != self.material_identity(composition_digest)
        ):
            raise SpatialMaterialStoreError("material_journal_envelope_mismatch")

    def _ciphertext_infos(
        self, directory_fd: int, identity: str,
    ) -> dict[str, os.stat_result]:
        final = self._filename(identity)
        names = (self._temporary_filename(final), final)
        result: dict[str, os.stat_result] = {}
        for name in names:
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                raise SpatialMaterialStoreSecurityError("material_ciphertext_unreadable") from None
            if (
                not stat.S_ISREG(info.st_mode) or info.st_uid != self._owner
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise SpatialMaterialStoreSecurityError("material_store_file_insecure")
            result[name] = info
        return result

    def _normalize_ciphertext_publication(self, directory_fd: int, identity: str) -> None:
        final = self._filename(identity)
        temporary = self._temporary_filename(final)
        infos = self._ciphertext_infos(directory_fd, identity)
        final_info = infos.get(final)
        temp_info = infos.get(temporary)
        if final_info is None and temp_info is None:
            return
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if final_info is not None and temp_info is not None:
            if (
                (final_info.st_dev, final_info.st_ino) != (temp_info.st_dev, temp_info.st_ino)
                or final_info.st_nlink != 2 or temp_info.st_nlink != 2
            ):
                raise SpatialMaterialStoreSecurityError("material_ciphertext_publication_insecure")
            try:
                fd = os.open(final, flags, dir_fd=directory_fd)
                self._verify_linked_publication(directory_fd, temporary, final, fd)
                os.unlink(temporary, dir_fd=directory_fd)
                os.fsync(directory_fd)
                self._verify_open_file(directory_fd, final, fd)
            except SpatialMaterialStoreError:
                raise
            except OSError:
                raise SpatialMaterialStoreSecurityError("material_ciphertext_recovery_failed") from None
            finally:
                if "fd" in locals():
                    os.close(fd)
            return
        if temp_info is not None:
            if temp_info.st_nlink != 1:
                raise SpatialMaterialStoreSecurityError("material_ciphertext_publication_insecure")
            try:
                fd = os.open(temporary, flags, dir_fd=directory_fd)
                self._verify_open_file(directory_fd, temporary, fd)
                os.link(
                    temporary, final, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.fsync(directory_fd)
                self._verify_linked_publication(directory_fd, temporary, final, fd)
                os.unlink(temporary, dir_fd=directory_fd)
                os.fsync(directory_fd)
                self._verify_open_file(directory_fd, final, fd)
            except SpatialMaterialStoreError:
                raise
            except OSError:
                raise SpatialMaterialStoreSecurityError("material_ciphertext_recovery_failed") from None
            finally:
                if "fd" in locals():
                    os.close(fd)
            return
        if final_info is not None and final_info.st_nlink != 1:
            raise SpatialMaterialStoreSecurityError("material_ciphertext_publication_insecure")

    def _unlink_ciphertext(self, directory_fd: int, identity: str, *, invalid: bool = False) -> None:
        final = self._filename(identity)
        temporary = self._temporary_filename(final)
        infos = self._ciphertext_infos(directory_fd, identity)
        if not infos:
            return
        if len(infos) == 1:
            if next(iter(infos.values())).st_nlink != 1:
                raise SpatialMaterialStoreSecurityError("material_store_file_insecure")
        else:
            final_info = infos[final]
            temp_info = infos[temporary]
            same = (final_info.st_dev, final_info.st_ino) == (temp_info.st_dev, temp_info.st_ino)
            if same and (final_info.st_nlink != 2 or temp_info.st_nlink != 2):
                raise SpatialMaterialStoreSecurityError("material_store_file_insecure")
            if not same and (final_info.st_nlink != 1 or temp_info.st_nlink != 1):
                raise SpatialMaterialStoreSecurityError("material_store_file_insecure")
        try:
            for name in (temporary, final):
                if name in infos:
                    os.unlink(name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
        except OSError:
            reason = "material_invalid_ciphertext_remove_failed" if invalid else "material_ciphertext_delete_failed"
            raise SpatialMaterialStoreSecurityError(reason) from None

    def _ensure_terminal_absence(self, directory_fd: int, identity: str) -> None:
        final = self._filename(identity)
        temporary = self._temporary_filename(final)
        for name in (temporary, final):
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                raise SpatialMaterialStoreSecurityError("material_terminal_path_unavailable") from None
            if stat.S_ISDIR(info.st_mode):
                raise SpatialMaterialStoreSecurityError("material_terminal_path_directory")
            try:
                os.unlink(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except OSError:
                raise SpatialMaterialStoreSecurityError("material_terminal_unlink_failed") from None

    def _recover(
        self, directory_fd: int, journal_fd: int, records: list[dict[str, object]], *, restart: bool = False,
    ) -> None:
        identities = list(dict.fromkeys(record["material_identity"] for record in records))
        for identity in identities:
            latest = self._latest(records, identity)  # type: ignore[arg-type]
            if latest is None:
                continue
            state = latest["state"]
            if state == "seal_intent":
                valid = False
                try:
                    self._normalize_ciphertext_publication(directory_fd, identity)  # type: ignore[arg-type]
                    envelope = self._read_envelope(directory_fd, identity)  # type: ignore[arg-type]
                    self._decrypt_envelope(envelope, now=_aware_utc(self._clock(), "material_store_clock_invalid"))
                    valid = (
                        envelope.composition_digest == latest["composition_digest"]
                        and envelope.material_digest == latest["material_digest"]
                    )
                except SpatialMaterialStoreSecurityError:
                    raise
                except SpatialMaterialStoreError as exc:
                    if str(exc) in {
                        "material_decrypt_key_unknown", "material_decrypt_key_revoked",
                        "material_key_not_yet_valid", "material_key_decrypt_horizon_elapsed",
                    }:
                        continue
                    if str(exc) not in {
                        "material_ciphertext_absent", "material_ciphertext_size_invalid",
                        "material_ciphertext_truncated", "material_envelope_invalid",
                        "material_authentication_failed", "material_plaintext_invalid",
                        "material_digest_mismatch", "material_lineage_mismatch",
                        "material_identity_mismatch", "material_envelope_environment_mismatch",
                    }:
                        raise
                    valid = False
                if valid:
                    try:
                        self._append_record(
                            directory_fd, journal_fd, records, identity=identity,
                            composition_digest=latest["composition_digest"],
                            digest=latest["material_digest"], state="sealed",
                            envelope_digest=self._envelope_digest(envelope),
                        )
                    except SpatialMaterialStoreError as exc:
                        if str(exc) != "material_journal_capacity_exceeded":
                            raise
                else:
                    self._unlink_ciphertext(directory_fd, identity, invalid=True)  # type: ignore[arg-type]
                    try:
                        self._append_record(
                            directory_fd, journal_fd, records, identity=identity,
                            composition_digest=latest["composition_digest"],
                            digest=latest["material_digest"], state="seal_aborted_missing_ciphertext",
                        )
                    except SpatialMaterialStoreError as exc:
                        if str(exc) != "material_journal_capacity_exceeded":
                            raise
            elif state == "sealed" and restart:
                envelope = self._read_envelope(directory_fd, identity)  # type: ignore[arg-type]
                self._verify_sealed_envelope_binding(
                    envelope, latest, composition_digest=latest["composition_digest"]  # type: ignore[arg-type]
                )
            elif state == "seal_aborted_missing_ciphertext":
                self._ensure_terminal_absence(directory_fd, identity)  # type: ignore[arg-type]
            elif state in {"delete_tombstone", "deleted"}:
                self._ensure_terminal_absence(directory_fd, identity)  # type: ignore[arg-type]
                if state == "delete_tombstone":
                    self._append_record(
                        directory_fd, journal_fd, records, identity=identity,
                        composition_digest=latest["composition_digest"],
                        digest=latest["material_digest"], state="deleted",
                        envelope_digest=latest["envelope_digest"], requested_at=latest["requested_at"],
                        observed_at=latest["observed_at"],
                    )

    def recover_pending_intent(
        self,
        material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object],
        *,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None = None,
    ) -> dict[str, object]:
        if not self.authority_guarded_recovery:
            raise SpatialMaterialStoreError("material_explicit_recovery_mode_required")
        parsed = parse_execution_material(
            _safe_model_dump(material, "execution_material")
            if isinstance(material, GovernedSpatialExecutionMaterialV1)
            else material
        )
        digest = material_digest(parsed)
        identity = self.material_identity(parsed.composition_digest)
        self._require_lifecycle_guard(parsed.composition_digest, lifecycle_guard)
        now = _aware_utc(self._clock(), "material_store_clock_invalid")
        # Pending-record completion is allowed only after retention authority revalidation.
        self._verified_retention_expiry(parsed)
        if now >= _as_datetime(parsed.retention_expires_at):
            raise SpatialMaterialStoreError("material_retention_expired")
        with self._journal() as (directory_fd, journal_fd, records):
            latest = self._latest(records, identity)
            if latest is not None and latest["state"] in {"delete_tombstone", "deleted"}:
                raise SpatialMaterialStoreError("material_tombstoned")
            if latest is not None and latest["material_digest"] != digest:
                raise SpatialMaterialStoreError("material_identity_write_conflict")

            if latest is None:
                return {
                    "state": "absent",
                    "composition_digest": parsed.composition_digest,
                    "material_digest": digest,
                }
            state = latest["state"]
            if state == "seal_aborted_missing_ciphertext":
                self._ensure_terminal_absence(directory_fd, identity)
                return {
                    "state": state,
                    "composition_digest": parsed.composition_digest,
                    "material_digest": digest,
                }
            if state == "sealed":
                envelope = self._read_envelope(directory_fd, identity)
                loaded = self._decrypt_envelope(envelope, now=now)
                self._verify_sealed_envelope_binding(
                    envelope, latest, composition_digest=parsed.composition_digest
                )
                if (
                    material_digest(loaded) != digest
                    or _safe_model_dump(loaded, "execution_material")
                    != _safe_model_dump(parsed, "execution_material")
                ):
                    raise SpatialMaterialStoreError("material_recovery_plaintext_mismatch")
                return {
                    "state": "sealed",
                    "composition_digest": parsed.composition_digest,
                    "material_digest": digest,
                }
            if state != "seal_intent":
                raise SpatialMaterialStoreError("material_repair_not_allowed")

            try:
                self._normalize_ciphertext_publication(directory_fd, identity)
                envelope = self._read_envelope(directory_fd, identity)
                loaded = self._decrypt_envelope(envelope, now=now)
                valid = (
                    envelope.material_identity == identity
                    and envelope.composition_digest == parsed.composition_digest
                    and envelope.material_digest == digest
                    and latest["composition_digest"] == parsed.composition_digest
                    and latest["material_digest"] == digest
                    and material_digest(loaded) == digest
                    and _safe_model_dump(loaded, "execution_material")
                    == _safe_model_dump(parsed, "execution_material")
                )
                if not valid:
                    raise SpatialMaterialStoreError("material_recovery_plaintext_mismatch")
            except SpatialMaterialStoreSecurityError:
                raise
            except SpatialMaterialStoreError as exc:
                if str(exc) in {
                    "material_decrypt_key_unknown",
                    "material_decrypt_key_revoked",
                    "material_key_not_yet_valid",
                    "material_key_decrypt_horizon_elapsed",
                }:
                    raise
                if str(exc) not in {
                    "material_ciphertext_absent",
                    "material_ciphertext_size_invalid",
                    "material_ciphertext_truncated",
                    "material_envelope_invalid",
                    "material_authentication_failed",
                    "material_plaintext_invalid",
                    "material_digest_mismatch",
                    "material_lineage_mismatch",
                    "material_identity_mismatch",
                    "material_envelope_environment_mismatch",
                    "material_recovery_plaintext_mismatch",
                }:
                    raise
                self._unlink_ciphertext(directory_fd, identity, invalid=True)
                self._append_record(
                    directory_fd,
                    journal_fd,
                    records,
                    identity=identity,
                    composition_digest=parsed.composition_digest,
                    digest=digest,
                    state="seal_aborted_missing_ciphertext",
                )
                return {
                    "state": "seal_aborted_missing_ciphertext",
                    "composition_digest": parsed.composition_digest,
                    "material_digest": digest,
                }

            self._append_record(
                directory_fd,
                journal_fd,
                records,
                identity=identity,
                composition_digest=parsed.composition_digest,
                digest=digest,
                state="sealed",
                envelope_digest=self._envelope_digest(envelope),
            )
            return {
                "state": "sealed",
                "composition_digest": parsed.composition_digest,
                "material_digest": digest,
            }

    def _verified_retention_expiry(self, material: GovernedSpatialExecutionMaterialV1) -> datetime:
        source = _as_datetime(material.source_packet_created_at)
        compose = _as_datetime(material.compose_created_at)
        supplied = _as_datetime(material.retention_expires_at)
        hard_ceiling = min(source, compose) + timedelta(days=30)
        if supplied > hard_ceiling:
            raise SpatialMaterialStoreError("material_retention_ceiling_exceeded")
        if self._retention_resolver is None:
            raise SpatialMaterialStoreError("material_retention_verifier_unavailable")
        try:
            verified = _aware_utc(
                self._retention_resolver(material), "material_retention_verification_failed"
            )
        except SpatialMaterialStoreError:
            raise
        except Exception:
            raise SpatialMaterialStoreError("material_retention_verification_failed") from None
        if verified > hard_ceiling:
            raise SpatialMaterialStoreError("material_retention_ceiling_exceeded")
        if verified != supplied:
            raise SpatialMaterialStoreError("material_retention_verification_mismatch")
        return verified

    def seal(
        self,
        material: GovernedSpatialExecutionMaterialV1 | Mapping[str, object],
        *,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None = None,
    ) -> GovernedSpatialExecutionMaterialEnvelopeV1:
        parsed = parse_execution_material(
            _safe_model_dump(material, "execution_material") if isinstance(material, GovernedSpatialExecutionMaterialV1) else material
        )
        plaintext = canonical_material_bytes(parsed)
        digest = "sha256:" + hashlib.sha256(plaintext).hexdigest()
        identity = self.material_identity(parsed.composition_digest)
        self._require_lifecycle_guard(parsed.composition_digest, lifecycle_guard)
        now = _aware_utc(self._clock(), "material_store_clock_invalid")
        retention = _as_datetime(parsed.retention_expires_at)
        if now >= retention:
            raise SpatialMaterialStoreError("material_retention_expired")
        if self.authority_guarded_recovery:
            self._verified_retention_expiry(parsed)
        with self._journal(
            pending_mode="defer" if self.authority_guarded_recovery else "recover"
        ) as (directory_fd, journal_fd, records):
            if not self.authority_guarded_recovery:
                self._recover(directory_fd, journal_fd, records)
            latest = self._latest(records, identity)
            if latest is not None:
                if latest["material_digest"] != digest:
                    raise SpatialMaterialStoreError("material_identity_write_conflict")
                if latest["state"] in {"delete_tombstone", "deleted"}:
                    raise SpatialMaterialStoreError("material_tombstoned")
                if latest["state"] == "sealed":
                    envelope = self._read_envelope(directory_fd, identity)
                    self._decrypt_envelope(envelope, now=now)
                    self._verify_sealed_envelope_binding(
                        envelope, latest, composition_digest=parsed.composition_digest
                    )
                    return envelope
                if latest["state"] == "seal_intent":
                    raise SpatialMaterialStoreError("material_unavailable")
                if latest["state"] != "seal_aborted_missing_ciphertext":
                    raise SpatialMaterialStoreError("material_repair_not_allowed")
            self._verified_retention_expiry(parsed)
            key = self.keys.encryption_key(
                environment=self.environment, compose_at=_as_datetime(parsed.compose_created_at),
                retention_expires_at=retention,
            )
            self._append_record(
                directory_fd, journal_fd, records, identity=identity, composition_digest=parsed.composition_digest,
                digest=digest, state="seal_intent",
            )
            self._crash_hook("after_seal_intent")
            nonce = self._randomness(12)
            if not isinstance(nonce, bytes) or len(nonce) != 12:
                raise SpatialMaterialStoreError("material_randomness_invalid")
            payload: dict[str, object] = {
                "contract_name": "ea.governed_spatial_execution_material_envelope.v1",
                "contract_version": "1.0.0",
                "environment": self.environment,
                "material_identity": identity,
                "material_digest": digest,
                "composition_digest": parsed.composition_digest,
                "request_digest": parsed.request_digest,
                "source_packet_digest": parsed.source_packet_digest,
                "style_snapshot_digest": parsed.style_snapshot_digest,
                "output_contract_digest": parsed.output_contract_digest,
                "execution_target_digest": parsed.execution_target_digest,
                "created_at": parsed.compose_created_at,
                "retention_expires_at": parsed.retention_expires_at,
                "key_ref": key.key_ref,
                "key_epoch": key.key_epoch,
                "key_fingerprint": key.key_fingerprint,
                "algorithm": "aes-256-gcm",
                "nonce_encoding": "base64url_no_padding",
                "nonce": _b64url(nonce),
                "ciphertext_encoding": "base64url_no_padding",
                "ciphertext": "",
                "canonicalization": CANONICALIZATION,
                "aad_digest": "",
            }
            envelope, encoded_envelope = _seal_envelope_payload(
                payload, plaintext=plaintext, key_bytes=key.key_bytes
            )
            self._atomic_publish(directory_fd, self._filename(identity), encoded_envelope)
            self._crash_hook("after_ciphertext_fsync")
            self._append_record(
                directory_fd, journal_fd, records, identity=identity, composition_digest=parsed.composition_digest,
                digest=digest, state="sealed", envelope_digest=self._envelope_digest(envelope),
            )
            self._crash_hook("after_sealed")
            return envelope

    def load(
        self,
        composition_digest: str,
        *,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None = None,
    ) -> GovernedSpatialExecutionMaterialV1:
        identity = self.material_identity(composition_digest)
        self._require_lifecycle_guard(composition_digest, lifecycle_guard)
        now = _aware_utc(self._clock(), "material_store_clock_invalid")
        with self._journal(
            pending_mode="defer" if self.authority_guarded_recovery else "recover"
        ) as (directory_fd, journal_fd, records):
            if not self.authority_guarded_recovery:
                self._recover(directory_fd, journal_fd, records)
            latest = self._latest(records, identity)
            if latest is None:
                raise SpatialMaterialStoreError("material_absent")
            if latest["state"] in {"delete_tombstone", "deleted"}:
                raise SpatialMaterialStoreError("material_tombstoned")
            if latest["state"] != "sealed":
                raise SpatialMaterialStoreError("material_unavailable")
            envelope = self._read_envelope(directory_fd, identity)
            if now >= _as_datetime(envelope.retention_expires_at):
                self._verify_sealed_envelope_binding(
                    envelope, latest, composition_digest=composition_digest
                )
                requested = _timestamp(now)
                self._append_record(
                    directory_fd, journal_fd, records, identity=identity, composition_digest=latest["composition_digest"],
                    digest=latest["material_digest"], state="delete_tombstone",
                    envelope_digest=latest["envelope_digest"], requested_at=requested,
                    observed_at=requested,
                )
                self._ensure_terminal_absence(directory_fd, identity)
                self._append_record(
                    directory_fd, journal_fd, records, identity=identity, composition_digest=latest["composition_digest"],
                    digest=latest["material_digest"], state="deleted",
                    envelope_digest=latest["envelope_digest"], requested_at=requested,
                    observed_at=requested,
                )
                raise SpatialMaterialStoreError("material_retention_expired")
            material = self._decrypt_envelope(envelope, now=now)
            self._verify_sealed_envelope_binding(
                envelope, latest, composition_digest=composition_digest
            )
            return material

    @staticmethod
    def _deletion_evidence_projection(
        composition_digest: str,
        tombstone: Mapping[str, object],
        deleted: Mapping[str, object] | None,
    ) -> PropertyDeletionEvidenceProjectionV1:
        evidence_base = {
            "scope_digest": composition_digest,
            "tombstone_digest": tombstone["record_digest"],
            "requested_at": tombstone["requested_at"],
            "tombstoned_at": tombstone["observed_at"],
            "ciphertext_deleted_at": deleted["observed_at"] if deleted is not None else None,
        }
        evidence_digest = "sha256:" + hashlib.sha256(
            _bounded_canonical_bytes(evidence_base)
        ).hexdigest()
        try:
            return PropertyDeletionEvidenceProjectionV1.model_validate(
                {
                    "contract_name": "propertyquarry.governed_spatial_deletion_evidence_projection.v1",
                    "contract_version": "1.0.0",
                    **evidence_base,
                    "deletion_evidence_digest": evidence_digest,
                    "derivative_coverage": "complete",
                    "provider_deletion_state": "not_applicable",
                    "retry_state": "not_required",
                    "next_retry_at": None,
                }
            )
        except (ValidationError, ValueError, SpatialExecutionContractError):
            raise SpatialMaterialStoreError("material_deletion_projection_invalid") from None

    def preemptive_tombstone(
        self,
        composition_digest: str,
        material_digest_value: str,
        *,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None = None,
        requested_at: datetime | None = None,
    ) -> PropertyDeletionEvidenceProjectionV1:
        if not self.authority_guarded_recovery:
            raise SpatialMaterialStoreError("material_preemptive_tombstone_mode_required")
        try:
            validate_digest(composition_digest)
            validate_digest(material_digest_value)
        except (SpatialExecutionContractError, ValueError):
            raise SpatialMaterialStoreError(
                "material_preemptive_tombstone_binding_invalid"
            ) from None
        identity = self.material_identity(composition_digest)
        self._require_lifecycle_guard(
            composition_digest,
            lifecycle_guard,
            allow_privacy=True,
            require_privacy=True,
        )
        if lifecycle_guard is None:
            raise SpatialMaterialStoreError("material_lifecycle_guard_required")
        privacy_status = lifecycle_guard.privacy_status
        if not isinstance(privacy_status, Mapping):
            raise SpatialMaterialStoreError(
                "material_lifecycle_privacy_tombstone_required"
            )
        recorded_at = privacy_status.get("recorded_at")
        try:
            if privacy_status.get("scope_digest") != composition_digest:
                raise ValueError
            _validate_timestamp(recorded_at)  # type: ignore[arg-type]
            privacy_requested = _as_datetime(recorded_at)  # type: ignore[arg-type]
            if _timestamp(privacy_requested) != recorded_at:
                raise ValueError
        except (TypeError, ValueError):
            raise SpatialMaterialStoreError(
                "material_lifecycle_privacy_tombstone_invalid"
            ) from None
        if requested_at is not None:
            supplied_requested = _aware_utc(
                requested_at, "material_store_clock_invalid"
            )
            if supplied_requested != privacy_requested:
                raise SpatialMaterialStoreError(
                    "material_preemptive_tombstone_request_mismatch"
                )
        operation_now = _aware_utc(self._clock(), "material_store_clock_invalid")
        requested = privacy_requested
        observed = max(operation_now, requested)
        with self._journal(
            pending_mode="tombstone",
            pending_identity=identity,
        ) as (directory_fd, journal_fd, records):
            latest = self._latest(records, identity)
            if latest is not None and (
                latest["composition_digest"] != composition_digest
                or latest["material_digest"] != material_digest_value
            ):
                raise SpatialMaterialStoreError("material_identity_write_conflict")
            if latest is None or latest["state"] not in {"delete_tombstone", "deleted"}:
                tombstone = self._append_record(
                    directory_fd,
                    journal_fd,
                    records,
                    identity=identity,
                    composition_digest=composition_digest,
                    digest=material_digest_value,
                    state="delete_tombstone",
                    envelope_digest=latest["envelope_digest"] if latest is not None else None,
                    requested_at=_timestamp(requested),
                    observed_at=_timestamp(observed),
                )
                self._crash_hook("after_delete_tombstone")
            else:
                tombstone = next(
                    record
                    for record in reversed(records)
                    if record["material_identity"] == identity
                    and record["state"] == "delete_tombstone"
                )
            latest = self._latest(records, identity)
            if latest is not None and latest["state"] == "delete_tombstone":
                self._ensure_terminal_absence(directory_fd, identity)
                self._crash_hook("after_ciphertext_unlink")
                deleted = self._append_record(
                    directory_fd,
                    journal_fd,
                    records,
                    identity=identity,
                    composition_digest=composition_digest,
                    digest=material_digest_value,
                    state="deleted",
                    envelope_digest=latest["envelope_digest"],
                    requested_at=latest["requested_at"],
                    observed_at=tombstone["observed_at"],
                )
                self._crash_hook("after_deleted")
            else:
                deleted = latest
                self._ensure_terminal_absence(directory_fd, identity)
            return self._deletion_evidence_projection(
                composition_digest,
                tombstone,
                deleted,
            )

    def delete(
        self,
        composition_digest: str,
        *,
        requested_at: datetime | None = None,
        lifecycle_guard: SpatialCompositionLifecycleGuard | None = None,
    ) -> PropertyDeletionEvidenceProjectionV1:
        identity = self.material_identity(composition_digest)
        self._require_lifecycle_guard(composition_digest, lifecycle_guard)
        operation_now = _aware_utc(self._clock(), "material_store_clock_invalid")
        requested = _aware_utc(requested_at or operation_now, "material_store_clock_invalid")
        if requested > operation_now:
            raise SpatialMaterialStoreError("material_delete_request_in_future")
        with self._journal(
            pending_mode="defer" if self.authority_guarded_recovery else "recover"
        ) as (directory_fd, journal_fd, records):
            if not self.authority_guarded_recovery:
                self._recover(directory_fd, journal_fd, records)
            latest = self._latest(records, identity)
            if latest is None:
                raise SpatialMaterialStoreError("material_absent")
            if latest["state"] not in {"delete_tombstone", "deleted"}:
                tombstone = self._append_record(
                    directory_fd, journal_fd, records, identity=identity, composition_digest=latest["composition_digest"],
                    digest=latest["material_digest"], state="delete_tombstone",
                    envelope_digest=latest["envelope_digest"], requested_at=_timestamp(requested),
                    observed_at=_timestamp(operation_now),
                )
                self._crash_hook("after_delete_tombstone")
            else:
                tombstone = next(
                    record for record in reversed(records)
                    if record["material_identity"] == identity and record["state"] == "delete_tombstone"
                )
            latest = self._latest(records, identity)
            if latest is not None and latest["state"] == "delete_tombstone":
                self._ensure_terminal_absence(directory_fd, identity)
                self._crash_hook("after_ciphertext_unlink")
                deleted = self._append_record(
                    directory_fd, journal_fd, records, identity=identity, composition_digest=latest["composition_digest"],
                    digest=latest["material_digest"], state="deleted",
                    envelope_digest=latest["envelope_digest"], requested_at=latest["requested_at"],
                    observed_at=tombstone["observed_at"],
                )
                self._crash_hook("after_deleted")
            else:
                deleted = latest
                self._ensure_terminal_absence(directory_fd, identity)
            return self._deletion_evidence_projection(
                composition_digest,
                tombstone,
                deleted,
            )


__all__ = [
    "CANONICALIZATION",
    "Ed25519Signature",
    "GovernedSpatialAssetBindingV1",
    "GovernedSpatialExecutionMaterialEnvelopeV1",
    "GovernedSpatialExecutionMaterialV1",
    "GovernedSpatialExecutionRequestV1",
    "GovernedSpatialExecutionResultV1",
    "GovernedSpatialOperationReconciliationV1",
    "GovernedSpatialRenderSpecV1",
    "GovernedSpatialStyleSnapshotV1",
    "PropertyDeletionEvidenceProjectionV1",
    "PropertyExecutionProjectionV1",
    "PropertyResponse",
    "SpatialExecutionMaterialStore",
    "SpatialExecutionContractError",
    "SpatialMaterialKeyRecord",
    "SpatialMaterialKeyRegistry",
    "SpatialMaterialStoreError",
    "SpatialMaterialStoreSecurityError",
    "canonical_material_bytes",
    "envelope_aad_bytes",
    "fixed_material_retention_expiry",
    "key_fingerprint",
    "material_digest",
    "parse_execution_material",
    "parse_execution_request",
    "parse_property_response",
    "reconciliation_digest",
    "validate_digest",
    "validate_execution_ref",
    "validate_execution_gate_versions",
    "validate_execution_request_material_binding",
    "validate_reconciliation_freshness",
    "validate_reconciliation_transition",
    "validate_style_snapshot_time",
]
