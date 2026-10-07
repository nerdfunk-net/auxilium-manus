"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";

import { SelectOrExpressionField } from "../shared/select-or-expression-field";
import { missingRequiredFields } from "./add-nautobot-metadata-config";
import {
  fieldDefinitionsFor,
  METADATA_TYPE_OPTIONS,
  type MetadataType,
  type MetadataValues,
} from "./types";

interface AddNautobotMetadataDialogProps {
  open: boolean;
  metadataType: MetadataType;
  value: MetadataValues;
  sourceId: string;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
  onClose: () => void;
  onSave: (value: MetadataValues) => void;
}

type DialogFormProps = Omit<AddNautobotMetadataDialogProps, "open">;

function AddNautobotMetadataDialogForm({
  metadataType,
  value,
  sourceId,
  nodeId,
  workflowNodes,
  workflowEdges,
  onClose,
  onSave,
}: DialogFormProps) {
  const [draft, setDraft] = useState<MetadataValues>(value);
  const definitions = fieldDefinitionsFor(metadataType);
  const draftRecord = draft as unknown as Record<string, string>;
  const missing = missingRequiredFields(metadataType, draft);
  const title =
    METADATA_TYPE_OPTIONS.find((option) => option.value === metadataType)?.label ?? metadataType;

  const patchField = useCallback((key: string, text: string) => {
    setDraft((current) => ({ ...current, [key]: text }) as MetadataValues);
  }, []);

  const handleSave = useCallback(() => onSave(draft), [draft, onSave]);

  return (
    <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <DialogHeader className="border-b step-header px-4 py-3">
        <DialogTitle className="text-base text-step-header-foreground">
          Add {title} Configuration
        </DialogTitle>
        <DialogDescription className="sr-only">
          Set each {title.toLowerCase()} value to a fixed text, a Nautobot list entry, or an
          attribute-bag expression.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-3 overflow-y-auto bg-muted p-4">
        <p className="text-[11px] leading-4 text-muted-foreground">
          Each value is a fixed text, a pick from Nautobot, or an attribute-bag expression such as{" "}
          <code className="font-mono">{"{custom.location_name}"}</code>. Existing objects are
          reused, so the step is safe to run again.
        </p>
        {definitions.map((definition) => (
          <SelectOrExpressionField
            key={definition.key}
            label={definition.label}
            placeholder={definition.placeholder}
            required={definition.required}
            hint={definition.hint}
            optionsField={definition.optionsField}
            value={draftRecord[definition.key] ?? ""}
            onValueChange={(text) => patchField(definition.key, text)}
            sourceId={sourceId}
            nodeId={nodeId}
            workflowNodes={workflowNodes}
            workflowEdges={workflowEdges}
          />
        ))}
        {missing.length > 0 ? (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            Still empty: {missing.join(", ")}
          </p>
        ) : null}
      </div>

      <DialogFooter className="border-t bg-card px-4 py-3">
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="bg-step text-step-foreground hover:bg-step-hover"
          type="button"
          onClick={handleSave}
        >
          Save
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function AddNautobotMetadataDialog({ open, onClose, ...rest }: AddNautobotMetadataDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      {open ? <AddNautobotMetadataDialogForm onClose={onClose} {...rest} /> : null}
    </Dialog>
  );
}
