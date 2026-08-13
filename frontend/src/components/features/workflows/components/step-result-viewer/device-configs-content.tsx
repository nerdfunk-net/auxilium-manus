"use client";

import type { DeviceContext } from "@/lib/workflow-context-types";

import { ConfigArtifactPanel } from "./config-artifact-panel";

export function DeviceConfigsContent({
  runId,
  device,
}: {
  runId: number | null;
  device: DeviceContext;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Config content is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {device.running_config_ref ? (
        <ConfigArtifactPanel
          runId={runId}
          label="Running config"
          artifactRef={device.running_config_ref}
        />
      ) : null}
      {device.startup_config_ref ? (
        <ConfigArtifactPanel
          runId={runId}
          label="Startup config"
          artifactRef={device.startup_config_ref}
        />
      ) : null}
    </div>
  );
}
