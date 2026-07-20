#!/usr/bin/env python3
"""Materialize, but never install, the reviewed schema-v6 clock-floor fix.

The live sentinel is a root-owned, checksum-pinned executable outside this
repository.  Restarting it starts a new qualification epoch.  This tool
therefore accepts only the exact currently deployed source, applies a bounded
source transformation, and writes a new private candidate file.  It never
touches the live source, checksum manifest, service, or sentinel state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Final, Sequence


LIVE_SOURCE: Final = Path("/usr/local/libexec/vexp-codex-sentinel-v6.mjs")
EXPECTED_LIVE_SOURCE_SHA256: Final = (
    "fa094bb04d9bcb22d11decb04f750d6ae7a2fa9984e36c6c7fec2dfe927719ce"
)
MAX_SOURCE_BYTES: Final = 512 * 1024
CONTRACT_NAME: Final = "ea.vexp_schema_v6_sentinel_source_candidate.v1"


class CandidateError(RuntimeError):
    """Stable source-candidate denial."""


PATCHES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "epoch_wall_clock_single_sample",
        """  state.epoch_started_at = new Date().toISOString();
  state.epoch_started_ms = Date.now();
  state.epoch_started_monotonic_ms = performance.now();""",
        """  const epochStartedMs = Date.now();
  state.epoch_started_at = new Date(epochStartedMs).toISOString();
  state.epoch_started_ms = epochStartedMs;
  state.epoch_started_monotonic_ms = performance.now();""",
    ),
    (
        "deterministic_earliest_helpers",
        """function effectiveQualificationElapsedMs(now = performance.now()) {
  return Math.max(
    0,
    now - Number(state.epoch_started_monotonic_ms || now)
      - qualificationDeferredDurationMs(now),
  );
}

function canonicalDeferralReason(issue) {""",
        """function effectiveQualificationElapsedMs(now = performance.now()) {
  return Math.max(
    0,
    now - Number(state.epoch_started_monotonic_ms || now)
      - qualificationDeferredDurationMs(now),
  );
}

function qualificationEarliestCompletionMs(now = performance.now()) {
  const epochStartedMs = Number(state.epoch_started_ms);
  const epochStartedMonotonicMs = Number(state.epoch_started_monotonic_ms);
  if (!Number.isFinite(epochStartedMs)
      || !Number.isFinite(epochStartedMonotonicMs)) return null;
  const deferredMs = Math.max(
    0,
    Math.ceil(qualificationDeferredDurationMs(now)),
  );
  return epochStartedMs + qualificationDurationMs + deferredMs;
}

function qualificationEarliestCompletionAt(now = performance.now()) {
  const earliestMs = qualificationEarliestCompletionMs(now);
  return Number.isFinite(earliestMs) ? new Date(earliestMs).toISOString() : null;
}

function qualificationWallClockFloorReached(
  wallClockMs = Date.now(),
  monotonicNow = performance.now(),
) {
  const earliestMs = qualificationEarliestCompletionMs(monotonicNow);
  return Number.isFinite(wallClockMs)
    && Number.isFinite(earliestMs)
    && wallClockMs >= earliestMs;
}

function canonicalDeferralReason(issue) {""",
    ),
    (
        "emit_uses_epoch_floor",
        """    state.qualification_earliest_completion_at = !hasEpoch
      ? null
      : state.qualified_at || new Date(
        Date.now() + Math.max(0, qualificationDurationMs - effectiveElapsedMs),
      ).toISOString();""",
        """    state.qualification_earliest_completion_at = !hasEpoch
      ? null
      : qualificationEarliestCompletionAt(monotonicNow);""",
    ),
    (
        "reset_uses_epoch_floor",
        """  state.qualification_earliest_completion_at = new Date(
    Date.now() + qualificationDurationMs,
  ).toISOString();""",
        """  state.qualification_earliest_completion_at =
    qualificationEarliestCompletionAt(state.epoch_started_monotonic_ms);""",
    ),
    (
        "terminal_requires_wall_floor",
        """          && licenseReady && appArmorReady && state.daily_bursts >= 7) {""",
        """          && licenseReady && appArmorReady && state.daily_bursts >= 7
          && qualificationWallClockFloorReached(Date.now(), heartbeatNow)) {""",
    ),
    (
        "policy_selftest_exact_floor",
        """  resumeQualification(1_200);
  assert(
    state.qualification_deferred_ms === 1_000
      && state.qualification_deferred_since_monotonic_ms === null
      && state.qualification_deferred_since_at === null
      && effectiveQualificationElapsedMs(2_200) === 1_100,
    \"completed deferment was not persisted exactly once\",
  );
  metrics.cgroups.host_codex.memory_events.high--;""",
        """  resumeQualification(1_200);
  assert(
    state.qualification_deferred_ms === 1_000
      && state.qualification_deferred_since_monotonic_ms === null
      && state.qualification_deferred_since_at === null
      && effectiveQualificationElapsedMs(2_200) === 1_100,
    \"completed deferment was not persisted exactly once\",
  );
  state.epoch_started_at = \"2026-07-19T02:03:22.235Z\";
  state.epoch_started_ms = Date.parse(state.epoch_started_at);
  state.epoch_started_monotonic_ms = 100;
  state.qualification_deferred_ms = 0;
  state.qualification_deferred_since_monotonic_ms = null;
  assert(
    qualificationEarliestCompletionAt(100)
      === \"2026-07-26T02:03:22.235Z\",
    \"earliest completion drifted before the exact seven-day wall-clock floor\",
  );
  assert(
    !qualificationWallClockFloorReached(
      Date.parse(\"2026-07-26T02:03:22.234Z\"),
      100,
    )
      && qualificationWallClockFloorReached(
        Date.parse(\"2026-07-26T02:03:22.235Z\"),
        100,
      ),
    \"terminal wall-clock floor accepted a one-millisecond-early claim\",
  );
  state.qualification_deferred_since_monotonic_ms = 100;
  assert(
    qualificationEarliestCompletionAt(100.25)
      === \"2026-07-26T02:03:22.236Z\",
    \"fractional active deferment was rounded down\",
  );
  state.qualification_deferred_since_monotonic_ms = null;
  metrics.cgroups.host_codex.memory_events.high--;""",
    ),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_stable_regular_file(path: Path) -> bytes:
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise CandidateError("sentinel_source_unavailable") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or not 0 < before.st_size <= MAX_SOURCE_BYTES
    ):
        raise CandidateError("sentinel_source_untrusted")
    try:
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise CandidateError("sentinel_source_unavailable") from exc

    def identity(row: os.stat_result) -> tuple[int, ...]:
        return (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )

    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise CandidateError("sentinel_source_changed_during_read")
    return raw


def patched_source(raw: bytes, *, expected_sha256: str) -> bytes:
    if _sha256(raw) != expected_sha256:
        raise CandidateError("sentinel_source_digest_mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandidateError("sentinel_source_encoding_invalid") from exc
    for label, old, new in PATCHES:
        if text.count(old) != 1:
            raise CandidateError(f"sentinel_source_patch_context_invalid:{label}")
        text = text.replace(old, new, 1)
    candidate = text.encode("utf-8")
    if candidate == raw:
        raise CandidateError("sentinel_source_patch_empty")
    return candidate


def _write_new_private_file(path: Path, raw: bytes) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise CandidateError("candidate_output_location_invalid")
    try:
        parent = path.parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise CandidateError("candidate_output_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise CandidateError("candidate_output_parent_untrusted")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(raw):
            written += os.write(descriptor, raw[written:])
        os.fsync(descriptor)
    except OSError as exc:
        raise CandidateError("candidate_output_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def materialize_candidate(
    *,
    source: Path,
    output: Path,
    expected_sha256: str = EXPECTED_LIVE_SOURCE_SHA256,
) -> dict[str, object]:
    source = source.absolute()
    output = output.absolute()
    if source == output:
        raise CandidateError("live_source_overwrite_forbidden")
    raw = _read_stable_regular_file(source)
    candidate = patched_source(raw, expected_sha256=expected_sha256)
    _write_new_private_file(output, candidate)
    return {
        "contract_name": CONTRACT_NAME,
        "status": "candidate_materialized_not_installed",
        "source_name": source.name,
        "source_sha256": _sha256(raw),
        "candidate_name": output.name,
        "candidate_sha256": _sha256(candidate),
        "patches": [label for label, _old, _new in PATCHES],
        "live_source_modified": False,
        "sentinel_state_modified": False,
        "service_restarted": False,
        "qualification_epoch_preserved": True,
        "installation_authority": False,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=LIVE_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = materialize_candidate(source=args.source, output=args.output)
    except CandidateError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
