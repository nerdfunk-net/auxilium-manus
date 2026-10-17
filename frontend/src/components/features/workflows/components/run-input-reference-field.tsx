"use client";

import { useMemo } from "react";

import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { useSavedInventoriesQuery } from "@/hooks/queries/use-saved-inventories-query";

interface RunInputReferenceFieldProps {
  value: unknown;
  onChange: (value: number) => void;
}

/**
 * Searchable picker for an ``inventory`` reference run parameter. Shows saved
 * inventories by name (substring filter) and emits the numeric id the backend
 * expects, so users never have to know or type an id.
 */
export function RunInputReferenceField({ value, onChange }: RunInputReferenceFieldProps) {
  const inventoriesQuery = useSavedInventoriesQuery();

  const options = useMemo<ComboboxOption[]>(
    () =>
      (inventoriesQuery.data ?? [])
        .filter((inv) => inv.is_active)
        .map((inv) => ({
          value: String(inv.id),
          label: inv.scope === "private" ? `${inv.name} (private)` : inv.name,
        })),
    [inventoriesQuery.data],
  );

  const handleValueChange = (next: string) => onChange(Number(next));

  return (
    <div className="grid gap-1">
      <Combobox
        options={options}
        value={value != null && value !== "" ? String(value) : ""}
        onValueChange={handleValueChange}
        placeholder={inventoriesQuery.isLoading ? "Loading inventories…" : "Select an inventory"}
        searchPlaceholder="Search inventories…"
        emptyText="No inventories found"
        disabled={inventoriesQuery.isLoading}
        className="h-9 text-xs"
        inline
      />
      {inventoriesQuery.isError ? (
        <p className="text-xs text-destructive">Could not load inventories.</p>
      ) : null}
    </div>
  );
}
