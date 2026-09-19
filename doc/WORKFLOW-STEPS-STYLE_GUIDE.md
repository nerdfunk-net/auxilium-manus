# Workflow Step Style Guide

Reference implementation: `get-nautobot-devices/`

---

## Color palette

All steps use the **step** token family from `frontend/src/app/globals.css` (teal). Never use raw `teal-*`, `sky-*`, `blue-*`, or arbitrary hex colors.

| Role | Class | Usage |
|---|---|---|
| Card / dialog header | `step-header` | Gradient bar; sets header text color |
| Header muted text | `text-step-header-muted` | Counts, helper text on the header |
| Header badge / pill | `bg-step-header-foreground/20 text-step-header-foreground` | Counts, labels in header |
| Primary action button | `bg-step text-step-foreground hover:bg-step-hover` | Round `+` / submit button |
| Selected row / item | `bg-step-surface text-step-surface-foreground` | Active state in lists/sidebars |
| Accent icons | `text-step` | Folder, status icons |
| Info banner | `bg-step-surface text-step-surface-foreground` | Contextual hint strips |
| Info badge border | `border-step-border` | Pill borders inside info banners |
| Focus ring | `focus:ring-step/40` / `focus-visible:ring-step/40` | Inputs, selects |
| Checkbox accent | `accent-step` | Native checkboxes |
| Unconfigured hint | `text-[11px] text-warning-foreground` | Missing source / incomplete config |

---

## Card anatomy

```
┌─────────────────────────────────────┐
│  Header (.step-header)              │  py-2.5 px-4, font-semibold
├─────────────────────────────────────┤
│  Body (bg-muted)                    │  overflow-y-auto, space-y-4, p-4
│   • warning banner (bg-warning)     │  when source not configured
│   • main content                    │
│   • preview results                 │
├─────────────────────────────────────┤
│  Footer (bg-card, border-t)         │  flex-wrap gap-2, px-4 py-3
└─────────────────────────────────────┘
```

- Outer wrapper: `rounded-xl border border-border bg-card shadow-sm`
- Dialog variant: `rounded-none border-0 shadow-none` (strip rounding/border when inside a Dialog)

---

## Canvas node (React Flow)

Reference implementation: `components/features/workflows/components/nodes/workflow-node.tsx`

Every workflow step shares **one** canvas renderer. Step authors implement the
`ConfigPanel` only — they do **not** create a separate canvas component or a custom
render branch for their step.

When a user drags a step onto the canvas, React Flow renders it through `WorkflowNode`.
The node's look is driven entirely by registry metadata (`name`, `description`,
`artifact_type`, `outcomes`) plus optional icon and fan-out configuration.

### Fixed size — all nodes equal

All canvas nodes use the same width and height. Never override dimensions per step.

| Property | Tailwind class | Value |
|---|---|---|
| Width | `w-80` | 320 px |
| Height | `h-32` | 128 px |

The card wrapper is `rounded-xl border bg-card shadow-sm`. Do not use `w-64`, `w-72`,
`min-h-*`, or step-specific sizing — inconsistent nodes were a recurring bug when
individual steps (e.g. `merge-content`, `compare-data`) had their own render paths.

### Title and description

| Field | Source | Canvas rule |
|---|---|---|
| Title | Registry `name` → `data.title` | **Must be fully visible.** Use `text-sm font-semibold leading-snug` and let the title wrap. Never use `truncate` or `line-clamp-1` on the title — long names such as "Get Nautobot Attributes" must not be cut off with an ellipsis. |
| Description | Registry `description` → `data.description` | `line-clamp-2 text-xs leading-5 text-muted-foreground` — at most two lines; overflow is acceptable here. |

Right padding depends on outcome count: `pr-10` when the step has a single source handle,
`pr-24` when it has multiple outcomes (room for outcome labels on the right edge).

### Connection handles

All handle dots use `!size-3 !border-2`. Input and output handles use different colours
so upstream wiring is visually distinct from branching outcomes.

#### Input handle (target, left edge)

Shown when the step's registry `requires` list is non-empty (the step accepts upstream
input). One handle centred on the left edge (`id="input"`, `type="target"`).

| Role | Tailwind classes |
|---|---|
| Input handle | `!bg-muted-foreground/40 !border-muted-foreground` |

Defined once as `TARGET_HANDLE_CLASS` in `workflow-node.tsx`. Always light gray — never
match outcome green/red styling.

#### Output handles (source, right edge) — success and failure colors

Outcome names come from the step's `outcomes` list in `registry.yaml`. The shared
renderer colours labels and source handles automatically:

| Outcome name (case-insensitive) | Label pill | Handle dot |
|---|---|---|
| `success`, `match`, `pass` | `bg-success text-success-foreground border border-success-border` | `!bg-success-foreground !border-success-foreground` |
| `failure`, `fail`, `error`, `mismatch` | `bg-error text-error-foreground border border-error-border` | `!bg-error-foreground !border-error-foreground` |
| `default` | `bg-warning text-warning-foreground border border-warning-border` | `!bg-warning-foreground !border-warning-foreground` |
| anything else | `bg-info text-info-foreground border border-info-border` | `!bg-info-foreground !border-info-foreground` |

Rules:

- Prefer standard outcome names (`success` / `failure`, or `match` / `mismatch` /
  `failure` for compare steps) so green/red styling applies without extra code.
- Outcome **labels** are shown only when `outcomes.length > 1`. A single-outcome step
  still gets a coloured source handle; the label is omitted to save space.
- Handles are stacked vertically on the right edge; labels sit just left of each handle.

#### Configurable handle sides

The side each handle group attaches to is editor-only canvas metadata, set per node on
the General tab of `node-config-modal.tsx`: `incomeHandleSide` (default `"left"`) for
the input handle and `outcomeHandleSide` (default `"right"`) for all outcome handles.
Both accept any of `"top" | "bottom" | "left" | "right"` (`HandleSide` in
`types/workflow-canvas.ts`) and are resolved independently in `workflow-node.tsx`.

- **Income has priority**: `outcomeHandleSide` can never equal `incomeHandleSide`. The
  outcome `Select` disables whichever option currently matches income; if the user
  changes income to the side outcome currently occupies, outcome is swapped away
  automatically (`workflow-builder-page.tsx`'s `handleIncomeHandleSideChange`).
- Content padding, outcome label placement, and the `useUpdateNodeInternals` remeasure
  effect all key off these two fields (not a single shared orientation flag), so each
  side can be picked independently — e.g. income on top, outcomes on the left.
- Legacy canvases saved with the older single `portOrientation` (`"horizontal"` /
  `"vertical"`) field are migrated on load in `migrate-canvas.ts` to the equivalent
  `incomeHandleSide`/`outcomeHandleSide` pair.

### Step icon

Icons are resolved in `workflow-node.tsx`:

1. **Kind override** — add an entry to `nodeIconsByKind` when the generic
   `artifact_type` icon is not distinctive enough (e.g. `merge-content` → `Combine`,
   `compare-data` → `Scale`, `filter-output` → `Filter`, `fan-in` → `GitMerge`).
2. **Default** — `nodeIconsByType[artifact_type]` (e.g. `command_execution` → terminal,
   `inventory_selector` → router, `control_flow` → branch).
3. **Fallback** — `Database`.

Icon sits in a `size-10 rounded-lg` tile coloured by `artifact_type` via
`nodeAccentClassesByType` (e.g. `control_flow` → amber, `command_execution` → emerald).

When adding a new step, only add a `nodeIconsByKind` entry if the default
`artifact_type` icon is misleading. Do **not** fork the whole node layout.

### Fan-out badge on the canvas node

When an inventory node has `pluginConfig.fan_out.enabled === true`, the canvas node renders
a small "Fan out" badge next to its title so the active split is visible at a glance:

- `<Badge variant="outline" className="gap-1 border-step-border bg-step-surface text-step-muted-foreground">` with
  a `<Split className="size-3" aria-hidden />` icon. Step tokens only — no `sky-`/`blue-`/`teal-*`.

### What step authors implement

For a new step, frontend work is **only**:

1. `frontend/src/components/features/workflow-steps/{step-id}/index.tsx` — export
   `PluginUIComponent` with a `ConfigPanel`.
2. `frontend/src/lib/plugin-ui-registry.ts` — register the step id.
3. Optionally one line in `nodeIconsByKind` inside `workflow-node.tsx`.

Do **not** add per-step canvas JSX, duplicate handle wiring, or hard-coded titles/descriptions
on the canvas — those belong in `registry.yaml`.

### Canvas node — do not

- ❌ Custom `if (data.kind === "my-step")` render branches in `workflow-node.tsx`
- ❌ Different width/height/padding per step kind
- ❌ `truncate` or ellipsis on the node title
- ❌ Per-node status badges (`Draft`, `Ready`, …) — workflow save state lives in the
  top bar (`workflowStatus`), not on individual nodes
- ❌ Hard-coded description text on the canvas instead of registry `description`

### Exception — canvas decorations

`label` and `background` (`artifact_type: canvas_decoration`, `executable: false`)
are **not** rendered by `WorkflowNode`. They use dedicated React Flow node types
(`labelNode`, `backgroundNode`) with configurable width/height and no connection
handles. Background nodes use a low `zIndex` so they stay behind other steps.

Rules that still apply:

- ConfigPanel / HelpPanel use the same teal chrome as other steps
- Never add handles or outcomes
- Never register an executor — `StepRunner` skips them

Do **not** use this exception for executable steps. New real steps must stay on the
shared `WorkflowNode` renderer.

---

## Node config modal tabs

Reference implementation: `secret-generate/index.tsx` (Configuration + Help panels) plus
the shared `node-config-general-tab.tsx` / `node-config-description-tab.tsx`. Opening a
step from the canvas shows a modal (`node-config-modal.tsx`) with up to four tabs:
**General**, **Configuration**, (optional plugin-defined tabs), **Description**, **Help**.
Each tab has one job — do not let step-specific "what does this do" text leak into
Configuration.

### General tab — shared, never forked per step

`node-config-general-tab.tsx` renders identically for every step. At the top, above the
Step name field, it shows the step's registry description in **default black/foreground
text, no colored banner**:

- Bold headline: registry `overview` → `<p className="text-sm font-medium text-foreground">`
- Body paragraph: registry `description` → `<p className="text-xs leading-5 text-foreground">`

This is automatic from `activeNode.data.overview` / `activeNode.data.description` — step
authors never add this themselves and never fork this component per step.

### Configuration tab — configuration fields only

The step's `ConfigPanel` renders here. It must contain **only configuration controls**
(connection pickers, path templates, selects, switches, etc.) — never a "what this step
does" banner. That explanation already lives on the General tab (above) and the
Description tab (below); duplicating it as a `bg-step-surface` info banner at the top of
`ConfigPanel` is a legacy pattern and should be removed when found (see the **Config
panel** section below for what a step's `ConfigPanel` content should look like instead).

### Description tab — shared, never forked per step

`node-config-description-tab.tsx` renders identically for every step, built entirely from
registry metadata: title + description, a **Capabilities** block (Produces / Consumes), a
**Schema** block (Configuration inputs / Requires / Outcomes), and — at the bottom — an
**Artifact Type** section:

- `<SectionHeader icon={Tags} label="Artifact Type" />`
- `<Badge variant="secondary">{formatArtifactType(activeNode.data.artifactType)}</Badge>`

Step authors do not touch this component; it needs no per-step work.

### Help tab

Per-step `HelpPanel` — see the **Checklist** below.

---

## Config panel (node side-panel)

The `ConfigPanel` component renders inside the React Flow node property panel — it is narrow (~220 px) and must stay compact.

- Use `space-y-1.5` for label → hint → button stacking
- Labels: `font-mono text-xs font-medium` for parameter names
- Badges: `<Badge variant="secondary">` for type hints (`nautobot`, `filter tree`, …)
- Status hint (configured): `text-[11px] text-muted-foreground truncate`
- Status hint (unconfigured): `text-[11px] text-warning-foreground`
- Action button: `<Button variant="outline" size="sm" className="h-7 w-full text-xs">`
- No step description banner at the top — see **Node config modal tabs** above; the
  General tab already shows the registry `overview`/`description` in default black text

---

## Attribute path fields — Browse attributes picker

Any input whose value can be a `{path}`-style attribute reference (e.g.
`{nautobot.origin}`, `{custom.site}`, `{parsed.cisco_config.running.hostname}`) must
offer the shared **Browse attributes** picker next to it, not just a bare text input.
Reference implementations: `route-on-attribute/index.tsx`, `update-config-context/index.tsx`,
`config-to-attributes/index.tsx` (`parsed_key`), and `update-nautobot-device` (every
`update_fields`/`custom_fields` value, via `shared/nautobot-field-rows.tsx`).

- Component: `workflow-steps/shared/attribute-path-picker.tsx`'s `AttributePathPicker` —
  never fork or reimplement it per step. It browses real attribute values discovered from
  the workflow's most recent run, scoped to the current node's canvas ancestors.
- Trigger: a small icon-only button next to the field, using the shared icon-button
  pattern — `<Button variant="outline" size="icon" className="size-8 shrink-0" title="Browse attributes"><Search className="size-3.5" /></Button>` —
  never a full-width "Browse attributes" text button crammed into a narrow row.
- Wiring: give the `ConfigPanel` a `pickerOpen` (or, for a field-set with many pickable
  inputs like Update Device's per-field rows, a `pickerTarget` naming *which* field is
  being edited) piece of state; open it on the icon's `onClick`; on `onSelect(path)`,
  patch the target field's value and close. Pass `nodeId`, `workflowNodes`, and
  `workflowEdges` straight through from `PluginConfigPanelProps` — never re-derive them.
- One field's value isn't always the whole picked path: `config-to-attributes`'s
  `parsed_key` only wants the segment right after the fixed `parsed.` namespace, so its
  `onSelect` extracts that one segment (`parsedKeyFromAttributePath`) instead of using
  the raw path verbatim. Transform the picked value to fit the field, don't change the
  picker.
- For a field type reused across steps (e.g. the Nautobot field-value rows in
  `shared/nautobot-field-rows.tsx`), add the picker to the **shared** row component as an
  optional `onBrowse?: () => void` prop (button hidden when omitted) — one dialog instance
  owned by the parent panel serves every row, rather than each row managing its own
  picker state.
- You never need to filter what the picker shows for your own step: the backend
  discovery service (`services/workflow_context/attribute_path_discovery.py`) already
  collapses raw, non-browsable blobs (e.g. Genie's raw `show running-config` parse tree,
  keyed by literal CLI lines) into a single opaque leaf — a new step's parsed output
  doesn't need special-casing there unless it introduces a genuinely new "this dict is
  not real field data" shape.

---

## Fan-out config (inventory steps)

Inventory steps (`get-nautobot-devices`, `get-git-devices`) expose a **fan-out** block at
the bottom of their `ConfigPanel`. Reference implementation:
`get-nautobot-devices/index.tsx`. Keep every inventory step's fan-out UI identical:

- Separate the block with `border-t pt-3` and wrap controls in `space-y-2`.
- Header row: `flex items-center justify-between` with a `font-mono text-xs font-medium`
  `fan_out` label on the left and a Shadcn `<Switch>` on the right.
- One-line helper under the header: `text-[11px] text-muted-foreground`.
- Reveal Mode / Chunk size / Max concurrency **only when enabled**, indented with `pl-1`.
- Sub-field labels: `<Label className="text-[11px] text-muted-foreground">`.
- Mode uses a Shadcn `<Select>` (`h-7 text-xs`); numeric fields use `<Input type="number">`
  with `h-7 font-mono text-xs` and a `min` of `1` (chunk size) or `0` (max concurrency).
- Hold defaults in a module-level `DEFAULT_FAN_OUT` constant and patch immutably through a
  single `useCallback` handler (`{ ...config, fan_out: { ...fanOut, ...patch } }`).

> Fan-out has real backend consequences (each device/chunk runs as an isolated child
> workflow). Before adding it to a step, read the **Fan-out execution** section of
> `WORKFLOW-STEPS.md` — git/filesystem sinks are not automatically fan-out-safe.

### Fan-in node config panel

The **Fan In** node (`fan-in`) has no configuration. Its `ConfigPanel`
(`workflow-steps/fan-in/index.tsx`) is info-only:

- A single step info banner (`rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground`)
  explaining the rejoin, plus a `text-[11px] text-muted-foreground` hint to place git/store
  steps after it. No inputs, no `onChange`.

---

## Dialogs

- Use `<Dialog>` from Shadcn.
- Wide dialogs (filter builder): `max-w-4xl h-[85vh] flex flex-col gap-0 overflow-hidden p-0`
- Compact dialogs (source config): `sm:max-w-md`
- Footer: `<DialogFooter className="shrink-0 border-t bg-card px-4 py-3">`
- Always include `<DialogHeader className="sr-only">` with `DialogTitle` + `DialogDescription` for accessibility.

---

## Toolbar buttons (footer row)

```tsx
// Primary action
<Button variant="secondary" size="sm" className="h-8 gap-1.5 rounded-lg text-xs">
  <Icon className="h-3.5 w-3.5" aria-hidden />
  Label
</Button>

// Secondary / outlined
<Button variant="outline" size="sm" className="h-8 gap-1.5 rounded-lg border-input text-xs">
  <Icon className="h-3.5 w-3.5" aria-hidden />
  Label
</Button>

// Accent outlined (e.g. Manage Inventory)
<Button variant="outline" size="sm"
  className="h-8 gap-1.5 rounded-lg border-violet-400 text-xs text-violet-700 hover:bg-violet-50 hover:text-violet-800">
  <Icon className="h-3.5 w-3.5 text-violet-600" aria-hidden />
  Label
</Button>
```

---

## Sidebar (group tree)

- Outer: `bg-card border-r border-border`
- Section header: `text-[10px] font-semibold uppercase tracking-wide text-muted-foreground`, `border-b border-border px-3 py-2`
- Row selected: `bg-step-surface text-step-surface-foreground`
- Row hover: `hover:bg-muted`
- Folder icon: `text-step`
- Count badge: `text-[10px] text-muted-foreground`

---

## Inputs

All text/number inputs follow the same pattern:

```tsx
<input
  className="h-9 w-full rounded-lg border border-input bg-card px-2 text-xs
             focus:outline-none focus:ring-2 focus:ring-step/40
             disabled:cursor-not-allowed disabled:bg-muted/50"
/>
```

---

## Condition / info banners

Yellow/amber warning banners always use the **small `text-[11px]` body font** — never
`text-xs` or an unset (inherited, larger) size. An unset size is the bug that made the
`HelpWarning` boxes in a step's Help tab look oversized next to every other small-font
banner in the app (fixed in `shared/step-help.tsx`); when adding a new warning banner,
copy the `text-[11px]` size explicitly rather than relying on inheritance.

```tsx
// Step info (adding-to context)
<div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
  Adding conditions to:{" "}
  <span className="inline-flex rounded-full border border-step-border bg-card px-2 py-0.5 font-medium text-step-surface-foreground shadow-sm">
    Root
  </span>
</div>

// Warning (missing config, or inline in a ConfigPanel) — reference: fan-out-config.tsx
<p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
  Configure a Nautobot source…
</p>

// Warning inside a Help tab — always use the shared HelpWarning component,
// never a hand-rolled div; it already carries the correct text-[11px] size
<HelpWarning title="Fan-out risk if path_template is not device-unique">
  <p>…</p>
</HelpWarning>
```

---

## Checklist for new steps

### Canvas node (shared renderer — do not fork)

- [ ] No custom canvas render branch added in `workflow-node.tsx`
- [ ] Registry `name` is short enough to wrap cleanly at `w-80`, or intentionally concise
- [ ] Registry `description` is the single source of truth for the subtitle on the canvas
- [ ] Outcomes use standard names (`success` / `failure`, or `match` / `mismatch` / `failure`)
      so green/red output handle colours apply automatically
- [ ] Input handle stays muted (`!bg-muted-foreground/40 !border-muted-foreground`) — do not style
      target handles like outcomes
- [ ] Optional: `nodeIconsByKind` entry only when `artifact_type` default icon is wrong
- [ ] Canvas decorations (`label` / `background`) are the only exception — see
      **Exception — canvas decorations** above; do not copy that pattern for executable steps

### Config panel, dialogs, and forms

- [ ] ConfigPanel (Configuration tab) has no `bg-step-surface` (or similar colored) "what
      this step does" banner — that content belongs on the General tab, driven
      automatically by registry `overview`/`description` (see **Node config modal tabs**)
- [ ] Header uses `step-header`
- [ ] No `sky-` / `blue-` / raw `teal-*` colors anywhere in the step **config UI** (canvas outcome
      colours are defined centrally in `step-visuals.ts`)
- [ ] ConfigPanel is narrow, uses `h-7 w-full` outline buttons
- [ ] All inputs use `focus:ring-step/40` or `focus-visible:ring-step/40`
- [ ] Dialog footers use `border-t bg-card px-4 py-3`
- [ ] `<DialogHeader className="sr-only">` present with title + description
- [ ] `aria-hidden` on all decorative icons
- [ ] Shadcn primitives used for all UI (no raw `<select>`, `<dialog>`, etc.)
- [ ] Inventory steps: fan-out block matches the shared pattern (`border-t pt-3`, Switch header, fields revealed only when enabled)
- [ ] Every field that accepts a `{path}` attribute reference has the shared **Browse
      attributes** icon next to it (see **Attribute path fields** above) — no bare text
      input left as the only way to enter a path
- [ ] `HelpPanel` documents every Configuration control with examples (reuse
      `workflow-steps/shared/step-help.tsx`; reference `get-nautobot-devices/help-panel.tsx`)

### Backend executor logging

- [ ] `execute()` logs at least one line when the step starts and one when it finishes
      (`logger = logging.getLogger(__name__)`, `logger.info(...)`) — see **Logging** in
      `WORKFLOW-STEPS.md`
- [ ] Steps that share one implementation helper (e.g. `git-clone` / `git-pull` /
      `git-push` via `run_git_workflow_step`) log once in the shared helper, not once per
      thin `execute()` wrapper

### Backend secret handling

- [ ] Any credential/secret-like value the step writes into `attribute_bags` is sealed
      with `seal_secret()`, never written as a raw string — see **Secret-valued
      attributes** in `WORKFLOW-STEPS.md`
- [ ] Any resolved attribute value the step copies into a new bag, log line, or step
      summary (rather than consuming it in-memory for one call) is resolved with
      `reveal_secrets=False`, unless the step is a documented trusted consumer
- [ ] If the ConfigPanel has a field that holds a secret the user types in directly
      (e.g. a fixed TACACS+ key value, not a `{path.to.value}` expression), mask it with
      `type="password"` the way any other credential input would be
