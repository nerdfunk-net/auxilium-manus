"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useUpdateAttributeDeviceProbeMutation,
  useUpdateAttributeProbeMutation,
  type UpdateAttributeProbeResult,
} from "@/hooks/queries/use-update-attribute-mutations";

import type { RegexFlags } from "./update-attribute-config";

const EMPTY_PROBE_RESULT: UpdateAttributeProbeResult | null = null;

interface RegexProbePanelProps {
  pattern: string;
  destinationTemplate: string;
  regexFlags: RegexFlags;
  sourcePath: string;
}

function ProbeResultView({ result }: { result: UpdateAttributeProbeResult }) {
  return (
    <div className="space-y-2 rounded-lg border border-teal-200 bg-teal-50 p-3 text-teal-900">
      <div className="flex items-center gap-2">
        <Badge
          className={
            result.matched
              ? "bg-teal-600 text-white hover:bg-teal-600"
              : "bg-amber-100 text-amber-900 hover:bg-amber-100"
          }
        >
          {result.matched ? "Matched" : "No match"}
        </Badge>
        {result.source_text ? (
          <span className="truncate font-mono text-[11px]">{result.source_text}</span>
        ) : null}
      </div>

      {result.matched ? (
        <div className="space-y-1.5 text-[11px] leading-4">
          {result.full_match ? (
            <p>
              <span className="font-medium">Full match:</span>{" "}
              <span className="font-mono">{result.full_match}</span>
            </p>
          ) : null}
          {Object.keys(result.groups).length > 0 ? (
            <div>
              <p className="font-medium">Numbered groups</p>
              <ul className="mt-1 space-y-0.5 font-mono">
                {Object.entries(result.groups).map(([key, value]) => (
                  <li key={key}>
                    {`\\${key}`} = {value}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {Object.keys(result.named_groups).length > 0 ? (
            <div>
              <p className="font-medium">Named groups</p>
              <ul className="mt-1 space-y-0.5 font-mono">
                {Object.entries(result.named_groups).map(([key, value]) => (
                  <li key={key}>
                    {`\\g<${key}>`} = {value}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.destination_value ? (
            <p>
              <span className="font-medium">Destination value:</span>{" "}
              <span className="font-mono">{result.destination_value}</span>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-[11px] leading-4">
          The pattern did not match the source text. At runtime, the step skips the update
          and continues.
        </p>
      )}
    </div>
  );
}

export function RegexProbePanel({
  pattern,
  destinationTemplate,
  regexFlags,
  sourcePath,
}: RegexProbePanelProps) {
  const [sampleText, setSampleText] = useState("l123-router-1.local.zz");
  const [deviceJson, setDeviceJson] = useState(
    JSON.stringify(
      {
        id: "device-1",
        name: "l123-router-1.local.zz",
        hostname: "l123-router-1.local.zz",
        attribute_bags: {},
      },
      null,
      2,
    ),
  );
  const [manualResult, setManualResult] = useState<UpdateAttributeProbeResult | null>(
    EMPTY_PROBE_RESULT,
  );
  const [deviceResult, setDeviceResult] = useState<UpdateAttributeProbeResult | null>(
    EMPTY_PROBE_RESULT,
  );
  const [deviceError, setDeviceError] = useState<string | null>(null);

  const probeMutation = useUpdateAttributeProbeMutation();
  const deviceProbeMutation = useUpdateAttributeDeviceProbeMutation();

  const probePayload = useMemo(
    () => ({
      pattern,
      destination_template: destinationTemplate,
      regex_flags: regexFlags,
    }),
    [pattern, destinationTemplate, regexFlags],
  );

  const handleManualProbe = useCallback(async () => {
    const result = await probeMutation.mutateAsync({
      sample_text: sampleText,
      ...probePayload,
    });
    setManualResult(result);
  }, [probeMutation, probePayload, sampleText]);

  const handleDeviceProbe = useCallback(async () => {
    setDeviceError(null);
    try {
      const device = JSON.parse(deviceJson) as Record<string, unknown>;
      const result = await deviceProbeMutation.mutateAsync({
        device,
        source_path: sourcePath,
        ...probePayload,
      });
      setDeviceResult(result);
    } catch (error) {
      setDeviceResult(null);
      setDeviceError(error instanceof Error ? error.message : "Invalid device JSON");
    }
  }, [deviceJson, deviceProbeMutation, probePayload, sourcePath]);

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-4 text-muted-foreground">
        Test your Python regular expression before running the workflow. Destination templates
        support backrefs such as <span className="font-mono">{"\\1"}</span> and{" "}
        <span className="font-mono">{"\\g<location>"}</span>.
      </p>

      <div className="space-y-2 rounded-lg border bg-background p-3">
        <Label className="text-[11px] text-muted-foreground">Sample text</Label>
        <Input
          value={sampleText}
          onChange={(event) => setSampleText(event.target.value)}
          placeholder="l123-router-1.local.zz"
          className="h-8 font-mono text-xs"
        />
        <Button
          type="button"
          size="sm"
          className="bg-teal-500 text-white hover:bg-teal-600"
          onClick={() => void handleManualProbe()}
          disabled={probeMutation.isPending}
        >
          Probe sample text
        </Button>
        {manualResult ? <ProbeResultView result={manualResult} /> : null}
        {probeMutation.error ? (
          <p className="text-[11px] text-destructive">{probeMutation.error.message}</p>
        ) : null}
      </div>

      <div className="space-y-2 rounded-lg border bg-background p-3">
        <Label className="text-[11px] text-muted-foreground">
          Device JSON ({sourcePath || "source_path"})
        </Label>
        <Textarea
          value={deviceJson}
          onChange={(event) => setDeviceJson(event.target.value)}
          rows={8}
          className="font-mono text-xs"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void handleDeviceProbe()}
          disabled={deviceProbeMutation.isPending}
        >
          Probe against device
        </Button>
        {deviceError ? <p className="text-[11px] text-destructive">{deviceError}</p> : null}
        {deviceResult ? <ProbeResultView result={deviceResult} /> : null}
        {deviceProbeMutation.error ? (
          <p className="text-[11px] text-destructive">{deviceProbeMutation.error.message}</p>
        ) : null}
      </div>
    </div>
  );
}
