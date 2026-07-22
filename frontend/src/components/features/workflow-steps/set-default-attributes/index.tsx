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
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import {
  countConfiguredFields,
  modeFromConfig,
  overwriteFromConfig,
  parseAttributesConfig,
  parseGitConfig,
  resourceTypeFromConfig,
} from "./set-default-attributes-config";
import { GitSourceSelectDialog } from "./git-source-select-dialog";
import { SetDefaultAttributesDialog } from "./set-default-attributes-dialog";
import type { AttributesConfig, DefaultsMode, ResourceType } from "./types";
import { RESOURCE_TYPE_OPTIONS } from "./types";
import { SetDefaultAttributesHelpPanel } from "./help-panel";

function SetDefaultAttributesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const resourceType = useMemo(() => resourceTypeFromConfig(config), [config]);
  const mode = useMemo(() => modeFromConfig(config), [config]);
  const overwrite = useMemo(() => overwriteFromConfig(config), [config]);
  const attributes = useMemo(() => parseAttributesConfig(config), [config]);
  const git = useMemo(() => parseGitConfig(config), [config]);
  const configuredCount = useMemo(() => countConfiguredFields(attributes), [attributes]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);

  const handleTypeChange = useCallback(
    (value: string) => {
      onChange({ ...config, type: value as ResourceType });
    },
    [config, onChange],
  );

  const handleModeChange = useCallback(
    (value: string) => {
      onChange({ ...config, mode: value as DefaultsMode });
    },
    [config, onChange],
  );

  const handleOverwriteChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, overwrite: checked });
    },
    [config, onChange],
  );

  const handleAttributesSave = useCallback(
    (next: AttributesConfig) => {
      onChange({ ...config, attributes: next });
    },
    [config, onChange],
  );

  const handleGitSourceChange = useCallback(
    (git_source_id: string) => {
      onChange({ ...config, git: { ...git, git_source_id } });
    },
    [config, git, onChange],
  );

  const handleFilenamePatternChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, git: { ...git, filename_pattern: event.target.value } });
    },
    [config, git, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">type</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={resourceType} onValueChange={handleTypeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RESOURCE_TYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} disabled={!option.enabled}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={mode} onValueChange={handleModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="manual">Manual panel</SelectItem>
            <SelectItem value="git">Git repo (YAML)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center justify-between gap-2">
        <Label className="font-mono text-xs font-medium">overwrite</Label>
        <Switch checked={overwrite} onCheckedChange={handleOverwriteChange} />
      </div>
      <p className="-mt-2 text-[11px] text-muted-foreground">
        {overwrite
          ? "Defaults replace values the device already has."
          : "Defaults only fill in fields the device doesn't already have."}
      </p>

      {mode === "manual" ? (
        <div className="space-y-1.5 border-t pt-3">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">attributes</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              object
            </Badge>
          </div>
          {configuredCount > 0 ? (
            <p className="text-[11px] text-muted-foreground">
              {configuredCount} field{configuredCount === 1 ? "" : "s"} configured
            </p>
          ) : (
            <p className="text-[11px] text-amber-600">No default fields configured yet</p>
          )}
          <Button
            className="h-7 w-full text-xs"
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setDialogOpen(true)}
          >
            Edit Defaults
          </Button>
        </div>
      ) : (
        <div className="space-y-3 border-t pt-3">
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">git_source_id</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                git
              </Badge>
            </div>
            {git.git_source_id ? (
              <p className="font-mono text-[11px] text-muted-foreground">{git.git_source_id}</p>
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
              {git.git_source_id ? "Edit Source" : "Configure Source"}
            </Button>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <Label className="font-mono text-xs font-medium" htmlFor="set-default-attributes-filename-pattern">
                filename_pattern
              </Label>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                glob
              </Badge>
            </div>
            <Input
              id="set-default-attributes-filename-pattern"
              className="h-7 font-mono text-xs"
              placeholder="*.yaml"
              value={git.filename_pattern}
              onChange={handleFilenamePatternChange}
            />
            <p className="text-[11px] text-muted-foreground">
              The matched file must contain a top-level <span className="font-mono">devices</span>{" "}
              mapping of default values.
            </p>
          </div>
        </div>
      )}

      <SetDefaultAttributesDialog
        open={dialogOpen}
        value={config}
        onClose={() => setDialogOpen(false)}
        onChange={handleAttributesSave}
      />

      <GitSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={git.git_source_id}
        onClose={() => setSourceOpen(false)}
        onSave={handleGitSourceChange}
      />
    </div>
  );
}

export const SetDefaultAttributesPlugin: PluginUIComponent = {
  ConfigPanel: SetDefaultAttributesConfigPanel,
  HelpPanel: SetDefaultAttributesHelpPanel,
};
