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
11. Which public docs lack current ClickRank freshness or crawl proof?
12. Which Teable projection lacks a write-audit or freshness receipt?
13. Which provider promotion lacks a false-complete gate?
14. Which public artifact lacks both input and output hashes?
15. Which direct-send path lacks a named product-ownership switch?
16. Which 1min background task lacks slot and credit receipts?
17. Which media candidate can publish without human approval?
18. Which operator-facing provider label could expose a private identifier?
19. Which parked LTD is described as live or production-ready?
20. Which external provider appears to own product, rules, or release truth?
21. Which public-safe, synthetic conversation rehearsal could use Tough Tongue without carrying a real voice, private office data, a customer destination, or outbound authority?

Run `python scripts/query_ltd_opportunity_index.py --execute` for a fresh local projection. The runner invokes `vexp capsule`, redacts terminal output to bounded excerpts, records the source HEAD, and fails if fewer than 20 opportunity candidates can be derived. It never edits canon or provider configuration.
