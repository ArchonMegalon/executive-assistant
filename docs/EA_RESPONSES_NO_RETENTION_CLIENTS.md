# EA Responses no-retention clients

The Responses proxy supports narrowly scoped service clients that need EA's
central provider/account manager without transferring provider credentials.
This is a runtime provider capability, not product or release authority.

Set `EA_RESPONSES_NO_RETENTION_CLIENTS_FILE` to a root-owned JSON file that is
mounted read-only in the Responses proxy:

```json
{
  "clients": [
    {
      "principal_id": "example-service",
      "token": "replace-with-at-least-32-random-characters"
    }
  ]
}
```

Each configured token is bound to its principal; the caller cannot override
that identity. The token must be different from the normal EA API token.
Requests must include `X-EA-Retention: none`. The proxy then forces synchronous
non-streaming execution, `store=false`, no tools, no previous-response lookup,
and disables response database, debug-capture, and live-summary writes for the
request. A successful reply is returned only when the upstream provider is
`onemin` and includes:

```json
{
  "metadata": {
    "ea_retention": "none",
    "ea_retention_contract": "no_response_storage_no_debug_v1",
    "upstream_provider": "onemin"
  }
}
```

The caller must reject a missing receipt or any other upstream provider. Never
commit the client file, provider keys, service tokens, prompts, or raw replies.
