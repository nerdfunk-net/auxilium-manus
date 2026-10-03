"use client";

import { useCallback, useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface FactOption {
  value: string;
  label: string;
  hint: string;
}

interface FactCheckboxGroupProps {
  /** Config key shown as the parameter name, e.g. "facts". */
  name: string;
  options: readonly FactOption[];
  selected: readonly string[];
  onChange: (next: string[]) => void;
}

/** Checkbox list for a string_list config key; keeps the options' own order. */
export function FactCheckboxGroup({
  name,
  options,
  selected,
  onChange,
}: FactCheckboxGroupProps) {
  const groupId = useId();

  const handleToggle = useCallback(
    (value: string, checked: boolean) => {
      const wanted = new Set(selected);
      if (checked) wanted.add(value);
      else wanted.delete(value);
      onChange(options.map((o) => o.value).filter((v) => wanted.has(v)));
    },
    [onChange, options, selected],
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{name}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          string_list
        </Badge>
      </div>
      <div className="space-y-2" role="group" aria-label={name}>
        {options.map((option) => {
          const id = `${groupId}-${option.value}`;
          return (
            <div key={option.value} className="flex items-start gap-2">
              <Checkbox
                id={id}
                className="mt-0.5"
                checked={selected.includes(option.value)}
                onCheckedChange={(checked) =>
                  handleToggle(option.value, checked === true)
                }
              />
              <Label htmlFor={id} className="flex flex-col gap-0.5 font-normal">
                <span className="text-xs font-medium">{option.label}</span>
                <span className="text-[11px] text-muted-foreground">
                  {option.hint}
                </span>
              </Label>
            </div>
          );
        })}
      </div>
      {selected.length === 0 ? (
        <p className="text-[11px] text-warning-foreground">
          Select at least one — the step fails without one.
        </p>
      ) : null}
    </div>
  );
}

interface ParsedOutputKeyFieldProps {
  value: string;
  fallback: string;
  /** Fact name appended to the path hint, e.g. "<fact>" or "health". */
  suffix: string;
  onChange: (next: string) => void;
}

export function ParsedOutputKeyField({
  value,
  fallback,
  suffix,
  onChange,
}: ParsedOutputKeyFieldProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">parsed_output_key</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          string
        </Badge>
      </div>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={fallback}
        aria-label="Parsed output key"
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">
        Read as parsed.{value || fallback}.{suffix}.parsed
      </p>
    </div>
  );
}

/** Reads a string_list config value, falling back when absent or malformed. */
export function readStringList(
  config: Record<string, unknown>,
  key: string,
  fallback: readonly string[],
): string[] {
  const raw = config[key];
  if (!Array.isArray(raw)) return [...fallback];
  return raw.filter((item): item is string => typeof item === "string");
}

export function readString(
  config: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : fallback;
}
