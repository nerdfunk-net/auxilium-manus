"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DAY_OPTIONS,
  type DayValue,
  parseCronExpression,
} from "@/components/features/workflows/utils/schedule-cron";

import type { ScheduleType } from "../types/schedule";

export interface TimingValue {
  schedule_type: ScheduleType;
  frequency: "hourly" | "daily" | "weekly" | "custom";
  minute: string;
  time: string;
  days: DayValue[];
  customCron: string;
  /** `datetime-local` value (UTC), used only when schedule_type === "once". */
  runAt: string;
}

export const DEFAULT_TIMING: TimingValue = {
  schedule_type: "cron",
  frequency: "daily",
  minute: "0",
  time: "09:00",
  days: ["mon"],
  customCron: "",
  runAt: "",
};

/** Build a TimingValue from an existing schedule's cron/run_at fields. */
export function timingFromSchedule(
  schedule_type: ScheduleType,
  cron_expression: string | null,
  run_at: string | null,
): TimingValue {
  if (schedule_type === "once") {
    return {
      ...DEFAULT_TIMING,
      schedule_type: "once",
      runAt: run_at ? new Date(run_at).toISOString().slice(0, 16) : "",
    };
  }
  return {
    ...DEFAULT_TIMING,
    schedule_type: "cron",
    ...parseCronExpression(cron_expression ?? ""),
  };
}

function useCurrentUtcTime(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return `${now.toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

interface ScheduleTimingFieldsProps {
  value: TimingValue;
  onChange: (next: TimingValue) => void;
}

export function ScheduleTimingFields({ value, onChange }: ScheduleTimingFieldsProps) {
  const currentUtcTime = useCurrentUtcTime();
  const minRunAt = useMemo(() => new Date().toISOString().slice(0, 16), []);

  const patch = useCallback(
    (partial: Partial<TimingValue>) => onChange({ ...value, ...partial }),
    [value, onChange],
  );

  const toggleDay = useCallback(
    (day: DayValue, checked: boolean) => {
      const next = new Set(value.days);
      if (checked) next.add(day);
      else next.delete(day);
      patch({ days: Array.from(next) });
    },
    [value.days, patch],
  );

  return (
    <div className="space-y-3">
      <p className="text-[11.5px] text-muted-foreground">
        All times are UTC. Current time:{" "}
        <span className="font-mono text-foreground">{currentUtcTime}</span>
      </p>

      <Tabs
        value={value.schedule_type}
        onValueChange={(v) => patch({ schedule_type: v as ScheduleType })}
      >
        <TabsList className="w-full">
          <TabsTrigger className="flex-1" value="once">
            Run once
          </TabsTrigger>
          <TabsTrigger className="flex-1" value="cron">
            Repeat
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {value.schedule_type === "once" ? (
        <div className="grid gap-1">
          <Label className="text-xs" htmlFor="schedule-run-at">
            Date &amp; time (UTC)
          </Label>
          <Input
            id="schedule-run-at"
            type="datetime-local"
            min={minRunAt}
            value={value.runAt}
            onChange={(e) => patch({ runAt: e.target.value })}
          />
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid gap-1">
            <Label className="text-xs">Frequency</Label>
            <Select
              value={value.frequency}
              onValueChange={(v) => patch({ frequency: v as TimingValue["frequency"] })}
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

          {value.frequency === "hourly" ? (
            <div className="grid gap-1">
              <Label className="text-xs">Minute of hour (UTC)</Label>
              <Select value={value.minute} onValueChange={(v) => patch({ minute: v })}>
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

          {value.frequency === "daily" || value.frequency === "weekly" ? (
            <div className="grid gap-1">
              <Label className="text-xs" htmlFor="schedule-time">
                Time (UTC)
              </Label>
              <Input
                id="schedule-time"
                type="time"
                value={value.time}
                onChange={(e) => patch({ time: e.target.value })}
              />
            </div>
          ) : null}

          {value.frequency === "weekly" ? (
            <div className="grid gap-1">
              <Label className="text-xs">Days</Label>
              <div className="flex flex-wrap gap-2.5">
                {DAY_OPTIONS.map((day) => (
                  <label key={day.value} className="flex items-center gap-1.5 text-xs">
                    <Checkbox
                      checked={value.days.includes(day.value)}
                      onCheckedChange={(checked) => toggleDay(day.value, checked === true)}
                    />
                    {day.label}
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          {value.frequency === "custom" ? (
            <div className="grid gap-1">
              <Label className="text-xs" htmlFor="schedule-cron">
                Cron expression (UTC)
              </Label>
              <Input
                id="schedule-cron"
                placeholder="0 9 * * 1-5"
                value={value.customCron}
                onChange={(e) => patch({ customCron: e.target.value })}
              />
              <p className="text-[11px] text-muted-foreground">
                Standard 5-field cron: minute hour day-of-month month day-of-week.
              </p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
