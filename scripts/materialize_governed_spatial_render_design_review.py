from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
CHUMMER_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design")
DEFAULT_DECISION = (
    CHUMMER_DESIGN_ROOT
    / "products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md"
)
DEFAULT_PETITION = ROOT / "EA_GOVERNED_SPATIAL_RENDER_DESIGN_PETITION.md"
DEFAULT_HANDOFF = ROOT / "PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md"
DEFAULT_OUTPUT = (
    ROOT / "_completion/governed-spatial-render/"
    "GOVERNED_SPATIAL_RENDER_DESIGN_REVIEW_RECEIPT.generated.json"
)
CANONICAL_REVIEW_STATUS = "canonical_review_revise_implementation_blocked"

_CANONICAL_VALIDATION_REASON_PREFIXES = frozenset(
    {
        "canonical_input_hash_drift",
        "canonical_input_missing",
        "decision_authority_marker_missing",
        "decision_canonical_binding_missing",
        "decision_evidence_binding_missing",
        "decision_hash_drift",
        "decision_heading_invalid",
        "decision_metadata_invalid",
        "decision_missing",
        "handoff_hash_drift",
        "handoff_missing",
        "petition_hash_drift",
        "petition_missing",
    }
)

EXPECTED_DECISION_SHA256 = (
    "2a5e4888bf2e9074a93e97e83d682e385eff53dd9c5ef8961fdc2fec6c2d1d6c"
)
EXPECTED_PETITION_SHA256 = (
    "ed4f8452d59760e11b6ab7784c9a35d272db4d62520d6c742740573424b3f45e"
)
EXPECTED_HANDOFF_SHA256 = (
    "e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06"
)
EXPECTED_CANONICAL_INPUTS = {
    "products/chummer/LEAD_DESIGNER_OPERATING_MODEL.md": (
        "0eca794b5ece5bc83a48cb6f6816f89d139e739754c7f528e2c394238bbb6892"
    ),
    "products/chummer/ARCHITECTURE.md": (
        "bd2941f7539376de35b068fb73ac5af581a931ed268b180634b5eaa782e90650"
    ),
    "products/chummer/OWNERSHIP_MATRIX.md": (
        "6a584dcad3c4f81b93a81740097b4f8ee29b08947b9611918c3619f64223cb63"
    ),
    "products/chummer/CONTRACT_SETS.yaml": (
        "8c071093fecb37f265c32bcfd566c4d59df6052f3f9b6964c46af7ab45ef81ff"
    ),
    "products/chummer/PROGRAM_MILESTONES.yaml": (
        "a64d00450ba8f919aaffbda1b30ffc45c001e7c9fb2b8b66acf44d0a8fa4a0bb"
    ),
    "products/chummer/projects/executive-assistant.md": (
        "42371aa85147793958e7587a42adfddcd1583c8fcc1a976474b2eb840a4de508"
    ),
    "products/chummer/HORIZON_REGISTRY.yaml": (
        "f7a0b245f8d50cb2e38ff14871c2e57b6f9b3d9423447ef1a41e785549640891"
    ),
    "products/chummer/MEDIA_ARTIFACT_RECIPE_REGISTRY.yaml": (
        "887ada36bdaf5d7879fa8092dfa7342902751d1abaee958fc3ba9d80da7a4ef4"
    ),
}
REQUIRED_DECISION_HEADINGS = (
    "## Independent review declaration",
    "## Authority adjudication",
    "## Privacy, retention, deletion, and takedown posture",
    "## Promotion, canary, and rollback gates",
    "## Permitted scope while blocked",
    "## Forbidden scope while blocked",
    "## Exact amendments and canonical follow-up",
    "## Risks and controller-review requirement",
)
REQUIRED_DECISION_MARKERS = (
    "`chummer6-media-factory` must own the schema in `Chummer.Media.Contracts`",
    "`chummer6-hub` owns the Chummer bridge and orchestration",
    "The exact PropertyQuarry repo/package owner must be ratified by PropertyQuarry canon",
    "A combat preview must be a separate private Chummer media recipe",
    "Under the proposed, unregistered contract, nobody is authorized to reserve or consume quota",
    "No provider is found ready by this decision",
    "clean 48-hour canary",
    "items 1 through 10 pass controller and independent design review",
)
REQUIRED_AMENDMENTS = (
    "contract_canon",
    "architecture_and_ownership",
    "repo_scopes_and_propertyquarry_authority",
    "separate_chummer_recipes",
    "runsite_boundary",
    "privacy_schedule",
    "capability_and_quota_evidence",
    "milestones_and_gates",
    "mirror_discipline",
    "independent_re_review_packet",
)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _utc_iso(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _parse_time(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redacted_validation_failure(error: BaseException) -> tuple[str, str]:
    raw = str(error).strip()
    candidate = raw.split(":", 1)[0]
    reason = (
        candidate
        if candidate in _CANONICAL_VALIDATION_REASON_PREFIXES
        else "canonical_validation_failed"
    )
    return reason, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label}_missing:{path}")
    actual = _file_sha256(path)
    if actual != expected:
        raise ValueError(f"{label}_hash_drift:{actual}")


def _validate_decision_text(text: str) -> None:
    exact_lines = (
        "Petition ID: `ea-governed-spatial-render-contract-v1`",
        "Disposition: revise",
        "Implementation state: blocked",
    )
    lines = text.splitlines()
    for expected in exact_lines:
        if lines.count(expected) != 1:
            raise ValueError(f"decision_metadata_invalid:{expected}")
    for heading in REQUIRED_DECISION_HEADINGS:
        if lines.count(heading) != 1:
            raise ValueError(f"decision_heading_invalid:{heading}")
    for marker in REQUIRED_DECISION_MARKERS:
        if marker not in text:
            raise ValueError(f"decision_authority_marker_missing:{marker}")


def _validate_bound_sources() -> list[dict[str, str]]:
    _require_hash(DEFAULT_DECISION, EXPECTED_DECISION_SHA256, "decision")
    _require_hash(DEFAULT_PETITION, EXPECTED_PETITION_SHA256, "petition")
    _require_hash(DEFAULT_HANDOFF, EXPECTED_HANDOFF_SHA256, "handoff")
    decision_text = DEFAULT_DECISION.read_text(encoding="utf-8")
    _validate_decision_text(decision_text)

    rows: list[dict[str, str]] = []
    for relative_path, expected_hash in EXPECTED_CANONICAL_INPUTS.items():
        path = CHUMMER_DESIGN_ROOT / relative_path
        _require_hash(path, expected_hash, "canonical_input")
        if relative_path not in decision_text or expected_hash not in decision_text:
            raise ValueError(f"decision_canonical_binding_missing:{relative_path}")
        rows.append({"path": str(path), "sha256": expected_hash})
    for evidence_path, expected_hash in (
        (DEFAULT_PETITION, EXPECTED_PETITION_SHA256),
        (DEFAULT_HANDOFF, EXPECTED_HANDOFF_SHA256),
    ):
        if (
            str(evidence_path) not in decision_text
            or expected_hash not in decision_text
        ):
            raise ValueError(f"decision_evidence_binding_missing:{evidence_path}")
    return rows


def build_design_review_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    canonical_snapshot = _validate_bound_sources()
    now = (observed_at or _utc_now()).astimezone(UTC)
    body: dict[str, object] = {
        "contract_name": "ea.governed_spatial_render_design_review_intake.v1",
        "generated_at": _utc_iso(now),
        "petition_id": "ea-governed-spatial-render-contract-v1",
        "status": "revise_blocked",
        "review_applicable": True,
        "decision": {
            "path": str(DEFAULT_DECISION),
            "sha256": EXPECTED_DECISION_SHA256,
            "disposition": "revise",
            "implementation_state": "blocked",
            "independent_review": True,
        },
        "evidence_snapshot": [
            {"path": str(DEFAULT_PETITION), "sha256": EXPECTED_PETITION_SHA256},
            {"path": str(DEFAULT_HANDOFF), "sha256": EXPECTED_HANDOFF_SHA256},
        ],
        "canonical_snapshot": canonical_snapshot,
        "authority_contract": {
            "durable_chummer_contract_owner": "chummer6-media-factory:Chummer.Media.Contracts",
            "chummer_product_bridge_owner": "chummer6-hub",
            "propertyquarry_bridge_owner": "propertyquarry_canon_decision_required",
            "combat_overlay_boundary": (
                "private_chummer_recipe_only:immutable_truth_refs:no_mechanics:no_propertyquarry_input"
            ),
            "current_quota_authority": "none_under_unregistered_proposal",
            "future_private_execution_receipt_owner": (
                "chummer6-media-factory_subject_to_canonical_amendment"
            ),
            "privacy_retention": "incomplete_numeric_policy_and_deletion_cascade_required",
            "promotion_gates": (
                "canonical_amendments:independent_re_review:artifact_gates:48h_canary:explicit_promotion"
            ),
        },
        "required_amendments": list(REQUIRED_AMENDMENTS),
        "implementation_authorized": False,
        "provider_execution_authorized": False,
        "quota_authorized": False,
        "product_bridge_registration_authorized": False,
        "live_change_authorized": False,
        "independent_re_review_required": True,
        "launch_recommendation": "no",
    }
    receipt = {**body, "receipt_digest": _sha256_json(body)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    output_path.chmod(0o600)
    return receipt


def verify_design_review_receipt_payload(
    value: object,
    *,
    verify_bound_files: bool = True,
) -> dict[str, object]:
    issues: list[str] = []
    validation_failure_fingerprints: list[dict[str, str]] = []
    receipt = dict(value) if isinstance(value, Mapping) else {}
    body = {key: nested for key, nested in receipt.items() if key != "receipt_digest"}
    if receipt.get("receipt_digest") != _sha256_json(body):
        issues.append("design_review_receipt_digest_invalid")
    expected_scalars = {
        "contract_name": "ea.governed_spatial_render_design_review_intake.v1",
        "petition_id": "ea-governed-spatial-render-contract-v1",
        "status": "revise_blocked",
        "review_applicable": True,
        "implementation_authorized": False,
        "provider_execution_authorized": False,
        "quota_authorized": False,
        "product_bridge_registration_authorized": False,
        "live_change_authorized": False,
        "independent_re_review_required": True,
        "launch_recommendation": "no",
    }
    for field, expected in expected_scalars.items():
        if receipt.get(field) != expected:
            issues.append(f"design_review_field_invalid:{field}")

    decision = (
        dict(receipt.get("decision"))
        if isinstance(receipt.get("decision"), Mapping)
        else {}
    )
    expected_decision = {
        "path": str(DEFAULT_DECISION),
        "sha256": EXPECTED_DECISION_SHA256,
        "disposition": "revise",
        "implementation_state": "blocked",
        "independent_review": True,
    }
    for field, expected in expected_decision.items():
        if decision.get(field) != expected:
            issues.append(f"design_review_decision_invalid:{field}")

    expected_evidence = [
        {"path": str(DEFAULT_PETITION), "sha256": EXPECTED_PETITION_SHA256},
        {"path": str(DEFAULT_HANDOFF), "sha256": EXPECTED_HANDOFF_SHA256},
    ]
    if receipt.get("evidence_snapshot") != expected_evidence:
        issues.append("design_review_evidence_snapshot_invalid")
    expected_canon = [
        {"path": str(CHUMMER_DESIGN_ROOT / path), "sha256": digest}
        for path, digest in EXPECTED_CANONICAL_INPUTS.items()
    ]
    if receipt.get("canonical_snapshot") != expected_canon:
        issues.append("design_review_canonical_snapshot_invalid")
    if receipt.get("required_amendments") != list(REQUIRED_AMENDMENTS):
        issues.append("design_review_required_amendments_invalid")

    authority = (
        dict(receipt.get("authority_contract"))
        if isinstance(receipt.get("authority_contract"), Mapping)
        else {}
    )
    expected_authority = {
        "durable_chummer_contract_owner": "chummer6-media-factory:Chummer.Media.Contracts",
        "chummer_product_bridge_owner": "chummer6-hub",
        "propertyquarry_bridge_owner": "propertyquarry_canon_decision_required",
        "combat_overlay_boundary": (
            "private_chummer_recipe_only:immutable_truth_refs:no_mechanics:no_propertyquarry_input"
        ),
        "current_quota_authority": "none_under_unregistered_proposal",
        "future_private_execution_receipt_owner": (
            "chummer6-media-factory_subject_to_canonical_amendment"
        ),
        "privacy_retention": "incomplete_numeric_policy_and_deletion_cascade_required",
        "promotion_gates": (
            "canonical_amendments:independent_re_review:artifact_gates:48h_canary:explicit_promotion"
        ),
    }
    if authority != expected_authority:
        issues.append("design_review_authority_contract_invalid")

    if verify_bound_files:
        try:
            _validate_bound_sources()
        except (OSError, UnicodeError, ValueError) as exc:
            reason, fingerprint = _redacted_validation_failure(exc)
            issues.append(reason)
            validation_failure_fingerprints.append(
                {"reason": reason, "fingerprint": fingerprint}
            )
    return {
        "contract_name": "ea.governed_spatial_render_design_review_verification.v1",
        "status": "pass" if not issues else "fail",
        "issues": list(dict.fromkeys(issues)),
        "validation_failure_fingerprints": validation_failure_fingerprints,
        "decision_sha256": decision.get("sha256", ""),
    }


def verify_design_review_receipt(path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "contract_name": "ea.governed_spatial_render_design_review_verification.v1",
            "status": "fail",
            "issues": [f"design_review_receipt_unreadable:{type(exc).__name__}"],
            "path": str(path),
        }
    result = verify_design_review_receipt_payload(payload)
    result["path"] = str(path)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize the hash-bound independent governed spatial-render design review."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    parser.add_argument("--verify", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.verify:
        result = verify_design_review_receipt(args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    receipt = build_design_review_receipt(
        output_path=args.output,
        observed_at=_parse_time(args.observed_at),
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "decision_sha256": receipt["decision"]["sha256"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
