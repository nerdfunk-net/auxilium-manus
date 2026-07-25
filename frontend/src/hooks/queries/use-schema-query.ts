"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface TableColumnRef {
  table: string;
  column: string;
}

export interface TableIndexRef {
  table: string;
  index: string;
}

export interface ColumnDiff {
  table: string;
  column: string;
  db_type: string;
  model_type: string;
  type_changed: boolean;
  nullable_changed: boolean;
  db_nullable: boolean;
  model_nullable: boolean;
  safe: boolean;
}

export interface SchemaStatus {
  is_up_to_date: boolean;
  missing_tables: string[];
  extra_tables: string[];
  missing_columns: TableColumnRef[];
  extra_columns: TableColumnRef[];
  column_diffs: ColumnDiff[];
  missing_indexes: TableIndexRef[];
  extra_indexes: TableIndexRef[];
}

export function useSchemaStatusQuery() {
  const { apiCall } = useApi();

  return useQuery<SchemaStatus>({
    queryKey: queryKeys.system.schemaStatus(),
    queryFn: () => apiCall("system/schema/status", { method: "GET" }),
    staleTime: 10 * 1000,
  });
}
