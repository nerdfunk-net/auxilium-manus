"use client";

import { useCallback, useMemo, useState } from "react";

import { COMMAND_VARIABLES, NETMIKO_AUTO_VARIABLES } from "../constants";
import type { CommandEntry, EditorVariable, TemplateVariableRecord } from "../types";

let customVariableCounter = 0;

const COMMAND_VARIABLE_IDS = COMMAND_VARIABLES.map((variable) => `auto:${variable.name}`);

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
      loadCustomVariables,
    ],
  );
}
