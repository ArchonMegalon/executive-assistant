"""Bounded local Origin execution with an exclusively owned browser window.

An already approved FirstBook profile is required. No profile creation/import,
login, account selection, purchases or publication. The existing intake and
provider fences remain authoritative. In-flight/uncertain sessions are retained
for reconciliation, never closed or adopted by another invocation automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from scripts import origin_chapter_intake as intake

worker = intake.worker
_SAFE_CLOSE = {"idle", "review_required", "chapter_limit_reached", "awaiting_reader_acceptance", "final_chapter_retained"}


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
                interval: int = 5, browser=None, now=time.time, sleep=time.sleep) -> dict:
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
            or previous["binding"] != binding or previous["state"] != "closed"):
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
            if not opened:
                retain("opening")
                attempted = True
                browser.open(configuration["profile_id"], session)
                opened = True
                retain("open")
                browser.verify_account(session, admission["account_sha256"])
            work_may_have_started = True

        try:
            for index in range(cycles):
                # Expiry and Hub owner/source/acceptance are rechecked every
                # tick, while retaining the lease throughout observation waits.
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
        except BaseException:
            # A failed open acknowledgement may still have created a window.
            # Never discover/close it from a name or silently open a replacement.
            if opened and not work_may_have_started:
                close()
            elif attempted:
                retain("retained_for_reconciliation")
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration-path", type=Path, required=True)
    parser.add_argument("--hub-origin", required=True)
    parser.add_argument("--hub-host")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=60)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    configuration = worker._json(worker._read_private(args.configuration_path, 16000))
    _configuration(configuration, "validation-only", time.time())
    hub = worker.LocalHub(args.hub_origin, args.token_file, host=args.hub_host)
    print(json.dumps(run_bounded(configuration, hub, args.output_root, cycles=args.cycles, interval=args.interval)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
