"use client";

import { useCallback, useMemo } from "react";

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
import { Input } from "@/components/ui/input";

import { CheckboxField } from "../shared/checkbox-field";
import { FieldHeader } from "../shared/field-header";
import { clampReadTimeout, DEFAULT_READ_TIMEOUT } from "../run-command/config";
import {
  buildCollectClientDataConfig,
  clampDnsConcurrency,
  clampDnsTimeout,
  DEFAULT_DNS_CONCURRENCY,
  DEFAULT_DNS_TIMEOUT_SECONDS,
  MAX_DNS_CONCURRENCY,
  MAX_DNS_TIMEOUT_SECONDS,
  MIN_DNS_CONCURRENCY,
  MIN_DNS_TIMEOUT_SECONDS,
} from "./config";
import { CollectClientDataHelpPanel } from "./help-panel";

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function CollectClientDataConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const collectIp = config.collect_ip_address !== false;
  const collectMac = config.collect_mac_address !== false;
  const collectVrfs = collectIp && config.collect_vrfs !== false;
  const collectHostname = collectIp && config.collect_hostname === true;
  const collectNeighbors = config.collect_neighbors === true;
  const dryRun = config.dry_run === true;
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const readTimeout = numberOr(config.read_timeout, DEFAULT_READ_TIMEOUT);
  const dnsTimeout = numberOr(config.dns_timeout_seconds, DEFAULT_DNS_TIMEOUT_SECONDS);
  const dnsConcurrency = numberOr(config.dns_concurrency, DEFAULT_DNS_CONCURRENCY);
  const retryBackoffSeconds = useMemo(() => parseRetryBackoffSeconds(config), [config]);

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => onChange(buildCollectClientDataConfig(config, patch)),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <CheckboxField
        id="collect-ip-address"
        label="collect_ip_address"
        checked={collectIp}
        onCheckedChange={(checked) => patchConfig({ collect_ip_address: checked })}
        description="Read the ARP table (show ip arp): IP address, MAC, interface, VRF and VLAN."
      />
      <CheckboxField
        id="collect-mac-address"
        label="collect_mac_address"
        checked={collectMac}
        onCheckedChange={(checked) => patchConfig({ collect_mac_address: checked })}
        description="Read the MAC address table (show mac address-table). A device without that command is recorded as not supported, not failed."
      />
      <CheckboxField
        id="collect-vrfs"
        label="collect_vrfs"
        checked={collectVrfs}
        onCheckedChange={(checked) => patchConfig({ collect_vrfs: checked })}
        description="Discover the VRFs (show vrf) and read the ARP table of each. Needs collect_ip_address."
      />
      <CheckboxField
        id="collect-hostname"
        label="collect_hostname"
        checked={collectHostname}
        onCheckedChange={(checked) => patchConfig({ collect_hostname: checked })}
        description="Resolve the IP addresses to hostnames with reverse DNS. Needs collect_ip_address."
      />

      <CheckboxField
        id="collect-neighbors"
        label="collect_neighbors"
        checked={collectNeighbors}
        onCheckedChange={(checked) => patchConfig({ collect_neighbors: checked })}
        description="Read the LLDP and CDP neighbours (and the port-channels) of the ports. A port with a switch, router or access point behind it is then an uplink, instead of a guess from the number of MACs. Off by default: it adds commands per device."
      />

      {collectHostname ? (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <FieldHeader name="dns_timeout_seconds" type="number" />
            <Input
              type="number"
              step="0.1"
              min={MIN_DNS_TIMEOUT_SECONDS}
              max={MAX_DNS_TIMEOUT_SECONDS}
              value={dnsTimeout}
              onChange={(event) =>
                patchConfig({ dns_timeout_seconds: clampDnsTimeout(event.target.value) })
              }
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">Seconds to wait per lookup.</p>
          </div>
          <div className="space-y-1.5">
            <FieldHeader name="dns_concurrency" type="integer" />
            <Input
              type="number"
              min={MIN_DNS_CONCURRENCY}
              max={MAX_DNS_CONCURRENCY}
              value={dnsConcurrency}
              onChange={(event) =>
                patchConfig({ dns_concurrency: clampDnsConcurrency(event.target.value) })
              }
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">Lookups at the same time.</p>
          </div>
        </div>
      ) : null}

      <CheckboxField
        id="collect-client-data-dry-run"
        label="dry_run"
        checked={dryRun}
        onCheckedChange={(checked) => patchConfig({ dry_run: checked })}
        description={
          <>
            Do not connect to devices or write to the database. Records the commands that would
            run under <span className="font-mono">dry_run_results</span>.
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
          Overrides each device&apos;s network driver. Supported: cisco_ios, cisco_xe, cisco_nxos.
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

export const CollectClientDataPlugin: PluginUIComponent = {
  ConfigPanel: CollectClientDataConfigPanel,
  HelpPanel: CollectClientDataHelpPanel,
};
