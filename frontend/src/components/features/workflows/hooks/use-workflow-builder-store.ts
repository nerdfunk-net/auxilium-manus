import { create } from "zustand";

type WorkflowMode = "editor" | "executions";

interface WorkflowBuilderState {
  workflowName: string;
  workflowStatus: "Draft" | "Saved" | "Running" | "Error";
  mode: WorkflowMode;
  selectedNodeId: string | null;
  lastAction: string;
  setMode: (mode: WorkflowMode) => void;
  selectNode: (nodeId: string | null) => void;
  markSaved: (message?: string) => void;
  markRunning: (message?: string) => void;
  markError: (message: string) => void;
}

export const useWorkflowBuilderStore = create<WorkflowBuilderState>((set) => ({
  workflowName: "Network backup workflow",
  workflowStatus: "Draft",
  mode: "editor",
  selectedNodeId: null,
  lastAction: "Ready to design workflow",
  setMode: (mode) => set({ mode }),
  selectNode: (selectedNodeId) => set({ selectedNodeId }),
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
