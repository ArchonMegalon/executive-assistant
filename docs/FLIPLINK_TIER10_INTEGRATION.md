# FlipLink Tier 10 Integration Guide

PropertyQuarry owns search, ranking, facts, preference learning, privacy, audit state, and entitlement state. FlipLink is only the redacted packet publishing layer for polished PDF/flipbook delivery, branded links, QR/share flows, lead capture, and later paid report distribution.

## Product Lane

```text
PropertyQuarry Search
  -> ranked listing
  -> redacted research packet
  -> PDF render
  -> FlipLink publication
  -> branded packet link / QR / embed
  -> FlipLink lead webhook
  -> PropertyQuarry external-feedback inbox
```

Use Smart Documents for evidence-heavy due-diligence packets, agent briefs, and paid market reports. Use 3D Flipbooks for visual family review packets, shortlist brochures, QR handouts, and investor-style decks. The selected FlipLink format is treated as permanent after packet render and cannot be changed by the manual-link endpoint.

## Runtime Contract

```env
FLIPLINK_LOGIN_EMAIL=
FLIPLINK_LOGIN_PASSWORD=
FLIPLINK_ACCOUNT_TIER=10
FLIPLINK_ACTIVE_PUBLICATION_CAP=1000
FLIPLINK_CUSTOM_DOMAIN=packets.propertyquarry.com
FLIPLINK_WEBHOOK_SECRET=
FLIPLINK_WEBHOOK_ALLOWED=1
FLIPLINK_WEBHOOK_ALLOW_QUERY_SECRET=0
FLIPLINK_DEFAULT_FORMAT=smart_document
FLIPLINK_BROWSERACT_ENABLED=0
```

`EA_FLIPLINK_LOGIN_EMAIL`, `EA_FLIPLINK_LOGIN_PASSWORD`, and `FLIPLINK_API_KEY` remain compatible placeholders, but the first production lane does not assume a public FlipLink document-creation API.

## Implemented Phase

The current implementation is the safe manual lane plus webhook ingestion:

- Render redacted PropertyQuarry PDFs.
- Store publication rows and audit events.
- Download operator PDF artifacts.
- Record manually published FlipLink URLs.
- Ingest FlipLink lead webhooks as `untrusted_external`.
- Show a packet dashboard at `/app/properties/packets`.
- Keep owner review explicit before feedback affects preference learning.

## API

```http
POST /app/api/properties/{property_ref}/packets/render
POST /app/api/properties/packets/{publication_id}/fliplink/manual-link
GET  /app/api/properties/packets/{publication_id}
GET  /app/api/properties/packets/{publication_id}/pdf
GET  /app/api/properties/packets/feedback-inbox
POST /app/api/properties/packets/feedback/{event_id}/review
POST /v1/integrations/fliplink/webhook
```

## Privacy Rule

Redact before PDF generation. Do not upload raw dossiers, raw tours, raw source packets, preference snapshots, internal notes, credentials, tokens, exact address fields for anonymous/public modes, or unreviewed learning state to FlipLink.

Every rendered packet stores an internal redaction receipt with:

- redaction policy version
- privacy mode
- removed fields
- allowed fact keys
- source refs
- PDF SHA-256
- generated timestamp

Receipts are internal only and are not published to FlipLink.

## Webhook Rule

FlipLink webhook data must be secret-gated and treated as untrusted:

- `X-PropertyQuarry-Webhook-Secret: <secret>` is preferred.
- `?secret=<secret>` is disabled by default and should only be enabled with `FLIPLINK_WEBHOOK_ALLOW_QUERY_SECRET=1` for providers that cannot send custom headers.
- Email addresses are stored as masked/hash values in packet events.
- Owner acceptance is required before any preference evidence is recorded.
- Custom fields are allowlisted to `viewer_role`, `reaction`, `question`, `intent`, `property_ref`, `packet_kind`, and `privacy_mode`; extra or nested fields are marked as redacted.

## Source References

- FlipLink product page: https://fliplink.me/
- FlipLink webhook page: https://fliplink.me/integrations/webhooks
- FlipLink Stripe/Sale Mode page: https://fliplink.me/integrations/stripe
