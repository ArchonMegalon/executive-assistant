# Mirror Scope Boundary

EA loads the cross-repo Chummer design front door for context, but this repository does not mirror every canonical Chummer product document.

The release gate treats these as the local authoritative mirror set:

- `.codex-design/product/README.md`
- `.codex-design/repo/IMPLEMENTATION_SCOPE.md`
- `.codex-design/review/REVIEW_CONTEXT.md`
- `.codex-design/ea/*`
- the bounded queue mirror verified by `scripts/verify_design_mirror_bundle.py`

The large canonical file list in `.codex-design/product/README.md` is a navigation index for the full Chummer design plane. Missing files from that list are not local EA mirror failures unless a verifier or implementation scope promotes them into the bounded EA mirror set.

If EA needs a missing Chummer design file to make a product claim, add it to a bounded mirror verifier or emit a design petition instead of silently treating assistant-local notes as canon.
