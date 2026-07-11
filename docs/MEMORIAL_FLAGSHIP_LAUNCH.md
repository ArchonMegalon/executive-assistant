# Manfred Memorial Flagship Launch

This launch note tracks the source-first memorial flagship and its accessible conversation surface.

## Current public flagship

The public memorial intentionally combines:

- curated, explicitly public memories and sources
- a visible synthetic-voice and audio-processing disclosure
- microphone conversation with interruption and recovery
- a keyboard-only text conversation fallback
- a private-by-default family contribution and withdrawal journey
- install support and a discoverable public document archive

Private recordings, family notes, raw transcripts, provider identifiers, consent records, and operator voice-review tooling are never projected onto the public page.

## Family contribution safety

A submitted family memory stays private until a curator publishes a separately reviewed public version. The submission response includes a one-time recovery receipt and management token. The token is stored only as a one-way hash on the server and cannot be recovered; family members must keep the receipt or continue from the browser that saved it. With that token, the private status endpoint reports review state and available correction or withdrawal actions without returning the original submission, curator notes, or a stored token hash.

Curators can reject a pending submission or immediately unpublish an approved memory. These actions require operator access, a named reviewer, and a reason. A public-safe tombstone containing only the contribution ID, status, and timestamps is written before the public projection and private audit ledger are changed. Public reads and every later projection rebuild honor that tombstone, so an individual write failure cannot make removed text reappear.

Withdrawal, rejection, and unpublishing remove the public memory; they do not silently erase the private submission or its bounded moderation history. When the detailed history reaches its limit, the oldest event is folded into a rolling count and SHA-256 digest before the new event is appended, so history saturation never blocks a safety removal. That retained material and its tamper-evident compaction receipt remain private for recovery, consent evidence, and curator support. A permanent-erasure request is a separate, token-authenticated action in the memorial contribution manager. It creates the durable public takedown first, records a private `pending_operator_review` request, and explicitly reports that erasure is not yet complete. The management token stays in the private request header and is never placed in a URL, generic support message, or response body.

Recovery inventory schema v3 includes and verifies the public-safe takedown ledger as public contribution state, restores it with mode `0644` before either the private ledger or public projection, and never classifies it as private source media. Older inventories must be regenerated before restore because they cannot prove that a takedown authority was preserved.

## Preflight and exit gates

Run the preflight:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}"
```

Run the live rehearsal and snapshot:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Run the one-command showtime wrapper:

```bash
python3 scripts/memorial_showtime.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates
```

Final room-ready pass right before the presentation:

```bash
python3 scripts/memorial_room_ready.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_room_ready --optional-exit-gates
```

Run the full memorial exit gates:

```bash
scripts/memorial_flagship_exit_gates.sh \
  --real-public \
  --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
```

This is the launch-capable lane: it requires a credential-free HTTPS origin whose DNS answers are all globally routable, runs the browser check with real STT, gold mode, and public-origin enforcement, and then evaluates the fresh browser receipt with the full gold-readiness verifier. Reserved hostnames, private or mixed DNS answers, resolver failures, and the diagnostic meaningful-turn bypass all fail before a launch claim. Voice, browser, meaningful-turn, and manual-room receipts must name the same slug and origin, carry the same immutable source revision emitted by the deployed image, and share current source-state evidence; the mounted-surface receipt must also pass. The runner parses the final verifier receipt and requires explicit claim authority instead of trusting process exit alone. For a provider-free loopback candidate check, use the explicitly weaker lane:

```bash
scripts/memorial_flagship_exit_gates.sh \
  --provider-free-local \
  --base-url http://127.0.0.1:18090
```

The local lane exits after deterministic suites and the live privacy preflight; it does not run room-ready or conversational browser actions and cannot establish microphone, provider, voice-identity, room-playback, family-approval, or public-launch readiness. The live preflight also requires the raw manifest to be exactly `404`, rejects both public TTS override fields, recursively scans public memorial JSON, archive JSON, and voice configuration for sensitive fields, and fails if the public archive projection contains family-only material.

## Supporting docs

- [MEMORIAL_FLAGSHIP_RUNBOOK.md](MEMORIAL_FLAGSHIP_RUNBOOK.md)
- [MEMORIAL_GO_NO_GO_CHECKLIST.md](MEMORIAL_GO_NO_GO_CHECKLIST.md)

The provider-free production candidate, immutable image build, restart proof, and read-only-source/writable-contribution data layout are documented in the runbook. Candidate success is an intermediate deployment receipt, not public launch authority or family approval.

## Archive publishing

Archive generation creates contained public HTML/PDF artifacts and a public-only registry. Built, approved public HTML can be served through the memorial's internal archive route without a paid provider. FlipLink is optional and must only replace that route after it returns a real, non-placeholder HTTPS publication URL.

Build archive documents:

```bash
cd "$EA_REPO_ROOT"
python3 ea/scripts/build_memorial_archive_documents.py manfred
```

Publish approved public documents:

```bash
python3 ea/scripts/publish_memorial_fliplink_publications.py manfred --public-only
```
