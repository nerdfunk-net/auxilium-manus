"use client";

import { useCallback, useMemo, useState } from "react";

import {
  BATFISH_VARIABLE,
  COMMAND_VARIABLES,
  NETMIKO_AUTO_VARIABLES,
  PARSED_CONFIG_VARIABLE,
} from "../constants";
import type {
  BatfishQueryResult,
  CommandEntry,
  EditorVariable,
  TemplateVariableRecord,
} from "../types";
import type { ParsedVariableEntry } from "../utils/parse-variables";
import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

/** How a name collision with an existing custom variable is resolved. */
export type MergeVariablesMode = "skip" | "overwrite";

let customVariableCounter = 0;

const COMMAND_VARIABLE_IDS = COMMAND_VARIABLES.map((variable) => `auto:${variable.name}`);
const PARSED_CONFIG_VARIABLE_ID = `auto:${PARSED_CONFIG_VARIABLE.name}`;
const BATFISH_VARIABLE_ID = `auto:${BATFISH_VARIABLE.name}`;
const RUN_INPUT_VARIABLE_ID = "auto:run_input";

/** Reference workflow whose static_attributes are previewed in the "run_input"
 * variable — see workflow-static-attributes-panel.tsx. Not persisted with the
 * template; a per-session discovery aid only. */
export interface RunInputSource {
  workflowName: string;
  attributes: StaticAttributeDef[];
}

function createAutoVariables(): EditorVariable[] {
  return NETMIKO_AUTO_VARIABLES.map((variable) => ({
    id: `auto:${variable.name}`,
    name: variable.name,
    value: "",
    type: "auto",
    isAutoFilled: true,
    description: variable.description,
  }));
}

function createCommandVariables(): EditorVariable[] {
  return COMMAND_VARIABLES.map((variable) => ({
    id: `auto:${variable.name}`,
    name: variable.name,
    value: "",
    type: "auto",
    isAutoFilled: true,
    description: variable.description,
  }));
}

function isCommandVariable(variable: EditorVariable): boolean {
  return COMMAND_VARIABLE_IDS.includes(variable.id);
}

function createParsedConfigVariable(): EditorVariable[] {
  return [
    {
      id: PARSED_CONFIG_VARIABLE_ID,
      name: PARSED_CONFIG_VARIABLE.name,
      value: "",
      type: "auto",
      isAutoFilled: true,
      description: PARSED_CONFIG_VARIABLE.description,
    },
  ];
}

function isParsedConfigVariable(variable: EditorVariable): boolean {
  return variable.id === PARSED_CONFIG_VARIABLE_ID;
}

function createBatfishVariable(): EditorVariable[] {
  return [
    {
      id: BATFISH_VARIABLE_ID,
      name: BATFISH_VARIABLE.name,
      value: "",
      type: "auto",
      isAutoFilled: true,
      description: BATFISH_VARIABLE.description,
    },
  ];
}

function isBatfishVariable(variable: EditorVariable): boolean {
  return variable.id === BATFISH_VARIABLE_ID;
}

export function useTemplateVariables() {
  const [variables, setVariables] = useState<EditorVariable[]>(createAutoVariables);

  const addVariable = useCallback((name: string, value: string, type = "custom") => {
    customVariableCounter += 1;
    const id = `custom:${customVariableCounter}`;
    setVariables((current) => [
      ...current,
      { id, name, value, type, isAutoFilled: false },
    ]);
    return id;
  }, []);

  const removeVariable = useCallback((id: string) => {
    setVariables((current) => current.filter((variable) => variable.id !== id));
  }, []);

  const updateVariableValue = useCallback((id: string, value: string) => {
    setVariables((current) =>
      current.map((variable) =>
        variable.id === id ? { ...variable, value } : variable,
      ),
    );
  }, []);

  const setDeviceInfo = useCallback((device: Record<string, unknown> | null) => {
    setVariables((current) =>
      current.map((variable) =>
        variable.id === "auto:device"
          ? { ...variable, value: device ? JSON.stringify(device, null, 2) : "" }
          : variable,
      ),
    );
  }, []);

  const setNautobotAttributes = useCallback((bag: unknown) => {
    setVariables((current) =>
      current.map((variable) =>
        variable.id === "auto:nautobot"
          ? {
              ...variable,
              value: bag ? JSON.stringify(bag, null, 2) : "",
            }
          : variable,
      ),
    );
  }, []);

  const toggleCommandVariables = useCallback((enabled: boolean) => {
    setVariables((current) => {
      const hasCommandVars = current.some(isCommandVariable);
      if (enabled && !hasCommandVars) {
        return [...current, ...createCommandVariables()];
      }
      if (!enabled && hasCommandVars) {
        return current.filter((variable) => !isCommandVariable(variable));
      }
      return current;
    });
  }, []);

  const setCommandResults = useCallback((entries: CommandEntry[]) => {
    const commandsByName: Record<string, CommandEntry> = {};
    for (const entry of entries) {
      commandsByName[entry.name] = entry;
    }
    // The last configured command is the most recently executed one, matching
    // the workflow step's "command" alias.
    const latest = entries.length > 0 ? entries[entries.length - 1] : null;

    const valueById: Record<string, string> = {
      "auto:commands": JSON.stringify(entries, null, 2),
      "auto:commands_by_name": JSON.stringify(commandsByName, null, 2),
      "auto:command": latest ? JSON.stringify(latest, null, 2) : "",
    };

    setVariables((current) =>
      current.map((variable) =>
        variable.id in valueById
          ? { ...variable, value: valueById[variable.id] }
          : variable,
      ),
    );
  }, []);

  const toggleParsedConfigVariable = useCallback((enabled: boolean) => {
    setVariables((current) => {
      const hasParsedConfigVar = current.some(isParsedConfigVariable);
      if (enabled && !hasParsedConfigVar) {
        return [...current, ...createParsedConfigVariable()];
      }
      if (!enabled && hasParsedConfigVar) {
        return current.filter((variable) => !isParsedConfigVariable(variable));
      }
      return current;
    });
  }, []);

  /** Merge one named entry into the shared `parsed` auto-variable's JSON
   * object -- `{...current, [key]: entry}` -- rather than replacing the
   * whole value, so multiple sources (Get Configs's "cisco_config", a
   * Batfish facts preview's output_key) can populate `parsed` without
   * clobbering each other. `entry === null`/`undefined` removes that key
   * instead of setting it to null, so a cleared source doesn't leave
   * clutter behind. */
  const setParsedNamespaceEntry = useCallback((key: string, entry: unknown) => {
    setVariables((current) =>
      current.map((variable) => {
        if (variable.id !== PARSED_CONFIG_VARIABLE_ID) return variable;
        let parsedValue: Record<string, unknown> = {};
        if (variable.value) {
          try {
            const existing: unknown = JSON.parse(variable.value);
            if (existing && typeof existing === "object" && !Array.isArray(existing)) {
              parsedValue = existing as Record<string, unknown>;
            }
          } catch {
            parsedValue = {};
          }
        }
        if (entry === null || entry === undefined) {
          delete parsedValue[key];
        } else {
          parsedValue = { ...parsedValue, [key]: entry };
        }
        const hasEntries = Object.keys(parsedValue).length > 0;
        return { ...variable, value: hasEntries ? JSON.stringify(parsedValue, null, 2) : "" };
      }),
    );
  }, []);

  const clearParsedNamespaceEntry = useCallback(
    (key: string) => setParsedNamespaceEntry(key, null),
    [setParsedNamespaceEntry],
  );

  const setParsedConfig = useCallback(
    (entry: unknown) => setParsedNamespaceEntry("cisco_config", entry),
    [setParsedNamespaceEntry],
  );

  const toggleBatfishVariable = useCallback((enabled: boolean) => {
    setVariables((current) => {
      const hasBatfishVar = current.some(isBatfishVariable);
      if (enabled && !hasBatfishVar) {
        return [...current, ...createBatfishVariable()];
      }
      if (!enabled && hasBatfishVar) {
        return current.filter((variable) => !isBatfishVariable(variable));
      }
      return current;
    });
  }, []);

  const setBatfishResult = useCallback((result: BatfishQueryResult | null) => {
    setVariables((current) =>
      current.map((variable) =>
        variable.id === BATFISH_VARIABLE_ID
          ? { ...variable, value: result ? JSON.stringify(result, null, 2) : "" }
          : variable,
      ),
    );
  }, []);

  const setRunInputSource = useCallback((source: RunInputSource | null) => {
    setVariables((current) => {
      const withoutRunInput = current.filter((variable) => variable.id !== RUN_INPUT_VARIABLE_ID);
      if (!source) return withoutRunInput;

      const preview = Object.fromEntries(
        source.attributes.map((attr) => [attr.name, attr.default ?? null]),
      );
      return [
        ...withoutRunInput,
        {
          id: RUN_INPUT_VARIABLE_ID,
          name: "run_input",
          value: JSON.stringify(preview, null, 2),
          type: "auto",
          isAutoFilled: true,
          description:
            `Values supplied when workflow "${source.workflowName}" is triggered ` +
            "manually (Properties panel → Static Attributes). Access as {{ run_input.<name> }}.",
        },
      ];
    });
  }, []);

  const mergeCustomVariables = useCallback(
    (entries: ParsedVariableEntry[], mode: MergeVariablesMode) => {
      setVariables((current) => {
        const autoNames = new Set(
          current.filter((variable) => variable.isAutoFilled).map((variable) => variable.name),
        );
        const byName = new Map(current.map((variable) => [variable.name, variable] as const));
        let next = current;

        for (const { name, value } of entries) {
          if (!name || autoNames.has(name)) {
            continue;
          }
          const existing = byName.get(name);
          if (existing) {
            if (mode === "overwrite" && !existing.isAutoFilled) {
              next = next.map((variable) =>
                variable.id === existing.id ? { ...variable, value } : variable,
              );
            }
            continue;
          }
          customVariableCounter += 1;
          const created: EditorVariable = {
            id: `custom:${customVariableCounter}`,
            name,
            value,
            type: "custom",
            isAutoFilled: false,
          };
          next = [...next, created];
          byName.set(name, created);
        }

        return next;
      });
    },
    [],
  );

  const loadCustomVariables = useCallback(
    (record: Record<string, TemplateVariableRecord>) => {
      const custom: EditorVariable[] = Object.entries(record).map(([name, entry]) => {
        customVariableCounter += 1;
        return {
          id: `custom:${customVariableCounter}`,
          name,
          value: entry.value ?? "",
          type: entry.type ?? "custom",
          isAutoFilled: false,
        };
      });
      setVariables([...createAutoVariables(), ...custom]);
    },
    [],
  );

  return useMemo(
    () => ({
      variables,
      addVariable,
      removeVariable,
      updateVariableValue,
      setDeviceInfo,
      setNautobotAttributes,
      toggleCommandVariables,
      setCommandResults,
      toggleParsedConfigVariable,
      setParsedConfig,
      setParsedNamespaceEntry,
      clearParsedNamespaceEntry,
      toggleBatfishVariable,
      setBatfishResult,
      setRunInputSource,
      mergeCustomVariables,
      loadCustomVariables,
    }),
    [
      variables,
      addVariable,
      removeVariable,
      updateVariableValue,
      setDeviceInfo,
      setNautobotAttributes,
      toggleCommandVariables,
      setCommandResults,
      toggleParsedConfigVariable,
      setParsedConfig,
      setParsedNamespaceEntry,
      clearParsedNamespaceEntry,
      toggleBatfishVariable,
      setBatfishResult,
      setRunInputSource,
      mergeCustomVariables,
      loadCustomVariables,
    ],
  );
}
