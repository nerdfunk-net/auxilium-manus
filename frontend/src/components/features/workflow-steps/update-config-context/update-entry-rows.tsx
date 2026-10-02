"use client";

import { Plus, Search, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import {
  addUpdateEntry,
  patchUpdateEntry,
  removeUpdateEntry,
  type UpdateEntry,
} from "./config";
import { ValueSourceFields, type ValueSourceSharedProps } from "./value-source-fields";

interface PathInputProps {
  value: string;
  onChange: (value: string) => void;
  onBrowse: () => void;
  placeholder: string;
  ariaLabel: string;
}

/** Path text input plus the shared icon-only "Browse attributes" button. */
export function PathInput({ value, onChange, onBrowse, placeholder, ariaLabel }: PathInputProps) {
  return (
    <div className="flex items-center gap-1.5">
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-8 font-mono text-xs"
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="size-8 shrink-0"
        onClick={onBrowse}
        title="Browse attributes"
        aria-label={ariaLabel}
      >
        <Search className="size-3.5" aria-hidden />
      </Button>
    </div>
  );
}

const UPDATE_PATH_PLACEHOLDER = "tacacs[address=1.2.3.4].key";

interface UpdateEntryRowsProps extends ValueSourceSharedProps {
  updates: readonly UpdateEntry[];
  onChange: (next: UpdateEntry[]) => void;
  onBrowsePath: (index: number) => void;
  onBrowseValue: (index: number) => void;
  onPreviewTemplate: (index: number) => void;
}

/** The repeating path/value rows of an `update` mode step. */
export function UpdateEntryRows({
  updates,
  onChange,
  onBrowsePath,
  onBrowseValue,
  onPreviewTemplate,
  ...shared
}: UpdateEntryRowsProps) {
  return (
    <div className="space-y-2">
      {updates.map((entry, index) => (
        <div key={index} className="space-y-1.5 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-medium">updates[{index}]</span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-6"
              disabled={updates.length === 1}
              onClick={() => onChange(removeUpdateEntry(updates, index))}
              title="Remove this path/value pair"
              aria-label={`Remove path/value pair ${index + 1}`}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          </div>

          <div className="space-y-1">
            <span className="text-[11px] font-medium text-muted-foreground">path</span>
            <PathInput
              value={entry.path}
              onChange={(path) => onChange(patchUpdateEntry(updates, index, { path }))}
              onBrowse={() => onBrowsePath(index)}
              placeholder={UPDATE_PATH_PLACEHOLDER}
              ariaLabel={`Browse attributes for path ${index + 1}`}
            />
          </div>

          <div className="space-y-1.5">
            <span className="text-[11px] font-medium text-muted-foreground">value</span>
            <ValueSourceFields
              {...shared}
              value={entry.value_source}
              onChange={(value_source) =>
                onChange(patchUpdateEntry(updates, index, { value_source }))
              }
              onBrowse={() => onBrowseValue(index)}
              onPreviewTemplate={() => onPreviewTemplate(index)}
              ariaLabel={`value ${index + 1}`}
            />
          </div>
        </div>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 w-full text-xs"
        onClick={() => onChange(addUpdateEntry(updates))}
      >
        <Plus className="mr-1 size-3.5" aria-hidden />
        Add path
      </Button>
    </div>
  );
}
