Title: Chummer governor-packet successor guard

Package: next90-m106-ea-governor-packets

Owned surfaces: operator_packets:weekly_governor, reporter_followthrough:release_truth

What changed:
- Added explicit proof guardrails to `docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml` for the canonical queue row, milestone `106`, work task `106.2`, dependencies `101` through `105`, and allowed paths.
- Tightened `tests/test_chummer_governor_packet_pack.py` so the EA pack must keep matching the successor queue, canonical registry, mirrored progress-mail workflow stage payloads, and shared evidence bindings.
- Updated `docs/chummer_governor_packets/README.md` to point future shards at the fail-closed proof boundary.

Proof:
- `python -m pytest tests/test_chummer_governor_packet_pack.py` could not run because `pytest` is not installed in the EA environment.
- Direct Python invocation of every `tests/test_chummer_governor_packet_pack.py::test_*` function passed with `ran=12 failed=0`.

Result:
- EA's governor-packet slice is guarded against queue, registry, source-binding, and reporter-workflow drift without reopening the closed flagship wave or claiming Fleet, Hub, Registry, or design-owned authority.
