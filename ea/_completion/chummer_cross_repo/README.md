# Chummer cross-repository receipt mirror

This directory is a read-only evidence mirror consumed by
`scripts/materialize_whole_project_gold_map.py`. Chummer repositories remain
the owners of these receipts; Executive Assistant does not gain product,
release, or publication authority by carrying exact-byte copies.

The July 28, 2026 sync intentionally preserves mixed upstream truth:

- core rule authority receipts report `pass`;
- the desktop layout receipt reports `pass`, while desktop executable and
  visual-familiarity receipts report `fail`;
- public reachability and clickability receipts report `pass`, while the Hub
  flagship-readiness receipt reports `fail`;
- the mobile local-release receipt reports `passed`;
- the Black Ledger media receipt reports `pass`, but the EA whole-project map
  continues to require asset-specific publication and human approval evidence.

Missing, invalid, or non-passing receipts must continue to block the
corresponding whole-project plane. Do not edit mirrored JSON to improve its
status; refresh it from the owning repository instead.
