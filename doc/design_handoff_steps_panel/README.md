# Handoff: Steps Panel + Canvas Redesign (Workflow Builder)

## Overview
Rework the Auxilium Manus workflow builder so that **adding steps happens in the right‑hand panel** instead of a floating "Add step" card, and **polish the canvas nodes**.

The right panel becomes a two‑tab panel:
- **Steps** — a searchable, collapsible catalog of every workflow step, grouped by `artifact_type`. Add a step by **clicking** it (drops on the canvas) or **dragging** it onto the canvas at a chosen position.
- **Properties** — the existing contextual controls (edge style, multi‑select align), plus a richer single‑node view. It **auto‑focuses when the user selects** an edge or one/more nodes.

The floating draggable `NodePalette` card is removed. The left‑sidebar **"Steps"** item now just activates the right panel's Steps tab (see State Management).

Canvas nodes get a category color accent, clearer outcome pills/handles, and a cleaner config affordance (a gear that opens Properties).

---

## About the Design Files
The files in this bundle are **design references created in HTML** — a single streaming prototype (`Workflow Builder.dc.html`) showing the intended look and behavior. **It is not production code to copy.** It uses a small internal runtime (`support.js`) and inline styles purely so the mock renders standalone.

Your task is to **recreate this design in the existing React/Next.js frontend** (`frontend/src/…`), using its established patterns: React 19 + `@xyflow/react` (React Flow), Tailwind v4 with the CSS variables in `src/app/globals.css`, the shadcn‑style primitives in `src/components/ui/*`, `lucide-react` icons, and the Zustand store in `hooks/use-workflow-builder-store.ts`. Do **not** introduce inline styles or new color literals — map everything to the existing Tailwind tokens (below).

## Fidelity
**High‑fidelity.** Colors, typography, spacing, and interactions are final. Recreate pixel‑for‑pixel using the codebase's existing libraries/tokens. Where the mock uses a raw hex, use the matching Tailwind token or CSS variable instead of hardcoding.

---

## Target files (what to change)

| File | Change |
|---|---|
| `components/features/workflows/components/workflow-properties-panel.tsx` | Add a **Steps \| Properties** tab header. Render the step catalog under the Steps tab; keep existing edge / multi‑select controls under Properties and add the single‑node view. |
| `components/features/workflows/components/workflow-node-palette.tsx` | Extract the catalog list (search + grouping + category sections + step rows) into a presentational **`StepCatalog`** used inside the panel. Delete the floating‑card chrome (drag, collapse, absolute positioning, `X`/`hideActionsPanel`). |
| `components/features/workflows/components/workflow-canvas.tsx` | Remove the `<NodePalette>` render and `isActionsPanelVisible` usage. Add native drag‑drop handlers (`onDragOver`/`onDrop`) so a step dragged from the catalog is placed at the drop point (use `screenToFlowPosition`). |
| `components/features/workflows/components/nodes/workflow-node.tsx` | Add the left **category accent border**; keep outcome pills/handles (already close). Make the hover gear open Properties (select the node) rather than only opening the config modal — see Interactions. |
| `components/features/workflows/workflow-builder-page.tsx` | Pass `plugins`, `isPluginsLoading`, `pluginError`, and `onAddStep` into the properties panel (they currently go to the canvas → palette). Keep `handleAddStep` as the add entry point; add an `onAddStepAtPosition` variant for drops. |
| `components/features/workflows/hooks/use-workflow-builder-store.ts` | Add `rightPanelTab: 'steps' \| 'properties'` + `setRightPanelTab`. Auto‑set to `'properties'` inside `selectNode`/`selectEdge` when a selection is made, and to `'steps'` when cleared. Repurpose the sidebar "Steps" action to `setRightPanelTab('steps')` (the `isActionsPanelVisible`/`toggleActionsPanel` machinery can be removed). |
| `components/features/workflows/components/workflow-sidebar.tsx` | "Steps" nav item calls `setRightPanelTab('steps')`; its active state = `rightPanelTab === 'steps'`. |

The design reference for all of the above is **`Workflow Builder.dc.html`** in this bundle.

---

## Screens / Views

### 1. Right panel — Steps tab (default)
- **Purpose:** browse and add workflow steps to the canvas.
- **Layout:** fixed panel, **344px** wide, `border-l`, `bg-card`, full height flex column.
  - **Header** (`p-3` top, `border-b`): a segmented tab control (`bg-muted`, `border`, `rounded-[10px]`, `p-[3px]`) with two buttons **Steps** and **Properties**; each button `text-[13px] font-medium px-[14px] py-[6px] rounded-[7px]`, active = `bg-card text-foreground shadow-sm`, inactive = `text-muted-foreground`. A right‑aligned collapse button (`ChevronsRight`, `text-muted-foreground`, 32×32). Below, a one‑line subtitle in `text-xs text-muted-foreground` (Steps: "Drag onto the canvas, or click to add.").
  - **Search row** (`p-[12px_14px]`, `border-b` in `#eef2f7` ≈ `border`/50): a `bg-muted/60 border rounded-[10px] px-3 py-[9px]` field with a leading `Search` icon (`text-muted-foreground`) and an input (`text-[13px]`, no border, transparent bg), placeholder "Search steps…".
  - **List** (`flex-1 overflow-y-auto p-[8px_10px_24px]`): one **category section** per `artifact_type`.
- **Category section:**
  - Header: full‑width button, `p-2`, left → a **26px** colored icon tile (see Design Tokens › category colors), category label `text-[13px] font-semibold`, a count pill (`text-[11px] text-muted-foreground bg-muted rounded-full px-2`), and a trailing `ChevronDown` that rotates ‑90° when collapsed (`transition-transform .15s`).
  - Expanded by default. Collapsing is per‑category (persist in local state or store). When a search query is active, force all matching sections open.
  - Body: `flex flex-col gap-1`, one **step row** per step.
- **Step row (draggable + clickable):**
  - `flex items-start gap-[11px] p-[9px_10px] border rounded-[10px] bg-card cursor-grab`.
  - Hover: border → `#bae6fd` (sky‑200), `bg` → very light sky (`#f8fbff`), `shadow` sky‑tinted (`0 2px 8px rgba(56,189,248,.14)`).
  - Left: **32px** colored icon tile. Middle: name `text-[12.5px] font-semibold` + description `text-[11px] text-muted-foreground line-clamp-2` (description hidden when the "catalog descriptions" toggle is off). Right: a faint `Plus` icon (`text-border`) hinting click‑to‑add.
- **Empty search state:** centered `text-[13px] text-muted-foreground` — `No steps match "{query}".`

### 2. Right panel — Properties tab
Same header. Body `flex-1 overflow-y-auto p-[16px_16px_24px]`. Four mutually‑exclusive states:

- **None selected:** centered empty state — `Sliders` icon (`text-border`, 30px) over `text-[13px] text-muted-foreground` copy: "Select a step, an edge, or multiple steps on the canvas to see controls here."
- **Single node:**
  - Row: **42px** colored icon tile + uppercase category label (`text-[11px] font-semibold tracking-[.05em] text-muted-foreground`).
  - **Editable title** `<input>`: `text-[15px] font-semibold`, `border rounded-[9px] p-[9px_11px]`; focus = `border-ring` + `ring` (`0 0 0 3px rgba(56,189,248,.18)`). Writes back via `onNodeTitleChange` (already exists in the builder page).
  - Description paragraph `text-[12.5px] text-muted-foreground`.
  - **Data contract** section (label style = uppercase muted, as above): "Requires (input)" and "Produces (output)", each a wrap of mono chips (`font-mono text-[11px] text-slate-700 bg-muted border rounded-[6px] px-2 py-[2px]`). Empty requires → "None — start step"; empty produces → "Passes context through".
  - **Outcomes:** wrap of pills — dot + name, colored by outcome (Design Tokens › outcomes).
  - **Actions:** primary `Open configuration` (`bg-primary text-primary-foreground`, full width, `Settings2` icon) → opens the existing `NodeConfigModal` (`openConfigModal(nodeId)`). Then a row: `Duplicate` (outline, `Copy` icon) and `Delete` (outline, `border-destructive/30 text-destructive`, `Trash` icon).
- **Multi‑select:** "{n} steps selected" + subtitle. **Align** = 3×2 grid of outline buttons (Left / Center / Right / Top / Middle / Bottom). **Distribute** = 2‑col (Horizontal / Vertical). Then a destructive full‑width `Delete {n} steps`. Wire to `onAlignNodes` (exists) + a new distribute + delete handler. This replaces/extends the current `MultiStepLayoutPanel`.
- **Edge selected:** "Connection" label; `source →(MoveRight)→ target` in `text-[14px] font-semibold`. **Edge style** = two buttons Straight / Smooth, active = `bg-primary text-primary-foreground` (wire to existing `onEdgeStyleChange`). Hint paragraph. Destructive `Remove connection`.

### 3. Canvas (polish)
- Background: `bg-slate-50` with React Flow dot grid (`#cbd5e1`, gap 22, size 1) — already present.
- **Node card** (`workflow-node.tsx`): keep `w-80 h-32`. Add **left accent**: `border-l-[3px]` colored by `artifact_type` (Design Tokens › category `color`). Keep the icon tile, title (`text-sm font-semibold`), description (`line-clamp-2 text-xs text-muted-foreground`). Selected = `border-ring shadow-lg ring-2 ring-ring/20` (unchanged). Outcome pills + colored source handles and the gray target handle are already implemented and correct — keep them.
- **Gear affordance:** the hover gear (top‑right) should **select the node** (which auto‑switches the panel to Properties). Keep the existing config‑modal open available from the Properties "Open configuration" button. (In the mock the gear opens Properties; either behavior is fine — pick "select + focus Properties" for consistency.)
- Controls (bottom‑left zoom/fit/lock) and minimap (bottom‑right) are the existing React Flow `<Controls>` / `<CollapsibleMiniMap>` — no change required beyond what's there.

---

## Interactions & Behavior
- **Tabs:** clicking Steps/Properties sets `rightPanelTab`. Selecting a node or edge on the canvas **auto‑switches to Properties**; clicking empty canvas (deselect) switches back to **Steps**. Manual tab clicks always win until the next selection change.
- **Click‑to‑add:** clicking a catalog step calls `onAddStep(step)` → appends a node (existing `handleAddStep` logic; keep the cascade offset), selects it, and focuses Properties.
- **Drag‑to‑place:** `pointerdown`/native `dragstart` on a step row starts a drag with a small ghost (icon tile + name). Dropping over the canvas adds the node at the pointer location. In React Flow, convert the drop client coords with `screenToFlowPosition({ x, y })` and center the node on it (subtract half of 320×128). Dropping outside the canvas cancels. If not dragged (a click), fall back to click‑to‑add.
  - Recommended: use HTML5 DnD — `draggable` on the row, `dataTransfer.setData('application/x-am-step', step.id)` on `dragstart`; `onDragOver`(preventDefault)/`onDrop` on the React Flow wrapper.
- **Search:** case‑insensitive match on step `name`, `description`, and `id`. Hide non‑matching steps; hide empty categories; force‑expand matching categories.
- **Edge style / align / delete / duplicate:** wire to the store + `setNodes/setEdges` handlers already in `workflow-builder-page.tsx` (`handleEdgeStyleChange`, `handleAlignNodes`, `handleNodeConfigChange`, etc.). Add: distribute (even‑space selected nodes on an axis), delete node(s), delete edge, duplicate node.

## State Management
Add to `use-workflow-builder-store.ts`:
- `rightPanelTab: 'steps' | 'properties'` (default `'steps'`) + `setRightPanelTab(tab)`.
- In `selectNode(id)` / `selectEdge(id)`: when `id` is non‑null set `rightPanelTab = 'properties'`; when cleared (`selectNode(null)`) set `'steps'`.
- Remove `isActionsPanelVisible`, `showActionsPanel`, `hideActionsPanel`, `toggleActionsPanel` (no longer a floating panel). Update `workflow-sidebar.tsx` and `workflow-node-palette.tsx` references accordingly.
- Per‑category collapse state can be local component state (`Record<artifactType, boolean>`), not global.

Existing state reused as‑is: `selectedNodeId`, `selectedEdgeId`, `configModalNodeId` / `openConfigModal`, `mode`.

Multi‑select node ids come from React Flow node `selected` flags (as the current properties panel already derives via `nodes.filter(n => n.selected)`).

---

## Design Tokens

**Base (from `globals.css`, light theme):**
- background `#f8fafc` · foreground `#0f172a` · card `#ffffff` · muted `#f1f5f9` · muted‑foreground `#64748b` · border/input `#e2e8f0` · accent `#e0f2fe` · accent‑foreground `#075985` · primary `#0f172a` · primary‑foreground `#f8fafc` · ring `#38bdf8` · destructive `#dc2626` · radius `0.75rem`.
- Fonts: **Geist** (sans) / **Geist Mono** — already wired via `--font-geist-sans/mono`.

**Category (artifact_type) colors** — icon‑tile `bg` / icon+accent `color` (these match `nodeAccentClassesByType` in `workflow-node.tsx`; the `color` hex is the node left‑accent):
| artifact_type | tile bg | color |
|---|---|---|
| inventory_selector | `#e0f2fe` (sky‑100) | `#0369a1` (sky‑700) |
| control_flow | `#fef3c7` (amber‑100) | `#b45309` (amber‑700) |
| template_rendering | `#ffedd5` (orange‑100) | `#c2410c` (orange‑700) |
| command_execution | `#d1fae5` (emerald‑100) | `#047857` (emerald‑700) |
| configuration_retrieval | `#e0e7ff` (indigo‑100) | `#4338ca` (indigo‑700) |
| persistent_artifact | `#ede9fe` (violet‑100) | `#6d28d9` (violet‑700) |

**Outcome colors** (pills + handles; matches `outcomeClasses`/`outcomeHandleClasses`):
| outcome | bg | text | border | dot/handle |
|---|---|---|---|---|
| success / match / pass | `#f0fdf4` | `#15803d` | `#bbf7d0` | `#22c55e` |
| failure / fail / error / mismatch | `#fef2f2` | `#b91c1c` | `#fecaca` | `#ef4444` |
| default / unmatched | `#fffbeb` | `#b45309` | `#fde68a` | `#f59e0b` |
| other (e.g. ios, nxos) | `#f0f9ff` | `#0369a1` | `#bae6fd` | `#38bdf8` |

**Category order** (as in `ARTIFACT_TYPE_ORDER`): inventory_selector, control_flow, template_rendering, command_execution, configuration_retrieval, persistent_artifact.

**Spacing / radius used:** panel width 344px; node 320×128 (`w-80 h-32`); tile sizes 26 / 32 / 34 / 42px; radii 6–12px; card shadow `0 1px 2px rgba(15,23,42,.06)`, selected node `0 12px 28px -10px rgba(56,189,248,.5)`.

---

## Assets & Icons
No image assets. Icons are **lucide‑react** (the app already uses it). Mapping (kind → icon), matching `nodeIconsByKind` + `iconByArtifactType`:
- inventory (`get-nautobot-devices`, `get-git-devices`, `get-nautobot-attributes`) → `Router`
- `run-command` → `TerminalSquare` · `get-device-configs` → `HardDriveDownload`
- `render-jinja-template` → `FileText`
- control_flow: `route-on-attribute` → `Split` · `fan-in` → `GitMerge` · `merge-content` → `Combine` · `compare-data` → `Scale` · `filter-output` → `Filter` · `workflow-log` → `List` (default control_flow → `GitBranch`)
- persistent: `store-artifact` → `FileArchive`/`Archive` · `git-clone/pull/push` → `GitBranch`
- Chrome: `Search`, `Plus`, `Minus`, `Maximize`, `Lock`, `ChevronDown`, `ChevronsRight`, `Sliders`/`SlidersHorizontal`, `MoveRight`, `Settings2`, `Copy`, `Trash2`, `Layers` (Steps tab), `Map` (overview).

The step catalog data (names, descriptions, `artifact_type`, `requires`, `produces`, `outcomes`) is **already served** by `GET /api/workflow-steps` from `backend/workflow_steps/registry.yaml` and consumed via `useWorkflowStepsQuery()`. Build the catalog from that, not from hardcoded data — the mock's list is just a snapshot of it.

## Files in this bundle
- `Workflow Builder.dc.html` — the high‑fidelity interactive design reference (open in a wide browser window; the panel is on the right).
- `README.md` — this document.
