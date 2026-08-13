# vexp LTD opportunity index

This is an operator query pack, not product canon. It uses the local vexp index to find places where an already-owned LTD could reduce cost or proof debt. Results are draft opportunities and always require owner review.

## Weekly queries

1. Which Chummer docs mention Black Ledger but have no bounded media provider mapped?
2. Which scripts produce release receipts but do not project status to Teable?
3. Which support surfaces could use bounded Emailit transport without owning support truth?
4. Which docs mention Foundry handoff but lack approved FlipLink or MarkupGo artifacts?
5. Which campaign-memory surfaces could emit approved Unmixr audio?
6. Which provider lanes are documented but absent from LTDs.md or governance `LANES`?
7. Which generated receipts name a revision different from the current source revision?
8. Which Tier 1 or Tier 2 LTD lacks a fresh next-proof receipt or must-not-claim boundary?
9. Which runtime selector names a provider whose credential is empty?
10. Which route exists without provider, privacy, approval, and rollback proof?

Run `python scripts/query_ltd_opportunity_index.py --execute` for a fresh local projection. The runner invokes `vexp capsule`, redacts terminal output to bounded excerpts, records the source HEAD, and fails if fewer than 20 opportunity candidates can be derived. It never edits canon or provider configuration.

