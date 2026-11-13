"use client";

import { useCallback, useMemo, useState, type ChangeEvent } from "react";

import { DeployReadTimeoutFields } from "@/components/features/workflow-steps/deploy-rendered-template/deploy-fields";
import {
  parseRetryBackoffSeconds,
  RetryBackoffSecondsField,
} from "@/components/features/workflow-steps/shared/retry-backoff-fields";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import { clampReadTimeout, DEFAULT_READ_TIMEOUT } from "../run-command/config";
import { CheckboxField } from "../shared/checkbox-field";
import { FieldHeader } from "../shared/field-header";
import {
  isNautobotSourceConfigured,
  NAUTOBOT_SOURCE_ID_KEY,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import {
  buildDiscoverNetworkConfig,
  clampConcurrency,
  clampMaxDepth,
  clampMaxDevices,
  configIssues,
  DEFAULT_CONCURRENCY,
  DEFAULT_MAX_DEPTH,
  DEFAULT_MAX_DEVICES,
  managementIpHint,
  MAX_CONCURRENCY,
  MAX_MAX_DEPTH,
  MAX_MAX_DEVICES,
  MIN_CONCURRENCY,
  MIN_MAX_DEPTH,
  MIN_MAX_DEVICES,
  parsePrefixText,
} from "./config";
import { DiscoverNetworkHelpPanel } from "./help-panel";

const EMPTY_PREFIXES: string[] = [];

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

interface ManagementIpFieldsProps {
  config: Record<string, unknown>;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onSourceChange: (sourceId: string) => void;
}

/** The Nautobot lookup of a discovered device's management address, and its source. */
function ManagementIpFields({
  config,
  enabled,
  onEnabledChange,
  onSourceChange,
}: ManagementIpFieldsProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const [sourceOpen, setSourceOpen] = useState(false);
  const isSourceConfigured = isNautobotSourceConfigured(config);
  const hint = useMemo(() => managementIpHint(config), [config]);

  return (
    <div className="flex flex-col gap-2">
      <CheckboxField
        id="discover-network-management-ip"
        label="resolve_management_ip"
        checked={enabled}
        onCheckedChange={onEnabledChange}
        description="Get the management IP of a discovered device. CDP reports an interface address, which is often not the address a device accepts logins on. The device is looked up in Nautobot by name; if that finds nothing, by the interface address. The management IP found is the one that is checked against the permitted prefixes and logged into."
      />
      {enabled ? (
        <div className="space-y-1.5">
          <FieldHeader name={NAUTOBOT_SOURCE_ID_KEY} type="string" />
          {isSourceConfigured ? (
            <p className="font-mono text-[11px] text-muted-foreground">
              {sourceId}
              {credentials.isReady ? (
                <span className="block truncate font-sans">{credentials.url}</span>
              ) : credentials.isLoading ? (
                <span className="block font-sans">Loading credentials…</span>
              ) : (
                <span className="block font-sans text-warning-foreground">
                  Source not found in settings
                </span>
              )}
            </p>
          ) : null}
          {hint ? <p className="text-[11px] text-warning-foreground">{hint}</p> : null}
          <Button
            className="h-7 w-full text-xs"
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setSourceOpen(true)}
          >
            {isSourceConfigured ? "Edit Source" : "Configure Source"}
          </Button>
          <NautobotSourceSelectDialog
            open={sourceOpen}
            selectedSourceId={sourceId}
            onClose={() => setSourceOpen(false)}
            onSave={onSourceChange}
          />
        </div>
      ) : null}
    </div>
  );
}

interface PermittedPrefixesFieldProps {
  prefixes: string[];
  onChange: (prefixes: string[]) => void;
}

/** One CIDR prefix per line. The text is kept locally so a half-typed line is not rewritten. */
function PermittedPrefixesField({ prefixes, onChange }: PermittedPrefixesFieldProps) {
  const [text, setText] = useState(() => prefixes.join("\n"));

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      setText(event.target.value);
      onChange(parsePrefixText(event.target.value));
    },
    [onChange],
  );

  return (
    <div className="space-y-1.5">
      <FieldHeader name="permitted_prefixes" type="string_list" />
      <Textarea
        id="discover-network-prefixes"
        value={text}
        onChange={handleChange}
        rows={4}
        placeholder={"10.1.0.0/16\n192.168.5.0/24"}
        className="font-mono text-xs"
        aria-label="Permitted prefixes"
      />
      <p className="text-[11px] text-muted-foreground">
        One IPv4 prefix per line in CIDR form. A discovered device is logged into only if its
        management address lies in one of them.
      </p>
    </div>
  );
}

function DiscoverNetworkConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const follow = config.follow_neighbors === true;
  const prefixes = Array.isArray(config.permitted_prefixes)
    ? (config.permitted_prefixes as string[])
    : EMPTY_PREFIXES;
  const onlyInfrastructure = config.follow_only_infrastructure !== false;
  const dryRun = config.dry_run === true;
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const readTimeout = numberOr(config.read_timeout, DEFAULT_READ_TIMEOUT);
  const maxDevices = numberOr(config.max_devices, DEFAULT_MAX_DEVICES);
  const maxDepth = numberOr(config.max_depth, DEFAULT_MAX_DEPTH);
  const concurrency = numberOr(config.concurrency, DEFAULT_CONCURRENCY);
  const retryBackoffSeconds = useMemo(() => parseRetryBackoffSeconds(config), [config]);
  const issues = useMemo(() => configIssues(config), [config]);

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => onChange(buildDiscoverNetworkConfig(config, patch)),
    [config, onChange],
  );
  const handleResolveChange = useCallback(
    (checked: boolean) => patchConfig({ resolve_management_ip: checked }),
    [patchConfig],
  );
  const handleSourceChange = useCallback(
    (sourceId: string) => patchConfig({ [NAUTOBOT_SOURCE_ID_KEY]: sourceId }),
    [patchConfig],
  );
  const handlePrefixes = useCallback(
    (next: string[]) => patchConfig({ permitted_prefixes: next }),
    [patchConfig],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <CheckboxField
        id="discover-network-follow"
        label="follow_neighbors"
        checked={follow}
        onCheckedChange={(checked) => patchConfig({ follow_neighbors: checked })}
        description="Log into the devices found through CDP and follow their neighbours in turn. Off: only the devices coming into this step are visited and their neighbours are listed. Needs permitted prefixes. The operator must also allow it (DISCOVER_NETWORK_FOLLOW_ENABLED). CDP is not authenticated: use narrow prefixes and a read-only credential."
      />

      {follow || prefixes.length > 0 ? (
        <PermittedPrefixesField prefixes={prefixes} onChange={handlePrefixes} />
      ) : null}

      {issues.length > 0 ? (
        <ul className="space-y-0.5" role="alert">
          {issues.map((issue) => (
            <li key={issue} className="text-[11px] text-destructive">
              {issue}
            </li>
          ))}
        </ul>
      ) : null}

      {follow ? (
        <ManagementIpFields
          config={config}
          enabled={config.resolve_management_ip !== false}
          onEnabledChange={handleResolveChange}
          onSourceChange={handleSourceChange}
        />
      ) : null}

      <CheckboxField
        id="discover-network-infrastructure"
        label="follow_only_infrastructure"
        checked={onlyInfrastructure}
        onCheckedChange={(checked) => patchConfig({ follow_only_infrastructure: checked })}
        description="Follow only neighbours that advertise a router or switch capability. Phones, access points and hosts are listed but not logged into."
      />

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <FieldHeader name="max_devices" type="integer" />
          <Input
            type="number"
            min={MIN_MAX_DEVICES}
            max={MAX_MAX_DEVICES}
            value={maxDevices}
            onChange={(event) => patchConfig({ max_devices: clampMaxDevices(event.target.value) })}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">Devices to log into, seeds included.</p>
        </div>
        <div className="space-y-1.5">
          <FieldHeader name="max_depth" type="integer" />
          <Input
            type="number"
            min={MIN_MAX_DEPTH}
            max={MAX_MAX_DEPTH}
            value={maxDepth}
            onChange={(event) => patchConfig({ max_depth: clampMaxDepth(event.target.value) })}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">Hops from a seed.</p>
        </div>
        <div className="space-y-1.5">
          <FieldHeader name="concurrency" type="integer" />
          <Input
            type="number"
            min={MIN_CONCURRENCY}
            max={MAX_CONCURRENCY}
            value={concurrency}
            onChange={(event) =>
              patchConfig({ concurrency: clampConcurrency(event.target.value) })
            }
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">Logins at the same time.</p>
        </div>
      </div>

      <CheckboxField
        id="discover-network-dry-run"
        label="dry_run"
        checked={dryRun}
        onCheckedChange={(checked) => patchConfig({ dry_run: checked })}
        description={
          <>
            Do not connect to devices. Records the command and the scope that would be used under{" "}
            <span className="font-mono">dry_run_results</span>.
          </>
        }
      />

      <div className="space-y-1.5">
        <FieldHeader name="network_driver_override" type="string" />
        <Input
          value={networkDriverOverride}
          onChange={(event) => patchConfig({ network_driver_override: event.target.value })}
          placeholder="cisco_ios (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          For devices whose platform is unknown, and for discovered devices that report no
          platform. Supported: cisco_ios, cisco_xe, cisco_nxos.
        </p>
      </div>

      <DeployReadTimeoutFields
        readTimeout={readTimeout}
        onReadTimeoutChange={(value) => patchConfig({ read_timeout: clampReadTimeout(value) })}
      />

      <RetryBackoffSecondsField
        retryBackoffSeconds={retryBackoffSeconds}
        onRetryBackoffSecondsChange={(next) => patchConfig({ retry_backoff_seconds: next })}
      />
    </div>
  );
}

export const DiscoverNetworkPlugin: PluginUIComponent = {
  ConfigPanel: DiscoverNetworkConfigPanel,
  HelpPanel: DiscoverNetworkHelpPanel,
};
