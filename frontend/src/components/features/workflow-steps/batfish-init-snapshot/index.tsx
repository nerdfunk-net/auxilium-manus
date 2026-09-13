"use client";

import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishSourceSelectDialog } from "../shared/batfish-source-select-dialog";
import {
  batfishSourceIdFromConfig,
  BATFISH_SOURCE_ID_KEY,
} from "../shared/batfish-source-config";
import { GitSourceConfigPanel } from "../shared/git-source-config-panel";
import { BatfishInitSnapshotHelpPanel } from "./help-panel";

const RETAIN_SNAPSHOTS_KEY = "retain_snapshots";
const NETWORK_NAME_KEY = "network_name";
const CONFIG_SOURCE_KEY = "config_source";
const BASE_PATH_KEY = "base_path";
const GLOB_PATTERN_KEY = "glob_pattern";

type ConfigSource = "live" | "git";

const CONFIG_SOURCE_OPTIONS = [
  {
    value: "live",
    label: "Live (this run's devices)",
    hint: "Uses this run's device running-configs. Must run after a Fan In if the workflow fans out.",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Reads already-collected configs from a Git repository. No devices required -- pair with a Start Batfish Run step upstream.",
  },
] as const;

function retainSnapshotsFromConfig(config: Record<string, unknown>): string {
  const raw = config[RETAIN_SNAPSHOTS_KEY];
  return typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw : "";
}

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function configSourceFromConfig(config: Record<string, unknown>): ConfigSource {
  return config[CONFIG_SOURCE_KEY] === "git" ? "git" : "live";
}

function BatfishInitSnapshotConfigPanel({
  config,
  onChange,
  nodeId,
  onPreview,
}: PluginConfigPanelProps) {
  const sourceId = batfishSourceIdFromConfig(config);
  const retainSnapshots = retainSnapshotsFromConfig(config);
  const networkName = stringFromConfig(config, NETWORK_NAME_KEY);
  const configSource = configSourceFromConfig(config);
  const isGitSource = configSource === "git";
  const basePath = stringFromConfig(config, BASE_PATH_KEY);
  const globPattern = stringFromConfig(config, GLOB_PATTERN_KEY);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [BATFISH_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleRetainSnapshotsChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      onChange({
        ...config,
        [RETAIN_SNAPSHOTS_KEY]: Number.isNaN(parsed) ? value : parsed,
      });
    },
    [config, onChange],
  );

  const handleConfigSourceChange = useCallback(
    (value: string) => {
      onChange({ ...config, [CONFIG_SOURCE_KEY]: value });
    },
    [config, onChange],
  );

  const handleFieldChange = useCallback(
    (key: string) => (value: string) => {
      onChange({ ...config, [key]: value });
    },
    [config, onChange],
  );

  const configSourceHint = CONFIG_SOURCE_OPTIONS.find(
    (option) => option.value === configSource,
  )?.hint;

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{CONFIG_SOURCE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={configSource} onValueChange={handleConfigSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONFIG_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {configSourceHint ? (
          <p className="text-[11px] leading-4 text-muted-foreground">{configSourceHint}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{BATFISH_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            batfish
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

      {isGitSource ? (
        <>
          <GitSourceConfigPanel
            config={config}
            onChange={onChange}
            nodeId={nodeId}
            onPreview={onPreview}
            description="Git repository to read device configs from (the same repository your config-backup job writes into)."
          />

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">{BASE_PATH_KEY}</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={basePath}
              onChange={(event) => handleFieldChange(BASE_PATH_KEY)(event.target.value)}
              placeholder="configs/running"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Directory inside the repository to search from. Blank searches the repo root.
            </p>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">{GLOB_PATTERN_KEY}</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={globPattern}
              onChange={(event) => handleFieldChange(GLOB_PATTERN_KEY)(event.target.value)}
              placeholder="**/*.running.cfg"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Glob matched under base_path -- supports ** for recursive directories, e.g.{" "}
              <span className="font-mono">**/*.running.cfg</span> (filename-suffix convention) or{" "}
              <span className="font-mono">configs/running/**/*.cfg</span> (directory convention).
              Batfish identifies each device from its own hostname line, not this pattern.
            </p>
          </div>
        </>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NETWORK_NAME_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkName}
          onChange={(event) => handleFieldChange(NETWORK_NAME_KEY)(event.target.value)}
          placeholder="manus-workflow-<workflow_id> (default)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Overrides the default network name with a stable one independent of
          workflow_id -- use for a production network refreshed on a schedule.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{RETAIN_SNAPSHOTS_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={0}
          value={retainSnapshots}
          onChange={(event) => handleRetainSnapshotsChange(event.target.value)}
          placeholder="5"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Snapshots for this network beyond the N most recent are deleted after each
          successful run.
        </p>
      </div>

      <BatfishSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const BatfishInitSnapshotPlugin: PluginUIComponent = {
  ConfigPanel: BatfishInitSnapshotConfigPanel,
  HelpPanel: BatfishInitSnapshotHelpPanel,
};
