"use client";

import { useCallback, useMemo } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useSecretManagerConnectionsQuery,
  type SecretManagerConnectionRecord,
} from "@/hooks/queries/use-secret-manager-connections-query";

interface SecretManagerConnectionFieldProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

const BACKEND_LABELS: Record<string, string> = {
  openbao: "OpenBao",
  infisical: "Infisical",
};

const EMPTY_CONNECTIONS: SecretManagerConnectionRecord[] = [];

/** connection_id picker shared by secret-get / secret-set / secret-generate. */
export function SecretManagerConnectionField({
  config,
  onChange,
}: SecretManagerConnectionFieldProps) {
  const { data, isLoading } = useSecretManagerConnectionsQuery({ activeOnly: true });
  const connections = data?.connections ?? EMPTY_CONNECTIONS;

  const connectionId = typeof config.connection_id === "number" ? config.connection_id : null;

  const selected = useMemo(
    () => connections.find((connection) => connection.id === connectionId) ?? null,
    [connections, connectionId],
  );

  const setConnection = useCallback(
    (value: string) => onChange({ ...config, connection_id: Number(value) }),
    [config, onChange],
  );

  return (
    <div className="space-y-1.5">
      <span className="font-mono text-xs font-medium">connection_id</span>
      {isLoading ? (
        <p className="text-[11px] text-muted-foreground">Loading connections…</p>
      ) : connections.length === 0 && connectionId == null ? (
        <p className="text-[11px] text-warning-foreground">
          No Secret Manager connections in Settings → Secret Manager
        </p>
      ) : (
        <Select
          value={connectionId != null ? String(connectionId) : ""}
          onValueChange={setConnection}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select a connection" />
          </SelectTrigger>
          <SelectContent>
            {connectionId != null && !connections.some((c) => c.id === connectionId) && (
              <SelectItem value={String(connectionId)} disabled>
                Connection #{connectionId} (not accessible)
              </SelectItem>
            )}
            {connections.map((connection) => (
              <SelectItem key={connection.id} value={String(connection.id)}>
                {connection.name} ({BACKEND_LABELS[connection.backend] ?? connection.backend})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <p className="text-[11px] text-muted-foreground">
        {selected
          ? `${BACKEND_LABELS[selected.backend] ?? selected.backend} connection, configured in Settings → Secret Manager.`
          : "Which configured Secret Manager connection to use. Configure connections in Settings → Secret Manager."}
      </p>
    </div>
  );
}
