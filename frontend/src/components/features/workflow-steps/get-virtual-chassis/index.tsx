"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { GetVirtualChassisHelpPanel } from "./help-panel";
import { IntegerField } from "./integer-field";
import {
  DEFAULT_ATTRIBUTE_BAG,
  DEFAULT_INDEX_DEFAULT,
  DEFAULT_INDEX_KEY,
  DEFAULT_INDEX_OFFSET,
  DEFAULT_INDEX_REGEX,
  NAME_MATCH_OPTIONS,
  intFromConfig,
  nameMatchFromConfig,
  stringFromConfig,
  type NameMatchMode,
} from "./types";

interface FieldLabelProps {
  name: string;
  badge: string;
  optional?: boolean;
}

function FieldLabel({ name, badge, optional = true }: FieldLabelProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-medium">{name}</span>
      <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
        {badge}
      </Badge>
      {optional && (
        <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
          optional
        </Badge>
      )}
    </div>
  );
}

function GetVirtualChassisConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const [sourceOpen, setSourceOpen] = useState(false);

  const nameFilter = stringFromConfig(config, "name_filter", "");
  const nameMatch = nameMatchFromConfig(config);
  const splitMembers = config.split_members === true;
  const indexRegex = stringFromConfig(config, "index_regex", DEFAULT_INDEX_REGEX);
  const indexOffset = intFromConfig(config, "index_offset", DEFAULT_INDEX_OFFSET);
  const indexDefault = intFromConfig(config, "index_default", DEFAULT_INDEX_DEFAULT);
  const attributeBag = stringFromConfig(config, "attribute_bag", DEFAULT_ATTRIBUTE_BAG);
  const indexKey = stringFromConfig(config, "index_key", DEFAULT_INDEX_KEY);
  const isSourceConfigured = isNautobotSourceConfigured(config);

  const patch = useCallback(
    (update: Record<string, unknown>) => onChange({ ...config, ...update }),
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (update: Partial<FanOutConfig>) =>
      onChange({ ...config, fan_out: { ...fanOut, ...update } }),
    [config, fanOut, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <FieldLabel name={NAUTOBOT_SOURCE_ID_KEY} badge="nautobot" optional={false} />
        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
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
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="name_filter" badge="string" />
        <Input
          aria-label="Virtual chassis name filter"
          className="h-7 font-mono text-xs"
          placeholder="empty = all virtual chassis"
          value={nameFilter}
          onChange={(e) => patch({ name_filter: e.target.value })}
        />
        <Select
          value={nameMatch}
          onValueChange={(value) => patch({ name_match: value as NameMatchMode })}
        >
          <SelectTrigger aria-label="Name match mode" className="h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {NAME_MATCH_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          Leave empty to read every virtual chassis from Nautobot.
        </p>
      </div>

      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-medium">split_members</span>
          <Switch
            aria-label="Split stack into members"
            checked={splitMembers}
            onCheckedChange={(checked) => patch({ split_members: checked })}
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          {splitMembers
            ? "One device per stack member. Every member connects through the master's primary IPv4 and keeps its own name."
            : "One device per stack (the master's IP). Members are listed in the attribute bag."}
        </p>
      </div>

      <div className="space-y-2 border-t pt-3">
        <FieldLabel name="index_regex" badge="regex" />
        <Input
          aria-label="Stack number regular expression"
          className="h-7 font-mono text-xs"
          value={indexRegex}
          onChange={(e) => patch({ index_regex: e.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          Applied to each member name; the first capture group is the stack number.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">index_offset</Label>
            <IntegerField
              ariaLabel="Stack number offset"
              value={indexOffset}
              onCommit={(value) => patch({ index_offset: value })}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">index_default</Label>
            <IntegerField
              ariaLabel="Stack number default"
              value={indexDefault}
              onCommit={(value) => patch({ index_default: value })}
            />
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Offset is added to the captured number; the default is used when the name has no
          match (the master).
        </p>
      </div>

      <div className="space-y-2">
        <FieldLabel name="attribute_bag" badge="string" />
        <Input
          aria-label="Attribute bag name"
          className="h-7 font-mono text-xs"
          value={attributeBag}
          onChange={(e) => patch({ attribute_bag: e.target.value })}
        />
        <Label className="text-[11px] text-muted-foreground">index_key</Label>
        <Input
          aria-label="Stack number attribute key"
          className="h-7 font-mono text-xs"
          value={indexKey}
          onChange={(e) => patch({ index_key: e.target.value })}
        />
        <p className="text-[11px] text-muted-foreground">
          Read the number as{" "}
          <span className="font-mono">
            {`{${attributeBag || DEFAULT_ATTRIBUTE_BAG}.${indexKey || DEFAULT_INDEX_KEY}}`}
          </span>
          .
        </p>
      </div>

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={(newSourceId) => patch({ [NAUTOBOT_SOURCE_ID_KEY]: newSourceId })}
      />
    </div>
  );
}

export const GetVirtualChassisPlugin: PluginUIComponent = {
  ConfigPanel: GetVirtualChassisConfigPanel,
  HelpPanel: GetVirtualChassisHelpPanel,
};
