from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import cleanup_manfred_memorial_candidates as cleanup
from scripts.manfred_candidate_registry import (
    CANDIDATE_ENV_KEYS,
    EXECUTION_INPUT_SCHEMA,
    RUNTIME_POSTURE_SCHEMA,
)


REVISION_A = "a" * 40
REVISION_B = "b" * 40
IMAGE_A = "sha256:" + "1" * 64
IMAGE_B = "sha256:" + "2" * 64
PROJECT_A = "ea-manfred-candidate-aaaaaaaaaaaa"
PROJECT_B = "ea-manfred-candidate-bbbbbbbbbbbb"
LEGACY_PROJECT = "ea-manfred-candidate"


def _runtime_identity(revision: str) -> dict[str, object]:
    return {
        "path": "/version",
        "status": 200,
        "commit_sha": revision,
        "body_commit_sha": revision,
        "source_revision_header": revision,
        "expected_commit_sha": revision,
        "oci_image_revision": revision,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }


def _write_v5_receipt(
    path: Path,
    *,
    project: str,
    revision: str,
    image_id: str,
    api_container_id: str,
    gateway_container_id: str,
    port: int,
    observed_at: str,
) -> dict[str, object]:
    release_root = path.parent / "release" / revision
    runtime_root = path.parent / "runtime" / project
    environment_sha256 = "7" * 64
    projection_files = [
        {
            "path": "public_memorials/manfred/memorial.json",
            "sha256": "9" * 64,
            "size_bytes": 2,
            "mode": "444",
        }
    ]
    projection_sha256 = hashlib.sha256(
        json.dumps(
            projection_files,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    runtime_projection = {
        "schema": "ea.manfred_candidate_runtime_projection.v1",
        "projection_sha256": projection_sha256,
        "file_count": 1,
        "projection_bytes": 2,
        "mount_roots": [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/public_property_tours",
            "/data/release-authority",
        ],
        "runtime_bytes_match_prepared_projection": True,
    }
    images = {
        "api": {
            "container_id": api_container_id,
            "image_id": image_id,
        },
        "gateway": {
            "container_id": gateway_container_id,
            "image_id": image_id,
        },
        "prepared_image_id": image_id,
        "revision_label": revision,
        "all_match_prepared_image": True,
    }
    payload = {
        "schema": cleanup.RUNTIME_SCHEMA_V5,
        "status": "pass",
        "observed_at": observed_at,
        "compose_project": project,
        "candidate_port": port,
        "image": f"ea-runtime:manfred-{revision}",
        "image_id": image_id,
        "image_source_revision": revision,
        "compose_attestation": {
            "canonical_relative_path": (
                "deploy/manfred-memorial/docker-compose.candidate.yml"
            ),
            "canonical_source_path": str(
                path.parent
                / "source"
                / "deploy/manfred-memorial/docker-compose.candidate.yml"
            ),
            "candidate_commit": revision,
            "git_blob_oid": "5" * 40,
            "sha256": "6" * 64,
            "size_bytes": 8192,
            "canonical_path_enforced": True,
            "tracked_blob_bytes_enforced": True,
        },
        "execution_inputs": {
            "schema": EXECUTION_INPUT_SCHEMA,
            "compose_sha256": "6" * 64,
            "compose_size_bytes": 8192,
            "compose_git_blob_oid": "5" * 40,
            "environment_sha256": environment_sha256,
            "environment_size_bytes": 4096,
            "environment_keys": sorted(CANDIDATE_ENV_KEYS),
            "compose_image_id": image_id,
            "compose_image_reference_source": "prepared_image_id",
            "transport": "sealed_memfd",
            "required_seals": ["grow", "seal", "shrink", "write"],
            "all_compose_commands_use_sealed_inputs": True,
            "mutable_source_paths_consumed_by_compose": False,
            "mutable_image_locator_consumed_by_compose": False,
        },
        "release_root": str(release_root),
        "projection_sha256": projection_sha256,
        "projection_files": projection_files,
        "projection_file_count": 1,
        "projection_bytes": 2,
        "runtime_projection_initial": runtime_projection,
        "runtime_projection_final": runtime_projection,
        "runtime_projection_identity_stable": True,
        "runtime_source_revision": revision,
        "runtime_authority_commit": revision,
        "runtime_version_identity": _runtime_identity(revision),
        "candidate_container_images": images,
        "candidate_container_images_initial": images,
        "candidate_container_images_final": images,
        "candidate_container_image_identity_stable": True,
        "candidate_api_container_id": api_container_id,
        "runtime_api_posture": {
            "schema": RUNTIME_POSTURE_SCHEMA,
            "api_container_id": api_container_id,
            "image_id": image_id,
            "environment_sha256": "8" * 64,
            "execution_environment_sha256": environment_sha256,
            "environment_keys": sorted(CANDIDATE_ENV_KEYS),
            "environment_exact": True,
            "provider_credentials_present": False,
            "mounts": [
                {
                    "destination": destination,
                    "identity": str(release_root / leaf),
                    "read_only": True,
                    "type": "bind",
                }
                for destination, leaf in (
                    ("/data/memorial/public", "public_memorials"),
                    ("/data/memorial/private", "private_memorial_profiles"),
                    ("/data/memorial/archive", "memorial_archive"),
                    ("/data/public_property_tours", "public_property_tours"),
                    ("/data/release-authority", "release-authority"),
                )
            ]
            + [
                {
                    "destination": destination,
                    "identity": str(runtime_root / leaf),
                    "read_only": False,
                    "type": "bind",
                }
                for destination, leaf in (
                    (
                        "/data/memorial/public-contributions",
                        "public-contributions",
                    ),
                    (
                        "/data/memorial/private-contributions",
                        "private-contributions",
                    ),
                    ("/data/memorial/state", "state"),
                )
            ]
            + [
                {
                    "destination": "/data/artifacts",
                    "identity": f"{project}_artifacts",
                    "read_only": False,
                    "type": "volume",
                }
            ],
            "mounts_exact": True,
            "tmpfs_exact": True,
            "networks": [f"{project}_backend"],
            "network_exact": True,
            "ingress_attached": False,
            "read_only_rootfs": True,
            "all_capabilities_dropped": True,
            "no_new_privileges": True,
            "runtime_user": "10001:10001",
            "running_and_healthy": True,
        },
        "candidate_left_running": True,
        "live_ea_api_unchanged": True,
        "promotion_authority": False,
        "provider_credentials_present": False,
        "provider_calls_performed": False,
        "gateway_has_runtime_secrets": False,
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.write_bytes(encoded)
    path.chmod(0o600)
    return {
        "project": project,
        "receipt_path": str(path.resolve()),
        "receipt_sha256": hashlib.sha256(encoded).hexdigest(),
        "observed_at": observed_at,
        "image_id": image_id,
        "runtime_schema": cleanup.RUNTIME_SCHEMA_V5,
        "legacy": False,
        "retention_eligible": True,
        "quarantined": False,
        "quarantine_reason": "",
        "automatic_retirement_authorized": False,
    }


def _legacy_posture(
    *,
    schema: str = cleanup.RUNTIME_SCHEMA_V3,
    project: str = LEGACY_PROJECT,
) -> dict[str, object]:
    return {
        "project": project,
        "receipt_path": f"/unused/legacy-{schema.rsplit('.', 1)[-1]}.json",
        "receipt_sha256": "9" * 64,
        "observed_at": "2026-07-14T10:00:00Z",
        "image_id": IMAGE_B,
        "runtime_schema": schema,
        "legacy": True,
        "retention_eligible": False,
        "quarantined": True,
        "quarantine_reason": f"legacy_runtime_receipt_{schema.rsplit('.', 1)[-1]}",
        "automatic_retirement_authorized": False,
    }


def _container(
    *,
    identifier: str,
    project: str,
    service: str,
    image_id: str,
    healthy: bool = True,
) -> dict[str, object]:
    return {
        "Id": identifier,
        "Image": image_id,
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": True,
            "Health": {"Status": "healthy" if healthy else "unhealthy"},
        },
    }


def _project_containers(
    *,
    project: str,
    image_id: str,
    id_characters: tuple[str, str, str, str],
) -> list[dict[str, object]]:
    return [
        _container(
            identifier=character * 64,
            project=project,
            service=service,
            image_id=image_id,
        )
        for service, character in zip(
            ("api", "gateway", "postgres", "redis"),
            id_characters,
            strict=True,
        )
    ]


class _DockerFixture:
    def __init__(
        self,
        snapshots: list[list[dict[str, object]]],
        image_revisions: dict[str, str],
    ) -> None:
        self.snapshots = snapshots
        self.image_revisions = image_revisions
        self.commands: list[list[str]] = []
        self.list_calls = 0

    def __call__(self, argv: list[str], *, timeout: int = 30) -> bytes:
        del timeout
        command = list(argv)
        self.commands.append(command)
        if command == [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
        ]:
            index = min(self.list_calls, len(self.snapshots) - 1)
            self.list_calls += 1
            identifiers = [str(row["Id"]) for row in self.snapshots[index]]
            return ("\n".join(identifiers) + ("\n" if identifiers else "")).encode()
        if command[:3] == ["docker", "container", "inspect"]:
            index = min(max(self.list_calls - 1, 0), len(self.snapshots) - 1)
            rows = self.snapshots[index]
            self.asserted_identifiers = {str(row["Id"]) for row in rows}
            if set(command[3:]) != self.asserted_identifiers:
                raise AssertionError("container inspection did not bind the list")
            return json.dumps(rows).encode()
        if command[:3] == ["docker", "image", "inspect"]:
            image_id = command[3]
            return json.dumps(
                [
                    {
                        "Id": image_id,
                        "Config": {
                            "Labels": {
                                cleanup.OCI_REVISION_LABEL: self.image_revisions[
                                    image_id
                                ]
                            }
                        },
                    }
                ]
            ).encode()
        raise AssertionError(f"unexpected Docker command: {command!r}")

    def assert_read_only(self, testcase: unittest.TestCase) -> None:
        testcase.assertTrue(self.commands)
        for command in self.commands:
            testcase.assertTrue(
                command
                == [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                ]
                or command[:3]
                in (
                    ["docker", "container", "inspect"],
                    ["docker", "image", "inspect"],
                ),
                command,
            )


class CleanupManfredMemorialCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.lock_path = self.root / cleanup.FLEET_LOCK_PATH.name
        self.registry_path = self.root / "registry.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_invalid_registered_receipt_is_quarantined_without_aborting_audit(
        self,
    ) -> None:
        project = "ea-manfred-candidate-stale00000000"
        posture = {
            "project": project,
            "runtime_schema": "unknown",
            "legacy": False,
            "retention_eligible": False,
            "quarantined": True,
            "quarantine_reason": "registered_receipt_invalid",
            "registry_receipt_invalid": True,
            "automatic_retirement_authorized": False,
        }
        docker = _DockerFixture([[], []], {})

        report = self._evaluate(postures=[posture], docker=docker)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            report["candidates"],
            [
                {
                    "project": project,
                    "runtime_schema": "unknown",
                    "qualification": "ineligible",
                    "quarantined": True,
                    "quarantine_reason": "registered_receipt_invalid",
                    "automatic_retirement_authorized": False,
                    "error": ("manfred_candidate_retention_registered_receipt_invalid"),
                }
            ],
        )
        docker.assert_read_only(self)

    def test_inventory_tolerates_unlabeled_unrelated_container(self) -> None:
        identifier = "f" * 64
        image_id = "sha256:" + "e" * 64
        responses = [
            f"{identifier}\n".encode("ascii"),
            json.dumps(
                [
                    {
                        "Id": identifier,
                        "Image": image_id,
                        "Config": {"Labels": None},
                        "State": {"Running": True, "Health": None},
                    }
                ]
            ).encode("utf-8"),
        ]
        with mock.patch.object(cleanup, "_run_docker", side_effect=responses):
            inventory = cleanup._container_inventory()
        self.assertEqual(
            inventory,
            (
                {
                    "id": identifier,
                    "project": "",
                    "service": "",
                    "image_id": image_id,
                    "running": True,
                    "health": "",
                },
            ),
        )

    @staticmethod
    def _probe(
        port: int,
        *,
        expected_commit: str,
        oci_image_revision: str,
    ) -> dict[str, object]:
        if not 1024 <= port <= 65535 or expected_commit != oci_image_revision:
            raise RuntimeError("test_probe_identity_mismatch")
        return _runtime_identity(expected_commit)

    def _evaluate(
        self,
        *,
        postures: list[dict[str, object]],
        docker: _DockerFixture,
        apply: bool = False,
        probe: object | None = None,
    ) -> dict[str, object]:
        runtime_probe = probe or self._probe
        with (
            mock.patch.object(
                cleanup,
                "registered_candidate_receipt_postures",
                return_value=postures,
            ),
            mock.patch.object(cleanup, "_run_docker", side_effect=docker),
            mock.patch.object(
                cleanup,
                "_probe_runtime_identity",
                side_effect=runtime_probe,
            ),
        ):
            return cleanup.evaluate_retention(
                registry_path=self.registry_path,
                lock_path=self.lock_path,
                apply=apply,
                sample_spacing_seconds=1,
                sleep=lambda _seconds: None,
            )

    def test_v3_and_v5_coexist_with_legacy_quarantined(self) -> None:
        v5_rows = _project_containers(
            project=PROJECT_A,
            image_id=IMAGE_A,
            id_characters=("a", "b", "c", "d"),
        )
        legacy_rows = _project_containers(
            project=LEGACY_PROJECT,
            image_id=IMAGE_B,
            id_characters=("e", "f", "3", "4"),
        )
        live_row = _container(
            identifier="5" * 64,
            project=cleanup.LIVE_COMPOSE_PROJECT,
            service="api",
            image_id=IMAGE_B,
        )
        posture = _write_v5_receipt(
            self.root / "candidate-a.json",
            project=PROJECT_A,
            revision=REVISION_A,
            image_id=IMAGE_A,
            api_container_id="a" * 64,
            gateway_container_id="b" * 64,
            port=18080,
            observed_at="2026-07-14T11:00:00Z",
        )
        snapshot = [*v5_rows, *legacy_rows, live_row]
        docker = _DockerFixture([snapshot, snapshot], {IMAGE_A: REVISION_A})

        report = self._evaluate(
            postures=[_legacy_posture(), posture],
            docker=docker,
        )

        by_project = {row["project"]: row for row in report["candidates"]}
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["identity_stable_projects"], [PROJECT_A])
        self.assertEqual(
            by_project[PROJECT_A]["qualification"],
            "observed_identity_stable",
        )
        self.assertTrue(by_project[LEGACY_PROJECT]["quarantined"])
        self.assertEqual(
            by_project[LEGACY_PROJECT]["quarantine_reason"],
            "legacy_runtime_receipt_v3",
        )
        self.assertEqual(report["live_project_container_count"], 1)
        self.assertFalse(report["automatic_retirement_authorized"])
        self.assertFalse(report["mutation_performed"])
        docker.assert_read_only(self)

    def test_v4_receipt_metadata_is_quarantined_without_receipt_parsing(self) -> None:
        docker = _DockerFixture([[], []], {})
        posture = _legacy_posture(
            schema=cleanup.RUNTIME_SCHEMA_V4,
            project=PROJECT_A,
        )

        report = self._evaluate(postures=[posture], docker=docker)

        assert report["identity_stable_projects"] == []
        assert report["candidates"] == [
            {
                "project": PROJECT_A,
                "runtime_schema": cleanup.RUNTIME_SCHEMA_V4,
                "qualification": "ineligible",
                "quarantined": True,
                "quarantine_reason": "legacy_runtime_receipt_v4",
                "automatic_retirement_authorized": False,
            }
        ]
        docker.assert_read_only(self)

    def test_apply_with_identity_change_performs_zero_docker_mutation(self) -> None:
        initial = _project_containers(
            project=PROJECT_A,
            image_id=IMAGE_A,
            id_characters=("a", "b", "c", "d"),
        )
        final = [dict(row) for row in initial]
        final[0] = {**final[0], "Image": IMAGE_B}
        posture = _write_v5_receipt(
            self.root / "candidate-a.json",
            project=PROJECT_A,
            revision=REVISION_A,
            image_id=IMAGE_A,
            api_container_id="a" * 64,
            gateway_container_id="b" * 64,
            port=18080,
            observed_at="2026-07-14T11:00:00Z",
        )
        docker = _DockerFixture([initial, final], {IMAGE_A: REVISION_A})

        report = self._evaluate(
            postures=[posture],
            docker=docker,
            apply=True,
        )

        candidate = report["candidates"][0]
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["mode"], "apply_requested")
        self.assertTrue(candidate["quarantined"])
        self.assertEqual(
            candidate["quarantine_reason"],
            "runtime_identity_stability_revoked",
        )
        self.assertFalse(report["mutation_performed"])
        self.assertFalse(report["automatic_retirement_authorized"])
        self.assertEqual(
            report["apply_block_reason"],
            "manfred_candidate_retention_destructive_apply_not_implemented",
        )
        docker.assert_read_only(self)

    def test_every_candidate_service_requires_exact_healthy_status(self) -> None:
        for index, health in enumerate((None, {"Status": "starting"})):
            with self.subTest(health=health):
                snapshot = _project_containers(
                    project=PROJECT_A,
                    image_id=IMAGE_A,
                    id_characters=("a", "b", "c", "d"),
                )
                snapshot[index]["State"]["Health"] = health
                posture = _write_v5_receipt(
                    self.root / f"candidate-health-{index}.json",
                    project=PROJECT_A,
                    revision=REVISION_A,
                    image_id=IMAGE_A,
                    api_container_id="a" * 64,
                    gateway_container_id="b" * 64,
                    port=18080,
                    observed_at="2026-07-14T11:00:00Z",
                )
                docker = _DockerFixture([snapshot, snapshot], {})

                report = self._evaluate(postures=[posture], docker=docker)

                candidate = report["candidates"][0]
                self.assertTrue(candidate["quarantined"])
                self.assertEqual(
                    candidate["quarantine_reason"],
                    "runtime_identity_not_qualified",
                )
                self.assertEqual(
                    candidate["error"],
                    "manfred_candidate_retention_candidate_health_invalid",
                )
                self.assertEqual(report["identity_stable_projects"], [])
                docker.assert_read_only(self)

    def test_four_way_runtime_mismatch_avoids_qualification(self) -> None:
        snapshot = _project_containers(
            project=PROJECT_A,
            image_id=IMAGE_A,
            id_characters=("a", "b", "c", "d"),
        )
        posture = _write_v5_receipt(
            self.root / "candidate-a.json",
            project=PROJECT_A,
            revision=REVISION_A,
            image_id=IMAGE_A,
            api_container_id="a" * 64,
            gateway_container_id="b" * 64,
            port=18080,
            observed_at="2026-07-14T11:00:00Z",
        )
        docker = _DockerFixture([snapshot, snapshot], {IMAGE_A: REVISION_A})

        def mismatched_probe(
            port: int,
            *,
            expected_commit: str,
            oci_image_revision: str,
        ) -> dict[str, object]:
            del port, expected_commit, oci_image_revision
            return _runtime_identity(REVISION_B)

        report = self._evaluate(
            postures=[posture],
            docker=docker,
            probe=mismatched_probe,
        )

        candidate = report["candidates"][0]
        self.assertTrue(candidate["quarantined"])
        self.assertEqual(
            candidate["quarantine_reason"],
            "runtime_identity_not_qualified",
        )
        self.assertEqual(report["identity_stable_projects"], [])
        self.assertFalse(candidate["automatic_retirement_authorized"])
        docker.assert_read_only(self)

    def test_unknown_candidate_is_quarantined_and_live_ea_is_excluded(self) -> None:
        unknown = _project_containers(
            project=PROJECT_A,
            image_id=IMAGE_A,
            id_characters=("a", "b", "c", "d"),
        )
        live = _container(
            identifier="e" * 64,
            project=cleanup.LIVE_COMPOSE_PROJECT,
            service="api",
            image_id=IMAGE_B,
        )
        snapshot = [*unknown, live]
        docker = _DockerFixture([snapshot, snapshot], {})

        report = self._evaluate(postures=[], docker=docker)

        self.assertEqual(report["unknown_projects"], [PROJECT_A])
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(
            report["candidates"][0]["quarantine_reason"],
            "unregistered_candidate_project",
        )
        self.assertNotIn(
            cleanup.LIVE_COMPOSE_PROJECT,
            [row["project"] for row in report["candidates"]],
        )
        self.assertTrue(report["live_compose_project_protected"])
        self.assertEqual(report["live_project_container_count"], 1)
        docker.assert_read_only(self)

    def test_apply_remains_blocked_with_two_stable_v5_observations(self) -> None:
        rows_a = _project_containers(
            project=PROJECT_A,
            image_id=IMAGE_A,
            id_characters=("a", "b", "c", "d"),
        )
        rows_b = _project_containers(
            project=PROJECT_B,
            image_id=IMAGE_B,
            id_characters=("e", "f", "3", "4"),
        )
        posture_a = _write_v5_receipt(
            self.root / "candidate-a.json",
            project=PROJECT_A,
            revision=REVISION_A,
            image_id=IMAGE_A,
            api_container_id="a" * 64,
            gateway_container_id="b" * 64,
            port=18080,
            observed_at="2026-07-14T11:00:00Z",
        )
        posture_b = _write_v5_receipt(
            self.root / "candidate-b.json",
            project=PROJECT_B,
            revision=REVISION_B,
            image_id=IMAGE_B,
            api_container_id="e" * 64,
            gateway_container_id="f" * 64,
            port=18081,
            observed_at="2026-07-14T12:00:00Z",
        )
        snapshot = [*rows_a, *rows_b]
        docker = _DockerFixture(
            [snapshot, snapshot],
            {IMAGE_A: REVISION_A, IMAGE_B: REVISION_B},
        )

        report = self._evaluate(
            postures=[posture_a, posture_b],
            docker=docker,
            apply=True,
        )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["identity_stable_projects"],
            [PROJECT_A, PROJECT_B],
        )
        self.assertEqual(
            {row["qualification"] for row in report["candidates"]},
            {"observed_identity_stable"},
        )
        self.assertTrue(
            all(
                row["automatic_retirement_authorized"] is False
                for row in report["candidates"]
            )
        )
        self.assertTrue(
            all(row["quarantined"] is False for row in report["candidates"])
        )
        self.assertEqual(report["quarantined_projects"], [])
        self.assertFalse(report["mutation_performed"])
        docker.assert_read_only(self)

    def test_cli_defaults_to_dry_run(self) -> None:
        arguments = cleanup.build_parser().parse_args([])

        self.assertFalse(arguments.apply)
        self.assertEqual(arguments.sample_spacing_seconds, 5.0)


if __name__ == "__main__":
    unittest.main()
