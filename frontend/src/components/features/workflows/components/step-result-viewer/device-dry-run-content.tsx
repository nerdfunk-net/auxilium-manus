"use client";

import { Badge } from "@/components/ui/badge";

export interface DryRunEntry {
  nodeId: string;
  payload: Record<string, unknown>;
}

const KNOWN_KEYS = new Set([
  "would_execute",
  "would_deploy",
  "execution_mode",
  "commands",
  "host",
]);

function asStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.every((item) => typeof item === "string") ? (value as string[]) : null;
}

function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

/** Every step that supports dry_run writes device.dry_run_results keyed by its
 * own node id -- this reads that field regardless of which step(s) produced it. */
export function getDryRunEntries(
  dryRunResults: Record<string, Record<string, unknown>>,
): DryRunEntry[] {
  return Object.entries(dryRunResults ?? {}).map(([nodeId, payload]) => ({
    nodeId,
    payload: (payload ?? {}) as Record<string, unknown>,
  }));
}

export function DeviceDryRunContent({ entries }: { entries: DryRunEntry[] }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        No commands were sent to this device — this is a preview of what each dry-run step below
        would have done.
      </p>
      {entries.map(({ nodeId, payload }) => {
        const commands = asStringList(payload.commands);
        const extraEntries = Object.entries(payload).filter(([key]) => !KNOWN_KEYS.has(key));
        const wouldLabel = payload.would_deploy
          ? "would deploy"
          : payload.would_execute
            ? "would execute"
            : null;

        return (
          <div key={nodeId} className="rounded-lg border bg-card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-medium">{nodeId}</span>
              {wouldLabel ? (
                <Badge className="text-[10px]" variant="secondary">
                  {wouldLabel}
                </Badge>
              ) : null}
              {typeof payload.execution_mode === "string" ? (
                <Badge className="text-[10px]" variant="outline">
                  {payload.execution_mode}
                </Badge>
              ) : null}
            </div>
            {typeof payload.host === "string" && payload.host ? (
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">{payload.host}</p>
            ) : null}
            {commands && commands.length > 0 ? (
              <pre className="mt-2 max-h-60 overflow-auto rounded bg-muted/40 p-2 text-[11px] font-mono whitespace-pre-wrap">
                {commands.join("\n")}
              </pre>
            ) : null}
            {extraEntries.length > 0 ? (
              <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[11px]">
                {extraEntries.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="font-mono text-muted-foreground">{key}</dt>
                    <dd className="break-all">{formatValue(value)}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
