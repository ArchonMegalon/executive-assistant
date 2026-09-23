"""One local intake tick for one explicitly enrolled Origin book.

The private controller fixes the Hub book/first job, provider account, owned
browser session, expiry and chapter/credit ceiling. Hub still owns consent,
facts, predecessor acceptance and jobs. No account discovery, reader approval,
credit purchase, automatic replay, public endpoint or service enablement.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import time
import uuid

from scripts import origin_chapter_cycle as cycle

worker = cycle.worker
_SCHEMA = "firstbook.local-book-execution/v1"
_STATES = cycle._OBSERVABLE | {"working", "review_required", "awaiting_reader_acceptance",
    "reconciliation_required", "outline_reconciliation_required", "framework_observed_needs_project_binding",
    "framework_bound_needs_outline_review"}
_STATES = _STATES | {"final_chapter_retained"}


def _admission(value: dict, now: float) -> dict:
    fields = {"schema", "approved", "book_ref", "first_work_id", "account_sha256", "workspace_id",
        "locale", "browser_session", "expires_at", "maximum_chapters", "maximum_book_credits"}
    if (not isinstance(value, dict) or set(value) != fields or value.get("schema") != _SCHEMA
        or value.get("approved") is not True or type(value.get("expires_at")) is not int
        or not now < value["expires_at"] <= now + 7 * 86400
        or type(value.get("maximum_chapters")) is not int or not 1 <= value["maximum_chapters"] <= 100
        or type(value.get("maximum_book_credits")) is not int or value["maximum_book_credits"] != 1):
        raise ValueError("origin_intake_not_admitted")
    for key in ("book_ref", "account_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise ValueError("origin_intake_not_admitted")
    for key, pattern in (("first_work_id", r"[0-9a-f]{64}\.[0-9a-f]{64}"),
                         ("browser_session", r"[A-Za-z0-9_-]{1,128}"),
                         ("locale", r"(?:de|en|es)(?:-[A-Za-z]{2})?")):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ValueError("origin_intake_not_admitted")
    worker.writer.capture._text(value, "workspace_id", 256)
    # The same book cannot gain another account/credit budget by changing the
    # input file. A fresh owned browser/expiry can resume the same private work.
    return {key: item for key, item in value.items() if key not in ("browser_session", "expires_at")}


def _previous(entry: dict) -> dict:
    if entry["state"] != "review_required" or not isinstance(entry.get("prepared"), dict):
        raise RuntimeError("origin_intake_predecessor_not_retained")
    packet = entry["packet"]
    return {key: packet[key] for key in ("work_id", "execution_admission", "approved_source")} | {
        "prepared": entry["prepared"]}


def _scope(work: dict, admission: dict) -> None:
    source = work.get("job", {}).get("source", {}) if isinstance(work.get("job"), dict) else {}
    if (work.get("bookRef") != admission["book_ref"]
        or not isinstance(work.get("workId"), str)
        or not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work["workId"])
        or work["workId"][:64] != admission["first_work_id"][:64]
        or source.get("workspaceId") != admission["workspace_id"] or source.get("locale") != admission["locale"]):
        raise ValueError("origin_intake_book_scope_mismatch")


def _restore(path: Path, binding: dict) -> dict:
    state = worker.writer._load(path)
    if state is None:
        return {"binding": binding, "jobs": []}
    if (set(state) != {"binding", "jobs"} or state["binding"] != binding
        or not isinstance(state["jobs"], list) or len(state["jobs"]) > binding["maximum_chapters"]):
        raise RuntimeError("origin_intake_retained_admission_mismatch")
    seen = set()
    for index, entry in enumerate(state["jobs"]):
        if (not isinstance(entry, dict) or set(entry) != {"packet", "state", "prepared"}
            or entry["state"] not in _STATES):
            raise RuntimeError("origin_intake_retained_job_invalid")
        packet = entry["packet"]
        cycle._packet(packet)
        source, setup = packet["approved_source"], packet["setup"]
        if (packet["work_id"] in seen or packet["work_id"][:64] != binding["first_work_id"][:64]
            or setup["account_sha256"] != binding["account_sha256"]
            or source["workspaceId"] != binding["workspace_id"] or source["locale"] != binding["locale"]
            or index == 0 and (packet["work_id"] != binding["first_work_id"] or "previous" in packet)
            or index > 0 and packet.get("previous") != _previous(state["jobs"][index - 1])):
            raise RuntimeError("origin_intake_retained_job_invalid")
        if entry["state"] == "review_required":
            worker.writer._binding(_previous(entry)["prepared"])
        seen.add(packet["work_id"])
    return state


def _new_packet(work: dict, admission: dict, prior: dict | None) -> dict:
    _scope(work, admission)
    if work.get("executionAdmission") is not None:
        # Missing custody never grants permission to take over consumed work.
        raise RuntimeError("origin_intake_existing_admission_requires_recovery")
    job = work["job"]
    packet = {"work_id": work["workId"], "execution_admission": "origin-intake-" + uuid.uuid4().hex,
        "automatic_execution_approved": True, "approved_source": copy.deepcopy(job["source"]),
        "setup": {"browser_session": admission["browser_session"], "account_sha256": admission["account_sha256"],
            "source_packet_sha256": job["sourceDigest"], "chapter_generation_approved": True,
            "framework_generation_approved": True}}
    if prior is None:
        if work["workId"] != admission["first_work_id"] or job.get("previous") is not None:
            raise ValueError("origin_intake_first_chapter_mismatch")
        packet["setup"].update(outline_activation_approved=True, maximum_book_credits=1,
            framework_project_discovery_approved=True)
    else:
        packet["previous"] = _previous(prior)
        packet["setup"]["outline_update_approved"] = True
    cycle._packet(packet)
    worker._validate_work(work, packet, preparing=True)
    return packet


def run_once(admission: dict, hub: worker.LocalHub, output_root: Path, *, now=time.time) -> dict:
    """Fetch/advance at most one job; caller owns the browser exclusively."""
    binding = _admission(admission, now())
    root = worker.writer._private_root(output_root)
    path = root / ("intake-" + binding["book_ref"] + ".json")
    # Share the cycle lock, including queue selection and persistence, so two
    # local controllers cannot allocate competing slots or navigate one session.
    with cycle._lease(output_root):
        state = _restore(path, binding)
        jobs = state["jobs"]
        if jobs and jobs[-1]["state"] != "review_required":
            entry = jobs[-1]
        else:
            if len(jobs) >= binding["maximum_chapters"]:
                return {"state": "chapter_limit_reached", "publication_authorized": False}
            pending = hub.pending(binding["book_ref"])
            if not isinstance(pending, list) or len(pending) > 20:
                raise ValueError("origin_intake_pending_invalid")
            candidates = []
            for work in pending:
                if not isinstance(work, dict):
                    raise ValueError("origin_intake_pending_invalid")
                _scope(work, admission)
                if ((not jobs and work["workId"] == binding["first_work_id"])
                    or (jobs and work.get("previousWorkId") == jobs[-1]["packet"]["work_id"])):
                    candidates.append(work)
            if not candidates:
                return {"state": "idle", "publication_authorized": False}
            if len(candidates) != 1:
                raise RuntimeError("origin_intake_ambiguous_successor")
            # Queue enumeration is not a dispatch snapshot. Re-read exact work.
            work = hub.call(candidates[0]["workId"])
            packet = _new_packet(work, admission, jobs[-1] if jobs else None)
            if jobs:
                previous = packet["previous"]
                worker._validate_previous(work, hub.call(previous["work_id"]), previous)
            entry = {"packet": packet, "state": "working", "prepared": None}
            jobs.append(entry)
            worker.writer._save(path, state)  # before any provider/Hub write
        packet = copy.deepcopy(entry["packet"])
        packet["setup"]["browser_session"] = admission["browser_session"]
        _scope(hub.call(packet["work_id"]), admission)
        result = cycle._step(packet, hub, output_root)
        if result.get("state") not in _STATES:
            raise RuntimeError("origin_intake_cycle_state_unknown")
        if result["state"] == "review_required":
            prepared = cycle.retained_preparation(packet, binding["book_ref"], output_root)
            if prepared is None:
                raise RuntimeError("origin_intake_completed_handoff_missing")
            entry["prepared"] = {**prepared, "generation_approved": True}
        entry["state"] = result["state"]
        worker.writer._save(path, state)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    admission = worker._json(worker._read_private(args.admission_path, 16000))
    _admission(admission, time.time())
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    print(json.dumps(run_once(admission, hub, args.output_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
