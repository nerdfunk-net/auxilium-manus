"use client";

import { Minus, Plus, Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { AttributePathPicker } from "../shared/attribute-path-picker";
import { ExpressionField } from "../shared/expression-field";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";
import { AddToIseHelpPanel } from "./help-panel";
import { IseDeviceGroupPickerDialog } from "./ise-device-group-picker-dialog";

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

const DEVICE_NAME_KEY = "device_name";
const DESCRIPTION_KEY = "description";
const IP_ADDRESS_KEY = "ip_address";
const NETMASK_OVERRIDE_KEY = "netmask_override";
const NEW_KEY_KEY = "new_key";
const DEVICE_GROUPS_KEY = "device_groups";
const CREATE_MISSING_GROUPS_KEY = "create_missing_groups";
const SINGLE_CONNECT_MODE_KEY = "single_connect_mode";
const DEFAULT_SINGLE_CONNECT_MODE = "OFF";
const SINGLE_CONNECT_MODES = [
  { value: "OFF", label: "Off" },
  { value: "ON_LEGACY", label: "Legacy Cisco Device" },
  { value: "ON_DRAFT_COMPLIANT", label: "TACACS Draft Compliance Single Connect Support" },
] as const;

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

function AddToIseConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const deviceName = useMemo(() => stringFromConfig(config, DEVICE_NAME_KEY), [config]);
  const description = useMemo(() => stringFromConfig(config, DESCRIPTION_KEY), [config]);
  const ipAddress = useMemo(() => stringFromConfig(config, IP_ADDRESS_KEY), [config]);
  const netmaskOverride = useMemo(() => stringFromConfig(config, NETMASK_OVERRIDE_KEY), [config]);
  const newKey = useMemo(() => stringFromConfig(config, NEW_KEY_KEY), [config]);
  const deviceGroups = useMemo(() => deviceGroupsFromConfig(config), [config]);
  const createMissingGroups = config[CREATE_MISSING_GROUPS_KEY] === true;
  const singleConnectMode = useMemo(
    () => stringFromConfig(config, SINGLE_CONNECT_MODE_KEY) || DEFAULT_SINGLE_CONNECT_MODE,
    [config],
  );

  const [sourceOpen, setSourceOpen] = useState(false);
  const [groupPickerOpen, setGroupPickerOpen] = useState(false);
  // Index of the device_groups row the attribute browser is editing (null = closed).
  const [attributePickerRow, setAttributePickerRow] = useState<number | null>(null);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleDeviceNameChange = useCallback(
    (next: string) => {
      onChange({ ...config, [DEVICE_NAME_KEY]: next });
    },
    [config, onChange],
  );

  const handleDescriptionChange = useCallback(
    (next: string) => {
      onChange({ ...config, [DESCRIPTION_KEY]: next });
    },
    [config, onChange],
  );

  const handleIpAddressChange = useCallback(
    (next: string) => {
      onChange({ ...config, [IP_ADDRESS_KEY]: next });
    },
    [config, onChange],
  );

  const handleNetmaskOverrideChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [NETMASK_OVERRIDE_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleNewKeyChange = useCallback(
    (next: string) => {
      onChange({ ...config, [NEW_KEY_KEY]: next });
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

  const handleOpenGroupPicker = useCallback(() => setGroupPickerOpen(true), []);
  const handleCloseGroupPicker = useCallback(() => setGroupPickerOpen(false), []);

  // Fills a trailing empty row if there is one, otherwise appends a new row.
  const handlePickGroup = useCallback(
    (name: string) => {
      const lastIndex = deviceGroups.length - 1;
      const next =
        lastIndex >= 0 && deviceGroups[lastIndex].trim() === ""
          ? [...deviceGroups.slice(0, lastIndex), name]
          : [...deviceGroups, name];
      onChange({ ...config, [DEVICE_GROUPS_KEY]: next });
    },
    [config, deviceGroups, onChange],
  );

  const handleCloseAttributePicker = useCallback(() => setAttributePickerRow(null), []);

  const handleAttributePicked = useCallback(
    (path: string) => {
      if (attributePickerRow !== null) {
        handleGroupChange(attributePickerRow, `{${path}}`);
      }
      setAttributePickerRow(null);
    },
    [attributePickerRow, handleGroupChange],
  );

  const handleSingleConnectModeChange = useCallback(
    (next: string) => {
      onChange({ ...config, [SINGLE_CONNECT_MODE_KEY]: next });
    },
    [config, onChange],
  );

  const handleCreateMissingGroupsChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [CREATE_MISSING_GROUPS_KEY]: checked });
    },
    [config, onChange],
  );

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
          <p className="text-[11px] text-warning-foreground">Not configured</p>
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
      <ExpressionField
        configKey={DEVICE_NAME_KEY}
        value={deviceName}
        placeholder="{name} or router1"
        onValueChange={handleDeviceNameChange}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      >
        <ExpressionHint example="{name}" />
        {!deviceName && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </ExpressionField>

      {/* description */}
      <ExpressionField
        configKey={DESCRIPTION_KEY}
        value={description}
        placeholder="Optional description or {path.to.value}"
        onValueChange={handleDescriptionChange}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Fixed text, or <span className="font-mono">{"{path.to.value}"}</span>{" "}
          resolved per device. If it resolves to nothing, the device is created without a
          description.
        </p>
      </ExpressionField>

      {/* ip_address */}
      <ExpressionField
        configKey={IP_ADDRESS_KEY}
        value={ipAddress}
        placeholder="{primary_ip4} or 10.0.0.1"
        onValueChange={handleIpAddressChange}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      >
        <ExpressionHint example="{primary_ip4}" />
        <p className="text-[11px] leading-4 text-muted-foreground">
          A netmask suffix (e.g. <span className="font-mono">/24</span>) is sent to ISE as the
          mask; without one the mask is <span className="font-mono">/32</span>. Use{" "}
          <span className="font-mono">{NETMASK_OVERRIDE_KEY}</span> below to force a mask.
        </p>
        {!ipAddress && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </ExpressionField>

      {/* netmask_override */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{NETMASK_OVERRIDE_KEY}</span>
        <Input
          className="h-9 font-mono text-xs"
          placeholder="Optional, e.g. 32"
          inputMode="numeric"
          value={netmaskOverride}
          onChange={handleNetmaskOverrideChange}
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional prefix length (<span className="font-mono">32</span> or{" "}
          <span className="font-mono">/32</span>) that overrides the mask. Blank: use the mask
          from <span className="font-mono">{IP_ADDRESS_KEY}</span>, or{" "}
          <span className="font-mono">/32</span> if it has none.
        </p>
      </div>

      {/* new_key */}
      <ExpressionField
        configKey={NEW_KEY_KEY}
        value={newKey}
        placeholder="MySecretKey123 or {custom.new_tacacs_key}"
        onValueChange={handleNewKeyChange}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
        secret
      >
        <ExpressionHint example="{custom.new_tacacs_key}" />
        {!newKey && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </ExpressionField>

      {/* single_connect_mode */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{SINGLE_CONNECT_MODE_KEY}</span>
        <Select value={singleConnectMode} onValueChange={handleSingleConnectModeChange}>
          <SelectTrigger className="h-9 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SINGLE_CONNECT_MODES.map((mode) => (
              <SelectItem key={mode.value} value={mode.value}>
                {mode.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          ISE&apos;s &quot;Enable Single Connect Mode&quot; for TACACS+. Off leaves it unchecked.
        </p>
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
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={!sourceId}
              onClick={handleOpenGroupPicker}
              title={sourceId ? "Load groups from ISE" : "Configure an ISE source first"}
            >
              Get List
            </Button>
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
        </div>

        <div className="space-y-2">
          {deviceGroups.map((group, index) => (
            <div key={`group-${index}`} className="flex items-center gap-2">
              <Input
                value={group}
                onChange={(event) => handleGroupChange(index, event.target.value)}
                placeholder="Location#All Locations or {custom.group}"
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => setAttributePickerRow(index)}
                title="Browse attributes"
                aria-label={`Browse attributes for group ${index + 1}`}
              >
                <Search className="size-3.5" aria-hidden />
              </Button>
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
          Full hierarchical ISE group names, or <span className="font-mono">{"{path.to.value}"}</span>{" "}
          resolved per device. A path that does not exist fails the device; one that exists but is
          blank adds no group. Click Get List to pick from ISE. Leave empty for none.
        </p>

        <label className="flex items-start gap-1.5 pt-1 text-xs font-medium">
          <Checkbox
            className="mt-0.5"
            checked={createMissingGroups}
            onCheckedChange={(checked) => handleCreateMissingGroupsChange(checked === true)}
          />
          <span>
            Add group if it does not exist
            <span className="block text-[11px] font-normal leading-4 text-muted-foreground">
              Creates each missing group (and missing parents) in ISE before adding the device.
              If off, ISE rejects a device whose group does not exist and the device fails.
            </span>
          </span>
        </label>
      </div>

      <AttributePathPicker
        open={attributePickerRow !== null}
        onClose={handleCloseAttributePicker}
        onSelect={handleAttributePicked}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />

      <IseDeviceGroupPickerDialog
        open={groupPickerOpen}
        sourceId={sourceId}
        selectedGroups={deviceGroups}
        onClose={handleCloseGroupPicker}
        onSelect={handlePickGroup}
      />

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
