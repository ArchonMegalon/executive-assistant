"""Run the finite pool with one existing local Chrome profile, never all EA.

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
import time
import uuid

from scripts import origin_book_pool as pool


def _private_directory(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir():
        raise RuntimeError("origin_container_directory_invalid")
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("origin_container_directory_not_private")


def prepare_browser(config: dict, root: Path) -> None:
    profile = config["profile_id"]
    if not re.fullmatch(r"chrome_local_[0-9]{1,32}", profile):
        raise RuntimeError("origin_container_local_profile_required")
    if os.environ.get("BROWSERACT_API_KEY") or os.environ.get("BROWSERACT_CLI_SERVICE_URL"):
        raise RuntimeError("origin_container_ambient_browser_credentials")
    _private_directory(root)
    profiles = root / "profiles"
    if profiles.is_symlink() or not profiles.is_dir() or {p.name for p in profiles.iterdir()} != {profile}:
        raise RuntimeError("origin_container_only_approved_profile_allowed")
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
            registry.insert_browser_row(connection, id=profile, name="firstbook-origin-dossier",
                type="chrome", source="local", desc="Consented Chummer Origin only; no purchases or publication.")
        db.chmod(0o600)
    info = db.stat()
    if not db.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("origin_container_registry_not_private")
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,type,source,mode,profile,source_profile,api_key_hash,"
            "proxy_type,dynamic_proxy,custom_proxy,static_proxy_id,confirm_before_use FROM browsers").fetchall()
        if rows != [(profile, "chrome", "local", "normal", None, None, None, None, None, None, None, 0)]:
            raise RuntimeError("origin_container_registry_not_scoped")
        if connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] != 0:
            raise RuntimeError("origin_container_imported_profiles_forbidden")


def preflight(config: dict, browser=None) -> dict:
    """Owned read-only account probe; no Hub mutation or provider generation."""
    browser = browser or pool.runtime.Browser()
    session = "origin-preflight-" + uuid.uuid4().hex
    browser.open(config["profile_id"], session)
    try:
        browser.verify_account(session, config["account_sha256"])
    finally:
        browser.close(session)
    return {"state": "account_verified", "profile_id": config["profile_id"],
        "browser_session": session, "browser_retained": False, "credits_spent": 0}


def watch_or_retain(load, hub, *, duration: int, hold=signal.pause, selected_book_ref=None) -> dict:
    try:
        result = pool.watch(load, hub, Path("/custody"), duration=duration,
            selected_book_ref=selected_book_ref)
    except Exception:
        result = {"state": "reconciliation_required", "publication_authorized": False}
    if result["state"] == "reconciliation_required":
        # Do not let PID 1 exit and kill an in-progress provider page. Nothing
        # retries here. Keep the owned browser available for explicit recovery.
        print(json.dumps({**result, "controller": "stopped_no_retry"}), flush=True)
        while True:
            hold()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--watch-seconds", type=int, default=3600)
    parser.add_argument("--selected-book", help="Restrict this invocation to one exact admitted book.")
    args = parser.parse_args()
    os.umask(0o077)
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
        hub = pool.worker.LocalHub("http://127.0.0.1:15099", Path("/private/worker.token"), host="chummer.run")
        result = watch_or_retain(load, hub, duration=args.watch_seconds, selected_book_ref=args.selected_book)
    print(json.dumps(result))
    return 2 if result["state"] == "reconciliation_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
