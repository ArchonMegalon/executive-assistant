"""Explicit existing-credit approval after completed-only custody recovery.

Operator-only, stopped service operation. Never called by the worker. It keeps
every recovered reservation and journal; a provider balance cannot reset them.
The new allowance covers future requests, not an unknown pre-recovery backlog.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time

from scripts import origin_custody_recovery as recovery

pool, worker, writer = recovery.pool, recovery.worker, recovery.writer
_SCHEMA = "firstbook.recovered-credit-approval/v1"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _plan(value, now):
    fields = {"schema", "configuration", "expected_pool_sha256", "expected_recovery_sha256",
              "observed_at", "stopped_executor_id", "executor_stopped", "browsers_closed", "accounts"}
    if (not isinstance(value, dict) or set(value) != fields or value["schema"] != _SCHEMA
        or value["executor_stopped"] is not True or value["browsers_closed"] is not True
        or type(value["observed_at"]) is not int or not 0 <= now - value["observed_at"] <= 1800
        or any(not recovery._digest(value[key]) for key in
               ("expected_pool_sha256", "expected_recovery_sha256", "stopped_executor_id"))):
        raise ValueError("origin_recovered_allowance_observation_required")
    target = pool._configuration(value["configuration"], now)
    if target["schema"] != pool._SERVICE_SCHEMA or not isinstance(value["accounts"], list):
        raise ValueError("origin_recovered_allowance_standing_required")
    if len(value["accounts"]) != len(pool.accounts(target)):
        raise ValueError("origin_recovered_allowance_accounts_invalid")
    for account, observed in zip(pool.accounts(target), value["accounts"]):
        if (not isinstance(observed, dict) or set(observed) != {"profile_id", "account_sha256",
                "remaining_credits", "observed_at", "capture_sha256", "session", "closed"}
            or observed["profile_id"] != account["profile_id"]
            or observed["account_sha256"] != account["account_sha256"]
            or observed["closed"] is not True or not recovery._digest(observed["capture_sha256"])
            or type(observed["remaining_credits"]) is not int or not 0 <= observed["remaining_credits"] <= 1000
            or type(observed["observed_at"]) is not int or not 0 <= now - observed["observed_at"] <= 1800
            or not isinstance(observed["session"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", observed["session"])):
            raise ValueError("origin_recovered_allowance_accounts_invalid")
    return copy.deepcopy(value)


def approve(load_configuration, load_recovery_plan, load_plan, hub, output_root: Path, *, now=time.time):
    plan = _plan(load_plan(), now())
    target = plan["configuration"]
    original = pool._configuration(load_configuration(), now())
    historical = load_recovery_plan()
    # Validate historical shape at its observation time; this does not revive
    # its old executor observation. The fresh stopped-service plan above is required.
    historical = recovery._plan(historical, historical.get("observed_at", 0))
    if (original != historical["configuration"] or target["approval_id"] == original["approval_id"]
        or target["maximum_chapters_per_book"] != original["maximum_chapters_per_book"]
        or not set(original["excluded_book_refs"]) <= set(target["excluded_book_refs"])
        or [{k: v for k, v in a.items() if k != "maximum_new_books"} for a in pool.accounts(original)]
            != [{k: v for k, v in a.items() if k != "maximum_new_books"} for a in pool.accounts(target)]):
        raise ValueError("origin_recovered_allowance_scope_changed")
    with pool._lease(output_root) as path, pool.runtime.intake.cycle._lease(output_root):
        raw = worker._read_private(path, pool._LEDGER_LIMIT)
        if _hash(raw) != plan["expected_pool_sha256"]:
            raise RuntimeError("origin_recovered_allowance_snapshot_changed")
        state = pool._restore(path, original, now())
        if not state["new_book_admission_exhausted"] or len(state["books"]) != original["maximum_new_books"]:
            raise RuntimeError("origin_recovered_allowance_not_recovery_baseline")
        receipt_path = path.parent / "completed-custody-recovery.json"
        receipt_raw = worker._read_private(receipt_path, 4_000_000)
        receipt = worker._json(receipt_raw)
        if (_hash(receipt_raw) != plan["expected_recovery_sha256"]
            or receipt.get("plan_sha256") != recovery._sha(historical)
            or receipt.get("state") != "completed_history_reconstructed"
            or receipt.get("new_book_admission_allowed") is not False):
            raise RuntimeError("origin_recovered_allowance_recovery_mismatch")
        snapshots = {receipt_path: receipt_raw}
        recovered, histories = [], []
        for book, recorded in zip(historical["books"], receipt["books"]):
            # This transition accepts only the untouched completed-only recovery
            # baseline. A later session, even closed, needs separate review; it
            # cannot be used to excuse an uncertain pre-recovery operation.
            session_path = path.parent / ("owned-session-" + book["book_ref"] + ".json")
            if session_path.exists() or session_path.is_symlink():
                raise RuntimeError("origin_recovered_allowance_session_requires_review")
            enrolled, intake, records = recovery._history(hub, book, original, now())
            histories.append((enrolled, intake, records))
            recovered.append(enrolled)
            if (recorded["book_ref"] != book["book_ref"]
                or recorded["intake_sha256"] != recovery._sha(intake)
                or recorded["exact_receipts"] != [work["job"]["providerReceiptDigest"] for work, _ in records]):
                raise RuntimeError("origin_recovered_allowance_recovery_mismatch")
            intake_path = path.parent / ("intake-" + book["book_ref"] + ".json")
            snapshots[intake_path] = worker._read_private(intake_path, 4_000_000)
            if worker._json(snapshots[intake_path]) != intake:
                raise RuntimeError("origin_recovered_allowance_custody_changed")
            for work, record in records:
                item = writer._record_path(path.parent, record["binding"])
                snapshots[item] = worker._read_private(item, 4_000_000)
                if _hash(snapshots[item]) != work["job"]["providerReceiptDigest"]:
                    raise RuntimeError("origin_recovered_allowance_custody_changed")
        if recovered != state["books"] or len(receipt["books"]) != len(historical["books"]):
            raise RuntimeError("origin_recovered_allowance_reservations_changed")
        for account, observed in zip(pool.accounts(target), plan["accounts"]):
            reserved = sum(b["admission"]["account_sha256"] == account["account_sha256"] for b in recovered)
            if account["maximum_new_books"] != reserved + observed["remaining_credits"]:
                raise ValueError("origin_recovered_allowance_credit_snapshot_mismatch")
        if target["maximum_new_books"] <= len(recovered):
            raise ValueError("origin_recovered_allowance_no_new_credit")
        # Do not silently activate old unknown requests after losing old custody.
        # Only a complete, unchanged backlog covered by explicit exclusions is safe.
        pending = hub.pending_books()
        if (not isinstance(pending, list) or len(pending) >= 20
            or any(not isinstance(w, dict) or w.get("bookRef") not in target["excluded_book_refs"] for w in pending)):
            raise RuntimeError("origin_recovered_allowance_backlog_requires_review")
        if (any(recovery._history(hub, book, original, now()) != history
                for book, history in zip(historical["books"], histories))
            or hub.pending_books() != pending or load_configuration() != original
            or load_recovery_plan() != historical or _plan(load_plan(), now()) != plan
            or worker._read_private(path, pool._LEDGER_LIMIT) != raw
            or any(worker._read_private(p, 4_000_000) != data for p, data in snapshots.items())):
            raise RuntimeError("origin_recovered_allowance_snapshot_changed")
        transitioned = {**state, "configuration": target, "new_book_admission_exhausted": False}
        after = recovery._sha(transitioned)
        result = {"state": "recovered_service_allowance_approved", "reserved_books": len(recovered),
            "remaining_books": target["maximum_new_books"] - len(recovered),
            "pool_before_sha256": plan["expected_pool_sha256"], "pool_after_sha256": after,
            "provider_dispatch": False, "hub_mutation": False, "historical_ledger_restored": False,
            "publication_authorized": False}
        record = {**result, "operator_plan": plan, "previous_pool": state,
            "custody_sha256": {p.name: _hash(data) for p, data in snapshots.items()}}
        destination = path.parent / ("recovered-allowance-" + plan["expected_pool_sha256"] + "-" + after + ".json")
        prior = writer._load(destination)
        if prior is not None and prior != record:
            raise RuntimeError("origin_recovered_allowance_receipt_changed")
        if prior is None:
            writer._save(destination, record)
        # Atomic ledger commit last. Until explicitly deployed with the matching
        # new approval, both old and mismatched worker configurations fail closed.
        pool._save_pool(path, transitioned)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("configuration-path", "recovery-plan-path", "approval-plan-path", "token-file", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    args = parser.parse_args()
    load = lambda p: worker._json(worker._read_private(p, 128000))
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    print(json.dumps(approve(lambda: load(args.configuration_path), lambda: load(args.recovery_plan_path),
        lambda: load(args.approval_plan_path), hub, args.output_root)))


if __name__ == "__main__":
    main()
