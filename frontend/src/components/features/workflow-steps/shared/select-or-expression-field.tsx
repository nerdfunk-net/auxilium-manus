"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import { useGetNautobotDevicesFieldValuesQuery } from "@/hooks/queries/use-get-nautobot-devices-field-values-query";

import { AttributePathPicker } from "./attribute-path-picker";

interface SelectOrExpressionFieldProps {
  label: string;
  value: string;
  placeholder: string;
  onValueChange: (value: string) => void;
  /** Nautobot source id; the list is skipped while empty. */
  sourceId: string;
  /** Field name for GET sources/nautobot/field-values/{field}; omit for a free-text field. */
  optionsField?: string;
  required?: boolean;
  hint?: string;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
}

/**
 * One value that can be a fixed text, a pick from a Nautobot list, or a
 * `{path.to.value}` attribute-bag expression. The text input is the single source
 * of truth: the dropdown writes the chosen name into it, and the lens button
 * writes the chosen path back as `{path}`.
 */
export function SelectOrExpressionField({
  label,
  value,
  placeholder,
  onValueChange,
  sourceId,
  optionsField,
  required = false,
  hint,
  nodeId,
  workflowNodes,
  workflowEdges,
}: SelectOrExpressionFieldProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const options = useGetNautobotDevicesFieldValuesQuery({
    sourceId,
    field: optionsField ?? "",
    enabled: Boolean(optionsField),
  });

  const optionValues = useMemo(() => options.data?.values ?? [], [options.data]);
  const selected = optionValues.some((option) => option.value === value) ? value : "";
  const isEmpty = !value.trim();

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => onValueChange(event.target.value),
    [onValueChange],
  );
  const handleClosePicker = useCallback(() => setPickerOpen(false), []);
  const handleSelectPath = useCallback(
    (path: string) => {
      onValueChange(`{${path}}`);
      setPickerOpen(false);
    },
    [onValueChange],
  );

  const listPlaceholder = !sourceId
    ? "Select a source first"
    : options.isLoading
      ? "Loading…"
      : optionValues.length === 0
        ? "No options"
        : "Pick from Nautobot";

  return (
    <div
      className={`space-y-1 rounded-lg border p-2.5 ${
        required && isEmpty ? "border-warning-border bg-warning" : "border-border bg-muted"
      }`}
    >
      <Label className="text-[11px] font-medium text-muted-foreground">
        {label} {required ? <span className="text-warning-foreground">*</span> : null}
      </Label>
      <div className="flex items-center gap-1.5">
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          placeholder={placeholder}
          value={value}
          onChange={handleInputChange}
          aria-label={label}
        />
        {optionsField ? (
          <Select
            value={selected}
            onValueChange={onValueChange}
            disabled={!sourceId || optionValues.length === 0}
          >
            <SelectTrigger
              className="h-8 w-[10.5rem] shrink-0 text-xs focus:ring-step/40"
              aria-label={`${label} from Nautobot`}
            >
              <SelectValue placeholder={listPlaceholder} />
            </SelectTrigger>
            <SelectContent>
              {optionValues.map((option) => (
                <SelectItem key={option.value} value={option.value} className="text-xs">
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-8 shrink-0"
          onClick={() => setPickerOpen(true)}
          title="Browse attributes"
          aria-label={`Browse attributes for ${label}`}
        >
          <Search className="size-3.5" aria-hidden />
        </Button>
      </div>
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
      <AttributePathPicker
        open={pickerOpen}
        onClose={handleClosePicker}
        onSelect={handleSelectPath}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />
    </div>
  );
}
