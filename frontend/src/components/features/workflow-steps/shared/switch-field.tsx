import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

interface SwitchFieldProps {
  id: string;
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  description?: ReactNode;
  disabled?: boolean;
}

/** Monospace key label + switch + optional help text — the standard on/off config row. */
export function SwitchField({
  id,
  label,
  checked,
  onCheckedChange,
  description,
  disabled,
}: SwitchFieldProps) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <Label htmlFor={id} className="font-mono text-xs font-medium">
          {label}
        </Label>
        <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
      </div>
      {description ? <p className="text-[11px] text-muted-foreground">{description}</p> : null}
    </div>
  );
}
