# Workflow recipes: request phrases and the wiring they mean

Confirmed patterns for recurring requests. They supplement `get_workflow_reference` (rules) and
`get_step_schema` (fields): a recipe says which steps a phrase usually means and how to wire them.
Always check each step's fields with `get_step_schema` before using a recipe, and state the steps you
chose (display name and registry id) in your answer so the user can correct you.

## Wiring conventions

1. **Sequence in the sentence is a chain.** "Get the devicelist X and the attributes" is an inventory
   step whose `success` edge leads to the attributes step. Use parallel branches only when the request
   says "also", "separately" or "in parallel".
2. **Rename `device.name` to the real hostname before any Batfish step when identity did not come from
   Nautobot.** `get-from-user` / `get-from-list` set `device.name` to whatever was typed, often an IP.
   `batfish-extract-facts` matches facts by the lowercased `device.name`, while Batfish's node name is
   the `hostname` line of the parsed config. Fix: an `update-attribute` step (`mode: regex`,
   `source_path: parsed.<output_key of the parse step>.running.hostname`, `destination_path:
   device.name`) placed *before* `fan-in` / `batfish-init-snapshot`. The same rename lets a later
   `update-nautobot-device` with `device_identifier: {mode: from_context}` find an existing device.
3. **A scalar from Run Command / Genie output needs a list index.** TextFSM output is a list of rows,
   and fields such as `serial` or `hardware` are lists inside the row. Use the index form
   `parsed.<key>.show version.parsed[0].serial`. A multi-word command is a plain path segment: do not
   quote or bracket it. The index is `[0]`, never `[]`. A wrong path fails silently (the device is
   skipped for that attribute), so double-check it. For a stack member the index can come from the
   device itself: the text inside the brackets may be a `{bag.key}` placeholder, for example
   `parsed.<key>.show version.parsed[0].serial[{virtual_chassis.stack_index}]` or
   `parsed.<key>.show switch detail.parsed[switch={virtual_chassis.position}].role`. Placeholders
   work only inside brackets, and an unresolved one skips the device like a wrong path does.

## Phrase -> steps

### "get the devicelist NAME" / "get devices from NAME" / "select NAME inventory"
One `get-nautobot-devices` ("Get from Nautobot") step.
- NAME is a **saved inventory**. Find it with `list_references(kind="inventories")`; never invent an id.
- Default `inventory_source: "fixed"`: set `inventory_id`, `inventory_name` and `inventory_type`
  (`filter` or `static`) from the listing and leave `device_filter` / `device_ids` at their defaults.
  The step resolves the inventory live on every run, so later edits to the inventory change the
  targets. Do not copy the inventory's filter into the step.
- Use `inventory_source: "run_param"` when the request mentions scheduling or choosing the inventory
  per run: set `inventory_param` (for example `target_inventory`) and add a `static_attributes` entry
  `{"name": "target_inventory", "type": "reference", "ref_kind": "inventory", "default": <inventory id>,
  "required": false}`. `static_attributes` is a full replacement: keep the existing entries.
- `nautobot_source_id` comes from `list_references(kind="sources")`; ask when there are several.
- You cannot count devices. If the inventory may be large (the user mentions many devices), ask
  whether to enable `fan_out` (`{"enabled": true, "mode": "per_device", "chunk_size": 1,
  "max_concurrency": 10}`). Do not enable it silently.
- **Enabling fan-out:** everything up to the next `fan-in` runs once per device. `store-artifact` with
  `destination: "git"`, `git-clone`, `git-pull`, `git-push` and `open-change-request` each make one
  commit per caller, so insert a `fan-in` step immediately before the first git-touching step. For a
  backup workflow that is devices -> attributes -> configs -> **fan-in** -> git-pull -> store-artifact
  -> git-push. Mention the extra step in your answer.

### "ask the user for the name or IP of a device"
One `get-from-user` ("Get from User") step. It needs no upstream step and produces `identity`, so it
can start a branch. It reads a run input, one device per line (hostname, IP or `name,ip_address`).
- Set `device_param` (required, for example `target_devices`) and add the matching
  `static_attributes` entry `{"name": "<device_param>", "type": "string", "required": true}`.
  Required, because the executor fails when the input is missing. Keep existing entries.
- Leave `lookup_mode` unset (plain text box) unless the request asks for a Nautobot search box.

### "get the attributes (from Nautobot)"
One `get-nautobot-attributes` ("Get Nautobot Attributes") step after a device-selection step; it
requires `identity` and cannot start a branch. Same `nautobot_source_id` as the inventory step.
Leave `list_of_attributes` empty (core fields only) unless the request names groups, for example
"and the interfaces" adds `interfaces`.

### "get the stack(s)" / "get the virtual chassis" / "get the switch stack members"
One `get-virtual-chassis` ("Get Virtual Chassis") step; it starts a branch and needs no upstream step.
Same `nautobot_source_id` as the other Nautobot steps.
- `name_filter` + `name_match` (`exact`, `contains`, `regex`) pick the stacks; leave `name_filter`
  empty for all stacks.
- `split_members: false` (default) gives one device per stack, using the master's primary IPv4.
  `split_members: true` gives one device per member, all using that same IP, each with its number in
  `<attribute_bag>.<index_key>` (defaults `virtual_chassis.stack_index`, 0-based).
- Do not invent the regex: the default `index_regex` `:(\d+)` with `index_offset` -1 and
  `index_default` 0 fits names like `LAB.local.zz` and `LAB:2.local.zz`. Change it only when the user
  names a different convention.
- To act on each member after a command (for example update every member's serial), keep
  `split_members: false`, run the command once, then add `split-virtual-chassis` ("Split Virtual
  Chassis"; optional `attribute_bag`, default `virtual_chassis`). It needs an upstream stack device
  and returns the members with their Nautobot ids.

### "onboard DEVICE" / "add it to Nautobot, or update it if it already exists"
`add-to-nautobot` followed by a `route-on-attribute` step on its **`failure`** outcome, not a plain
success/failure branch.
1. `route-on-attribute` with `attribute_path: "error.code"`. `add-to-nautobot` sets the stable code
   `device_already_exists` when Nautobot rejects the name as a duplicate; every other failure keeps
   another code.
2. Route `device_already_exists` to `update-nautobot-device` (`device_identifier: {mode:
   from_context}`; this is why convention 2 matters). If a second write pass is needed after creation,
   wire `add-to-nautobot`'s `success` to the same `update-nautobot-device` step.
3. Leave every other code on the unwired `default_outcome` (for example `STOP`) so unrelated failures
   end the run. Say so in your answer; an unconnected default outcome is deliberate.
4. Only `add-to-nautobot` has this classification. Do not assume another create step sets
   `device_already_exists`.

### "collect X for the report" / "store the serials for reports" / "record the interface states"
One `store-for-report` ("Store for Report") step after the step that makes the data available; it
requires `identity` and has `success` / `failure` outcomes. It feeds the Reports app: the data is
read there by dataset and field name, never by workflow output.
- `dataset`: a short lowercase name (letters, digits, `_`, `-`), one per kind of row. Ask when the
  request does not give one. Reuse the existing name when the user wants to extend or refresh a
  dataset the Reports app already lists.
- `mode: device` (default) for one row per device (serial, model, a count of shutdown interfaces);
  `mode: items` plus `items_path` for one row per list element (each interface, each NTP server), with
  field paths relative to the element (`.` is the element itself).
- `fields`: `name` (lowercase letters, digits, `_`) and `attribute_path` per field. Take every path
  from a tool or from the upstream step's output, never a guess: a path that resolves to nothing is
  stored as empty without an error. For a count of items use `aggregate: count`, optionally with
  `where_field` / `where_equals`. Secret-looking fields or paths (password, community, token) are
  refused.
- Put **all** fields of one dataset into **one** step. A second Store for Report step that writes the
  same dataset for the same device in the same run fails that device, on purpose.
- Wire `success` onward and leave `failure` as the user wants; say which. The step needs no Fan In.
- Tell the user the data appears in the Reports app (Explore) after the first run, and that "which
  devices have none" is answered there by grouping by device name with *Count items* (a device that
  found nothing shows 0); *Count devices* counts every collected device.

## Not covered
For a phrase that is not listed, pick the steps from `list_steps` and `get_step_schema`, say what you
chose and why, and ask when a name or id cannot be resolved with the tools.
