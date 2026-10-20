import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDeviceSelectorModals } from "./use-device-selector-modals";
import type { useSavedInventories } from "./use-saved-inventories";

const h = vi.hoisted(() => ({
  toast: vi.fn(),
  loadSavedInventories: vi.fn(),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));

const saved = { loadSavedInventories: h.loadSavedInventories } as unknown as ReturnType<
  typeof useSavedInventories
>;

function setup(conditionTreeItemCount = 1, selectedDeviceCount = 1) {
  return renderHook(() =>
    useDeviceSelectorModals({ saved, conditionTreeItemCount, selectedDeviceCount }),
  );
}

beforeEach(() => {
  h.toast.mockReset();
  h.loadSavedInventories.mockReset();
  h.loadSavedInventories.mockResolvedValue(undefined);
});

describe("useDeviceSelectorModals", () => {
  it("starts with everything closed", () => {
    const { result } = setup();
    expect(result.current.showSaveModal).toBe(false);
    expect(result.current.showSaveDeviceListModal).toBe(false);
    expect(result.current.showLoadModal).toBe(false);
    expect(result.current.showManageModal).toBe(false);
    expect(result.current.showLogicalTreeModal).toBe(false);
    expect(result.current.showHelpModal).toBe(false);
    expect(result.current.selectionMode).toBe(false);
  });

  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("refuses to open the save dialog without conditions", async () => {
    const { result } = setup(0, 5);
    await act(() => result.current.handleOpenSaveModal());
    expect(result.current.showSaveModal).toBe(false);
    expect(h.loadSavedInventories).not.toHaveBeenCalled();
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Nothing to save", variant: "destructive" }),
    );
  });

  it("refreshes the saved inventories, then opens the save dialog", async () => {
    const { result } = setup(2, 0);
    await act(() => result.current.handleOpenSaveModal());
    expect(h.loadSavedInventories).toHaveBeenCalledTimes(1);
    expect(result.current.showSaveModal).toBe(true);
    act(() => result.current.closeSaveModal());
    expect(result.current.showSaveModal).toBe(false);
  });

  it("refuses to open the device-list dialog without a selection", async () => {
    const { result } = setup(3, 0);
    await act(() => result.current.handleOpenSaveDeviceListModal());
    expect(result.current.showSaveDeviceListModal).toBe(false);
    expect(h.loadSavedInventories).not.toHaveBeenCalled();
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Nothing to save" }));
  });

  it("opens and closes the device-list dialog", async () => {
    const { result } = setup(0, 2);
    await act(() => result.current.handleOpenSaveDeviceListModal());
    expect(result.current.showSaveDeviceListModal).toBe(true);
    act(() => result.current.closeSaveDeviceListModal());
    expect(result.current.showSaveDeviceListModal).toBe(false);
  });

  it("opens the load and manage dialogs after a refresh, with no precondition", async () => {
    const { result } = setup(0, 0);
    await act(() => result.current.handleOpenLoadModal());
    await act(() => result.current.handleOpenManageModal());
    expect(h.loadSavedInventories).toHaveBeenCalledTimes(2);
    expect(result.current.showLoadModal).toBe(true);
    expect(result.current.showManageModal).toBe(true);
    act(() => result.current.closeLoadModal());
    act(() => result.current.closeManageModal());
    expect(result.current.showLoadModal).toBe(false);
    expect(result.current.showManageModal).toBe(false);
  });

  it("does not open a dialog before the refresh has finished", async () => {
    let finish: () => void = () => {};
    h.loadSavedInventories.mockReturnValue(new Promise<void>((r) => (finish = r)));
    const { result } = setup();
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.handleOpenLoadModal();
    });
    expect(result.current.showLoadModal).toBe(false);
    await act(async () => {
      finish();
      await pending;
    });
    expect(result.current.showLoadModal).toBe(true);
  });

  it("toggles the help, logical-tree dialogs and selection mode", () => {
    const { result } = setup();
    act(() => result.current.openHelpModal());
    act(() => result.current.openLogicalTreeModal());
    act(() => result.current.toggleSelectionMode());
    expect(result.current.showHelpModal).toBe(true);
    expect(result.current.showLogicalTreeModal).toBe(true);
    expect(result.current.selectionMode).toBe(true);
    act(() => result.current.closeHelpModal());
    act(() => result.current.closeLogicalTreeModal());
    act(() => result.current.toggleSelectionMode());
    expect(result.current.showHelpModal).toBe(false);
    expect(result.current.showLogicalTreeModal).toBe(false);
    expect(result.current.selectionMode).toBe(false);
    act(() => result.current.setSelectionMode(true));
    expect(result.current.selectionMode).toBe(true);
  });
});
