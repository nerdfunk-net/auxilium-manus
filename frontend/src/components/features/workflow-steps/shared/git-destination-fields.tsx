"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { COMMIT_MESSAGE_PLACEHOLDERS } from "./filename-placeholders";
import { GitRepositorySelectDialog } from "./git-repository-select-dialog";
import { GitRepositoryValue } from "./git-repository-value";

export interface GitDestinationValues {
  git_repository_id: number | null;
  repository_subdirectory: string;
  pull_before_write: boolean;
  commit_after_write: boolean;
  push_after_write: boolean;
  commit_message_template: string;
}

interface GitDestinationFieldsProps {
  values: GitDestinationValues;
  gitRepositoryOpen: boolean;
  onGitRepositoryOpenChange: (open: boolean) => void;
  onChange: (patch: Partial<GitDestinationValues>) => void;
  idPrefix: string;
}

export function GitDestinationFields({
  values,
  gitRepositoryOpen,
  onGitRepositoryOpenChange,
  onChange,
  idPrefix,
}: GitDestinationFieldsProps) {
  const gitRepositoryId = values.git_repository_id;
  const pullId = `${idPrefix}-pull-before-write`;
  const commitId = `${idPrefix}-commit-after-write`;
  const pushId = `${idPrefix}-push-after-write`;

  return (
    <>
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
          onClick={() => onGitRepositoryOpenChange(true)}
        >
          {gitRepositoryId !== null ? "Change repository" : "Choose repository"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Uses the same Git repositories as get-git-devices (Settings → Git Repositories).
        </p>
      </div>

      <GitRepositorySelectDialog
        open={gitRepositoryOpen}
        selectedRepositoryId={gitRepositoryId}
        onClose={() => onGitRepositoryOpenChange(false)}
        onSave={(value) => onChange({ git_repository_id: value })}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">repository_subdirectory</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={values.repository_subdirectory}
          onChange={(event) => onChange({ repository_subdirectory: event.target.value })}
          placeholder="network/backups"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Optional prefix inside the repository before the filename template path.
        </p>
      </div>

      <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Git sync options
        </p>
        <div className="flex items-start gap-2">
          <input
            id={pullId}
            type="checkbox"
            checked={values.pull_before_write}
            onChange={(event) => onChange({ pull_before_write: event.target.checked })}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor={pullId} className="font-mono text-xs font-medium">
              pull_before_write
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Pull latest changes once before writing. Fails the step if pull fails.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <input
            id={commitId}
            type="checkbox"
            checked={values.commit_after_write}
            onChange={(event) => onChange({ commit_after_write: event.target.checked })}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor={commitId} className="font-mono text-xs font-medium">
              commit_after_write
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Create one commit for all files written in this step.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <input
            id={pushId}
            type="checkbox"
            checked={values.push_after_write}
            onChange={(event) => onChange({ push_after_write: event.target.checked })}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor={pushId} className="font-mono text-xs font-medium">
              push_after_write
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Push after commit. Disable for batch workflows that use a separate push step.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">commit_message_template</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={values.commit_message_template}
          onChange={(event) => onChange({ commit_message_template: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Placeholders: {COMMIT_MESSAGE_PLACEHOLDERS.join(", ")}.
        </p>
      </div>
    </>
  );
}
