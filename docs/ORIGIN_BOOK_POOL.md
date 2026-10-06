# Cumulative Origin book budget and standing service

The historical user approval was up to **three new books total** on 24 September 2026, only
for explicitly consented Chummer facts, using existing FirstBook credits, no
purchases or publication. This does not renew daily, per account, or on restart.
The completed synthetic book grants remain historical and unchanged. Later
standing approval covers existing FirstBook credits, and on 4 October the user
explicitly requested switching to their next account when one is empty. Neither
decision resets an existing ledger or authorizes uncertain-job replay, purchases
or publication. The three-book example below documents the original grant.

`scripts.origin_book_pool` adds a narrow local controller over the existing
owned-browser runtime. It reserves each distinct Hub book before any provider or
Hub write (a v2 account balance probe is read-only). Each admitted book retains the existing one-credit cap. Later chapter
requests reuse that paid book and require the exact reader-accepted predecessor.
The controller never creates chapter requests, accepts prose, publishes a book,
transfers an existing book to another account or buys credits.

## Standing existing-credit service

`firstbook.local-book-service/v1` implements the later standing approval without
silently renewing the historical v1/v2 finite grants. It has the same fields as
the rotating v2 configuration, except `expires_at` must be `null` and **each**
account also has an integer `maximum_new_books` ceiling. Their sum must equal
the top-level ceiling (1–1,000 books). Before deployment, verify each account's
actual remaining credits. Set its ceiling to that observed balance **plus its
reservations already retained in this pool**. This is a recorded existing-credit
snapshot, not a permission to purchase credits or automatically add future
refills. Accounts with a zero ceiling remain scoped but are not probed for new
books. The private ledger is capped at 2 MB; ordinary chapter records retain
their existing 512 KB limit.

For example, one reserved book plus two currently available credits on account A,
and four currently available credits on B, means ceilings 3 and 4, total 7—not
seven additional credits. These numbers are illustrative, not provider evidence.
The unchanged private approval is checked on every execution tick. Revocation,
changed budgets/accounts, missing custody and uncertain jobs stop execution.
Each runtime invocation still receives a finite one-hour, one-credit child grant;
standalone runtime/intake admission does not accept a non-expiring grant.

New books rotate only on verified zero balance or when the recorded account
ceiling is reserved. Higher provider balances cannot enlarge that ceiling.
If all eligible accounts are observed empty, a durable latch stops new-book
discovery and balance probes, including after restart. **Already paid books
continue** when the reader requests an accepted successor. Exhaustion never
means accepting prose, generating the next chapter without the reader, or moving
an existing book to another account. `remaining_books` denotes unreserved
approved slots, not live provider credits.

For existing finite custody, stop and inspect the old executor first. Use a new
private approval ID and reviewed credit snapshot; retain the same accounts for
every reserved book, all historical exclusions and the chapter ceiling. Then:

```sh
python3 -m scripts.origin_book_pool \
  --configuration-path /private/old-approval.json \
  --approve-standing-service /private/standing-approval.json \
  --output-root /private/existing-pool \
  --expected-pool-sha256 <exact-inspected-ledger-sha256>
```

This explicit transition takes both execution leases, rejects uncertainty or
incomplete/missing book custody, retains the prior ledger in a private transition
record, and commits the new ledger last. It never opens a browser or writes Hub.
Every intake, provider and session journal remains byte-identical, including
account/workspace identity and completed chapter bindings. Existing reservations
count against the new ceilings. A partial transition cannot run using mismatched
configuration. Do not erase custody, import an old book into another fresh pool,
or clear a fence to activate this mode. This transition does not prove a live
executor is stopped: independently inspect the exact process/container first.

Point the existing local scoped Docker service at the new approval and **same**
custody, run account preflight, then use `--serve` without `--selected-book` to
allow new consented books. `restart: no`, exclusive profiles and existing
no-replay recovery remain. No new public listener, provider purchase, publication,
or automatic failover is added. Source support and simulated-provider tests do
not establish that a deployment is active or that a new real book was generated.

## Account rotation for finite new-book grants

The optional `firstbook.local-book-pool/v2` configuration replaces the three
top-level `profile_id`, `profile_use_approved` and `account_sha256` fields with
an ordered `accounts` array. Each entry contains those same three fields, with
a distinct verified account hash and a distinct explicitly approved browser
profile. All remaining approval, expiry and cumulative-budget fields are unchanged.

Before reserving a **new** book, the controller reads the current account's
visible `CREDIT BALANCE` under its verified identity. Only exactly zero advances
to the next configured account. Missing/ambiguous balance, authentication errors,
account mismatch and network failures stop selection; they are never exhaustion.
All accounts empty returns `accounts_exhausted` without reserving or starting a
book. Only configured existing profiles are used; the controller never logs out,
creates profiles, imports cookies or reads a credential inventory.

The chosen account/profile is persisted with the book before execution and reused
for all later chapters, even when its new-book balance reaches zero. The shared
in-flight fence still stops unknown paid work from being repeated on another
account. Read-only probes also retain a lifecycle fence if their browser open or
close is unconfirmed. Monthly allowance and refill dates are not remaining credits.

Existing v1 custody remains readable and unchanged; editing it to v2 is rejected.
Do not create a new ledger to retry an old admitted book. A deployment must first
reconcile existing work and explicitly enroll only genuinely new requests.
The default Compose file still mounts one profile. For v2, add only each exact
approved profile as a separate private bind mount in a local Compose override;
never mount the global profile root or unrelated accounts. The scoped registry
and mounted profiles must exactly match the admitted account set. Run the
read-only preflight for all profiles before enabling rotation.

The private owner-only configuration supplies:

```json
{
  "schema": "firstbook.local-book-pool/v1",
  "approval_id": "owner-three-new-books-20260924",
  "approved": true,
  "maximum_new_books": 3,
  "maximum_chapters_per_book": 100,
  "profile_id": "<existing-approved-profile>",
  "profile_use_approved": true,
  "source_scope": "consented_origin",
  "account_sha256": "<verified-account-hash>",
  "expires_at": 0,
  "excluded_book_refs": ["<historical-book-ref>"]
}
```

Replace the placeholders privately. Expiry must be future Unix seconds within
seven days. The chapter maximum is a safety ceiling, not authorization to invent
100 chapters; only separately consented Hub chapter requests are processed.
There is no provider-balance claim in the configuration. Existing activation
checks still require the one-credit provider control and exact account.

Initialize explicitly **once** into empty private custody:

```sh
python3 -m scripts.origin_book_pool --initialize \
  --configuration-path /private/three-books.json --output-root /private/pool
```

Run one bounded local watch against the existing private Hub listener:

```sh
python3 -m scripts.origin_book_pool \
  --configuration-path /private/three-books.json --output-root /private/pool \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --watch-seconds 3600 --poll-interval 30
```

An invocation without `--watch-seconds` performs one sweep. It admits at most
one new book per sweep and services already reserved books. No browser opens
for idle or already retained results. The fourth new book stays queued. A full
20-item Hub queue page or ambiguous first chapter stops; there is no guessed
pagination or arbitrary choice between conflicting chapters.

For a deliberate single-book run, add `--selected-book <exact-64-hex-book-ref>`
to either the pool CLI or the Docker entrypoint. This services only that book,
while retaining every previous reservation and the shared execution fence.
A missing, excluded, ambiguous or over-budget selection fails closed; it never
falls back to a different queued book. A selected existing book does not reserve
another credit. Selection does not recover or reopen historical sessions.
The three-book configuration above records the original approval, not a renewed
allowance. A later explicit owner grant needs a separately reviewed custody and
configuration amendment, preserving all reservations; `--selected-book` does
not enlarge it.

`book-pool.json` contains the immutable approval binding, cumulative reservations
and an in-flight marker. Keep it with all provider/intake/session journals in
private recovery custody. Missing custody fails closed; execution never
auto-initializes. Config edits cannot reset, enlarge or transfer a used budget.
Failures, lost acknowledgements and process death retain the reservation and
require reconciliation before further work. Never delete the marker, change the
root, or use an unconditional error-restart loop to get a new allowance.

Watch lifetime is finite (up to 24 hours), with unchanged approval rechecked
before every runtime tick. Renewal is not implicit. This source addition alone
does not install a Docker service or activate an unattended production worker.
Keep deployment local, provider profiles private, and no public worker listener.

Focused tests use a simulated provider with the actual intake/runtime. They
cover three-book admission, fourth-book denial, persistence, chapter reuse,
revocation, ambiguity, changed source, lost custody, errors and concurrent
controllers. They are not new paid generation or physical Play-install proof.

## Continue a completed one-book recovery

A deliberately one-chapter repair must not leave the user's later chapters
permanently limited to that diagnostic allowance. With explicit continuing
authority, `scripts.origin_completed_book_import` imports one **completed**
single-book pool into fresh private custody under the new approved pool config.
Stop the old executor first. Supply the exact inspected source-ledger SHA-256.
The destination must be empty; do not initialize it separately.

The operator import takes the pool/cycle and direct writer locks, requires closed browser custody,
validates every completed job and byte-identical provider receipt against Hub,
and requires an empty queue for this book. Account/profile, source scope,
provider project/slots and all retained job packets remain unchanged. Only the
future chapter ceiling/expiry is taken from the new approval. The imported book
counts as one already reserved book, not another available credit.

Original custody remains untouched. The import retains source-file hashes and
the original/continuation envelopes; provider receipt files are copied byte for
byte. The destination ledger is committed last. Partial imports cannot execute
or be automatically restarted. Unknown files, pending/uncertain jobs, edited
drafts and multiple-book source pools are deliberately unsupported. This is an
explicit completed-state handoff, never general paid-job recovery or replay.
Reader acceptance is still checked normally before any successor dispatch.
Retain the old custody but do not run both pools for the same book/profile.

## Scoped local Docker execution

`docker-compose.origin-book.yml` runs only this worker, not the general EA
stack. Build locally using two **software-only** named contexts: the installed
BrowserAct 1.1.0 Python environment and the existing Chrome program directory.
Neither context may contain browser profiles, credentials or runtime state.

```sh
docker build -f docker/origin-book/Dockerfile \
  --build-context browseract=/path/to/browser-act-cli-environment \
  --build-context chrome=/path/to/google/chrome-program-directory \
  --tag chummer-origin-book:local .
```

Use the inspected image ID as `ORIGIN_BOOK_IMAGE`, not a mutable remote tag.
The build checks that BrowserAct discovers normal Chrome and that it executes.
A downloaded BrowserAct kernel is not a substitute for the local Chrome driver.
The container supplies a private Xvfb display; it never mounts the host display.
Chrome uses `--no-sandbox`, as does the existing local operator installation:
the required non-root, read-only, capability-free container is the isolation
boundary, not Chrome's renderer sandbox. Do not use host networking: unrelated
Docker interface churn can interrupt Chromium with `ERR_NETWORK_CHANGED`.
The worker joins the exact running Hub container's network namespace. Supply
its inspected full 64-character ID in `ORIGIN_BOOK_HUB_CONTAINER_ID`, and the
existing private **container-internal** listener port in `ORIGIN_BOOK_HUB_PORT`
(currently 5089, not the host-published 15099). Confirm the target is the intended
running local Hub before launch. Names, shortened IDs and an ambient host-mode
fallback are not accepted. A recreated Hub needs an explicit repin; do not
automatically follow a mutable service name or resume a retained paid job.

`LocalHub` still connects only to literal loopback with proxies and redirects
disabled. No Hub listener is changed or newly published. Verify the private
worker route rejects unauthenticated requests and browser/control listeners
bind only to loopback **inside the shared namespace**. The Hub container is
therefore part of the local browser-control trust boundary. Its existing public
ingress must never proxy those random control ports. No Docker socket is mounted.
Host UTS supplies the existing profile's stable hostname only; networking,
PID/IPC and display remain isolated, all capabilities are dropped, and the
non-root worker cannot change that hostname. On host replacement, preserve the
profile's hostname or reconcile it explicitly; never delete locks to force entry.

For the default single-account deployment, provide five exact private bind mounts through the Compose variables:
approval, worker token, existing cumulative custody, separate BrowserAct state,
and **only** the approved existing local profile. No global BrowserAct registry,
API key, host home, Docker socket, imported profiles or unapproved accounts.
The scoped registry records that same existing profile, not a newly created or
imported browser. State/profile ownership must match the non-root runtime UID;
directories are 0700 and secret files 0600. Profile access must be exclusive:
do not operate it concurrently from the host. Never remove Chrome lock files
to force startup. Keep the deployment hostname stable between invocations.

Load the CLI's current core skill in this isolated state before first use, then
run `docker compose -f docker-compose.origin-book.yml run --rm origin-book
--preflight`. It opens its own fresh window, verifies the approved account,
and closes it, without reading/mutating the Hub queue or starting generation.
Do not activate the watch unless that preflight succeeds. A challenge or account
mismatch needs operator reconciliation, not automatic login/profile changes.

The default watch lasts one hour and has `restart: no`. Explicitly start another
bounded invocation only after the previous result and custody are reconciled;
this never renews the total allowance. On uncertainty the controller stops
without retry and keeps its container/browser alive for reconciliation. A
running container in that state is **not** a healthy working controller.

For normal local hosting, opt into `docker-compose.origin-book-service.yml`
on top of the existing Compose file, or pass `--serve` to the scoped container.
This observes later user-requested chapters without the one-hour invocation
cutoff. It uses the **same** cumulative custody and exact approval. It stops on
finite approval expiry, changed/revoked authority, exhausted finite accounts or reconciliation;
it never renews a grant, refills reservations or replays uncertain jobs.
SIGTERM/SIGINT stop an idle service promptly and drain an active bounded chapter
before shutdown; the overlay allows six minutes. A forced kill leaves the
existing in-flight fence intact. `restart: no` remains intentional: inspect
terminal state and custody before starting again. This is continuous processing
within the exact approval, not automatic failover or an unlimited credit grant.
`--serve`, `--preflight` and `--watch-seconds` are mutually exclusive. Optional
`--selected-book` retains its exact-book restriction in service mode too.

Retain the approval, cumulative ledger, worker token and subsequent execution
journals in private recovery custody together. A pre-activation empty snapshot
is not a safe restore point after any execution. Automatic restore/resume is
not authorized: reconcile current Hub/provider state and all reservations before
running on a replacement host. Do not claim zero data loss or automatic failover.

Local verification on 24 September 2026: scoped image built; actual Chrome
151.0.7922.71 opened FirstBook, the approved account matched, and the owned
window closed. Observed control listeners were loopback-only. No book or credit
was consumed. This proves account preflight, not unattended generation or full
host recovery. Earlier image attempts failed before this correction; they are
not successful provider evidence.
