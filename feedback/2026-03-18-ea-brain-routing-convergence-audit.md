# EA brain routing convergence audit

Date: 2026-03-18
Audience: `executive-assistant` repo owners and the `solo-ea` fleet lane
Status: injected fleet feedback

## Verdict

EA is directionally good, but its backend brain is still split across two systems.

The Responses/Codex side now behaves like a real cheap/fast/groundwork/review/core/survival engine. The planner/provider-registry side still behaves like an older runtime centered on `gemini_vortex` for structured generation and BrowserAct for audits/web generation.

The next backend milestone should be convergence, not more parallel routing logic.

## What is already strong

* startup posture is materially healthier: EA now has an explicit `RuntimeProfile`, stronger prod boot validation, and whole-container fallback instead of subsystem-by-subsystem ambiguity
* the public Responses/Codex surface is real: `core`, `easy`, `repair`, `groundwork`, `review-light`, `survival`, and `audit` are exposed and documented
* the budget defaults are no longer reckless: default lane is cheap, hard concurrency is bounded, hard timeout is bounded, and onemin caps are non-zero
* `review_light` is already intentionally narrow, using one ChatPlayground model and one role

## What is still wrong

### 1. The brain is split

Responses knows about profile/lane semantics such as `groundwork`, `review_light`, `audit`, and `survival`.

The provider-registry/planner side still mostly reasons in older executable-provider terms:

* `artifact_repository`
* `browseract`
* `connector_dispatch`
* `gemini_vortex`

That means the smart route table exists, but only inside the Responses façade. Planner-generated work still uses a simpler and older execution brain.

### 2. Provider state is modeled, but not durable enough

EA now has typed provider-binding models such as `ProviderBindingState` and `ProviderBindingRecord`, but the container still instantiates the provider registry with an in-memory provider-binding repository.

The runtime therefore knows what durable provider state should look like while still behaving as if probe/priority/cooldown health is process-local.

### 3. Task-contract policy is typed, but not truly canonical

`TaskContractRuntimePolicy` and `SkillCatalogRecord` are real typed models now, but contract persistence still serializes runtime policy back into `budget_policy_json`.

That is cleaner than raw dicts, but storage truth is still too bag-shaped for long-term evolution.

### 4. Lane definitions are duplicated

Profile tables, public alias exports, provider capabilities, and planner behavior still live in separate modules.

They line up better than before, but they are still separate sources of truth:

* `responses.py`
* `responses_upstream.py`
* `provider_registry.py`
* `planner.py`

### 5. Groundwork and review-light are still Responses-brain features only

EA exposes `groundwork` and `review_light` at the route/profile level, but the provider registry still does not have a logical backend identity for those higher-level lane concepts.

Outside Responses, the rest of EA still cannot reason in those same terms.

## Required implementation order

### PR 1. Canonical brain-profile definitions

Create one typed module for lane/profile definitions and make both `responses.py` and `responses_upstream.py` derive from it.

Required outcome:

* one `BrainProfile` source of truth
* no duplicate public-model definitions
* `/v1/models` and `/v1/codex/profiles` derived from the same canonical table

### PR 2. Real `BrainRouterService`

Add one backend service that decides:

* selected profile
* provider order
* fallback chain
* block reasons
* post-hoc review profile

This service should consume live provider state but should not execute providers directly.

Responses and planner should both call this same router instead of each carrying partial routing logic.

### PR 3. Persist provider binding state

Replace the in-memory provider-binding repository with a real storage-backed implementation when the runtime is on durable storage.

Persist at least:

* probe results
* health/cooldown state
* provider priority changes
* owner-ledger metadata matches
* last successful use timestamp

### PR 4. Converge planner/runtime generation onto the same brain

Add one logical internal provider such as `brain_router` for planner-driven structured generation and review-shaped work.

Planner-generated work should be able to request:

* `easy`
* `groundwork`
* `review_light`

instead of hardcoding `gemini_vortex.structured_generate` as the old default authority.

### PR 5. Make policy storage canonical enough to evolve cleanly

Add explicit persisted `runtime_policy_json` and `skill_catalog_policy_json` fields while keeping `budget_policy_json` as a compatibility shadow for one migration cycle.

Reads should prefer the typed fields.
Writes should write both during the transition.

### PR 6. Tighten cheap-but-smart backend defaults

Keep the existing cheap defaults, but make the backend posture explicit:

* `groundwork` should require Gemini first
* one light ChatPlayground fallback is acceptable when Gemini fails or returns unusable output
* `groundwork` should not silently escalate to onemin
* response metadata should expose `brain_profile`, `selected_provider`, `fallback_chain`, and `posthoc_review_profile`

## What to queue next

1. add canonical `BrainProfile` definitions shared by Responses and model export
2. add a real `BrainRouterService` and wire it into `responses.py`
3. replace in-memory provider-binding state with durable persistence under durable runtime profiles
4. make planner-generated structured work route through the same brain instead of the old gemini-only path
5. split typed runtime policy persistence away from the generic `budget_policy_json` bag
6. expose backend routing metadata so operators can see which provider/profile actually ran

## Single most important direction

Stop treating the EA brain as "Responses plus some tools".

Build one internal routing layer that:

* owns profile semantics
* consumes durable provider state
* and is reused by both Responses and planner-generated work

Right now EA is smart in the Responses path and simpler everywhere else. The next round should make it smart once, in one place.
