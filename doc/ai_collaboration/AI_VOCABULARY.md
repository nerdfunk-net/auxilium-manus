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

## General wiring conventions

**1. Sequence in the sentence = chain in the canvas.** Confirmed from the seed
example below: when a request names two or more Nautobot/inventory-style actions
**in sequence** (e.g. "get the devicelist X **and** the attributes"), the default
interpretation is a **chain**, not parallel branches — an edge from the first
step's `success` outcome to the second step's input, in the order mentioned. This
also happens to be the only wiring the registry allows here:
`get-nautobot-attributes` declares `requires: [identity]`, which only
`get-nautobot-devices`' `produces: [identity]` satisfies, so there is no ambiguity
to resolve for this specific pair — but the "sequence in the sentence = chain in
the canvas" default extends to other same-shaped requests too, absent a signal like
"also", "separately", or "in parallel" suggesting independent branches instead.

**2. Rename `device.name` to the real hostname before any Batfish step, whenever
identity didn't come from Nautobot.** Confirmed 2026-09-27 building the
`onboarding` gallery workflow (see `contributing-data/workflow-gallery/onboarding.json`'s
own notes for the full write-up). `get-from-user`/`get-from-list` set
`device.name` to whatever was typed — often just an IP address, since there's no
inventory system backing either step to supply a real name. But
`batfish-extract-facts` defaults its node filter to `device.name.lower()` *and*
attributes facts back to devices by that same lowercased name, while Batfish's
own node name always comes from the `hostname` line inside the actual parsed
config — never from anything Manus knows beforehand. A bare IP isn't even valid
Batfish node-specifier syntax (a literal 400 from the Batfish API on
`batfish-extract-facts`), and even a name-shaped `device.name` wouldn't
necessarily match. Fix: an `update-attribute` node, `mode: regex`,
`source_path: "parsed.<parse-cisco-config's output_key>.running.hostname"` (or
the equivalent for whichever step parsed the config), `destination_path:
"device.name"`, placed *before* `fan-in`/`batfish-init-snapshot` in the chain —
never after. This also happens to be what lets a later `update-nautobot-device`
(`device_identifier: {mode: from_context}`) correctly resolve an
already-existing device by name, if the workflow has a create-or-update step
downstream (see the "onboard `<device>`" mapping below) — one rename, two
independent payoffs.

**3. A Run Command/Genie scalar field often needs a list index, not just a dot
path.** Also confirmed 2026-09-27, same workflow. TextFSM's output is always a
list of rows, even for a single-row command like `show version` — and several
common ntc-templates fields (`serial`, `hardware`, `mac_address`) are declared
`Value List`, so they're a list *inside* that one row too. Reaching a scalar like
the chassis serial number needs `attribute_path.py`'s numeric-index segment,
`field[N]` (e.g. `parsed.<parsed_output_key>.show version.parsed[0].serial`) —
`field[key=value]` doesn't help here, since there's no per-device field known
ahead of time to filter on, and a multi-item list would be genuinely ambiguous
anyway. Two syntax traps to avoid when writing this by hand instead of using the
attribute picker: a multi-word command like `show version` is a perfectly
ordinary path segment as-is — don't quote or bracket it
(`parsed["show version"]` is wrong; it's treated as one literal, nonexistent
dict key and silently resolves to nothing, no error); and the index form is
`[0]` (a bare digit), not `[]` — an empty bracket isn't recognized at all. A
wrong path here fails **silently** (`update-attribute` just skips that device
for that attribute), so a missing value downstream is the only symptom.

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
2. `get_inventory_by_name(name, username)` for its `id`, `inventory_type`
   (`filter`/`static`), and `conditions` — a live lookup, never a guess.
3. **Default: `inventory_source: "fixed"`** (corrected 2026-09-24 — an earlier
   version of this recipe defaulted to `"run_param"` for every case; that's now
   the exception, not the default — see below). Most workflows run live against
   a named inventory, not on a schedule, so a canvas-time snapshot is what the
   user actually means by "use the inventory named X":
   - `inventory_type == "static"`: set `inventory_id`, `inventory_name`,
     `inventory_type: "static"`, and `device_ids` to the lookup result's
     `device_ids` list verbatim — a plain UUID list, no conversion needed.
   - `inventory_type == "filter"`: set `inventory_id`, `inventory_name`,
     `inventory_type: "filter"`, and `device_filter` to
     `scripts/ai_inventory_filter.py::saved_conditions_to_device_filter(conditions)`
     — a Python port of the frontend's `tree-format-converters.ts` (the piece
     that actually matters is ~25 lines, not the ~180 the whole file suggested;
     verified byte-identical to the real runtime converter's output for the
     real `LAB` inventory, see that module's tests). This *is* a snapshot,
     same caveat as a human picking the inventory in the UI: it won't notice if
     `LAB`'s definition changes later. That's expected "fixed" semantics, not a
     bug — say so in the proposed plan so the user can ask for `"run_param"`
     instead if they'd rather it stay live.
4. **Use `inventory_source: "run_param"` instead when the request says (or
   implies) the workflow will be scheduled, or needs the inventory chosen
   per-run/per-schedule** — that's what it's for. In that case: leave
   `inventory_id`/`inventory_name`/`inventory_type`/`device_filter`/`device_ids`
   at their config defaults, set `inventory_param` to a run-parameter name (the
   registry's own example is `target_inventory`; use a step-specific name if a
   workflow needs more than one), and add a matching `reference`/`inventory`
   `static_attribute` (full replacement of `static_attributes` — merge with
   whatever the workflow already has, never drop existing entries):
   `{"name": "target_inventory", "type": "reference", "ref_kind": "inventory",
   "default": <the resolved id>, "required": false}`. With `default` set, an
   unqualified trigger still resolves to the named inventory
   (`resolve_run_inputs` fills declared defaults) while staying live and
   overridable per-run/per-schedule — this is the right tradeoff specifically
   when scheduling is in view, not as a general-purpose default.
5. **Fan-out threshold — check the live device count, don't guess.** Before
   finalizing the node, call
   `scripts/ai_inventory_filter.py::count_inventory_devices(db, inventory_id=...,
   username=..., nautobot_source_id=...)` — this hits the real Nautobot API via
   the same path the step's own executor uses
   (`NautobotSourceService.analyze_inventory`), since a filter-type inventory's
   true count can only be known by evaluating it live, not by reading the DB.
   - **`device_count <= 10`** (`FAN_OUT_DEVICE_THRESHOLD`): leave `fan_out`
     unset — a single run looping over the device list is fine.
   - **`device_count > 10`**: **stop and ask** whether to enable fan-out, before
     applying anything — don't silently pick either way. If the user says yes,
     use `DEFAULT_FAN_OUT_CONFIG`:
     `{"enabled": true, "mode": "per_device", "chunk_size": 1,
     "max_concurrency": 10}` (the user's own stated default, 2026-09-24 — not a
     per-use-case guess). If they say no, leave `fan_out` unset as above.
6. **Enabling fan-out means re-checking every downstream step for a shared
   sink, not just adding the config block.** Once `fan_out.enabled: true` is on
   the inventory step, everything downstream up to the next `fan-in` node runs
   once *per device*, in parallel, potentially cross-process
   (`doc/WORKFLOW-STEPS.md`'s "Writing concurrency-safe steps"). Per-device
   compute steps (`get-device-configs`, `get-nautobot-attributes`, `run-command`,
   `render-jinja-template`, …) are fine as-is. But `store-artifact` with
   `destination: "git"`, `git-clone`, `git-pull`, `git-push`, and
   `open-change-request` all open **one shared on-disk working tree per git
   repository** — a per-repo lock stops the tree from being *corrupted*, but
   each fanned-out caller still opens its **own commit**, so N devices means N
   commits/pushes, not one. (`store-artifact` with `destination: "filesystem"`
   is the one exception that doesn't strictly need this — it's safe as long as
   `filename_template` is device-unique, which it always is in this recipe.)
   **Rule: insert a `fan-in` node ("Fan In") immediately before the first
   git-touching step in the chain**, wiring per-device steps before it and
   git/store steps after it — exactly the shape `fan-in`'s own registry entry
   documents: *"Place git / store-artifact steps after Fan In for safe,
   single-commit exports."* For the backup workflow's shape (devices →
   attributes → configs → git-pull → store-artifact → git-push), that means
   Fan In goes right after "Get Configs" and before "Git Pull" — so pull,
   write, and push each happen exactly once, over the merged device set, not
   once per device. State this explicitly in the proposed plan whenever
   fan-out is enabled; don't let the extra node be a surprise.

`AI_DEFAULTS.md`'s Inventories table only names the **safe default for an
unspecified first run** (`LAB`) — it is not a general inventory-name-to-id cache. A
request that names an inventory explicitly (as in this example) always gets a
fresh lookup by that name, whether or not it happens to be `LAB`.

### "ask the user for the name or IP address of a device" / "ask the user for a device"

→ One `get-from-user` node ("Get from User"). `requires: []`, so — unlike
`get-nautobot-attributes` — this one *can* be the first node in a branch; it
`produces: [identity]`, same as `get-nautobot-devices`, so the wiring
convention above still applies if the request chains a Nautobot-attributes
step after it.

This step has no Nautobot dependency at all: it reads a plain delimited-text
run input the operator fills in via the Run Inputs dialog when starting the
run (one device per line — hostname, IP address, or `name,ip_address`; see
`workflow_steps/get_from_user/executor.py`), not a live or saved inventory.

1. `device_param` (**required**) — name a run-parameter (the step's own
   registry example is `target_devices`; use a step-specific name if a
   workflow needs more than one prompt-for-device step). Add a matching
   `static_attribute` (full replacement of `static_attributes` — merge with
   whatever the workflow already has, never drop existing entries):
   `{"name": "<device_param>", "type": "string", "required": true}` — required
   because the executor raises if the run input is absent, not optional like
   the reference-type `static_attribute` used for `inventory_param` above.
2. `lookup_mode` — leave unset/`"manual"` (plain multi-line box) unless the
   request implies a Nautobot-backed typeahead (e.g. "let them search for it"),
   in which case use `"nautobot_search"` with `nautobot_source_id` resolved
   from `AI_DEFAULTS.md`'s Sources table — both are UI hints only, never read
   by the executor itself.

### "onboard `<device>`" / "add it to Nautobot, or update it if it's already there"

→ `add-to-nautobot`'s `failure` outcome, routed by `error.code` through a
`route-on-attribute` node, not a plain success/failure branch. Confirmed
2026-09-27 building `contributing-data/workflow-gallery/onboarding.json` — see
its own wiki notes for the full worked recipe (Get from User → parallel
Get Configs+Parse Cisco Config / Run Command → Update Attribute (rename +
extract) → Batfish-for-interfaces → Add to Nautobot → this routing → Update
Nautobot Device).

1. `add-to-nautobot`'s `failure` outcome → one `route-on-attribute` node,
   `attribute_path: "error.code"`. `add-to-nautobot` sets a specific,
   stable code — `device_already_exists` — when the failure is Nautobot's own
   uniqueness-violation 400 (a device with that name already exists at that
   location); every other failure (a missing required field, an unreachable
   source, a permissions error) keeps a different code, so it's
   distinguishable from "already exists" (see `attribute_path.py`'s
   `error.*` namespace and `add_to_nautobot/executor.py::_is_already_exists`).
2. Route `device_already_exists` to an `update-nautobot-device` node
   (`device_identifier: {mode: from_context}` — resolves the existing device
   by name, which is why "General wiring conventions" #2 above, renaming
   `device.name` to the real hostname, matters even more here). Wire
   `add-to-nautobot`'s own `success` outcome to the **same**
   `update-nautobot-device` node too if the workflow
   needs a second write pass after creation (e.g. pushing interfaces
   `add-to-nautobot` didn't set at creation time) — both paths converging on
   one shared node is the pattern the gallery workflow uses, not a
   coincidence.
3. **Leave every other error code an unwired `default_outcome`** (e.g.
   `STOP`) rather than routing it anywhere — an unrelated, unrecoverable
   failure should end the run, not be silently treated as "already exists."
   Say this explicitly in the proposed plan so the user knows a bare
   `default_outcome` name with nothing connected to it is deliberate, not a
   forgotten wire.
4. This `error.code` classification currently exists only on
   `add-to-nautobot` — don't assume another create-oriented step has the same
   `device_already_exists` code without checking its executor first.

### "get the attributes (from nautobot)" / "get nautobot attributes"

→ One `get-nautobot-attributes` node ("Get Nautobot Attributes"), chained after a
device-selection step per the wiring convention above (it `requires: [identity]`,
so it cannot be the first node in a branch).

1. `nautobot_source_id` — same resolved source as the paired devices step.
2. `list_of_attributes` — leave `[]` (core fields only: ID, name, role, device
   type, platform, location, status, …) unless the request names specific
   attribute groups (e.g. "and the interfaces" → add `interfaces` to the list).

### Worked example — the seed for this file

Request: *"Get the devicelist LAB and the attributes from nautobot."* (Live run,
not scheduled — the default case per step 3 above.)

1. `get-nautobot-devices` ("Get from Nautobot"): `nautobot_source_id` resolved from
   `AI_DEFAULTS.md`. Look up the inventory named `LAB` — confirmed live: `id: 1`,
   `inventory_type: "filter"`, with real `conditions`. Config: `inventory_id: 1`,
   `inventory_name: "LAB"`, `inventory_type: "filter"`, `device_filter` from
   `saved_conditions_to_device_filter(conditions)` — verified live to produce the
   exact same device set as the runtime converter (see `ai_inventory_filter.py`'s
   tests).
2. `get-nautobot-attributes` ("Get Nautobot Attributes"): same resolved
   `nautobot_source_id`; `list_of_attributes: []` (nothing beyond "attributes" was
   specified).
3. One edge: node 1's `success` outcome → node 2's input.

No `static_attribute` needed for this one — `"fixed"` mode doesn't add a run
parameter. If the request had instead said "...and run this on a schedule" (or
similar), step 1 would use `inventory_source: "run_param"` per step 4 above, and
a `target_inventory` static_attribute would be added and stated explicitly in the
proposed plan.

---

## Confirmed phrase → template mappings

Same discipline as the step mappings above, but for `ai_template_apply.py`
(`PROCESS.md`'s "The template apply mechanism") instead of a workflow canvas.

### "add a new template" / "add a template named `<NAME>`"

→ Create via `ai_template_apply.py` with no `--template-id`.

- Use the user's exact given name verbatim — **no `[AI Draft] ` prefix.** That
  convention (`AI_DEFAULTS.md`'s "Name prefix" row) is for a name the AI itself
  invents on an unprompted draft; it doesn't apply when the user names the
  template explicitly in the same request.
- `category`/`template_type` default to `netmiko`/`jinja2` (the app's only
  real-world values today) unless the request says otherwise.
- If content isn't fully specified (e.g. "a one-liner"), state the concrete
  content you're about to write as part of the proposed plan in chat before
  applying — same propose-before-apply discipline as everything else in
  `PROCESS.md`, just for a template instead of a canvas patch.

### "edit it" / "edit the template and add `<X>`"

→ Update via `ai_template_apply.py --template-id <id>` with a full new
`content` string — there is no append operation, `content` always replaces the
whole field (see "Critical rule" in `PROCESS.md`'s template apply section).
Re-fetch the template's current `content` first, don't trust what you wrote in
a previous turn.

### Worked example — the seed for this section

Request: *"Add a new template (a one liner) to the templates. Name it
at-collab-test."* then, next turn: *"edit it and add a second line."*

1. Create: `name: "at-collab-test"` (verbatim, no prefix — explicitly named),
   `category: "netmiko"`, `template_type: "jinja2"`, `content: "hostname {{
   hostname }}"` (a one-line Jinja config line, stated in chat before
   applying). Result: template id 7, `created_by: "ai-assistant"`.
2. Edit: re-used the just-created content from the same turn's own output
   (acceptable here since nothing else could have changed it in between) and
   sent the full two-line replacement: `"hostname {{ hostname
   }}\ndescription {{ description }}"`. **In general, prefer a fresh fetch over
   reusing remembered content** — this step happened to be safe only because no
   turn had elapsed where a human could have edited the template via the UI.

---

## Not yet covered

Any phrase not listed above gets the normal `PROCESS.md` treatment: the AI states
its best-guess interpretation as part of the proposed plan (which registry steps,
what wiring, what it resolved and from where) before applying anything, and stops
to ask rather than guess a name it can't resolve. If the guess is confirmed or
corrected, add the resulting mapping here.
