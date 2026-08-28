"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";

const GIT_REPOSITORY_ID_KEY = "git_repository_id";

function gitRepositoryIdFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[GIT_REPOSITORY_ID_KEY];
  return typeof raw === "number" ? raw : null;
}

interface GitSourceConfigPanelProps extends PluginConfigPanelProps {
  description: string;
}

export function GitSourceConfigPanel({
  config,
  onChange,
  nodeId,
  description,
}: GitSourceConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const repositoryId = gitRepositoryIdFromConfig(config);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (config[GIT_REPOSITORY_ID_KEY] === undefined) {
      onChange({ ...config, [GIT_REPOSITORY_ID_KEY]: null });
    }
  }, [nodeId, config, onChange]);

  const handleRepositoryIdChange = useCallback(
    (newRepositoryId: number) => {
      onChange({ ...config, [GIT_REPOSITORY_ID_KEY]: newRepositoryId });
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
        {repositoryId !== null ? (
          <p className="font-mono text-[11px] text-muted-foreground">{repositoryId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
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
    </div>
  );
}
