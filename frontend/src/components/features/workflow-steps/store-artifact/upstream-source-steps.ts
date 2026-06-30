import type { WorkflowCanvasNode } from "@/components/features/workflows/types/workflow-canvas";

export interface UpstreamSourceStep {
  nodeId: string;
  title: string;
  stepKind: string;
  outputKey?: string;
}

const SOURCE_STEP_KIND: Partial<Record<string, string>> = {
  command_output: "run-command",
  rendered_template: "render-jinja-template",
  merged_content: "merge-content",
  comparison_diff: "compare-data",
  filtered_output: "filter-output",
};

function readRenderOutputKey(node: WorkflowCanvasNode): string {
  const pluginConfig = (node.data.pluginConfig ?? {}) as Record<string, unknown>;
  if (typeof pluginConfig.output_key === "string" && pluginConfig.output_key.trim()) {
    return pluginConfig.output_key.trim();
  }
  return "device_config";
}

export function listUpstreamSourceSteps(
  nodes: WorkflowCanvasNode[],
  contentSource: string,
  currentNodeId: string,
): UpstreamSourceStep[] {
  const stepKind = SOURCE_STEP_KIND[contentSource];
  if (!stepKind) {
    return [];
  }

  return nodes
    .filter((node) => node.id !== currentNodeId && node.data.kind === stepKind)
    .map((node) => ({
      nodeId: node.id,
      title: node.data.title?.trim() || node.id,
      stepKind: node.data.kind,
      outputKey: stepKind === "render-jinja-template" ? readRenderOutputKey(node) : undefined,
    }));
}
