# Chummer Governor Packet Pack

This directory carries EA-local proof for `next90-m106-ea-governor-packets`.

The pack does not make EA a release authority or support-case database. It defines the bounded synthesis contract EA can own: an operator-ready weekly governor packet and reporter followthrough mail readiness compiled from the same mirrored truth anchors.

Current contract artifact:

* `CHUMMER_GOVERNOR_PACKET_PACK.yaml`
* `OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml`
* `SUCCESSOR_HANDOFF_CLOSEOUT.yaml`

The shared evidence anchors are:

* mirrored weekly product pulse
* EA Chummer5a parity-lab pack
* feedback release gate
* reporter progress email workflow

Reporter `fix_available` output stays fail-closed until Registry truth says the fix reached the reporter channel. Operator packet copy may recommend launch, freeze, canary, rollback, or focus-shift posture, but Fleet and design retain decision and canon authority.

The packet now carries explicit gates for every operator posture and reporter mail stage. That keeps EA from producing launch, canary, rollback, or fix-available copy from incomplete support, readiness, parity, or release evidence.

The operator packet and reporter followthrough specimen now also share one normalized truth bundle, `ea-m106-governor-readiness-parity-support-release-v1`. That bundle is the EA-local contract that release health, flagship readiness, journey gates, support closure, parity evidence, reporter followthrough, and release-channel truth are projected once and reused by both packet families.

`OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml` is the handoff-ready projection shape: it shows the operator packet and reporter followthrough payloads using the same evidence anchors, while keeping Fleet, Hub, Registry, and design as the owning truth planes.

`SUCCESSOR_HANDOFF_CLOSEOUT.yaml` is the machine-readable repeat-prevention manifest for successor frontier `1758984842`. It names the completed outputs, proof artifacts, proof command, canonical registry and queue authority, runtime-safety posture, active-run handoff review, and the sibling owner lanes that must not be treated as EA-owned work.

The closeout manifest also carries `terminal_verification_policy`. Once the canonical registry task `106.2`, the design and Fleet queue rows, and `python tests/test_chummer_governor_packet_pack.py` all still agree, future workers should not add another timestamp-only active-run handoff refresh for this same EA package. A newer handoff timestamp is an assignment signal, not EA-owned implementation evidence, unless it changes the package authority or one of the guarded proof artifacts fails. Later repeated handoffs for the same package id and frontier id are covered by that policy without adding per-handoff manifest rows.

The terminal policy also pins the post-terminal proof command result to the current direct-run test inventory. Historical verification rows may retain their original runner count, but any new verification after the terminal timestamp must cite the current `ran=20 failed=0` result instead of reusing older `ran=17` evidence.

Implementation-only retries for the same package id and frontier id are covered by the same terminal policy. They must not create new timestamp-only feedback notes, append task-local telemetry or active-run handoff timestamps to proof artifacts, or refresh queue and registry evidence just because the worker was reassigned. Only real authority drift or a failing package proof command can reopen the EA packet work.

The terminal policy now also carries `retry_helper_loop_guard`. That guard is specifically for implementation-only retries after helper-loop churn: task-local telemetry and `ACTIVE_RUN_HANDOFF.generated.md` may be read as assignment context when the prompt requires it, but supervisor status, ETA, polling, active-run wait loops, operator telemetry, or `codexea status`/`codexea eta` helpers are not orientation, proof, or reopen evidence for this EA package. The repo-local proof boundary remains the packet pack, specimens, handoff closeout, and focused test file.

For this implementation-only retry, the guard also pins the direct-read context set from the worker prompt and marks invented orientation as denied. That preserves the useful assignment inputs without letting those mutable runtime files become package evidence or a reason to append another feedback note.

The same guard now records the required startup context as prompt-relative assignment intake instead of pinning a single retry run id. Workers must read the task-local telemetry path supplied by the active prompt first, at least one listed canonical repo file second, the worker-safe handoff when required, and the target `docs`, `tests`, `feedback`, or `skills` files before editing. Those reads are assignment intake, not proof, and they must not be substituted with supervisor status, ETA, polling, active-run wait loops, operator telemetry, or invented orientation helpers.

The retry context pattern is recorded only inside the terminal guard as assignment intake: task-local telemetry under `/docker/fleet/state/chummer_design_supervisor/shard-12/runs/*/TASK_LOCAL_TELEMETRY.generated.json` and handoff path `/docker/fleet/state/chummer_design_supervisor/shard-12/ACTIVE_RUN_HANDOFF.generated.md`. Matching run ids, telemetry paths, and handoff timestamps must not be copied into completed outputs, proof artifacts, queue proof, registry evidence, or successor verification history unless a guarded reopen trigger exposes real artifact or authority drift.

`tests/test_chummer_governor_packet_pack.py` now fails closed when the package drifts from the Fleet-published successor queue, the design-owned successor queue, milestone `106` work task `106.2`, mirrored progress-mail workflow stages, shared evidence bindings, the EA closeout feedback note, the handoff closeout manifest, or the recorded active-run handoff review for frontier `1758984842`. It also checks recorded successor-wave verification notes for blocked active-run helper or operator telemetry output, while still allowing handoff-assignment review text. It can run directly with `python tests/test_chummer_governor_packet_pack.py` in worker runtimes where `pytest` is not installed; when the image has only `python3`, the closeout manifest permits `python3 tests/test_chummer_governor_packet_pack.py` as the same direct-run proof module with the same expected result. That is the local proof boundary for this EA-owned successor slice; sibling Fleet, Hub, Registry, and design packages remain open under their own queue rows.

Successor frontier `1758984842` is therefore complete for the EA-owned surfaces in this package. Future shards should verify this pack and its focused tests before reopening packet synthesis; any remaining milestone `106` execution belongs to the sibling Fleet, Hub, Registry, or design packages.
