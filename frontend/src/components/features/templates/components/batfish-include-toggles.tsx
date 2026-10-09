"use client";

import { Switch } from "@/components/ui/switch";

import type { BatfishParams } from "./batfish-param-fields";

const OSPF_TOGGLES = [
  ["include_process", "Process"],
  ["include_areas", "Areas"],
  ["include_interfaces", "Interfaces"],
  ["include_edges", "Adjacencies"],
] as const;

const BGP_TOGGLES = [
  ["include_process", "Process"],
  ["include_peers", "Peers"],
  ["include_sessions", "Sessions"],
  ["include_edges", "Adjacencies"],
] as const;

interface BatfishIncludeTogglesProps {
  question: "ospfFacts" | "bgpFacts";
  params: BatfishParams;
  onParamsChange: (params: BatfishParams) => void;
}

/** "include_*" sub-question switches; a key is on unless explicitly `false`. */
export function BatfishIncludeToggles({
  question,
  params,
  onParamsChange,
}: BatfishIncludeTogglesProps) {
  const toggles = question === "ospfFacts" ? OSPF_TOGGLES : BGP_TOGGLES;
  const anyEnabled = toggles.some(([key]) => params[key] !== false);

  return (
    <>
      <div className="col-span-full grid grid-cols-2 gap-2 sm:grid-cols-4">
        {toggles.map(([key, label]) => (
          <label
            key={key}
            htmlFor={`batfish-${key}`}
            className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs"
          >
            {label}
            <Switch
              id={`batfish-${key}`}
              checked={params[key] !== false}
              onCheckedChange={(checked) => onParamsChange({ ...params, [key]: checked })}
            />
          </label>
        ))}
      </div>
      {anyEnabled ? null : (
        <p className="col-span-full text-xs text-destructive">At least one question must be enabled</p>
      )}
    </>
  );
}
