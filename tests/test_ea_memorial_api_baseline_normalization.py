from __future__ import annotations

import json
import os
import pwd
import stat
import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pytest

from scripts import deploy_ea_memorial as deploy
from scripts import execute_ea_memorial_api_baseline_normalization as normalization


REVISION = "1" * 40
IMAGE_ID = f"sha256:{'2' * 64}"
CONFIG_HASH = "3" * 64
MANIFEST_SHA256 = "4" * 64
PLAN_SHA256 = "5" * 64


def _live_api_render_input() -> dict[str, Any]:
    return {
        "Config": {
            "Image": "ea-runtime:memorial-main-111111111111",
            "Env": [
                f"EA_SOURCE_REVISION={REVISION}",
                "EA_ENABLE_PUBLIC_MEMORIALS=1",
                "EA_HEALTHCHECK_MEMORIAL_SLUG=manfred",
                "EA_PUBLIC_MEMORIAL_RATE_BACKEND=redis",
                "EA_PUBLIC_MEMORIAL_REDIS_URL=redis://private.invalid:6379/0",
                "EA_PUBLIC_MEMORIAL_DIR=/data/memorial_data/public_memorials",
                "EA_PRIVATE_MEMORIAL_PROFILE_DIR=/data/memorial_data/private_memorial_profiles",
                "EA_MEMORIAL_LIVE_TTS_PLUGIN=unmixr_clone",
                "EA_TRUSTED_PROXY_CIDRS=172.30.0.0/16,127.0.0.1/32",
                "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES=origin.example.invalid",
                "EA_ALLOWED_PUBLIC_HOSTS=example.invalid,www.example.invalid",
            ],
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/srv/memorial/release",
                "Destination": "/data/memorial_data",
                "RW": False,
            },
            *[
                {
                    "Type": "bind",
                    "Source": f"/srv/memorial/runtime/{leaf}",
                    "Destination": f"/data/memorial-writable/{leaf}",
                    "RW": True,
                }
                for leaf in (
                    "public-contributions",
                    "private-contributions",
                    "state",
                )
            ],
        ],
    }


class StaticJournal:
    def __init__(self, active: Mapping[str, Any] | None = None) -> None:
        self.active = None if active is None else dict(active)

    def read(self) -> dict[str, Any] | None:
        return None if self.active is None else dict(self.active)


class RecordingRunner:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[tuple[list[str], Path, dict[str, str], bool]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = list(args)
        self.calls.append((command, cwd, dict(env), check))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, 0, "", "")


class OrderingJournal:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.current: dict[str, Any] | None = None

    def read(self) -> dict[str, Any] | None:
        return None if self.current is None else dict(self.current)

    def create(self, payload: Mapping[str, Any]) -> None:
        assert self.current is None
        self.current = dict(payload)
        self.events.append("journal:create")

    def with_phase(
        self, payload: Mapping[str, Any], phase: str, *, now: str
    ) -> dict[str, Any]:
        replacement = dict(payload)
        replacement["phase"] = phase
        replacement["updated_at"] = now
        return replacement

    def update(
        self,
        *,
        expected: Mapping[str, Any],
        replacement: Mapping[str, Any],
    ) -> None:
        assert self.current == dict(expected)
        before_phase = expected.get("phase")
        after_phase = replacement.get("phase")
        if before_phase != after_phase:
            self.events.append(f"journal:phase:{after_phase}")
        elif expected.get("protected_image_recorded") != replacement.get(
            "protected_image_recorded"
        ):
            self.events.append("journal:evidence:protected")
        elif expected.get("api_mutation_recorded") != replacement.get(
            "api_mutation_recorded"
        ):
            self.events.append("journal:evidence:api")
        elif expected.get("terminal_evidence_recorded") != replacement.get(
            "terminal_evidence_recorded"
        ):
            self.events.append("journal:evidence:terminal")
        self.current = dict(replacement)

    def record_protected_image(
        self,
        payload: Mapping[str, Any],
        *,
        observed_image_id: str,
        observed_rollback_tag: str,
        now: str,
    ) -> dict[str, Any]:
        replacement = dict(payload)
        replacement.update(
            {
                "protected_image_recorded": True,
                "observed_image_id": observed_image_id,
                "observed_rollback_tag": observed_rollback_tag,
                "updated_at": now,
            }
        )
        return replacement

    def record_api_mutation(
        self,
        payload: Mapping[str, Any],
        *,
        observed_api_identity: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        replacement = dict(payload)
        replacement.update(
            {
                "api_mutation_recorded": True,
                "observed_api_identity": dict(observed_api_identity),
                "updated_at": now,
            }
        )
        return replacement

    def record_terminal_evidence(
        self,
        payload: Mapping[str, Any],
        *,
        kind: str,
        receipt_sha256: str,
        **_evidence: Any,
    ) -> dict[str, Any]:
        replacement = dict(payload)
        replacement.update(
            {
                "terminal_evidence_recorded": True,
                "terminal_kind": kind,
                "terminal_receipt_sha256": receipt_sha256,
            }
        )
        return replacement

    def remove(self, *, expected: Mapping[str, Any]) -> None:
        assert self.current == dict(expected)
        self.events.append("journal:remove")
        self.current = None


@pytest.fixture
def lane_factory(
    tmp_path: Path,
) -> Callable[..., normalization.ApiBaselineNormalizationLane]:
    sequence = 0

    def build(**overrides: Any) -> normalization.ApiBaselineNormalizationLane:
        nonlocal sequence
        sequence += 1
        root = Path(overrides.pop("root", tmp_path / f"release-{sequence}"))
        root.mkdir(parents=True, exist_ok=True)
        runtime = root / ".runtime"
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        runtime.chmod(0o700)
        receipt_dir = Path(
            overrides.pop(
                "operational_receipt_dir",
                runtime / "deployments" / "memorial-normalization-operations",
            )
        )
        receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_dir.chmod(0o700)
        env = {
            "EA_DEPLOYMENT_ID": f"operation-{sequence:04d}",
            **dict(overrides.pop("env", {})),
        }
        journal = overrides.pop("journal", StaticJournal())
        runner = overrides.pop("runner", RecordingRunner())
        return normalization.ApiBaselineNormalizationLane(
            plan_path=Path(overrides.pop("plan_path", root / "plan.json")),
            bundle_parent=Path(
                overrides.pop("bundle_parent", root / "retained-bundles")
            ),
            public_origin=str(
                overrides.pop("public_origin", "https://myexternalbrain.com")
            ),
            root=root,
            env=env,
            runner=runner,
            operational_receipt_dir=receipt_dir,
            global_lock_path=Path(
                overrides.pop("global_lock_path", tmp_path / "global.lock")
            ),
            durable_root_check=overrides.pop("durable_root_check", lambda _path: None),
            journal_factory=overrides.pop("journal_factory", lambda **_kwargs: journal),
            sleep=overrides.pop("sleep", lambda _seconds: None),
            monotonic=overrides.pop("monotonic", lambda: 0.0),
            now=overrides.pop("now", lambda: "2026-07-21T12:00:00.000Z"),
            **overrides,
        )

    return build


def _bundle(bundle_root: Path) -> dict[str, Any]:
    return {
        "bundle_path": str(bundle_root),
        "compose_files": [
            str(bundle_root / filename)
            for filename in normalization.NORMALIZATION_COMPOSE_FILES
        ],
        "environment_files": [str(bundle_root / ".env")],
        "runtime_environment_files": [
            str(
                bundle_root
                / normalization.RUNTIME_DIRECTORY
                / normalization.RUNTIME_ENV_FILE
            ),
            str(
                bundle_root
                / normalization.RUNTIME_DIRECTORY
                / normalization.RUNTIME_LOCAL_ENV_FILE
            ),
        ],
    }


@pytest.mark.parametrize(
    ("contract_name", "version", "local_present", "accepted"),
    [
        ("ea.memorial_api_baseline_bundle.v1", 1, False, False),
        ("ea.memorial_api_baseline_bundle.v2", 2, True, False),
        ("ea.memorial_api_baseline_bundle.v3", 3, True, False),
        ("ea.memorial_api_baseline_bundle.v4", 4, True, True),
        ("ea.memorial_api_baseline_bundle.v1", 4, True, False),
        ("ea.memorial_api_baseline_bundle.v4", 1, False, False),
    ],
)
def test_recovery_bundle_loader_accepts_only_exact_current_contract_pair(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
    tmp_path: Path,
    contract_name: str,
    version: int,
    local_present: bool,
    accepted: bool,
) -> None:
    bundle_root = tmp_path / f"recovery-bundle-{version}-{local_present}"
    compose_files = [
        str(bundle_root / name) for name in normalization.NORMALIZATION_COMPOSE_FILES
    ]
    environment_files = [str(bundle_root / ".env")]
    local_file = bundle_root / ".env.local"
    if local_present:
        environment_files.append(str(local_file))
    runtime_environment_files = [
        str(
            bundle_root
            / normalization.RUNTIME_DIRECTORY
            / normalization.RUNTIME_ENV_FILE
        ),
        str(
            bundle_root
            / normalization.RUNTIME_DIRECTORY
            / normalization.RUNTIME_LOCAL_ENV_FILE
        ),
    ]
    seal = {
        "contract_name": ("ea.memorial_api_baseline_bundle_recovery_seal.v1"),
        "manifest_sha256": MANIFEST_SHA256,
        "plan_sha256": PLAN_SHA256,
    }
    info = {
        "bundle_path": str(bundle_root),
        "compose_files": compose_files,
        "contract_name": contract_name,
        "environment_files": environment_files,
        "manifest_path": str(bundle_root / "baseline-bundle-manifest.json"),
        "manifest_sha256": MANIFEST_SHA256,
        "origin_main_commit": REVISION,
        "plan_sha256": PLAN_SHA256,
        "runtime_environment_files": runtime_environment_files,
        "source_revision": REVISION,
        "version": version,
    }
    validator_calls: list[dict[str, Any]] = []

    def validator(**kwargs: Any) -> dict[str, Any]:
        validator_calls.append(dict(kwargs))
        return dict(info)

    lane = lane_factory(recovery_bundle_validator=validator)
    payload = {
        "source_revision": REVISION,
        "retained_bundle": {
            "path": str(bundle_root),
            "manifest_path": info["manifest_path"],
            "recovery_seal": seal,
            "ordered_compose_files": compose_files,
            "environment_file": environment_files[0],
            "environment_local_file": (str(local_file) if local_present else None),
        },
    }

    if accepted:
        loaded, reseal = lane._load_recovery_bundle(payload)
        assert loaded == info
        assert reseal() == info
        assert len(validator_calls) == 2
    else:
        with pytest.raises(
            deploy.DeployError,
            match="normalization_recovery_bundle_binding_mismatch",
        ):
            lane._load_recovery_bundle(payload)
        assert len(validator_calls) == 1


def test_constructor_skips_release_env_and_sanitizes_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text(
        "EA_MEMORIAL_IMAGE=attacker/image:latest\nCOMPOSE_FILE=/attacker/compose.yml\n",
        encoding="utf-8",
    )
    parse_calls: list[Path] = []

    def reject_release_env(path: Path) -> dict[str, str]:
        parse_calls.append(path)
        raise AssertionError("normalization constructor read release .env")

    monkeypatch.setattr(deploy, "_parse_env_file", reject_release_env)
    transports = {
        "DOCKER_HOST": "unix:///run/user/1000/docker.sock",
        "DOCKER_CONTEXT": "governed-context",
        "DOCKER_TLS_VERIFY": "1",
        "SSH_AUTH_SOCK": "/run/user/1000/keyring/ssh",
    }
    lane = lane_factory(
        root=root,
        env={
            **transports,
            "EA_MEMORIAL_IMAGE": "attacker/image:latest",
            "EA_MEMORIAL_CANDIDATE_RECEIPT": "/attacker/receipt.json",
            "COMPOSE_FILE": "/attacker/compose.yml",
            "COMPOSE_PROJECT_NAME": "attacker",
            "COMPOSE_PROFILES": "attacker",
            "DOCKER_DEFAULT_PLATFORM": "linux/attacker",
            "PATH": "/attacker/bin",
        },
    )

    assert parse_calls == []
    assert lane.env == {
        "EA_DEPLOYMENT_ID": lane.deployment_id,
        **transports,
    }
    assert lane.release_env == lane.compose_process_env
    assert {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        **transports,
    }.items() <= lane.compose_process_env.items()
    assert lane.compose_process_env["HOME"] == pwd.getpwuid(os.geteuid()).pw_dir
    assert not any(
        key.startswith(("EA_", "COMPOSE_")) for key in lane.compose_process_env
    )
    assert "DOCKER_DEFAULT_PLATFORM" not in lane.compose_process_env


def test_live_bundle_render_environment_is_exact_and_excludes_runtime_secret(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    inspection = _live_api_render_input()
    image_reference = str(inspection["Config"]["Image"])

    rendered = lane._live_bundle_render_environment(
        {
            "api_raw": inspection,
            "expected_revision": REVISION,
            "expected_image_reference": image_reference,
        }
    )

    assert set(rendered) == normalization.BASELINE_RENDER_ENV_KEYS
    assert rendered == {
        "EA_MEMORIAL_DATA_HOST_PATH": "/srv/memorial/release",
        "EA_MEMORIAL_IMAGE": image_reference,
        "EA_MEMORIAL_RUNTIME_HOST_PATH": "/srv/memorial/runtime",
        "EA_MEMORIAL_TRUSTED_PROXY_CIDRS": ("172.30.0.0/16,127.0.0.1/32"),
        "EA_SOURCE_REVISION": REVISION,
    }
    assert "EA_PUBLIC_MEMORIAL_REDIS_URL" not in rendered


def test_live_bundle_environment_names_are_value_free_and_exact(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    inspection = _live_api_render_input()

    names = lane._live_bundle_environment_names({"api_raw": inspection})

    assert names == frozenset(
        entry.split("=", 1)[0] for entry in inspection["Config"]["Env"]
    )
    assert "redis://private.invalid:6379/0" not in names

    inspection["Config"]["Env"].append(
        "EA_PUBLIC_MEMORIAL_REDIS_URL=duplicate-secret"
    )
    with pytest.raises(
        deploy.DeployError, match="normalization_live_environment_invalid"
    ):
        lane._live_bundle_environment_names({"api_raw": inspection})


@pytest.mark.parametrize(
    "invalid_entry",
    [None, "MISSING_EQUALS", "INVALID-NAME=value", "NUL\x00NAME=value"],
)
def test_live_bundle_environment_names_reject_malformed_entries(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
    invalid_entry: object,
) -> None:
    lane = lane_factory()
    inspection = _live_api_render_input()
    inspection["Config"]["Env"].append(invalid_entry)

    with pytest.raises(
        deploy.DeployError, match="normalization_live_environment_invalid"
    ):
        lane._live_bundle_environment_names({"api_raw": inspection})


def test_live_bundle_render_environment_fails_closed_on_mount_or_source_drift(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    inspection = _live_api_render_input()
    image_reference = str(inspection["Config"]["Image"])
    inspection["Mounts"] = list(inspection["Mounts"])[1:]

    with pytest.raises(
        deploy.DeployError, match="rollback_memorial_mount_identity_invalid"
    ):
        lane._live_bundle_render_environment(
            {
                "api_raw": inspection,
                "expected_revision": REVISION,
                "expected_image_reference": image_reference,
            }
        )

    inspection = _live_api_render_input()
    with pytest.raises(
        deploy.DeployError,
        match="normalization_live_render_environment_invalid",
    ):
        lane._live_bundle_render_environment(
            {
                "api_raw": inspection,
                "expected_revision": "9" * 40,
                "expected_image_reference": image_reference,
            }
        )


@pytest.mark.parametrize(
    "drift",
    ["none", "render_value", "environment_name"],
)
def test_fresh_preparation_seals_live_render_inputs_and_rechecks_drift(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
    drift: str,
) -> None:
    lane = lane_factory()
    before_api = _live_api_render_input()
    after_api = json.loads(json.dumps(before_api))
    if drift == "render_value":
        after_api["Config"]["Env"] = [
            (
                "EA_TRUSTED_PROXY_CIDRS=10.0.0.0/8"
                if entry.startswith("EA_TRUSTED_PROXY_CIDRS=")
                else entry
            )
            for entry in after_api["Config"]["Env"]
        ]
    elif drift == "environment_name":
        after_api["Config"]["Env"].append("FUTURE_DISABLED_KEY=0")
    image_reference = str(before_api["Config"]["Image"])
    repository = {
        "branch": "main",
        "upstream": "origin/main",
        "head": REVISION,
        "origin_main": REVISION,
    }
    plan = {"source_requirements": {"expected_revision": REVISION}}

    def validated_live(api_raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "api_raw": dict(api_raw or before_api),
            "config_hash": CONFIG_HASH,
            "expected_revision": REVISION,
            "expected_image_id": IMAGE_ID,
            "expected_image_reference": image_reference,
            "recorded_working_dir": "/srv/recorded",
            "recorded_environment_label": "/srv/recorded/.env",
            "ordered_external_config_files": ["/srv/a", "/srv/b"],
        }

    runtime_values = iter(
        [
            {"api_raw": before_api, "identity": "before"},
            {"api_raw": after_api, "identity": "after"},
        ]
    )
    captured: dict[str, str] = {}
    captured_environment_names: set[str] = set()
    bundle = {
        "bundle_path": str(lane.bundle_parent / "api-baseline-v3-plan"),
        "origin_main_commit": REVISION,
        "source_revision": REVISION,
    }
    lane._fresh_public_origin = lambda: "https://example.invalid"
    lane._private_fresh_bundle_parent = lambda: lane.bundle_parent
    lane._clean_current_main = lambda: dict(repository)
    lane._read_plan = lambda: dict(plan)
    lane._validate_live_split_baseline = lambda **kwargs: validated_live(
        kwargs.get("api_raw")
    )
    lane._require_rollback_tag_absent = lambda: "ea-runtime:rollback-test"
    lane._capture_runtime_evidence = lambda _origin: next(runtime_values)

    def materialize(
        _plan: Mapping[str, Any],
        _parent: Path,
        _repository: Mapping[str, str],
        render_environment: Mapping[str, str],
        baseline_environment_names: frozenset[str],
    ) -> dict[str, Any]:
        captured.update(render_environment)
        captured_environment_names.update(baseline_environment_names)
        return dict(bundle)

    lane._materialize_fresh_bundle = materialize
    lane._render_bundle_compose = lambda *_args, **_kwargs: {"hash": CONFIG_HASH}
    lane._reseal_bundle = lambda value: dict(value)
    lane._require_fresh_bundle_parent = lambda _value: None
    lane._require_bundle_repository_binding = lambda *_args: None
    lane._compare_runtime_evidence = lambda *_args: {"status": "match"}

    if drift != "none":
        expected_reason = (
            "normalization_live_render_environment_changed"
            if drift == "render_value"
            else "normalization_live_environment_names_changed"
        )
        with pytest.raises(
            deploy.DeployError,
            match=expected_reason,
        ):
            lane._prepare_fresh()
    else:
        prepared = lane._prepare_fresh()
        assert prepared["bundle"] == bundle
        assert "render_environment" not in prepared
    assert set(captured) == normalization.BASELINE_RENDER_ENV_KEYS
    assert "EA_PUBLIC_MEMORIAL_REDIS_URL" not in captured
    assert captured_environment_names == {
        entry.split("=", 1)[0] for entry in before_api["Config"]["Env"]
    }


def test_operational_receipt_namespace_is_reserved(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
    tmp_path: Path,
) -> None:
    root = tmp_path / "reserved-release"
    runtime = root / ".runtime"

    with pytest.raises(
        deploy.DeployError,
        match="normalization_operational_receipt_path_reserved",
    ):
        lane_factory(root=root, operational_receipt_dir=runtime)


def test_receipts_publish_private_and_terminal_reuse_is_byte_exact(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    assert lane.receipt["contract_name"] == (
        "ea.memorial_api_baseline_normalization_operation.v2"
    )
    assert normalization.RECEIPT_CONTRACT == (
        "ea.memorial_api_baseline_normalization.v2"
    )
    lane._write_receipt()
    operation_before = lane.receipt_path.stat()
    terminal = {
        "contract_name": normalization.RECEIPT_CONTRACT,
        "status": "pass",
        "transaction_id": lane.deployment_id,
    }

    first_digest = lane._write_terminal_receipt(
        terminal, receipt_path=lane.transaction_receipt_path
    )
    terminal_before = lane.transaction_receipt_path.stat()
    second_digest = lane._write_terminal_receipt(
        terminal, receipt_path=lane.transaction_receipt_path
    )

    assert first_digest == second_digest
    assert lane.receipt_path.stat().st_ino == operation_before.st_ino
    assert lane.transaction_receipt_path.stat().st_ino == terminal_before.st_ino
    assert stat.S_IMODE(lane.receipt_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(lane.receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((lane.root / ".runtime").stat().st_mode) == 0o700
    assert stat.S_IMODE(lane.transaction_receipt_path.stat().st_mode) == 0o600

    original = lane.transaction_receipt_path.read_bytes()
    with pytest.raises(
        deploy.DeployError, match="normalization_terminal_receipt_already_exists"
    ):
        lane._write_terminal_receipt(
            {**terminal, "status": "different"},
            receipt_path=lane.transaction_receipt_path,
        )
    assert lane.transaction_receipt_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["operational", "terminal"])
@pytest.mark.parametrize(
    "attack", ["different_bytes", "wrong_mode", "symlink", "hardlink"]
)
def test_receipt_destination_attacks_never_overwrite(
    kind: str,
    attack: str,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    terminal = {
        "contract_name": normalization.RECEIPT_CONTRACT,
        "status": "pass",
        "transaction_id": lane.deployment_id,
    }
    if kind == "operational":
        path = lane.receipt_path
        expected_raw = normalization._private_json_bytes(lane.receipt)
        publish = lane._write_receipt
    else:
        path = lane.transaction_receipt_path
        expected_raw = normalization._private_json_bytes(terminal)

        def publish() -> None:
            lane._write_terminal_receipt(terminal, receipt_path=path)

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    sentinel = b'{"attacker":"must-survive"}\n'
    linked_source: Path | None = None
    if attack == "different_bytes":
        path.write_bytes(sentinel)
        path.chmod(0o600)
    elif attack == "wrong_mode":
        path.write_bytes(expected_raw)
        path.chmod(0o640)
    elif attack == "symlink":
        linked_source = path.with_name(f"{path.name}.attacker")
        linked_source.write_bytes(sentinel)
        linked_source.chmod(0o600)
        path.symlink_to(linked_source)
    else:
        linked_source = path.with_name(f"{path.name}.attacker")
        linked_source.write_bytes(sentinel)
        linked_source.chmod(0o600)
        os.link(linked_source, path)
    before = path.lstat()
    before_content = path.read_bytes()

    with pytest.raises(deploy.DeployError):
        publish()

    after = path.lstat()
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    assert path.read_bytes() == before_content
    if linked_source is not None:
        assert linked_source.read_bytes() == sentinel
    if attack == "symlink":
        assert path.is_symlink()
    if attack == "hardlink":
        assert after.st_nlink == 2


def test_execute_recovery_precedes_and_ignores_fresh_caller_inputs(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    active = {"transaction_id": "existing-transaction", "phase": "prepared"}
    lane = lane_factory(
        plan_path=Path("/caller/plan/does-not-exist.json"),
        bundle_parent=Path("/caller/bundle/does-not-exist"),
        public_origin="http://caller-origin.invalid/with/path",
        journal=StaticJournal(active),
    )
    events: list[str] = []
    monkeypatch.setattr(lane, "_global_lock", lambda: nullcontext())
    monkeypatch.setattr(lane, "_write_receipt", lambda: events.append("receipt"))
    monkeypatch.setattr(
        lane,
        "_require_joint_recovery_absent",
        lambda: events.append("joint-clear"),
    )
    monkeypatch.setattr(
        lane,
        "_prepare_fresh",
        lambda: pytest.fail("fresh inputs were consulted during recovery"),
    )

    def recover(payload: Mapping[str, Any]) -> dict[str, Any]:
        events.append("recover")
        assert payload == active
        return {"status": "recovered"}

    monkeypatch.setattr(lane, "_recover", recover, raising=False)

    assert lane.execute() == {"status": "recovered"}
    assert events == ["receipt", "joint-clear", "recover"]


def test_preflight_rejects_active_recovery_before_receipt_or_fresh_inputs(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory(
        preflight_only=True,
        journal=StaticJournal(
            {"transaction_id": "existing-transaction", "phase": "prepared"}
        ),
    )
    monkeypatch.setattr(lane, "_global_lock", lambda: nullcontext())
    monkeypatch.setattr(
        lane,
        "_write_receipt",
        lambda: pytest.fail("preflight published over active recovery"),
    )
    monkeypatch.setattr(
        lane,
        "_prepare_fresh",
        lambda: pytest.fail("preflight consulted fresh inputs"),
    )

    with pytest.raises(deploy.DeployError, match="normalization_recovery_active"):
        lane.execute()


class RecreateFailure(RuntimeError):
    pass


@pytest.mark.parametrize("runner_fails", [False, True], ids=["success", "failure"])
def test_sealed_api_recreate_is_api_only_pull_never_and_always_reseals(
    runner_fails: bool,
    tmp_path: Path,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    action_error = RecreateFailure("compose action failed")
    runner = RecordingRunner(action_error if runner_fails else None)
    seal_calls: list[dict[str, Any]] = []

    def seal(value: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(value)
        seal_calls.append(sealed)
        return sealed

    lane = lane_factory(runner=runner, bundle_seal_validator=seal)
    bundle_root = (tmp_path / "sealed-bundle").resolve()
    bundle = _bundle(bundle_root)
    expected = [
        "docker",
        "compose",
        "--project-name",
        deploy.PROJECT_NAME,
        "--project-directory",
        str(bundle_root),
        "--env-file",
        str(bundle_root / ".env"),
    ]
    for compose_file in bundle["compose_files"]:
        expected.extend(["-f", compose_file])
    expected.extend(
        [
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "--force-recreate",
            deploy.API_SERVICE,
        ]
    )

    if runner_fails:
        with pytest.raises(RecreateFailure, match="compose action failed"):
            lane._sealed_api_recreate(bundle)
    else:
        lane._sealed_api_recreate(bundle)

    assert [call[0] for call in runner.calls] == [expected]
    assert seal_calls == [bundle, bundle]
    process_env = runner.calls[0][2]
    assert not any(key.startswith(("EA_", "COMPOSE_")) for key in process_env)


def test_preflight_receipt_excludes_secret_and_filesystem_inputs(
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    secret = "SUPER-SECRET-DO-NOT-SERIALIZE"
    trusted_path = "/trusted/operator/release.env"
    external_path = "/external/untrusted/docker-compose.yml"
    bundle_path = "/private/retained/bundle-operation-0001"
    prepared = {
        "plan": {"secret": secret, "trusted_path": trusted_path},
        "bundle": {
            "manifest_sha256": MANIFEST_SHA256,
            "plan_sha256": PLAN_SHA256,
            "bundle_path": bundle_path,
            "compose_files": [external_path],
            "environment_files": [trusted_path],
            "secret": secret,
        },
        "live": {
            "expected_revision": REVISION,
            "api_raw": {"Config": {"Env": [f"TOKEN={secret}"]}},
        },
        "repository": {
            "branch": "main",
            "upstream": "origin/main",
            "root": external_path,
        },
        "compose": {
            "rendered_service_image": "ea-runtime:memorial-main",
            "pull_policy": "never",
            "rendered_config_hash": CONFIG_HASH,
            "prefix": [external_path],
        },
        "runtime_comparison": {
            "api_domain_sha256": "6" * 64,
            "cloudflared_domain_sha256": "7" * 64,
            "public_network_identity_sha256": "8" * 64,
            "public_edge_identity_sha256": "9" * 64,
            "docker_daemon_identity_sha256": "a" * 64,
            "api_topology_label_evidence": {
                "working_dir_sha256": "b" * 64,
                "config_files_sha256": "c" * 64,
                "environment_file_sha256": "d" * 64,
            },
        },
        "runtime": {
            "public_edge_identity": {
                "headers": {"authorization": secret},
                "source_path": external_path,
            }
        },
        "public_origin": "https://myexternalbrain.com",
    }

    receipt = lane._preflight_receipt(prepared)
    raw = lane.receipt_path.read_text(encoding="utf-8")

    assert json.loads(raw) == receipt
    assert receipt["contract_name"] == (
        "ea.memorial_api_baseline_normalization_preflight.v2"
    )
    assert receipt["version"] == 2
    assert receipt["status"] == "pass"
    assert receipt["execution"] == {
        "journal_created": False,
        "docker_mutations": 0,
        "compose_up_invocations": 0,
        "build_or_pull_invocations": 0,
        "ingress_mutations": 0,
    }
    for forbidden in (
        secret,
        trusted_path,
        external_path,
        bundle_path,
        str(lane.plan_path),
        str(lane.bundle_parent),
    ):
        assert forbidden not in raw
    assert stat.S_IMODE(lane.receipt_path.stat().st_mode) == 0o600
    assert not lane.transaction_receipt_path.exists()


def _test_terminal_receipt(
    payload: Mapping[str, Any],
    *,
    kind: str,
    observation: Mapping[str, Any],
    completed_at: str,
) -> dict[str, Any]:
    return {
        "contract_name": "test.normalization.terminal.v1",
        "transaction_id": payload["transaction_id"],
        "kind": kind,
        "observation": dict(observation),
        "completed_at": completed_at,
    }


def _recovery_capture(*, protected: bool) -> dict[str, Any]:
    return {
        "runtime": {
            "api_identity": {"domain": "api"},
            "cloudflared_identity": {"domain": "cloudflared"},
            "public_network_identity": {"domain": "network"},
            "public_edge_identity": {"domain": "edge"},
            "docker_daemon_identity": "daemon-identity",
        },
        "protected_image": (
            {"Id": IMAGE_ID, "RepoTags": ["ea-runtime:rollback"]} if protected else None
        ),
    }


@pytest.mark.parametrize(
    ("phase", "authorized", "expected_route"),
    [
        ("prepared", False, "clean_abort"),
        ("protect_previous_image_possible", False, "verified_recovery"),
        ("api_mutation_possible", True, "verified_forward_recovery"),
        ("rollback_in_progress", False, "verified_recovery"),
        ("rollback_in_progress", True, "verified_forward_recovery"),
        ("rollback_failed", False, "verified_recovery"),
        ("rollback_failed", True, "verified_forward_recovery"),
    ],
)
def test_recovery_dispatch_phase_and_authority_matrix(
    phase: str,
    authorized: bool,
    expected_route: str,
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    payload = {
        "phase": phase,
        "api_boundary_authorized": authorized,
        "evidence": {},
    }
    events: list[str] = []

    def route(name: str) -> Callable[[Mapping[str, Any]], dict[str, str]]:
        def selected(_payload: Mapping[str, Any]) -> dict[str, str]:
            events.append(f"route:{name}")
            return {"route": name}

        return selected

    def load(
        _payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], Callable[[], dict[str, Any]]]:
        events.append("load:bundle")

        def reseal() -> dict[str, Any]:
            events.append("reseal")
            return {}

        return {}, reseal

    monkeypatch.setattr(lane, "_recover_prepared", route("clean_abort"))
    monkeypatch.setattr(lane, "_recover_old_baseline", route("verified_recovery"))
    monkeypatch.setattr(lane, "_recover_forward", route("verified_forward_recovery"))
    monkeypatch.setattr(lane, "_load_recovery_bundle", load)
    monkeypatch.setattr(
        lane,
        "_reuse_orphan_durable_commit",
        lambda _payload, **_kwargs: events.append("orphan:durable") and None,
    )
    monkeypatch.setattr(
        lane,
        "_reuse_orphan_recovery_receipt",
        lambda _payload: events.append("orphan:recovery") and None,
    )
    monkeypatch.setattr(
        lane,
        "_run_sanitized",
        lambda *_args, **_kwargs: pytest.fail(
            "dispatcher performed a Docker mutation directly"
        ),
    )

    assert lane._recover_dispatch(payload) == {"route": expected_route}
    assert events.count(f"route:{expected_route}") == 1
    if authorized:
        assert "route:verified_recovery" not in events


@pytest.mark.parametrize(
    ("phase", "reason"),
    [
        ("commit_pending", "normalization_recovery_commit_terminal_missing"),
        ("cleanup_pending", "normalization_recovery_cleanup_terminal_missing"),
    ],
)
def test_commit_and_cleanup_require_recorded_terminal_evidence(
    phase: str,
    reason: str,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()

    with pytest.raises(deploy.DeployError, match=reason):
        lane._recover_dispatch({"phase": phase, "evidence": {}})


@pytest.mark.parametrize(
    ("phase", "recaptures"),
    [("commit_pending", True), ("cleanup_pending", False)],
)
def test_recorded_terminal_recaptures_unless_cleanup_is_already_pending(
    phase: str,
    recaptures: bool,
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    lane = lane_factory()
    payload = {
        "phase": phase,
        "evidence": {"terminal": {"kind": "durable_commit"}},
    }
    events: list[str] = []
    capture = {"capture": "current"}

    def load(
        _payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], Callable[[], dict[str, Any]]]:
        events.append("load:bundle")

        def reseal() -> dict[str, Any]:
            events.append("reseal")
            return {}

        return {}, reseal

    def recapture(
        _payload: Mapping[str, Any],
        *,
        target_topology: bool,
        protected_tag_state: str,
    ) -> dict[str, str]:
        assert target_topology is True
        assert protected_tag_state == "exact"
        events.append("capture:terminal")
        return capture

    def finish(
        _payload: Mapping[str, Any],
        *,
        current_capture: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        events.append(
            "finish:recaptured" if current_capture is capture else "finish:direct"
        )
        return {"status": "finished"}

    monkeypatch.setattr(lane, "_load_recovery_bundle", load)
    monkeypatch.setattr(lane, "_capture_full_recovery_runtime", recapture)
    monkeypatch.setattr(lane, "_finish_recorded_terminal", finish)

    assert lane._recover_dispatch(payload) == {"status": "finished"}
    if recaptures:
        assert events == [
            "load:bundle",
            "reseal",
            "capture:terminal",
            "reseal",
            "finish:recaptured",
        ]
    else:
        assert events == ["finish:direct"]


def test_recovery_uses_only_journal_authority(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    payload = {
        "transaction_id": "journal-transaction",
        "phase": "prepared",
        "public_origin": "https://journal-authority.example",
        "evidence": {},
    }
    events: list[str] = []
    journal = OrderingJournal(events)
    journal.current = dict(payload)
    lane = lane_factory(
        journal=journal,
        plan_path=Path("/caller/plan/must-not-be-read.json"),
        bundle_parent=Path("/caller/bundle/must-not-be-read"),
        public_origin="http://caller-origin.invalid",
        env={
            "EA_MEMORIAL_IMAGE": "caller/image:forbidden",
            "COMPOSE_FILE": "/caller/compose/forbidden.yml",
            "DOCKER_HOST": "unix:///approved/docker.sock",
        },
    )

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("recovery consulted fresh caller authority")

    def dispatch(owned: Mapping[str, Any]) -> dict[str, str]:
        assert owned == payload
        assert lane.requested_public_origin == "http://caller-origin.invalid"
        assert lane.compose_process_env["DOCKER_HOST"] == (
            "unix:///approved/docker.sock"
        )
        assert not any(
            key.startswith(("EA_", "COMPOSE_")) for key in lane.compose_process_env
        )
        return {"status": "journal-only"}

    monkeypatch.setattr(lane, "_write_receipt", lambda: events.append("receipt"))
    monkeypatch.setattr(lane, "_recover_dispatch", dispatch)
    monkeypatch.setattr(lane, "_read_plan", forbidden)
    monkeypatch.setattr(lane, "_read_private_file", forbidden)
    monkeypatch.setattr(lane, "_clean_current_main", forbidden)
    monkeypatch.setattr(lane, "_run_git", forbidden)
    monkeypatch.setattr(lane, "_fresh_public_origin", forbidden)
    monkeypatch.setattr(lane, "bundle_materializer", forbidden)

    assert lane._recover(payload) == {"status": "journal-only"}
    assert lane.receipt["recovery_transaction_id"] == "journal-transaction"
    assert events == ["receipt"]


def test_old_baseline_recovery_persists_phase_before_exact_tag_removal(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    events: list[str] = []
    journal = OrderingJournal(events)
    rollback_tag = "ea-runtime:rollback-journal-transaction"
    payload = {
        "transaction_id": "journal-transaction",
        "phase": "protect_previous_image_possible",
        "api_boundary_authorized": False,
        "previous_image": {
            "image_id": IMAGE_ID,
            "rollback_tag": rollback_tag,
        },
    }
    journal.current = dict(payload)
    lane = lane_factory(journal=journal)
    captures = 0

    def reseal() -> dict[str, Any]:
        events.append("reseal")
        return {}

    def capture(
        _payload: Mapping[str, Any],
        *,
        target_topology: bool,
        protected_tag_state: str,
    ) -> dict[str, Any]:
        nonlocal captures
        captures += 1
        assert target_topology is False
        events.append(f"capture:{protected_tag_state}")
        return {"protected_image": {"Id": IMAGE_ID} if captures == 1 else None}

    def run(
        args: Sequence[str], *, check: bool = True, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        del check, cwd
        assert list(args) == ["docker", "image", "rm", rollback_tag]
        events.append("mutation:tag-rm")
        return subprocess.CompletedProcess(list(args), 0, "", "")

    def attach(
        recovering: Mapping[str, Any],
        *,
        kind: str,
        capture: Mapping[str, Any],
    ) -> dict[str, str]:
        assert recovering["phase"] == "rollback_in_progress"
        assert kind == "verified_recovery"
        assert capture["protected_image"] is None
        events.append("attach:terminal")
        return {"status": "recovered"}

    monkeypatch.setattr(lane, "_load_recovery_bundle", lambda _payload: ({}, reseal))
    monkeypatch.setattr(lane, "_capture_full_recovery_runtime", capture)
    monkeypatch.setattr(lane, "_run_sanitized", run)
    monkeypatch.setattr(lane, "_inspect_image_optional", lambda _tag: None)
    monkeypatch.setattr(lane, "_attach_recovery_terminal", attach)
    assert lane._recover_old_baseline(payload) == {"status": "recovered"}
    assert events.index("journal:phase:rollback_in_progress") < events.index(
        "mutation:tag-rm"
    )
    assert events.count("mutation:tag-rm") == 1
    assert events.count("reseal") == 3


@pytest.mark.parametrize("authorized", [False, True])
def test_rollback_orphan_exact_receipt_is_reused_without_duplicate_mutation(
    authorized: bool,
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    events: list[str] = []
    journal = OrderingJournal(events)
    lane = lane_factory(
        journal=journal,
        terminal_receipt_builder=_test_terminal_receipt,
    )
    payload = {
        "transaction_id": lane.deployment_id,
        "transaction_receipt_path": str(lane.transaction_receipt_path),
        "phase": "rollback_failed",
        "api_boundary_authorized": authorized,
        "evidence": {},
    }
    journal.current = dict(payload)
    kind = "verified_forward_recovery" if authorized else "verified_recovery"
    observation = {"verification_sha256": "e" * 64}
    completed_at = "2026-07-21T12:30:00.000Z"
    receipt = _test_terminal_receipt(
        payload,
        kind=kind,
        observation=observation,
        completed_at=completed_at,
    )
    raw = normalization._private_json_bytes(receipt)
    existing = (receipt, raw, normalization._sha256(raw))
    optional_calls: list[Path] = []

    def optional(*, receipt_path: Path) -> tuple[dict[str, Any], bytes, str]:
        optional_calls.append(receipt_path)
        return existing

    def reseal() -> dict[str, Any]:
        events.append("reseal")
        return {}

    def capture(
        _payload: Mapping[str, Any],
        *,
        target_topology: bool,
        protected_tag_state: str,
    ) -> dict[str, Any]:
        assert target_topology is authorized
        assert protected_tag_state == ("exact" if authorized else "absent")
        events.append("capture:orphan")
        return _recovery_capture(protected=authorized)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("orphan receipt recovery repeated a Docker mutation")

    monkeypatch.setattr(lane, "_optional_terminal_receipt", optional)
    monkeypatch.setattr(lane, "_load_recovery_bundle", lambda _payload: ({}, reseal))
    monkeypatch.setattr(lane, "_capture_full_recovery_runtime", capture)
    monkeypatch.setattr(
        lane,
        "_terminal_observation_from_capture",
        lambda _payload, _capture: observation,
    )
    monkeypatch.setattr(lane, "_write_terminal_receipt", forbidden)
    monkeypatch.setattr(lane, "_run_sanitized", forbidden)
    monkeypatch.setattr(lane, "_recovery_bundle_api_up", forbidden)
    monkeypatch.setattr(lane, "_write_receipt", lambda: None)

    assert lane._reuse_orphan_recovery_receipt(payload) == receipt
    assert optional_calls == [
        lane.transaction_receipt_path,
        lane.transaction_receipt_path,
    ]
    assert events.count("capture:orphan") == 1
    assert events.index("journal:phase:rollback_in_progress") < events.index(
        "journal:evidence:terminal"
    )
    assert events[-1] == "journal:remove"
    assert journal.current is None


def test_api_durable_orphan_records_commit_pending_without_recreating_api(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    events: list[str] = []
    journal = OrderingJournal(events)
    lane = lane_factory(
        journal=journal,
        terminal_receipt_builder=_test_terminal_receipt,
    )
    payload = {
        "transaction_id": lane.deployment_id,
        "transaction_receipt_path": str(lane.transaction_receipt_path),
        "phase": "api_mutation_possible",
        "api_boundary_authorized": True,
        "evidence": {},
    }
    journal.current = dict(payload)
    observation = {"verification_sha256": "f" * 64}
    completed_at = "2026-07-21T12:45:00.000Z"
    receipt = _test_terminal_receipt(
        payload,
        kind="durable_commit",
        observation=observation,
        completed_at=completed_at,
    )
    raw = normalization._private_json_bytes(receipt)
    existing = (receipt, raw, normalization._sha256(raw))

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("durable orphan recovery repeated a Docker mutation")

    monkeypatch.setattr(lane, "_optional_terminal_receipt", lambda **_kwargs: existing)
    monkeypatch.setattr(
        lane,
        "_capture_full_recovery_runtime",
        lambda _payload, **_kwargs: _recovery_capture(protected=True),
    )
    monkeypatch.setattr(
        lane,
        "_terminal_observation_from_capture",
        lambda _payload, _capture: observation,
    )
    monkeypatch.setattr(lane, "_write_terminal_receipt", forbidden)
    monkeypatch.setattr(lane, "_run_sanitized", forbidden)
    monkeypatch.setattr(lane, "_recovery_bundle_api_up", forbidden)
    monkeypatch.setattr(lane, "_write_receipt", lambda: None)

    assert (
        lane._reuse_orphan_durable_commit(
            payload, reseal=lambda: events.append("reseal") or {}
        )
        == receipt
    )
    assert events.index("journal:evidence:terminal") < events.index(
        "journal:phase:commit_pending"
    )
    assert events.count("reseal") == 1
    assert events[-1] == "journal:remove"
    assert journal.current is None


def test_forward_recovery_reseals_after_terminal_capture_before_attachment(
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    events: list[str] = []
    journal = OrderingJournal(events)
    payload = {
        "transaction_id": "journal-forward-transaction",
        "phase": "api_mutation_possible",
        "api_boundary_authorized": True,
    }
    journal.current = dict(payload)
    lane = lane_factory(journal=journal)

    def reseal() -> dict[str, Any]:
        events.append("reseal")
        return {}

    monkeypatch.setattr(lane, "_load_recovery_bundle", lambda _payload: ({}, reseal))
    monkeypatch.setattr(
        lane,
        "_forward_recovery_precheck",
        lambda _payload: events.append("precheck"),
    )
    monkeypatch.setattr(
        lane,
        "_render_recovery_bundle_compose",
        lambda *_args: events.append("render") or {},
    )
    monkeypatch.setattr(
        lane,
        "_recovery_bundle_api_up",
        lambda *_args: events.append("mutation:compose-up"),
    )
    monkeypatch.setattr(
        lane, "_wait_api_healthy", lambda: events.append("wait:healthy") or {}
    )
    monkeypatch.setattr(
        lane,
        "_capture_full_recovery_runtime",
        lambda *_args, **_kwargs: (
            events.append("capture:terminal") or _recovery_capture(protected=True)
        ),
    )
    monkeypatch.setattr(
        lane,
        "_attach_recovery_terminal",
        lambda *_args, **_kwargs: (
            events.append("attach:terminal") or {"status": "recovered"}
        ),
    )
    assert lane._recover_forward(payload) == {"status": "recovered"}
    assert events.index("mutation:compose-up") < events.index("capture:terminal")
    terminal_seal = max(
        index for index, event in enumerate(events) if event == "reseal"
    )
    assert events.index("capture:terminal") < terminal_seal
    assert terminal_seal < events.index("attach:terminal")


@pytest.mark.parametrize("runner_fails", [False, True], ids=["success", "failure"])
def test_recovery_api_up_is_exact_pull_never_and_reseals_after_action(
    runner_fails: bool,
    tmp_path: Path,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    action_error = RecreateFailure("recovery compose action failed")
    runner = RecordingRunner(action_error if runner_fails else None)
    lane = lane_factory(runner=runner)
    bundle_root = (tmp_path / "recovery-bundle").resolve()
    bundle = _bundle(bundle_root)
    seal_calls: list[dict[str, Any]] = []

    def reseal() -> dict[str, Any]:
        sealed = dict(bundle)
        seal_calls.append(sealed)
        return sealed

    expected = [
        "docker",
        "compose",
        "--project-name",
        deploy.PROJECT_NAME,
        "--project-directory",
        str(bundle_root),
        "--env-file",
        str(bundle_root / ".env"),
    ]
    for compose_file in bundle["compose_files"]:
        expected.extend(["-f", compose_file])
    expected.extend(
        [
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--no-deps",
            "--force-recreate",
            deploy.API_SERVICE,
        ]
    )

    if runner_fails:
        with pytest.raises(RecreateFailure, match="recovery compose action failed"):
            lane._recovery_bundle_api_up(bundle, reseal)
    else:
        lane._recovery_bundle_api_up(bundle, reseal)

    assert [call[0] for call in runner.calls] == [expected]
    assert seal_calls == [bundle, bundle]
    assert not any(key.startswith(("EA_", "COMPOSE_")) for key in runner.calls[0][2])


@pytest.mark.parametrize(
    ("phase", "has_terminal", "marked"),
    [
        ("rollback_in_progress", False, True),
        ("rollback_in_progress", True, False),
        ("rollback_failed", False, False),
        ("api_mutation_possible", False, False),
    ],
)
def test_recovery_marks_rollback_failed_only_for_unterminalized_in_progress(
    phase: str,
    has_terminal: bool,
    marked: bool,
    monkeypatch: pytest.MonkeyPatch,
    lane_factory: Callable[..., normalization.ApiBaselineNormalizationLane],
) -> None:
    events: list[str] = []
    journal = OrderingJournal(events)
    payload = {
        "transaction_id": "journal-transaction",
        "phase": phase,
        "evidence": {
            "terminal": {"kind": "verified_recovery"} if has_terminal else None
        },
    }
    journal.current = dict(payload)
    lane = lane_factory(journal=journal)
    failure = RecreateFailure("recovery failed")

    def fail_dispatch(_payload: Mapping[str, Any]) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(lane, "_recover_dispatch", fail_dispatch)
    monkeypatch.setattr(lane, "_write_receipt", lambda: None)
    with pytest.raises(RecreateFailure, match="recovery failed") as raised:
        lane._recover(payload)

    assert raised.value is failure
    if marked:
        assert journal.current is not None
        assert journal.current["phase"] == "rollback_failed"
        assert events == ["journal:phase:rollback_failed"]
    else:
        assert journal.current == payload
        assert events == []
