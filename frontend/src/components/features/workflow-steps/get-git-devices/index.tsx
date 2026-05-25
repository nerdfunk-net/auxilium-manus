"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useGetGitDevicesPreviewMutation } from "@/hooks/queries/use-get-git-devices-preview-mutation";
import type { GitDevicePreview } from "@/hooks/queries/use-get-git-devices-preview-mutation";

import { GitSourceSelectDialog } from "./git-source-select-dialog";
import { GitDevicesPreviewDialog } from "./preview-dialog";

const GIT_SOURCE_ID_KEY = "git_source_id";
const FILENAME_PATTERN_KEY = "filename_pattern";
const DEVICE_MAPPING_KEY = "device_mapping";

function gitSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[GIT_SOURCE_ID_KEY];
  return typeof raw === "string" && raw.trim() ? raw.trim().toLowerCase() : "";
}

function filenamePatternFromConfig(config: Record<string, unknown>): string {
  const raw = config[FILENAME_PATTERN_KEY];
  return typeof raw === "string" ? raw : "*.yaml";
}

function GitDevicesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => gitSourceIdFromConfig(config), [config]);
  const filenamePattern = useMemo(
    () => filenamePatternFromConfig(config),
    [config],
  );

  const [sourceOpen, setSourceOpen] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDevices, setPreviewDevices] = useState<GitDevicePreview[]>([]);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetGitDevicesPreviewMutation();

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [GIT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handlePatternChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [FILENAME_PATTERN_KEY]: e.target.value });
    },
    [config, onChange],
  );

  const handleShowPreview = useCallback(async () => {
    console.debug("[DEBUG] handleShowPreview — called, sourceId=%s pattern=%s", sourceId, filenamePattern);
    try {
      const result = await runPreview({
        git_source_id: sourceId,
        filename_pattern: filenamePattern,
      });
      console.debug("[DEBUG] handleShowPreview — runPreview resolved", result);
      setPreviewDevices(result.devices);
      setPreviewOpen(true);
    } catch (err) {
      console.debug("[DEBUG] handleShowPreview — runPreview threw", err);
      // error state is surfaced via previewIsError / previewError below
    }
  }, [runPreview, sourceId, filenamePattern]);

  const isConfigured = Boolean(sourceId) && Boolean(filenamePattern.trim());

  return (
    <div className="flex flex-col gap-4">
      {/* git_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {GIT_SOURCE_ID_KEY}
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            git
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
          </p>
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
          subdirectory).
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
          Custom field mapping for YAML keys.
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

      {/* Dialogs */}
      <GitSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <Dialog open={mappingOpen} onOpenChange={(isOpen) => !isOpen && setMappingOpen(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Device Mapping</DialogTitle>
            <DialogDescription>
              Device mapping configuration will be implemented in a future
              release. The default mapping reads{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">
                name
              </code>
              ,{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">
                primary_ip4
              </code>
              , and{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">
                network_driver
              </code>{" "}
              fields from each device entry in the YAML file.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => setMappingOpen(false)}
            >
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <GitDevicesPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        devices={previewDevices}
        sourceId={sourceId}
      />
    </div>
  );
}

export const GetGitDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GitDevicesConfigPanel,
};
