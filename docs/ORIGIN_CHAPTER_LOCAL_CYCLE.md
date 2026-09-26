# Local Origin chapter execution cycle

`scripts/origin_chapter_cycle.py` composes the existing private First Book
preparation, outline, writer and Hub-result adapters. It advances **one exact
approved job** without an operator copying provider IDs/outlines between phases.
It does not create Hub jobs, select accounts, reserve credits, accept stories,
change a character or publish anything. Hub remains consent/job/reader authority.

## Private input and execution

Use the existing private worker packet with its exact `work_id`,
`execution_admission`, `approved_source` and `setup`. Add:

- `automatic_execution_approved: true` at the packet root;
- `chapter_generation_approved: true` inside `setup`;
- the owned `browser_session`, provider account hash and exact source digest.

Those assertions belong to the trusted local controller/operator, never the
public app or provider output. They cannot substitute for fresh Hub admission.
Input files remain owner-only; do not put tokens or browser cookies in packets.

For the initial book, keep the existing separate approvals:
`framework_generation_approved`, `outline_activation_approved` and
`maximum_book_credits: 1`. Optional `framework_project_discovery_approved: true`
allows the completed framework to be identified without manually copying its
provider ID. Discovery requires the exact retained dispatch session/page, a
unique expected title, the verified provider account, one provider ID and exact
premise/goal/audience. It cannot bind by title alone, leave an active generation,
start a second project or authorize a second credit. A lost/cold dispatch page
still requires explicit reconciliation using the existing project-binding path.

For a later chapter, supply the existing `previous` packet and
`setup.outline_update_approved: true`. The predecessor is not guessed from queue
order or provider slot count. Its exact Hub reader acceptance is checked before
continuing; old chapters and other outline slots remain unchanged. The paid book
is reused. The current chapter itself always stops at `review_required`.
New Hub jobs bind `previous` (request/source/receipt/accepted-text identity) and
`previousWorkId`. The worker must match both against the exact prior Hub result;
it cannot substitute another accepted chapter. A predecessor may have its own
history, but that history is not recursively copied into execution packets.
Historical null-edge jobs remain readable; their chronology is not inferred.

```sh
python3 -m scripts.origin_chapter_cycle \
  --packet-path /private/exact-approved-job.json \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --output-root /private/provider-journals \
  --cycles 30 --interval 10
```

Default execution is one non-waiting cycle. Bounded observation accepts at most
120 cycles with 2–60 seconds between them. The loop observes only named in-flight
transitions; it stops on reader approval requirements, reconciliation, unknown
states, transport errors or browser failures. It does not retry uncertain writes.
The root-wide cycle lease is held during observation waits. The controller must
also own the browser session exclusively; do not run older manual adapters in
parallel against that session or use a different journal root for the same book.

Setup, activation, outline saves, advancement and chapter generation retain their
existing separate fsynced dispatch fences. The cycle derives prepared inputs from
those validated journals, not a caller-supplied replacement mapping. A completed
Hub result needs only one GET and no browser. A missing journal after a consumed
admission is reconciliation-only, never permission to regenerate.

Before either initial Hub delivery or replacement of an unaccepted draft, the
worker screens the retained text for the observed FirstBook nonfiction scaffold:
`counter-argument` together with `actionable ... steps`. Detection stops with
`origin_worker_draft_needs_editorial_review`; the original and any separately
captured revision remain private and unchanged. Selecting an exact text digest
is not an editorial approval and cannot bypass this check. No automatic rewrite,
credit use or provider change follows. Use the existing session-reconciliation
rules below; do not clear a dispatch fence to regenerate the chapter.

This is a narrow negative screen for a reproduced output defect, **not** proof
that other text has the right language, length, mechanics, canon or prose quality.
Those checks and the exact reader acceptance remain separate. Historical
delivered/accepted text is not rewritten or retroactively revoked by this screen.

## Delivery status and remaining work

This adds phase orchestration, **not a deployed queue service**. The companion
intake tick below adds bounded Hub selection and exact predecessor handoff. No
polling daemon or new spending policy is enabled by installing either module.
Profile authorization is a separate operator decision. Real-user execution
requires a profile approved for `consented_origin`, fresh Chummer consent to the
exact character facts, and a separate book-scoped execution admission. A profile
login or an app consent flag alone cannot enlarge the execution budget.

Focused tests exercise exact preparation handoffs, next-slot continuation,
one-write fencing, missing/changed Hub authority, acceptance boundaries, finite
observation, lock ownership and project discovery. Simulated-browser tests are
not a new live generation or Android UI proof. Existing signed-Hub chapter
reconciliation can be tested read-only with provider calls and POSTs forbidden.

On 24 September, the separate native linked-owner synthetic first-decision
smoke completed genuine provider generation, review, explicit adoption, HTML
export and cold reopen. Preview29 was separately observed on Play Internal.
Neither observation proves a complete multi-chapter real-user route, physical
Play installation, or a deployed tester-queue consumer. This source module
does not grant any publication authority.

## Book-scoped intake

`scripts/origin_chapter_intake.py` performs one tick for one trusted local
enrollment. Its owner-only JSON admission names schema
`firstbook.local-book-execution/v1`, `approved: true`, the exact `book_ref`,
`first_work_id`, `account_sha256`, `workspace_id`, `locale`, an exclusively owned
`browser_session`, future Unix `expires_at` (at most seven days),
`maximum_chapters` (1–100), and `maximum_book_credits: 1`. This is authorization
to consume one existing book credit, not to buy credits or assert a provider
balance. It must not be populated from client/provider-controlled fields.

```sh
python3 -m scripts.origin_chapter_intake \
  --admission-path /private/approved-book.json \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --output-root /private/provider-journals
```

The initial work ID is explicit. Later work comes from the private Hub's
book-filtered pending route and must link to the last completed execution using
the exact Hub edge. Multiple successors stop; no sorting heuristic chooses a
story. Fresh Hub acceptance and cumulative facts are checked before retaining
the next dispatch. New packet/source/admission identity is fsynced before any
provider action. A lost result resumes that exact work directly even when it no
longer appears in pending. Account and budget cannot silently change on restart.
A completed chapter does not imply reader acceptance and does not advance itself.

Private `intake-<bookRef>.json` joins the existing execution journals in recovery
custody. Missing custody for an already consumed Hub admission requires recovery,
not regeneration. Enrollment changes cannot expand the retained limit; a new owned
browser session/expiry can resume the same execution without replacing its identity.
Keep all journals for that book together; restore is not a new credit allowance.

The tick uses the existing cycle lock and never creates or logs into a browser.
The bounded runtime below supplies owned session startup/shutdown. Credential
and profile scope approval remain explicit; no service is enabled here. Tests include
the real phase cycle/writer/result adapter with a simulated browser, not a new
paid generation or a production-user rollout.

## Owned browser runtime

`scripts/origin_chapter_runtime.py` wraps intake for one chapter, holding the
existing cycle lease throughout bounded observation (1–120 ticks, 2–30 second
interval). The private configuration contains `profile_id`,
`profile_use_approved: true`, `source_scope` (`synthetic_only` or explicitly
authorized `consented_origin`), and the intake `admission` above **without**
`browser_session`. Do not derive that approval from the user's chapter text.
The controller must first verify that the chosen profile/account is authorized
for that data class. No new profile, cookie import, login or security change is
performed by the runtime.

```sh
python3 -m scripts.origin_chapter_runtime \
  --configuration-path /private/approved-book-runtime.json \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --output-root /private/provider-journals
```

It creates a unique window only when exact pending work reaches the provider
boundary, verifies the visible account hash, and reuses that owned window across
the framework/outline/chapter phases. Idle or already completed Hub work does
not open a browser. No app/provider-supplied session name can select an existing
window. A successful result closes only the window this invocation opened, with
an explicit close acknowledgement.

An in-flight generation, ambiguous result, expired admission during work, lost
open/close acknowledgement or failed phase retains its session record for
reconciliation. The runtime does **not** close an active frontend merely because
its observation budget ended. A subsequent invocation refuses to open a
replacement or claim ownership from the retained name. Inspect the actual live
session/process and original journals; never delete the record to authorize a
retry. `owned-session-<bookRef>.json` is private execution custody, not a Hub job
or provider-result authority. Backup it with the intake and provider journals.

This is a bounded local entry point, not an enabled polling daemon or a general
provider-account allocator. Verify the selected profile's current authorized
scope before each enrollment. A live read-only account/session check and idle
Hub intake do not prove paid generation, real-user rollout, Android UI behavior
or Play delivery.

The optional [enrolled-book watch](ORIGIN_CHAPTER_WATCH.md) waits for later exact
chapter requests within the original admission and a finite lifetime. It does
not enroll new books, activate a service or renew expired execution approval.
