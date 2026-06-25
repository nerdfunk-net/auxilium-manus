import { treeToOperations } from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/tree-to-operation";
import {
  emptyTree,
  type FilterTree,
} from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/types";
import { nautobotSourceIdFromConfig } from "@/components/features/workflow-steps/shared/nautobot-source-config";
import type { DevicePreview } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";
import type { WorkflowCanvasNode } from "@/components/features/workflows/types/workflow-canvas";

function filterFromConfig(config: Record<string, unknown>): FilterTree {
  const raw = config.device_filter;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const filter = raw as Record<string, unknown>;
    if (Array.isArray(filter.items)) {
      return raw as FilterTree;
    }
  }
  return emptyTree();
}

export interface WorkflowInventoryStep {
  nodeId: string;
  title: string;
  sourceId: string;
}

export function listInventorySteps(nodes: WorkflowCanvasNode[]): WorkflowInventoryStep[] {
  return nodes
    .filter((node) => node.data.kind === "get-nautobot-devices")
    .map((node) => ({
      nodeId: node.id,
      title: node.data.title || node.id,
      sourceId: nautobotSourceIdFromConfig(
        (node.data.pluginConfig ?? {}) as Record<string, unknown>,
      ),
    }))
    .filter((step) => Boolean(step.sourceId));
}

export function inventoryOperationsFromNode(node: WorkflowCanvasNode) {
  const config = (node.data.pluginConfig ?? {}) as Record<string, unknown>;
  const tree = filterFromConfig(config);
  return treeToOperations(tree);
}

export function devicePreviewToPayload(
  device: DevicePreview,
  sourceId: string,
): Record<string, unknown> {
  return {
    id: device.id,
    name: device.name ?? device.id,
    hostname: device.name ?? device.id,
    platform: device.platform ?? undefined,
    primary_ip4: device.primary_ip4 ?? undefined,
    source: "nautobot",
    source_id: sourceId,
    capabilities: ["identity"],
    status: "ok",
    attribute_bags: {
      nautobot: {
        role: device.role ? { name: device.role } : undefined,
        location: device.location ? { name: device.location } : undefined,
        device_type: device.device_type ? { model: device.device_type } : undefined,
        manufacturer: device.manufacturer ? { name: device.manufacturer } : undefined,
        tags: device.tags.map((name) => ({ name })),
        status: device.status ? { name: device.status } : undefined,
      },
    },
  };
}
