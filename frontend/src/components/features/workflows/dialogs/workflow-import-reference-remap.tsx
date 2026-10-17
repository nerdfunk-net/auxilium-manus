"use client";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface WorkflowImportReferenceOption {
  value: string;
  label: string;
}

export interface WorkflowImportReferenceRequirement {
  /** Old value (git_repository_id as a string, or a source_id). */
  key: string;
  label: string;
}

interface WorkflowImportReferenceRemapProps {
  title: string;
  description: string;
  requirements: WorkflowImportReferenceRequirement[];
  options: WorkflowImportReferenceOption[];
  value: Record<string, string>;
  onChange: (oldKey: string, newValue: string) => void;
  isLoading?: boolean;
  emptyMessage: string;
}

/** Generic "pick a replacement for this reference" section, reused for
 * git_repository_id and every nautobot/mattermost/batfish/pyats
 * `*_source_id` field during workflow import — same shape as
 * WorkflowImportCredentialRemap, minus the visibility/owner badge that only
 * applies to credentials. */
export function WorkflowImportReferenceRemap({
  title,
  description,
  requirements,
  options,
  value,
  onChange,
  isLoading = false,
  emptyMessage,
}: WorkflowImportReferenceRemapProps) {
  return (
    <div className="grid gap-3 rounded-md border p-3">
      <div className="grid gap-1">
        <Label>{title}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : options.length === 0 ? (
        <p className="text-xs text-warning-foreground">{emptyMessage}</p>
      ) : (
        requirements.map((requirement) => (
          <div key={requirement.key} className="grid gap-1.5">
            <span className="font-mono text-xs font-medium">
              {requirement.label}
            </span>
            <Select
              value={value[requirement.key] ?? ""}
              onValueChange={(selected: string) =>
                onChange(requirement.key, selected)
              }
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Select replacement" />
              </SelectTrigger>
              <SelectContent>
                {options.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))
      )}
    </div>
  );
}
