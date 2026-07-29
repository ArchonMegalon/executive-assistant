from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

from app.services.proactive_ooda_approval_outcomes import (
    attach_proactive_ooda_approval_bundle_snapshot,
    attach_proactive_ooda_approval_teable_sync,
    default_proactive_ooda_artifact_dir,
    default_proactive_ooda_approval_outcome_path,
    record_proactive_ooda_approval_outcome,
)
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle
from app.services.proactive_ooda_runtime_artifacts import latest_run_receipts
from app.services.proactive_ooda_runtime_artifacts import choose_stage_and_safe_work_for_run_receipt
from app.services.proactive_ooda_runtime_artifacts import resolve_runtime_artifact_paths
from app.services.proactive_ooda_teable_sync import (
    sync_proactive_ooda_approval_outcome_to_teable,
    teable_sync_enabled,
)


def default_proactive_ooda_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        try:
            if (candidate / "scripts" / "run_proactive_ooda.py").is_file():
                return candidate
        except OSError:
            # Optional image-layout candidates can be intentionally private to
            # their owning user. Keep walking toward the canonical /app root
            # instead of failing before a readable runtime marker is reached.
            continue
    return current.parents[3]


def default_proactive_ooda_gold_acceptance_path(*, root: Path) -> Path:
    preferred = root / ".codex-studio" / "published"
    return default_proactive_ooda_artifact_dir(root=root, preferred=preferred) / "ea_proactive_ooda_gold_acceptance.generated.json"


def default_proactive_ooda_operator_status_path(*, root: Path) -> Path:
    preferred = root / ".codex-studio" / "published"
    return default_proactive_ooda_artifact_dir(root=root, preferred=preferred) / "ea_proactive_ooda_operator_status.generated.json"


def finalize_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    packet_ref: str,
    staged_artifact_ref: str,
    source_kind: str = "unknown",
    recorded_at: str | None = None,
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    approval_outcome_path: str | Path = "",
    operator_status_path: str | Path = "",
    gold_acceptance_path: str | Path = "",
    database_url: str | None = None,
    runtime_artifact_loader: Callable[..., dict[str, Any]] | None = None,
    teable_sync_decider: Callable[[], bool] | None = None,
    teable_syncer: Callable[..., dict[str, Any]] | None = None,
    operator_status_materializer: Callable[..., Any] | None = None,
    gold_materializer: Callable[..., None] | None = None,
) -> dict[str, Any]:
    resolved_root = root or default_proactive_ooda_root()
    resolved_approval_outcome_path = default_proactive_ooda_approval_outcome_path(
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
    )
    if str(approval_outcome_path or "").strip():
        candidate = Path(str(approval_outcome_path))
        resolved_approval_outcome_path = candidate if candidate.is_absolute() else resolved_root / candidate
    resolved_operator_status_path = default_proactive_ooda_operator_status_path(root=resolved_root)
    if str(operator_status_path or "").strip():
        candidate = Path(str(operator_status_path))
        resolved_operator_status_path = candidate if candidate.is_absolute() else resolved_root / candidate
    resolved_gold_acceptance_path = default_proactive_ooda_gold_acceptance_path(root=resolved_root)
    if str(gold_acceptance_path or "").strip():
        candidate = Path(str(gold_acceptance_path))
        resolved_gold_acceptance_path = candidate if candidate.is_absolute() else resolved_root / candidate

    approval_outcome = record_proactive_ooda_approval_outcome(
        principal_id=principal_id,
        outcome=outcome,
        evidence=evidence,
        actor=actor,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        source_kind=source_kind,
        recorded_at=recorded_at,
        output_path=resolved_approval_outcome_path,
        database_url=database_url,
    )
    bundle_loader = runtime_artifact_loader or load_runtime_artifact_bundle
    bundle = bundle_loader(
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    bundle = _bundle_for_requested_artifacts(
        bundle=bundle,
        bundle_loader=bundle_loader,
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
    )
    approval_outcome = attach_proactive_ooda_approval_bundle_snapshot(
        approval_outcome=approval_outcome,
        output_path=resolved_approval_outcome_path,
        bundle=bundle,
        recorded_at=str(approval_outcome.get("recorded_at") or recorded_at or "").strip(),
    )
    effective_run_receipt_path = _path_or_default(bundle.get("run_receipt_path"), root=resolved_root, fallback=receipt_path)
    effective_stage_packet_dir = _path_or_default(bundle.get("stage_packet_dir"), root=resolved_root, fallback=stage_packet_dir)
    effective_safe_work_result_dir = _path_or_default(bundle.get("safe_work_result_dir"), root=resolved_root, fallback=safe_work_result_dir)

    operator_materializer = operator_status_materializer or _materialize_operator_status
    operator_status_materialization = {
        "status": "materialized",
        "error": "",
        "path": resolved_operator_status_path,
    }
    try:
        operator_materializer(
            output_path=resolved_operator_status_path,
            live_receipt_path=effective_run_receipt_path,
        )
    except Exception as exc:
        operator_status_materialization = {
            "status": "failed",
            "error": _materialization_error(exc),
            "path": resolved_operator_status_path,
        }

    teable_sync: dict[str, Any] = {
        "status": "disabled",
        "sync_attempted": False,
        "blocked_reason": "",
    }
    sync_enabled = teable_sync_decider or teable_sync_enabled
    if sync_enabled():
        syncer = teable_syncer or sync_proactive_ooda_approval_outcome_to_teable
        teable_sync = syncer(
            receipt=dict(bundle.get("run_receipt") or {}),
            safe_work_result=dict(bundle.get("safe_work_result") or {}),
            approval_outcome=approval_outcome,
        )
        approval_outcome = attach_proactive_ooda_approval_teable_sync(
            approval_outcome=approval_outcome,
            output_path=resolved_approval_outcome_path,
            teable_sync=teable_sync,
        )

    materializer = gold_materializer or _materialize_gold_acceptance
    gold_acceptance_materialization = {
        "status": "skipped",
        "error": "operator_status_materialization_failed",
        "path": resolved_gold_acceptance_path,
    }
    if operator_status_materialization["status"] == "materialized":
        gold_acceptance_materialization = {
            "status": "materialized",
            "error": "",
            "path": resolved_gold_acceptance_path,
        }
        try:
            materializer(
                output_path=resolved_gold_acceptance_path,
                operator_status_path=resolved_operator_status_path,
                run_receipt_path=effective_run_receipt_path,
                stage_packet_dir=effective_stage_packet_dir,
                safe_work_result_dir=effective_safe_work_result_dir,
                approval_outcome_path=resolved_approval_outcome_path,
            )
        except Exception as exc:
            gold_acceptance_materialization = {
                "status": "failed",
                "error": _materialization_error(exc),
                "path": resolved_gold_acceptance_path,
            }
    return {
        "approval_outcome": approval_outcome,
        "approval_outcome_path": resolved_approval_outcome_path,
        "operator_status_path": resolved_operator_status_path,
        "gold_acceptance_path": resolved_gold_acceptance_path,
        "operator_status_materialization": operator_status_materialization,
        "gold_acceptance_materialization": gold_acceptance_materialization,
        "teable_sync": teable_sync,
        "state_path": _resolve_optional_path(resolved_root, state_path),
        "receipt_path": _resolve_optional_path(resolved_root, receipt_path),
    }


def _materialize_operator_status(*, output_path: Path, live_receipt_path: Path | None = None) -> None:
    materializer = _load_script_symbol(
        module_name="materialize_proactive_ooda_operator_status",
        attribute="build_proactive_ooda_operator_status",
    )
    materializer(
        output_path=output_path,
        live_receipt_path=live_receipt_path,
    )


def _materialize_gold_acceptance(
    *,
    output_path: Path,
    operator_status_path: Path,
    run_receipt_path: Path | None,
    stage_packet_dir: Path | None,
    safe_work_result_dir: Path | None,
    approval_outcome_path: Path,
) -> None:
    materializer = _load_script_symbol(
        module_name="materialize_proactive_ooda_gold_acceptance",
        attribute="materialize_proactive_ooda_gold_acceptance",
    )
    materializer(
        output_path=output_path,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        approval_outcome_path=approval_outcome_path,
    )


def _load_script_symbol(*, module_name: str, attribute: str) -> Any:
    repo_root = default_proactive_ooda_root()
    original_sys_path0 = sys.path[0] if sys.path else ""
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
        original_sys_path0 = str(repo_root)

    try:
        sys.path[0] = str(repo_root)
        try:
            module = __import__(f"scripts.{module_name}", fromlist=[attribute])
            symbol = getattr(module, attribute)
            if callable(symbol):
                return symbol
            raise ModuleNotFoundError(f"scripts.{module_name}.{attribute}")
        except ModuleNotFoundError as exc:
            if str(exc.name) != f"scripts.{module_name}":
                raise
    finally:
        if sys.path:
            sys.path[0] = original_sys_path0

    fallback_root = default_proactive_ooda_root() / "scripts"
    target = fallback_root / f"{module_name}.py"
    if not target.is_file():
        raise ModuleNotFoundError(f"scripts.{module_name}")
    if str(default_proactive_ooda_root()) not in sys.path:
        sys.path.insert(0, str(default_proactive_ooda_root()))

    module_spec = importlib.util.spec_from_file_location(module_name, str(target))
    if module_spec is None or module_spec.loader is None:
        raise ModuleNotFoundError(f"scripts.{module_name}")

    loaded = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(loaded)
    if not hasattr(loaded, attribute):
        raise ModuleNotFoundError(f"scripts.{module_name}.{attribute}")
    symbol = getattr(loaded, attribute)
    if callable(symbol):
        return symbol
    raise ModuleNotFoundError(f"scripts.{module_name}.{attribute}")


def _resolve_optional_path(root: Path, value: str | Path) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    path = Path(normalized)
    return path if path.is_absolute() else root / path


def _path_or_default(value: Any, *, root: Path, fallback: str | Path) -> Path | None:
    if isinstance(value, Path):
        return value
    resolved = _resolve_optional_path(root, fallback)
    return resolved


def _materialization_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}:{str(exc or '').strip() or 'materialization_failed'}"


def _bundle_for_requested_artifacts(
    *,
    bundle: dict[str, Any],
    bundle_loader: Callable[..., dict[str, Any]],
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
    packet_ref: str,
    staged_artifact_ref: str,
) -> dict[str, Any]:
    normalized_packet_ref = str(packet_ref or "").strip()
    normalized_artifact_ref = str(staged_artifact_ref or "").strip()
    if not normalized_packet_ref or not normalized_artifact_ref:
        return dict(bundle or {})
    current_bundle = dict(bundle or {})
    if _bundle_matches_requested_artifacts(
        current_bundle,
        packet_ref=normalized_packet_ref,
        staged_artifact_ref=normalized_artifact_ref,
    ):
        return current_bundle
    resolved = _matching_runtime_bundle_for_artifact_refs(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        packet_ref=normalized_packet_ref,
        staged_artifact_ref=normalized_artifact_ref,
    )
    if resolved:
        return resolved
    fallback_bundle = bundle_loader(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    fallback_bundle = dict(fallback_bundle or {})
    if _bundle_matches_requested_artifacts(
        fallback_bundle,
        packet_ref=normalized_packet_ref,
        staged_artifact_ref=normalized_artifact_ref,
    ):
        return fallback_bundle
    return current_bundle


def _bundle_matches_requested_artifacts(
    bundle: dict[str, Any] | None,
    *,
    packet_ref: str,
    staged_artifact_ref: str,
) -> bool:
    current_bundle = dict(bundle or {})
    stage_packet = dict(current_bundle.get("stage_packet") or {})
    safe_work_result = dict(current_bundle.get("safe_work_result") or {})
    return bool(
        str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip() == packet_ref
        and str(safe_work_result.get("result_ref") or "").strip() == staged_artifact_ref
    )


def _matching_runtime_bundle_for_artifact_refs(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
    packet_ref: str,
    staged_artifact_ref: str,
) -> dict[str, Any]:
    paths = resolve_runtime_artifact_paths(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    run_receipt_dir = paths["run_receipt_dir"]
    stage_dir = paths["stage_packet_dir"]
    safe_dir = paths["safe_work_result_dir"]
    if not (run_receipt_dir.is_dir() and stage_dir.is_dir() and safe_dir.is_dir()):
        return {}
    for run_path, run_receipt, _mtime in latest_run_receipts(run_receipt_dir):
        selected = choose_stage_and_safe_work_for_run_receipt(
            stage_packet_dir=stage_dir,
            safe_work_result_dir=safe_dir,
            run_receipt=run_receipt,
        )
        if selected is None:
            continue
        stage_path, stage_packet, safe_path, safe_work_result = selected
        if (
            str(dict(stage_packet).get("packet_ref") or dict(stage_packet).get("packet_id") or "").strip()
            != packet_ref
        ):
            continue
        if str(dict(safe_work_result).get("result_ref") or "").strip() != staged_artifact_ref:
            continue
        return {
            "run_receipt_path": run_path,
            "run_receipt": dict(run_receipt or {}),
            "stage_packet_dir": stage_dir,
            "safe_work_result_dir": safe_dir,
            "approval_outcome_path": paths["approval_outcome_path"],
            "approval_callback_dir": paths["approval_callback_dir"],
            "stage_packet_path": stage_path,
            "stage_packet": dict(stage_packet or {}),
            "safe_work_result_path": safe_path,
            "safe_work_result": dict(safe_work_result or {}),
            "approval_outcome": {},
        }
    return {}
