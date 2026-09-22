"use client";

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WidgetComponentProps } from "@/components/features/dashboard/types/dashboard";
import { useJobStatisticsJobsQuery } from "@/hooks/queries/use-job-statistics-jobs-query";
import { useJobStatisticsPieQuery } from "@/hooks/queries/use-job-statistics-pie-query";

const SUCCESS_COLOR = "var(--success-foreground)";
const FAILED_COLOR = "var(--error-foreground)";

export function JobStatisticsWidget({ settings, onSettingsChange }: WidgetComponentProps) {
  const { data: jobsData, isLoading: jobsLoading, error: jobsError } = useJobStatisticsJobsQuery();

  const persistedWorkflowId =
    typeof settings?.workflowId === "number" ? settings.workflowId : null;
  // Local override lets a fresh pick feel instant instead of waiting on the
  // save round-trip; persistedWorkflowId still wins once it catches up.
  const [localWorkflowId, setLocalWorkflowId] = useState<number | null>(null);

  const jobs = jobsData?.jobs ?? [];
  const effectiveWorkflowId = localWorkflowId ?? persistedWorkflowId ?? jobs[0]?.workflow_id ?? null;

  const handleWorkflowIdChange = (workflowId: number) => {
    setLocalWorkflowId(workflowId);
    onSettingsChange?.({ workflowId });
  };

  const {
    data: pieData,
    isLoading: pieLoading,
    error: pieError,
  } = useJobStatisticsPieQuery(effectiveWorkflowId);

  const chartData = useMemo(() => {
    if (!pieData) {
      return [];
    }
    return [
      { name: "Success", value: pieData.success_count, fill: SUCCESS_COLOR },
      { name: "Failed", value: pieData.failed_count, fill: FAILED_COLOR },
    ];
  }, [pieData]);

  if (jobsLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
      </div>
    );
  }

  if (jobsError) {
    return (
      <p className="text-sm text-destructive">
        Failed to load job statistics: {jobsError.message}
      </p>
    );
  }

  if (jobs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No recorded statistics yet — add a Collect Statistics step to a workflow.
      </p>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2">
      {jobs.length > 1 ? (
        <Select
          value={effectiveWorkflowId ? String(effectiveWorkflowId) : undefined}
          onValueChange={(value) => handleWorkflowIdChange(Number(value))}
        >
          <SelectTrigger className="h-8 shrink-0 text-xs">
            <SelectValue placeholder="Choose a job…" />
          </SelectTrigger>
          <SelectContent>
            {jobs.map((job) => (
              <SelectItem key={job.workflow_id} value={String(job.workflow_id)}>
                {job.workflow_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      {pieLoading ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : pieError ? (
        <p className="text-sm text-destructive">
          Failed to load job statistics: {pieError.message}
        </p>
      ) : pieData ? (
        <>
          <div className="min-h-0 flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius="55%"
                  outerRadius="80%"
                />
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <p className="shrink-0 text-xs text-muted-foreground">
            {pieData.total_count} devices — {pieData.success_count} success /{" "}
            {pieData.failed_count} failed (run #{pieData.run_id})
          </p>
        </>
      ) : null}
    </div>
  );
}
