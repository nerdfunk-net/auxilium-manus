"use client";

import { useCallback } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { SecretManagerConnectionField } from "@/components/features/workflow-steps/shared/secret-manager-connection-field";

import { SecretGetHelpPanel } from "./help-panel";

function stringField(config: Record<string, unknown>, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function SecretGetConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const setField = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;
  const versionValue = typeof config.version === "number" ? String(config.version) : "";

  return (
    <div className="flex flex-col gap-4">
      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-path">
          path_template
        </Label>
        <Input
          id="secret-get-path"
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
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-field">
          field
        </Label>
        <Input
          id="secret-get-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field")}
          onChange={(event) => setField("field", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Field name to read within the secret stored at path_template. Blank uses
          the default shown above.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-destination">
          destination_path
        </Label>
        <Input
          id="secret-get-destination"
          className="h-8 font-mono text-xs"
          placeholder="tacacs.shared_secret"
          value={stringField(config, "destination_path")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the sealed value is written to (bag.field form). Blank
          uses the default shown above.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-version">
          version (optional)
        </Label>
        <Input
          id="secret-get-version"
          className="h-8 font-mono text-xs"
          type="number"
          placeholder="latest"
          value={versionValue}
          onChange={(event) => {
            const raw = event.target.value.trim();
            setField("version", raw ? Number(raw) : null);
          }}
        />
        <p className="text-[11px] text-muted-foreground">
          Specific version to read (e.g. to fetch a previous secret before rotation).
          Leave blank to read the latest version.
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

export const SecretGetPlugin: PluginUIComponent = {
  ConfigPanel: SecretGetConfigPanel,
  HelpPanel: SecretGetHelpPanel,
};
