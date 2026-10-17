"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";

interface IntegerFieldProps {
  value: number;
  onCommit: (value: number) => void;
  ariaLabel: string;
}

/** Integer input that keeps a draft string, so "-" or "" can be typed on the way to a
 * valid number. The parent only sees values that parse as integers. */
export function IntegerField({ value, onCommit, ariaLabel }: IntegerFieldProps) {
  const [draft, setDraft] = useState<string | null>(null);

  return (
    <Input
      aria-label={ariaLabel}
      className="h-7 font-mono text-xs"
      inputMode="numeric"
      value={draft ?? String(value)}
      onBlur={() => setDraft(null)}
      onChange={(e) => {
        const text = e.target.value;
        setDraft(text);
        if (/^-?\d+$/.test(text.trim())) {
          onCommit(Number.parseInt(text, 10));
        }
      }}
    />
  );
}
