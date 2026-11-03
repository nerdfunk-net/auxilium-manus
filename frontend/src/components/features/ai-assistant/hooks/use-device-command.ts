"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type {
  CommandParser,
  CommandParseError,
  DeviceCommandResult,
} from "../types/ai-assistant";

interface DeviceCommandResponse {
  success: boolean;
  error: string | null;
  device_name: string;
  commands: string[];
  output: string;
  truncated: boolean;
  handle: string | null;
  parser?: CommandParser;
  parsed_handle?: string | null;
  parsed_text?: string;
  parse_errors?: CommandParseError[];
}

export interface DeviceCommandRequest {
  token: string;
  credentialId: number;
  /** The user's device type choice, only when the inventory names none Netmiko knows. */
  networkDriver?: string;
}

/**
 * The user's click on a proposed device command. The body is only the signed token and the SSH
 * credential: the device and the commands are in the token, so the request cannot ask for more
 * than the card showed. Not cached or retried: a retry would open another SSH session.
 */
export function useDeviceCommandMutation() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async ({
      token,
      credentialId,
      networkDriver,
    }: DeviceCommandRequest): Promise<DeviceCommandResult> => {
      const response = await apiCall<DeviceCommandResponse>(
        "ai/exec/device-command",
        {
          method: "POST",
          body: JSON.stringify({
            token,
            credential_id: credentialId,
            ...(networkDriver ? { network_driver: networkDriver } : {}),
          }),
        },
      );
      return {
        success: response.success,
        error: response.error,
        deviceName: response.device_name,
        commands: response.commands,
        output: response.output,
        truncated: response.truncated,
        handle: response.handle,
        parser: response.parser ?? "none",
        parsedHandle: response.parsed_handle ?? null,
        parsedText: response.parsed_text ?? "",
        parseErrors: response.parse_errors ?? [],
      };
    },
  });
}
