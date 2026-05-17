import type { WorkflowNodeKind } from "./workflow-canvas";

export interface WorkflowDefinition {
  id: string;
  name: string;
  version: number;
  deviceSelection: {
    strategy: "manual" | "inventory-query";
    deviceIds: string[];
  };
  steps: WorkflowStepDefinition[];
}

export interface WorkflowStepDefinition {
  id: string;
  type: WorkflowNodeKind;
  name: string;
  description: string;
  dependsOn: string[];
  inputMappings: WorkflowInputMapping[];
  metadata: Record<string, string>;
}

export interface WorkflowInputMapping {
  sourceStepId: string;
  sourceOutcome: string;
  sourceKey: string;
  targetKey: string;
}
