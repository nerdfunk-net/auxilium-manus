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
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Read a secret per device</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Reads one field from a Secret Manager connection per device and seals it into the
          device&apos;s attribute bag. A device with no value is routed to the failure outcome.
        </p>
      </div>

      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-path">
          path_template
        </Label>
        <Input
          id="secret-get-path"
          className="h-8 font-mono text-xs"
          placeholder="network/{device.name}/tacacs"
          value={stringField(config, "path_template", "network/{device.name}/tacacs")}
          onChange={(event) => setField("path_template", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-field">
          field
        </Label>
        <Input
          id="secret-get-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field", "key")}
          onChange={(event) => setField("field", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-get-destination">
          destination_path
        </Label>
        <Input
          id="secret-get-destination"
          className="h-8 font-mono text-xs"
          placeholder="tacacs.shared_secret"
          value={stringField(config, "destination_path", "tacacs.shared_secret")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the sealed value is written to (bag.field form).
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
};
