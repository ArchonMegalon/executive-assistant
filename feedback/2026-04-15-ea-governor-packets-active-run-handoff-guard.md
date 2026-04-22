Title: EA governor-packet active-run handoff guard

Package: next90-m106-ea-governor-packets

What changed:
- Recorded that this pass reviewed the active-run handoff for successor frontier `1758984842`, package `next90-m106-ea-governor-packets`, and the closed EA-owned surfaces.
- Pinned the handoff review to the worker-safety instruction that operator telemetry and active-run helper commands must not be invoked inside this run.
- Kept the proof repo-local without making repo tests depend on mutable handoff tail text.
- Updated `docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` and `README.md` so future shards can distinguish a repeated assignment handoff from unfinished EA-owned packet synthesis.

Proof:
- `python tests/test_chummer_governor_packet_pack.py` exits 0 with `ran=17 failed=0`.
- `python -m py_compile tests/test_chummer_governor_packet_pack.py` exits 0.

Result:
- The EA package remains closed for `operator_packets:weekly_governor` and `reporter_followthrough:release_truth`; any remaining milestone `106` work belongs to Fleet, Hub, Registry, or design sibling lanes.
