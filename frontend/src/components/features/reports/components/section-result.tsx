"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Presentation } from "../types/report-definition";
import type { QueryResult } from "../types/report-query";
import { chartData, singleNumber } from "../utils/report-sections";
import { ResultTable } from "./result-table";

// Existing theme tokens (the app defines no chart palette); they follow light and dark mode.
const SERIES_COLORS = [
  "var(--primary)",
  "var(--info-foreground)",
  "var(--success-foreground)",
  "var(--warning-foreground)",
  "var(--error-foreground)",
];


interface SectionResultProps {
  result: QueryResult;
  presentation: Presentation;
}

/** One query result drawn the way its section asks. Falls back to a table when a chart cannot be drawn. */
export function SectionResult({ result, presentation }: SectionResultProps) {
  if (presentation === "number") {
    const value = singleNumber(result);
    if (value) {
      return (
        <div className="py-2">
          <p className="text-4xl font-semibold tabular-nums">{value.value.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">{value.label}</p>
        </div>
      );
    }
  }
  if (presentation === "bar" || presentation === "line") {
    const data = chartData(result);
    if (data.seriesKeys.length > 0 && data.points.length > 0) {
      return <SectionChart kind={presentation} data={data} />;
    }
  }
  return (
    <div className="max-h-96 overflow-hidden rounded-md border">
      <div className="max-h-96">
        <ResultTable result={result} />
      </div>
    </div>
  );
}

function SectionChart({
  kind,
  data,
}: {
  kind: "bar" | "line";
  data: ReturnType<typeof chartData>;
}) {
  const Chart = kind === "bar" ? BarChart : LineChart;
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data.points}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={data.labelKey} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} allowDecimals />
          <Tooltip />
          {data.seriesKeys.length > 1 ? <Legend /> : null}
          {data.seriesKeys.map((key, index) =>
            kind === "bar" ? (
              <Bar key={key} dataKey={key} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
            ) : (
              <Line
                key={key}
                dataKey={key}
                type="monotone"
                stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                dot={false}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
