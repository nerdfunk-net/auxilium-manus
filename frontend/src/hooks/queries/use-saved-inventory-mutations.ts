import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  SavedConditionPayload,
  SavedInventory,
} from "@/components/features/workflow-steps/get-nautobot-devices/types/saved-inventory";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface CreateInventoryInput {
  name: string;
  description?: string | null;
  scope: string;
  group_path?: string | null;
  conditions: SavedConditionPayload[];
}

export interface UpdateInventoryInput {
  id: number;
  name?: string;
  description?: string | null;
  scope?: string;
  group_path?: string | null;
  conditions?: SavedConditionPayload[];
}

export function useCreateInventoryMutation() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (input: CreateInventoryInput) =>
      apiCall<SavedInventory>("sources/nautobot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    onSuccess: (inventory) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.inventories() });
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.groups() });
      toast({
        title: "Inventory saved",
        description: `"${inventory.name}" was saved successfully.`,
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Save failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useUpdateInventoryMutation() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ id, ...data }: UpdateInventoryInput) =>
      apiCall<SavedInventory>(`sources/nautobot/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (inventory) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.inventories() });
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.groups() });
      toast({
        title: "Inventory updated",
        description: `"${inventory.name}" was updated.`,
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Update failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useDeleteInventoryMutation() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (inventoryId: number) =>
      apiCall(`sources/nautobot/${inventoryId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.inventories() });
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.groups() });
      toast({
        title: "Inventory deleted",
        description: "The saved filter was removed.",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Delete failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
