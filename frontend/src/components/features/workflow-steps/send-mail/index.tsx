"use client";

import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { SendMailHelpPanel } from "./help-panel";
import { PlaceholderField } from "./placeholder-field";

const SMTP_SERVER_KEY = "smtp_server";
const SMTP_PORT_KEY = "smtp_port";
const SECURITY_KEY = "security";
const VERIFY_TLS_KEY = "verify_tls";
const CREDENTIAL_KEY = "credential_reference";
const FROM_KEY = "from_address";
const TO_KEY = "to";
const SUBJECT_KEY = "subject";
const BODY_KEY = "body";

type SecurityMode = "none" | "starttls" | "ssl";

const DEFAULT_SECURITY: SecurityMode = "starttls";

const SECURITY_OPTIONS: ReadonlyArray<{ value: SecurityMode; label: string; port: number }> = [
  { value: "none", label: "None (plain SMTP)", port: 25 },
  { value: "starttls", label: "STARTTLS", port: 587 },
  { value: "ssl", label: "SSL/TLS (implicit)", port: 465 },
];

const DEFAULT_PORT = 587;
/** Radix Select forbids an empty-string item value, so "no credential" needs a sentinel. */
const NO_CREDENTIAL = "__none__";
/** Basic Auth only: an SSH device password must never be sent to the configured SMTP host. */
const SMTP_CREDENTIAL_TYPES: ReadonlySet<string> = new Set(["generic"]);

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function securityFromConfig(config: Record<string, unknown>): SecurityMode {
  const raw = config[SECURITY_KEY];
  return SECURITY_OPTIONS.some((option) => option.value === raw)
    ? (raw as SecurityMode)
    : DEFAULT_SECURITY;
}

function portFromConfig(config: Record<string, unknown>): string {
  const raw = config[SMTP_PORT_KEY];
  if (typeof raw === "number") return String(raw);
  if (typeof raw === "string") return raw;
  return String(DEFAULT_PORT);
}

function SendMailConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const { data, isLoading } = useCredentialsQuery();
  const credentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) =>
          SMTP_CREDENTIAL_TYPES.has(credential.type) && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const server = stringFromConfig(config, SMTP_SERVER_KEY);
  const port = portFromConfig(config);
  const security = securityFromConfig(config);
  const credentialReference = stringFromConfig(config, CREDENTIAL_KEY);
  // Absent means "on": workflows saved before this option existed stay verified.
  const verifyTls = config[VERIFY_TLS_KEY] !== false;

  const patch = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const handleServerChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => patch(SMTP_SERVER_KEY, event.target.value),
    [patch],
  );

  const handlePortChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const digits = event.target.value.replace(/\D/g, "");
      patch(SMTP_PORT_KEY, digits === "" ? "" : Number(digits));
    },
    [patch],
  );

  // Switching protocol moves the port to that protocol's conventional port,
  // but only while the port is still the previous protocol's default -- a
  // deliberately typed custom port is left alone.
  const handleSecurityChange = useCallback(
    (next: string) => {
      const previousDefault = SECURITY_OPTIONS.find((option) => option.value === security)?.port;
      const nextDefault = SECURITY_OPTIONS.find((option) => option.value === next)?.port;
      const portIsDefault = port === String(previousDefault);
      onChange({
        ...config,
        [SECURITY_KEY]: next,
        ...(portIsDefault && nextDefault !== undefined ? { [SMTP_PORT_KEY]: nextDefault } : {}),
      });
    },
    [config, onChange, port, security],
  );

  const handleVerifyTlsChange = useCallback(
    (checked: boolean) => patch(VERIFY_TLS_KEY, checked),
    [patch],
  );

  const handleCredentialChange = useCallback(
    (value: string) => patch(CREDENTIAL_KEY, value === NO_CREDENTIAL ? "" : value),
    [patch],
  );

  const fieldProps = { nodeId, workflowNodes, workflowEdges };

  return (
    <div className="flex flex-col gap-4">
      {/* smtp_server */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{SMTP_SERVER_KEY}</span>
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          placeholder="smtp.example.com"
          value={server}
          onChange={handleServerChange}
        />
        {!server && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      {/* security */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{SECURITY_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            smtp
          </Badge>
        </div>
        <Select value={security} onValueChange={handleSecurityChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SECURITY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* verify_tls: only meaningful when the connection is encrypted */}
      {security !== "none" && (
        <div className="space-y-1.5">
          <label className="flex items-start gap-1.5 text-xs font-medium">
            <Checkbox
              className="mt-0.5"
              checked={verifyTls}
              onCheckedChange={(checked) => handleVerifyTlsChange(checked === true)}
            />
            <span>
              Validate TLS certificate
              <span className="block text-[11px] font-normal leading-4 text-muted-foreground">
                Turn off only for a server with a self-signed certificate, e.g. a local Proton
                Mail Bridge.
              </span>
            </span>
          </label>
          {!verifyTls && (
            <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
              The server&apos;s identity is not checked. Traffic is still encrypted, but anyone
              who can intercept the connection could impersonate the server. Use this only on a
              trusted local connection.
            </p>
          )}
        </div>
      )}

      {/* smtp_port */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{SMTP_PORT_KEY}</span>
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          inputMode="numeric"
          placeholder="587"
          value={port}
          onChange={handlePortChange}
        />
        {!port && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      {/* credential_reference */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{CREDENTIAL_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            vault
          </Badge>
        </div>
        {isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : (
          <Select
            value={credentialReference || NO_CREDENTIAL}
            onValueChange={handleCredentialChange}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select credential" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CREDENTIAL}>No authentication</SelectItem>
              {credentialReference &&
                !credentials.some((credential) => credential.name === credentialReference) && (
                  <SelectItem value={credentialReference} disabled>
                    {credentialReference} (not accessible)
                  </SelectItem>
                )}
              {credentials.map((credential) => (
                <SelectItem key={credential.id} value={credential.name}>
                  {credential.name} ({credential.username})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <p className="text-[11px] leading-4 text-muted-foreground">
          Username and password are read from the credential vault, never stored in the step.
          Only Basic Auth credentials are listed.
        </p>
        {security === "none" && credentialReference && (
          <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
            The password would be sent unencrypted, so this step will not run. Choose STARTTLS or
            SSL/TLS, or select No authentication.
          </p>
        )}
      </div>

      <PlaceholderField
        {...fieldProps}
        configKey={FROM_KEY}
        placeholder="manus@example.com"
        value={stringFromConfig(config, FROM_KEY)}
        onValueChange={(value) => patch(FROM_KEY, value)}
      />
      <PlaceholderField
        {...fieldProps}
        configKey={TO_KEY}
        placeholder="ops@example.com, {custom.owner_email}"
        value={stringFromConfig(config, TO_KEY)}
        onValueChange={(value) => patch(TO_KEY, value)}
      />
      <PlaceholderField
        {...fieldProps}
        configKey={SUBJECT_KEY}
        placeholder="Config changed on {device.name}"
        value={stringFromConfig(config, SUBJECT_KEY)}
        onValueChange={(value) => patch(SUBJECT_KEY, value)}
      />
      <PlaceholderField
        {...fieldProps}
        multiline
        configKey={BODY_KEY}
        placeholder="Workflow finished: {device_count} device(s) ({devices})"
        value={stringFromConfig(config, BODY_KEY)}
        onValueChange={(value) => patch(BODY_KEY, value)}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">{"{path.to.value}"}</span> for device attributes, e.g{" "}
          <span className="font-mono">{"{device.name}"}</span>.{" "}
          <span className="font-mono">{"{devices}"}</span> and{" "}
          <span className="font-mono">{"{device_count}"}</span> summarize a multi-device run.
        </p>
      </PlaceholderField>
    </div>
  );
}

export const SendMailPlugin: PluginUIComponent = {
  ConfigPanel: SendMailConfigPanel,
  HelpPanel: SendMailHelpPanel,
};
