import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { FieldHeader } from "../shared/field-header";
import { PyATSSourceSelectDialog } from "../shared/pyats-source-select-dialog";
import { PYATS_SOURCE_ID_KEY } from "../shared/pyats-source-config";
import { PARSER_MODE_OPTIONS, type ParserMode } from "./config";

interface ParserFieldsProps {
  parserLocked: boolean;
  parserMode: ParserMode;
  hasPyatsSource: boolean;
  pyatsSourceId: string;
  parsedOutputKey: string;
  onPatch: (patch: Record<string, unknown>) => void;
}

export function ParserFields({
  parserLocked,
  parserMode,
  hasPyatsSource,
  pyatsSourceId,
  parsedOutputKey,
  onPatch,
}: ParserFieldsProps) {
  const [sourceDialogOpen, setSourceDialogOpen] = useState(false);

  if (parserLocked) {
    return (
      <div className="space-y-1.5 border-t pt-3">
        <FieldHeader name="parser" type="string" />
        <p className="text-[11px] text-muted-foreground">
          Parser is unavailable when execution_mode is config_mode or auto_confirm_prompts is
          enabled.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5 border-t pt-3">
      <FieldHeader name="parser" type="string" />
      <Select value={parserMode} onValueChange={(value) => onPatch({ parser: value })}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PARSER_MODE_OPTIONS.filter((option) => option.value !== "genie" || hasPyatsSource).map(
            (option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ),
          )}
        </SelectContent>
      </Select>
      <p className="text-[11px] text-muted-foreground">
        Normalizes command output into structured data. Whichever parser you pick, downstream
        steps read it the same way.
      </p>

      {parserMode !== "none" && (
        <div className="space-y-2 border-t pt-3">
          {parserMode === "genie" && (
            <div className="space-y-1.5">
              <FieldHeader name={PYATS_SOURCE_ID_KEY} type="pyats" />

              {pyatsSourceId ? (
                <p className="font-mono text-[11px] text-muted-foreground">{pyatsSourceId}</p>
              ) : (
                <p className="text-[11px] text-warning-foreground">Not configured</p>
              )}

              <Button
                className="h-7 w-full text-xs"
                size="sm"
                type="button"
                variant="outline"
                onClick={() => setSourceDialogOpen(true)}
              >
                {pyatsSourceId ? "Edit Source" : "Configure Source"}
              </Button>

              <PyATSSourceSelectDialog
                open={sourceDialogOpen}
                selectedSourceId={pyatsSourceId}
                onClose={() => setSourceDialogOpen(false)}
                onSave={(newSourceId) => onPatch({ [PYATS_SOURCE_ID_KEY]: newSourceId })}
              />
            </div>
          )}

          <div className="space-y-1.5">
            <FieldHeader name="parsed_output_key" type="string" />
            <Input
              value={parsedOutputKey}
              onChange={(event) => onPatch({ parsed_output_key: event.target.value })}
              placeholder="parsed"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Key for this step&apos;s parsed output on each device (
              <span className="font-mono">
                parsed.{parsedOutputKey || "parsed"}.&quot;&lt;command&gt;&quot;
              </span>
              ).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
