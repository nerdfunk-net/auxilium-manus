# Canvas Groups (Step Groups)

A **group** is a purely organisational container on the workflow canvas: a
collapsed node you can double-click to open and work inside, like a NiFi process
group. Groups have **no runtime meaning** — execution, run results, fan-out and
the capability model all operate on the flat step graph, and the backend never
interprets `canvas_groups` beyond the consistency repair described below.

## Canvas state architecture

Three arrays are the only stateful canvas data, owned by
`hooks/use-workflow-canvas-core.ts`:

- `allNodes` / `allEdges` — the **flat, authoritative graph** (every real step
  and every real edge, including steps inside groups).
- `groups` (`CanvasGroup[]`, persisted as `canvas_groups`) — membership only:
  `id`, `title`, `nodeIds`, `position`, optional `isContainer`, `parentGroupId`
  (reserved; nesting is not implemented) and optional `parentId`.
  `parentId` is the id of the **background** node a group is attached to — the
  same single-level containment steps use (`utils/canvas-containment.ts`),
  resolved on drag-end. When set, `position` is relative to that background (so
  the group moves with it); otherwise it is absolute. Deleting the background
  detaches the group to absolute coordinates; a dangling `parentId` is dropped
  on load (`repairOrphanGroups`). Not to be confused with `parentGroupId`.

Everything React Flow renders is a **pure projection** of those arrays
(`utils/canvas-group-projection.ts::projectCanvasView`) and must never be stored
in its own state. At the root level member steps are hidden and each group
becomes one synthetic node; inside an open group only that group's members and
their internal edges are shown.

Consequence: anything that needs "what does this step's upstream provide" must
use the **flat** graph (`computeOutcomeProvides(allNodes, allEdges)`, exposed as
`outcomeProvides`), never the rendered nodes/edges — an open group hides
everything outside it.

## Ports are derived, never stored

`utils/canvas-group-ports.ts::deriveGroupPorts(nodeIds, edges)` turns every edge
that crosses the group boundary into a port. Moving a step in or out of a group
only changes `nodeIds`; edges are untouched and the ports re-derive. The
collapsed node renders one handle per port (`in:<edgeId>` / `out:<edgeId>`),
labelled with the inner step's name. There is no chain, single-entry, single-exit
or cycle restriction on what can be grouped.

## Creating groups

- **Group selected steps** (multi-select panel): needs at least two steps, none
  already grouped, none inside a background (`validateGroupBoundary`). Such a
  group dissolves when it drops below two members.
- **Palette → Visuals → Step Group** (registry id `step-group`): creates an
  empty container group (`isContainer: true`) at the drop position. Container
  groups survive at any size, including empty. Not allowed while inside a group
  (no nesting).

## Moving steps in and out

- Side panel: **Move to group…** (root) / **Move out of group** (inside a group).
- Drag a step (or multi-selection) onto a collapsed group node; while inside a
  group, drag onto the "Drop here to move out of group" strip.
- Logic: `addNodesToGroup` / `removeNodesFromGroups`
  (`canvas-group-projection.ts`), wrapped by `handleMoveToGroup` /
  `handleMoveOutOfGroup` (`hooks/use-canvas-groups.ts`). Drag hit-testing:
  `utils/canvas-group-dnd.ts`.

## Connecting to and from a group

A collapsed group has no fixed step, so a connection touching it is resolved to a
member by `utils/group-connection-candidates.ts::listGroupConnectionCandidates`:

- **Input side:** members that accept input and whose `requires` are satisfied by
  the other end's provided capabilities (judged on the flat graph).
- **Output side:** (member, outcome) pairs whose provides satisfy the target.
- Existing port handle → that port's inner step only.
- Validation (`isValidConnection`) accepts the connection if at least one
  candidate exists. Exactly one → the edge is created directly; several →
  `GroupConnectionDialog` asks which step; none → error toast.
- Limit: when **both** ends are groups and either side has several candidates, the
  user must open a group and connect inside it. Group↔group connections are not
  capability-checked on the canvas (caught at run time).

## Backend

`canvas_groups` is stored as opaque JSON. The only backend logic is
`WorkflowService._repair_orphan_groups` (runs on create/update): it drops member
ids that no longer exist and dissolves selection groups left with fewer than two
members. **Container groups (`isContainer: true`) are never dissolved.**

## Key files

`frontend/src/components/features/workflows/`: `utils/canvas-group-projection.ts`,
`canvas-group-ports.ts`, `canvas-group-boundary.ts`, `canvas-group-dnd.ts`,
`group-connection-candidates.ts`, `hooks/use-canvas-groups.ts`,
`hooks/use-workflow-canvas-core.ts`, `components/nodes/group-node.tsx`,
`components/move-to-group-control.tsx`, `dialogs/group-connection-dialog.tsx`.
