"use client";

import { useCallback, useMemo, useState } from "react";
import { CirclePlus, Plus, RefreshCw, Settings2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetNautobotDevicesFieldOptionsQuery } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";
import {
  useGetNautobotDevicesFieldValuesQuery,
  type FieldValueOption,
} from "@/hooks/queries/use-get-nautobot-devices-field-values-query";

import { formatLogicalExpression } from "./format-logical-expression";
import {
  emptyTree,
  isCondition,
  type FilterCondition,
  type FilterGroup,
  type FilterItem,
  type FilterTree,
} from "./types";

const IP_PREFIX_OPERATORS = [
  { value: "within_include", label: "Within (include)" },
  { value: "within", label: "Within" },
  { value: "exact", label: "Exact" },
];

const EMPTY_DRAFT: FilterCondition = {
  id: "",
  field: "",
  operator: "equals",
  value: "",
};

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
  const { data: valuesData } = useGetNautobotDevicesFieldValuesQuery({
    nautobot_url,
    nautobot_token,
    field: condition.field,
    enabled: Boolean(condition.field),
  });

  const valueOptions: FieldValueOption[] = valuesData?.values ?? [];
  const inputType = valuesData?.input_type ?? "text";
  const rowOperators =
    condition.field === "ip_prefix" ? IP_PREFIX_OPERATORS : operators;

  return (
    <div className="flex items-end gap-2 rounded-lg border border-slate-200 bg-white p-2">
      <Select
        value={condition.field}
        onValueChange={(v) =>
          onUpdate({
            ...condition,
            field: v,
            value: "",
            operator: v === "ip_prefix" ? "within_include" : "equals",
          })
        }
      >
        <SelectTrigger className="h-8 w-32 rounded-lg text-xs">
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
        <SelectTrigger className="h-8 w-28 rounded-lg text-xs">
          <SelectValue placeholder="Operator..." />
        </SelectTrigger>
        <SelectContent>
          {rowOperators.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-xs">
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {inputType === "select" && valueOptions.length > 0 ? (
        <Select
          value={condition.value}
          onValueChange={(v) => {
            if (condition.field === "custom_fields") {
              onUpdate({ ...condition, field: v, value: "", operator: "equals" });
              return;
            }
            onUpdate({ ...condition, value: v });
          }}
        >
          <SelectTrigger className="h-8 min-w-0 flex-1 rounded-lg text-xs">
            <SelectValue placeholder="Select value..." />
          </SelectTrigger>
          <SelectContent>
            {valueOptions.map((option) => (
              <SelectItem key={option.value} value={option.value} className="text-xs">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : inputType === "boolean" ? (
        <Select
          value={condition.value}
          onValueChange={(v) => onUpdate({ ...condition, value: v })}
        >
          <SelectTrigger className="h-8 min-w-0 flex-1 rounded-lg text-xs">
            <SelectValue placeholder="Select..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true" className="text-xs">
              True
            </SelectItem>
            <SelectItem value="false" className="text-xs">
              False
            </SelectItem>
          </SelectContent>
        </Select>
      ) : (
        <input
          className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-background px-2 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400/40"
          placeholder={condition.field ? "Value..." : "Select a field first"}
          disabled={!condition.field}
          value={condition.value}
          onChange={(e) => onUpdate({ ...condition, value: e.target.value })}
        />
      )}

      <Button
        className="h-8 w-8 shrink-0 rounded-lg p-0 text-muted-foreground hover:text-destructive"
        onClick={onRemove}
        size="sm"
        type="button"
        variant="ghost"
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
    <div
      className={`space-y-2 ${!isRoot ? "rounded-lg border border-dashed border-slate-300 bg-white p-2" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {!isRoot ? (
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            Group
          </span>
        ) : null}
        <Select
          value={group.logic}
          onValueChange={(v) => onUpdate({ ...group, logic: v as "AND" | "OR" })}
        >
          <SelectTrigger className="h-7 w-16 rounded-lg text-[10px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="AND" className="text-xs">
              AND
            </SelectItem>
            <SelectItem value="OR" className="text-xs">
              OR
            </SelectItem>
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <input
            id={`negate-${group.id}`}
            type="checkbox"
            checked={group.negate}
            onChange={(e) => onUpdate({ ...group, negate: e.target.checked })}
            className="h-3.5 w-3.5 rounded accent-sky-500"
          />
          <label
            htmlFor={`negate-${group.id}`}
            className="cursor-pointer text-[10px] text-muted-foreground"
          >
            Negate (NOT)
          </label>
        </div>

        <div className="ml-auto flex items-center gap-1">
          <Button
            className="h-7 rounded-lg px-2 text-[10px]"
            onClick={addCondition}
            size="sm"
            type="button"
            variant="outline"
          >
            <Plus className="mr-0.5 h-3 w-3" />
            Condition
          </Button>
          {depth < 2 ? (
            <Button
              className="h-7 rounded-lg px-2 text-[10px]"
              onClick={addGroup}
              size="sm"
              type="button"
              variant="outline"
            >
              <Plus className="mr-0.5 h-3 w-3" />
              Group
            </Button>
          ) : null}
          {!isRoot && onRemove ? (
            <Button
              className="h-7 w-7 rounded-lg p-0 text-muted-foreground hover:text-destructive"
              onClick={onRemove}
              size="sm"
              type="button"
              variant="ghost"
              aria-label="Remove group"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          ) : null}
        </div>
      </div>

      {group.items.length === 0 ? (
        <p className="py-2 text-center text-[11px] text-muted-foreground">
          No conditions in this group.
        </p>
      ) : null}
      {group.items.map((item, index) => (
        <div key={item.id}>
          {index > 0 ? (
            <div className="flex items-center gap-2 py-1">
              <div className="h-px flex-1 bg-border" />
              <span className="text-[10px] font-medium text-muted-foreground">
                {group.logic}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
          ) : null}
          {isCondition(item) ? (
            <ConditionRow
              condition={item}
              fields={fields}
              nautobot_url={nautobot_url}
              nautobot_token={nautobot_token}
              operators={operators}
              onRemove={() => removeItem(index)}
              onUpdate={(updated) => updateItem(index, updated)}
            />
          ) : (
            <GroupBlock
              depth={depth + 1}
              fields={fields}
              group={item}
              nautobot_url={nautobot_url}
              nautobot_token={nautobot_token}
              operators={operators}
              onRemove={() => removeItem(index)}
              onUpdate={(updated) => updateItem(index, updated)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function wrapCondition(
  condition: FilterCondition,
  negate: boolean,
  logic: "AND" | "OR",
): FilterItem {
  if (!negate) return condition;
  return {
    id: crypto.randomUUID(),
    logic,
    negate: true,
    items: [condition],
  };
}

interface DraftConditionRowProps {
  draft: FilterCondition;
  connector: "AND" | "OR";
  negate: boolean;
  fields: { value: string; label: string }[];
  operators: { value: string; label: string }[];
  nautobot_url: string;
  nautobot_token: string;
  onDraftChange: (draft: FilterCondition) => void;
  onConnectorChange: (logic: "AND" | "OR") => void;
  onNegateChange: (negate: boolean) => void;
  onAddCondition: () => void;
  onAddGroup: () => void;
  onReset: () => void;
  onToggleTree: () => void;
  showTree: boolean;
}

function DraftConditionRow({
  draft,
  connector,
  negate,
  fields,
  operators,
  nautobot_url,
  nautobot_token,
  onDraftChange,
  onConnectorChange,
  onNegateChange,
  onAddCondition,
  onAddGroup,
  onReset,
  onToggleTree,
  showTree,
}: DraftConditionRowProps) {
  const { data: valuesData } = useGetNautobotDevicesFieldValuesQuery({
    nautobot_url,
    nautobot_token,
    field: draft.field,
    enabled: Boolean(draft.field),
  });

  const valueOptions: FieldValueOption[] = valuesData?.values ?? [];
  const inputType = valuesData?.input_type ?? "text";
  const rowOperators =
    draft.field === "ip_prefix" ? IP_PREFIX_OPERATORS : operators;

  const canAdd = Boolean(draft.field && draft.value);

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-[7rem] flex-1 space-y-1">
        <span className="text-[10px] font-medium text-muted-foreground">Field</span>
        <Select
          value={draft.field || undefined}
          onValueChange={(v) =>
            onDraftChange({
              ...draft,
              field: v,
              value: "",
              operator: v === "ip_prefix" ? "within_include" : "equals",
            })
          }
        >
          <SelectTrigger className="h-9 w-full rounded-lg bg-white text-xs">
            <SelectValue placeholder="Select field..." />
          </SelectTrigger>
          <SelectContent>
            {fields.map((f) => (
              <SelectItem key={f.value} value={f.value} className="text-xs">
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="min-w-[6rem] flex-1 space-y-1">
        <span className="text-[10px] font-medium text-muted-foreground">Operator</span>
        <Select
          value={draft.operator}
          onValueChange={(v) => onDraftChange({ ...draft, operator: v })}
        >
          <SelectTrigger className="h-9 w-full rounded-lg bg-white text-xs">
            <SelectValue placeholder="Equals" />
          </SelectTrigger>
          <SelectContent>
            {rowOperators.map((o) => (
              <SelectItem key={o.value} value={o.value} className="text-xs">
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="min-w-[8rem] flex-[1.5] space-y-1">
        <span className="text-[10px] font-medium text-muted-foreground">Value</span>
        {inputType === "select" && valueOptions.length > 0 ? (
          <Select
            value={draft.value || undefined}
            onValueChange={(v) => {
              if (draft.field === "custom_fields") {
                onDraftChange({ ...draft, field: v, value: "", operator: "equals" });
                return;
              }
              onDraftChange({ ...draft, value: v });
            }}
          >
            <SelectTrigger className="h-9 w-full rounded-lg bg-white text-xs">
              <SelectValue placeholder="Select value..." />
            </SelectTrigger>
            <SelectContent>
              {valueOptions.map((option) => (
                <SelectItem key={option.value} value={option.value} className="text-xs">
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : inputType === "boolean" ? (
          <Select
            value={draft.value || undefined}
            onValueChange={(v) => onDraftChange({ ...draft, value: v })}
          >
            <SelectTrigger className="h-9 w-full rounded-lg bg-white text-xs">
              <SelectValue placeholder="Select..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="true" className="text-xs">
                True
              </SelectItem>
              <SelectItem value="false" className="text-xs">
                False
              </SelectItem>
            </SelectContent>
          </Select>
        ) : (
          <input
            className="h-9 w-full rounded-lg border border-input bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400/40 disabled:cursor-not-allowed disabled:bg-muted/50"
            disabled={!draft.field}
            placeholder={draft.field ? "Enter value..." : "Select a field first"}
            value={draft.value}
            onChange={(e) => onDraftChange({ ...draft, value: e.target.value })}
          />
        )}
      </div>

      <div className="min-w-[5.5rem] space-y-1">
        <span className="text-[10px] font-medium text-muted-foreground">Connector</span>
        <Select
          value={connector}
          onValueChange={(v) => onConnectorChange(v as "AND" | "OR")}
        >
          <SelectTrigger className="h-9 w-full rounded-lg bg-white text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="AND" className="text-xs">
              AND
            </SelectItem>
            <SelectItem value="OR" className="text-xs">
              OR
            </SelectItem>
          </SelectContent>
        </Select>
        <div className="flex items-center gap-1 pt-0.5">
          <input
            checked={negate}
            className="h-3.5 w-3.5 rounded accent-sky-500"
            id="draft-negate"
            onChange={(e) => onNegateChange(e.target.checked)}
            type="checkbox"
          />
          <label
            className="cursor-pointer text-[10px] text-muted-foreground"
            htmlFor="draft-negate"
          >
            Negate (NOT)
          </label>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5 pb-0.5">
        <Button
          aria-label="Add condition"
          className="h-9 w-9 rounded-full bg-sky-500 p-0 text-white shadow-sm hover:bg-sky-600"
          disabled={!canAdd}
          onClick={onAddCondition}
          size="sm"
          type="button"
        >
          <Plus className="h-4 w-4" />
        </Button>
        <Button
          className="h-9 gap-1 rounded-lg border-slate-300 bg-white text-xs"
          onClick={onAddGroup}
          size="sm"
          type="button"
          variant="outline"
        >
          <CirclePlus className="h-3.5 w-3.5" />
          Group
        </Button>
        <Button
          aria-label="Reset filter"
          className="h-9 w-9 rounded-lg border-slate-300 bg-white p-0"
          onClick={onReset}
          size="sm"
          type="button"
          variant="outline"
        >
          <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
        </Button>
        <Button
          className="h-9 gap-1 rounded-lg border-slate-300 bg-white text-xs"
          onClick={onToggleTree}
          size="sm"
          type="button"
          variant={showTree ? "secondary" : "outline"}
        >
          <Settings2 className="h-3.5 w-3.5" />
          {showTree ? "Hide Tree" : "Show Tree"}
        </Button>
      </div>
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
  const { data: fieldOptions } = useGetNautobotDevicesFieldOptionsQuery();
  const fields = useMemo(() => fieldOptions?.fields ?? [], [fieldOptions?.fields]);
  const operators = useMemo(
    () => fieldOptions?.operators ?? [],
    [fieldOptions?.operators],
  );

  const [draft, setDraft] = useState<FilterCondition>({ ...EMPTY_DRAFT });
  const [draftNegate, setDraftNegate] = useState(false);
  const [showTree, setShowTree] = useState(false);

  const connector = tree.logic;

  const expression = useMemo(
    () => formatLogicalExpression(tree, fields, operators),
    [tree, fields, operators],
  );

  const handleReset = useCallback(() => {
    onChange(emptyTree());
    setDraft({ ...EMPTY_DRAFT });
    setDraftNegate(false);
    setShowTree(false);
  }, [onChange]);

  const handleAddCondition = useCallback(() => {
    if (!draft.field || !draft.value) return;

    const condition: FilterCondition = {
      id: crypto.randomUUID(),
      field: draft.field,
      operator: draft.operator,
      value: draft.value,
    };

    const item = wrapCondition(condition, draftNegate, tree.logic);
    onChange({
      ...tree,
      logic: connector,
      items: [...tree.items, item],
    });

    setDraft({ ...EMPTY_DRAFT });
    setDraftNegate(false);
  }, [draft, draftNegate, tree, connector, onChange]);

  const handleAddGroup = useCallback(() => {
    const newGroup: FilterGroup = {
      id: crypto.randomUUID(),
      logic: connector,
      negate: draftNegate,
      items: [],
    };
    onChange({
      ...tree,
      logic: connector,
      items: [...tree.items, newGroup],
    });
    setDraftNegate(false);
    setShowTree(true);
  }, [connector, draftNegate, tree, onChange]);

  const handleConnectorChange = useCallback(
    (logic: "AND" | "OR") => {
      onChange({ ...tree, logic });
    },
    [tree, onChange],
  );

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-sky-100/80 px-3 py-2 text-xs text-sky-900">
        Adding conditions to:{" "}
        <span className="inline-flex rounded-full border border-white bg-white px-2 py-0.5 font-medium text-sky-950 shadow-sm">
          Root
        </span>
      </div>

      <DraftConditionRow
        connector={connector}
        draft={draft}
        fields={fields}
        negate={draftNegate}
        nautobot_token={nautobot_token}
        nautobot_url={nautobot_url}
        operators={operators}
        showTree={showTree}
        onAddCondition={handleAddCondition}
        onAddGroup={handleAddGroup}
        onConnectorChange={handleConnectorChange}
        onDraftChange={setDraft}
        onNegateChange={setDraftNegate}
        onReset={handleReset}
        onToggleTree={() => setShowTree((v) => !v)}
      />

      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Logical Expression</p>
        <div className="min-h-[5.5rem] rounded-lg border border-slate-200 bg-white px-3 py-3">
          {expression ? (
            <p className="font-mono text-xs leading-relaxed text-foreground">{expression}</p>
          ) : (
            <p className="text-xs italic text-muted-foreground">
              No conditions added yet. Add conditions or groups above to filter devices.
            </p>
          )}
        </div>
      </div>

      {showTree ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">Filter tree</p>
          <GroupBlock
            depth={0}
            fields={fields}
            group={tree}
            nautobot_token={nautobot_token}
            nautobot_url={nautobot_url}
            operators={operators}
            onUpdate={onChange}
          />
        </div>
      ) : null}
    </div>
  );
}
