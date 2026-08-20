# Frontend Large-File Refactoring Plan

**Source:** remaining files ≥400 lines after the splits already landed from `doc/refactoring/FRONTEND.md` (M9 ContentSourcePicker, M10 shared GitSourceSelectDialog, M11 `use-workflow-canvas.ts` facade). Line counts from `wc -l` on 2026-08-20, current tree.
**Goal:** Implement this document top-to-bottom with no further codebase analysis. After the last item, no *application* `.ts`/`.tsx` file under `frontend/src/components/features` should exceed **~400 lines**, except static help panels (`help-panel.tsx`, `jinja-help-dialog.tsx`) and generated Shadcn under `components/ui/`.
**Out of scope:** security/proxy/CSP work in `doc/refactoring/FRONTEND.md`; help-panel copy; Shadcn primitives; product redesign; merging inventory vs `get-nautobot-devices` condition trees (different types — do not unify in this plan).

Already done — **do not redo:**

| File now | Lines | What happened |
|----------|------:|---------------|
| `workflows/hooks/use-workflow-canvas.ts` | 73 | Facade over `use-workflow-canvas-core.ts` / `use-canvas-layout.ts` / `use-canvas-groups.ts` / `use-canvas-steps.ts` |
| `workflow-steps/shared/content-source-picker.tsx` | — | Shared picker; `CONTENT_SOURCE_OPTIONS` lives in `content-source-options.ts` |
| `workflow-steps/shared/git-source-select-dialog.tsx` | — | Single Git source picker |

`use-workflow-canvas-core.ts` is still **428** lines — that leftover is **L12**.

---

## How to implement

- Apply items **in the numbered order**. L1–L2 shrink several files at once; later splits assume those shared modules exist.
- Do not change step config JSON keys, workflow save payloads, or dialog UX. Move code; do not redesign.
- Keep `'use client'` on every extracted component/hook that uses hooks or event handlers.
- After each item: `cd frontend && npm run lint && npx tsc --noEmit`.
- After L1–L3 and L6–L8: `npx vitest run` (no new tests required unless an item says so; existing tests must stay green).
- After the last item: `find frontend/src/components/features -name '*.tsx' -o -name '*.ts' | xargs wc -l | awk '$1>=400'` — leftover hits should only be help panels / this plan's documented exceptions.

---

## Work order

| ID | Remaining after | Item |
|----|----------------:|------|
| L1 | store-artifact, compare-data, compare-pyats-snapshot | Shared filename placeholders + Git destination fieldset |
| L2 | add-to-nautobot, update-device, set-default-attributes dialogs | Shared Nautobot field-row / custom-field / interface-row primitives |
| L3 | store-artifact (706), compare-data (648) | Split remaining ConfigPanel sections into sibling files |
| L4 | template-editor-page (642) | Extract `use-template-editor.ts`; page becomes layout |
| L5 | sources-settings-canvas (638) | Extract `use-sources-settings.ts`; canvas becomes composition |
| L6 | workflow-import-dialog (603) | Extract file picker, credential remap, overwrite confirm |
| L7 | manage-inventory-modal (603) | Extract row editor + import/export bar |
| L8 | workflow-properties-panel (573) | Extract selected-edge / selected-step / multi-select panels |
| L9 | node-config-modal (531) | Extract General / Description tab bodies |
| L10 | add-to-nautobot-dialog (681), update-device-dialog (561), set-default-attributes-dialog (436) | Split remaining dialog sections (depends on L2) |
| L11 | condition-tree-builder (541), device-selector (470) | Extract add-condition bar; extract modal wiring hook |
| L12 | Remaining 400–525 line files | Canvas-core node changes, persistence payload, schedule cron, manage-dialog list, logging overrides, leftover ConfigPanels |

---

## Current inventory (≥400 lines, excluding `ui/` and tests)

| Lines | File |
|------:|------|
| 706 | `workflow-steps/store-artifact/index.tsx` |
| 681 | `workflow-steps/add-to-nautobot/add-to-nautobot-dialog.tsx` |
| 648 | `workflow-steps/compare-data/index.tsx` |
| 642 | `templates/template-editor-page.tsx` |
| 638 | `settings/components/sources-settings-canvas.tsx` |
| 603 | `workflows/dialogs/workflow-import-dialog.tsx` |
| 603 | `inventory/dialogs/manage-inventory-modal.tsx` |
| 573 | `workflows/components/workflow-properties-panel.tsx` |
| 561 | `workflow-steps/update-nautobot-device/update-device-dialog.tsx` |
| 541 | `inventory/components/condition-tree-builder.tsx` |
| 531 | `workflows/components/node-config-modal.tsx` |
| 525 | `workflows/dialogs/workflow-manage-dialog.tsx` |
| 515 | `workflow-steps/compare-pyats-snapshot/index.tsx` |
| 470 | `inventory/components/device-selector.tsx` |
| 457 | `workflow-steps/upload-config/index.tsx` |
| 445 | `workflow-steps/deploy-rendered-template/index.tsx` |
| 436 | `workflows/components/workflow-schedule-panel.tsx` |
| 436 | `workflow-steps/set-default-attributes/set-default-attributes-dialog.tsx` |
| 428 | `workflows/hooks/use-workflow-canvas-core.ts` |
| 425 | `workflow-steps/filter-output/index.tsx` |
| 422 | `workflows/hooks/use-workflow-persistence.ts` |
| 399 | `settings/components/logging-settings-canvas.tsx` (watch — include in L12) |

---

## L1 — Shared filename placeholders + Git destination fieldset

**Files:** new `frontend/src/components/features/workflow-steps/shared/filename-placeholders.ts`; new `frontend/src/components/features/workflow-steps/shared/git-destination-fields.tsx`; edit `store-artifact/index.tsx`, `compare-data/index.tsx`, `compare-pyats-snapshot/index.tsx`.

### Why

Three ConfigPanels copy the same `{device.name}` placeholder list. `store-artifact` and `compare-data` also duplicate the “choose git repo + subdirectory + pull/commit/push + commit message” block (~120 lines each). `GitSourceConfigPanel` only covers `git_source_id` for git-* steps — it is **not** this fieldset. Do not stretch it; add a sibling.

### Code before — placeholder arrays (three copies)

```51:66:frontend/src/components/features/workflow-steps/store-artifact/index.tsx
const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
  "{command.name}",
  "{parsed.output_key}",
  "{run.timestamp}",
  "{run.date}",
  "{run.id}",
];

const COMMIT_MESSAGE_PLACEHOLDERS = ["{timestamp}", "{run.id}", "{workflow.id}"];
```

`compare-data/index.tsx` ~69–80 is the same list **without** `{nautobot.custom_fields.<slug>}`. `compare-pyats-snapshot/index.tsx` ~41 is the compare-data list. Export the **union** (store-artifact’s list) as the shared constant; extra placeholders in the hint are harmless.

### Code after — `workflow-steps/shared/filename-placeholders.ts` (new, entire file)

```ts
export const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
  "{command.name}",
  "{parsed.output_key}",
  "{run.timestamp}",
  "{run.date}",
  "{run.id}",
] as const;

export const COMMIT_MESSAGE_PLACEHOLDERS = [
  "{timestamp}",
  "{run.id}",
  "{workflow.id}",
] as const;

export function filenamePlaceholderHint(prefix = "Placeholders"): string {
  return `${prefix}: ${FILENAME_PLACEHOLDERS.join(", ")}.`;
}
```

Replace every local `FILENAME_PLACEHOLDERS` / `COMMIT_MESSAGE_PLACEHOLDERS` with these imports. Keep the surrounding hint sentence in each step (store-artifact mentions subdirectories; compare-pyats says “No …”).

### Code before — Git destination block (`store-artifact/index.tsx` ~330–470, mirrored in `compare-data` when `reference_location === "git"`)

Choose-repository button, `GitSourceSelectDialog`, `repository_subdirectory` input, three checkboxes (`pull_before_write`, `commit_after_write`, `push_after_write`), `commit_message_template` input. Keys and labels must stay identical.

### Code after — `workflow-steps/shared/git-destination-fields.tsx` (new)

```tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { GitSourceSelectDialog } from "./git-source-select-dialog";
import { COMMIT_MESSAGE_PLACEHOLDERS } from "./filename-placeholders";

export interface GitDestinationValues {
  git_source_id: string;
  repository_subdirectory: string;
  pull_before_write: boolean;
  commit_after_write: boolean;
  push_after_write: boolean;
  commit_message_template: string;
}

interface GitDestinationFieldsProps {
  values: GitDestinationValues;
  gitSourceOpen: boolean;
  onGitSourceOpenChange: (open: boolean) => void;
  onChange: (patch: Partial<GitDestinationValues>) => void;
  idPrefix: string;
}

export function GitDestinationFields({
  values,
  gitSourceOpen,
  onGitSourceOpenChange,
  onChange,
  idPrefix,
}: GitDestinationFieldsProps) {
  // Move the JSX from store-artifact/index.tsx ~330–470 verbatim.
  // Use `${idPrefix}-pull-before-write` etc. so two panels on one canvas
  // do not collide (store-artifact vs compare-data).
  return null; // replace with moved JSX
}
```

### Code after — call site in `store-artifact/index.tsx`

```tsx
<GitDestinationFields
  idPrefix="store-artifact"
  gitSourceOpen={gitSourceOpen}
  onGitSourceOpenChange={setGitSourceOpen}
  values={{
    git_source_id: gitSourceId,
    repository_subdirectory:
      typeof config.repository_subdirectory === "string"
        ? config.repository_subdirectory
        : "",
    pull_before_write: config.pull_before_write === true,
    commit_after_write: config.commit_after_write === true,
    push_after_write: config.push_after_write === true,
    commit_message_template:
      typeof config.commit_message_template === "string"
        ? config.commit_message_template
        : "commit {timestamp}",
  }}
  onChange={(patch) => onChange(buildStoreArtifactConfig(config, patch))}
/>
```

Same pattern in `compare-data` with `buildCompareDataConfig`. `compare-pyats-snapshot` only needs the placeholder import unless it also has the git fieldset — if it does, wire `GitDestinationFields` the same way.

**Verify:** `grep -rn "FILENAME_PLACEHOLDERS = \[" frontend/src` returns only `filename-placeholders.ts`. `grep -rn "pull_before_write" frontend/src/components/features/workflow-steps` shows the shared fieldset plus config builders, not duplicated checkbox JSX. Store-artifact / compare-data git destination still saves the same keys.

---

## L2 — Shared Nautobot dialog field primitives

**Files:** new `frontend/src/components/features/workflow-steps/shared/nautobot-field-rows.tsx`; edit `add-to-nautobot/add-to-nautobot-dialog.tsx`, `update-nautobot-device/update-device-dialog.tsx`, `set-default-attributes/set-default-attributes-dialog.tsx`.

### Why

`OptionalFieldRow` in add-to-nautobot (~118–150) and `FieldRow` in update-device (~85–117) are the same checkbox+input. `set-default-attributes-dialog.tsx` has `OptionalFieldRow` again. Custom-field row lists and interface row lists (name / type / status / ip / namespace / primary) are the same shape in add-to-nautobot and update-device.

Do **not** merge the dialogs or their config types (`AddToNautobotConfig` vs `UpdateNautobotDeviceConfig`). Only extract presentational rows.

### Code before — `update-device-dialog.tsx` `FieldRow`

```85:117:frontend/src/components/features/workflow-steps/update-nautobot-device/update-device-dialog.tsx
function FieldRow({
  label,
  placeholder,
  spec,
  onChange,
}: {
  label: string;
  placeholder: string;
  spec: UpdateFieldSpec;
  onChange: (patch: Partial<UpdateFieldSpec>) => void;
}) {
  return (
    <div className="space-y-1 rounded-lg border border-border bg-muted p-2.5">
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={spec.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
          className="size-4 rounded border accent-step"
          aria-label={`Enable ${label}`}
        />
        <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      </div>
      <Input
        className="h-8 text-xs focus-visible:ring-step/40 disabled:opacity-50"
        disabled={!spec.enabled}
        placeholder={placeholder}
        value={spec.value}
        onChange={(event) => onChange({ value: event.target.value })}
      />
    </div>
  );
}
```

### Code after — `workflow-steps/shared/nautobot-field-rows.tsx` (new)

```tsx
"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface EnabledValueSpec {
  enabled: boolean;
  value: string;
}

export function NautobotRequiredFieldRow({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  // Move RequiredFieldRow JSX from add-to-nautobot-dialog.tsx ~87–116.
}

export function NautobotOptionalFieldRow({
  label,
  placeholder,
  spec,
  onChange,
}: {
  label: string;
  placeholder: string;
  spec: EnabledValueSpec;
  onChange: (patch: Partial<EnabledValueSpec>) => void;
}) {
  // Move FieldRow / OptionalFieldRow JSX verbatim (see Code before).
}

export interface NautobotInterfaceRowValues {
  id: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace: string;
  description?: string;
  is_primary_ipv4?: boolean;
}

export function NautobotInterfaceRow({
  row,
  onChange,
  onRemove,
}: {
  row: NautobotInterfaceRowValues;
  onChange: (patch: Partial<NautobotInterfaceRowValues>) => void;
  onRemove: () => void;
}) {
  // Move one interface card from add-to-nautobot-dialog (name, type, status,
  // ip, namespace, description, primary checkbox, trash). Keep input names
  // and classes identical.
}

export interface NautobotCustomFieldRowValues {
  id: string;
  name: string;
  enabled: boolean;
  value: string;
}

export function NautobotCustomFieldRow({
  row,
  onChange,
  onRemove,
}: {
  row: NautobotCustomFieldRowValues;
  onChange: (patch: Partial<NautobotCustomFieldRowValues>) => void;
  onRemove: () => void;
}) {
  // Move one custom-field row (enable checkbox, name, value, trash).
}
```

Delete the local copies. Wire `NautobotOptionalFieldRow` from all three dialogs. Wire interface/custom-field rows from add-to-nautobot and update-device. `set-default-attributes-dialog.tsx` uses the optional row + its own interface helper — use `NautobotOptionalFieldRow` and `NautobotInterfaceRow` if the fields match; if a field is missing on that step, pass empty strings, do not add new config keys.

**Verify:** add-to-nautobot / update-device / set-default-attributes dialogs look unchanged. `grep -n "function FieldRow\|function OptionalFieldRow\|function RequiredFieldRow" frontend/src/components/features/workflow-steps` returns only the shared file.

---

## L3 — Split remaining store-artifact / compare-data ConfigPanels

**Files:** new `store-artifact/destination-fields.tsx`, `store-artifact/content-fields.tsx`; new `compare-data/reference-fields.tsx`, `compare-data/content-fields.tsx`; slim both `index.tsx` files. Keep `buildStoreArtifactConfig` / `buildCompareDataConfig` in `index.tsx` or move to `store-artifact-config.ts` / `compare-data-config.ts` next to the existing pattern in `upload-config/upload-config-config.ts`.

### Why

After L1 each file is still ~500+ lines of one ConfigPanel. Split by **form section**, not by hooks vs JSX (the handlers are 1:1 with fields).

### Code before — `store-artifact/index.tsx` structure

```
buildStoreArtifactConfig
StoreArtifactConfigPanel
  destination select (filesystem | git)
  GitDestinationFields          // after L1
  content source picker
  source step / parsed key
  filename template + strict_templates + retention
StoreArtifactPlugin export
```

### Code after — `store-artifact/content-fields.tsx` (new)

```tsx
"use client";

import { ContentSourcePicker } from "@/components/features/workflow-steps/shared/content-source-picker";
import type { ContentSource } from "@/components/features/workflow-steps/shared/content-source-options";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";
// ... Select for source_step_node_id / parsed_output_key ...

export function StoreArtifactContentFields(/* props: the content-source slice of the panel */) {
  // JSX currently under the ContentSourcePicker in index.tsx
}
```

### Code after — `store-artifact/destination-fields.tsx` (new)

Filesystem vs git radio/select + subdirectory + (when git) `<GitDestinationFields />`. Filename template + retention stay in `index.tsx` or a third `filename-fields.tsx` if `index.tsx` is still over 400.

`index.tsx` keeps: `buildStoreArtifactConfig`, plugin export, `useEffect` init, and composition:

```tsx
function StoreArtifactConfigPanel(props: PluginConfigPanelProps) {
  // existing state + handlers
  return (
    <div className="flex flex-col gap-4">
      <StoreArtifactDestinationFields ... />
      <StoreArtifactContentFields ... />
      {/* filename + retention */}
      <StoreArtifactHelpPanel />
    </div>
  );
}
```

Mirror for `compare-data`: `CompareDataContentFields` (picker + source step) and `CompareDataReferenceFields` (filesystem vs git path + `GitDestinationFields`). Keep the comparison-diff copy button in `index.tsx`.

**Verify:** `wc -l` on each new/changed file in these two packages < 400. Opening store-artifact and compare-data config modals still shows every field in the same order.

---

## L4 — Template editor: extract hook, leave page as layout

**Files:** new `frontend/src/components/features/templates/hooks/use-template-editor.ts`; slim `template-editor-page.tsx`.

### Why

Panels already exist (`GeneralPanel`, `NetmikoOptionsPanel`, `CodeEditorPanel`, `VariablesPanel`, dialogs). The page file is 642 lines because **all state and handlers** live in `TemplateEditorContent`. Move them into a hook; the page only renders.

Do not merge this with `doc/refactoring/FRONTEND.md` M4–M7 if those already landed (device attributes query, explicit SSH fetch, render mutation). This item only **moves** remaining state out of the page.

### Code before — `template-editor-page.tsx` ~52–464

`TemplateEditorContent` declares ~20 `useState`s, wires queries/mutations, `handleSave`, command/config fetch, export. Return JSX starts at ~475.

### Code after — `templates/hooks/use-template-editor.ts` (new)

```ts
"use client";

export function useTemplateEditor() {
  // Move everything currently in TemplateEditorContent *except* the return JSX
  // and the loading spinner branch. Return a single memoized object:

  return useMemo(
    () => ({
      isEditMode,
      isLoading: isEditMode && templateQuery.isLoading,
      name, setName,
      description, setDescription,
      templateType, setTemplateType,
      content, setContent,
      // ...every value the JSX currently closes over...
      handleSave,
      isSaving,
      variableManager,
      renderer,
      // dialog open flags + setters
    }),
    [/* exhaustive */],
  );
}
```

### Code after — `template-editor-page.tsx`

```tsx
function TemplateEditorContent() {
  const editor = useTemplateEditor();

  if (editor.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <RefreshCw className="mr-2 size-5 animate-spin" />
        Loading template…
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      {/* existing JSX, replacing local names with editor.* */}
    </div>
  );
}
```

Keep `bareIp` in `utils/` (e.g. `templates/utils/bare-ip.ts`) if the hook still needs it — do not leave helpers in the page.

**Verify:** `wc -l template-editor-page.tsx` < 400; hook may be ~400 — if the hook exceeds 450, split save/export into `use-template-editor-save.ts`. Create / edit / render / get-configs still work.

---

## L5 — Sources settings: extract hook

**Files:** new `frontend/src/components/features/settings/hooks/use-sources-settings.ts`; slim `sources-settings-canvas.tsx`.

### Why

The canvas already composes five `SourceListSection`s plus five dialogs. ~400 lines are query wiring and `saveNautobot` / `saveGit` / `saveIse` / … / delete / pull / remove-and-clone. Extract that; leave JSX.

### Code before — `sources-settings-canvas.tsx` ~70–370

`DialogState`, all source queries/mutations, `*ById` maps, `existing*Ids`, `saveNautobot` … `saveMattermost`, delete handlers, pull / remove-and-clone.

### Code after — `settings/hooks/use-sources-settings.ts` (new)

```ts
"use client";

export type SourcesDialogState =
  | { type: "closed" }
  | { type: "nautobot"; mode: "create" | "edit"; sourceId?: string }
  | { type: "git"; mode: "create" | "edit"; sourceId?: string }
  | { type: "ise"; mode: "create" | "edit"; sourceId?: string }
  | { type: "pyats"; mode: "create" | "edit"; sourceId?: string }
  | { type: "mattermost"; mode: "create" | "edit"; sourceId?: string }
  | {
      type: "delete";
      sourceType: "nautobot" | "git" | "ise" | "pyats" | "mattermost";
      sourceId: string;
      key: string;
    }
  | { type: "remove-and-clone"; sourceId: string };

export function useSourcesSettings() {
  // Move DialogState, queries, save*/delete*/pull handlers verbatim.
  return useMemo(() => ({ dialog, setDialog, /* lists, handlers */ }), [/* ... */]);
}
```

### Code after — `sources-settings-canvas.tsx`

Keep the five `SourceListSection` blocks and the dialog switch at the bottom; replace local state with `const sources = useSourcesSettings()`.

**Verify:** `wc -l sources-settings-canvas.tsx` < 400. Create/edit/delete/pull still work for each source type.

---

## L6 — Workflow import dialog split

**Files:** new `workflows/dialogs/workflow-import-file-field.tsx`, `workflows/dialogs/workflow-import-credential-remap.tsx`, `workflows/dialogs/workflow-import-overwrite-dialog.tsx` (or one `workflow-import/` folder); slim `workflow-import-dialog.tsx`.

### Why

One dialog owns file parse, RHF metadata, credential remap, template-create summary, name-clash overwrite, and `performSave`. Utils already live in `utils/workflow-import.ts` — only UI/state is fat.

### Code before — file picker (~200–231 and JSX ~384–397)

```200:231:frontend/src/components/features/workflows/dialogs/workflow-import-dialog.tsx
  const handleChooseFile = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = parseWorkflowExportFile(JSON.parse(text));
        setImportFile(parsed);
        // ...
      } catch (err) {
        // ...
      }
    };
    input.click();
  }, [reset]);
```

### Code after — `workflow-import-file-field.tsx`

```tsx
"use client";

export function WorkflowImportFileField({
  importFile,
  parseError,
  onParsed,
  onError,
}: {
  importFile: WorkflowExportFile | null;
  parseError: string | null;
  onParsed: (file: WorkflowExportFile) => void;
  onError: (message: string) => void;
}) {
  const handleChooseFile = useCallback(() => {
    // move handleChooseFile; call onParsed/onError instead of setState
  }, [onParsed, onError]);

  return (
    <div className="grid gap-1.5">
      <Label>File</Label>
      <Button type="button" variant="outline" onClick={handleChooseFile}>
        {importFile ? "Choose a different file…" : "Choose file…"}
      </Button>
      {/* success / parseError copy unchanged */}
    </div>
  );
}
```

### Code after — `workflow-import-credential-remap.tsx`

Move the remap `Select` list (the block that maps `remapRequirements` → credential dropdowns) unchanged. Props: `requirements`, `credentials`, `value`, `onChange`.

### Code after — overwrite confirm

If overwrite UI is a second `Dialog` or an inline banner, move it to `workflow-import-overwrite.tsx` with `pendingOverwrite`, `onConfirm`, `onCancel`.

`workflow-import-dialog.tsx` keeps RHF, `performSave`, `onSubmit`, and composes the three pieces.

**Verify:** import with credential remap, template create, and name overwrite still work. Parent file < 400 lines.

---

## L7 — Manage inventory modal split

**Files:** new `inventory/dialogs/manage-inventory-row.tsx`, `inventory/dialogs/manage-inventory-import-export.tsx`; slim `manage-inventory-modal.tsx`.

### Why

`GroupTreePanel` is already extracted. The modal still inlines edit/delete/export per row (~200 lines of handlers + row JSX) and a hidden-file import control.

### Code before — handlers ~202–259 plus the per-inventory row JSX later in the file

`saveEdit`, `handleDeleteClick`, `confirmDelete`, `handleExport`, `handleImportClick`.

### Code after — `manage-inventory-row.tsx`

```tsx
"use client";

export function ManageInventoryRow({
  inventory,
  isEditing,
  deleteConfirmId,
  isDeleting,
  isExporting,
  // edit field values + setters, or a small edit draft object
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDeleteClick,
  onExport,
}: { /* ... */ }) {
  // Move one row's view/edit/delete-confirm markup verbatim.
}
```

### Code after — `manage-inventory-import-export.tsx`

Move `handleImportClick` + the Import/Export toolbar buttons.

Parent keeps group-tree selection, `parseInventoryTree`, and maps `savedInventories` → `ManageInventoryRow`.

**Verify:** rename, delete (two-click confirm), export, import, group rename still work. Modal file < 400.

---

## L8 — Workflow properties panel split

**Files:** new `workflows/components/selected-edge-panel.tsx`, `workflows/components/selected-step-panel.tsx`, `workflows/components/multi-select-panel.tsx`; slim `workflow-properties-panel.tsx`.

### Why

`StepCatalog`, `WorkflowSchedulePanel`, `WorkflowStaticAttributesPanel`, `MultiStepLayoutPanel` are already children. The remaining bulk is the **properties** tab: edge labels/style, single-step inspector, multi-select actions. That JSX is ~300 lines inline from ~259.

### Code before — `workflow-properties-panel.tsx` ~259

```259:276:frontend/src/components/features/workflows/components/workflow-properties-panel.tsx
          {selectedEdge ? (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
                Connection
              </span>
              <div className="mt-2 flex items-center gap-2 text-[14px] font-semibold">
                <span className="min-w-0 truncate">
                  {sourceNode?.data.title ?? selectedEdge.source}
                </span>
                <MoveRight className="size-4 shrink-0 text-muted-foreground" />
                ...
```

### Code after — three panels, same props the parent already has

```tsx
{selectedEdge ? (
  <SelectedEdgePanel
    edge={selectedEdge}
    sourceTitle={sourceNode?.data.title}
    targetTitle={targetNode?.data.title}
    onEdgeStyleChange={onEdgeStyleChange}
    onEdgeLabelChange={onEdgeLabelChange}
    onEdgeStartLabelChange={onEdgeStartLabelChange}
    onEdgeEndLabelChange={onEdgeEndLabelChange}
    onEdgeLabelBoldChange={onEdgeLabelBoldChange}
    onEdgeLabelFontSizeChange={onEdgeLabelFontSizeChange}
    onDeleteEdge={onDeleteEdge}
  />
) : isMultiSelect ? (
  <MultiSelectPanel
    nodes={selectedCanvasNodes}
    onAlignNodes={onAlignNodes}
    onAutoLayoutNodes={onAutoLayoutNodes}
    onGroupSelectedSteps={onGroupSelectedSteps}
    onDeleteNodes={onDeleteNodes}
    autoLayoutDirection={autoLayoutDirection}
    isAutoLayoutRunning={isAutoLayoutRunning}
  />
) : singleNode ? (
  <SelectedStepPanel
    node={singleNode}
    plugins={plugins}
    onOpenConfig={() => openConfigModal(singleNode.id)}
    onNodeTitleChange={onNodeTitleChange}
    onDuplicateNode={onDuplicateNode}
    onDeleteNodes={onDeleteNodes}
    onRenameGroup={onRenameGroup}
    onUngroupGroup={onUngroupGroup}
    onOpenGroup={onOpenGroup}
  />
) : (
  <>
    <WorkflowSchedulePanel />
    <WorkflowStaticAttributesPanel
      staticAttributes={staticAttributes}
      onStaticAttributesChange={onStaticAttributesChange}
    />
  </>
)}
```

Move `EDGE_STYLE_OPTIONS` / `EDGE_STYLE_DESCRIPTIONS` into `selected-edge-panel.tsx`. Move `DataContractChips` with `SelectedStepPanel` if only that panel uses it.

Parent keeps collapse chrome, Steps/Properties toggle, and `StepCatalog`.

**Verify:** selecting a step, an edge, and multiple steps still shows the same controls. Parent < 400 lines.

---

## L9 — Node config modal: extract tab bodies

**Files:** new `workflows/components/node-config-general-tab.tsx`, `workflows/components/node-config-description-tab.tsx`; slim `node-config-modal.tsx`. Keep `FieldRow` / `CapabilityList` / `SectionHeader` / `OutcomeRow` / `MockConfigRow` in `node-config-description-tab.tsx` (they are only used there).

### Why

The modal shell (dialog + tab list + plugin ConfigPanel slot) is ~180 lines. General tab (name + handle sides) and Description tab (capabilities/schema/help) are the rest.

### Code before — General tab ~277–365; Description tab ~408–503

Leave Configuration tab and dynamic `visibleModalTabs` in the parent — those only render `pluginUI.ConfigPanel`.

### Code after — `node-config-general-tab.tsx`

```tsx
"use client";

export function NodeConfigGeneralTab({
  activeNode,
  plugin,
  onNodeTitleChange,
  onNodeIncomeHandleSideChange,
  onNodeOutcomeHandleSideChange,
}: { /* ... */ }) {
  // Move TabsContent value="general" inner JSX, without the TabsContent wrapper
  // (parent still wraps in TabsContent) OR include TabsContent here — pick one
  // and use it for both extracted tabs. Prefer including TabsContent so the
  // parent is only TabsList + tab sequence.
}
```

### Code after — parent

```tsx
<Tabs defaultValue="general" className="flex min-h-0 flex-1 flex-col">
  <TabsList>...</TabsList>
  <NodeConfigGeneralTab ... />
  {hasConfigTab ? (
    <TabsContent value="configuration">{pluginUI.ConfigPanel}</TabsContent>
  ) : null}
  {visibleModalTabs.map(...)}
  <NodeConfigDescriptionTab plugin={plugin} activeNode={activeNode} />
  <TabsContent value="help">{pluginUI.HelpPanel ?? <HelpUnavailable />}</TabsContent>
</Tabs>
```

**Verify:** handle-side selects, step rename, description schema, and plugin ConfigPanel still work. Modal file < 400.

---

## L10 — Nautobot dialogs: remaining section split

**Depends on L2.** After field rows move out, add-to-nautobot (~681) and update-device (~561) should drop by ~150–200 lines. If either is still ≥400, split **sections** into sibling files in the same folder.

**Files (only if still ≥400 after L2):**

- `add-to-nautobot/device-fields-section.tsx` — required + optional + rack fields
- `add-to-nautobot/interfaces-section.tsx` — interface list + add button
- `add-to-nautobot/custom-fields-section.tsx`
- `add-to-nautobot/virtual-chassis-section.tsx`
- `update-nautobot-device/update-fields-section.tsx` + `interfaces-section.tsx` (or reuse add-to-nautobot section components if props match)

`set-default-attributes-dialog.tsx` (436): after L2 it should fall under 400. If not, extract its interface list the same way.

### Code after — example `device-fields-section.tsx`

```tsx
export function AddToNautobotDeviceFieldsSection({
  fields,
  onPatchRequired,
  onPatchOptional,
}: {
  fields: DeviceFieldsConfig;
  onPatchRequired: (key: DeviceFieldKey, value: string) => void;
  onPatchOptional: (key: DeviceFieldKey, patch: Partial<UpdateFieldSpec>) => void;
}) {
  return (
    <>
      {REQUIRED_DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
        <NautobotRequiredFieldRow
          key={key}
          label={label}
          placeholder={placeholder}
          value={/* current required value */}
          onChange={(value) => onPatchRequired(key, value)}
        />
      ))}
      {/* optional + rack: NautobotOptionalFieldRow */}
    </>
  );
}
```

Dialog form keeps `buildInitialDraft`, `onChange` aggregation, and footer buttons.

**Verify:** saving add-to-nautobot / update-device still writes the same config object. Each new section file < 250 lines; each dialog `index`/dialog file < 400.

---

## L11 — Condition tree builder + device selector

**Files:** new `inventory/components/add-condition-bar.tsx`; new `inventory/hooks/use-device-selector-modals.ts`; slim `condition-tree-builder.tsx` and `device-selector.tsx`.

### Why

`ConditionTreeBuilder` already delegates nodes to `ConditionGroup` / `ConditionItem`. The fat part is the **toolbar** (field/operator/value + add group/condition + path breadcrumb + action buttons). `DeviceSelector` is an orchestrator of modals; extract modal open-state + load/save callbacks.

### Code before — `condition-tree-builder.tsx` toolbar (the block with `Plus`, field `Select`, operator `Select`, value `Input`, AND/OR group add)

Move that markup to `AddConditionBar` with the callbacks the builder already receives (`addConditionToTree`, `addGroup`, …).

### Code after — `add-condition-bar.tsx`

```tsx
"use client";

export function AddConditionBar({
  fieldOptions,
  customFields,
  onAddCondition,
  onAddGroup,
}: {
  fieldOptions: FieldOption[];
  customFields: CustomField[];
  onAddCondition: (field: string, operator: string, value: string) => void;
  onAddGroup: (logic: "AND" | "OR", negate: boolean) => void;
}) {
  // local draft state for the "new condition" row currently inside the builder
}
```

Builder keeps tree rendering + `currentGroupPath` breadcrumb.

### Code after — `use-device-selector-modals.ts`

```ts
"use client";

export function useDeviceSelectorModals() {
  // Move useState for help / load / save / manage / logical-tree / save-device-list
  // and the handlers that open them. DeviceSelector JSX stays, but
  // `const modals = useDeviceSelectorModals()` replaces a dozen useStates.
}
```

**Verify:** adding conditions/groups, preview, save/load/manage still work. Both files < 400.

---

## L12 — Remaining 400–525 line files

Do these as **one PR after L1–L11**, each a mechanical extract. Stop when `wc -l` is under 400.

### L12a — `use-workflow-canvas-core.ts` (428)

**Files:** new `workflows/hooks/use-canvas-node-changes.ts`.

`handleNodesChange` is ~178–302. Move it (and any helpers it closes over that are *only* used there, e.g. containment / z-index on drag) into `useCanvasNodeChanges({ allNodes, setAllNodes, groups, markDirty, ... })`. Core keeps state, projection, `handleEdgesChange`, `handleConnect`, `handleViewportChange`, `applyLoadedCanvas`, `clearCanvas`.

**Verify:** dragging, snapping, deleting via React Flow change, and group containment still work. Facade `use-workflow-canvas.ts` **does not change**.

### L12b — `use-workflow-persistence.ts` (422)

**Files:** new `workflows/utils/canvas-persist-payload.ts`.

### Code before — repeated payload in `handleSaveAs` / `handleOverwrite` / `handleSave`

```ts
canvas_nodes: allNodes as unknown as Record<string, unknown>[],
canvas_edges: allEdges as unknown as Record<string, unknown>[],
canvas_groups: groups as unknown as Record<string, unknown>[],
static_attributes: staticAttributes,
```

### Code after

```ts
export function canvasPersistPayload(
  allNodes: PersistedCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  staticAttributes: StaticAttributeDef[],
) {
  return {
    canvas_nodes: allNodes as unknown as Record<string, unknown>[],
    canvas_edges: allEdges as unknown as Record<string, unknown>[],
    canvas_groups: groups as unknown as Record<string, unknown>[],
    static_attributes: staticAttributes,
  };
}
```

If the hook is still ≥400, move `handleSaveAs` + `handleOverwrite` + `handleSave` into `use-workflow-save.ts` that takes `canvas` + store setters. Do not change dialog open flags.

### L12c — `workflow-schedule-panel.tsx` (436)

**Files:** new `workflows/utils/schedule-cron.ts`.

Move `DAY_OPTIONS`, `buildCronExpression` (~69), `parseCronExpression` (~92) unchanged. Panel keeps RHF + tabs.

**Verify:** hourly/daily/weekly/custom still round-trip the same cron strings. Add a vitest file `schedule-cron.test.ts` with 3–4 examples taken from the current helper (copy a daily and a weekly case from manual UI: e.g. daily 09:00 → the expression the helper already produces — snapshot the *current* output, do not invent a new cron dialect).

### L12d — `workflow-manage-dialog.tsx` (525)

`WorkflowRow` and `DeleteConfirmRow` are already at the bottom of the same file (~423+). **Move them** to `workflow-manage-row.tsx`. If the parent is still ≥400, extract the filter/search bar into `workflow-manage-filters.tsx`.

### L12e — `logging-settings-canvas.tsx` (399)

Extract the per-logger override Card (the list + add-name input ~330–381) to `logging-overrides-card.tsx`. Parent keeps root level + workflow.log fields.

### L12f — Leftover step ConfigPanels after L1

If still ≥400:

| File | Extract |
|------|---------|
| `compare-pyats-snapshot/index.tsx` | exclude-keys list UI → `exclude-keys-fields.tsx`; reuse `GitDestinationFields` if not already |
| `upload-config/index.tsx` | timeout + credential selects → `upload-config-fields.tsx` (config helpers already in `upload-config-config.ts`) |
| `filter-output/index.tsx` | rule list → `filter-rules-fields.tsx` |
| `deploy-rendered-template/index.tsx` | credential + command preview → `deploy-fields.tsx` |

Move JSX only; keep `build*Config` next to the plugin export or in the existing `*-config.ts`.

**Verify (L12):** `awk '$1>=400'` on `frontend/src/components/features` shows only `help-panel.tsx` / `jinja-help-dialog.tsx` / this document’s exceptions. Canvas drag, save workflow, schedule, manage-workflow, logging overrides, and the four leftover steps still configure as before.

---

## Suggested PR grouping

| PR | Items | Why together |
|----|-------|----------------|
| 1 | L1 | Shared primitives used by later ConfigPanel splits |
| 2 | L2 | Shared primitives used by L10 |
| 3 | L3 | store-artifact + compare-data |
| 4 | L4 + L5 | Unrelated pages; both are “extract hook” |
| 5 | L6 + L7 | Dialog splits |
| 6 | L8 + L9 | Workflow chrome |
| 7 | L10 | Nautobot dialogs |
| 8 | L11 | Inventory |
| 9 | L12 | Sweep |

Do not combine L1 with L3 in the same commit — L3 rebases cleanly on L1.

---

## Done when

```bash
cd frontend && npm run lint && npx tsc --noEmit && npx vitest run
find frontend/src/components/features \( -name '*.ts' -o -name '*.tsx' \) \
  ! -name 'help-panel.tsx' ! -name 'jinja-help-dialog.tsx' \
  -print0 | xargs -0 wc -l | awk '$1>=400 {print}'
```

The awk listing should be empty (or only files this plan explicitly exempted). No step config key, workflow persist payload, or settings API shape has changed.
