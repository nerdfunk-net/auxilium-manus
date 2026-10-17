"use client";

import { Loader2, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useReportCatalogQuery } from "@/hooks/queries/use-report-catalog-query";

import {
  type DatasetInfo,
  type ReportQuerySpec,
  type ReportSource,
} from "../types/report-query";
import {
  buildReportQuery,
  columnOptions as columnOptionsFor,
  DEFAULT_BUILDER_STATE,
  groupByOptions,
  MAX_QUERY_LIMIT,
  outputKeys,
  type BuilderState,
} from "../utils/query-spec";
import { CheckboxList } from "./checkbox-list";
import { DatasetFieldsPanel } from "./dataset-fields-panel";
import { FiltersEditor } from "./filters-editor";
import { LabeledSelect } from "./labeled-select";
import { MetricsEditor } from "./metrics-editor";

interface QueryBuilderProps {
  sources: readonly ReportSource[];
  isRunning: boolean;
  onRun: (query: ReportQuerySpec) => void;
  /** Start from a saved query (editing a report section) instead of an empty form. */
  initialState?: BuilderState;
  /** When set, a second button hands the validated query over (e.g. "Add to report"). */
  onSave?: (query: ReportQuerySpec) => void;
  saveLabel?: string;
}

const EMPTY_DATASETS: DatasetInfo[] = [];

const SCOPE_OPTIONS = [
  { value: "latest", label: "Latest collection per device" },
  { value: "history", label: "History (all collections)" },
] as const;

const BUCKET_OPTIONS = [
  { value: "none", label: "No time bucket" },
  { value: "day", label: "Per day" },
  { value: "week", label: "Per week" },
] as const;

const DIRECTION_OPTIONS = [
  { value: "asc", label: "Ascending" },
  { value: "desc", label: "Descending" },
] as const;

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

export function QueryBuilder({
  sources,
  isRunning,
  onRun,
  initialState = DEFAULT_BUILDER_STATE,
  onSave,
  saveLabel = "Save",
}: QueryBuilderProps) {
  const { control, setValue, getValues } = useForm<BuilderState>({
    defaultValues: initialState,
  });
  const values = useWatch({ control }) as BuilderState;
  const [errors, setErrors] = useState<string[]>([]);

  // A single source needs no choice: select it as soon as the list is known.
  useEffect(() => {
    if (!getValues("sourceId") && sources.length > 0)
      setValue("sourceId", sources[0].id);
  }, [getValues, setValue, sources]);

  const catalog = useReportCatalogQuery(values.sourceId ?? "");
  const datasets = catalog.data ?? EMPTY_DATASETS;
  const dataset = useMemo(
    () => datasets.find((d) => d.name === values.dataset),
    [datasets, values.dataset],
  );

  const resetDatasetState = useCallback(
    (name: string) => {
      setValue("dataset", name);
      setValue("select", []);
      setValue("groupBy", []);
      setValue("metrics", []);
      setValue("filters", []);
      setValue("orderKey", "");
      setErrors([]);
    },
    [setValue],
  );

  const handleRun = useCallback(() => {
    const result = buildReportQuery(getValues(), dataset);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors([]);
    onRun(result.query);
  }, [dataset, getValues, onRun]);

  const handleSave = useCallback(() => {
    if (!onSave) return;
    const result = buildReportQuery(getValues(), dataset);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors([]);
    onSave(result.query);
  }, [dataset, getValues, onSave]);

  const columnOptions = useMemo(() => columnOptionsFor(dataset), [dataset]);
  const groupOptions = useMemo(
    () => groupByOptions(values, dataset),
    [dataset, values],
  );
  const orderOptions = useMemo(
    () =>
      outputKeys(values, dataset).map((key) => ({ value: key, label: key })),
    [values, dataset],
  );

  const isSummary = values.mode === "summary";

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border bg-card">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        <Section title="Data">
          {sources.length > 1 ? (
            <Controller
              control={control}
              name="sourceId"
              render={({ field }) => (
                <LabeledSelect
                  value={field.value}
                  onChange={(value) => {
                    field.onChange(value);
                    resetDatasetState("");
                  }}
                  options={sources.map((s) => ({
                    value: s.id,
                    label: s.label,
                  }))}
                  placeholder="Source"
                  ariaLabel="Source"
                  className="h-8 w-full text-xs"
                />
              )}
            />
          ) : null}
          <Controller
            control={control}
            name="dataset"
            render={({ field }) => (
              <LabeledSelect
                value={field.value}
                onChange={resetDatasetState}
                options={datasets.map((d) => ({
                  value: d.name,
                  label: d.name,
                }))}
                placeholder={
                  catalog.isLoading ? "Loading datasets…" : "Dataset"
                }
                ariaLabel="Dataset"
                className="h-8 w-full text-xs"
              />
            )}
          />
          {!catalog.isLoading && datasets.length === 0 && values.sourceId ? (
            <p className="text-xs text-muted-foreground">
              No datasets yet. Run a workflow with a Store for Report step
              first.
            </p>
          ) : null}
          {dataset ? <DatasetFieldsPanel dataset={dataset} /> : null}
        </Section>

        {dataset ? (
          <>
            <Section title="Scope">
              <Controller
                control={control}
                name="scopeKind"
                render={({ field }) => (
                  <LabeledSelect
                    value={field.value}
                    onChange={field.onChange}
                    options={SCOPE_OPTIONS}
                    placeholder="Scope"
                    ariaLabel="Scope"
                    className="h-8 w-full text-xs"
                  />
                )}
              />
              {values.scopeKind === "history" ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="datetime-local"
                      aria-label="From"
                      className="h-8 text-xs"
                      value={values.since ?? ""}
                      onChange={(event) =>
                        setValue("since", event.target.value)
                      }
                    />
                    <Input
                      type="datetime-local"
                      aria-label="Until"
                      className="h-8 text-xs"
                      value={values.until ?? ""}
                      onChange={(event) =>
                        setValue("until", event.target.value)
                      }
                    />
                  </div>
                  <LabeledSelect
                    value={values.bucket || "none"}
                    onChange={(value) =>
                      setValue(
                        "bucket",
                        value === "none" ? "" : (value as "day" | "week"),
                      )
                    }
                    options={BUCKET_OPTIONS}
                    placeholder="Bucket"
                    ariaLabel="Time bucket"
                    className="h-8 w-full text-xs"
                  />
                </div>
              ) : null}
            </Section>

            <Section title="Filters">
              <FiltersEditor
                control={control}
                setValue={setValue}
                dataset={dataset}
              />
            </Section>

            <Section title="Result">
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={isSummary ? "outline" : "default"}
                  onClick={() => setValue("mode", "rows")}
                >
                  List rows
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={isSummary ? "default" : "outline"}
                  onClick={() => setValue("mode", "summary")}
                >
                  Summarize
                </Button>
              </div>
              {isSummary ? (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Group by (optional)</Label>
                    <CheckboxList
                      idPrefix="group"
                      options={groupOptions}
                      selected={values.groupBy ?? []}
                      onChange={(next) => setValue("groupBy", next)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Metrics</Label>
                    <MetricsEditor
                      control={control}
                      setValue={setValue}
                      dataset={dataset}
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-1.5">
                  <Label className="text-xs">
                    Columns (none selected = all)
                  </Label>
                  <CheckboxList
                    idPrefix="column"
                    options={columnOptions}
                    selected={values.select ?? []}
                    onChange={(next) => setValue("select", next)}
                  />
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                <LabeledSelect
                  value={values.orderKey || "none"}
                  onChange={(value) =>
                    setValue("orderKey", value === "none" ? "" : value)
                  }
                  options={[
                    { value: "none", label: "Default order" },
                    ...orderOptions,
                  ]}
                  placeholder="Order by"
                  ariaLabel="Order by"
                  className="h-8 w-full text-xs"
                />
                <LabeledSelect
                  value={values.orderDirection ?? "asc"}
                  onChange={(value) =>
                    setValue("orderDirection", value as "asc" | "desc")
                  }
                  options={DIRECTION_OPTIONS}
                  placeholder="Direction"
                  ariaLabel="Order direction"
                  className="h-8 w-full text-xs"
                />
              </div>
              <div className="flex items-center gap-2">
                <Label htmlFor="report-limit" className="text-xs">
                  Limit
                </Label>
                <Input
                  id="report-limit"
                  type="number"
                  min={1}
                  max={MAX_QUERY_LIMIT}
                  className="h-8 w-28 text-xs"
                  value={values.limit ?? ""}
                  onChange={(event) => setValue("limit", event.target.value)}
                />
              </div>
            </Section>
          </>
        ) : null}
      </div>

      {dataset ? (
        <div className="space-y-2 border-t p-3">
          {errors.length > 0 ? (
            <Alert variant="destructive">
              <AlertDescription>
                <ul className="list-disc pl-4">
                  {errors.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}
          <Button
            type="button"
            className="w-full"
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Play className="mr-2 size-4" />
            )}
            Run query
          </Button>
          {onSave ? (
            <Button type="button" variant="secondary" className="w-full" onClick={handleSave}>
              {saveLabel}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
