"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { MattermostSourceSelectDialog } from "../shared/mattermost-source-select-dialog";
import {
  MATTERMOST_SOURCE_ID_KEY,
  mattermostSourceIdFromConfig,
} from "../shared/mattermost-source-config";
import { NotifyMattermostHelpPanel } from "./help-panel";

const TEAM_NAME_KEY = "team_name";
const CHANNEL_NAME_KEY = "channel_name";
const MESSAGE_KEY = "message";

const DEFAULT_MESSAGE = "Workflow finished: {device_count} device(s) ({devices})";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function NotifyMattermostConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => mattermostSourceIdFromConfig(config), [config]);
  const teamName = useMemo(() => stringFromConfig(config, TEAM_NAME_KEY), [config]);
  const channelName = useMemo(() => stringFromConfig(config, CHANNEL_NAME_KEY), [config]);
  const message = useMemo(() => stringFromConfig(config, MESSAGE_KEY), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [MATTERMOST_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleTeamNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [TEAM_NAME_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleChannelNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [CHANNEL_NAME_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleMessageChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange({ ...config, [MESSAGE_KEY]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* mattermost_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{MATTERMOST_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            mattermost
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      {/* team_name */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{TEAM_NAME_KEY}</span>
        <Input
          className="h-8 font-mono text-xs"
          placeholder="networking"
          value={teamName}
          onChange={handleTeamNameChange}
        />
        {!teamName && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      {/* channel_name */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{CHANNEL_NAME_KEY}</span>
        <Input
          className="h-8 font-mono text-xs"
          placeholder="alerts"
          value={channelName}
          onChange={handleChannelNameChange}
        />
        {!channelName && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      {/* message */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{MESSAGE_KEY}</span>
        <Textarea
          className="min-h-20 font-mono text-xs focus-visible:ring-step/40"
          placeholder={DEFAULT_MESSAGE}
          value={message}
          onChange={handleMessageChange}
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">{"{path.to.value}"}</span> to
          interpolate the first device&apos;s resolved attribute, e.g.{" "}
          <span className="font-mono">device.name</span>. Use{" "}
          <span className="font-mono">{"{devices}"}</span> and{" "}
          <span className="font-mono">{"{device_count}"}</span> to summarize
          a multi-device run.
        </p>
        {!message && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      <MattermostSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const NotifyMattermostPlugin: PluginUIComponent = {
  ConfigPanel: NotifyMattermostConfigPanel,
  HelpPanel: NotifyMattermostHelpPanel,
};
