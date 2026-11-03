import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDeviceCommandMutation } from "./use-device-command";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const response = {
  success: true,
  error: null,
  device_name: "LAB",
  commands: ["show running-config"],
  output: "$ show running-config\nhostname LAB",
  truncated: false,
  handle: "res_0123456789ab",
};

beforeEach(() => {
  apiCall.mockReset();
  apiCall.mockResolvedValue(response);
});

describe("useDeviceCommandMutation", () => {
  it("posts only the token and the credential, and maps the answer", async () => {
    const { result } = renderHook(() => useDeviceCommandMutation(), {
      wrapper,
    });

    const mapped = await result.current.mutateAsync({
      token: "signed.token",
      credentialId: 11,
    });

    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("ai/exec/device-command");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      token: "signed.token",
      credential_id: 11,
    });
    expect(mapped).toEqual({
      success: true,
      error: null,
      deviceName: "LAB",
      commands: ["show running-config"],
      output: "$ show running-config\nhostname LAB",
      truncated: false,
      handle: "res_0123456789ab",
      parser: "none",
      parsedHandle: null,
      parsedText: "",
      parseErrors: [],
    });
  });

  it("maps the parser fields of a parsed run", async () => {
    apiCall.mockResolvedValue({
      ...response,
      parser: "genie",
      parsed_handle: "res_aaaaaaaaaaaa",
      parsed_text: "[1]",
      parse_errors: [{ command: "show clock", error: "no parser" }],
    });
    const { result } = renderHook(() => useDeviceCommandMutation(), {
      wrapper,
    });

    const mapped = await result.current.mutateAsync({
      token: "signed.token",
      credentialId: 11,
    });

    expect(mapped.parser).toBe("genie");
    expect(mapped.parsedHandle).toBe("res_aaaaaaaaaaaa");
    expect(mapped.parsedText).toBe("[1]");
    expect(mapped.parseErrors).toEqual([
      { command: "show clock", error: "no parser" },
    ]);
  });

  it("adds the device type only when the user chose one", async () => {
    const { result } = renderHook(() => useDeviceCommandMutation(), {
      wrapper,
    });

    await result.current.mutateAsync({
      token: "t",
      credentialId: 1,
      networkDriver: "cisco_xe",
    });

    expect(JSON.parse(apiCall.mock.calls[0][1].body)).toEqual({
      token: "t",
      credential_id: 1,
      network_driver: "cisco_xe",
    });
  });

  it("does not retry a failed run (a retry would open another SSH session)", async () => {
    apiCall.mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useDeviceCommandMutation(), {
      wrapper,
    });

    await expect(
      result.current.mutateAsync({ token: "t", credentialId: 1 }),
    ).rejects.toThrow("nope");

    expect(apiCall).toHaveBeenCalledTimes(1);
  });
});
