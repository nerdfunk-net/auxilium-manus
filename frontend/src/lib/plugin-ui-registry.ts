import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { CompareDataPlugin } from "@/components/features/workflow-steps/compare-data";
import { FanInPlugin } from "@/components/features/workflow-steps/fan-in";
import { MergeContentPlugin } from "@/components/features/workflow-steps/merge-content";
import { GetDeviceConfigsPlugin } from "@/components/features/workflow-steps/get-device-configs";
import { GetGitDevicesPlugin } from "@/components/features/workflow-steps/get-git-devices";
import { GitClonePlugin } from "@/components/features/workflow-steps/git-clone";
import { GitPullPlugin } from "@/components/features/workflow-steps/git-pull";
import { GitPushPlugin } from "@/components/features/workflow-steps/git-push";
import { GetNautobotDevicesPlugin } from "@/components/features/workflow-steps/get-nautobot-devices";
import { GetNautobotAttributesPlugin } from "@/components/features/workflow-steps/get-nautobot-attributes";
import { RouteOnAttributePlugin } from "@/components/features/workflow-steps/route-on-attribute";
import { RenderJinjaTemplatePlugin } from "@/components/features/workflow-steps/render-jinja-template";
import { RunCommandPlugin } from "@/components/features/workflow-steps/run-command";
import { WorkflowLogPlugin } from "@/components/features/workflow-steps/workflow-log";
import { StoreArtifactPlugin } from "@/components/features/workflow-steps/store-artifact";

const PLUGIN_UI_REGISTRY: Record<string, PluginUIComponent> = {
  "get-nautobot-devices": GetNautobotDevicesPlugin,
  "get-git-devices": GetGitDevicesPlugin,
  "get-nautobot-attributes": GetNautobotAttributesPlugin,
  "get-device-configs": GetDeviceConfigsPlugin,
  "run-command": RunCommandPlugin,
  "route-on-attribute": RouteOnAttributePlugin,
  "fan-in": FanInPlugin,
  "merge-content": MergeContentPlugin,
  "compare-data": CompareDataPlugin,
  "render-jinja-template": RenderJinjaTemplatePlugin,
  "store-artifact": StoreArtifactPlugin,
  "git-clone": GitClonePlugin,
  "git-pull": GitPullPlugin,
  "git-push": GitPushPlugin,
  "workflow-log": WorkflowLogPlugin,
};

export function getPluginUI(pluginId: string): PluginUIComponent | undefined {
  return PLUGIN_UI_REGISTRY[pluginId];
}
