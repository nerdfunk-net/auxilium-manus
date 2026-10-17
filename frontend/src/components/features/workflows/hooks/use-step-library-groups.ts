import { useMemo } from "react";

import { useBatfishSourcesQuery } from "@/hooks/queries/use-batfish-sources-query";
import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";
import { useSecretManagerConnectionsQuery } from "@/hooks/queries/use-secret-manager-connections-query";

import type { PluginDefinition } from "../types/plugin-registry";
import { groupPaletteItems, type PaletteGroup } from "../utils/step-catalog";
import { filterAvailableGroups } from "../utils/step-library-filter";

/** Palette groups for the Steps library, minus steps whose sources/connections aren't configured. */
export function useStepLibraryGroups(plugins: PluginDefinition[]): PaletteGroup[] {
  const { data: pyatsSourcesData } = usePyATSSourcesQuery();
  const { data: batfishSourcesData } = useBatfishSourcesQuery();
  const { data: secretManagerConnectionsData } = useSecretManagerConnectionsQuery();

  const hasPyatsSource = (pyatsSourcesData?.sources.length ?? 0) > 0;
  const hasBatfishSource = (batfishSourcesData?.sources.length ?? 0) > 0;
  const hasSecretManagerConnection = (secretManagerConnectionsData?.connections.length ?? 0) > 0;

  return useMemo(
    () =>
      filterAvailableGroups(groupPaletteItems(plugins), {
        hasPyatsSource,
        hasBatfishSource,
        hasSecretManagerConnection,
      }),
    [plugins, hasPyatsSource, hasBatfishSource, hasSecretManagerConnection],
  );
}
