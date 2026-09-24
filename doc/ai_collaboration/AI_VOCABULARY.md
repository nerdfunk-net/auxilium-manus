# AI_VOCABULARY.md

A glossary mapping the user's own recurring shorthand phrases to the exact registry
steps and wiring they mean, so the AI collaborator's first-draft interpretation of a
request matches their intent more often — see `doc/ai_collaboration/PROCESS.md`'s
"Turn-taking discipline" for why this doesn't replace, only supplements, that
safety net.

## What this is (and isn't) for

Three docs govern an AI collab session, each answering a different question:
- `PROCESS.md` — *how* the collaboration mechanically works (identity, consent,
  apply script, propose-before-apply discipline). Required reading every session.
- `AI_DEFAULTS.md` — *which concrete value* to use for a name/category the user
  didn't spell out (which credential, which git repo, which source, the safe
  inventory for a first run). Required reading every session.
- **This file** — *which steps and wiring* a recurring phrase actually means, and
  *what else the user calls a given step* beyond its registry `id`/display `name`
  (aliases). Also required reading every session, but deliberately small: it is a
  glossary of **confirmed** mappings, not an attempt at a general natural-language
  grammar. Natural language is infinite; this file will never cover everything,
  and it isn't supposed to try.

**This does not replace `PROCESS.md`'s propose-before-apply step.** Even when a
phrase matches an entry below, the AI still states the concrete plan (steps, order,
config, wiring) in chat before calling `ai_workflow_apply.py`, exactly as
`PROCESS.md`'s loop step 4 already requires — this file just makes that first guess
more likely to be right, so fewer round-trips are needed to correct it.

**How entries get added.** Whenever the AI's proposed interpretation of a phrase
turns out to be wrong (the user corrects it) or right-but-only-confirmed-once (the
user explicitly confirms an unlisted phrase), add or update an entry here — same
"record from correction and from confirmation" discipline as any other feedback.
The same rule covers step **aliases** (see "Naming" below): the first time the
user refers to a step by a name that's neither its registry `id` nor its display
`name`, add it as an alias, don't wait for a second occurrence. Don't pre-populate
this file with speculative phrase mappings or aliases that haven't actually been
used and confirmed; an unconfirmed one gets proposed as a best guess in chat per
`PROCESS.md`, not silently assumed from a guess written down here.

---

## Naming: registry id, display name, and aliases

Every step already has two names that don't always match — its registry `id`
(e.g. `get-nautobot-devices`, kebab-case, stable, referenced everywhere in code,
config, and saved workflows) and its frontend display `name` (e.g. "Get from
Nautobot", editable, shown in the canvas). Talking past each other by using one
without the other is exactly the "trap" this section exists to prevent — bad
enough in one real case (`batfish-start-run` for a step whose display name was
"Get from Batfish") that the id itself was renamed to `get-batfish-devices`
instead of just documenting the mismatch; `get-pyats-config` → `get-pyats-running-config`
was the other. Most steps aren't that bad, but the id and the display name are
still two different strings, and citing only one of them is how this confusion
starts.

**The canonical id ↔ display-name mapping is `registry.yaml` itself** (`id:`/
`name:` per entry) — look it up fresh, never assume it or duplicate it here as a
full table. With ~140 steps, a copied table would go stale the moment one is added
or renamed, exactly the staleness risk this whole file exists to avoid elsewhere.

**Always cite both together** when a step comes up in a proposed plan or in chat —
"Get from Nautobot (`get-nautobot-devices`)", never the id or the display name
alone. This isn't just politeness: it's what makes a third name — an alias —
visible in the first place. If the user's own wording matches neither half of that
pair, it's an alias, and gets recorded below.

### Confirmed aliases

A user may have their own personal shorthand for a step — a nickname, an
abbreviation, a term carried over from another tool — that matches neither its
`id` nor its display `name`. Record it here the first time it comes up, same
discipline as the rest of this file: confirmed usage only, never pre-populated
speculatively. One step can have more than one alias; add a row per alias.

| Alias | Registry `id` | Display name |
|---|---|---|
| *(none recorded yet)* | | |

---

## General wiring convention

Confirmed from the seed example below: when a request names two or more Nautobot/
inventory-style actions **in sequence** (e.g. "get the devicelist X **and** the
attributes"), the default interpretation is a **chain**, not parallel branches — an
edge from the first step's `success` outcome to the second step's input, in the
order mentioned. This also happens to be the only wiring the registry allows here:
`get-nautobot-attributes` declares `requires: [identity]`, which only
`get-nautobot-devices`' `produces: [identity]` satisfies, so there is no ambiguity
to resolve for this specific pair — but the "sequence in the sentence = chain in
the canvas" default extends to other same-shaped requests too, absent a signal like
"also", "separately", or "in parallel" suggesting independent branches instead.

---

## Confirmed phrase → step mappings

### "get the devicelist `<NAME>`" / "get devices from `<NAME>`" / "select `<NAME>` inventory"

→ One `get-nautobot-devices` node ("Get from Nautobot").

`<NAME>` is a **saved inventory name** (Settings → Inventories / the workflow
builder's inventory picker), not a Nautobot filter to invent from scratch. Resolve
it with a live lookup — never guess. There is no HTTP path for this (the AI actor
never has a browser session/JWT — see `PROCESS.md`'s "AI actor identity"), so do it
the same way `scripts/ai_defaults.py` resolves its own entries: a small one-off
script using
`services.sources.nautobot.persistence_service.InventoryService.get_inventory_by_name(name, username)`.

1. `nautobot_source_id` — resolve via `AI_DEFAULTS.md`'s Sources table (`nautobot`),
   same as any other Nautobot step.
2. `get_inventory_by_name(name, username)` for its `id` and `inventory_type`
   (`filter`/`static`) — mainly to confirm the name actually exists (fail loudly,
   don't guess, if it doesn't) and to get the id for step 4.
3. **Target it via `inventory_source: "run_param"`, not `"fixed"` — regardless of
   `inventory_type`.** This resolves the named inventory's *live* definition at
   run time (`NautobotSourceService.resolve_saved_inventory_devices_by_id`, which
   internally calls `utils/inventory_converter.py::convert_saved_inventory_to_operations`
   for a `"filter"`-type inventory, or reads `device_ids` directly for
   `"static"`) — a real, full, **backend-native** resolution path, not a
   workaround. It is arguably the more correct reading of "use the inventory named
   `LAB`" than `"fixed"` mode would be: `"fixed"` mode freezes a canvas-format
   snapshot of the filter at authoring time (only ever produced by the frontend's
   condition-builder UI — there is no backend equivalent that produces that
   specific snapshot shape), so it can silently drift from `LAB`'s current
   definition if `LAB` is edited later; `"run_param"` always reflects the
   inventory's current, live database state.
4. Add a `reference`/`inventory`-type `static_attribute` to the workflow (full
   replacement of `static_attributes`, per `PROCESS.md`'s patch-shape rules — merge
   with whatever the workflow already has, never drop existing entries):
   `{"name": "target_inventory", "type": "reference", "ref_kind": "inventory",
   "default": <the resolved id>, "required": false}` — `"target_inventory"` is the
   registry's own example name for this pattern; use a step-specific name
   (`target_inventory_devices`, `target_inventory_backups`, …) if the workflow
   needs more than one. Set the node's `inventory_param` to that same name and
   `inventory_source` to `"run_param"`.
5. Leave `inventory_id`/`inventory_name`/`inventory_type`/`device_filter`/
   `device_ids` at their config defaults (unused by the executor in `run_param`
   mode) and `fan_out` unset unless the request implies per-device parallel
   processing.

With the `default` set, a manual trigger that supplies no override resolves to
`LAB` automatically (`resolve_run_inputs` fills declared defaults) — in practice
this behaves exactly like "always target `LAB`," while remaining live and,
unlike `"fixed"` mode, overridable per-run/per-schedule without editing the
canvas. Say this explicitly in the proposed plan (per `PROCESS.md`'s
propose-before-apply step) so the user can object if they specifically want a
frozen, non-overridable snapshot instead — that narrower case genuinely has no
safe backend-only path today (it would need the frontend's
`savedConditionsToFilterTree` tree-format conversion, `frontend/.../inventory/
utils/tree-format-converters.ts`, ported to Python; not done, out of scope unless
requested).

`AI_DEFAULTS.md`'s Inventories table only names the **safe default for an
unspecified first run** (`LAB`) — it is not a general inventory-name-to-id cache. A
request that names an inventory explicitly (as in this example) always gets a
fresh lookup by that name, whether or not it happens to be `LAB`.

### "get the attributes (from nautobot)" / "get nautobot attributes"

→ One `get-nautobot-attributes` node ("Get Nautobot Attributes"), chained after a
device-selection step per the wiring convention above (it `requires: [identity]`,
so it cannot be the first node in a branch).

1. `nautobot_source_id` — same resolved source as the paired devices step.
2. `list_of_attributes` — leave `[]` (core fields only: ID, name, role, device
   type, platform, location, status, …) unless the request names specific
   attribute groups (e.g. "and the interfaces" → add `interfaces` to the list).

### Worked example — the seed for this file

Request: *"Get the devicelist LAB and the attributes from nautobot."*

1. `get-nautobot-devices` ("Get from Nautobot"): `nautobot_source_id` resolved from
   `AI_DEFAULTS.md`. Look up the inventory named `LAB` — confirmed live, `id: 1`
   (this is that inventory's own row data; `AI_DEFAULTS.md` separately happens to
   name `LAB` as the *safe default for an unspecified run*, but that's a
   coincidence here, not why it was looked up). Config:
   `inventory_source: "run_param"`, `inventory_param: "target_inventory"`.
2. Add `static_attribute`: `{"name": "target_inventory", "type": "reference",
   "ref_kind": "inventory", "default": 1, "required": false}` (merged with any
   existing `static_attributes` on the workflow).
3. `get-nautobot-attributes` ("Get Nautobot Attributes"): same resolved
   `nautobot_source_id`; `list_of_attributes: []` (nothing beyond "attributes" was
   specified).
4. One edge: node 1's `success` outcome → node 2's input.

State step 2 explicitly in the proposed plan — it's the one piece of workflow
structure ("a `target_inventory` run parameter, defaulting to `LAB`") that isn't
obviously implied by the sentence, even though it behaves as a hardcoded target
unless someone deliberately overrides it at trigger/schedule time.

---

## Not yet covered

Any phrase not listed above gets the normal `PROCESS.md` treatment: the AI states
its best-guess interpretation as part of the proposed plan (which registry steps,
what wiring, what it resolved and from where) before applying anything, and stops
to ask rather than guess a name it can't resolve. If the guess is confirmed or
corrected, add the resulting mapping here.
