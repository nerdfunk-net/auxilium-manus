"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import {
  DEFAULT_GET_FROM_USER_CONFIG,
  DEFAULT_GET_FROM_USER_DEVICE_PARAM,
} from "./config";
import { GetFromUserHelpPanel } from "./help-panel";

const DEVICE_PARAM_KEY = "device_param";
const LOOKUP_MODE_KEY = "lookup_mode";

const CONFIG_INPUT_CLASS = "h-8 font-mono text-xs focus-visible:ring-step/40";

type LookupMode = "manual" | "nautobot_search";

function deviceParamFromConfig(config: Record<string, unknown>): string {
  const raw = config[DEVICE_PARAM_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return DEFAULT_GET_FROM_USER_DEVICE_PARAM;
}

function lookupModeFromConfig(config: Record<string, unknown>): LookupMode {
  return config[LOOKUP_MODE_KEY] === "nautobot_search" ? "nautobot_search" : "manual";
}

function buildConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    ...DEFAULT_GET_FROM_USER_CONFIG,
    ...config,
    fan_out: fanOutFromConfig(config),
    ...patch,
  };
}

function GetFromUserConfigPanel({ nodeId, config, onChange }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;

    const raw = config[DEVICE_PARAM_KEY];
    const needsDefaults =
      typeof raw !== "string" || raw.trim().length === 0 || config.fan_out === undefined;
    if (needsDefaults) {
      onChange(buildConfig(config));
    }
  }, [nodeId, config, onChange]);

  const deviceParam = useMemo(() => deviceParamFromConfig(config), [config]);
  const lookupMode = useMemo(() => lookupModeFromConfig(config), [config]);
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const isSourceConfigured = isNautobotSourceConfigured(config);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleDeviceParamChange = useCallback(
    (name: string) => onChange(buildConfig(config, { [DEVICE_PARAM_KEY]: name })),
    [config, onChange],
  );

  const handleLookupModeChange = useCallback(
    (mode: LookupMode) => onChange(buildConfig(config, { [LOOKUP_MODE_KEY]: mode })),
    [config, onChange],
  );

  const handleSourceIdChange = useCallback(
    (newSourceId: string) =>
      onChange(buildConfig(config, { [NAUTOBOT_SOURCE_ID_KEY]: newSourceId })),
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange(buildConfig(config, { fan_out: { ...fanOut, ...patch } }));
    },
    [config, fanOut, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{DEVICE_PARAM_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            run parameter
          </Badge>
        </div>
        <Input
          className={CONFIG_INPUT_CLASS}
          placeholder={DEFAULT_GET_FROM_USER_DEVICE_PARAM}
          value={deviceParam}
          onChange={(e) => handleDeviceParamChange(e.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Run parameter prompted when the workflow starts. Defaults to{" "}
          <span className="font-mono">{DEFAULT_GET_FROM_USER_DEVICE_PARAM}</span> and is
          synced automatically — change it only if you need a different name.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{LOOKUP_MODE_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              ui hint
            </Badge>
          </div>
          <Tabs
            value={lookupMode}
            onValueChange={(v) => handleLookupModeChange(v as LookupMode)}
          >
            <TabsList className="h-7">
              <TabsTrigger className="h-5 px-2 text-[11px]" value="manual">
                Manual
              </TabsTrigger>
              <TabsTrigger className="h-5 px-2 text-[11px]" value="nautobot_search">
                Nautobot search
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {lookupMode === "nautobot_search" ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                nautobot
              </Badge>
            </div>
            {isSourceConfigured ? (
              <p className="truncate font-mono text-[11px] text-muted-foreground">{sourceId}</p>
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
              {isSourceConfigured ? "Edit Source" : "Configure Source"}
            </Button>
            <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
              The Run Inputs prompt suggests devices whose name contains what the operator
              types (3+ characters) against this source. Suggestions are a convenience
              only — the operator can still type a raw name or IP if Nautobot is
              unreachable or a device isn&apos;t found.
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
            The operator types devices directly — one name or IP address per line, no
            Nautobot lookup involved.
          </div>
        )}
      </div>

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const GetFromUserPlugin: PluginUIComponent = {
  ConfigPanel: GetFromUserConfigPanel,
  HelpPanel: GetFromUserHelpPanel,
};
