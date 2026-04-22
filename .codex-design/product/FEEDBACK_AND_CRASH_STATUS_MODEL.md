# Support and feedback status model

## Purpose

This file defines how Chummer support and feedback cases move from intake to closure once crash, bug, and feedback lanes exist.

It keeps status communication honest and tied to release truth instead of developer-local events.

## Canonical support case links

Every support case may carry:

* `case_id`
* `case_kind` of `crash`, `bug`, or `feedback`
* `user_id` when known
* `installation_id`
* version
* channel
* platform
* arch
* desktop head
* runtime head or runtime-bundle head where known
* linked public issue or knowledge article when safe

## Status spine

The minimum canonical status family is:

* `received`
* `clustered`
* `routed`
* `awaiting_evidence`
* `known_issue`
* `accepted`
* `deferred`
* `rejected`
* `in_progress`
* `fixed_pending_release`
* `released_to_reporter_channel`
* `user_notified`
* `closed`

Optional later variants may exist, but they must not redefine the meaning of these baseline states.

## Event model

Support cases use append-only status events.

The minimum event family is:

* intake accepted
* case clustered into a packet
* packet routed to the next owner
* case linked to installation
* case linked to user
* duplicate or cluster match
* more-info request
* fix linked to work item or public issue
* release reached reporter channel
* user notified
* follow-up survey invited
* case closed

## Meanings that must stay stable

* `clustered` means the case is now part of a grouped evidence packet; it does not imply an accepted fix path.
* `routed` means the packet has a next owner and next lane.
* `accepted` means the issue or idea is intentionally kept alive.
* `deferred` means "not now" with an explicit reason, not silent disappearance.
* `rejected` means the idea or request is intentionally declined.
* `user_notified` means a reporter-facing update was actually sent.

## Closure rule

Do not notify a reporter that the issue is resolved only because:

* a bug was reproduced
* a patch was drafted
* a PR merged
* a preview build exists somewhere else

Notify a reporter that the issue is fixed only when Registry truth says the fix has reached that reporter's channel.

## Guest versus claimed install

### Guest install

Guest cases may stay pseudonymous and installation-linked.

Guest users may still:

* submit a crash
* submit a bug
* submit feedback
* add contact detail later

### Claimed install

Claimed installs allow:

* case history in the account surface
* version-aware update recommendations
* targeted release-notice delivery
* follow-up surveys after a real fix lands

## Notification rule

Allowed outbound messages:

* we received your report
* we need one more detail
* this is a duplicate of a known issue
* this issue is fixed in version `X.Y.Z` on your channel
* did that fix it

Forbidden outbound message:

* resolved, when the fix is not yet available to that reporter's install/channel

Whole-product release control enforces that rule through `FEEDBACK_LOOP_RELEASE_GATE.yaml`.
`released_to_reporter_channel`, `user_notified`, and `closed` only count as healthy closure when support packets and registry release truth agree.

## Progress email workflow

Reporter-facing progress mail must follow `FEEDBACK_PROGRESS_EMAIL_WORKFLOW.yaml`.

The minimum staged email spine is:

* `request_received`
* `audited_decision`
* `fix_available`

`audited_decision` must include the bounded reason, implementation posture, ETA text or explicit no-ETA posture, next owner, and next lane.

Decision awards must stay stable:

* accepted, known-issue, and needs-info paths may award `Clad Feedbacker`
* rejected and deferred paths must award `Denied`

`fix_available` must only fire after `released_to_reporter_channel` is true for that reporter and the notice can name a real download or update route.

## Survey rule

Survey invites are downstream follow-up signals.

They must:

* be triggered by Hub-owned case logic
* keep canonical invite/result linkage in Hub
* remain optional

They must not replace the support-case truth.
