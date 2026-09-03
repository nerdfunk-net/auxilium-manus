"use client";

import { useMemo } from "react";

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
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { useSavedInventoriesQuery } from "@/hooks/queries/use-saved-inventories-query";
import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

interface ScheduleParameterFieldsProps {
  attributes: StaticAttributeDef[];
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

export function ScheduleParameterFields({
  attributes,
  values,
  onChange,
}: ScheduleParameterFieldsProps) {
  const needsInventory = attributes.some(
    (a) => a.type === "reference" && a.ref_kind === "inventory",
  );
  const needsCredential = attributes.some(
    (a) => a.type === "reference" && a.ref_kind === "credential",
  );

  const inventoriesQuery = useSavedInventoriesQuery({ enabled: needsInventory });
  const credentialsQuery = useCredentialsQuery({ enabled: needsCredential });

  const sshCredentials = useMemo(
    () => (credentialsQuery.data?.credentials ?? []).filter((c) => c.type === "ssh"),
    [credentialsQuery.data],
  );

  const setValue = (name: string, value: unknown) => {
    onChange({ ...values, [name]: value });
  };

  if (attributes.length === 0) {
    return (
      <p className="text-[12px] text-muted-foreground">
        This workflow declares no run parameters.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {attributes.map((attr) => {
        const current = values[attr.name];
        const label = (
          <Label className="text-xs" htmlFor={`param-${attr.name}`}>
            {attr.name}
            {attr.required ? <span className="text-destructive"> *</span> : null}
          </Label>
        );

        if (attr.type === "reference" && attr.ref_kind === "inventory") {
          return (
            <div key={attr.name} className="grid gap-1">
              {label}
              <Select
                value={current != null ? String(current) : ""}
                onValueChange={(v) => setValue(attr.name, Number(v))}
              >
                <SelectTrigger id={`param-${attr.name}`}>
                  <SelectValue placeholder="Select an inventory" />
                </SelectTrigger>
                <SelectContent>
                  {(inventoriesQuery.data ?? []).map((inv) => (
                    <SelectItem key={inv.id} value={String(inv.id)}>
                      {inv.name}
                      {inv.scope === "private" ? " (private)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }

        if (attr.type === "reference" && attr.ref_kind === "credential") {
          return (
            <div key={attr.name} className="grid gap-1">
              {label}
              <Select
                value={current != null ? String(current) : ""}
                onValueChange={(v) => setValue(attr.name, v)}
              >
                <SelectTrigger id={`param-${attr.name}`}>
                  <SelectValue placeholder="Select an SSH credential" />
                </SelectTrigger>
                <SelectContent>
                  {sshCredentials.map((cred) => (
                    <SelectItem key={cred.id} value={cred.name}>
                      {cred.name}
                      {cred.visibility === "private" ? " (private)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }

        if (attr.type === "boolean") {
          return (
            <div key={attr.name} className="flex items-center justify-between gap-2">
              {label}
              <Switch
                id={`param-${attr.name}`}
                checked={current === true}
                onCheckedChange={(checked) => setValue(attr.name, checked)}
              />
            </div>
          );
        }

        return (
          <div key={attr.name} className="grid gap-1">
            {label}
            <Input
              id={`param-${attr.name}`}
              type={attr.type === "number" ? "number" : "text"}
              value={current != null ? String(current) : ""}
              onChange={(e) =>
                setValue(
                  attr.name,
                  attr.type === "number"
                    ? e.target.value === ""
                      ? ""
                      : Number(e.target.value)
                    : e.target.value,
                )
              }
            />
          </div>
        );
      })}
    </div>
  );
}
