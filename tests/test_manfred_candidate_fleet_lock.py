from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.manfred_candidate_fleet_lock import (
    FLEET_LOCK_BUSY,
    FLEET_LOCK_INVALID,
    FLEET_LOCK_PATH,
    hold_candidate_fleet_lock,
)


class CandidateFleetLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.lock_path = self.root / FLEET_LOCK_PATH.name

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_lock_is_private_nonblocking_and_reusable(self) -> None:
        with hold_candidate_fleet_lock(lock_path=self.lock_path) as evidence:
            self.assertEqual(
                evidence,
                {
                    "scope": "manfred_candidate_fleet",
                    "lock_file": FLEET_LOCK_PATH.name,
                    "exclusive": True,
                    "nonblocking": True,
                },
            )
            metadata = self.lock_path.stat()
            self.assertTrue(stat.S_ISREG(metadata.st_mode))
            self.assertEqual(metadata.st_uid, os.getuid())
            self.assertEqual(metadata.st_nlink, 1)
            self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
            with hold_candidate_fleet_lock(
                lock_path=self.lock_path,
                skip_if_busy=True,
            ) as skipped:
                self.assertIsNone(skipped)
            with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_BUSY):
                with hold_candidate_fleet_lock(lock_path=self.lock_path):
                    self.fail("a held fleet lock must not be re-entered")

        with hold_candidate_fleet_lock(lock_path=self.lock_path) as reacquired:
            self.assertIsNotNone(reacquired)

    def test_wrong_lock_filename_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_INVALID):
            with hold_candidate_fleet_lock(lock_path=self.root / "different.lock"):
                self.fail("wrong lock filename was accepted")

    def test_world_writable_nonsticky_parent_is_rejected(self) -> None:
        insecure = self.root / "insecure"
        insecure.mkdir(mode=0o700)
        insecure.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_INVALID):
            with hold_candidate_fleet_lock(lock_path=insecure / FLEET_LOCK_PATH.name):
                self.fail("insecure lock parent was accepted")

    def test_group_writable_nonsticky_parent_is_rejected(self) -> None:
        insecure = self.root / "group-writable"
        insecure.mkdir(mode=0o700)
        insecure.chmod(0o770)
        with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_INVALID):
            with hold_candidate_fleet_lock(lock_path=insecure / FLEET_LOCK_PATH.name):
                self.fail("group-writable non-sticky lock parent was accepted")

    def test_group_writable_sticky_parent_is_accepted(self) -> None:
        sticky = self.root / "group-writable-sticky"
        sticky.mkdir(mode=0o700)
        sticky.chmod(0o1770)
        with hold_candidate_fleet_lock(
            lock_path=sticky / FLEET_LOCK_PATH.name
        ) as evidence:
            self.assertIsNotNone(evidence)

    def test_symlink_lock_is_rejected_without_following(self) -> None:
        target = self.root / "target"
        target.write_bytes(b"")
        target.chmod(0o600)
        self.lock_path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            with hold_candidate_fleet_lock(lock_path=self.lock_path):
                self.fail("symlink lock was accepted")

    def test_hardlinked_lock_is_rejected(self) -> None:
        target = self.root / "target"
        target.write_bytes(b"")
        target.chmod(0o600)
        os.link(target, self.lock_path)
        self.assertEqual(target.stat().st_nlink, 2)
        with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_INVALID):
            with hold_candidate_fleet_lock(lock_path=self.lock_path):
                self.fail("hardlinked lock was accepted")

    def test_non_private_existing_lock_is_rejected(self) -> None:
        self.lock_path.write_bytes(b"")
        self.lock_path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, FLEET_LOCK_INVALID):
            with hold_candidate_fleet_lock(lock_path=self.lock_path):
                self.fail("non-private lock was accepted")


if __name__ == "__main__":
    unittest.main()
