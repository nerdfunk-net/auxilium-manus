import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { ConditionTree, DeviceInfo } from "../types/device-selector";
import { mapPreviewDevices, useDevicePreview } from "./use-device-preview";
import type { RawPreviewDevice } from "./use-device-preview";

const h = vi.hoisted(() => ({ apiCall: vi.fn(), toast: vi.fn() }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));

const raw = (id: string, over: Partial<RawPreviewDevice> = {}): RawPreviewDevice => ({
  id,
  name: `sw-${id}`,
  serial: null,
  location: null,
  role: null,
  tags: [],
  device_type: null,
  manufacturer: null,
  platform: null,
  primary_ip4: null,
  status: null,
  ...over,
});

const cond = (id: string, field: string, value: string) => ({
  id,
  field,
  operator: "equals",
  value,
});

const EMPTY_TREE: ConditionTree = { type: "root", internalLogic: "AND", items: [] };
const TREE: ConditionTree = {
  type: "root",
  internalLogic: "AND",
  items: [cond("c1", "location", "berlin")],
};

const OPTIONS = { sourceId: "src-1", sourceReady: true };
const NOT_READY = { sourceId: "src-1", sourceReady: false };
const NO_DEVICES: DeviceInfo[] = [];

function respond(devices: RawPreviewDevice[], extra: Record<string, unknown> = {}) {
  h.apiCall.mockResolvedValue({
    devices,
    total_count: devices.length,
    operations_executed: 1,
    ...extra,
  });
}

function setup(
  tree: ConditionTree = TREE,
  options = OPTIONS,
  initialDevices: DeviceInfo[] = NO_DEVICES,
  selectedIds?: string[],
  onDevicesSelected?: Parameters<typeof useDevicePreview>[4],
  onSelectionChange?: Parameters<typeof useDevicePreview>[5],
) {
  const { wrapper } = createQueryWrapper();
  return renderHook(
    () =>
      useDevicePreview(
        tree,
        options,
        initialDevices,
        selectedIds,
        onDevicesSelected,
        onSelectionChange,
      ),
    { wrapper },
  );
}

async function load(result: { current: ReturnType<typeof useDevicePreview> }) {
  act(() => result.current.loadPreview());
  await waitFor(() => expect(result.current.isLoadingPreview).toBe(false));
}

beforeEach(() => {
  h.apiCall.mockReset();
  h.toast.mockReset();
});

describe("mapPreviewDevices", () => {
  it("turns null fields into undefined and keeps the rest", () => {
    expect(
      mapPreviewDevices([raw("a", { location: "ber", primary_ip4: "10.0.0.1", tags: ["x"] })]),
    ).toEqual([
      {
        id: "a",
        name: "sw-a",
        serial: null,
        location: "ber",
        role: undefined,
        device_type: undefined,
        manufacturer: undefined,
        platform: undefined,
        primary_ip4: "10.0.0.1",
        status: undefined,
        tags: ["x"],
      },
    ]);
  });

  it("falls back to an empty tag list when the API sent none", () => {
    const device = { ...raw("a"), tags: undefined } as unknown as RawPreviewDevice;
    expect(mapPreviewDevices([device])[0]?.tags).toEqual([]);
  });

  it("an empty list stays empty and the input is not mutated", () => {
    const input = [raw("a")];
    const snapshot = JSON.stringify(input);
    expect(mapPreviewDevices([])).toEqual([]);
    mapPreviewDevices(input);
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});

describe("loadPreview", () => {
  it("refuses without a Nautobot source and does not call the API", () => {
    const { result } = setup(TREE, NOT_READY);
    act(() => result.current.loadPreview());
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Nautobot source required", variant: "destructive" }),
    );
    expect(h.apiCall).not.toHaveBeenCalled();
  });

  it("refuses an empty condition tree", () => {
    const { result } = setup(EMPTY_TREE);
    act(() => result.current.loadPreview());
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "No conditions", variant: "destructive" }),
    );
    expect(h.apiCall).not.toHaveBeenCalled();
  });

  it("posts the source and the operations built from the tree", async () => {
    respond([raw("a")]);
    const { result } = setup();
    await load(result);
    expect(h.apiCall).toHaveBeenCalledTimes(1);
    const [endpoint, init] = h.apiCall.mock.calls[0];
    expect(endpoint).toBe("sources/nautobot/preview");
    expect(JSON.parse(init.body)).toEqual({
      source_id: "src-1",
      operations: [
        {
          operation_type: "AND",
          conditions: [{ field: "location", operator: "equals", value: "berlin" }],
          nested_operations: [],
        },
      ],
    });
  });

  it("exposes the mapped devices, the total and the operation count", async () => {
    respond([raw("a"), raw("b")], { total_count: 57, operations_executed: 3 });
    const { result } = setup();
    await load(result);
    expect(result.current.previewDevices.map((d) => d.id)).toEqual(["a", "b"]);
    expect(result.current.totalDevices).toBe(57);
    expect(result.current.operationsExecuted).toBe(3);
    expect(result.current.showPreviewResults).toBe(true);
  });

  it("reports loading while the request is in flight", async () => {
    let finish!: (value: unknown) => void;
    h.apiCall.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = setup();
    act(() => result.current.loadPreview());
    await waitFor(() => expect(result.current.isLoadingPreview).toBe(true));
    await act(async () => finish({ devices: [], total_count: 0, operations_executed: 1 }));
    await waitFor(() => expect(result.current.isLoadingPreview).toBe(false));
  });

  it("hands the devices and the flattened conditions to onDevicesSelected", async () => {
    respond([raw("a")]);
    const onDevicesSelected = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, undefined, onDevicesSelected);
    await load(result);
    expect(onDevicesSelected).toHaveBeenCalledTimes(1);
    const [devices, conditions] = onDevicesSelected.mock.calls[0];
    expect(devices.map((d: DeviceInfo) => d.id)).toEqual(["a"]);
    expect(conditions).toEqual([
      { field: "location", operator: "equals", value: "berlin", logic: "AND" },
    ]);
  });

  it("uses the latest callback, not the one from the first render", async () => {
    respond([raw("a")]);
    const first = vi.fn();
    const second = vi.fn();
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(
      ({ cb }) => useDevicePreview(TREE, OPTIONS, NO_DEVICES, undefined, cb),
      { wrapper, initialProps: { cb: first } },
    );
    rerender({ cb: second });
    await load(result);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("toasts the error when the preview fails", async () => {
    h.apiCall.mockRejectedValue(new Error("Nautobot timed out"));
    const { result } = setup();
    act(() => result.current.loadPreview());
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith({
        title: "Preview failed",
        description: "Nautobot timed out",
        variant: "destructive",
      }),
    );
  });

  it("a new preview goes back to page 1 and shows hidden results again", async () => {
    respond(Array.from({ length: 45 }, (_, i) => raw(`d${i}`)));
    const { result } = setup();
    await load(result);
    act(() => result.current.handlePageChange(3));
    act(() => result.current.setShowPreviewResults(false));
    expect(result.current.currentPage).toBe(3);
    expect(result.current.showPreviewResults).toBe(false);
    await load(result);
    expect(result.current.currentPage).toBe(1);
    expect(result.current.showPreviewResults).toBe(true);
  });
});

describe("initial devices", () => {
  const initial: DeviceInfo[] = [{ id: "i1", name: "saved", tags: [] }];

  it("shows the saved devices before any preview was loaded", () => {
    const { result } = setup(TREE, OPTIONS, initial);
    expect(result.current.previewDevices).toBe(initial);
    expect(result.current.totalDevices).toBe(1);
    expect(result.current.operationsExecuted).toBe(0);
    expect(result.current.showPreviewResults).toBe(true);
  });

  it("shows nothing without saved devices or a preview", () => {
    const { result } = setup();
    expect(result.current.previewDevices).toEqual([]);
    expect(result.current.showPreviewResults).toBe(false);
  });

  it("hiding the results wins over saved devices", () => {
    const { result } = setup(TREE, OPTIONS, initial);
    act(() => result.current.setShowPreviewResults(false));
    expect(result.current.showPreviewResults).toBe(false);
    act(() => result.current.setShowPreviewResults(true));
    expect(result.current.showPreviewResults).toBe(true);
  });

  it("a loaded preview replaces the saved devices", async () => {
    respond([raw("n1")]);
    const { result } = setup(TREE, OPTIONS, initial);
    await load(result);
    expect(result.current.previewDevices.map((d) => d.id)).toEqual(["n1"]);
  });
});

describe("selection", () => {
  const devices = [raw("a"), raw("b"), raw("c")];

  it("starts from the selected ids it was given", () => {
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, ["x", "y"]);
    expect(Array.from(result.current.selectedIds)).toEqual(["x", "y"]);
  });

  it("select all reports every id and device; clearing reports nothing", async () => {
    respond(devices);
    const onSelectionChange = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, undefined, undefined, onSelectionChange);
    await load(result);
    act(() => result.current.handleSelectAll(true));
    expect(onSelectionChange).toHaveBeenLastCalledWith(
      ["a", "b", "c"],
      expect.arrayContaining([expect.objectContaining({ id: "a" })]),
    );
    expect(result.current.selectedIds.size).toBe(3);
    act(() => result.current.handleSelectAll(false));
    expect(onSelectionChange).toHaveBeenLastCalledWith([], []);
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("toggling a device adds and removes it and reports the matching devices", async () => {
    respond(devices);
    const onSelectionChange = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, undefined, undefined, onSelectionChange);
    await load(result);
    act(() => result.current.handleSelectDevice("b", true));
    expect(onSelectionChange.mock.lastCall?.[0]).toEqual(["b"]);
    expect(onSelectionChange.mock.lastCall?.[1].map((d: DeviceInfo) => d.id)).toEqual(["b"]);
    act(() => result.current.handleSelectDevice("c", true));
    expect(onSelectionChange.mock.lastCall?.[0]).toEqual(["b", "c"]);
    act(() => result.current.handleSelectDevice("b", false));
    expect(onSelectionChange.mock.lastCall?.[0]).toEqual(["c"]);
    expect(Array.from(result.current.selectedIds)).toEqual(["c"]);
  });

  it("does not mutate the selected set it was given", () => {
    const { result } = setup();
    const before = result.current.selectedIds;
    act(() => result.current.handleSelectDevice("a", true));
    expect(before.size).toBe(0);
    expect(result.current.selectedIds).not.toBe(before);
  });

  it("works without an onSelectionChange callback", async () => {
    respond(devices);
    const { result } = setup();
    await load(result);
    expect(() => act(() => result.current.handleSelectDevice("a", true))).not.toThrow();
    expect(() => act(() => result.current.handleSelectAll(true))).not.toThrow();
  });
});

describe("selection after a new preview", () => {
  it("drops selected ids that are not in the new device list and reports the rest", async () => {
    respond([raw("a"), raw("b"), raw("c")]);
    const onSelectionChange = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, undefined, undefined, onSelectionChange);
    await load(result);
    act(() => result.current.handleSelectAll(true));
    onSelectionChange.mockClear();

    respond([raw("b"), raw("d")]);
    await load(result);

    expect(Array.from(result.current.selectedIds)).toEqual(["b"]);
    expect(onSelectionChange).toHaveBeenCalledTimes(1);
    expect(onSelectionChange.mock.lastCall?.[0]).toEqual(["b"]);
    expect(onSelectionChange.mock.lastCall?.[1].map((d: DeviceInfo) => d.id)).toEqual(["b"]);
  });

  it("selects nothing when no selected device is in the new list", async () => {
    respond([raw("a")]);
    const onSelectionChange = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, ["a"], undefined, onSelectionChange);
    await load(result);
    onSelectionChange.mockClear();

    respond([raw("x")]);
    await load(result);

    expect(result.current.selectedIds.size).toBe(0);
    expect(onSelectionChange).toHaveBeenCalledWith([], []);
  });

  it("does not report a selection that did not change", async () => {
    respond([raw("a"), raw("b")]);
    const onSelectionChange = vi.fn();
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, ["a"], undefined, onSelectionChange);
    await load(result);

    respond([raw("a"), raw("c")]);
    await load(result);

    expect(Array.from(result.current.selectedIds)).toEqual(["a"]);
    expect(onSelectionChange).not.toHaveBeenCalled();
  });

  it("works without an onSelectionChange callback", async () => {
    respond([raw("a")]);
    const { result } = setup(TREE, OPTIONS, NO_DEVICES, ["z"]);
    await load(result);
    expect(result.current.selectedIds.size).toBe(0);
  });
});

describe("paging", () => {
  const many = Array.from({ length: 45 }, (_, i) => raw(`d${i}`));

  it("slices 20 devices per page by default", async () => {
    respond(many);
    const { result } = setup();
    await load(result);
    expect(result.current.totalPages).toBe(3);
    expect(result.current.currentPageDevices).toHaveLength(20);
    act(() => result.current.handlePageChange(3));
    expect(result.current.currentPageDevices.map((d) => d.id)).toEqual(
      ["d40", "d41", "d42", "d43", "d44"],
    );
  });

  it("a larger page size changes the page count", async () => {
    respond(many);
    const { result } = setup();
    await load(result);
    act(() => result.current.setPageSize(50));
    expect(result.current.totalPages).toBe(1);
    expect(result.current.currentPageDevices).toHaveLength(45);
  });

  it("no devices means no pages", () => {
    const { result } = setup();
    expect(result.current.totalPages).toBe(0);
    expect(result.current.currentPageDevices).toEqual([]);
  });
});

describe("treeToFlatConditions", () => {
  it("flattens nested groups, using the group's logic for all but its first item", () => {
    const { result } = setup();
    const tree: ConditionTree = {
      type: "root",
      internalLogic: "AND",
      items: [
        cond("1", "role", "core"),
        {
          id: "g",
          type: "group",
          logic: "AND",
          internalLogic: "OR",
          items: [cond("2", "location", "ber"), cond("3", "location", "ham")],
        },
        cond("4", "status", "active"),
      ],
    };
    expect(result.current.treeToFlatConditions(tree)).toEqual([
      { field: "role", operator: "equals", value: "core", logic: "AND" },
      { field: "location", operator: "equals", value: "ber", logic: "AND" },
      { field: "location", operator: "equals", value: "ham", logic: "OR" },
      { field: "status", operator: "equals", value: "active", logic: "AND" },
    ]);
  });

  it("uses the root's logic from the second item on", () => {
    const { result } = setup();
    const tree: ConditionTree = {
      type: "root",
      internalLogic: "OR",
      items: [cond("1", "a", "1"), cond("2", "b", "2")],
    };
    expect(result.current.treeToFlatConditions(tree).map((c) => c.logic)).toEqual(["AND", "OR"]);
  });

  it("an empty tree flattens to nothing", () => {
    const { result } = setup();
    expect(result.current.treeToFlatConditions(EMPTY_TREE)).toEqual([]);
  });
});

describe("useDevicePreview stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("keeps loadPreview stable between renders", async () => {
    respond([raw("a")]);
    const { result, rerender } = setup();
    const first = result.current.loadPreview;
    rerender();
    expect(result.current.loadPreview).toBe(first);
  });
});
