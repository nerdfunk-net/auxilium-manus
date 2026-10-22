import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import type { ConditionTree } from "../types/device-selector";
import { useSavedInventories } from "./use-saved-inventories";

const h = vi.hoisted(() => {
  const exportMutateAsync = vi.fn();
  const importMutateAsync = vi.fn();
  return {
    apiCall: vi.fn(),
    toast: vi.fn(),
    exportMutateAsync,
    importMutateAsync,
    // One stable object each, as useMutation's mutateAsync is stable in production.
    exportMutation: { mutateAsync: exportMutateAsync },
    importMutation: { mutateAsync: importMutateAsync },
  };
});
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));
vi.mock("@/hooks/queries/use-inventory-export-mutation", () => ({
  useInventoryExportMutation: () => h.exportMutation,
}));
vi.mock("@/hooks/queries/use-inventory-import-mutation", () => ({
  useInventoryImportMutation: () => h.importMutation,
}));

const TREE: ConditionTree = {
  type: "root",
  internalLogic: "AND",
  items: [{ id: "c1", field: "location", operator: "equals", value: "berlin" }],
};

const LIST = {
  inventories: [{ id: 1, name: "core", scope: "global" }],
  total: 1,
};

function setup() {
  const { wrapper, client } = createQueryWrapper();
  const view = renderHook(() => useSavedInventories(), { wrapper });
  return { ...view, client };
}

const callsTo = (method: string) =>
  h.apiCall.mock.calls.filter(([, init]) => (init as { method?: string } | undefined)?.method === method);
const bodyOf = (call: unknown[]) => JSON.parse((call[1] as { body: string }).body);

beforeEach(() => {
  h.apiCall.mockReset();
  h.toast.mockReset();
  h.exportMutateAsync.mockReset().mockResolvedValue(undefined);
  h.importMutateAsync.mockReset().mockResolvedValue(undefined);
  h.apiCall.mockImplementation((url: string, init?: { method?: string }) => {
    if (url === "sources/nautobot" && (!init || init.method === "GET")) {
      return Promise.resolve(LIST);
    }
    return Promise.resolve({ id: 7, name: "saved" });
  });
});

describe("useSavedInventories", () => {
  it("lists the saved inventories", async () => {
    const { result } = setup();
    expect(result.current.isLoadingInventories).toBe(true);
    await waitFor(() => expect(result.current.savedInventories).toHaveLength(1));
    expect(result.current.isLoadingInventories).toBe(false);
  });

  it("returns the same object when nothing changed", async () => {
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.savedInventories).toHaveLength(1));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("reloads the list on request", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.savedInventories).toHaveLength(1));
    const before = h.apiCall.mock.calls.length;
    await act(() => result.current.loadSavedInventories());
    expect(h.apiCall.mock.calls.length).toBe(before + 1);
  });

  describe("saveInventory", () => {
    it("creates a filter inventory with the tree in the v2 envelope", async () => {
      const { result } = setup();
      let ok: boolean | undefined;
      await act(async () => {
        ok = await result.current.saveInventory("core", "", "global", TREE);
      });
      expect(ok).toBe(true);
      const [post] = callsTo("POST");
      expect(post![0]).toBe("sources/nautobot");
      expect(bodyOf(post!)).toEqual({
        name: "core",
        description: null,
        conditions: [{ version: 2, tree: TREE }],
        inventory_type: "filter",
        scope: "global",
        group_path: null,
      });
    });

    it("updates by id without sending name or scope", async () => {
      const { result } = setup();
      await act(async () => {
        await result.current.saveInventory("core", "text", "global", TREE, true, 5, "a/b");
      });
      const [put] = callsTo("PUT");
      expect(put![0]).toBe("sources/nautobot/5");
      expect(bodyOf(put!)).toEqual({
        description: "text",
        conditions: [{ version: 2, tree: TREE }],
        inventory_type: "filter",
        group_path: "a/b",
      });
      expect(callsTo("POST")).toHaveLength(0);
    });

    it("refuses an update without an id instead of creating a duplicate", async () => {
      const { result } = setup();
      await act(async () => {
        await expect(
          result.current.saveInventory("core", "", "global", TREE, true, undefined),
        ).rejects.toThrow(/id/i);
      });
      expect(callsTo("POST")).toHaveLength(0);
      expect(callsTo("PUT")).toHaveLength(0);
      expect(result.current.isSavingInventory).toBe(false);
      // No mutation ran, so no mutation toasted: the guard has to say it itself.
      expect(h.toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Save failed", variant: "destructive" }),
      );
    });

    it.each([0, null])("refuses an update with the falsy id %s", async (id) => {
      const { result } = setup();
      await act(async () => {
        await expect(
          result.current.saveInventory("core", "", "global", TREE, true, id as unknown as number),
        ).rejects.toThrow(/id/i);
      });
      expect(callsTo("POST")).toHaveLength(0);
    });

    it("clears the saving flag when the save fails and rethrows", async () => {
      h.apiCall.mockImplementation((url: string, init?: { method?: string }) =>
        init?.method === "POST" ? Promise.reject(new Error("boom")) : Promise.resolve(LIST),
      );
      const { result } = setup();
      await act(async () => {
        await expect(result.current.saveInventory("core", "", "global", TREE)).rejects.toThrow("boom");
      });
      expect(result.current.isSavingInventory).toBe(false);
      expect(h.toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Save failed", description: "boom" }),
      );
    });

    it("refreshes the list after a save", async () => {
      const { result, client } = setup();
      const spy = vi.spyOn(client, "invalidateQueries");
      await act(async () => {
        await result.current.saveInventory("core", "", "global", TREE);
      });
      expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.sourcesNautobot.inventories() });
    });
  });

  describe("saveDeviceList", () => {
    it("creates a static inventory with no conditions", async () => {
      const { result } = setup();
      await act(async () => {
        await result.current.saveDeviceList("list", "d", "global", ["a", "b"]);
      });
      const [post] = callsTo("POST");
      expect(bodyOf(post!)).toEqual({
        name: "list",
        description: "d",
        inventory_type: "static",
        device_ids: ["a", "b"],
        conditions: [],
        scope: "global",
        group_path: null,
      });
    });

    it("updates the device ids of an existing static inventory", async () => {
      const { result } = setup();
      await act(async () => {
        await result.current.saveDeviceList("list", "", "global", ["x"], true, 9);
      });
      const [put] = callsTo("PUT");
      expect(put![0]).toBe("sources/nautobot/9");
      expect(bodyOf(put!)).toEqual({
        description: null,
        inventory_type: "static",
        device_ids: ["x"],
        group_path: null,
      });
    });

    it.each([undefined, 0, null])("refuses an update with the id %s", async (id) => {
      const { result } = setup();
      await act(async () => {
        await expect(
          result.current.saveDeviceList(
            "list",
            "",
            "global",
            ["x"],
            true,
            id as unknown as number | undefined,
          ),
        ).rejects.toThrow(/id/i);
      });
      expect(callsTo("POST")).toHaveLength(0);
    });
  });

  describe("loadInventory", () => {
    const stored = (over: Record<string, unknown>) => {
      h.apiCall.mockImplementation((url: string) =>
        url === "sources/nautobot"
          ? Promise.resolve(LIST)
          : Promise.resolve({ id: 3, name: "inv", scope: "global", description: "d", ...over }),
      );
    };

    it("returns a static inventory with its device ids", async () => {
      stored({ inventory_type: "static", device_ids: ["a"], group_path: "g" });
      const { result } = setup();
      await expect(result.current.loadInventory(3)).resolves.toEqual({
        inventory_type: "static",
        device_ids: ["a"],
        id: 3,
        name: "inv",
        description: "d",
        scope: "global",
        group_path: "g",
      });
    });

    it("treats a static inventory without device ids as empty", async () => {
      stored({ inventory_type: "static" });
      const { result } = setup();
      const loaded = await result.current.loadInventory(3);
      expect(loaded?.device_ids).toEqual([]);
      expect(loaded?.group_path).toBeNull();
    });

    it("reads a version 2 tree", async () => {
      stored({ inventory_type: "filter", conditions: [{ version: 2, tree: TREE }] });
      const { result } = setup();
      const loaded = await result.current.loadInventory(3);
      expect(loaded?.inventory_type).toBe("filter");
      expect(loaded?.tree).toEqual(TREE);
    });

    it("converts the old flat condition list into an AND tree", async () => {
      stored({
        conditions: [
          { field: "location", operator: "equals", value: "berlin" },
          { field: "role", operator: "equals", value: "edge" },
        ],
      });
      const { result } = setup();
      const loaded = await result.current.loadInventory(3);
      expect(loaded?.inventory_type).toBe("filter");
      expect(loaded?.tree?.internalLogic).toBe("AND");
      expect(loaded?.tree?.items.map((i) => ("field" in i ? i.field : null))).toEqual([
        "location",
        "role",
      ]);
    });

    it("returns null when the server sends nothing", async () => {
      h.apiCall.mockImplementation((url: string) =>
        url === "sources/nautobot" ? Promise.resolve(LIST) : Promise.resolve(null),
      );
      const { result } = setup();
      await expect(result.current.loadInventory(3)).resolves.toBeNull();
    });

    it("loads a filter inventory without conditions as an empty tree", async () => {
      stored({ inventory_type: "filter", conditions: [] });
      const { result } = setup();
      const loaded = await result.current.loadInventory(3);
      expect(loaded?.inventory_type).toBe("filter");
      expect(loaded?.tree).toEqual({ type: "root", internalLogic: "AND", items: [] });
    });

    it("returns null for a version 2 envelope whose tree cannot be read", async () => {
      stored({ conditions: [{ version: 2, tree: "garbage" }] });
      const { result } = setup();
      await expect(result.current.loadInventory(3)).resolves.toBeNull();
    });
  });

  it("updates only the details of an inventory", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.updateInventoryDetails(4, "new", "", "private", "x");
    });
    const [put] = callsTo("PUT");
    expect(put![0]).toBe("sources/nautobot/4");
    expect(bodyOf(put!)).toEqual({ name: "new", description: null, scope: "private", group_path: "x" });
  });

  it("deletes an inventory", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.deleteInventory(4);
    });
    const [del] = callsTo("DELETE");
    expect(del![0]).toBe("sources/nautobot/4");
  });

  it("exports through the export mutation", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.exportInventory(4);
    });
    expect(h.exportMutateAsync).toHaveBeenCalledWith(4);
  });

  it("imports a file, then reloads the list", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.savedInventories).toHaveLength(1));
    const before = h.apiCall.mock.calls.length;
    const file = new File(["{}"], "inv.json");
    await act(async () => {
      await result.current.importInventory(file);
    });
    expect(h.importMutateAsync).toHaveBeenCalledWith(file);
    expect(h.apiCall.mock.calls.length).toBe(before + 1);
  });

  it("does not reload after a failed import", async () => {
    h.importMutateAsync.mockRejectedValue(new Error("bad file"));
    const { result } = setup();
    await waitFor(() => expect(result.current.savedInventories).toHaveLength(1));
    const before = h.apiCall.mock.calls.length;
    await act(async () => {
      await expect(result.current.importInventory(new File(["x"], "x.json"))).rejects.toThrow(
        "bad file",
      );
    });
    expect(h.apiCall.mock.calls.length).toBe(before);
  });
});
