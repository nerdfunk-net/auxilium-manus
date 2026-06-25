"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { GitSourceSelectDialog } from "@/components/features/workflow-steps/get-git-devices/git-source-select-dialog";

const GIT_SOURCE_ID_KEY = "git_source_id";

function gitSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[GIT_SOURCE_ID_KEY];
  return typeof raw === "string" && raw.trim() ? raw.trim().toLowerCase() : "";
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
  const [sourceOpen, setSourceOpen] = useState(false);
  const sourceId = gitSourceIdFromConfig(config);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config[GIT_SOURCE_ID_KEY]) {
      onChange({ ...config, [GIT_SOURCE_ID_KEY]: "" });
    }
  }, [nodeId, config, onChange]);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [GIT_SOURCE_ID_KEY]: newSourceId });
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
        <p className="text-[11px] text-muted-foreground">{description}</p>
      </div>

      <GitSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}
