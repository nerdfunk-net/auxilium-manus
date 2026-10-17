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

import type { DatasetInfo, MetricOp } from "../types/report-query";
import {
  METRIC_OP_LABELS,
  metricFieldChoices,
  type BuilderState,
} from "../utils/query-spec";
import { LabeledSelect } from "./labeled-select";

interface MetricsEditorProps {
  control: Control<BuilderState>;
  setValue: UseFormSetValue<BuilderState>;
  dataset: DatasetInfo | undefined;
}

const METRIC_OPS = Object.keys(METRIC_OP_LABELS) as MetricOp[];
const ROWS_SENTINEL = "__rows__";

export function MetricsEditor({
  control,
  setValue,
  dataset,
}: MetricsEditorProps) {
  const { fields, append, remove } = useFieldArray({
    control,
    name: "metrics",
  });
  const rows = useWatch({ control, name: "metrics" });

  return (
    <div className="space-y-2">
      {fields.map((row, index) => {
        const op = rows?.[index]?.op ?? "count";
        const choices = metricFieldChoices(op, dataset).map((c) => ({
          value: c.name,
          label: c.name,
        }));
        const options =
          op === "count"
            ? [{ value: ROWS_SENTINEL, label: "(all rows)" }, ...choices]
            : choices;
        return (
          <div
            key={row.id}
            className="space-y-1.5 rounded-md border bg-muted/20 p-2"
          >
            <div className="flex items-center gap-1.5">
              <Controller
                control={control}
                name={`metrics.${index}.op`}
                render={({ field }) => (
                  <LabeledSelect
                    value={field.value}
                    onChange={(nextOp) => {
                      field.onChange(nextOp);
                      // Keep the chosen field only if the new operation accepts it.
                      const kept = metricFieldChoices(
                        nextOp as MetricOp,
                        dataset,
                      ).some((c) => c.name === rows?.[index]?.field);
                      if (!kept) setValue(`metrics.${index}.field`, "");
                    }}
                    options={METRIC_OPS.map((value) => ({
                      value,
                      label: METRIC_OP_LABELS[value],
                    }))}
                    placeholder="Metric"
                    ariaLabel={`Metric ${index + 1} operation`}
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
                aria-label={`Remove metric ${index + 1}`}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {op === "count_devices" || op === "count_items" ? (
                <p className="self-center text-xs text-muted-foreground">
                  Reads devices that found nothing too.
                </p>
              ) : (
                <Controller
                  control={control}
                  name={`metrics.${index}.field`}
                  render={({ field }) => (
                    <LabeledSelect
                      value={
                        field.value === "" && op === "count"
                          ? ROWS_SENTINEL
                          : field.value
                      }
                      onChange={(value) =>
                        field.onChange(value === ROWS_SENTINEL ? "" : value)
                      }
                      options={options}
                      placeholder="Field"
                      ariaLabel={`Metric ${index + 1} field`}
                      className="h-8 w-full text-xs"
                    />
                  )}
                />
              )}
              <Controller
                control={control}
                name={`metrics.${index}.alias`}
                render={({ field }) => (
                  <Input
                    {...field}
                    placeholder="column name (optional)"
                    title="Name of the result column: lowercase letters, digits and underscores"
                    aria-label={`Metric ${index + 1} column name`}
                    className="h-8 font-mono text-xs"
                  />
                )}
              />
            </div>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8"
        onClick={() => append({ op: "count", field: "", alias: "" })}
      >
        <Plus className="mr-1 size-3.5" />
        Add metric
      </Button>
    </div>
  );
}
