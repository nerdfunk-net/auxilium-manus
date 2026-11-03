"use client";

import { TriangleAlert } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

/** The Select cannot hold an empty value, so "no devices input" has its own item value. */
export const NO_DEVICES_INPUT = "__none__";

interface WorkflowAiReleaseInputsProps {
  textInputNames: string[];
  credentialInputNames: string[];
  devicesInput: string;
  selectedCredentials: string[];
  allowFreeIp: boolean;
  disabled: boolean;
  onDevicesInputChange: (value: string) => void;
  onCredentialToggle: (name: string, checked: boolean) => void;
  onAllowFreeIpChange: (checked: boolean) => void;
}

/**
 * Where the devices an Ask the Net user names go, which credential inputs the user fills in on the
 * confirm card, and whether an IPv4 address outside the inventory may be passed (onboarding).
 */
export function WorkflowAiReleaseInputs({
  textInputNames,
  credentialInputNames,
  devicesInput,
  selectedCredentials,
  allowFreeIp,
  disabled,
  onDevicesInputChange,
  onCredentialToggle,
  onAllowFreeIpChange,
}: WorkflowAiReleaseInputsProps) {
  const hasDevicesInput = devicesInput !== NO_DEVICES_INPUT;

  return (
    <>
      <div className="space-y-1.5">
        <Label className="text-[13px]" htmlFor="ai-release-devices">
          Devices input
        </Label>
        <Select
          value={devicesInput}
          onValueChange={onDevicesInputChange}
          disabled={disabled}
        >
          <SelectTrigger id="ai-release-devices" aria-label="Devices input">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_DEVICES_INPUT}>
              None (takes no devices)
            </SelectItem>
            {textInputNames.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          The text input a Get from User step reads. The devices a user names in
          Ask the Net are put into it.
        </p>
      </div>

      {credentialInputNames.length > 0 ? (
        <fieldset className="space-y-1.5">
          <legend className="text-[13px] font-medium">
            Credentials chosen by the user
          </legend>
          {credentialInputNames.map((name) => (
            <div key={name} className="flex items-center gap-2">
              <Checkbox
                id={`ai-release-cred-${name}`}
                checked={selectedCredentials.includes(name)}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  onCredentialToggle(name, checked === true)
                }
              />
              <Label
                className="text-[13px]"
                htmlFor={`ai-release-cred-${name}`}
              >
                {name}
              </Label>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">
            Whoever confirms a run picks one of their own credentials on the
            card. The assistant never sees or sets it.
          </p>
        </fieldset>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label className="text-[13px]" htmlFor="ai-release-free-ip">
            Accept IPv4 addresses outside the inventory
          </Label>
          <Switch
            id="ai-release-free-ip"
            checked={allowFreeIp && hasDevicesInput}
            disabled={disabled || !hasDevicesInput}
            onCheckedChange={onAllowFreeIpChange}
          />
        </div>
        {allowFreeIp && hasDevicesInput ? (
          <p
            className="flex gap-1.5 text-[11px] text-destructive"
            role="status"
          >
            <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
            The workflow will log in to an address the assistant was given in
            the chat, with the credential the user chooses. Allow this only for
            onboarding-type workflows.
          </p>
        ) : null}
      </div>
    </>
  );
}
