"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { NotifyOnErrorHelpPanel } from "./help-panel";

const MESSAGE_KEY = "message";
const NOTIFY_LOCAL_KEY = "notify_local";
const NOTIFY_MATTERMOST_KEY = "notify_mattermost";
const TEAM_NAME_KEY = "team_name";
const CHANNEL_NAME_KEY = "channel_name";

const DEFAULT_MESSAGE =
  "Device {device.name} failed at {error.step_id} (node {error.node_id}): {error.message}";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function boolFromConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  const raw = config[key];
  return typeof raw === "boolean" ? raw : fallback;
}

function NotifyOnErrorConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const message = stringFromConfig(config, MESSAGE_KEY);
  const notifyLocal = boolFromConfig(config, NOTIFY_LOCAL_KEY, true);
  const notifyMattermost = boolFromConfig(config, NOTIFY_MATTERMOST_KEY, false);
  const sourceId = mattermostSourceIdFromConfig(config);
  const teamName = stringFromConfig(config, TEAM_NAME_KEY);
  const channelName = stringFromConfig(config, CHANNEL_NAME_KEY);

  const [sourceOpen, setSourceOpen] = useState(false);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!message.trim()) {
      onChange({ ...config, [MESSAGE_KEY]: DEFAULT_MESSAGE });
    }
  }, [nodeId, message, config, onChange]);

  const handleMessageChange = useCallback(
    (value: string) => onChange({ ...config, [MESSAGE_KEY]: value }),
    [config, onChange],
  );

  const handleNotifyLocalChange = useCallback(
    (checked: boolean) => onChange({ ...config, [NOTIFY_LOCAL_KEY]: checked }),
    [config, onChange],
  );

  const handleNotifyMattermostChange = useCallback(
    (checked: boolean) => onChange({ ...config, [NOTIFY_MATTERMOST_KEY]: checked }),
    [config, onChange],
  );

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => onChange({ ...config, [MATTERMOST_SOURCE_ID_KEY]: newSourceId }),
    [config, onChange],
  );

  const handleTeamNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) =>
      onChange({ ...config, [TEAM_NAME_KEY]: event.target.value }),
    [config, onChange],
  );

  const handleChannelNameChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) =>
      onChange({ ...config, [CHANNEL_NAME_KEY]: event.target.value }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">message</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Textarea
          value={message}
          onChange={(event) => handleMessageChange(event.target.value)}
          placeholder={DEFAULT_MESSAGE}
          className="min-h-20 font-mono text-xs focus-visible:ring-step/40"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Rendered once per accumulated error on each device (a device that failed
          at two different steps before reaching this node gets two rows). Use{" "}
          <span className="font-mono">{"{path.to.value}"}</span> for a device
          attribute, e.g. <span className="font-mono">device.name</span>, plus{" "}
          <span className="font-mono">error.step_id</span>,{" "}
          <span className="font-mono">error.node_id</span>,{" "}
          <span className="font-mono">error.code</span>,{" "}
          <span className="font-mono">error.message</span> for the specific error
          being reported. A path that doesn&apos;t resolve renders as an empty
          string. Severity is always <span className="font-mono">error</span>. This
          same rendered text is also used for the Mattermost post below, when
          enabled.
        </p>
      </div>

      <div className="space-y-2 border-t pt-3">
        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={notifyLocal}
            onCheckedChange={(checked) => handleNotifyLocalChange(checked === true)}
          />
          Notify locally
        </label>
        <p className="text-[11px] text-muted-foreground">
          Write a Notification row for each accumulated error (visible under
          Notifications).
        </p>
      </div>

      <div className="space-y-2 border-t pt-3">
        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={notifyMattermost}
            onCheckedChange={(checked) => handleNotifyMattermostChange(checked === true)}
          />
          Notify via Mattermost
        </label>
        <p className="text-[11px] text-muted-foreground">
          Post the same rendered message to Mattermost for each accumulated
          error. Best-effort — a failed post is logged but does not fail this
          step or block local notifications.
        </p>

        {notifyMattermost ? (
          <div className="space-y-2 pl-1">
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
              <span className="font-mono text-[11px] font-medium">{TEAM_NAME_KEY}</span>
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
              <span className="font-mono text-[11px] font-medium">{CHANNEL_NAME_KEY}</span>
              <Input
                className="h-8 font-mono text-xs"
                placeholder="alerts"
                value={channelName}
                onChange={handleChannelNameChange}
              />
              {!channelName && (
                <p className="text-[11px] text-warning-foreground">Not configured</p>
              )}
            </div>
          </div>
        ) : null}
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

export const NotifyOnErrorPlugin: PluginUIComponent = {
  ConfigPanel: NotifyOnErrorConfigPanel,
  HelpPanel: NotifyOnErrorHelpPanel,
};
