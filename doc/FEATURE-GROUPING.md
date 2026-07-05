# Canvas Step Grouping

## Introduction

Workflow builders often accumulate long linear chains of similar steps — for example, ten
**Update Attribute** steps after a Nautobot inventory fetch. The canvas becomes visually
noisy even though the runtime graph is correct.

This feature adds **editor-only step groups**: a collapsed group appears as a single node
with one input and one output on the root canvas. Double-clicking the group opens an inner
view that shows only the grouped steps. A breadcrumb control returns to the parent view.

**Runtime behaviour must not change.** The backend continues to execute the flat
`canvas_nodes` / `canvas_edges` graph exactly as today. Groups are presentation metadata
stored alongside the canvas JSON.

---

## Goals

- Collapse a set of steps into one **Group** node on the root canvas (one input, one
  success output).
- Double-click a group to **drill in** and edit its member steps on a dedicated canvas
  view.
- **Breadcrumb navigation** ("Go to upper group" / root) to drill back out.
- **Create group** from multi-selected steps in the Properties panel.
- **Rename** and **ungroup** from the Properties panel.
- Persist group metadata with the workflow (save/load round-trip).
- v1 targets **linear chains** (single entry node, single exit node) — the common
  Update Attribute use case.

## Non-goals (v1)

- Nested groups (group inside a group) — defer to v2; design the data model to allow it.
- Arbitrary subgraph topology (parallel branches, multiple entry/exit points) — v1 rejects
  these at group-creation time with a clear error message.
- Backend changes (`StepRunner`, registry, new step kind).
- Execution panel changes (step results still keyed by real node id).
- Group nodes as executable steps in `registry.yaml`.
- React Flow native `parentId` containment boxes on the same canvas (different UX).

---

## Critical architecture constraint

The workflow **canvas is the execution graph**. `StepRunner` topologically sorts every
entry in `canvas_nodes` and runs each by `data.kind`:

```
backend/services/execution/step_runner.py  →  execute_all()
frontend save/load                         →  canvas_nodes, canvas_edges
```

Therefore:

| Do | Don't |
|----|-------|
| Store real steps and real edges in `canvas_nodes` / `canvas_edges` unchanged | Persist a group as a node with `kind: "group"` unless the backend is updated to skip it |
| Add separate **editor metadata** (`canvas_groups`) | Rewrite edges when collapsing — only **derive** proxy edges in the view layer |
| Filter/synthesize nodes only in the React editor | Filter nodes before save (the full flat graph must always be saved) |

---

## Data model

### New type: `CanvasGroup`

Add to `frontend/src/components/features/workflows/types/workflow-canvas.ts`:

```typescript
export interface CanvasGroup {
  /** Stable id, e.g. "group-1". Never reuse after delete. */
  id: string;
  /** Display title on the collapsed Group node. */
  title: string;
  /** Member step node ids (must all exist in canvas_nodes). */
  nodeIds: string[];
  /**
   * Cached boundary ids — recomputed on group create/ungroup/member change.
   * v1 requires exactly one entry and one exit.
   */
  entryNodeId: string;
  exitNodeId: string;
  /** Position of the collapsed Group node on the root canvas. */
  position: { x: number; y: number };
  /** Reserved for v2 nested groups. Always null in v1. */
  parentGroupId: string | null;
}
```

### Persistence

Add `canvas_groups` as a sibling JSON field on the workflow record.

**Backend** (minimal, schema-only):

- `backend/models/workflows.py` — add `canvas_groups: list[dict[str, Any]]` to
  `WorkflowCreate`, `WorkflowUpdate`, `WorkflowResponse` (default `[]`).
- `backend/core/models/workflows.py` — add nullable JSON column `canvas_groups`.
- Alembic migration — `canvas_groups JSONB DEFAULT '[]'`.
- `backend/repositories/workflow_repository.py` — pass through on create/update/read.

**Frontend**:

- `frontend/src/components/features/workflows/types/workflow-persistence.ts` — mirror the
  field on create/update/response types.
- `workflow-builder-page.tsx` — include `canvas_groups` in all save/load paths alongside
  nodes and edges.

Existing workflows without `canvas_groups` load as `[]` (no migration of node data
required).

### Editor state (Zustand, not persisted)

Add to `use-workflow-builder-store.ts`:

```typescript
/** null = root canvas view */
activeGroupId: string | null;
/** Stack for breadcrumb; [null] or [] means root. Last item = current view. */
groupNavigationStack: (string | null)[];
```

Navigation actions:

- `enterGroup(groupId)` — push `groupId` onto stack, set `activeGroupId`.
- `exitToParent()` — pop stack; set `activeGroupId` to new top (or `null`).
- `exitToRoot()` — clear stack, set `activeGroupId = null`.
- Reset navigation on `loadWorkflow` / `resetToNew`.

---

## View projection (core algorithm)

All grouping logic should funnel through one module:

```
frontend/src/components/features/workflows/utils/canvas-group-projection.ts
```

### Source of truth vs displayed graph

| Layer | Contents |
|-------|----------|
| **Authoritative** (`allNodes`, `allEdges`, `groups`) | Full flat graph; what gets saved |
| **Projected** (`visibleNodes`, `visibleEdges`) | What React Flow renders for `activeGroupId` |

React Flow in `workflow-canvas.tsx` receives **projected** nodes/edges. Mutations
(add/delete/move/connect) must write back to the **authoritative** graph via inverse
projection helpers (see Hard Part 2 below).

### `projectCanvasView` signature

```typescript
interface ProjectedCanvas {
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];
  /** Maps synthetic group-node id → CanvasGroup id */
  groupNodeIds: Map<string, string>;
}

function projectCanvasView(
  allNodes: WorkflowCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  activeGroupId: string | null,
): ProjectedCanvas;
```

### Root view (`activeGroupId === null`)

1. Collect all node ids that belong to any group: `groupedNodeIds`.
2. **Visible step nodes** = `allNodes.filter(n => !groupedNodeIds.has(n.id))`.
3. For each `CanvasGroup`, synthesize a **Group node**:

   ```typescript
   {
     id: `__group__${group.id}`,       // synthetic prefix avoids collision
     type: "groupNode",
     position: group.position,
     data: {
       kind: "__canvas-group__",      // not a registry plugin
       title: group.title,
       memberCount: group.nodeIds.length,
       groupId: group.id,
       // Derived from boundary nodes — see Hard Part 3
       requires: entryNode.data.requires,
       requiresParsed: entryNode.data.requiresParsed,
       outcomes: [{ name: "success" }],
       produces: exitNode.data.produces,
       producesParsed: exitNode.data.producesParsed,
     },
   }
   ```

4. **Visible edges** — start from real edges, apply replacement rules:

   | Real edge | Root projection |
   |-----------|-----------------|
   | `A → B` where neither A nor B is grouped | Keep as-is |
   | `A → B` where B is inside group G, A is outside | Replace target with `__group__G`, keep A's source handle |
   | `A → B` where A is inside group G, B is outside | Replace source with `__group__G`, use handle `success` |
   | Both inside same group G | Omit (internal) |
   | `A → B` where A in G1, B in G2 | Omit in v1 (reject at group creation) |

5. Assign stable synthetic edge ids, e.g. `__group-edge__${originalEdgeId}`.

### Inner view (`activeGroupId === G`)

1. **Visible step nodes** = member nodes of G only (`group.nodeIds`).
2. **Visible edges** = real edges where both source and target are in `group.nodeIds`.
3. Do **not** render the synthetic Group node inside its own view.
4. Optionally render faint "ghost" handles or a banner showing external connections
   (entry/exit) — nice-to-have, not required for v1.

### v2 note (nested groups)

When `parentGroupId` is used, root view shows only top-level groups; inner view of parent
shows child groups as synthetic nodes. v1 sets `parentGroupId: null` always and skips this.

---

## Hard parts (precise specification)

### Hard Part 1 — Boundary detection (group creation)

When the user selects nodes and clicks **Group selected steps**, compute whether the
selection forms a valid v1 group.

**Definitions** (given `selectedIds: Set<string>`, full `edges`):

```
incomingFromOutside(e) = e.target ∈ selectedIds ∧ e.source ∉ selectedIds
outgoingToOutside(e)   = e.source ∈ selectedIds ∧ e.target ∉ selectedIds
internalEdges          = both source and target ∈ selectedIds
```

**v1 validity rules**:

1. `selectedIds.size >= 2`.
2. Exactly **one** incoming edge from outside → its `target` is `entryNodeId`.
3. Exactly **one** outgoing edge to outside → its `source` is `exitNodeId`.
4. Every node in `selectedIds` is reachable from `entryNodeId` following internal edges
   only, and `exitNodeId` is reachable from every node (equivalently: the induced subgraph
   is a **single directed path** from entry to exit for the common case, or at minimum a
   **single entry / single exit DAG** where all nodes lie on some path from entry to
   exit).
5. No node in `selectedIds` may already belong to another group.
6. No two different groups may be merged in one action in v1.

**Practical v1 simplification** (recommended for first implementation):

Verify the stricter **linear chain** property:

1. Sort selected nodes by topological order (use same Kahn logic as
   `computeOutcomeProvides`).
2. Confirm consecutive pairs `(n[i], n[i+1])` each have at least one edge `n[i] → n[i+1]`.
3. Confirm no extra incoming/outgoing boundary edges beyond first/last.

This matches the Update Attribute chain use case and is easier to test. Document in UI:
"Grouping currently supports sequential step chains."

**On success**:

- Create `CanvasGroup` with computed `entryNodeId`, `exitNodeId`.
- Set `group.position` to centroid of selected node positions (or entry node position).
- Do **not** delete or modify real nodes/edges.

**On failure**: toast with specific reason, e.g. "Group must be a single chain with one
input and one output."

**Files**: new `utils/canvas-group-boundary.ts`, called from
`workflow-builder-page.tsx` or a `useCanvasGroups` hook.

---

### Hard Part 2 — Mutations must round-trip through projection

React Flow emits changes against **visible** nodes/edges. The page must translate these
to **authoritative** state.

| User action | View context | Authoritative mutation |
|-------------|--------------|------------------------|
| Drag step node | Inside group | Update `allNodes[id].position` |
| Drag Group node | Root | Update `groups[groupId].position` |
| Connect `A → Group` | Root | Connect `A → entryNodeId` (real edge) |
| Connect `Group → B` | Root | Connect `exitNodeId → B` (real edge) |
| Connect inside group | Inner | Normal `addEdge` on `allEdges` |
| Delete Group node | Root | **Ungroup** (remove group metadata, keep steps) — do not delete member steps |
| Delete step inside group | Inner | Remove from `allNodes`, `allEdges`, and `group.nodeIds`; recompute or dissolve group if `< 2` members |
| Add step from catalog | Root | Normal add (ungrouped) |
| Add step from catalog | Inner | Normal add + append id to `group.nodeIds` |

Implement `resolveProjectionMutation` helpers rather than scattering if/else across
handlers.

**Edge case — reconnect at group boundary**: When the user disconnects a proxy edge on
the root view, remove the corresponding real edge touching `entryNodeId` or `exitNodeId`.
When they create a new proxy edge, create the real edge on the boundary node.

**Edge case — duplicate synthetic ids**: Synthetic node id prefix `__group__` must never
be used as a real node id. Document in code; enforce in `buildStepNode` id generation.

---

### Hard Part 3 — Capability validation on synthetic Group nodes

`workflow-canvas.tsx` → `isValidConnection` uses `computeOutcomeProvides(nodes, edges)`.

At root view, pass **projected** nodes/edges into validation so Group nodes participate
in connection checks. The synthetic Group node must carry:

- **Input (`requires`)** copied from `entryNode.data.requires` / `requiresParsed`.
- **Output (`success` handle)** copied from `exitNode.data.produces` / `producesParsed`.

When the user connects upstream → Group input, validation runs against entry requirements.
When connecting Group success → downstream, `computeOutcomeProvides` must emit exit
produces on handle `__group__G:success`.

**Option A (recommended)**: Run `computeOutcomeProvides` on projected root graph only when
`activeGroupId === null`. Inside a group, run on the inner subgraph (no synthetic nodes).

**Option B**: Run always on full flat graph — Group validation won't work on root without
projection.

**Stale derived data**: When a member step's capabilities change (config modal), re-derive
Group node data on next projection — do not cache on the group record.

---

### Hard Part 4 — `computeOutcomeProvides` and inner views

Inside a group, upstream steps **outside** the group are not visible but their capabilities
flow in through the entry node (real edge from outside → entry already exists).

Validation for the first inner step should still work because the real edge into
`entryNodeId` exists in `allEdges` and entry is visible in the inner projection.

**Verify explicitly**: first step inside group shows valid connection from outside step
when viewed from inside (the incoming edge should appear if you include boundary-crossing
edges in inner view — **recommended**: include edges where `target === entryNodeId` even
if source is outside, rendered as a dangling left-side indicator or listed in a small
"External inputs" panel; minimum v1: rely on existing real edge in data and only validate
on root view).

Document the v1 decision in code comments to avoid confusion during implementation.

---

### Hard Part 5 — Save, load, and dirty state

- `canvas_groups` is part of saved workflow JSON; changes mark workflow dirty.
- `validateCanvasWorkflow` continues to validate the **full** flat graph (all real nodes,
  all real edges). Groups do not affect validity.
- On load: reset `activeGroupId` and `groupNavigationStack` to root.
- **Orphan repair** on load (defensive): remove group entries whose `nodeIds` reference
  missing nodes; dissolve groups with fewer than 2 members.

---

### Hard Part 6 — Selection, properties panel, and keyboard flows

| Scenario | Expected behaviour |
|----------|-------------------|
| Click Group node on root | Properties shows group title, member count, Rename, Ungroup, Enter group |
| Double-click Group node | `enterGroup(groupId)` |
| Multi-select includes grouped members on root | Members are hidden on root — multi-select cannot include them; only Group node is selectable |
| Multi-select inside group | Align, delete, (future) add to new group |
| `handleFocusStepOnCanvas` from executions | If step is grouped, auto `enterGroup` then select step |
| Config modal | Always opened by real node id; never by synthetic Group id |

---

## UI components

### `GroupNode` (`components/nodes/group-node.tsx`)

- Same footprint as workflow nodes (`w-80` × `h-32`) for visual consistency.
- Icon: `FolderOpen` or `Group` from Lucide.
- One target handle (`input`), one source handle (`success`).
- Subtitle: `"N steps"`.
- Double-click → `enterGroup`.
- Register in `workflow-canvas.tsx` `nodeTypes.groupNode`.

### Breadcrumb bar

Place above the canvas (inside `workflow-builder-page.tsx` or a thin
`CanvasGroupBreadcrumb` component):

```
Workflow root  ›  Attribute updates
[ Go to upper group ]
```

- Shown when `activeGroupId !== null`.
- Segments are clickable to jump to that level (v1: only two levels, so one button is
  enough).

### Properties panel additions

**Multi-select panel** (`multi-step-layout-panel.tsx` or sibling):

- Button: **Group selected steps** (calls boundary validation + create group).

**Group node selected** (new section in `workflow-properties-panel.tsx`):

- Editable title.
- Member count (read-only).
- **Open group** / **Ungroup** buttons.

---

## Implementation phases

### Phase 0 — Backend persistence scaffold

- [ ] Alembic migration: `workflows.canvas_groups JSONB NOT NULL DEFAULT '[]'`
- [ ] SQLAlchemy model + Pydantic models + repository pass-through
- [ ] Frontend types + save/load wiring (can save empty `[]` before UI exists)

### Phase 1 — Data + projection (no UI)

- [ ] `CanvasGroup` type, `canvas-group-boundary.ts`, `canvas-group-projection.ts`
- [ ] Unit tests for projection and boundary detection (see Testing)
- [ ] `useCanvasGroups` hook holding `groups` state in builder page

### Phase 2 — Root view rendering

- [ ] `GroupNode` component
- [ ] Wire `projectCanvasView` into canvas props
- [ ] Breadcrumb + `enterGroup` / `exitToParent`
- [ ] Manual test: hand-edit `canvas_groups` JSON to verify collapsed view

### Phase 3 — Mutations

- [ ] Round-trip connect/disconnect on group boundaries
- [ ] Drag Group node (updates `group.position`)
- [ ] Drag inner steps (updates real node positions)
- [ ] Delete / ungroup

### Phase 4 — Create group UX

- [ ] "Group selected steps" from multi-select panel
- [ ] Group properties (rename, ungroup, open)
- [ ] Toast errors for invalid selections

### Phase 5 — Polish

- [ ] Execution focus: navigate into group when focusing a grouped step
- [ ] Minimap works with projected nodes (should work automatically)
- [ ] Load repair for orphan groups
- [ ] Update `doc/WORKFLOW-STEPS-STYLE_GUIDE.md` with Group node styling note (optional)

---

## Files to create or modify

### New files

| File | Purpose |
|------|---------|
| `utils/canvas-group-projection.ts` | View projection + inverse mutation helpers |
| `utils/canvas-group-boundary.ts` | Group creation validation |
| `utils/canvas-group-projection.test.ts` | Projection unit tests |
| `utils/canvas-group-boundary.test.ts` | Boundary unit tests |
| `components/nodes/group-node.tsx` | Synthetic group node render |
| `components/canvas-group-breadcrumb.tsx` | Navigation breadcrumb (optional split) |
| `hooks/use-canvas-groups.ts` | Groups state + CRUD (optional) |

### Modified files

| File | Change |
|------|--------|
| `types/workflow-canvas.ts` | `CanvasGroup`, `GroupNodeData` |
| `types/workflow-persistence.ts` | `canvas_groups` field |
| `hooks/use-workflow-builder-store.ts` | Navigation state |
| `workflow-builder-page.tsx` | Groups state, projection, save/load, handlers |
| `components/workflow-canvas.tsx` | Projected nodes/edges, double-click, `groupNode` type |
| `components/workflow-properties-panel.tsx` | Group + create-group UI |
| `components/multi-step-layout-panel.tsx` | "Group selected steps" button |
| `backend/models/workflows.py` | Pydantic field |
| `backend/core/models/workflows.py` | DB column |
| `backend/repositories/workflow_repository.py` | CRUD |
| `backend/migrations/versions/NNN_add_canvas_groups.py` | Migration |

**Do not modify** `step_runner.py`, `registry.yaml`, or any step executor for v1.

---

## Testing

### Unit tests (required)

`canvas-group-projection.test.ts`:

1. Root projection hides member nodes, shows synthetic group node.
2. Internal edges omitted at root; boundary edges become proxy edges.
3. Inner projection shows only members and internal edges.
4. Linear chain 3 nodes → 1 group → root shows 1 group node, 2 proxy edges.

`canvas-group-boundary.test.ts`:

1. Valid linear chain accepted.
2. Reject: zero outside incoming.
3. Reject: two outside incoming.
4. Reject: node already in another group.
5. Reject: single node selection.

### Manual test script

1. Build Nautobot → Get attributes → 3× Update Attribute chain.
2. Group the three update steps; root shows one Group node.
3. Save, reload — group persists, still collapsed at root.
4. Double-click group — inner view shows 3 steps.
5. Go to upper group — root view restored.
6. Run workflow — all steps execute in order (verify in executions panel).
7. Connect new step to Group output on root — real edge attaches to exit node.
8. Ungroup — all steps visible on root again.

---

## v2 extensions (out of scope, design headroom)

| Feature | Notes |
|---------|-------|
| Nested groups | `parentGroupId`; projection recurses |
| Non-linear subgraphs | Multiple entry/exit or true DAG grouping; needs richer boundary UI |
| Drag step into/out of group | Drop target zones in inner view |
| Group colour / notes | Editor metadata on `CanvasGroup` |
| Collapse without drill-down | Inline expand on same canvas (alternative UX) |

---

## Open questions (for plan review)

1. **Separate DB column vs embed in node data** — this plan uses `canvas_groups` column
   for clarity; embedding in a wrapper object inside existing JSON is possible but couples
   migration to node parsing.
2. **Linear-only vs single-entry/single-exit DAG** — linear is simpler; DAG allows a
   short parallel section inside a group without v2.
3. **Show incoming external edge inside group view** — improves editability but adds UI
   work; v1 can rely on root view for external connections.
4. **Auto-group** — future convenience to group all consecutive steps of same `kind`.

---

## Summary

Groups are **view metadata** over an unchanged flat execution graph. The implementation
centers on `projectCanvasView` and careful **mutation round-tripping** at group
boundaries. v1 intentionally limits group creation to linear chains to ship the Update
Attribute use case quickly; the data model and projection function should be written to
allow nested and non-linear groups later without rewriting persistence.
