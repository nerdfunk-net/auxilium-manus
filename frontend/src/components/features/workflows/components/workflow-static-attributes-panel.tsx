"use client";

import { ListChecks, Plus, Trash2 } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import type {
  StaticAttributeDef,
  StaticAttributeType,
} from "../types/workflow-persistence";

interface WorkflowStaticAttributesPanelProps {
  value: StaticAttributeDef[];
  onChange: (next: StaticAttributeDef[]) => void;
}

const DEFAULT_NEW_ATTRIBUTE: StaticAttributeDef = {
  name: "",
  type: "string",
  default: undefined,
  required: false,
};

function defaultForType(type: StaticAttributeType): string | number | boolean | undefined {
  if (type === "boolean") return false;
  if (type === "number") return undefined;
  return undefined;
}

export function WorkflowStaticAttributesPanel({
  value,
  onChange,
}: WorkflowStaticAttributesPanelProps) {
  const updateAt = useCallback(
    (index: number, patch: Partial<StaticAttributeDef>) => {
      onChange(value.map((attr, i) => (i === index ? { ...attr, ...patch } : attr)));
    },
    [value, onChange],
  );

  const removeAt = useCallback(
    (index: number) => {
      onChange(value.filter((_, i) => i !== index));
    },
    [value, onChange],
  );

  const addAttribute = useCallback(() => {
    onChange([...value, { ...DEFAULT_NEW_ATTRIBUTE }]);
  }, [value, onChange]);

  const namesSeen = new Set<string>();
  const duplicateIndexes = new Set<number>();
  value.forEach((attr, index) => {
    const trimmed = attr.name.trim();
    if (trimmed && namesSeen.has(trimmed)) duplicateIndexes.add(index);
    namesSeen.add(trimmed);
  });

  return (
    <div>
      <div className="flex items-center gap-2">
        <ListChecks className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          Static Attributes
        </span>
      </div>
      <p className="mt-1.5 text-[11.5px] text-muted-foreground">
        Values an operator enters when starting a run manually. Available to every
        step as <code className="font-mono">{"{run_input.<name>}"}</code>.
      </p>

      <div className="mt-3 space-y-2.5">
        {value.map((attr, index) => {
          const isDuplicate = duplicateIndexes.has(index);
          return (
            <div
              key={index}
              className="space-y-1.5 rounded-lg border border-slate-200 bg-white p-2.5"
            >
              <div className="flex items-center gap-1.5">
                <Input
                  aria-label="Attribute name"
                  className="h-7 flex-1 font-mono text-xs"
                  onChange={(event) => updateAt(index, { name: event.target.value })}
                  placeholder="attribute_name"
                  value={attr.name}
                />
                <Button
                  aria-label="Remove attribute"
                  className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => removeAt(index)}
                  size="icon"
                  type="button"
                  variant="ghost"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </div>
              {isDuplicate ? (
                <p className="text-[11px] text-amber-600">Duplicate attribute name.</p>
              ) : null}
              {!attr.name.trim() ? (
                <p className="text-[11px] text-amber-600">Name is required.</p>
              ) : null}

              <div className="flex items-center gap-1.5">
                <Select
                  value={attr.type}
                  onValueChange={(next) =>
                    updateAt(index, {
                      type: next as StaticAttributeType,
                      default: defaultForType(next as StaticAttributeType),
                    })
                  }
                >
                  <SelectTrigger className="h-7 flex-1 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="string">String</SelectItem>
                    <SelectItem value="number">Number</SelectItem>
                    <SelectItem value="boolean">Boolean</SelectItem>
                  </SelectContent>
                </Select>

                {attr.type === "boolean" ? (
                  <div className="flex h-7 flex-1 items-center justify-between rounded-md border border-input px-2">
                    <Label className="text-[11px] text-muted-foreground">Default</Label>
                    <Switch
                      checked={attr.default === true}
                      onCheckedChange={(checked) => updateAt(index, { default: checked })}
                    />
                  </div>
                ) : (
                  <Input
                    aria-label="Default value"
                    className="h-7 flex-1 text-xs"
                    onChange={(event) =>
                      updateAt(index, {
                        default:
                          attr.type === "number"
                            ? event.target.value === ""
                              ? undefined
                              : Number(event.target.value)
                            : event.target.value,
                      })
                    }
                    placeholder="Default (optional)"
                    type={attr.type === "number" ? "number" : "text"}
                    value={
                      attr.default === undefined || attr.default === null
                        ? ""
                        : String(attr.default)
                    }
                  />
                )}
              </div>

              <div className="flex items-center justify-between gap-2 pt-0.5">
                <Label className="text-[11px] text-muted-foreground">
                  Required (no default)
                </Label>
                <Switch
                  checked={attr.required}
                  onCheckedChange={(checked) => updateAt(index, { required: checked })}
                />
              </div>
            </div>
          );
        })}
      </div>

      <Button
        className="mt-2.5 h-7 w-full gap-1.5 text-xs"
        onClick={addAttribute}
        size="sm"
        type="button"
        variant="outline"
      >
        <Plus className="size-3.5" aria-hidden />
        Add attribute
      </Button>
    </div>
  );
}
