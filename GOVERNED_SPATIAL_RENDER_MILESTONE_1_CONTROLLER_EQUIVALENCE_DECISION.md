# Governed Spatial Render Milestone 1 Controller Equivalence Decision

Date: 2026-07-12 (Europe/Vienna)

Decision: `accept_controller_recovery_audit_as_process_evidence_equivalent`

Maximum claim: `backend_contract_implemented_and_locally_verified`

This decision exercises the explicit future-controller option in section 13
of `GOVERNED_SPATIAL_RENDER_PROPERTYQUARRY_IMPLEMENTATION_HANDOFF.md`. It does
not fabricate, replace, or relabel the missing receipt from CodexEA worker
session `019f5169-0c0b-7402-a27c-d918ada2e9da`. That worker still produced no
valid receipt. Instead, the later controller recovery, hardening, independent
audit, hash-stable reruns, and zero-effect evidence are accepted as equivalent
process evidence for Milestone 1 only.

## Bound authorities

- Revision 9 independent rereview:
  `431881fd03814b91dafa009c63abf4791264413ff7476015fec187039dd4e10a`
- Revision 9 frozen matrix:
  `325897ba027c8f8b5041e15e2b21fabc3d4ca4b3c982b79ef92edb0096f1210f`
- Revision 9 case manifest:
  `b9f17c0ea2681cd698b8df4f5ed3bb2a66d3cb94d31376972d136834c6a6a6ad`
- Capability/quota evidence schema:
  `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f`
- Canonical amendment:
  `874f3ce32c160d396814381cee98ad936cb53bbb15f95a5591fecf9af17f82e7`
- PropertyQuarry authority decision:
  `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a`
- PropertyQuarry/Chummer pivot handoff:
  `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06`
- Milestone 1 implementation handoff:
  `be40d2c17ec5290946778b8b96946344c12d7f2b7d2a87501a7a2629f9f71bfe`

## Accepted hash-bound implementation snapshot

- `ea/app/services/governed_spatial_render.py`:
  `f961f9792d166edf58ccc5b2001c8c2f57614e32cb27e6d4061531213524b2a3`
- `ea/app/services/governed_spatial_execution.py`:
  `946d0f535ce7b20d19c8c52e79cbfe98b45b9d9fbed586e4929bbc87d45a423d`
- `ea/tests/test_governed_spatial_render.py`:
  `9c8ef7f3b53f04a51e8e3e702e4a3763eef1c83a152c89cf36290548accf4502`
- `ea/tests/test_governed_spatial_execution.py`:
  `d258e2966ee5f57603d51853c1539c61e0b79e87668966c5fa81f40a876b2245`

The current R11 pair passed `455` tests in one hash-stable offline run. The
legacy handoff slices also passed: EA `52` focused and `77` broader;
PropertyQuarry `84` focused and `97` broader. The controller audit performed
no network, provider, account, quota, browser, server, container, deployment,
publication, promotion, Telegram, or generated-receipt actions.

The repositories remain intentionally dirty and several accepted files are
untracked. This decision accepts only the exact bytes above and makes no claim
that they are committed, deployed, attributable to the failed worker, or
ready for public serving.

## Decision boundary

The missing-worker-receipt process blocker for Milestone 1 is closed by
controller equivalence. Milestone 1 is accepted only as a locally verified,
provider-neutral backend contract and PropertyQuarry bridge.

The following remain blocked and are not waived:

- trusted immutable Artifact Receipt verification and production runtime
  wiring beyond the Milestone 1 no-provider ceiling;
- authoritative numeric PropertyQuarry retention policy and current
  source/style/asset/publication authority receipts;
- accepted provider/vendor walkthrough artifacts, including a current
  3DVista-only browser receipt and any accepted MagicFit result;
- the uncovered `266/299` tour controls and remaining gold-projection gaps;
- post-integration HTTPS desktop/mobile proof, isolated candidate acceptance,
  a 48-hour canary, deployment, publication, promotion, and readiness.

Any later milestone must preserve provider-safe public projections, consume no
quota on audit paths, fail closed when authority or runtime wiring is absent,
and bind its own immutable evidence. This decision is not authority to invent
retention values, call a provider, spend quota, deploy, publish, or promote.
