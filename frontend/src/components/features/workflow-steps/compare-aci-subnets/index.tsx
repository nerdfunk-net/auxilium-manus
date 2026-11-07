"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { ACI_SOURCE_ID_KEY, aciSourceIdFromConfig } from "../shared/aci-source-config";
import { AciSourceSelectDialog } from "../shared/aci-source-select-dialog";
import { readString } from "../shared/catalyst-center-fact-fields";
import {
  NAUTOBOT_SOURCE_ID_KEY,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { CompareAciSubnetsHelpPanel } from "./help-panel";

const NAMESPACE_KEY = "namespace";
const FROM_VRF_KEY = "namespace_from_vrf";
const SCOPE_KEY = "scope_prefixes";
const OUTPUT_KEY = "output_key";
const DEFAULT_NAMESPACE = "Global";
const DEFAULT_OUTPUT_KEY = "aci_subnet_report";

function scopeFromConfig(config: Record<string, unknown>): string[] {
  const raw = config[SCOPE_KEY];
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
}

interface SourceRowProps {
  label: string;
  badge: string;
  sourceId: string;
  onOpen: () => void;
}

function SourceRow({ label, badge, sourceId, onOpen }: SourceRowProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{label}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {badge}
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
        onClick={onOpen}
      >
        {sourceId ? "Edit Source" : "Configure Source"}
      </Button>
    </div>
  );
}

function CompareAciSubnetsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const aciSourceId = useMemo(() => aciSourceIdFromConfig(config), [config]);
  const nautobotSourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const namespace = readString(config, NAMESPACE_KEY, DEFAULT_NAMESPACE);
  const fromVrf = Boolean(config[FROM_VRF_KEY]);
  const scope = useMemo(() => scopeFromConfig(config), [config]);
  const outputKey = readString(config, OUTPUT_KEY, DEFAULT_OUTPUT_KEY);
  const [aciOpen, setAciOpen] = useState(false);
  const [nautobotOpen, setNautobotOpen] = useState(false);

  const set = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );
  const handleScope = useCallback(
    // Blank lines stay while typing so the cursor is not pulled away after Enter.
    (text: string) => set(SCOPE_KEY, text.split("\n")),
    [set],
  );

  return (
    <div className="flex flex-col gap-4">
      <SourceRow
        label={ACI_SOURCE_ID_KEY}
        badge="aci"
        sourceId={aciSourceId}
        onOpen={() => setAciOpen(true)}
      />
      <SourceRow
        label={NAUTOBOT_SOURCE_ID_KEY}
        badge="nautobot"
        sourceId={nautobotSourceId}
        onOpen={() => setNautobotOpen(true)}
      />

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-subnets-namespace">
          {NAMESPACE_KEY}
        </Label>
        <Input
          id="aci-subnets-namespace"
          className="h-8 font-mono text-xs"
          value={namespace}
          disabled={fromVrf}
          placeholder={DEFAULT_NAMESPACE}
          onChange={(event) => set(NAMESPACE_KEY, event.target.value)}
        />
        <div className="flex items-center gap-2">
          <Switch
            id="aci-subnets-from-vrf"
            checked={fromVrf}
            onCheckedChange={(checked) => set(FROM_VRF_KEY, checked)}
          />
          <Label className="font-mono text-xs" htmlFor="aci-subnets-from-vrf">
            {FROM_VRF_KEY}
          </Label>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Compare in one Nautobot namespace, or use each subnet&apos;s VRF name as the namespace.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-subnets-scope">
          {SCOPE_KEY}
        </Label>
        <Textarea
          id="aci-subnets-scope"
          className="min-h-16 font-mono text-xs"
          placeholder="10.0.0.0/8"
          value={scope.join("\n")}
          onChange={(event) => handleScope(event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          One prefix per line. Nautobot networks inside them that ACI lacks are reported too.
          Empty skips that check.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="aci-subnets-output-key">
          {OUTPUT_KEY}
        </Label>
        <Input
          id="aci-subnets-output-key"
          className="h-8 font-mono text-xs"
          value={outputKey}
          placeholder={DEFAULT_OUTPUT_KEY}
          onChange={(event) => set(OUTPUT_KEY, event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Summary lands in the run metadata as &lt;node id&gt;.{outputKey || DEFAULT_OUTPUT_KEY};
          the full report is an artifact.
        </p>
      </div>

      <AciSourceSelectDialog
        open={aciOpen}
        selectedSourceId={aciSourceId}
        onClose={() => setAciOpen(false)}
        onSave={(next) => set(ACI_SOURCE_ID_KEY, next)}
      />
      <NautobotSourceSelectDialog
        open={nautobotOpen}
        selectedSourceId={nautobotSourceId}
        onClose={() => setNautobotOpen(false)}
        onSave={(next) => set(NAUTOBOT_SOURCE_ID_KEY, next)}
      />
    </div>
  );
}

export const CompareAciSubnetsPlugin: PluginUIComponent = {
  ConfigPanel: CompareAciSubnetsConfigPanel,
  HelpPanel: CompareAciSubnetsHelpPanel,
};
