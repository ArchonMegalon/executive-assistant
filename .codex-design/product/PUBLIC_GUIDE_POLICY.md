# Public guide policy

## Purpose

`Chummer6` is the downstream human guide for public explanation and product framing.
It is not a second design authority.

`chummer.run` is the product homepage and invitation surface.
`Chummer6` is the richer downstream guide.

## Rules

* `Chummer6` may explain canonical design and horizon posture in plain language.
* `Chummer6` must stay subordinate to `PUBLIC_LANDING_POLICY.md` and the landing manifest relationship: homepage first, guide depth second.
* `Chummer6` must not outrun `products/chummer/HORIZONS.md`, `products/chummer/horizons/*.md`, `products/chummer/features/*.md`, or `PUBLIC_FEATURE_REGISTRY.yaml`.
* `Chummer6` must not outrun `products/chummer/PARTICIPATION_AND_BOOSTER_WORKFLOW.md`.
* `Chummer6` must not invent a public feature map that contradicts `PUBLIC_LANDING_MANIFEST.yaml` or `PUBLIC_FEATURE_REGISTRY.yaml`.
* When a public feature already has first-party pages in `PUBLIC_FEATURE_REGISTRY.yaml`, public guide copy should point readers there before sending them deeper into feature prose.
* `Chummer6` must compile page classes from public-safe guide registries instead of scraping implementation scopes for public prose.
* `PUBLIC_GUIDE_PAGE_REGISTRY.yaml` is the contract for page classes, allowed sources, forbidden sources, and depth limits.
* `PUBLIC_PART_REGISTRY.yaml` owns public part pages.
* `PUBLIC_FAQ_REGISTRY.yaml` and `PUBLIC_HELP_COPY.md` own FAQ/help participation copy.
* The root `products/chummer/HORIZON_REGISTRY.yaml` owns horizon existence, order, and public-guide eligibility.
* The root `products/chummer/HORIZON_REGISTRY.yaml` is the only source for horizon public-guide eligibility and order.
* `products/chummer/horizons/HORIZON_REGISTRY.yaml` is a derived guide-routing index only; it may not widen eligibility, reorder horizons, or create a second canon. It must preserve the root registry order exactly.
* If the guide and design canon disagree, the guide is wrong and must be corrected.
* Generated public guide output must include a human-facing help/support page that explains guided contribution and points readers at the Hub participation endpoint.
* Guided-contribution support must describe opt-in premium help on top of the cheap baseline, not a return to premium-by-default execution.
* Public help/support copy should prefer `participate` and `guided contribution` rather than leading with internal jargon such as `participant burst lane`.
* Feature and horizon suggestions from the public go to `Chummer6`, ProductLift, Discord, or other public intake pages, not to `chummer6-design`.
* Public prioritization, polls, and votes are advisory only.
* Katteb may audit or draft public guide/article improvements only from approved Chummer copy, screenshots, and release notes.
* Accepted Katteb recommendations must become upstream `chummer6-design` or public-guide copy changes before published guide pages change.
* The generated public guide must not be hand-edited to accept Katteb output.
* ClickRank may audit generated public guide pages and public site pages for crawlability, metadata, schema, internal links, and search visibility, but accepted changes still land upstream in Chummer-owned source before publication.

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
3. **Clear deeper links**
   Pages that intentionally point curious readers toward deeper design or repo detail.
   This is where technical readers can discover ownership maps and implementation detail without polluting the first-contact pages.

## ProductLift and Katteb posture

`PRODUCTLIFT_FEEDBACK_ROADMAP_BRIDGE.md`, `KATTEB_PUBLIC_GUIDE_OPTIMIZATION_LANE.md`, and `PUBLIC_SIGNAL_TO_CANON_PIPELINE.md` define the public signal/content loop.

ProductLift can point users at `/feedback`, `/roadmap`, and `/changelog`, but those pages remain public planning and follow-up views from Chummer.

Katteb can improve clarity and findability, but public guide claims still come from this repo and the approved public-guide registries.

ClickRank can make crawl, metadata, schema, and search visibility problems visible, but it cannot make public claims true. Accepted ClickRank recommendations patch Chummer-owned source first.
