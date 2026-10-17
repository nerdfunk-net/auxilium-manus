"use client";

import { useMutation } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type { CommandEntry, DeviceSummary, GetConfigsResponse } from "../types";
import { bareIp } from "../utils/bare-ip";
import type { useTemplateVariables } from "./use-template-variables";

type TemplateVariablesManager = ReturnType<typeof useTemplateVariables>;

interface UseTemplateEditorDeviceOptions {
  selectedDevice: DeviceSummary | null;
  credentialId: string;
  cleanedCommands: string[];
  useTextfsm: boolean;
  setCommandResults: TemplateVariablesManager["setCommandResults"];
  setParsedConfig: TemplateVariablesManager["setParsedConfig"];
}

export function useTemplateEditorDevice({
  selectedDevice,
  credentialId,
  cleanedCommands,
  useTextfsm,
  setCommandResults,
  setParsedConfig,
}: UseTemplateEditorDeviceOptions) {
  const { toast } = useToast();
  const { apiCall } = useApi();
  const [isExecutingCommands, setIsExecutingCommands] = useState(false);

  const fetchDeviceConfigsMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDevice || credentialId === "none") {
        throw new Error("Select a device and credential first");
      }
      const host = bareIp(selectedDevice.primary_ip4) ?? selectedDevice.name ?? "";
      return apiCall<GetConfigsResponse>("netmiko/get-configs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host,
          platform: selectedDevice.platform,
          network_driver: selectedDevice.network_driver,
          credential_id: Number(credentialId),
        }),
      });
    },
    onSuccess: (response) => {
      if (!response.success) {
        toast({
          title: "Get Configs failed",
          description: response.error ?? "Unknown error",
          variant: "destructive",
        });
        setParsedConfig(null);
        return;
      }
      setParsedConfig(response.parsed);
    },
    onError: (error) => {
      toast({
        title: "Get Configs failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
      setParsedConfig(null);
    },
  });

  const handleFetchConfigs = useCallback(() => {
    fetchDeviceConfigsMutation.mutate();
  }, [fetchDeviceConfigsMutation]);

  const canExecuteCommands = Boolean(
    selectedDevice && credentialId !== "none" && cleanedCommands.length > 0,
  );

  const executeHint = !selectedDevice
    ? "Select a test device to execute commands."
    : credentialId === "none"
      ? "Select SSH credentials to execute commands."
      : cleanedCommands.length === 0
        ? "Add at least one command to execute."
        : undefined;

  const handleExecuteCommands = useCallback(async () => {
    if (!selectedDevice || credentialId === "none" || cleanedCommands.length === 0) {
      return;
    }

    const host = bareIp(selectedDevice.primary_ip4) ?? selectedDevice.name ?? "";
    if (!host) {
      toast({
        title: "No device address",
        description: "The selected device has no primary IP or name",
        variant: "destructive",
      });
      return;
    }

    setIsExecutingCommands(true);
    try {
      const response = await apiCall<{
        success: boolean;
        commands: CommandEntry[];
        error: string | null;
      }>("netmiko/run-commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host,
          platform: selectedDevice.platform,
          network_driver: selectedDevice.network_driver,
          credential_id: Number(credentialId),
          commands: cleanedCommands,
          use_textfsm: useTextfsm,
        }),
      });

      setCommandResults(response.commands ?? []);
      if (!response.success) {
        throw new Error(response.error ?? "Command execution failed");
      }

      toast({
        title: "Commands executed",
        description: `Populated command, commands and commands_by_name from ${
          response.commands?.length ?? 0
        } command(s)`,
      });
    } catch (error) {
      toast({
        title: "Execution failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsExecutingCommands(false);
    }
  }, [
    selectedDevice,
    credentialId,
    cleanedCommands,
    useTextfsm,
    apiCall,
    toast,
    setCommandResults,
  ]);

  return {
    isFetchingConfigs: fetchDeviceConfigsMutation.isPending,
    canFetchConfigs: Boolean(selectedDevice) && credentialId !== "none",
    handleFetchConfigs,
    canExecuteCommands,
    isExecutingCommands,
    executeHint,
    handleExecuteCommands,
  };
}
