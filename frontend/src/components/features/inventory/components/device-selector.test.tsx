import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeviceSelector } from "./device-selector";

// The mutation hooks toast in their own onError, so these tests drive the handlers the page hands to
// its children and assert that the component adds no second toast of its own.
const h = await vi.hoisted(async () => {
  const toast = vi.fn();
  const saved = {
    savedInventories: [],
    isLoadingInventories: false,
    isSavingInventory: false,
    loadSavedInventories: vi.fn(),
    saveInventory: vi.fn(),
    saveDeviceList: vi.fn(),
    loadInventory: vi.fn(),
    updateInventoryDetails: vi.fn(),
    deleteInventory: vi.fn(),
    exportInventory: vi.fn(),
    importInventory: vi.fn(),
  };
  const selection = {
    selectedDevices: [{ id: "d1" }, { id: "d2" }],
    selectedCount: 2,
    removalSelectedIds: new Set<string>(),
    replaceAll: vi.fn(),
    addDevices: vi.fn(),
    removeDevice: vi.fn(),
    removeSelectedDevices: vi.fn(),
    selectAllForRemoval: vi.fn(),
    toggleRemovalSelect: vi.fn(),
  };
  const captured: {
    modals?: Record<string, (...args: never[]) => unknown>;
    builder?: Record<string, (...args: never[]) => unknown> & { loadedInventoryName?: string };
  } = {};
  return { toast, saved, selection, captured };
});

vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: vi.fn() }) }));
vi.mock("../hooks/use-saved-inventories", () => ({ useSavedInventories: () => h.saved }));
vi.mock("../hooks/use-selected-inventory", () => ({ useSelectedInventory: () => h.selection }));
vi.mock("../hooks/use-device-filter", () => ({ useDeviceFilter: () => ({}) }));
vi.mock("../hooks/use-device-selector-modals", () => ({
  useDeviceSelectorModals: () => ({ selectionMode: false, closeLoadModal: vi.fn(), setSelectionMode: vi.fn() }),
}));
vi.mock("../hooks/use-device-preview", () => ({
  mapPreviewDevices: vi.fn(),
  useDevicePreview: () => ({
    previewDevices: [],
    selectedIds: new Set<string>(),
    currentPageDevices: [],
    setShowPreviewResults: vi.fn(),
  }),
}));
vi.mock("./condition-tree-builder", () => ({
  ConditionTreeBuilder: (props: NonNullable<typeof h.captured.builder>) => {
    h.captured.builder = props;
    return null;
  },
}));
vi.mock("./device-selector-modals", () => ({
  DeviceSelectorModals: (props: NonNullable<typeof h.captured.modals>) => {
    h.captured.modals = props;
    return null;
  },
}));
vi.mock("./device-table", () => ({ DeviceTable: () => null }));
vi.mock("./selected-inventory-list", () => ({ SelectedInventoryList: () => null }));

type SaveHandler = (
  name: string,
  description: string,
  scope: string,
  isUpdate: boolean,
  existingId?: number,
  groupPath?: string | null,
) => Promise<boolean>;

const modalHandler = <T,>(name: string) => h.captured.modals![name] as unknown as T;

beforeEach(() => {
  h.toast.mockReset();
  h.saved.saveInventory.mockReset();
  h.saved.saveDeviceList.mockReset();
  h.saved.exportInventory.mockReset();
  h.saved.importInventory.mockReset();
  h.captured.modals = undefined;
  h.captured.builder = undefined;
  render(<DeviceSelector sourceId="nb-1" sourceReady />);
});

describe("DeviceSelector save and transfer handlers", () => {
  it("saves a filter inventory and reports success to the dialog", async () => {
    h.saved.saveInventory.mockResolvedValue(true);
    const save = modalHandler<SaveHandler>("onSaveInventory");
    let ok: boolean | undefined;
    await act(async () => {
      ok = await save("core", "d", "global", false, undefined, "/lab");
    });
    expect(ok).toBe(true);
    expect(h.saved.saveInventory).toHaveBeenCalledWith(
      "core", "d", "global", expect.objectContaining({ type: "root" }), false, undefined, "/lab",
    );
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("keeps the save dialog open on a failed save and adds no toast of its own", async () => {
    h.saved.saveInventory.mockRejectedValue(new Error("name taken"));
    const save = modalHandler<SaveHandler>("onSaveInventory");
    let ok: boolean | undefined;
    await act(async () => {
      ok = await save("core", "", "global", false);
    });
    expect(ok).toBe(false);
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("saves a device list from the selection and adds no toast when that fails", async () => {
    h.saved.saveDeviceList.mockRejectedValue(new Error("boom"));
    const save = modalHandler<SaveHandler>("onSaveDeviceList");
    let ok: boolean | undefined;
    await act(async () => {
      ok = await save("list", "", "global", true, 7, null);
    });
    expect(h.saved.saveDeviceList).toHaveBeenCalledWith(
      "list", "", "global", ["d1", "d2"], true, 7, null,
    );
    expect(ok).toBe(false);
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("does not save the loaded inventory directly when none is loaded", async () => {
    const saveCurrent = h.captured.builder!.onSaveCurrent as unknown as () => Promise<void>;
    await act(async () => {
      await saveCurrent();
    });
    expect(h.saved.saveInventory).not.toHaveBeenCalled();
  });

  it("adds no toast when the direct save of a loaded inventory fails", async () => {
    const tree = { type: "root", internalLogic: "AND", items: [] };
    h.saved.loadInventory.mockResolvedValue({
      id: 5, name: "core", description: "d", scope: "global", group_path: "/lab",
      inventory_type: "filter", tree,
    });
    await act(async () => {
      await (h.captured.modals!.onLoadInventory as unknown as (id: number) => Promise<void>)(5);
    });
    expect(h.captured.builder!.loadedInventoryName).toBe("core");
    h.saved.saveInventory.mockRejectedValue(new Error("boom"));
    await act(async () => {
      await (h.captured.builder!.onSaveCurrent as unknown as () => Promise<void>)();
    });
    expect(h.saved.saveInventory).toHaveBeenCalledWith(
      "core", "d", "global", expect.anything(), true, 5, "/lab",
    );
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("swallows a failed export and import without a second toast", async () => {
    h.saved.exportInventory.mockRejectedValue(new Error("no"));
    h.saved.importInventory.mockRejectedValue(new Error("bad file"));
    const exportInventory = modalHandler<(id: number) => Promise<void>>("onExportInventory");
    const importInventory = modalHandler<(file: File) => Promise<void>>("onImportInventory");
    await act(async () => {
      await expect(exportInventory(3)).resolves.toBeUndefined();
      await expect(importInventory(new File(["{}"], "i.json"))).resolves.toBeUndefined();
    });
    expect(h.saved.exportInventory).toHaveBeenCalledWith(3);
    expect(h.saved.importInventory).toHaveBeenCalledTimes(1);
    expect(h.toast).not.toHaveBeenCalled();
  });
});
