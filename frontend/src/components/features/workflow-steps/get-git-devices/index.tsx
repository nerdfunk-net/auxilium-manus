"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useGetGitDevicesPreviewMutation } from "@/hooks/queries/use-get-git-devices-preview-mutation";
import type { GitDevicePreview } from "@/hooks/queries/use-get-git-devices-preview-mutation";

import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";
import { DeviceMappingDialog } from "./device-mapping-dialog";
import { GitDevicesPreviewDialog } from "./preview-dialog";
import { mappingFromConfig, type DeviceMappingRule } from "./utils/device-mapping";
import { GetGitDevicesHelpPanel } from "./help-panel";

const GIT_REPOSITORY_ID_KEY = "git_repository_id";
const FILENAME_PATTERN_KEY = "filename_pattern";
const DIRECTORY_KEY = "directory";
const DEVICE_MAPPING_KEY = "device_mapping";

const EMPTY_KEYS: string[] = [];

function gitRepositoryIdFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[GIT_REPOSITORY_ID_KEY];
  return typeof raw === "number" ? raw : null;
}

function filenamePatternFromConfig(config: Record<string, unknown>): string {
  const raw = config[FILENAME_PATTERN_KEY];
  return typeof raw === "string" ? raw : "*.yaml";
}

function directoryFromConfig(config: Record<string, unknown>): string {
  const raw = config[DIRECTORY_KEY];
  return typeof raw === "string" ? raw : "";
}

function GitDevicesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const repositoryId = useMemo(() => gitRepositoryIdFromConfig(config), [config]);
  const filenamePattern = useMemo(
    () => filenamePatternFromConfig(config),
    [config],
  );
  const directory = useMemo(() => directoryFromConfig(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const mapping = useMemo(() => mappingFromConfig(config), [config]);

  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDevices, setPreviewDevices] = useState<GitDevicePreview[]>([]);
  const [availableKeys, setAvailableKeys] = useState<string[]>(EMPTY_KEYS);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>(EMPTY_KEYS);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetGitDevicesPreviewMutation();

  const handleRepositoryIdChange = useCallback(
    (newRepositoryId: number) => {
      onChange({ ...config, [GIT_REPOSITORY_ID_KEY]: newRepositoryId });
    },
    [config, onChange],
  );

  const handlePatternChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [FILENAME_PATTERN_KEY]: e.target.value });
    },
    [config, onChange],
  );

  const handleDirectoryChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [DIRECTORY_KEY]: e.target.value });
    },
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange({ ...config, fan_out: { ...fanOut, ...patch } });
    },
    [config, fanOut, onChange],
  );

  const loadPreview = useCallback(async () => {
    if (repositoryId === null) {
      return null;
    }
    try {
      const result = await runPreview({
        git_repository_id: repositoryId,
        filename_pattern: filenamePattern,
        directory,
        device_mapping: mapping,
      });
      setAvailableKeys(result.available_keys);
      setPreviewWarnings(result.warnings);
      return result;
    } catch {
      // error state is surfaced via previewIsError / previewError below
      return null;
    }
  }, [runPreview, repositoryId, filenamePattern, directory, mapping]);

  const handleShowPreview = useCallback(async () => {
    const result = await loadPreview();
    if (result) {
      setPreviewDevices(result.devices);
      setPreviewOpen(true);
    }
  }, [loadPreview]);

  const handleLoadKeys = useCallback(() => {
    void loadPreview();
  }, [loadPreview]);

  const handleMappingSave = useCallback(
    (rules: DeviceMappingRule[]) => {
      onChange({ ...config, [DEVICE_MAPPING_KEY]: rules });
      setMappingOpen(false);
    },
    [config, onChange],
  );

  const handleMappingClose = useCallback(() => setMappingOpen(false), []);

  const isConfigured = repositoryId !== null && Boolean(filenamePattern.trim());

  return (
    <div className="flex flex-col gap-4">
      {/* git_repository_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {GIT_REPOSITORY_ID_KEY}
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            git
          </Badge>
        </div>

        <GitRepositoryValue repositoryId={repositoryId} />

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setRepositoryOpen(true)}
        >
          {repositoryId !== null ? "Edit Repository" : "Configure Repository"}
        </Button>
      </div>

      {/* filename_pattern */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Label
            className="font-mono text-xs font-medium"
            htmlFor="git-filename-pattern"
          >
            {FILENAME_PATTERN_KEY}
          </Label>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            glob
          </Badge>
        </div>
        <Input
          id="git-filename-pattern"
          className="h-7 font-mono text-xs"
          placeholder="*.yaml"
          value={filenamePattern}
          onChange={handlePatternChange}
        />
        <p className="text-[11px] text-muted-foreground">
          Glob pattern relative to the repository root (or configured
          directory below).
        </p>
      </div>

      {/* directory */}
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="git-devices-directory">
          {DIRECTORY_KEY}
        </Label>
        <Input
          id="git-devices-directory"
          className="h-7 font-mono text-xs"
          placeholder="inventory/"
          value={directory}
          onChange={handleDirectoryChange}
        />
        <p className="text-[11px] text-muted-foreground">
          Directory inside the repository to search (blank = repo root).
        </p>
      </div>

      {/* device_mapping */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {DEVICE_MAPPING_KEY}
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            optional
          </Badge>
        </div>
        <p className="text-[11px] text-muted-foreground">
          {mapping.length > 0
            ? `${mapping.length} mapping${mapping.length === 1 ? "" : "s"} configured.`
            : "Default: name, primary_ip4, network_driver."}
        </p>
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setMappingOpen(true)}
        >
          Configure Mapping
        </Button>
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
          {previewError instanceof Error
            ? previewError.message
            : "Unknown error"}
        </p>
      )}

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      {/* Dialogs */}
      <GitRepositorySelectDialog
        open={repositoryOpen}
        selectedRepositoryId={repositoryId}
        onClose={() => setRepositoryOpen(false)}
        onSave={handleRepositoryIdChange}
      />

      <DeviceMappingDialog
        open={mappingOpen}
        rules={mapping}
        availableKeys={availableKeys}
        loadingKeys={previewPending}
        canLoadKeys={isConfigured}
        onLoadKeys={handleLoadKeys}
        onClose={handleMappingClose}
        onSave={handleMappingSave}
      />

      <GitDevicesPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        devices={previewDevices}
        warnings={previewWarnings}
        repositoryId={repositoryId}
      />
    </div>
  );
}

export const GetGitDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GitDevicesConfigPanel,
  HelpPanel: GetGitDevicesHelpPanel,
};
