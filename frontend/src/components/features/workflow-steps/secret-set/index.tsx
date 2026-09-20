"use client";

import { Search } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { SecretManagerConnectionField } from "@/components/features/workflow-steps/shared/secret-manager-connection-field";

import { SecretSetHelpPanel } from "./help-panel";

function stringField(config: Record<string, unknown>, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function SecretSetConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const setField = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );
  const [pickerOpen, setPickerOpen] = useState(false);

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
        <Label className="font-mono text-xs font-medium" htmlFor="secret-set-source-path">
          source_path
        </Label>
        <div className="flex items-center gap-1.5">
          <Input
            id="secret-set-source-path"
            className="h-8 font-mono text-xs"
            placeholder="run_input.new_tacacs_key"
            value={stringField(config, "source_path")}
            onChange={(event) => setField("source_path", event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Attribute path to read the value from — a run input supplied at trigger time
          (run_input.&lt;name&gt;) or the destination_path of an upstream secret step. A
          sealed value here is read as trusted cleartext for this write only. Blank uses
          the default shown above. There is no literal-value option: step config is
          stored in plaintext in the workflow definition.
        </p>
        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={(path) => setField("source_path", path)}
          nodeId={nodeId}
          workflowNodes={workflowNodes ?? []}
          workflowEdges={workflowEdges ?? []}
        />
      </div>

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
