"use client";

import { Plus } from "lucide-react";
import type { DragEvent } from "react";

import { Button } from "@/components/ui/button";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { ADD_STEP_BUTTON_DRAG_MIME_TYPE } from "../utils/step-catalog";

interface AddStepButtonProps {
  /** Icon-only variant for the collapsed properties panel. */
  compact?: boolean;
}

/**
 * Opens the Steps library. Dragging it onto the canvas stores the drop point
 * (see WorkflowCanvas handleDrop); a plain click opens the library without one.
 * The drag source is a wrapper <div>, because Firefox does not reliably start
 * a drag from a <button>.
 */
export function AddStepButton({ compact = false }: AddStepButtonProps) {
  const openStepLibrary = useWorkflowBuilderStore((state) => state.openStepLibrary);

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.setData(ADD_STEP_BUTTON_DRAG_MIME_TYPE, "add-step");
    event.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div className="cursor-grab" draggable onDragStart={handleDragStart}>
      {compact ? (
        <Button
          aria-label="Add new Step"
          onClick={() => openStepLibrary(null)}
          size="icon"
          title="Add new Step"
          type="button"
        >
          <Plus className="size-4" aria-hidden />
        </Button>
      ) : (
        <Button onClick={() => openStepLibrary(null)} type="button">
          <Plus className="size-4" aria-hidden />
          Add new Step
        </Button>
      )}
    </div>
  );
}
