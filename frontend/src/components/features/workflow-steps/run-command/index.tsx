"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { parseRetryBackoffSeconds } from "@/components/features/workflow-steps/shared/retry-backoff-fields";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";

import { pyatsSourceIdFromConfig } from "../shared/pyats-source-config";
import { CommandListField } from "./command-list-field";
import {
  buildRunCommandConfig,
  DEFAULT_READ_TIMEOUT,
  parseCommands,
  parseParsedOutputKey,
  parseParserMode,
  type ExecutionMode,
} from "./config";
import { ExecutionFields } from "./execution-fields";
import { RunCommandHelpPanel } from "./help-panel";
import { ParserFields } from "./parser-fields";

function RunCommandConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.commands) || config.commands.length === 0) {
      onChange(buildRunCommandConfig(config));
    }
  }, [nodeId, config, onChange]);

  const commands = useMemo(() => parseCommands(config), [config]);
  const parserMode = useMemo(() => parseParserMode(config), [config]);
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const executionMode: ExecutionMode =
    config.execution_mode === "config_mode" ? "config_mode" : "exec_mode";
  const writeConfigAfterExecution = config.write_config_after_execution === true;
  const readTimeout =
    typeof config.read_timeout === "number" && Number.isFinite(config.read_timeout)
      ? config.read_timeout
      : DEFAULT_READ_TIMEOUT;
  const autoConfirmPrompts = config.auto_confirm_prompts === true;
  const dryRun = config.dry_run === true;
  const parserLocked = executionMode === "config_mode" || autoConfirmPrompts;
  const retryBackoffSeconds = useMemo(() => parseRetryBackoffSeconds(config), [config]);

  const pyatsSourceId = useMemo(() => pyatsSourceIdFromConfig(config), [config]);
  const parsedOutputKey = useMemo(() => parseParsedOutputKey(config), [config]);
  const { data: pyatsSourcesData } = usePyATSSourcesQuery();
  const hasPyatsSource = (pyatsSourcesData?.sources.length ?? 0) > 0;

  // Eagerly correct a stale parser value the moment locking turns on, so a
  // workflow is never saved with e.g. parser: "textfsm" sitting under a
  // hidden section until some other field happens to be edited next.
  useEffect(() => {
    if (parserLocked && parserMode !== "none") {
      onChange(buildRunCommandConfig(config));
    }
  }, [parserLocked, parserMode, config, onChange]);

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => {
      onChange(buildRunCommandConfig(config, patch));
    },
    [config, onChange],
  );

  const handleCommandChange = useCallback(
    (index: number, value: string) => {
      const next = [...commands];
      next[index] = value;
      patchConfig({ commands: next });
    },
    [commands, patchConfig],
  );

  const handleAddCommand = useCallback(() => {
    patchConfig({ commands: [...commands, ""] });
  }, [commands, patchConfig]);

  const handleRemoveCommand = useCallback(
    (index: number) => {
      if (commands.length <= 1) {
        return;
      }
      patchConfig({ commands: commands.filter((_, itemIndex) => itemIndex !== index) });
    },
    [commands, patchConfig],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <CommandListField
        commands={commands}
        onChange={handleCommandChange}
        onAdd={handleAddCommand}
        onRemove={handleRemoveCommand}
      />

      <ExecutionFields
        executionMode={executionMode}
        dryRun={dryRun}
        networkDriverOverride={networkDriverOverride}
        readTimeout={readTimeout}
        retryBackoffSeconds={retryBackoffSeconds}
        writeConfigAfterExecution={writeConfigAfterExecution}
        autoConfirmPrompts={autoConfirmPrompts}
        onPatch={patchConfig}
      />

      <ParserFields
        parserLocked={parserLocked}
        parserMode={parserMode}
        hasPyatsSource={hasPyatsSource}
        pyatsSourceId={pyatsSourceId}
        parsedOutputKey={parsedOutputKey}
        onPatch={patchConfig}
      />
    </div>
  );
}

export const RunCommandPlugin: PluginUIComponent = {
  ConfigPanel: RunCommandConfigPanel,
  HelpPanel: RunCommandHelpPanel,
};
