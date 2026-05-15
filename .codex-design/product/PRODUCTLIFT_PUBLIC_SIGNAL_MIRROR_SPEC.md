# Product Signal Mirror Spec

The public routes already stay first-party:

- `/feedback`
- `/roadmap`
- `/changelog`
- `/packages/{packageId}/vote`
- `/packages/{packageId}/follow`
- `/participate/karma-forge`

Mirror contract:

```text
Chummer signal/event
-> ProductSignalReceipt
-> hosted-board projection payload
-> ProductLiftProjectionReceipt
```

Rules:

- hosted-board state never becomes Chummer truth
- private support never mirrors
- roadmap projection never outranks release proof
- package vote/follow mirrors only when the package route is public-safe
- Karma Forge mirrors only from a public-safe summary

Operator-only surfaces may inspect hosted-board references. Public surfaces may not expose provider details.
