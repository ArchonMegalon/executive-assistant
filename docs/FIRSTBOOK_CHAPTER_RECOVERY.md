# Private First Book chapter recovery

The dated observations below preserve the 22–23 September development history,
including failures and limitations of those inputs. On 24 September, the
separate native linked-owner synthetic first-decision route completed provider
generation, review/adoption, HTML export and cold reopen. That does not qualify
the entire multi-chapter route or physical Play installation. Current execution
entry points are documented in [ORIGIN_CHAPTER_LOCAL_CYCLE.md](ORIGIN_CHAPTER_LOCAL_CYCLE.md)
and [ORIGIN_CHAPTER_WATCH.md](ORIGIN_CHAPTER_WATCH.md); source availability alone
does not enable a service or expand provider-spending permission.

`scripts/booka_book_worker.py` supports `mode: capture_existing_chapter` for a
trusted local caller holding its own authenticated BrowserAct session. This is
a read-only provider adapter, **not** a deployed Android generation service.
It does not create books, buy credits, rewrite, approve, publish or claim canon.
The existing framework-generation mode is unchanged and is not retry-safe.

The caller must first use the BrowserAct/EA browser skill, select the approved
First Book profile and open its own session. Do not adopt another worker's
session. The capture does not log in or close the caller's session.

Pass a JSON packet through stdin or `--packet-path`:

```json
{
  "mode": "capture_existing_chapter",
  "browser_session": "owned-session-name",
  "request_id": "opaque-approved-job-capture-id",
  "account_sha256": "SHA256 of the case-folded exact expected account email",
  "provider_book_id": "exact-id-from-book-overview",
  "book_title": "Exact visible title",
  "chapter_title": "Exact current draft chapter title",
  "chapter_number": 1,
  "source_packet_sha256": "SHA256 of the caller-approved narrative source packet",
  "narrative_locale": "de-DE"
}
```

Hashes must be 64 lowercase hex characters. No passwords, cookies, runner files,
rules text or GM secrets belong in this packet. `source_packet_sha256` and locale
are caller bindings, not a claim that provider prose semantically matches them.

The adapter visits only the First Book origin, checks the visible account hash,
selects one exact-title book, verifies its exact project ID and resumes the
current writing page. It accepts exactly one read-only draft surface, exact
chapter title/number, bounded text and the visible approval-required state.
It waits for those concrete controls rather than global network-idle state.
Changed layouts, login challenges and ambiguous controls stop without generation.

The complete observation is atomically retained under
`EA_UI_SERVICE_WORKER_OUTPUT_ROOT/firstbook-private-captures/` in a 0700 directory
and a 0600 file. Reusing the same request returns those exact bytes without
browser actions, even after process restart. A changed owner, source, book,
chapter or locale on the same request is rejected. Use a newly admitted request
for a deliberate later rewrite capture; never silently replace an earlier draft.
These private captures must not be served by a static web server.

The generic UI-service adapter forbids public proxy publication for this mode,
does not resolve/pass login credentials and does not infer download URLs from
the story or provider origin. It refuses remote-workflow fallthrough.

`chapter_review_required` is not a full manuscript or player-approved canon.
The result always keeps `canon_approved`, `language_verified`,
`full_manuscript_ready`, `provider_generation_attempted` and
`publication_authorized` false. Review length, language, facts and the stopping
decision against the exact approved source before any downstream acceptance.

Remaining integration: deployed Hub-owned generation/consent jobs, admitted
worker dispatch and Android status/review/adoption using the real provider
result. This read adapter supplies recovery, not those end-to-end claims.

## Write one prepared chapter without replay

`python3 -m scripts.firstbook_chapter_write --packet-path PRIVATE_PACKET
--output-root PRIVATE_DIRECTORY` is a **trusted local caller** helper. It is
deliberately not registered as a public API or an ordinary EA tool. A caller's
`generation_approved: true` asserts prior execution admission; it does not grant
user consent, reserve credits, or replace Hub/quota authority.

The packet uses the same exact account/book/chapter/source binding as the read
adapter, plus `generation_approved: true` and an `expected_outline` list of three
`{ "title": "...", "description": "..." }` sections. These are the approved
prepared outline, not arbitrary model output to be trusted automatically.

The existing project must already be paid, prepared and on the requested
unwritten chapter. The helper verifies the account, exact provider project ID,
chapter identity, full outline, and the visible included-in-plan writing action;
selects Brief depth and verifies it again. Only then does it fsync a private
dispatch record **before** clicking Write Chapter once. Different request IDs
cannot silently generate the same provider chapter twice. No new-book creation,
outline locking, payment, rewrite, chapter approval, export or publication is
performed by this helper.

Subsequent calls observe/reconcile only. An active generation is checked without
navigating away, since First Book performs work through its live browser page.
Keep the owned session alive until generation completes. An ambiguous response
leaves the fence in place, including after process restart. It never becomes an
entitlement to click Write again. A completed unapproved draft is retained with
its exact text hash; cold retries then return it without browser actions.

The record is scoped to provider account/project/chapter in
`firstbook-private-writes/` (0700, files 0600). It is a private execution journal,
not canonical Hub job storage. A recovered draft remains review-required;
`generation_causally_attested`, canon and publication claims remain false. A
caller-supplied source hash alone cannot prove semantic consistency or that an
external actor did not change the provider project.

Real-browser correction: selecting a new paid book from the dashboard can open
its outline rather than its overview. The common read-only navigation now uses
Book Overview when present before checking the exact project ID and Resume
Writing; it never uses Lock/Start to recover navigation.

Book setup is still a separate admitted operation. The provider can change the
requested title during framework creation. Its two-step form can also submit
from Next when step two has already been filled. Do not automate creation with
the historical single-form framework worker or retry setup after a lost response.

## Hub job connector

`python3 -m scripts.origin_chapter_worker --packet-path PRIVATE_PACKET
--hub-origin http://127.0.0.1:5089 --token-file PRIVATE_TOKEN_FILE
--output-root PRIVATE_DIRECTORY` connects a single admitted Hub request to the
prepared-chapter helper. The listener must be deployed separately from Hub's
public/tunnel listener. No production token is created or looked up by this CLI.

The private packet contains `work_id`, `execution_admission`, `approved_source`
(the exact complete Hub source projection), and `prepared` (the chapter helper's
packet). `prepared.source_packet_sha256` is the exact Hub `sourceDigest`, and its
locale must match the approved source. The connector sets the helper's request
identity to the opaque owner-scoped work ID. It will not relabel a previous
canary capture or a chapter bound to another request/source.

The connector GETs the job, validates its source and safety fields, then asks Hub
for its one-shot admission transition. Missing/lost admission responses cannot
start provider work. When Hub returns `mayStartGeneration: false`, only an
existing local dispatch/result may be reconciled; a missing local fence remains
unresolved. On completion the private result file is revalidated and hashed,
then returned through Hub's exact admission-bound completion route. A lost
completion response is resolved by reading the same job on the next invocation.

Local HTTP ignores ambient proxies, rejects redirects, uses bounded streaming
before JSON materialization and rejects duplicate JSON keys. The service token
is read only from a same-user private regular file and sent in Authorization,
never inside the provider packet, logs or a command-line token argument.

If the local production Hub restricts `AllowedHosts`, supply `--hub-host
chummer.run` (or that deployment's exact allowed hostname). This changes only
the HTTP Host header, not the literal loopback connection or worker listener.
It does not open public worker access or disable host filtering. URLs, ports,
header injection and malformed hostnames are rejected before loading the token.
Without the option, the normal loopback Host header remains unchanged.

Before admission, the connector binds Hub's opaque `bookRef` to the exact
provider account/project/title/locale under `firstbook-private-writes/books/`.
That private mapping is append-only: later chapters reuse the same project;
another runner cannot claim it, a chapter slot cannot be reused, and a changed
source cannot silently rewrite it. Mapping writes are private and atomic, with
one local lock covering both runner lookup and provider-project ownership. They
do not create or pay for a book, infer chapter order, or grant reader approval.
Use one durable private output root for all jobs of this local worker lane.

Read-only provider inspection on 2026-09-22 showed that an unapproved chapter
keeps Resume Writing on that chapter; grey later chapters cannot be entered
through the inspected table of contents. Do not automate `Approve & Next` from
generation completion. Hub now carries an optional `readerAcceptedTextDigest`
after the signed app acknowledges its explicitly selected, durable reading
edition. The connector validates this against the exact draft bytes; it cannot
set acceptance or infer it from a completed generation. The effect/cost of
changing an already-started outline is not yet proven.

The connector's explicit `--advance-accepted` mode performs no generation. It
reads Hub's exact acceptance and delegates to `firstbook_chapter_advance.py`.
That helper requires the existing private chapter journal to match both the
accepted text hash and Hub's receipt-file hash. It then rechecks the live
account/project/draft and fsyncs an approval fence before clicking
`Approve & Next` once. Retried calls observe only; a still-visible old draft is
unresolved, never permission to click again. Observing the next unwritten
chapter closes this local step without writing it. An unverified final-book
finish/export flow is not entered. Keep one private output root across calls.

On 2026-09-23 the retained fictional Mira chapter advanced once using its exact
Hub-recorded synthetic acceptance. A subsequent read observed chapter 2 of 8,
an empty draft and the existing unapproved placeholder. This is real provider
navigation, not a real player's approval or a completed Android continuation.

`--prepare-next-chapter` takes a new `setup` packet with
`outline_update_approved: true` and the previous worker's exact `work_id`,
`execution_admission`, `approved_source` and `prepared` under `previous` (do not
recursively embed earlier packets). It reads both Hub jobs and requires the same book/workspace/locale,
a distinct chapter/decision and exact predecessor reader acceptance. It derives
only the next numbered slot's outline from the new confirmed source. Existing
book identity, paid setup and earlier prose are not replaced.

Preparation accepts only the existing paid-book `Lock & Start Writing` control,
not its one-credit variant. It inventories all eight fields of every chapter,
reopens the target accordion card, changes only that card, and verifies every
other field unchanged before saving. A durable fence precedes the save. A lost
save acknowledgement permits readback only; an input failure can resume only
after reopening the provider and matching the exact original persisted outline.
No new chapter text is generated by preparation.

Live synthetic follow-up on 2026-09-23: chapter 2 was updated from a new Hub
source after the fictional school choice, then reopened and matched exactly.
The first input attempt exposed an accordion-target bug; no save was dispatched.
The fix reopens the exact target after inventory. Recovery first reopened the
unchanged server outline, then saved once without a new book credit. The separate
writer subsequently dispatched chapter 2 once. The actual unedited provider
draft (8,396 characters / 1,213 whitespace-delimited words) was retained and
returned to Hub as review-required, with no reader acceptance or mechanics
permission. Signed reads returned the new prose and verified the original
chapter unchanged. The 450–650-word prompt was not obeyed; no automatic prose
quality/canon approval is claimed. This is not Android UI delivery.

Ten selected execution/input files, including the new approval, preparation and
write fences, were backed up as actual bytes to private Teable custody and
restored exactly into a new directory. This is a fresh bounded manual snapshot,
not automatic replication. Reader requests still took 21.91s / 20.12s in this
follow-up, beyond the shipping client's 20-second deadline; responsiveness
remains a release-blocking integration issue.

The completed private next-outline record supplies the exact `prepared` packet
for a separate normal worker invocation, retaining `previous`. That handoff can
use the already-admitted Hub job, but the existing per-slot writer fence still
prevents another generation after an uncertain outcome. The new chapter remains
review-required until the reader explicitly adopts its exact text.

This connector is not a daemon, a quota authority or public EA tool. Book setup,
automatic job orchestration, deployment and the actual Android-to-provider smoke remain
separate work; private-journal/provider deletion also remains an execution
obligation when an owning Hub job is erased. No publication authority is granted.

Focused local verification:

```sh
python3 -m pytest -q tests/test_firstbook_chapter_advance.py tests/test_firstbook_book_binding.py tests/test_origin_chapter_worker.py tests/test_firstbook_chapter_write.py tests/test_firstbook_chapter_capture.py tests/test_booka_book_worker.py
```

## Short scene quality and live rewrite observation

New `firstbook_outline_prepare.py` plans request one 450–650-word scene across
three sections (150–210 words per section), with no repeated opening and no
special physiology, enhanced senses or abilities inferred from metatype. Exact
older retained plans remain recoverable; this prompt change does not rewrite
their provider outline, invalidate a paid activation, truncate facts or authorize
another payment. Prompt instructions are not proof of narrative compliance.

The real First Book Rewrite dialog accepts feedback up to 800 characters and a
separate Brief selection. The provider keeps the previous draft on screen while
displaying `Writing Subchapter N of M`. The writer now treats those progress
labels outside the manuscript as active generation and will not navigate away.
Do not close the owned session or capture the visible old draft as the new result.

A private synthetic Ivo correction test on 2026-09-22 demonstrated the limit of
prompt-only correction: one rewrite removed the conspicuous invented special
perception but still produced 2,102 words despite explicit 450–650-word feedback.
The test used an already-started book and its older outline; it does **not**
qualify the new bounded outline end to end. Balance remained 22. No chapter was
approved, advanced or published. The original and rewritten drafts were retained
separately rather than replacing the immutable generation journal.

The same provider also exposes a Markdown Edit/Save Changes route. A deliberate
operator-edited, shortened derivative is editorial work, **not** evidence that
First Book followed the length instruction. Such an edit must retain the old
draft, remain review-required and receive a fresh exact-text reader acceptance
before continuation. Never rebind an earlier accepted digest to the changed text.
This manual editorial path is not an automatic worker rewrite/retry feature.

## First chapter after framework setup

Framework setup and its first chapter use the same Hub admission. Once setup
has durably reached `first_chapter_prepared`, the worker validates both retained
setup/outline records against the Hub work, book, source and exact prepared
provider chapter before reserving the mapping or invoking the writer. This
allows the separately fenced first Write even though `/admit` now returns
`mayStartGeneration: false`. The writer still checks the live exact outline and
fsyncs its own fence before Write. Missing, partial or uncertain activation
does not qualify; an existing write fence never permits a second click.

This is not permission for a second credit, future chapter, reader approval,
or automatic retry of an uncertain request. It does not make the app/provider
integration complete.

## Deliver a separately captured edited draft

Before the **first** Hub completion, the trusted local connector can use
`--capture-reviewed-draft TEXT_SHA256`. Supply the SHA-256 of the exact reviewed
UTF-8 rendered draft, not its Markdown source. Keep the same packet, book/source
binding, output root, admission and digest on recovery. This mode only reads the
existing provider draft; it cannot run a writer, rewrite, save or payment action.

The original completed writer journal must already exist for that exact job and
chapter. The Hub job must already have its original execution admission and must
still be pending reconciliation. A missing original, new admission, active
generation, started chapter advancement or a mismatched current text stops the
operation. The capture is a separate immutable private file; neither the old
writer journal nor earlier observations are overwritten. A wrong observed text
is retained but cannot be delivered under the requested digest, and a retry does
not silently recapture or regenerate it.

The existing Hub completion receives the selected text and that capture file's
digest. No public contract or Hub storage policy changes: an already delivered
job still rejects replacement text. A lost completion response is resolved by
reading that same job. Completed-job revision UX remains separate work, not a
capability claimed by this pre-delivery mode.

Android's later exact reader acceptance can refer to this selected capture.
`--advance-accepted` validates either the original journal or the selected
capture against the Hub text/receipt hashes, then checks the live provider draft
before its existing one-shot approval. Choosing an edited draft does not itself
acknowledge reader acceptance, change character facts or authorize the next
generation. Provider names identify the observed host, not a claim that the
provider alone wrote an operator-edited passage.

Focused coverage: `tests/test_firstbook_chapter_review.py` alongside the capture,
writer, advancement and worker suites. Real-provider capture is read-only;
reader-approved continuation still needs the actual app/Hub route.

## Revise an unaccepted delivered draft

The separate operator-only `--revise-unaccepted-draft TEXT_SHA256` mode also
requires `--expected-receipt-digest` and `--expected-text-digest` identifying the
exact previous Hub draft. Both the original writer journal and the selected
edited capture remain immutable in private custody. The operator edits the
existing provider page first; this command only captures it and calls the
private Hub `revise-unaccepted` endpoint. It does not click Edit, Rewrite, Write,
Save or Approve, spend credits, reset dispatch or acknowledge a reading.

Hub atomically checks the exact source, admission and previous result. A reader
acceptance, newer revision, changed source, wrong owner or replay prevents the
replacement. A lost reply can read back the identical committed revision.
Up to three superseded drafts are retained with the job; ordinary completion
still cannot replace a delivered result. Android must read and explicitly accept
the new proposal before continuation. This is an operator recovery seam, not an
automatic rewrite or a user-facing revision request control.
