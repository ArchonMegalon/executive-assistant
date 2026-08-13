# Next Session Handoff

## Priority override: Memorial release and governed EA integration

Date: 2026-08-13
EA repo: `/docker/EA`
Memorial repo: `/docker/Memorial`
Memorial exact source: `661eb568834f9657ee25f288379ad059ca13c042`
Goal status: active; Memorial is deployed and Alpha Build 39 is in Google review, but the
cross-repo/operator promotion gate remains deliberately open.

This section is current and overrides older Memorial claims below. Keep the later audiobook and
OODA sections as history.

### Completed release state

- `/docker/Memorial` is clean, pushed to `origin/main`, and deployed at exact revision
  `661eb568834f9657ee25f288379ad059ca13c042`.
- `https://memorial.myexternalbrain.com` is publicly healthy and ready. PostgreSQL, worker,
  scheduler, studio, mail import, Android download, generation, quality audit, VocalLab voice,
  and the Manfred demo all report `ready`. `https://myexternalbrain.com` remains the separate EA
  origin.
- The UI is minimal, locale-aware, and status-first. Dictation keeps its compact microphone
  control instead of replacing it with visible label text. Browser/native back gestures,
  packages, login return, microphone permissions, talk-mode notifications, source-grounded
  answers, and free conversation passed Android 15 E2E.
- The browser now derives the user's preferred locale; Manfred and status copy follow the
  supported local language. Speech state distinguishes listening, Manfred speaking, and
  thinking/failure states.
- VocalLab is the production voice provider. The authorized German Manfred clone exists under
  `the.girscheles`, a real synthesis passed, the provider lifecycle canary passed, and the
  production demo is pinned through the protected
  `runtime/secrets/personal-manfred-demo-voice-ref` file. The retired Unmixr demo reference is
  removed from host state and is actively deleted from older runtime secret volumes.
- The temporary Unmixr Pro API key was revoked after its quota proved unsuitable. The temporary
  VocalLab browser token was invalidated by signing out. Never treat the remaining seven Unmixr
  clone credits as a dependable production lane.
- Exact verification: 488 tests, 19 documentation gates, 416 mobile checks, zero npm audit
  findings, supply-chain pass, browser E2E pass, Android 15 emulator E2E pass, isolated product
  persistence pass, 250-request load smoke with zero failures, 56-table encrypted
  backup/restore pass, nine route/privacy checks, and 12/12 healthy alert rules.
- Read-only Cloudflare evidence proves exactly one Memorial hostname binding, the expected
  internal service, and separation from the EA root.
- Android version 39 / 2.3.23 was built with unit tests, lint, shrinking, and R8. The signed
  direct APK SHA-256 is `27ae203de2bf439b7847a792bef0c56fb712565db508c3d1b7cd6f778da6d64c`.
  The signed upload AAB SHA-256 is
  `bf856f076701ede29720a42fa85cc0141daea445929d92a8927e1baa6fbef727`.
- Google Play accepted Build 39 into Closed Alpha for 177/177 regions. It is in review for full
  Alpha rollout. The Play-generated universal APK SHA-256 is
  `f1206dd99cc8cbef22bc157722de795b1c56a557d1bed12ae703d2b1ac2c3ea7`; both the Play app-signing
  and upload certificates passed the exact release receipt.
- The exact promotion receipt now passes 14 of 16 gates. Android handoff/signing, direct APK,
  browser E2E, Android E2E, product integration, load, backup, privacy, observability, public
  ingress, VocalLab, Cloudflare binding, and supply chain are green.

### Current evidence

- Promotion: `/docker/Memorial/dist/cutover/release-promotion.json`
- Public ingress and Cloudflare binding: `/docker/Memorial/dist/cutover/public-ingress.json` and
  `/docker/Memorial/dist/cutover/ingress-binding.json`
- EA boundary: `/docker/Memorial/dist/cutover/ea-core-closeout.json`
- VocalLab and Android signing: `/docker/Memorial/dist/cutover/vocallab-contract.json`,
  `android-signing.json`, and `android-direct-signing.json`
- Browser/native E2E: `/docker/Memorial/dist/e2e/`
- Signed Android artifacts and rollback archives:
  `/docker/Memorial/runtime/mobile-signing/android/`
- Direct install handoff: `/docker/Memorial/runtime/release-downloads/`

### Remaining real blockers

Only two of 16 formal gates remain red:

1. `ea_core_closeout`: the standalone repository boundary passes, but `/docker/EA` has preserved
   unrelated worktree changes, `origin/main` is not exact HEAD, and the configured loopback EA
   runtime was unavailable/mismatched during the exact audit. Do not reset or commit the broad
   dirty worktree to make this receipt green. Align a reviewed clean EA main/runtime first, then
   regenerate `ea-core-closeout.json` for Memorial revision `661eb568...`.
2. `operator_release_dossier`: no human-reviewed canonical dossier and Ed25519 signature exists.
   Do not manufacture legal, accessibility, monitored-support, owner-authority, store, Gmail/IMAP,
   alert-drill, or EA acceptance. A real operator must review the actual evidence and sign it.

Google production is separately time-gated: Closed Alpha still reports one of twelve required
opted-in testers. `susanna.hoza@gmail.com` is listed but must opt in herself. Production requires
at least twelve real testers continuously for fourteen days. Build 39 review can complete without
pretending that production eligibility exists.

Security follow-up: a Pano2VR license key was exposed in local terminal output when the EA `.env`
was accidentally sourced. Rotate that vendor credential. Do not source `/docker/EA/.env`; parse
only required keys without echoing values. The VocalLab short-lived browser token and temporary
Unmixr key were already invalidated.

### Opportunities and LTD posture

- The consent-first email profile/import app is ingest-ready. Use the existing product-owned
  Gmail/IMAP selection, review, deletion, and entitlement lane before buying another profile app.
  Emailit remains transactional delivery only.
- AiWriteBook Tier 4 remains a bounded human-operated export opportunity, not a Memorial runtime
  dependency or publication authority.
- VocalLab is now the verified Manfred lane. Unmixr remains synthesis-only fallback capacity and
  must not replace VocalLab or hide quota/deletion limitations.
- Keep provider credits, identities, deletion receipts, and user consent fail-closed. A green LTD
  inventory means verified-or-blocked governance, not that every paid tool is a live dependency.

### Working-tree rule

The EA worktree contains unrelated concurrent generated and audiobook work. Preserve it. Do not
reset, clean, or fold unrelated files into the Memorial release slice.

## Priority override: flagship audiobook narration lane

Date: 2026-07-11
Owner repo: `/docker/EA`
Implementation root: `/docker/EA/ea`
Primary module: `ea/app/services/audiobook_epub_pipeline.py`

This section overrides the older active objective below for the Codex session that
owns EA audiobook work. Preserve the older handoff history; it remains relevant to
the rest of EA operations. Do not mark the broader Chummer flagship goal complete.

### User outcome

Implement this lane, not only a design note.

An uploaded EPUB or supported source document must produce an audiobook that feels
like one continuous performance instead of a sequence of clipped sentences. When
the source contains dialogue, listeners must actually hear a stable voice distinct
from the narrator without requiring an operator to configure a hidden environment
variable. Common fiction with multiple attributable speakers should retain stable
speaker-to-voice assignments across chapters.

The experience must remain minimal and automatic: source in, optional voice preview,
finished playable audiobook out. Internal provider, segmentation, retry, and repair
details belong in receipts/operator surfaces, not in the normal user journey.

### What the current code really does

The current contracts make the feature look more complete than the rendered result:

- `NARRATION_PLAN_CONTRACT_NAME` is still `ea.audiobook_narration_plan.v1`.
- `_audiobook_cinematic_narration()` defaults on, but the active Unmixr adapter is
  short TTS and `_audiobook_cinematic_single_pass()` defaults off. Normal output is
  therefore still a set of independent requests joined afterward.
- `_explicit_dialogue_paragraph()` recognizes only a whole paragraph that starts
  with a balanced quote or dialogue dash. Inline speech, several turns in one
  paragraph, and narration around a quote are assigned incorrectly.
- `_scene_performance_rows()` gives every detected spoken paragraph the generic
  role `dialogue`; `_write_private_narration_plan()` exposes only the synthetic
  `dialogue_partner` speaker id. There is no real character attribution.
- `_configured_dialogue_voice_selection()` returns a second voice only from
  `EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID` or a private, explicitly approved token.
  No normal audiobook flow currently creates that approved dialogue selection, so
  production commonly falls back to the narrator despite the dialogue contract.
- `_write_provider_audio_file()` normalizes every generated segment independently
  with `dynaudnorm` plus `loudnorm`, then `_merge_audio_segments_to_wav()` performs a
  hard concat. Provider edge silence, independent loudness decisions, and missing
  same-speaker continuation timing can make sentences sound clipped or reset.
- Existing strengths must be retained: exact source hashes, private narration plans,
  raw voice-id redaction, render locking, resumable segment fingerprints, throttling,
  M4B assembly, publication STT, playback acceptance, and Telegram/WhatsApp delivery.

### Required architecture

#### 1. Versioned source-to-performance planning

Create a versioned preprocessing contract before synthesis. A planner may live in a
focused module if that keeps the 12k-line pipeline maintainable, but integration and
public/private projections remain owned by `audiobook_epub_pipeline.py`.

The planner must:

- preserve the source verbatim; never paraphrase or silently rewrite book text
- emit exact source spans with chapter, scene, paragraph, and character offsets
- split narration from quoted speech inside a paragraph instead of assigning the
  whole paragraph to one voice
- support straight/curly German and English quotes, guillemets, and dialogue dashes
- retain dialogue tags such as `she said`, `Anna fragte`, or `antwortete Ben` as
  narrator text while assigning only the spoken span to the character
- derive stable speaker ids from explicit names and conservative pronoun/context
  evidence; uncertain attribution must be represented as uncertain, not invented
- use a deterministic fallback for alternating unattributed turns within a scene
- reconstruct canonical source text exactly and fail closed before synthesis on any
  coverage, order, overlap, offset, or hash mismatch
- cache the private plan by source hash and planner contract version

An optional governed LLM enrichment pass is acceptable only for speaker labels and
span offsets. It must return structured data, reconstruct against the immutable
source, expose confidence/provenance, and fall back to the deterministic planner on
timeout or invalid output. It must never return replacement prose as render input.

#### 2. Automatic stable voice casting

Replace the hidden-operator-only second voice with an automatic cast resolver:

- explicit user-approved or operator-provided choices still win
- otherwise select language-compatible voices from the existing ranked Unmixr
  catalog and exclude the narrator voice
- activate a distinct dialogue voice automatically whenever confirmed dialogue is
  present and at least two eligible voices exist
- for attributable recurring speakers, keep a deterministic per-book cast map and
  reuse it across chapters and resumptions
- use available gender/age/style tags only as ranking hints; do not claim inferred
  identity as fact
- cap the automatic cast to a small configurable number and use a documented stable
  fallback for low-confidence/minor speakers
- if a quality policy requires distinct dialogue and no second eligible voice is
  available, report a clear actionable block instead of claiming multi-speaker audio
- keep raw provider voice ids only in mode-0600 private state; public job data,
  receipts, errors, callbacks, and logs may contain hashes/labels/status only

The normal user must not need to know that `EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID`
exists. Voice audition should preview narrator and cast when useful, but a skipped
preview must still produce a sensible automatic cast.

#### 3. Continuity-aware synthesis units

Build performance passages, not sentence-sized requests:

- group adjacent spans for the same speaker up to the provider-safe character cap
- split only at sentence/clause boundaries; never split a word or quote pair
- keep chapter and real scene boundaries, but do not turn every EPUB block boundary
  into a dramatic pause
- record boundary intent (`continuation`, `sentence`, `paragraph`, `speaker`,
  `scene`, `chapter`) and punctuation-aware target timing in the private plan
- add a short controlled continuation gap when a same-speaker request must split at
  the provider limit; do not hard-concatenate two independently generated endings
- include planner version, cast hashes, prosody settings, and boundary policy in
  render fingerprints so legacy cached masters cannot masquerade as improved output

Do not enable whole-book short-TTS requests as the default workaround. A genuine
provider long-form API can be added as a separate capability with its own limits and
receipts; the short-TTS path must remain bounded and resumable.

#### 4. Post-processing and mastering

Move quality decisions to the assembled performance:

- convert provider output to one PCM format without independently mastering every
  segment
- conservatively trim excess provider head/tail silence while preserving breaths and
  consonants, then add the planner's controlled boundary timing
- normalize loudness and true peak once on the merged chapter/master track (or use a
  measured two-pass strategy with one shared target), not a fresh dynamic-normalizer
  decision per sentence
- only use crossfades where listening tests prove they do not swallow phonemes;
  controlled silence is the safe default at speaker boundaries
- retain chapter metadata and M4B chapter marks even when a continuous master is used
- make every post-process step resumable and signature-bound

#### 5. QA, repair, and honest receipts

Extend the private plan and safe receipt projection with evidence for:

- exact source coverage and source-integrity status
- dialogue span count, attributed/uncertain counts, and speaker count
- cast completeness and `distinct_from_narrator` per active dialogue voice
- passage sizes and any unsafe/very-short passage runs
- boundary counts and total inserted pause by kind
- per-segment format/energy checks plus final-track loudness, clipping, and silence
- cache/reuse versus regenerated passages
- publication STT coverage and playback acceptance

Retry only failed passages. A failed or changed passage must not force paid
regeneration of unaffected, fingerprint-matching audio. Never weaken source, privacy,
publication, or playback gates to make the new lane look green.

### Implementation order

1. Add focused planner data structures/helpers and deterministic EN/DE dialogue-span
   fixtures. Keep exact source reconstruction as the first invariant.
2. Integrate stable speaker ids and an automatic distinct cast resolver. Preserve
   explicit overrides and private voice-id storage.
3. Change render fingerprints and narration-plan contract/version so incompatible
   legacy audio is invalidated or explicitly migrated.
4. Replace per-segment mastering with segment preparation plus final-track mastering;
   add controlled boundary timing.
5. Add receipt/quality projections, selective repair, and user-facing voice-preview
   integration.
6. Run a bounded live canary only after mocked tests pass and provider balance/runtime
   readiness is checked through the existing live-ops lane. Do not purchase credit or
   broaden delivery without user approval.

### Required tests

Add focused tests near:

- `tests/test_telegram_epub_audiobook_pipeline.py`
- `ea/tests/test_audiobook_epub_pipeline.py`
- `ea/tests/test_audiobook_voice_audition.py`
- audiobook quality/receipt tests already covering M4B and live-delivery projections

At minimum prove:

- English and German inline quoted speech is separated from narrator attribution
- curly quotes, guillemets, dialogue dashes, multiple turns, and malformed quotes
  preserve exact source coverage and fail conservatively
- recurring named speakers receive stable ids and stable cast choices across chapters
- confirmed dialogue automatically uses a voice distinct from the narrator when the
  catalog contains at least two eligible voices
- one-voice catalogs cannot produce a false `distinct_from_narrator=true` claim
- explicit approved dialogue/cast choices override automatic choices
- adjacent same-speaker text is batched and provider-limit splits use a continuation
  boundary rather than a hard zero-gap concat
- narration around quoted speech remains narrator audio
- normalization/mastering runs on the final track, not independently per passage
- render signatures invalidate old segmentation/mastering/cast output
- interrupted renders reuse completed matching passages and retry only missing ones
- narration plan and render result never expose raw voice ids
- source tampering blocks before any paid synthesis request
- existing M4B, STT publication, playback acceptance, Telegram, WhatsApp, cleanup,
  throttling, and render-lock tests remain green

Use mocked provider audio for the broad suite. For the final live canary, use a short
rights-safe EN/DE fixture with at least narrator plus two dialogue turns. Listen to or
obtain human acceptance for these points: no clipped starts/ends, no abrupt level
reset, natural paragraph/scene timing, clearly distinct dialogue voice, stable speaker
identity, correct words, and useful chapter navigation. Persist the canary receipt;
do not equate waveform checks alone with perceived narration quality.

### Definition of done for this EA lane

The lane is done only when a fresh source can travel through the normal Telegram or
WhatsApp intake without hidden operator setup and produce a playable M4B/public player
reference whose current private plan and safe receipts prove exact text coverage,
automatic distinct dialogue casting, continuity-aware mastering, publication checks,
and human playback acceptance. A passing unit suite without a listened-to canary is
not enough. Report any provider limitation honestly rather than silently falling back
to chopped single-voice output.

Date: 2026-07-06
Repo: `/docker/EA`
Head: `4496e6a1`
Active workspace: `/docker/EA/ea`

## Active objective

Keep the proactive OODA gold-production slice honest and production-safe:

- ingest approved signals
- stage reversible next steps
- only interrupt on real user action
- keep irreversible actions consent-gated
- prove runtime posture from current receipts, not stale local projections

Do not mark the long-running goal complete or blocked.

## Latest delta after Pushbullet alias verification

Current live truth as of 2026-07-07:

- Pushbullet relay readiness is now live-verified again:
  - `python3 scripts/materialize_pushbullet_delivery_readiness.py --probe-live --pretty`
  - `status = ready_live_verified`
- The active primary client key remains `tibor`, but the live mailbox on that client is intentionally Tibor's Archon alias:
  - `PUSHBULLET_TIBOR_EMAIL=archon.megalon@gmail.com`
- The current `PB_TOKEN_TIBOR` token already matches that Archon mailbox and passes `/v2/users/me`.
- Do not "fix" this by renaming the client or forcing the email back to `tibor.girschele@gmail.com`; the client key is the operator-facing role, while the mailbox may be a Tibor-owned alias.

What changed:

- `tests/test_pushbullet_delivery.py`
  - added coverage that a named `tibor` client can verify a Gmail-dot-normalized Archon alias mailbox without mismatch
- `.env.example`
  - clarified that `PUSHBULLET_TIBOR_EMAIL` may point at a Tibor-owned alias such as `archon.megalon@gmail.com`

## Latest delta after Pushbullet relay implementation

User request handled in code:

- add a governed Pushbullet relay so:
  - PayPal-code pushes on Tibor's primary Pushbullet route forward to Elisabeth
  - all pushes on Elisabeth's Pushbullet route forward to Tibor
  - direct Tibor<->Elisabeth pair messages do not bounce back and forth
  - first run is future-only and primes state instead of replaying history

What changed:

- `ea/app/services/pushbullet_delivery.py`
  - added push-history read support via `list_pushbullet_pushes(...)`
  - added `pushbullet_client_email(...)`
  - extended `send_pushbullet_note(...)` with `target_email=...` for cross-account delivery
- `ea/app/services/pushbullet_relay.py`
  - new relay service with:
    - two default rules (`default` -> `elisabeth` PayPal-only, `elisabeth` -> `default` all)
    - local state file
    - first-run priming
    - pair-loop suppression
    - no raw message persistence beyond transient processing
- `ea/app/runner.py`
  - new scheduler hook:
    - `EA_PUSHBULLET_RELAY_ENABLED`
    - `EA_SCHEDULER_PUSHBULLET_RELAY_ENABLED`
    - `EA_SCHEDULER_PUSHBULLET_RELAY_INTERVAL_SECONDS`
  - relay logs at info only when primed/forwarded/blocked/error; otherwise debug
- `.env.example`
  - added `PUSHBULLET_EMAIL=` placeholder plus relay env placeholders
- tests:
  - `tests/test_pushbullet_delivery.py`
  - `tests/test_pushbullet_relay.py`
  - `tests/test_runner.py`

Verification completed:

- `python3 -m py_compile ea/app/services/pushbullet_delivery.py ea/app/services/pushbullet_relay.py ea/app/runner.py tests/test_pushbullet_delivery.py tests/test_pushbullet_relay.py tests/test_runner.py`
  - pass
- `pytest -q tests/test_pushbullet_delivery.py tests/test_pushbullet_relay.py tests/test_runner.py -k 'pushbullet or run_scheduler_pushbullet_relay or scheduler_pushbullet_relay_enabled'`
  - `10 passed, 20 deselected`

Live runtime truth:

- current Pushbullet live probe is still not green:
  - `python3 scripts/ea_live_ops.py probe-provider --provider pushbullet --format operator`
  - result: `status=blocked_setup_required`, `reason=pushbullet_live_probe_failed:elisabeth,pushbullet_relay_distinct_clients_required`
- direct live probe reason for Elisabeth token:
  - `pushbullet_account_email_mismatch`
- current repo env now has relay enabled flags:
  - `EA_PUSHBULLET_RELAY_ENABLED=1`
  - `EA_SCHEDULER_PUSHBULLET_RELAY_ENABLED=1`
  - `EA_PUSHBULLET_RELAY_PRIMARY_CLIENT=default`
  - `EA_PUSHBULLET_RELAY_SECONDARY_CLIENT=elisabeth`
- current repo env still exposes only the Elisabeth named client; there is no distinct Tibor/default Pushbullet client configured in `.env`
- because of that, the relay code is ready but cannot become live end-to-end until:
  - Tibor/default Pushbullet client email+token are configured
  - Elisabeth token is corrected so `/v2/users/me` matches `PUSHBULLET_ELISABETH_EMAIL`

Additional readiness hardening completed after the first relay patch:

- `scripts/materialize_pushbullet_delivery_readiness.py`
  - now emits relay posture under `relay`
  - fails closed with `pushbullet_relay_distinct_clients_required` when relay mode points both sides at the same effective account
  - no longer overclaims `client_coverage.multi_client_ready` when relay mode is enabled but only one effective account exists
- `scripts/verify_pushbullet_delivery_readiness.py`
  - verifies relay posture and relay delivery claims
- `tests/test_pushbullet_delivery_readiness.py`
  - covers relay-enabled blocked alias case
  - covers relay-enabled ready case with two distinct clients
- docs updated:
  - `README.md`
  - `RUNBOOK.md`

Verification completed:

- `pytest -q tests/test_pushbullet_delivery.py tests/test_pushbullet_relay.py tests/test_pushbullet_delivery_readiness.py tests/test_runner.py -k 'pushbullet or run_scheduler_pushbullet_relay or scheduler_pushbullet_relay_enabled'`
  - `21 passed`
- `python3 scripts/materialize_pushbullet_delivery_readiness.py`
- `python3 scripts/verify_pushbullet_delivery_readiness.py --pretty`
  - `status = pass`

## Latest delta after approval-surface and action-digest cleanup

Use this section over older proactive-approval and operator-action notes when they conflict.

Current live answer:

- `/admin/proactive-ooda/approval` is not an approval you need to click right now.
- The page now resolves to `Action needed, not approval` when the current state is a setup/recovery task rather than a consent-gated decision.
- When a live operator-action digest already selected a specific notification item, the approval page now prefers that digest-selected action instead of the first raw queue row.
- The current real action in the default digest is `pushbullet_delivery_setup`.
- `weekly_signal_to_decision_review_acceptance` stays queue-only/admin-visible proof work and no longer pollutes the approval/action surface.

What changed:

- `scripts/materialize_operator_action_required_digest.py`
  - dedupe/coverage now keys off prior notification coverage, not just prior internal digest membership
  - persisted state now records `last_notification_item_hashes`
  - a newly included action that was never actually notified can no longer be suppressed as `covered_by_previous_send`
- `scripts/materialize_operator_action_required_dedupe_proof.py`
  - proof now distinguishes:
    - `duplicate_suppression_valid`
    - `notification_required`
  - notification-required proof is now a valid passing outcome when a new action must still be surfaced
- `scripts/verify_operator_action_required_dedupe_proof.py`
  - verifier now accepts both proof shapes and enforces the matching sent/ready receipt semantics
- `ea/app/api/routes/proactive_ooda_approval_support.py`
  - fallback operator action picker now skips internal proof/noise rows
  - fallback operator action picker now prefers `notification_items` from `ea_operator_action_required_digest.generated.json` before falling back to the raw queue head
  - the approval page no longer promotes weekly/proof rows as if they were the thing to approve
- `ea/app/api/routes/landing_console_support.py`
  - loads `ea_operator_action_required_digest.generated.json` for the proactive approval page fallback
- `ea/app/api/routes/landing.py`
  - mirrors the same digest-backed fallback for the non-console route
- `scripts/materialize_continuous_improvement_goal_posture.py`
  - `pushbullet_delivery_setup` now uses `notification_policy = default` instead of `head_only`, so it can surface once as a real follow-on action behind a previously notified Google head

Live receipt truth after refresh:

- `ea_operator_action_required_digest.generated.json`
  - `status = ready_to_send`
  - `notification_status = ready_to_send`
  - `notification_mode = new_items_behind_existing_head`
  - `included_action_keys = ["google_workspace_oauth_setup", "pushbullet_delivery_setup"]`
  - `notification_action_keys = ["pushbullet_delivery_setup"]`
  - `send_requested = false`
  - `send_attempted = false`
- `ea_operator_action_required_dedupe_proof.generated.json`
  - `status = pass`
  - `proof_outcome = notification_required`
  - `would_send_without_force = true`
  - `suppressed_duplicate_expected = false`
  - `notification_action_keys_without_force = ["pushbullet_delivery_setup"]`
- `ea_continuous_improvement_goal_posture.generated.json`
  - `pushbullet_delivery_setup.notification_policy = default`
  - `weekly_signal_to_decision_review_acceptance.telegram_push_allowed = false`
  - `weekly_signal_to_decision_review_acceptance.action_digest_eligible = false`
  - `weekly_signal_to_decision_review_acceptance.default_action_digest_suppressed_reason = telegram_push_not_allowed`

Route/UI truth:

- When no consent-gated proactive packet is pending, `/admin/proactive-ooda/approval` should read as an action surface, not an approval surface.
- If a real operator action exists, the page should say `Action needed, not approval`.
- If no such action exists, it should remain a no-pending-approval state.

Verification completed:

- `pytest -q tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py tests/test_admin_surface_runtime_contracts.py -k 'operator_action_required or proactive_ooda_approval_page'`
  - `33 passed`
- `python3 -m pytest --import-mode=importlib -q /docker/EA/ea/tests/test_proactive_ooda_approval_capture.py`
  - `8 passed`
- `pytest -q /docker/EA/tests/test_operator_action_required_digest.py /docker/EA/tests/test_operator_action_required_dedupe_proof.py /docker/EA/tests/test_admin_surface_runtime_contracts.py -k 'operator_action_required or proactive_ooda_approval_page or digest_priority'`
  - `34 passed`
- `pytest -q tests/test_continuous_improvement_goal_posture.py tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py tests/test_proactive_ooda_gold_acceptance_materializer.py tests/test_proactive_ooda_gold_acceptance_verifier.py`
  - `119 passed`
- final verifiers passed:
  - `verify_proactive_ooda_operator_status.py`
  - `verify_continuous_improvement_goal_posture.py`
  - `verify_google_workspace_oauth_readiness.py`
  - `verify_pushbullet_delivery_readiness.py`
  - `verify_operator_action_required_digest.py`
  - `verify_operator_action_required_dedupe_proof.py`
  - `verify_proactive_ooda_gold_acceptance.py`

## Latest delta after weekly proof digest suppression

Use this section over older operator-action digest notes when they conflict.

Current live answer:

- Telegram/default action digest now includes only concrete office setup/recovery actions:
  - `google_workspace_oauth_setup`
  - `pushbullet_delivery_setup`
- `weekly_signal_to_decision_review_acceptance` remains visible in the admin/operator queue as required gold-proof work, but it is no longer pushed in the default Telegram digest.
- `proactive_ooda_packet_acceptance` remains queue-only/non-action-required for the current packet.

What changed:

- `scripts/materialize_continuous_improvement_goal_posture.py`
  - `_signal_review_action_context(...)` now sets `telegram_push_allowed = false`
  - adds `notification_policy = queue_only_proof`
  - keeps `user_action_required = true`, so the proof remains visible and auditable in the operator queue
- `scripts/verify_continuous_improvement_goal_posture.py`
  - verifier now permits weekly signal-review proof capture to be action-required but Telegram-suppressed
  - still enforces that real acceptance/proof rows do not allow non-action progress pushes
- `tests/test_continuous_improvement_goal_posture.py`
  - updated queue and digest assertions so weekly proof capture is `action_digest_eligible = false` with `default_action_digest_suppressed_reason = telegram_push_not_allowed`

Refreshed receipt truth:

- `ea_continuous_improvement_goal_posture.generated.json`
  - head action remains `google_workspace_oauth_setup`
  - weekly row:
    - `user_action_required = true`
    - `telegram_push_allowed = false`
    - `action_digest_eligible = false`
    - `default_action_digest_suppressed_reason = telegram_push_not_allowed`
- `ea_operator_action_required_digest.generated.json`
  - `included_action_keys = ["google_workspace_oauth_setup", "pushbullet_delivery_setup"]`
  - `suppressed_policy_blocked_count = 1`
  - `send_attempted = false`
  - `notification_status = suppressed_duplicate`

Verification completed:

- `pytest -q tests/test_continuous_improvement_goal_posture.py`
  - `33 passed`
- `pytest -q tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py`
  - `25 passed`
- verifiers passed:
  - `verify_continuous_improvement_goal_posture.py`
  - `verify_operator_action_required_digest.py`
  - `verify_operator_action_required_dedupe_proof.py`
  - `verify_proactive_ooda_gold_acceptance.py`
  - `verify_proactive_ooda_operator_status.py`
  - `verify_google_workspace_oauth_readiness.py`

## Latest delta after gold remaining-proof wording cleanup

Use this section over older gold-acceptance approval-proof notes when they conflict.

Current live answer:

- `/admin/proactive-ooda/approval` still has nothing to approve right now.
- The head action is still Google Workspace recovery:
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_label = Retry Google auth`
  - `next_action_href = /integrations/google`
- The gold receipt now routes low-level recovery to:
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `next_action_href = https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace`
- The remaining gold proof is now:
  - `current recordable proactive OODA packet acceptance evidence`

What changed:

- `scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `_remaining_external_proofs(...)` now accepts `approval_capture_required`
  - when the current packet is not recordable for approval capture, the receipt no longer claims that approval-capture readiness or an explicit approval outcome is missing for that packet
  - it instead reports the real missing proof: a current recordable proactive packet acceptance
- `tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - added regression coverage for Google source-health recovery plus a non-recordable reversible packet
  - updated the operator-safe mirrored-delivery expectation to the same wording

Why this matters:

- The gold receipt can still block gold production honestly.
- It must not send the operator back to a verdict/approval mental model when the current packet cannot be approved.
- This keeps approval capture, source recovery, and ordinary-use acceptance as separate concepts.

Verification completed:

- `python3 -m py_compile scripts/materialize_proactive_ooda_gold_acceptance.py tests/test_proactive_ooda_gold_acceptance_materializer.py scripts/verify_proactive_ooda_gold_acceptance.py tests/test_proactive_ooda_gold_acceptance_verifier.py`
- `pytest -q tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - `41 passed`
- `pytest -q tests/test_proactive_ooda_gold_acceptance_verifier.py`
  - `18 passed`
- refreshed receipts and verifiers passed:
  - `materialize_proactive_ooda_operator_status.py`
  - `materialize_google_workspace_oauth_readiness.py`
  - `materialize_pushbullet_delivery_readiness.py`
  - `materialize_proactive_ooda_gold_acceptance.py`
  - `materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `materialize_operator_action_required_dedupe_proof.py`
  - `verify_proactive_ooda_gold_acceptance.py`
  - `verify_proactive_ooda_operator_status.py`
  - `verify_continuous_improvement_goal_posture.py`
  - `verify_operator_action_required_digest.py`
  - `verify_operator_action_required_dedupe_proof.py`
  - `verify_google_workspace_oauth_readiness.py`

## Latest delta after Google source-health user-action normalization

User asked again what should actually be approved on `/admin/proactive-ooda/approval`.

Current answer:

- nothing is waiting for approval on that page right now
- the real action is Google Workspace recovery:
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_label = Retry Google auth`
  - `next_action_href = /integrations/google`
- the lower-level proactive operator/gold recovery action is:
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `next_action_href = https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace`

Code change:

- `scripts/materialize_proactive_ooda_operator_status.py`
  - added `_runtime_source_health_issue_requires_user_action(...)`
  - Google Workspace OAuth reauth failures now normalize to `user_action_required = true` even when the raw runtime source-health issue forgot the flag
  - generic source failures such as discovery `FileNotFoundError` remain operator-repair-only and do not become fake user actions
- `tests/test_proactive_ooda_operator_status_materializer.py`
  - added regression assertions that `google_oauth_invalid_grant` plus `reauthorize_google_workspace_binding` publishes both top-level and issue-level `user_action_required = true`

Refreshed receipt truth:

- `ea_proactive_ooda_operator_status.generated.json`
  - `status = ready_with_recovery_action`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `source_health.user_action_required = true`
  - `source_health.issues[0].user_action_required = true`
- `ea_continuous_improvement_goal_posture.generated.json`
  - head item remains `google_workspace_oauth_setup`
  - no proactive approval row is the head action
- `ea_operator_action_required_digest.generated.json`
  - `status = suppressed_duplicate`
  - `send_attempted = false`
  - `notification_item_count = 0`

Verification completed:

- `python3 -m py_compile ../scripts/materialize_proactive_ooda_operator_status.py ../tests/test_proactive_ooda_operator_status_materializer.py`
- `pytest -q ../tests/test_proactive_ooda_operator_status_materializer.py -k 'source_health or followthrough_repair' -vv`
  - `2 passed`
- `pytest -q ../tests/test_continuous_improvement_goal_posture.py -k 'source_health or google_workspace or proactive' -vv`
  - `9 passed`
- `pytest -q ../tests/test_google_workspace_oauth_readiness.py`
  - `12 passed`
- verifiers passed:
  - `verify_proactive_ooda_operator_status.py`
  - `verify_proactive_ooda_gold_acceptance.py`
  - `verify_continuous_improvement_goal_posture.py`
  - `verify_operator_action_required_digest.py`
  - `verify_operator_action_required_dedupe_proof.py`
  - `verify_google_workspace_oauth_readiness.py`

Do not regress this:

- `/admin/proactive-ooda/approval` is not a generic action queue.
- Google OAuth recovery is a real user action, but it is not something to "approve."
- Telegram remains quiet on duplicate-covered action sets.

## Latest delta after default action-digest stream eligibility

Use this section over older operator-action queue delivery-policy notes below when they conflict.

Current change:

- `scripts/materialize_continuous_improvement_goal_posture.py`
  - every `operator_action_queue` row now exposes `action_digest_eligible`
  - rows that are real user actions but not in the default Telegram digest stream expose `default_action_digest_suppressed_reason`
  - `operator_delivery_policy` now publishes:
    - `default_action_digest_eligible_count`
    - `default_action_digest_suppressed_count`
    - `next_action_digest_eligible`
- `scripts/materialize_operator_action_required_digest.py`
  - respects explicit `action_digest_eligible=false` before applying stream inclusion
  - sanitized notification items include `action_digest_eligible=true`
- `scripts/verify_continuous_improvement_goal_posture.py`
  - verifies row-level eligibility against stream, push, action-required, and delivery-policy fields
  - verifies aggregate delivery-policy counts against the queue
- tests updated:
  - `tests/test_continuous_improvement_goal_posture.py`
  - `tests/test_operator_action_required_digest.py`

Why this mattered:

- `media_memorial` actions such as audiobook voice choice, Manfred realtime proof, and WhatsApp audiobook pairing can still be real user actions in the admin queue
- they must not look eligible for the default Telegram action digest unless the stream policy explicitly widens
- this makes "Telegram only when action is needed" more precise: default digest covers office loop/setup/recovery; media/memorial actions stay visible but suppressed from the default push lane

Current live queue after refresh:

- default digest eligible: `3`
  - `google_workspace_oauth_setup`
  - `pushbullet_delivery_setup`
  - `weekly_signal_to_decision_review_acceptance`
- suppressed from default digest: `3`
  - `telegram_audiobook_live_delivery`
  - `manfred_stt_tts_realtime_conversation`
  - `whatsapp_audiobook_live_delivery`
- all suppressed media rows carry `default_action_digest_suppressed_reason = operator_stream_not_in_default_action_digest`

Verification completed:

- `pytest -q /docker/EA/tests/test_operator_action_required_digest.py /docker/EA/tests/test_operator_action_required_dedupe_proof.py`
  - `24 passed`
- `pytest -q /docker/EA/tests/test_continuous_improvement_goal_posture.py`
  - `33 passed`
- stable receipt refresh and verifiers:
  - `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 scripts/materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `python3 scripts/materialize_operator_action_required_dedupe_proof.py`
  - `python3 scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 scripts/verify_operator_action_required_digest.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_digest.generated.json`
  - `python3 scripts/verify_operator_action_required_dedupe_proof.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json`
  - `python3 scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `python3 scripts/verify_proactive_ooda_operator_status.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - all passed

Current live truth remains:

- top user action: `retry_full_workspace_auth_with_approved_account` at `/integrations/google`
- second user action: `pushbullet_token_missing:elisabeth`
- gold still blocked on real proactive packet acceptance evidence

## Latest delta after meta-only approval repair suppression

Use this section over older approval-capture and queue-visibility notes below when they conflict.

## Latest delta after action-required Telegram digest hardening

Use this section over older operator-action digest notes below when they conflict.

Current change:

- `scripts/materialize_operator_action_required_digest.py`
  - Telegram text now emits a clickable `Open:` action URL for `next_action_form_href`
  - relative EA action links are resolved against the public queue host, e.g. `/integrations/google` -> `https://myexternalbrain.com/integrations/google`
  - redacted auth retry templates are suppressed from Telegram text, so `<redacted-email>` placeholders do not become broken action links
- `tests/test_operator_action_required_digest.py`
  - added coverage for action-link rendering and redacted retry suppression
- `scripts/materialize_operator_action_required_dedupe_proof.py`
  - duplicate proof now fails closed when legacy key-only state has a mismatched `last_digest_sha256`
  - digest mismatch is accepted only when hash-backed per-item state proves the current action set is already covered

Live operator delivery proof:

- a single action-required Telegram digest was sent at `2026-07-06T17:21:56Z`
- state file: `.runtime/ea_operator_action_required_digest_state.json`
  - `last_notification_item_keys = ["google_workspace_oauth_setup"]`
  - `last_notification_mode = head_delta`
  - `message_id_count = 1`
- the published digest was then rebuilt without sending and now shows duplicate suppression:
  - `ea_operator_action_required_digest.generated.json`
  - `status = suppressed_duplicate`
  - `notification_status = suppressed_duplicate`
  - `notification_item_count = 0`
  - `dedupe_suppressed = true`
- formal duplicate proof:
  - `ea_operator_action_required_dedupe_proof.generated.json`
  - `status = pass`
  - `current_actions_covered_by_prior_state = true`
  - `notification_mode_without_force = covered_by_previous_send`
  - `state.message_id_count = 1`

Focused verification completed:

- `pytest -q /docker/EA/tests/test_operator_action_required_digest.py /docker/EA/tests/test_operator_action_required_dedupe_proof.py -k 'digest or dedupe or telegram_text'`
  - `23 passed`
- `python3 /docker/EA/scripts/verify_operator_action_required_digest.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_digest.generated.json`
  - pass
- `python3 /docker/EA/scripts/verify_operator_action_required_dedupe_proof.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json`
  - pass
- refreshed downstream receipts:
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `python3 /docker/EA/scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 /docker/EA/scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`

Current live truth after this slice:

- top operator action remains `Retry Google auth` at `/integrations/google`
- Pushbullet setup remains second with `pushbullet_token_missing:elisabeth`
- the Telegram action-required lane is no longer blocked by the stale `FileNotFoundError` receipt
- normal digest reruns do not message again until the action set changes or a forced resend is used

Follow-up verification on 2026-07-06 17:16Z:

- refreshed receipts:
  - `python3 scripts/materialize_google_workspace_oauth_readiness.py`
  - `python3 scripts/materialize_pushbullet_delivery_readiness.py`
  - `python3 scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
- verifiers passed:
  - `python3 scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
- focused tests passed:
  - `pytest -q /docker/EA/ea/tests/test_proactive_ooda_approval_capture.py -k 'approval_surface or approval_capture'`
  - `pytest -q /docker/EA/tests/test_proactive_ooda_operator_actions.py /docker/EA/tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'approval_capture or repair_proactive_approval_capture or maps_approval'`
- live loopback page check against `ea-api` returned 200 and visible text includes:
  - `Nothing waiting for approval`
  - `There is no live proactive packet waiting for explicit approval right now.`
  - `Pending approvals 0`
- refreshed goal posture says the actual user action is still:
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_href = /integrations/google`
  - `next_action_label = Retry Google auth`
- refreshed gold acceptance still tracks missing proof internally:
  - `status = blocked_missing_proactive_packet_evidence`
  - `approval_capture_surface.ready = false`
  - `current_packet_user_action_required = false`
  - `current_packet_live_pending_count = 0`

Current change:

- `ea/app/services/proactive_ooda_operator_actions.py`
  - `repair_proactive_approval_capture` now maps to `/admin/goals`, not `/admin/proactive-ooda/approval`
  - live approval actions still map to `/admin/proactive-ooda/approval` only for:
    - `tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome`
    - `record_proactive_ooda_approval_outcome`
- `scripts/materialize_continuous_improvement_goal_posture.py`
  - treats `repair_proactive_approval_capture` as meta-only follow-through when no current approval surface requires user action
  - hides that row from `operator_action_queue`
- tests updated:
  - `tests/test_proactive_ooda_operator_actions.py`
  - `tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - `tests/test_continuous_improvement_goal_posture.py`

Focused verification completed in this slice:

- `pytest -q /docker/EA/tests/test_proactive_ooda_operator_actions.py -k 'approval_capture_repair_to_goals or maps_approval_capture or maps_approval_reissue'`
- `pytest -q /docker/EA/tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'capture_surface_is_not_live_ready or repair_proactive_approval_capture'`
- `pytest -q /docker/EA/tests/test_continuous_improvement_goal_posture.py -k 'keeps_proactive_approval_queue_only_when_runtime_marks_no_user_action or hides_meta_only_proactive_approval_repair_without_live_surface or queue_only_proactive_recovery_without_approval_form'`
- live refresh sequence:
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `python3 /docker/EA/scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 /docker/EA/scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
- both verifiers returned `{"status":"pass","issues":[]}`

Current live truth after refresh:

- `ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = blocked_missing_proactive_packet_evidence`
  - `next_action = repair_proactive_approval_capture`
  - `next_action_href = https://myexternalbrain.com/admin/goals`
- `ea_continuous_improvement_goal_posture.generated.json`
  - top action remains Google auth recovery:
    - `next_action = retry_full_workspace_auth_with_approved_account`
    - `next_action_href = /integrations/google`
  - `proactive_ooda_packet_acceptance.action_context.operator_queue_visible = false`
  - `proactive_ooda_packet_acceptance.action_context.console_deep_link = ""`
  - `operator_action_queue` contains zero `proactive_ooda_packet_acceptance` rows

What this proves:

- `/admin/proactive-ooda/approval` is no longer used for proof-repair or stale/meta approval capture when no live approval is pending
- the user-facing queue now exposes only real action-required work; current head remains Google Workspace reauthorization
- gold production is still not complete because current evidence still lacks a real accepted proactive OODA packet outcome after live approval/capture, and Google Workspace auth is still unhealthy

## Latest delta after gold-acceptance approval-noise fix

Use this section over older gold-acceptance notes below when they conflict.

Current change:

- `scripts/materialize_proactive_ooda_gold_acceptance.py`
  - tightened the gold-state gate so `ready_for_approval_outcome_capture` only appears when approval capture is actually ready now, not merely because a historical proof row exists
  - when no live/manual capture is ready for the current packet, the receipt now falls back to `repair_proactive_approval_capture` instead of telling the user to record an approval outcome anyway
  - `remaining_external_proofs` now includes missing approval-capture readiness whenever the packet cannot actually be approved yet
- `scripts/verify_proactive_ooda_gold_acceptance.py`
  - added verifier enforcement that `ready_for_approval_outcome_capture` requires `proofs.approval_capture_readiness.ready = true`
- tests updated:
  - `tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - `tests/test_proactive_ooda_gold_acceptance_verifier.py`

Why this mattered:

- the user hit `/admin/proactive-ooda/approval` and saw noise because the gold receipt could still route to approval capture even when `current_packet_live_pending_count = 0`, `pending_approval_surface = false`, and the current packet did not require user approval
- that was mixing proof-capture semantics with real operator-action semantics

Focused verification completed in this slice:

- `python3 -m py_compile /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py`
- `pytest -q /docker/EA/tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'accepts_manual_approval_capture_without_live_callback or falls_back_to_recording_outcome_when_capture_surface_is_not_live_ready'`
- `pytest -q /docker/EA/tests/test_proactive_ooda_gold_acceptance_verifier.py -k 'accepts_valid_receipt or rejects_ready_status_without_live_capture_readiness'`

Current live truth after refresh:

- there is no real pending approval surface now
- fresh operator-status says:
  - `status = ready_with_recovery_action`
  - `reason = google_workspace_signal_source_unhealthy:google_oauth_invalid_grant`
  - `next_action = reauthorize_google_workspace_binding`
- fresh gold receipt no longer asks for approval capture; it downgraded to operator-runtime blockage
- continuous-improvement goal posture still points at Google auth recovery:
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_href = /integrations/google`

Open seam:

- repeated gold/operator-status refreshes can still report source-fingerprint drift between the two generated receipts
- this does not change the user-facing answer, but it keeps `verify_proactive_ooda_gold_acceptance.py` from going green after both files are regenerated
- likely next slice: align source-fingerprint semantics across generated receipt cross-links or exclude generated receipt churn consistently

## Latest delta after live source-fingerprint stabilization

Use this section over the older fingerprint-drift note above when they conflict.

Current change:

- `scripts/source_state_head.py`
  - added runtime artifact exclusions for `state/` and `ea/state/`
  - source-worktree fingerprinting now ignores proactive OODA live receipts, stage packets, safe-work results, and related runtime state churn
- `scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `operator_runtime_posture.next_action` now preserves the actual selected operator recovery action instead of being overwritten by lower-priority source-coverage detail
  - `_operator_runtime_next_action(...)` now prefers `operator_status.next_action` when the runtime reason is a `source_health_*` recovery state, which matches the current operator-status format for Google OAuth failure
- tests updated:
  - `tests/test_project_mode_manifests.py`
  - `tests/test_proactive_ooda_gold_acceptance_materializer.py`

Focused verification completed in this slice:

- `pytest -q /docker/EA/tests/test_project_mode_manifests.py -k 'source_worktree_metadata_reports_source_dirty_without_generated_noise or source_worktree_fingerprint_hashes_effective_source_files_only or source_worktree_fingerprint_falls_back_without_git_binary'`
- `pytest -q /docker/EA/tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'prefers_source_health_recovery_action_over_coverage_probe or reauthorize_google_workspace_binding or accepts_manual_approval_capture_without_live_callback or falls_back_to_recording_outcome_when_capture_surface_is_not_live_ready'`
- `python3 -m py_compile /docker/EA/scripts/source_state_head.py /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
- live refresh sequence:
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - result: `{"status":"pass","issues":[]}`

Current live truth after the sequential refresh:

- source fingerprint is now stable across repeated reads during the same live window
- fresh operator-status:
  - `status = ready_with_recovery_action`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `next_action = reauthorize_google_workspace_binding`
- fresh gold acceptance:
  - `status = blocked_missing_proactive_packet_evidence`
  - verifier passes
  - `proofs.operator_runtime_posture.next_action = reauthorize_google_workspace_binding`
  - remaining proofs are now narrowly:
    - `redacted approval-capture readiness for the proactive OODA packet`
    - `redacted explicit approval outcome for the proactive OODA packet`
- refreshed goal posture:
  - `status = active_with_blockers`
  - top operator action still points at Google auth retry for the approved work account

Remaining seam:

- gold acceptance is now stable and honest, but its top-level `next_action` still points at `repair_proactive_approval_capture` because gold proof is missing approval-capture evidence even though there is no live pending user approval surface
- goal posture currently masks that well by correctly prioritizing Google auth recovery
- next slice, if continuing here: separate gold-proof operator capture remediation from actual user-facing approval work so downstream surfaces never route a user to `/admin/proactive-ooda/approval` unless a current approval surface is truly live

## Latest delta after proactive approval-page fallback correction

Use this section over older approval-surface notes below when they conflict.

Current change:

- `ea/app/api/routes/proactive_ooda_approval_support.py`
  - added `approval_surface_fallback_operator_action(...)` so the no-pending approval surface prefers the live goal-posture head action over stale packet-derived fallback text
  - added `current_operator_action_head(...)` and normalized fallback action shaping so both current-packet and live-posture actions render through the same minimal contract
  - tightened the no-pending copy so it says there is nothing to approve and to follow the actual operator action below if it still matters
- `ea/app/api/routes/landing.py`
- `ea/app/api/routes/landing_console_support.py`
  - both approval routes now use the shared fallback resolver with the current continuous-improvement goal posture whenever `approval_surface_pending = false`
- `ea/tests/test_proactive_ooda_approval_capture.py`
  - added regression coverage that proves a stale internal-action packet no longer wins over the live blocker when no approval is pending

Why this mattered:

- `/admin/proactive-ooda/approval` was correctly computing `approval_surface_pending = false`, but it still preferred a stale packet-derived fallback whenever one existed
- that made the screen look like a vague approval/setup prompt instead of the real current blocker, which is why the user kept seeing noise instead of a concrete action

Focused verification completed in this slice:

- `python3 -m py_compile /docker/EA/ea/app/api/routes/proactive_ooda_approval_support.py /docker/EA/ea/app/api/routes/landing_console_support.py /docker/EA/ea/app/api/routes/landing.py /docker/EA/ea/tests/test_proactive_ooda_approval_capture.py`
- `pytest -q /docker/EA/ea/tests/test_proactive_ooda_approval_capture.py`
  - `6 passed`
- direct live bundle replay against current receipts now resolves:
  - `approval_surface_pending = false`
  - `console_title = Nothing waiting for approval`
  - fallback action = `Retry Google auth`
  - blocker detail = `Google Workspace auth needs reauthorization before EA can rely on that source. Retry the Full Workspace auth link with the approved work Google account.`

What is actually true now:

- there is nothing to approve on `/admin/proactive-ooda/approval` right now
- the page now points at the live blocker from goal posture instead of a stale packet summary
- the real current blocker remains Google Workspace reauthorization, not proactive approval capture

## Latest delta after default live-probe retry hardening

Use this section over older operator-status probe notes below when they conflict.

Current change:

- `scripts/materialize_proactive_ooda_operator_status.py`
  - added a targeted host-runtime retry path for live proactive probes
  - when the default live bundle comes back incomplete (`route_probe` missing, artifact probe empty, source coverage empty, or provider-cost probe empty), the materializer now retries once with `EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE=1`
  - the retry is accepted only when it produces a stronger live bundle than the initial probe path
- `tests/test_proactive_ooda_operator_status_materializer.py`
  - added regression coverage for the exact failure mode: default bundle incomplete, host-runtime retry healthy, final receipt must keep the stronger host-backed result

Why this mattered:

- the root operator-status receipt could still regress into a weak `followthrough_artifacts_missing` / `source_coverage not_checked` posture unless the materializer was run manually with host-runtime preference env flags
- that made the published receipt and later gold/goal posture materializations drift depending on which probe path happened to run

Focused verification completed in this slice:

- `pytest -q /docker/EA/tests/test_proactive_ooda_operator_status_materializer.py -k 'retries_host_runtime_probe_when_default_bundle_is_incomplete or provider_cost_pressure or route_artifact_probe or historical_browse_backed_packet or assistant_grade'`
- `python3 -m py_compile /docker/EA/scripts/materialize_proactive_ooda_operator_status.py /docker/EA/tests/test_proactive_ooda_operator_status_materializer.py`

Current verified published state after default re-materialization:

- `python3 /docker/EA/scripts/materialize_proactive_ooda_operator_status.py --pretty`
  - now succeeds without special env flags
  - published root operator-status receipt verifies cleanly
- `python3 /docker/EA/scripts/verify_proactive_ooda_operator_status.py --pretty`
  - `{"status": "pass", "issues": []}`
- `python3 /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
- `python3 /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py --pretty`
  - `{"status": "pass", "issues": []}`
- `python3 /docker/EA/scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
- `python3 /docker/EA/scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `{"status": "pass", "issues": []}`

Root published receipts now read:

- `ea_proactive_ooda_operator_status.generated.json`
  - `status = ready_with_recovery_action`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `summary = Proactive OODA route and packet runtime are available, but 1 signal source health issue(s) need operator recovery: google_workspace.`
  - `next_action = reauthorize_google_workspace_binding`
  - `source_coverage.status = ready`
  - `provider_cost_pressure.status = active_cost_control`
  - `provider_cost_pressure.primary_background_provider = onemin`
- `ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = ready_for_approval_outcome_capture`
  - `next_action = record_proactive_ooda_approval_outcome`
- `ea_continuous_improvement_goal_posture.generated.json`
  - `status = active_with_blockers`
  - `next_action_key = google_workspace_oauth_setup`
  - proactive approval followthrough is still tracked as proof but is no longer in `operator_action_queue` when `user_action_required = false`

What is actually true now:

- the old proactive-approval page noise is contained
- the default operator-status materializer no longer needs a manual env override to recover source coverage and provider-cost telemetry
- the real current blocker is Google Workspace source health / full-workspace auth recovery, not probe-path drift

## Latest delta after transcript payload hygiene fix

Use this section over older transcript-noise notes below when they conflict.

Current change:

- `ea/app/services/proactive_signal_discovery.py`
  - transcript-driven research-backed draft packets now write `draft_request_text` from `_transcript_task_focused_request_text(...)` instead of carrying the full raw mixed transcript into the staged packet
  - search-query expansion for this branch now also uses the focused task text instead of the full mixed transcript

Why this mattered:

- a live archived approval packet for an electrician draft still had a compact `research_query`, but its `safe_work_order.input_contract.draft_request_text` contained a long mixed medical/home transcript
- that made the packet internally noisy and created a path for irrelevant transcript spillover into later review surfaces

Focused verification completed in this slice:

- `pytest -q /docker/EA/tests/test_proactive_signal_discovery.py -k 'mixed_recording_display or buried_provider_note or electrician_draft'`
- `pytest -q /docker/EA/ea/tests/test_proactive_ooda_safe_work.py -k 'clean_query_over_transcript_noise or ambient_transcript_noise'`
- `python3 -m py_compile /docker/EA/ea/app/services/proactive_signal_discovery.py /docker/EA/tests/test_proactive_signal_discovery.py`

Runtime proof:

- container source check confirmed `/app/ea/app/services/proactive_signal_discovery.py` contains the new `focused_request` branch
- direct in-container probe of `observation_row_to_signal(...)` for a mixed medical/electrician Pocket transcript now returns:
  - `research_query = Elektriker fuer zusaetzliche Steckdosen.`
  - `draft_request_text = Und zusaetzlich, ich moechte auch einen Elektriker kommen lassen fuer zusaetzliche Steckdosen. Wenn du einen gefunden hast, formuliere bitte eine kurze Anfrage als Draft.`
  - no `blood pressure` or leg-swelling text in `draft_request_text` or `search_queries`

Still true after this fix:

- current live archived packet `proactive-ooda-stage-52e18b2afe75f3a5afb4baae` remains an old artifact created before this patch
- a fresh full live rerun was not used as proof because the current runtime latest-run receipt had `item_count = 0`, so the direct in-container signal-generation probe is the authoritative proof for this slice

## Latest delta after runtime proof refresh

Use this section over the older notes below when they conflict.

Current verified posture from the refreshed live receipts and published artifacts:

- `ea_proactive_ooda_operator_status.generated.json`
  - `status = ready_with_live_receipt`
  - `reason = ready`
  - `summary = Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.`
  - `assistant_grade_packet.bundle_source = historical_browse_backed_proof_bundle`
  - `assistant_grade_packet.stage_kind = decision_packet`
  - `assistant_grade_packet.work_type = research`
  - `assistant_grade_packet.requires_recovery = false`
  - `source_coverage.status = ready`
  - `source_coverage.missing_lane_keys = []`
  - `provider_cost_pressure.status = active_cost_control`
  - `provider_cost_pressure.primary_background_provider = onemin`
- `ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = ready_for_approval_outcome_capture`
  - `summary = A proactive OODA packet has local gold-proof runtime evidence; capture the redacted approval outcome next.`
  - `next_action = record_proactive_ooda_approval_outcome`
  - `next_action_label = Record packet verdict`
  - `next_action_href = https://myexternalbrain.com/admin/proactive-ooda/approval`
- `ea_continuous_improvement_goal_posture.generated.json`
  - verifier passes
  - `next_action_key = google_workspace_oauth_setup`
  - proactive proof item still stays `user_action_required = false` and `delivery_policy = queue_only`
  - proactive action context now reflects:
    - `gold_status = ready_for_approval_outcome_capture`
    - `operator_runtime_status = ready_with_live_receipt`

What changed in code this slice:

- `ea/app/api/routes/proactive_ooda_approval_support.py`
  - no-pending proactive approval surface can now point to the real current operator action instead of behaving like a dead end
- `ea/app/api/routes/landing_console_support.py`
  - proactive approval page now reads the current goal-posture head action when the proactive approval lane is empty
- `scripts/ea_live_ops.py`
  - `probe_proactive_route(..., include_artifact_probe=False)` is supported so the route probe can skip the hanging artifact subprobe
- `scripts/materialize_proactive_ooda_operator_status.py`
  - route probe now skips embedded artifact probing and falls back to local artifact resolution
- `ea/app/services/proactive_ooda_runtime_artifacts.py`
  - `prefer_browse_backed_delivery=True` now prefers an assistant-grade browse/research packet over a newer internal operator-action packet when building proof posture

Focused verification completed in this slice:

- `pytest -q /docker/EA/tests/test_ea_live_ops.py -k 'skip_artifact_probe or proactive_route'`
- `pytest -q /docker/EA/tests/test_proactive_ooda_operator_status_materializer.py -k 'assistant_grade or historical_browse_backed_packet or provider_cost_pressure or route_artifact_probe'`
- `pytest -q /docker/EA/ea/tests/test_proactive_ooda_runtime_artifacts.py -k 'browse_backed or assistant_grade or internal_action'`
- `pytest -q /docker/EA/tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'recording_outcome_when_capture_surface_is_not_live_ready or manual_approval_capture_without_live_callback or ready_for_approval_outcome_capture'`
- `python3 /docker/EA/scripts/verify_proactive_ooda_operator_status.py --pretty`
- `python3 /docker/EA/scripts/verify_proactive_ooda_gold_acceptance.py --pretty`
- `python3 /docker/EA/scripts/verify_continuous_improvement_goal_posture.py --pretty`

Live probes/materializers that now matter:

- `python3 /docker/EA/scripts/materialize_proactive_ooda_operator_status.py --skip-gmail-draft-followthrough-probe`
- `python3 /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py`
- `python3 /docker/EA/scripts/materialize_continuous_improvement_goal_posture.py`
- direct source coverage probe now works and shows all 8 lanes observed:
  - `postgres_observations`
  - `google_workspace`
  - `pocket_ai_audio_transcripts`
  - `calendar_and_renewal_signals`
  - `relationship_and_occasion_signals`
  - `shopping_and_vendor_signals`
  - `commitment_and_deadline_signals`
  - `durable_profile_and_location_context`

Remaining real blockers after this slice:

1. user-facing head action is still `google_workspace_oauth_setup`
   - the work Google account still needs the OAuth Audience/test-user check completed and retried
2. proactive gold is still not complete
   - runtime proof is now good
   - the approval page should now be treated as a narrow verdict-capture step for the current proactive packet, not a generic queue redirect
   - what remains is a real redacted approval outcome for a current proactive packet
3. other office-setup and live-delivery proofs still exist in the broader operator queue
   - pushbullet setup
   - audiobook live delivery proofs
   - weekly signal-to-decision review acceptance

## Latest delta after approval-noise hardening

Use this section over the older proactive-approval notes below when they conflict.

Current verified posture from the refreshed published receipts and live bundle checks:

- live `/admin/proactive-ooda/approval` state is `Nothing waiting for approval`
- live proactive bundle now resolves to an internal/setup packet, not a current user-approval packet
- `ea_proactive_ooda_gold_acceptance.generated.json` currently carries `current_packet_user_action_required = false`
- `ea_continuous_improvement_goal_posture.generated.json` now has:
  - `next_action_key = google_workspace_oauth_setup`
  - `next_action = add_google_oauth_test_user_and_retry_full_workspace_auth`
  - `operator_action_queue[0].key = google_workspace_oauth_setup`
- the `proactive_ooda_packet_acceptance` queue row is still present for audit continuity, but now correctly stays:
  - `user_action_required = false`
  - `delivery_policy = queue_only`
  - `notification_policy = default`

Digest posture after refresh:

- `python3 scripts/materialize_operator_action_required_digest.py --dry-run` now returns `status = ready_to_send`
- `notification_action_keys = ["google_workspace_oauth_setup"]`
- the proactive approval item is no longer the interrupting head item

Code hardening added in this slice:

- `scripts/materialize_continuous_improvement_goal_posture.py`
  - proactive action context now honors `approval_capture_surface.current_packet_user_action_required` when present
- `tests/test_continuous_improvement_goal_posture.py`
  - added regression coverage proving a non-actionable proactive packet remains queue-only even if legacy pending counters are still present

Still open after this slice:

- `python3 scripts/verify_continuous_improvement_goal_posture.py --pretty` is now blocked only by `decide.provider_cost_pressure`
- direct live probe `python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json` works and reports `primary_background_provider = onemin`
- published `ea_proactive_ooda_operator_status.generated.json` still carries `provider_cost_pressure.status = not_checked`
- attempted re-materialization of proactive operator status still hangs inside `ea_live_ops.probe_proactive_route -> probe_proactive_artifacts -> _docker_compose_exec_json`

So the next worker should treat the remaining gap as:

1. fix or bypass the blocking proactive-artifacts subprobe inside proactive operator-status rematerialization
2. refresh `ea_proactive_ooda_operator_status.generated.json`
3. re-materialize goal posture and re-run:
   - `python3 scripts/verify_proactive_ooda_operator_status.py --pretty`
   - `python3 scripts/verify_continuous_improvement_goal_posture.py --pretty`

## Current verified published state

All core published receipts were re-materialized and all current verifiers passed at the end of this slice.

### Operator status

File:

- `/docker/EA/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json`

Headline fields:

- `generated_at = 2026-07-06T06:02:48Z`
- `status = ready_with_recovery_action`
- `reason = source_health_google_workspace:google_oauth_invalid_grant`
- `next_action = reauthorize_google_workspace_binding`
- `source_state_fingerprint = ceb67093d7fcd779dd8c44d2bac6a7f972c4b3dea4a44e18327a927a82717fa3`

Important runtime posture:

- `assistant_grade_packet.bundle_source = historical_browse_backed_proof_bundle`
- `assistant_grade_packet.requires_recovery = false`
- `approval_capture_surface.ready = true`
- `approval_capture_surface.current_packet_status = pending_approval`
- `approval_capture_surface.current_packet_live_pending_count = 1`
- `provider_cost_pressure.status = active_cost_control`
- `provider_cost_pressure.primary_background_provider = onemin`

Meaning:

- the live assistant-grade packet selection is good again
- the remaining operator recovery reason is Google Workspace source health, not a packet-quality regression

### Gold acceptance

File:

- `/docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`

Headline fields:

- `generated_at = 2026-07-06T06:04:25Z`
- `status = ready_for_approval_outcome_capture`
- `next_action = record_proactive_ooda_approval_outcome`
- `source_state_fingerprint = ceb67093d7fcd779dd8c44d2bac6a7f972c4b3dea4a44e18327a927a82717fa3`

Important followthrough proof:

- `approval_followthrough_prompt_sent = true`
- `approval_followthrough_notification_status = sent`
- `approval_followthrough_message_count = 1`
- `remaining_external_proofs = ["redacted explicit approval outcome for the proactive OODA packet"]`

Meaning:

- the approval-needed Telegram prompt for the current packet was actually sent
- gold is now back to the correct final gate: record the current redacted approval outcome

### Continuous-improvement goal posture

File:

- `/docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`

Headline fields:

- `generated_at = 2026-07-06T06:03:44Z`
- `status = active_with_blockers`
- `next_action_key = proactive_ooda_packet_acceptance`
- `next_action = record_proactive_ooda_approval_outcome`
- `source_state_fingerprint = ceb67093d7fcd779dd8c44d2bac6a7f972c4b3dea4a44e18327a927a82717fa3`

Meaning:

- the current action-required head is again the proactive approval outcome capture

### Operator action-required digest

File:

- `/docker/EA/.codex-studio/published/ea_operator_action_required_digest.generated.json`

Headline fields:

- `generated_at = 2026-07-06T06:03:48Z`
- `status = sent`
- `notification_status = sent`
- `notification_action_keys = ["proactive_ooda_packet_acceptance"]`
- `send_requested = true`
- `send_attempted = true`
- `send_result.reason = sent`

Meaning:

- the current action-required-only digest was sent successfully for the proactive approval outcome packet

### Operator action-required dedupe proof

File:

- `/docker/EA/.codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json`

Headline fields:

- `generated_at = 2026-07-06T06:04:06Z`
- `status = pass`
- `current_actions_covered_by_prior_state = true`
- `notification_mode_without_force = covered_by_previous_send`
- `source_state_fingerprint = ceb67093d7fcd779dd8c44d2bac6a7f972c4b3dea4a44e18327a927a82717fa3`

Meaning:

- a matching future digest for the same current action set will suppress cleanly as a duplicate

## What changed this session

### 1. Rebuilt the published receipt chain to a green state

Completed:

- operator status materialized and verified
- gold acceptance materialized and verified
- goal posture materialized and verified
- operator action-required digest sent and verified
- operator action-required dedupe proof materialized and verified

### 2. Proved current live approval followthrough

Completed:

- the operator action-required digest send path delivered one current Telegram approval-followthrough message
- gold acceptance now reflects that sent followthrough proof

### 3. Fixed assistant-grade fallback behavior when a live receipt path is explicit

Files:

- `scripts/materialize_proactive_ooda_operator_status.py`
- `tests/test_proactive_ooda_operator_status_materializer.py`

Change:

- assistant-grade fallback now still probes for a historical browse-backed packet even when `live_receipt_path` is explicitly supplied
- this keeps explicit runtime-receipt materialization from falling into a false `internal_action_not_assistant_grade` recovery state

Focused tests passed:

- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py -k 'explicit_live_receipt_still_uses_historical_browse_backed_packet or uses_historical_browse_backed_packet_for_assistant_grade or recovers_on_internal_action_packet'`

### 4. Tightened live receipt default-path coverage

Files:

- `scripts/verify_proactive_ooda_live_receipt.py`
- `tests/test_verify_proactive_ooda_live_receipt.py`

Change:

- added coverage for runtime-receipt preference logic and repo-state fallback behavior

Focused tests passed:

- `pytest -q tests/test_verify_proactive_ooda_live_receipt.py -k 'default_prefers_runtime_receipt_when_present or default_prefers_repo_state_when_env_is_unset or default_falls_back_to_state_sibling or default_prefers_runtime_receipt_env'`

## Current verification set

Passed:

- `python3 scripts/verify_proactive_ooda_operator_status.py --pretty`
- `python3 scripts/verify_proactive_ooda_gold_acceptance.py --pretty`
- `python3 scripts/verify_continuous_improvement_goal_posture.py --pretty`
- `python3 scripts/verify_operator_action_required_digest.py --pretty`
- `python3 scripts/verify_operator_action_required_dedupe_proof.py`

## Remaining real gap

The remaining gold blocker is now narrow and explicit:

- record the current redacted approval outcome for the proactive OODA packet

Secondary recovery still present:

- Google Workspace OAuth/source-health recovery

## Next slice

1. Audit whether the host-side local `state/proactive_ooda_latest_run.generated.json` should still exist as a default path or whether published/operator flows should prefer the runtime-container receipt source more directly.
2. Keep the current approval-outcome capture surface and digest/dedupe chain aligned while the approval outcome remains pending.
3. Once approval outcome evidence is recorded for the current packet, re-materialize the same receipt chain and confirm gold can move from `ready_for_approval_outcome_capture` to `pass`.

## Latest delta after approval-lane noise fix

Files:

- `ea/app/api/routes/proactive_ooda_approval_support.py`
- `ea/app/api/routes/landing.py`
- `ea/app/api/routes/landing_console_support.py`
- `ea/app/services/proactive_ooda_live_ops_bridge.py`
- `ea/app/services/proactive_ooda_runtime_artifacts.py`
- `ea/tests/test_proactive_ooda_approval_capture.py`
- `ea/tests/test_proactive_ooda_live_ops_bridge.py`

Change:

- internal operator/setup packets now fail closed out of the proactive approval lane
- the approval routes first ask whether the current packet actually needs explicit user approval via `current_packet_user_approval_surface(...)`
- if not, `/admin/proactive-ooda/approval` renders as `Nothing waiting for approval` and exposes the real blocker/action as a fallback operator action instead of a verdict form
- live-runtime probe bundles are normalized the same way, so a probe that reports `current_packet_live_pending_count=1` for a `record_internal_action` packet is rewritten to `0`

Current live proof after the fix:

- bundle source: `live_runtime`
- `current_packet_live_pending_count = 0`
- `current_packet_user_approval_surface = false`
- fallback operator action:
  - label: `Open Google setup`
  - href: `https://myexternalbrain.com/integrations/google`
  - instruction: open Google setup, confirm the work account is in Audience/test users, save, retry Full Workspace auth
- rendered approval surface summary:
  - `console_title = Nothing waiting for approval`
  - row 1 = `No live proactive approval packets are pending.`
  - row 2 = current blocker pointing at Google setup
  - `has_form = false`

Focused tests passed:

- `pytest -q tests/test_proactive_ooda_approval_capture.py tests/test_proactive_ooda_live_ops_bridge.py`
- `python3 -m py_compile app/api/routes/proactive_ooda_approval_support.py app/api/routes/landing.py app/api/routes/landing_console_support.py app/services/proactive_ooda_live_ops_bridge.py app/services/proactive_ooda_runtime_artifacts.py`

Why this matters:

- the approval lane now means real consent-gated work only
- operator/setup/OAuth recovery actions still stay visible, but as blockers/actions, not as things the user is asked to approve

## Latest delta after admin goal-lane stale approval cleanup

Files:

- `ea/app/api/routes/admin_view_models.py`
- `ea/tests/test_assistant_property_handoff_visibility.py`

Change:

- admin goal-card visibility now treats stale approval-capture receipts as non-actionable unless there is a real current live pending surface
- operator recovery rows can still appear when the operator receipt carries a real recovery action
- the `Proactive OODA approval outcome` row now appears only when the gold receipt exposes a real current verdict surface (`proactive_gold_verdict_available`)

Current live proof after the fix:

- published operator receipt:
  - `status = ready_with_recovery_action`
  - `next_action_label = Reconnect Google workspace`
- published gold receipt:
  - `status = blocked_operator_runtime_posture`
  - `approval_capture_surface.current_packet_user_action_required = false`
  - `approval_capture_surface.ready = false`
- rendered admin goals payload with the real receipts/runtime bundle now includes:
  - `Proactive delivery recovery` with action `Reconnect Google workspace`
- and no longer includes:
  - `Proactive OODA approval outcome`

Focused tests passed:

- `pytest -q tests/test_assistant_property_handoff_visibility.py tests/test_proactive_ooda_approval_capture.py tests/test_proactive_ooda_live_ops_bridge.py`

Why this matters:

- operator-facing admin surfaces no longer turn Google reauth or other internal-action recovery work into fake approval work
- the proactive OODA lane stays decision-ready and quieter across both the approval page and the admin goal cards

## Latest delta after admin runtime live-bundle alignment

Files:

- `ea/app/api/routes/admin_view_models.py`
- `ea/tests/test_assistant_property_handoff_visibility.py`

Change:

- admin goal-card runtime state now comes from `resolve_proactive_ooda_capture_bundle(...)` instead of host-only `load_runtime_artifact_bundle(...)`
- this aligns admin goals with the approval page and live operator receipts, so the bundle resolves from the same live runtime source when available

Current live proof after the fix:

- `admin_view_models._load_current_proactive_ooda_runtime_bundle()` now resolves:
  - `state_path = /data/provider-ledger/proactive_ooda_notified.json`
  - `run_receipt_path = /data/provider-ledger/proactive_ooda_run_receipts/20260706T065050_040737_0000-sent-22f3340094f0.json`
  - `current_packet_live_pending_count = 0`
  - `stage_packet_ref = stage_packet:proactive-ooda-stage-0cd3cd8941183292666eab3d`
- rendered admin goals payload with real receipts/runtime still shows only:
  - `Proactive delivery recovery`
  - action label `Reconnect Google workspace`
- and no `Proactive OODA approval outcome` row

Focused tests passed:

- `pytest -q tests/test_assistant_property_handoff_visibility.py tests/test_proactive_ooda_approval_capture.py tests/test_proactive_ooda_live_ops_bridge.py`
- result: `32 passed`

Why this matters:

- operator-facing proactive state now comes from one live-truth resolver instead of splitting between `/data/provider-ledger` and stale host-local `/docker/EA/state`
- the next real blocker remains source-health recovery, not stale approval semantics

## Guardrails

- Do not revert unrelated worktree changes.
- Do not treat the Google Workspace recovery item as higher priority than the current approval-outcome capture gate when the packet itself is already in approval followthrough.
- Do not mark the goal complete or blocked.

## Latest delta after operator-status live artifact alignment

Files:

- `scripts/materialize_proactive_ooda_operator_status.py`
- `tests/test_proactive_ooda_operator_status_materializer.py`

Change:

- the root operator-status materializer no longer forces a host-local artifact bundle after a live route probe
- when the materializer is already using live route posture and there are no explicit local artifact dir overrides, it now allows `_local_artifact_probe(...)` to resolve through `resolve_proactive_ooda_capture_bundle(...)` against the live runtime artifact source first
- explicit `stage_packet_dir` or `safe_work_result_dir` overrides still keep the local artifact path authoritative

Focused tests passed:

- `pytest -q ../tests/test_proactive_ooda_operator_status_materializer.py -k 'projects_provider_cost_pressure or keeps_explicit_artifact_dirs_on_local_probe'`
- `pytest -q tests/test_assistant_property_handoff_visibility.py tests/test_proactive_ooda_approval_capture.py tests/test_proactive_ooda_live_ops_bridge.py tests/test_proactive_gold_source_coverage.py`

Current generated artifact proof after refresh:

- operator receipt: `.codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - `status = ready_with_live_receipt`
  - `next_action = maintain_proactive_ooda_runtime`
  - `safe_work_audit.source = in_process_runtime`
  - `approval_capture_surface.source = in_process_runtime`
  - `approval_capture_surface.current_packet_approval_request_recordable = false`
  - `approval_capture_surface.current_packet_user_action_required = false`
- gold receipt: `.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = ready_for_approval_outcome_capture`
  - `evidence_receipts.approval_capture_surface.current_packet_approval_request_recordable = false`
  - `evidence_receipts.approval_capture_surface.current_packet_user_action_required = false`
  - `proofs.approval_capture_readiness.current_packet_approval_request_recordable = false`

Why this matters:

- the generated operator-status receipt now agrees with the same live artifact resolver used by the approval page and admin runtime bundle instead of drifting back to stale host-local `/docker/EA/state` artifacts
- stale approval noise is removed at the receipt level, not just the UI layer

Remaining seam:

- the gold receipt still uses `next_action = record_proactive_ooda_approval_outcome` for meta proof capture even when `current_packet_user_action_required = false`
- that is now mostly hidden from user-facing admin surfaces, but it still exists in the receipt and in downstream posture/verifier logic
- if you continue this lane, the next slice is to separate operator proof-capture follow-up from user-action-required approval semantics without breaking `continuous_improvement_goal_posture`, `verify_proactive_ooda_gold_acceptance`, or `materialize_operator_action_required_digest`

## Latest delta after Telegram action-required delivery revalidation

Files changed:

- no code-path changes this slice
- refreshed receipts/state:
  - `.codex-studio/published/ea_operator_action_required_digest.generated.json`
  - `.runtime/ea_operator_action_required_digest_state.json`

Live findings:

- the previous `blocked_telegram_send_failed` digest receipt was stale
- current live probes show:
  - `probe-telegram-readiness` => `status=ready`
  - principal resolved to `cf-email:tibor.girschele@gmail.com`
  - bot token present
  - chat ref present
  - runtime container = `ea-api`
- runtime setup-only probe inside `ea-api` confirmed:
  - connector binding resolves
  - chat ref resolves
  - bot token resolves
- safe non-mutating Telegram API probes inside `ea-api` confirmed:
  - `getMe` works
  - `getChat` works for the bound private chat

Live proof after revalidation:

- `python3 ../scripts/materialize_operator_action_required_digest.py --dry-run --send --principal-id 'cf-email:tibor.girschele@gmail.com'`
  - `status = ready_to_send`
  - `notification_status = dry_run_ready`
  - `send_result.reason = dry_run`
  - `send_result.ready = true`
- `python3 ../scripts/materialize_operator_action_required_digest.py --send --principal-id 'cf-email:tibor.girschele@gmail.com'`
  - `status = sent`
  - `notification_status = sent`
  - `send_result.sent = true`
  - `send_result.message_count = 1`
  - state file now records:
    - `last_sent_at = 2026-07-06T11:04:05Z`
    - `message_id_count = 1`

Focused verification passed:

- `python3 ../scripts/verify_operator_action_required_digest.py`
  - `status = pass`
- `pytest -q ../tests/test_operator_action_required_digest.py -k 'sent or dry_run_ready or dedupe'`
  - `2 passed`

Why this matters:

- action-required-only Telegram delivery now has fresh live proof instead of an older failed receipt
- the proactive loop can actually reach the operator on Telegram for real setup blockers again
- the queue-only proactive gold meta-verdict item remains suppressed from push delivery; only the real Google setup blocker was sent

## Latest delta after continuous-goal provider-cost-pressure fallback repair

Files changed:

- `scripts/materialize_continuous_improvement_goal_posture.py`
- `tests/test_continuous_improvement_goal_posture.py`
- `ea/app/api/routes/proactive_ooda_approval_support.py`
- `ea/tests/test_proactive_ooda_approval_capture.py`

What changed:

- the `/admin/proactive-ooda/approval` empty state was clarified so it now says there is nothing to approve and points at the actual blocker instead of implying a consent action exists
- `materialize_continuous_improvement_goal_posture.py` now probes live provider-cost pressure when the mirrored proactive-operator receipt is present but still unprobed or incomplete
- the decide lens now truthfully projects:
  - `provider_cost_pressure.checked = true`
  - `provider_cost_pressure.status = active_cost_control`
  - `provider_cost_pressure.primary_background_provider = onemin`
  - `provider_cost_pressure.provider_order = ["onemin", "magixai", "gemini_vortex"]`
  - `provider_cost_pressure.gemini_background_cost_gate = open`
  - `provider_cost_pressure.explicit_gemini_requests_allowed = true`
- added a regression proving the continuous-goal materializer prefers the live provider-cost probe when the proactive-operator receipt still says `not_checked`

Current live proof:

- `python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json`
  - `status = active_cost_control`
  - `primary_background_provider = onemin`
  - `provider_order = ["onemin", "magixai", "gemini_vortex"]`
  - `gemini_token_tracking.background_cost_gate = open`
  - `gemini_token_tracking.explicit_gemini_requests_allowed = true`
- `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - refreshed `.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
- `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt .codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `status = pass`
- `pytest -q tests/test_continuous_improvement_goal_posture.py -k 'provider_cost_probe_when_operator_status_is_unchecked or emits_required_lenses_and_conservative_claims'`
  - `2 passed`

Why this matters:

- the long-running continuous-improvement posture no longer emits stale/noise provider-cost pressure after the user asked for 1min.ai-first routing and Gemini fallback
- live verifier proof now agrees with the runtime provider-cost probe instead of waiting for the heavier proactive-operator materializer path to refresh first

Remaining seam:

- `ea_proactive_ooda_operator_status.generated.json` can still publish `provider_cost_pressure.status = not_checked` when the full operator-status materializer falls back before its cost probe finishes
- the continuous-goal posture is now robust against that, but the cleaner long-term fix is still to make `materialize_proactive_ooda_operator_status.py` refresh its provider-cost-pressure slice reliably even when other live probes degrade

## Latest delta after operator-status explicit-live-receipt provider-cost backfill

Files changed:

- `scripts/materialize_proactive_ooda_operator_status.py`
- `tests/test_proactive_ooda_operator_status_materializer.py`

What changed:

- `build_proactive_ooda_operator_status()` now backfills `provider_cost_pressure` directly when the main live-probe bundle leaves it empty
- this specifically fixes the admin/runtime materialization shape where an explicit `live_receipt_path` is supplied: that path previously skipped the provider-cost probe even with `skip_provider_cost_pressure_probe=False`
- added a regression proving the explicit-live-receipt path now projects checked provider-cost pressure instead of `not_checked`

Current live proof:

- before the fix, published `.codex-studio/published/ea_proactive_ooda_operator_status.generated.json` had:
  - `provider_cost_pressure.checked = false`
  - `provider_cost_pressure.status = not_checked`
  - empty provider order / missing `primary_background_provider`
- after:
  - `python3 scripts/materialize_proactive_ooda_operator_status.py --receipt-path /docker/EA/ea/state/proactive_ooda_latest_run.generated.json`
  - published receipt now has:
    - `provider_cost_pressure.checked = true`
    - `provider_cost_pressure.probe_ok = true`
    - `provider_cost_pressure.status = active_cost_control`
    - `provider_cost_pressure.source = runtime_container_exec:ea-api:provider_ledger_cache`
    - `provider_cost_pressure.primary_background_provider = onemin`
    - full provider order `["onemin", "magixai", "gemini_vortex"]`
    - Gemini token tracking boundary and background gate populated
- `python3 scripts/verify_proactive_ooda_operator_status.py --receipt .codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - `status = pass`
- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py -k 'projects_provider_cost_pressure or backfills_provider_cost_pressure_with_explicit_live_receipt_path or keeps_running_when_onemin_probe_is_pending or recovers_on_provider_cost_misconfiguration'`
  - `4 passed`
- `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
- `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt .codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `status = pass`

Why this matters:

- the lower-level proactive operator-status receipt now stays truthful about 1min.ai-first cost routing on the same admin path that writes the published runtime artifacts
- the higher-level continuous-goal posture no longer has to compensate for that specific production path drifting to `not_checked`

## Latest delta after proactive source-coverage fallback-noise suppression

Files changed:

- `scripts/ea_live_ops.py`
- `tests/test_ea_live_ops.py`

What changed:

- the in-process proactive source-coverage probe now suppresses only the specific `ea.container` warning:
  - `postgres runtime profile unavailable, switching whole container to memory: ...`
- behavior did not change:
  - if in-process Postgres is usable, the probe still uses it
  - if not, the probe still falls back to Docker/runtime exec
- the change only removes false-alarm operator noise on the successful fallback path

Current live proof:

- `pytest -q tests/test_ea_live_ops.py -k 'probe_proactive_source_coverage_falls_back_to_docker_when_in_process_errors or suppresses_container_fallback_warning or prefers_in_process_when_database_url_present'`
  - `3 passed`
- `python3 scripts/ea_live_ops.py probe-proactive-source-coverage --format json`
  - returns `status = ready`
  - `observed_lane_count = 8`
  - `missing_lane_keys = []`
  - no prefixed Postgres fallback warning noise was emitted before the JSON payload
- `python3 scripts/verify_proactive_ooda_operator_status.py --receipt .codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - `status = pass`

Why this matters:

- operator-safe live checks are now quieter and more trustworthy
- the proactive OODA runtime can still use a Docker-backed truth path when local Postgres wiring is unavailable, without presenting that fallback as an alarming runtime failure when the probe still succeeds

## Latest delta after approval-lane stale-verdict suppression for non-approval packets

Files changed:

- `ea/app/api/routes/landing_console_support.py`
- `ea/app/api/routes/landing.py`
- `tests/test_admin_surface_runtime_contracts.py`

What changed:

- the admin/app proactive approval route now clears saved approval-history state when the current packet is not a real approval candidate
- concrete rule:
  - if `current_packet_user_approval_surface(...)` is false and `current_packet_live_pending_count == 0`, the route suppresses:
    - stale saved approval verdict projection
    - stale approval status/source metadata
- this keeps the page in the correct mode:
  - `Nothing to approve`
  - show only the actual operator action, if any
  - do not leak older packet verdicts into the current lane

Current live proof:

- live artifact probe currently resolves:
  - `stage_kind = internal_action`
  - `work_type = record_internal_action`
  - `requires_user_approval = false`
  - `approval_surface_pending = false`
  - `stale_saved_approval_outcome_visible_after_patch = false`
- command used:
  - small Python snippet calling `resolve_proactive_ooda_capture_bundle(...)` + `current_packet_user_approval_surface(...)`
- targeted tests:
  - `pytest -q tests/test_admin_surface_runtime_contracts.py -k 'marks_mismatched_saved_approval_as_stale or hides_stale_saved_verdict_for_internal_action_packet or points_to_current_operator_action_when_lane_is_clear'`
    - `3 passed`
  - `pytest -q ea/tests/test_proactive_ooda_approval_capture.py`
    - `6 passed`
- `python3 -m py_compile ea/app/api/routes/landing_console_support.py ea/app/api/routes/landing.py tests/test_admin_surface_runtime_contracts.py`
  - pass

Why this matters:

- `/admin/proactive-ooda/approval` stops behaving like a junk drawer for stale packet history
- internal actions and low-value research packets no longer masquerade as things the user should approve
- the page now matches the intended operator model:
  - real consent-gated packet => approval lane
  - otherwise => no approval, maybe an operator action elsewhere

## Latest delta after explicit-live-receipt route recovery in operator-status materialization

Files changed:

- `scripts/materialize_proactive_ooda_operator_status.py`
- `tests/test_proactive_ooda_operator_status_materializer.py`

What changed:

- `build_proactive_ooda_operator_status()` now retries the proactive route probe without a pinned receipt path when:
  - a configured/explicit live receipt path was supplied, and
  - the pinned route probe came back `probe_ok=true` but `live_receipt.errors` included `receipt_missing`
- the retry is only adopted when it produces stronger live-receipt truth
  - current scoring prefers `live_receipt.ok`, archived sent-receipt recovery, sent notification status, and followthrough presence
- this fixes the production seam where the published operator-status receipt was degraded by the stale host `state/proactive_ooda_latest_run.generated.json` path even though the runtime could already prove a richer archived sent receipt

Current live proof:

- direct runtime comparison now reproduces the seam cleanly:
  - `python3 scripts/ea_live_ops.py probe-proactive-route --format json`
    - `live_receipt.ok = true`
    - `archived_sent_receipt_used = true`
    - `receipt_path = /data/provider-ledger/proactive_ooda_run_receipts/20260706T065050_040737_0000-sent-22f3340094f0.json`
    - `followthrough_status = ok`
  - `python3 scripts/ea_live_ops.py probe-proactive-route --format json --receipt-path /docker/EA/ea/state/proactive_ooda_latest_run.generated.json`
    - `live_receipt.ok = false`
    - `errors = ["receipt_missing"]`
- instrumented build of `build_proactive_ooda_operator_status(...)` with the explicit host receipt path now performs two route probes:
  - first with the pinned host receipt path
  - second unpinned, which resolves the archived sent receipt
  - final in-memory receipt lands on:
    - `status = ready_with_live_receipt`
    - `reason = ready`
    - `route_probe_source = docker_compose_exec`
    - `live_receipt.archived_sent_receipt_used = true`

Targeted tests:

- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py -k 'uses_live_route_probe_with_explicit_receipt_path or fills_missing_live_receipt_path_from_route_probe or recovers_from_explicit_missing_receipt_via_unpinned_route_probe or does_not_force_host_fallback_receipt_path_into_live_route_probe'`
  - `4 passed`
- `python3 -m py_compile scripts/materialize_proactive_ooda_operator_status.py tests/test_proactive_ooda_operator_status_materializer.py`
  - pass

Published artifact proof after refresh:

- `python3 scripts/materialize_proactive_ooda_operator_status.py --receipt-path /docker/EA/ea/state/proactive_ooda_latest_run.generated.json`
- `python3 scripts/verify_proactive_ooda_operator_status.py --receipt .codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - `status = pass`
- refreshed operator-status receipt now shows:
  - `status = ready_with_live_receipt`
  - `reason = ready`
  - `summary = Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.`
  - `live_receipt.ok = true`
  - `live_receipt.archived_sent_receipt_used = true`
  - `provider_cost_pressure.status = active_cost_control`
  - `provider_cost_pressure.primary_background_provider = onemin`
  - `source_health.status = clear`

Downstream artifact refresh:

- `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
- `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
- `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt .codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `status = pass`
- `python3 scripts/verify_proactive_ooda_gold_acceptance.py --receipt .codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = pass`

Current artifact posture:

- `ea_proactive_ooda_operator_status.generated.json`
  - `status = ready_with_live_receipt`
- `ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = ready_for_approval_outcome_capture`
  - `next_action = record_proactive_ooda_approval_outcome`
- `ea_continuous_improvement_goal_posture.generated.json`
  - still `active_with_blockers`
  - current top blocker remains `google_workspace_oauth_setup`
  - this now looks like the next real lane to audit, not a stale receipt-path artifact problem

## Latest delta after no-pending approval page cleanup

User reported `/admin/proactive-ooda/approval` as noise and asked what they actually need to approve.

Current truth from generated receipts:

- there is no live proactive OODA packet requiring explicit approval
- the actual head operator action is `Retry Google auth`
- current action URL is `/integrations/google`
- current missing setup is `oauth_access_retry_or_account_selection_required`
- later action-required items include the Elisabeth Pushbullet token and weekly signal-loop review, but they are not approval-page decisions

Files changed:

- `ea/app/api/routes/proactive_ooda_approval_support.py`
- `ea/tests/test_proactive_ooda_approval_capture.py`

What changed:

- `_no_pending_approval_surface()` now leads with the real operator action when there is no live approval packet.
- The no-pending branch now says:
  - `console_title = Nothing to approve`
  - `object_ooda_title = Actual action needed`
  - first row title `Do this`
  - first row tag `Retry Google auth`
  - first row href `/integrations/google`
  - second row says the approval state is clear
- The sidebar form remains empty, so there is no fake verdict/approval form when nothing is pending.

Preview generated from current artifacts:

```json
{
  "pending": false,
  "requires": false,
  "console_title": "Nothing to approve",
  "object_ooda_title": "Actual action needed",
  "object_ooda_rows": [
    {
      "title": "Do this",
      "detail": "Google Workspace auth needs reauthorization before EA can rely on that source. Retry the Full Workspace auth link with the approved work Google account.",
      "tag": "Retry Google auth",
      "href": "/integrations/google"
    },
    {
      "title": "Approval state",
      "detail": "Nothing needs approval on this page right now.",
      "tag": "Clear"
    }
  ],
  "object_sidebar_form": {}
}
```

Verification:

- `pytest -q tests/test_proactive_ooda_approval_capture.py`
  - `7 passed`
- `pytest -q tests/test_assistant_property_handoff_visibility.py tests/test_proactive_ooda_runtime_artifacts.py`
  - `25 passed`

Do not regress this back to treating setup recovery, stale callbacks, or internal reminders as approval-lane decisions.

## Latest delta after gold next-action cleanup

Gold receipt was still falling back to `repair_proactive_approval_capture` with the generic `Open goals` surface when the selected current packet had no approval capture to perform.

Current receipt truth after refresh:

- `ea_proactive_ooda_gold_acceptance.generated.json`
  - `status = blocked_missing_proactive_packet_evidence`
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `next_action_href = https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace`
- gold `approval_capture_readiness`
  - `present = true`
  - `required = false`
  - `current_packet_approval_request_recordable = false`
  - `manual_outcome_capture_ready = false`
  - `telegram_approval_surface_ready = false`
- gold `operator_runtime_posture`
  - `status = pass`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `next_action = reauthorize_google_workspace_binding`

Files changed:

- `scripts/materialize_proactive_ooda_gold_acceptance.py`
- `ea/tests/test_proactive_gold_source_coverage.py`

What changed:

- `_operator_runtime_next_action()` now keeps a concrete operator recovery action when the operator-status source snapshot is stale but the receipt has a clear recovery action, especially Google Workspace reauth.
- `_next_action()` now accepts `approval_capture_required`.
- When no approval outcome exists but the current packet is not recordable and no approval capture is required, gold no longer emits `repair_proactive_approval_capture`.
  - If a concrete operator recovery action exists, gold surfaces it.
  - Otherwise gold asks for `stage_fresh_assistant_grade_proactive_packet`.

Verification:

- `python3 -m py_compile /docker/EA/scripts/materialize_proactive_ooda_gold_acceptance.py tests/test_proactive_gold_source_coverage.py`
  - pass
- `pytest -q tests/test_proactive_gold_source_coverage.py`
  - `33 passed`
- refreshed:
  - `python3 scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 scripts/materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `python3 scripts/materialize_operator_action_required_dedupe_proof.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
- verified:
  - `python3 scripts/verify_proactive_ooda_operator_status.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json`
  - `python3 scripts/verify_proactive_ooda_gold_acceptance.py --receipt /docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`
  - `python3 scripts/verify_continuous_improvement_goal_posture.py --receipt /docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`
  - `python3 scripts/verify_operator_action_required_digest.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_digest.generated.json`
  - `python3 scripts/verify_operator_action_required_dedupe_proof.py --receipt /docker/EA/.codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json`
  - all returned `status = pass`

Current remaining operator blockers:

- Google Workspace reauth is still the head user action.
- Pushbullet client token for Elisabeth is still missing.
- Weekly signal-to-decision review acceptance still needs a real redacted review receipt.

## Latest delta after action-required clarity and Pushbullet env hints

User asked again what they actually need to approve on `/admin/proactive-ooda/approval`.

Current live answer from receipts:

- There is nothing to approve on `/admin/proactive-ooda/approval` right now.
- Head action is Google Workspace recovery:
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `next_action_href = https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace`
- Continuous-improvement goal posture still has the operator-facing head as:
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_label = Retry Google auth`
  - `next_action_href = /integrations/google`
- Pushbullet setup is secondary, not an approval:
  - missing client key: `elisabeth`
  - env var to configure: `PB_TOKEN_ELISABETH`
- Action-required digest is suppressed as duplicate:
  - `notification_status = suppressed_duplicate`
  - `notification_mode = covered_by_previous_send`
  - `notification_item_count = 0`
  - no Telegram send attempted during this refresh.

Files changed in this slice:

- `scripts/materialize_continuous_improvement_goal_posture.py`
  - Pushbullet action context now carries `pushbullet_missing_token_envs`, resolving `elisabeth` to `PB_TOKEN_ELISABETH`.
  - Telegram/action text now says `Missing token env: PB_TOKEN_ELISABETH.` without exposing a token or email.
- `scripts/materialize_operator_action_required_digest.py`
  - sanitizer/digest material now preserves Pushbullet token-env hints and includes them in material hashes.
  - Telegram text would include `Env: PB_TOKEN_ELISABETH` only when that item is actually sent.
- `scripts/materialize_operator_action_required_dedupe_proof.py`
  - dedupe proof now passes when digest notification is suppressed by policy as `covered_by_previous_send`, even if tail material changed due a clarification hint.
  - Still fails closed for legacy key-only stale state by requiring current per-item hash state for the suppression-drift pass.
- `scripts/verify_proactive_ooda_operator_status.py`
  - verifier now treats `followthrough_*` recovery reasons like Google/source-health recovery: they do not require `delivery_route_error`.
- Tests updated:
  - `tests/test_continuous_improvement_goal_posture.py`
  - `tests/test_operator_action_required_digest.py`
  - `tests/test_operator_action_required_dedupe_proof.py`
  - `tests/test_proactive_ooda_operator_status_verifier.py`

Verification after refresh:

- `pytest -q /docker/EA/tests/test_continuous_improvement_goal_posture.py /docker/EA/tests/test_operator_action_required_digest.py`
  - `54 passed`
- `pytest -q /docker/EA/tests/test_continuous_improvement_goal_posture.py /docker/EA/tests/test_operator_action_required_digest.py /docker/EA/tests/test_operator_action_required_dedupe_proof.py`
  - `58 passed`
- `pytest -q /docker/EA/tests/test_proactive_ooda_operator_status_verifier.py`
  - `13 passed`
- Receipt/verifier chain refreshed and all passed:
  - `materialize_proactive_ooda_operator_status.py`
  - `materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `materialize_operator_action_required_dedupe_proof.py`
  - `materialize_proactive_ooda_gold_acceptance.py`
  - `verify_proactive_ooda_operator_status.py`
  - `verify_continuous_improvement_goal_posture.py`
  - `verify_operator_action_required_digest.py`
  - `verify_operator_action_required_dedupe_proof.py`
  - `verify_proactive_ooda_gold_acceptance.py`
  - all returned pass.

Do not make `/admin/proactive-ooda/approval` a generic queue. It is only for real consent-gated packet approvals. Current next user-facing action is Google reauth, not approving a packet.

## Latest delta after browser operator-scope redirect hardening

Continued the same gold-production OODA goal after the approval-noise fix. The next local hardening gap was the raw browser error the user previously saw:

```json
{"error":{"code":"operator_scope_required", ...}}
```

This is not acceptable for human action-required links, especially the current weekly signal-to-decision evidence link.

Files changed:

- `ea/app/api/errors.py`
  - Added a browser-only `operator_scope_required` redirect path for admin/app document GET/HEAD requests.
  - Preserves API behavior: non-HTML/API-style requests still receive structured JSON errors.
  - Preserves property-surface boundary handling.
  - Redirects authenticated principals with no active operator profile to `/admin/bootstrap-operator?return_to=...`.
  - Redirects other browser operator-scope failures to `/sign-in?return_to=...`.
  - Preserves query strings in `return_to`, so links like `/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review` return to the exact form after bootstrap/sign-in.
- `tests/test_api_error_logging.py`
  - Added regression coverage for browser GET redirecting to operator bootstrap.
  - Added regression coverage proving API-style requests still return JSON `operator_scope_required`.

Verification:

- `python3 -m py_compile ea/app/api/errors.py tests/test_api_error_logging.py`
  - pass
- `pytest -q tests/test_api_error_logging.py tests/test_admin_surface_runtime_contracts.py -k 'operator_scope or bootstrap_operator or admin_action_get_redirects or admin_surface_redirects_principal_session'`
  - `7 passed, 23 deselected`
- Refreshed and verified receipts:
  - `python3 scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 scripts/materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `python3 scripts/materialize_operator_action_required_dedupe_proof.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
  - all five verifiers passed:
    - operator status
    - continuous-improvement goal posture
    - operator action-required digest
    - operator action-required dedupe proof
    - proactive OODA gold acceptance

Current receipt truth after refresh:

- Goal posture: `active_with_blockers`, head action `Retry Google auth` at `/integrations/google`.
- Operator status: `ready_with_recovery_action`, reason `source_health_google_workspace:google_oauth_invalid_grant`, action `Reconnect Google workspace`.
- Gold: `blocked_missing_proactive_packet_evidence`, action `Reconnect Google workspace`.
- Digest: `suppressed_duplicate`, `notification_mode = covered_by_previous_send`, `notification_item_count = 0`.

Remaining blockers are unchanged:

- Google Workspace OAuth reauth still needs the user.
- Pushbullet Elisabeth still needs `PB_TOKEN_ELISABETH`.
- Weekly signal-to-decision review still needs real redacted review evidence, but its browser link should no longer dead-end as raw `operator_scope_required` JSON.

## Latest delta after weekly action text and source-health precedence hardening

Continued the same gold-production OODA goal. Two local operator-noise issues were fixed.

### 1. Weekly signal review action now has real Telegram text

Problem:

- `weekly_signal_to_decision_review_acceptance` was action-digest eligible but had an empty `telegram_message`.
- If that item ever became the notified item, EA could send a blank/vague action line instead of a concrete request.

Files changed:

- `scripts/materialize_continuous_improvement_goal_posture.py`
  - `_signal_review_action_context(...)` now preserves packet-provided `telegram_message` or emits a concise default:
    - review: `Action needed: record that you reviewed the weekly signal-to-decision packet. Open the evidence form and save a short redacted review note.`
    - followthrough: `Action needed: record the signal-to-decision follow-through outcome. Open the evidence form and save a short redacted outcome note.`
- `tests/test_continuous_improvement_goal_posture.py`
  - Added regression assertions that the weekly queue row has non-empty action-needed Telegram text.

Verification:

- `python3 -m py_compile scripts/materialize_continuous_improvement_goal_posture.py tests/test_continuous_improvement_goal_posture.py`
  - pass
- `pytest -q tests/test_continuous_improvement_goal_posture.py -k 'required_lenses or action_required_digest or signal_to_decision'`
  - `1 passed, 32 deselected`
- `pytest -q tests/test_continuous_improvement_goal_posture.py tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py`
  - `58 passed`

Current refreshed digest confirms:

- weekly goal/digest `telegram_message` is non-empty and concise.
- digest remains `suppressed_duplicate`, `notification_mode = covered_by_previous_send`, `notification_item_count = 0`.
- no Telegram resend happened.

### 2. Source-health recovery wins over generic follow-through repair

Problem:

- A refreshed live operator receipt had both:
  - `followthrough_artifacts_missing`
  - Google Workspace source-health issue with concrete recovery `reauthorize_google_workspace_binding`
- Operator/gold briefly surfaced the generic `repair_proactive_operator_runtime_posture` / `Open goals`, which reintroduced vague operator noise.

Files changed:

- `scripts/materialize_proactive_ooda_operator_status.py`
  - Added `_source_health_recovery_candidate_status(...)`.
  - Source-health recovery can now override a soft `followthrough_*` recovery state, but still leaves real approval follow-through and hard blockers alone.
- `scripts/materialize_proactive_ooda_gold_acceptance.py`
  - `_concrete_operator_recovery_action(...)` now falls back to concrete `source_health.issues[*].next_action` when the operator receipt itself still has a generic repair action.
- `tests/test_proactive_ooda_operator_status_materializer.py`
  - Added regression for `followthrough_artifacts_missing` plus Google source-health next action.
- `tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - Added regression for source-health issue next action beating generic follow-through repair.

Focused verification:

- `python3 -m py_compile scripts/materialize_proactive_ooda_operator_status.py scripts/materialize_proactive_ooda_gold_acceptance.py tests/test_proactive_ooda_operator_status_materializer.py tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - pass
- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py -k 'prefers_source_health_over_followthrough_repair or prioritizes_approval_followthrough_over_workspace_reauth' -vv`
  - new regression passed
  - existing `prioritizes_approval_followthrough_over_workspace_reauth` still failed; this appears to be part of an older approval-surface regression set, not introduced by the source-health precedence change.
- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py -k 'source_health or followthrough_repair'`
  - `2 passed, 46 deselected`
- `pytest -q tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'source_health_recovery_action or concrete_operator_recovery_action'`
  - `2 passed, 38 deselected`

Broad affected-suite note:

- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py tests/test_proactive_ooda_operator_status_verifier.py tests/test_proactive_ooda_gold_acceptance_materializer.py tests/test_proactive_ooda_gold_acceptance_verifier.py tests/test_continuous_improvement_goal_posture.py tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py`
  - `162 passed`, `15 failed`.
  - Failures cluster around older approval-surface/current-artifact expectations, for example:
    - filtered current artifact not recorded
    - internal-action packet recovery not active
    - pending approval capture surface not ready
    - expired current-packet callback hygiene
    - approval follow-through versus workspace reauth priority
  - Do not treat those failures as resolved; they need a separate approval-surface cleanup slice.

Final receipt refresh after this slice:

- `python3 scripts/materialize_proactive_ooda_operator_status.py`
- `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
- `python3 scripts/materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
- `python3 scripts/materialize_operator_action_required_dedupe_proof.py`
- `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
- Verifiers all passed:
  - operator status
  - continuous-improvement goal posture
  - operator action-required digest
  - operator action-required dedupe proof
  - proactive OODA gold acceptance

Current receipt truth after final refresh:

- Operator status:
  - `status = ready_with_recovery_action`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
- Gold:
  - `status = blocked_missing_proactive_packet_evidence`
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
- Goal posture:
  - `status = active_with_blockers`
  - `next_action = retry_full_workspace_auth_with_approved_account`
  - `next_action_label = Retry Google auth`
- Digest:
  - `status = suppressed_duplicate`
  - `notification_status = suppressed_duplicate`
  - `notification_mode = covered_by_previous_send`
  - `notification_item_count = 0`

## Latest delta: approval page no longer asks the operator to interpret an empty approval lane

User complaint:

- `/admin/proactive-ooda/approval` was perceived as noise because it was not clear what, if anything, should be approved.

Runtime truth at inspection time:

- `current_packet_live_pending_count = 0`
- `current_packet_user_action_required = false`
- No consent-gated proactive packet approval is pending.
- The real operator action is Google Workspace auth recovery:
  - goal/action label: `Retry Google auth`
  - operator/gold label: `Reconnect Google workspace`
  - current route target: `/integrations/google` or full workspace auth link, depending on surface

Files changed in this slice:

- `ea/app/api/routes/proactive_ooda_approval_support.py`
  - Empty approval state now renders `Action needed, not approval` when a concrete fallback action exists.
  - The page title now leads with `Do this instead: <action>`.
  - The OODA row says `No proactive packet needs approval right now.`
  - The sidebar says `Action, not approval` and does not render a verdict form.
- `ea/tests/test_proactive_ooda_approval_capture.py`
  - Updated no-pending approval assertions to lock the action-not-approval state.

Verification:

- `python3 -m py_compile app/api/routes/proactive_ooda_approval_support.py tests/test_proactive_ooda_approval_capture.py`
  - pass
- `pytest -q tests/test_proactive_ooda_approval_capture.py`
  - `7 passed`
- `pytest -q tests/test_assistant_property_handoff_visibility.py -k 'approval_outcome or operator_recovery_visible or proactive'`
  - `6 passed, 11 deselected`

Important repo note:

- From repo root `/docker/EA`, these two files currently appear untracked:
  - `ea/app/api/routes/proactive_ooda_approval_support.py`
  - `ea/tests/test_proactive_ooda_approval_capture.py`
- They are imported and used by the live route code, so do not delete them. Decide later whether to add them to the repo or fold the helpers/tests back into tracked files.

## Latest delta: approval capture now distinguishes current user action from proof history

User asked what they should actually approve on `/admin/proactive-ooda/approval`.

Direct answer for the current runtime:

- Nothing is waiting for approval on that page.
- The current user action is `Reconnect Google workspace`.
- Current operator receipt:
  - `status = ready_with_recovery_action`
  - `reason = source_health_google_workspace:google_oauth_invalid_grant`
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `next_action_href = https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace`
- Current gold receipt:
  - `status = blocked_missing_proactive_packet_evidence`
  - `selected_bundle_source = historical_browse_backed_proof_bundle`
  - `next_action = reauthorize_google_workspace_binding`
  - `next_action_label = Reconnect Google workspace`
  - `approval_capture_readiness_present = true`
  - `approval_capture_readiness_ready = false`
  - `approval_capture_surface_ready = false`

Implementation changes in this slice:

- `scripts/materialize_proactive_ooda_operator_status.py`
  - Artifact probe scoring now prefers real current evidence over bare host/internal-action retries.
  - Historical assistant-grade fallback is allowed only with explicit fallback permission or a current run receipt path.
  - Approval followthrough can take precedence over soft source-health recovery only when the live receipt and approval surface are actually ready.
- `ea/app/services/proactive_ooda_live_ops_bridge.py`
  - Runtime callback counts are preserved for real current packets.
  - Current pending callback counts are zeroed only for explicit internal/setup packets, not merely because an artifact has no prompt text.
- `scripts/materialize_proactive_ooda_gold_acceptance.py`
  - Explicit local artifact inputs now stop implicit live-runtime probing unless `--live-runtime-probe` is passed.
  - Approval-capture readiness now means usable for the selected current packet, not just a generic capture probe somewhere.
  - Historical browse-proof bundles, mirrored deliveries, stale/invalid saved outcomes, and saved Gmail-draft proofs without a usable capture surface no longer route the user to `/admin/proactive-ooda/approval`.
  - Expired pending callbacks still block and request cleanup.
  - Already approved/rejected callback decisions remain valid after their old button expiry.
  - Legacy ready operator-status receipts without source stamps are accepted in the focused historical tests, while stamped receipts still have to match current source state.
- `tests/test_proactive_ooda_gold_acceptance_materializer.py`
  - Updated expectations so only real current approval-capture surfaces route to `/admin/proactive-ooda/approval`.
  - Historical proof and broken capture cases route to queue or repair actions instead of blind approval.

Verification after final source changes:

- `pytest -q tests/test_proactive_ooda_operator_status_materializer.py tests/test_proactive_ooda_operator_status_verifier.py`
  - `61 passed`
- `pytest -q tests/test_proactive_ooda_gold_acceptance_materializer.py tests/test_proactive_ooda_gold_acceptance_verifier.py`
  - `58 passed`
- `pytest -q tests/test_continuous_improvement_goal_posture.py tests/test_operator_action_required_digest.py tests/test_operator_action_required_dedupe_proof.py -k 'action_required or dedupe or google or goal or proactive'`
  - `58 passed`
- `cd ea && pytest -q tests/test_proactive_ooda_approval_capture.py tests/test_assistant_property_handoff_visibility.py -k 'approval_outcome or operator_recovery_visible or proactive'`
  - `13 passed, 11 deselected`
- Receipt materializers rerun sequentially:
  - `python3 scripts/materialize_proactive_ooda_operator_status.py`
  - `python3 scripts/materialize_continuous_improvement_goal_posture.py --root /docker/EA`
  - `python3 scripts/materialize_operator_action_required_digest.py --no-refresh-source --timeout-seconds 20`
  - `python3 scripts/materialize_operator_action_required_dedupe_proof.py`
  - `python3 scripts/materialize_proactive_ooda_gold_acceptance.py`
- Verifiers passed:
  - `python3 scripts/verify_proactive_ooda_operator_status.py`
  - `python3 scripts/verify_continuous_improvement_goal_posture.py`
  - `python3 scripts/verify_operator_action_required_digest.py`
  - `python3 scripts/verify_operator_action_required_dedupe_proof.py`
  - `python3 scripts/verify_proactive_ooda_gold_acceptance.py`

Important behavioral rule:

- `/admin/proactive-ooda/approval` is only for a real current consent-gated packet with a usable capture surface.
- If the system cannot name the concrete object, consequence, and current capture route, it must not ask the operator to approve anything there.
- For the current runtime, the page should say action needed, not approval, and point to Google workspace reconnect.

## Latest delta: approval page copy now states the exact action and says there is nothing to approve

Current live truth checked on 2026-07-07:

- `resolve_proactive_ooda_capture_bundle(...)` currently reports:
  - `current_packet_live_pending_count = 0`
  - `safe_work_summary = "Action needed: Google Workspace OAuth test-user setup."`
  - `safe_work_work_type = "record_internal_action"`
  - `safe_work_staged_action_url = https://myexternalbrain.com/integrations/google`
- `ea_operator_action_required_digest.generated.json` currently reports:
  - `status = sent`
  - `notification_action_keys = ["google_workspace_oauth_setup"]`
- `ea_continuous_improvement_goal_posture.generated.json` still shows the top operator action as:
  - `key = google_workspace_oauth_setup`
  - `next_action_label = Retry Google auth`
  - `next_action_form_href = /integrations/google`
  - `console_deep_link = https://console.cloud.google.com/auth/audience?project=propertyquarry-498318`

Direct operator answer for `/admin/proactive-ooda/approval`:

- Nothing should be approved there right now.
- The concrete action is:
  1. Open `/integrations/google`
  2. Retry Full Workspace auth with `work.tibor.girschele@gmail.com`
  3. If Google still blocks it, open the Audience page for project `propertyquarry-498318` and confirm the work account is still allowed

Copy changes made in this slice:

- `/docker/EA/ea/app/api/routes/proactive_ooda_approval_support.py`
  - fallback state now renders:
    - `console_title = "No approval pending"`
    - `console_summary = "Nothing needs approval here. Current action: <label>."`
    - `object_title = "Current action: <label>"`
    - object copy explicitly says the page does not record or accept an approval
  - the fallback section now leads with the action instead of “Action needed, not approval”

Tests updated and green:

- `/docker/EA/ea/tests/test_proactive_ooda_approval_capture.py`
- `/docker/EA/tests/test_admin_surface_runtime_contracts.py`
- verification command:
  - `python3 -m pytest --import-mode=importlib -q /docker/EA/ea/tests/test_proactive_ooda_approval_capture.py /docker/EA/tests/test_admin_surface_runtime_contracts.py -k 'approval_surface or proactive_ooda_approval_page'`
  - result: `13 passed, 24 deselected`
