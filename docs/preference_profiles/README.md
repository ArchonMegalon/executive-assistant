# Preference Profiles

This folder documents the operator-facing preference-profile review and Teable sync posture.

## Canonical posture

- EA is the canonical store for:
  - `person_profiles`
  - `preference_nodes`
  - `evidence_events`
  - `decision_assessments`
  - `profile_corrections`
- Teable is the review/sync surface, not the source of truth.

## Teable sync lane

EA now exposes:

- `GET /app/api/people/{person_id}/preference-profile/teable-projection`
- `GET /app/api/people/{person_id}/preference-profile/teable-projection-summary`
- `GET /app/api/people/{person_id}/preference-profile/teable-sync-preview`
- `POST /app/api/people/{person_id}/preference-profile/teable-sync`

The sync lane uses the built-in tool:

- `provider.teable.table_sync`

## Required environment

- `TEABLE_API_KEY`
- `TEABLE_BASE_URL`
  - default: `https://app.teable.ai`
- `TEABLE_TABLE_SYNC_CONFIG_JSON`

## Table mapping contract

`TEABLE_TABLE_SYNC_CONFIG_JSON` maps EA projection tables to Teable table IDs.

Current first-wave contract:

```json
{
  "preference_review_queue": {
    "table_id": "tbl_preference_review_queue",
    "key_field": "projection_id",
    "field_key_type": "name"
  }
}
```

Meaning:

- `table_id`: target Teable table
- `key_field`: stable EA field used for idempotent upsert
- `field_key_type`: Teable field addressing mode, usually `name`

## Current sync scope

The live preference-profile sync path only pushes:

- `preference_review_queue`

This is deliberate. The generic Teable projection adapter still has static sample tables for broader Chummer/EA projection work, but the preference-profile sync lane does not attempt to write those unrelated sample tables.

## Verification

Preview:

```bash
curl -sS \
  -H "X-EA-Principal-ID: <principal>" \
  http://127.0.0.1:8090/app/api/people/self/preference-profile/teable-sync-preview
```

Execute:

```bash
curl -sS -X POST \
  -H "X-EA-Principal-ID: <principal>" \
  http://127.0.0.1:8090/app/api/people/self/preference-profile/teable-sync
```

Local verifier:

```bash
PYTHONPATH=/docker/EA/ea:/docker/EA python3 /docker/EA/scripts/verify_preference_teable_sync.py --principal-id <principal> --person-id self
```

Execute via verifier:

```bash
PYTHONPATH=/docker/EA/ea:/docker/EA python3 /docker/EA/scripts/verify_preference_teable_sync.py --principal-id <principal> --person-id self --execute
```

Bootstrap the Teable table and emit/write the mapping:

```bash
PYTHONPATH=/docker/EA/ea:/docker/EA python3 /docker/EA/scripts/bootstrap_preference_teable_table.py --base-id <base-id>
PYTHONPATH=/docker/EA/ea:/docker/EA python3 /docker/EA/scripts/bootstrap_preference_teable_table.py --base-id <base-id> --create-table --write-config
```

If Teable returns Cloudflare `1010` or another access denial, run the bootstrap from an allowed network or browser-authenticated environment. The EA runtime contract is still valid; the block is external to EA.
