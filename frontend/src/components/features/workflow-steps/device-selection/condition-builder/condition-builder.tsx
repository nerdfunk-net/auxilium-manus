"use client";

import { useCallback, useState } from "react";
import { Plus, Trash2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDeviceSelectionFieldOptionsQuery } from "@/hooks/queries/use-device-selection-field-options-query";
import { useDeviceSelectionFieldValuesQuery } from "@/hooks/queries/use-device-selection-field-values-query";

import {
  emptyTree,
  isCondition,
  isGroup,
  type FilterCondition,
  type FilterGroup,
  type FilterItem,
  type FilterTree,
} from "./types";

interface ConditionRowProps {
  condition: FilterCondition;
  nautobot_url: string;
  nautobot_token: string;
  fields: { value: string; label: string }[];
  operators: { value: string; label: string }[];
  onUpdate: (updated: FilterCondition) => void;
  onRemove: () => void;
}

function ConditionRow({
  condition,
  nautobot_url,
  nautobot_token,
  fields,
  operators,
  onUpdate,
  onRemove,
}: ConditionRowProps) {
  const { data: valuesData } = useDeviceSelectionFieldValuesQuery({
    nautobot_url,
    nautobot_token,
    field: condition.field,
    enabled: Boolean(condition.field),
  });

  const values = valuesData?.values ?? [];
  const inputType = valuesData?.input_type ?? "text";

  return (
    <div className="flex items-center gap-2 rounded border bg-muted/30 p-2">
      <Select
        value={condition.field}
        onValueChange={(v) => onUpdate({ ...condition, field: v, value: "" })}
      >
        <SelectTrigger className="h-7 w-36 text-xs">
          <SelectValue placeholder="Field..." />
        </SelectTrigger>
        <SelectContent>
          {fields.map((f) => (
            <SelectItem key={f.value} value={f.value} className="text-xs">
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={condition.operator}
        onValueChange={(v) => onUpdate({ ...condition, operator: v })}
      >
        <SelectTrigger className="h-7 w-28 text-xs">
          <SelectValue placeholder="Operator..." />
        </SelectTrigger>
        <SelectContent>
          {operators.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-xs">
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {inputType === "select" && values.length > 0 ? (
        <Select
          value={condition.value}
          onValueChange={(v) => onUpdate({ ...condition, value: v })}
        >
          <SelectTrigger className="h-7 min-w-0 flex-1 text-xs">
            <SelectValue placeholder="Select value..." />
          </SelectTrigger>
          <SelectContent>
            {values.map((v) => (
              <SelectItem key={v} value={v} className="text-xs">
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : inputType === "boolean" ? (
        <Select
          value={condition.value}
          onValueChange={(v) => onUpdate({ ...condition, value: v })}
        >
          <SelectTrigger className="h-7 min-w-0 flex-1 text-xs">
            <SelectValue placeholder="Select..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true" className="text-xs">True</SelectItem>
            <SelectItem value="false" className="text-xs">False</SelectItem>
          </SelectContent>
        </Select>
      ) : (
        <input
          className="h-7 min-w-0 flex-1 rounded border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder={condition.field ? "Value..." : "Select a field first"}
          disabled={!condition.field}
          value={condition.value}
          onChange={(e) => onUpdate({ ...condition, value: e.target.value })}
        />
      )}

      <Button
        size="sm"
        variant="ghost"
        className="h-7 w-7 shrink-0 p-0 text-muted-foreground hover:text-destructive"
        onClick={onRemove}
        type="button"
        aria-label="Remove condition"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

interface GroupBlockProps {
  group: FilterGroup;
  depth: number;
  nautobot_url: string;
  nautobot_token: string;
  fields: { value: string; label: string }[];
  operators: { value: string; label: string }[];
  onUpdate: (updated: FilterGroup) => void;
  onRemove?: () => void;
}

function GroupBlock({
  group,
  depth,
  nautobot_url,
  nautobot_token,
  fields,
  operators,
  onUpdate,
  onRemove,
}: GroupBlockProps) {
  const addCondition = useCallback(() => {
    const newCondition: FilterCondition = {
      id: crypto.randomUUID(),
      field: "",
      operator: "equals",
      value: "",
    };
    onUpdate({ ...group, items: [...group.items, newCondition] });
  }, [group, onUpdate]);

  const addGroup = useCallback(() => {
    const newGroup: FilterGroup = {
      id: crypto.randomUUID(),
      logic: "AND",
      negate: false,
      items: [],
    };
    onUpdate({ ...group, items: [...group.items, newGroup] });
  }, [group, onUpdate]);

  const updateItem = useCallback(
    (index: number, updated: FilterItem) => {
      const items = group.items.map((item, i) => (i === index ? updated : item));
      onUpdate({ ...group, items });
    },
    [group, onUpdate],
  );

  const removeItem = useCallback(
    (index: number) => {
      const items = group.items.filter((_, i) => i !== index);
      onUpdate({ ...group, items });
    },
    [group, onUpdate],
  );

  const isRoot = depth === 0;

  return (
    <div className={`space-y-2 ${!isRoot ? "rounded border border-dashed p-2" : ""}`}>
      {/* Group header */}
      <div className="flex items-center gap-2">
        {!isRoot && (
          <Badge variant="outline" className="text-[10px]">
            Group
          </Badge>
        )}
        <Select
          value={group.logic}
          onValueChange={(v) => onUpdate({ ...group, logic: v as "AND" | "OR" })}
        >
          <SelectTrigger className="h-6 w-16 text-[10px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="AND" className="text-xs">AND</SelectItem>
            <SelectItem value="OR" className="text-xs">OR</SelectItem>
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <input
            id={`negate-${group.id}`}
            type="checkbox"
            checked={group.negate}
            onChange={(e) => onUpdate({ ...group, negate: e.target.checked })}
            className="h-3.5 w-3.5 rounded accent-primary"
          />
          <label htmlFor={`negate-${group.id}`} className="cursor-pointer text-[10px] text-muted-foreground">
            Negate (NOT)
          </label>
        </div>

        <div className="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-[10px]"
            onClick={addCondition}
            type="button"
          >
            <Plus className="mr-0.5 h-3 w-3" />
            Condition
          </Button>
          {depth < 2 && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10px]"
              onClick={addGroup}
              type="button"
            >
              <Plus className="mr-0.5 h-3 w-3" />
              Group
            </Button>
          )}
          {!isRoot && onRemove && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
              onClick={onRemove}
              type="button"
              aria-label="Remove group"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>

      {/* Items */}
      {group.items.length === 0 && (
        <p className="py-2 text-center text-[11px] text-muted-foreground">
          No conditions yet. Add a condition or group above.
        </p>
      )}
      {group.items.map((item, index) => (
        <div key={item.id}>
          {index > 0 && (
            <div className="flex items-center gap-2 py-1">
              <div className="h-px flex-1 bg-border" />
              <span className="text-[10px] font-medium text-muted-foreground">
                {group.logic}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
          )}
          {isCondition(item) ? (
            <ConditionRow
              condition={item}
              nautobot_url={nautobot_url}
              nautobot_token={nautobot_token}
              fields={fields}
              operators={operators}
              onUpdate={(updated) => updateItem(index, updated)}
              onRemove={() => removeItem(index)}
            />
          ) : (
            <GroupBlock
              group={item}
              depth={depth + 1}
              nautobot_url={nautobot_url}
              nautobot_token={nautobot_token}
              fields={fields}
              operators={operators}
              onUpdate={(updated) => updateItem(index, updated)}
              onRemove={() => removeItem(index)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

interface ConditionBuilderProps {
  tree: FilterTree;
  nautobot_url: string;
  nautobot_token: string;
  onChange: (tree: FilterTree) => void;
}

export function ConditionBuilder({
  tree,
  nautobot_url,
  nautobot_token,
  onChange,
}: ConditionBuilderProps) {
  const { data: fieldOptions } = useDeviceSelectionFieldOptionsQuery();
  const fields = fieldOptions?.fields ?? [];
  const operators = fieldOptions?.operators ?? [];

  const handleReset = useCallback(() => {
    onChange(emptyTree());
  }, [onChange]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Adding conditions to:{" "}
          <span className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
            Root
          </span>
        </p>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 gap-1 px-2 text-[10px] text-muted-foreground"
          onClick={handleReset}
          type="button"
        >
          <RefreshCw className="h-3 w-3" />
          Reset
        </Button>
      </div>

      <GroupBlock
        group={tree}
        depth={0}
        nautobot_url={nautobot_url}
        nautobot_token={nautobot_token}
        fields={fields}
        operators={operators}
        onUpdate={onChange}
      />
    </div>
  );
}
