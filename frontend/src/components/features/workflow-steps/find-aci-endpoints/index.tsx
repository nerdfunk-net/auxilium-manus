"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import {
  ACI_SOURCE_ID_KEY,
  aciSourceIdFromConfig,
} from "../shared/aci-source-config";
import { AciSourceSelectDialog } from "../shared/aci-source-select-dialog";
import { ParsedOutputKeyField, readString } from "../shared/catalyst-center-fact-fields";
import { FindAciEndpointsHelpPanel } from "./help-panel";

const ADDRESS_PATH_KEY = "address_path";
const DEFAULT_ADDRESS_PATH = "primary_ip4";
const DEFAULT_OUTPUT_KEY = "aci_endpoint";

function FindAciEndpointsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => aciSourceIdFromConfig(config), [config]);
  const addressPath = readString(config, ADDRESS_PATH_KEY, DEFAULT_ADDRESS_PATH);
  const outputKey = readString(config, "parsed_output_key", DEFAULT_OUTPUT_KEY);
  const [sourceOpen, setSourceOpen] = useState(false);

  const handleSourceIdChange = useCallback(
    (next: string) => onChange({ ...config, [ACI_SOURCE_ID_KEY]: next }),
    [config, onChange],
  );
  const handleAddressPathChange = useCallback(
    (next: string) => onChange({ ...config, [ADDRESS_PATH_KEY]: next }),
    [config, onChange],
  );
  const handleOutputKeyChange = useCallback(
    (next: string) => onChange({ ...config, parsed_output_key: next }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ACI_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            aci
          </Badge>
        </div>
        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ADDRESS_PATH_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={addressPath}
          onChange={(event) => handleAddressPathChange(event.target.value)}
          placeholder={DEFAULT_ADDRESS_PATH}
          aria-label="Address path"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Device attribute that holds the IPv4 or MAC address to look up. A device without a
          value fails with <code className="rounded bg-muted px-1">no_address</code>.
        </p>
      </div>

      <ParsedOutputKeyField
        value={outputKey}
        fallback={DEFAULT_OUTPUT_KEY}
        suffix="endpoints"
        onChange={handleOutputKeyChange}
      />

      <AciSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const FindAciEndpointsPlugin: PluginUIComponent = {
  ConfigPanel: FindAciEndpointsConfigPanel,
  HelpPanel: FindAciEndpointsHelpPanel,
};
