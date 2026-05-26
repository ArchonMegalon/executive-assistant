# Preference Profile And Decision Engine

Executive Assistant should not pretend to read minds.
It should build a visible, evidence-backed person model that gets better over time and helps the office make better recommendations.

The product goal is:

- anticipate likely preferences
- predict likely objections
- rank options by fit
- explain why
- stay correctable
- stay bounded by consent

This model starts with Willhaben and later extends to travel, shopping, and other executive-office decision lanes.

## Storage posture

Teable is a strong fit for the review and curation surface.
It is not the right canonical store for this system.

Preferred posture:

- first-party EA store owns canonical `person_profiles`, `preference_nodes`, `evidence_events`, `decision_assessments`, and `profile_corrections`
- Teable projects selected rows for operator review, bulk curation, and correction queues
- any Teable-originated change returns as an EA-owned intent or correction packet before canonical write

Why:

- this model is sensitive and high-stakes
- confidence, decay, evidence lineage, and consent controls need tight first-party guarantees
- recommendation scoring should not depend on an external projection table being up-to-date
- Teable is excellent as an operator workbench, but EA already treats it as projection-grade, not system-of-record truth

So the storage split should be:

- canonical truth: EA database
- operator review and triage board: Teable
- write-back path: EA correction or admin-intent API

## Teable role

Teable should host a governed projection for:

- low-confidence preference nodes needing review
- recent preference changes
- high-impact inferred aversions
- correction queue
- Willhaben recommendation review board
- cross-domain candidate ranking review

Each Teable row should carry:

- `projection_id`
- `person_id`
- `domain`
- `target_ref`
- `projection_version`
- `editable_fields_allowlist`
- `confidence`
- `evidence_ref_count`
- `last_updated_at`
- `expiry_at`
- `correlation_id`

Teable must not:

- own the only copy of a preference node
- become the only evidence ledger
- mutate canonical profile rows directly
- silently recompute fit scores without EA receipts

## Product promise

EA should be able to say:

- "This listing likely fits because of layout, district, and stroller practicality."
- "This will probably be rejected because of gas heating and street noise risk."
- "I am not confident whether balcony matters more than a separate office here."

EA should not say:

- "I know what your wife will think."
- "This is definitely right for you."
- anything that depends on invisible, uncorrectable psychological profiling

## Core objects

EA needs six first-class objects for this system.

### 1. `person_profiles`

The stable identity-level model for one human principal or approved related person.

Fields:

- `person_id`
- `principal_id`
- `display_name`
- `profile_scope`
- `consent_mode`
- `learning_enabled`
- `high_stakes_domains_enabled`
- `created_at`
- `updated_at`

### 2. `preference_nodes`

The editable graph of inferred and explicit preferences.

Fields:

- `node_id`
- `person_id`
- `domain`
- `category`
- `key`
- `value_json`
- `strength`
- `confidence`
- `source_mode`
- `status`
- `decay_policy`
- `last_confirmed_at`
- `last_observed_at`
- `updated_at`

Examples:

- `domain=willhaben category=must_have key=elevator value=true`
- `domain=willhaben category=aversion key=gas_heating strength=medium`
- `domain=travel category=soft_preference key=direct_flight strength=high`
- `domain=shopping category=decision_style key=price_comparison_before_purchase value=true`

### 3. `evidence_events`

The append-only ledger of what EA saw.

Fields:

- `event_id`
- `person_id`
- `domain`
- `event_type`
- `object_type`
- `object_id`
- `source_ref`
- `raw_signal_json`
- `interpreted_signal_json`
- `signal_strength`
- `reversible`
- `recorded_at`

Examples:

- saved a Willhaben listing
- ignored a listing after opening
- clicked a tour but did not schedule
- explicitly said "no gas heating"
- purchased an item after comparing three cheaper alternatives

### 4. `decision_assessments`

The scored explanation for one candidate object.

Fields:

- `assessment_id`
- `person_id`
- `domain`
- `object_type`
- `object_id`
- `fit_score`
- `confidence`
- `predicted_reaction`
- `recommendation`
- `match_reasons_json`
- `mismatch_reasons_json`
- `unknowns_json`
- `blocking_constraints_json`
- `generated_at`

### 5. `profile_corrections`

Every human correction to the profile.

Fields:

- `correction_id`
- `person_id`
- `target_type`
- `target_id`
- `old_value_json`
- `new_value_json`
- `reason`
- `corrected_by`
- `corrected_at`

### 6. `domain_preference_views`

Materialized views for fast domain scoring.

Examples:

- `willhaben_preference_view`
- `travel_preference_view`
- `shopping_preference_view`

## Preference taxonomy

Do not dump all preferences into one flat table of arbitrary tags.
The model needs stable categories.

### Constraints

Hard filters.

Examples:

- max rent
- must allow pets
- minimum rooms
- wheelchair access

### Soft preferences

Positive fit factors that can trade off.

Examples:

- quiet street
- balcony
- walkable groceries
- natural light

### Aversions

Negative fit factors that frequently cause rejection.

Examples:

- gas heating
- through-traffic
- poor storage
- long commute

### Tradeoff rules

What the person usually chooses when they cannot have everything.

Examples:

- location over size
- layout over headline room count
- lower friction over lower monthly cost

### Decision-style traits

Operational, not diagnostic.

Allowed examples:

- `needs_comparison_before_commitment`
- `regret_avoidance`
- `decision_fatigue_under_many_options`
- `uncertainty_tolerance`
- `novelty_seeking`
- `budget_anxiety`

Do not store amateur clinical labels.

## Evidence hierarchy

Not all evidence should update the model equally.

Priority order:

1. explicit stated preference
2. explicit correction
3. repeated accepted behavior
4. repeated rejected behavior
5. single-item behavior
6. weak passive telemetry

Rules:

- one-off actions should not rewrite identity
- recent repeated behavior should increase confidence
- contradictory evidence should lower confidence before flipping a node
- explicit statements beat inference unless stale or explicitly revoked

## Inference engine

EA needs a dedicated service:

- `PreferenceInferenceService`

Responsibilities:

- map evidence into candidate node updates
- merge with existing node state
- adjust confidence
- decay stale nodes
- create correction tasks when ambiguity is high

### Update rules

Each inference should have:

- `proposed_change`
- `confidence_delta`
- `evidence_refs`
- `explanation`
- `reversible`

If confidence is below threshold:

- do not silently harden the node
- attach a low-confidence state
- ask for confirmation at the next useful moment

## Willhaben scoring model

Willhaben is the first real lane.

EA should score listings in this order:

1. hard constraint check
2. fit score
3. objection prediction
4. uncertainty evaluation
5. action recommendation

### Candidate features

- district
- exact micro-location
- rent and total monthly burden
- sqm
- room count
- floorplan quality
- 360 or layout visibility
- heating type
- balcony, terrace, garden
- lift
- storage
- transit
- parking
- stroller friendliness
- school and errands proximity
- move-in timing
- renovation burden

### Output shape

Each listing should emit:

- `fit_score`
- `confidence`
- `predicted_reaction`
- `recommendation`
- `good_fit_reasons`
- `bad_fit_reasons`
- `unknowns`

Action classes:

- `ignore`
- `hide`
- `mention`
- `shortlist`
- `strong_recommend`
- `ask_for_clarification`
- `reject`

## Anticipation model

The anticipation layer is just scored prediction plus explanation.

It should estimate:

- what the person will likely prioritize
- what they will likely object to
- what framing will help them decide faster
- what uncertainty blocks a confident recommendation

It must never become a hidden black box.

Every prediction should be inspectable as:

- current evidence
- current preference nodes
- current tradeoff model
- confidence level

## Surfaces

### Operator-facing

Operators should see:

- current preference profile
- what changed recently
- top hard constraints
- strongest inferred aversions
- current tradeoff rules
- low-confidence nodes waiting for confirmation

### Principal-facing

The principal should be able to see:

- what EA thinks matters
- why EA thinks that
- what changed
- how to correct it
- how to pause learning

### Opportunity surfaces

Willhaben cards, travel recommendations, and shopping suggestions should all show:

- fit score
- recommendation
- likely objections
- unknowns still to verify

## Consent and privacy posture

This system is sensitive.

It must require:

- explicit consent per person
- visible inference boundaries
- edit and delete controls
- a switch for `explicit_only`
- a switch for `behavioral_learning_enabled`
- domain-by-domain enablement
- stricter confirmation for high-stakes domains

Guardrails:

- do not infer medical or mental-health conditions
- do not build hidden psychological dossiers
- do not use third-party private data without consent
- do not claim certainty
- do not let low-confidence inference silently block important options

## Delivery rules

When EA sends a recommendation, it should include:

- fit summary
- likely pros
- likely objections
- unknowns
- recommendation class

For example:

- shortlist
- view only if stronger alternatives fail
- reject

## APIs

EA now exposes this first-wave product surface.

### `GET /app/api/people/{person_id}/preference-profile`

Returns the current profile bundle:

- summary/profile metadata
- preference nodes
- evidence events
- decision assessments
- corrections

### `POST /app/api/people/{person_id}/preference-profile`

Creates or updates the profile summary in a non-destructive way.

Omitted fields must remain unchanged.

### `POST /app/api/people/{person_id}/preference-profile/nodes`

Creates or updates an explicit preference node.

### `POST /app/api/people/{person_id}/preference-profile/corrections`

Creates a correction and updates the graph.

### `POST /app/api/people/{person_id}/preference-profile/evidence`

Records explicit or behavioral evidence events from product actions.

### `POST /app/api/people/{person_id}/preference-profile/assessments`

Input:

- domain
- object type
- object id
- object payload

Output:

- fit score
- reasons
- objections
- recommendation

### `GET /app/api/people/{person_id}/preference-profile/teable-projection`

Returns the live EA-owned Teable projection rows for operator review.

### `GET /app/api/people/{person_id}/preference-profile/teable-projection-summary`

Returns table counts and sample-key summaries for the projection.

### `GET /app/api/people/{person_id}/preference-profile/teable-sync-preview`

Returns:

- the current provider state for Teable
- whether a real `table_sync` route is available
- the exact preview payload EA would sync
- a fail-closed `blocked_reason` when Teable is not actually usable

### `POST /app/api/people/{person_id}/preference-profile/teable-sync`

Requests a real Teable sync through `provider.teable.table_sync`.

Current first-wave sync scope:

- `preference_review_queue`

This route must fail closed when:

- `TEABLE_API_KEY` is missing
- `TEABLE_TABLE_SYNC_CONFIG_JSON` is missing or invalid
- the Teable route is not executable
- the provider state is `catalog_only`, `unconfigured`, or otherwise unroutable

## Teable sync runtime contract

The first-wave built-in Teable executor uses:

- `TEABLE_API_KEY`
- `TEABLE_BASE_URL`
- `TEABLE_TABLE_SYNC_CONFIG_JSON`

Current mapping shape:

```json
{
  "preference_review_queue": {
    "table_id": "tbl_preference_review_queue",
    "key_field": "projection_id",
    "field_key_type": "name"
  }
}
```

The executor must:

- list existing records by the stable key field
- update matching rows
- create missing rows
- preserve EA as the source of truth
- return a machine receipt with created/updated counts

## Services

First-wave implementation services:

- `PreferenceProfileService`
- `PreferenceInferenceService`
- `PreferenceEvidenceService`
- `DecisionAssessmentService`
- `WillhabenFitScorer`
- `DecisionExplanationBuilder`

## Rollout plan

### Phase 1

Explicit preferences only.

- schema
- API
- operator view
- manual editing
- Willhaben hard filters

### Phase 2

Evidence ledger and passive learning.

- saved/rejected/opened signals
- confidence updates
- recent-change feed

### Phase 3

Willhaben recommendation engine.

- fit score
- objection prediction
- unknown tracking
- shortlist automation

### Phase 4

Cross-domain reuse.

- travel
- shopping
- restaurants

### Phase 5

Decision-style inference with visible correction loops.

## Release bar

This system is not ready when it can merely infer.
It is ready when it is:

- explainable
- correctable
- bounded by consent
- useful on one high-value lane
- visibly better than static filters

The first real acceptance proof should be:

- Willhaben recommendations are meaningfully better than keyword filtering
- the principal can inspect and correct the model
- every surfaced recommendation explains itself
- no high-stakes silent inference is required for the system to be useful
