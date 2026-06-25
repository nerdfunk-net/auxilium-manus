"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GitSourceSelectDialog } from "@/components/features/workflow-steps/get-git-devices/git-source-select-dialog";

const GIT_SOURCE_ID_KEY = "git_source_id";
const COMMIT_MESSAGE_TEMPLATE_KEY = "commit_message_template";
const COMMIT_BEFORE_PUSH_KEY = "commit_before_push";

const COMMIT_MESSAGE_PLACEHOLDERS = ["{timestamp}", "{run.id}", "{workflow.id}"];

function gitSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[GIT_SOURCE_ID_KEY];
  return typeof raw === "string" && raw.trim() ? raw.trim().toLowerCase() : "";
}

function buildGitPushConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    git_source_id: gitSourceIdFromConfig(config),
    commit_before_push: config.commit_before_push !== false,
    commit_message_template:
      typeof config.commit_message_template === "string"
        ? config.commit_message_template
        : "commit {timestamp}",
    ...patch,
  };
}

function GitPushConfigPanel({
  config,
  onChange,
  nodeId,
}: {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  nodeId: string;
}) {
  const initializedForNode = useRef<string | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const sourceId = gitSourceIdFromConfig(config);
  const commitBeforePush = config.commit_before_push !== false;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config[GIT_SOURCE_ID_KEY] || !config[COMMIT_MESSAGE_TEMPLATE_KEY]) {
      onChange(buildGitPushConfig(config));
    }
  }, [nodeId, config, onChange]);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange(buildGitPushConfig(config, { git_source_id: newSourceId }));
    },
    [config, onChange],
  );

  const handleCommitMessageChange = useCallback(
    (value: string) => {
      onChange(buildGitPushConfig(config, { commit_message_template: value }));
    },
    [config, onChange],
  );

  const handleCommitBeforePushChange = useCallback(
    (checked: boolean) => {
      onChange(buildGitPushConfig(config, { commit_before_push: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{GIT_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            git
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
          {sourceId ? "Change repository" : "Choose repository"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Uses the same git sources as get-git-devices (Settings → Sources).
        </p>
      </div>

      <GitSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <div className="flex items-start gap-2">
        <input
          id="commit-before-push"
          type="checkbox"
          checked={commitBeforePush}
          onChange={(event) => handleCommitBeforePushChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="commit-before-push" className="font-mono text-xs font-medium">
            commit_before_push
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Stage and commit exported files from upstream store-artifact steps before pushing.
          </p>
        </div>
      </div>

      {commitBeforePush ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{COMMIT_MESSAGE_TEMPLATE_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={
              typeof config.commit_message_template === "string"
                ? config.commit_message_template
                : "commit {timestamp}"
            }
            onChange={(event) => handleCommitMessageChange(event.target.value)}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Placeholders: {COMMIT_MESSAGE_PLACEHOLDERS.join(", ")}.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export const GitPushPlugin: PluginUIComponent = {
  ConfigPanel: GitPushConfigPanel,
};
