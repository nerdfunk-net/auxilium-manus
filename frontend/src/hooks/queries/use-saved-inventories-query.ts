import { useQuery } from "@tanstack/react-query";

import type { SavedInventory } from "@/components/features/workflow-steps/get-nautobot-devices/types/saved-inventory";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface ListInventoriesResponse {
  inventories: SavedInventory[];
  total: number;
}

interface GroupsResponse {
  groups: string[];
}

interface UseSavedInventoriesOptions {
  enabled?: boolean;
}

export function useSavedInventoriesQuery(options: UseSavedInventoriesOptions = {}) {
  const { enabled = true } = options;
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.inventories(),
    queryFn: async () => {
      const response = await apiCall<ListInventoriesResponse>("sources/nautobot", {
        method: "GET",
      });
      return response.inventories;
    },
    enabled,
    staleTime: 30 * 1000,
  });
}

export function useInventoryGroupsQuery(options: UseSavedInventoriesOptions = {}) {
  const { enabled = true } = options;
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.groups(),
    queryFn: async () => {
      const response = await apiCall<GroupsResponse>("sources/nautobot/get-all-groups", {
        method: "GET",
      });
      return response.groups;
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
