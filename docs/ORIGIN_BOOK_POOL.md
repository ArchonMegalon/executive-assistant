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
