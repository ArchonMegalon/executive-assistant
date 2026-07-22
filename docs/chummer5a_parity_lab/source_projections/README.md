# Chummer source projections

This directory contains compact, redacted projections of the cross-repository proof fields consumed by the M141-M143 EA packet materializers. The projections make a clean checkout reproducible without copying large completion trees or embedding operator-specific filesystem paths.

The projections are evidence indexes, not replacements for canonical owner-repository artifacts. Live operators can point the materializers at current canonical sources with the existing `EA_CHUMMER_CROSS_REPO_COMPLETION_ROOT`, `EA_FLEET_COMPLETION_ROOT`, and per-source environment overrides. Generated packets record repo-relative paths for tracked inputs and logical `external:<filename>` provenance for override inputs.

Projection snapshot: 2026-07-15. Values are intentionally limited to the fields and receipt tokens required by the fail-closed packet contracts.
