import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useInventoryImportMutation() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text();
      const importData = JSON.parse(text) as {
        version?: number;
        conditionTree?: unknown;
        metadata?: { name?: string };
      };

      if (!importData.version || importData.version !== 2) {
        throw new Error("Invalid inventory file format. Expected version 2.");
      }
      if (!importData.conditionTree) {
        throw new Error("Invalid inventory file. Missing condition tree.");
      }
      if (!importData.metadata?.name) {
        throw new Error("Invalid inventory file. Missing metadata.");
      }

      await apiCall("sources/nautobot/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ import_data: importData }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.inventories() });
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.groups() });
      toast({
        title: "Import complete",
        description: "Inventory was imported successfully.",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Import failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
