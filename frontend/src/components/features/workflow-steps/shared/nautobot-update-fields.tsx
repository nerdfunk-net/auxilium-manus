import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { stringField } from "./config-field-helpers";
import { ExpressionField } from "./expression-field";
import {
  BAD_MODE_PROBLEM,
  LOCATIONS_KEY,
  LOCATIONS_MODE_KEY,
  LOCATIONS_MODE_OPTIONS,
  locationsModeFromConfig,
} from "./nautobot-locations";

/** Building blocks the Nautobot update panels (`update-nautobot-vlan`, `update-nautobot-prefix`,
 * `update-nautobot-ip`) have in common. */

interface SwitchRowProps {
  label: string;
  description: ReactNode;
  ariaLabel: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

function SwitchRow({ label, description, ariaLabel, checked, onCheckedChange }: SwitchRowProps) {
  return (
    <>
      <div className="space-y-0.5">
        <Label className="text-xs font-medium">{label}</Label>
        <p className="text-[11px] text-muted-foreground">{description}</p>
      </div>
      <Switch
        aria-label={ariaLabel}
        checked={checked}
        onCheckedChange={onCheckedChange}
        className="data-[state=checked]:bg-step"
      />
    </>
  );
}

interface FromInterfacesSwitchProps extends SwitchRowProps {
  bordered?: boolean;
}

/** The "<objects> from interfaces" mode switch. */
export function FromInterfacesSwitch({ bordered, ...row }: FromInterfacesSwitchProps) {
  return (
    <div
      className={`flex items-center justify-between gap-3${bordered ? " border-t pt-3" : ""}`}
    >
      <SwitchRow {...row} />
    </div>
  );
}

interface DryRunSwitchProps {
  description: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

/** The `dry_run` switch of the interface mode. */
export function DryRunSwitch({ description, checked, onCheckedChange }: DryRunSwitchProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <SwitchRow
        label="Dry run"
        description={description}
        ariaLabel="dry_run"
        checked={checked}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

interface LocationsFieldsProps
  extends Pick<PluginConfigPanelProps, "nodeId">,
    Required<Pick<PluginConfigPanelProps, "workflowNodes" | "workflowEdges">> {
  config: Record<string, unknown>;
  patch: (key: string, value: unknown) => void;
  problems: readonly string[];
  /** What the locations belong to, for the help text ("VLAN", "prefix"). */
  noun: string;
}

/** `locations` and `locations_mode` of a step that edits an object's locations. */
export function LocationsFields({
  config,
  patch,
  problems,
  noun,
  nodeId,
  workflowNodes,
  workflowEdges,
}: LocationsFieldsProps) {
  return (
    <>
      <ExpressionField
        configKey={LOCATIONS_KEY}
        value={stringField(config, LOCATIONS_KEY)}
        placeholder="Berlin, Munich"
        onValueChange={(next) => patch(LOCATIONS_KEY, next)}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      >
        <p className="text-[11px] leading-4 text-muted-foreground">
          Names or UUIDs separated by commas, or a {"{path}"}. Quote a name with a comma:
          &quot;Frankfurt, West&quot;.
        </p>
      </ExpressionField>

      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{LOCATIONS_MODE_KEY}</span>
        <Select
          value={locationsModeFromConfig(config)}
          onValueChange={(next) => patch(LOCATIONS_MODE_KEY, next)}
        >
          <SelectTrigger className="h-8 text-xs focus:ring-step/40" aria-label={LOCATIONS_MODE_KEY}>
            <SelectValue placeholder="Pick a mode" />
          </SelectTrigger>
          <SelectContent>
            {LOCATIONS_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} className="text-xs">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {problems.includes(BAD_MODE_PROBLEM) ? (
          <p className="text-[11px] text-warning-foreground">
            The stored mode is not valid and the step would fail. Pick replace, add or remove.
          </p>
        ) : (
          <p className="text-[11px] leading-4 text-muted-foreground">
            How the list is applied to the {noun}&apos;s current locations.
          </p>
        )}
      </div>
    </>
  );
}
