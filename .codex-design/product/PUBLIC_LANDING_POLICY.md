# Public landing policy

## Purpose

`chummer.run` is the public product homepage, proof shelf, and invitation surface for Chummer.
It is not the docs site, not a repo index, and not a second design authority.

`Chummer6` remains the richer downstream explainer and guide.
`chummer6-design` remains the canonical source.

## Public promise

The landing surface must let a normal person understand, in one visit:

* what Chummer is
* what is real today
* what is coming next
* what they can do right now
* what changes when they sign in

## Hard rules

* `chummer.run` is product-facing, not repo-facing.
* Public landing copy must not lead with repo jargon, pipeline jargon, or architecture sermon language.
* Provider names and LTD names are implementation details and must not be named on the landing page.
* Empty placeholder boxes are forbidden.
* If a feature is not live, the card must still explain what is coming and why it matters.
* Public guest chrome must expose `Sign in` plus one primary acquisition action.
* Public cards must not self-link back to the same route unless they are explicitly marked as non-clickable teasers.
* External exits must be explicit and labeled as fallbacks or guide links, not disguised as first-party defaults.
* Landing meaning must compile from design-owned manifest and registry data rather than hub-local improvisation.
* Public maturity, install, and update language must stay converged across `chummer.run`, `Chummer6`, and any linked release repo README or guide page.
* Public status is advisory and explanatory; it does not overrule canonical design truth.
* Provider names may appear only on dedicated auth and account-security surfaces, not on the landing hero or proof cards.
* Download-facing copy and CTA labels must follow `PUBLIC_DOWNLOADS_POLICY.md` and `PUBLIC_AUTO_UPDATE_POLICY.md`.

## Surface split

`chummer.run` owns:

* homepage / product front door
* public proof shelf
* public progress report
* current-state summary
* coming-next summary
* participate entry route
* signed-in home overlay

`Chummer6` owns:

* deeper human explainer copy
* richer examples
* horizon walkthroughs
* public help/support framing

The landing page should route people into `Chummer6` when they want more explanation, not try to replace the guide entirely.

## Public versus registered

Public visitors may access:

* `/`
* `/what-is-chummer`
* `/now`
* `/horizons`
* `/downloads`
* `/progress`
* `/participate`
* `/status`
* `/artifacts`

Registered overlays may unlock:

* `/home`
* `/account`
* horizon follows or watchlists
* beta-interest and waitlist state
* participation / guided-contribution state
* future vote placeholders

The early-access shell may keep registered overlays thin, but the split must be visible and canonical.

## CTA rule

The landing page must always provide at least these public actions:

* one primary acquisition action such as `Get preview build` or `Request early access`
* one proof action such as `See what works today`
* participate / help
* sign in

## Flow rule

The landing page should read in this order:

* value
* proof
* fit
* access

It should not read like a route index.

## Proof rule

The landing page must prove something real exists now.

Allowed proof surfaces include:

* current-state cards
* release shelf entries
* public featured artifacts
* public status summaries
* grounded horizon cards that clearly say `horizon`, `preview`, `guided preview`, or `available today`

The release shelf should feel like an install-and-update shelf first and an archive list second.
It must present one obvious recommended default per platform before exposing advanced alternatives.

## Participation wording

Use public language such as:

* participate
* guided contribution
* temporary help lane

Do not lead with operator terms like:

* participant burst lane
* jury lane
* worker topology
* Fleet
* device-code auth
* worker host

Those terms may appear only in deeper explainer surfaces where they are necessary.

## Ownership

* `chummer6-design` owns public landing structure, route map, copy constraints, feature visibility, and media briefs.
* `chummer6-hub` owns the hosted projection of that structure on `chummer.run`.
* `chummer6-media-factory` owns landing media generation and provenance.
* `Chummer6` may echo the same posture, but it does not become the landing authority.
* `fleet` may publish or synchronize generated outputs, but it must not become the source of landing meaning.
