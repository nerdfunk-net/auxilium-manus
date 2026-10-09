"use client";

import { useCallback, type ChangeEvent, type ReactNode } from "react";

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
import {
  boolField,
  joinedStringList,
  numberInputField,
  stringField,
} from "@/components/features/workflow-steps/shared/config-field-helpers";

export type BatfishParams = Record<string, unknown>;

export type ParamFieldSpec =
  | {
      kind: "text";
      key: string;
      id: string;
      label: string;
      placeholder?: string;
      /** Shows a red "Required" hint while the value is blank. */
      required?: boolean;
    }
  | {
      kind: "select";
      key: string;
      label: string;
      options: readonly string[];
      /** Shown (and used) when the param is unset. */
      fallback: string;
    }
  /** Comma-separated text stored as a string[] (e.g. applications). */
  | { kind: "list"; key: string; id: string; label: string; placeholder?: string }
  /** Integer input; keeps the raw text while it is not yet a valid integer. */
  | { kind: "integer"; key: string; id: string; label: string; min?: number }
  | { kind: "switch"; key: string; id: string; label: string };

interface ParamFieldGridProps {
  fields: readonly ParamFieldSpec[];
  params: BatfishParams;
  onParamsChange: (params: BatfishParams) => void;
  /** Rendered inside the same grid, after the spec fields. */
  children?: ReactNode;
}

export function ParamFieldGrid({ fields, params, onParamsChange, children }: ParamFieldGridProps) {
  const update = useCallback(
    (key: string, value: unknown) => onParamsChange({ ...params, [key]: value }),
    [params, onParamsChange],
  );

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {fields.map((field) => (
        <ParamFieldControl key={field.key} field={field} params={params} update={update} />
      ))}
      {children}
    </div>
  );
}

interface ParamFieldControlProps {
  field: ParamFieldSpec;
  params: BatfishParams;
  update: (key: string, value: unknown) => void;
}

function ParamFieldControl({ field, params, update }: ParamFieldControlProps) {
  switch (field.kind) {
    case "text": {
      const value = stringField(params, field.key);
      return (
        <div className="space-y-1.5">
          <Label htmlFor={field.id}>{field.label}</Label>
          <Input
            id={field.id}
            value={value}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              update(field.key, event.target.value)
            }
            placeholder={field.placeholder}
          />
          {field.required && !value.trim() ? (
            <p className="text-xs text-destructive">Required</p>
          ) : null}
        </div>
      );
    }
    case "select":
      return (
        <div className="space-y-1.5">
          <Label>{field.label}</Label>
          <Select
            value={stringField(params, field.key) || field.fallback}
            onValueChange={(value) => update(field.key, value)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {field.options.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
    case "list":
      return (
        <div className="space-y-1.5">
          <Label htmlFor={field.id}>{field.label}</Label>
          <Input
            id={field.id}
            value={joinedStringList(params, field.key)}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              update(
                field.key,
                event.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              )
            }
            placeholder={field.placeholder}
          />
        </div>
      );
    case "integer":
      return (
        <div className="space-y-1.5">
          <Label htmlFor={field.id}>{field.label}</Label>
          <Input
            id={field.id}
            type="number"
            min={field.min}
            value={numberInputField(params, field.key)}
            onChange={(event: ChangeEvent<HTMLInputElement>) => {
              const raw = event.target.value;
              const parsed = Number.parseInt(raw, 10);
              update(field.key, Number.isNaN(parsed) ? raw : parsed);
            }}
          />
        </div>
      );
    case "switch":
      return (
        <div className="flex items-center justify-between rounded-md border px-3 py-2">
          <Label htmlFor={field.id}>{field.label}</Label>
          <Switch
            id={field.id}
            checked={boolField(params, field.key)}
            onCheckedChange={(checked) => update(field.key, checked)}
          />
        </div>
      );
  }
}
