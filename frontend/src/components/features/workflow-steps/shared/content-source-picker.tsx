"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface ContentSourceOption<T extends string> {
  value: T;
  label: string;
  hint: string;
}

interface ContentSourcePickerProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: readonly ContentSourceOption<T>[];
  /** Steps that only allow "upstream_output" under certain upstream-content
   * conditions pass this to disable the option without filtering it out of
   * the list entirely. */
  isOptionDisabled?: (value: T) => boolean;
}

export function ContentSourcePicker<T extends string>({
  value,
  onChange,
  options,
  isOptionDisabled,
}: ContentSourcePickerProps<T>) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger className="h-8 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value}
            disabled={isOptionDisabled?.(option.value)}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
