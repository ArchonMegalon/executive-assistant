# Finite cumulative Origin book budget

The user approved up to **three new books total** on 24 September 2026, only
for explicitly consented Chummer facts, using existing FirstBook credits, no
purchases or publication. This does not renew daily, per account, or on restart.
The completed synthetic book grants remain historical and unchanged.

`scripts.origin_book_pool` adds a narrow local controller over the existing
owned-browser runtime. It reserves each distinct Hub book before any browser or
Hub write. Each admitted book retains the existing one-credit cap. Later chapter
requests reuse that paid book and require the exact reader-accepted predecessor.
The controller never creates chapter requests, accepts prose, publishes a book,
selects a different provider account or buys credits.

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
boundary, not Chrome's renderer sandbox. Host networking reaches the existing
loopback Hub; verify all browser/control listeners bind only to loopback.

Provide five exact private bind mounts through the Compose variables:
approval, worker token, existing cumulative custody, separate BrowserAct state,
and **only** the approved existing local profile. No global BrowserAct registry,
API key, host home, Docker socket, imported profiles or additional accounts.
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
