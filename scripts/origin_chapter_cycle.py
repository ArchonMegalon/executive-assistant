"""Advance one explicitly approved Origin execution packet without manual phases.

Hub remains job/consent/reader authority. This is not queue admission or account
selection: an operator/controller still supplies the exact approved packet and
an owned browser session. Existing durable provider journals authorize phase
handoffs, never a second paid dispatch. No reader acceptance or publication.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import time

from scripts import origin_chapter_worker as worker


# These states name known in-flight or completed phase transitions. Unknown
# outcomes, transport errors and reconciliation states stop rather than retry.
_OBSERVABLE = frozenset({
    "framework_dispatched", "framework_observation_pending", "credit_dispatched", "provider_busy",
    "outline_save_dispatched", "generation_dispatched",
})


def _packet(packet: dict) -> None:
    if (not isinstance(packet, dict) or packet.get("automatic_execution_approved") is not True
        or not isinstance(packet.get("setup"), dict)
        or packet["setup"].get("chapter_generation_approved") is not True):
        raise ValueError("origin_cycle_execution_not_admitted")
    work_id = worker.writer.capture._text(packet, "work_id")
    if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", work_id):
        raise ValueError("origin_worker_invalid_route")
    admission = worker.writer.capture._text(packet, "execution_admission")
    if any(ord(char) < 33 for char in admission):
        raise ValueError("origin_worker_admitted_packet_invalid")
    session = worker.writer.capture._text(packet["setup"], "browser_session", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        raise ValueError("firstbook_invalid_browser_session")
    # Validate complete source/locale/account bounds before any HTTP or browser.
    # The temporary BookRef is only for shape validation; actual identity is
    # obtained from the authenticated Hub below and cannot be supplied here.
    worker.preparation._binding({**packet["setup"], "work_id": work_id,
        "book_ref": "0" * 64, "approved_source": packet.get("approved_source"),
        "framework_generation_approved": True})
    if "previous" in packet:
        previous = packet["previous"]
        if not isinstance(previous, dict) or not isinstance(previous.get("prepared"), dict):
            raise ValueError("origin_worker_previous_chapter_required")
        worker.writer._binding({**previous["prepared"], "request_id": previous.get("work_id")})


def _step(packet: dict, hub: worker.LocalHub, output_root: Path) -> dict:
    observed = hub.call(packet["work_id"])
    job = worker._validate_work(observed, packet, preparing=True)
    if job["state"] == "review_required":
        # No browser, provider navigation or automatic reader acceptance.
        return {"state": "review_required", "work_id": packet["work_id"], "publication_authorized": False}
    setup = {**packet["setup"], "work_id": packet["work_id"], "book_ref": observed["bookRef"],
             "approved_source": job["source"]}
    if "previous" in packet:
        previous = packet["previous"]
        old = hub.call(previous["work_id"])
        old_job = worker._validate_work(old, previous)
        source, old_source = job["source"], old_job["source"]
        if (old["bookRef"] != observed["bookRef"]
            or any(source.get(key) != old_source.get(key) for key in ("workspaceId", "locale", "runnerName"))
            or source.get("chapterId") == old_source.get("chapterId")
            or source.get("acceptedDecisionId") == old_source.get("acceptedDecisionId")):
            raise ValueError("origin_worker_next_chapter_source_mismatch")
        if old_job.get("readerAcceptedTextDigest") is None:
            return {"state": "awaiting_reader_acceptance", "work_id": packet["work_id"], "publication_authorized": False}

    def retained():
        if "previous" in packet:
            prior = {**packet["previous"]["prepared"], "request_id": packet["previous"]["work_id"]}
            return worker.next_preparation.retained_next_chapter(setup, prior, output_root)
        return worker.outline_preparation.retained_first_chapter(setup, output_root)

    prepared = retained()
    if prepared is None:
        action = worker.prepare_next_once if "previous" in packet else worker.prepare_once
        result = action(packet, hub, output_root)
        if result["state"] not in ("first_chapter_prepared", "next_chapter_prepared"):
            return result
        prepared = retained()
        if prepared is None:
            raise RuntimeError("origin_cycle_preparation_not_retained")
    # Never trust a supplied prepared mapping over the exact retained handoff.
    # run_once re-reads Hub and independently checks the handoff and write fence.
    prepared = {**prepared, "browser_session": setup["browser_session"], "generation_approved": True}
    return worker.run_once({**packet, "prepared": prepared}, hub, output_root)


@contextmanager
def _lease(output_root: Path):
    root = worker.writer._private_root(output_root)
    fd = os.open(root / ".cycle.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("origin_cycle_busy") from None
        yield


def run_once(packet: dict, hub: worker.LocalHub, output_root: Path) -> dict:
    """One non-waiting cycle; refuses another cycle sharing these journals."""
    _packet(packet)
    with _lease(output_root):
        return _step(packet, hub, output_root)


def run_bounded(packet: dict, hub: worker.LocalHub, output_root: Path, *, cycles: int = 1,
                interval: int = 10, sleep=time.sleep) -> dict:
    """Observe known in-flight work, with a finite budget and no error retries."""
    if type(cycles) is not int or not 1 <= cycles <= 120 or type(interval) is not int or not 2 <= interval <= 60:
        raise ValueError("origin_cycle_invalid_budget")
    _packet(packet)
    # Keep ownership while the browser's frontend is doing asynchronous work;
    # a second cycle must not navigate it away between two observations.
    with _lease(output_root):
        for number in range(cycles):
            result = _step(packet, hub, output_root)
            if result["state"] not in _OBSERVABLE or number + 1 == cycles:
                return result
            sleep(interval)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    packet = worker._json(worker._read_private(args.packet_path, 64_000))
    _packet(packet)
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    result = run_bounded(packet, hub, args.output_root, cycles=args.cycles, interval=args.interval)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
