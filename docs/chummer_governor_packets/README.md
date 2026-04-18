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
* Fleet weekly governor packet
* Fleet support case packets
* Registry release-channel truth
* feedback release gate
* reporter progress email workflow

Reporter `fix_available` output stays fail-closed until Registry truth says the fix reached the reporter channel. Operator packet copy may recommend launch, freeze, canary, rollback, or focus-shift posture, but Fleet and design retain decision and canon authority.

The packet now carries explicit gates for every operator posture and reporter mail stage. That keeps EA from producing launch, canary, rollback, or fix-available copy from incomplete support, readiness, parity, or release evidence.

The operator packet and reporter followthrough specimen now also share one normalized truth bundle, `ea-m106-governor-readiness-parity-support-release-v1`. That bundle is the EA-local contract that release health, flagship readiness, journey gates, support closure, parity evidence, reporter followthrough, and release-channel truth are projected once and reused by both packet families.

That bundle is now explicit about the live packet sources, not only the abstract policy inputs. `CHUMMER_GOVERNOR_PACKET_PACK.yaml` binds EA output to Fleet's published `WEEKLY_GOVERNOR_PACKET.generated.json`, Fleet's published `SUPPORT_CASE_PACKETS.generated.json`, and Registry's published `RELEASE_CHANNEL.generated.json` alongside the mirrored pulse, parity, and workflow inputs. That keeps EA from synthesizing operator or reporter copy from a partial mirror when the live governor or release packet has already moved.

The live-source contract is now field-accurate as well as source-accurate. Operator synthesis reads Fleet's decision action and receipt routes from `measured_rollout_loop.decision_action_routes` and `measured_rollout_loop.decision_receipts`, not from nonexistent top-level rollout status fields, and the specimen pack records the normalization rule that maps Fleet's `launch_expand` and `freeze_launch` actions onto EA's `launch` and `freeze` packet vocabulary. Reporter followthrough bindings likewise state exactly which support-packet and release-channel fields must stay in the shared truth window before any fix-available mail can leave hold.

`OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml` is the handoff-ready projection shape: it shows the operator packet and reporter followthrough payloads using the same evidence anchors, while keeping Fleet, Hub, Registry, and design as the owning truth planes.

`SUCCESSOR_HANDOFF_CLOSEOUT.yaml` is the machine-readable repeat-prevention manifest for successor frontier `1758984842`. It names the completed outputs, proof artifacts, proof command, canonical registry and queue authority, runtime-safety posture, active-run handoff review, and the sibling owner lanes that must not be treated as EA-owned work.

The closeout manifest also carries `terminal_verification_policy`. Once the canonical registry task `106.2`, the design and Fleet queue rows, and `python tests/test_chummer_governor_packet_pack.py` all still agree, future workers should not add another timestamp-only active-run handoff refresh for this same EA package. A newer handoff timestamp is an assignment signal, not EA-owned implementation evidence, unless it changes the package authority or one of the guarded proof artifacts fails. Later repeated handoffs for the same package id and frontier id are covered by that policy without adding per-handoff manifest rows.

The terminal policy also pins the post-terminal proof command result to the current direct-run test inventory. Historical verification rows may retain their original runner count, but any new verification after the terminal timestamp must cite the current `ran=20 failed=0` result instead of reusing older `ran=17` evidence.

Implementation-only retries for the same package id and frontier id are covered by the same terminal policy. They must not create new timestamp-only feedback notes, append task-local telemetry or active-run handoff timestamps to proof artifacts, or refresh queue and registry evidence just because the worker was reassigned. Only real authority drift or a failing package proof command can reopen the EA packet work.

That same closure rule now applies to packet-artifact timestamps as well. A top-level `generated_at` refresh inside `CHUMMER_GOVERNOR_PACKET_PACK.yaml` or `OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml` is informational only and must not, by itself, append proof notes, refresh canonical queue or registry proof entries, or reopen the closed EA-owned packet slice.

If one of those two packet artifacts is refreshed, the other must carry the same top-level `generated_at`. The timestamps are still informational, but the closed packet pack should read as one synchronized snapshot window rather than two competing refresh moments.

Queue proof and registry evidence may cite only the terminal closeout trio:

* `feedback/2026-04-15-ea-governor-packets-package-closeout.md`
* `feedback/2026-04-15-chummer-governor-packets-successor-guard.md`
* `feedback/2026-04-15-ea-governor-packets-terminal-repeat-prevention.md`

Intermediate same-package pass notes and extra guard notes are historical context only; they are not canonical closeout proof for this package.

The terminal policy now also carries `retry_helper_loop_guard`. That guard is specifically for implementation-only retries after helper-loop churn: task-local telemetry and `ACTIVE_RUN_HANDOFF.generated.md` may be read as assignment context when the prompt requires it, but supervisor status, ETA, polling, active-run wait loops, operator telemetry, or `codexea status`/`codexea eta` helpers are not orientation, proof, or reopen evidence for this EA package. The repo-local proof boundary remains the packet pack, specimens, handoff closeout, and focused test file.

For this implementation-only retry, the guard also pins the direct-read context set from the worker prompt and marks invented orientation as denied. That preserves the useful assignment inputs without letting those mutable runtime files become package evidence or a reason to append another feedback note.

The same guard now records the required startup context as prompt-relative assignment intake instead of pinning a single retry run id. Workers must read the task-local telemetry path supplied by the active prompt first, at least one listed canonical repo file second, the worker-safe handoff when required, and the target `docs`, `tests`, `feedback`, or `skills` files before editing. Those reads are assignment intake, not proof, and they must not be substituted with supervisor status, ETA, polling, active-run wait loops, operator telemetry, or invented orientation helpers.

The guard now records the prompt-relative direct-read startup contract instead of pinning a stale retry run id. For this implementation-only retry shape, workers must read the task-local telemetry file first, one listed repo file second, and the target package files under `docs`, `tests`, `feedback`, or `skills` before editing. The first startup read must still match the exact task-local telemetry path named by the active prompt while satisfying the shard-local telemetry path pattern, so a previous retry run id cannot stay pinned as fake proof. The listed repo-file candidates and the prompt-named direct reads still include the closed biggest-wins registry, milestone spine, roadmap, worker-safe handoff, successor registry, and Fleet queue mirror, while any historical operator status snippets found in those files remain stale notes rather than commands to repeat.

That startup rule is intentionally exact for successor-wave retries: open the prompt-named task-local telemetry file first, then open one of the listed canonical repo files, then inspect the target package files directly. Do not replace that sequence with supervisor status or ETA checks, operator telemetry, active-run wait loops, or other invented orientation helpers. Those first reads only confirm assignment shape and proof boundaries; they are never queue proof, registry evidence, operator-packet evidence, or reporter-followthrough evidence.

The prompt-named canonical repo files are excluded just as explicitly. `NEXT_12_BIGGEST_WINS_REGISTRY.yaml`, `PROGRAM_MILESTONES.yaml`, `ROADMAP.md`, `ACTIVE_RUN_HANDOFF.generated.md`, `NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml`, and the Fleet successor queue mirror may be read to satisfy the worker prompt, but those paths must never migrate into completed outputs, proof artifacts, canonical registry evidence, design queue proof, Fleet queue proof, operator-packet evidence, or reporter-followthrough evidence for this closed EA package.

The retry context pattern is recorded only inside the terminal guard as assignment intake: task-local telemetry under `/var/lib/codex-fleet/chummer_design_supervisor/shard-12/runs/*/TASK_LOCAL_TELEMETRY.generated.json` and handoff path `/var/lib/codex-fleet/chummer_design_supervisor/shard-12/ACTIVE_RUN_HANDOFF.generated.md`. Matching run ids, telemetry paths, and handoff timestamps must not be copied into completed outputs, proof artifacts, queue proof, registry evidence, or successor verification history unless a guarded reopen trigger exposes real artifact or authority drift.

Implementation-only retry telemetry now has a bounded authority-shape check. Workers may use the task-local telemetry only to confirm the assignment still names `next90-m106-ea-governor-packets`, `executive-assistant`, milestone `106`, the two EA-owned surfaces, and the allowed `skills`, `tests`, `feedback`, and `docs` paths. Telemetry run ids, focus text, first-command receipts, timestamps, stdout, stderr, and helper-loop history remain excluded from packet proof, queue proof, registry evidence, reporter followthrough evidence, and successor verification history.

Startup read receipts are now explicitly excluded from package proof. The prompt-required `cat`, `sed`, and direct target reads are assignment intake only: they can confirm package shape and queue authority, but their command order, stdout or stderr, handoff tail text, helper-loop history, and historical operator snippets cannot be promoted into operator packet evidence, reporter followthrough evidence, queue proof, registry evidence, or successor verification history.

The terminal policy's forbidden retry feedback globs are executable guardrails, not only prose. A same-package retry after the terminal closeout must leave no `feedback/2026-04-16-ea-governor-packets-*`, `feedback/2026-04-17-ea-governor-packets-*`, or `feedback/2026-04-18-ea-governor-packets-*` package proof notes behind.

`tests/test_chummer_governor_packet_pack.py` now fails closed when the package drifts from the Fleet-published successor queue, the design-owned successor queue, milestone `106` work task `106.2`, mirrored progress-mail workflow stages, shared evidence bindings, the EA closeout feedback note, the handoff closeout manifest, or the recorded active-run handoff review for frontier `1758984842`. It also checks recorded successor-wave verification notes for blocked active-run helper or operator telemetry output, while still allowing handoff-assignment review text. It can run directly with `python tests/test_chummer_governor_packet_pack.py` in worker runtimes where `pytest` is not installed; when the image has only `python3`, the closeout manifest permits `python3 tests/test_chummer_governor_packet_pack.py` as the same direct-run proof module with the same expected result. That is the local proof boundary for this EA-owned successor slice; sibling Fleet, Hub, Registry, and design packages remain open under their own queue rows.

Successor frontier `1758984842` is therefore complete for the EA-owned surfaces in this package. Future shards should verify this pack and its focused tests before reopening packet synthesis; any remaining milestone `106` execution belongs to the sibling Fleet, Hub, Registry, or design packages.
