"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  CSV_DELIMITER_KEY,
  CSV_DELIMITERS,
  CSV_MULTILINE_KEY,
  DEFAULT_PATTERN,
  delimiterFromConfig,
  FILE_FORMAT_KEY,
  fileFormatFromConfig,
  multilineFromConfig,
  patternForFormat,
  type FileFormat,
} from "./utils/file-options";
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
  return typeof raw === "string" ? raw : DEFAULT_PATTERN[fileFormatFromConfig(config)];
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
  const fileFormat = useMemo(() => fileFormatFromConfig(config), [config]);
  const csvDelimiter = useMemo(() => delimiterFromConfig(config), [config]);
  const csvMultiline = useMemo(() => multilineFromConfig(config), [config]);
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

  const handleFileFormatChange = useCallback(
    (value: string) => {
      const next: FileFormat = value === "csv" ? "csv" : "yaml";
      onChange({
        ...config,
        [FILE_FORMAT_KEY]: next,
        [FILENAME_PATTERN_KEY]: patternForFormat(filenamePattern, next),
      });
    },
    [config, filenamePattern, onChange],
  );

  const handleDelimiterChange = useCallback(
    (value: string) => {
      onChange({ ...config, [CSV_DELIMITER_KEY]: value });
    },
    [config, onChange],
  );

  const handleMultilineChange = useCallback(
    (checked: boolean | "indeterminate") => {
      onChange({ ...config, [CSV_MULTILINE_KEY]: checked === true });
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
        file_format: fileFormat,
        csv_delimiter: csvDelimiter,
        csv_multiline: csvMultiline,
      });
      setAvailableKeys(result.available_keys);
      setPreviewWarnings(result.warnings);
      return result;
    } catch {
      // error state is surfaced via previewIsError / previewError below
      return null;
    }
  }, [
    runPreview,
    repositoryId,
    filenamePattern,
    directory,
    mapping,
    fileFormat,
    csvDelimiter,
    csvMultiline,
  ]);

  const handleShowPreview = useCallback(async () => {
    const result = await loadPreview();
    if (result) {
      setPreviewDevices(result.devices);
      setPreviewOpen(true);
    }
  }, [loadPreview]);

  const handleLoadKeys = useCallback(async () => {
    const result = await loadPreview();
    return result ? result.available_keys : null;
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

      {/* file_format (+ CSV options) */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="git-file-format">
            {FILE_FORMAT_KEY}
          </Label>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            file type
          </Badge>
        </div>
        <Select value={fileFormat} onValueChange={handleFileFormatChange}>
          <SelectTrigger className="h-7 text-xs" id="git-file-format">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="yaml">YAML</SelectItem>
            <SelectItem value="csv">CSV</SelectItem>
          </SelectContent>
        </Select>

        {fileFormat === "csv" && (
          <div className="space-y-2 pt-1">
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground" htmlFor="git-csv-delimiter">
                Delimiter
              </Label>
              <Select value={csvDelimiter} onValueChange={handleDelimiterChange}>
                <SelectTrigger className="h-7 text-xs" id="git-csv-delimiter">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CSV_DELIMITERS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-start gap-2">
              <Checkbox
                checked={csvMultiline}
                className="mt-0.5"
                id="git-csv-multiline"
                onCheckedChange={handleMultilineChange}
              />
              <div className="space-y-0.5">
                <Label className="text-xs font-medium" htmlFor="git-csv-multiline">
                  Multiple lines per device
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  Lines with the same name are merged into one device; later
                  non-empty values overwrite earlier ones.
                </p>
              </div>
            </div>
          </div>
        )}
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
          placeholder={DEFAULT_PATTERN[fileFormat]}
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
        fileFormat={fileFormat}
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
