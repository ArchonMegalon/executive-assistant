"""Bounded local Origin execution with an exclusively owned browser window.

An already approved FirstBook profile is required. No profile creation/import,
login, account selection, purchases or publication. The existing intake and
provider fences remain authoritative. In-flight/uncertain sessions are retained
for reconciliation, never closed or adopted by another invocation automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from scripts import origin_chapter_intake as intake

worker = intake.worker
_SAFE_CLOSE = {"idle", "review_required", "chapter_limit_reached", "awaiting_reader_acceptance", "final_chapter_retained"}
_WATCH_AGAIN = {"idle", "review_required", "awaiting_reader_acceptance"}


def _unstarted_recovery(root: Path, path: Path, previous: dict, binding: dict) -> bool:
    """Consume only an exact operator-reviewed pre-admission recovery record.

    The old lifecycle journal is preserved, not falsely marked closed. A new
    open replaces that journal, so this record cannot authorize another retry.
    """
    digest = hashlib.sha256(worker._read_private(path, 4_000_000)).hexdigest()
    receipt = worker.writer._load(root / ("unstarted-session-" + digest + ".json"))
    if receipt is None:
        return False
    expected = {"state", "binding", "session", "session_sha256", "intake_sha256",
        "pool_before_sha256", "book_ref", "work_id", "reserved_books", "remaining_books",
        "publication_authorized"}
    return (set(receipt) == expected and receipt["state"] == "reconciled_unstarted"
        and previous["state"] == "retained_for_reconciliation"
        and receipt["binding"] == binding and receipt["session"] == previous["session"]
        and receipt["session_sha256"] == digest
        and receipt["book_ref"] == binding["execution"]["book_ref"]
        and receipt["work_id"] == binding["execution"]["first_work_id"]
        and receipt["publication_authorized"] is False
        and receipt["intake_sha256"] == hashlib.sha256(worker._read_private(
            root / ("intake-" + receipt["book_ref"] + ".json"), 4_000_000)).hexdigest())


class Browser:
    @staticmethod
    def _command(*args: str) -> str:
        try:
            run = subprocess.run(["browser-act", *args], capture_output=True, text=True, check=True, timeout=45)
        except (subprocess.SubprocessError, OSError):
            raise RuntimeError("origin_runtime_browser_command_uncertain") from None
        if len(run.stdout) > 200000:
            raise RuntimeError("origin_runtime_browser_response_invalid")
        return run.stdout.strip()

    def open(self, profile: str, session: str) -> None:
        raw = self._command("--session", session, "browser", "open", profile, worker.writer.capture._ORIGIN)
        lines = raw.splitlines()
        if (lines.count("session_name=" + session) != 1
            or not any(line in ("browser_type=chrome", "browser_type=stealth") for line in lines)
            or "url=" + worker.writer.capture._ORIGIN not in lines):
            raise RuntimeError("origin_runtime_browser_open_not_verified")

    def verify_account(self, session: str, account: str) -> None:
        worker.writer.capture._open_dashboard(session, account)

    def close(self, session: str) -> None:
        raw = self._command("session", "close", session)
        if raw.splitlines().count("session_name=" + session + " closed=true") != 1:
            raise RuntimeError("origin_runtime_browser_close_not_verified")


def _configuration(value: dict, session: str, now: float) -> tuple[dict, dict]:
    if (not isinstance(value, dict) or set(value) != {"profile_id", "profile_use_approved", "source_scope", "admission"}
        or value.get("profile_use_approved") is not True
        or not isinstance(value.get("profile_id"), str)
        or not re.fullmatch(r"(?:chrome_local_[0-9]{1,32}|[0-9]{1,32})", value["profile_id"])
        or value.get("source_scope") not in ("synthetic_only", "consented_origin")
        or not isinstance(value.get("admission"), dict) or "browser_session" in value["admission"]):
        raise ValueError("origin_runtime_profile_not_admitted")
    admission = {**value["admission"], "browser_session": session}
    binding = intake._admission(admission, now)
    return admission, {"profile_id": value["profile_id"], "source_scope": value["source_scope"], "execution": binding}


def run_bounded(configuration: dict, hub: worker.LocalHub, output_root: Path, *, cycles: int = 60,
                interval: int = 5, browser=None, now=time.time, sleep=time.sleep, before_tick=None,
                report_idle_failure: bool = False) -> dict:
    if type(cycles) is not int or not 1 <= cycles <= 120 or type(interval) is not int or not 2 <= interval <= 30:
        raise ValueError("origin_runtime_invalid_budget")
    # Caller-supplied session names are forbidden: only this process opens and
    # controls this fresh window. Historical names are not ownership evidence.
    session = "origin-book-" + uuid.uuid4().hex
    admission, binding = _configuration(configuration, session, now())
    browser = browser or Browser()
    root = worker.writer._private_root(output_root)
    path = root / ("owned-session-" + admission["book_ref"] + ".json")
    with intake.cycle._lease(output_root):
        previous = worker.writer._load(path)
        if previous is not None and (set(previous) != {"binding", "session", "state"}
            or previous["binding"] != binding or (previous["state"] != "closed"
                and not _unstarted_recovery(root, path, previous, binding))):
            raise RuntimeError("origin_runtime_previous_session_requires_reconciliation")
        opened = attempted = work_may_have_started = False

        def retain(state):
            worker.writer._save(path, {"binding": binding, "session": session, "state": state})

        def close():
            nonlocal opened
            retain("closing")
            browser.close(session)
            retain("closed")
            opened = False

        def ensure_browser():
            nonlocal opened, attempted, work_may_have_started
            # Hub reads/account verification may consume the remaining lifetime.
            # Do not start a provider operation under an already expired watch.
            if before_tick is not None:
                before_tick()
            if not opened:
                retain("opening")
                attempted = True
                browser.open(configuration["profile_id"], session)
                opened = True
                retain("open")
                browser.verify_account(session, admission["account_sha256"])
                if before_tick is not None:
                    before_tick()
            work_may_have_started = True

        try:
            for index in range(cycles):
                # Expiry and Hub owner/source/acceptance are rechecked every
                # tick, while retaining the lease throughout observation waits.
                if before_tick is not None:
                    before_tick()
                result = intake._tick(admission, hub, output_root, now=now, before_cycle=ensure_browser)
                if result["state"] not in intake.cycle._OBSERVABLE or index + 1 == cycles:
                    break
                sleep(interval)
            if opened:
                if result["state"] in _SAFE_CLOSE:
                    close()
                else:
                    retain("retained_for_reconciliation")
            return {**result, "browser_session": session if attempted else None,
                "browser_retained": opened, "publication_authorized": False}
        except BaseException as error:
            # A failed open acknowledgement may still have created a window.
            # Never discover/close it from a name or silently open a replacement.
            no_browser = not attempted
            if opened and not work_may_have_started:
                close()
                no_browser = True  # only after the close acknowledgement and journal write
            elif attempted:
                retain("retained_for_reconciliation")
            if report_idle_failure and no_browser and isinstance(error, Exception):
                # Prior custody was validated above. This invocation either
                # never opened or verified its pre-work window closed. Preserve
                # the journals and pool fence without retaining an empty
                # container. Unknown opens/closes still raise and are retained.
                return {"state": "reconciliation_required", "browser_retained": False,
                    "stop_reason": "origin_runtime_failed_without_browser",
                    "publication_authorized": False}
            raise


def watch_book(load_configuration, hub: worker.LocalHub, output_root: Path, *,
               duration: int = 3600, poll_interval: int = 30, cycles: int = 60,
               interval: int = 5, browser=None, now=time.time, monotonic=time.monotonic,
               sleep=time.sleep) -> dict:
    """Poll one enrolled book, not a general queue or a renewed spending grant.

    Re-read owner-only enrollment before every tick. Changed/revoked admission,
    exceptions or uncertain provider work stop the process; never retry them.
    The initial expiry and monotonic lifetime cannot be extended by editing the
    file or by a wall-clock rollback. Existing journals protect process restart.
    """
    if (type(duration) is not int or not 1 <= duration <= 86400
        or type(poll_interval) is not int or not 15 <= poll_interval <= 300):
        raise ValueError("origin_runtime_invalid_watch_budget")
    original = load_configuration()
    _, binding = _configuration(original, "validation-only", now())
    expiry = original["admission"]["expires_at"]
    deadline = monotonic() + min(duration, expiry - now())
    polls = 0

    def check():
        current = load_configuration()
        _, current_binding = _configuration(current, "validation-only", now())
        if current_binding != binding or current["admission"]["expires_at"] > expiry:
            raise RuntimeError("origin_runtime_watch_admission_changed")
        if monotonic() >= deadline:
            raise RuntimeError("origin_runtime_watch_budget_exhausted")
        return current

    while monotonic() < deadline and now() < expiry:
        current = check()
        result = run_bounded(current, hub, output_root, cycles=cycles, interval=interval,
            browser=browser, now=now, sleep=sleep, before_tick=check)
        polls += 1
        # Includes retained browser custody, reconciliation, and quota/final-slot
        # stops. A watcher must not turn a bounded failure into blind retries.
        if result.get("browser_retained") is not False or result.get("state") not in _WATCH_AGAIN:
            return {**result, "watch_polls": polls}
        remaining = min(deadline - monotonic(), expiry - now())
        if remaining > 0:
            sleep(min(poll_interval, remaining))
    return {"state": "watch_finished", "watch_polls": polls,
        "browser_retained": False, "publication_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=60)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--watch-seconds", type=int, help="Poll this enrolled book for at most 86400 seconds.")
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()
    configuration = worker._json(worker._read_private(args.configuration_path, 16000))
    _configuration(configuration, "validation-only", time.time())
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    if args.watch_seconds is not None:
        result = watch_book(lambda: worker._json(worker._read_private(args.configuration_path, 16000)),
            hub, args.output_root, duration=args.watch_seconds, poll_interval=args.poll_interval,
            cycles=args.cycles, interval=args.interval)
        print(json.dumps(result))
        return 0 if result["state"] in ("watch_finished", "chapter_limit_reached", "final_chapter_retained") else 2
    print(json.dumps(run_bounded(configuration, hub, args.output_root, cycles=args.cycles, interval=args.interval)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
