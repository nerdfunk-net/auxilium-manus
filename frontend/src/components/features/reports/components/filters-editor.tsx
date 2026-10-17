"use client";

import { Plus, Trash2 } from "lucide-react";
import {
  Controller,
  useFieldArray,
  useWatch,
  type Control,
  type UseFormSetValue,
} from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import type { DatasetInfo, FilterOp } from "../types/report-query";
import {
  FILTER_OP_LABELS,
  fieldChoices,
  operatorsForType,
  type BuilderState,
} from "../utils/query-spec";
import { LabeledSelect } from "./labeled-select";

interface FiltersEditorProps {
  control: Control<BuilderState>;
  setValue: UseFormSetValue<BuilderState>;
  dataset: DatasetInfo | undefined;
}

const NULL_OPS: readonly FilterOp[] = ["is_null", "not_null"];

export function FiltersEditor({
  control,
  setValue,
  dataset,
}: FiltersEditorProps) {
  const { fields, append, remove } = useFieldArray({
    control,
    name: "filters",
  });
  const rows = useWatch({ control, name: "filters" });
  const choices = fieldChoices(dataset);

  return (
    <div className="space-y-2">
      {fields.map((row, index) => {
        const current = rows?.[index];
        const type =
          choices.find((c) => c.name === current?.field)?.type ?? "unknown";
        const showValue = current ? !NULL_OPS.includes(current.op) : true;
        return (
          <div
            key={row.id}
            className="space-y-1.5 rounded-md border bg-muted/20 p-2"
          >
            <div className="flex items-center gap-1.5">
              <Controller
                control={control}
                name={`filters.${index}.field`}
                render={({ field }) => (
                  <LabeledSelect
                    value={field.value}
                    onChange={(name) => {
                      field.onChange(name);
                      // The old operator and value may not fit the new field's type.
                      const nextType =
                        choices.find((c) => c.name === name)?.type ?? "unknown";
                      if (
                        !current ||
                        !operatorsForType(nextType).includes(current.op)
                      ) {
                        setValue(`filters.${index}.op`, "eq");
                        setValue(`filters.${index}.value`, "");
                      }
                    }}
                    options={choices.map((c) => ({
                      value: c.name,
                      label: c.name,
                    }))}
                    placeholder="Field"
                    ariaLabel={`Filter ${index + 1} field`}
                    className="h-8 w-full text-xs"
                  />
                )}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => remove(index)}
                aria-label={`Remove filter ${index + 1}`}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            <div className="flex items-center gap-1.5">
              <Controller
                control={control}
                name={`filters.${index}.op`}
                render={({ field }) => (
                  <LabeledSelect
                    value={field.value}
                    onChange={field.onChange}
                    options={operatorsForType(type).map((op) => ({
                      value: op,
                      label: FILTER_OP_LABELS[op],
                    }))}
                    placeholder="Operator"
                    ariaLabel={`Filter ${index + 1} operator`}
                    className="h-8 w-40 shrink-0 text-xs"
                  />
                )}
              />
              {showValue ? (
                <Controller
                  control={control}
                  name={`filters.${index}.value`}
                  render={({ field }) => (
                    <Input
                      {...field}
                      placeholder={current?.op === "in" ? "a, b, c" : "value"}
                      aria-label={`Filter ${index + 1} value`}
                      className="h-8 min-w-0 flex-1 font-mono text-xs"
                    />
                  )}
                />
              ) : null}
            </div>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8"
        onClick={() => append({ field: "", op: "eq", value: "" })}
      >
        <Plus className="mr-1 size-3.5" />
        Add filter
      </Button>
    </div>
  );
}
