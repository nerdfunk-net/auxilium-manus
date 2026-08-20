"use client";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export interface EnabledValueSpec {
  enabled: boolean;
  value: string;
}

export function NautobotRequiredFieldRow({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const isEmpty = !value.trim();
  return (
    <div
      className={`space-y-1 rounded-lg border p-2.5 ${
        isEmpty ? "border-warning-border bg-warning" : "border-border bg-muted"
      }`}
    >
      <Label className="text-[11px] font-medium text-muted-foreground">
        {label} <span className="text-warning-foreground">*</span>
      </Label>
      <Input
        className="h-8 text-xs focus-visible:ring-step/40"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

export function NautobotOptionalFieldRow({
  label,
  placeholder,
  spec,
  onChange,
}: {
  label: string;
  placeholder: string;
  spec: EnabledValueSpec;
  onChange: (patch: Partial<EnabledValueSpec>) => void;
}) {
  return (
    <div className="space-y-1 rounded-lg border border-border bg-muted p-2.5">
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={spec.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
          className="size-4 rounded border accent-step"
          aria-label={`Enable ${label}`}
        />
        <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      </div>
      <Input
        className="h-8 text-xs focus-visible:ring-step/40 disabled:opacity-50"
        disabled={!spec.enabled}
        placeholder={placeholder}
        value={spec.value}
        onChange={(event) => onChange({ value: event.target.value })}
      />
    </div>
  );
}

export interface NautobotInterfaceRowValues {
  id: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace: string;
  description?: string;
  is_primary_ipv4?: boolean;
}

export function NautobotInterfaceRow({
  row,
  onChange,
  onRemove,
}: {
  row: NautobotInterfaceRowValues;
  onChange: (patch: Partial<NautobotInterfaceRowValues>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-step-muted-foreground">Interface</span>
        <Button
          className="h-7 px-2 text-destructive hover:text-destructive"
          size="sm"
          type="button"
          variant="ghost"
          onClick={onRemove}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Name</Label>
          <Input
            className="h-8 text-xs"
            value={row.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Type</Label>
          <Input
            className="h-8 text-xs"
            placeholder="1000base-t"
            value={row.type ?? ""}
            onChange={(event) => onChange({ type: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Status</Label>
          <Input
            className="h-8 text-xs"
            placeholder="active"
            value={row.status ?? ""}
            onChange={(event) => onChange({ status: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">IP address</Label>
          <Input
            className="h-8 font-mono text-xs"
            placeholder="10.0.0.1/24"
            value={row.ip_address ?? ""}
            onChange={(event) => onChange({ ip_address: event.target.value })}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label className="text-[11px] text-muted-foreground">Description</Label>
          <Input
            className="h-8 text-xs"
            value={row.description ?? ""}
            onChange={(event) => onChange({ description: event.target.value })}
          />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <Label className="text-[11px] text-muted-foreground">Primary IPv4</Label>
        <Switch
          checked={row.is_primary_ipv4 ?? false}
          onCheckedChange={(checked) => onChange({ is_primary_ipv4: checked })}
        />
      </div>
    </div>
  );
}

export interface NautobotCustomFieldRowValues {
  id: string;
  name: string;
  enabled: boolean;
  value: string;
}

export function NautobotCustomFieldRow({
  row,
  onChange,
  onRemove,
  valuePlaceholder = "{custom.site | default('N/A')}",
}: {
  row: NautobotCustomFieldRowValues;
  onChange: (patch: Partial<NautobotCustomFieldRowValues>) => void;
  onRemove: () => void;
  valuePlaceholder?: string;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={row.enabled}
            onChange={(event) => onChange({ enabled: event.target.checked })}
            className="size-4 rounded border accent-step"
            aria-label={`Enable custom field ${row.name || "row"}`}
          />
          <span className="text-xs font-medium text-step-muted-foreground">Custom field</span>
        </div>
        <Button
          className="h-7 px-2 text-destructive hover:text-destructive"
          size="sm"
          type="button"
          variant="ghost"
          onClick={onRemove}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Input
          className="h-8 text-xs disabled:opacity-50"
          disabled={!row.enabled}
          placeholder="field_name"
          value={row.name}
          onChange={(event) => onChange({ name: event.target.value })}
        />
        <Input
          className="h-8 text-xs disabled:opacity-50"
          disabled={!row.enabled}
          placeholder={valuePlaceholder}
          value={row.value}
          onChange={(event) => onChange({ value: event.target.value })}
        />
      </div>
    </div>
  );
}
