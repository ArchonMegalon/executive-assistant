"""Explicit, read-only reconciliation of completed books after custody loss.

The operator must stop the old executor and verify/close its browser separately.
This command cannot recover uncertain jobs, mint credits, fabricate historical
sessions or relax the ordinary runtime. Only byte-exact completed writer records
whose hashes Hub already holds can become a new, labelled recovery baseline.
The resulting pool admits NO new books. Provider observations are operator-
verified private inputs, not authority inferred from a dashboard title or balance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time

from scripts import origin_book_pool as pool

worker = pool.worker
writer = worker.writer
intake = pool.runtime.intake
_SCHEMA = "firstbook.completed-custody-recovery/v1"


def _sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()


def _digest(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _plan(value: dict, now: float) -> dict:
    if (not isinstance(value, dict) or set(value) != {"schema", "configuration", "observed_at",
            "stopped_executor_id", "executor_stopped", "browsers_closed", "books"}
        or value["schema"] != _SCHEMA or value["executor_stopped"] is not True
        or value["browsers_closed"] is not True or not _digest(value["stopped_executor_id"])
        or type(value["observed_at"]) is not int or not 0 <= now - value["observed_at"] <= 7200
        or not isinstance(value["books"], list) or not 1 <= len(value["books"]) <= 20):
        raise ValueError("origin_recovery_observation_required")
    config = pool._configuration(value["configuration"], now)
    if config["schema"] != pool._SERVICE_SCHEMA or config["maximum_new_books"] != len(value["books"]):
        raise ValueError("origin_recovery_existing_books_only")
    seen, projects = set(), set()
    for book in value["books"]:
        if (not isinstance(book, dict) or set(book) != {"book_ref", "head_work_id", "profile_id",
                "account_sha256", "provider_book_id", "book_title", "chapter_number", "chapter_count",
                "text_sha256", "receipt_sha256", "capture_sha256", "review_required", "generating", "editing"}
            or not all(_digest(book[key]) for key in (
                "book_ref", "account_sha256", "text_sha256", "receipt_sha256", "capture_sha256"))
            or book["review_required"] is not True or book["generating"] is not False or book["editing"] is not False
            or type(book["chapter_number"]) is not int or type(book["chapter_count"]) is not int
            or not 1 <= book["chapter_number"] <= book["chapter_count"] <= config["maximum_chapters_per_book"]
            or not isinstance(book["head_work_id"], str)
            or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", book["head_work_id"])
            or book["book_ref"] in seen or book["book_ref"] in config["excluded_book_refs"]):
            raise ValueError("origin_recovery_book_invalid")
        worker.preparation._project({key: book[key] for key in ("provider_book_id", "book_title")})
        if not any(book["profile_id"] == a["profile_id"] and book["account_sha256"] == a["account_sha256"]
                   for a in pool.accounts(config)):
            raise ValueError("origin_recovery_account_mismatch")
        project = (book["account_sha256"], book["provider_book_id"])
        if project in projects:
            raise ValueError("origin_recovery_project_reused")
        seen.add(book["book_ref"])
        projects.add(project)
    for account in pool.accounts(config):
        if account["maximum_new_books"] != sum(b["account_sha256"] == account["account_sha256"] for b in value["books"]):
            raise ValueError("origin_recovery_existing_books_only")
    return copy.deepcopy(value)


def _record(work: dict, book: dict, previous: dict | None) -> tuple[dict, dict]:
    """Reconstruct only if exact historical serialized bytes match Hub's hash."""
    source = worker.preparation._binding({"framework_generation_approved": True,
        "work_id": work["workId"], "book_ref": work["bookRef"], "account_sha256": book["account_sha256"],
        "source_packet_sha256": work["job"]["sourceDigest"], "approved_source": work["job"]["source"]})
    matches = {}
    for version in range(1, 13):
        try:
            if previous is None:
                plan = worker.outline_preparation._plan(source, book["chapter_count"], version=version)
                prepared = worker.outline_preparation._prepared(source,
                    {key: book[key] for key in ("provider_book_id", "book_title")}, plan)
                prepared["generation_approved"] = True
            else:
                prepared = worker.next_preparation._plan(source, previous, version=version)[1]["prepared"]
            binding = writer._binding(prepared)
        except ValueError:
            continue  # Incompatible historical recipes cannot authorize anything.
        result = writer._result(binding, {"origin": writer.capture._ORIGIN.rstrip("/"),
            "bookTitles": [binding["book_title"]], "chapterTitle": binding["chapter_title"],
            "chapterNumber": binding["chapter_number"], "chapterCount": book["chapter_count"],
            "surfaceCount": 1, "text": work["job"]["draftText"], "reviewRequired": True,
            "editing": False, "approveControl": 1})
        record = {"binding": binding, "state": "chapter_review_required", "result": result}
        writer._validate_retained(binding, record)
        digest = _sha(record)
        if digest == work["job"]["providerReceiptDigest"]:
            matches[digest] = (prepared, record)
    if len(matches) != 1:
        raise RuntimeError("origin_recovery_exact_receipt_missing")
    return next(iter(matches.values()))


def _history(hub, book: dict, config: dict, now: float) -> tuple[dict, dict, list]:
    chain, seen, work_id = [], set(), book["head_work_id"]
    for _ in range(book["chapter_number"]):
        if not isinstance(work_id, str) or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work_id) or work_id in seen:
            raise ValueError("origin_recovery_chain_invalid")
        work = hub.call(work_id)
        if (not isinstance(work, dict) or work.get("workId") != work_id or work.get("bookRef") != book["book_ref"]
            or not isinstance(work.get("job"), dict) or work["job"].get("state") != "review_required"
            or not isinstance(work.get("executionAdmission"), str)):
            raise ValueError("origin_recovery_completed_admission_required")
        chain.append(work)
        seen.add(work_id)
        work_id = work.get("previousWorkId")
    if work_id is not None or chain[-1]["job"].get("previous") is not None:
        raise ValueError("origin_recovery_chain_incomplete")
    chain.reverse()
    account = next(a for a in pool.accounts(config) if a["account_sha256"] == book["account_sha256"])
    enrolled = pool._book_configuration(config, chain[0], account)
    admission, binding = pool.runtime._configuration(pool._execution_configuration(config, enrolled, now),
                                                     "reconstructed-completed-history", now)
    entries, records, prior = [], [], None
    for index, work in enumerate(chain):
        intake._scope(work, admission)
        packet = {"work_id": work["workId"], "execution_admission": work["executionAdmission"],
            "automatic_execution_approved": True, "approved_source": work["job"]["source"],
            "setup": {"browser_session": "reconstructed-completed-history", "account_sha256": book["account_sha256"],
                "source_packet_sha256": work["job"]["sourceDigest"], "chapter_generation_approved": True}}
        # No historical framework/activation/outline permission or invented
        # session/advance journal. These entries are already completed in Hub.
        if prior is not None:
            packet["previous"] = intake._previous(entries[-1])
        intake.cycle._packet(packet)
        job = worker._validate_work(work, packet, preparing=True)
        if job.get("readerAcceptedTextDigest") != writer.capture._sha(job["draftText"]):
            raise ValueError("origin_recovery_reader_acceptance_required")
        if prior is not None:
            worker._validate_previous(work, chain[index - 1], packet["previous"])
        prepared, record = _record(work, book, prior)
        entries.append({"packet": packet, "state": "review_required", "prepared": prepared})
        records.append((work, record))
        prior = prepared
    head = chain[-1]["job"]
    if head["readerAcceptedTextDigest"] != book["text_sha256"] or head["providerReceiptDigest"] != book["receipt_sha256"]:
        raise RuntimeError("origin_recovery_provider_head_mismatch")
    if hub.pending(book["book_ref"]) != []:
        raise RuntimeError("origin_recovery_pending_work_requires_reconciliation")
    return enrolled, {"binding": binding["execution"], "jobs": entries}, records


def recover_completed(load_plan, hub, output_root: Path, *, now=time.time) -> dict:
    """Operator-only operation. Hub GETs and private writes; no browser/actions.

    A new destination is mandatory. Partial output stays inert without a pool
    ledger. The ledger is committed last; this command never starts a worker.
    Old journals, exclusions and uncertain admissions are never modified.
    """
    plan = _plan(load_plan(), now())
    config = plan["configuration"]
    recovered = [_history(hub, b, config, now()) for b in plan["books"]]
    for book, (_, _, records) in zip(plan["books"], recovered):
        if (any(hub.call(work["workId"]) != work for work, _ in records)
            or hub.pending(book["book_ref"]) != []):
            raise RuntimeError("origin_recovery_snapshot_changed")
    if _plan(load_plan(), now()) != plan:
        raise RuntimeError("origin_recovery_plan_changed")
    for path in (output_root.absolute(), *output_root.absolute().parents):
        if path.is_symlink():
            raise RuntimeError("origin_recovery_linked_destination")
    output_root.mkdir(mode=0o700)  # Never overwrite/adopt even an empty destination.
    root = writer._private_root(output_root)
    receipt = {"schema": _SCHEMA, "state": "completed_history_reconstructed",
        "plan_sha256": _sha(plan), "observed_at": plan["observed_at"],
        "stopped_executor_id": plan["stopped_executor_id"], "new_book_admission_allowed": False,
        "historical_sessions_reconstructed": False, "historical_advance_fences_reconstructed": False,
        "provider_dispatch": False, "hub_mutation": False, "publication_authorized": False, "books": []}
    for book, (enrolled, state, records) in zip(plan["books"], recovered):
        for entry, (work, record) in zip(state["jobs"], records):
            path = writer._record_path(root, record["binding"])
            writer._save(path, record)
            if worker.advancement._receipt(path) != work["job"]["providerReceiptDigest"]:
                raise RuntimeError("origin_recovery_written_receipt_mismatch")
            worker.books.bind_prepared(book["book_ref"], work["job"]["source"]["chapterId"], entry["prepared"], output_root)
        path = root / ("intake-" + book["book_ref"] + ".json")
        writer._save(path, state)
        intake._restore(path, state["binding"])
        receipt["books"].append({"book_ref": book["book_ref"], "capture_sha256": book["capture_sha256"],
            "intake_sha256": _sha(state), "exact_receipts": [work["job"]["providerReceiptDigest"] for work, _ in records]})
    # Recheck authenticated Hub truth after I/O too. Failure leaves inert data,
    # never a runnable replacement of an uncertain historical pool.
    for book, (_, _, records) in zip(plan["books"], recovered):
        if any(hub.call(work["workId"]) != work for work, _ in records) or hub.pending(book["book_ref"]) != []:
            raise RuntimeError("origin_recovery_snapshot_changed")
    if _plan(load_plan(), now()) != plan:
        raise RuntimeError("origin_recovery_plan_changed")
    writer._save(root / "completed-custody-recovery.json", receipt)
    pool._save_pool(root / "book-pool.json", {"configuration": config,
        "books": [enrolled for enrolled, _, _ in recovered], "in_flight": None,
        "new_book_admission_exhausted": True})
    return {"state": receipt["state"], "books": len(recovered),
        "exact_completed_receipts": sum(len(records) for _, _, records in recovered),
        "new_book_admission_allowed": False, "provider_dispatch": False, "publication_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    load = lambda: worker._json(worker._read_private(args.plan_path, 128000))
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    print(json.dumps(recover_completed(load, hub, args.output_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
