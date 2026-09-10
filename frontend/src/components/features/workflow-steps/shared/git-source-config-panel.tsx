"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";

const GIT_REPOSITORY_ID_KEY = "git_repository_id";
const USE_CR_BRANCH_KEY = "use_change_request_branch";

function gitRepositoryIdFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[GIT_REPOSITORY_ID_KEY];
  return typeof raw === "number" ? raw : null;
}

interface GitSourceConfigPanelProps extends PluginConfigPanelProps {
  description: string;
  /** Show the CI/CD-pipeline "use change-request branch" toggle (git-clone / git-pull). */
  showChangeRequestBranchToggle?: boolean;
}

export function GitSourceConfigPanel({
  config,
  onChange,
  nodeId,
  description,
  showChangeRequestBranchToggle = false,
}: GitSourceConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const repositoryId = gitRepositoryIdFromConfig(config);
  const useChangeRequestBranch = config[USE_CR_BRANCH_KEY] === true;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    const patch: Record<string, unknown> = {};
    if (config[GIT_REPOSITORY_ID_KEY] === undefined) {
      patch[GIT_REPOSITORY_ID_KEY] = null;
    }
    if (showChangeRequestBranchToggle && config[USE_CR_BRANCH_KEY] === undefined) {
      patch[USE_CR_BRANCH_KEY] = false;
    }
    if (Object.keys(patch).length > 0) {
      onChange({ ...config, ...patch });
    }
  }, [nodeId, config, onChange, showChangeRequestBranchToggle]);

  const handleRepositoryIdChange = useCallback(
    (newRepositoryId: number) => {
      onChange({ ...config, [GIT_REPOSITORY_ID_KEY]: newRepositoryId });
    },
    [config, onChange],
  );

  const handleUseChangeRequestBranchChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [USE_CR_BRANCH_KEY]: checked });
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
        <p className="text-[11px] text-muted-foreground">{description}</p>
      </div>

      <GitRepositorySelectDialog
        open={repositoryOpen}
        selectedRepositoryId={repositoryId}
        onClose={() => setRepositoryOpen(false)}
        onSave={handleRepositoryIdChange}
      />

      {showChangeRequestBranchToggle ? (
        <div className="flex items-start gap-2">
          <input
            id={`${nodeId}-use-cr-branch`}
            type="checkbox"
            checked={useChangeRequestBranch}
            onChange={(event) => handleUseChangeRequestBranchChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label
              htmlFor={`${nodeId}-use-cr-branch`}
              className="font-mono text-xs font-medium"
            >
              {USE_CR_BRANCH_KEY}
            </Label>
            <p className="text-[11px] text-muted-foreground">
              CI/CD pipeline: when this run deploys an approved change request, use that
              change request&apos;s <span className="font-mono">manus/cr-*</span> branch
              instead of the repository&apos;s default branch. No effect on ordinary runs.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
