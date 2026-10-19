import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSourcesSettings } from "./use-sources-settings";

type Loadable = { data: unknown; isLoading: boolean };

const queries = vi.hoisted(() => ({
  settings: { data: undefined, isLoading: false } as Loadable,
  ise: { data: undefined, isLoading: false } as Loadable,
  catalyst: { data: undefined, isLoading: false } as Loadable,
  pyats: { data: undefined, isLoading: false } as Loadable,
  mattermost: { data: undefined, isLoading: false } as Loadable,
  batfish: { data: undefined, isLoading: false } as Loadable,
  settingsArgs: vi.fn(),
}));

const saveHandlers = vi.hoisted(() => ({
  value: {
    saveNautobot: vi.fn(),
    saveIse: vi.fn(),
    updateIse: vi.fn(),
    saveCatalystCenter: vi.fn(),
    updateCatalystCenter: vi.fn(),
    savePyats: vi.fn(),
    updatePyats: vi.fn(),
    saveMattermost: vi.fn(),
    updateMattermost: vi.fn(),
    saveBatfish: vi.fn(),
    updateBatfish: vi.fn(),
    confirmDelete: vi.fn(),
    upsertSettingIsPending: false,
    createIseSourceIsPending: false,
    updateIseSourceIsPending: false,
    createCatalystCenterSourceIsPending: false,
    updateCatalystCenterSourceIsPending: false,
    createPyatsSourceIsPending: false,
    updatePyatsSourceIsPending: false,
    createMattermostSourceIsPending: false,
    updateMattermostSourceIsPending: false,
    createBatfishSourceIsPending: false,
    updateBatfishSourceIsPending: false,
    deleteIseSourceIsPending: false,
    deleteCatalystCenterSourceIsPending: false,
    deletePyatsSourceIsPending: false,
    deleteMattermostSourceIsPending: false,
    deleteBatfishSourceIsPending: false,
    deleteSettingIsPending: false,
  },
  args: vi.fn(),
}));

vi.mock("@/hooks/queries/use-settings-query", () => ({
  useSettingsListQuery: (args: unknown) => (queries.settingsArgs(args), queries.settings),
}));
vi.mock("@/hooks/queries/use-ise-sources-query", () => ({ useISESourcesQuery: () => queries.ise }));
vi.mock("@/hooks/queries/use-catalyst-center-sources-query", () => ({
  useCatalystCenterSourcesQuery: () => queries.catalyst,
}));
vi.mock("@/hooks/queries/use-pyats-sources-query", () => ({ usePyATSSourcesQuery: () => queries.pyats }));
vi.mock("@/hooks/queries/use-mattermost-sources-query", () => ({
  useMattermostSourcesQuery: () => queries.mattermost,
}));
vi.mock("@/hooks/queries/use-batfish-sources-query", () => ({
  useBatfishSourcesQuery: () => queries.batfish,
}));
vi.mock("./use-sources-settings-save", () => ({
  useSourcesSettingsSave: (args: unknown) => (saveHandlers.args(args), saveHandlers.value),
}));

const idle = { data: undefined, isLoading: false };

beforeEach(() => {
  queries.settings = { ...idle };
  queries.ise = { ...idle };
  queries.catalyst = { ...idle };
  queries.pyats = { ...idle };
  queries.mattermost = { ...idle };
  queries.batfish = { ...idle };
  queries.settingsArgs.mockClear();
  saveHandlers.args.mockClear();
  for (const key of Object.keys(saveHandlers.value) as (keyof typeof saveHandlers.value)[]) {
    if (key.endsWith("IsPending")) (saveHandlers.value[key] as boolean) = false;
  }
});

const nautobotSetting = (id: string, value: Record<string, unknown> = { url: `https://${id}.example.com` }) => ({
  key: `sources.nautobot.${id}`,
  value,
  description: null,
  updated_at: "2026-01-01",
});

const httpSource = (id: string) => ({
  source_id: id,
  url: `https://${id}.example.com`,
  verify_ssl: false,
  timeout: 30,
  credential_id: 4,
});

describe("source lists", () => {
  it("are empty while nothing has loaded", () => {
    const { result } = renderHook(() => useSourcesSettings());
    expect(result.current).toMatchObject({
      nautobot: [],
      ise: [],
      catalystCenter: [],
      pyats: [],
      mattermost: [],
      batfish: [],
      existingNautobotIds: [],
      existingIseIds: [],
      existingCatalystCenterIds: [],
      existingPyatsIds: [],
      existingMattermostIds: [],
      existingBatfishIds: [],
    });
  });

  it("queries all settings under the sources prefix", () => {
    renderHook(() => useSourcesSettings());
    expect(queries.settingsArgs).toHaveBeenCalledWith({ keyPrefix: "sources." });
  });

  it("exposes each loaded type with its ids", () => {
    queries.ise = { data: { sources: [httpSource("ise-a")] }, isLoading: false };
    queries.catalyst = { data: { sources: [httpSource("cc-a"), httpSource("cc-b")] }, isLoading: false };
    queries.pyats = { data: { sources: [httpSource("py-a")] }, isLoading: false };
    queries.mattermost = { data: { sources: [httpSource("mm-a")] }, isLoading: false };
    queries.batfish = { data: { sources: [{ source_id: "bf-a", host: "h", port: 9996 }] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());

    expect(result.current.existingIseIds).toEqual(["ise-a"]);
    expect(result.current.existingCatalystCenterIds).toEqual(["cc-a", "cc-b"]);
    expect(result.current.existingPyatsIds).toEqual(["py-a"]);
    expect(result.current.existingMattermostIds).toEqual(["mm-a"]);
    expect(result.current.existingBatfishIds).toEqual(["bf-a"]);
  });

  it("parses Nautobot sources from the settings, sorted by id, and ignores other settings", () => {
    queries.settings = {
      data: {
        settings: [
          nautobotSetting("zeta"),
          nautobotSetting("alpha", { url: "https://a", verify_ssl: false, credential_id: 2 }),
          { ...nautobotSetting("broken"), value: {} },
          { key: "sources.other.x", value: { url: "u" }, description: null, updated_at: "" },
        ],
      },
      isLoading: false,
    };
    const { result } = renderHook(() => useSourcesSettings());

    expect(result.current.nautobot.map((n) => n.sourceId)).toEqual(["alpha", "zeta"]);
    expect(result.current.nautobot[0]).toMatchObject({ url: "https://a", verifySsl: false, credentialId: 2 });
    // The id list comes from the keys, so it also lists the entry whose value could not be parsed.
    expect(result.current.existingNautobotIds).toContain("broken");
  });

  it("passes the loading flags through", () => {
    queries.settings = { data: undefined, isLoading: true };
    queries.ise = { data: undefined, isLoading: true };
    queries.batfish = { data: undefined, isLoading: true };
    const { result } = renderHook(() => useSourcesSettings());
    expect(result.current).toMatchObject({
      isLoading: true,
      isIseLoading: true,
      isBatfishLoading: true,
      isCatalystCenterLoading: false,
      isPyatsLoading: false,
      isMattermostLoading: false,
    });
  });
});

describe("dialog state", () => {
  it("starts closed with no dialog selected", () => {
    const { result } = renderHook(() => useSourcesSettings());
    expect(result.current.dialog).toEqual({ type: "closed" });
    expect(result.current.nautobotDialogOpen).toBeNull();
    expect(result.current.deleteDialogOpen).toBeNull();
  });

  it.each([
    ["nautobot", "nautobotDialogOpen"],
    ["ise", "iseDialogOpen"],
    ["catalyst_center", "catalystCenterDialogOpen"],
    ["pyats", "pyatsDialogOpen"],
    ["mattermost", "mattermostDialogOpen"],
    ["batfish", "batfishDialogOpen"],
  ] as const)("opening the %s dialog exposes only %s", (type, field) => {
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog({ type, mode: "create" }));

    expect(result.current[field]).toEqual({ type, mode: "create" });
    const open = [
      "nautobotDialogOpen",
      "iseDialogOpen",
      "catalystCenterDialogOpen",
      "pyatsDialogOpen",
      "mattermostDialogOpen",
      "batfishDialogOpen",
      "deleteDialogOpen",
    ] as const;
    for (const other of open.filter((name) => name !== field)) {
      expect(result.current[other]).toBeNull();
    }
  });

  it("hands the dialog and the Nautobot index to the save hook", () => {
    queries.settings = { data: { settings: [nautobotSetting("alpha")] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog({ type: "ise", mode: "create" }));
    const args = saveHandlers.args.mock.lastCall![0];
    expect(args.dialog).toEqual({ type: "ise", mode: "create" });
    expect(args.nautobotById.has("alpha")).toBe(true);
  });

  it("re-exposes the save handlers", () => {
    const { result } = renderHook(() => useSourcesSettings());
    expect(result.current.saveIse).toBe(saveHandlers.value.saveIse);
    expect(result.current.updateBatfish).toBe(saveHandlers.value.updateBatfish);
    expect(result.current.confirmDelete).toBe(saveHandlers.value.confirmDelete);
  });
});

describe("the source being edited", () => {
  const httpExpected = (id: string) => ({
    sourceId: id,
    url: `https://${id}.example.com`,
    verifySsl: false,
    timeout: 30,
    credentialId: 4,
  });

  it("is a Nautobot source in edit mode", () => {
    queries.settings = { data: { settings: [nautobotSetting("alpha")] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog({ type: "nautobot", mode: "edit", sourceId: "alpha" }));
    expect(result.current.editingNautobot?.sourceId).toBe("alpha");
  });

  it.each([
    ["ise", "ise", "editingIseValue"],
    ["catalyst_center", "catalyst", "editingCatalystCenterValue"],
    ["pyats", "pyats", "editingPyatsValue"],
    ["mattermost", "mattermost", "editingMattermostValue"],
  ] as const)("is the mapped %s source in edit mode", (type, queryName, field) => {
    queries[queryName] = { data: { sources: [httpSource("one"), httpSource("two")] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog({ type, mode: "edit", sourceId: "two" }));
    expect(result.current[field]).toEqual(httpExpected("two"));
  });

  it("is the mapped Batfish source (host and port) in edit mode", () => {
    queries.batfish = { data: { sources: [{ source_id: "bf", host: "h", port: 9996 }] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog({ type: "batfish", mode: "edit", sourceId: "bf" }));
    expect(result.current.editingBatfishValue).toEqual({ sourceId: "bf", host: "h", port: 9996 });
  });

  it("is null in create mode, without an id, for an unknown id, or for another dialog", () => {
    queries.ise = { data: { sources: [httpSource("one")] }, isLoading: false };
    queries.batfish = { data: { sources: [{ source_id: "bf", host: "h", port: 1 }] }, isLoading: false };
    const { result } = renderHook(() => useSourcesSettings());

    act(() => result.current.setDialog({ type: "ise", mode: "create", sourceId: "one" }));
    expect(result.current.editingIseValue).toBeNull();

    act(() => result.current.setDialog({ type: "ise", mode: "edit" }));
    expect(result.current.editingIseValue).toBeNull();

    act(() => result.current.setDialog({ type: "ise", mode: "edit", sourceId: "gone" }));
    expect(result.current.editingIseValue).toBeNull();

    act(() => result.current.setDialog({ type: "batfish", mode: "edit", sourceId: "bf" }));
    expect(result.current.editingIseValue).toBeNull();
    expect(result.current.editingBatfishValue).not.toBeNull();
  });
});

describe("isDeletePending", () => {
  const del = (sourceType: "nautobot" | "ise" | "catalyst_center" | "pyats" | "mattermost" | "batfish") =>
    ({ type: "delete", sourceType, sourceId: "x", key: "sources.nautobot.x" }) as const;

  it.each([
    ["ise", "deleteIseSourceIsPending"],
    ["catalyst_center", "deleteCatalystCenterSourceIsPending"],
    ["pyats", "deletePyatsSourceIsPending"],
    ["mattermost", "deleteMattermostSourceIsPending"],
    ["batfish", "deleteBatfishSourceIsPending"],
    ["nautobot", "deleteSettingIsPending"],
  ] as const)("follows the delete mutation of a %s source", (sourceType, flag) => {
    (saveHandlers.value[flag] as boolean) = true;
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog(del(sourceType)));
    expect(result.current.isDeletePending).toBe(true);
    expect(result.current.deleteDialogOpen).toMatchObject({ sourceType });
  });

  it("ignores the delete flags of other source types", () => {
    saveHandlers.value.deleteBatfishSourceIsPending = true;
    const { result } = renderHook(() => useSourcesSettings());
    act(() => result.current.setDialog(del("ise")));
    expect(result.current.isDeletePending).toBe(false);
  });
});
