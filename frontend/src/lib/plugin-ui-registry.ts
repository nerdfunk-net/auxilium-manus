import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { AddToIsePlugin } from "@/components/features/workflow-steps/add-to-ise";
import { CompareDataPlugin } from "@/components/features/workflow-steps/compare-data";
import { FanInPlugin } from "@/components/features/workflow-steps/fan-in";
import { FilterOutputPlugin } from "@/components/features/workflow-steps/filter-output";
import { MergeContentPlugin } from "@/components/features/workflow-steps/merge-content";
import { GetDeviceConfigsPlugin } from "@/components/features/workflow-steps/get-device-configs";
import { ParseCiscoConfigPlugin } from "@/components/features/workflow-steps/parse-cisco-config";
import { GetFromListPlugin } from "@/components/features/workflow-steps/get-from-list";
import { GetGitDevicesPlugin } from "@/components/features/workflow-steps/get-git-devices";
import { GetIseDevicesPlugin } from "@/components/features/workflow-steps/get-ise-devices";
import { GetIseTacacsKeyPlugin } from "@/components/features/workflow-steps/get-ise-tacacs-key";
import { GitClonePlugin } from "@/components/features/workflow-steps/git-clone";
import { GitPullPlugin } from "@/components/features/workflow-steps/git-pull";
import { GitPushPlugin } from "@/components/features/workflow-steps/git-push";
import { GetNautobotDevicesPlugin } from "@/components/features/workflow-steps/get-nautobot-devices";
import { GetNautobotAttributesPlugin } from "@/components/features/workflow-steps/get-nautobot-attributes";
import { RouteOnAttributePlugin } from "@/components/features/workflow-steps/route-on-attribute";
import { RouteOnContentPlugin } from "@/components/features/workflow-steps/route-on-content";
import { ListContainsPlugin } from "@/components/features/workflow-steps/list-contains";
import { RenderJinjaTemplatePlugin } from "@/components/features/workflow-steps/render-jinja-template";
import { RunCommandPlugin } from "@/components/features/workflow-steps/run-command";
import { LogAttributesPlugin } from "@/components/features/workflow-steps/log-attributes";
import { WorkflowLogPlugin } from "@/components/features/workflow-steps/workflow-log";
import { StoreArtifactPlugin } from "@/components/features/workflow-steps/store-artifact";
import { UpdateNautobotDevicePlugin } from "@/components/features/workflow-steps/update-nautobot-device";
import { UpdateAttributePlugin } from "@/components/features/workflow-steps/update-attribute";
import { UpdateIseTacacsKeyPlugin } from "@/components/features/workflow-steps/update-ise-tacacs-key";

const PLUGIN_UI_REGISTRY: Record<string, PluginUIComponent> = {
  "get-nautobot-devices": GetNautobotDevicesPlugin,
  "get-from-list": GetFromListPlugin,
  "get-git-devices": GetGitDevicesPlugin,
  "get-ise-devices": GetIseDevicesPlugin,
  "get-ise-tacacs-key": GetIseTacacsKeyPlugin,
  "get-nautobot-attributes": GetNautobotAttributesPlugin,
  "get-device-configs": GetDeviceConfigsPlugin,
  "parse-cisco-config": ParseCiscoConfigPlugin,
  "run-command": RunCommandPlugin,
  "route-on-attribute": RouteOnAttributePlugin,
  "route-on-content": RouteOnContentPlugin,
  "list-contains": ListContainsPlugin,
  "fan-in": FanInPlugin,
  "merge-content": MergeContentPlugin,
  "filter-output": FilterOutputPlugin,
  "compare-data": CompareDataPlugin,
  "render-jinja-template": RenderJinjaTemplatePlugin,
  "store-artifact": StoreArtifactPlugin,
  "git-clone": GitClonePlugin,
  "git-pull": GitPullPlugin,
  "git-push": GitPushPlugin,
  "update-nautobot-device": UpdateNautobotDevicePlugin,
  "update-attribute": UpdateAttributePlugin,
  "update-ise-tacacs-key": UpdateIseTacacsKeyPlugin,
  "add-to-ise": AddToIsePlugin,
  "workflow-log": WorkflowLogPlugin,
  "log-attributes": LogAttributesPlugin,
};

export function getPluginUI(pluginId: string): PluginUIComponent | undefined {
  return PLUGIN_UI_REGISTRY[pluginId];
}
