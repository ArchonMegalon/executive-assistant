from __future__ import annotations

import hashlib
import fcntl
import io
import json
import os
import stat
from pathlib import Path

import pytest

from scripts import provision_memorial_gemini_oauth as subject


REFRESH_SECRET = "REFRESH_SECRET_MUST_NEVER_LEAK"
ACCESS_SECRET = "ACCESS_SECRET_MUST_NEVER_LEAK"


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "refresh_token": REFRESH_SECRET,
        "access_token": ACCESS_SECRET,
        "token_type": "Bearer",
        "scope": f"openid {subject.CLOUD_PLATFORM_SCOPE}",
        "expiry_date": 1_900_000_000_000,
    }
    value.update(overrides)
    return value


def _raw(**overrides: object) -> bytes:
    return json.dumps(_payload(**overrides), indent=2).encode("utf-8")


def _canonical(**overrides: object) -> bytes:
    return (
        json.dumps(
            _payload(**overrides),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _source(tmp_path: Path, raw: bytes | None = None) -> tuple[Path, Path]:
    anchor = _private_dir(tmp_path / "trusted")
    parent = _private_dir(anchor / "credentials")
    source = parent / "oauth_creds.json"
    source.write_bytes(_raw() if raw is None else raw)
    source.chmod(0o600)
    return anchor, source


def _runtime_root(tmp_path: Path) -> Path:
    return _private_dir(tmp_path / "runtime")


def _snapshot_bytes(snapshot: subject.CredentialSnapshot) -> bytes:
    buffer = io.BytesIO()
    snapshot.write_secret_to(buffer)
    return buffer.getvalue()


def test_source_snapshot_is_canonical_bounded_and_exposes_metadata_only(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)

    with subject.snapshot_source_credentials(source, trusted_root=anchor) as snapshot:
        canonical = _snapshot_bytes(snapshot)
        metadata = snapshot.metadata.as_dict()
        rendered = repr(snapshot)

    assert canonical == _canonical()
    assert metadata == {
        "schema": subject.CONTRACT,
        "status": "snapshotted",
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "size_bytes": len(canonical),
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "mode": "0600",
        "device": source.stat().st_dev,
        "inode": source.stat().st_ino,
    }
    assert REFRESH_SECRET not in rendered
    assert ACCESS_SECRET not in rendered
    with pytest.raises(subject.ProvisioningError, match="^oauth_snapshot_closed$"):
        snapshot.write_secret_to(io.BytesIO())


def test_source_snapshot_streams_through_partial_writes(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)

    class PartialSink(io.BytesIO):
        def write(self, value: bytes | bytearray | memoryview) -> int:
            return super().write(value[:7])

    sink = PartialSink()
    with subject.snapshot_source_credentials(source, trusted_root=anchor) as snapshot:
        snapshot.write_secret_to(sink)

    assert sink.getvalue() == _canonical()


def test_source_snapshot_close_zeroes_a_retained_exported_view(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)

    class RetainingSink:
        def __init__(self) -> None:
            self.view: memoryview | None = None

        def write(self, value: memoryview) -> int:
            self.view = value
            return len(value)

    sink = RetainingSink()
    with subject.snapshot_source_credentials(source, trusted_root=anchor) as snapshot:
        snapshot.write_secret_to(sink)  # type: ignore[arg-type]
        secret_size = snapshot.metadata.size_bytes

    assert sink.view is not None
    assert bytes(sink.view) == b"\0" * secret_size


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (
            b'{"refresh_token":"one","refresh_token":"two","access_token":"a",'
            b'"token_type":"Bearer","scope":"s","expiry_date":1}',
            "oauth_credentials_duplicate_key",
        ),
        (
            b'{"refresh_token":"r","access_token":"a","token_type":"Bearer",'
            b'"scope":"s","expiry_date":NaN}',
            "oauth_credentials_nonfinite",
        ),
        (
            b'{"refresh_token":"r","access_token":"a","token_type":"Bearer",'
            b'"scope":"s","expiry_date":1e999}',
            "oauth_credentials_nonfinite",
        ),
        (b"[]", "oauth_credentials_object_required"),
        (b"not-json", "oauth_credentials_json_invalid"),
    ],
)
def test_source_snapshot_rejects_malformed_or_ambiguous_json(
    tmp_path: Path, raw: bytes, code: str
) -> None:
    anchor, source = _source(tmp_path, raw)

    with pytest.raises(subject.ProvisioningError, match=f"^{code}$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


@pytest.mark.parametrize(
    "field",
    ["refresh_token", "token_type", "scope"],
)
@pytest.mark.parametrize("invalid", [None, "", "   "])
def test_required_text_fields_must_be_nonempty(
    tmp_path: Path, field: str, invalid: object
) -> None:
    anchor, source = _source(tmp_path, _raw(**{field: invalid}))

    with pytest.raises(subject.ProvisioningError, match=f"^oauth_credentials_{field}_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


@pytest.mark.parametrize("invalid", [None, "", "   ", 1])
def test_access_token_is_optional_but_must_be_nonempty_text_when_present(
    tmp_path: Path,
    invalid: object,
) -> None:
    anchor, source = _source(tmp_path, _raw(access_token=invalid))

    with pytest.raises(
        subject.ProvisioningError,
        match="^oauth_credentials_access_token_invalid$",
    ):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


@pytest.mark.parametrize(
    "expiry",
    [
        None,
        True,
        "1900000000000",
        1_900_000_000_000.0,
        0,
        -1,
        subject.MIN_EXPIRY_EPOCH_MS - 1,
        subject.MAX_EXPIRY_EPOCH_MS + 1,
        int("9" * 4000),
    ],
)
def test_expiry_must_be_a_sane_positive_integer_epoch_ms(
    tmp_path: Path,
    expiry: object,
) -> None:
    anchor, source = _source(tmp_path, _raw(expiry_date=expiry))

    with pytest.raises(subject.ProvisioningError, match="^oauth_credentials_expiry_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_access_token_and_expiry_are_optional(tmp_path: Path) -> None:
    value = _payload()
    value.pop("access_token")
    value.pop("expiry_date")
    raw = json.dumps(value).encode("utf-8")
    expected = (
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    anchor, source = _source(tmp_path, raw)

    with subject.snapshot_source_credentials(source, trusted_root=anchor) as snapshot:
        assert _snapshot_bytes(snapshot) == expected


@pytest.mark.parametrize("token_type", ["bearer", "Basic", " Bearer", "Bearer "])
def test_token_type_must_be_exact_bearer(tmp_path: Path, token_type: str) -> None:
    anchor, source = _source(tmp_path, _raw(token_type=token_type))

    with pytest.raises(
        subject.ProvisioningError,
        match="^oauth_credentials_token_type_invalid$",
    ):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


@pytest.mark.parametrize(
    "scope",
    [
        "openid",
        "https://www.googleapis.com/auth/cloud-platform.read-only",
        f"prefix-{subject.CLOUD_PLATFORM_SCOPE}",
    ],
)
def test_scope_requires_exact_cloud_platform_token(tmp_path: Path, scope: str) -> None:
    anchor, source = _source(tmp_path, _raw(scope=scope))

    with pytest.raises(subject.ProvisioningError, match="^oauth_credentials_scope_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_scope_allows_additional_tokens(tmp_path: Path) -> None:
    anchor, source = _source(
        tmp_path,
        _raw(scope=f"openid  {subject.CLOUD_PLATFORM_SCOPE}\tuserinfo.email"),
    )

    with subject.snapshot_source_credentials(source, trusted_root=anchor) as snapshot:
        assert snapshot.metadata.status == "snapshotted"


def test_parse_failure_has_no_secret_bearing_exception_chain_or_traceback_locals(
    tmp_path: Path,
) -> None:
    marker = "PARSE_SECRET_MUST_NOT_SURVIVE"
    raw = b'{"refresh_token":"' + marker.encode("ascii") + b'",}'
    anchor, source = _source(tmp_path, raw)

    with pytest.raises(subject.ProvisioningError) as captured:
        subject.snapshot_source_credentials(source, trusted_root=anchor)

    error = captured.value
    assert error.code == "oauth_credentials_json_invalid"
    assert error.__cause__ is None
    assert error.__context__ is None
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_globals.get("__name__") == subject.__name__:
            rendered = repr(dict(traceback.tb_frame.f_locals)).encode("utf-8", errors="ignore")
            assert marker.encode("ascii") not in rendered
        traceback = traceback.tb_next


def test_deep_json_is_a_fixed_parse_error(tmp_path: Path) -> None:
    prefix = (
        b'{"refresh_token":"r","access_token":"a","token_type":"Bearer",'
        + b'"scope":"'
        + subject.CLOUD_PLATFORM_SCOPE.encode("ascii")
        + b'","expiry_date":1900000000000,"extra":'
    )
    raw = prefix + (b"[" * 2000) + b"0" + (b"]" * 2000) + b"}"
    anchor, source = _source(tmp_path, raw)

    with pytest.raises(subject.ProvisioningError, match="^oauth_credentials_json_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_oversize_input(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path, b"x" * (subject.MAX_CREDENTIAL_BYTES + 1))

    with pytest.raises(subject.ProvisioningError, match="^oauth_credentials_size_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_in_place_change_between_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor, source = _source(tmp_path)
    original_read = subject._read_fd_once
    calls = 0

    def read_then_change(fd: int, *, code: str) -> bytes:
        nonlocal calls
        value = original_read(fd, code=code)
        calls += 1
        if calls == 1:
            source.write_bytes(_raw(access_token="changed-during-snapshot"))
            source.chmod(0o600)
        return value

    monkeypatch.setattr(subject, "_read_fd_once", read_then_change)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_unstable$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_symlink(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    actual = source.with_name("actual.json")
    source.replace(actual)
    source.symlink_to(actual.name)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_file_unsafe$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_hardlink(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    os.link(source, source.with_name("second-link.json"))

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_file_unsafe$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_fifo_without_opening_it_for_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor, source = _source(tmp_path)
    source.unlink()
    os.mkfifo(source, 0o600)

    def forbidden_reader(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("non-regular source reached readable open")

    monkeypatch.setattr(subject, "_open_bound_regular_reader", forbidden_reader)
    with pytest.raises(subject.ProvisioningError, match="^oauth_source_file_unsafe$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_PATH"])
def test_source_snapshot_fails_closed_without_required_linux_primitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    anchor, source = _source(tmp_path)
    monkeypatch.setattr(subject.os, flag, 0)

    with pytest.raises(subject.ProvisioningError, match="^oauth_platform_unsupported$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_non_private_mode(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    source.chmod(0o640)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_mode_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_file_owner_validation_is_exact(tmp_path: Path) -> None:
    _anchor, source = _source(tmp_path)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_owner_invalid$"):
        subject._validate_source_file(source.stat(), expected_uid=os.geteuid() + 1)


def test_source_snapshot_rejects_writable_trusted_parent(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    anchor.chmod(0o770)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_parent_untrusted$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_parent_symlink(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    parent = source.parent
    moved = anchor / "moved"
    parent.replace(moved)
    parent.symlink_to(moved.name, target_is_directory=True)

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_parent_untrusted$"):
        subject.snapshot_source_credentials(source, trusted_root=anchor)


def test_source_snapshot_rejects_traversal_and_untrusted_root(tmp_path: Path) -> None:
    anchor, source = _source(tmp_path)
    traversal = f"{anchor}/credentials/../credentials/{source.name}"

    with pytest.raises(subject.ProvisioningError, match="^oauth_source_path_invalid$"):
        subject.snapshot_source_credentials(traversal, trusted_root=anchor)
    with pytest.raises(subject.ProvisioningError, match="^oauth_source_trust_root_invalid$"):
        subject.snapshot_source_credentials(source, trusted_root=source.parent / "elsewhere")


def test_install_atomically_creates_private_canonical_target(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)

    receipt = subject.install_from_stdin(
        runtime_root,
        io.BytesIO(_raw()),
        expected_uid=os.geteuid(),
    )

    target_parent = runtime_root / "state" / "gemini-oauth"
    target = target_parent / "oauth_creds.json"
    value = target.stat()
    assert target.read_bytes() == _canonical()
    assert stat.S_IMODE(target_parent.stat().st_mode) == 0o700
    assert target_parent.stat().st_uid == os.geteuid()
    assert target_parent.stat().st_gid == os.getegid()
    assert stat.S_IMODE(value.st_mode) == 0o600
    assert value.st_uid == os.geteuid()
    assert value.st_gid == os.getegid()
    assert value.st_nlink == 1
    assert receipt == {
        "schema": subject.CONTRACT,
        "status": "provisioned",
        "sha256": hashlib.sha256(_canonical()).hexdigest(),
        "size_bytes": len(_canonical()),
        "uid": os.geteuid(),
        "gid": value.st_gid,
        "mode": "0600",
    }
    assert set(target_parent.iterdir()) == {
        target,
        target_parent / subject.LOCK_FILE_NAME,
    }
    lock_value = (target_parent / subject.LOCK_FILE_NAME).stat()
    assert stat.S_IMODE(lock_value.st_mode) == 0o600
    assert lock_value.st_uid == os.geteuid()
    assert lock_value.st_gid == os.getegid()
    assert lock_value.st_nlink == 1


def test_install_replaces_existing_private_regular_file(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    target = parent / "oauth_creds.json"
    target.write_bytes(_raw(access_token="old"))
    target.chmod(0o600)
    old_inode = target.stat().st_ino

    subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())

    assert target.read_bytes() == _canonical()
    assert target.stat().st_ino != old_inode


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_install_rejects_unsafe_existing_target(tmp_path: Path, kind: str) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    target = parent / "oauth_creds.json"
    actual = parent / "actual.json"
    actual.write_bytes(_raw())
    actual.chmod(0o600)
    if kind == "symlink":
        target.symlink_to(actual.name)
    else:
        os.link(actual, target)
        if kind == "mode":
            target.unlink()
            target.write_bytes(_raw())
            target.chmod(0o640)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_file_unsafe$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())


def test_install_rejects_existing_target_fifo_without_reading_it(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    os.mkfifo(parent / "oauth_creds.json", 0o600)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_file_unsafe$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "fifo"])
def test_install_rejects_unsafe_lock_file(tmp_path: Path, kind: str) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    lock = parent / subject.LOCK_FILE_NAME
    actual = parent / ".lock-actual"
    if kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        actual.touch(mode=0o600)
        actual.chmod(0o600)
        if kind == "symlink":
            lock.symlink_to(actual.name)
        elif kind == "hardlink":
            os.link(actual, lock)
        else:
            lock.touch(mode=0o640)
            lock.chmod(0o640)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_lock_unsafe$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())
    assert not (parent / "oauth_creds.json").exists()


def test_install_fails_closed_when_runtime_lock_is_held(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    lock = parent / subject.LOCK_FILE_NAME
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    lock_fd = os.open(lock, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(subject.ProvisioningError, match="^oauth_target_lock_busy$"):
            subject.install_from_stdin(
                runtime_root,
                io.BytesIO(_raw()),
                expected_uid=os.geteuid(),
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    assert not (parent / "oauth_creds.json").exists()


@pytest.mark.parametrize("component", ["state", "gemini-oauth"])
def test_install_rejects_symlinked_target_parent(tmp_path: Path, component: str) -> None:
    runtime_root = _runtime_root(tmp_path)
    outside = _private_dir(tmp_path / "outside")
    if component == "state":
        (runtime_root / "state").symlink_to(outside, target_is_directory=True)
        code = "oauth_target_state_unsafe"
    else:
        state = _private_dir(runtime_root / "state")
        (state / "gemini-oauth").symlink_to(outside, target_is_directory=True)
        code = "oauth_target_parent_unsafe"

    with pytest.raises(subject.ProvisioningError, match=f"^{code}$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())


def test_install_rejects_target_parent_wrong_mode(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    parent.chmod(0o750)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_parent_unsafe$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())


def test_runtime_directory_owner_validation_is_exact(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    fd = os.open(runtime_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(subject.ProvisioningError, match="^oauth_target_root_unsafe$"):
            subject._validate_runtime_directory(
                fd,
                expected_uid=os.geteuid() + 1,
                expected_gid=os.getegid(),
                exact_mode=None,
                code="oauth_target_root_unsafe",
            )
        with pytest.raises(subject.ProvisioningError, match="^oauth_target_root_unsafe$"):
            subject._validate_runtime_directory(
                fd,
                expected_uid=os.geteuid(),
                expected_gid=os.getegid() + 1,
                exact_mode=None,
                code="oauth_target_root_unsafe",
            )
    finally:
        os.close(fd)


def test_install_requires_exact_effective_uid_and_gid(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)

    with pytest.raises(subject.ProvisioningError, match="^oauth_provision_uid_invalid$"):
        subject.install_from_stdin(
            runtime_root,
            io.BytesIO(_raw()),
            expected_uid=os.geteuid(),
            expected_gid=os.getegid() + 1,
        )
    assert not (runtime_root / "state").exists()


def test_install_rejects_target_path_traversal(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_path_invalid$"):
        subject.install_from_stdin(
            f"{runtime_root}/../{runtime_root.name}",
            io.BytesIO(_raw()),
            expected_uid=os.geteuid(),
        )


def test_install_detects_post_replace_content_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = _runtime_root(tmp_path)
    original_replace = subject.os.replace

    def replace_then_tamper(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if not source.startswith(".oauth-creds.tmp-"):
            return
        fd = os.open(target, os.O_WRONLY | os.O_TRUNC, dir_fd=dst_dir_fd)
        try:
            os.write(fd, b"{}\n")
            os.fsync(fd)
        finally:
            os.close(fd)

    monkeypatch.setattr(subject.os, "replace", replace_then_tamper)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_verification_failed$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())
    parent = runtime_root / "state" / "gemini-oauth"
    assert not (parent / "oauth_creds.json").exists()
    assert set(parent.iterdir()) == {parent / subject.LOCK_FILE_NAME}


def test_install_detects_post_replace_inode_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = _runtime_root(tmp_path)
    original_replace = subject.os.replace

    def replace_then_swap(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if not source.startswith(".oauth-creds.tmp-"):
            return
        swap_name = ".attacker-swap"
        fd = os.open(swap_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dst_dir_fd)
        try:
            os.write(fd, _canonical())
            os.fsync(fd)
        finally:
            os.close(fd)
        original_replace(swap_name, target, src_dir_fd=dst_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(subject.os, "replace", replace_then_swap)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_rollback_conflict$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())
    target = runtime_root / "state" / "gemini-oauth" / "oauth_creds.json"
    assert target.read_bytes() == _canonical()


def test_install_detects_post_replace_parent_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = _runtime_root(tmp_path)
    original_replace = subject.os.replace

    def replace_then_swap_parent(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if not source.startswith(".oauth-creds.tmp-"):
            return
        state = runtime_root / "state"
        parent = state / "gemini-oauth"
        original_replace(parent, state / "detached-gemini-oauth")
        _private_dir(parent)

    monkeypatch.setattr(subject.os, "replace", replace_then_swap_parent)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_race_detected$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())
    state = runtime_root / "state"
    assert not (state / "gemini-oauth" / "oauth_creds.json").exists()
    assert not (state / "detached-gemini-oauth" / "oauth_creds.json").exists()


def test_install_restores_previous_target_after_post_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    target = parent / "oauth_creds.json"
    previous = _canonical(access_token="previous")
    target.write_bytes(previous)
    target.chmod(0o600)
    previous_inode = target.stat().st_ino
    original_replace = subject.os.replace

    def replace_then_tamper(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if source.startswith(".oauth-creds.tmp-"):
            fd = os.open(destination, os.O_WRONLY | os.O_TRUNC, dir_fd=dst_dir_fd)
            try:
                os.write(fd, b"{}\n")
                os.fsync(fd)
            finally:
                os.close(fd)

    monkeypatch.setattr(subject.os, "replace", replace_then_tamper)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_verification_failed$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())

    assert target.read_bytes() == previous
    assert target.stat().st_ino == previous_inode
    assert set(parent.iterdir()) == {target, parent / subject.LOCK_FILE_NAME}


def test_install_restores_previous_target_when_replace_commits_then_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    target = parent / "oauth_creds.json"
    previous = _canonical(access_token="previous")
    target.write_bytes(previous)
    target.chmod(0o600)
    previous_inode = target.stat().st_ino
    original_replace = subject.os.replace

    def replace_then_raise(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if source.startswith(".oauth-creds.tmp-"):
            raise OSError("synthetic committed replace failure")

    monkeypatch.setattr(subject.os, "replace", replace_then_raise)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_replace_failed$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())

    assert target.read_bytes() == previous
    assert target.stat().st_ino == previous_inode


def test_rollback_never_overwrites_an_independently_changed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = _runtime_root(tmp_path)
    parent = _private_dir(_private_dir(runtime_root / "state") / "gemini-oauth")
    target = parent / "oauth_creds.json"
    target.write_bytes(_canonical(access_token="previous"))
    target.chmod(0o600)
    independently_changed = _canonical(access_token="independent")
    original_replace = subject.os.replace

    def replace_then_independent_change(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if source.startswith(".oauth-creds.tmp-"):
            independent_name = ".independent-change"
            fd = os.open(
                independent_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(fd, independently_changed)
                os.fsync(fd)
            finally:
                os.close(fd)
            original_replace(
                independent_name,
                destination,
                src_dir_fd=dst_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

    monkeypatch.setattr(subject.os, "replace", replace_then_independent_change)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_rollback_conflict$"):
        subject.install_from_stdin(runtime_root, io.BytesIO(_raw()), expected_uid=os.geteuid())

    assert target.read_bytes() == independently_changed
    assert set(parent.iterdir()) == {target, parent / subject.LOCK_FILE_NAME}


def test_cli_success_emits_only_fixed_receipt_metadata(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = subject._run_cli(
        ["install", "--runtime-root", str(runtime_root)],
        stdin=io.BytesIO(_raw()),
        stdout=stdout,
        stderr=stderr,
        expected_uid=os.geteuid(),
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(output)["status"] == "provisioned"
    assert REFRESH_SECRET not in output
    assert ACCESS_SECRET not in output


@pytest.mark.parametrize(
    ("argv", "raw", "expected_error"),
    [
        (["install", "SECRET_ON_ARGV"], b"SECRET_ON_STDIN", "oauth_provision_arguments_invalid"),
        (
            ["install", "--runtime-root", "/does/not/matter"],
            b"SECRET_ON_STDIN",
            "oauth_provision_uid_invalid",
        ),
    ],
)
def test_cli_errors_are_fixed_and_never_echo_argv_or_stdin(
    argv: list[str], raw: bytes, expected_error: str
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    expected_uid = os.geteuid() if expected_error.endswith("arguments_invalid") else os.geteuid() + 1

    exit_code = subject._run_cli(
        argv,
        stdin=io.BytesIO(raw),
        stdout=stdout,
        stderr=stderr,
        expected_uid=expected_uid,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == expected_error + "\n"
    assert "SECRET_ON_ARGV" not in stderr.getvalue()
    assert "SECRET_ON_STDIN" not in stderr.getvalue()


def test_cli_invalid_secret_emits_fixed_code_without_payload(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    secret = b"INVALID_SECRET_PROVIDER_RESPONSE"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = subject._run_cli(
        ["install", "--runtime-root", str(runtime_root)],
        stdin=io.BytesIO(secret),
        stdout=stdout,
        stderr=stderr,
        expected_uid=os.geteuid(),
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "oauth_credentials_json_invalid\n"
    assert secret.decode() not in stderr.getvalue()


def test_cli_rejects_oversize_stdin_without_creating_state(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = subject._run_cli(
        ["install", "--runtime-root", str(runtime_root)],
        stdin=io.BytesIO(b"x" * (subject.MAX_CREDENTIAL_BYTES + 1)),
        stdout=stdout,
        stderr=stderr,
        expected_uid=os.geteuid(),
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "oauth_credentials_size_invalid\n"
    assert not (runtime_root / "state").exists()


def test_stdin_reader_consumes_short_chunks_through_eof(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    payload = _raw()

    class ChunkedInput:
        def __init__(self) -> None:
            self.offset = 0

        def read(self, requested: int) -> bytes:
            if self.offset >= len(payload):
                return b""
            count = min(requested, 7)
            chunk = payload[self.offset : self.offset + count]
            self.offset += len(chunk)
            return chunk

    receipt = subject.install_from_stdin(
        runtime_root,
        ChunkedInput(),  # type: ignore[arg-type]
        expected_uid=os.geteuid(),
    )

    assert receipt["sha256"] == hashlib.sha256(_canonical()).hexdigest()


def test_stdin_reader_rejects_a_stream_that_overreturns_requested_bytes(
    tmp_path: Path,
) -> None:
    runtime_root = _runtime_root(tmp_path)

    class OverreturningInput:
        def read(self, requested: int) -> bytes:
            return b"x" * (requested + 1)

    with pytest.raises(subject.ProvisioningError, match="^oauth_credentials_size_invalid$"):
        subject.install_from_stdin(
            runtime_root,
            OverreturningInput(),  # type: ignore[arg-type]
            expected_uid=os.geteuid(),
        )
    assert not (runtime_root / "state").exists()


def test_target_writer_completes_partial_os_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = _runtime_root(tmp_path)
    original_write = subject.os.write

    def partial_write(fd: int, value: bytes | memoryview) -> int:
        return original_write(fd, value[:7])

    monkeypatch.setattr(subject.os, "write", partial_write)
    receipt = subject.install_from_stdin(
        runtime_root,
        io.BytesIO(_raw()),
        expected_uid=os.geteuid(),
    )

    assert receipt["sha256"] == hashlib.sha256(_canonical()).hexdigest()


def test_target_writer_cleans_temporary_file_after_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = _runtime_root(tmp_path)
    monkeypatch.setattr(subject.os, "write", lambda _fd, _value: 0)

    with pytest.raises(subject.ProvisioningError, match="^oauth_target_write_failed$"):
        subject.install_from_stdin(
            runtime_root,
            io.BytesIO(_raw()),
            expected_uid=os.geteuid(),
        )

    parent = runtime_root / "state" / "gemini-oauth"
    assert set(parent.iterdir()) == {parent / subject.LOCK_FILE_NAME}


def test_cli_rejects_text_stdin_as_fixed_error(tmp_path: Path) -> None:
    runtime_root = _runtime_root(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = subject._run_cli(
        ["install", "--runtime-root", str(runtime_root)],
        stdin=io.StringIO("TEXT_SECRET"),  # type: ignore[arg-type]
        stdout=stdout,
        stderr=stderr,
        expected_uid=os.geteuid(),
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "oauth_credentials_stdin_failed\n"
    assert "TEXT_SECRET" not in stderr.getvalue()


def test_public_cli_is_pinned_to_candidate_uid() -> None:
    if os.geteuid() == subject.TARGET_UID:
        pytest.skip("host already runs as candidate uid")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = subject._run_cli(
        ["install", "--runtime-root", "/runtime"],
        stdin=io.BytesIO(_raw()),
        stdout=stdout,
        stderr=stderr,
        expected_uid=subject.TARGET_UID,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "oauth_provision_uid_invalid\n"
