# Interop and portability model

## Purpose

Chummer portability is not a side quest.
It is the rule that a runner, campaign, and grounded output can cross product surfaces without turning into folklore, screenshots, or one-off export cargo.

This file canonizes:

* what "portable" means for Chummer
* which package families own interop and portability seams
* how import, export, migration, and publication stay honest

## Product promise

Chummer promises:

* a runner and campaign can leave one surface without losing provenance
* import/export formats are explicit and versioned
* compatibility claims are machine-readable and human-explained
* active rule-environment, preset, and amend-package truth travels with the portable object
* migration from legacy single-character-file thinking is a guided transition, not silent reinterpretation

Portability is therefore part of the product promise, not just a compatibility adapter hidden in old tooling.

## Canonical ownership split

### `chummer6-design`

Owns the canon, vocabulary, exit criteria, and public promise for interop and portability.

### `chummer6-core`

Owns deterministic import/export interpretation, migration receipts, compatibility reasoning, and rules-truth-safe transformation logic.

### `chummer6-hub`

Owns hosted import/export orchestration, account-aware handoff, continuity-safe packaging, and round-trip provenance surfaces.

### `chummer6-hub-registry`

Owns immutable artifact, install, channel, and publication metadata that portable packages may point at, but it does not redefine dossier or campaign meaning.

### `chummer6-media-factory`

Owns render-only artifact publication and preview/manifests for creator outputs. It consumes canonical portability truth; it does not redefine it.

## Canonical package families

### `Chummer.Campaign.Contracts`

Owns the long-lived product objects that portability must preserve:

* runner dossier identity
* crew and campaign refs
* run, scene, objective, and recap linkage
* roaming restore and continuity state
* rule-environment refs that define what the portable object actually means

### `Chummer.Play.Contracts.Interop`

Owns the active round-trip package seam for cross-surface asset exchange:

* export package manifest
* import mode and import result
* asset documents and provenance pointers
* round-trip proof that an export/import cycle stayed explainable

### `Chummer.Hub.Registry.Contracts`

Owns immutable install/update/publication truth that portable packages may reference:

* release channel posture
* installer/update metadata
* artifact and compatibility records

Registry truth may annotate the package, but it does not become the semantic owner of dossier or campaign meaning.

## Portable package families

### Dossier package

Carries the living runner identity, relevant rules/environment refs, continuity-safe receipts, and publication-safe projections.

### Campaign package

Carries campaign, crew, run, scene, objective, continuity, and recap linkage with replay-safe provenance.

### Publication packet

Carries share-safe or creator-safe projections of dossier or campaign truth with explicit provenance, compatibility, and render lineage.

Publication packets are derived outputs, not the canonical continuity owner.

## Import and export modes

### Inspect only

Read the package, validate provenance and compatibility, and show what would happen without mutating canonical state.

### Merge

Accept portable state as additive input and preserve existing identity/history where the semantic owners allow it.

### Replace

Use the imported package as the new authoritative portable state only when the destination surface explicitly allows replacement and can emit a receipt for the cutover.

Silent last-write-wins is forbidden.

## Migration and cutover rules

Legacy single-character-file flows remain a compatibility lane, not the target product model.

Every migration path must emit a receipt that classifies fields as:

* safe
* changed
* needs review
* blocked

If a legacy import depends on Chummer5a-style amend/custom-data behavior, the receipt must also classify:

* carried forward as canonical amend package
* downgraded to source-pack-only behavior
* blocked due to unsupported amend semantics

Migration receipts belong to the user-facing trust surface, not only to tests or operator notes.

## Compatibility and support rules

Interop must never claim more compatibility than the current package/versioning posture can actually support.

Portable packages must therefore carry:

* explicit format identity
* version identity
* compatibility or fingerprint context where applicable
* provenance pointers that explain where important values came from

Support and trust surfaces may explain package state and compatibility, but they must not imply that an import succeeded cleanly when the receipt says otherwise.

## Current implementation seam

The current executable seam is:

* design canon here
* `Chummer.Play.Contracts.Interop` for import/export package contracts
* `chummer6-hub` `InteropController` and `InteropExportService` for hosted round-trip behavior
* `chummer6-core` migration and compatibility verification for deterministic interpretation

That is enough to make portability a first-class product lane now, while deeper dossier/campaign package depth can continue as additive work.
