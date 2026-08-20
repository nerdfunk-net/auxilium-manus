export const DAY_OPTIONS = [
  { value: "mon", label: "Mon", cron: 1 },
  { value: "tue", label: "Tue", cron: 2 },
  { value: "wed", label: "Wed", cron: 3 },
  { value: "thu", label: "Thu", cron: 4 },
  { value: "fri", label: "Fri", cron: 5 },
  { value: "sat", label: "Sat", cron: 6 },
  { value: "sun", label: "Sun", cron: 0 },
] as const;

export type DayValue = (typeof DAY_OPTIONS)[number]["value"];
type CronDay = (typeof DAY_OPTIONS)[number]["cron"];

export interface ScheduleCronValues {
  frequency: "hourly" | "daily" | "weekly" | "custom";
  minute?: string;
  time?: string;
  days?: DayValue[];
  customCron?: string;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function buildCronExpression(values: ScheduleCronValues): string {
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
export function parseCronExpression(expression: string): Partial<ScheduleCronValues> {
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
