"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { ListContainsHelpPanel } from "./help-panel";

function parseString(config: Record<string, unknown>, key: string): string {
  return typeof config[key] === "string" ? (config[key] as string) : "";
}

function parseCaseSensitive(config: Record<string, unknown>): boolean {
  return config.case_sensitive === true;
}

function ListContainsConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const listPath = parseString(config, "list_path");
  const field = parseString(config, "field");
  const value = parseString(config, "value");
  const caseSensitive = parseCaseSensitive(config);

  const handleListPathChange = useCallback(
    (next: string) => onChange({ ...config, list_path: next }),
    [config, onChange],
  );
  const handleFieldChange = useCallback(
    (next: string) => onChange({ ...config, field: next }),
    [config, onChange],
  );
  const handleValueChange = useCallback(
    (next: string) => onChange({ ...config, value: next }),
    [config, onChange],
  );
  const handleCaseSensitiveChange = useCallback(
    (checked: boolean) => onChange({ ...config, case_sensitive: checked }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">list_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={listPath}
          onChange={(event) => handleListPathChange(event.target.value)}
          placeholder="parsed.cisco_config.access_lists[name=MGMT_100].entries"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Dot path to the list to search — supports{" "}
          <span className="font-mono">device.*</span>, bag paths (
          <span className="font-mono">nautobot.tags</span>), and{" "}
          <span className="font-mono">parsed.*</span> for a step&apos;s parsed
          output. Add <span className="font-mono">[field=value]</span> to a segment
          to filter down to one matching item first (e.g. one ACL by name) before
          continuing the path — see Help for a worked example.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">field</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            optional
          </Badge>
        </div>
        <Input
          value={field}
          onChange={(event) => handleFieldChange(event.target.value)}
          placeholder="source"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Field to read from each list item before comparing. Leave empty for a list
          of plain values (e.g. a VLAN id list).
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">value</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={value}
          onChange={(event) => handleValueChange(event.target.value)}
          placeholder="172.16.9.100"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The value to look for. Use a fixed value, or{" "}
          <span className="font-mono">{"{custom.field}"}</span> to resolve it per
          device, optionally with{" "}
          <span className="font-mono">{"{custom.field | default('x')}"}</span>.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id={`case-sensitive-${nodeId}`}
          type="checkbox"
          checked={caseSensitive}
          onChange={(event) => handleCaseSensitiveChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor={`case-sensitive-${nodeId}`} className="font-mono text-xs font-medium">
            case_sensitive
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When disabled, value comparison ignores letter case.
          </p>
        </div>
      </div>
    </div>
  );
}

export const ListContainsPlugin = {
  ConfigPanel: ListContainsConfigPanel,
  HelpPanel: ListContainsHelpPanel,
};
