"use client";

import { useCallback, useState, type ChangeEvent } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { BATFISH_GENERIC_QUESTION_NAMES } from "@/components/features/workflow-steps/shared/batfish-generic-question-names";

import type { BatfishParams } from "./batfish-param-fields";

interface BatfishGenericFieldsProps {
  questionName: string;
  onQuestionNameChange: (name: string) => void;
  params: BatfishParams;
  onParamsChange: (params: BatfishParams) => void;
}

export function BatfishGenericFields({
  questionName,
  onQuestionNameChange,
  params,
  onParamsChange,
}: BatfishGenericFieldsProps) {
  // Buffered locally so invalid-mid-typing JSON doesn't get discarded. Seeded from
  // `params` on mount (this component only mounts while question === "generic").
  const [paramsText, setParamsText] = useState(() => JSON.stringify(params, null, 2));
  const [paramsError, setParamsError] = useState<string | null>(null);

  const handleParamsChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      const text = event.target.value;
      setParamsText(text);
      if (!text.trim()) {
        setParamsError(null);
        onParamsChange({});
        return;
      }
      try {
        const parsed: unknown = JSON.parse(text);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("Params must be a JSON object");
        }
        setParamsError(null);
        onParamsChange(parsed as BatfishParams);
      } catch (error) {
        setParamsError(error instanceof Error ? error.message : "Invalid JSON");
      }
    },
    [onParamsChange],
  );

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="batfish-generic-question">Question Name</Label>
        <Input
          id="batfish-generic-question"
          value={questionName}
          onChange={(event) => onQuestionNameChange(event.target.value)}
          placeholder="e.g. bgpPeerConfiguration"
          list="batfish-generic-question-names"
          autoComplete="off"
        />
        <datalist id="batfish-generic-question-names">
          {BATFISH_GENERIC_QUESTION_NAMES.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <p className="text-[11px] leading-4 text-muted-foreground">
          A suggestion list, not the full set of allowed questions -- the backend rejects
          anything not on its own allow-list with a plain 400.
        </p>
        {questionName.trim() ? null : <p className="text-xs text-destructive">Required</p>}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="batfish-generic-params">Params (JSON, Optional)</Label>
        <Textarea
          id="batfish-generic-params"
          value={paramsText}
          onChange={handleParamsChange}
          placeholder={'{\n  "nodes": "R1"\n}'}
          className="min-h-24 font-mono text-xs"
        />
        {paramsError ? <p className="text-xs text-destructive">{paramsError}</p> : null}
      </div>
    </div>
  );
}
