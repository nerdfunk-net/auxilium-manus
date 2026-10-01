"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";

import { AttributePathPicker } from "./attribute-path-picker";

interface ExpressionFieldProps {
  configKey: string;
  value: string;
  placeholder: string;
  onValueChange: (value: string) => void;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
  /** Mask fixed values (e.g. keys). `{path}` expressions stay readable. */
  secret?: boolean;
  children?: React.ReactNode;
}

const EXPRESSION_PATTERN = /^\s*\{.*\}\s*$/;

/**
 * Text input for a fixed value or a `{path.to.value}` expression, with a
 * "Browse attributes" button that opens the shared attribute path picker and
 * writes the chosen path back as `{path}`.
 */
export function ExpressionField({
  configKey,
  value,
  placeholder,
  onValueChange,
  nodeId,
  workflowNodes,
  workflowEdges,
  secret = false,
  children,
}: ExpressionFieldProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const inputType = useMemo(
    () => (secret && !EXPRESSION_PATTERN.test(value) ? "password" : "text"),
    [secret, value],
  );

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => onValueChange(event.target.value),
    [onValueChange],
  );
  const handleClosePicker = useCallback(() => setPickerOpen(false), []);
  const handleSelect = useCallback(
    (path: string) => {
      onValueChange(`{${path}}`);
      setPickerOpen(false);
    },
    [onValueChange],
  );

  return (
    <div className="space-y-1.5">
      <span className="font-mono text-xs font-medium">{configKey}</span>
      <div className="flex items-center gap-1.5">
        <Input
          className="h-9 font-mono text-xs"
          placeholder={placeholder}
          type={inputType}
          value={value}
          onChange={handleInputChange}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-9 shrink-0"
          onClick={() => setPickerOpen(true)}
          title="Browse attributes"
          aria-label={`Browse attributes for ${configKey}`}
        >
          <Search className="size-3.5" aria-hidden />
        </Button>
      </div>
      {children}
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
