# Nautobot MCP server — TODO

Handoff for the next session. State as of **2026-11-01**: the server works and Claude Desktop
connects. Read [DESIGN.md](DESIGN.md) (decisions, module table, HTTP design) and
[NAUTOBOT_FINDINGS.md](NAUTOBOT_FINDINGS.md) (verified Nautobot behavior) first.

## Where things stand

- `mcp/nautobot/`: standalone project (like `agent/<name>/`), official `mcp` SDK 2.3.0
  (`MCPServer`, not `FastMCP`), Python 3.12, local `venv/` (git-ignored, installed with
  `pip install -e ../../libs/nautobot_read -e .`).
- **The query logic is not here any more.** Vocabularies, filter building, paging, item shaping and the
  13 queries live in the shared library `libs/nautobot_read/` (own tests, 100 % coverage, own README), which
  the backend's Ask the Net tools use as well (`doc/AI_TOOL_CHAIN.md` §31). This project keeps config, the
  httpx transport, instructions, the HTTP app and one thin wrapper per tool. A change to a query is a change
  in the library: the Ask the Net tools get it too, and their prompt/tests may need the same update.
- 13 read-only tools: organization (6), DCIM (4), IPAM (3). stdio and HTTP transport (static
  per-client bearer tokens), Dockerfile + `docker-compose.example.yml`, `check-image.sh`.
- Quality gate: 93 tests here and 117 in `libs/nautobot_read`, 100 % coverage enforced on both, `ruff` clean,
  `pip-audit` clean.
- Verified live against the dev Nautobot (http://127.0.0.1:8080, v3.2.7): stdio, HTTP as a
  separate process, and the Docker container reached from a second container.
- Committed with the Ask the Net branch (`c273bfd`). GraphQL error text no longer reaches the model: the tool
  error is "Nautobot rejected the query." and Nautobot's wording goes to the server log only.
- The dev token is a read-only key that lives in the user's Claude Desktop config. Never write
  it into a file in the repo. (Tests and probes pass it through environment variables.)

Run the gates from `mcp/nautobot/` (the library's own: `libs/nautobot_read/README.md`):

```bash
./venv/bin/ruff check .
./venv/bin/python -m pytest -q --cov=nautobot_mcp --cov-fail-under=100
./venv/bin/pip-audit -r requirements.txt
./check-image.sh        # needs Docker; no Nautobot required
```

## 1. Do first

- [x] **Remove the silent 5000-row cap.** Done: `list_all` raises `TooManyRowsError` above 5000 rows instead
      of truncating. The queries then fall back where they can (no location tree: a direct lookup by name or
      id, plain names as labels; `libs/nautobot_read/nautobot_read/queries/locations.py`).
- [x] **Commit.** Done (see above).
- [ ] **Run real questions in Claude Desktop** and fix what they show. Suggested set: devices
      of a country, devices by role, IPs of a device, prefixes containing an address, a typo
      in a role name, an ambiguous location name. Note wrong tool choices, slow queries and
      confusing error text; adjust tool descriptions before touching code.

## 2. Verify (open questions about Nautobot)

- [ ] Does the **prefix `location` filter include child locations**? (`devices(location:)`
      does.) Needs a prefix assigned to a location in the dev data; update the `list_prefixes`
      description either way. **This also decides a sentence of the Ask the Net prompt**: it says a prefix
      location filter is not verified to include children (`NAUTOBOT_PROMPT`, `ListPrefixesInput.location`);
      update both when this is answered.
- [ ] Does a **multi-value filter** (`role: ["A","B"]`) behave as OR? The dev data is too small.
      Only matters if tools ever accept lists.
- [ ] Success paths with data: **platform** filter (no device has a platform), **tags**
      (no tag applies to locations or IPs), **IP roles** (Loopback, VIP) on real addresses.
- [ ] **Duplicate device-type model names** across manufacturers make the `device_type`
      filter ambiguous (`DEVICE_TYPES_SPEC` uses the model name only). Handle like locations
      if the production data has duplicates.
- [ ] Run against a **production-sized Nautobot**: startup time (instructions load all
      locations), `list_locations` / `list_devices` paging, GraphQL timeouts (client timeout
      is 30 s).
- [ ] **Pyright** is not installed in the venv; an IDE flagged and I fixed one protocol
      mismatch by inspection only. Run it once (the backend uses pyright as advisory).
- [ ] The **`mcp-ci.yml` workflow has never run on GitHub**, and the Docker build with company
      CA certificates (`certs/`) is untested.

## 3. Features (when wanted)

- [ ] `search_devices(text)` for the "router" case where the word is not a role: additive,
      built on Nautobot's `q` filter, reusing the client, vocabulary cache and `envelope`.
- [ ] Exact totals ("228 IPs") via REST `count`; today only `has_more` exists.
- [ ] More objects: VLANs, racks, tenants, circuits, manufacturers, interfaces as their own
      tool, custom fields, config contexts.
- [ ] Instructions are fixed at startup (the SDK builds them in the constructor); changes to
      the Nautobot vocabulary need a server restart. Only the validation cache refreshes
      (TTL 300 s). Fine for now; revisit if it hurts.

## 4. HTTP hardening and decisions

- [ ] **Per-client rate limits** for the HTTP transport (not implemented).
- [ ] **Token rotation / revocation** workflow (today: edit the secret file and restart).
- [ ] **TLS**: the server speaks plain HTTP. Decide whether a reverse proxy exists in the
      Docker setup (open question 3 in DESIGN.md) and document it.
- [ ] Open decisions from DESIGN.md that could change the design: who the Docker clients are
      (own app vs. third-party tools that expect OAuth), and whether one shared read-only
      Nautobot view is acceptable (vs. per-user permissions).
- [ ] The `httpx` INFO log lines print every Nautobot request URL; consider lowering them if
      logs get noisy. Tokens never appear in logs (verified).

## 5. Docs elsewhere in the repo

- [x] `CLAUDE.md` (Key File Locations) and `doc/claude/development.md` mention the shared library
      `libs/nautobot_read`. Still missing there: a pointer to `mcp/nautobot/doc/DESIGN.md` and `mcp-ci.yml`.
- [ ] Mention the MCP server in `docker/README.md` only if it should be deployed with the app
      stack (it is currently self-contained and not part of `docker/`).

## Lessons from this build (keep in mind)

- The SDK shows the model only `ToolError` text; wrap tools with `@guarded`.
- Nautobot silently ignores some invalid filter values (`prefixes(contains: "zzz")` returns
  everything; `ip_addresses(device:)` matches by exact name only). Validate before querying.
- In `mcp` 2.x a long-lived in-memory `Client` fixture breaks under pytest-asyncio; the tests
  use `McpHarness` (one connection per call).
- Claude Desktop starts the server from an unrelated directory: install the packages
  (`pip install -e ../../libs/nautobot_read -e .`) rather than relying on `PYTHONPATH`.
- A named Docker build context is not covered by the repo-root `.dockerignore`: it reads its own
  (`libs/nautobot_read/.dockerignore`). A `venv/` or `.env` in that directory would otherwise be copied into
  an image layer that a later `rm` cannot shrink.
- Check each new GraphQL query against the live instance before writing the tool.
