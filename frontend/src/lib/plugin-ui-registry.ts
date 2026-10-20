import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";

/**
 * Step config panels, loaded on demand. A panel is needed only when a step's configuration or
 * help is opened, so none of them belong in the workflow page's first load (Q5-01). Use
 * `usePluginUI` (hooks/use-plugin-ui.ts) from components; `hasPluginUI` answers synchronously
 * whether a step has a panel at all.
 */
type PluginUILoader = () => Promise<PluginUIComponent>;

const PLUGIN_UI_LOADERS: Record<string, PluginUILoader> = {
  "get-nautobot-devices": () => import("@/components/features/workflow-steps/get-nautobot-devices").then((m) => m.GetNautobotDevicesPlugin),
  "get-from-list": () => import("@/components/features/workflow-steps/get-from-list").then((m) => m.GetFromListPlugin),
  "get-from-user": () => import("@/components/features/workflow-steps/get-from-user").then((m) => m.GetFromUserPlugin),
  "get-from-config": () => import("@/components/features/workflow-steps/get-from-config").then((m) => m.GetFromConfigPlugin),
  "get-git-devices": () => import("@/components/features/workflow-steps/get-git-devices").then((m) => m.GetGitDevicesPlugin),
  "from-change-request": () => import("@/components/features/workflow-steps/from-change-request").then((m) => m.FromChangeRequestPlugin),
  "get-catalyst-center-devices": () => import("@/components/features/workflow-steps/get-catalyst-center-devices").then((m) => m.GetCatalystCenterDevicesPlugin),
  "get-catalyst-center-configs": () => import("@/components/features/workflow-steps/get-catalyst-center-configs").then((m) => m.GetCatalystCenterConfigsPlugin),
  "get-catalyst-center-details": () => import("@/components/features/workflow-steps/get-catalyst-center-details").then((m) => m.GetCatalystCenterDetailsPlugin),
  "get-catalyst-center-topology": () => import("@/components/features/workflow-steps/get-catalyst-center-topology").then((m) => m.GetCatalystCenterTopologyPlugin),
  "get-catalyst-center-health": () => import("@/components/features/workflow-steps/get-catalyst-center-health").then((m) => m.GetCatalystCenterHealthPlugin),
  "run-catalyst-center-command": () => import("@/components/features/workflow-steps/run-catalyst-center-command").then((m) => m.RunCatalystCenterCommandPlugin),
  "get-ise-devices": () => import("@/components/features/workflow-steps/get-ise-devices").then((m) => m.GetIseDevicesPlugin),
  "get-ise-tacacs-key": () => import("@/components/features/workflow-steps/get-ise-tacacs-key").then((m) => m.GetIseTacacsKeyPlugin),
  "get-nautobot-attributes": () => import("@/components/features/workflow-steps/get-nautobot-attributes").then((m) => m.GetNautobotAttributesPlugin),
  "get-device-location": () => import("@/components/features/workflow-steps/get-device-location").then((m) => m.GetDeviceLocationPlugin),
  "get-virtual-chassis": () => import("@/components/features/workflow-steps/get-virtual-chassis").then((m) => m.GetVirtualChassisPlugin),
  "split-virtual-chassis": () => import("@/components/features/workflow-steps/split-virtual-chassis").then((m) => m.SplitVirtualChassisPlugin),
  "set-default-attributes": () => import("@/components/features/workflow-steps/set-default-attributes").then((m) => m.SetDefaultAttributesPlugin),
  "config-to-attributes": () => import("@/components/features/workflow-steps/config-to-attributes").then((m) => m.ConfigToAttributesPlugin),
  "get-device-configs": () => import("@/components/features/workflow-steps/get-device-configs").then((m) => m.GetDeviceConfigsPlugin),
  "read-config": () => import("@/components/features/workflow-steps/read-config").then((m) => m.ReadConfigPlugin),
  "read-from-file": () => import("@/components/features/workflow-steps/read-from-file").then((m) => m.ReadFromFilePlugin),
  "parse-cisco-config": () => import("@/components/features/workflow-steps/parse-cisco-config").then((m) => m.ParseCiscoConfigPlugin),
  "add-pyats-testbed": () => import("@/components/features/workflow-steps/add-pyats-testbed").then((m) => m.AddPyatsTestbedPlugin),
  "get-pyats-running-config": () => import("@/components/features/workflow-steps/get-pyats-running-config").then((m) => m.GetPyatsRunningConfigPlugin),
  "get-pyats-snapshot": () => import("@/components/features/workflow-steps/get-pyats-snapshot").then((m) => m.GetPyatsSnapshotPlugin),
  "get-batfish-devices": () => import("@/components/features/workflow-steps/get-batfish-devices").then((m) => m.GetBatfishDevicesPlugin),
  "batfish-init-snapshot": () => import("@/components/features/workflow-steps/batfish-init-snapshot").then((m) => m.BatfishInitSnapshotPlugin),
  "batfish-routing-table": () => import("@/components/features/workflow-steps/batfish-routing-table").then((m) => m.BatfishRoutingTablePlugin),
  "batfish-node-properties": () => import("@/components/features/workflow-steps/batfish-node-properties").then((m) => m.BatfishNodePropertiesPlugin),
  "batfish-interface-properties": () => import("@/components/features/workflow-steps/batfish-interface-properties").then((m) => m.BatfishInterfacePropertiesPlugin),
  "batfish-ospf-facts": () => import("@/components/features/workflow-steps/batfish-ospf-facts").then((m) => m.BatfishOspfFactsPlugin),
  "batfish-bgp-facts": () => import("@/components/features/workflow-steps/batfish-bgp-facts").then((m) => m.BatfishBgpFactsPlugin),
  "batfish-path-check": () => import("@/components/features/workflow-steps/batfish-path-check").then((m) => m.BatfishPathCheckPlugin),
  "batfish-acl-check": () => import("@/components/features/workflow-steps/batfish-acl-check").then((m) => m.BatfishAclCheckPlugin),
  "batfish-validate-facts": () => import("@/components/features/workflow-steps/batfish-validate-facts").then((m) => m.BatfishValidateFactsPlugin),
  "batfish-extract-facts": () => import("@/components/features/workflow-steps/batfish-extract-facts").then((m) => m.BatfishExtractFactsPlugin),
  "undefined-and-unused": () => import("@/components/features/workflow-steps/undefined-and-unused").then((m) => m.UndefinedAndUnusedPlugin),
  "run-command": () => import("@/components/features/workflow-steps/run-command").then((m) => m.RunCommandPlugin),
  "deploy-rendered-template": () => import("@/components/features/workflow-steps/deploy-rendered-template").then((m) => m.DeployRenderedTemplatePlugin),
  "route-on-attribute": () => import("@/components/features/workflow-steps/route-on-attribute").then((m) => m.RouteOnAttributePlugin),
  "route-on-content": () => import("@/components/features/workflow-steps/route-on-content").then((m) => m.RouteOnContentPlugin),
  "list-contains": () => import("@/components/features/workflow-steps/list-contains").then((m) => m.ListContainsPlugin),
  "exists-in-nautobot": () => import("@/components/features/workflow-steps/exists-in-nautobot").then((m) => m.ExistsInNautobotPlugin),
  "get-next-free-ip": () => import("@/components/features/workflow-steps/get-next-free-ip").then((m) => m.GetNextFreeIpPlugin),
  reachable: () => import("@/components/features/workflow-steps/reachable").then((m) => m.ReachablePlugin),
  "login-successful": () => import("@/components/features/workflow-steps/login-successful").then((m) => m.LoginSuccessfulPlugin),
  "fan-in": () => import("@/components/features/workflow-steps/fan-in").then((m) => m.FanInPlugin),
  "stop-here": () => import("@/components/features/workflow-steps/stop-here").then((m) => m.StopHerePlugin),
  "merge-config": () => import("@/components/features/workflow-steps/merge-config").then((m) => m.MergeConfigPlugin),
  "merge-content": () => import("@/components/features/workflow-steps/merge-content").then((m) => m.MergeContentPlugin),
  "filter-output": () => import("@/components/features/workflow-steps/filter-output").then((m) => m.FilterOutputPlugin),
  "collect-statistics": () => import("@/components/features/workflow-steps/collect-statistics").then((m) => m.CollectStatisticsPlugin),
  "compare-data": () => import("@/components/features/workflow-steps/compare-data").then((m) => m.CompareDataPlugin),
  "compare-pyats-snapshot": () => import("@/components/features/workflow-steps/compare-pyats-snapshot").then((m) => m.ComparePyatsSnapshotPlugin),
  "configure-replace-config": () => import("@/components/features/workflow-steps/configure-replace-config").then((m) => m.ConfigureReplaceConfigPlugin),
  "render-jinja-template": () => import("@/components/features/workflow-steps/render-jinja-template").then((m) => m.RenderJinjaTemplatePlugin),
  "store-artifact": () => import("@/components/features/workflow-steps/store-artifact").then((m) => m.StoreArtifactPlugin),
  "store-in-db": () => import("@/components/features/workflow-steps/store-in-db").then((m) => m.StoreInDbPlugin),
  "store-for-report": () => import("@/components/features/workflow-steps/store-for-report").then((m) => m.StoreForReportPlugin),
  "get-from-db": () => import("@/components/features/workflow-steps/get-from-db").then((m) => m.GetFromDbPlugin),
  "open-change-request": () => import("@/components/features/workflow-steps/open-change-request").then((m) => m.OpenChangeRequestPlugin),
  "git-clone": () => import("@/components/features/workflow-steps/git-clone").then((m) => m.GitClonePlugin),
  "git-pull": () => import("@/components/features/workflow-steps/git-pull").then((m) => m.GitPullPlugin),
  "git-push": () => import("@/components/features/workflow-steps/git-push").then((m) => m.GitPushPlugin),
  "git-status": () => import("@/components/features/workflow-steps/git-status").then((m) => m.GitStatusPlugin),
  "update-nautobot-device": () => import("@/components/features/workflow-steps/update-nautobot-device").then((m) => m.UpdateNautobotDevicePlugin),
  "start-nautobot-job": () => import("@/components/features/workflow-steps/start-nautobot-job").then((m) => m.StartNautobotJobPlugin),
  "check-nautobot-job": () => import("@/components/features/workflow-steps/check-nautobot-job").then((m) => m.CheckNautobotJobPlugin),
  "start-workflow": () => import("@/components/features/workflow-steps/start-workflow").then((m) => m.StartWorkflowPlugin),
  "update-config-context": () => import("@/components/features/workflow-steps/update-config-context").then((m) => m.UpdateConfigContextPlugin),
  "update-attribute": () => import("@/components/features/workflow-steps/update-attribute").then((m) => m.UpdateAttributePlugin),
  "encrypt-attribute": () => import("@/components/features/workflow-steps/encrypt-attribute").then((m) => m.EncryptAttributePlugin),
  "decrypt-attribute": () => import("@/components/features/workflow-steps/decrypt-attribute").then((m) => m.DecryptAttributePlugin),
  "update-content": () => import("@/components/features/workflow-steps/update-content").then((m) => m.UpdateContentPlugin),
  "update-ise-tacacs-key": () => import("@/components/features/workflow-steps/update-ise-tacacs-key").then((m) => m.UpdateIseTacacsKeyPlugin),
  "upload-config": () => import("@/components/features/workflow-steps/upload-config").then((m) => m.UploadConfigPlugin),
  "add-to-ise": () => import("@/components/features/workflow-steps/add-to-ise").then((m) => m.AddToIsePlugin),
  "add-to-nautobot": () => import("@/components/features/workflow-steps/add-to-nautobot").then((m) => m.AddToNautobotPlugin),
  "add-nautobot-metadata": () => import("@/components/features/workflow-steps/add-nautobot-metadata").then((m) => m.AddNautobotMetadataPlugin),
  "log-message": () => import("@/components/features/workflow-steps/log-message").then((m) => m.LogMessagePlugin),
  "log-attributes": () => import("@/components/features/workflow-steps/log-attributes").then((m) => m.LogAttributesPlugin),
  "show-summary": () => import("@/components/features/workflow-steps/show-summary").then((m) => m.ShowSummaryPlugin),
  notify: () => import("@/components/features/workflow-steps/notify").then((m) => m.NotifyPlugin),
  "notify-mattermost": () => import("@/components/features/workflow-steps/notify-mattermost").then((m) => m.NotifyMattermostPlugin),
  "notify-on-error": () => import("@/components/features/workflow-steps/notify-on-error").then((m) => m.NotifyOnErrorPlugin),
  "secret-get": () => import("@/components/features/workflow-steps/secret-get").then((m) => m.SecretGetPlugin),
  "secret-set": () => import("@/components/features/workflow-steps/secret-set").then((m) => m.SecretSetPlugin),
  "send-mail": () => import("@/components/features/workflow-steps/send-mail").then((m) => m.SendMailPlugin),
  "secret-generate": () => import("@/components/features/workflow-steps/secret-generate").then((m) => m.SecretGeneratePlugin),
  "generate-password": () => import("@/components/features/workflow-steps/generate-password").then((m) => m.GeneratePasswordPlugin),
  label: () => import("@/components/features/workflow-steps/label").then((m) => m.LabelPlugin),
  background: () => import("@/components/features/workflow-steps/background").then((m) => m.BackgroundPlugin),
  funnel: () => import("@/components/features/workflow-steps/funnel").then((m) => m.FunnelPlugin),
};

const loaded = new Map<string, PluginUIComponent>();
const inflight = new Map<string, Promise<PluginUIComponent | undefined>>();

export function hasPluginUI(pluginId: string): boolean {
  // Own keys only: `in` would also accept inherited ones such as "constructor".
  return Object.hasOwn(PLUGIN_UI_LOADERS, pluginId);
}

/** The panel set if it has been loaded already, else undefined (never triggers a load). */
export function getLoadedPluginUI(pluginId: string): PluginUIComponent | undefined {
  return loaded.get(pluginId);
}

export function loadPluginUI(pluginId: string): Promise<PluginUIComponent | undefined> {
  const ready = loaded.get(pluginId);
  if (ready) return Promise.resolve(ready);
  if (!hasPluginUI(pluginId)) return Promise.resolve(undefined);
  const loader = PLUGIN_UI_LOADERS[pluginId];
  let pending = inflight.get(pluginId);
  if (!pending) {
    pending = loader()
      .then((ui) => {
        loaded.set(pluginId, ui);
        return ui;
      })
      .finally(() => inflight.delete(pluginId));
    inflight.set(pluginId, pending);
  }
  return pending;
}
