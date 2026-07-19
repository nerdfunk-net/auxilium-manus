"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";
import { AddToIseHelpPanel } from "./help-panel";

const DEVICE_NAME_KEY = "device_name";
const DESCRIPTION_KEY = "description";
const IP_ADDRESS_KEY = "ip_address";
const NEW_KEY_KEY = "new_key";
const DEVICE_GROUPS_KEY = "device_groups";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function deviceGroupsFromConfig(config: Record<string, unknown>): string[] {
  const raw = config[DEVICE_GROUPS_KEY];
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => (typeof item === "string" ? item : ""));
}

function ExpressionHint({ example }: { example: string }) {
  return (
    <p className="text-[11px] leading-4 text-muted-foreground">
      Fixed value, or <span className="font-mono">{"{path.to.value}"}</span> such as{" "}
      <span className="font-mono">{example}</span>, optionally with a fallback:{" "}
      <span className="font-mono">{`${example.slice(0, -1)} | default('fallback')}`}</span>.
    </p>
  );
}

function AddToIseConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const deviceName = useMemo(() => stringFromConfig(config, DEVICE_NAME_KEY), [config]);
  const description = useMemo(() => stringFromConfig(config, DESCRIPTION_KEY), [config]);
  const ipAddress = useMemo(() => stringFromConfig(config, IP_ADDRESS_KEY), [config]);
  const newKey = useMemo(() => stringFromConfig(config, NEW_KEY_KEY), [config]);
  const deviceGroups = useMemo(() => deviceGroupsFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleDeviceNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [DEVICE_NAME_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleDescriptionChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [DESCRIPTION_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleIpAddressChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [IP_ADDRESS_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleNewKeyChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [NEW_KEY_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleGroupChange = useCallback(
    (index: number, value: string) => {
      const next = [...deviceGroups];
      next[index] = value;
      onChange({ ...config, [DEVICE_GROUPS_KEY]: next });
    },
    [config, deviceGroups, onChange],
  );

  const handleAddGroup = useCallback(() => {
    onChange({ ...config, [DEVICE_GROUPS_KEY]: [...deviceGroups, ""] });
  }, [config, deviceGroups, onChange]);

  const handleRemoveGroup = useCallback(
    (index: number) => {
      const next = deviceGroups.filter((_, itemIndex) => itemIndex !== index);
      onChange({ ...config, [DEVICE_GROUPS_KEY]: next });
    },
    [config, deviceGroups, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* ise_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ISE_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            ise
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-amber-600">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      {/* device_name */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{DEVICE_NAME_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="{name} or router1"
          value={deviceName}
          onChange={handleDeviceNameChange}
        />
        <ExpressionHint example="{name}" />
        {!deviceName && <p className="text-[11px] text-amber-600">Not configured</p>}
      </div>

      {/* description */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{DESCRIPTION_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="Optional description"
          value={description}
          onChange={handleDescriptionChange}
        />
      </div>

      {/* ip_address */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{IP_ADDRESS_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="{primary_ip4} or 10.0.0.1"
          value={ipAddress}
          onChange={handleIpAddressChange}
        />
        <ExpressionHint example="{primary_ip4}" />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Registered as a single host in ISE. A netmask suffix (e.g.{" "}
          <span className="font-mono">/24</span>) is stripped automatically — there is no
          separate netmask field.
        </p>
        {!ipAddress && <p className="text-[11px] text-amber-600">Not configured</p>}
      </div>

      {/* new_key */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{NEW_KEY_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="MySecretKey123 or {custom.new_tacacs_key}"
          type="password"
          value={newKey}
          onChange={handleNewKeyChange}
        />
        <ExpressionHint example="{custom.new_tacacs_key}" />
        {!newKey && <p className="text-[11px] text-amber-600">Not configured</p>}
      </div>

      {/* device_groups */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{DEVICE_GROUPS_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddGroup}
            title="Add group"
          >
            <Plus className="size-3.5" />
          </Button>
        </div>

        <div className="space-y-2">
          {deviceGroups.map((group, index) => (
            <div key={`group-${index}`} className="flex items-center gap-2">
              <Input
                value={group}
                onChange={(event) => handleGroupChange(index, event.target.value)}
                placeholder="Location#All Locations"
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemoveGroup(index)}
                title="Remove group"
              >
                <Minus className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-muted-foreground">
          Full hierarchical ISE group names. Leave empty for none.
        </p>
      </div>

      <ISESourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const AddToIsePlugin: PluginUIComponent = {
  ConfigPanel: AddToIseConfigPanel,
  HelpPanel: AddToIseHelpPanel,
};
