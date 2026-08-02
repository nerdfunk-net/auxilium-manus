"use client";

import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";
import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "@/components/features/workflow-steps/shared/fan-out-config";
import { useGetFromConfigPreviewMutation } from "@/hooks/queries/use-get-from-config-preview-mutation";
import type { GitContentSearchPreviewMatch } from "@/hooks/queries/use-get-from-config-preview-mutation";

import { GetFromConfigPreviewDialog } from "./preview-dialog";
import { GetFromConfigHelpPanel } from "./help-panel";

const GIT_SOURCE_ID_KEY = "git_source_id";
const DIRECTORY_KEY = "directory";
const FILE_FILTER_KEY = "file_filter";
const RECURSIVE_KEY = "recursive";
const INCLUDE_HISTORY_KEY = "include_history";
const SEARCH_TEXT_KEY = "search_text";
const CASE_SENSITIVE_KEY = "case_sensitive";

function gitSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[GIT_SOURCE_ID_KEY];
  return typeof raw === "string" && raw.trim() ? raw.trim().toLowerCase() : "";
}

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function boolFromConfig(config: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const raw = config[key];
  return typeof raw === "boolean" ? raw : fallback;
}

function GetFromConfigConfigPanel(props: PluginConfigPanelProps) {
  const { config, onChange } = props;

  const sourceId = useMemo(() => gitSourceIdFromConfig(config), [config]);
  const directory = useMemo(() => stringFromConfig(config, DIRECTORY_KEY), [config]);
  const fileFilter = useMemo(() => stringFromConfig(config, FILE_FILTER_KEY), [config]);
  const searchText = useMemo(() => stringFromConfig(config, SEARCH_TEXT_KEY), [config]);
  const recursive = useMemo(() => boolFromConfig(config, RECURSIVE_KEY, true), [config]);
  const includeHistory = useMemo(
    () => boolFromConfig(config, INCLUDE_HISTORY_KEY, false),
    [config],
  );
  const caseSensitive = useMemo(
    () => boolFromConfig(config, CASE_SENSITIVE_KEY, false),
    [config],
  );
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewMatches, setPreviewMatches] = useState<GitContentSearchPreviewMatch[]>([]);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetFromConfigPreviewMutation();

  const handleFieldChange = useCallback(
    (key: string, value: string) => {
      onChange({ ...config, [key]: value });
    },
    [config, onChange],
  );

  const handleToggleChange = useCallback(
    (key: string, value: boolean) => {
      onChange({ ...config, [key]: value });
    },
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange({ ...config, fan_out: { ...fanOut, ...patch } });
    },
    [config, fanOut, onChange],
  );

  const isConfigured = Boolean(sourceId) && Boolean(searchText.trim());

  const handleShowPreview = useCallback(async () => {
    try {
      const result = await runPreview({
        git_source_id: sourceId,
        directory,
        file_filter: fileFilter,
        recursive,
        include_history: includeHistory,
        search_text: searchText,
        case_sensitive: caseSensitive,
      });
      setPreviewMatches(result.matches);
      setPreviewOpen(true);
    } catch {
      // error state is surfaced via previewIsError / previewError below
    }
  }, [
    runPreview,
    sourceId,
    directory,
    fileFilter,
    recursive,
    includeHistory,
    searchText,
    caseSensitive,
  ]);

  return (
    <div className="flex flex-col gap-4">
      <GitSourceConfigPanel
        {...props}
        description="Git source to search for matching config files."
      />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-config-directory">
          {DIRECTORY_KEY}
        </Label>
        <Input
          id="get-from-config-directory"
          className="h-7 font-mono text-xs"
          placeholder="configs/"
          value={directory}
          onChange={(e) => handleFieldChange(DIRECTORY_KEY, e.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Directory inside the source to search (blank = repo root).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-config-file-filter">
          {FILE_FILTER_KEY}
        </Label>
        <Input
          id="get-from-config-file-filter"
          className="h-7 font-mono text-xs"
          placeholder="*.cfg"
          value={fileFilter}
          onChange={(e) => handleFieldChange(FILE_FILTER_KEY, e.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Glob pattern to restrict which files are searched (blank = all files).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="get-from-config-search-text">
          {SEARCH_TEXT_KEY}
        </Label>
        <Input
          id="get-from-config-search-text"
          className="h-7 font-mono text-xs"
          placeholder="snmp-server community"
          value={searchText}
          onChange={(e) => handleFieldChange(SEARCH_TEXT_KEY, e.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">Text to search for inside files.</p>
      </div>

      <div className="flex items-center justify-between">
        <Label className="text-[11px] text-muted-foreground">Recursive</Label>
        <Switch
          checked={recursive}
          onCheckedChange={(checked) => handleToggleChange(RECURSIVE_KEY, checked)}
        />
      </div>

      <div className="flex items-center justify-between">
        <Label className="text-[11px] text-muted-foreground">Search history too</Label>
        <Switch
          checked={includeHistory}
          onCheckedChange={(checked) => handleToggleChange(INCLUDE_HISTORY_KEY, checked)}
        />
      </div>

      <div className="flex items-center justify-between">
        <Label className="text-[11px] text-muted-foreground">Case sensitive</Label>
        <Switch
          checked={caseSensitive}
          onCheckedChange={(checked) => handleToggleChange(CASE_SENSITIVE_KEY, checked)}
        />
      </div>

      <Button
        className="h-7 w-full text-xs"
        size="sm"
        type="button"
        variant="secondary"
        disabled={!isConfigured || previewPending}
        onClick={handleShowPreview}
      >
        {previewPending ? "Searching…" : "Show Preview"}
      </Button>

      {previewIsError && (
        <p className="text-[11px] text-destructive">
          Preview failed:{" "}
          {previewError instanceof Error ? previewError.message : "Unknown error"}
        </p>
      )}

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      <GetFromConfigPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        matches={previewMatches}
        sourceId={sourceId}
      />
    </div>
  );
}

export const GetFromConfigPlugin: PluginUIComponent = {
  ConfigPanel: GetFromConfigConfigPanel,
  HelpPanel: GetFromConfigHelpPanel,
};
