"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";

const GIT_REPOSITORY_ID_KEY = "git_repository_id";
const ALLOW_STALE_KEY = "allow_stale_repository";

function gitRepositoryIdFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[GIT_REPOSITORY_ID_KEY];
  return typeof raw === "number" ? raw : null;
}

interface GitSourceConfigPanelProps extends PluginConfigPanelProps {
  description: string;
  /** Show the "allow stale repository" switch (read steps that work on a pulled copy). */
  showAllowStaleToggle?: boolean;
}

export function GitSourceConfigPanel({
  config,
  onChange,
  nodeId,
  description,
  showAllowStaleToggle = false,
}: GitSourceConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const repositoryId = gitRepositoryIdFromConfig(config);
  const allowStale = config[ALLOW_STALE_KEY] === true;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    const patch: Record<string, unknown> = {};
    if (config[GIT_REPOSITORY_ID_KEY] === undefined) {
      patch[GIT_REPOSITORY_ID_KEY] = null;
    }
    if (showAllowStaleToggle && config[ALLOW_STALE_KEY] === undefined) {
      patch[ALLOW_STALE_KEY] = false;
    }
    if (Object.keys(patch).length > 0) {
      onChange({ ...config, ...patch });
    }
  }, [nodeId, config, onChange, showAllowStaleToggle]);

  const handleRepositoryIdChange = useCallback(
    (newRepositoryId: number) => {
      onChange({ ...config, [GIT_REPOSITORY_ID_KEY]: newRepositoryId });
    },
    [config, onChange],
  );

  const handleAllowStaleChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [ALLOW_STALE_KEY]: checked });
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

      {showAllowStaleToggle ? (
        <div className="flex items-start gap-2">
          <Checkbox
            id={`${nodeId}-allow-stale`}
            checked={allowStale}
            onCheckedChange={(checked) => handleAllowStaleChange(checked === true)}
            className="mt-0.5"
          />
          <div className="space-y-0.5">
            <Label htmlFor={`${nodeId}-allow-stale`} className="font-mono text-xs font-medium">
              {ALLOW_STALE_KEY}
            </Label>
            <p className="text-[11px] text-muted-foreground">
              When the repository cannot be refreshed (expired token, conflict, offline), read the
              last local copy instead of failing the step. Off by default.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
