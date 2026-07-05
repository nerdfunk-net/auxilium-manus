import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

interface RenameGroupInput {
  old_path: string;
  new_name: string;
}

export function useRenameInventoryGroupMutation() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (input: RenameGroupInput) =>
      apiCall<{ updated_count: number; new_path: string }>(
        "sources/nautobot/rename-group",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        },
      ),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.inventories() });
      queryClient.invalidateQueries({ queryKey: queryKeys.sourcesNautobot.groups() });
      toast({
        title: "Group renamed",
        description: `Updated ${result.updated_count} inventories.`,
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Rename failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
