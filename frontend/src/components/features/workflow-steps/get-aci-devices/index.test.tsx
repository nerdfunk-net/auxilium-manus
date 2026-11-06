import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GetAciDevicesPlugin } from "./index";

const h = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  state: { isPending: false, isError: false, error: null as unknown },
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks/queries/use-aci-sources-query", () => ({
  useAciSourcesQuery: () => ({ data: { sources: [], total: 0 }, isLoading: false }),
}));
vi.mock("@/hooks/queries/use-get-aci-devices-preview-mutation", () => ({
  ACI_PREVIEW_LIMIT: 25,
  useGetAciDevicesPreviewMutation: () => ({
    mutateAsync: h.mutateAsync,
    isPending: h.state.isPending,
    isError: h.state.isError,
    error: h.state.error,
  }),
}));

const { ConfigPanel } = GetAciDevicesPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

function lastConfig(onChange: ReturnType<typeof setup>): Config {
  const calls = onChange.mock.calls;
  return calls[calls.length - 1]![0];
}

const previewButton = () => screen.getByRole("button", { name: /Show Preview|Loading/ }) as HTMLButtonElement;

beforeEach(() => {
  h.mutateAsync.mockReset();
  h.state.isPending = false;
  h.state.isError = false;
  h.state.error = null;
});

describe("source", () => {
  it("asks for a source when none is set", () => {
    setup({});
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure Source" })).toBeTruthy();
  });

  it("shows the configured source id", () => {
    setup({ aci_source_id: "lab-aci" });
    expect(screen.getByText("lab-aci")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit Source" })).toBeTruthy();
  });
});

describe("safety guard", () => {
  it("warns that a filter or allow_all is needed", () => {
    setup({ aci_source_id: "lab" });
    expect(screen.getByText("Add at least one filter, or enable allow_all.")).toBeTruthy();
  });

  it("warns that allow_all selects the whole fabric", () => {
    setup({ aci_source_id: "lab", allow_all: true });
    expect(screen.getByText(/every leaf and spine of the fabric will be selected/)).toBeTruthy();
    expect(screen.queryByText("Add at least one filter, or enable allow_all.")).toBeNull();
  });

  it("stores allow_all without touching the other settings", () => {
    const onChange = setup({ aci_source_id: "lab", filters: { names: ["a"] } });
    fireEvent.click(screen.getByRole("switch", { name: "Allow selecting every switch" }));
    expect(lastConfig(onChange)).toEqual({
      aci_source_id: "lab",
      filters: { names: ["a"] },
      allow_all: true,
    });
  });

  it("stores max_devices as a positive whole number, otherwise null", () => {
    const onChange = setup({});
    const input = screen.getByLabelText("max_devices");
    fireEvent.change(input, { target: { value: "25" } });
    expect(lastConfig(onChange).max_devices).toBe(25);
    fireEvent.change(input, { target: { value: "0" } });
    expect(lastConfig(onChange).max_devices).toBeNull();
    fireEvent.change(input, { target: { value: "" } });
    expect(lastConfig(onChange).max_devices).toBeNull();
  });
});

describe("filters", () => {
  it("offers every filter kind that is not yet used", () => {
    setup({ filters: { names: [] } });
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("Role");
    expect(options).toContain("CIDR");
    expect(options).not.toContain("Name");
  });

  it("adds a list filter as an empty list and cidr as an empty string", () => {
    const onChange = setup({});
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "models" } });
    expect(lastConfig(onChange).filters).toEqual({ models: [] });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "cidr" } });
    expect(lastConfig(onChange).filters).toEqual({ cidr: "" });
  });

  it("keeps blank lines while typing", () => {
    const onChange = setup({ filters: { names: [] } });
    fireEvent.change(screen.getByPlaceholderText(/dc1-leaf-\*/), {
      target: { value: "leaf-*\n" },
    });
    expect(lastConfig(onChange).filters).toEqual({ names: ["leaf-*", ""] });
  });

  it("removes a filter", () => {
    const onChange = setup({ filters: { names: ["a"], models: ["m"] } });
    fireEvent.click(screen.getByRole("button", { name: "Remove Name filter" }));
    expect(lastConfig(onChange).filters).toEqual({ models: ["m"] });
  });

  it("never mutates the config it was given", () => {
    const config: Config = { filters: { names: ["a"] } };
    const snapshot = JSON.stringify(config);
    setup(config);
    fireEvent.click(screen.getByRole("button", { name: "Remove Name filter" }));
    expect(JSON.stringify(config)).toBe(snapshot);
  });

  it("shows ids that were stored as numbers instead of an empty, unconfigured-looking box", () => {
    setup({ aci_source_id: "lab", filters: { node_ids: [101, 102] } });
    expect((screen.getByPlaceholderText(/101/) as HTMLTextAreaElement).value).toBe("101\n102");
  });

  it("keeps numeric ids when another filter is edited afterwards", () => {
    const onChange = setup({ filters: { node_ids: [101, 102], names: ["a"] } });
    fireEvent.click(screen.getByRole("button", { name: "Remove Name filter" }));
    expect(lastConfig(onChange).filters).toEqual({ node_ids: ["101", "102"] });
  });

  it("previews with the numeric ids a config stored", async () => {
    h.mutateAsync.mockResolvedValue({ devices: [], truncated: false });
    setup({ aci_source_id: "lab", filters: { node_ids: [101] } });
    await act(async () => {
      fireEvent.click(previewButton());
    });
    expect(h.mutateAsync).toHaveBeenCalledWith({ source_id: "lab", filters: { node_ids: [101] } });
  });

  it("says that an unticked role row is not a filter", () => {
    setup({ aci_source_id: "lab", filters: { roles: [] } });
    expect(screen.getByText(/not a filter/i)).toBeTruthy();
    // ...which is also what the guard below it says, so the two texts agree
    expect(screen.getByText("Add at least one filter, or enable allow_all.")).toBeTruthy();
  });

  it("offers only leaf and spine as role choices, never the controller", () => {
    setup({ filters: { roles: [] } });
    expect(screen.getByRole("checkbox", { name: "leaf" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "spine" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /controller/ })).toBeNull();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("ticks roles in canonical order and unticks them again", () => {
    const onChange = setup({ filters: { roles: ["spine"] } });
    fireEvent.click(screen.getByRole("checkbox", { name: "leaf" }));
    expect((lastConfig(onChange).filters as Config).roles).toEqual(["leaf", "spine"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "spine" }));
    expect((lastConfig(onChange).filters as Config).roles).toEqual([]);
  });

  it("shows the current role selection", () => {
    setup({ filters: { roles: ["leaf"] } });
    expect(screen.getByRole("checkbox", { name: "leaf" }).getAttribute("data-state")).toBe("checked");
    expect(screen.getByRole("checkbox", { name: "spine" }).getAttribute("data-state")).toBe("unchecked");
  });
});

describe("preview", () => {
  it("is disabled without a source", () => {
    setup({ filters: { names: ["leaf-*"] } });
    expect(previewButton().disabled).toBe(true);
  });

  it("is disabled with a source but neither a filter nor allow_all", () => {
    setup({ aci_source_id: "lab", filters: { names: ["", "  "], roles: [] } });
    expect(previewButton().disabled).toBe(true);
  });

  it("is enabled with a source and a filter, or with allow_all", () => {
    setup({ aci_source_id: "lab", filters: { names: ["leaf-*"] } });
    expect(previewButton().disabled).toBe(false);
  });

  it("is enabled with a source and allow_all", () => {
    setup({ aci_source_id: "lab", allow_all: true });
    expect(previewButton().disabled).toBe(false);
  });

  it("is disabled while a preview is loading", () => {
    h.state.isPending = true;
    setup({ aci_source_id: "lab", allow_all: true });
    expect(previewButton().disabled).toBe(true);
    expect(previewButton().textContent).toBe("Loading…");
  });

  it("sends the cleaned filters (numbers as numbers) and shows the result", async () => {
    h.mutateAsync.mockResolvedValue({
      devices: [
        {
          node_id: 101,
          name: "leaf-1",
          role: "leaf",
          pod_id: 1,
          model: "N9K-C9396PX",
          serial_number: "TEP-1-101",
          software_version: "simsw-6.1(4h)",
          fabric_state: "active",
          management_ip: null,
        },
      ],
      truncated: false,
    });
    setup({
      aci_source_id: "lab",
      filters: { node_ids: ["101", ""], names: [" leaf-* "], cidr: "  " },
    });
    await act(async () => {
      fireEvent.click(previewButton());
    });
    expect(h.mutateAsync).toHaveBeenCalledWith({
      source_id: "lab",
      filters: { names: ["leaf-*"], node_ids: [101] },
    });
    await waitFor(() => expect(screen.getByText("Switch Preview")).toBeTruthy());
    expect(screen.getByText("leaf-1")).toBeTruthy();
    expect(screen.getByText("none configured")).toBeTruthy();
    expect(screen.getByText("1 switch found", { exact: false })).toBeTruthy();
  });

  it("says when more switches match than the preview shows", async () => {
    h.mutateAsync.mockResolvedValue({ devices: [], truncated: true });
    setup({ aci_source_id: "lab", allow_all: true });
    await act(async () => {
      fireEvent.click(previewButton());
    });
    await waitFor(() => expect(screen.getByText("No switches match the configured filters.")).toBeTruthy());
  });

  it("reports a failed preview without opening the dialog", async () => {
    h.mutateAsync.mockRejectedValue(new Error("boom"));
    h.state.isError = true;
    h.state.error = new Error("APIC rejected the credentials");
    setup({ aci_source_id: "lab", allow_all: true });
    await act(async () => {
      fireEvent.click(previewButton());
    });
    expect(screen.getByText(/Preview failed:/).textContent).toContain("APIC rejected the credentials");
    expect(screen.queryByText("Switch Preview")).toBeNull();
  });
});

describe("plugin", () => {
  it("also provides the Help tab", () => {
    expect(GetAciDevicesPlugin.HelpPanel).toBeDefined();
  });
});
