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

import { SecretGenerateHelpPanel } from "./help-panel";

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
      <SecretManagerConnectionField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-path">
          path_template
        </Label>
        <Input
          id="secret-generate-path"
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
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-field">
          field
        </Label>
        <Input
          id="secret-generate-field"
          className="h-8 font-mono text-xs"
          placeholder="key"
          value={stringField(config, "field")}
          onChange={(event) => setField("field", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Field name to store the generated value under, within the secret at
          path_template. Blank uses the default shown above.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="secret-generate-destination">
          destination_path
        </Label>
        <Input
          id="secret-generate-destination"
          className="h-8 font-mono text-xs"
          placeholder="tacacs.shared_secret"
          value={stringField(config, "destination_path")}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the sealed value is written to (bag.field form), for a
          later step in the same run to use. Blank uses the default shown above.
        </p>
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
        <p className="text-[11px] text-muted-foreground">
          Character set used to generate the value — pick the preset matching what
          the target device/system expects.
        </p>
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
        <p className="text-[11px] text-muted-foreground">
          Length of the generated value, in characters (4–256).
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

export const SecretGeneratePlugin: PluginUIComponent = {
  ConfigPanel: SecretGenerateConfigPanel,
  HelpPanel: SecretGenerateHelpPanel,
};
