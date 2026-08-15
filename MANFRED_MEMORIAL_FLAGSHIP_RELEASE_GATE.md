# Manfred Memorial Flagship Release Gate

> **Superseded historical packet — not current release authority.** This file
> records the retired EA-hosted Memorial candidate from 2026-07-13. EA Core no
> longer owns or serves Memorial product routes. Current product, voice,
> deployment, store, and promotion truth is owned by the standalone
> `/docker/Memorial` repository and its exact-revision receipts. EA may expose
> only provider/runtime telemetry and the governed integration closeout; it
> must not project this historical packet as current Memorial readiness.

Date: 2026-07-13 (Europe/Vienna)

State: `blocked_not_launch_ready`

Text-first memorial source boundary: `implemented_and_exact_candidate_verified`

Voice, realtime conversation, archive publication, and deployment parity:
`blocked`

## Decision

The memorial may continue as a dignified text-first experience, but it must not
be described or promoted as voice/realtime/publication ready. The current exact
candidate satisfies the strict text-first policy and source-revision boundary;
it is not yet the production deployment and carries no promotion authority.

No generated system may claim to be Manfred, speak for him, hide its synthetic
nature, or publish family/archive material without a private, digest-bound
human authority receipt.

## Current evidence

Local source verification on 2026-07-13:

- The governed deployment and memorial deployment contract slice passes
  `161/161` on the exact release commit.
- Ruff, Python compilation, source diff checks, and three independent reviews
  pass for the hardened scoped deployment lane.
- The candidate browser audit passes desktop and mobile layout, reduced motion,
  accessibility labeling, narrator disclosure, and provider-denial checks.

Running candidate verification:

- Candidate health and `/memorials/manfred` return HTTP 200 on loopback port
  `18094` under isolated project
  `ea-manfred-candidate-364ed9f7-183000`.
- Source commit is `364ed9f7736338679c10a54fff33df4d14122a5e`; image ID is
  `sha256:18f8c40f71f1c461cdd5182efb102d59cdf6da600e0e6bf8003308d9ad3212cb`.
- Runtime-v3 revalidated projection digest
  `9608eaeb07780c01e6e6ef1ef239e151945e9bd04387338ed000f172ac6a12a7`.
- Browser proof records zero provider requests, external requests, WebSockets,
  failed requests, page errors, and HTTP errors.
- No provider credentials were present and no provider calls were performed.
- The candidate remains isolated and available for inspection with
  `promotion_authority=false`.

Production observation:

- `https://myexternalbrain.com/memorials/manfred` still returns HTTP 404.
- Live EA remains in `EA_CORE` mode and is unchanged from the candidate proof.

Release authority is also fail-closed:

- The current memorial readiness gate reports
  `deployment_id_local_fallback` and
  `public_origin_not_deployed_in_memorial_mode`.
- The clean candidate worktree itself is source-clean; the dirty development
  checkout is not used as release authority.
- The required next action is guard-authorized scoped preflight with a fresh
  single-use deployment ID, followed by promotion and rematerialized private
  post-deploy evidence.

## Identity and dignity boundary

The only acceptable generated role is a transparent source-grounded memorial
guide. Its stable boundary is equivalent to:

> I am the source-grounded memorial guide for this page. I can organize
> documented memories, but I cannot speak for Manfred.

The deployed German copy must make the same meaning continuously visible. It
must not be limited to an answer shown only when a visitor challenges the
system's identity.

Model output is rejected or replaced when it:

- says or implies “I am Manfred”;
- uses first-person identity as Manfred;
- asks the visitor to treat generated speech as an original recording;
- removes the memorial/AI disclosure; or
- presents inference as a sourced memory.

## Voice release boundary

Voice remains unavailable until a private, regular, non-symlinked,
owner-restricted authority receipt is independently verified and bound to:

- memorial slug and person identity;
- exact permitted scopes;
- every source recording SHA-256;
- the public disclosure SHA-256;
- stable receipt ID and signed timestamp;
- authority/reviewer role;
- revocation state; and
- an independently verifiable receipt digest/signature.

The public projection must report clone truth accurately. Credentials, a voice
label, or a self-asserted JSON consent object are not authority. Page rendering
must not prewarm a blocked voice, and speech endpoints must fail with a typed
unavailable response before provider work.

## Realtime release boundary

Realtime conversation remains blocked until one deployed, permission-safe
release receipt binds the current slug and deployment source and proves:

- captured STT meets the accepted diagnostic threshold;
- the captured diagnostic is clean and immutable;
- room-audio evidence passed;
- final manual room checks are confirmed; and
- `runtime_enablement_allowed=true` was explicitly authorized.

Current captured evidence is below that bar (`token_f1=0.2353`,
`WER=0.8889`), and the room packet is manual/preparatory rather than final
deployment proof. WebSocket denial must happen before acceptance while this
gate is blocked.

## Archive and asset publication boundary

Archive entries, audio, icons, and source media are public only when their own
review/provenance receipts pass. An approved local HTML build is not
automatically a publication.

- External publication requires a real HTTPS URL, provider publication ID,
  provider timestamp, content digest, and human review receipt.
- Internal publication requires a contained HTML build, matching digest,
  stable internal publication ID, and human review receipt.
- `noindex=true` is the default; indexability requires a separate explicit
  privacy/search decision.
- With no approved audio clips, the UI must not promise original playback or
  project audio-specific suggested prompts.
- Generated SVG fallback art remains preferable to unreviewed image assets.

## Promotion sequence

1. Finish the text-first UX/content/accessibility review with voice/realtime
   disabled.
2. Generate the private human authority and publication receipts outside the
   public artifact tree.
3. Re-run captured STT and final room-audio evidence; do not reuse preparatory
   attestations as deployment proof.
4. Build a clean candidate image from the reviewed source tree.
5. Deploy with an explicit deployment ID through the real release system.
6. Verify candidate/source parity, public JSON, narrator identity, empty-state
   copy, keyboard/mobile behavior, provider non-invocation while blocked, and
   terminal revocation.
7. Rematerialize deploy context, release manifest, and release-authority
   status.
8. Promote only when the authority gate passes and no P0/P1 memorial blockers
   remain.

Until then, the honest flagship posture is a polished text-first memorial with
voice, realtime, and publication visibly unavailable—not a simulated person.
