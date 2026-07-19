"use client";

import { HelpCircle } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import {
  useGetIseDevicesPreviewMutation,
  type IseDevicePreview,
} from "@/hooks/queries/use-get-ise-devices-preview-mutation";

import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { nautobotSourceIdFromConfig, NAUTOBOT_SOURCE_ID_KEY } from "../shared/nautobot-source-config";
import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import { IseDevicesHelpDialog } from "./help-dialog";
import { IseDevicesPreviewDialog } from "./preview-dialog";
import { ISESourceSelectDialog } from "../shared/ise-source-select-dialog";
import { iseSourceIdFromConfig, ISE_SOURCE_ID_KEY } from "../shared/ise-source-config";
import { GetIseDevicesHelpPanel } from "./help-panel";

type QueryMode = "name" | "cidr" | "group";

const QUERY_MODE_KEY = "query_mode";
const DEVICE_NAMES_KEY = "device_names";
const CIDR_KEY = "cidr";
const GROUP_NAME_KEY = "group_name";
const RESOLVE_TO_DEVICES_KEY = "resolve_to_devices";

function queryModeFromConfig(config: Record<string, unknown>): QueryMode {
  const raw = config[QUERY_MODE_KEY];
  return raw === "cidr" || raw === "group" ? raw : "name";
}

function deviceNamesFromConfig(config: Record<string, unknown>): string[] {
  const raw = config[DEVICE_NAMES_KEY];
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
}

/** Trims and drops blank lines — used when the names are actually consumed
 * (configured-check, preview/run payload), never for the textarea's own
 * controlled value, or a blank line typed by the user (e.g. right after
 * pressing Enter) gets stripped out from under the cursor immediately. */
function nonBlankDeviceNames(names: string[]): string[] {
  return names.map((name) => name.trim()).filter(Boolean);
}

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function GetIseDevicesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => iseSourceIdFromConfig(config), [config]);
  const queryMode = useMemo(() => queryModeFromConfig(config), [config]);
  const deviceNames = useMemo(() => deviceNamesFromConfig(config), [config]);
  const cidr = useMemo(() => stringFromConfig(config, CIDR_KEY), [config]);
  const groupName = useMemo(() => stringFromConfig(config, GROUP_NAME_KEY), [config]);
  const resolveToDevices = Boolean(config[RESOLVE_TO_DEVICES_KEY]);
  const nautobotSourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [nautobotSourceOpen, setNautobotSourceOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDevices, setPreviewDevices] = useState<IseDevicePreview[]>([]);
  const [previewTruncated, setPreviewTruncated] = useState(false);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetIseDevicesPreviewMutation();

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ISE_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleQueryModeChange = useCallback(
    (mode: QueryMode) => {
      onChange({ ...config, [QUERY_MODE_KEY]: mode });
    },
    [config, onChange],
  );

  const handleDeviceNamesChange = useCallback(
    (text: string) => {
      onChange({ ...config, [DEVICE_NAMES_KEY]: text.split("\n") });
    },
    [config, onChange],
  );

  const handleCidrChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [CIDR_KEY]: e.target.value });
    },
    [config, onChange],
  );

  const handleGroupNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [GROUP_NAME_KEY]: e.target.value });
    },
    [config, onChange],
  );

  const handleResolveToDevicesChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [RESOLVE_TO_DEVICES_KEY]: checked });
    },
    [config, onChange],
  );

  const handleNautobotSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange({ ...config, fan_out: { ...fanOut, ...patch } });
    },
    [config, fanOut, onChange],
  );

  const configuredDeviceNames = useMemo(
    () => nonBlankDeviceNames(deviceNames),
    [deviceNames],
  );

  const isConfigured =
    Boolean(sourceId) &&
    ((queryMode === "name" && configuredDeviceNames.length > 0) ||
      (queryMode === "cidr" && Boolean(cidr.trim())) ||
      (queryMode === "group" && Boolean(groupName.trim())));

  const handleShowPreview = useCallback(async () => {
    try {
      const result = await runPreview({
        source_id: sourceId,
        query_mode: queryMode,
        device_names: configuredDeviceNames,
        cidr,
        group_name: groupName,
      });
      setPreviewDevices(result.devices);
      setPreviewTruncated(result.truncated);
      setPreviewOpen(true);
    } catch {
      // error state is surfaced via previewIsError / previewError below
    }
  }, [runPreview, sourceId, queryMode, configuredDeviceNames, cidr, groupName]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button
          className="size-7"
          size="icon"
          type="button"
          variant="ghost"
          title="Help"
          aria-label="Help"
          onClick={() => setHelpOpen(true)}
        >
          <HelpCircle className="size-4 text-muted-foreground" aria-hidden />
        </Button>
      </div>

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

      {/* query_mode */}
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium">{QUERY_MODE_KEY}</Label>
        <Select value={queryMode} onValueChange={(v) => handleQueryModeChange(v as QueryMode)}>
          <SelectTrigger className="h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="name">Device name(s)</SelectItem>
            <SelectItem value="cidr">IP address / CIDR</SelectItem>
            <SelectItem value="group">Network device group</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {queryMode === "name" && (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium">{DEVICE_NAMES_KEY}</Label>
          <Textarea
            className="min-h-[70px] font-mono text-xs"
            placeholder={"router1\nrouter2"}
            value={deviceNames.join("\n")}
            onChange={(e) => handleDeviceNamesChange(e.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            One ISE device name per line.
          </p>
        </div>
      )}

      {queryMode === "cidr" && (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium">{CIDR_KEY}</Label>
          <Input
            className="h-7 font-mono text-xs"
            placeholder="10.10.10.0/24"
            value={cidr}
            onChange={handleCidrChange}
          />
          <p className="text-[11px] text-muted-foreground">
            A single IP (e.g. <code className="rounded bg-muted px-1">10.10.10.1</code>) or a
            CIDR prefix.
          </p>
        </div>
      )}

      {queryMode === "group" && (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium">{GROUP_NAME_KEY}</Label>
          <Input
            className="h-7 font-mono text-xs"
            placeholder="Location#All Locations#Building1"
            value={groupName}
            onChange={handleGroupNameChange}
          />
          <p className="text-[11px] text-muted-foreground">
            Full hierarchical ISE network device group (NDG) name.
          </p>
        </div>
      )}

      {/* resolve_to_devices */}
      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-medium">{RESOLVE_TO_DEVICES_KEY}</span>
          <Switch checked={resolveToDevices} onCheckedChange={handleResolveToDevicesChange} />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Expand entries with a netmask other than /32 (possible groups/subnets) into
          individual devices by matching Nautobot&apos;s Primary Prefix against the CIDR.
        </p>

        {resolveToDevices && (
          <div className="space-y-1.5 pl-1">
            {nautobotSourceId ? (
              <p className="font-mono text-[11px] text-muted-foreground">
                {nautobotSourceId}
              </p>
            ) : (
              <p className="text-[11px] text-amber-600">
                Nautobot source required for resolve_to_devices
              </p>
            )}
            <Button
              className="h-7 w-full text-xs"
              size="sm"
              type="button"
              variant="outline"
              onClick={() => setNautobotSourceOpen(true)}
            >
              {nautobotSourceId ? "Edit Nautobot Source" : "Configure Nautobot Source"}
            </Button>
          </div>
        )}
      </div>

      {/* Show Preview */}
      <Button
        className="h-7 w-full text-xs"
        size="sm"
        type="button"
        variant="secondary"
        disabled={!isConfigured || previewPending}
        onClick={handleShowPreview}
      >
        {previewPending ? "Loading…" : "Show Preview"}
      </Button>

      {previewIsError && (
        <p className="text-[11px] text-destructive">
          Preview failed:{" "}
          {previewError instanceof Error ? previewError.message : "Unknown error"}
        </p>
      )}

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      {/* Dialogs */}
      <ISESourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <IseDevicesPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        devices={previewDevices}
        truncated={previewTruncated}
        sourceId={sourceId}
      />

      <NautobotSourceSelectDialog
        open={nautobotSourceOpen}
        selectedSourceId={nautobotSourceId}
        onClose={() => setNautobotSourceOpen(false)}
        onSave={handleNautobotSourceIdChange}
      />

      <IseDevicesHelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}

export const GetIseDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GetIseDevicesConfigPanel,
  HelpPanel: GetIseDevicesHelpPanel,
};
