import { create } from "zustand";

import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { StaticAttributeDef, WorkflowVisibility } from "../types/workflow-persistence";
import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";

type RightPanelTab = "steps" | "properties";
type RunMode = "normal" | "debug";

/**
 * Snapshot of the in-progress (possibly unsaved) canvas, keyed by the
 * workflowId it belongs to (null = an unsaved new workflow). This is a
 * module-level Zustand singleton, so unlike the canvas `useState` in
 * WorkflowBuilderPage it survives that component unmounting when the user
 * navigates to another route (Inventory, Runs, Settings) and back.
 */
interface CanvasDraft {
  workflowId: number | null;
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
  staticAttributes: StaticAttributeDef[];
  /** Pan/zoom at the time of unmount, so it isn't force-refit on remount. */
  viewport: { x: number; y: number; zoom: number } | null;
}

interface WorkflowMetadata {
  workflowId: number | null;
  workflowUuid: string | null;
  workflowName: string;
  workflowDescription: string;
  workflowFolder: string;
  workflowVisibility: WorkflowVisibility;
  workflowIsVersionControlled: boolean;
}

interface WorkflowBuilderState extends WorkflowMetadata {
  workflowStatus: "Draft" | "Saved" | "Running" | "Error";
  isDirty: boolean;
  runMode: RunMode;
  activeRunId: number | null;
  rightPanelTab: RightPanelTab;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  configModalNodeId: string | null;
  lastAction: string;
  stepCatalogExpanded: Record<string, boolean>;
  overviewPanelOpen: boolean;
  /** null = root canvas view */
  activeGroupId: string | null;
  /** Stack for breadcrumb; [] means root. Last item = current view. */
  groupNavigationStack: string[];
  canvasDraft: CanvasDraft | null;
  /** Shared by every auto-layout entry point (selection panel, canvas-level
   * control) — not a persisted workflow setting, just a UI preference. */
  autoLayoutDirection: AutoLayoutDirection;
  /** Rounds a dragged node's position to `SNAP_GRID` (workflow-canvas.tsx).
   * Not a persisted workflow setting — resets to off each page load. */
  snapToGrid: boolean;
  /** Toggles the canvas alignment grid (React Flow <Background> in
   * workflow-canvas.tsx). UI-only, resets to off each page load. */
  showGrid: boolean;
  /**
   * Node ids the canvas should `fitView` to next, set once a
   * `handleAutoLayout` run resolves and cleared once WorkflowCanvas has
   * acted on it. Trigger-style transient state, same pattern as
   * `configModalNodeId`.
   */
  pendingFitViewNodeIds: string[] | null;
  setCanvasDraft: (draft: CanvasDraft) => void;
  enterGroup: (groupId: string) => void;
  exitToParent: () => void;
  exitToRoot: () => void;
  setRunMode: (runMode: RunMode) => void;
  setActiveRunId: (activeRunId: number | null) => void;
  setRightPanelTab: (tab: RightPanelTab) => void;
  selectNode: (nodeId: string | null) => void;
  selectEdge: (edgeId: string | null) => void;
  selectCanvasBackground: () => void;
  openConfigModal: (nodeId: string) => void;
  closeConfigModal: () => void;
  setAutoLayoutDirection: (direction: AutoLayoutDirection) => void;
  setSnapToGrid: (snapToGrid: boolean) => void;
  setShowGrid: (showGrid: boolean) => void;
  requestFitView: (nodeIds: string[]) => void;
  clearFitViewRequest: () => void;
  toggleStepCatalogCategory: (artifactType: string) => void;
  setOverviewPanelOpen: (open: boolean) => void;
  markSaved: (message?: string) => void;
  markDirty: () => void;
  markRunning: (message?: string) => void;
  markError: (message: string) => void;
  setWorkflowId: (id: number | null) => void;
  setWorkflowUuid: (uuid: string | null) => void;
  setWorkflowName: (name: string) => void;
  setWorkflowDescription: (description: string) => void;
  setWorkflowFolder: (folder: string) => void;
  setWorkflowVisibility: (visibility: WorkflowVisibility) => void;
  setWorkflowIsVersionControlled: (isVersionControlled: boolean) => void;
  loadWorkflow: (meta: WorkflowMetadata) => void;
  resetToNew: () => void;
}

const NEW_WORKFLOW_DEFAULTS: WorkflowMetadata = {
  workflowId: null,
  workflowUuid: null,
  workflowName: "Untitled Workflow",
  workflowDescription: "",
  workflowFolder: "/",
  workflowVisibility: "private",
  workflowIsVersionControlled: false,
};

export const useWorkflowBuilderStore = create<WorkflowBuilderState>((set) => ({
  ...NEW_WORKFLOW_DEFAULTS,
  workflowStatus: "Draft",
  isDirty: false,
  runMode: "normal",
  activeRunId: null,
  rightPanelTab: "steps",
  selectedNodeId: null,
  selectedEdgeId: null,
  configModalNodeId: null,
  lastAction: "Ready to design workflow",
  stepCatalogExpanded: {},
  overviewPanelOpen: true,
  activeGroupId: null,
  groupNavigationStack: [],
  canvasDraft: null,
  autoLayoutDirection: "horizontal",
  snapToGrid: false,
  showGrid: false,
  pendingFitViewNodeIds: null,
  setCanvasDraft: (draft) => set({ canvasDraft: draft }),
  enterGroup: (groupId) =>
    set((state) => {
      const groupNavigationStack = [...state.groupNavigationStack, groupId];
      return { groupNavigationStack, activeGroupId: groupId };
    }),
  exitToParent: () =>
    set((state) => {
      const groupNavigationStack = state.groupNavigationStack.slice(0, -1);
      return {
        groupNavigationStack,
        activeGroupId: groupNavigationStack[groupNavigationStack.length - 1] ?? null,
      };
    }),
  exitToRoot: () => set({ groupNavigationStack: [], activeGroupId: null }),
  setRunMode: (runMode) => set({ runMode }),
  setActiveRunId: (activeRunId) => set({ activeRunId }),
  setRightPanelTab: (rightPanelTab) => set({ rightPanelTab }),
  selectNode: (selectedNodeId) =>
    set({
      selectedNodeId,
      selectedEdgeId: null,
      rightPanelTab: selectedNodeId ? "properties" : "steps",
    }),
  selectEdge: (selectedEdgeId) =>
    set({
      selectedEdgeId,
      selectedNodeId: null,
      rightPanelTab: selectedEdgeId ? "properties" : "steps",
    }),
  // Explicit "user clicked the empty canvas" interaction — unlike selectNode(null)
  // (also used for rubber-band deselect), this always surfaces the Properties tab
  // since the nothing-selected state now hosts the workflow's schedule panel.
  selectCanvasBackground: () =>
    set({ selectedNodeId: null, selectedEdgeId: null, rightPanelTab: "properties" }),
  openConfigModal: (configModalNodeId) => set({ configModalNodeId }),
  closeConfigModal: () => set({ configModalNodeId: null }),
  setAutoLayoutDirection: (autoLayoutDirection) => set({ autoLayoutDirection }),
  setSnapToGrid: (snapToGrid) => set({ snapToGrid }),
  setShowGrid: (showGrid) => set({ showGrid }),
  requestFitView: (nodeIds) => set({ pendingFitViewNodeIds: nodeIds }),
  clearFitViewRequest: () => set({ pendingFitViewNodeIds: null }),
  toggleStepCatalogCategory: (artifactType) =>
    set((state) => ({
      stepCatalogExpanded: {
        ...state.stepCatalogExpanded,
        [artifactType]: !(state.stepCatalogExpanded[artifactType] ?? false),
      },
    })),
  setOverviewPanelOpen: (overviewPanelOpen) => set({ overviewPanelOpen }),
  markSaved: (message = "Workflow saved") =>
    set({
      workflowStatus: "Saved",
      isDirty: false,
      lastAction: message,
    }),
  markDirty: () => set({ isDirty: true, workflowStatus: "Draft" }),
  markRunning: (message = "Workflow run started") =>
    set({
      workflowStatus: "Running",
      lastAction: message,
    }),
  markError: (message) =>
    set({
      workflowStatus: "Error",
      lastAction: message,
    }),
  setWorkflowId: (workflowId) => set({ workflowId }),
  setWorkflowUuid: (workflowUuid) => set({ workflowUuid }),
  setWorkflowName: (workflowName) => set({ workflowName }),
  setWorkflowDescription: (workflowDescription) => set({ workflowDescription }),
  setWorkflowFolder: (workflowFolder) => set({ workflowFolder }),
  setWorkflowVisibility: (workflowVisibility) => set({ workflowVisibility }),
  setWorkflowIsVersionControlled: (workflowIsVersionControlled) =>
    set({ workflowIsVersionControlled }),
  loadWorkflow: (meta) =>
    set({
      workflowId: meta.workflowId,
      workflowUuid: meta.workflowUuid,
      workflowName: meta.workflowName,
      workflowDescription: meta.workflowDescription,
      workflowFolder: meta.workflowFolder,
      workflowVisibility: meta.workflowVisibility,
      workflowIsVersionControlled: meta.workflowIsVersionControlled,
      workflowStatus: "Saved",
      isDirty: false,
      activeRunId: null,
      activeGroupId: null,
      groupNavigationStack: [],
      lastAction: `Loaded "${meta.workflowName}"`,
    }),
  resetToNew: () =>
    set({
      ...NEW_WORKFLOW_DEFAULTS,
      workflowStatus: "Draft",
      isDirty: false,
      activeRunId: null,
      activeGroupId: null,
      groupNavigationStack: [],
      rightPanelTab: "steps",
      selectedNodeId: null,
      selectedEdgeId: null,
      configModalNodeId: null,
      lastAction: "New workflow created",
    }),
}));
