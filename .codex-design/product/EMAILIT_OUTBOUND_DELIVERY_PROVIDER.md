# Emailit Outbound Delivery Provider

## Purpose

Emailit is the promoted outbound email delivery candidate for Hub-owned transactional and lifecycle email.

Core rule:

> Emailit delivers mail. Hub owns notification truth.

Emailit may send transactional, campaign, and digest email through an adapter. It must not decide who should be notified, what the notification means, whether a workflow is complete, or whether a user has access.

## Allowed uses

Emailit may deliver:

- claim and install emails
- support closure emails
- fixed-on-your-channel notifications
- ProductLift voter-closeout follow-ups
- Shadowcasters open-run invitations
- GM application decisions
- scheduling companion emails for Lunacal-backed flows
- BLACK LEDGER world tick digests
- faction newsletters
- creator-program updates
- KARMA FORGE discovery invitations
- release/download campaign messages

## Forbidden uses

Emailit must not own:

- support case state
- release state
- install or claim state
- entitlement state
- run, roster, or schedule truth
- campaign or world truth
- consent truth
- unsubscribe or suppression interpretation without Hub mirroring
- public roadmap or feature truth

## Delivery flow

```text
Hub event or approved packet
  -> notification eligibility check
  -> template selection
  -> recipient consent and suppression check
  -> Emailit adapter send request
  -> EmailDeliveryReceipt
  -> webhook delivery events
  -> Hub notification timeline and retry policy
```

The user-facing truth is the Hub notification timeline, not the vendor dashboard.

## Required adapter behavior

The Hub adapter must provide:

- template id and version
- source event id
- idempotency key
- recipient consent receipt
- suppression check result
- sender-domain policy
- retry policy
- delivery receipt
- webhook verification
- bounce and complaint handling
- kill switch

## Sender-domain readiness

Emailit cannot send production user-facing mail until:

- sending domain is authenticated
- SPF, DKIM, and DMARC posture is documented
- bounce domain is configured or explicitly accepted
- suppression list mirroring is tested
- unsubscribe behavior is tested for campaign/digest mail
- transactional and marketing categories are separated
- staging templates are clearly separated from production templates

## Template families

Initial template families:

```yaml
emailit_template_families:
  install_and_claim:
    owner: chummer6-hub
    examples:
      - claim_link
      - install_recovery
      - channel_update_available
  support_closure:
    owner: chummer6-hub
    examples:
      - bug_fixed_on_channel
      - workaround_available
      - case_closed_with_release
  shadowcasters_ops:
    owner: chummer6-hub
    examples:
      - open_run_invite
      - application_accepted
      - application_waitlisted
      - schedule_confirmed
  black_ledger_digest:
    owner: chummer6-hub
    examples:
      - world_tick_digest
      - faction_newsletter
      - seasonal_honors
  product_feedback_closeout:
    owner: chummer6-hub
    examples:
      - productlift_voter_shipped
      - discovery_followup
      - karma_forge_candidate_update
```

## Closeout rule

An email is not proof that a workflow happened.

Examples:

- A support fix is true only when support case state and release/channel truth agree.
- A run acceptance is true only when Hub roster state accepts the player.
- A world tick digest is true only when Hub publication state says the tick is published.
- A voter closeout is true only when Product Governor and release evidence say the feature shipped.

## Metrics

Track delivery health in Hub:

- send attempted
- accepted by provider
- delivered
- bounced
- complained
- opened where allowed
- clicked where allowed
- unsubscribed where applicable
- suppressed
- retried

Emailit metrics are delivery telemetry. Product interpretation belongs to Hub, Fleet, and Product Governor review.

## Canonical decision

Emailit is a serious Hub outbound delivery candidate.
It is not notification truth.
