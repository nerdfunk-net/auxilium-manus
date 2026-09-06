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
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";

import {
  FORMAT_OPTIONS,
  SOURCE_OPTIONS,
  buildReadFromFileConfig,
  type ReadFromFileFormat,
  type ReadFromFileSource,
} from "./config";
import { ReadFromFileHelpPanel } from "./help-panel";

function ReadFromFileConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const [gitRepositoryOpen, setGitRepositoryOpen] = useState(false);

  const source = (config.source as ReadFromFileSource) || "filesystem";
  const isGitSource = source === "git";
  const gitRepositoryId =
    typeof config.git_repository_id === "number" ? config.git_repository_id : null;
  const path = typeof config.path === "string" ? config.path : "";
  const format: ReadFromFileFormat =
    config.format === "yaml" || config.format === "json" ? config.format : "auto";
  const destinationPath =
    typeof config.destination_path === "string" ? config.destination_path : "data";
  const overwrite = config.overwrite === true;

  const sourceHint = useMemo(
    () => SOURCE_OPTIONS.find((option) => option.value === source)?.hint,
    [source],
  );

  const patch = useCallback(
    (next: Record<string, unknown>) => onChange(buildReadFromFileConfig(config, next)),
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
        <Select value={source} onValueChange={(value) => patch({ source: value })}>
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
            <span className="font-mono text-xs font-medium">git_repository_id</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              git
            </Badge>
          </div>
          <GitRepositoryValue repositoryId={gitRepositoryId} />
          <Button
            className="h-7 w-full text-xs"
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setGitRepositoryOpen(true)}
          >
            {gitRepositoryId !== null ? "Change repository" : "Choose repository"}
          </Button>
          <p className="text-[11px] text-muted-foreground">
            Uses the same Git repositories as Get from Git / Store Artifact (Settings → Git
            Repositories).
          </p>

          <GitRepositorySelectDialog
            open={gitRepositoryOpen}
            selectedRepositoryId={gitRepositoryId}
            idPrefix="read-from-file-git-repository"
            onClose={() => setGitRepositoryOpen(false)}
            onSave={(value) => patch({ git_repository_id: value })}
          />
        </div>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={path}
          placeholder="data/site-defaults.yaml"
          onChange={(event) => patch({ path: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Relative path within the root. Subdirectories are allowed; the path must stay inside
          the root.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">format</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={format} onValueChange={(value) => patch({ format: value })}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FORMAT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          <span className="font-mono">auto</span> picks by file extension, then falls back to
          JSON then YAML. The YAML parser also reads JSON.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={destinationPath}
          placeholder="data"
          onChange={(event) => patch({ destination_path: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          <span className="font-mono">bag</span> or <span className="font-mono">bag.field</span>{" "}
          form, e.g. <span className="font-mono">data.site</span> → read later as{" "}
          <span className="font-mono">{"{{ data.site.region }}"}</span>. Cannot target{" "}
          <span className="font-mono">parsed</span> / <span className="font-mono">run_input</span>{" "}
          or a device scalar field.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id="read-from-file-overwrite"
          type="checkbox"
          checked={overwrite}
          onChange={(event) => patch({ overwrite: event.target.checked })}
          className="mt-0.5 size-4 rounded border accent-step"
        />
        <div className="space-y-0.5">
          <Label htmlFor="read-from-file-overwrite" className="font-mono text-xs font-medium">
            overwrite
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When off (default), keys already present at the destination are kept and only new
            keys are added. Turn on to let file values win on collisions. Nested objects always
            merge key-by-key; lists are replaced wholesale.
          </p>
        </div>
      </div>
    </div>
  );
}

export const ReadFromFilePlugin: PluginUIComponent = {
  ConfigPanel: ReadFromFileConfigPanel,
  HelpPanel: ReadFromFileHelpPanel,
};
