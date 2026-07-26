from __future__ import annotations

import base64
import importlib.util
import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "capture_blipai_browseract_session.py"
EXPECTED_EMAIL = "operator@example.test"
EXPECTED_SUBJECT = "user-fixture-123"
REFRESH_TOKEN = "refresh-token-fixture-DO-NOT-LEAK"


def _module():
    name = f"capture_blipai_browseract_session_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


INVOCATION_NONCE = _b64url(b"n" * 32)


def _jwt(
    *,
    email: str = EXPECTED_EMAIL,
    subject: str = EXPECTED_SUBJECT,
    issued_at: int | None = None,
    expires_at: int | None = None,
) -> str:
    now = int(time.time())
    issued = now - 30 if issued_at is None else int(issued_at)
    expires = now + 3_600 if expires_at is None else int(expires_at)
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "aud": "authenticated",
        "email": email,
        "exp": expires,
        "iat": issued,
        "iss": "https://hqwmccawtepvundsgnil.supabase.co",
        "role": "authenticated",
        "sub": subject,
    }
    return ".".join(
        (
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
            _b64url(b"fixture-signature"),
        )
    )


def _write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)
    return path


def _fake_browser_act(
    tmp_path: Path,
    *,
    access_token: str,
    refresh_token: str = REFRESH_TOKEN,
    payload_origin: str = "https://www.blipai.app",
    payload_storage_key: str = "sb-hqwmccawtepvundsgnil-auth-token",
    fail_quiescence: bool = False,
) -> tuple[Path, dict[str, Path]]:
    logs = {
        "argv": tmp_path / "browser-argv.json",
        "program": tmp_path / "browser-program.js",
        "output": tmp_path / "browser-output.txt",
    }
    source = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import base64
        import json
        import re
        import sys
        from pathlib import Path

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        ACCESS_TOKEN = {access_token!r}
        REFRESH_TOKEN = {refresh_token!r}
        PAYLOAD_ORIGIN = {payload_origin!r}
        PAYLOAD_STORAGE_KEY = {payload_storage_key!r}
        ARGV_LOG = Path({os.fspath(logs["argv"])!r})
        PROGRAM_LOG = Path({os.fspath(logs["program"])!r})
        OUTPUT_LOG = Path({os.fspath(logs["output"])!r})
        STATE_FILE = Path({os.fspath(tmp_path / "browser-quiesced.state")!r})
        FAIL_QUIESCENCE = {fail_quiescence!r}

        def b64url_encode(value):
            return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

        def b64url_decode(value):
            return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))

        program = sys.stdin.read()
        with ARGV_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sys.argv) + "\\n")
        with PROGRAM_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(program) + "\\n")
        if "EA_BLIP_CAPTURE_CAS_QUIESCED_V1:" in program:
            challenge_match = re.search(
                r'const challenge = "([A-Za-z0-9_-]{{32}})";',
                program,
            )
            if (
                FAIL_QUIESCENCE
                or challenge_match is None
                or not STATE_FILE.exists()
                or STATE_FILE.read_text(encoding="ascii")
                != challenge_match.group(1)
                or "localStorage.removeItem(storageKey)" not in program
                or "delete globalThis[handoffKey]" not in program
                or "location.replace(target)" not in program
            ):
                raise SystemExit(42)
            STATE_FILE.write_text(
                "navigated:" + challenge_match.group(1),
                encoding="ascii",
            )
            output = (
                "EA_BLIP_CAPTURE_CAS_QUIESCED_V1:"
                + challenge_match.group(1)
                + "\\n"
            )
            with OUTPUT_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(output) + "\\n")
            sys.stdout.write(output)
            raise SystemExit(0)
        if "EA_BLIP_CAPTURE_QUIESCED_V1:" in program:
            challenge_match = re.search(
                r'const challenge = "([A-Za-z0-9_-]{{32}})";',
                program,
            )
            if (
                FAIL_QUIESCENCE
                or challenge_match is None
                or not STATE_FILE.exists()
                or STATE_FILE.read_text(encoding="ascii")
                != "navigated:" + challenge_match.group(1)
            ):
                raise SystemExit(42)
            output = (
                "EA_BLIP_CAPTURE_QUIESCED_V1:"
                + challenge_match.group(1)
                + "\\n"
            )
            with OUTPUT_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(output) + "\\n")
            sys.stdout.write(output)
            raise SystemExit(0)
        public_match = re.search(r'const publicKeyB64 = "([^"]+)";', program)
        aad_match = re.search(r'const aadB64 = "([^"]+)";', program)
        if public_match is None or aad_match is None:
            raise SystemExit(41)
        public_key = serialization.load_der_public_key(
            b64url_decode(public_match.group(1))
        )
        aad = b64url_decode(aad_match.group(1))
        binding = json.loads(aad.decode("utf-8"))
        payload = {{
            "access_token": ACCESS_TOKEN,
            "alg": binding["alg"],
            "challenge": binding["challenge"],
            "origin": PAYLOAD_ORIGIN,
            "refresh_token": REFRESH_TOKEN,
            "schema": binding["schema"],
            "session": binding["session"],
            "storage_key": PAYLOAD_STORAGE_KEY,
            "version": binding["version"],
        }}
        aes_key = AESGCM.generate_key(bit_length=256)
        iv = b"fixture-iv12"
        ciphertext = AESGCM(aes_key).encrypt(
            iv,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            aad,
        )
        wrapped_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=aad,
            ),
        )
        envelope = {{
            "alg": binding["alg"],
            "challenge": binding["challenge"],
            "ciphertext": b64url_encode(ciphertext),
            "iv": b64url_encode(iv),
            "version": binding["version"],
            "wrapped_key": b64url_encode(wrapped_key),
        }}
        output = (
            "EA_BLIP_CAPTURE_ENVELOPE_V1:"
            + b64url_encode(
                json.dumps(envelope, separators=(",", ":")).encode("utf-8")
            )
            + "\\n"
        )
        if (
            "Object.defineProperty(globalThis, handoffKey" not in program
            or "localStorage.removeItem(storageKey)" in program
            or "location.replace(" in program
        ):
            raise SystemExit(43)
        STATE_FILE.write_text(binding["challenge"], encoding="ascii")
        with OUTPUT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(output) + "\\n")
        sys.stdout.write(output)
        """
    )
    return _write_executable(tmp_path / "fake-browser-act", source), logs


def _fake_docker(
    tmp_path: Path,
    *,
    fail_final: bool = False,
) -> tuple[Path, dict[str, Path]]:
    logs = {
        "calls": tmp_path / "docker-calls.jsonl",
        "stdin": tmp_path / "docker-stdin.jsonl",
        "output": tmp_path / "docker-output.txt",
    }
    source = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import json
        import sys
        from pathlib import Path

        CALLS_LOG = Path({os.fspath(logs["calls"])!r})
        STDIN_LOG = Path({os.fspath(logs["stdin"])!r})
        OUTPUT_LOG = Path({os.fspath(logs["output"])!r})
        FAIL_FINAL = {fail_final!r}

        body = sys.stdin.buffer.read().decode("utf-8")
        with CALLS_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sys.argv) + "\\n")
        with STDIN_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body) + "\\n")
        if "--interactive" not in sys.argv and "-i" not in sys.argv:
            output = "EA_BLIP_TOKEN_STATE_FAIL\\n"
            OUTPUT_LOG.write_text(output, encoding="utf-8")
            sys.stdout.write(output)
            raise SystemExit(24)
        is_final = any(
            item.endswith("/memorial_blipai_shadow_stt_tokens.json")
            for item in sys.argv
        )
        if FAIL_FINAL and is_final:
            output = "EA_BLIP_TOKEN_STATE_FAIL\\n"
            OUTPUT_LOG.write_text(output, encoding="utf-8")
            sys.stdout.write(output)
            raise SystemExit(23)
        output = "EA_BLIP_TOKEN_STATE_OK\\n"
        OUTPUT_LOG.write_text(output, encoding="utf-8")
        sys.stdout.write(output)
        """
    )
    return _write_executable(tmp_path / "fake-docker", source), logs


def _operator_args(
    *,
    state_dir: Path,
    receipt: Path,
    api_key_file: Path | None = None,
) -> list[str]:
    args = [
        "--session",
        "owned-blip-session",
        "--expected-email",
        EXPECTED_EMAIL,
        "--state-dir",
        os.fspath(state_dir),
        "--receipt",
        os.fspath(receipt),
        "--invocation-nonce",
        INVOCATION_NONCE,
        "--operator-confirmed-session-owned-and-remote-assist-released",
        "--operator-confirmed-dedicated-session-and-no-other-blip-tabs",
    ]
    if api_key_file is not None:
        args.extend(["--supabase-api-key-file", os.fspath(api_key_file)])
    return args


def _use_fake_executables(
    module,
    monkeypatch: pytest.MonkeyPatch,
    *,
    browser_act: Path,
    docker: Path,
) -> None:
    monkeypatch.setattr(
        module,
        "CANONICAL_BROWSER_ACT_BIN",
        os.fspath(browser_act),
    )
    monkeypatch.setattr(
        module,
        "CANONICAL_DOCKER_BIN",
        os.fspath(docker),
    )


def _prepared_state_dir(
    module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    state_dir = tmp_path / "runtime-state"
    state_dir.mkdir(mode=0o700)
    state_dir.chmod(0o700)
    monkeypatch.setattr(module, "EXPECTED_RUNTIME_UID", os.geteuid())
    monkeypatch.setattr(module, "EXPECTED_RUNTIME_GID", os.getegid())
    return state_dir


def _read_json_lines(path: Path) -> list[object]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _assert_no_credentials(values: list[str], *surfaces: str) -> None:
    for surface in surfaces:
        for value in values:
            assert value not in surface


def _assert_receipt_has_no_credential_metadata(
    receipt: dict[str, object],
    receipt_text: str,
    *,
    sensitive_values: list[str],
) -> None:
    forbidden_keys = {
        "access_token",
        "credential_hash",
        "credential_length",
        "email",
        "expires_at",
        "issued_at",
        "refresh_token",
        "session_id",
        "subject",
        "token_hash",
        "token_length",
        "user_id",
    }

    def _walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)

    _walk(receipt)
    _assert_no_credentials(sensitive_values, receipt_text)


def _api_key_file(tmp_path: Path) -> Path:
    path = tmp_path / "supabase-public-api-key"
    path.write_text("public-anon-fixture\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_base64url_decoder_rejects_noncanonical_trailing_bits() -> None:
    module = _module()

    assert module._b64url_decode("AA", maximum=1, error="invalid") == b"\x00"
    with pytest.raises(module.CaptureFailure, match="^invalid$"):
        module._b64url_decode("AB", maximum=1, error="invalid")


def test_fresh_session_is_encrypt_first_and_child_tokens_reach_only_docker_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    access_token = _jwt()
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    api_key_file = _api_key_file(tmp_path)
    observed_user_validation: dict[str, str] = {}

    def _validate_user_session(**kwargs):
        observed_user_validation.update(
            {
                "access_token": str(kwargs["access_token"]),
                "api_key": str(kwargs["api_key"]),
                "expected_email": str(kwargs["expected_email"]),
                "expected_subject": str(kwargs["expected_subject"]),
            }
        )

    monkeypatch.setattr(module, "_validate_user_session", _validate_user_session)

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=api_key_file,
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    browser_argv = browser_logs["argv"].read_text(encoding="utf-8")
    browser_program = browser_logs["program"].read_text(encoding="utf-8")
    browser_output = browser_logs["output"].read_text(encoding="utf-8")
    docker_calls = docker_logs["calls"].read_text(encoding="utf-8")
    docker_stdin = docker_logs["stdin"].read_text(encoding="utf-8")

    assert result == 0
    assert receipt["status"] == "capture_complete"
    assert receipt["invocation_nonce"] == INVOCATION_NONCE
    assert receipt["local_refresh"] == "not_needed"
    assert receipt["provider_validation"] == "user_endpoint"
    assert receipt["runtime_preflight"] == "pass"
    assert receipt["protected_original_save_reload"] == "pass"
    assert receipt["rotated_overwrite_save_reload"] == "not_needed"
    assert receipt["protected_runtime_provider_currentness"] == (
        "captured_original_provider_validated"
    )
    assert receipt["runtime_save_reload"] == "pass"
    assert receipt["runtime_secrets_included"] is False
    assert receipt["credential_metadata_included"] is False
    assert receipt["capture_helper_persisted_browser_output"] is False
    assert receipt["browser_tool_output_retention"] == "not_asserted"
    assert receipt["browser_session_quiescence"] == (
        "exact_storage_cas_cleared_and_page_replaced"
    )
    assert receipt["token_family_ownership"] == "not_independently_proven"
    assert receipt["separate_ownership_gate_required"] is True
    assert "browser_output_persisted" not in receipt
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    browser_outputs = _read_json_lines(browser_logs["output"])
    assert len(browser_outputs) == 3
    assert str(browser_outputs[0]).startswith("EA_BLIP_CAPTURE_ENVELOPE_V1:")
    assert str(browser_outputs[1]).startswith(
        "EA_BLIP_CAPTURE_CAS_QUIESCED_V1:"
    )
    assert str(browser_outputs[2]).startswith("EA_BLIP_CAPTURE_QUIESCED_V1:")
    assert len(_read_json_lines(browser_logs["argv"])) == 3
    assert access_token in docker_stdin
    assert REFRESH_TOKEN in docker_stdin
    assert len(_read_json_lines(docker_logs["calls"])) == 2
    assert observed_user_validation == {
        "access_token": access_token,
        "api_key": "public-anon-fixture",
        "expected_email": EXPECTED_EMAIL,
        "expected_subject": EXPECTED_SUBJECT,
    }
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN, "public-anon-fixture"],
        browser_argv,
        browser_program,
        browser_output,
        docker_calls,
        captured_stdout,
        receipt_text,
    )
    assert EXPECTED_EMAIL not in receipt_text
    assert EXPECTED_SUBJECT not in receipt_text
    assert "expires_at" not in receipt_text
    assert "token_sha" not in receipt_text
    _assert_receipt_has_no_credential_metadata(
        receipt,
        receipt_text,
        sensitive_values=[
            access_token,
            REFRESH_TOKEN,
            EXPECTED_EMAIL,
            EXPECTED_SUBJECT,
            "public-anon-fixture",
        ],
    )

    call_argv = _read_json_lines(docker_logs["calls"])
    for argv in call_argv:
        assert "--pull=never" in argv
        assert "--interactive" in argv
        assert "--network=none" in argv
        assert "--read-only" in argv
        tmpfs_index = argv.index("--tmpfs")
        assert argv[tmpfs_index + 1] == (
            "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777"
        )
        assert "--cap-drop=ALL" in argv
        assert "--security-opt=no-new-privileges" in argv
        assert "--log-driver=none" in argv
        assert f"--user={os.geteuid()}:{os.getegid()}" in argv
        mount_index = argv.index("--mount")
        assert argv[mount_index + 1].endswith(
            f",dst={module.CONTAINER_STATE_DIR}"
        )
        assert ",rw" not in argv[mount_index + 1]


@pytest.mark.parametrize(
    ("payload_origin", "token_email", "expected_error"),
    [
        ("https://wrong.example.test", EXPECTED_EMAIL, "browser_capture_binding_invalid"),
        (
            "https://www.blipai.app",
            "different-account@example.test",
            "captured_token_claims_invalid",
        ),
    ],
)
def test_wrong_origin_or_account_allows_only_secret_free_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload_origin: str,
    token_email: str,
    expected_error: str,
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    access_token = _jwt(email=token_email)
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
        payload_origin=payload_origin,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    api_key_file = _api_key_file(tmp_path)

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=api_key_file,
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert result == 1
    assert receipt["status"] == "fail"
    assert receipt["error_code"] == expected_error
    docker_calls = docker_logs["calls"].read_text(encoding="utf-8")
    assert len(_read_json_lines(docker_logs["calls"])) == 1
    assert ".blipai-capture-preflight-" in docker_calls
    assert FINAL_STATE_NAME_FOR_TEST not in docker_calls
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN],
        browser_logs["argv"].read_text(encoding="utf-8"),
        browser_logs["program"].read_text(encoding="utf-8"),
        browser_logs["output"].read_text(encoding="utf-8"),
        docker_calls,
        captured_stdout,
        receipt_text,
    )
    assert token_email not in receipt_text
    assert EXPECTED_SUBJECT not in receipt_text
    _assert_receipt_has_no_credential_metadata(
        receipt,
        receipt_text,
        sensitive_values=[
            access_token,
            REFRESH_TOKEN,
            token_email,
            EXPECTED_SUBJECT,
            "public-anon-fixture",
        ],
    )


def test_refresh_failure_leaves_verified_original_pair_protected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    now = int(time.time())
    access_token = _jwt(issued_at=now - 3_700, expires_at=now - 100)
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    api_key_file = _api_key_file(tmp_path)

    def _fail_refresh(**_kwargs):
        raise module.CaptureFailure("refresh_failed")

    monkeypatch.setattr(module, "_refresh_session", _fail_refresh)
    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=api_key_file,
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    docker_calls = docker_logs["calls"].read_text(encoding="utf-8")
    assert result == 1
    assert receipt["status"] == "fail"
    assert receipt["error_code"] == "refresh_failed"
    assert len(_read_json_lines(docker_logs["calls"])) == 2
    assert ".blipai-capture-preflight-" in docker_calls
    assert FINAL_STATE_NAME_FOR_TEST in docker_calls
    assert receipt["runtime_preflight"] == "pass"
    assert receipt["protected_original_save_reload"] == "pass"
    assert receipt["runtime_save_reload"] == "protected_original_pass"
    assert receipt["browser_session_quiescence"] == (
        "exact_storage_cas_cleared_and_page_replaced"
    )
    assert receipt["local_refresh"] == "single_attempt_started_result_unproven"
    assert receipt["rotated_overwrite_save_reload"] == "unproven"
    assert receipt["protected_runtime_provider_currentness"] == (
        "unknown_after_refresh_attempt"
    )
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN],
        browser_logs["argv"].read_text(encoding="utf-8"),
        browser_logs["program"].read_text(encoding="utf-8"),
        browser_logs["output"].read_text(encoding="utf-8"),
        docker_calls,
        captured_stdout,
        receipt_text,
    )
    _assert_receipt_has_no_credential_metadata(
        receipt,
        receipt_text,
        sensitive_values=[
            access_token,
            REFRESH_TOKEN,
            EXPECTED_EMAIL,
            EXPECTED_SUBJECT,
            "public-anon-fixture",
        ],
    )


def test_docker_final_save_failure_retries_and_never_surfaces_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    access_token = _jwt()
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
    )
    docker, docker_logs = _fake_docker(tmp_path, fail_final=True)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    api_key_file = _api_key_file(tmp_path)

    def _validate_user_session(**_kwargs):
        return None

    monkeypatch.setattr(module, "_validate_user_session", _validate_user_session)

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=api_key_file,
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    docker_calls = docker_logs["calls"].read_text(encoding="utf-8")
    assert result == 1
    assert json.loads(receipt_text)["error_code"] == "runtime_state_write_failed"
    assert len(_read_json_lines(docker_logs["calls"])) == 3
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN],
        browser_logs["argv"].read_text(encoding="utf-8"),
        browser_logs["program"].read_text(encoding="utf-8"),
        browser_logs["output"].read_text(encoding="utf-8"),
        docker_calls,
        captured_stdout,
        receipt_text,
    )
    _assert_receipt_has_no_credential_metadata(
        json.loads(receipt_text),
        receipt_text,
        sensitive_values=[
            access_token,
            REFRESH_TOKEN,
            EXPECTED_EMAIL,
            EXPECTED_SUBJECT,
            "public-anon-fixture",
        ],
    )


def test_missing_api_key_fails_before_browser_or_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    access_token = _jwt()
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert result == 1
    assert receipt["error_code"] == "supabase_api_key_required"
    assert not browser_logs["argv"].exists()
    assert not docker_logs["calls"].exists()
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN],
        captured_stdout,
        receipt_text,
    )
    _assert_receipt_has_no_credential_metadata(
        receipt,
        receipt_text,
        sensitive_values=[
            access_token,
            REFRESH_TOKEN,
            EXPECTED_EMAIL,
            EXPECTED_SUBJECT,
        ],
    )


def test_refresh_request_has_no_stale_bearer_and_uses_one_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    requests = []
    refreshed_access = _jwt()

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return module.REFRESH_URL

        def read(self, _maximum):
            return json.dumps(
                {
                    "access_token": refreshed_access,
                    "refresh_token": "rotated-refresh-token",
                    "user": {
                        "id": EXPECTED_SUBJECT,
                        "email": EXPECTED_EMAIL,
                    },
                }
            ).encode("utf-8")

    class _Opener:
        def open(self, request, *, timeout):
            assert timeout == 20
            requests.append(request)
            return _Response()

    monkeypatch.setattr(
        module.urllib.request,
        "build_opener",
        lambda *_handlers: _Opener(),
    )

    material = module._refresh_once(
        refresh_token=REFRESH_TOKEN,
        api_key="public-anon-fixture",
    )

    assert material.refresh_token == "rotated-refresh-token"
    assert len(requests) == 1
    request = requests[0]
    headers = {name.lower(): value for name, value in request.header_items()}
    assert "authorization" not in headers
    assert headers["apikey"] == "public-anon-fixture"
    assert json.loads(request.data.decode("utf-8")) == {
        "refresh_token": REFRESH_TOKEN
    }


@pytest.mark.parametrize("failure_after_response", [False, True])
def test_refresh_session_never_retries_a_refresh_token(
    failure_after_response: bool,
) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _once(**kwargs):
        calls.append(dict(kwargs))
        if not failure_after_response:
            raise module.CaptureFailure("refresh_failed")
        return module.RefreshedMaterial(
            access_token=_jwt(),
            refresh_token="rotated-refresh-token",
            subject="wrong-subject",
            email=EXPECTED_EMAIL,
        )

    with pytest.raises(module.CaptureFailure):
        module._refresh_session(
            access_token=_jwt(),
            refresh_token=REFRESH_TOKEN,
            api_key="public-anon-fixture",
            expected_email=EXPECTED_EMAIL,
            expected_subject=EXPECTED_SUBJECT,
            refresh_once=_once,
        )

    assert len(calls) == 1
    assert calls[0] == {
        "refresh_token": REFRESH_TOKEN,
        "api_key": "public-anon-fixture",
    }


def test_api_key_open_is_fstat_bound_to_the_lstat_inode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    api_key_file = _api_key_file(tmp_path)
    real_fstat = os.fstat
    calls = 0

    def _mismatched_fstat(descriptor):
        nonlocal calls
        calls += 1
        metadata = real_fstat(descriptor)
        if calls != 1:
            return metadata
        return SimpleNamespace(
            st_mode=metadata.st_mode,
            st_dev=metadata.st_dev,
            st_ino=metadata.st_ino + 1,
            st_uid=metadata.st_uid,
            st_gid=metadata.st_gid,
            st_nlink=metadata.st_nlink,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns,
            st_ctime_ns=metadata.st_ctime_ns,
        )

    monkeypatch.setattr(module.os, "fstat", _mismatched_fstat)

    with pytest.raises(
        module.CaptureFailure,
        match="^refresh_api_key_file_invalid$",
    ):
        module._read_api_key_file(api_key_file)


def test_api_key_open_is_nonblocking_and_does_not_follow_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    api_key_file = _api_key_file(tmp_path)
    real_open = os.open
    observed_flags: list[int] = []

    def _recording_open(path, flags, *args, **kwargs):
        if Path(os.fspath(path)) == api_key_file:
            observed_flags.append(int(flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", _recording_open)

    assert module._read_api_key_file(api_key_file) == "public-anon-fixture"
    assert len(observed_flags) == 1
    assert observed_flags[0] & os.O_NOFOLLOW
    assert observed_flags[0] & os.O_NONBLOCK


def test_blocked_child_stdin_is_governed_by_the_process_deadline() -> None:
    module = _module()
    started = time.monotonic()

    with pytest.raises(module.CaptureFailure, match="^bounded_failure$"):
        module._run_bounded_process(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(10)",
            ],
            stdin_bytes=b"x" * (8 * 1024 * 1024),
            environment={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            stdout_limit=1_024,
            stderr_limit=1_024,
            timeout=1,
            error="bounded_failure",
        )

    assert time.monotonic() - started < 3


def test_host_validation_does_not_traverse_the_uid10001_final_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    final_target = state_dir / module.FINAL_STATE_NAME
    real_lstat = os.lstat

    def _untraversable_child(path, *args, **kwargs):
        if Path(os.fspath(path)) == final_target:
            raise PermissionError("simulated 0700 UID10001 child")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "lstat", _untraversable_child)

    assert module._validate_state_dir(state_dir) == state_dir
    assert "os.lstat(path)" in module._CONTAINER_STATE_HELPER
    assert "metadata.st_uid == EXPECTED_UID" in module._CONTAINER_STATE_HELPER
    assert "metadata.st_gid == EXPECTED_GID" in module._CONTAINER_STATE_HELPER
    assert "metadata.st_nlink == 1" in module._CONTAINER_STATE_HELPER
    assert "stat.S_IMODE(metadata.st_mode) == 0o600" in (
        module._CONTAINER_STATE_HELPER
    )


def test_production_parser_rejects_arbitrary_executable_overrides(
    tmp_path: Path,
) -> None:
    module = _module()
    parser = module.build_parser()
    args = _operator_args(
        state_dir=tmp_path / "state",
        receipt=tmp_path / "receipt.json",
        api_key_file=tmp_path / "key",
    )

    with pytest.raises(SystemExit):
        parser.parse_args(args + ["--browser-act-bin", "/tmp/fake"])
    with pytest.raises(SystemExit):
        parser.parse_args(args + ["--docker-bin", "/tmp/fake"])


def test_canonical_executable_validation_rejects_a_symlink(
    tmp_path: Path,
) -> None:
    module = _module()
    executable = _write_executable(
        tmp_path / "real-executable",
        "#!/bin/sh\nexit 0\n",
    )
    symlink = tmp_path / "executable-link"
    symlink.symlink_to(executable)

    with pytest.raises(module.CaptureFailure, match="^executable_invalid$"):
        module._validate_canonical_executable(
            os.fspath(symlink),
            allowed_uids=frozenset({os.geteuid()}),
            error="executable_invalid",
        )


def test_existing_receipt_is_not_overwritten_and_nonce_disambiguates_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=_jwt(),
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    stale_nonce = _b64url(b"s" * 32)
    stale_text = json.dumps(
        {"status": "pass", "invocation_nonce": stale_nonce},
        sort_keys=True,
    )
    receipt_path.write_text(stale_text, encoding="utf-8")
    receipt_path.chmod(0o600)

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=_api_key_file(tmp_path),
        )
    )

    stdout_receipt = json.loads(capsys.readouterr().out)
    assert result == 1
    assert receipt_path.read_text(encoding="utf-8") == stale_text
    assert stdout_receipt["status"] == "fail"
    assert stdout_receipt["invocation_nonce"] == INVOCATION_NONCE
    assert stdout_receipt["error_code"] == "receipt_write_failed"
    assert stale_nonce != INVOCATION_NONCE
    assert not browser_logs["argv"].exists()
    assert not docker_logs["calls"].exists()


def test_noncanonical_invocation_nonce_fails_before_browser_and_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=_jwt(),
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"
    args = _operator_args(
        state_dir=state_dir,
        receipt=receipt_path,
        api_key_file=_api_key_file(tmp_path),
    )
    args[args.index("--invocation-nonce") + 1] = ("A" * 42) + "B"

    result = module.main(args)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert result == 1
    assert receipt["error_code"] == "invocation_nonce_invalid"
    assert receipt["invocation_nonce"] == ("A" * 42) + "B"
    assert json.loads(capsys.readouterr().out) == receipt
    assert not browser_logs["argv"].exists()
    assert not docker_logs["calls"].exists()


def test_quiescence_failure_occurs_only_after_original_pair_is_protected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    access_token = _jwt()
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=access_token,
        fail_quiescence=True,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )
    receipt_path = tmp_path / "capture-receipt.json"

    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=_api_key_file(tmp_path),
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert result == 1
    assert receipt["error_code"] == "browser_quiescence_failed"
    assert receipt["runtime_preflight"] == "pass"
    assert receipt["browser_capture"] == "encrypted_and_bound"
    assert receipt["protected_original_save_reload"] == "pass"
    assert receipt["runtime_save_reload"] == "protected_original_pass"
    assert receipt["protected_runtime_provider_currentness"] == (
        "captured_original_saved_not_yet_provider_validated"
    )
    assert receipt["browser_session_quiescence"] == "unproven"
    assert len(_read_json_lines(docker_logs["calls"])) == 2
    assert len(_read_json_lines(browser_logs["argv"])) == 2
    _assert_no_credentials(
        [access_token, REFRESH_TOKEN],
        browser_logs["argv"].read_text(encoding="utf-8"),
        browser_logs["program"].read_text(encoding="utf-8"),
        browser_logs["output"].read_text(encoding="utf-8"),
        docker_logs["calls"].read_text(encoding="utf-8"),
        captured_stdout,
        receipt_text,
    )


def test_preflight_and_original_save_precede_quiescence_and_provider_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    events: list[str] = []
    access_token = _jwt()
    config = module.CaptureConfig(
        session="owned-blip-session",
        expected_email=EXPECTED_EMAIL,
        image_id=module.DEFAULT_IMAGE_ID,
        state_dir=tmp_path,
        receipt_path=tmp_path / "unused-receipt.json",
        invocation_nonce=INVOCATION_NONCE,
        supabase_api_key_file=tmp_path / "unused-key",
        operator_confirmed=True,
        dedicated_session_confirmed=True,
    )
    monkeypatch.setattr(module, "_validate_config", lambda value: value)
    monkeypatch.setattr(
        module,
        "_read_api_key_file",
        lambda _path: events.append("api_key") or "api-key",
    )
    monkeypatch.setattr(
        module,
        "_preflight_runtime_state",
        lambda *_args, **_kwargs: events.append("preflight"),
    )
    monkeypatch.setattr(
        module,
        "_capture_browser_session",
        lambda _config: (
            events.append("capture") or access_token,
            REFRESH_TOKEN,
            "Y2hhbGxlbmdlLWZpeHR1cmUtMTIz",
        ),
    )
    monkeypatch.setattr(
        module,
        "_save_runtime_state_with_retries",
        lambda *_args, **_kwargs: events.append("save_original"),
    )
    monkeypatch.setattr(
        module,
        "_quiesce_browser_session",
        lambda *_args, **_kwargs: events.append("cas_quiesce"),
    )
    monkeypatch.setattr(
        module,
        "_verify_browser_quiescence",
        lambda *_args, **_kwargs: events.append("verify_quiescence"),
    )
    monkeypatch.setattr(
        module,
        "_validate_user_session",
        lambda **_kwargs: events.append("provider_validate"),
    )

    receipt = module._run_capture(config)

    assert receipt["status"] == "capture_complete"
    assert events == [
        "api_key",
        "preflight",
        "capture",
        "save_original",
        "cas_quiesce",
        "verify_quiescence",
        "provider_validate",
    ]


def test_expired_rotation_overwrites_only_after_original_pair_is_protected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    state_dir = _prepared_state_dir(module, monkeypatch, tmp_path)
    now = int(time.time())
    original_access = _jwt(issued_at=now - 3_700, expires_at=now - 100)
    rotated_access = _jwt()
    rotated_refresh = "rotated-refresh-token-fixture"
    browser_act, browser_logs = _fake_browser_act(
        tmp_path,
        access_token=original_access,
    )
    docker, docker_logs = _fake_docker(tmp_path)
    _use_fake_executables(
        module,
        monkeypatch,
        browser_act=browser_act,
        docker=docker,
    )

    def _refresh_session(**_kwargs):
        return rotated_access, rotated_refresh

    monkeypatch.setattr(module, "_refresh_session", _refresh_session)
    receipt_path = tmp_path / "capture-receipt.json"
    result = module.main(
        _operator_args(
            state_dir=state_dir,
            receipt=receipt_path,
            api_key_file=_api_key_file(tmp_path),
        )
    )

    captured_stdout = capsys.readouterr().out
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    stdin_payloads = [
        json.loads(value)
        for value in _read_json_lines(docker_logs["stdin"])
    ]
    assert result == 0
    assert receipt["status"] == "capture_complete"
    assert receipt["protected_original_save_reload"] == "pass"
    assert receipt["local_refresh"] == "pass"
    assert receipt["provider_validation"] == "refresh"
    assert receipt["rotated_overwrite_save_reload"] == "pass"
    assert receipt["protected_runtime_provider_currentness"] == (
        "rotated_pair_saved_and_reloaded"
    )
    assert len(stdin_payloads) == 3
    assert stdin_payloads[1] == {
        "access_token": original_access,
        "refresh_token": REFRESH_TOKEN,
    }
    assert stdin_payloads[2] == {
        "access_token": rotated_access,
        "refresh_token": rotated_refresh,
    }
    _assert_no_credentials(
        [
            original_access,
            REFRESH_TOKEN,
            rotated_access,
            rotated_refresh,
        ],
        browser_logs["argv"].read_text(encoding="utf-8"),
        browser_logs["program"].read_text(encoding="utf-8"),
        browser_logs["output"].read_text(encoding="utf-8"),
        docker_logs["calls"].read_text(encoding="utf-8"),
        captured_stdout,
        receipt_text,
    )


FINAL_STATE_NAME_FOR_TEST = "memorial_blipai_shadow_stt_tokens.json"
