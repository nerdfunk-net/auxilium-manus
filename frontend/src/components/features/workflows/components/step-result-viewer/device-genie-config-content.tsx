"use client";

import type { GenieParsedConfigEntry } from "./types";

export function DeviceGenieConfigContent({
  entries,
}: {
  entries: Array<{ key: string; entry: GenieParsedConfigEntry }>;
}) {
  return (
    <div className="mt-2 space-y-3">
      {entries.map(({ key, entry }) => (
        <div key={key} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">output_key: {key}</p>
          {"running" in entry ? (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Running config (parsed)
              </p>
              <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono">
                {entry.running != null ? JSON.stringify(entry.running, null, 2) : "—"}
              </pre>
            </div>
          ) : null}
          {"startup" in entry ? (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Startup config (parsed)
              </p>
              <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono">
                {entry.startup != null ? JSON.stringify(entry.startup, null, 2) : "—"}
              </pre>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
