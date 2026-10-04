"""Operator-only continuation of one completed book in a fresh pool.

Preserves original custody and byte-identical provider receipts. Never opens a
browser, writes Hub, replays a paid operation, or accepts prose. The operator
must stop the old executor first. Locks and closed session custody are also
required; normal watches never invoke this operation automatically.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from scripts import origin_book_pool as pool
from scripts import firstbook_book_binding as mapping


@contextmanager
def _writer_lease(directory: Path):
    path = directory / ".writer.lock"
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError("origin_import_linked_custody")
    # A completed source already has these locks. Do not create or replace any
    # source files during transfer, and exclude direct low-level writers too.
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+") as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("origin_import_invalid_writer_lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("origin_import_writer_busy") from None
        yield


def import_completed_book(source: Path, destination: Path, configuration: dict,
                          hub, *, expected_source_sha256: str, now=time.time) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        raise ValueError("origin_import_snapshot_required")
    target = pool._configuration(configuration, now())
    with pool._lease(source) as source_path, pool.runtime.intake.cycle._lease(source), \
         _writer_lease(source_path.parent), _writer_lease(source_path.parent / "books"), \
         pool._lease(destination) as target_path, pool.runtime.intake.cycle._lease(destination):
        if any(p.name not in (".pool.lock", ".cycle.lock") for p in target_path.parent.iterdir()):
            raise RuntimeError("origin_import_destination_not_empty")
        raw = pool.worker._read_private(source_path, 200000)
        if hashlib.sha256(raw).hexdigest() != expected_source_sha256:
            raise RuntimeError("origin_import_snapshot_changed")
        original = pool.worker._json(raw)["configuration"]
        # Old execution may have expired. Validate its historical structure;
        # only the new, currently valid approval permits future continuation.
        expiry = original.get("expires_at")
        if type(expiry) is not int or expiry <= 0:
            raise ValueError("origin_import_source_invalid")
        original = pool._configuration(original, expiry - 1)
        state = pool._restore(source_path, original, expiry - 1)
        if (len(state["books"]) != 1 or original["source_scope"] != target["source_scope"]
            or original["approval_id"] == target["approval_id"]
            or target["maximum_chapters_per_book"] < original["maximum_chapters_per_book"]):
            raise RuntimeError("origin_import_completed_single_book_required")
        previous = state["books"][0]
        admission, old_binding = pool.runtime._configuration(previous, "validation-only", expiry - 1)
        ref = admission["book_ref"]
        account = next((a for a in pool.accounts(target) if a["profile_id"] == previous["profile_id"]
            and a["account_sha256"] == admission["account_sha256"]), None)
        if account is None or ref in target["excluded_book_refs"]:
            raise RuntimeError("origin_import_account_or_scope_changed")
        root = source_path.parent
        snapshots = {Path("book-pool.json"): raw}

        def read(relative):
            relative = Path(relative)
            path = root / relative
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise RuntimeError("origin_import_linked_custody")
            snapshots[relative] = pool.worker._read_private(path, 4_000_000)
            return pool.worker._json(snapshots[relative])

        intake_name, session_name = f"intake-{ref}.json", f"owned-session-{ref}.json"
        read(intake_name)
        intake = pool.runtime.intake._restore(root / intake_name, old_binding["execution"])
        session = read(session_name)
        if (set(session) != {"binding", "session", "state"} or session["binding"] != old_binding
            or session["state"] != "closed" or not re.fullmatch(r"origin-book-[0-9a-f]{32}", session["session"])):
            raise RuntimeError("origin_import_session_not_closed")
        if not intake["jobs"] or any(j["state"] != "review_required" for j in intake["jobs"]):
            raise RuntimeError("origin_import_unfinished_work")
        book = read(f"books/{ref}.json")
        mapping._check(book, ref)
        read(f"setup-{ref}.json")
        read(f"outline-{ref}.json")
        observed = []
        for entry in intake["jobs"]:
            packet = entry["packet"]
            work = hub.call(packet["work_id"])
            pool.runtime.intake._scope(work, admission)
            job = pool.worker._validate_work(work, packet, preparing=True)
            if job["state"] != "review_required" or job.get("editorial") is not None:
                raise RuntimeError("origin_import_unfinished_or_edited_work")
            if observed:
                pool.worker._validate_previous(work, observed[-1], packet["previous"])
            prepared = pool.worker.writer._binding(entry["prepared"])
            receipt_path = pool.worker.writer._record_path(root, prepared)
            record = read(receipt_path.relative_to(root))
            pool.worker.writer._validate_retained(prepared, record)
            if (record["state"] != "chapter_review_required"
                or record["result"]["text"] != job["draftText"]
                or hashlib.sha256(snapshots[receipt_path.relative_to(root)]).hexdigest() != job["providerReceiptDigest"]):
                raise RuntimeError("origin_import_provider_receipt_mismatch")
            provider = {k: prepared[k] for k in ("account_sha256", "provider_book_id", "book_title", "narrative_locale")}
            slot = {"work_id": packet["work_id"], "chapter_id": packet["approved_source"]["chapterId"],
                "source_packet_sha256": prepared["source_packet_sha256"], "chapter_number": prepared["chapter_number"]}
            if book["mapping"]["provider"] != provider or slot not in book["mapping"]["chapters"]:
                raise RuntimeError("origin_import_provider_mapping_mismatch")
            observed.append(work)
        if len(book["mapping"]["chapters"]) != len(observed) or hub.pending(ref) != []:
            raise RuntimeError("origin_import_pending_work")
        expected_names = {p.parts[0] for p in snapshots} | {".pool.lock", ".cycle.lock", ".writer.lock"}
        if ({p.name for p in root.iterdir()} - expected_names
            or {p.name for p in (root / "books").iterdir()} - {ref + ".json", ".writer.lock"}):
            raise RuntimeError("origin_import_unaccounted_custody")
        if (any(hub.call(w["workId"]) != w for w in observed) or hub.pending(ref) != []
            or any(pool.worker._read_private(root / p, 4_000_000) != data for p, data in snapshots.items())):
            raise RuntimeError("origin_import_snapshot_changed")
        new_book = pool._book_configuration(target, observed[0], account)
        _, new_binding = pool.runtime._configuration(new_book, "validation-only", now())
        # Completed job packets and provider bytes do not change. Only the
        # explicitly approved future execution envelope receives a new limit.
        continued_intake = {**intake, "binding": new_binding["execution"]}
        continued_session = {**session, "binding": new_binding}
        result = {"state": "completed_book_imported", "book_ref": ref,
            "source_pool_sha256": expected_source_sha256, "source_configuration": original,
            "target_configuration": target, "retained_jobs": len(observed),
            "reserved_books": 1, "remaining_books": target["maximum_new_books"] - 1,
            "source_files": {str(p): hashlib.sha256(data).hexdigest() for p, data in snapshots.items()},
            "provider_dispatch": False, "reader_acceptance_changed": False, "publication_authorized": False}
        destination_root = target_path.parent
        # Ledger is written LAST. Interrupted copies cannot start a worker and
        # cannot be retried automatically over a partially imported directory.
        for relative, data in snapshots.items():
            if str(relative) in ("book-pool.json", intake_name, session_name):
                continue
            output = destination_root / relative
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for name, record in ((intake_name, continued_intake), (session_name, continued_session),
                             (f"completed-import-{ref}.json", result)):
            pool.worker.writer._save(destination_root / name, record)
        directory = os.open(destination_root / "books", os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        pool.worker.writer._save(target_path, {"configuration": target, "books": [new_book], "in_flight": None})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--configuration-path", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    configuration = pool.worker._json(pool.worker._read_private(args.configuration_path, 16000))
    hub = pool.worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    result = import_completed_book(args.source_root, args.output_root, configuration, hub,
        expected_source_sha256=args.expected_source_sha256)
    print(json.dumps({k: result[k] for k in ("state", "book_ref", "reserved_books", "remaining_books", "provider_dispatch")}))


if __name__ == "__main__":
    main()
