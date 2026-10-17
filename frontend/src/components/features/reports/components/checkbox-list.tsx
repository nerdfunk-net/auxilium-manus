"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface CheckboxListProps {
  idPrefix: string;
  options: readonly string[];
  selected: readonly string[];
  onChange: (next: string[]) => void;
}

/** A wrapped list of checkboxes that keeps the selection in option order. */
export function CheckboxList({ idPrefix, options, selected, onChange }: CheckboxListProps) {
  const toggle = (name: string, checked: boolean) => {
    const next = checked ? [...selected, name] : selected.filter((item) => item !== name);
    onChange(options.filter((option) => next.includes(option)));
  };

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      {options.map((name) => {
        const id = `${idPrefix}-${name}`;
        return (
          <div key={name} className="flex items-center gap-1.5">
            <Checkbox
              id={id}
              checked={selected.includes(name)}
              onCheckedChange={(checked) => toggle(name, checked === true)}
            />
            <Label htmlFor={id} className="font-mono text-xs font-normal">
              {name}
            </Label>
          </div>
        );
      })}
    </div>
  );
}
