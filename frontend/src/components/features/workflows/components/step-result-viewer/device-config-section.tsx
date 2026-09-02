"use client";

import { useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DeviceContext } from "@/lib/workflow-context-types";

import { ContentViewer } from "./content-viewer";
import { DeviceConfigsContent } from "./device-configs-content";
import type { GenieParsedConfigEntry } from "./types";

/**
 * Detail-dialog "Device configs" section. Shows raw running/startup config and,
 * when a parse step (parse-cisco-config / get-pyats-config) also ran, exposes the
 * Genie-parsed structure behind a Raw / Parsed tab switch.
 */
export function DeviceConfigSection({
  device,
  runId,
  genieConfigEntries,
}: {
  device: DeviceContext;
  runId: number | null;
  genieConfigEntries: Array<{ key: string; entry: GenieParsedConfigEntry }>;
}) {
  const hasRaw = Boolean(device.running_config_ref || device.startup_config_ref);
  const hasParsed = genieConfigEntries.length > 0;
  const [tab, setTab] = useState("raw");

  const parsedPanels = (
    <div className="space-y-4">
      {genieConfigEntries.map(({ key, entry }) => (
        <div key={key} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">output_key: {key}</p>
          {"running" in entry ? (
            <ContentViewer
              label="Running config (parsed)"
              content={
                entry.running != null ? JSON.stringify(entry.running, null, 2) : "—"
              }
              downloadName={`${device.name}-running-parsed`}
              height="full"
            />
          ) : null}
          {"startup" in entry ? (
            <ContentViewer
              label="Startup config (parsed)"
              content={
                entry.startup != null ? JSON.stringify(entry.startup, null, 2) : "—"
              }
              downloadName={`${device.name}-startup-parsed`}
              height="full"
            />
          ) : null}
        </div>
      ))}
    </div>
  );

  if (!hasParsed) {
    return <DeviceConfigsContent runId={runId} device={device} expanded />;
  }

  if (!hasRaw) {
    return parsedPanels;
  }

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList className="h-8">
        <TabsTrigger value="raw" className="text-xs">
          Raw
        </TabsTrigger>
        <TabsTrigger value="parsed" className="text-xs">
          Parsed
        </TabsTrigger>
      </TabsList>
      <TabsContent value="raw" className="mt-3">
        <DeviceConfigsContent runId={runId} device={device} expanded />
      </TabsContent>
      <TabsContent value="parsed" className="mt-3">
        {parsedPanels}
      </TabsContent>
    </Tabs>
  );
}
