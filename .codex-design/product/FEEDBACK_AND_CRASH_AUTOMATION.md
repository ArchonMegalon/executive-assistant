# Feedback and crash automation

## Purpose

This file defines how crash and support automation flows after the first support plane exists.

The canonical rule is:

> Crash reports flow into a Hub-owned intake plane; Fleet may consume normalized crash work items for automated triage, repro, and patch proposal, but must not become canonical support truth or bypass the standard review/release/update pipeline.

Clustered crash and support packets then feed the broader routing loop defined in `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`.

## Non-goals

This file does not allow:

* raw desktop clients to send crash payloads straight to Fleet as the primary seam
* Fleet to become the crash or support database
* a single crash report to trigger an autonomous merge or direct production release
* hot-patching user installs outside the normal updater, registry, and review pipeline

## Canonical flow

1. `chummer6-ui` catches the crash, writes a local pending report, and sends a redacted `CrashEnvelope` to a Hub-owned crash intake endpoint when transport is available.
2. `chummer6-hub` stores the hosted incident/case truth, attaches user-safe support context, and normalizes the crash into machine work.
3. `chummer6-hub-registry` enriches that incident with installed version, channel, platform, arch, desktop head, runtime-bundle head, and update-availability facts.
4. `fleet` consumes the normalized crash work item and performs clustering, dedupe, fingerprinting, reproduction attempts, regression-test drafting, candidate patch drafting, and PR creation in the owning repo.
5. Review and approval still gate any landing.
6. User-visible repair still flows through the standard desktop release/update path: UI owns updater behavior, Registry owns feed/channel truth, and Fleet may orchestrate the release wave without becoming the client authority.

## Repo split

### `chummer6-ui`

Owns:

* crash capture on the client
* local pending-report state
* redaction before hosted submission
* `CrashEnvelope` emission to Hub-owned intake

Must not own:

* direct Fleet submission as the primary crash seam
* crash-cluster truth
* automated patch landing or release decisions

### `chummer6-hub`

Owns:

* hosted crash/support incident truth
* intake/orchestration APIs
* normalization from `CrashEnvelope` into crash jobs
* human/operator review context

Must not own:

* registry release truth
* Fleet execution truth
* client-local crash interception

### `chummer6-hub-registry`

Owns:

* release/install/update facts used to enrich crash incidents
* canonical version/channel/platform/runtime-bundle context

Must not own:

* crash intake truth
* support case truth
* Fleet automation state

### `fleet`

Owns:

* crash clustering and dedupe
* repro automation
* regression-test generation
* candidate patch drafting and PR preparation
* alerting and operator-facing triage aids

Must not own:

* raw client-intake truth
* canonical support-case truth
* merge/release authority without the normal review and release path

## Automation allowed

Fleet may automatically:

* cluster duplicate crashes by fingerprint
* correlate incidents with registry-backed release facts
* detect regressions after rollout
* open or update a canonical incident link
* attempt repro in bounded worker lanes
* draft failing tests and candidate patches
* attach CI and verification evidence to review

Hub and EA may automatically:

* compose reporter-facing progress mail from canonical support-case truth
* queue that mail through EA `connector.dispatch` / delivery outbox
* require sent Emailit receipts before the E2E gate counts the mail stage as complete

Those progress emails must follow `FEEDBACK_PROGRESS_EMAIL_WORKFLOW.yaml`; they are downstream of Hub case truth and Registry release truth, not a side channel that invents its own status story.

## Automation forbidden

Fleet must not automatically:

* ingest raw full diagnostics by default from desktop clients
* become the canonical crash/support store
* merge code solely because automation proposed a fix
* bypass Hub-owned intake or Registry-owned release truth
* release straight to users outside the normal updater/channel pipeline

## Data rule

Default auto-send is minimal and redacted:

* app version
* channel
* platform and arch
* stack trace
* crash fingerprint
* last safe UI action category
* short redacted log tail

Full diagnostics remain opt-in:

* full log archive
* local state snapshot
* memory dump
* screenshots or attachments

## DTO families

The first contract families are:

* `CrashEnvelope`: UI-to-Hub crash intake payload with redacted client facts and attachment refs
* `CrashCluster`: Hub/Fleet-facing grouped crash signature and regression view
* `CrashWorkItem`: normalized repro/triage/patch-prep work item consumed by Fleet

These DTO families belong under `Chummer.Control.Contracts` because Hub owns the intake/control boundary and Fleet is a downstream consumer rather than the semantic owner.
