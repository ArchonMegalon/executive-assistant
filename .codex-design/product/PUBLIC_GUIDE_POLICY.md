# Public guide policy

## Purpose

`Chummer6` is the downstream human guide for public explanation and product framing.
It is not a second design authority.

`chummer.run` is the product homepage, proof shelf, and invitation surface.
`Chummer6` is the richer downstream guide.

## Rules

* `Chummer6` may explain canonical design and horizon posture in plain language.
* `Chummer6` must stay subordinate to `PUBLIC_LANDING_POLICY.md` and the landing manifest relationship: homepage first, guide depth second.
* `Chummer6` must not outrun `products/chummer/HORIZONS.md` or `products/chummer/horizons/*.md`.
* `Chummer6` must not outrun `products/chummer/PARTICIPATION_AND_BOOSTER_WORKFLOW.md`.
* `Chummer6` must not invent a public feature map that contradicts `PUBLIC_LANDING_MANIFEST.yaml` or `PUBLIC_FEATURE_REGISTRY.yaml`.
* `Chummer6` must compile page classes from public-safe guide registries instead of scraping implementation scopes for public prose.
* `PUBLIC_GUIDE_PAGE_REGISTRY.yaml` is the contract for page classes, allowed sources, forbidden sources, and depth limits.
* `PUBLIC_PART_REGISTRY.yaml` is the source of truth for public part pages.
* `PUBLIC_FAQ_REGISTRY.yaml` and `PUBLIC_HELP_COPY.md` are the source of truth for FAQ/help participation copy.
* The root `products/chummer/HORIZON_REGISTRY.yaml` is the only source of truth for horizon existence, order, and public-guide eligibility.
* `products/chummer/horizons/HORIZON_REGISTRY.yaml` is a derived guide-routing index only; it may not widen eligibility, reorder horizons, or create a second canon.
* If the guide and design canon disagree, the guide is wrong and must be corrected.
* Generated public guide output must include a human-facing help/support lane that explains the guided contribution concept and points readers at the Hub participation endpoint.
* The guided-contribution support lane must describe opt-in premium help on top of the cheap baseline, not a return to premium-by-default execution.
* Public help/support copy should prefer `participate` and `guided contribution` rather than leading with operator jargon such as `participant burst lane`.
* Feature and horizon suggestions from the public go to `Chummer6`, Discord, or other public intake lanes, not to `chummer6-design`.
* Public prioritization, polls, and votes are advisory only.

## Canon order

1. `chummer6-design`
2. approved public-status summaries
3. page-type-specific public registries and manifests
4. owning code repos, only when the page class explicitly allows them
4. `Chummer6`

## Working rule

The public guide explains canon.
It does not create canon.

## Public guide layers

1. **Public product story**
   Root story pages, current status, landing mirrors, and other first-contact explanation pages.
   These should only use public story canon, landing canon, public user model, approved public status, and the public guide page registry.
2. **Public explainer depth**
   Part pages, horizon pages, FAQ, and help/support pages.
   These should use public-safe summaries explicitly authored for public readers, not raw implementation scope bullets.
3. **Deep source trail**
   Pages that intentionally point curious readers toward deeper design or repo truth.
   This is where technical readers can discover ownership maps and implementation detail without polluting the first-contact pages.
