import { useEffect, useState } from "react";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { getLoadedPluginUI, loadPluginUI } from "@/lib/plugin-ui-registry";

/**
 * The config/help panels of one step, loaded on first use. Returns undefined while loading (or
 * when the step has no panel); `hasPluginUI` tells those two apart.
 */
export function usePluginUI(pluginId: string | undefined): PluginUIComponent | undefined {
  const [loadedFor, setLoadedFor] = useState<{
    id: string;
    ui: PluginUIComponent;
  } | null>(null);

  useEffect(() => {
    if (!pluginId || getLoadedPluginUI(pluginId)) return;
    let cancelled = false;
    void loadPluginUI(pluginId).then((ui) => {
      if (!cancelled && ui) setLoadedFor({ id: pluginId, ui });
    });
    return () => {
      cancelled = true;
    };
  }, [pluginId]);

  if (!pluginId) return undefined;
  return getLoadedPluginUI(pluginId) ?? (loadedFor?.id === pluginId ? loadedFor.ui : undefined);
}
