"use client";

import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ReferenceKind } from "@/components/features/workflows/types/workflow-persistence";

export type RunParamSourceMode = "fixed" | "run_param";

interface RunParamSourceFieldProps {
  /** Human label, e.g. "Credential" or "Inventory". */
  label: string;
  /** The `reference` static-attribute kind a run parameter here must declare. */
  refKind: ReferenceKind;
  /** Current `config[sourceKey]` value. */
  mode: RunParamSourceMode;
  /** Current `config[paramKey]` value — the chosen run-parameter name. */
  paramName: string;
  onModeChange: (mode: RunParamSourceMode) => void;
  onParamNameChange: (name: string) => void;
  /** The existing "fixed value" editor (rendered when mode === "fixed"). */
  children: ReactNode;
}

/**
 * Wraps a step's fixed-value field (a credential picker, an inventory filter…)
 * with a toggle to instead take that value from a workflow run parameter — a
 * `static_attributes` entry of `type: "reference"` with the matching `ref_kind`,
 * resolved per triggering user at dispatch. The actual value is chosen per run /
 * per schedule (Schedules app); here you only name the parameter.
 * See doc/SCHEDULES.md.
 */
export function RunParamSourceField({
  label,
  refKind,
  mode,
  paramName,
  onModeChange,
  onParamNameChange,
  children,
}: RunParamSourceFieldProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-xs font-medium">{label}</Label>
        <Tabs value={mode} onValueChange={(v) => onModeChange(v as RunParamSourceMode)}>
          <TabsList className="h-7">
            <TabsTrigger className="h-5 px-2 text-[11px]" value="fixed">
              Fixed
            </TabsTrigger>
            <TabsTrigger className="h-5 px-2 text-[11px]" value="run_param">
              Run parameter
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {mode === "run_param" ? (
        <div className="space-y-1">
          <Input
            className="h-8 text-xs"
            placeholder="run parameter name"
            value={paramName}
            onChange={(e) => onParamNameChange(e.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            Name a <span className="font-mono">reference</span> run parameter
            (ref_kind <span className="font-mono">{refKind}</span>) declared in the
            workflow Properties panel. Its value is set per run / per schedule.
          </p>
        </div>
      ) : (
        children
      )}
    </div>
  );
}
