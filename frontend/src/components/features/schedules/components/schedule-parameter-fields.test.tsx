import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

import { ScheduleParameterFields } from "./schedule-parameter-fields";

const h = vi.hoisted(() => ({
  inventories: vi.fn(),
  credentials: vi.fn(),
  canReadCredentials: { value: true },
  inventoryData: { value: undefined as unknown },
  credentialData: { value: undefined as unknown },
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/hooks/queries/use-saved-inventories-query", () => ({
  useSavedInventoriesQuery: (options: unknown) => {
    h.inventories(options);
    return { data: h.inventoryData.value };
  },
}));
vi.mock("@/components/features/settings/credentials/hooks/use-credentials-query", () => ({
  useCredentialsQuery: (options: unknown) => {
    h.credentials(options);
    return { data: h.credentialData.value };
  },
}));
vi.mock("@/hooks/use-has-permission", () => ({
  useHasPermission: (resource: string, action: string) =>
    resource === "credentials" && action === "read" ? h.canReadCredentials.value : false,
}));

const attr = (over: Partial<StaticAttributeDef> & { name: string }): StaticAttributeDef => ({
  type: "string",
  required: false,
  ...over,
});

const INVENTORY_ATTR = attr({ name: "targets", type: "reference", ref_kind: "inventory" });
const CREDENTIAL_ATTR = attr({ name: "login", type: "reference", ref_kind: "credential" });

function setup(attributes: StaticAttributeDef[], values: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  render(<ScheduleParameterFields attributes={attributes} values={values} onChange={onChange} />);
  return onChange;
}

beforeEach(() => {
  h.inventories.mockReset();
  h.credentials.mockReset();
  h.canReadCredentials.value = true;
  h.inventoryData.value = [
    { id: 1, name: "core", scope: "global" },
    { id: 2, name: "lab", scope: "private" },
  ];
  h.credentialData.value = {
    credentials: [
      { id: 1, name: "ops-ssh", type: "ssh", visibility: "global" },
      { id: 2, name: "mine", type: "ssh", visibility: "private" },
      { id: 3, name: "api-token", type: "token", visibility: "global" },
    ],
  };
});

describe("ScheduleParameterFields", () => {
  it("says so when the workflow declares no parameters", () => {
    setup([]);
    expect(screen.getByText("This workflow declares no run parameters.")).toBeTruthy();
  });

  it("marks required parameters", () => {
    setup([attr({ name: "site", required: true }), attr({ name: "note" })]);
    expect(screen.getByText("site").textContent).toContain("*");
    expect(screen.getByText("note").textContent).not.toContain("*");
  });

  it("writes a text value into a copy of the values", () => {
    const values = { keep: 1 };
    const onChange = setup([attr({ name: "site" })], values);
    fireEvent.change(screen.getByLabelText("site"), { target: { value: "berlin" } });
    expect(onChange).toHaveBeenCalledWith({ keep: 1, site: "berlin" });
    expect(values).toEqual({ keep: 1 });
  });

  it("shows the current value of a parameter", () => {
    setup([attr({ name: "site" })], { site: "oslo" });
    expect((screen.getByLabelText("site") as HTMLInputElement).value).toBe("oslo");
  });

  it("toggles a boolean parameter", () => {
    const onChange = setup([attr({ name: "dry_run", type: "boolean" })], { dry_run: false });
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith({ dry_run: true });
  });

  describe("inventory reference", () => {
    it("lists the inventories and marks private ones", () => {
      setup([INVENTORY_ATTR]);
      const options = screen.getAllByRole("option").map((o) => o.textContent);
      expect(options).toEqual(expect.arrayContaining(["core", "lab (private)"]));
    });

    it("stores the chosen inventory as a number", () => {
      const onChange = setup([INVENTORY_ATTR], { other: "x" });
      fireEvent.change(screen.getByLabelText("targets"), { target: { value: "2" } });
      expect(onChange).toHaveBeenCalledWith({ other: "x", targets: 2 });
    });

    it("shows the stored inventory as selected", () => {
      setup([INVENTORY_ATTR], { targets: 1 });
      expect((screen.getByLabelText("targets") as HTMLSelectElement).value).toBe("1");
    });

    it("shows no selection when nothing is stored", () => {
      setup([INVENTORY_ATTR]);
      expect((screen.getByLabelText("targets") as HTMLSelectElement).value).toBe("");
    });

    it("copes with a list that has not loaded", () => {
      h.inventoryData.value = undefined;
      setup([INVENTORY_ATTR]);
      expect(screen.getByLabelText("targets")).toBeTruthy();
    });
  });

  describe("credential reference", () => {
    it("offers only SSH credentials and marks private ones", () => {
      setup([CREDENTIAL_ATTR]);
      const options = screen.getAllByRole("option").map((o) => o.textContent);
      expect(options).toEqual(expect.arrayContaining(["ops-ssh", "mine (private)"]));
      expect(options).not.toContain("api-token");
    });

    it("stores the credential by name", () => {
      const onChange = setup([CREDENTIAL_ATTR]);
      fireEvent.change(screen.getByLabelText("login"), { target: { value: "mine" } });
      expect(onChange).toHaveBeenCalledWith({ login: "mine" });
    });
  });

  describe("which lists are requested", () => {
    it("asks for neither list when no parameter needs one", () => {
      setup([attr({ name: "site" })]);
      expect(h.inventories).toHaveBeenLastCalledWith({ enabled: false });
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: false });
    });

    it("asks for the inventory list only when an inventory parameter exists", () => {
      setup([INVENTORY_ATTR]);
      expect(h.inventories).toHaveBeenLastCalledWith({ enabled: true });
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: false });
    });

    it("asks for the credential list when a credential parameter exists and the user may read it", () => {
      setup([CREDENTIAL_ATTR]);
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: true });
      expect(h.inventories).toHaveBeenLastCalledWith({ enabled: false });
    });

    it("does not request credentials a user without credentials:read could only get a 403 for", () => {
      h.canReadCredentials.value = false;
      setup([CREDENTIAL_ATTR]);
      expect(h.credentials).toHaveBeenLastCalledWith({ enabled: false });
    });
  });
});
