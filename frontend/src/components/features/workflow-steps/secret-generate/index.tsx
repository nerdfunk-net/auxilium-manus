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

const CHARSET_OPTIONS = [
  { value: "hex", label: "hex — TACACS+ keys, generic tokens" },
  { value: "alnum", label: "alnum — SNMP community strings" },
  { value: "alnum_symbols", label: "alnum_symbols — SNMPv3 auth/priv passphrases" },
];

function SecretGenerateConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const setField = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;
  const length = typeof config.length === "number" ? config.length : 32;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Generate and store a random secret per device</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          The TACACS+/SNMP rotation primitive. The generated value is never shown in the run UI,
          never logged, and is sealed into the device&apos;s attribute bag for a later step (e.g.
          a push-config step) in the same run.
        </p>
      </div>

      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-path">
          path_template
        </Label>
        <Input
          id="secret-generate-path"
          className="h-8 font-mono text-xs"
          placeholder="network/{device.name}/tacacs"
          value={stringField(config, "path_template", "network/{device.name}/tacacs")}
          onChange={(event) => setField("path_template", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-field">
          field
        </Label>
        <Input
          id="secret-generate-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field", "key")}
          onChange={(event) => setField("field", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-destination">
          destination_path
        </Label>
        <Input
          id="secret-generate-destination"
          className="h-8 font-mono text-xs"
          placeholder="tacacs.shared_secret"
          value={stringField(config, "destination_path", "tacacs.shared_secret")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium">charset</Label>
        <Select
          value={stringField(config, "charset", "hex")}
          onValueChange={(value) => setField("charset", value)}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHARSET_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-length">
          length
        </Label>
        <Input
          id="secret-generate-length"
          className="h-8 font-mono text-xs"
          type="number"
          min={4}
          max={256}
          value={length}
          onChange={(event) => setField("length", Number(event.target.value) || 32)}
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

export const SecretGeneratePlugin: PluginUIComponent = {
  ConfigPanel: SecretGenerateConfigPanel,
};
