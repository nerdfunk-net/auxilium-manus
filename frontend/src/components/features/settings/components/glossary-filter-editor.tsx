"use client";

import { Plus, Trash2 } from "lucide-react";
import { useCallback } from "react";

import type {
  GlossaryCondition,
  GlossaryFilter,
  GlossaryGroup,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { operatorRuleForField } from "@/components/features/inventory/utils/field-operators";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetNautobotDevicesFieldValuesQuery } from "@/hooks/queries/use-get-nautobot-devices-field-values-query";

const CUSTOM_FIELD = "cf_";
const FIELDS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "name", label: "Name" },
  { value: "location", label: "Location" },
  { value: "role", label: "Role" },
  { value: "status", label: "Status" },
  { value: "tag", label: "Tag" },
  { value: "device_type", label: "Device type" },
  { value: "manufacturer", label: "Manufacturer" },
  { value: "platform", label: "Platform" },
  { value: "has_primary", label: "Has primary IP" },
  { value: "ip_prefix", label: "IP prefix" },
  { value: "primary_prefix", label: "Primary IP prefix" },
  { value: CUSTOM_FIELD, label: "Custom field" },
];
const VALUE_LIST_FIELDS = new Set([
  "location",
  "role",
  "status",
  "tag",
  "device_type",
  "manufacturer",
  "platform",
]);
const DEFAULT_OPERATORS = [
  { value: "equals", label: "Equals" },
  { value: "contains", label: "Contains" },
];
const MAX_CONDITIONS = 20;
const MAX_GROUPS = 10;

export const EMPTY_GLOSSARY_FILTER: GlossaryFilter = {
  logic: "AND",
  conditions: [{ field: "role", operator: "equals", value: "" }],
  groups: [],
};

function selectKey(field: string): string {
  return field.startsWith(CUSTOM_FIELD) ? CUSTOM_FIELD : field;
}

interface LogicSelectProps {
  value: "AND" | "OR";
  onChange: (value: "AND" | "OR") => void;
  label: string;
}

function LogicSelect({ value, onChange, label }: LogicSelectProps) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as "AND" | "OR")}>
      <SelectTrigger className="w-24" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="AND">All of</SelectItem>
        <SelectItem value="OR">Any of</SelectItem>
      </SelectContent>
    </Select>
  );
}

interface ConditionRowProps {
  condition: GlossaryCondition;
  sourceId: string;
  index: number;
  onChange: (next: GlossaryCondition) => void;
  onRemove: () => void;
}

function ConditionRow({
  condition,
  sourceId,
  index,
  onChange,
  onRemove,
}: ConditionRowProps) {
  const rule = operatorRuleForField(condition.field);
  const operators = rule.options ?? DEFAULT_OPERATORS;
  const listId = `glossary-values-${index}-${condition.field}`;
  const { data } = useGetNautobotDevicesFieldValuesQuery({
    sourceId,
    field: condition.field,
    enabled: VALUE_LIST_FIELDS.has(condition.field),
  });

  const handleField = (picked: string) => {
    const field = picked === CUSTOM_FIELD ? CUSTOM_FIELD : picked;
    const next = operatorRuleForField(field);
    onChange({
      field,
      operator: next.forcedOperator ?? next.options?.[0]?.value ?? "equals",
      value: "",
    });
  };

  return (
    <div className="flex items-center gap-2">
      <Select value={selectKey(condition.field)} onValueChange={handleField}>
        <SelectTrigger
          className="w-44"
          aria-label={`Condition ${index + 1} field`}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELDS.map((f) => (
            <SelectItem key={f.value} value={f.value}>
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {condition.field.startsWith(CUSTOM_FIELD) && (
        <Input
          className="w-32"
          aria-label={`Condition ${index + 1} custom field name`}
          placeholder="name"
          value={condition.field.slice(CUSTOM_FIELD.length)}
          onChange={(e) =>
            onChange({
              ...condition,
              field: `${CUSTOM_FIELD}${e.target.value.replace(/[^A-Za-z0-9_]/g, "")}`,
            })
          }
        />
      )}
      <Select
        value={condition.operator}
        onValueChange={(operator) => onChange({ ...condition, operator })}
      >
        <SelectTrigger
          className="w-36"
          aria-label={`Condition ${index + 1} operator`}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {operators.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        className="flex-1"
        aria-label={`Condition ${index + 1} value`}
        list={listId}
        value={condition.value}
        maxLength={200}
        onChange={(e) => onChange({ ...condition, value: e.target.value })}
      />
      {data && (
        <datalist id={listId}>
          {data.values.map((v) => (
            <option key={v.value} value={v.value} />
          ))}
        </datalist>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onRemove}
        aria-label={`Remove condition ${index + 1}`}
      >
        <Trash2 className="size-4" />
      </Button>
    </div>
  );
}

interface ConditionListProps {
  conditions: GlossaryCondition[];
  sourceId: string;
  onChange: (next: GlossaryCondition[]) => void;
}

function ConditionList({ conditions, sourceId, onChange }: ConditionListProps) {
  return (
    <div className="space-y-2">
      {conditions.map((condition, index) => (
        <ConditionRow
          // Rows are edited in place and reordered never, so the index is a stable key.
          key={index}
          condition={condition}
          sourceId={sourceId}
          index={index}
          onChange={(next) =>
            onChange(conditions.map((c, i) => (i === index ? next : c)))
          }
          onRemove={() => onChange(conditions.filter((_, i) => i !== index))}
        />
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={conditions.length >= MAX_CONDITIONS}
        onClick={() =>
          onChange([
            ...conditions,
            { field: "role", operator: "equals", value: "" },
          ])
        }
      >
        <Plus className="mr-1 size-4" />
        Add condition
      </Button>
    </div>
  );
}

interface GlossaryFilterEditorProps {
  value: GlossaryFilter;
  sourceId: string;
  onChange: (next: GlossaryFilter) => void;
}

/** Root conditions plus groups (each optionally excluded), one level deep like the assistant's filter. */
export function GlossaryFilterEditor({
  value,
  sourceId,
  onChange,
}: GlossaryFilterEditorProps) {
  const setGroup = useCallback(
    (index: number, next: GlossaryGroup | null) =>
      onChange({
        ...value,
        groups: next
          ? value.groups.map((g, i) => (i === index ? next : g))
          : value.groups.filter((_, i) => i !== index),
      }),
    [onChange, value],
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        Match
        <LogicSelect
          label="Match logic"
          value={value.logic}
          onChange={(logic) => onChange({ ...value, logic })}
        />
        of the following
      </div>
      <ConditionList
        conditions={value.conditions}
        sourceId={sourceId}
        onChange={(conditions) => onChange({ ...value, conditions })}
      />
      {value.groups.map((group, index) => (
        <div key={index} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center gap-3 text-sm">
            <span>Group {index + 1}:</span>
            <LogicSelect
              label={`Group ${index + 1} logic`}
              value={group.logic}
              onChange={(logic) => setGroup(index, { ...group, logic })}
            />
            <label className="flex items-center gap-2">
              <Checkbox
                checked={group.negate}
                onCheckedChange={(checked) =>
                  setGroup(index, { ...group, negate: checked === true })
                }
                aria-label={`Exclude group ${index + 1}`}
              />
              Exclude devices matching this group
            </label>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="ml-auto"
              onClick={() => setGroup(index, null)}
              aria-label={`Remove group ${index + 1}`}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
          <ConditionList
            conditions={group.conditions}
            sourceId={sourceId}
            onChange={(conditions) => setGroup(index, { ...group, conditions })}
          />
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={value.groups.length >= MAX_GROUPS}
        onClick={() =>
          onChange({
            ...value,
            groups: [
              ...value.groups,
              {
                logic: "AND",
                negate: false,
                conditions: [{ field: "role", operator: "equals", value: "" }],
              },
            ],
          })
        }
      >
        <Plus className="mr-1 size-4" />
        Add group
      </Button>
    </div>
  );
}
