import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DeviceSummary } from "../types";
import { OptionsDialog } from "./options-dialog";

const h = vi.hoisted(() => ({
  credentials: vi.fn(),
  search: vi.fn(),
  perms: { credentialsRead: true, batfishQuery: true },
  credentialData: { value: undefined as unknown },
  devices: { value: [] as unknown[] },
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/hooks/use-has-permission", () => ({
  useHasPermission: (resource: string, action: string) => {
    if (resource === "credentials" && action === "read") return h.perms.credentialsRead;
    if (resource === "sources.batfish" && action === "query") return h.perms.batfishQuery;
    return false;
  },
}));
vi.mock("@/components/features/settings/credentials/hooks/use-credentials-query", () => ({
  useCredentialsQuery: (options: unknown) => {
    h.credentials(options);
    return { data: h.credentialData.value };
  },
}));
vi.mock("@/hooks/queries/use-netmiko-device-search-query", () => ({
  useNetmikoDeviceSearchQuery: (options: unknown) => {
    h.search(options);
    return { data: { devices: h.devices.value }, isFetching: false };
  },
}));
vi.mock("./batfish-options-tab", () => ({
  BatfishOptionsTab: () => <div data-testid="batfish-tab" />,
}));

type Props = React.ComponentProps<typeof OptionsDialog>;

function setup(over: Partial<Props> = {}) {
  const handlers = {
    onOpenChange: vi.fn(),
    onSourceChange: vi.fn(),
    onSelectDevice: vi.fn(),
    onConfigureCommands: vi.fn(),
    onConfigureAttributes: vi.fn(),
    onCredentialChange: vi.fn(),
    onGetConfigsChange: vi.fn(),
    onFetchConfigs: vi.fn(),
    onBatfishTargetConfigChange: vi.fn(),
    onBatfishQuestionChange: vi.fn(),
    onBatfishGenericQuestionNameChange: vi.fn(),
    onBatfishParamsChange: vi.fn(),
    onBatfishEnabledChange: vi.fn(),
    onRunBatfishQuery: vi.fn(),
  };
  const props: Props = {
    open: true,
    sources: [{ sourceId: "nb1" }, { sourceId: "nb2" }],
    sourceId: "nb1",
    sourceReady: true,
    commandCount: 0,
    attributeCount: 0,
    credentialId: "none",
    getConfigs: false,
    isFetchingConfigs: false,
    canFetchConfigs: true,
    batfishTargetConfig: {},
    batfishQuestion: "routes",
    batfishGenericQuestionName: "",
    batfishParams: {},
    batfishEnabled: false,
    isRunningBatfishQuery: false,
    canRunBatfishQuery: false,
    batfishResult: null,
    ...handlers,
    ...over,
  };
  render(<OptionsDialog {...props} />);
  return handlers;
}

const DEVICE_A: DeviceSummary = { id: "d-1", name: "edge-sw-1", primary_ip4: "10.0.0.1" } as DeviceSummary;
const DEVICE_B: DeviceSummary = { id: "d-2", name: "edge-sw-2", primary_ip4: null } as DeviceSummary;

const searchBox = () => screen.getByLabelText("Test Device (Optional)") as HTMLInputElement;
const typeDevice = (value: string) => fireEvent.change(searchBox(), { target: { value } });

beforeEach(() => {
  h.credentials.mockReset();
  h.search.mockReset();
  h.perms.credentialsRead = true;
  h.perms.batfishQuery = true;
  h.devices.value = [];
  h.credentialData.value = {
    credentials: [
      { id: 1, name: "ops-ssh", type: "ssh" },
      { id: 2, name: "api-token", type: "token" },
    ],
  };
});

describe("OptionsDialog", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByText("Options")).toBeNull();
  });

  describe("Batfish tab", () => {
    it("is offered to a user who may run Batfish queries", () => {
      setup();
      expect(screen.getByRole("tab", { name: "Batfish" })).toBeTruthy();
    });

    it("is hidden from a user who may not", () => {
      h.perms.batfishQuery = false;
      setup();
      expect(screen.queryByRole("tab", { name: "Batfish" })).toBeNull();
      expect(screen.getByRole("tab", { name: "Netmiko" })).toBeTruthy();
    });
  });

  describe("credentials", () => {
    it("lists only SSH credentials", () => {
      setup();
      const options = screen.getAllByRole("option").map((o) => o.textContent);
      expect(options).toContain("ops-ssh");
      expect(options).not.toContain("api-token");
    });

    it("does not request the list without credentials:read", () => {
      h.perms.credentialsRead = false;
      setup();
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: false });
    });

    it("requests the list with credentials:read", () => {
      setup();
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: true });
    });

    it("reports the chosen credential", () => {
      const { onCredentialChange } = setup();
      fireEvent.change(screen.getByDisplayValue("None"), { target: { value: "1" } });
      expect(onCredentialChange).toHaveBeenCalledWith("1");
    });

    it("copes with a list that has not loaded", () => {
      h.credentialData.value = undefined;
      setup();
      expect(screen.getAllByRole("option", { name: "None" }).length).toBeGreaterThan(0);
      expect(screen.queryByRole("option", { name: "ops-ssh" })).toBeNull();
    });
  });

  describe("Nautobot source", () => {
    it("lists the configured sources", () => {
      setup();
      expect(screen.getByRole("option", { name: "nb2" })).toBeTruthy();
    });

    it("says when none is configured", () => {
      setup({ sources: [], sourceId: "" });
      expect(screen.getByRole("option", { name: "No sources configured" })).toBeTruthy();
    });

    it("reports an empty source when the placeholder entry is chosen", () => {
      const { onSourceChange } = setup({ sources: [], sourceId: "" });
      fireEvent.change(screen.getAllByRole("combobox")[0]!, { target: { value: "__none__" } });
      expect(onSourceChange).toHaveBeenCalledWith("");
    });

    it("reports the chosen source", () => {
      const { onSourceChange } = setup();
      fireEvent.change(screen.getByDisplayValue("nb1"), { target: { value: "nb2" } });
      expect(onSourceChange).toHaveBeenCalledWith("nb2");
    });

    it("forgets the test device of the previous source", () => {
      const { onSourceChange, onSelectDevice } = setup();
      typeDevice("edge-sw-1");
      onSelectDevice.mockClear();
      fireEvent.change(screen.getByDisplayValue("nb1"), { target: { value: "nb2" } });
      expect(onSourceChange).toHaveBeenCalledWith("nb2");
      expect(onSelectDevice).toHaveBeenCalledWith(null);
      expect(searchBox().value).toBe("");
    });
  });

  describe("test device search", () => {
    it("is disabled until a source is ready", () => {
      setup({ sourceReady: false });
      expect(searchBox().disabled).toBe(true);
      expect(searchBox().placeholder).toBe("Select a Nautobot source first");
    });

    it("searches the chosen source", () => {
      setup();
      expect(h.search).toHaveBeenLastCalledWith({ sourceId: "nb1", searchTerm: "", enabled: true });
    });

    it("shows no results for fewer than three characters", () => {
      h.devices.value = [DEVICE_A];
      setup();
      typeDevice("ed");
      expect(screen.queryByText("edge-sw-1")).toBeNull();
    });

    it("shows the matching devices with their address", () => {
      h.devices.value = [DEVICE_A, DEVICE_B];
      setup();
      typeDevice("edge");
      expect(screen.getByText("edge-sw-1")).toBeTruthy();
      expect(screen.getByText("10.0.0.1")).toBeTruthy();
      expect(screen.getByText("No IP")).toBeTruthy();
    });

    it("selects a device, fills the box and hides the list", () => {
      h.devices.value = [DEVICE_A];
      const { onSelectDevice } = setup();
      typeDevice("edge");
      fireEvent.click(screen.getByText("edge-sw-1"));
      expect(onSelectDevice).toHaveBeenCalledWith(DEVICE_A);
      expect(searchBox().value).toBe("edge-sw-1");
      expect(screen.queryByText("10.0.0.1")).toBeNull();
    });

    it("falls back to the id for a device without a name", () => {
      h.devices.value = [{ id: "d-9", name: null, primary_ip4: null }];
      setup();
      typeDevice("d-9");
      fireEvent.click(screen.getByText("d-9"));
      expect(searchBox().value).toBe("d-9");
    });

    it("clears the selected device when the box is emptied", () => {
      const { onSelectDevice } = setup();
      typeDevice("edge");
      onSelectDevice.mockClear();
      typeDevice("");
      expect(onSelectDevice).toHaveBeenCalledWith(null);
    });

    it("treats a box with only spaces as empty", () => {
      const { onSelectDevice } = setup();
      typeDevice("   ");
      expect(onSelectDevice).toHaveBeenCalledWith(null);
    });

    it("does not clear the selection while the user is still typing", () => {
      const { onSelectDevice } = setup();
      typeDevice("edge");
      expect(onSelectDevice).not.toHaveBeenCalled();
    });

    it("closes the list on a click outside and reopens it on focus", () => {
      h.devices.value = [DEVICE_A];
      setup();
      typeDevice("edge");
      expect(screen.getByText("edge-sw-1")).toBeTruthy();
      fireEvent.mouseDown(document.body);
      expect(screen.queryByText("edge-sw-1")).toBeNull();
      fireEvent.focus(searchBox());
      expect(screen.getByText("edge-sw-1")).toBeTruthy();
    });

    it("keeps the list open for a click inside it", () => {
      h.devices.value = [DEVICE_A];
      setup();
      typeDevice("edge");
      fireEvent.mouseDown(searchBox());
      expect(screen.getByText("edge-sw-1")).toBeTruthy();
    });

    it("shows no list without a ready source", () => {
      h.devices.value = [DEVICE_A];
      setup({ sourceReady: false });
      expect(screen.queryByText("edge-sw-1")).toBeNull();
    });
  });

  describe("commands and attributes", () => {
    it("opens the command and attribute editors", () => {
      const { onConfigureCommands, onConfigureAttributes } = setup();
      fireEvent.click(screen.getByRole("button", { name: /Commands/ }));
      fireEvent.click(screen.getByRole("button", { name: /Nautobot/ }));
      expect(onConfigureCommands).toHaveBeenCalledTimes(1);
      expect(onConfigureAttributes).toHaveBeenCalledTimes(1);
    });

    it("shows how many of each are configured, and nothing for zero", () => {
      setup({ commandCount: 3, attributeCount: 5 });
      expect(screen.getByRole("button", { name: /Commands/ }).textContent).toContain("3");
      expect(screen.getByRole("button", { name: /Nautobot/ }).textContent).toContain("5");
    });

    it("shows no count badge when none is configured", () => {
      setup();
      expect(screen.getByRole("button", { name: /Commands/ }).textContent).toBe("Commands");
      expect(screen.getByRole("button", { name: /Nautobot/ }).textContent).toBe("Nautobot");
    });
  });

  describe("get configs", () => {
    it("toggles parsing of the config", () => {
      const { onGetConfigsChange } = setup();
      fireEvent.click(screen.getByRole("checkbox"));
      expect(onGetConfigsChange).toHaveBeenCalledWith(true);
    });

    it("offers Fetch only while parsing is on", () => {
      setup({ getConfigs: false });
      expect(screen.queryByRole("button", { name: /Fetch/ })).toBeNull();
    });

    it("fetches the configs", () => {
      const { onFetchConfigs } = setup({ getConfigs: true });
      fireEvent.click(screen.getByRole("button", { name: /Fetch/ }));
      expect(onFetchConfigs).toHaveBeenCalledTimes(1);
    });

    it("cannot fetch without a target or while fetching", () => {
      setup({ getConfigs: true, canFetchConfigs: false });
      expect((screen.getByRole("button", { name: /Fetch/ }) as HTMLButtonElement).disabled).toBe(true);
    });

    it("cannot fetch twice at once", () => {
      setup({ getConfigs: true, isFetchingConfigs: true });
      expect((screen.getByRole("button", { name: /Fetch/ }) as HTMLButtonElement).disabled).toBe(true);
    });
  });
});
