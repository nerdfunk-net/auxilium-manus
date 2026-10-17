"use client";

import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { NautobotCustomFieldRow } from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import type { CustomFieldRow, CustomFieldsSource } from "./types";

interface CustomFieldsSectionProps {
  customFieldsSource: CustomFieldsSource;
  customFieldRows: CustomFieldRow[];
  onSourceChange: (source: CustomFieldsSource) => void;
  onAddRow: () => void;
  onPatchRow: (id: string, patch: Partial<CustomFieldRow>) => void;
  onRemoveRow: (id: string) => void;
}

export function CustomFieldsSection({
  customFieldsSource,
  customFieldRows,
  onSourceChange,
  onAddRow,
  onPatchRow,
  onRemoveRow,
}: CustomFieldsSectionProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-medium">custom_fields</span>
        {customFieldsSource === "manual" ? (
          <Button
            className="h-7 bg-step text-step-foreground hover:bg-step-hover"
            size="sm"
            type="button"
            onClick={onAddRow}
          >
            <Plus className="mr-1 size-3.5" />
            Add
          </Button>
        ) : null}
      </div>
      <Select
        value={customFieldsSource}
        onValueChange={(source) => onSourceChange(source as CustomFieldsSource)}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="manual">Manual — rows below</SelectItem>
          <SelectItem value="nautobot_origin">All from Nautobot origin</SelectItem>
        </SelectContent>
      </Select>

      {customFieldsSource === "nautobot_origin" ? (
        <p className="text-[11px] text-muted-foreground">
          Every custom field present in the device&apos;s nautobot attribute bag is sent as-is —
          however many there are, whatever they&apos;re named. The rows below are ignored while
          this is selected.
        </p>
      ) : customFieldRows.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No custom fields configured.</p>
      ) : (
        <div className="space-y-2">
          {customFieldRows.map((row) => (
            <NautobotCustomFieldRow
              key={row.id}
              row={row}
              onChange={(patch) => onPatchRow(row.id, patch)}
              onRemove={() => onRemoveRow(row.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
