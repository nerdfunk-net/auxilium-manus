"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ComboboxOption {
  value: string;
  label: string;
}

interface ComboboxProps {
  options: ComboboxOption[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Dependency-free searchable select. Filters `options` client-side as the
 * user types; does not fetch data itself. Mirrors the trigger styling of
 * `Select`/`SelectTrigger` and the popover/dismissal pattern already used in
 * run-input-device-list-field.tsx, without pulling in cmdk/Popover.
 */
export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = "Select value...",
  searchPlaceholder = "Search...",
  emptyText = "No results.",
  disabled = false,
  className,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const selectedOption = useMemo(
    () => options.find((option) => option.value === value),
    [options, value],
  );

  const filteredOptions = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    if (!query) {
      return options;
    }
    return options.filter((option) => option.label.toLowerCase().includes(query));
  }, [options, searchTerm]);

  const closeCombobox = () => {
    setOpen(false);
    setSearchTerm("");
  };

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        closeCombobox();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useEffect(() => {
    if (open) {
      searchInputRef.current?.focus();
    }
  }, [open]);

  const handleToggle = () => {
    if (open) {
      closeCombobox();
    } else {
      setOpen(true);
    }
  };

  const handleSelect = (option: ComboboxOption) => {
    onValueChange(option.value);
    closeCombobox();
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      closeCombobox();
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <Button
        className={cn(
          "w-full justify-between font-normal",
          !selectedOption && "text-muted-foreground",
          className,
        )}
        disabled={disabled}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        type="button"
        variant="outline"
      >
        <span className="truncate">{selectedOption ? selectedOption.label : placeholder}</span>
        <ChevronDown className="size-4 shrink-0 opacity-50" />
      </Button>

      {open ? (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border border-border bg-popover shadow-lg">
          <div className="border-b border-border p-1.5">
            <Input
              className="h-8"
              onChange={(event) => setSearchTerm(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={searchPlaceholder}
              ref={searchInputRef}
              value={searchTerm}
            />
          </div>
          <div className="max-h-64 overflow-auto p-1">
            {filteredOptions.length > 0 ? (
              filteredOptions.map((option) => (
                <Button
                  className="h-auto w-full justify-start gap-2 rounded-sm px-2 py-1.5 text-left text-sm font-normal"
                  key={option.value}
                  onClick={() => handleSelect(option)}
                  type="button"
                  variant="ghost"
                >
                  <Check
                    className={cn(
                      "size-4 shrink-0",
                      option.value === value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{option.label}</span>
                </Button>
              ))
            ) : (
              <p className="px-2 py-1.5 text-sm text-muted-foreground">{emptyText}</p>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
