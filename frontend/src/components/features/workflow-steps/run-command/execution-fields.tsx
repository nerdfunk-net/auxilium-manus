import type { ComponentProps } from "react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DeployReadTimeoutFields } from "@/components/features/workflow-steps/deploy-rendered-template/deploy-fields";
import { RetryBackoffSecondsField } from "@/components/features/workflow-steps/shared/retry-backoff-fields";

import { CheckboxField } from "../shared/checkbox-field";
import { FieldHeader } from "../shared/field-header";
import { clampReadTimeout, EXECUTION_MODE_OPTIONS, type ExecutionMode } from "./config";

type RetryBackoffSeconds = ComponentProps<typeof RetryBackoffSecondsField>["retryBackoffSeconds"];

interface ExecutionFieldsProps {
  executionMode: ExecutionMode;
  dryRun: boolean;
  networkDriverOverride: string;
  readTimeout: number;
  retryBackoffSeconds: RetryBackoffSeconds;
  writeConfigAfterExecution: boolean;
  autoConfirmPrompts: boolean;
  /** Merge a partial config through `buildRunCommandConfig` and emit it. */
  onPatch: (patch: Record<string, unknown>) => void;
}

export function ExecutionFields({
  executionMode,
  dryRun,
  networkDriverOverride,
  readTimeout,
  retryBackoffSeconds,
  writeConfigAfterExecution,
  autoConfirmPrompts,
  onPatch,
}: ExecutionFieldsProps) {
  const executionModeHint = EXECUTION_MODE_OPTIONS.find(
    (option) => option.value === executionMode,
  )?.hint;

  return (
    <>
      <div className="space-y-1.5">
        <FieldHeader name="execution_mode" type="string" />
        <Select
          value={executionMode}
          onValueChange={(value) => onPatch({ execution_mode: value })}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXECUTION_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {executionModeHint ? (
          <p className="text-[11px] text-muted-foreground">{executionModeHint}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <CheckboxField
          id="dry-run"
          label="dry_run"
          checked={dryRun}
          onCheckedChange={(checked) => onPatch({ dry_run: checked })}
          description={
            <>
              Do not send anything to devices. Records what would happen under{" "}
              <span className="font-mono">dry_run_results</span> for this step, visible in the
              run&apos;s detail view.
            </>
          }
        />
      </div>

      <div className="space-y-1.5">
        <FieldHeader name="network_driver_override" type="string" />
        <Input
          value={networkDriverOverride}
          onChange={(event) => onPatch({ network_driver_override: event.target.value })}
          placeholder="cisco_ios (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Overrides each device&apos;s network driver for Netmiko in this step.
        </p>
      </div>

      <DeployReadTimeoutFields
        readTimeout={readTimeout}
        onReadTimeoutChange={(value) => onPatch({ read_timeout: clampReadTimeout(value) })}
      />

      <RetryBackoffSecondsField
        retryBackoffSeconds={retryBackoffSeconds}
        onRetryBackoffSecondsChange={(next) => onPatch({ retry_backoff_seconds: next })}
      />

      {executionMode === "config_mode" ? (
        <CheckboxField
          id="write-config-after-execution"
          label="write_config_after_execution"
          checked={writeConfigAfterExecution}
          onCheckedChange={(checked) => onPatch({ write_config_after_execution: checked })}
          description={
            <>
              After a successful config_mode run, run &ldquo;copy running-config
              startup-config&rdquo; and confirm the prompt automatically. Skipped when the run
              itself fails.
            </>
          }
        />
      ) : null}

      <div className="space-y-1.5">
        <CheckboxField
          id="auto-confirm-prompts"
          label="auto_confirm_prompts"
          checked={autoConfirmPrompts}
          onCheckedChange={(checked) => onPatch({ auto_confirm_prompts: checked })}
          description={
            <>
              Automatically press Enter to accept a device&apos;s interactive confirmation (e.g.
              &ldquo;...Do you want to continue? [confirm]&rdquo;) instead of failing.
            </>
          }
        />
        {autoConfirmPrompts ? (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            Risky: any command in this step that raises a confirmation prompt will be accepted
            automatically, with no human review. Only enable this when every command is expected
            and safe to auto-accept.
          </p>
        ) : null}
      </div>
    </>
  );
}
