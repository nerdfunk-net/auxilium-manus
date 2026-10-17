"use client";

import { Fingerprint, Loader2, Search, Trash2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

export type NautobotUuidResourceType =
  | "location"
  | "role"
  | "status"
  | "platform"
  | "device"
  | "device_type"
  | "namespace"
  | "rack";

export interface NautobotUuidResolution {
  resource_type: NautobotUuidResourceType;
  content_type?: string;
}

export interface ValueSpec {
  value: string;
  uuid_resolution?: NautobotUuidResolution;
}

export interface EnabledValueSpec extends ValueSpec {
  enabled: boolean;
}

export const UUID_RESOURCE_TYPE_OPTIONS: { value: NautobotUuidResourceType; label: string }[] = [
  { value: "location", label: "Location" },
  { value: "role", label: "Role" },
  { value: "status", label: "Status" },
  { value: "platform", label: "Platform" },
  { value: "device", label: "Device" },
  { value: "device_type", label: "Device type" },
  { value: "namespace", label: "Namespace" },
  { value: "rack", label: "Rack" },
];

// Content types this codebase's resolvers are already exercised against — extend as needed.
export const UUID_CONTENT_TYPE_OPTIONS = [
  { value: "dcim.device", label: "dcim.device" },
  { value: "dcim.interface", label: "dcim.interface" },
];

const CONTENT_TYPE_SCOPED_RESOURCE_TYPES = new Set<NautobotUuidResourceType>(["role", "status"]);

export function isAttributeExpression(value: string): boolean {
  return /^\{.*\}$/.test(value.trim());
}

export interface TestResolveState {
  status: "idle" | "pending" | "success" | "error";
  id?: string;
  error?: string;
}

interface UuidResolutionControlsProps {
  value: string;
  uuidResolution?: NautobotUuidResolution;
  onUuidResolutionChange?: (next: NautobotUuidResolution | undefined) => void;
  uuidAutoDetect?: NautobotUuidResolution;
  onTestResolve?: (resolution: NautobotUuidResolution) => void;
  testResolve?: TestResolveState;
  disabled?: boolean;
}

function UuidToggleButton({
  active,
  disabled,
  onClick,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant={active ? "default" : "outline"}
      size="icon"
      className="size-8 shrink-0"
      disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      title="Convert to UUID"
    >
      <Fingerprint className="size-3.5" />
    </Button>
  );
}

function UuidResolutionSubRow({
  value,
  uuidResolution,
  onUuidResolutionChange,
  onTestResolve,
  testResolve,
  disabled,
}: UuidResolutionControlsProps) {
  if (!uuidResolution || !onUuidResolutionChange) return null;

  const needsContentType = CONTENT_TYPE_SCOPED_RESOURCE_TYPES.has(uuidResolution.resource_type);
  const canTestResolve = Boolean(onTestResolve) && !isAttributeExpression(value) && Boolean(value.trim());

  return (
    <div className="flex flex-wrap items-center gap-1.5 pl-1">
      <Select
        value={uuidResolution.resource_type}
        onValueChange={(next) =>
          onUuidResolutionChange({
            resource_type: next as NautobotUuidResourceType,
            content_type: uuidResolution.content_type,
          })
        }
      >
        <SelectTrigger className="h-7 w-[9.5rem] text-xs" disabled={disabled}>
          <SelectValue placeholder="Resolve as…" />
        </SelectTrigger>
        <SelectContent>
          {UUID_RESOURCE_TYPE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value} className="text-xs">
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {needsContentType ? (
        <Select
          value={uuidResolution.content_type ?? "dcim.device"}
          onValueChange={(next) =>
            onUuidResolutionChange({ ...uuidResolution, content_type: next })
          }
        >
          <SelectTrigger className="h-7 w-[9.5rem] font-mono text-[11px]" disabled={disabled}>
            <SelectValue placeholder="Content type…" />
          </SelectTrigger>
          <SelectContent>
            {UUID_CONTENT_TYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} className="font-mono text-[11px]">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      {onTestResolve ? (
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-[11px]"
            disabled={disabled || !canTestResolve || testResolve?.status === "pending"}
            title={
              isAttributeExpression(value)
                ? "Attribute expressions resolve per device at run time"
                : undefined
            }
            onClick={() => onTestResolve(uuidResolution)}
          >
            {testResolve?.status === "pending" ? (
              <Loader2 className="size-3 animate-spin" />
            ) : null}
            Test resolve
          </Button>
          {testResolve?.status === "success" ? (
            <span className="truncate font-mono text-[10px] text-success-foreground">
              {testResolve.id}
            </span>
          ) : null}
          {testResolve?.status === "error" ? (
            <span className="text-[10px] text-destructive">{testResolve.error ?? "Not found"}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function NautobotRequiredFieldRow({
  label,
  placeholder,
  value,
  onChange,
  badge,
  onBrowse,
  uuidResolution,
  onUuidResolutionChange,
  uuidAutoDetect,
  onTestResolve,
  testResolve,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  /** Optional type badge next to the label, e.g. a job parameter's declared type. */
  badge?: string;
  /** Renders a "Browse attributes" icon button next to the value input when provided. */
  onBrowse?: () => void;
  /** Current UUID-conversion setting for this field, if enabled. */
  uuidResolution?: NautobotUuidResolution;
  /** Renders the "Convert to UUID" toggle when provided. */
  onUuidResolutionChange?: (next: NautobotUuidResolution | undefined) => void;
  /** Suggested resolution (from the job schema or a name heuristic) seeded on first toggle-on. */
  uuidAutoDetect?: NautobotUuidResolution;
  /** Renders the "Test resolve" control when provided. */
  onTestResolve?: (resolution: NautobotUuidResolution) => void;
  testResolve?: TestResolveState;
}) {
  const isEmpty = !value.trim();
  return (
    <div
      className={`space-y-1 rounded-lg border p-2.5 ${
        isEmpty ? "border-warning-border bg-warning" : "border-border bg-muted"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <Label className="text-[11px] font-medium text-muted-foreground">
          {label} <span className="text-warning-foreground">*</span>
        </Label>
        {badge ? (
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            {badge}
          </Badge>
        ) : null}
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          className="h-8 text-xs focus-visible:ring-step/40"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        {onUuidResolutionChange ? (
          <UuidToggleButton
            active={Boolean(uuidResolution)}
            onClick={() =>
              onUuidResolutionChange(
                uuidResolution ? undefined : (uuidAutoDetect ?? { resource_type: "location" }),
              )
            }
          />
        ) : null}
        {onBrowse ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={onBrowse}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        ) : null}
      </div>
      <UuidResolutionSubRow
        value={value}
        uuidResolution={uuidResolution}
        onUuidResolutionChange={onUuidResolutionChange}
        onTestResolve={onTestResolve}
        testResolve={testResolve}
      />
    </div>
  );
}

export function NautobotOptionalFieldRow({
  label,
  placeholder,
  spec,
  onChange,
  onBrowse,
  enableUuidResolution = false,
  uuidAutoDetect,
  onTestResolve,
  testResolve,
}: {
  label: string;
  placeholder: string;
  spec: EnabledValueSpec;
  onChange: (patch: Partial<EnabledValueSpec>) => void;
  /** Renders a "Browse attributes" icon button next to the value input when provided. */
  onBrowse?: () => void;
  /** Renders the "Convert to UUID" toggle when true. Off by default for existing callers. */
  enableUuidResolution?: boolean;
  /** Suggested resolution (from the job schema or a name heuristic) seeded on first toggle-on. */
  uuidAutoDetect?: NautobotUuidResolution;
  /** Renders the "Test resolve" control when provided. */
  onTestResolve?: (resolution: NautobotUuidResolution) => void;
  testResolve?: TestResolveState;
}) {
  return (
    <div className="space-y-1 rounded-lg border border-border bg-muted p-2.5">
      <div className="flex items-center gap-2">
        <Checkbox
          checked={spec.enabled}
          onCheckedChange={(checked) => onChange({ enabled: checked === true })}
          aria-label={`Enable ${label}`}
        />
        <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          className="h-8 text-xs focus-visible:ring-step/40 disabled:opacity-50"
          disabled={!spec.enabled}
          placeholder={placeholder}
          value={spec.value}
          onChange={(event) => onChange({ value: event.target.value })}
        />
        {enableUuidResolution ? (
          <UuidToggleButton
            active={Boolean(spec.uuid_resolution)}
            disabled={!spec.enabled}
            onClick={() =>
              onChange({
                uuid_resolution: spec.uuid_resolution
                  ? undefined
                  : (uuidAutoDetect ?? { resource_type: "location" }),
              })
            }
          />
        ) : null}
        {onBrowse ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            disabled={!spec.enabled}
            onClick={onBrowse}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        ) : null}
      </div>
      {enableUuidResolution ? (
        <UuidResolutionSubRow
          value={spec.value}
          uuidResolution={spec.uuid_resolution}
          onUuidResolutionChange={(next) => onChange({ uuid_resolution: next })}
          onTestResolve={onTestResolve}
          testResolve={testResolve}
          disabled={!spec.enabled}
        />
      ) : null}
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
  onBrowse,
  valuePlaceholder = "{custom.site | default('N/A')}",
}: {
  row: NautobotCustomFieldRowValues;
  onChange: (patch: Partial<NautobotCustomFieldRowValues>) => void;
  onRemove: () => void;
  /** Renders a "Browse attributes" icon button next to the value input when provided. */
  onBrowse?: () => void;
  valuePlaceholder?: string;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Checkbox
            checked={row.enabled}
            onCheckedChange={(checked) => onChange({ enabled: checked === true })}
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
        <div className="flex items-center gap-1.5">
          <Input
            className="h-8 text-xs disabled:opacity-50"
            disabled={!row.enabled}
            placeholder={valuePlaceholder}
            value={row.value}
            onChange={(event) => onChange({ value: event.target.value })}
          />
          {onBrowse ? (
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8 shrink-0"
              disabled={!row.enabled}
              onClick={onBrowse}
              title="Browse attributes"
            >
              <Search className="size-3.5" />
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
