import json
from pathlib import Path
import sqlite3

import pytest

from scripts import origin_browser_container as container
from tests.test_origin_book_pool import configuration
from tests.test_origin_chapter_runtime import Browser


def prepared(tmp_path):
    root = tmp_path / "browseract"
    root.mkdir(mode=0o700)
    profile = root / "profiles" / configuration()["profile_id"]
    profile.mkdir(mode=0o700, parents=True)
    (profile / "Default").mkdir(mode=0o700)
    # Existing scoped registry fixture. Actual BrowserAct schema initialization
    # and account verification are checked by the local container preflight.
    db = root / "browsers.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE browsers (id TEXT,type TEXT,source TEXT,mode TEXT,profile TEXT,"
            "source_profile TEXT,api_key_hash TEXT,proxy_type INTEGER,dynamic_proxy TEXT,"
            "custom_proxy TEXT,static_proxy_id INTEGER,confirm_before_use INTEGER)")
        connection.execute("INSERT INTO browsers VALUES (?,?,?,'normal',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0)",
            (configuration()["profile_id"], "chrome", "local"))
        connection.execute("CREATE TABLE profiles (id TEXT)")
    db.chmod(0o600)
    return root, profile


def test_only_mounted_existing_profile_and_no_ambient_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERACT_CLI_SERVICE_URL", raising=False)
    root, profile = prepared(tmp_path)
    container.prepare_browser(configuration(), root)
    assert json.loads((root / "config.json").read_text()) == {
        "analytics_disabled": True, "exception_report_disabled": True}
    assert (root / "config.json").stat().st_mode & 0o077 == 0
    assert list((root / "profiles").iterdir()) == [profile]
    container.prepare_browser(configuration(), root)  # no registry/profile reset


@pytest.mark.parametrize("variable", ["BROWSERACT_API_KEY", "BROWSERACT_CLI_SERVICE_URL"])
def test_ambient_browser_authority_rejected(tmp_path, monkeypatch, variable):
    root, _ = prepared(tmp_path)
    monkeypatch.setenv(variable, "not-for-this-worker")
    with pytest.raises(RuntimeError, match="ambient_browser_credentials"):
        container.prepare_browser(configuration(), root)


@pytest.mark.parametrize("field,value", [("id", "chrome_local_999"), ("type", "stealth"),
    ("api_key_hash", "other-account"), ("source_profile", "other-login"),
    ("custom_proxy", "http://proxy"), ("confirm_before_use", 1)])
def test_wrong_registry_scope_rejected(tmp_path, field, value):
    root, _ = prepared(tmp_path)
    with sqlite3.connect(root / "browsers.db") as db:
        db.execute(f"UPDATE browsers SET {field} = ?", (value,))
    with pytest.raises(RuntimeError, match="registry_not_scoped"):
        container.prepare_browser(configuration(), root)


def test_extra_profile_directory_rejected(tmp_path):
    root, _ = prepared(tmp_path)
    (root / "profiles/other").mkdir()
    with pytest.raises(RuntimeError, match="only_approved_profile"):
        container.prepare_browser(configuration(), root)


def test_extra_registry_row_rejected(tmp_path):
    root, _ = prepared(tmp_path)
    with sqlite3.connect(root / "browsers.db") as db:
        db.execute("INSERT INTO browsers SELECT * FROM browsers")
    with pytest.raises(RuntimeError, match="registry_not_scoped"):
        container.prepare_browser(configuration(), root)


def test_import_catalog_is_not_mounted(tmp_path):
    root, _ = prepared(tmp_path)
    with sqlite3.connect(root / "browsers.db") as db:
        db.execute("INSERT INTO profiles VALUES ('unrelated')")
    with pytest.raises(RuntimeError, match="imported_profiles"):
        container.prepare_browser(configuration(), root)


@pytest.mark.parametrize("part", ["config.json", "browsers.db", "profiles/chrome_local_12345/Default"])
def test_linked_state_rejected(tmp_path, part):
    root, _ = prepared(tmp_path)
    path = root / part
    target = tmp_path / "outside"
    if path.exists(): path.rename(target)
    else: target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises((RuntimeError, ValueError)):
        container.prepare_browser(configuration(), root)


@pytest.mark.parametrize("part", [".", "browsers.db", "profiles/chrome_local_12345"])
def test_nonprivate_state_rejected(tmp_path, part):
    root, _ = prepared(tmp_path)
    (root / part).chmod(0o755)
    with pytest.raises(RuntimeError, match="not_private"):
        container.prepare_browser(configuration(), root)


def test_changed_browser_settings_rejected(tmp_path):
    root, _ = prepared(tmp_path)
    container.prepare_browser(configuration(), root)
    (root / "config.json").write_text('{"api_key":"not-for-this-worker"}')
    with pytest.raises(RuntimeError, match="browser_config_changed"):
        container.prepare_browser(configuration(), root)


def test_cli_version_observations_do_not_grant_account_or_remote_authority(tmp_path):
    root, _ = prepared(tmp_path)
    container.prepare_browser(configuration(), root)
    path = root / "config.json"
    settings = json.loads(path.read_text()) | {"latest_kernel_version": "148.1.4.49",
        "version_check_latest": "0.1.30", "version_check_min": "0.1.18", "version_check_ts": 1790274959}
    path.write_text(json.dumps(settings))
    container.prepare_browser(configuration(), root)
    for extra in ({"server_url": "https://remote"}, {"analytics_disabled": False},
                  {"root_dir": "/other"}, {"latest_kernel_version": "../../elsewhere"}):
        path.write_text(json.dumps(settings | extra))
        with pytest.raises(RuntimeError, match="browser_config_changed"):
            container.prepare_browser(configuration(), root)


def test_preflight_owns_fresh_window_and_closes_after_account_failure():
    browser = Browser()
    first = container.preflight(configuration(), browser)
    second = container.preflight(configuration(), browser)
    assert first["browser_session"] != second["browser_session"]
    assert [c[0] for c in browser.calls] == ["open", "account", "close"] * 2
    assert first["credits_spent"] == 0
    def fail(*_): raise RuntimeError("wrong_account")
    browser.verify_account = fail
    with pytest.raises(RuntimeError, match="wrong_account"):
        container.preflight(configuration(), browser)
    assert browser.calls[-1][0] == "close"


def test_compose_has_no_automatic_restart_daemon_or_broad_host_mount():
    import yaml
    spec = yaml.safe_load(Path("docker-compose.origin-book.yml").read_text())
    service = spec["services"]["origin-book"]
    assert service["restart"] == "no" and service["pull_policy"] == "never"
    assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
    assert service["hostname"] == "chummer-origin-book"
    assert "ports" not in service and "env_file" not in service
    assert len(service["volumes"]) == 5
    assert all(v["bind"]["create_host_path"] is False for v in service["volumes"])
    assert {v["target"] for v in service["volumes"]} == {
        "/private/approval.json", "/private/worker.token", "/custody", "/browseract",
        "/browseract/profiles/${ORIGIN_BOOK_PROFILE_ID:?Approved local profile ID}"}


def test_image_supplies_normal_chrome_and_private_display():
    dockerfile = Path("docker/origin-book/Dockerfile").read_text()
    assert "COPY --from=chrome / /opt/google/chrome/" in dockerfile
    assert "find_chrome_executable()" in dockerfile and "google-chrome --version" in dockerfile
    entrypoint = Path("docker/origin-book/entrypoint").read_text()
    assert "-nolisten tcp" in entrypoint and "Xvfb :97" in entrypoint
    assert "USER 1000:1000" in dockerfile


@pytest.mark.parametrize("failure", [True, False])
def test_uncertain_watch_keeps_window_alive_without_retry(monkeypatch, capsys, failure):
    calls = []
    def watch(*args, **kwargs):
        calls.append(1)
        if failure: raise RuntimeError("sensitive_provider_diagnostic")
        return {"state": "reconciliation_required"}
    class Held(Exception): pass
    def hold(): raise Held()
    monkeypatch.setattr(container.pool, "watch", watch)
    with pytest.raises(Held):
        container.watch_or_retain(lambda: {}, object(), duration=1, hold=hold)
    assert calls == [1]
    output = capsys.readouterr().out
    assert "stopped_no_retry" in output and "sensitive_provider_diagnostic" not in output


def test_container_propagates_exact_book_selection(monkeypatch):
    def watch(*args, **kwargs):
        assert kwargs["selected_book_ref"] == "a" * 64
        return {"state": "watch_finished"}
    monkeypatch.setattr(container.pool, "watch", watch)
    assert container.watch_or_retain(lambda: {}, object(), duration=1,
        selected_book_ref="a" * 64)["state"] == "watch_finished"


def test_verified_no_browser_failure_exits_instead_of_holding_display(monkeypatch):
    result = {"state": "reconciliation_required", "browser_retained": False,
        "stop_reason": "origin_runtime_failed_without_browser", "publication_authorized": False}
    monkeypatch.setattr(container.pool, "watch", lambda *a, **k: result)
    def hold():
        pytest.fail("No owned browser can need retention in this verified failure")
    assert container.watch_or_retain(lambda: {}, object(), duration=1, hold=hold) == result
