from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts import run_manfred_memorial_candidate as candidate_runner
from scripts.manfred_candidate_registry import (
    CANDIDATE_ENV_KEYS,
    EXECUTION_INPUT_SCHEMA,
    REGISTRY_SCHEMA,
    RUNTIME_POSTURE_SCHEMA,
    RUNTIME_SCHEMA_V3,
    RUNTIME_SCHEMA_V4,
    RUNTIME_SCHEMA_V5,
    candidate_registry_recovery_state,
    clear_candidate_pending_exact,
    compact_candidate_registry,
    register_candidate_pending,
    register_candidate_receipt,
    registered_candidate_pending,
    registered_candidate_receipt_postures,
    registered_candidate_receipts,
)


REVISION_A = "a" * 40
REVISION_B = "b" * 40
IMAGE_ID_A = "sha256:" + "1" * 64
IMAGE_ID_B = "sha256:" + "2" * 64
API_CONTAINER_ID = "3" * 64
GATEWAY_CONTAINER_ID = "4" * 64
PROJECT = "ea-manfred-candidate-a1b2c3d4"
PROJECT_B = "ea-manfred-candidate-b1c2d3e4"


def test_registry_execution_input_allowlist_matches_candidate_runner() -> None:
    assert CANDIDATE_ENV_KEYS == frozenset(candidate_runner.ALLOWED_ENV_KEYS)


class CandidateRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.registry = self.root / "manfred-candidate-registry.json"
        self.receipts = self.root / "receipts"
        self.receipts.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _runtime_payload(
        self,
        *,
        schema: str = RUNTIME_SCHEMA_V5,
        project: str = PROJECT,
        revision: str = REVISION_A,
        image_id: str = IMAGE_ID_A,
        port: int = 18091,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": schema,
            "status": "pass",
            "observed_at": "2026-07-14T13:56:31Z",
            "compose_project": project,
            "image": f"ea-runtime:memorial-{revision}",
            "image_id": image_id,
            "image_source_revision": revision,
            "runtime_source_revision": revision,
            "image_locator_evidence": {
                "locator": f"ea-runtime:memorial-{revision}",
                "resolved_image_id": image_id,
                "revision_label": revision,
                "used_for_attestation_only": True,
                "consumed_by_compose": False,
            },
            "compose_uses_immutable_image_id": True,
            "candidate_port": port,
            "live_ea_api_unchanged": True,
            "promotion_authority": False,
            "provider_credentials_present": False,
            "provider_calls_performed": False,
            "gateway_has_runtime_secrets": False,
        }
        if schema == RUNTIME_SCHEMA_V5:
            payload["candidate_left_running"] = True
            release_root = self.root / "release" / revision
            runtime_root = self.root / "runtime" / project
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
            container_images = {
                "api": {
                    "container_id": API_CONTAINER_ID,
                    "image_id": image_id,
                },
                "gateway": {
                    "container_id": GATEWAY_CONTAINER_ID,
                    "image_id": image_id,
                },
                "prepared_image_id": image_id,
                "revision_label": revision,
                "all_match_prepared_image": True,
            }
            payload.update(
                {
                    "compose_attestation": {
                        "canonical_relative_path": (
                            "deploy/manfred-memorial/docker-compose.candidate.yml"
                        ),
                        "canonical_source_path": str(
                            self.root
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
                    "candidate_api_container_id": API_CONTAINER_ID,
                    "candidate_container_images": container_images,
                    "candidate_container_images_initial": container_images,
                    "candidate_container_images_final": container_images,
                    "candidate_container_image_identity_stable": True,
                    "runtime_authority_commit": revision,
                    "runtime_version_identity": {
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
                    },
                    "runtime_api_posture": {
                        "schema": RUNTIME_POSTURE_SCHEMA,
                        "api_container_id": API_CONTAINER_ID,
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
                                (
                                    "/data/memorial/private",
                                    "private_memorial_profiles",
                                ),
                                ("/data/memorial/archive", "memorial_archive"),
                                (
                                    "/data/public_property_tours",
                                    "public_property_tours",
                                ),
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
                }
            )
        return payload

    def test_v5_registration_requires_commit_bound_compose_attestation(self) -> None:
        payload = self._runtime_payload()
        attestation = payload["compose_attestation"]
        self.assertIsInstance(attestation, dict)
        assert isinstance(attestation, dict)
        attestation["candidate_commit"] = REVISION_B
        receipt, _digest = self._write_json(
            self.receipts / "candidate-invalid-compose.json",
            payload,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_compose_attestation_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

    def test_v5_registration_requires_exact_execution_input_seals(self) -> None:
        payload = self._runtime_payload()
        execution_inputs = dict(payload["execution_inputs"])
        execution_inputs["required_seals"] = ["seal", "write"]
        payload["execution_inputs"] = execution_inputs
        receipt, _digest = self._write_json(
            self.receipts / "candidate-invalid-execution-inputs.json",
            payload,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_execution_inputs_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

    def test_v5_registration_requires_immutable_image_id_semantics(self) -> None:
        payload = self._runtime_payload()
        payload["compose_uses_immutable_image_id"] = False
        receipt, _digest = self._write_json(
            self.receipts / "candidate-invalid-image-reference.json",
            payload,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_image_reference_semantics_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

    def test_v5_registration_requires_exact_runtime_api_posture(self) -> None:
        payload = self._runtime_payload()
        posture = dict(payload["runtime_api_posture"])
        posture["ingress_attached"] = True
        payload["runtime_api_posture"] = posture
        receipt, _digest = self._write_json(
            self.receipts / "candidate-invalid-runtime-posture.json",
            payload,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_runtime_posture_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

    def _write_json(
        self,
        path: Path,
        payload: dict[str, object],
    ) -> tuple[Path, str]:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        raw = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        path.chmod(0o600)
        return path, hashlib.sha256(raw).hexdigest()

    def _registry_entry(
        self,
        receipt: Path,
        digest: str,
        payload: dict[str, object],
    ) -> dict[str, str]:
        return {
            "project": str(payload["compose_project"]),
            "receipt_path": str(receipt.resolve()),
            "receipt_sha256": digest,
            "observed_at": str(payload["observed_at"]),
            "image_id": str(payload["image_id"]),
        }

    def test_pending_to_v5_registration_is_atomic_private_and_idempotent(self) -> None:
        receipt = self.receipts / "candidate-v5.json"
        pending = register_candidate_pending(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=f"ea-runtime:memorial-{REVISION_A}",
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self.assertTrue(pending["pending_registered"])
        self.assertEqual(
            len(registered_candidate_pending(registry_path=self.registry)), 1
        )

        self._write_json(receipt, self._runtime_payload())
        registration = register_candidate_receipt(
            receipt,
            registry_path=self.registry,
        )
        self.assertTrue(registration["registered"])
        self.assertFalse(registration["idempotent"])
        self.assertEqual(registered_candidate_pending(registry_path=self.registry), [])
        self.assertEqual(
            registered_candidate_receipts(registry_path=self.registry),
            [receipt.resolve()],
        )

        metadata = self.registry.stat()
        self.assertEqual(metadata.st_uid, os.getuid())
        self.assertEqual(metadata.st_nlink, 1)
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        registry_text = self.registry.read_text(encoding="utf-8")
        self.assertNotIn("EA_API_TOKEN", registry_text)
        self.assertNotIn("EA_SIGNING_SECRET", registry_text)
        self.assertNotIn("DATABASE_URL", registry_text)
        stored = json.loads(registry_text)
        self.assertEqual(stored["schema"], REGISTRY_SCHEMA)
        self.assertEqual(stored["entry_count"], 1)
        self.assertEqual(stored["pending_count"], 0)

        repeated = register_candidate_receipt(
            receipt,
            registry_path=self.registry,
        )
        self.assertTrue(repeated["idempotent"])
        posture = registered_candidate_receipt_postures(registry_path=self.registry)
        self.assertEqual(len(posture), 1)
        self.assertEqual(posture[0]["runtime_schema"], RUNTIME_SCHEMA_V5)
        self.assertFalse(posture[0]["legacy"])
        self.assertTrue(posture[0]["retention_eligible"])
        self.assertFalse(posture[0]["quarantined"])

    def test_new_legacy_v3_and_v4_registration_is_forbidden(self) -> None:
        for schema in (RUNTIME_SCHEMA_V3, RUNTIME_SCHEMA_V4):
            with self.subTest(schema=schema):
                receipt, _digest = self._write_json(
                    self.receipts / f"candidate-{schema.rsplit('.', 1)[-1]}.json",
                    self._runtime_payload(schema=schema),
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "manfred_candidate_registry_legacy_receipt_forbidden",
                ):
                    register_candidate_receipt(receipt, registry_path=self.registry)
                self.assertFalse(self.registry.exists())

    def test_schema_v1_registry_reads_and_quarantines_legacy_v3(self) -> None:
        payload = self._runtime_payload(schema=RUNTIME_SCHEMA_V3)
        receipt, digest = self._write_json(self.receipts / "legacy-v3.json", payload)
        entry = self._registry_entry(receipt, digest, payload)
        self._write_json(
            self.registry,
            {
                "schema": REGISTRY_SCHEMA,
                "entry_count": 1,
                "entries": [entry],
                "pending_count": 0,
                "pending": [],
            },
        )

        self.assertEqual(
            registered_candidate_receipts(registry_path=self.registry),
            [receipt.resolve()],
        )
        posture = registered_candidate_receipt_postures(registry_path=self.registry)
        self.assertEqual(
            posture,
            [
                {
                    **entry,
                    "runtime_schema": RUNTIME_SCHEMA_V3,
                    "legacy": True,
                    "retention_eligible": False,
                    "quarantined": True,
                    "quarantine_reason": "legacy_runtime_receipt_v3",
                    "automatic_retirement_authorized": False,
                }
            ],
        )
        compacted = compact_candidate_registry(
            set(),
            registry_path=self.registry,
        )
        self.assertEqual(compacted["before_count"], 1)
        self.assertEqual(compacted["after_count"], 1)
        self.assertTrue(receipt.exists())

    def test_schema_v1_registry_reads_and_quarantines_legacy_v4_metadata(
        self,
    ) -> None:
        payload = self._runtime_payload(schema=RUNTIME_SCHEMA_V4)
        receipt, digest = self._write_json(self.receipts / "legacy-v4.json", payload)
        entry = self._registry_entry(receipt, digest, payload)
        self._write_json(
            self.registry,
            {
                "schema": REGISTRY_SCHEMA,
                "entry_count": 1,
                "entries": [entry],
                "pending_count": 0,
                "pending": [],
            },
        )

        posture = registered_candidate_receipt_postures(registry_path=self.registry)

        self.assertEqual(posture[0]["runtime_schema"], RUNTIME_SCHEMA_V4)
        self.assertTrue(posture[0]["legacy"])
        self.assertFalse(posture[0]["retention_eligible"])
        self.assertTrue(posture[0]["quarantined"])
        self.assertEqual(
            posture[0]["quarantine_reason"],
            "legacy_runtime_receipt_v4",
        )

    def test_v5_container_identity_drift_is_rejected(self) -> None:
        payload = self._runtime_payload()
        final = dict(payload["candidate_container_images_final"])
        final["revision_label"] = REVISION_B
        payload["candidate_container_images_final"] = final
        receipt, _digest = self._write_json(
            self.receipts / "container-drift.json",
            payload,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_receipt_container_identity_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

    def test_v5_revision_disagreement_is_rejected(self) -> None:
        payload = self._runtime_payload()
        identity = dict(payload["runtime_version_identity"])
        identity["body_commit_sha"] = REVISION_B
        payload["runtime_version_identity"] = identity
        receipt, _digest = self._write_json(
            self.receipts / "mismatch.json",
            payload,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_receipt_identity_invalid",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)
        self.assertFalse(self.registry.exists())

    def test_receipt_candidate_port_requires_an_exact_integer(self) -> None:
        for index, invalid_port in enumerate((True, "18091", 18091.0)):
            with self.subTest(port=invalid_port):
                payload = self._runtime_payload()
                payload["candidate_port"] = invalid_port
                receipt, _digest = self._write_json(
                    self.receipts / f"invalid-port-{index}.json",
                    payload,
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "manfred_candidate_registry_receipt_invalid",
                ):
                    register_candidate_receipt(receipt, registry_path=self.registry)
        self.assertFalse(self.registry.exists())

    def test_pending_port_requires_an_exact_integer(self) -> None:
        for invalid_port in (True, "18091", 18091.0):
            with self.subTest(port=invalid_port):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "manfred_candidate_registry_pending_invalid",
                ):
                    register_candidate_pending(
                        project=PROJECT,
                        port=invalid_port,
                        receipt_path=self.receipts / "candidate.json",
                        image=f"ea-runtime:memorial-{REVISION_A}",
                        image_id=IMAGE_ID_A,
                        revision=REVISION_A,
                        registry_path=self.registry,
                    )
        self.assertFalse(self.registry.exists())

    def test_persisted_cross_set_receipt_path_collision_is_rejected(self) -> None:
        payload = self._runtime_payload()
        receipt, digest = self._write_json(
            self.receipts / "shared.json",
            payload,
        )
        self._write_json(
            self.registry,
            {
                "schema": REGISTRY_SCHEMA,
                "entry_count": 1,
                "entries": [self._registry_entry(receipt, digest, payload)],
                "pending_count": 1,
                "pending": [
                    {
                        "project": PROJECT_B,
                        "port": 18092,
                        "receipt_path": str(receipt.resolve()),
                        "image": f"ea-runtime:memorial-{REVISION_B}",
                        "image_id": IMAGE_ID_B,
                        "revision": REVISION_B,
                        "created_at": "2026-07-14T13:57:31Z",
                    }
                ],
            },
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_pending_invalid",
        ):
            registered_candidate_pending(registry_path=self.registry)

    def test_pending_cannot_claim_registered_receipt_path(self) -> None:
        receipt, _digest = self._write_json(
            self.receipts / "registered-shared.json",
            self._runtime_payload(),
        )
        register_candidate_receipt(receipt, registry_path=self.registry)

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_receipt_path_conflict",
        ):
            register_candidate_pending(
                project=PROJECT_B,
                port=18092,
                receipt_path=receipt,
                image=f"ea-runtime:memorial-{REVISION_B}",
                image_id=IMAGE_ID_B,
                revision=REVISION_B,
                registry_path=self.registry,
            )
        self.assertEqual(
            registered_candidate_receipts(registry_path=self.registry),
            [receipt.resolve()],
        )

    def test_receipt_cannot_claim_another_projects_pending_path(self) -> None:
        receipt = self.receipts / "pending-shared.json"
        register_candidate_pending(
            project=PROJECT_B,
            port=18092,
            receipt_path=receipt,
            image=f"ea-runtime:memorial-{REVISION_B}",
            image_id=IMAGE_ID_B,
            revision=REVISION_B,
            registry_path=self.registry,
        )
        self._write_json(receipt, self._runtime_payload())

        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_receipt_path_conflict",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)
        pending = registered_candidate_pending(registry_path=self.registry)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["project"], PROJECT_B)

    def test_pending_identity_mismatch_is_rejected_and_preserved(self) -> None:
        receipt = self.receipts / "candidate.json"
        register_candidate_pending(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=f"ea-runtime:memorial-{REVISION_A}",
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self._write_json(
            receipt,
            self._runtime_payload(port=18092),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_pending_mismatch",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)
        pending = registered_candidate_pending(registry_path=self.registry)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["project"], PROJECT)

    def test_pending_only_crash_state_clears_only_after_absence_proof(self) -> None:
        receipt = self.receipts / "pending-only.json"
        image = f"ea-runtime:memorial-{REVISION_A}"
        register_candidate_pending(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        state = candidate_registry_recovery_state(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self.assertEqual(state["state"], "pending_only")
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_recovery_not_proven",
        ):
            clear_candidate_pending_exact(
                project=PROJECT,
                port=18091,
                receipt_path=receipt,
                image=image,
                image_id=IMAGE_ID_A,
                revision=REVISION_A,
                resources_absent=False,
                registry_path=self.registry,
            )
        self.assertEqual(
            len(registered_candidate_pending(registry_path=self.registry)), 1
        )
        cleared = clear_candidate_pending_exact(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            resources_absent=True,
            registry_path=self.registry,
        )
        self.assertTrue(cleared["pending_cleared"])
        self.assertFalse(cleared["receipt_preserved"])
        self.assertEqual(registered_candidate_pending(registry_path=self.registry), [])

    def test_pending_receipt_crash_state_is_exact_and_receipt_is_preserved(
        self,
    ) -> None:
        receipt = self.receipts / "pending-receipt.json"
        image = f"ea-runtime:memorial-{REVISION_A}"
        register_candidate_pending(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        _path, digest = self._write_json(receipt, self._runtime_payload())
        state = candidate_registry_recovery_state(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self.assertEqual(state["state"], "pending_receipt")
        self.assertEqual(state["receipt_sha256"], digest)
        cleared = clear_candidate_pending_exact(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            resources_absent=True,
            expected_receipt_sha256=digest,
            registry_path=self.registry,
        )
        self.assertTrue(cleared["receipt_preserved"])
        self.assertTrue(receipt.exists())
        self.assertEqual(registered_candidate_pending(registry_path=self.registry), [])

    def test_interrupted_no_replace_publication_is_reported_for_recovery(self) -> None:
        receipt = self.receipts / "interrupted-publication.json"
        image = f"ea-runtime:memorial-{REVISION_A}"
        register_candidate_pending(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        temporary, _digest = self._write_json(
            self.receipts / ".ea-manfred-receipt.1234.abcdef012345abcdef012345.tmp",
            self._runtime_payload(),
        )
        os.link(temporary, receipt)
        self.assertEqual(receipt.stat().st_nlink, 2)
        state = candidate_registry_recovery_state(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=image,
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self.assertEqual(state["state"], "pending_receipt_unreadable")
        self.assertEqual(
            len(registered_candidate_pending(registry_path=self.registry)), 1
        )

    def test_registered_receipt_is_restart_recoverable(self) -> None:
        receipt, digest = self._write_json(
            self.receipts / "registered-recovery.json",
            self._runtime_payload(),
        )
        register_candidate_receipt(receipt, registry_path=self.registry)
        state = candidate_registry_recovery_state(
            project=PROJECT,
            port=18091,
            receipt_path=receipt,
            image=f"ea-runtime:memorial-{REVISION_A}",
            image_id=IMAGE_ID_A,
            revision=REVISION_A,
            registry_path=self.registry,
        )
        self.assertEqual(state["state"], "registered_receipt")
        self.assertEqual(state["receipt_sha256"], digest)

    def test_registration_can_require_matching_pending_intent(self) -> None:
        receipt, _digest = self._write_json(
            self.receipts / "requires-pending.json",
            self._runtime_payload(),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_pending_missing",
        ):
            register_candidate_receipt(
                receipt,
                registry_path=self.registry,
                require_pending=True,
            )
        self.assertFalse(self.registry.exists())

    def test_registered_project_cannot_be_rebound(self) -> None:
        first, _digest = self._write_json(
            self.receipts / "first.json",
            self._runtime_payload(),
        )
        register_candidate_receipt(first, registry_path=self.registry)
        second, _digest = self._write_json(
            self.receipts / "second.json",
            self._runtime_payload(revision=REVISION_B, image_id=IMAGE_ID_B),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_project_already_registered",
        ):
            register_candidate_receipt(second, registry_path=self.registry)
        self.assertEqual(
            registered_candidate_receipts(registry_path=self.registry),
            [first.resolve()],
        )

    def test_registered_receipt_path_cannot_be_rebound_to_another_project(
        self,
    ) -> None:
        receipt, _digest = self._write_json(
            self.receipts / "registered-path.json",
            self._runtime_payload(),
        )
        register_candidate_receipt(receipt, registry_path=self.registry)
        registry_before = self.registry.read_bytes()

        self._write_json(
            receipt,
            self._runtime_payload(
                project=PROJECT_B,
                revision=REVISION_B,
                image_id=IMAGE_ID_B,
                port=18092,
            ),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_receipt_path_conflict",
        ):
            register_candidate_receipt(receipt, registry_path=self.registry)

        self.assertEqual(self.registry.read_bytes(), registry_before)

    def test_receipt_symlink_and_hardlink_are_rejected(self) -> None:
        target, _digest = self._write_json(
            self.receipts / "target.json",
            self._runtime_payload(),
        )
        symlink = self.receipts / "symlink.json"
        symlink.symlink_to(target)
        with self.assertRaises(RuntimeError):
            register_candidate_receipt(symlink, registry_path=self.registry)
        symlink.unlink()

        hardlink = self.receipts / "hardlink.json"
        os.link(target, hardlink)
        self.assertEqual(target.stat().st_nlink, 2)
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_file_invalid",
        ):
            register_candidate_receipt(hardlink, registry_path=self.registry)

    def test_registry_mode_symlink_and_hardlink_are_rejected(self) -> None:
        payload = {
            "schema": REGISTRY_SCHEMA,
            "entry_count": 0,
            "entries": [],
            "pending_count": 0,
            "pending": [],
        }
        self._write_json(self.registry, payload)
        self.registry.chmod(0o644)
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_file_invalid",
        ):
            registered_candidate_pending(registry_path=self.registry)

        self.registry.unlink()
        target, _digest = self._write_json(self.root / "registry-target.json", payload)
        self.registry.symlink_to(target)
        with self.assertRaises(RuntimeError):
            registered_candidate_pending(registry_path=self.registry)

        self.registry.unlink()
        os.link(target, self.registry)
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_file_invalid",
        ):
            registered_candidate_pending(registry_path=self.registry)

    def test_insecure_registry_parent_is_rejected(self) -> None:
        insecure = self.root / "insecure"
        insecure.mkdir(mode=0o700)
        insecure.chmod(0o770)
        with self.assertRaisesRegex(
            RuntimeError,
            "manfred_candidate_registry_parent_invalid",
        ):
            register_candidate_pending(
                project=PROJECT,
                port=18091,
                receipt_path=self.receipts / "candidate.json",
                image=f"ea-runtime:memorial-{REVISION_A}",
                image_id=IMAGE_ID_A,
                revision=REVISION_A,
                registry_path=insecure / "registry.json",
            )


if __name__ == "__main__":
    unittest.main()
