"use client";

import { Plus, Search, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  EMPTY_WORKFLOW_EDGES,
  EMPTY_WORKFLOW_NODES,
} from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";

import {
  buildStoreForReportConfig,
  datasetNameError,
  EMPTY_REPORT_FIELD,
  fieldNameError,
  normalizeReportFields,
  normalizeReportMode,
  REPORT_MODE_OPTIONS,
  removeReportField,
  updateReportField,
  type ReportAggregate,
  type ReportField,
} from "./config";
import { StoreForReportHelpPanel } from "./help-panel";

type PickerTarget = { kind: "items" } | { kind: "field"; index: number } | null;

const VALUE_AGGREGATE = "value";

function FieldLabel({ name, type }: { name: string; type: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-medium">{name}</span>
      <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
        {type}
      </Badge>
    </div>
  );
}

function StoreForReportConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
  workflowEdges = EMPTY_WORKFLOW_EDGES,
}: PluginConfigPanelProps) {
  const [picker, setPicker] = useState<PickerTarget>(null);

  const dataset = typeof config.dataset === "string" ? config.dataset : "";
  const itemsPath = typeof config.items_path === "string" ? config.items_path : "";
  const mode = normalizeReportMode(config.mode);
  const isItems = mode === "items";
  const fields = useMemo(() => normalizeReportFields(config.fields, mode), [config.fields, mode]);
  const datasetError = datasetNameError(dataset);
  const modeHint = REPORT_MODE_OPTIONS.find((option) => option.value === mode)?.hint;

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => onChange(buildStoreForReportConfig(config, patch)),
    [config, onChange],
  );

  const handleFieldsChange = useCallback(
    (next: ReportField[]) => patchConfig({ fields: next }),
    [patchConfig],
  );

  const handleAddField = useCallback(
    () => handleFieldsChange([...fields, EMPTY_REPORT_FIELD]),
    [fields, handleFieldsChange],
  );

  const handlePickerSelect = useCallback(
    (path: string) => {
      if (picker?.kind === "items") {
        patchConfig({ items_path: path });
      } else if (picker?.kind === "field") {
        handleFieldsChange(updateReportField(fields, picker.index, { attribute_path: path }));
      }
    },
    [fields, handleFieldsChange, patchConfig, picker],
  );

  const handlePickerClose = useCallback(() => setPicker(null), []);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <FieldLabel name="dataset" type="string" />
        <Input
          value={dataset}
          onChange={(event) => patchConfig({ dataset: event.target.value })}
          placeholder={isItems ? "interfaces" : "inventory"}
          aria-invalid={datasetError !== null}
          className="h-8 font-mono text-xs"
        />
        {datasetError ? <p className="text-[11px] text-destructive">{datasetError}</p> : null}
        <p className="text-[11px] text-muted-foreground">
          Name of the report dataset (lowercase letters, digits, &apos;_&apos; or
          &apos;-&apos;). Reports select data by this name. Keep device rows and list-item
          rows in separate datasets.
        </p>
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="mode" type="string" />
        <Select value={mode} onValueChange={(value) => patchConfig({ mode: value })}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REPORT_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {modeHint ? <p className="text-[11px] text-muted-foreground">{modeHint}</p> : null}
      </div>

      {isItems ? (
        <div className="space-y-1.5">
          <FieldLabel name="items_path" type="string" />
          <div className="flex items-center gap-1.5">
            <Input
              value={itemsPath}
              onChange={(event) => patchConfig({ items_path: event.target.value })}
              placeholder="parsed.parsed.show interfaces status.parsed"
              className="h-8 font-mono text-xs"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8 shrink-0"
              onClick={() => setPicker({ kind: "items" })}
              title="Browse attributes"
              aria-label="Browse attributes for items_path"
            >
              <Search className="size-3.5" />
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Path to the list. One row is stored for every element; the fields below are read
            relative to each element.
          </p>
        </div>
      ) : null}

      <div className="space-y-1.5">
        <FieldLabel name="fields" type="list" />

        {fields.map((field, index) => {
          const nameError = fieldNameError(field.name);
          return (
          <div key={index} className="space-y-1.5 rounded-md border bg-muted/20 p-2">
            <div className="flex items-center gap-1.5">
              <Input
                value={field.name}
                onChange={(event) =>
                  handleFieldsChange(updateReportField(fields, index, { name: event.target.value }))
                }
                placeholder={isItems ? "status" : "serial_number"}
                aria-label={`Field ${index + 1} name`}
                aria-invalid={nameError !== null}
                className="h-8 w-2/5 font-mono text-xs"
              />
              <Input
                value={field.attribute_path}
                onChange={(event) =>
                  handleFieldsChange(
                    updateReportField(fields, index, { attribute_path: event.target.value }),
                  )
                }
                placeholder={isItems ? "status" : "nautobot.serial"}
                aria-label={`Field ${index + 1} attribute path`}
                className="h-8 flex-1 font-mono text-xs"
              />
              {!isItems ? (
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-8 shrink-0"
                  onClick={() => setPicker({ kind: "field", index })}
                  title="Browse attributes"
                  aria-label={`Browse attributes for field ${index + 1}`}
                >
                  <Search className="size-3.5" />
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleFieldsChange(removeReportField(fields, index))}
                title="Remove field"
                aria-label={`Remove field ${index + 1}`}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            {nameError ? <p className="text-[11px] text-destructive">{nameError}</p> : null}

            {!isItems ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <Select
                  value={field.aggregate === "count" ? "count" : VALUE_AGGREGATE}
                  onValueChange={(value) =>
                    handleFieldsChange(
                      updateReportField(fields, index, {
                        aggregate: (value === "count" ? "count" : "") as ReportAggregate,
                      }),
                    )
                  }
                >
                  <SelectTrigger
                    className="h-8 w-40 text-xs"
                    aria-label={`Field ${index + 1} aggregate`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={VALUE_AGGREGATE}>Store the value</SelectItem>
                    <SelectItem value="count">Count list items</SelectItem>
                  </SelectContent>
                </Select>
                {field.aggregate === "count" ? (
                  <>
                    <span className="text-[11px] text-muted-foreground">only where</span>
                    <Input
                      value={field.where_field}
                      onChange={(event) =>
                        handleFieldsChange(
                          updateReportField(fields, index, { where_field: event.target.value }),
                        )
                      }
                      placeholder="status (optional)"
                      aria-label={`Field ${index + 1} where field`}
                      className="h-8 w-32 font-mono text-xs"
                    />
                    <span className="text-[11px] text-muted-foreground">=</span>
                    <Input
                      value={field.where_equals}
                      onChange={(event) =>
                        handleFieldsChange(
                          updateReportField(fields, index, { where_equals: event.target.value }),
                        )
                      }
                      placeholder="disabled"
                      aria-label={`Field ${index + 1} where value`}
                      className="h-8 w-32 font-mono text-xs"
                    />
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
          );
        })}

        <Button type="button" variant="outline" size="sm" className="h-8" onClick={handleAddField}>
          <Plus className="mr-1 size-3.5" />
          Add field
        </Button>
        <p className="text-[11px] text-muted-foreground">
          {isItems
            ? "Each path is read from one list element (use . for the element itself). A missing value is stored as null; a list/object value or a secret fails the device."
            : "A path that resolves to nothing is stored as null; a list/object value or a secret fails the device. Use “Count list items” to store how many items a list has, optionally only those where a field equals a value."}
        </p>
      </div>

      <AttributePathPicker
        open={picker !== null}
        onClose={handlePickerClose}
        onSelect={handlePickerSelect}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />
    </div>
  );
}

export const StoreForReportPlugin: PluginUIComponent = {
  ConfigPanel: StoreForReportConfigPanel,
  HelpPanel: StoreForReportHelpPanel,
};
