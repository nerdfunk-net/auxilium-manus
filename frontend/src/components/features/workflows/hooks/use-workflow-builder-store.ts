import { create } from "zustand";

import type { WorkflowVisibility } from "../types/workflow-persistence";

type RightPanelTab = "steps" | "properties";
type RunMode = "normal" | "debug";

interface WorkflowMetadata {
  workflowId: number | null;
  workflowUuid: string | null;
  workflowName: string;
  workflowDescription: string;
  workflowFolder: string;
  workflowVisibility: WorkflowVisibility;
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
  enterGroup: (groupId: string) => void;
  exitToParent: () => void;
  exitToRoot: () => void;
  setRunMode: (runMode: RunMode) => void;
  setActiveRunId: (activeRunId: number | null) => void;
  setRightPanelTab: (tab: RightPanelTab) => void;
  selectNode: (nodeId: string | null) => void;
  selectEdge: (edgeId: string | null) => void;
  openConfigModal: (nodeId: string) => void;
  closeConfigModal: () => void;
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
  openConfigModal: (configModalNodeId) => set({ configModalNodeId }),
  closeConfigModal: () => set({ configModalNodeId: null }),
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
  loadWorkflow: (meta) =>
    set({
      workflowId: meta.workflowId,
      workflowName: meta.workflowName,
      workflowDescription: meta.workflowDescription,
      workflowFolder: meta.workflowFolder,
      workflowVisibility: meta.workflowVisibility,
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
