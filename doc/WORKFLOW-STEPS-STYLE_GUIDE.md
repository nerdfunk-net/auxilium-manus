# Workflow Step Style Guide

Reference implementation: `get-nautobot-devices/`

---

## Color palette

All steps use the **teal** accent family from Tailwind. Never use `sky-`, `blue-`, or arbitrary hex colors.

| Role | Tailwind class | Usage |
|---|---|---|
| Card header background | `bg-gradient-to-r from-teal-600 to-teal-500` | Step card top bar |
| Header text / icons | `text-white` | On gradient header |
| Header badge / pill | `bg-white/20 text-white` | Counts, labels in header |
| Primary action button | `bg-teal-500 hover:bg-teal-600 text-white` | Round `+` / submit button |
| Selected row / item | `bg-teal-50 text-teal-900` | Active state in lists/sidebars |
| Accent icons | `text-teal-500` | Folder, status icons |
| Info banner | `bg-teal-50 text-teal-900` | Contextual hint strips |
| Info badge border | `border-teal-200` | Pill borders inside info banners |
| Focus ring | `focus:ring-teal-400/40` | Inputs, selects |
| Checkbox accent | `accent-teal-500` | Native checkboxes |

---

## Card anatomy

```
┌─────────────────────────────────────┐
│  Header (gradient from-teal-600 …)  │  py-2.5 px-4, text-white, font-semibold
├─────────────────────────────────────┤
│  Body (bg-slate-50)                 │  overflow-y-auto, space-y-4, p-4
│   • warning banner (amber-50)       │  when source not configured
│   • main content                    │
│   • preview results                 │
├─────────────────────────────────────┤
│  Footer (bg-white, border-t)        │  flex-wrap gap-2, px-4 py-3
└─────────────────────────────────────┘
```

- Outer wrapper: `rounded-xl border border-slate-200 bg-card shadow-sm`
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
| Input handle | `!bg-slate-300 !border-slate-400` |

Defined once as `TARGET_HANDLE_CLASS` in `workflow-node.tsx`. Always light gray — never
match outcome green/red styling.

#### Output handles (source, right edge) — success and failure colors

Outcome names come from the step's `outcomes` list in `registry.yaml`. The shared
renderer colours labels and source handles automatically:

| Outcome name (case-insensitive) | Label pill | Handle dot |
|---|---|---|
| `success`, `match`, `pass` | `bg-green-50 text-green-700 border border-green-200` | `!bg-green-500 !border-green-600` |
| `failure`, `fail`, `error`, `mismatch` | `bg-red-50 text-red-700 border border-red-200` | `!bg-red-500 !border-red-600` |
| `default` | `bg-amber-50 text-amber-700 border border-amber-200` | `!bg-amber-500 !border-amber-600` |
| anything else | `bg-sky-50 text-sky-700 border border-sky-200` | `!bg-sky-500 !border-sky-600` |

Rules:

- Prefer standard outcome names (`success` / `failure`, or `match` / `mismatch` /
  `failure` for compare steps) so green/red styling applies without extra code.
- Outcome **labels** are shown only when `outcomes.length > 1`. A single-outcome step
  still gets a coloured source handle; the label is omitted to save space.
- Handles are stacked vertically on the right edge; labels sit just left of each handle.

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

- `<Badge variant="outline" className="gap-1 border-teal-300 bg-teal-50 text-teal-700">` with
  a `<Split className="size-3" aria-hidden />` icon. Teal family only — no `sky-`/`blue-`.

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

---

## Config panel (node side-panel)

The `ConfigPanel` component renders inside the React Flow node property panel — it is narrow (~220 px) and must stay compact.

- Use `space-y-1.5` for label → hint → button stacking
- Labels: `font-mono text-xs font-medium` for parameter names
- Badges: `<Badge variant="secondary">` for type hints (`nautobot`, `filter tree`, …)
- Status hint (configured): `text-[11px] text-muted-foreground truncate`
- Status hint (unconfigured): `text-[11px] text-amber-600`
- Action button: `<Button variant="outline" size="sm" className="h-7 w-full text-xs">`

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

- A single teal info banner (`rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900`)
  explaining the rejoin, plus a `text-[11px] text-muted-foreground` hint to place git/store
  steps after it. No inputs, no `onChange`.

---

## Dialogs

- Use `<Dialog>` from Shadcn.
- Wide dialogs (filter builder): `max-w-4xl h-[85vh] flex flex-col gap-0 overflow-hidden p-0`
- Compact dialogs (source config): `sm:max-w-md`
- Footer: `<DialogFooter className="shrink-0 border-t bg-white px-4 py-3">`
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
<Button variant="outline" size="sm" className="h-8 gap-1.5 rounded-lg border-slate-300 text-xs">
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

- Outer: `bg-white border-r border-slate-200`
- Section header: `text-[10px] font-semibold uppercase tracking-wide text-muted-foreground`, `border-b border-slate-200 px-3 py-2`
- Row selected: `bg-teal-50 text-teal-900`
- Row hover: `hover:bg-muted`
- Folder icon: `text-teal-500`
- Count badge: `text-[10px] text-muted-foreground`

---

## Inputs

All text/number inputs follow the same pattern:

```tsx
<input
  className="h-9 w-full rounded-lg border border-input bg-white px-2 text-xs
             focus:outline-none focus:ring-2 focus:ring-teal-400/40
             disabled:cursor-not-allowed disabled:bg-muted/50"
/>
```

---

## Condition / info banners

```tsx
// Teal info (adding-to context)
<div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
  Adding conditions to:{" "}
  <span className="inline-flex rounded-full border border-teal-200 bg-white px-2 py-0.5 font-medium text-teal-900 shadow-sm">
    Root
  </span>
</div>

// Amber warning (missing config)
<p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
  Configure a Nautobot source…
</p>
```

---

## Checklist for new steps

### Canvas node (shared renderer — do not fork)

- [ ] No custom canvas render branch added in `workflow-node.tsx`
- [ ] Registry `name` is short enough to wrap cleanly at `w-80`, or intentionally concise
- [ ] Registry `description` is the single source of truth for the subtitle on the canvas
- [ ] Outcomes use standard names (`success` / `failure`, or `match` / `mismatch` / `failure`)
      so green/red output handle colours apply automatically
- [ ] Input handle stays light gray (`!bg-slate-300 !border-slate-400`) — do not style
      target handles like outcomes
- [ ] Optional: `nodeIconsByKind` entry only when `artifact_type` default icon is wrong

### Config panel, dialogs, and forms

- [ ] Header uses `bg-gradient-to-r from-teal-600 to-teal-500`
- [ ] No `sky-` / `blue-` colors anywhere in the step **config UI** (canvas outcome
      green/red/amber is defined centrally in `workflow-node.tsx`)
- [ ] ConfigPanel is narrow, uses `h-7 w-full` outline buttons
- [ ] All inputs use `focus:ring-teal-400/40`
- [ ] Dialog footers use `border-t bg-white px-4 py-3`
- [ ] `<DialogHeader className="sr-only">` present with title + description
- [ ] `aria-hidden` on all decorative icons
- [ ] Shadcn primitives used for all UI (no raw `<select>`, `<dialog>`, etc.)
- [ ] Inventory steps: fan-out block matches the shared pattern (`border-t pt-3`, Switch header, fields revealed only when enabled)
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
