import { create } from "zustand";

type WorkflowMode = "editor" | "executions";

interface WorkflowBuilderState {
  workflowName: string;
  workflowStatus: "Draft" | "Saved" | "Running" | "Error";
  mode: WorkflowMode;
  isActionsPanelVisible: boolean;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  lastAction: string;
  setMode: (mode: WorkflowMode) => void;
  showActionsPanel: () => void;
  hideActionsPanel: () => void;
  toggleActionsPanel: () => void;
  selectNode: (nodeId: string | null) => void;
  selectEdge: (edgeId: string | null) => void;
  markSaved: (message?: string) => void;
  markRunning: (message?: string) => void;
  markError: (message: string) => void;
}

export const useWorkflowBuilderStore = create<WorkflowBuilderState>((set) => ({
  workflowName: "Network backup workflow",
  workflowStatus: "Draft",
  mode: "editor",
  isActionsPanelVisible: false,
  selectedNodeId: null,
  selectedEdgeId: null,
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
  markSaved: (message = "Workflow definition prepared locally") =>
    set({
      workflowStatus: "Saved",
      lastAction: message,
    }),
  markRunning: (message = "Mock execution started") =>
    set({
      workflowStatus: "Running",
      lastAction: message,
    }),
  markError: (message) =>
    set({
      workflowStatus: "Error",
      lastAction: message,
    }),
}));
