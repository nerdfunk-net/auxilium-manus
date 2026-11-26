# nautobot-read

Read-only Nautobot queries, independent of how they are called. Two consumers:

- `mcp/nautobot/` wraps each query as an MCP tool.
- `backend/services/ai_assistant/` wraps each query as an Ask the Net tool, with the
  user's permissions and the data-sharing gates.

Some workflow steps read through it too: `get-virtual-chassis` (the virtual-chassis query),
`discover-network` (the client) and `get-device-location` (`location_chain.py`).

## Layout

| Module | Role |
|--------|------|
| `client.py` | `GraphQLClient`: implement `graphql()`; paging (`list_page`, `list_all`) is shared. `NautobotError` |
| `vocabulary.py`, `vocabularies.py` | Name vocabularies, `LocationDirectory`, TTL cache, guiding "closest / available" errors |
| `networks.py` | Validation of IP addresses and prefixes before they reach Nautobot |
| `location_chain.py` | A device's location hierarchy: the GraphQL text (depth 8) and its walk (`find_locations_by_type`, `describe_chain`); pure, the caller runs the query |
| `context.py` | `QueryContext` (client + vocabularies) every query takes |
| `queries/` | One async function per query (`organization`, `dcim`, `ipam`), keyword-only arguments |
| `errors.py` | `EXPECTED_ERRORS`: the errors written for the LLM; a caller turns them into a tool error |

Rules: no `mcp`, no `backend` imports; every name is resolved against a vocabulary before it is
sent (Nautobot fails the whole query on an unknown filter value); no query writes.

## Checks

```bash
pip install -r requirements-dev.txt && pip install -e .
ruff check . && python -m pytest -q --cov=nautobot_read --cov-fail-under=100
```
