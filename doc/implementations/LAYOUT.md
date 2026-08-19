# Auto Layout for the Workflow Canvas

Status: **planned, not implemented**. This document is the design and task
breakdown for adding an "Auto layout" action to the workflow builder canvas.
No code has been written yet — see `TODO` at the end for the ordered task
list.

## Goal

Let a user click a button and have the steps currently visible on the canvas
rearranged into a clean, readable layout that follows the edges between
them, instead of hand-dragging every node. This is a **one-shot, user
triggered** action (like "Align left"), not continuous auto-layout while
editing.

Non-goals for v1:
- Live/continuous re-layout while dragging or editing.
- Laying out nested groups recursively in one pass (layout runs on one
  projected view at a time — see "Scope").
- Changing the executable workflow definition. This is purely a canvas
  (`position`) operation, identical in spirit to `alignCanvasNodes`
  (`frontend/src/components/features/workflows/utils/node-alignment.ts`).

## Why ELK, not Dagre

Both are viable per the React Flow examples
([Dagre](https://reactflow.dev/examples/layout/dagre),
[ELK](https://reactflow.dev/examples/layout/elkjs),
[ELK multiple handles](https://reactflow.dev/examples/layout/elkjs-multiple-handles)),
but they differ on the one thing that matters most for this canvas: **ports**.

- `WorkflowNode` (`frontend/src/components/features/workflows/components/nodes/workflow-node.tsx`)
  can render **multiple named source handles** on one side (`success`/`failure`,
  `route-on-attribute` outcomes, etc.), plus a single target handle whose side
  is independently configurable (`incomeHandleSide` / `outcomeHandleSide` in
  `frontend/src/components/features/workflows/types/workflow-canvas.ts`).
- Dagre's layout unit is a plain box — it has no concept of "this edge leaves
  from the handle at 66% down the right edge." Every edge is routed
  source-center → target-center, so branching steps (route-on-attribute,
  success/failure) end up with visibly crossed/overlapping edges near the
  node regardless of the layered ordering Dagre computes.
- ELK models **ports** (`elk.eclipse.org` port constraints, `FIXED_ORDER`,
  per-port `side`) exactly matching what this canvas already has: one port
  per handle id (`input`, each outcome name, funnel `output`), each pinned to
  a side (`WEST`/`EAST`/`NORTH`/`SOUTH`). The
  [multiple-handles example](https://reactflow.dev/examples/layout/elkjs-multiple-handles)
  is close to a direct template for this node type.
- ELK also layers left-to-right or top-to-bottom the same way Dagre does, so
  we lose nothing on the "simple chain" case Dagre is good at — ELK is a
  superset for our purposes, at the cost of an async API and a larger bundle
  (`elkjs/lib/elk.bundled.js`).

Given branching (`route-on-attribute`, funnels merging many-to-one, and
future step kinds with multiple outcomes) is a normal, expected shape in this
app rather than an edge case, ELK's port model pays for itself immediately.
Dagre would still need a second pass to fan edges out along a side by hand,
which is most of ELK's job anyway.

## Scope: what gets laid out

Layout must operate on the **projected view** the user currently sees, the
same input `alignCanvasNodes` already takes
(`ProjectedCanvasNode[]` from `projectCanvasView` in
`frontend/src/components/features/workflows/utils/canvas-group-projection.ts`),
not the raw `allNodes`/`allEdges` arrays:

- **Root view**: real un-grouped steps + one synthetic 320×128 node per
  collapsed group (`groupNode`, fixed size, see
  `synthesizeGroupNode` in `canvas-group-projection.ts`). Laying out
  `allNodes` directly would move group members that aren't even rendered at
  the root and desync them from their group's synthetic position.
- **Inside a group** (`activeGroupId !== null`): only that group's member
  nodes and the edges between them.
- Only one of these two scopes is laid out per invocation — matches how the
  canvas is already scoped everywhere else (selection, alignment, delete).

Excluded from the layout graph entirely:
- **Canvas decorations** — `labelNode` / `backgroundNode`
  (`isCanvasDecorationKind`). They carry no `requires`/`produces` and never
  have edges (`isValidConnection` in `workflow-canvas.tsx` rejects edges
  touching them). They keep their existing position untouched.
- Funnel nodes (`funnelNode`, kind `"funnel"`) are **included** — they are
  real graph participants (many-in, one-out) and need a slot in the ranking,
  just a very small one (40×40 vs. 320×128).

### Selection scope: boundary edges

When `handleAutoLayout` runs on a specific selection (`nodeIds !== null`, the
`MultiStepLayoutPanel` "tidy this branch" case) rather than the whole view,
some edges of the selected nodes may connect to **unselected** neighbors that
keep their current position. Laying out only the selected nodes with no
awareness of those neighbors lets ELK drift the whole selection away from
where it's anchored, turning previously-short edges into long diagonals.

v1 handles this by including each unselected neighbor in the ELK graph as a
**pinned node**: same size/ports as normal, but with a fixed position (ELK's
`elk.position` plus `"org.eclipse.elk.layered.crossingMinimization.semiInteractive"`
/ interactive-layout mode, or equivalent — confirm exact ELK option during
implementation) so the layout algorithm treats it as an immovable anchor
rather than something it's free to place. Only the originally-selected nodes'
computed positions are written back via `setAllNodes`; pinned neighbor nodes
are included in the ELK graph solely to influence ranking/ordering and are
never mutated. Edges between a selected and pinned node still get their
`waypoints` cleared per the usual rule.

## Data flow (mirrors `handleAlignNodes`)

```
useWorkflowCanvas.handleAutoLayout(scope: "view" | "selection")
  -> collect nodes+edges for the current projection (same as alignment)
  -> convert parented (background-child) nodes to absolute coordinates
     (parentOffset()-style helper already in node-alignment.ts)
  -> build ELK graph: one elk node per canvas node (real size), one elk edge
     per canvas edge, ports per handle
  -> await elk.layout(graph)
  -> map elk positions back to canvas positions (undo the parent-offset
     conversion, same as alignCanvasNodes' final `.map`)
  -> setAllNodes(...) / setGroups(...) with new positions, same as
     handleAlignNodes lines 478-499 in use-workflow-canvas.ts
  -> clear `data.waypoints` on edges touched by the relaid-out nodes
  -> markDirty()
  -> fitView() over the affected nodes (see "Viewport after layout")
```

No backend/API/persistence-format changes: `canvas_nodes`/`canvas_edges`
(`frontend/src/components/features/workflows/types/workflow-persistence.ts`)
are untyped JSON columns that already round-trip the full node object
(`position`, `width`/`height`, `parentId`, `data`) on every save; layout only
ever writes into fields already covered by that round-trip.

### Coordinate handling (backgrounds / parented nodes)

Same rule `node-alignment.ts` already implements: a node parented to a
background node stores `position` **relative** to that parent, everything
else is **absolute**. Reuse (or extract into a shared helper) the
`parentOffset()` logic so ELK only ever sees absolute coordinates, then
convert back afterward. Do not attempt to feed ELK's own nesting/hierarchy
support for this — background containment here is a presentation concern
(`resolveContainment` in `canvas-containment.ts`) decided by geometric
overlap after the fact, not a structural parent/child graph edge.

After layout, re-run `resolveContainment` for any node whose new position
lands inside/outside a background box, exactly as node drags already do
(`use-workflow-canvas.ts` around the `updated.width ?? updated.measured?.width`
block) — otherwise a node visually moved out of its background would keep a
stale `parentId`.

### Ports per node kind

| Node kind | Elk ports | Notes |
|---|---|---|
| `workflowNode` (step) | 1 target port (`input`) if `requires`/`requiresParsed` non-empty, 1 source port per `outcomes[]` entry | Port `side` comes from `incomeHandleSide`/`outcomeHandleSide`, mapped `left→WEST, right→EAST, top→NORTH, bottom→SOUTH` |
| `groupNode` (collapsed group) | 1 target port (`input`) if entry step requires anything, 1 source port (`success`) | Always fixed left/right today — matches `group-node.tsx` |
| `funnelNode` | 1 target port (`input`), 1 source port (`output`) | Size 40×40, not 320×128 |
| `labelNode` / `backgroundNode` | excluded, not sent to ELK | positions untouched |

Set `elk.portConstraints: FIXED_ORDER` (or `FIXED_SIDE` if order among
same-side ports doesn't need to match today's top-to-bottom `outcomes[]`
order) on every node with more than one port, per the multiple-handles
example, so `route-on-attribute` branches keep a stable, non-crossing order
matching the order they're already drawn in on the node card.

`buildElkGraph` must decide each node's ports by **node kind/type**
(`workflowNode` / `groupNode` / `funnelNode`), never by presence of `data`
fields. `FunnelCanvasNode` reuses `WorkflowNodeData`
(`frontend/src/components/features/workflows/types/workflow-canvas.ts`), so a
funnel node can carry a stale `outcomes`/`requires` array left over from
before it became a funnel; branching on "does `data.outcomes` exist" instead
of on kind would give a funnel spurious multi-outcome ports.

### Direction

Two options exposed in the UI, both left-to-right/top-to-bottom rather than
their reverses (matches current default `incomeHandleSide: "left"` /
`outcomeHandleSide: "right"`):

- **Horizontal** — `elk.direction: RIGHT`. Default, matches today's default
  handle sides.
- **Vertical** — `elk.direction: DOWN`.

v1 does **not** auto-flip a node's `incomeHandleSide`/`outcomeHandleSide` to
match the chosen direction — those are an explicit per-node user choice
(`node-config-modal.tsx`) and silently overwriting them would surprise users
who deliberately set a node to top/bottom in an otherwise horizontal
workflow. Port `side` sent to ELK always reflects the node's *current*
handle sides, so mixed-orientation graphs still lay out (just less tidily
than a fully-consistent one). A later iteration can offer an opt-in
checkbox: "Also align handle sides to layout direction."

## UI

- Add an "Auto layout" entry next to the existing Align/Distribute controls.
  Two natural spots:
  - `MultiStepLayoutPanel` (`frontend/src/components/features/workflows/components/multi-step-layout-panel.tsx`)
    when ≥ 2 nodes are selected — lays out only the selected subgraph plus
    the edges between them ("tidy this branch").
  - A canvas-level control (e.g. next to `Controls`/`CollapsibleMiniMap` in
    `workflow-canvas.tsx`) for "lay out everything in the current view" with
    no selection required.
- A small direction toggle (Horizontal / Vertical) — reuse the icon set
  already imported in `multi-step-layout-panel.tsx` (`lucide-react` align
  icons already establish the visual language).
- No new persisted setting. The action fires once, writes positions like a
  drag, and `markDirty()` the same as everything else — the user saves (or
  not) exactly as today.
- No confirmation dialog for v1, but see `TODO` re: undo — a "just in case"
  affordance may be worth adding before this ships broadly, since a bad
  auto-layout on a large canvas is more tedious to hand-fix than undo one
  alignment.
- **Viewport after layout**: unlike alignment/drag (which never move the
  camera), a layout run calls React Flow's `fitView()` scoped to the affected
  nodes (the selection, or everything in the current view/group) once
  positions are written back. This is a deliberate deviation from
  `handleAlignNodes`'s behavior — layout can relocate nodes far enough that
  leaving the viewport untouched would strand the result off-screen with no
  indication anything happened.

## Implementation plan

1. **Dependency**: add `elkjs` to `frontend/package.json`. It has no React
   dependency; load it as a plain client-side module (dynamic `import()`
   inside the hook, not top-level, to keep it out of the initial bundle —
   this only runs on a user click).
2. **New util module** `frontend/src/components/features/workflows/utils/auto-layout.ts`:
   - `buildElkGraph(nodes: ProjectedCanvasNode[], edges: WorkflowCanvasEdge[], direction): ElkNode`
     — filters out decorations, emits one ELK node + ports per remaining
     canvas node, one ELK edge per canvas edge (using `sourceHandle`/
     `targetHandle` as the port id).
   - `applyElkLayout(nodes, elkResult): ProjectedCanvasNode[]` — maps
     `x`/`y` back onto each node's `position`, honoring the same
     parent-offset convention as `alignCanvasNodes`.
   - `runAutoLayout(nodes, edges, direction): Promise<ProjectedCanvasNode[]>`
     — the only exported entry point; owns the dynamic `elkjs` import.
3. **Shared coordinate helper**: extract `parentOffset()`, and the unexported
   `nodeWidth()`/`nodeHeight()` fallback pair (`DEFAULT_NODE_WIDTH = 224`,
   `DEFAULT_NODE_HEIGHT = 112`, used when a node hasn't been measured by
   React Flow yet) out of `node-alignment.ts` into a small shared helper
   (e.g. `canvas-containment.ts` or a new `canvas-coordinates.ts`) so
   alignment and auto-layout share one implementation instead of
   copy-pasting it. `buildElkGraph` needs the same measured/fallback
   resolution as alignment for any node ELK hasn't seen rendered dimensions
   for yet.
4. **Hook wiring** in `use-workflow-canvas.ts`: add
   `handleAutoLayout(nodeIds: string[] | null, direction: "horizontal" | "vertical")`
   next to `handleAlignNodes`, following the exact same
   `projected.nodes` → `setAllNodes`/`setGroups` → `markDirty()` shape. Since
   `runAutoLayout` is async, this becomes an async callback; disable the
   triggering button while in flight and surface a toast on failure (ELK can
   throw on disconnected/degenerate graphs — always have a fallback: if ELK
   errors, leave positions untouched and toast an error rather than
   partially applying a bad layout).
   - Also clear `data.waypoints` on every edge whose source or target moved,
     mirroring how other position-changing operations don't try to preserve
     manual bends that no longer make geometric sense.
   - Re-run `resolveContainment` per moved node for background reparenting.
5. **UI wiring**:
   - Extend `MultiStepLayoutPanelProps` with an `onAutoLayout` callback (and
     direction toggle state, likely lifted to `use-workflow-builder-store.ts`
     or kept local to the panel). Note `MultiStepLayoutPanel` doesn't take
     `onAlignNodes` directly today — `onAlignNodes={canvas.handleAlignNodes}`
     (`workflow-builder-page.tsx`) is passed to `WorkflowPropertiesPanel`,
     which wraps it into the panel's simpler `onAlign(alignment)` prop.
     `onAutoLayout` needs the same intermediate wiring through
     `WorkflowPropertiesPanel`, not just a direct prop on the panel.
   - Add the canvas-level "lay out all" control and wire it to
     `handleAutoLayout(null, direction)` (null = "everything in the current
     view" instead of a specific selection).
   - Pass through `workflow-builder-page.tsx` the same way
     `onAlignNodes={canvas.handleAlignNodes}` is passed today.
6. **Tests**:
   - Unit test `auto-layout.ts` pure functions (`buildElkGraph`,
     `applyElkLayout`) with mocked ELK output — no real `elkjs` layout math
     needs testing, just the mapping to/from canvas coordinates, port
     construction, and decoration exclusion.
   - Existing coverage pattern to follow:
     `frontend/src/components/features/workflows/utils/*.test.ts` if present,
     otherwise colocate `auto-layout.test.ts` next to the new util.
7. **Docs**: once implemented, add a short section to
   `doc/WORKFLOW-STEPS-STYLE_GUIDE.md` or `doc/ARCHITECTURAL_OVERVIEW.md`
   only if the port-mapping rules need to be discoverable for future step
   authors (e.g. "if you add a step kind with N outcomes, this is how they
   get ordered by auto-layout") — otherwise this file is sufficient.

## Edge cases to handle explicitly (do not skip)

- **Cycles**: cannot occur in a saved/validated workflow
  (`services/execution/graph.py` `DetectCycle`, `workflow_service.py`
  `_validate_no_cycle`), but the canvas can be mid-edit with a cycle before
  save. ELK layered layout tolerates cycles by breaking them internally, so
  this is not a hard failure case — just note it won't produce a "correct"
  layered order for the cyclic portion.
- **Disconnected nodes** (no edges at all, or a node with no path to the
  rest of the graph): ELK lays out disconnected components separately and
  packs them — verify the packing doesn't visually overlap the connected
  component; may need `elk.spacing.componentComponent` tuned.
- **Funnels**: many-to-one — funnel needs to rank after all of its inputs
  and before its single output's target. ELK's layered algorithm handles
  many-to-one naturally (it's just in-degree > 1 at one node); nothing
  special required beyond including the funnel node with its small size.
- **Group entry/exit highlighting** (`isGroupEntryPoint`/`isGroupExitPoint`
  view-only flags set by `projectCanvasView` when inside a group): layout
  must not touch or need these — it only reads size/handles/edges, and the
  flags stay attached to `data` untouched through the position-only update.
- **Single node or empty selection**: no-op, same guard
  `alignCanvasNodes` already has (`targets.length < 2`) — for a *selection*
  scope. The "lay out everything in view" scope should still run with as
  few as 1 edge.
- **Resizable decorations near steps**: label/background nodes keep their
  position, so a layout pass can visually "leave a step behind" inside/near
  a background that didn't move. This is expected — decorations are
  explicitly out of scope — but worth confirming looks acceptable rather
  than jarring in a quick manual pass after implementation.
- **Selection-scope boundary edges**: see "Selection scope: boundary edges"
  above — unselected neighbors of a laid-out selection are sent to ELK as
  pinned/fixed-position nodes so the tidied subgraph doesn't drift away from
  its anchors, but only the selected nodes' positions are written back.
- **Funnel node data staleness**: `FunnelCanvasNode` reuses `WorkflowNodeData`
  and can carry a leftover `outcomes`/`requires` array from before it became
  a funnel. Port assignment in `buildElkGraph` must switch on node
  kind/type, never on which `data` fields happen to be present.

## TODO

- [ ] Add `elkjs` to `frontend/package.json`; confirm it plays well with the
      Next.js client bundle (dynamic import, no SSR issues — it's pure JS,
      no DOM access, so this should be low-risk).
- [ ] Extract shared parent-offset + node-size-fallback coordinate helpers
      (`parentOffset()`, `nodeWidth()`/`nodeHeight()`) out of
      `node-alignment.ts` for reuse.
- [ ] Implement `utils/auto-layout.ts` (`buildElkGraph`, `applyElkLayout`,
      `runAutoLayout`), excluding `labelNode`/`backgroundNode`, including
      `funnelNode` with its real 40×40 size, honoring `incomeHandleSide`/
      `outcomeHandleSide` as ELK port sides, `FIXED_ORDER` ports for
      multi-outcome nodes, port assignment keyed on node kind (not `data`
      field presence), and pinned/fixed-position ELK nodes for unselected
      neighbors of a selection-scoped layout.
- [ ] Add `handleAutoLayout` to `use-workflow-canvas.ts`: async, operates on
      `projected.nodes`/`projected.edges`, writes back to `allNodes`/
      `groups` positions, clears stale edge `waypoints`, re-resolves
      background containment, `fitView()`s the affected nodes, `markDirty()`,
      toast on ELK failure without mutating state.
- [ ] Add direction toggle (horizontal/vertical) UI state.
- [ ] Wire "auto layout selection" into `MultiStepLayoutPanel`, threading
      `onAutoLayout` through `WorkflowPropertiesPanel` alongside the existing
      `onAlign`.
- [ ] Wire "auto layout current view" into a canvas-level control.
- [ ] Thread new props through `workflow-builder-page.tsx`.
- [ ] Unit tests for the pure mapping functions in `auto-layout.ts`.
- [ ] Manual pass: verify multi-outcome nodes (`route-on-attribute`,
      success/failure steps), funnels, collapsed groups, backgrounds with
      parented children, and mixed handle-side nodes all look correct after
      a layout run, in both directions.
- [ ] Decide on undo/confirm affordance before enabling this for large,
      hand-tuned canvases (no undo stack exists yet for alignment either —
      confirm whether this ships blocked on that or independently).
