"use client";

import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TabsContent } from "@/components/ui/tabs";

import type { PluginDefinition } from "../types/plugin-registry";
import type { HandleSide, PersistedCanvasNode } from "../types/workflow-canvas";

const MODAL_TAB_CONTENT_CLASS = "mt-0 min-h-0 flex-1 overflow-y-auto p-6";

const HANDLE_SIDE_OPTIONS: { value: HandleSide; label: string }[] = [
  { value: "top", label: "Top" },
  { value: "bottom", label: "Bottom" },
  { value: "left", label: "Left" },
  { value: "right", label: "Right" },
];

/** Node types whose canvas handles attach to a configurable side. */
const HANDLE_SIDE_CONFIGURABLE_NODE_TYPES = new Set(["workflowNode", "funnelNode"]);

interface NodeConfigGeneralTabProps {
  activeNode: PersistedCanvasNode;
  plugin: PluginDefinition | undefined;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  onNodeIncomeHandleSideChange?: (nodeId: string, side: HandleSide) => void;
  onNodeOutcomeHandleSideChange?: (nodeId: string, side: HandleSide) => void;
}

export function NodeConfigGeneralTab({
  activeNode,
  plugin,
  onNodeTitleChange,
  onNodeIncomeHandleSideChange,
  onNodeOutcomeHandleSideChange,
}: NodeConfigGeneralTabProps) {
  return (
    <TabsContent className={MODAL_TAB_CONTENT_CLASS} value="general">
      <div className="max-w-sm space-y-1.5">
        <Label className="text-xs font-medium" htmlFor="modal-step-name">
          Step name
        </Label>
        <Input
          id="modal-step-name"
          value={activeNode.data.title}
          onChange={(event) => onNodeTitleChange?.(activeNode.id, event.target.value)}
          onBlur={(event) => {
            const trimmed = event.target.value.trim();
            const fallback = plugin?.name ?? activeNode.data.title;
            if (!trimmed) {
              onNodeTitleChange?.(activeNode.id, fallback);
            } else if (trimmed !== event.target.value) {
              onNodeTitleChange?.(activeNode.id, trimmed);
            }
          }}
          placeholder={plugin?.name ?? "Step name"}
          className="h-8 text-sm"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Shown on the canvas and in run results.
        </p>
      </div>

      {HANDLE_SIDE_CONFIGURABLE_NODE_TYPES.has(activeNode.type ?? "") ? (
        <div className="mt-4 flex max-w-sm gap-3">
          <div className="flex-1 space-y-1.5">
            <Label className="text-xs font-medium" htmlFor="modal-step-income-side">
              Income position
            </Label>
            <Select
              value={activeNode.data.incomeHandleSide ?? "left"}
              onValueChange={(value) =>
                onNodeIncomeHandleSideChange?.(activeNode.id, value as HandleSide)
              }
            >
              <SelectTrigger className="h-8 text-sm" id="modal-step-income-side">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HANDLE_SIDE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex-1 space-y-1.5">
            <Label className="text-xs font-medium" htmlFor="modal-step-outcome-side">
              Outcome position
            </Label>
            <Select
              value={activeNode.data.outcomeHandleSide ?? "right"}
              onValueChange={(value) =>
                onNodeOutcomeHandleSideChange?.(activeNode.id, value as HandleSide)
              }
            >
              <SelectTrigger className="h-8 text-sm" id="modal-step-outcome-side">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HANDLE_SIDE_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.value}
                    disabled={option.value === (activeNode.data.incomeHandleSide ?? "left")}
                    value={option.value}
                  >
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      ) : null}
      {HANDLE_SIDE_CONFIGURABLE_NODE_TYPES.has(activeNode.type ?? "") ? (
        <p className="mt-1.5 max-w-sm text-[11px] leading-4 text-muted-foreground">
          Which sides this step&apos;s input and outcome handles attach to. Income takes priority
          — outcome cannot use the same side.
        </p>
      ) : null}
    </TabsContent>
  );
}
