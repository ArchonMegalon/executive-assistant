"""Cumulative local admission for a finite number of consented Origin books.

One fixed FirstBook account/profile, one existing credit per new book. Hub owns
the consented facts, chapter requests and reader acceptance. This controller
never buys credits, creates Hub jobs, accepts prose or publishes. Reservations
are durable before execution and are never refunded by failures or restarts.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time

from scripts import origin_chapter_runtime as runtime

worker = runtime.worker
_SCHEMA = "firstbook.local-book-pool/v1"
_SAFE = runtime._SAFE_CLOSE


def _configuration(value: dict, now: float) -> dict:
    fields = {"schema", "approval_id", "approved", "maximum_new_books", "maximum_chapters_per_book",
              "profile_id", "profile_use_approved", "source_scope", "account_sha256", "expires_at",
              "excluded_book_refs"}
    if (not isinstance(value, dict) or set(value) != fields or value.get("schema") != _SCHEMA
        or value.get("approved") is not True or value.get("source_scope") != "consented_origin"
        or not isinstance(value.get("approval_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["approval_id"])
        or type(value.get("maximum_new_books")) is not int or not 1 <= value["maximum_new_books"] <= 20
        or not isinstance(value.get("excluded_book_refs"), list)
        or len(value["excluded_book_refs"]) > 128
        or any(not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{64}", ref)
               for ref in value["excluded_book_refs"])
        or len(set(value["excluded_book_refs"])) != len(value["excluded_book_refs"])):
        raise ValueError("origin_pool_not_admitted")
    # Reuse the established profile, expiry, locale and one-credit bounds.
    dummy = {"bookRef": "0" * 64, "workId": "0" * 64 + "." + "1" * 64,
             "job": {"source": {"workspaceId": "validation-only", "locale": "en"}}}
    runtime._configuration(_book_configuration(value, dummy), "validation-only", now)
    return copy.deepcopy(value)


def _book_configuration(config: dict, work: dict) -> dict:
    source = work["job"]["source"]
    return {key: config[key] for key in ("profile_id", "profile_use_approved", "source_scope")} | {
        "admission": {"schema": runtime.intake._SCHEMA, "approved": True,
            "book_ref": work["bookRef"], "first_work_id": work["workId"],
            "account_sha256": config["account_sha256"], "workspace_id": source["workspaceId"],
            "locale": source["locale"], "expires_at": config["expires_at"],
            "maximum_chapters": config["maximum_chapters_per_book"], "maximum_book_credits": 1}}


@contextmanager
def _lease(output_root: Path):
    root = worker.writer._private_root(output_root)
    fd = os.open(root / ".pool.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("origin_pool_busy") from None
        yield root / "book-pool.json"


def initialize(config: dict, output_root: Path, *, now=time.time) -> dict:
    """Explicit operator setup, never performed by run/watch on missing custody."""
    binding = _configuration(config, now())
    with _lease(output_root) as path:
        if any(item.name != ".pool.lock" for item in path.parent.iterdir()):
            raise RuntimeError("origin_pool_initialization_requires_empty_custody")
        worker.writer._save(path, {"configuration": binding, "books": [], "in_flight": None})
    return {"state": "initialized", "reserved_books": 0,
            "remaining_books": binding["maximum_new_books"], "publication_authorized": False}


def _read_ledger(path: Path, binding: dict, now: float) -> dict:
    # Missing/invalid custody is not a fresh allowance. Duplicate JSON members
    # are rejected too; no counter is ever inferred from remaining provider credits.
    try:
        state = worker._json(worker._read_private(path, 200000))
    except FileNotFoundError:
        raise RuntimeError("origin_pool_custody_missing") from None
    if (not isinstance(state, dict) or set(state) != {"configuration", "books", "in_flight"}
        or state["configuration"] != binding or not isinstance(state["books"], list)
        or len(state["books"]) > binding["maximum_new_books"]):
        raise RuntimeError("origin_pool_custody_mismatch")
    seen = set()
    for entry in state["books"]:
        runtime._configuration(entry, "validation-only", now)
        admission = entry["admission"]
        ref = admission["book_ref"]
        expected = _book_configuration(binding, {"bookRef": ref, "workId": admission["first_work_id"],
            "job": {"source": {"workspaceId": admission["workspace_id"], "locale": admission["locale"]}}})
        if entry != expected or ref in seen or ref in binding["excluded_book_refs"]:
            raise RuntimeError("origin_pool_custody_mismatch")
        seen.add(ref)
    if state["in_flight"] is not None and state["in_flight"] not in seen:
        raise RuntimeError("origin_pool_custody_mismatch")
    return state


def _restore(path: Path, binding: dict, now: float) -> dict:
    state = _read_ledger(path, binding, now)
    if state["in_flight"] is not None:
        raise RuntimeError("origin_pool_execution_requires_reconciliation")
    return state


def reconcile_completed(load_configuration, hub, output_root: Path, *,
                        expected_pool_sha256: str, book_ref: str, now=time.time) -> dict:
    """Explicit operator recovery of an idle/completed sweep, never a retry.

    A stopped executor must first be inspected by the operator. Both execution
    leases, a reviewed exact ledger, closed session custody, all completed Hub
    jobs and an empty book queue are required here. Uncertain provider work is
    deliberately unsupported. Reservations, expiry and reader acceptance stay
    unchanged; watch/run never invoke this recovery automatically.
    """
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in (expected_pool_sha256, book_ref)):
        raise ValueError("origin_pool_reconciliation_identity_invalid")
    binding = _configuration(load_configuration(), now())
    with _lease(output_root) as path, runtime.intake.cycle._lease(output_root):
        raw = worker._read_private(path, 200000)
        if hashlib.sha256(raw).hexdigest() != expected_pool_sha256:
            raise RuntimeError("origin_pool_reconciliation_snapshot_changed")
        state = _read_ledger(path, binding, now())
        if state["in_flight"] != book_ref:
            raise RuntimeError("origin_pool_reconciliation_fence_mismatch")
        config = next(b for b in state["books"] if b["admission"]["book_ref"] == book_ref)
        admission, book_binding = runtime._configuration(config, "validation-only", now())
        root = path.parent
        intake_path = root / ("intake-" + book_ref + ".json")
        session_path = root / ("owned-session-" + book_ref + ".json")
        snapshots = {p: worker._read_private(p, 4_000_000) for p in (intake_path, session_path)}
        # Duplicate members are not an operator-reviewable snapshot.
        for data in snapshots.values():
            worker._json(data)
        session = worker._json(snapshots[session_path])
        if (not isinstance(session, dict) or set(session) != {"binding", "session", "state"}
            or session["binding"] != book_binding or session["state"] != "closed"
            or not isinstance(session["session"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session["session"])):
            raise RuntimeError("origin_pool_reconciliation_session_not_closed")
        intake = runtime.intake._restore(intake_path, book_binding["execution"])
        if not intake["jobs"] or any(entry["state"] != "review_required" for entry in intake["jobs"]):
            raise RuntimeError("origin_pool_reconciliation_jobs_not_completed")
        observed, completed = [], []
        for entry in intake["jobs"]:
            packet = entry["packet"]
            work = hub.call(packet["work_id"])
            runtime.intake._scope(work, admission)
            job = worker._validate_work(work, packet, preparing=True)
            if job["state"] != "review_required":
                raise RuntimeError("origin_pool_reconciliation_jobs_not_completed")
            if observed:
                worker._validate_previous(work, observed[-1], packet["previous"])
            observed.append(work)
            completed.append({"work_id": packet["work_id"],
                "text_sha256": hashlib.sha256(job["draftText"].encode("utf-8")).hexdigest(),
                "provider_receipt_sha256": job["providerReceiptDigest"],
                "reader_accepted_text_sha256": job.get("readerAcceptedTextDigest")})
        if hub.pending(book_ref) != []:
            raise RuntimeError("origin_pool_reconciliation_queue_not_empty")
        # Re-read: a revision, successor, revocation or custody change during
        # observation must not be treated as the operator's reviewed snapshot.
        if any(hub.call(work["workId"]) != work for work in observed) or hub.pending(book_ref) != []:
            raise RuntimeError("origin_pool_reconciliation_snapshot_changed")
        if (_configuration(load_configuration(), now()) != binding
            or worker._read_private(path, 200000) != raw
            or any(worker._read_private(p, 4_000_000) != data for p, data in snapshots.items())):
            raise RuntimeError("origin_pool_reconciliation_snapshot_changed")
        state["in_flight"] = None
        result = {"state": "reconciled_completed", "book_ref": book_ref,
            "pool_before_sha256": expected_pool_sha256,
            "pool_after_sha256": hashlib.sha256(json.dumps(state, ensure_ascii=False).encode("utf-8")).hexdigest(),
            "reserved_books": len(state["books"]),
            "remaining_books": binding["maximum_new_books"] - len(state["books"]),
            "completed_jobs": completed, "publication_authorized": False}
        receipt_path = root / ("pool-reconciliation-" + expected_pool_sha256 + ".json")
        existing = worker.writer._load(receipt_path)
        if existing is not None and existing != result:
            raise RuntimeError("origin_pool_reconciliation_receipt_mismatch")
        if existing is None:
            worker.writer._save(receipt_path, result)
        worker.writer._save(path, state)
        return result


def reconcile_unstarted(load_configuration, hub, output_root: Path, *,
                        expected_pool_sha256: str, expected_session_sha256: str,
                        stopped_session: str, book_ref: str, now=time.time) -> dict:
    """Explicit recovery BEFORE the first Hub/provider execution admission.

    The operator must independently verify the executor is terminal and its
    browser is absent, then supply that exact stopped session and reviewed
    hashes. Names/journals alone do not prove a stopped process. This function
    never stops/adopts a browser, dispatches work, refunds a reservation or
    changes Hub. Neither run nor watch invokes it automatically.
    """
    if (any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (expected_pool_sha256, expected_session_sha256, book_ref))
        or not isinstance(stopped_session, str)
        or not re.fullmatch(r"origin-book-[0-9a-f]{32}", stopped_session)):
        raise ValueError("origin_pool_reconciliation_identity_invalid")
    binding = _configuration(load_configuration(), now())
    with _lease(output_root) as path, runtime.intake.cycle._lease(output_root):
        raw = worker._read_private(path, 200000)
        if hashlib.sha256(raw).hexdigest() != expected_pool_sha256:
            raise RuntimeError("origin_pool_reconciliation_snapshot_changed")
        state = _read_ledger(path, binding, now())
        if state["in_flight"] != book_ref:
            raise RuntimeError("origin_pool_reconciliation_fence_mismatch")
        config = next(b for b in state["books"] if b["admission"]["book_ref"] == book_ref)
        admission, book_binding = runtime._configuration(config, "validation-only", now())
        root = path.parent
        intake_path = root / ("intake-" + book_ref + ".json")
        session_path = root / ("owned-session-" + book_ref + ".json")
        snapshots = {p: worker._read_private(p, 4_000_000) for p in (intake_path, session_path)}
        for data in snapshots.values():
            worker._json(data)
        session = worker._json(snapshots[session_path])
        if (hashlib.sha256(snapshots[session_path]).hexdigest() != expected_session_sha256
            or not isinstance(session, dict) or set(session) != {"binding", "session", "state"}
            or session["binding"] != book_binding or session["session"] != stopped_session
            or session["state"] != "retained_for_reconciliation"):
            raise RuntimeError("origin_pool_reconciliation_session_mismatch")
        intake = runtime.intake._restore(intake_path, book_binding["execution"])
        if (len(intake["jobs"]) != 1 or intake["jobs"][0]["state"] != "working"
            or intake["jobs"][0]["prepared"] is not None):
            raise RuntimeError("origin_pool_reconciliation_not_unstarted")
        packet = intake["jobs"][0]["packet"]
        work = hub.call(packet["work_id"])
        runtime.intake._scope(work, admission)
        job = worker._validate_work(work, packet, preparing=True)
        if (job["state"] != "awaiting_authoring" or "executionAdmission" not in work
            or work["executionAdmission"] is not None or work.get("previousWorkId") is not None
            or job.get("previous") is not None or packet["setup"]["browser_session"] != stopped_session):
            raise RuntimeError("origin_pool_reconciliation_not_unstarted")
        # Hub /admit precedes any provider action. Also reject surviving local
        # setup/outline custody, including malformed or linked files.
        def assert_no_provider_custody():
            for prefix in ("setup-", "outline-"):
                if worker.writer._load(root / (prefix + book_ref + ".json")) is not None:
                    raise RuntimeError("origin_pool_reconciliation_not_unstarted")
        assert_no_provider_custody()
        if hub.pending(book_ref) != [work]:
            raise RuntimeError("origin_pool_reconciliation_queue_changed")
        if (hub.call(packet["work_id"]) != work or hub.pending(book_ref) != [work]
            or _configuration(load_configuration(), now()) != binding
            or worker._read_private(path, 200000) != raw
            or any(worker._read_private(p, 4_000_000) != data for p, data in snapshots.items())):
            raise RuntimeError("origin_pool_reconciliation_snapshot_changed")
        assert_no_provider_custody()
        result = {"state": "reconciled_unstarted", "binding": book_binding,
            "session": stopped_session, "session_sha256": expected_session_sha256,
            "intake_sha256": hashlib.sha256(snapshots[intake_path]).hexdigest(),
            "pool_before_sha256": expected_pool_sha256, "book_ref": book_ref,
            "work_id": packet["work_id"], "reserved_books": len(state["books"]),
            "remaining_books": binding["maximum_new_books"] - len(state["books"]),
            "publication_authorized": False}
        receipt_path = root / ("unstarted-session-" + expected_session_sha256 + ".json")
        existing = worker.writer._load(receipt_path)
        if existing is not None and existing != result:
            raise RuntimeError("origin_pool_reconciliation_receipt_mismatch")
        if existing is None:
            worker.writer._save(receipt_path, result)
        # Persist the exact recovery before releasing the pool fence. If this
        # last write fails, execution remains blocked and explicit recovery is
        # repeatable against the same snapshots. Intake/session history is intact.
        state["in_flight"] = None
        worker.writer._save(path, state)
        return result


def _new_books(hub, binding: dict, enrolled: set[str], now: float) -> list[dict]:
    pending = hub.pending_books()
    if not isinstance(pending, list) or len(pending) >= 20:
        # The bounded Hub endpoint has no cursor: a full page is not a complete
        # view from which to resolve multiple initial requests for the same book.
        raise RuntimeError("origin_pool_pending_incomplete")
    groups = {}
    for work in pending:
        if not isinstance(work, dict) or not isinstance(work.get("job"), dict):
            raise ValueError("origin_pool_pending_invalid")
        ref = work.get("bookRef")
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{64}", ref):
            raise ValueError("origin_pool_pending_invalid")
        if ref in enrolled or ref in binding["excluded_book_refs"]:
            continue
        job = work["job"]
        if (work.get("executionAdmission") is not None or work.get("previousWorkId") is not None
            or job.get("previous") is not None or job.get("state") != "awaiting_authoring"):
            continue  # Existing/consumed work is never a new-credit enrollment.
        configuration = _book_configuration(binding, work)
        admission, _ = runtime._configuration(configuration, "validation-only", now)
        runtime.intake._new_packet(work, admission, None)  # full source/consent/job shape
        groups.setdefault(ref, []).append(work)
    if any(len(items) != 1 for items in groups.values()):
        raise RuntimeError("origin_pool_ambiguous_first_chapter")
    return [items[0] for _, items in sorted(groups.items())]


def run_once(load_configuration, hub, output_root: Path, *, now=time.time, browser=None,
             cycles=60, interval=5, sleep=time.sleep) -> dict:
    binding = _configuration(load_configuration(), now())

    def check():
        if _configuration(load_configuration(), now()) != binding:
            raise RuntimeError("origin_pool_approval_changed")

    with _lease(output_root) as path:
        state = _restore(path, binding, now())
        books = state["books"]
        if len(books) < binding["maximum_new_books"]:
            candidates = _new_books(hub, binding, {b["admission"]["book_ref"] for b in books}, now())
            if candidates:
                # Enumerating a queue isn't consent/source admission. Re-read
                # the exact Hub item and reject any changed initial snapshot.
                selected = candidates[0]
                fresh = hub.call(selected["workId"])
                if fresh != selected:
                    raise RuntimeError("origin_pool_initial_source_changed")
                check()
                books.append(_book_configuration(binding, fresh))
                worker.writer._save(path, state)  # reserve BEFORE any browser/Hub write
        results = []
        for config in books:
            check()
            state["in_flight"] = config["admission"]["book_ref"]
            worker.writer._save(path, state)
            result = runtime.run_bounded(config, hub, output_root, now=now, browser=browser,
                cycles=cycles, interval=interval, sleep=sleep, before_tick=check)
            if result.get("browser_retained") is not False or result.get("state") not in _SAFE:
                return {"state": "reconciliation_required", "reserved_books": len(books),
                    "remaining_books": binding["maximum_new_books"] - len(books), "publication_authorized": False}
            # An exception or process death leaves in_flight intact. No automatic
            # retry, release of the reservation or new browser on process restart.
            state["in_flight"] = None
            worker.writer._save(path, state)
            results.append(result["state"])
        return {"state": "idle" if not results or all(r == "idle" for r in results) else "observed",
            "reserved_books": len(books), "remaining_books": binding["maximum_new_books"] - len(books),
            "book_states": results, "publication_authorized": False}


def watch(load_configuration, hub, output_root: Path, *, duration=3600, poll_interval=30,
          now=time.time, monotonic=time.monotonic, sleep=time.sleep, **kwargs) -> dict:
    if (type(duration) is not int or not 1 <= duration <= 86400
        or type(poll_interval) is not int or not 15 <= poll_interval <= 300):
        raise ValueError("origin_pool_watch_budget_invalid")
    original = _configuration(load_configuration(), now())
    deadline = monotonic() + min(duration, original["expires_at"] - now())

    def check():
        current = _configuration(load_configuration(), now())
        if current != original or monotonic() >= deadline:
            raise RuntimeError("origin_pool_watch_approval_changed_or_expired")
        return current

    last = None
    while monotonic() < deadline and now() < original["expires_at"]:
        last = run_once(check, hub, output_root, now=now, sleep=sleep, **kwargs)
        if last["state"] == "reconciliation_required":
            return last
        remaining = min(deadline - monotonic(), original["expires_at"] - now())
        if remaining > 0:
            sleep(min(poll_interval, remaining))
    return {**(last or {}), "state": "watch_finished", "publication_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--reconcile-completed-book", help="Operator-only recovery; never starts execution.")
    parser.add_argument("--expected-pool-sha256")
    parser.add_argument("--hub-origin")
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--watch-seconds", type=int)
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()
    if args.reconcile_completed_book is not None:
        if args.initialize or args.watch_seconds is not None or args.expected_pool_sha256 is None:
            parser.error("reconciliation requires an exact pool hash and cannot initialize/watch")
    elif args.expected_pool_sha256 is not None:
        parser.error("--expected-pool-sha256 requires --reconcile-completed-book")
    load = lambda: worker._json(worker._read_private(args.configuration_path, 16000))
    if args.initialize:
        result = initialize(load(), args.output_root)
    else:
        if not args.hub_origin or args.token_file is None:
            parser.error("--hub-origin and --token-file are required for execution")
        hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
        if args.reconcile_completed_book is not None:
            result = reconcile_completed(load, hub, args.output_root,
                expected_pool_sha256=args.expected_pool_sha256, book_ref=args.reconcile_completed_book)
        elif args.watch_seconds is not None:
            result = watch(load, hub, args.output_root, duration=args.watch_seconds, poll_interval=args.poll_interval)
        else:
            result = run_once(load, hub, args.output_root)
    print(json.dumps(result))
    return 2 if result["state"] == "reconciliation_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
