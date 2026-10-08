"use client";

import { Search } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";

import { AttributePathPicker } from "../shared/attribute-path-picker";

interface PlaceholderFieldProps {
  configKey: string;
  value: string;
  placeholder: string;
  onValueChange: (value: string) => void;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
  multiline?: boolean;
  children?: React.ReactNode;
}

/**
 * Text field whose value may contain `{path.to.value}` placeholders. The
 * "Browse attributes" button inserts the picked path as `{path}` at the end of
 * the current text instead of replacing it, so a subject such as
 * `Config changed on {device.name}` survives picking a second attribute.
 */
export function PlaceholderField({
  configKey,
  value,
  placeholder,
  onValueChange,
  nodeId,
  workflowNodes,
  workflowEdges,
  multiline = false,
  children,
}: PlaceholderFieldProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      onValueChange(event.target.value),
    [onValueChange],
  );
  const handleClosePicker = useCallback(() => setPickerOpen(false), []);
  const handleSelect = useCallback(
    (path: string) => {
      onValueChange(`${value}{${path}}`);
      setPickerOpen(false);
    },
    [onValueChange, value],
  );

  return (
    <div className="space-y-1.5">
      <span className="font-mono text-xs font-medium">{configKey}</span>
      <div className="flex items-start gap-1.5">
        {multiline ? (
          <Textarea
            className="min-h-24 font-mono text-xs focus-visible:ring-step/40"
            placeholder={placeholder}
            value={value}
            onChange={handleInputChange}
          />
        ) : (
          <Input
            className="h-8 font-mono text-xs focus-visible:ring-step/40"
            placeholder={placeholder}
            value={value}
            onChange={handleInputChange}
          />
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-8 shrink-0"
          onClick={() => setPickerOpen(true)}
          title="Browse attributes"
          aria-label={`Browse attributes for ${configKey}`}
        >
          <Search className="size-3.5" aria-hidden />
        </Button>
      </div>
      {children}
      {!value && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      <AttributePathPicker
        open={pickerOpen}
        onClose={handleClosePicker}
        onSelect={handleSelect}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />
    </div>
  );
}
