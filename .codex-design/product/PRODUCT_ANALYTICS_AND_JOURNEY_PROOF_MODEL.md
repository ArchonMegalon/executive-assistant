# Product Analytics and Journey Proof Model

## Purpose

This file defines the missing product instrumentation layer.

The goal is to prove that users succeed, not only that Chummer published something.

PostHog and Sentry are candidate infrastructure tools for product analytics, web analytics, session replay, feature flags, experiments, error monitoring, tracing, uptime, logs, and reliability proof. They are not LTD truth systems and they do not replace Hub-owned receipts.

## Core rule

> Hub owns journey receipts. Analytics tools observe and aggregate. Product Governor interprets.

## Golden journeys

```yaml
golden_journeys:
  download_claim_launch_update:
    steps:
      - download_started
      - installer_verified
      - claim_started
      - claim_completed
      - app_launched
      - update_checked
      - update_applied
  open_run_lifecycle:
    steps:
      - open_run_viewed
      - application_started
      - application_submitted
      - application_accepted
      - schedule_confirmed
      - run_played
      - resolution_submitted
  intel_to_job:
    steps:
      - intel_started
      - intel_submitted
      - intel_reviewed
      - intel_adopted
      - job_seed_created
      - job_packet_published
  productlift_to_ship:
    steps:
      - idea_posted
      - idea_clustered
      - discovery_started
      - design_accepted
      - implementation_started
      - shipped
      - voter_notified
  karma_forge_discovery:
    steps:
      - request_submitted
      - interview_completed
      - demand_packet_created
      - candidate_reviewed
      - prototype_started
  world_tick_distribution:
    steps:
      - world_tick_approved
      - map_updated
      - newsreel_published
      - signitic_campaign_started
      - taja_clip_published
      - email_digest_sent
      - engagement_reviewed
```

## Event ownership

- Hub owns product and user journey receipts.
- Fleet owns weekly pulse synthesis and health review.
- Sentry candidate owns crash/error/trace observation only.
- PostHog candidate owns aggregate product journey analytics only.
- Product Governor owns interpretation and priority decisions.

## Privacy posture

Journey proof must follow `PRIVACY_AND_RETENTION_BOUNDARIES.md` and `PRODUCT_USAGE_TELEMETRY_MODEL.md`.

Do not collect raw character sheets, campaign notes, private runner state, support payloads, raw transcripts, or sourcebook text for analytics.

## Success criteria

The model is working when Chummer can answer:

- where users abandon install or claim
- whether open-run applicants make it to scheduled sessions
- whether intel submissions become reviewed artifacts
- whether ProductLift voters hear back when work ships
- whether BLACK LEDGER campaigns create playable outcomes
- whether errors and crashes correlate with failed journeys
