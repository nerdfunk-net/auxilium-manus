"use client";

import { useCallback } from "react";

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
import { SecretManagerConnectionField } from "@/components/features/workflow-steps/shared/secret-manager-connection-field";

function stringField(config: Record<string, unknown>, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function SecretSetConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const setField = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const mode = stringField(config, "mode", "fixed") === "attribute" ? "attribute" : "fixed";
  const strictTemplates = config.strict_templates !== false;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Write an explicit secret value per device</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Writes a literal value, or one read from another attribute path, to a Secret Manager
          connection per device. Also seals the value into the device&apos;s attribute bag.
        </p>
      </div>

      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-path">
          path_template
        </Label>
        <Input
          id="secret-set-path"
          className="h-8 font-mono text-xs"
          placeholder="network/{device.name}/tacacs"
          value={stringField(config, "path_template", "network/{device.name}/tacacs")}
          onChange={(event) => setField("path_template", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-field">
          field
        </Label>
        <Input
          id="secret-set-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field", "key")}
          onChange={(event) => setField("field", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium">mode</Label>
        <Select value={mode} onValueChange={(value) => setField("mode", value)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">fixed — a literal value</SelectItem>
            <SelectItem value="attribute">attribute — read from another attribute path</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {mode === "fixed" ? (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="secret-set-fixed-value">
            fixed_value
          </Label>
          <Input
            id="secret-set-fixed-value"
            className="h-8 font-mono text-xs"
            type="password"
            autoComplete="new-password"
            value={stringField(config, "fixed_value")}
            onChange={(event) => setField("fixed_value", event.target.value)}
          />
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="secret-set-source-path">
            source_path
          </Label>
          <Input
            id="secret-set-source-path"
            className="h-8 font-mono text-xs"
            placeholder="run_input.new_tacacs_key"
            value={stringField(config, "source_path")}
            onChange={(event) => setField("source_path", event.target.value)}
          />
        </div>
      )}

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-destination">
          destination_path
        </Label>
        <Input
          id="secret-set-destination"
          className="h-8 font-mono text-xs"
          placeholder="tacacs.shared_secret"
          value={stringField(config, "destination_path", "tacacs.shared_secret")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the written value is also sealed into (bag.field form).
        </p>
      </div>

      <div className="flex items-center justify-between rounded-lg border px-3 py-2">
        <div>
          <span className="font-mono text-xs font-medium">strict_templates</span>
          <p className="text-[11px] text-muted-foreground">
            Fail when a namespaced placeholder resolves empty.
          </p>
        </div>
        <Switch
          checked={strictTemplates}
          onCheckedChange={(checked) => setField("strict_templates", checked)}
        />
      </div>
    </div>
  );
}

export const SecretSetPlugin: PluginUIComponent = {
  ConfigPanel: SecretSetConfigPanel,
};
