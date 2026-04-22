# EA flagship truth plane

## Purpose

Executive Assistant needs its own release truth so flagship claims do not depend on the all-released `MILESTONE.json` plus checklist completion alone.

This plane is EA-owned release evidence, not product canon. It sits below `IMPLEMENTATION_SCOPE.md` and above the release checklists.

`EA_FLAGSHIP_TRUTH_PLANE.md` is the human-readable form of this plane.
`EA_FLAGSHIP_RELEASE_GATE.json` is the machine-readable seed that release verification consumes.

## What counts as truth

A flagship claim for Executive Assistant must be supported by:

1. the browser workflow proof that exercises seeded product objects and real workspace actions
2. the machine-readable gate seed in `EA_FLAGSHIP_RELEASE_GATE.json`
3. release asset verification that knows how to validate the gate seed
4. release checklists that point at this plane instead of treating `MILESTONE.json` as the oracle

## What does not count as truth

- `MILESTONE.json` alone
- checklist completion alone
- polished shell copy without browser proof
- endpoint inventory without real workspace behavior

## Evidence base

Use the existing browser proof as the release evidence base:

- `tests/test_product_browser_journeys.py`
- `tests/e2e/test_product_workflows.py`

Those tests prove the workspace renders seeded objects, actions change live state, and the browser can follow the core executive-office loop.

## Release claim rule

EA is flagship-grade only when the shipped workspace behaves like a real executive-office work system and the browser proof, gate seed, and release verification agree.

If those three disagree, the safe answer is not flagship.

## Operating rule

Treat `MILESTONE.json` as supporting delivery history.
Treat this plane as the release truth for EA-specific flagship claims.
