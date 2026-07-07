"use client";

import { useCallback, useMemo, useState } from "react";

import { NETMIKO_AUTO_VARIABLES, PRE_RUN_VARIABLES } from "../constants";
import type { EditorVariable, TemplateVariableRecord } from "../types";

let customVariableCounter = 0;

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

function createPreRunVariables(): EditorVariable[] {
  return PRE_RUN_VARIABLES.map((variable) => ({
    id: `auto:${variable.name}`,
    name: variable.name,
    value: "",
    type: "auto",
    isAutoFilled: true,
    description: variable.description,
  }));
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

  const updateDeviceData = useCallback((data: { devices: unknown; device_details: unknown } | null) => {
    setVariables((current) =>
      current.map((variable) => {
        if (variable.id === "auto:devices") {
          return {
            ...variable,
            value: data ? JSON.stringify(data.devices, null, 2) : "",
          };
        }
        if (variable.id === "auto:device_details") {
          return {
            ...variable,
            value: data ? JSON.stringify(data.device_details, null, 2) : "",
          };
        }
        return variable;
      }),
    );
  }, []);

  const togglePreRunVariables = useCallback((enabled: boolean) => {
    setVariables((current) => {
      const hasPreRun = current.some((variable) => variable.name === "command.raw");
      if (enabled && !hasPreRun) {
        return [...current, ...createPreRunVariables()];
      }
      if (!enabled && hasPreRun) {
        return current.filter((variable) => !variable.name.startsWith("command."));
      }
      return current;
    });
  }, []);

  const setPreRunExecuting = useCallback((executing: boolean) => {
    setVariables((current) =>
      current.map((variable) =>
        variable.name.startsWith("command.")
          ? { ...variable, isExecuting: executing }
          : variable,
      ),
    );
  }, []);

  const setPreRunOutput = useCallback((raw: string, parsed: string) => {
    setVariables((current) =>
      current.map((variable) => {
        if (variable.name === "command.raw") {
          return { ...variable, value: raw, isExecuting: false };
        }
        if (variable.name === "command.parsed") {
          return { ...variable, value: parsed, isExecuting: false };
        }
        return variable;
      }),
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
      updateDeviceData,
      togglePreRunVariables,
      setPreRunExecuting,
      setPreRunOutput,
      loadCustomVariables,
    }),
    [
      variables,
      addVariable,
      removeVariable,
      updateVariableValue,
      updateDeviceData,
      togglePreRunVariables,
      setPreRunExecuting,
      setPreRunOutput,
      loadCustomVariables,
    ],
  );
}
