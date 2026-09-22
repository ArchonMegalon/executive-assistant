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

Remaining integration: Hub-owned resumable generation/consent jobs, real paid
request reconciliation, Android status/review/adoption and accepted-book export.
This adapter supplies recovery of an already generated draft, not those claims.

Focused local verification:

```sh
python3 -m pytest -q tests/test_firstbook_chapter_capture.py tests/test_booka_book_worker.py tests/test_ui_service_worker_cleanup_contracts.py
```
