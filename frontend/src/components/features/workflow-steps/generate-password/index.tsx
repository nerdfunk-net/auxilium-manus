"use client";

import { useCallback } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { GeneratePasswordHelpPanel } from "./help-panel";

function numberField(config: Record<string, unknown>, key: string, fallback: number): number {
  const value = config[key];
  return typeof value === "number" ? value : fallback;
}

function stringField(config: Record<string, unknown>, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function GeneratePasswordConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const setField = useCallback(
    (key: string, value: unknown) => onChange({ ...config, [key]: value }),
    [config, onChange],
  );

  const length = numberField(config, "length", 16);
  const minDigits = numberField(config, "min_digits", 2);
  const minUppercase = numberField(config, "min_uppercase", 2);
  const minLowercase = numberField(config, "min_lowercase", 2);
  const minSpecial = numberField(config, "min_special", 2);
  const destinationPath = stringField(config, "destination_path", "generated_password.value");

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-length">
          length
        </Label>
        <Input
          id="generate-password-length"
          className="h-8 font-mono text-xs"
          type="number"
          min={8}
          max={256}
          value={length}
          onChange={(event) => setField("length", Number(event.target.value) || 16)}
        />
        <p className="text-[11px] text-muted-foreground">
          Total password length (8–256 characters).
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-min-digits">
          min_digits
        </Label>
        <Input
          id="generate-password-min-digits"
          className="h-8 font-mono text-xs"
          type="number"
          min={0}
          max={256}
          value={minDigits}
          onChange={(event) => setField("min_digits", Number(event.target.value) || 0)}
        />
        <p className="text-[11px] text-muted-foreground">
          Minimum digits (0–9). 0 excludes digits entirely.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-min-uppercase">
          min_uppercase
        </Label>
        <Input
          id="generate-password-min-uppercase"
          className="h-8 font-mono text-xs"
          type="number"
          min={0}
          max={256}
          value={minUppercase}
          onChange={(event) => setField("min_uppercase", Number(event.target.value) || 0)}
        />
        <p className="text-[11px] text-muted-foreground">
          Minimum uppercase letters. 0 excludes uppercase entirely.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-min-lowercase">
          min_lowercase
        </Label>
        <Input
          id="generate-password-min-lowercase"
          className="h-8 font-mono text-xs"
          type="number"
          min={0}
          max={256}
          value={minLowercase}
          onChange={(event) => setField("min_lowercase", Number(event.target.value) || 0)}
        />
        <p className="text-[11px] text-muted-foreground">
          Minimum lowercase letters. 0 excludes lowercase entirely.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-min-special">
          min_special
        </Label>
        <Input
          id="generate-password-min-special"
          className="h-8 font-mono text-xs"
          type="number"
          min={0}
          max={256}
          value={minSpecial}
          onChange={(event) => setField("min_special", Number(event.target.value) || 0)}
        />
        <p className="text-[11px] text-muted-foreground">
          Minimum special characters, from a fixed alphabet. 0 excludes special characters entirely.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="font-mono text-xs font-medium" htmlFor="generate-password-destination">
          destination_path
        </Label>
        <Input
          id="generate-password-destination"
          className="h-8 font-mono text-xs"
          value={destinationPath}
          onChange={(event) => setField("destination_path", event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag path the sealed password is written to (bag.field form), for a
          later step in the same run to use.
        </p>
      </div>
    </div>
  );
}

export const GeneratePasswordPlugin: PluginUIComponent = {
  ConfigPanel: GeneratePasswordConfigPanel,
  HelpPanel: GeneratePasswordHelpPanel,
};
