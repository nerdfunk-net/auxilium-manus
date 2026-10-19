import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { DeviceSummary } from "../types";
import { useTemplateEditorDevice } from "./use-template-editor-device";

const h = vi.hoisted(() => ({
  apiCall: vi.fn(),
  toast: vi.fn(),
  setCommandResults: vi.fn(),
  setParsedConfig: vi.fn(),
}));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));

const DEVICE: DeviceSummary = {
  id: "d1",
  name: "core-1",
  primary_ip4: "10.0.0.1/24",
  platform: "cisco_ios",
  network_driver: "cisco_ios",
};
const COMMANDS = ["show version", "show ip int brief"];

interface Props {
  selectedDevice: DeviceSummary | null;
  credentialId: string;
  cleanedCommands: string[];
  useTextfsm: boolean;
}

const DEFAULTS: Props = {
  selectedDevice: DEVICE,
  credentialId: "5",
  cleanedCommands: COMMANDS,
  useTextfsm: false,
};

function setup(props: Partial<Props> = {}) {
  const { wrapper } = createQueryWrapper();
  return renderHook(
    (p: Props) =>
      useTemplateEditorDevice({
        ...p,
        setCommandResults: h.setCommandResults,
        setParsedConfig: h.setParsedConfig,
      }),
    { wrapper, initialProps: { ...DEFAULTS, ...props } },
  );
}

beforeEach(() => {
  h.apiCall.mockReset();
  h.toast.mockReset();
  h.setCommandResults.mockReset();
  h.setParsedConfig.mockReset();
});

describe("availability flags", () => {
  it("fetching needs a device and a credential", () => {
    expect(setup().result.current.canFetchConfigs).toBe(true);
    expect(setup({ selectedDevice: null }).result.current.canFetchConfigs).toBe(false);
    expect(setup({ credentialId: "none" }).result.current.canFetchConfigs).toBe(false);
  });

  it("executing also needs at least one command", () => {
    expect(setup().result.current.canExecuteCommands).toBe(true);
    expect(setup({ cleanedCommands: [] }).result.current.canExecuteCommands).toBe(false);
    expect(setup({ selectedDevice: null }).result.current.canExecuteCommands).toBe(false);
    expect(setup({ credentialId: "none" }).result.current.canExecuteCommands).toBe(false);
  });

  it.each([
    [{ selectedDevice: null }, "Select a test device to execute commands."],
    [{ credentialId: "none" }, "Select SSH credentials to execute commands."],
    [{ cleanedCommands: [] }, "Add at least one command to execute."],
    [{}, undefined],
  ] as [Partial<Props>, string | undefined][])("hint for %j", (props, hint) => {
    expect(setup(props).result.current.executeHint).toBe(hint);
  });
});

describe("handleFetchConfigs", () => {
  it("posts the bare IP, platform, driver and numeric credential id", async () => {
    h.apiCall.mockResolvedValue({ success: true, parsed: { hostname: "core-1" }, error: null });
    const { result } = setup();
    act(() => result.current.handleFetchConfigs());
    await waitFor(() => expect(h.setParsedConfig).toHaveBeenCalledWith({ hostname: "core-1" }));
    const [endpoint, init] = h.apiCall.mock.calls[0];
    expect(endpoint).toBe("netmiko/get-configs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      host: "10.0.0.1",
      platform: "cisco_ios",
      network_driver: "cisco_ios",
      credential_id: 5,
    });
  });

  it("falls back to the device name when it has no IP", async () => {
    h.apiCall.mockResolvedValue({ success: true, parsed: {}, error: null });
    const { result } = setup({ selectedDevice: { ...DEVICE, primary_ip4: null } });
    act(() => result.current.handleFetchConfigs());
    await waitFor(() => expect(h.apiCall).toHaveBeenCalled());
    expect(JSON.parse(h.apiCall.mock.calls[0][1].body).host).toBe("core-1");
  });

  it("does not send a request for a device with neither IP nor name", async () => {
    const { result } = setup({ selectedDevice: { ...DEVICE, primary_ip4: null, name: null } });
    act(() => result.current.handleFetchConfigs());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Get Configs failed", variant: "destructive" }),
      ),
    );
    expect(h.apiCall).not.toHaveBeenCalled();
    expect(h.setParsedConfig).toHaveBeenCalledWith(null);
  });

  it("a backend-reported failure toasts its message and clears the parsed config", async () => {
    h.apiCall.mockResolvedValue({ success: false, parsed: null, error: "auth failed" });
    const { result } = setup();
    act(() => result.current.handleFetchConfigs());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith({
        title: "Get Configs failed",
        description: "auth failed",
        variant: "destructive",
      }),
    );
    expect(h.setParsedConfig).toHaveBeenCalledWith(null);
  });

  it("a failure without a message says Unknown error", async () => {
    h.apiCall.mockResolvedValue({ success: false, parsed: null, error: null });
    const { result } = setup();
    act(() => result.current.handleFetchConfigs());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ description: "Unknown error" })),
    );
  });

  it("a rejected request toasts the error and clears the parsed config", async () => {
    h.apiCall.mockRejectedValue(new Error("502 bad gateway"));
    const { result } = setup();
    act(() => result.current.handleFetchConfigs());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith(
        expect.objectContaining({ description: "502 bad gateway" }),
      ),
    );
    expect(h.setParsedConfig).toHaveBeenCalledWith(null);
  });

  it("refuses without a device or credential, with a message", async () => {
    const { result } = setup({ credentialId: "none" });
    act(() => result.current.handleFetchConfigs());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith(
        expect.objectContaining({ description: "Select a device and credential first" }),
      ),
    );
    expect(h.apiCall).not.toHaveBeenCalled();
  });

  it("reports pending while the request runs", async () => {
    let finish!: (value: unknown) => void;
    h.apiCall.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = setup();
    act(() => result.current.handleFetchConfigs());
    await waitFor(() => expect(result.current.isFetchingConfigs).toBe(true));
    await act(async () => finish({ success: true, parsed: {}, error: null }));
    await waitFor(() => expect(result.current.isFetchingConfigs).toBe(false));
  });
});

describe("handleExecuteCommands", () => {
  const ok = (commands: unknown[] = [{ command: "show version" }, { command: "x" }]) => ({
    success: true,
    commands,
    error: null,
  });

  it("posts the commands with the textfsm flag and stores the results", async () => {
    h.apiCall.mockResolvedValue(ok());
    const { result } = setup({ useTextfsm: true });
    await act(() => result.current.handleExecuteCommands());
    const [endpoint, init] = h.apiCall.mock.calls[0];
    expect(endpoint).toBe("netmiko/run-commands");
    expect(JSON.parse(init.body)).toEqual({
      host: "10.0.0.1",
      platform: "cisco_ios",
      network_driver: "cisco_ios",
      credential_id: 5,
      commands: COMMANDS,
      use_textfsm: true,
    });
    expect(h.setCommandResults).toHaveBeenCalledWith([{ command: "show version" }, { command: "x" }]);
    expect(h.toast).toHaveBeenCalledWith({
      title: "Commands executed",
      description: "Populated command, commands and commands_by_name from 2 command(s)",
    });
  });

  it("is busy only while the request runs", async () => {
    let finish!: (value: unknown) => void;
    h.apiCall.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = setup();
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.handleExecuteCommands();
    });
    expect(result.current.isExecutingCommands).toBe(true);
    await act(async () => {
      finish(ok());
      await pending;
    });
    expect(result.current.isExecutingCommands).toBe(false);
  });

  it("does nothing while the preconditions are missing", async () => {
    for (const props of [{ selectedDevice: null }, { credentialId: "none" }, { cleanedCommands: [] }]) {
      const { result } = setup(props);
      await act(() => result.current.handleExecuteCommands());
    }
    expect(h.apiCall).not.toHaveBeenCalled();
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("a device with neither IP nor name is reported before any request", async () => {
    const { result } = setup({ selectedDevice: { ...DEVICE, primary_ip4: null, name: null } });
    await act(() => result.current.handleExecuteCommands());
    expect(h.apiCall).not.toHaveBeenCalled();
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "No device address", variant: "destructive" }),
    );
    expect(result.current.isExecutingCommands).toBe(false);
  });

  it("keeps the partial results and shows the error when the backend reports failure", async () => {
    h.apiCall.mockResolvedValue({ success: false, commands: [{ command: "show version" }], error: "timeout on 2nd command" });
    const { result } = setup();
    await act(() => result.current.handleExecuteCommands());
    expect(h.setCommandResults).toHaveBeenCalledWith([{ command: "show version" }]);
    expect(h.toast).toHaveBeenCalledWith({
      title: "Execution failed",
      description: "timeout on 2nd command",
      variant: "destructive",
    });
    expect(h.toast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "Commands executed" }));
  });

  it("a failure without a message uses the generic text", async () => {
    h.apiCall.mockResolvedValue({ success: false, commands: [], error: null });
    const { result } = setup();
    await act(() => result.current.handleExecuteCommands());
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: "Command execution failed" }),
    );
  });

  it("a missing command list becomes an empty result", async () => {
    h.apiCall.mockResolvedValue({ success: true, error: null });
    const { result } = setup();
    await act(() => result.current.handleExecuteCommands());
    expect(h.setCommandResults).toHaveBeenCalledWith([]);
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: expect.stringContaining("from 0 command(s)") }),
    );
  });

  it("a rejected request toasts and releases the busy flag", async () => {
    h.apiCall.mockRejectedValue(new Error("network down"));
    const { result } = setup();
    await act(() => result.current.handleExecuteCommands());
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Execution failed", description: "network down" }),
    );
    expect(result.current.isExecutingCommands).toBe(false);
    expect(h.setCommandResults).not.toHaveBeenCalled();
  });

  it("a non-Error rejection reads Unknown error", async () => {
    h.apiCall.mockRejectedValue("nope");
    const { result } = setup();
    await act(() => result.current.handleExecuteCommands());
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ description: "Unknown error" }));
  });
});

describe("useTemplateEditorDevice stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender({ ...DEFAULTS });
    expect(result.current).toBe(first);
  });

  it("keeps handleFetchConfigs stable between renders", () => {
    const { result, rerender } = setup();
    const first = result.current.handleFetchConfigs;
    rerender({ ...DEFAULTS });
    expect(result.current.handleFetchConfigs).toBe(first);
  });
});
