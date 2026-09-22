# Private First Book chapter recovery

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

Focused local verification:

```sh
python3 -m pytest -q tests/test_firstbook_chapter_write.py tests/test_firstbook_chapter_capture.py tests/test_booka_book_worker.py
```
