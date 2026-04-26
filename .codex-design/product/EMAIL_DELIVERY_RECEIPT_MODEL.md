# Email Delivery Receipt Model

## Purpose

This file defines the Chummer-owned receipt shape for outbound email delivery.

The receipt lets Hub prove what it attempted to send, why it was eligible, which template was used, which provider handled the request, and what delivery events returned.

## Receipt shape

```yaml
email_delivery_receipt:
  receipt_id: edr_20260426_001
  source_event:
    event_id: hub_event_id
    event_type: support_case_closed
    source_contract: Chummer.Control.Contracts.SupportCase
    source_version: 12
  notification_truth_owner: chummer6-hub
  provider:
    key: emailit
    adapter_version: emailit_adapter_v1
    provider_message_id: vendor_message_id_or_null
  idempotency_key: sha256_source_event_template_recipient
  template:
    template_id: support_bug_fixed_channel
    template_version: 3
    locale: en-US
  recipient:
    recipient_ref: hub_user_or_contact_ref
    address_hash: sha256_lowercase_email
    consent_receipt_id: consent_or_transactional_basis_ref
    suppression_check: passed
  send:
    requested_at: 2026-04-26T00:00:00Z
    accepted_at: null
    status: requested
    retry_policy: standard_transactional
  webhooks:
    verified: true
    events:
      - type: delivered
        provider_event_id: provider_event_id
        received_at: 2026-04-26T00:01:00Z
  public_claim_allowed: false
```

## State model

```yaml
email_delivery_states:
  requested: Hub queued the provider call.
  accepted: Provider accepted the send request.
  deferred: Provider or policy delayed delivery.
  delivered: Provider reported delivery.
  bounced: Provider reported hard or soft bounce.
  complained: Recipient complaint received.
  suppressed: Hub or provider suppression blocked send.
  cancelled: Hub cancelled before send.
  failed: Provider call or retry policy failed.
```

## Privacy rule

Receipts should not store raw email addresses by default.
Use recipient refs and address hashes unless an active support case explicitly needs the address in a restricted operator view.
