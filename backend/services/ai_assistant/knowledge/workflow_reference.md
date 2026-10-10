# Authoring workflows in Auxilium Manus

Distilled from `doc/WORKFLOW-STEPS.md` and the validation rules. You work with a **compact plan**;
the server turns it into the real canvas (positions, sizes, registry data, edge handles).

## The plan
- `nodes`: `{id, kind, title?, config, disabled?}`. `kind` is a registry step id (see `list_steps`),
  `config` is that step's configuration (see `get_step_schema`). Ids are yours to choose
  (letters, digits, `-`, `_`). **Keep the existing id for a step you keep**; a node's `kind` can never
  change - use a new id for a different step.
- `edges`: `{from, outcome, to}`. An edge leaves a step through one of its **outcomes** (usually
  `success` or `failure`; `get_step_schema` lists them) and enters the next step.
- `static_attributes`: optional full replacement of the workflow's run inputs (see below). Omit it to
  leave them unchanged.
- Always send the **complete** plan, not a diff: every step and edge the workflow should have.
- A step with no outgoing edge for an outcome simply ends that branch. Wire `failure` only when you
  handle it.
- The workflow must be acyclic. Layout is automatic for new steps.

## Choosing steps
- Never guess a step id or config field: call `list_steps`, then `get_step_schema` for each step you
  use. Config fields not in the schema are rejected by validation.
- When you tell the user about a step, name it with **both** its display name and registry id, for
  example "Get from Nautobot (`get-nautobot-devices`)".
- Sequence in the request usually means a chain: "get the devices and their attributes" is
  inventory step -> attributes step.

## Capability flow (the main source of validation errors)
Each step declares `requires`, `produces` and `consumes` capabilities (for example `identity`,
`attributes`, `running_config`, `parsed`). An edge is valid only when everything the target `requires`
is already available from upstream. Typical order:
1. an **inventory step** that produces `identity` (for example `get-nautobot-devices`,
   `get-git-devices`, `get-ise-devices`, `get-from-list`, `get-from-user`);
2. steps that enrich devices (attributes, configs, parsed data);
3. steps that act on or export them (render, deploy, store, notify).
A `failure` outcome carries the step's *input* capabilities (the work did not happen), not its output.
Where two parents join, only capabilities guaranteed on **every** incoming branch count.

## Fan-out and fan-in
- An inventory step can enable `fan_out` in its config so each device (or chunk) runs as its own child
  workflow: `{enabled, mode: "per_device"|"chunked", chunk_size, max_concurrency, approval}`.
  `max_concurrency` 0 = unlimited, 1 = sequential. `approval.enabled` pauses between batches for a
  human to release the next batch (canary rollouts).
- When fan-out is on, put per-device work (configs, commands, rendering) **before** one `fan-in` step
  and git / store-artifact / push steps **after** it, so exports commit exactly once.
- At most one `fan-in`, no nested fan-out, and `stop-here` must not sit between a fanned-out inventory
  step and its `fan-in`.

## Static attributes (run inputs)
Declared per workflow as `{name, type, ref_kind?, default, required}` with `type` one of `string`,
`number`, `boolean`, `reference`. A `reference` needs `ref_kind` `inventory` (value = inventory id) or
`credential` (value = credential name). Values are available to templates and steps as `run_input.<name>`
and let one workflow serve many inventories or credentials (for example an inventory step with
`inventory_source: "run_param"` and `inventory_param: "<name>"`).

## References must be real
Credentials, git repositories, sources and saved inventories are referenced by id or name in step
config. Always get the real values from `list_references`; never invent one. Git steps use a numeric
`git_repository_id`; sources are referenced by their name. Validation fails loudly on a reference that
does not exist or has the wrong type.

## Secrets
Never ask the user to paste a password, key or token. Secret-looking values in the current workflow
appear as `__SECRET_n__` tokens: keep a token unchanged to keep that value, delete it to remove it.
Reference credentials by name instead of embedding secrets in step config.

## Validation you will be told about
`propose_workflow` runs the same checks as saving and running: **schema** (required config fields),
**references** (credential / git / source / inventory exist), **capability flow** (above) and
**attribute-path wiring** (a `parsed.<node-id>...` path must point at an upstream step). Errors must be
fixed before a proposal is shown; warnings are shown to the user.
