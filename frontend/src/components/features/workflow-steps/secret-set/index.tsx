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

import { SecretSetHelpPanel } from "./help-panel";

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
      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-path">
          path_template
        </Label>
        <Input
          id="secret-set-path"
          className="h-8 font-mono text-xs"
          placeholder="network/{device.name}/tacacs"
          value={stringField(config, "path_template")}
          onChange={(event) => setField("path_template", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Path in the connection, rendered per device — supports {"{device.*}"} /{" "}
          {"{nautobot.*}"} / {"{git.*}"} placeholders, same as store-artifact&apos;s
          filename_template. Blank uses the default shown above.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-field">
          field
        </Label>
        <Input
          id="secret-set-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field")}
          onChange={(event) => setField("field", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Field name to write within the secret stored at path_template. Blank uses
          the default shown above.
        </p>
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
        <p className="text-[11px] text-muted-foreground">
          fixed writes the literal value typed below; attribute reads the value from
          another attribute path instead (e.g. a run input supplied at trigger time).
        </p>
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
          <p className="text-[11px] text-muted-foreground">
            The literal value to write. Required in fixed mode; masked like any other
            credential input.
          </p>
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
          <p className="text-[11px] text-muted-foreground">
            Attribute path to read the value from. Required in attribute mode; a
            sealed value here is read as trusted cleartext for this write only.
          </p>
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
          value={stringField(config, "destination_path")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the written value is also sealed into (bag.field form).
          Blank uses the default shown above.
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
  HelpPanel: SecretSetHelpPanel,
};
