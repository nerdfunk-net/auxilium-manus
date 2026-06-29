import { create } from "zustand";

import type { WorkflowVisibility } from "../types/workflow-persistence";

type WorkflowMode = "editor" | "executions";

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
  mode: WorkflowMode;
  isActionsPanelVisible: boolean;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  configModalNodeId: string | null;
  lastAction: string;
  setMode: (mode: WorkflowMode) => void;
  showActionsPanel: () => void;
  hideActionsPanel: () => void;
  toggleActionsPanel: () => void;
  selectNode: (nodeId: string | null) => void;
  selectEdge: (edgeId: string | null) => void;
  openConfigModal: (nodeId: string) => void;
  closeConfigModal: () => void;
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
  mode: "editor",
  isActionsPanelVisible: false,
  selectedNodeId: null,
  selectedEdgeId: null,
  configModalNodeId: null,
  lastAction: "Ready to design workflow",
  setMode: (mode) => set({ mode }),
  showActionsPanel: () => set({ isActionsPanelVisible: true, mode: "editor" }),
  hideActionsPanel: () => set({ isActionsPanelVisible: false }),
  toggleActionsPanel: () =>
    set((state) => ({
      isActionsPanelVisible: !state.isActionsPanelVisible,
      mode: "editor",
    })),
  selectNode: (selectedNodeId) => set({ selectedNodeId, selectedEdgeId: null }),
  selectEdge: (selectedEdgeId) => set({ selectedEdgeId, selectedNodeId: null }),
  openConfigModal: (configModalNodeId) => set({ configModalNodeId }),
  closeConfigModal: () => set({ configModalNodeId: null }),
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
      lastAction: `Loaded "${meta.workflowName}"`,
    }),
  resetToNew: () =>
    set({
      ...NEW_WORKFLOW_DEFAULTS,
      workflowStatus: "Draft",
      isDirty: false,
      selectedNodeId: null,
      selectedEdgeId: null,
      configModalNodeId: null,
      lastAction: "New workflow created",
    }),
}));
