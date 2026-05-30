# Telegram Flagship Runtime Design

## Objective

Make Telegram feel like a flagship executive-assistant surface:

- fast first response;
- deterministic handling for simple intents;
- asynchronous processing for heavier work;
- no request/response hanging on the Telegram webhook;
- no reply loops;
- explicit operator-visible state;
- inline buttons only where they reduce ambiguity instead of adding noise.

## Non-negotiable runtime rules

1. `ingest` must persist first.
2. transport ack must happen before heavy reasoning.
3. non-deterministic work must run off the webhook thread.
4. every outbound step must be idempotent and deduped.
5. callback queries must be exact-action only, never routed into free-form model chat.
6. repeated low-signal follow-ups must not emit the same blocking reply forever.

## Turn classes

### Class A: deterministic sync

Handled inline on ingest:

- `/start`, `/help`, `/status`
- safe math
- explicit local tools
- exact document delivery hits
- exact calendar/direct status answers

Requirement:

- bounded, no external long-running reasoning
- target latency: sub-second to a few seconds

### Class B: decoupled async

Handled by:

1. persist event
2. send processing ack
3. schedule async worker
4. send final answer later

Use this for:

- open questions
- multi-step grounding
- Codex-backed reasoning
- anything that may block on provider latency

## Input / processing split

### Ingress contract

Telegram webhook should do only:

1. verify bot secret
2. normalize payload
3. resolve principal
4. persist observation
5. classify deterministic vs async
6. optionally send small ack
7. enqueue worker
8. return

It should not depend on full reasoning success.

### Worker contract

Worker should:

1. read persisted observation
2. compute reply
3. send reply
4. persist delivery receipt
5. persist failure receipt on any exception

## Inline button policy

Inline buttons are good when they:

- collapse ambiguity;
- expose exact bounded next actions;
- avoid typing for frequent branch points.

Inline buttons are bad when they:

- duplicate free-form chat for everything;
- create menu sprawl;
- encourage state drift.

### Approved button uses

1. async processing ack
   - `Status`
   - `Retry`
   - `Help`

2. bounded disambiguation
   - source corpus choice
   - yes/no confirmation
   - date-window selection
   - send/open/skip

3. workflow continuation
   - approve
   - reject
   - snooze
   - escalate

### Rejected button uses

- giant persistent command menus
- “chat with the bot” navigation trees
- multi-level menu labyrinths

## Callback query rules

Callback queries must:

- be idempotent;
- be deduped by callback id;
- be answered immediately with `answerCallbackQuery`;
- execute only exact mapped actions.

They must not:

- call general LLM chat directly;
- recurse into the same free-form Telegram turn router;
- depend on missing session state without fallback.

## Reliability controls

### Dedupe

Required keys:

- inbound message dedupe
- inbound callback dedupe
- processing ack dedupe
- async-start dedupe
- final-reply dedupe

### Loop prevention

Required checks:

- same reply recently sent to same chat
- same async prompt already pending
- callback actions exact-match only
- low-signal completion cues suppressed when they would repeat the same blocker

### Failure posture

If heavy reasoning fails:

1. persist `telegram.reply_async_failed`
2. fall back to deterministic/local reply if available
3. otherwise send a short failure-safe user message

No silent drop.

## UX posture

### Immediate ack

Use short transport-safe copy:

- `Saved. EA is processing this asynchronously now.`
- `Working on it. EA saved your request and is processing it asynchronously.`

### Final reply

Must be:

- directly useful;
- not meta;
- not duplicate the ack;
- grounded where possible.

## Next hardening steps

Implemented:

1. callback action signature tokens with expiry
2. explicit `queued / processing / sent / failed` async turn timeline in observations
3. scheduler replay for stranded async turns after restart
4. per-turn callback packets bound to the original Telegram message id and chat id
5. durable observation-backed outbox as the primary async execution lane

Remaining:

1. add transport-level reply retry state for Telegram send failures
2. add inline disambiguation packets for split document backends and date/place ambiguity
3. add replay-safe message-edit support for ack cards where useful
