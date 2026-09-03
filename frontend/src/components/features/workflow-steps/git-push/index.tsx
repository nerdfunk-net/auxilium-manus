"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";
import { GitPushHelpPanel } from "./help-panel";

const GIT_REPOSITORY_ID_KEY = "git_repository_id";
const COMMIT_MESSAGE_TEMPLATE_KEY = "commit_message_template";
const COMMIT_BEFORE_PUSH_KEY = "commit_before_push";

const COMMIT_MESSAGE_PLACEHOLDERS = ["{timestamp}", "{run.id}", "{workflow.id}"];

function gitRepositoryIdFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[GIT_REPOSITORY_ID_KEY];
  return typeof raw === "number" ? raw : null;
}

function buildGitPushConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    git_repository_id: gitRepositoryIdFromConfig(config),
    [COMMIT_BEFORE_PUSH_KEY]: config[COMMIT_BEFORE_PUSH_KEY] !== false,
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
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const repositoryId = gitRepositoryIdFromConfig(config);
  const commitBeforePush = config[COMMIT_BEFORE_PUSH_KEY] !== false;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (config[GIT_REPOSITORY_ID_KEY] === undefined || !config[COMMIT_MESSAGE_TEMPLATE_KEY]) {
      onChange(buildGitPushConfig(config));
    }
  }, [nodeId, config, onChange]);

  const handleRepositoryIdChange = useCallback(
    (newRepositoryId: number) => {
      onChange(buildGitPushConfig(config, { git_repository_id: newRepositoryId }));
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
      onChange(buildGitPushConfig(config, { [COMMIT_BEFORE_PUSH_KEY]: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{GIT_REPOSITORY_ID_KEY}</span>
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
          {repositoryId !== null ? "Change repository" : "Choose repository"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Uses the same Git repositories as get-git-devices (Settings → Git Repositories).
        </p>
      </div>

      <GitRepositorySelectDialog
        open={repositoryOpen}
        selectedRepositoryId={repositoryId}
        onClose={() => setRepositoryOpen(false)}
        onSave={handleRepositoryIdChange}
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
            {COMMIT_BEFORE_PUSH_KEY}
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
  HelpPanel: GitPushHelpPanel,
};
