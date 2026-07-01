# LTD Integration Map

## Emailit

Use for:

- morning memo delivery
- registration links
- workspace invites
- approval links
- delivery receipts

## Sendr

Use for:

- founder/operator demo outreach
- review-before-send trust campaigns
- Google Workspace workflow campaigns
- private beta and trial onboarding nudges
- partner outreach
- re-engagement of warm leads
- personalized EA demo pages and approved intro videos

Do not use for:

- EA product truth
- office memory
- raw Gmail
- raw Calendar
- people memory
- draft truth
- decision truth
- commitment truth
- support truth
- billing truth
- automatic replies
- publication approval
- private workspace data

Sendr is EA's governed outbound-growth lane, not another assistant runtime. EA creates approved outreach packets, validates product claims, recipient basis, suppression, privacy, and human review, then Sendr may sequence approved outreach. Replies and engagement return to EA as signals and review candidates only.

Default posture:

```text
EA_SENDR_ENABLED=0
EA_SENDR_API_ENABLED=0
EA_SENDR_WEBHOOKS_ENABLED=0
EA_SENDR_WHATSAPP_ENABLED=0
EA_SENDR_DIRECT_SEND_ENABLED=0
EA_SENDR_AUTO_REPLY_ENABLED=0
EA_SENDR_PRIVATE_WORKSPACE_DATA_ALLOWED=0
```

Allowed Sendr inputs are limited to approved public EA docs, approved demo copy, synthetic demo snapshots, public business contacts, prior relationship contacts, inbound leads, and opt-in contacts. Raw office data, private people memory, commitments, decisions, drafts, attachments, support conversations, secrets, and billing data must never be sent to Sendr.

Operator proof:

- `python3 scripts/build_ea_sendr_campaign_packet.py --type FOUNDER_DEMO_OUTREACH --packet ea-founder-demo-review-before-send-001`
- `python3 scripts/verify_ea_sendr_campaign_packet.py --packet .codex-studio/published/ea_sendr_campaign_packet.generated.json --pretty`
- `python3 scripts/materialize_ea_sendr_campaign_receipt.py --packet .codex-studio/published/ea_sendr_campaign_packet.generated.json --dry-run`
- `python3 scripts/verify_ltd_provider_lanes.py --lane sendr_ea_growth_outreach`

The first pilot should stay email-first, capped at 50 contacts, and manually reviewed before any limited send. WhatsApp, direct send, auto-reply, and high-volume enrollment remain disabled until provider verification, recipient-basis, suppression sync, product-claim, privacy, message-copy, and human-approval receipts pass.

## Documentation.AI

Use for:

- customer docs
- operator docs
- API docs
- `llms.txt`

Do not use for:

- raw workspace data
- customer support tickets
- private incident logs
- private decision records
- secrets
- silent writeback to product truth

Documentation.AI is a published docs projection. Git markdown, release receipts, and operator-approved docs own truth. Each publication must bind to source hashes, current HEAD, freshness checks, link verification, and `llms.txt` verification.

## MarkupGo

Use for:

- memo PDFs
- audit receipts
- board-prep packs
- support bundles

Do not use for:

- changing memo content
- raw Gmail
- raw Calendar
- unredacted board material
- granting access
- publication truth

MarkupGo renders EA-approved source packets only. EA owns redaction, authorization, expiry, artifact hashes, and delivery receipts.

## FlipLink.me

Use for:

- redacted PropertyQuarry review-packet flipbooks
- shareable property shortlist packets
- customer-facing packet presentation downstream of PropertyQuarry facts
- EA board packs and premium packet presentation after MarkupGo render proof

Do not use for:

- listing truth
- ranking truth
- entitlement truth
- public-tour asset truth
- unredacted private board material
- access-grant truth
- direct publication

For private EA packets, FlipLink requires access policy, link expiration, revocation, download policy, viewer analytics policy, no public indexing, and an EA delivery receipt.

## Hedy

Use for:

- meeting capture
- transcript-backed evidence
- commitment extraction
- decision proposals
- people-memory enrichment

Do not use for:

- unconsented recording
- direct final commitment creation
- direct decision creation
- direct people-memory overwrite
- follow-up sending without review
- provider-owned truth

Hedy session mapping:

```text
transcript / summary -> evidence
action item -> commitment candidate
question requiring choice -> decision proposal
named person/context -> people-memory candidate
follow-up wording -> draft candidate
```

Every Hedy ingest requires recording consent, webhook signature verification, transcript correction path, restricted evidence handling, retention policy, and human review before object promotion.

## ApproveThis

Use for:

- external approval transport
- vendor spend approval
- contract approval
- board-pack sign-off
- marketing publication approval
- external legal review

Do not use for:

- replacing EA's internal review queue
- approval truth
- broad workspace scope
- direct downstream action
- policy bypass

EA Decision records remain the system of record. ApproveThis responses return as Evidence, update only the matching EA Decision, and still pass EA's final policy gate before any send, publish, or operational action.

## Rafter and Pixefy

Use for:

- EA-specific release security checks
- responsive visual QA
- approval-page checks
- morning memo rendering checks
- expired-link and error-state checks

Do not use for:

- product truth
- release truth
- roadmap truth
- source mutation
- direct publishing

EA release receipts, tests, and operator approval own release truth. Rafter and Pixefy can block a release with evidence, but cannot make a release green by themselves.

## Poppy AI

Use for:

- public video transcript repurposing drafts
- public PDF summary drafts
- manually approved operator-note drafts
- public release-copy variants

Do not use for:

- live assistant runtime
- product truth
- release truth
- support truth
- private campaign data
- sourcebook copied text
- memorial-private material

Operator proof:

- `python3 scripts/verify_poppy_session.py`
- `python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt>`

The source packet and human review own truth. Poppy output is only draft text until reviewed and copied into EA/Chummer-owned source material.

## Unmixr AI

Use for:

- governed memorial and promo narration
- Telegram EPUB audiobook narration after operator approval
- Origin Dossier approved-story audiobooks when the player requests one
- chapter-by-chapter audiobook WAV/MP3 exports

Do not use for:

- raw Gmail
- raw Calendar
- people memory
- workspace secrets
- unlicensed book text
- automatic public publication
- provider-owned audiobook truth

Audiobook workflow:

```text
Telegram EPUB
  -> pCloud job root
  -> extracted chapter text
  -> automatic voice selection from configured presets
  -> Unmixr narration only after EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED=1
  -> resumable bulk pacing for long EPUBs
  -> m4b-tool merge or ffmpeg chaptered-M4B fallback
  -> Audiobookshelf import folder
  -> player/runner-scoped EA audiobook reference for Chummer6 desktop
```

Operator proof:

- `ea/app/services/audiobook_epub_pipeline.py`
- `ea/tests/test_telegram_epub_audiobook_pipeline.py`
- `.codex-design/ea/AUDIOBOOK_EPUB_TELEGRAM_SKILL.md`
- `python3 scripts/materialize_audiobook_epub_quality_contract.py --pretty`
- `python3 scripts/verify_audiobook_epub_quality_contract.py --pretty`

EA owns the job ledger, storage root, rights gate, M4B assembly, import status, and Telegram reply. Unmixr only narrates approved book text.

The current inventory has three Unmixr Tier 4 accounts. EA uses `UNMIXR_API_KEY` as the primary runtime slot and may use `UNMIXR_API_KEY_FALLBACK_1` / `UNMIXR_API_KEY_FALLBACK_2` for additional accounts once those API keys are seeded outside git. Login/password/license-code facts alone do not make an additional account an active runtime lane.

One active account is enough for normal Origin Dossier narration, but long EPUB jobs must be paced so they do not consume the only provider lane. Additional active API-key slots should reduce provider-throttle stalls, but do not remove the need for pacing, rights gates, or scheduler priority. Origin Dossier story jobs are priority small narration work and should bypass bulk EPUB pacing unless Unmixr has already applied a real account-wide throttle.

If several paused or throttled jobs become due together, EA resumes Origin Dossier source kinds before bulk EPUB jobs. That keeps a player-requested origin-story audiobook from sitting behind a long private book once the provider window reopens.

Chummer6 desktop consumes the player-scoped EA reference for the selected runner. It must not hold an Audiobookshelf admin token, global library token, provider secret, or raw pCloud path.

## Promo Video Providers

Use for:

- public faction promo review assets
- homepage or onboarding teaser video candidates
- storyboard, caption, poster, and local MP4 review bundles
- provider-proof-first video experiments such as Advertisemind

Do not use for:

- product truth
- release truth
- route deployment truth
- claiming a named provider is live without provider proof
- public publication without human review
- sourcebook copied text
- unapproved campaign spoilers

Promo video providers are stronger than the local fallback only after real account, export, safety, route, and human-review receipts exist. Until then, EA may produce high-quality local fallback assets, but receipts must keep `provider_ready=false`, `live_provider_runtime_verified=false`, `route_deployment_verified=false`, `not_provider_proof=true`, and `not_public_route_proof=true`.

Operator proof:

- `python3 scripts/materialize_ea_promo_review_bundle.py --faction-id ashline-circle --requested-provider Advertisemind`
- `python3 scripts/verify_ea_promo_review_bundle.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle`
- `python3 scripts/materialize_ea_promo_quality_rubric.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle`
- `python3 scripts/verify_ea_promo_quality_rubric.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle`

`promo_quality_rubric.generated.json` is a local creative-quality receipt. It proves the fallback promo is coherent and reviewable; it does not prove provider availability, public route deployment, or product release readiness.

## ChatLab / ChatPlayground AI

Use for:

- Manfred memorial chat transport experiments
- contract-only provider capability checks
- public memorial answer draft candidates after EA guardrails
- difficult-memory fallback evidence review

Do not use for:

- memorial memory truth
- persona truth
- raw private memorial context upload
- guardrail override
- public publication authority
- gold claim authority
- storing provider secrets in receipts

ChatLab and ChatPlayground AI are bounded chat transports for Manfred, not a memorial source of truth. EA keeps the public answer route, difficult-memory guardrails, publication rules, and memory state. Provider output can become an evidence candidate only after an EA-owned receipt proves account capability, runtime behavior, no private-context upload, and guardrail preservation.

Operator proof:

- `python3 scripts/materialize_memorial_chatlab_contract_receipt.py --slug manfred --pretty`
- `python3 scripts/verify_memorial_chatlab_contract_receipt.py --pretty`
- `python3 scripts/materialize_memorial_chatlab_runtime_preflight.py --slug manfred --pretty`
- `python3 scripts/verify_memorial_chatlab_runtime_preflight.py --pretty`
- `python3 scripts/materialize_memorial_chatlab_external_evidence.py --slug manfred --provider chatlab --account-capability-evidence "$CHATLAB_ACCOUNT_CAPABILITY_EVIDENCE" --runtime-probe-evidence "$CHATLAB_RUNTIME_PROBE_EVIDENCE" --no-private-context-evidence "$CHATLAB_NO_PRIVATE_CONTEXT_EVIDENCE" --guardrail-preservation-evidence "$CHATLAB_GUARDRAIL_PRESERVATION_EVIDENCE" --pretty`
- `python3 scripts/materialize_memorial_chatlab_route_surface.py --slug manfred --pretty`
- `python3 scripts/verify_memorial_chatlab_route_surface.py --pretty`
- `ea/app/services/memorial_chatlab_integration.py`
- `ea/tests/test_memorial_chatlab_contract_receipt.py`
- `ea/tests/test_memorial_chatlab_runtime_preflight.py`
- `ea/tests/test_memorial_chatlab_route_surface.py`

The generated `memorial_chatlab_contract.generated.json` must keep provider readiness, live runtime verification, persona truth, memory truth, publication, raw private context exposure, and gold claims false until separate runtime receipts prove otherwise.
The generated `memorial_chatlab_runtime_preflight.generated.json` may warn when provider account or runtime probe receipts are still missing, but it must fail on configuration errors and must not expose credentials, endpoints, raw private context, or live-provider claims.
The generated `memorial_chatlab_external_evidence.generated.json` is the redacted handoff for those separate receipts. It stores only evidence hashes and pass/missing status for account capability, runtime probe, no-private-context upload, and guardrail preservation; it must not store raw prompts, provider responses, endpoints, credentials, or private memorial context.
The generated `memorial_chatlab_route_surface.generated.json` proves the public `/memorials/manfred/chatlab/status` route returns the same bounded fallback and configured-contract-only posture, keeps first-party chat authoritative, and does not expose provider credentials, endpoints, raw private context, or live-provider claims.

## Active Media / LTD Goal Bundle

Use for:

- one local evidence receipt across EPUB audiobooks, M4B structure, Manfred ChatLab, Manfred realtime speaker readiness, cinematic narration, and fallback promo video
- operator handoff before collecting external provider and public-route proofs
- preventing a local receipt from becoming a gold, provider-ready, or route-deployed claim

Do not use for:

- product truth
- release truth
- live provider truth
- public route deployment truth
- goal completion truth

Operator proof:

- `python3 scripts/materialize_active_media_ltd_goal_bundle.py --pretty`
- `python3 scripts/verify_active_media_ltd_goal_bundle.py --pretty`
- `ea/tests/test_active_media_ltd_goal_bundle.py`

The generated `active_media_ltd_goal_bundle.generated.json` aggregates the current local receipts and lower verifiers. A passing status means `ready_local_evidence`: local audiobook, ChatLab-boundary, Manfred realtime readiness, cinematic-narration, and fallback-promo lanes are coherent enough for operator review. It must still keep provider readiness, live runtime verification, public-route deployment, provider-output truth, gold claims, and goal-completion claims false.

The bundle also verifies `manfred_realtime_conversation_readiness.generated.json` and embeds `external_proof_posture.manfred_spoken_conversation` from `MEMORIAL_OPERATOR_STATUS.generated.json`. Those sections may report production STT, public-origin TTS playback, room-audio attestation, and captured-fixture status, but they must not become a premium spoken claim unless real captured STT evidence and real room-audio attestation both pass.

For captured STT fixture blockers, the operator proof is:

- `python3 scripts/materialize_memorial_stt_captured_candidate_diagnostic.py`
- `python3 scripts/verify_memorial_stt_captured_candidate_diagnostic.py --pretty`

The diagnostic can prove a captured candidate is not promotable because the full-runtime transcript hashes, required-token presence, token F1, or WER do not match the operator-confirmed ground truth. It keeps transcript text redacted in committed/public receipts and points full-text debugging at operator-local use only.

The bundle must list remaining external proofs before any wider claim: ChatLab live runtime evidence, named promo provider account/runtime evidence, deployed public promo route browser evidence, human review for public promo publication, real user EPUB playback acceptance, real Manfred realtime room acceptance, and real Manfred spoken-conversation STT/TTS roundtrip evidence.
