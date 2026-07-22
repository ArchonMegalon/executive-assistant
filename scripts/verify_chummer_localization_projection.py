#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


CHUMMER_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
CHUMMER_UI_ROOT = Path("/docker/chummercomplete/chummer6-ui")

DEFAULT_MATRIX = CHUMMER_DESIGN_ROOT / "LOCALIZATION_PARITY_MATRIX.yaml"
DEFAULT_SYSTEM = CHUMMER_DESIGN_ROOT / "LOCALIZATION_AND_LANGUAGE_SYSTEM.md"
DEFAULT_BLOCKERS = CHUMMER_DESIGN_ROOT / "GROUP_BLOCKERS.md"
DEFAULT_GOLD_GRAPH = CHUMMER_DESIGN_ROOT / "FINAL_GOLD_GRAPH.generated.json"
DEFAULT_WEEKLY_PULSE = CHUMMER_DESIGN_ROOT / "WEEKLY_PRODUCT_PULSE.generated.json"
DEFAULT_UI_RECEIPT = CHUMMER_UI_ROOT / ".codex-studio/published/UI_LOCALIZATION_RELEASE_GATE.generated.json"

CONTRACT_NAME = "ea.chummer_localization_projection.v1"
PASS_STATUS = "pass_consistent"
BLOCKED_CONTRADICTORY_STATUS = "blocked_contradictory_evidence"
BLOCKED_MISSING_STATUS = "blocked_missing_evidence"
DEFAULT_MAX_PROOF_AGE_HOURS = 168.0

SYSTEM_REQUIRED_MARKERS = {
    "acceptance_gate_heading": "## acceptance gates",
    "companion_card_smoke": "companion cards",
    "voice_opt_in_fallback_smoke": "voice-opt-in fallback smoke",
    "localized_companion_runtime": "localized companion runtime copy",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_locale(value: object) -> str:
    return str(value or "").strip().replace("_", "-").lower()


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _content_timestamp(key: str, payload: object, text: str) -> str | None:
    if key == "blocker_register":
        match = re.search(r"(?mi)^Last reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$", text)
        return match.group(1) if match else None
    if isinstance(payload, dict):
        for field in ("generated_at_utc", "generated_at", "last_reviewed", "as_of"):
            value = str(payload.get(field) or "").strip()
            if value:
                return value
    return None


def _load_bound_input(key: str, path: Path, kind: str) -> tuple[dict[str, Any], object | None, str]:
    requested_path = path.expanduser()
    binding: dict[str, Any] = {
        "key": key,
        "path": requested_path.as_posix(),
        "resolved_path": requested_path.resolve(strict=False).as_posix(),
        "exists": requested_path.is_file(),
        "read_status": "missing",
    }
    if not requested_path.is_file():
        return binding, None, ""

    try:
        raw = requested_path.read_bytes()
        stat = requested_path.stat()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError):
        binding["read_status"] = "invalid"
        return binding, None, ""

    binding.update(
        {
            "sha256": _sha256_bytes(raw),
            "size_bytes": len(raw),
            "mtime_utc": _format_utc(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
        }
    )

    try:
        if kind == "json":
            payload: object = json.loads(text)
        elif kind == "yaml":
            payload = yaml.safe_load(text)
        else:
            payload = text
    except (json.JSONDecodeError, yaml.YAMLError):
        binding["read_status"] = "invalid"
        return binding, None, text

    if kind in {"json", "yaml"} and not isinstance(payload, dict):
        binding["read_status"] = "invalid"
        return binding, None, text

    binding["read_status"] = "bound"
    binding["content_timestamp"] = _content_timestamp(key, payload, text)
    return binding, payload, text


def _finding(code: str, detail: str, *, owner: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "owner": owner}


def _blk_009_state(text: str) -> dict[str, Any]:
    match = re.search(r"(?ms)^### BLK-009\b.*?(?=^### |^## |\Z)", text)
    if not match:
        return {"present": False, "declared_status": "unknown", "cleared_at": None}
    section = match.group(0)
    cleared = re.search(r"(?mi)^Cleared\s+(\d{4}-\d{2}-\d{2})\.\s*$", section)
    return {
        "present": True,
        "declared_status": "cleared" if cleared else "active_or_unclassified",
        "cleared_at": cleared.group(1) if cleared else None,
        "section_sha256": _sha256_bytes(section.encode("utf-8")),
    }


def _gold_localization_state(payload: dict[str, Any]) -> dict[str, Any]:
    audit = _dict(payload.get("completion_audit"))
    requirements = _items(audit.get("requirements"))
    requirement = next(
        (
            _dict(item)
            for item in requirements
            if isinstance(item, dict) and str(item.get("id") or "").strip() == "localization"
        ),
        {},
    )
    proof_inputs = _items(payload.get("proof_inputs"))
    proof = next(
        (
            _dict(item)
            for item in proof_inputs
            if isinstance(item, dict)
            and str(item.get("kind") or "").strip() == "ui_localization_release_gate"
        ),
        {},
    )
    return {
        "graph_status": str(payload.get("status") or "").strip(),
        "verdict": str(payload.get("verdict") or "").strip(),
        "requirement_status": str(requirement.get("status") or "").strip(),
        "missing_or_failed_proof_kinds": _strings(requirement.get("missing_or_failed_proof_kinds")),
        "proof_status": str(proof.get("status") or "").strip(),
        "proof_path": str(proof.get("path") or "").strip(),
        "proof_generated_at": str(proof.get("generated_at") or "").strip(),
    }


def _weekly_state(payload: dict[str, Any]) -> dict[str, Any]:
    release_health = _dict(payload.get("release_health"))
    flagship_readiness = _dict(payload.get("flagship_readiness"))
    return {
        "contract_name": str(payload.get("contract_name") or "").strip(),
        "generated_at": str(payload.get("generated_at") or "").strip(),
        "as_of": str(payload.get("as_of") or "").strip(),
        "release_health_state": str(release_health.get("state") or "").strip(),
        "flagship_readiness_state": str(flagship_readiness.get("state") or "").strip(),
        "flagship_proof_status": str(flagship_readiness.get("proof_status") or "").strip(),
    }


def build_projection(
    *,
    matrix_path: Path = DEFAULT_MATRIX,
    system_path: Path = DEFAULT_SYSTEM,
    blockers_path: Path = DEFAULT_BLOCKERS,
    gold_graph_path: Path = DEFAULT_GOLD_GRAPH,
    weekly_pulse_path: Path = DEFAULT_WEEKLY_PULSE,
    ui_receipt_path: Path = DEFAULT_UI_RECEIPT,
    observed_at: datetime | None = None,
    max_proof_age_hours: float = DEFAULT_MAX_PROOF_AGE_HOURS,
) -> dict[str, Any]:
    observed = (observed_at or _utc_now()).astimezone(timezone.utc)
    source_specs = (
        ("localization_matrix", matrix_path, "yaml"),
        ("localization_system", system_path, "text"),
        ("blocker_register", blockers_path, "text"),
        ("final_gold_graph", gold_graph_path, "json"),
        ("weekly_product_pulse", weekly_pulse_path, "json"),
        ("ui_localization_receipt", ui_receipt_path, "json"),
    )
    bindings: dict[str, dict[str, Any]] = {}
    payloads: dict[str, object | None] = {}
    texts: dict[str, str] = {}
    findings: list[dict[str, str]] = []

    for key, path, kind in source_specs:
        binding, payload, text = _load_bound_input(key, path, kind)
        bindings[key] = binding
        payloads[key] = payload
        texts[key] = text
        if binding["read_status"] != "bound":
            findings.append(
                _finding(
                    f"input_{binding['read_status']}:{key}",
                    f"Required input {key} is {binding['read_status']}: {path}",
                    owner="ea",
                )
            )

    missing_or_invalid = any(binding["read_status"] != "bound" for binding in bindings.values())
    matrix = _dict(payloads.get("localization_matrix"))
    system_text = texts.get("localization_system", "")
    blocker_text = texts.get("blocker_register", "")
    gold = _dict(payloads.get("final_gold_graph"))
    weekly = _dict(payloads.get("weekly_product_pulse"))
    proof = _dict(payloads.get("ui_localization_receipt"))

    canonical_locales = [_normalize_locale(item) for item in _strings(matrix.get("shipping_locales"))]
    canonical_domains = [
        str(item.get("id") or "").strip()
        for item in _items(matrix.get("domains"))
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    canonical_gates = _strings(matrix.get("acceptance_gates"))
    canonical_locale_domains: dict[str, list[str]] = {}
    for row in _items(matrix.get("locale_matrix")):
        if not isinstance(row, dict):
            continue
        locale = _normalize_locale(row.get("locale"))
        domains = _dict(row.get("domains"))
        canonical_locale_domains[locale] = sorted(
            str(key) for key, value in domains.items() if str(value).strip() == "release_required"
        )

    if not canonical_locales:
        findings.append(_finding("canonical_shipping_locales_missing", "Matrix has no shipping locales.", owner="chummer6-design"))
    if not canonical_domains:
        findings.append(_finding("canonical_domains_missing", "Matrix has no localization domains.", owner="chummer6-design"))
    if not canonical_gates:
        findings.append(_finding("canonical_acceptance_gates_missing", "Matrix has no acceptance gates.", owner="chummer6-design"))
    if set(canonical_locale_domains) != set(canonical_locales):
        findings.append(
            _finding(
                "canonical_locale_matrix_incomplete",
                "Locale matrix rows do not exactly cover the shipping locale set.",
                owner="chummer6-design",
            )
        )

    folded_system = system_text.casefold()
    for marker_key, marker in SYSTEM_REQUIRED_MARKERS.items():
        if marker.casefold() not in folded_system:
            findings.append(
                _finding(
                    f"localization_system_marker_missing:{marker_key}",
                    f"Localization system is missing required marker: {marker}",
                    owner="chummer6-design",
                )
            )

    proof_status = str(proof.get("status") or "").strip().lower()
    proof_locales = {_normalize_locale(item) for item in _strings(proof.get("shipping_locales"))}
    proof_domains = _dict(proof.get("domain_coverage"))
    proof_gates = set(_strings(proof.get("acceptance_gates")))
    missing_locales = sorted(set(canonical_locales) - proof_locales)
    missing_domains = sorted(set(canonical_domains) - set(proof_domains))
    nonpassing_domains = sorted(
        domain
        for domain in canonical_domains
        if domain in proof_domains and str(proof_domains.get(domain) or "").strip().lower() != "pass"
    )
    missing_gates = sorted(set(canonical_gates) - proof_gates)

    if proof_status != "pass":
        findings.append(
            _finding(
                "ui_receipt_status_not_pass",
                f"UI localization receipt status is {proof_status or '<missing>'}.",
                owner="chummer6-ui",
            )
        )
    if missing_locales:
        findings.append(
            _finding(
                "ui_receipt_shipping_locales_missing",
                "Missing shipping locales: " + ", ".join(missing_locales),
                owner="chummer6-ui",
            )
        )
    if missing_domains:
        findings.append(
            _finding(
                "ui_receipt_domains_missing",
                "Missing localization domains: " + ", ".join(missing_domains),
                owner="chummer6-ui",
            )
        )
    if nonpassing_domains:
        findings.append(
            _finding(
                "ui_receipt_domains_not_pass",
                "Non-passing localization domains: " + ", ".join(nonpassing_domains),
                owner="chummer6-ui",
            )
        )
    if missing_gates:
        findings.append(
            _finding(
                "ui_receipt_acceptance_gates_missing",
                "Missing acceptance gates: " + ", ".join(missing_gates),
                owner="chummer6-ui",
            )
        )

    if str(proof.get("explicit_fallback_runtime") or "").strip().lower() != "pass":
        findings.append(
            _finding(
                "ui_receipt_explicit_fallback_not_pass",
                "Explicit fallback runtime is not passing.",
                owner="chummer6-ui",
            )
        )
    if str(_dict(proof.get("signoff_smoke_runner")).get("status") or "").strip().lower() != "pass":
        findings.append(
            _finding(
                "ui_receipt_signoff_smoke_not_pass",
                "Localization signoff smoke runner is not passing.",
                owner="chummer6-ui",
            )
        )
    if proof.get("blocking_findings") not in ([], None):
        findings.append(_finding("ui_receipt_has_blocking_findings", "UI receipt reports blocking findings.", owner="chummer6-ui"))
    if proof.get("translation_backlog_findings") not in ([], None):
        findings.append(_finding("ui_receipt_has_translation_backlog", "UI receipt reports translation backlog.", owner="chummer6-ui"))

    locale_summaries = {
        _normalize_locale(item.get("locale")): item
        for item in _items(proof.get("locale_summary"))
        if isinstance(item, dict) and _normalize_locale(item.get("locale"))
    }
    locale_coverage = {
        _normalize_locale(locale): _dict(value)
        for locale, value in _dict(proof.get("locale_domain_coverage")).items()
    }
    for locale in canonical_locales:
        summary = _dict(locale_summaries.get(locale))
        if not summary:
            findings.append(
                _finding(
                    f"ui_receipt_locale_summary_missing:{locale}",
                    f"Locale summary is missing for {locale}.",
                    owner="chummer6-ui",
                )
            )
        else:
            if summary.get("untranslated_key_count") != 0:
                findings.append(
                    _finding(
                        f"ui_receipt_untranslated_keys:{locale}",
                        f"Locale {locale} does not report zero untranslated keys.",
                        owner="chummer6-ui",
                    )
                )
            if _strings(summary.get("missing_release_seed_keys")):
                findings.append(
                    _finding(
                        f"ui_receipt_release_seed_keys_missing:{locale}",
                        f"Locale {locale} is missing release seed keys.",
                        owner="chummer6-ui",
                    )
                )
            minimum = summary.get("minimum_override_count")
            override_count = summary.get("override_count")
            if not isinstance(minimum, int) or not isinstance(override_count, int) or override_count < minimum:
                findings.append(
                    _finding(
                        f"ui_receipt_override_floor_not_met:{locale}",
                        f"Locale {locale} does not meet its override floor.",
                        owner="chummer6-ui",
                    )
                )
            if summary.get("legacy_xml_present") is not True or summary.get("legacy_data_xml_present") is not True:
                findings.append(
                    _finding(
                        f"ui_receipt_legacy_corpus_missing:{locale}",
                        f"Locale {locale} does not bind both legacy language corpora.",
                        owner="chummer6-ui",
                    )
                )

        coverage = locale_coverage.get(locale, {})
        missing_locale_domains = sorted(
            domain
            for domain in canonical_locale_domains.get(locale, canonical_domains)
            if str(coverage.get(domain) or "").strip().lower() != "pass"
        )
        if missing_locale_domains:
            findings.append(
                _finding(
                    f"ui_receipt_locale_domains_not_pass:{locale}",
                    f"Locale {locale} lacks passing domains: " + ", ".join(missing_locale_domains),
                    owner="chummer6-ui",
                )
            )

    proof_source_head = str(proof.get("source_git_head") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", proof_source_head):
        findings.append(
            _finding(
                "ui_receipt_source_git_head_missing_or_invalid",
                "UI receipt is not bound to a 40-character source Git head.",
                owner="chummer6-ui",
            )
        )
    expected_matrix_sha = str(bindings.get("localization_matrix", {}).get("sha256") or "")
    expected_system_sha = str(bindings.get("localization_system", {}).get("sha256") or "")
    if str(proof.get("localization_matrix_sha256") or "").strip() != expected_matrix_sha:
        findings.append(
            _finding(
                "ui_receipt_matrix_binding_missing_or_mismatch",
                "UI receipt is not bound to the observed canonical localization matrix hash.",
                owner="chummer6-ui",
            )
        )
    if str(proof.get("localization_system_sha256") or "").strip() != expected_system_sha:
        findings.append(
            _finding(
                "ui_receipt_system_binding_missing_or_mismatch",
                "UI receipt is not bound to the observed canonical localization system hash.",
                owner="chummer6-ui",
            )
        )

    proof_generated_at_text = str(proof.get("generated_at") or "").strip()
    proof_generated_at = _parse_timestamp(proof_generated_at_text)
    proof_age_seconds: int | None = None
    if proof_generated_at is None:
        findings.append(
            _finding(
                "ui_receipt_generated_at_missing_or_invalid",
                "UI receipt generated_at is missing or invalid.",
                owner="chummer6-ui",
            )
        )
    else:
        proof_age_seconds = int((observed - proof_generated_at).total_seconds())
        if proof_age_seconds < -300:
            findings.append(_finding("ui_receipt_generated_in_future", "UI receipt timestamp is in the future.", owner="chummer6-ui"))
        elif proof_age_seconds > int(max_proof_age_hours * 3600):
            findings.append(
                _finding(
                    "ui_receipt_stale",
                    f"UI receipt is {proof_age_seconds}s old; maximum is {int(max_proof_age_hours * 3600)}s.",
                    owner="chummer6-ui",
                )
            )

    proof_issue_codes = [item["code"] for item in findings if item["owner"] in {"chummer6-design", "chummer6-ui"}]
    blocker_state = _blk_009_state(blocker_text)
    gold_state = _gold_localization_state(gold)
    weekly_state = _weekly_state(weekly)

    if not blocker_state["present"]:
        findings.append(_finding("blk_009_missing", "BLK-009 is absent from the canonical blocker register.", owner="chummer6-design"))
    if blocker_state["declared_status"] == "cleared" and proof_issue_codes:
        findings.append(
            _finding(
                "blk_009_clearance_conflicts_with_structural_proof",
                "BLK-009 is declared cleared while current structural localization proof is incomplete.",
                owner="chummer6-design",
            )
        )

    if gold_state["requirement_status"] != "pass" or gold_state["proof_status"] != "pass":
        findings.append(
            _finding(
                "gold_graph_localization_not_pass",
                "Final gold graph does not report passing localization requirement and proof input.",
                owner="chummer6-design",
            )
        )
    if gold_state["requirement_status"] == "pass" and proof_issue_codes:
        findings.append(
            _finding(
                "gold_graph_localization_pass_conflicts_with_structural_proof",
                "Final gold graph reports localization pass while the bound proof misses canonical requirements.",
                owner="chummer6-design",
            )
        )
    if gold_state["proof_generated_at"] and gold_state["proof_generated_at"] != proof_generated_at_text:
        findings.append(
            _finding(
                "gold_graph_ui_proof_timestamp_mismatch",
                "Gold graph localization proof timestamp does not match the bound UI receipt.",
                owner="chummer6-design",
            )
        )

    if weekly_state["contract_name"] != "chummer.weekly_product_pulse":
        findings.append(
            _finding(
                "weekly_pulse_contract_mismatch",
                "Canonical weekly pulse input is not chummer.weekly_product_pulse; possible EA/Chummer path collision.",
                owner="ea",
            )
        )
    if _parse_timestamp(weekly_state["generated_at"]) is None:
        findings.append(_finding("weekly_pulse_generated_at_missing_or_invalid", "Weekly pulse timestamp is invalid.", owner="chummer6-design"))

    if missing_or_invalid:
        status = BLOCKED_MISSING_STATUS
    elif findings:
        status = BLOCKED_CONTRADICTORY_STATUS
    else:
        status = PASS_STATUS

    petition_required = status != PASS_STATUS
    return {
        "contract_name": CONTRACT_NAME,
        "contract_version": 1,
        "generated_by": "scripts/verify_chummer_localization_projection.py",
        "generated_at": _format_utc(observed),
        "status": status,
        "claim_scope": "non_authoritative_derived_localization_telemetry",
        "summary": (
            "Observed Chummer localization evidence is structurally consistent with canonical requirements."
            if status == PASS_STATUS
            else "Observed Chummer localization evidence cannot support a current localization-clearance claim."
        ),
        "canonical_release_authority": False,
        "blocker_mutation_allowed": False,
        "petition_required": petition_required,
        "boundary": {
            "ea_owns_canon": False,
            "ea_owns_chummer_release_readiness": False,
            "canonical_release_authority": False,
            "blocker_mutation_allowed": False,
            "allowed_action": "emit_derived_telemetry_and_design_petition",
        },
        "input_bindings": bindings,
        "canonical_requirements": {
            "shipping_locales": canonical_locales,
            "domains": canonical_domains,
            "acceptance_gates": canonical_gates,
            "locale_required_domains": canonical_locale_domains,
            "system_required_markers": SYSTEM_REQUIRED_MARKERS,
        },
        "observed_ui_proof": {
            "status": proof_status,
            "shipping_locales": sorted(proof_locales),
            "domains": {str(key): str(value) for key, value in proof_domains.items()},
            "acceptance_gates": sorted(proof_gates),
            "source_git_head": proof_source_head,
            "localization_matrix_sha256": str(proof.get("localization_matrix_sha256") or ""),
            "localization_system_sha256": str(proof.get("localization_system_sha256") or ""),
            "generated_at": proof_generated_at_text,
            "proof_age_seconds": proof_age_seconds,
            "max_proof_age_seconds": int(max_proof_age_hours * 3600),
        },
        "canonical_declarations": {
            "blk_009": blocker_state,
            "final_gold_graph_localization": gold_state,
            "weekly_product_pulse": weekly_state,
        },
        "blocking_findings": findings,
        "blocking_finding_codes": [item["code"] for item in findings],
        "next_action": (
            "No EA action required beyond continued monitoring."
            if not petition_required
            else "Petition chummer6-design and chummer6-ui to reconcile BLK-009, canonical companion requirements, and the bound UI proof; EA must not mutate canonical status."
        ),
        "next_action_owners": ["chummer6-design", "chummer6-ui"] if petition_required else [],
    }


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit fail-closed, non-authoritative EA telemetry for Chummer localization evidence."
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--system", type=Path, default=DEFAULT_SYSTEM)
    parser.add_argument("--blockers", type=Path, default=DEFAULT_BLOCKERS)
    parser.add_argument("--gold-graph", type=Path, default=DEFAULT_GOLD_GRAPH)
    parser.add_argument("--weekly-pulse", type=Path, default=DEFAULT_WEEKLY_PULSE)
    parser.add_argument("--ui-receipt", type=Path, default=DEFAULT_UI_RECEIPT)
    parser.add_argument("--max-proof-age-hours", type=float, default=DEFAULT_MAX_PROOF_AGE_HOURS)
    parser.add_argument("--observed-at", help="Optional ISO-8601 observation time for reproducible verification.")
    parser.add_argument("--output", type=Path, help="Optional private derived receipt path. Inputs are never mutated.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the complete derived receipt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not math.isfinite(args.max_proof_age_hours) or args.max_proof_age_hours <= 0:
        raise SystemExit("--max-proof-age-hours must be positive")
    observed_at = _parse_timestamp(args.observed_at) if args.observed_at else None
    if args.observed_at and observed_at is None:
        raise SystemExit("--observed-at must be a valid ISO-8601 timestamp")
    projection = build_projection(
        matrix_path=args.matrix,
        system_path=args.system,
        blockers_path=args.blockers,
        gold_graph_path=args.gold_graph,
        weekly_pulse_path=args.weekly_pulse,
        ui_receipt_path=args.ui_receipt,
        observed_at=observed_at,
        max_proof_age_hours=args.max_proof_age_hours,
    )
    if args.output:
        _write_receipt(args.output, projection)
    if args.pretty or not args.output:
        print(json.dumps(projection, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": projection["status"],
                    "output": args.output.as_posix(),
                    "petition_required": projection["petition_required"],
                },
                sort_keys=True,
            )
        )
    return 0 if projection["status"] == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
