"use client";

import { Search } from "lucide-react";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { AttributePathPreview } from "@/components/features/workflow-steps/shared/attribute-path-preview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { ValueSourceConfig, ValueSourceType } from "./config";

export interface TemplateOption {
  id: number;
  name: string;
}

/** Canvas context the attribute preview needs; passed straight through from the ConfigPanel props. */
export type CanvasGraphProps = Pick<
  PluginConfigPanelProps,
  "nodeId" | "workflowNodes" | "workflowEdges"
>;

/** What every value-source editor on the panel shares (one template list, one canvas). */
export interface ValueSourceSharedProps {
  templates: readonly TemplateOption[];
  templatesLoading: boolean;
  templatesError: boolean;
  graph: CanvasGraphProps;
}

interface ValueSourceFieldsProps extends ValueSourceSharedProps {
  value: ValueSourceConfig;
  onChange: (next: ValueSourceConfig) => void;
  onBrowse: () => void;
  onPreviewTemplate: () => void;
  /** Disambiguates the icon button for screen readers when several editors are on screen. */
  ariaLabel: string;
}

/** Device attribute / rendered template picker for one value source. */
export function ValueSourceFields({
  value,
  onChange,
  onBrowse,
  onPreviewTemplate,
  ariaLabel,
  templates,
  templatesLoading,
  templatesError,
  graph,
}: ValueSourceFieldsProps) {
  const selectedTemplateId = value.template_id !== null ? String(value.template_id) : "";
  const selectedTemplateMissing =
    value.template_id !== null &&
    !templatesLoading &&
    !templatesError &&
    !templates.some((template) => template.id === value.template_id);

  return (
    <>
      <Select
        value={value.type}
        onValueChange={(next) => onChange({ ...value, type: next as ValueSourceType })}
      >
        <SelectTrigger className="h-8 w-full text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="attribute" className="text-xs">
            Device attribute
          </SelectItem>
          <SelectItem value="template" className="text-xs">
            Rendered template
          </SelectItem>
        </SelectContent>
      </Select>

      {value.type === "attribute" ? (
        <div className="space-y-1.5 pl-1">
          <div className="flex items-center gap-1.5">
            <Input
              value={value.attribute_path}
              onChange={(event) => onChange({ ...value, attribute_path: event.target.value })}
              placeholder="tacacs.shared_secret"
              className="h-8 font-mono text-xs"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8 shrink-0"
              onClick={onBrowse}
              title="Browse attributes"
              aria-label={`Browse attributes for ${ariaLabel}`}
            >
              <Search className="size-3.5" aria-hidden />
            </Button>
          </div>
          <AttributePathPreview
            path={value.attribute_path}
            nodeId={graph.nodeId}
            workflowNodes={graph.workflowNodes ?? []}
            workflowEdges={graph.workflowEdges ?? []}
          />
        </div>
      ) : (
        <div className="space-y-1.5 pl-1">
          <Select
            value={selectedTemplateId}
            onValueChange={(next) => onChange({ ...value, template_id: Number(next) })}
            disabled={templatesLoading || templates.length === 0}
          >
            <SelectTrigger className="h-8 w-full text-xs">
              <SelectValue
                placeholder={templatesLoading ? "Loading templates…" : "Select a stored template"}
              />
            </SelectTrigger>
            <SelectContent>
              {templates.map((template) => (
                <SelectItem key={template.id} value={String(template.id)} className="text-xs">
                  {template.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {templatesError ? (
            <p className="text-[11px] leading-4 text-destructive">
              Failed to load stored templates.
            </p>
          ) : null}
          {!templatesLoading && !templatesError && templates.length === 0 ? (
            <p className="text-[11px] leading-4 text-muted-foreground">
              No stored Jinja2 templates yet. Create one in the Templates section first.
            </p>
          ) : null}
          {selectedTemplateMissing ? (
            <p className="text-[11px] leading-4 text-destructive">
              The previously selected template no longer exists. Pick another one.
            </p>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 w-full text-xs"
            disabled={value.template_id === null || selectedTemplateMissing}
            onClick={onPreviewTemplate}
          >
            Preview Template
          </Button>
        </div>
      )}
    </>
  );
}
