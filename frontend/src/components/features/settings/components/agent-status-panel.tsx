"use client";

import { Badge } from "@/components/ui/badge";
import { useAgentStatusQuery } from "@/hooks/queries/use-agent-sources-query";

interface AgentStatusPanelProps {
  sourceId: string;
  enabled: boolean;
}

function formatHeartbeat(epochSeconds: number | null): string | null {
  if (epochSeconds == null) {
    return null;
  }
  return new Date(epochSeconds * 1000).toLocaleString();
}

/** Heartbeat view of a saved agent: online/offline, version and the handlers it offers. */
export function AgentStatusPanel({ sourceId, enabled }: AgentStatusPanelProps) {
  const { data, isLoading, isError } = useAgentStatusQuery(sourceId, { enabled });

  if (isLoading) {
    return <p className="text-xs text-muted-foreground">Reading agent status…</p>;
  }
  if (isError || !data) {
    return <p className="text-xs text-muted-foreground">Agent status is not available.</p>;
  }

  const label = data.online === true ? "Online" : data.online === false ? "Offline" : "Unknown";
  const variant = data.online === true ? "default" : data.online === false ? "destructive" : "secondary";
  const lastSeen = formatHeartbeat(data.last_heartbeat);

  return (
    <div className="space-y-1.5 rounded-lg border bg-muted/30 p-3" aria-label="Agent status">
      <div className="flex items-center gap-2">
        <Badge variant={variant}>{label}</Badge>
        {data.version ? (
          <span className="text-xs text-muted-foreground">version {data.version}</span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{data.message}</p>
      {lastSeen ? <p className="text-xs text-muted-foreground">Last heartbeat: {lastSeen}</p> : null}
      {data.handlers.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Handlers: <span className="font-mono">{data.handlers.join(", ")}</span>
        </p>
      ) : null}
    </div>
  );
}
