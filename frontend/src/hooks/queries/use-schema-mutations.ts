"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface SchemaMigrationResult {
  success: boolean;
  message: string;
  tables_created: number;
  columns_added: number;
  indexes_created: number;
  column_changes_applied: string[];
  column_changes_skipped: string[];
  errors: string[];
}

export function useSchemaMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const migrateSchema = useMutation({
    mutationFn: (force: boolean) =>
      apiCall<SchemaMigrationResult>(`system/schema/migrate?force=${force}`, {
        method: "POST",
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.system.schemaStatus() });
      if (!result.success) {
        toast({ title: "Migration finished with errors", description: result.message, variant: "destructive" });
      }
    },
    onError: (error: Error) => {
      toast({ title: "Migration failed", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(
    () => ({ migrateSchema }),
    [migrateSchema],
  );
}
