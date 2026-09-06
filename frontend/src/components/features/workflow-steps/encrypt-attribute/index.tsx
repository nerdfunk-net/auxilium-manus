"use client";

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
import { SharedSecretCredentialField } from "@/components/features/workflow-steps/shared/shared-secret-credential-field";
import { SHARED_SECRET_ALGORITHMS } from "@/lib/shared-secret-algorithms";

import {
  buildEncryptAttributeConfig,
  parseEncryptAttributeConfig,
} from "./config";
import { EncryptAttributeHelpPanel } from "./help-panel";
import { EncryptAttributeTestDialog } from "./test-dialog";

const ALGORITHM_DEFAULT_SENTINEL = "__default__";

function EncryptAttributeConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseEncryptAttributeConfig(config), [config]);
  const [testOpen, setTestOpen] = useState(false);

  const setField = useCallback(
    (key: "source_path" | "destination_path" | "algorithm", value: string) => {
      onChange(buildEncryptAttributeConfig(config, { [key]: value }));
    },
    [config, onChange],
  );

  const isConfigured =
    Boolean(parsed.source_path.trim()) &&
    Boolean(parsed.destination_path.trim()) &&
    Boolean(parsed.credential_reference.trim());

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Encrypt an attribute value with a shared secret</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Reads a cleartext value, encrypts it, and writes the portable ciphertext
          token to the destination path for later persistence (disk or Git).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="encrypt-attribute-source">
          source_path
        </Label>
        <Input
          id="encrypt-attribute-source"
          className="h-8 font-mono text-xs"
          placeholder="run_input.enable_password"
          value={parsed.source_path}
          onChange={(event) => setField("source_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Dot path to the cleartext value. Sealed secrets are rejected.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="encrypt-attribute-destination">
          destination_path
        </Label>
        <Input
          id="encrypt-attribute-destination"
          className="h-8 font-mono text-xs"
          placeholder="secrets.enable_password_enc"
          value={parsed.destination_path}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Where the ciphertext token is written (<span className="font-mono">bag.field</span>).
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
        disabled={!isConfigured}
        onClick={() => setTestOpen(true)}
      >
        Test Encryption
      </Button>

      {testOpen ? (
        <EncryptAttributeTestDialog
          onClose={() => setTestOpen(false)}
          algorithm={parsed.algorithm}
        />
      ) : null}
    </div>
  );
}

export const EncryptAttributePlugin: PluginUIComponent = {
  ConfigPanel: EncryptAttributeConfigPanel,
  HelpPanel: EncryptAttributeHelpPanel,
};
