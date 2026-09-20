"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

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
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { SharedSecretCredentialField } from "@/components/features/workflow-steps/shared/shared-secret-credential-field";
import { SHARED_SECRET_ALGORITHMS } from "@/lib/shared-secret-algorithms";

import {
  buildDecryptAttributeConfig,
  parseDecryptAttributeConfig,
} from "./config";
import { DecryptAttributeHelpPanel } from "./help-panel";
import { DecryptAttributeTestDialog } from "./test-dialog";

const ALGORITHM_DEFAULT_SENTINEL = "__default__";

function DecryptAttributeConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseDecryptAttributeConfig(config), [config]);
  const [testOpen, setTestOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const setField = useCallback(
    (
      key: "source_path" | "destination_path" | "algorithm" | "item_field",
      value: string,
    ) => {
      onChange(buildDecryptAttributeConfig(config, { [key]: value }));
    },
    [config, onChange],
  );

  const isListMode = Boolean(parsed.item_field.trim());

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="decrypt-attribute-source">
          source_path
        </Label>
        <div className="flex items-center gap-1.5">
          <Input
            id="decrypt-attribute-source"
            className="h-8 font-mono text-xs"
            placeholder={
              isListMode
                ? "nautobot.config_context.credentials"
                : "nautobot.config_context.secrets.enable_password"
            }
            value={parsed.source_path}
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
          {isListMode
            ? "Dot path to a list. Each entry's item_field is decrypted."
            : "Dot path to the encrypted value (ciphertext token)."}
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
        <Label className="font-mono text-xs font-medium" htmlFor="decrypt-attribute-item-field">
          item_field
        </Label>
        <Input
          id="decrypt-attribute-item-field"
          className="h-8 font-mono text-xs"
          placeholder="password"
          value={parsed.item_field}
          onChange={(event) => setField("item_field", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Blank = single value. Set a field name to run <span className="font-medium">list
          mode</span>: source_path resolves to a list and this field is decrypted on
          every entry (unknown length / usernames).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="decrypt-attribute-destination">
          destination_path{isListMode ? " (optional)" : ""}
        </Label>
        <Input
          id="decrypt-attribute-destination"
          className="h-8 font-mono text-xs"
          placeholder={isListMode ? "(blank = rewrite source list in place)" : "secrets.enable_password"}
          value={parsed.destination_path}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          {isListMode
            ? "Blank rewrites source_path's list in place. Set a bag.field path to write the transformed list elsewhere."
            : "Where the decrypted value is written, sealed (bag.field)."}
        </p>
      </div>

      <SharedSecretCredentialField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium">algorithm</Label>
        <Select
          value={parsed.algorithm || ALGORITHM_DEFAULT_SENTINEL}
          onValueChange={(value) =>
            setField("algorithm", value === ALGORITHM_DEFAULT_SENTINEL ? "" : value)
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALGORITHM_DEFAULT_SENTINEL}>Use credential default</SelectItem>
            {SHARED_SECRET_ALGORITHMS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Button
        className="h-7 w-full text-xs"
        size="sm"
        type="button"
        variant="secondary"
        onClick={() => setTestOpen(true)}
      >
        Test Decryption
      </Button>

      {testOpen ? (
        <DecryptAttributeTestDialog onClose={() => setTestOpen(false)} />
      ) : null}
    </div>
  );
}

export const DecryptAttributePlugin: PluginUIComponent = {
  ConfigPanel: DecryptAttributeConfigPanel,
  HelpPanel: DecryptAttributeHelpPanel,
};
