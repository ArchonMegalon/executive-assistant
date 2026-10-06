"""Run the approved book pool with scoped local Chrome profiles, never all EA.

No profile creation/import, cookie copying, API credential or host daemon mount.
Only selected metadata is registered for the already mounted profile. The host
must not operate that profile concurrently. Chrome's own profile lock remains
intact; never delete Singleton files to force a start.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import threading
import time
import uuid

from scripts import origin_book_pool as pool


def _private_directory(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir():
        raise RuntimeError("origin_container_directory_invalid")
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("origin_container_directory_not_private")


def hub_origin() -> str:
    """Validate the exact namespace/port inputs also consumed by Compose.

    Docker performs the namespace join; this is not proof of that join for
    an arbitrary manual launch. Never accept a URL, hostname, mutable container
    name or host-network fallback. LocalHub retains its own loopback, proxy and
    redirect checks. A replaced Hub requires an explicit new inspected ID.
    """
    container_id = os.environ.get("ORIGIN_BOOK_HUB_CONTAINER_ID", "")
    port = os.environ.get("ORIGIN_BOOK_HUB_PORT", "")
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise RuntimeError("origin_container_exact_hub_required")
    if not re.fullmatch(r"[1-9][0-9]{3,4}", port) or not 1024 <= int(port) <= 65535:
        raise RuntimeError("origin_container_private_hub_port_required")
    return f"http://127.0.0.1:{port}"


def prepare_browser(config: dict, root: Path) -> None:
    approved = {account["profile_id"] for account in pool.accounts(config)}
    if any(not re.fullmatch(r"chrome_local_[0-9]{1,32}", profile) for profile in approved):
        raise RuntimeError("origin_container_local_profile_required")
    if os.environ.get("BROWSERACT_API_KEY") or os.environ.get("BROWSERACT_CLI_SERVICE_URL"):
        raise RuntimeError("origin_container_ambient_browser_credentials")
    _private_directory(root)
    profiles = root / "profiles"
    if profiles.is_symlink() or not profiles.is_dir() or {p.name for p in profiles.iterdir()} != approved:
        raise RuntimeError("origin_container_only_approved_profile_allowed")
    for profile in approved:
        _private_directory(profiles / profile)
        if not (profiles / profile / "Default").is_dir():
            raise RuntimeError("origin_container_existing_profile_required")
        _private_directory(profiles / profile / "Default")
    settings = {"analytics_disabled": True, "exception_report_disabled": True}
    settings_path = root / "config.json"
    if settings_path.is_symlink():
        raise RuntimeError("origin_container_browser_config_linked")
    if settings_path.exists():
        current = pool.worker._json(pool.worker._read_private(settings_path, 16000))
        # The CLI records kernel/version observations itself. These do not
        # authorize a credential, remote service, imported profile or telemetry.
        metadata = {"latest_kernel_version", "version_check_latest", "version_check_min", "version_check_ts"}
        if (not isinstance(current, dict) or set(current) - set(settings) - metadata
            or any(current.get(k) is not v for k, v in settings.items())
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", v)
                   for k, v in current.items() if k in metadata - {"version_check_ts"})
            or ("version_check_ts" in current and (type(current["version_check_ts"]) not in (int, float)
                or not math.isfinite(current["version_check_ts"])))):
            raise RuntimeError("origin_container_browser_config_changed")
    else:
        pool.worker.writer._save(settings_path, settings)
    db = root / "browsers.db"
    if db.is_symlink():
        raise RuntimeError("origin_container_registry_invalid")
    if not db.exists():
        # Pinned BrowserAct 1.1.0 initializes its own schema. Do NOT use
        # create_browser/import-profile: this is the identical existing profile.
        from browser_act_cli.registry import Registry
        registry = Registry(registry_path=db)
        with registry._connect() as connection:
            for profile in sorted(approved):
                registry.insert_browser_row(connection, id=profile, name="firstbook-origin-dossier",
                    type="chrome", source="local", desc="Consented Chummer Origin only; no purchases or publication.")
        db.chmod(0o600)
    info = db.stat()
    if not db.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("origin_container_registry_not_private")
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,type,source,mode,profile,source_profile,api_key_hash,"
            "proxy_type,dynamic_proxy,custom_proxy,static_proxy_id,confirm_before_use FROM browsers").fetchall()
        if sorted(rows) != [(profile, "chrome", "local", "normal", None, None, None, None, None, None, None, 0)
                            for profile in sorted(approved)]:
            raise RuntimeError("origin_container_registry_not_scoped")
        if connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] != 0:
            raise RuntimeError("origin_container_imported_profiles_forbidden")


def preflight(config: dict, browser=None) -> dict:
    """Owned read-only account probe; no Hub mutation or provider generation."""
    browser = browser or pool.runtime.Browser()
    if config["schema"] in (pool._ROTATING_SCHEMA, pool._SERVICE_SCHEMA):
        results = [preflight({**config, **account, "schema": pool._SCHEMA}, browser)
                   for account in pool.accounts(config)]
        return {"state": "accounts_verified", "accounts": results, "credits_spent": 0,
                "browser_retained": False}
    session = "origin-preflight-" + uuid.uuid4().hex
    browser.open(config["profile_id"], session)
    try:
        browser.verify_account(session, config["account_sha256"])
    finally:
        browser.close(session)
    return {"state": "account_verified", "profile_id": config["profile_id"],
        "browser_session": session, "browser_retained": False, "credits_spent": 0}


def watch_or_retain(load, hub, *, duration: int | None, hold=signal.pause,
                    selected_book_ref=None, stop_requested=lambda: False,
                    idle_sleep=time.sleep) -> dict:
    previous = None

    def observe(result):
        nonlocal previous
        # State transitions only; no book identity, prose, credentials or raw
        # exception text. "Running" Docker alone does not prove an active loop.
        current = {key: result[key] for key in
                   ("state", "reserved_books", "remaining_books", "browser_retained") if key in result}
        if current != previous:
            print(json.dumps({**current, "controller": "watch_observation"}), flush=True)
            previous = current

    try:
        if duration is None:
            result = pool.serve(load, hub, Path("/custody"), stop_requested=stop_requested,
                idle_wait=idle_sleep, selected_book_ref=selected_book_ref, observe=observe)
        else:
            result = pool.watch(load, hub, Path("/custody"), duration=duration,
                selected_book_ref=selected_book_ref, observe=observe)
    except Exception:
        result = {"state": "reconciliation_required", "publication_authorized": False}
    if result["state"] == "reconciliation_required" and result.get("browser_retained") is not False:
        # Do not let PID 1 exit and kill an in-progress provider page. Nothing
        # retries here. Keep the owned browser available for explicit recovery.
        # An explicit no-browser runtime result can exit while leaving its fence
        # intact. Missing/uncertain lifecycle evidence must still retain PID 1.
        print(json.dumps({**result, "controller": "stopped_no_retry"}), flush=True)
        while True:
            hold()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--watch-seconds", type=int)
    mode.add_argument("--serve", action="store_true",
        help="Serve the exact finite/standing approval until expiry, revocation or graceful stop.")
    parser.add_argument("--selected-book", help="Restrict this invocation to one exact admitted book.")
    args = parser.parse_args()
    os.umask(0o077)
    origin = hub_origin()  # Fail before reading credentials/custody or opening a browser.
    load = lambda: pool.worker._json(pool.worker._read_private(Path("/private/approval.json"), 16000))
    config = pool._configuration(load(), time.time())
    # Missing/changed/uncertain custody cannot become a new allowance, even
    # through deployment setup. Initialization remains a separate operator act.
    with pool._lease(Path("/custody")) as ledger:
        pool._restore(ledger, config, time.time())
    prepare_browser(config, Path("/browseract"))
    if args.preflight:
        result = preflight(config)
    else:
        hub = pool.worker.LocalHub(origin, Path("/private/worker.token"), host="chummer.run")
        if args.serve:
            stop = threading.Event()
            previous = {sig: signal.signal(sig, lambda *_: stop.set())
                        for sig in (signal.SIGTERM, signal.SIGINT)}
            try:
                result = watch_or_retain(load, hub, duration=None,
                    stop_requested=stop.is_set, idle_sleep=stop.wait,
                    selected_book_ref=args.selected_book)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        else:
            result = watch_or_retain(load, hub, duration=3600 if args.watch_seconds is None else args.watch_seconds,
                selected_book_ref=args.selected_book)
    print(json.dumps(result))
    return 2 if result["state"] == "reconciliation_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
