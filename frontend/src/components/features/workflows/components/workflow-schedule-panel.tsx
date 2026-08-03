"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarClock, Loader2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWorkflowScheduleMutations } from "@/hooks/queries/use-workflow-schedule-mutations";
import { useWorkflowScheduleQuery } from "@/hooks/queries/use-workflow-schedule-query";
import { useToast } from "@/hooks/use-toast";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

type Frequency = "hourly" | "daily" | "weekly" | "custom";
const DAY_OPTIONS = [
  { value: "mon", label: "Mon", cron: 1 },
  { value: "tue", label: "Tue", cron: 2 },
  { value: "wed", label: "Wed", cron: 3 },
  { value: "thu", label: "Thu", cron: 4 },
  { value: "fri", label: "Fri", cron: 5 },
  { value: "sat", label: "Sat", cron: 6 },
  { value: "sun", label: "Sun", cron: 0 },
] as const;
type DayValue = (typeof DAY_OPTIONS)[number]["value"];
type CronDay = (typeof DAY_OPTIONS)[number]["cron"];

const scheduleFormSchema = z.object({
  enabled: z.boolean(),
  mode: z.enum(["once", "repeat"]),
  runAt: z.string().optional(),
  frequency: z.enum(["hourly", "daily", "weekly", "custom"]),
  minute: z.string().optional(),
  time: z.string().optional(),
  days: z.array(z.enum(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])).optional(),
  customCron: z.string().optional(),
});

type ScheduleFormValues = z.infer<typeof scheduleFormSchema>;

const DEFAULT_VALUES: ScheduleFormValues = {
  enabled: true,
  mode: "repeat",
  runAt: "",
  frequency: "daily",
  minute: "0",
  time: "09:00",
  days: ["mon"],
  customCron: "",
};

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function buildCronExpression(values: ScheduleFormValues): string {
  if (values.frequency === "custom") {
    return (values.customCron ?? "").trim();
  }
  if (values.frequency === "hourly") {
    const minute = Number(values.minute ?? "0");
    return `${minute} * * * *`;
  }
  const [hh, mm] = (values.time ?? "00:00").split(":");
  const hour = Number(hh ?? "0");
  const minute = Number(mm ?? "0");
  if (values.frequency === "daily") {
    return `${minute} ${hour} * * *`;
  }
  const dayNumbers = (values.days ?? [])
    .map((d) => DAY_OPTIONS.find((opt) => opt.value === d)?.cron)
    .filter((n): n is CronDay => n !== undefined)
    .sort((a, b) => a - b);
  const dayField = dayNumbers.length > 0 ? dayNumbers.join(",") : "*";
  return `${minute} ${hour} * * ${dayField}`;
}

/** Best-effort reverse mapping so an existing cron expression prefills the builder UI. */
function parseCronExpression(expression: string): Partial<ScheduleFormValues> {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) {
    return { frequency: "custom", customCron: expression };
  }
  const [minute, hour, dom, month, dow] = parts;
  const isDigits = (s: string) => /^\d+$/.test(s);

  if (dom === "*" && month === "*" && hour === "*" && isDigits(minute) && dow === "*") {
    return { frequency: "hourly", minute };
  }
  if (dom === "*" && month === "*" && isDigits(minute) && isDigits(hour)) {
    if (dow === "*") {
      return { frequency: "daily", time: `${pad2(Number(hour))}:${pad2(Number(minute))}` };
    }
    const days = dow
      .split(",")
      .map((n) => DAY_OPTIONS.find((opt) => opt.cron === Number(n))?.value)
      .filter((d): d is DayValue => d !== undefined);
    return {
      frequency: "weekly",
      time: `${pad2(Number(hour))}:${pad2(Number(minute))}`,
      days: days.length > 0 ? days : ["mon"],
    };
  }
  return { frequency: "custom", customCron: expression };
}

function toDatetimeLocalValue(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 16);
}

function formatLastTriggered(iso: string | null): string {
  if (!iso) return "Never run yet.";
  const date = new Date(iso);
  return `Last ran: ${date.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

/** All schedule inputs on this panel are UTC — show a live clock so it's obvious what time it is there. */
function useCurrentUtcTime(): string {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const intervalId = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(intervalId);
  }, []);

  return `${now.toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

export function WorkflowSchedulePanel() {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const { toast } = useToast();
  const { data: schedule, isLoading } = useWorkflowScheduleQuery(workflowId);
  const { upsertSchedule, deleteSchedule } = useWorkflowScheduleMutations();

  const { register, control, handleSubmit, reset, setValue } = useForm<ScheduleFormValues>({
    resolver: zodResolver(scheduleFormSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const mode = useWatch({ control, name: "mode" });
  const frequency = useWatch({ control, name: "frequency" });
  const watchedDays = useWatch({ control, name: "days" });
  const days = useMemo(() => watchedDays ?? [], [watchedDays]);
  const enabled = useWatch({ control, name: "enabled" });
  const minute = useWatch({ control, name: "minute" }) ?? "0";

  useEffect(() => {
    if (!schedule) {
      reset(DEFAULT_VALUES);
      return;
    }
    if (schedule.schedule_type === "once") {
      reset({
        ...DEFAULT_VALUES,
        enabled: schedule.enabled,
        mode: "once",
        runAt: schedule.run_at ? toDatetimeLocalValue(schedule.run_at) : "",
      });
    } else {
      reset({
        ...DEFAULT_VALUES,
        enabled: schedule.enabled,
        mode: "repeat",
        ...parseCronExpression(schedule.cron_expression ?? ""),
      });
    }
  }, [schedule, reset]);

  const toggleDay = useCallback(
    (day: DayValue, checked: boolean) => {
      const current = new Set(days);
      if (checked) current.add(day);
      else current.delete(day);
      setValue("days", Array.from(current) as DayValue[], { shouldDirty: true });
    },
    [days, setValue],
  );

  const onSubmit = useCallback(
    (values: ScheduleFormValues) => {
      if (!workflowId) return;

      if (values.mode === "once") {
        if (!values.runAt) {
          toast({ description: "Pick a date and time.", variant: "destructive" });
          return;
        }
        upsertSchedule.mutate(
          {
            workflowId,
            data: {
              schedule_type: "once",
              run_at: `${values.runAt}:00Z`,
              enabled: values.enabled,
            },
          },
          {
            onSuccess: () => toast({ description: "Schedule saved." }),
            onError: (error) =>
              toast({ description: error.message, variant: "destructive" }),
          },
        );
        return;
      }

      const cronExpression = buildCronExpression(values);
      if (!cronExpression) {
        toast({ description: "Enter a cron expression.", variant: "destructive" });
        return;
      }
      upsertSchedule.mutate(
        {
          workflowId,
          data: {
            schedule_type: "cron",
            cron_expression: cronExpression,
            enabled: values.enabled,
          },
        },
        {
          onSuccess: () => toast({ description: "Schedule saved." }),
          onError: (error) => toast({ description: error.message, variant: "destructive" }),
        },
      );
    },
    [workflowId, upsertSchedule, toast],
  );

  const handleRemove = useCallback(() => {
    if (!workflowId) return;
    deleteSchedule.mutate(workflowId, {
      onSuccess: () => {
        reset(DEFAULT_VALUES);
        toast({ description: "Schedule removed." });
      },
      onError: (error) => toast({ description: error.message, variant: "destructive" }),
    });
  }, [workflowId, deleteSchedule, reset, toast]);

  const minRunAt = useMemo(() => new Date().toISOString().slice(0, 16), []);
  const currentUtcTime = useCurrentUtcTime();

  if (!workflowId) {
    return (
      <div className="flex flex-col items-center px-3 py-11 text-center text-muted-foreground">
        <CalendarClock className="mb-3.5 size-[30px] text-border" aria-hidden />
        <p className="max-w-[220px] text-[13px] leading-[1.5]">
          Save the workflow to configure a schedule.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-11 text-muted-foreground">
        <Loader2 className="size-5 animate-spin" aria-hidden />
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <div className="flex items-center gap-2">
        <CalendarClock className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          Schedule
        </span>
      </div>

      <p className="mt-1.5 text-[11.5px] text-muted-foreground">
        Current time (UTC): <span className="font-mono text-foreground">{currentUtcTime}</span>
      </p>

      <div className="mt-3 flex items-center justify-between gap-2">
        <Label className="text-[13px]" htmlFor="schedule-enabled">
          Enable schedule
        </Label>
        <Switch
          id="schedule-enabled"
          checked={enabled}
          onCheckedChange={(checked) => setValue("enabled", checked, { shouldDirty: true })}
        />
      </div>

      <Tabs
        className="mt-3"
        value={mode}
        onValueChange={(v) => setValue("mode", v as ScheduleFormValues["mode"], { shouldDirty: true })}
      >
        <TabsList className="w-full">
          <TabsTrigger className="flex-1" value="once">
            Run once
          </TabsTrigger>
          <TabsTrigger className="flex-1" value="repeat">
            Repeat
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {mode === "once" ? (
        <div className="mt-3 grid gap-1">
          <Label className="text-xs" htmlFor="schedule-run-at">
            Date &amp; time (UTC)
          </Label>
          <Input
            id="schedule-run-at"
            type="datetime-local"
            min={minRunAt}
            {...register("runAt")}
          />
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="grid gap-1">
            <Label className="text-xs">Frequency</Label>
            <Select
              value={frequency}
              onValueChange={(v) => setValue("frequency", v as Frequency, { shouldDirty: true })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="hourly">Hourly</SelectItem>
                <SelectItem value="daily">Daily</SelectItem>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="custom">Custom (cron)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {frequency === "hourly" ? (
            <div className="grid gap-1">
              <Label className="text-xs">Minute of hour (UTC)</Label>
              <Select
                value={String(minute)}
                onValueChange={(v) => setValue("minute", v, { shouldDirty: true })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">:00</SelectItem>
                  <SelectItem value="15">:15</SelectItem>
                  <SelectItem value="30">:30</SelectItem>
                  <SelectItem value="45">:45</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {frequency === "daily" || frequency === "weekly" ? (
            <div className="grid gap-1">
              <Label className="text-xs" htmlFor="schedule-time">
                Time (UTC)
              </Label>
              <Input id="schedule-time" type="time" {...register("time")} />
            </div>
          ) : null}

          {frequency === "weekly" ? (
            <div className="grid gap-1">
              <Label className="text-xs">Days</Label>
              <div className="flex flex-wrap gap-2.5">
                {DAY_OPTIONS.map((day) => (
                  <label key={day.value} className="flex items-center gap-1.5 text-xs">
                    <Checkbox
                      checked={days.includes(day.value)}
                      onCheckedChange={(checked) => toggleDay(day.value, checked === true)}
                    />
                    {day.label}
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          {frequency === "custom" ? (
            <div className="grid gap-1">
              <Label className="text-xs" htmlFor="schedule-cron">
                Cron expression (UTC)
              </Label>
              <Input
                id="schedule-cron"
                placeholder="0 9 * * 1-5"
                {...register("customCron")}
              />
              <p className="text-[11px] text-muted-foreground">
                Standard 5-field cron: minute hour day-of-month month day-of-week.
              </p>
            </div>
          ) : null}
        </div>
      )}

      {schedule ? (
        <p className="mt-3 text-[11.5px] text-muted-foreground">
          {formatLastTriggered(schedule.last_triggered_at)}
        </p>
      ) : null}

      <Button className="mt-4 w-full" disabled={upsertSchedule.isPending} type="submit">
        {upsertSchedule.isPending ? "Saving…" : "Save schedule"}
      </Button>

      {schedule ? (
        <Button
          className="mt-2 w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
          disabled={deleteSchedule.isPending}
          onClick={handleRemove}
          type="button"
          variant="outline"
        >
          <Trash2 className="size-3.5" aria-hidden />
          Remove schedule
        </Button>
      ) : null}
    </form>
  );
}
