# Inventory filter reference

How the inventory builder selects devices, and how to write a filter for `preview_filter` and
`propose_inventory`. A filter is a root (`logic`, `conditions`, `groups`) whose conditions and
groups are combined with the root `logic` (AND or OR). A group is a bracketed set of conditions
with its own `logic` and an optional `negate` that excludes the devices the group matches.
Groups do not nest. Use at most 20 conditions and 10 groups.

A condition is `field`, `operator`, `value` (all text).

## Fields and operators

| field | operators | value |
|---|---|---|
| `location` | equals, not_equals | A location name exactly as Nautobot spells it. Devices in child locations are included (a country returns the devices of its cities). Names are not unique: if two locations share a name, tell the user. |
| `role` | equals, not_equals | Device role name, e.g. `Network`. |
| `status` | equals, not_equals | Device status name, e.g. `Active`. |
| `tag` | equals, not_equals | Tag name. |
| `device_type` | equals, not_equals | Device type model name. |
| `manufacturer` | equals, not_equals | Manufacturer name. |
| `platform` | equals | Platform name. |
| `has_primary` | equals | `true` (device has a primary IPv4 address) or `false`. |
| `name` | equals, contains | Device name or a part of it. |
| `ip_prefix` | within_include, within, exact | A CIDR prefix such as `10.0.0.0/8`: devices with an address in it. |
| `primary_prefix` | within_include | A CIDR prefix: devices whose primary address is in it. |
| `cf_<name>` | equals, contains | A custom field value. |

`location` never supports `contains`: "City" would also match "City A".

## Writing a filter

1. Find the real names first with `list_field_values` (role, status, location, tag, platform,
   device_type, manufacturer). Never invent a value; names are matched case-insensitively and the
   tool corrects the spelling, but a name that does not exist is an error.
2. Words like "router", "switch" or "network devices" may be a role, a device type or a platform in
   this instance. Look at the lists; if more than one fits, ask the user which they mean.
3. Put everything the user wants to be true together in `conditions` with `logic` AND.
4. "A or B" for the same field: a group with `logic` OR (or the root `logic` OR when everything is
   an alternative).
5. "Not X" / "except X": a condition with `not_equals`, or a group with `negate` true for several.
   A filter made only of negated groups matches nothing; it needs one positive condition.
6. Call `preview_filter`. Check the count against what the user expects ("all network devices in
   City A" returning 3 000 is suspicious). A count of 0 can also mean Nautobot could not be queried.
7. Call `propose_inventory` with a one-line summary. The user reviews it in the inventory builder
   and saves it themselves; you cannot save.

## Glossary

A word the user used that matches no Nautobot name ("core", "DC") may be defined by the
administrators. Call `get_glossary` with the word. It returns a filter fragment (`conditions` and
`groups`): merge it into the filter you build, keeping the user's other conditions. A `stale` entry
names a value Nautobot no longer has; check `list_field_values` and ask the user instead of using it.
No entry means ask which Nautobot name they mean.

## Recipes

- "all network devices in City A with a primary IP":
  `role equals Network`, `location equals City A`, `has_primary equals true`.
- "... and status Active": add `status equals Active`.
- "everything in City A except lab devices": `location equals City A` plus a group with
  `negate` true containing `tag equals lab`.
- "devices in City A or City B": a group `logic` OR with the two locations, plus the other conditions
  at the root.
- "switches whose name starts with sw": `name contains sw` (there is no starts-with).
