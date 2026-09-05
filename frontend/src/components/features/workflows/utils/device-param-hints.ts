const GET_FROM_USER_KIND = "get-from-user";

export type DeviceParamLookupMode = "manual" | "nautobot_search";

export interface DeviceParamConfig {
  lookupMode: DeviceParamLookupMode;
  /** Set when ``lookupMode`` is ``nautobot_search`` and the step has a
   * configured Nautobot source; empty otherwise. */
  sourceId: string;
}

/** Nodes loaded from the canvas or from a persisted workflow's
 * ``canvas_nodes`` — only ``data.kind`` / ``data.pluginConfig`` are read. */
export interface CanvasNodeLike {
  data?: {
    kind?: string;
    title?: string;
    pluginConfig?: Record<string, unknown>;
  };
}

export const EMPTY_DEVICE_PARAM_CONFIGS: Record<string, DeviceParamConfig> = {};

/**
 * Scan the canvas for ``get-from-user`` nodes and build a map from each
 * node's ``pluginConfig.device_param`` (a workflow static_attribute name) to
 * the Run Inputs / schedule UI widget that should collect its value.
 *
 * Intentionally scoped to ``get-from-user`` only. If two nodes point at the
 * same static_attribute with different modes or sources, the last node
 * encountered wins — an authoring mistake, not validated here.
 */
export function computeDeviceParamConfigs(
  nodes: CanvasNodeLike[],
): Record<string, DeviceParamConfig> {
  const configs: Record<string, DeviceParamConfig> = {};

  for (const node of nodes) {
    if (node.data?.kind !== GET_FROM_USER_KIND) {
      continue;
    }
    const config = node.data.pluginConfig ?? {};
    const deviceParam =
      typeof config.device_param === "string" ? config.device_param.trim() : "";
    if (!deviceParam) {
      continue;
    }

    const lookupMode: DeviceParamLookupMode =
      config.lookup_mode === "nautobot_search" ? "nautobot_search" : "manual";
    const sourceId =
      typeof config.nautobot_source_id === "string"
        ? config.nautobot_source_id.trim()
        : "";

    configs[deviceParam] = {
      lookupMode,
      sourceId: lookupMode === "nautobot_search" ? sourceId : "",
    };
  }

  return configs;
}
