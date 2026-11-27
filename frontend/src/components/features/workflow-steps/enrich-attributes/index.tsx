"use client";

import { useCallback, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";

import {
  MATCH_MODE_OPTIONS,
  SOURCE_OPTIONS,
  buildEnrichAttributesConfig,
  type EnrichAttributesMatchMode,
  type EnrichAttributesSource,
} from "./config";
import { EnrichAttributesHelpPanel } from "./help-panel";
import { CheckboxField } from "../shared/checkbox-field";

interface FieldLabelProps {
  name: string;
  type?: string;
}

function FieldLabel({ name, type = "string" }: FieldLabelProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-medium">{name}</span>
      <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
        {type}
      </Badge>
    </div>
  );
}

function EnrichAttributesConfigPanel(props: PluginConfigPanelProps) {
  const { config, onChange, nodeId, workflowNodes, workflowEdges } = props;
  const [pickerOpen, setPickerOpen] = useState(false);

  const source = (config.source as EnrichAttributesSource) || "filesystem";
  const isGitSource = source === "git";
  const path = typeof config.path === "string" ? config.path : "";
  const delimiter = typeof config.delimiter === "string" ? config.delimiter : ";";
  const keyColumn = typeof config.key_column === "string" ? config.key_column : "";
  const devicePath =
    typeof config.device_attribute_path === "string" ? config.device_attribute_path : "";
  const matchMode: EnrichAttributesMatchMode =
    config.match_mode === "contains" ? "contains" : "match";
  const caseInsensitive = config.case_insensitive === true;
  const destinationPath =
    typeof config.destination_path === "string" ? config.destination_path : "data";
  const overwrite = config.overwrite === true;

  const sourceHint = useMemo(
    () => SOURCE_OPTIONS.find((option) => option.value === source)?.hint,
    [source],
  );
  const matchHint = useMemo(
    () => MATCH_MODE_OPTIONS.find((option) => option.value === matchMode)?.hint,
    [matchMode],
  );

  const patch = useCallback(
    (next: Record<string, unknown>) => onChange(buildEnrichAttributesConfig(config, next)),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <FieldLabel name="source" />
        <Select value={source} onValueChange={(value) => patch({ source: value })}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {sourceHint ? <p className="text-[11px] text-muted-foreground">{sourceHint}</p> : null}
      </div>

      {isGitSource ? (
        <GitSourceConfigPanel
          {...props}
          description="Uses the same Git repositories as Get from Git / Store Artifact (Settings → Git Repositories)."
          showRefreshToggle
          showAllowStaleToggle
        />
      ) : null}

      <div className="space-y-1.5">
        <FieldLabel name="path" />
        <Input
          value={path}
          placeholder="data/serials.csv"
          onChange={(event) => patch({ path: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Relative path of the CSV file within the root. The first row is the header.
        </p>
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="delimiter" />
        <Input
          value={delimiter}
          placeholder=";"
          onChange={(event) => patch({ delimiter: event.target.value })}
          className="h-8 w-24 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          One character (<span className="font-mono">;</span>, <span className="font-mono">,</span>)
          or <span className="font-mono">tab</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="key_column" />
        <Input
          value={keyColumn}
          placeholder="serial"
          onChange={(event) => patch({ key_column: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Header name of the CSV column that identifies the device.
        </p>
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="device_attribute_path" />
        <div className="flex items-center gap-1.5">
          <Input
            value={devicePath}
            placeholder="nautobot.serial"
            onChange={(event) => patch({ device_attribute_path: event.target.value })}
            className="h-8 font-mono text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPickerOpen(true)}
            title="Browse attributes"
            aria-label="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Device attribute compared with the key column. A device without a value here is left
          unchanged.
        </p>
        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={(selected) => patch({ device_attribute_path: selected })}
          nodeId={nodeId}
          workflowNodes={workflowNodes ?? []}
          workflowEdges={workflowEdges ?? []}
        />
      </div>

      <div className="space-y-1.5">
        <FieldLabel name="match_mode" />
        <Select value={matchMode} onValueChange={(value) => patch({ match_mode: value })}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MATCH_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {matchHint ? <p className="text-[11px] text-muted-foreground">{matchHint}</p> : null}
      </div>

      <CheckboxField
        id="enrich-attributes-case-insensitive"
        label="case_insensitive"
        checked={caseInsensitive}
        onCheckedChange={(checked) => patch({ case_insensitive: checked })}
        description="Compare the device value and the key ignoring upper/lower case."
      />

      <div className="space-y-1.5">
        <FieldLabel name="destination_path" />
        <Input
          value={destinationPath}
          placeholder="data"
          onChange={(event) => patch({ destination_path: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          <span className="font-mono">bag</span> or <span className="font-mono">bag.field</span>{" "}
          form. The other CSV columns are added below it, e.g.{" "}
          <span className="font-mono">inventory.data</span>. Cannot target{" "}
          <span className="font-mono">parsed</span> / <span className="font-mono">run_input</span>{" "}
          or a device scalar field.
        </p>
      </div>

      <CheckboxField
        id="enrich-attributes-overwrite"
        label="overwrite"
        checked={overwrite}
        onCheckedChange={(checked) => patch({ overwrite: checked })}
        description="When off (default), keys already present at the destination are kept and only new keys are added. Turn on to let file values win on collisions."
      />
    </div>
  );
}

export const EnrichAttributesPlugin: PluginUIComponent = {
  ConfigPanel: EnrichAttributesConfigPanel,
  HelpPanel: EnrichAttributesHelpPanel,
};
