"use client";

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
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitSourceSelectDialog } from "@/components/features/workflow-steps/get-git-devices/git-source-select-dialog";

import { ReadConfigHelpPanel } from "./help-panel";

const SOURCE_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Read from the default export directory (Settings → General).",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Read from a git source configured under Settings → Sources.",
  },
] as const;

type Source = (typeof SOURCE_OPTIONS)[number]["value"];

const PATH_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
];

function buildReadConfigConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    source: config.source === "git" ? "git" : "filesystem",
    git_source_id:
      typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "",
    path_template: typeof config.path_template === "string" ? config.path_template : "{device.name}.cfg",
    overwrite_existing: config.overwrite_existing === true,
    ...patch,
  };
}

function ReadConfigConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const [gitSourceOpen, setGitSourceOpen] = useState(false);

  const source = (config.source as Source) || "filesystem";
  const isGitSource = source === "git";
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";
  const pathTemplate =
    typeof config.path_template === "string" ? config.path_template : "{device.name}.cfg";
  const overwriteExisting = config.overwrite_existing === true;

  const sourceHint = useMemo(
    () => SOURCE_OPTIONS.find((option) => option.value === source)?.hint,
    [source],
  );

  const handleSourceChange = useCallback(
    (value: string) => {
      onChange(buildReadConfigConfig(config, { source: value }));
    },
    [config, onChange],
  );

  const handleGitSourceIdChange = useCallback(
    (value: string) => {
      onChange(buildReadConfigConfig(config, { git_source_id: value }));
    },
    [config, onChange],
  );

  const handlePathTemplateChange = useCallback(
    (value: string) => {
      onChange(buildReadConfigConfig(config, { path_template: value }));
    },
    [config, onChange],
  );

  const handleOverwriteExistingChange = useCallback(
    (checked: boolean) => {
      onChange(buildReadConfigConfig(config, { overwrite_existing: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={source} onValueChange={handleSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {sourceHint ? <p className="text-[11px] text-muted-foreground">{sourceHint}</p> : null}
      </div>

      {isGitSource ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">git_source_id</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              git
            </Badge>
          </div>
          {gitSourceId ? (
            <p className="font-mono text-[11px] text-muted-foreground">{gitSourceId}</p>
          ) : (
            <p className="text-[11px] text-warning-foreground">Not configured</p>
          )}
          <Button
            className="h-7 w-full text-xs"
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setGitSourceOpen(true)}
          >
            {gitSourceId ? "Change repository" : "Choose repository"}
          </Button>
          <p className="text-[11px] text-muted-foreground">
            Uses the same git sources as Get from Git / Store Artifact (Settings → Sources).
          </p>

          <GitSourceSelectDialog
            open={gitSourceOpen}
            selectedSourceId={gitSourceId}
            onClose={() => setGitSourceOpen(false)}
            onSave={handleGitSourceIdChange}
          />
        </div>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">path_template</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={pathTemplate}
          onChange={(event) => handlePathTemplateChange(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Placeholders: {PATH_PLACEHOLDERS.join(", ")}. Supports subdirectories, e.g.{" "}
          <span className="font-mono">{"{nautobot.location.name}/{device.name}.cfg"}</span>.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id="overwrite-existing"
          type="checkbox"
          checked={overwriteExisting}
          onChange={(event) => handleOverwriteExistingChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="overwrite-existing" className="font-mono text-xs font-medium">
            overwrite_existing
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When off (default), a device that already has a running config in this run is left
            unchanged and nothing is read for it. Turn on to always replace it with the file
            content.
          </p>
        </div>
      </div>
    </div>
  );
}

export const ReadConfigPlugin: PluginUIComponent = {
  ConfigPanel: ReadConfigConfigPanel,
  HelpPanel: ReadConfigHelpPanel,
};
