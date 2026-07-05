import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

export function useInventoryExportMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (inventoryId: number) => {
      const response = await apiCall<{
        version: number;
        metadata: {
          name: string;
          description: string;
          scope: string;
          exportedAt: string;
          exportedBy: string;
          originalId: number;
        };
        conditionTree: unknown;
      }>(`sources/nautobot/export/${inventoryId}`, { method: "GET" });

      const blob = new Blob([JSON.stringify(response, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const filename = `inventory-${response.metadata.name.replace(/[^a-z0-9]/gi, "-").toLowerCase()}-${Date.now()}.json`;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
    onSuccess: () => {
      toast({
        title: "Export complete",
        description: "Inventory JSON was downloaded.",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Export failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
