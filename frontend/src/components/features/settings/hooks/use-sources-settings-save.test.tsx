import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSourcesSettingsSave } from "./use-sources-settings-save";
import type { SourcesDialogState } from "./use-sources-settings-save";

const fn = () => vi.fn().mockResolvedValue(undefined);

const m = vi.hoisted(() => {
  const make = () => ({ mutateAsync: vi.fn(), isPending: false });
  const source = () => ({ createSource: make(), updateSource: make(), deleteSource: make() });
  return {
    settings: { upsertSetting: make(), deleteSetting: make() },
    ise: source(),
    catalyst: source(),
    pyats: source(),
    mattermost: source(),
    batfish: source(),
  };
});

// Like useMutation: a new result object on every render, a stable mutateAsync.
const fresh = <T extends Record<string, { mutateAsync: unknown; isPending: boolean }>>(group: T) =>
  Object.fromEntries(Object.entries(group).map(([k, v]) => [k, { ...v }])) as T;

vi.mock("@/hooks/queries/use-settings-mutations", () => ({
  useSettingsMutations: () => fresh(m.settings),
}));
vi.mock("@/hooks/queries/use-ise-sources-mutations", () => ({
  useISESourcesMutations: () => fresh(m.ise),
}));
vi.mock("@/hooks/queries/use-catalyst-center-sources-mutations", () => ({
  useCatalystCenterSourcesMutations: () => fresh(m.catalyst),
}));
vi.mock("@/hooks/queries/use-pyats-sources-mutations", () => ({
  usePyATSSourcesMutations: () => fresh(m.pyats),
}));
vi.mock("@/hooks/queries/use-mattermost-sources-mutations", () => ({
  useMattermostSourcesMutations: () => fresh(m.mattermost),
}));
vi.mock("@/hooks/queries/use-batfish-sources-mutations", () => ({
  useBatfishSourcesMutations: () => fresh(m.batfish),
}));

const CLOSED: SourcesDialogState = { type: "closed" };
const NAUTOBOT_BY_ID = new Map<string, unknown>();
const setDialog = vi.fn();

function setup(dialog: SourcesDialogState = CLOSED, nautobotById = NAUTOBOT_BY_ID) {
  return renderHook(() => useSourcesSettingsSave({ dialog, setDialog, nautobotById }));
}

beforeEach(() => {
  setDialog.mockReset();
  const groups = [m.settings, m.ise, m.catalyst, m.pyats, m.mattermost, m.batfish];
  for (const group of groups) {
    for (const mutation of Object.values(group)) {
      mutation.mutateAsync = fn();
      mutation.isPending = false;
    }
  }
});

describe("saveNautobot", () => {
  it("creates the setting with url, verify_ssl and credential, then closes the dialog", async () => {
    const { result } = setup();
    await act(() =>
      result.current.saveNautobot(
        { sourceId: "nb", url: "https://nb", verifySsl: true, credentialId: 3 } as never,
        "sources.nautobot.nb",
      ),
    );
    expect(m.settings.upsertSetting.mutateAsync).toHaveBeenCalledWith({
      key: "sources.nautobot.nb",
      value: { url: "https://nb", verify_ssl: true, credential_id: 3 },
      description: "Nautobot source nb",
      exists: false,
    });
    expect(setDialog).toHaveBeenCalledWith({ type: "closed" });
  });

  it("marks an already known source as existing and leaves out a missing credential", async () => {
    const { result } = setup(CLOSED, new Map([["nb", {}]]));
    await act(() =>
      result.current.saveNautobot(
        { sourceId: "nb", url: "https://nb", verifySsl: false, credentialId: null } as never,
        "sources.nautobot.nb",
      ),
    );
    expect(m.settings.upsertSetting.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ exists: true, value: { url: "https://nb", verify_ssl: false } }),
    );
  });

  it("keeps the dialog open when the save fails", async () => {
    m.settings.upsertSetting.mutateAsync.mockRejectedValue(new Error("nope"));
    const { result } = setup();
    await act(async () => {
      await expect(
        result.current.saveNautobot({ sourceId: "nb", url: "u", verifySsl: true } as never, "k"),
      ).rejects.toThrow("nope");
    });
    expect(setDialog).not.toHaveBeenCalled();
  });
});

describe.each([
  ["Ise", "ise", "saveIse", "updateIse"],
  ["CatalystCenter", "catalyst", "saveCatalystCenter", "updateCatalystCenter"],
  ["Pyats", "pyats", "savePyats", "updatePyats"],
  ["Mattermost", "mattermost", "saveMattermost", "updateMattermost"],
  ["Batfish", "batfish", "saveBatfish", "updateBatfish"],
] as const)("%s source", (_label, group, saveName, updateName) => {
  it("creates the source, then closes the dialog", async () => {
    const { result } = setup();
    await act(() => (result.current[saveName] as (v: unknown) => Promise<void>)({ source_id: "a" }));
    expect(m[group].createSource.mutateAsync).toHaveBeenCalledWith({ source_id: "a" });
    expect(setDialog).toHaveBeenCalledWith({ type: "closed" });
  });

  it("updates the source by id, then closes the dialog", async () => {
    const { result } = setup();
    await act(() =>
      (result.current[updateName] as (id: string, v: unknown) => Promise<void>)("a", { url: "u" }),
    );
    expect(m[group].updateSource.mutateAsync).toHaveBeenCalledWith({
      sourceId: "a",
      data: { url: "u" },
    });
    expect(setDialog).toHaveBeenCalledWith({ type: "closed" });
  });
});

describe("confirmDelete", () => {
  it("does nothing unless the delete dialog is open", async () => {
    const { result } = setup();
    await act(() => result.current.confirmDelete());
    expect(setDialog).not.toHaveBeenCalled();
    expect(m.settings.deleteSetting.mutateAsync).not.toHaveBeenCalled();
  });

  it.each([
    ["ise", "ise"],
    ["catalyst_center", "catalyst"],
    ["pyats", "pyats"],
    ["mattermost", "mattermost"],
    ["batfish", "batfish"],
  ] as const)("deletes a %s source by id and closes", async (sourceType, group) => {
    const { result } = setup({ type: "delete", sourceType, sourceId: "a", key: "k" });
    await act(() => result.current.confirmDelete());
    expect(m[group].deleteSource.mutateAsync).toHaveBeenCalledWith("a");
    expect(m.settings.deleteSetting.mutateAsync).not.toHaveBeenCalled();
    expect(setDialog).toHaveBeenCalledWith({ type: "closed" });
  });

  it("deletes a Nautobot source through its setting key", async () => {
    const { result } = setup({ type: "delete", sourceType: "nautobot", sourceId: "nb", key: "sources.nautobot.nb" });
    await act(() => result.current.confirmDelete());
    expect(m.settings.deleteSetting.mutateAsync).toHaveBeenCalledWith("sources.nautobot.nb");
    expect(setDialog).toHaveBeenCalledWith({ type: "closed" });
  });
});

describe("pending flags", () => {
  it("reflect each mutation", () => {
    m.ise.deleteSource.isPending = true;
    m.settings.upsertSetting.isPending = true;
    const { result } = setup();
    expect(result.current.deleteIseSourceIsPending).toBe(true);
    expect(result.current.upsertSettingIsPending).toBe(true);
    expect(result.current.deletePyatsSourceIsPending).toBe(false);
  });
});

describe("useSourcesSettingsSave stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  const FLAGS = [
    ["settings", "upsertSetting", "upsertSettingIsPending"],
    ["settings", "deleteSetting", "deleteSettingIsPending"],
    ...(["ise", "catalyst", "pyats", "mattermost", "batfish"] as const).flatMap((group) => {
      const type = { ise: "Ise", catalyst: "CatalystCenter", pyats: "Pyats", mattermost: "Mattermost", batfish: "Batfish" }[group];
      return (["create", "update", "delete"] as const).map(
        (verb) => [group, `${verb}Source`, `${verb}${type}SourceIsPending`] as const,
      );
    }),
  ] as const;

  it.each(FLAGS)("returns a new object when %s %s pending changes", (group, mutation, flag) => {
    const { result, rerender } = setup();
    const first = result.current;
    (m[group] as Record<string, { isPending: boolean }>)[mutation].isPending = true;
    rerender();
    expect(result.current).not.toBe(first);
    expect((result.current as Record<string, unknown>)[flag]).toBe(true);
  });
});
