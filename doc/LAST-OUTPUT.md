# Last Output — Topology-Aware Content Source Defaults

## Problem

Steps that consume device content (`store-artifact`, `filter-output`, `compare-data`) ask
the user to pick a `content_source` from a flat dropdown of eight options and then, for most
choices, also pick a `source_step_node_id` by node id. In a simple linear flow — run commands,
merge them, store the result — this means three manual selections for what is conceptually
"the output of the previous step."

The canvas already knows the graph topology. The goal is to use that knowledge so that when
the user opens a config panel for one of these consuming steps, the correct upstream source
is pre-selected automatically. The user can always override it; the intent is to make the
default obvious rather than require manual lookup.

---

## Solution: Topology-Aware Upstream Output Detection

The canvas computes a topological ordering of nodes to validate connections
(`computeOutcomeProvides` in `utils/capability-graph.ts`). The same edge map can be used to
walk backwards from any node and find the nearest content-producing upstream step.

No backend or data-model changes are required. This is purely a UI-layer improvement.

### Concept

Each step that modifies device content is called a **content producer**. Steps that only
route, log, or gate devices — without changing their content — are **pass-through** steps.
When a consuming step's config panel opens, the utility walks the edge graph backwards from
that node, skipping pass-through steps, and returns the first content producer it finds. That
descriptor is used to pre-populate `content_source` and `source_step_node_id`.

---

## Registry: `primary_output` field

Add an optional `primary_output` field to each step's registry entry. The field describes
what content the step produces for downstream steps. Pass-through steps omit it.

```yaml
# backend/workflow_steps/registry.yaml

plugins:
  - id: get-device-configs
    # ...
    primary_output: running_config          # first / most useful output

  - id: run-command
    # ...
    primary_output: command_output

  - id: merge-content
    # ...
    primary_output: merged_content

  - id: filter-output
    # ...
    primary_output: filtered_output

  - id: render-jinja-template
    # ...
    primary_output: rendered_template

  - id: compare-data
    # ...
    primary_output: comparison_diff         # only on mismatch outcome — consuming steps
                                            # connected to the "mismatch" handle need the diff

  # Pass-through steps (no primary_output field):
  # get-nautobot-devices, get-git-devices, get-nautobot-attributes,
  # route-on-attribute, workflow-log, fan-in, git-clone, git-pull, git-push
```

The frontend reads `primary_output` from the plugin definitions it already loads from
`GET /api/workflow-steps`. No additional API endpoint is needed.

---

## New Utility: `findUpstreamOutput`

**File:** `frontend/src/components/features/workflows/utils/upstream-output.ts`

```typescript
import type { WorkflowCanvasEdge, WorkflowCanvasNode } from "../types/workflow-canvas";
import type { PluginDefinition } from "../types/plugin-registry";

export interface UpstreamOutput {
  contentSource: string;   // e.g. "merged_content"
  sourceNodeId: string;    // the node id to put in source_step_node_id
  stepTitle: string;       // human-readable, for the UI hint
  stepKind: string;        // e.g. "merge-content"
}

/**
 * Walk the edge graph backwards from `nodeId`, skipping pass-through steps,
 * and return a descriptor for the nearest content-producing upstream step.
 *
 * Returns null when no content producer is found (e.g. node is a source step),
 * or when the immediate upstream is ambiguous (multiple converging branches
 * each producing different content types).
 */
export function findUpstreamOutput(
  nodeId: string,
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  plugins: PluginDefinition[],
): UpstreamOutput | null {
  const nodesById = new Map(nodes.map((n) => [n.id, n]));
  const pluginsById = new Map(plugins.map((p) => [p.id, p]));

  // Build parent map: nodeId → [parentNodeId, ...]
  const parents = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parents.get(edge.target) ?? [];
    list.push(edge.source);
    parents.set(edge.target, list);
  }

  // BFS backwards, skipping pass-through nodes
  const queue: string[] = [nodeId];
  const visited = new Set<string>([nodeId]);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const parentIds = parents.get(current) ?? [];

    for (const parentId of parentIds) {
      if (visited.has(parentId)) continue;
      visited.add(parentId);

      const parentNode = nodesById.get(parentId);
      if (!parentNode) continue;

      const plugin = pluginsById.get(parentNode.data.kind);
      const primaryOutput = (plugin as (PluginDefinition & { primary_output?: string }) | undefined)
        ?.primary_output;

      if (primaryOutput) {
        return {
          contentSource: primaryOutput,
          sourceNodeId: parentId,
          stepTitle: parentNode.data.title?.trim() || parentId,
          stepKind: parentNode.data.kind,
        };
      }

      // Pass-through: keep walking
      queue.push(parentId);
    }
  }

  return null;
}
```

### Ambiguity rule

If a consuming step has multiple parents (converging branches), BFS visits all of them in
parallel. When the first content-producer found from one branch differs from another, return
`null` — ambiguous, let the user choose manually. When both branches resolve to the same
content type and the same node id, return that result.

In practice, steps like `merge-content` sit at the convergence point and are themselves a
content producer, so BFS from a `store-artifact` placed after `merge-content` immediately
finds `merge-content` as the single parent — no ambiguity.

---

## Props Changes

### `PluginConfigPanelProps`

Add `workflowEdges` so config panels can run the upstream traversal:

**File:** `frontend/src/components/features/workflows/types/plugin-ui.ts`

```typescript
export interface PluginConfigPanelProps {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  onPreview: () => void;
  workflowNodes?: WorkflowCanvasNode[];
  workflowEdges?: WorkflowCanvasEdge[];      // ← new
  plugins?: PluginDefinition[];              // ← new (for primary_output lookup)
}
```

### `NodeConfigModal`

Pass `edges` and `plugins` down to the ConfigPanel:

**File:** `frontend/src/components/features/workflows/components/node-config-modal.tsx`

```typescript
// Add to NodeConfigModalProps
interface NodeConfigModalProps {
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];               // ← new
  plugins?: PluginDefinition[];
  // ...
}

// Inside the ConfigPanel render:
<pluginUI.ConfigPanel
  config={...}
  nodeId={activeNode.id}
  workflowNodes={workflowNodes}
  workflowEdges={edges}                      // ← new
  plugins={plugins}                          // ← new
  onChange={...}
  onPreview={...}
/>
```

`NodeConfigModal` is called from `workflow-builder-page.tsx` which already has both `edges`
and `plugins` in scope. Passing them through is a one-liner addition.

---

## "Upstream output" Virtual Option

Steps with a `content_source` selector (`store-artifact`, `filter-output`, `compare-data`)
gain a new virtual option at the top of their dropdown:

```
┌──────────────────────────────────────┐
│ ▼ Upstream output (auto-detected)    │  ← new, pre-selected when a producer is found
│   Running configuration              │
│   Startup configuration              │
│   Command output (specific step)     │
│   …                                  │
└──────────────────────────────────────┘
```

**Behaviour:**

| Situation | What happens |
|-----------|-------------|
| Config panel opens, `content_source` is unset, upstream producer found | Pre-select "Upstream output"; resolve `content_source` + `source_step_node_id` from `findUpstreamOutput`; call `onChange` silently |
| Config panel opens, `content_source` already saved | Respect the saved value — never overwrite explicit user choices |
| User selects "Upstream output" manually | Re-run `findUpstreamOutput` and apply the result |
| Upstream output is ambiguous or not found | "Upstream output" option shown but greyed out with a hint; no auto-apply |
| Graph is edited and upstream changes | Re-evaluate when the config panel is next opened (not live) |

The "Upstream output" value is **never persisted** in `pluginConfig`. When the user selects
it, the underlying `content_source` and `source_step_node_id` are what get saved — the
virtual option is purely a shortcut for selection. This means no backend change is needed and
the config remains fully explicit at execution time.

A small indicator label appears below the selector when auto-detection was used:

```
↑ Auto-detected from "Merge Commands" (merge-content)
```

---

## Steps Affected

### `store-artifact` (`index.tsx`)

1. Accept `workflowEdges` and `plugins` from props.
2. On mount (when `content_source` is unset), call `findUpstreamOutput` and apply.
3. Add "Upstream output" as the first `CONTENT_SOURCE_OPTIONS` entry.
4. Show the auto-detection hint label when the selection was auto-applied.

### `filter-output` (`index.tsx`)

`filter-output` already requires `content_source` and `source_step_node_id`. Apply the same
pattern: auto-detect on mount, add the virtual option, show hint.

### `compare-data` (`index.tsx`)

Same pattern. Note: `compare-data` is often placed after `filter-output` or `merge-content`,
so the auto-detection will typically resolve to `filtered_output` or `merged_content` — the
common case users find confusing today.

---

## `listUpstreamSourceSteps` Deprecation

The current `upstream-source-steps.ts` lists ALL workflow nodes of a matching kind (no
topology awareness). It is still correct for the node-id picker (when the user selects
"Command output (specific step)" they want to see every run-command in the workflow). Leave
it in place; `findUpstreamOutput` adds topology awareness on top for the default-selection
behaviour only.

---

## `PluginDefinition` type extension

**File:** `frontend/src/components/features/workflows/types/plugin-registry.ts`

Add the optional field so TypeScript knows about it:

```typescript
export interface PluginDefinition {
  // ... existing fields
  primary_output?: string;   // ← new; content source key this step produces
}
```

---

## Implementation Checklist

**Phase 1 — Infrastructure**

- [ ] Add `primary_output` to each content-producing step in `registry.yaml`
- [ ] Add `primary_output?: string` to `PluginDefinition` TypeScript interface
- [ ] Create `frontend/src/components/features/workflows/utils/upstream-output.ts`
      with `findUpstreamOutput` and its `UpstreamOutput` return type
- [ ] Extend `PluginConfigPanelProps` with `workflowEdges?` and `plugins?`
- [ ] Pass `edges` and `plugins` through `NodeConfigModal` → `ConfigPanel`

**Phase 2 — store-artifact**

- [ ] Add `{ value: "upstream_output", label: "Upstream output (auto-detected)", hint: "…" }`
      as first entry in `CONTENT_SOURCE_OPTIONS`
- [ ] On mount with no saved `content_source`, call `findUpstreamOutput` and apply result
- [ ] Show hint label "↑ Auto-detected from …" when auto-apply was used
- [ ] Greyed-out state and tooltip when result is null

**Phase 3 — filter-output and compare-data**

- [ ] Apply the same virtual option + auto-detect pattern to `filter-output/index.tsx`
- [ ] Apply the same virtual option + auto-detect pattern to `compare-data/index.tsx`

**Phase 4 — Tests**

- [ ] Unit test `findUpstreamOutput`:
  - linear chain resolves correctly
  - pass-through steps are skipped
  - ambiguous multi-branch returns null
  - node with no upstream returns null
- [ ] Snapshot or interaction test for store-artifact auto-select on mount

---

## Non-Goals

- No backend changes. `primary_output` in the registry is consumed by the frontend via the
  existing `GET /api/workflow-steps` response.
- No "Last Output" data field in `WorkflowContext` or `DeviceContext`. Content addressing
  remains explicit at execution time.
- No live re-evaluation when the graph changes while the modal is open. Re-evaluation happens
  on the next modal open.
- No change to capability/connection validation — that stays as-is in `capability-graph.ts`.
